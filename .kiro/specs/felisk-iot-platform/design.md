# Design Document

## Overview

Felisk is a three-tier dual-mode agentic IoT system for feline access control and TNR operations. The tiers are:

1. **Edge Tier** — Raspberry Pi Pico W (MicroPython): sensors, actuators, mode-aware gate control, and HTTP command API.
2. **Vision Tier** — macOS laptop running YOLOv8 inference on webcam frames, signaling Temporal and commanding the Pico directly.
3. **Orchestration Tier** — Temporal.io durable workflow engine managing a dual-mode state machine with Saga compensation.
4. **Dashboard Tier** — Flask web app providing live telemetry, mode toggling, and volunteer controls.

Communication flows over Wi-Fi: the Pico W exposes an HTTP API on port 80, the Vision Node connects to both the Pico (direct commands) and Temporal (signals), and the Dashboard polls Temporal via query.

## Architecture

```
┌─────────────────────┐     ┌─────────────────────────┐     ┌───────────────────┐
│  Edge Tier          │     │  Orchestration Tier     │     │  Vision Tier      │
│  Pico W (felisk.py) │────▶│  Temporal Workflow      │◀────│  lpyolo.py        │
│                     │◀────│  (workflows.py)         │     │                   │
│  HC-SR04 (GP2/GP3)  │     │  Activities             │     │  YOLOv8 + Webcam  │
│  MFRC522 (SPI GP16) │     │  (activities.py)        │     │  Direct Pico cmds │
│  SG90 Servo (GP15)  │     │  Worker (worker.py)     │     │  Keyboard testing │
│  LEDs (GP13/GP14)   │     └─────────────────────────┘     └───────────────────┘
│  Buzzer (GP12)      │              │
│  HTTP API :80       │              ▼
└─────────────────────┘     ┌─────────────────────────┐
                            │  Dashboard Tier         │
                            │  app.py (Flask :5050)   │
                            │  Mode toggle + telemetry│
                            │  Volunteer controls     │
                            └─────────────────────────┘
```

## Components and Interfaces

### 1. Pico W Edge Controller (`felisk.py`)

**Hardware Pin Map:**

| Function | Pin | Protocol |
|----------|-----|----------|
| HC-SR04 Trigger | GP2 | Digital Out |
| HC-SR04 Echo | GP3 | Digital In (timed) |
| Servo Gate | GP15 | PWM (50Hz) |
| Buzzer | GP12 | Digital Out |
| MFRC522 SCK | GP18 | SPI0 CLK |
| MFRC522 MOSI | GP19 | SPI0 TX |
| MFRC522 MISO | GP16 | SPI0 RX |
| MFRC522 CS | GP17 | SPI0 CSn |
| MFRC522 RST | GP20 | Digital Out |
| Red LED | GP13 | Digital Out |
| Green LED | GP14 | Digital Out |

**HTTP Command API (Port 80):**

| Command | Effect |
|---------|--------|
| `MODE_DOMESTIC` | Set gate resting position to 0° (locked), red LED |
| `MODE_TNR` | Set gate resting position to 90° (open), green LED |
| `ACCESS_APPROVED` | Open gate temporarily (Domestic: 4s then relock; TNR: stay open) |
| `LOCK_CAPTURE` | Lock gate at 0° for capture |
| `SAFE_RELEASE` | Open gate to 90°, then return to mode's resting position |
| `GET /api/status` | Return JSON: status, mode, last_tag, distance |

**Core Loop:**
1. Poll HC-SR04 every 50ms for distance reading.
2. If object < 15cm → set `target_in_corridor = True`, chirp, start RFID scanning.
3. If RFID tag detected → validate against local authorized_felines list, report status.
4. Listen non-blocking on port 80 for HTTP commands from Temporal activities or vision node.
5. Execute actuator commands based on received HTTP requests.
6. When no object detected → reset corridor state.

**Mode-Aware Behavior:**
- `portal_mode` variable tracks current mode (DOMESTIC/TNR).
- `get_resting_angle()` returns 0° for DOMESTIC, 90° for TNR.
- All commands return gate to resting position after execution completes.

### 2. Vision Node (`lpyolo.py`)

**YOLOv8 Inference Pipeline:**
1. Load YOLOv8n model (COCO pretrained).
2. Open webcam, process every 3rd frame for performance.
3. Detect "cat" class → if found, signal `presence_event` to Temporal.
4. Check for "bird"/"mouse" (prey classes) → signal `prey_checked_event` with result.
5. Send direct HTTP command to Pico W for immediate hardware feedback.
6. 3-second cooldown between auto-detections to prevent signal spam.

**Temporal Integration:**
- Maintains a background asyncio event loop for non-blocking signal delivery.
- Caches Temporal client connection for performance.
- Signals: `presence_event`, `prey_checked_event`, `tag_scanned_event`.

**Signal Delivery:**
- `signal_temporal_workflow()` in the vision node blocks until signal is confirmed delivered (5s timeout).
- `simulate_detection()` sends `presence_event` → 500ms delay → `prey_checked_event`, blocking on each.

**Workflow Boot:**
- `app.py` terminates any existing workflow and starts fresh on every launch, ensuring code changes take effect immediately.

### 3. Temporal Orchestration Engine

**Workflow: `TnrPortalWorkflow` (`temporal_engine/workflows.py`)**

Single long-running workflow handling both modes. Uses signals for event ingestion and queries for state inspection.

**State Container:**
```python
@dataclass
class PortalState:
    mode: str = "DOMESTIC"        # DOMESTIC or TNR
    presence_active: bool = False
    tag_scanned: str = ""
    visual_status: str = ""       # clean, prey, intact_ear, ear_tipped
    human_decision: str = ""      # APPROVE_CAPTURE, SAFE_RELEASE
    workflow_phase: str = "IDLE"  # IDLE, MONITORING, LOCKED, RELEASED
    encounter_count: int = 0
    last_event: str = ""          # Human-readable last action
```

**Signals:**
| Signal | Source | Purpose |
|--------|--------|---------|
| `presence_event(bool)` | Vision node / Pico | Wake workflow from MONITORING |
| `tag_scanned_event(str)` | Pico RFID | Report scanned tag UID |
| `prey_checked_event(str)` | Vision node | Report classification result |
| `volunteer_decision(str)` | Dashboard | TNR volunteer action |
| `set_mode(str)` | Dashboard | Toggle DOMESTIC/TNR + command Pico |

**Query:**
| Query | Returns |
|-------|---------|
| `get_workflow_state` | Full state dict for dashboard polling |

**Encounter Loop:**
1. Set phase to MONITORING, clear per-encounter state (tag, vision, decision).
2. If `presence_active` is already true (signal arrived during previous hold), skip wait.
3. Otherwise, wait for `presence_event` or `human_decision` signal.
4. Route to domestic or TNR handler based on current mode.
5. Hold result state for 3 seconds (dashboard visibility).
6. Increment encounter count, clear `presence_active`, loop.

**Domestic Handler:**
1. Wait up to 5s for RFID tag OR vision classification.
2. If no authorized RFID → LOCKED (reject).
3. If authorized RFID → wait up to 3s for vision.
4. If vision says "prey" → LOCKED (block entry).
5. Otherwise (clean or no vision) → RELEASED (open gate). RFID alone is sufficient for resident cats.

**TNR Handler:**
1. Wait up to 10s for RFID or vision classification.
2. Known RFID tag → RELEASED (log visit, gate stays open).
3. Vision "ear_tipped" or "clean" → RELEASED (pass freely).
4. Vision "intact_ear" or "prey" → LOCKED (capture).
5. If locked: wait for volunteer decision (4h timeout → Saga rollback auto-release).

**Activities (`temporal_engine/activities.py`):**
| Activity | Command Sent | Purpose |
|----------|-------------|---------|
| `pico_unlock_gate` | `ACCESS_APPROVED` | Open gate for authorized/clean cat |
| `pico_lock_gate` | `LOCK_CAPTURE` | Lock gate for TNR capture |
| `pico_safe_release` | `SAFE_RELEASE` | Saga compensation — release animal |
| `pico_set_mode` | `MODE_DOMESTIC` / `MODE_TNR` | Switch Pico resting gate position |

All activities use HTTP GET to `PICO_IP:80` with 6-second timeout and 2-attempt retry policy.

**Saga Compensation Pattern:**
- If capture activity fails → workflow enters RELEASED state (animal safety invariant).
- If volunteer timeout (4 hours) → `pico_safe_release` executes automatically.
- If worker crashes → Temporal replays deterministically on restart.

**Continue-As-New:** After 50 encounters, workflow refreshes to prevent unbounded history.

### 4. Dashboard (`app.py`)

**Flask Application (Port 5050):**

| Route | Method | Purpose |
|-------|--------|---------|
| `/` | GET | Serve dashboard HTML |
| `/api/state` | GET | Query Temporal workflow state |
| `/api/mode` | POST | Send `set_mode` signal to workflow |
| `/api/signal` | POST | Send `volunteer_decision` signal |
| `/api/start` | POST | Start workflow (used at boot) |

**Dashboard Features:**
- Mode toggle (Domestic / TNR) with description.
- Phase banner (MONITORING / LOCKED / RELEASED / DISCONNECTED).
- Four sensor cards: Proximity, RFID, Vision AI, Servo Gate.
- Detection pipeline visualization (4-step: Detect → Identify → Classify → Actuate).
- Volunteer action buttons (only visible in TNR mode when LOCKED).
- Last event description in human-readable text.
- 800ms polling interval.
- Auto-terminates stale workflow and starts fresh on boot.

## Data Flow — Complete Encounter Cycle

### Domestic Mode (Happy Path):
1. Cat approaches → HC-SR04 detects < 15cm → Pico chirps
2. Cat's collar RFID tag scanned → Pico reports tag locally
3. Vision node detects cat on webcam → signals `presence_event(True)` to Temporal
4. Workflow wakes from MONITORING → waits for RFID signal (5s)
5. Vision classifies "clean" → signals `prey_checked_event("clean")`
6. Workflow: authorized tag + clean = RELEASED → executes `pico_unlock_gate` activity
7. Pico receives `ACCESS_APPROVED` → servo to 90°, green LED, chirp → 4s → relock to 0°
8. Workflow holds RELEASED state 3s for dashboard visibility → resets to MONITORING

### TNR Mode (Capture Path):
1. Cat enters open shelter → HC-SR04 detects presence
2. Vision node detects cat → signals `presence_event(True)`
3. Workflow wakes → waits for RFID or vision (10s)
4. Vision classifies "intact_ear" → signals `prey_checked_event("intact_ear")`
5. Workflow: intact stray = LOCKED → executes `pico_lock_gate` activity
6. Pico receives `LOCK_CAPTURE` → servo to 0°, red LED, warning chirp
7. Dashboard shows LOCKED + volunteer buttons appear
8. Volunteer clicks "Release Cat Safely" → `volunteer_decision("SAFE_RELEASE")` signal
9. Workflow executes `pico_safe_release` → Pico opens gate → RELEASED
10. OR: 4h timeout → Saga auto-executes `pico_safe_release` → RELEASED

## Error Handling

| Scenario | Handler | Recovery |
|----------|---------|----------|
| Pico W unreachable | Activity raises ApplicationError (non-retryable) | Workflow enters RELEASED state |
| Temporal worker crash | Temporal preserves history | Worker restart replays and resumes |
| Network timeout on activity | Retry policy: 2 attempts, 1s backoff | After failure, safe state |
| Vision node offline | Workflow times out waiting for vision (10s) | Defaults to lock (Domestic) or pass (TNR) |
| Volunteer timeout (4h) | Saga timer in workflow | Auto-release via compensating activity |
| Dashboard disconnected | Query fails gracefully | Shows DISCONNECTED state |

## Testing Strategy

### Automated Test Suite (`python -m pytest tests/ -v`)

**Activity Unit Tests (`tests/test_activities.py`):**
- Verify HTTP command formatting to Pico W.
- Verify non-retryable ApplicationError on socket failure/timeout.
- Verify PicoCommand dataclass behavior.

**Workflow Integration Tests (`tests/test_workflows.py`):**
Using Temporal's time-skipping test environment:
- Workflow starts in DOMESTIC/MONITORING mode.
- Domestic: authorized tag + clean vision → RELEASED → resets.
- Domestic: authorized tag + prey → LOCKED.
- Domestic: unknown tag → LOCKED (rejected).
- TNR: ear-tipped cat → RELEASED (passes freely).
- TNR: intact stray → LOCKED.
- TNR: locked + volunteer SAFE_RELEASE → RELEASED.
- Mode switch signal updates state and triggers Pico command.
- Query returns full state with all fields.

### Adversarial Integration Testing (Manual/Demo)
- Keyboard triggers in vision node inject signals through the full pipeline.
- Exercises identical code path as real YOLOv8 detections end-to-end.
- Dashboard updates in real time during test execution.

### Hardware-in-the-Loop (Manual)
- Physical RFID tag scan → workflow receives tag_scanned_event.
- Proximity detection → vision node activation.
- Servo actuation on each command type.
- Mode switch physically moves servo between 0° and 90°.
