"""
Felisk — Dual-Mode Dashboard (app.py)
Real-time Flask dashboard with mode toggle (Domestic / TNR).
Polls Temporal workflow state and provides mode switching + volunteer controls.
"""

import asyncio
from threading import Thread
from typing import Optional

from flask import Flask, jsonify, render_template_string, request
from temporalio.client import Client

# ─── Configuration ───────────────────────────────────────────────────────────
TEMPORAL_ADDRESS = "localhost:7233"
TASK_QUEUE = "felisk-task-queue"
WORKFLOW_ID = "felisk-tnr-portal"

app = Flask(__name__)

_loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()


def _start_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


_thread = Thread(target=_start_loop, args=(_loop,), daemon=True)
_thread.start()


def _run_async(coro):
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    return future.result(timeout=5.0)


# ─── Temporal Helpers ────────────────────────────────────────────────────────
_client: Optional[Client] = None


async def _get_client() -> Client:
    global _client
    if _client is None:
        _client = await Client.connect(TEMPORAL_ADDRESS)
    return _client


async def _query_state() -> dict:
    client = await _get_client()
    handle = client.get_workflow_handle(WORKFLOW_ID)
    try:
        return await handle.query("get_workflow_state")
    except Exception as e:
        return {"error": str(e), "workflow_phase": "DISCONNECTED"}


async def _send_signal(signal_name: str, payload: str) -> None:
    client = await _get_client()
    handle = client.get_workflow_handle(WORKFLOW_ID)
    await handle.signal(signal_name, payload)


async def _start_workflow() -> str:
    client = await _get_client()
    from temporal_engine.workflows import TnrPortalWorkflow

    handle = await client.start_workflow(
        TnrPortalWorkflow.run,
        id=WORKFLOW_ID,
        task_queue=TASK_QUEUE,
    )
    return handle.id


async def _restart_workflow() -> str:
    """Terminate any existing workflow and start fresh."""
    client = await _get_client()
    try:
        handle = client.get_workflow_handle(WORKFLOW_ID)
        await handle.terminate("Restarting with updated code")
    except Exception:
        pass
    import asyncio
    await asyncio.sleep(0.5)
    from temporal_engine.workflows import TnrPortalWorkflow
    handle = await client.start_workflow(
        TnrPortalWorkflow.run,
        id=WORKFLOW_ID,
        task_queue=TASK_QUEUE,
    )
    return handle.id



# ─── Dashboard HTML ──────────────────────────────────────────────────────────
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Felisk — Smart Cat Portal</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Inter', sans-serif;
            background: #0f0f0f;
            color: #f5f5f5;
            min-height: 100vh;
            padding: 2rem 1.5rem;
        }
        .container { max-width: 840px; margin: 0 auto; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 2rem; }
        h1 { font-size: 1.75rem; font-weight: 700; letter-spacing: -0.03em; }
        h1 span { color: #a78bfa; }

        /* Mode Toggle */
        .mode-toggle {
            display: flex;
            background: #1a1a1a;
            border: 1px solid #2a2a2a;
            border-radius: 10px;
            overflow: hidden;
        }
        .mode-btn {
            padding: 0.6rem 1.2rem;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            border: none;
            cursor: pointer;
            transition: all 0.2s ease;
            background: transparent;
            color: #6b7280;
        }
        .mode-btn.active-domestic { background: #1e3a5f; color: #60a5fa; }
        .mode-btn.active-tnr { background: #5f3a1e; color: #fb923c; }
        .mode-btn:hover { color: #f5f5f5; }

        /* Mode Description */
        .mode-desc {
            font-size: 0.8rem;
            color: #6b7280;
            margin-bottom: 2rem;
            padding: 0.75rem 1rem;
            background: #1a1a1a;
            border-radius: 8px;
            border-left: 3px solid #2a2a2a;
        }
        .mode-desc.domestic { border-left-color: #60a5fa; }
        .mode-desc.tnr { border-left-color: #fb923c; }

        /* Phase Banner */
        .phase-banner {
            text-align: center;
            padding: 1.25rem 2rem;
            border-radius: 14px;
            margin-bottom: 1.5rem;
            transition: all 0.4s ease;
        }
        .phase-banner .phase-label {
            font-size: 0.65rem;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            opacity: 0.7;
            margin-bottom: 0.4rem;
        }
        .phase-banner .phase-value {
            font-size: 2.25rem;
            font-weight: 800;
            letter-spacing: -0.02em;
        }
        .phase-MONITORING { background: linear-gradient(135deg, #1e3a5f, #1a2332); }
        .phase-MONITORING .phase-value { color: #60a5fa; }
        .phase-LOCKED { background: linear-gradient(135deg, #5f1e1e, #321a1a); }
        .phase-LOCKED .phase-value { color: #f87171; }
        .phase-RELEASED { background: linear-gradient(135deg, #1e5f2e, #1a3221); }
        .phase-RELEASED .phase-value { color: #4ade80; }
        .phase-IDLE { background: linear-gradient(135deg, #2d2d2d, #1a1a1a); }
        .phase-IDLE .phase-value { color: #9ca3af; }
        .phase-DISCONNECTED { background: linear-gradient(135deg, #3d1f1f, #1a1111); }
        .phase-DISCONNECTED .phase-value { color: #ef4444; }

        /* Event Log */
        .last-event {
            text-align: center;
            font-size: 0.8rem;
            color: #a78bfa;
            margin-bottom: 1.5rem;
            min-height: 1.2em;
            font-weight: 500;
        }

        /* Grid */
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; margin-bottom: 1.5rem; }
        .card {
            background: #1a1a1a;
            border: 1px solid #2a2a2a;
            border-radius: 10px;
            padding: 1.25rem;
            transition: border-color 0.3s ease;
        }
        .card.active { border-color: #a78bfa; }
        .card-label {
            font-size: 0.65rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: #6b7280;
            margin-bottom: 0.5rem;
        }
        .card-value {
            font-size: 1.1rem;
            font-weight: 600;
            font-family: 'SF Mono', 'Fira Code', monospace;
        }
        .card-value.detected { color: #4ade80; }
        .card-value.danger { color: #f87171; }
        .card-value.neutral { color: #6b7280; }
        .card-value.info { color: #60a5fa; }

        /* Pipeline */
        .timeline {
            background: #1a1a1a;
            border: 1px solid #2a2a2a;
            border-radius: 10px;
            padding: 1.25rem;
            margin-bottom: 1.5rem;
        }
        .timeline-title {
            font-size: 0.65rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: #6b7280;
            margin-bottom: 0.75rem;
        }
        .pipeline { display: flex; align-items: center; gap: 0.4rem; }
        .pipe-step {
            flex: 1;
            text-align: center;
            padding: 0.5rem 0.4rem;
            border-radius: 6px;
            font-size: 0.65rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            background: #2a2a2a;
            color: #6b7280;
            transition: all 0.3s ease;
        }
        .pipe-step.done { background: #065f46; color: #4ade80; }
        .pipe-step.active { background: #1e3a5f; color: #60a5fa; animation: glow 1.5s infinite; }
        .pipe-step.alert { background: #5f1e1e; color: #f87171; }
        .pipe-arrow { color: #4b5563; font-size: 0.75rem; }
        @keyframes glow { 0%, 100% { opacity: 1; } 50% { opacity: 0.6; } }

        /* TNR Actions (only visible in TNR mode when locked) */
        .tnr-actions {
            display: none;
            gap: 0.75rem;
            margin-bottom: 1.5rem;
        }
        .tnr-actions.visible { display: flex; }
        .tnr-btn {
            flex: 1;
            padding: 0.7rem 1rem;
            border: none;
            border-radius: 8px;
            font-size: 0.8rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.15s ease;
        }
        .tnr-btn:active { transform: scale(0.97); }
        .btn-release { background: #065f46; color: #4ade80; }
        .btn-release:hover { background: #047857; }
        .btn-capture { background: #5f1e1e; color: #f87171; }
        .btn-capture:hover { background: #7f1d1d; }

        .footer {
            text-align: center;
            font-size: 0.7rem;
            color: #4b5563;
            margin-top: 1rem;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Felisk <span>Live</span></h1>
            <div class="mode-toggle">
                <button class="mode-btn active-domestic" id="btnDomestic" onclick="switchMode('DOMESTIC')">
                    🏠 Domestic
                </button>
                <button class="mode-btn" id="btnTnr" onclick="switchMode('TNR')">
                    🐾 TNR
                </button>
            </div>
        </div>

        <div class="mode-desc domestic" id="modeDesc">
            Gate normally locked. Opens only for your registered cat with no prey in mouth.
            Blocks foreign cats and stray animals from entering your home.
        </div>

        <div class="phase-banner phase-IDLE" id="phaseBanner">
            <div class="phase-label">Portal Status</div>
            <div class="phase-value" id="phaseValue">IDLE</div>
        </div>

        <div class="last-event" id="lastEvent"></div>

        <div class="grid">
            <div class="card" id="presenceCard">
                <div class="card-label">Proximity (HC-SR04)</div>
                <div class="card-value neutral" id="presenceValue">No Motion</div>
            </div>
            <div class="card" id="rfidCard">
                <div class="card-label">RFID (MFRC522)</div>
                <div class="card-value neutral" id="rfidValue">—</div>
            </div>
            <div class="card" id="visionCard">
                <div class="card-label">Vision AI (YOLOv8)</div>
                <div class="card-value neutral" id="visionValue">Standby</div>
            </div>
            <div class="card" id="actionCard">
                <div class="card-label">Servo Gate (SG90)</div>
                <div class="card-value neutral" id="actionValue">—</div>
            </div>
        </div>

        <div class="timeline">
            <div class="timeline-title">Detection Pipeline</div>
            <div class="pipeline">
                <div class="pipe-step" id="step1">Detect</div>
                <div class="pipe-arrow">→</div>
                <div class="pipe-step" id="step2">Identify</div>
                <div class="pipe-arrow">→</div>
                <div class="pipe-step" id="step3">Classify</div>
                <div class="pipe-arrow">→</div>
                <div class="pipe-step" id="step4">Actuate</div>
            </div>
        </div>

        <div class="tnr-actions" id="tnrActions">
            <button class="tnr-btn btn-release" onclick="volunteerDecision('SAFE_RELEASE')">
                Release Cat Safely
            </button>
            <button class="tnr-btn btn-capture" onclick="volunteerDecision('APPROVE_CAPTURE')">
                Confirm TNR Pickup
            </button>
        </div>

        <div class="footer" id="footer"></div>
    </div>

    <script>
        let currentMode = 'DOMESTIC';

        async function switchMode(mode) {
            try {
                await fetch('/api/mode', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({mode: mode})
                });
                currentMode = mode;
                updateModeUI();
            } catch (e) { console.error(e); }
        }

        function updateModeUI() {
            const btnD = document.getElementById('btnDomestic');
            const btnT = document.getElementById('btnTnr');
            const desc = document.getElementById('modeDesc');

            btnD.className = 'mode-btn' + (currentMode === 'DOMESTIC' ? ' active-domestic' : '');
            btnT.className = 'mode-btn' + (currentMode === 'TNR' ? ' active-tnr' : '');

            if (currentMode === 'DOMESTIC') {
                desc.className = 'mode-desc domestic';
                desc.textContent = 'Gate normally locked. Opens only for your registered cat with no prey in mouth. Blocks foreign cats and dead animals from entering your home.';
            } else {
                desc.className = 'mode-desc tnr';
                desc.textContent = 'Gate normally open for community shelter. Locks only when an un-neutered stray enters for humane TNR capture. Ear-tipped cats pass freely.';
            }
        }

        async function volunteerDecision(decision) {
            try {
                await fetch('/api/signal', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({decision: decision})
                });
            } catch (e) { console.error(e); }
        }

        async function poll() {
            try {
                const res = await fetch('/api/state');
                const d = await res.json();
                const phase = d.workflow_phase || 'DISCONNECTED';

                // Sync mode from workflow
                if (d.mode && d.mode !== currentMode) {
                    currentMode = d.mode;
                    updateModeUI();
                }

                // Phase banner
                document.getElementById('phaseBanner').className = 'phase-banner phase-' + phase;
                document.getElementById('phaseValue').textContent = phase;

                // Last event
                document.getElementById('lastEvent').textContent = d.last_event || '';

                // Presence
                const presVal = document.getElementById('presenceValue');
                const presCard = document.getElementById('presenceCard');
                if (d.presence_active) {
                    presVal.textContent = 'Motion Detected';
                    presVal.className = 'card-value detected';
                    presCard.classList.add('active');
                } else {
                    presVal.textContent = 'No Motion';
                    presVal.className = 'card-value neutral';
                    presCard.classList.remove('active');
                }

                // RFID
                const rfidVal = document.getElementById('rfidValue');
                const rfidCard = document.getElementById('rfidCard');
                if (d.tag_scanned) {
                    const isAuth = ['A1B2C3D4','DEADBEEF','CAFEBABE','146_73_250_5'].includes(d.tag_scanned);
                    rfidVal.textContent = isAuth ? '✓ ' + d.tag_scanned : '✗ ' + d.tag_scanned;
                    rfidVal.className = isAuth ? 'card-value detected' : 'card-value danger';
                    rfidCard.classList.add('active');
                } else {
                    rfidVal.textContent = '—';
                    rfidVal.className = 'card-value neutral';
                    rfidCard.classList.remove('active');
                }

                // Vision
                const visVal = document.getElementById('visionValue');
                const visCard = document.getElementById('visionCard');
                const vs = d.visual_status;
                if (vs === 'clean') {
                    visVal.textContent = '✓ No Prey';
                    visVal.className = 'card-value detected';
                    visCard.classList.add('active');
                } else if (vs === 'ear_tipped') {
                    visVal.textContent = '✓ Ear-Tipped';
                    visVal.className = 'card-value detected';
                    visCard.classList.add('active');
                } else if (vs === 'prey') {
                    visVal.textContent = '⚠ Prey Detected';
                    visVal.className = 'card-value danger';
                    visCard.classList.add('active');
                } else if (vs === 'intact_ear') {
                    visVal.textContent = '⚠ Intact Stray';
                    visVal.className = 'card-value danger';
                    visCard.classList.add('active');
                } else {
                    visVal.textContent = 'Standby';
                    visVal.className = 'card-value neutral';
                    visCard.classList.remove('active');
                }

                // Gate action
                const actVal = document.getElementById('actionValue');
                const actCard = document.getElementById('actionCard');
                if (phase === 'RELEASED') {
                    actVal.textContent = '🔓 Open (90°)';
                    actVal.className = 'card-value detected';
                    actCard.classList.add('active');
                } else if (phase === 'LOCKED') {
                    actVal.textContent = '🔒 Locked (0°)';
                    actVal.className = 'card-value danger';
                    actCard.classList.add('active');
                } else if (phase === 'MONITORING') {
                    actVal.textContent = currentMode === 'DOMESTIC' ? '🔒 Locked (0°)' : '🔓 Open (90°)';
                    actVal.className = 'card-value neutral';
                    actCard.classList.remove('active');
                } else {
                    actVal.textContent = '—';
                    actVal.className = 'card-value neutral';
                    actCard.classList.remove('active');
                }

                // Pipeline
                const steps = ['step1','step2','step3','step4'].map(id => document.getElementById(id));
                steps.forEach(s => s.className = 'pipe-step');

                if (phase === 'MONITORING' && !d.presence_active) {
                    steps[0].classList.add('active');
                } else if (d.presence_active && !d.tag_scanned && !vs) {
                    steps[0].classList.add('done');
                    steps[1].classList.add('active');
                } else if (d.presence_active && (d.tag_scanned || vs)) {
                    steps[0].classList.add('done');
                    steps[1].classList.add('done');
                    steps[2].classList.add(vs ? 'done' : 'active');
                    if (phase === 'RELEASED') steps[3].classList.add('done');
                    else if (phase === 'LOCKED') steps[3].classList.add('alert');
                    else if (vs) steps[3].classList.add('active');
                }

                // Show TNR volunteer actions only when locked in TNR mode
                const tnrEl = document.getElementById('tnrActions');
                tnrEl.className = (currentMode === 'TNR' && phase === 'LOCKED')
                    ? 'tnr-actions visible' : 'tnr-actions';

                // Footer
                document.getElementById('footer').textContent =
                    `${d.encounter_count || 0} encounters processed · ${currentMode} mode · Temporal workflow active`;

            } catch (e) {
                document.getElementById('phaseBanner').className = 'phase-banner phase-DISCONNECTED';
                document.getElementById('phaseValue').textContent = 'DISCONNECTED';
            }
        }

        setInterval(poll, 800);
        poll();
    </script>
</body>
</html>
"""


# ─── Routes ──────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)


@app.route("/api/state")
def api_state():
    try:
        state = _run_async(_query_state())
        return jsonify(state)
    except Exception as e:
        return jsonify({"error": str(e), "workflow_phase": "DISCONNECTED"})


@app.route("/api/mode", methods=["POST"])
def api_mode():
    """Switch between DOMESTIC and TNR mode."""
    data = request.get_json()
    mode = data.get("mode", "")
    if mode not in ("DOMESTIC", "TNR"):
        return jsonify({"error": "Invalid mode"}), 400
    try:
        _run_async(_send_signal("set_mode", mode))
        return jsonify({"status": f"Mode switched to {mode}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/signal", methods=["POST"])
def api_signal():
    """Send volunteer decision (TNR mode)."""
    data = request.get_json()
    decision = data.get("decision", "")
    if decision not in ("APPROVE_CAPTURE", "SAFE_RELEASE"):
        return jsonify({"error": "Invalid decision"}), 400
    try:
        _run_async(_send_signal("volunteer_decision", decision))
        return jsonify({"status": f"Decision sent: {decision}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/start", methods=["POST"])
def api_start():
    try:
        wf_id = _run_async(_start_workflow())
        return jsonify({"status": f"Workflow started: {wf_id}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    # Always restart workflow fresh so code changes take effect
    try:
        _run_async(_restart_workflow())
        print("[FELISK] Workflow restarted fresh.")
    except Exception as e:
        print(f"[FELISK] Workflow start issue: {e}")

    print("[FELISK] Dashboard live at http://localhost:5050")
    app.run(host="0.0.0.0", port=5050, debug=False)
