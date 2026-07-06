"""
Felisk — Temporal Activities
Socket-based actuator commands sent to the Pico W over TCP :5000.
"""

import socket
from dataclasses import dataclass
from temporalio import activity
from temporalio.exceptions import ApplicationError

# ─── Configuration ───────────────────────────────────────────────────────────
PICO_IP: str = "10.143.184.136"
PICO_PORT: int = 80  # Pico W listens on port 80 (HTTP-style commands)
SOCKET_TIMEOUT: float = 6.0  # Pico holds servo open 4s before responding


# ─── Data Classes ────────────────────────────────────────────────────────────
@dataclass
class PicoCommand:
    """Payload sent to an activity for Pico W communication."""
    command: str
    description: str = ""


# ─── Helpers ─────────────────────────────────────────────────────────────────
def _send_to_pico(command: str) -> str:
    """
    Send an HTTP GET request to the Pico W matching its firmware API format.
    The Pico listens on port 80 and parses 'GET /api/command?value=CMD'.
    Returns the response or raises ApplicationError (non-retryable) on failure.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(SOCKET_TIMEOUT)
            s.connect((PICO_IP, PICO_PORT))
            http_req = (
                f"GET /api/command?value={command} HTTP/1.1\r\n"
                f"Host: {PICO_IP}\r\n"
                "Connection: close\r\n\r\n"
            )
            s.sendall(http_req.encode("utf-8"))
            response = s.recv(1024).decode("utf-8").strip()
        activity.logger.info(f"Pico response for '{command}': {response}")
        return response
    except (OSError, socket.timeout) as exc:
        raise ApplicationError(
            f"Socket communication failed for command '{command}': {exc}",
            non_retryable=True,
        )


# ─── Activities ──────────────────────────────────────────────────────────────
@activity.defn
async def pico_unlock_gate(cmd: PicoCommand) -> str:
    """Send ACCESS_APPROVED to Pico W — opens the servo gate."""
    activity.logger.info(f"Unlocking gate: {cmd.description}")
    return _send_to_pico("ACCESS_APPROVED")


@activity.defn
async def pico_lock_gate(cmd: PicoCommand) -> str:
    """Send LOCK_CAPTURE to Pico W — locks the servo gate for TNR capture."""
    activity.logger.info(f"Locking gate: {cmd.description}")
    return _send_to_pico("LOCK_CAPTURE")


@activity.defn
async def pico_safe_release(cmd: PicoCommand) -> str:
    """
    Send SAFE_RELEASE to Pico W — compensating activity (Saga rollback).
    Opens the gate to ensure an animal is never left trapped.
    """
    activity.logger.info(f"Safe release (Saga compensation): {cmd.description}")
    return _send_to_pico("SAFE_RELEASE")


@activity.defn
async def pico_set_mode(cmd: PicoCommand) -> str:
    """
    Switch Pico W gate resting state.
    MODE_DOMESTIC → gate locks at 0°
    MODE_TNR → gate opens to 90°
    """
    activity.logger.info(f"Setting mode: {cmd.command}")
    return _send_to_pico(cmd.command)
