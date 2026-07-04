"""
Felisk — Laptop Vision Node (lpyolo.py)
Processes webcam frames via YOLOv8, classifies cats and prey,
and signals the running Temporal workflow with classification results.
Also sends direct socket commands to the Pico W for immediate actuation.

Keyboard Overrides (for demo/presentation):
  'i' — Simulate intact stray (un-neutered) detection → gate locks
  't' — Simulate ear-tipped (neutered) detection → gate opens
  'p' — Simulate prey in mouth detection → gate locks
  'c' — Simulate clean cat (no prey) → gate opens
  'q' — Quit
"""

import asyncio
import socket
import threading
import time
from typing import Optional

import cv2
from ultralytics import YOLO

# ─── Configuration ───────────────────────────────────────────────────────────
PICO_IP: str = "10.143.184.136"
PICO_PORT: int = 80
MODEL_PATH: str = "yolov8n.pt"
CONFIDENCE_THRESHOLD: float = 0.25
PREY_CLASSES: set = {"bird", "mouse"}
LISTEN_PORT: int = 5001

TEMPORAL_ADDRESS: str = "localhost:7233"
WORKFLOW_ID: str = "felisk-tnr-portal"

# ─── State ───────────────────────────────────────────────────────────────────
camera_active = threading.Event()
camera_active.set()


# ─── Temporal Integration ────────────────────────────────────────────────────
_temporal_client = None
_temporal_loop: Optional[asyncio.AbstractEventLoop] = None


def _get_temporal_loop() -> asyncio.AbstractEventLoop:
    global _temporal_loop
    if _temporal_loop is None or _temporal_loop.is_closed():
        _temporal_loop = asyncio.new_event_loop()
        t = threading.Thread(target=_temporal_loop.run_forever, daemon=True)
        t.start()
    return _temporal_loop


def signal_temporal_workflow(signal_name: str, payload) -> None:
    """Send a signal to the running Temporal workflow (non-blocking)."""
    loop = _get_temporal_loop()

    async def _signal():
        global _temporal_client
        try:
            from temporalio.client import Client
            if _temporal_client is None:
                _temporal_client = await Client.connect(TEMPORAL_ADDRESS)
            handle = _temporal_client.get_workflow_handle(WORKFLOW_ID)
            await handle.signal(signal_name, payload)
            print(f"  [TEMPORAL] Signal sent: {signal_name} = {payload}")
        except Exception as e:
            print(f"  [TEMPORAL] Signal failed: {e}")

    asyncio.run_coroutine_threadsafe(_signal(), loop)


def simulate_detection(visual_status: str, pico_command: str) -> None:
    """
    Simulate a full detection cycle: presence → classification → actuation.
    This is what keyboard overrides call to trigger a complete workflow encounter.
    """
    # Step 1: Signal presence (wakes the workflow from MONITORING)
    signal_temporal_workflow("presence_event", True)
    # Step 2: Small delay so the workflow registers presence and starts waiting for vision
    time.sleep(0.3)
    # Step 3: Send the vision classification
    signal_temporal_workflow("prey_checked_event", visual_status)
    # Step 4: Direct command to Pico W (immediate hardware feedback)
    send_to_pico(pico_command)


# ─── Socket Communication ────────────────────────────────────────────────────
def send_to_pico(command: str) -> bool:
    """Send an HTTP GET command to the Pico W matching its firmware API."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(6.0)
            s.connect((PICO_IP, PICO_PORT))
            http_req = (
                f"GET /api/command?value={command} HTTP/1.1\r\n"
                f"Host: {PICO_IP}\r\n"
                "Connection: close\r\n\r\n"
            )
            s.sendall(http_req.encode("utf-8"))
            s.recv(1024)
        print(f"  [PICO] Command sent: {command}")
        return True
    except (OSError, socket.timeout) as e:
        print(f"  [PICO] Unreachable ({command}): {e}")
        return False


def listen_for_pico_commands() -> None:
    """Background thread: listen for TRIGGER_CAMERA / STOP_CAMERA from Pico."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", LISTEN_PORT))
    srv.listen(1)
    srv.settimeout(2.0)
    print(f"[NET] Listening for Pico commands on :{LISTEN_PORT}")

    while True:
        try:
            conn, _ = srv.accept()
            data = conn.recv(256).decode("utf-8").strip()
            conn.sendall(b"ACK\n")
            conn.close()

            if data == "TRIGGER_CAMERA":
                camera_active.set()
                signal_temporal_workflow("presence_event", True)
                print("[CMD] Camera activated by Pico proximity trigger")
            elif data == "STOP_CAMERA":
                camera_active.clear()
                signal_temporal_workflow("presence_event", False)
                print("[CMD] Camera paused — no motion")
        except socket.timeout:
            continue
        except OSError:
            continue


# ─── YOLOv8 Classification ───────────────────────────────────────────────────
def classify_frame(model: YOLO, frame) -> tuple[bool, bool, list[str]]:
    """
    Run YOLOv8 inference on a single frame.
    Returns: (cat_detected, prey_detected, labels_found)
    """
    results = model(frame, verbose=False, conf=CONFIDENCE_THRESHOLD)
    cat_detected = False
    prey_detected = False
    labels: list[str] = []

    for r in results:
        for box in r.boxes:
            label = model.names[int(box.cls)]
            labels.append(label)
            if label == "cat":
                cat_detected = True
            elif label in PREY_CLASSES:
                prey_detected = True

    return cat_detected, prey_detected, labels


# ─── Keyboard Handler ────────────────────────────────────────────────────────
def handle_key(key: int) -> bool:
    """Process keyboard input. Returns True if should quit."""
    if key == ord("q"):
        return True
    elif key == ord("i"):
        print("\n[DEMO] Simulating: Intact stray detected → LOCK")
        simulate_detection("intact_ear", "LOCK_CAPTURE")
    elif key == ord("t"):
        print("\n[DEMO] Simulating: Ear-tipped cat detected → RELEASE")
        simulate_detection("ear_tipped", "ACCESS_APPROVED")
    elif key == ord("p"):
        print("\n[DEMO] Simulating: Prey in mouth detected → LOCK")
        simulate_detection("prey", "LOCK_CAPTURE")
    elif key == ord("c"):
        print("\n[DEMO] Simulating: Clean cat verified → RELEASE")
        simulate_detection("clean", "ACCESS_APPROVED")
    return False



# ─── Main Loop ───────────────────────────────────────────────────────────────
def main() -> None:
    model = YOLO(MODEL_PATH)

    # Start background listener for Pico commands
    listener = threading.Thread(target=listen_for_pico_commands, daemon=True)
    listener.start()

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[FELISK] Cannot open webcam — running in demo-only mode.")
        print("  macOS: grant camera access in System Settings → Privacy → Camera")
        print()
        print("  Demo keys:")
        print("    i = intact stray (locks gate)")
        print("    t = ear-tipped cat (opens gate)")
        print("    p = prey detected (locks gate)")
        print("    c = clean cat (opens gate)")
        print("    q = quit")
        print()
        # Fallback: keyboard-only mode (no camera needed for demo)
        # Need a tiny OpenCV window for key capture
        import numpy as np
        blank = np.zeros((200, 400, 3), dtype=np.uint8)
        cv2.putText(blank, "Felisk Vision — Demo Mode", (20, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 130, 255), 2)
        cv2.putText(blank, "i=stray  t=tipped  p=prey  c=clean", (20, 110),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
        cv2.putText(blank, "q=quit", (20, 150),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)

        while True:
            cv2.imshow("Felisk Vision", blank)
            key = cv2.waitKey(200) & 0xFF
            if key == 255:
                continue
            if handle_key(key):
                break

        cv2.destroyAllWindows()
        return

    print("[FELISK] Vision node online — webcam active.")
    print("  Demo keys: i=stray  t=tipped  p=prey  c=clean  q=quit")
    print()

    frame_count = 0
    last_detection_time = 0
    COOLDOWN = 3.0  # seconds between auto-detections to avoid signal spam

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if not camera_active.is_set():
            time.sleep(0.1)
            continue

        frame_count += 1

        # Run YOLO every 3rd frame for performance
        if frame_count % 3 == 0 and (time.time() - last_detection_time) > COOLDOWN:
            cat_detected, prey_detected, labels = classify_frame(model, frame)

            if cat_detected:
                last_detection_time = time.time()
                signal_temporal_workflow("presence_event", True)

                if prey_detected:
                    print(f"[AI] Cat with PREY detected: {labels}")
                    time.sleep(0.2)
                    signal_temporal_workflow("prey_checked_event", "prey")
                    send_to_pico("LOCK_CAPTURE")
                else:
                    print(f"[AI] Clean cat verified: {labels}")
                    time.sleep(0.2)
                    signal_temporal_workflow("prey_checked_event", "clean")
                    send_to_pico("ACCESS_APPROVED")

        # Draw YOLO annotations on display frame
        results = model(frame, verbose=False, conf=CONFIDENCE_THRESHOLD)
        annotated = results[0].plot() if results else frame
        cv2.imshow("Felisk Vision", annotated)

        key = cv2.waitKey(1) & 0xFF
        if key != 255 and handle_key(key):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
