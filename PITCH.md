# Felisk — Durable Agentic AI Portal for Community Feline Care

## The Problem

Feral cat overpopulation is an ecological and welfare crisis hiding in plain sight.

- **70 million** feral cats roam the United States alone (ASPCA estimate)
- A single unspayed female can produce **100+ descendants** in 7 years
- Feral cats are the **#1 direct cause of bird mortality** in North America, killing 1.3–4 billion birds annually (Nature Communications, 2013)
- Traditional Trap-Neuter-Return (TNR) relies entirely on **manual volunteer labor** — cage traps must be physically monitored, checked daily, and managed by hand

TNR is the only humane, proven method to stabilize feral colonies. But it doesn't scale. Volunteers burn out. Traps sit unchecked. Cats that have already been neutered get re-trapped, wasting time and resources. Cats carrying prey (indicating active hunting of endangered species) get released back without intervention.

There is no intelligent, automated system bridging the gap between detection and humane action.

---

## The Solution: Felisk

Felisk is a fully autonomous, AI-driven TNR portal that replaces the manual trap-check-release cycle with an intelligent edge agent. It perceives, reasons, acts, and self-heals — all without human intervention in the normal case.

### What Happens When a Cat Approaches

1. **Proximity Detection** — HC-SR04 ultrasonic sensor detects motion within 15cm of the portal entrance
2. **Identity Scan** — MFRC522 RFID reader checks for a registered microchip tag
3. **Visual Classification** — YOLOv8 runs inference on a live camera feed, checking for:
   - Ear-tip (indicates already neutered — safe to release)
   - Intact ear (unregistered stray — candidate for TNR)
   - Prey in mouth (bird/mouse — block entry to protect wildlife)
4. **Physical Actuation** — SG90 micro-servo opens or locks the gate based on the AI's decision
5. **Durable State Management** — Temporal workflow ensures the encounter completes correctly regardless of power loss, network drops, or hardware failure

---

## Why This Is a True Agentic AI System

Traditional IoT is reactive: sensor input → hardcoded rule → static output.

Felisk follows the autonomous **Perceive → Reason → Act → Self-Heal** loop:

```
┌────────────────────────────────────────────────────────┐
│                     PERCEIVE                           │
│  Pico W reads ultrasonic distance + scans RFID tags   │
└───────────────────────┬────────────────────────────────┘
                        ▼
┌────────────────────────────────────────────────────────┐
│                      REASON                            │
│  YOLOv8 classifies: ear-tip / intact / prey           │
└───────────────────────┬────────────────────────────────┘
                        ▼
┌────────────────────────────────────────────────────────┐
│                       ACT                              │
│  Servo gate opens (safe cat) or locks (TNR/prey)      │
└───────────────────────┬────────────────────────────────┘
                        ▼
┌────────────────────────────────────────────────────────┐
│                    SELF-HEAL                           │
│  Temporal recovers workflow state after any failure    │
└────────────────────────────────────────────────────────┘
```

---

## Self-Healing: What It Actually Means

This is not marketing language. Here is exactly what the system does and what Temporal guarantees:

**Scenario 1: Power loss mid-capture**
A stray cat triggers the portal. The gate locks. The Pico W loses power before a volunteer responds. When power returns, the Temporal workflow is still running in the cloud — it knows the gate is in LOCKED state, it knows no volunteer has responded yet, and the 4-hour safety timer is still counting. No state is lost. No duplicate actions occur.

**Scenario 2: Network dropout**
The vision node classifies a cat and sends a signal to the workflow, but the network drops before the activity (gate command) executes. Temporal retries the activity automatically when connectivity resumes. The workflow does not advance to the next state until the activity confirms success.

**Scenario 3: Saga compensation (safety invariant)**
If a cat is locked and no volunteer decision arrives within 4 hours, the workflow executes a **compensating activity** — it sends `SAFE_RELEASE` to the Pico W, forcing the gate open. This is the Saga pattern: the system guarantees that no animal is ever left trapped indefinitely, regardless of external failures.

**Scenario 4: Worker crash**
The Python worker process crashes (OOM, exception, machine restart). Temporal preserves the full workflow execution history. When the worker restarts, it replays the history deterministically and resumes from exactly where it left off — mid-encounter, mid-timer, mid-wait.

These are properties of Temporal's durable execution model. They are not simulated. They work in production.

---

## Technical Differentiators

| Capability | How It's Implemented |
|-----------|---------------------|
| Edge AI inference | YOLOv8n running locally on laptop GPU — no cloud latency, works offline |
| Durable orchestration | Temporal workflow with signal-driven state machine — survives any failure |
| Saga rollback | Compensating activities auto-release gate on timeout — animal safety guaranteed |
| History management | `continue_as_new` after 50 encounters — infinite runtime, bounded resources |
| Real-time dashboard | Flask app polling Temporal query API at 800ms — live pipeline visualization |
| Direct hardware control | HTTP socket commands to Pico W — sub-second gate actuation |
| Dual-path verification | RFID for known residents + Vision AI for unknowns — no false captures |

---

## Hardware Stack

- **Raspberry Pi Pico W** — WiFi-enabled microcontroller (MicroPython)
- **HC-SR04** — Ultrasonic proximity sensor (2cm–400cm range)
- **MFRC522** — 13.56MHz RFID reader/writer (SPI interface)
- **SG90** — Micro servo motor (0–180° PWM control)
- **Active buzzer** — Audible status feedback
- **Red/Green LEDs** — Visual gate status indicators

## Software Stack

- **YOLOv8** (Ultralytics) — Real-time object detection trained on COCO
- **Temporal** — Durable workflow orchestration with Saga compensation
- **Flask** — Live monitoring dashboard
- **OpenCV** — Webcam capture and frame processing
- **MicroPython** — Pico W firmware with non-blocking socket API

---

## Demo Script (60 seconds)

1. All components running: Temporal server, worker, dashboard (localhost:5050), vision node
2. Dashboard shows MONITORING — system is alive, waiting
3. Press `t` in vision node: "Ear-tipped cat detected"
   - Dashboard lights up: Presence → Vision AI → **RELEASED** → Gate opens
   - System auto-resets to MONITORING after 5 seconds
4. Press `i`: "Intact stray detected"
   - Dashboard shows: **LOCKED** — gate secured for TNR pickup
   - After 4h timeout (or demo override), Saga rollback releases the gate
5. Press `p`: "Prey in mouth detected"
   - Dashboard shows: **LOCKED** — protecting local wildlife

The entire pipeline is visible in real time. Every state transition is driven by the Temporal workflow. No manual intervention needed for the happy path.

---

## One-Line Pitch

**"Felisk is a self-healing, AI-powered cat portal that autonomously identifies, classifies, and manages feral cats for TNR programs — using durable workflow orchestration to guarantee no animal is ever left trapped."**
