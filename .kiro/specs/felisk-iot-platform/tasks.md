# Implementation Plan

## Completed Tasks

- [x] 1. Pico W Edge Controller (`felisk.py`)
  - [x] 1.1 HC-SR04 ultrasonic sensor driver (GP2/GP3, 50ms polling, <15cm threshold)
  - [x] 1.2 MFRC522 RFID reader via SPI (GP16–GP20, authorized_felines registry)
  - [x] 1.3 SG90 servo gate control (GP15 PWM, 0°–90° range)
  - [x] 1.4 Active buzzer and LED indicators (GP12, GP13, GP14)
  - [x] 1.5 Wi-Fi connection and HTTP command API on port 80
  - [x] 1.6 Dual-mode support (MODE_DOMESTIC / MODE_TNR commands)
  - [x] 1.7 Mode-aware gate resting position (0° Domestic, 90° TNR)
  - [x] 1.8 Non-blocking main loop integrating sensors + HTTP listener
  - _Requirements: 1, 2, 3_

- [x] 2. Vision Node (`lpyolo.py`)
  - [x] 2.1 YOLOv8n inference pipeline (webcam, cat/bird/mouse detection)
  - [x] 2.2 Temporal signal integration (presence_event, prey_checked_event)
  - [x] 2.3 Direct Pico W HTTP commands for immediate actuation
  - [x] 2.4 Adversarial integration testing suite (keyboard: i, t, p, c)
  - [x] 2.5 Cooldown logic (3s between auto-detections)
  - [x] 2.6 Demo-only fallback mode (OpenCV window without webcam)
  - _Requirements: 7_

- [x] 3. Temporal Orchestration Engine
  - [x] 3.1 TnrPortalWorkflow — dual-mode state machine (`temporal_engine/workflows.py`)
  - [x] 3.2 Domestic mode handler (RFID + vision verification)
  - [x] 3.3 TNR mode handler (selective capture, ear-tip pass-through)
  - [x] 3.4 Saga rollback on 4-hour volunteer timeout
  - [x] 3.5 Mode switch signal with pico_set_mode activity
  - [x] 3.6 Continue-as-new after 50 encounters
  - [x] 3.7 Activities: pico_unlock_gate, pico_lock_gate, pico_safe_release, pico_set_mode
  - [x] 3.8 Worker registration on felisk-task-queue (`temporal_engine/worker.py`)
  - _Requirements: 1, 2, 3, 4, 5_

- [x] 4. Dashboard (`app.py`)
  - [x] 4.1 Flask app on port 5050 with Temporal client
  - [x] 4.2 Live state polling via Temporal query (800ms interval)
  - [x] 4.3 Mode toggle (Domestic / TNR) sending set_mode signal
  - [x] 4.4 Phase banner with animated state transitions
  - [x] 4.5 Four sensor cards (Proximity, RFID, Vision AI, Servo Gate)
  - [x] 4.6 Detection pipeline visualization (4-step)
  - [x] 4.7 Volunteer action buttons (TNR mode, LOCKED state only)
  - [x] 4.8 Last event description display
  - [x] 4.9 Auto-start workflow on boot
  - _Requirements: 1, 6_

- [x] 5. Test Suite
  - [x] 5.1 Activity unit tests — socket mocking, error handling (`tests/test_activities.py`)
  - [x] 5.2 Workflow integration tests — Temporal time-skipping environment (`tests/test_workflows.py`)
  - [x] 5.3 Domestic mode tests (authorized+clean, authorized+prey, unknown rejection)
  - [x] 5.4 TNR mode tests (ear-tipped pass, intact lock, volunteer release)
  - [x] 5.5 Mode switch signal test
  - [x] 5.6 State query verification test
  - _Requirements: All_

- [x] 6. Documentation
  - [x] 6.1 README.md — full project documentation with architecture, setup, and test instructions
  - [x] 6.2 PITCH.md — judges-facing pitch document with problem stats, agentic loop, and technical differentiators
  - [x] 6.3 demoScript.md — step-by-step demo recording guide with voiceover script

## Run Commands

```bash
# Start Temporal dev server
temporal server start-dev

# Start worker
python -m temporal_engine.worker

# Start dashboard (auto-starts workflow)
python app.py

# Start vision node
python lpyolo.py

# Run test suite (14 tests, all passing)
python -m pytest tests/ -v
```

## File Structure

```
felisk/
├── felisk.py                     # Pico W firmware (MicroPython)
├── lpyolo.py                     # Vision node (YOLOv8 + Temporal signals)
├── app.py                        # Flask dashboard (port 5050)
├── temporal_engine/
│   ├── __init__.py
│   ├── workflows.py              # TnrPortalWorkflow (dual-mode state machine)
│   ├── activities.py             # Pico W HTTP command activities
│   └── worker.py                 # Temporal worker registration
├── tests/
│   ├── test_activities.py        # Activity unit tests
│   └── test_workflows.py         # Workflow integration tests
├── pytest.ini                    # Test configuration
├── README.md                     # Project documentation
├── PITCH.md                      # Pitch document
├── demoScript.md                 # Demo recording script (gitignored)
└── .gitignore
```
