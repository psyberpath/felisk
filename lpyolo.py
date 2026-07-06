"""
Felisk — Laptop Vision Node (lpyolo.py)
Processes webcam frames via YOLOv8, classifies cats and prey,
and signals the running Temporal workflow with classification results.
Also sends direct socket commands to the Pico W for immediate actuation.

Works with both modes:
  DOMESTIC: Blocks prey-carrying cats from entering. Opens for clean residents.
  TNR: Locks gate on intact strays for capture. Ear-tipped cats pass freely.

Keyboard Overrides (for demo):
  'i' — Simulate intact stray (un-neutered) detection
  't' — Simulate ear-tipped (neutered) detection
  'p' — Simulate prey in mouth detection
  'c' — Simulate clean cat (no prey) detection
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
    """Send a signal to the running Temporal workflow. Blocks until sent."""
    loop = _get_temporal_loop()

    async def _signal():
        global _temporal_client
        from temporalio.client import Client
        if _temporal_client is None:
            _temporal_client = await Client.connect(TEMPORAL_ADDRESS)
        handle = _temporal_client.get_workflow_handle(WORKFLOW_ID)
        await handle.signal(signal_name, payload)
        print(f"  [TEMPORAL] Signal sent: {signal_name} = {payload}")

    future = asyncio.run_coroutine_threadsafe(_signal(), loop)
    try:
        future.result(timeout=5.0)  # Block until signal is confirmed sent
    except Exception as e:
        print(f"  [TEMPORAL] Signal failed: {e}")


def simulate_detection(visual_status: str) -> None:
    """
    Simulate a full detection cycle: presence → classification.
    Blocks until both signals are confirmed delivered to Temporal.
    """
    signal_temporal_workflow("presence_event", True)
    time.sleep(0.5)
    signal_temporal_workflow("prey_checked_event", visual_status)


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
    """Background thread: listen for commands from Pico (presence, RFID tags)."""
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
                print("[CMD] Camera paused — no motion")
            elif data.startswith("RFID:"):
                # Pico sends "RFID:<tag_uid>" when a tag is scanned
                tag_uid = data[5:]
                signal_temporal_workflow("tag_scanned_event", tag_uid)
                print(f"[CMD] RFID tag forwarded to workflow: {tag_uid}")
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
        print("\n[DEMO] Simulating: Intact stray detected")
        simulate_detection("intact_ear")
    elif key == ord("t"):
        print("\n[DEMO] Simulating: Ear-tipped cat detected")
        simulate_detection("ear_tipped")
    elif key == ord("p"):
        print("\n[DEMO] Simulating: Prey in mouth detected")
        simulate_detection("prey")
    elif key == ord("c"):
        print("\n[DEMO] Simulating: Clean cat verified")
        simulate_detection("clean")
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
        print("    i = intact stray        t = ear-tipped cat")
        print("    p = prey detected       c = clean cat")
        print("    q = quit")
        print()
        # Fallback: keyboard-only mode (no camera needed for demo)
        # Need a tiny OpenCV window for key capture
        import numpy as np
        blank = np.zeros((200, 420, 3), dtype=np.uint8)
        cv2.putText(blank, "Felisk Vision — Demo Mode", (20, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 130, 255), 2)
        cv2.putText(blank, "i=stray  t=tipped  p=prey  c=clean", (20, 100),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
        cv2.putText(blank, "q=quit", (20, 140),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
        cv2.putText(blank, "Toggle mode on dashboard (localhost:5050)", (20, 180),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (120, 120, 120), 1)

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
                else:
                    print(f"[AI] Clean cat verified: {labels}")
                    time.sleep(0.2)
                    signal_temporal_workflow("prey_checked_event", "clean")

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
