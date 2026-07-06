# Requirements Document

## Introduction

Felisk is a dual-mode agentic IoT platform for the #hackthekitty 2026 hackathon. The system connects a Raspberry Pi Pico W (MicroPython) with a laptop-based YOLOv8 computer vision node and a Temporal.io durable orchestration backend. It operates as either a Domestic pet gate (normally closed, RFID + vision verification) or a Community TNR trap (normally open, locks on intact strays). The architecture prioritizes animal safety through Saga compensation patterns, fault tolerance via durable workflow execution, and affordable open-source hardware.

## Glossary

- **Felisk System**: The complete IoT platform comprising the Pico W edge controller, laptop vision node, Temporal.io orchestration backend, and Flask dashboard.
- **Pico W**: Raspberry Pi Pico W microcontroller running MicroPython, acting as the edge sensor/actuator hub with an HTTP command API.
- **Vision Node**: A macOS laptop running YOLOv8 inference on webcam frames (`lpyolo.py`), signaling the Temporal workflow with classification results.
- **Temporal Engine**: The Temporal.io durable workflow orchestration backend managing the dual-mode state machine, Saga rollbacks, and signal-driven encounter processing.
- **Dashboard**: Flask web application (`app.py`) on port 5050 providing live telemetry, mode toggling, and volunteer controls.
- **HC-SR04**: Ultrasonic distance sensor on GP2 (Trigger) and GP3 (Echo) for presence detection.
- **MFRC522**: SPI-based RFID reader on GP16–GP20 for cat wearable (collar tag) scanning.
- **Servo Gate**: SG90 PWM-driven servo motor on GP15 controlling physical access (0° = closed, 90° = open).
- **Cat Wearable**: RFID collar tag serving as a digital identity passport for registered domestic cats.
- **Domestic Mode**: Gate normally locked at 0°. Opens only for authorized RFID + clean vision verification.
- **TNR Mode**: Gate normally open at 90°. Locks only when an intact (un-neutered) stray is detected for capture.
- **Ear-Tip Classification**: YOLOv8-based visual classification distinguishing ear-tipped (neutered) cats from intact-ear (un-neutered) cats.
- **Saga Rollback**: Temporal compensating activity that auto-releases the gate after a 4-hour volunteer timeout, guaranteeing no animal is trapped indefinitely.
- **Adversarial Integration Testing**: Keyboard-driven mock signal injection exercising the full Temporal pipeline without live animals.

## Requirements

### Requirement 1: Dual-Mode Operation

**User Story:** As a system operator, I want to toggle between Domestic and TNR mode from the dashboard, so that the same hardware serves both residential pet security and community animal welfare.

#### Acceptance Criteria

1. WHEN the operator selects Domestic mode on the dashboard, THE system SHALL signal the Temporal workflow to set mode to DOMESTIC and command the Pico W to lock the gate at 0°.
2. WHEN the operator selects TNR mode on the dashboard, THE system SHALL signal the Temporal workflow to set mode to TNR and command the Pico W to open the gate at 90°.
3. THE mode switch SHALL propagate to the Pico W hardware within 10 seconds via a Temporal activity.
4. THE dashboard SHALL display the current mode and its behavioral description at all times.

### Requirement 2: Domestic Mode — Authorized Access with Prey Blocking

**User Story:** As a cat owner, I want the portal to open only for my registered cat when it is not carrying prey, so that foreign cats and dead animals are kept out of my home.

#### Acceptance Criteria

1. IN Domestic mode, THE Servo Gate SHALL remain locked at 0° until an authorized RFID tag is scanned AND vision classification confirms no prey.
2. WHEN an authorized RFID tag is scanned AND vision reports "clean" or "ear_tipped", THE gate SHALL open to 90° for 4 seconds then relock to 0°.
3. IF an authorized RFID tag is scanned BUT vision reports "prey", THE gate SHALL remain locked and THE system SHALL log "Prey detected — entry denied."
4. IF no authorized RFID tag is detected within 5 seconds of presence, THE gate SHALL remain locked and THE system SHALL log the rejection.

### Requirement 3: TNR Mode — Selective Capture of Intact Strays

**User Story:** As a TNR volunteer, I want the portal to lock only on un-neutered stray cats while allowing ear-tipped cats to pass freely, so that capture is selective and humane.

#### Acceptance Criteria

1. IN TNR mode, THE Servo Gate SHALL default to the open position (90°) to allow free entry.
2. WHEN the vision node classifies a cat as "ear_tipped" or "clean", THE gate SHALL remain open and THE encounter SHALL be logged.
3. WHEN the vision node classifies a cat as "intact_ear" or "prey", THE gate SHALL lock to 0° and THE Temporal workflow SHALL enter the LOCKED phase awaiting volunteer decision.
4. WHEN locked in TNR mode, THE dashboard SHALL display volunteer action buttons (Release / Confirm Capture).

### Requirement 4: Saga Rollback — Animal Safety Guarantee

**User Story:** As a TNR volunteer, I want the system to automatically release a trapped animal if no human responds within 4 hours, so that animals are never left trapped indefinitely.

#### Acceptance Criteria

1. WHEN a cat is captured in TNR mode, THE Temporal workflow SHALL start a 4-hour volunteer verification timer.
2. IF a volunteer signals "SAFE_RELEASE", THE system SHALL execute the pico_safe_release activity to open the gate.
3. IF no volunteer decision is received within 4 hours, THE Temporal workflow SHALL automatically execute the pico_safe_release compensating activity (Saga rollback).
4. THE gate SHALL return to the mode's resting position after release (90° in TNR mode).

### Requirement 5: Durable Execution and Crash Recovery

**User Story:** As a system operator, I want the workflow to survive power failures, network dropouts, and process crashes without losing state, so that the system is reliable in unattended outdoor deployments.

#### Acceptance Criteria

1. IF the Temporal worker process crashes, THE workflow state SHALL be preserved and resumed on worker restart without duplicate actions.
2. IF a Pico W activity fails due to network timeout, THE Temporal engine SHALL retry the activity up to 2 times with 1-second backoff.
3. IF an activity permanently fails, THE workflow SHALL enter a safe state (RELEASED) to prevent trapping.
4. AFTER 50 encounters, THE workflow SHALL execute continue-as-new to prevent unbounded history growth.

### Requirement 6: Real-Time Dashboard Telemetry

**User Story:** As a system operator, I want a live dashboard showing sensor states, vision classification, gate position, and pipeline progress, so that I can monitor the system in real time.

#### Acceptance Criteria

1. THE dashboard SHALL poll workflow state via Temporal query every 800ms.
2. THE dashboard SHALL display: proximity status, RFID scan result, vision AI classification, gate position, current phase, and encounter count.
3. THE dashboard SHALL visualize the detection pipeline (Detect → Identify → Classify → Actuate) with active/done/alert states.
4. THE dashboard SHALL display a human-readable description of the last action taken.

### Requirement 7: Vision Node Classification and Signaling

**User Story:** As a system operator, I want the vision node to classify cats in real time and signal the workflow, so that the system makes autonomous decisions based on visual evidence.

#### Acceptance Criteria

1. THE vision node SHALL run YOLOv8 inference on webcam frames, detecting "cat", "bird", and "mouse" classes.
2. WHEN a cat is detected, THE vision node SHALL signal the Temporal workflow with presence_event and prey_checked_event.
3. THE vision node SHALL send direct HTTP commands to the Pico W for immediate hardware feedback.
4. THE vision node SHALL include keyboard-driven adversarial integration testing (keys i, t, p, c) exercising the full signal path end-to-end.
