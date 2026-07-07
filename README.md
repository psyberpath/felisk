# Felisk — Autonomous TNR Portal

**An AI-powered smart cat flap that detects, classifies, and manages feral cat encounters in real time using IoT sensors, computer vision, and durable workflow orchestration.**

Built for #hackthekitty 2026.

---

## What It Does

Felisk is a fully autonomous Trap-Neuter-Return (TNR) portal. Read [PITCH.md](https://github.com/psyberpath/felisk/blob/main/PITCH.md) for more comprehensive detail.

When a cat approaches:

1. **Ultrasonic sensor** detects motion at the portal entrance
2. **RFID scanner** checks if the cat is a registered resident
3. **YOLOv8 vision AI** classifies the cat (ear-tipped/intact, carrying prey)
4. **Servo gate** actuates — granting access to known cats or safely containing unregistered strays for TNR pickup

The entire pipeline is orchestrated by a **Temporal durable workflow** that guarantees no animal is ever trapped indefinitely (4-hour safety timeout auto-releases), survives crashes/restarts, and maintains full audit state.

---

## Architecture

```
┌─────────────────┐     ┌────────────────────┐     ┌──────────────────┐
│  Pico W (IoT)   │────▶│  Temporal Workflow  │◀────│  YOLOv8 Vision   │
│  felisk.py      │     │  workflows.py       │     │  lpyolo.py       │
│                 │◀────│  activities.py      │     │                  │
│ HC-SR04 + RFID  │     │  worker.py          │     │ Webcam + YOLO    │
│ + Servo + LEDs  │     └────────────────────┘     └──────────────────┘
└─────────────────┘              │
                                 ▼
                    ┌────────────────────────┐
                    │  Live Dashboard        │
                    │  app.py (Flask)        │
                    │  localhost:5050        │
                    └────────────────────────┘
```

---

## Components & Their Role

| Component | File | What It Does |
|-----------|------|--------------|
| **IoT Firmware** | `felisk.py` | Runs on Raspberry Pi Pico W. Reads HC-SR04 ultrasonic distance, scans MFRC522 RFID tags, controls SG90 servo gate, LEDs, and buzzer. Exposes HTTP API for remote actuation. |
| **Vision Node** | `lpyolo.py` | Runs on laptop with webcam. Uses YOLOv8 to detect cats and prey (birds/mice) in real time. Signals the Temporal workflow with classification results and sends direct commands to Pico W. |
| **Temporal Workflow** | `temporal_engine/workflows.py` | Durable state machine managing the full encounter lifecycle. Accepts signals from all sensors, makes decisions, executes gate commands via activities. Implements Saga pattern for safety rollback. |
| **Temporal Activities** | `temporal_engine/activities.py` | Network activities that send HTTP commands to the Pico W servo gate. Isolated for retry/timeout handling. |
| **Temporal Worker** | `temporal_engine/worker.py` | Registers workflow and activities with the Temporal server. Processes task queue events. |
| **Live Dashboard** | `app.py` | Flask web app polling Temporal workflow state in real time. Visualizes the detection pipeline, gate status, and encounter history. |

---

## Why Temporal?

Temporal provides **durable execution** — the workflow survives process crashes, network failures, and restarts without losing state. This is critical for animal safety:

- **Saga Pattern**: If a cat is locked and no volunteer responds within 4 hours, the compensating activity auto-releases the gate. The animal is never trapped indefinitely.
- **Signal-Driven**: Sensors push events (presence, RFID, vision) as signals. The workflow reacts without polling.
- **Continue-As-New**: After 50 encounters, the workflow refreshes its history to prevent unbounded growth while maintaining continuity.
- **Query State**: The dashboard reads live workflow state without side effects.

---

## How to Run

### Prerequisites

- Python 3.11+
- [Temporal CLI](https://docs.temporal.io/cli) (local dev server)
- Webcam (for vision node)
- Raspberry Pi Pico W with sensors (for hardware demo)

### 1. Start Temporal Server

```bash
temporal server start-dev
```

### 2. Install Dependencies

```bash
python -m venv venv
source venv/bin/activate
pip install temporalio flask ultralytics opencv-python
```

### 3. Start the Temporal Worker

```bash
python -m temporal_engine.worker
```

### 4. Start the Dashboard

```bash
python app.py
```

Opens at [http://localhost:5050](http://localhost:5050). The workflow starts automatically.

### 5. Start the Vision Node

```bash
python lpyolo.py
```

Keyboard overrides for demo without a live cat:
- `i` — simulate intact stray detection
- `t` — simulate ear-tipped (neutered) cat
- `p` — simulate prey detection
- `q` — quit

### 6. Flash the Pico W (optional for hardware demo)

Copy `felisk.py` to the Pico W along with the `mfrc522` library. Update `WIFI_SSID` and `WIFI_PASS`, then the Pico boots into its sensor loop and HTTP command API automatically.

---

## Demo Flow

1. Start Temporal, worker, dashboard, and vision node
2. Dashboard shows **MONITORING** — waiting for a cat
3. Press `t` in vision node → ear-tipped cat detected → gate opens → dashboard shows **RELEASED**
4. System auto-resets to MONITORING for the next encounter
5. Press `i` → intact stray → gate locks → dashboard shows **LOCKED**
6. After timeout (or manually), gate auto-releases (Saga rollback)

The dashboard updates in real time throughout, showing exactly which stage of the pipeline is active.

---

## Tech Stack

- **Hardware/IoT** — Raspberry Pi Pico W, MicroPython, HC-SR04, MFRC522, SG90 servo
- **YOLOv8** (Ultralytics) — real-time object detection
- **Temporal** — durable workflow orchestration, Saga compensation
- **Flask** — live monitoring dashboard
- **OpenCV** — webcam frame capture and display

---

## License

MIT

---

## Demo Video

Watch the full demo: https://drive.google.com/drive/folders/1YmOivOhYAosYQEg68PwJZZc2VgkJdpQ4

A captions `.txt` file is included in the folder — kindly use it to follow along with the video narration.
