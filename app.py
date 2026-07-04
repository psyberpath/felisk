"""
Felisk — Live Monitoring Dashboard (app.py)
Real-time Flask dashboard that displays the state of the TNR Portal workflow.
Polls Temporal workflow state and visualizes the autonomous detection pipeline.
"""

import asyncio
from threading import Thread
from typing import Optional

from flask import Flask, jsonify, render_template_string
from temporalio.client import Client

# ─── Configuration ───────────────────────────────────────────────────────────
TEMPORAL_ADDRESS = "localhost:7233"
TASK_QUEUE = "felisk-task-queue"
WORKFLOW_ID = "felisk-tnr-portal"

app = Flask(__name__)

# Background event loop for async Temporal calls
_loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()


def _start_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


_thread = Thread(target=_start_loop, args=(_loop,), daemon=True)
_thread.start()


def _run_async(coro):
    """Run an async coroutine from synchronous Flask context."""
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
        state = await handle.query("get_workflow_state")
        return state
    except Exception as e:
        return {"error": str(e), "workflow_phase": "DISCONNECTED"}


async def _start_workflow() -> str:
    client = await _get_client()
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
    <title>Felisk — TNR Live Monitor</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Inter', sans-serif;
            background: #0f0f0f;
            color: #f5f5f5;
            min-height: 100vh;
            padding: 2.5rem 2rem;
        }
        .container { max-width: 800px; margin: 0 auto; }
        h1 {
            font-size: 2rem;
            font-weight: 700;
            letter-spacing: -0.03em;
            margin-bottom: 0.25rem;
        }
        h1 span { color: #a78bfa; }
        .subtitle {
            font-size: 0.85rem;
            color: #6b7280;
            margin-bottom: 2.5rem;
        }
        .phase-banner {
            text-align: center;
            padding: 1.5rem 2rem;
            border-radius: 16px;
            margin-bottom: 2rem;
            transition: all 0.4s ease;
        }
        .phase-banner .phase-label {
            font-size: 0.7rem;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            opacity: 0.7;
            margin-bottom: 0.5rem;
        }
        .phase-banner .phase-value {
            font-size: 2.5rem;
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

        .grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1rem;
            margin-bottom: 2rem;
        }
        .card {
            background: #1a1a1a;
            border: 1px solid #2a2a2a;
            border-radius: 12px;
            padding: 1.5rem;
            transition: border-color 0.3s ease;
        }
        .card.active { border-color: #a78bfa; }
        .card-label {
            font-size: 0.7rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: #6b7280;
            margin-bottom: 0.75rem;
        }
        .card-value {
            font-size: 1.25rem;
            font-weight: 600;
            font-family: 'SF Mono', 'Fira Code', monospace;
        }
        .card-value.detected { color: #4ade80; }
        .card-value.danger { color: #f87171; }
        .card-value.neutral { color: #6b7280; }
        .card-value.info { color: #60a5fa; }

        .timeline {
            background: #1a1a1a;
            border: 1px solid #2a2a2a;
            border-radius: 12px;
            padding: 1.5rem;
        }
        .timeline-title {
            font-size: 0.7rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: #6b7280;
            margin-bottom: 1rem;
        }
        .pipeline {
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        .pipe-step {
            flex: 1;
            text-align: center;
            padding: 0.6rem 0.5rem;
            border-radius: 8px;
            font-size: 0.7rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            background: #2a2a2a;
            color: #6b7280;
            transition: all 0.3s ease;
        }
        .pipe-step.done { background: #065f46; color: #4ade80; }
        .pipe-step.active { background: #1e3a5f; color: #60a5fa; animation: glow 1.5s infinite; }
        .pipe-step.alert { background: #5f1e1e; color: #f87171; }
        .pipe-arrow { color: #4b5563; font-size: 0.8rem; }

        @keyframes glow {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.7; }
        }

        .encounters {
            margin-top: 1.5rem;
            text-align: center;
            font-size: 0.75rem;
            color: #4b5563;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Felisk <span>Live</span></h1>
        <p class="subtitle">Autonomous TNR Portal — Real-time Workflow Monitor</p>

        <div class="phase-banner phase-IDLE" id="phaseBanner">
            <div class="phase-label">Current Phase</div>
            <div class="phase-value" id="phaseValue">IDLE</div>
        </div>

        <div class="grid">
            <div class="card" id="presenceCard">
                <div class="card-label">Proximity Sensor</div>
                <div class="card-value neutral" id="presenceValue">No Motion</div>
            </div>
            <div class="card" id="rfidCard">
                <div class="card-label">RFID Tag</div>
                <div class="card-value neutral" id="rfidValue">—</div>
            </div>
            <div class="card" id="visionCard">
                <div class="card-label">Vision AI</div>
                <div class="card-value neutral" id="visionValue">Standby</div>
            </div>
            <div class="card" id="actionCard">
                <div class="card-label">Gate Action</div>
                <div class="card-value neutral" id="actionValue">Secure</div>
            </div>
        </div>

        <div class="timeline">
            <div class="timeline-title">Detection Pipeline</div>
            <div class="pipeline">
                <div class="pipe-step" id="step1">Detect</div>
                <div class="pipe-arrow">→</div>
                <div class="pipe-step" id="step2">Scan</div>
                <div class="pipe-arrow">→</div>
                <div class="pipe-step" id="step3">Classify</div>
                <div class="pipe-arrow">→</div>
                <div class="pipe-step" id="step4">Actuate</div>
            </div>
        </div>

        <div class="encounters" id="encounters"></div>
    </div>

    <script>
        async function poll() {
            try {
                const res = await fetch('/api/state');
                const d = await res.json();
                const phase = d.workflow_phase || 'DISCONNECTED';

                // Phase banner
                const banner = document.getElementById('phaseBanner');
                banner.className = 'phase-banner phase-' + phase;
                document.getElementById('phaseValue').textContent = phase;

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
                    rfidVal.textContent = d.tag_scanned;
                    rfidVal.className = 'card-value info';
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
                if (vs === 'clean' || vs === 'ear_tipped') {
                    visVal.textContent = vs === 'clean' ? '✓ Clean' : '✓ Ear-Tipped';
                    visVal.className = 'card-value detected';
                    visCard.classList.add('active');
                } else if (vs === 'prey' || vs === 'intact_ear') {
                    visVal.textContent = vs === 'prey' ? '⚠ Prey Detected' : '⚠ Intact Stray';
                    visVal.className = 'card-value danger';
                    visCard.classList.add('active');
                } else {
                    visVal.textContent = 'Standby';
                    visVal.className = 'card-value neutral';
                    visCard.classList.remove('active');
                }

                // Action
                const actVal = document.getElementById('actionValue');
                const actCard = document.getElementById('actionCard');
                if (phase === 'RELEASED') {
                    actVal.textContent = '🔓 Gate Open';
                    actVal.className = 'card-value detected';
                    actCard.classList.add('active');
                } else if (phase === 'LOCKED') {
                    actVal.textContent = '🔒 Gate Locked';
                    actVal.className = 'card-value danger';
                    actCard.classList.add('active');
                } else {
                    actVal.textContent = 'Secure';
                    actVal.className = 'card-value neutral';
                    actCard.classList.remove('active');
                }

                // Pipeline steps
                const s1 = document.getElementById('step1');
                const s2 = document.getElementById('step2');
                const s3 = document.getElementById('step3');
                const s4 = document.getElementById('step4');
                [s1,s2,s3,s4].forEach(s => s.className = 'pipe-step');

                if (phase === 'MONITORING' && !d.presence_active) {
                    s1.classList.add('active');
                } else if (d.presence_active && !d.tag_scanned && !vs) {
                    s1.classList.add('done');
                    s2.classList.add('active');
                } else if (d.presence_active && (d.tag_scanned || vs)) {
                    s1.classList.add('done');
                    s2.classList.add('done');
                    s3.classList.add(vs ? 'done' : 'active');
                    if (phase === 'RELEASED') s4.classList.add('done');
                    else if (phase === 'LOCKED') s4.classList.add('alert');
                    else if (vs) s4.classList.add('active');
                }

                // Encounters
                if (d.encounter_count !== undefined) {
                    document.getElementById('encounters').textContent =
                        `${d.encounter_count} encounter${d.encounter_count !== 1 ? 's' : ''} processed this session`;
                }
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


@app.route("/api/start", methods=["POST"])
def api_start():
    """Start the workflow if not already running (used by worker bootstrap)."""
    try:
        wf_id = _run_async(_start_workflow())
        return jsonify({"status": f"Workflow started: {wf_id}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    # Auto-start the workflow on dashboard boot
    try:
        _run_async(_start_workflow())
        print("[FELISK] Workflow started automatically.")
    except Exception as e:
        print(f"[FELISK] Workflow may already be running: {e}")

    print("[FELISK] Dashboard live at http://localhost:5050")
    app.run(host="0.0.0.0", port=5050, debug=False)
