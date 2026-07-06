# Felisk 

> "The community hardware space suffers from a massive cost barrier. Commercial smart traps cost $350–$700. Community TNR programs run on volunteer burnout and wire cages left unchecked in the cold. So I engineered a single, ultra-affordable hardware stack — using off-the-shelf parts — that completely transitions roles based on user demand: an automated security asset for your home, and a community animal welfare tool. Same board. Same servo. Two radically different missions."

---

## One-Line Pitch

**"Felisk is a self-healing, durable agentic AI portal for community feline care — an under-$50 open-source IoT kit that autonomously identifies, classifies, and manages cats using edge AI and fault-tolerant workflow orchestration, guaranteeing no animal is ever left trapped."**

---

## The Problem (With Numbers)

- **70 million** feral cats in the US alone
- **1.3–4 billion** birds killed annually by feral cats in North America
- One unspayed female → **100+ descendants** in 7 years
- TNR is the only humane, proven stabilization method — but it's **a lot of manual labor**
- Commercial smart traps: **$350–$700** per unit — completely inaccessible to non-profits
- Domestic cat owners lose **an estimated 3.6 million songbirds per year** to prey brought indoors
- Current solutions: duct-tape-and-prayer DIY scripts that crash when WiFi drops, leaving animals trapped indefinitely

---

## The Solution: Unified Dual-Mode Platform

One piece of hardware. A cat wearable (RFID collar tag) as the identity layer. A laptop with a webcam as the vision brain. A Temporal workflow engine as the fault-tolerant backbone.

### Domestic Mode — "Keep the Dead Birds Out"
Gate normally locked. Your cat approaches wearing its RFID wearable → identity confirmed → YOLOv8 checks mouth for prey → clean? Gate opens 4 seconds. Carrying a dead bird? Gate stays shut. Foreign cat with no tag? Rejected at the hardware level.

### TNR Mode — "Catch, Don't Cage"
Gate normally open. Community shelter box in an alley. Feral cats enter freely to eat. Ear-tipped cats (already neutered) pass through — logged but never disturbed. Intact stray enters? Gate snaps shut. Temporal starts a 4-hour timer. Volunteer confirms pickup on the dashboard, or the system auto-releases. No animal sits in a cold wire cage overnight.

---

## Felisk Agentic AI Capability

This is not a sensor hooked to an if/else script. This is a physical edge agent executing an autonomous decision loop:

**PERCEIVE** — The Raspberry Pi Pico W continuously reads ultrasonic distance (GP2/GP3) and scans for RFID identity tags via SPI (GP16–GP20). It knows something is there and who it might be.

**REASON** — When identity alone isn't sufficient, the system escalates to visual AI. YOLOv8 runs locally on the laptop, performing semantic evaluation: Is there prey in the mouth? Is the left ear tipped (indicating prior neutering)? The model makes a classification decision that the hardware cannot.

**ACT** — The Pico W's GP15 PWM controller translates the AI's decision into physical motion, driving the micro-servo gate between 0° (locked) and 90° (open). The decision becomes a physical action in the real world.

**SELF-HEAL** — This is the ultimate technical differentiator. Using Temporal, the system treats physical capture as a long-running, state-aware transaction. Failures at any point in the loop are recovered automatically without human intervention.

---

## Self-Healing: What It Actually Does

This is not a marketing claim. These are concrete failure scenarios and exactly what the system does:

**Power loss mid-capture:** A stray triggers the portal. Gate locks. Pico loses power. When power returns, the Temporal workflow is still running in the cloud — it knows the gate is LOCKED, no volunteer responded yet, the 4-hour safety timer is still counting. Execution resumes exactly where it stopped.

**Network dropout:** Vision node classifies a cat and signals the workflow. Network drops before the gate activity executes. Temporal retries the activity automatically when connectivity resumes. The workflow does not advance until the physical action confirms success.

**Saga compensation (the safety invariant):** If a cat is locked and no volunteer responds within 4 hours, the workflow executes a compensating activity — `SAFE_RELEASE` fires the servo to 90°. This is the Saga pattern applied to physical hardware. The system mathematically guarantees no animal is trapped indefinitely.

**Worker crash:** Python process dies (OOM, unhandled exception, machine restart). Temporal preserves full execution history server-side. Worker restarts → replays deterministically → resumes from the exact state. No duplicate actions. No orphaned state.

---

## Technical Differentiators

| Capability | Implementation | Why It Matters |
|-----------|---------------|----------------|
| Edge AI inference | YOLOv8n running locally — no cloud API calls | Works offline, zero latency, no subscription cost |
| Durable orchestration | Temporal workflow with signal-driven state machine | Survives any failure mode — power, network, process |
| Saga rollback | Compensating activities on timeout | Animal safety guaranteed at the protocol level |
| Dual-mode switching | Dashboard toggle → Temporal signal → Pico actuation | Same hardware, two radically different use cases |
| History management | `continue_as_new` after 50 encounters | Infinite runtime, bounded memory |
| Cat wearable identity | RFID collar tag as digital passport | Hardware-level resident/stranger discrimination |
| $50 total BOM | All commodity components, open-source stack | 10x cheaper than commercial alternatives |

---

## Adversarial Integration Testing

Because live feral cats cannot be summoned on demand, the system includes an adversarial integration testing suite. Keyboard triggers inject mock computer-vision payloads directly into the Temporal pipeline to demonstrate deterministic edge-case handling.

This exercises the identical signal path that real YOLOv8 detections use — end-to-end through Temporal, through the activity layer, and out to the physical servo. Judges can verify every branch of the state machine without a live animal.

---

## Hardware Stack

| Component | Role |
|-----------|------|
| Raspberry Pi Pico W | WiFi edge controller |
| HC-SR04 Ultrasonic | Proximity sensing |
| MFRC522 RFID Module | Identity scanning |
| SG90 Micro Servo | Gate actuation |
| RFID Tags (x5) | Cat wearable collar tags |
| Breadboard + Jumpers | Prototyping |
| LEDs + Buzzer + Resistors | Status indicators |
| USB Power Supply | Portable power |

---

## Software Stack

- **MicroPython** — Pico W firmware (sensor polling, HTTP command API, mode-aware actuation)
- **YOLOv8** (Ultralytics) — Real-time object detection, COCO-pretrained
- **Temporal** — Durable workflow orchestration, Saga compensation, signal-driven state machine
- **Flask** — Live telemetry dashboard with mode toggle and volunteer controls
- **OpenCV** — Webcam frame capture and annotation display

---

## The Path Forward

The current prototype is a breadboard + paper box. The path to production:

1. **3D-printed enclosure** — weatherproof, cat-sized, with integrated sensor mounts
2. **Custom PCB** — replace breadboard with soldered board for reliability
3. **Solar power** — outdoor TNR deployments need off-grid capability
4. **Multi-node mesh** — multiple portals reporting to a single Temporal workflow
5. **Open-source hardware files** — STL files, KiCad schematics, full build guide

The code is already open-source. The vision is community volunteer networks worldwide deploying affordable kits to stabilize feral colonies at scale.

---

## Closing Line

> "Every year, millions of feral cats and billions of birds die because we don't have affordable, intelligent infrastructure for humane management. Felisk is that infrastructure — a self-healing edge agent that costs less than a vet visit and guarantees no animal is ever left behind."
