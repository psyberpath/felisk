"""
Felisk — Temporal Workflow: TnrPortalWorkflow
Dual-mode durable workflow managing the smart cat portal.
Supports DOMESTIC mode (normally locked) and TNR mode (normally open).
Uses signals for event ingestion, queries for state inspection,
and the Saga pattern for safe rollback on timeout or fault.
"""

from dataclasses import dataclass, field
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from temporal_engine.activities import (
        PicoCommand,
        pico_lock_gate,
        pico_safe_release,
        pico_set_mode,
        pico_unlock_gate,
    )


# ─── Constants ───────────────────────────────────────────────────────────────
TASK_QUEUE = "felisk-task-queue"
VOLUNTEER_TIMEOUT = timedelta(hours=4)
ACTIVITY_TIMEOUT = timedelta(seconds=10)
ACTIVITY_RETRY = RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=1))

MAX_ENCOUNTERS = 50

# Authorized RFID tags (matching felisk.py firmware authorized_felines list)
AUTHORIZED_TAGS: set[str] = {"A1B2C3D4", "DEADBEEF", "CAFEBABE", "146_73_250_5"}


# ─── State Container ─────────────────────────────────────────────────────────
@dataclass
class PortalState:
    mode: str = "DOMESTIC"  # "DOMESTIC" or "TNR"
    presence_active: bool = False
    tag_scanned: str = ""
    visual_status: str = ""  # "clean", "prey", "intact_ear", "ear_tipped"
    human_decision: str = ""  # "APPROVE_CAPTURE", "SAFE_RELEASE"
    workflow_phase: str = "IDLE"  # IDLE, MONITORING, LOCKED, RELEASED
    encounter_count: int = 0
    last_event: str = ""  # Human-readable description of last action



# ─── Workflow Definition ─────────────────────────────────────────────────────
@workflow.defn
class TnrPortalWorkflow:
    """
    Dual-mode Felisk Portal workflow.

    DOMESTIC mode (gate normally locked at 0°):
      - Only opens for authorized RFID + clean vision check
      - Blocks cats carrying prey (birds/mice)
      - Blocks unknown/foreign cats

    TNR mode (gate normally open at 90°):
      - Gate stays open so ferals can enter shelter freely
      - Locks only when intact (un-neutered) stray is detected
      - Ear-tipped cats pass through freely
      - Saga rollback releases gate after 4h if no volunteer responds
    """

    def __init__(self) -> None:
        self._state = PortalState()

    # ─── Signals ─────────────────────────────────────────────────────────
    @workflow.signal
    async def presence_event(self, detected: bool) -> None:
        """HC-SR04 presence detection signal."""
        if isinstance(detected, str):
            self._state.presence_active = detected.lower() in ("true", "1", "yes")
        else:
            self._state.presence_active = bool(detected)

    @workflow.signal
    async def tag_scanned_event(self, tag_uid: str) -> None:
        """RFID tag scan result."""
        self._state.tag_scanned = tag_uid

    @workflow.signal
    async def prey_checked_event(self, visual_status: str) -> None:
        """YOLOv8 classification result from the vision node."""
        self._state.visual_status = visual_status

    @workflow.signal
    async def volunteer_decision(self, decision: str) -> None:
        """Volunteer decision from dashboard (TNR mode only)."""
        self._state.human_decision = decision

    @workflow.signal
    async def set_mode(self, mode: str) -> None:
        """Toggle between DOMESTIC and TNR modes — also commands the Pico gate."""
        if mode in ("DOMESTIC", "TNR"):
            self._state.mode = mode
            self._state.last_event = f"Mode switched to {mode}"
            # Send mode command to Pico W to change resting gate position
            pico_cmd = "MODE_DOMESTIC" if mode == "DOMESTIC" else "MODE_TNR"
            try:
                await workflow.execute_activity(
                    pico_set_mode,
                    PicoCommand(command=pico_cmd, description=f"Switch to {mode}"),
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    retry_policy=ACTIVITY_RETRY,
                )
            except Exception:
                pass

    # ─── Queries ─────────────────────────────────────────────────────────
    @workflow.query
    def get_workflow_state(self) -> dict:
        """Return current workflow state for dashboard polling."""
        return {
            "mode": self._state.mode,
            "presence_active": self._state.presence_active,
            "tag_scanned": self._state.tag_scanned,
            "visual_status": self._state.visual_status,
            "human_decision": self._state.human_decision,
            "workflow_phase": self._state.workflow_phase,
            "encounter_count": self._state.encounter_count,
            "last_event": self._state.last_event,
        }

    # ─── Helpers ─────────────────────────────────────────────────────────
    async def _hold_result(self) -> None:
        """Hold final state visible for 3s so the dashboard catches it."""
        await workflow.sleep(3)

    # ─── Main Run ────────────────────────────────────────────────────────
    @workflow.run
    async def run(self) -> str:
        while self._state.encounter_count < MAX_ENCOUNTERS:
            self._state.workflow_phase = "MONITORING"
            # Clear per-encounter state BEFORE waiting for new signals
            self._state.tag_scanned = ""
            self._state.visual_status = ""
            self._state.human_decision = ""

            # Wait for presence OR check if it's already set from a signal
            # that arrived during the previous hold period
            if not self._state.presence_active:
                await workflow.wait_condition(
                    lambda: self._state.presence_active
                    or self._state.human_decision != ""
                )

            if self._state.mode == "DOMESTIC":
                await self._handle_domestic()
            else:
                await self._handle_tnr()

            # Hold result for dashboard visibility, then reset presence
            await self._hold_result()
            self._state.encounter_count += 1
            self._state.presence_active = False

        workflow.continue_as_new()

    # ─── DOMESTIC MODE ───────────────────────────────────────────────────
    async def _handle_domestic(self) -> None:
        """
        Domestic mode: gate is normally LOCKED (0°).
        Opens only for authorized RFID + vision says clean (no prey).
        If no RFID arrives, rejects immediately once vision arrives (or after timeout).
        """
        # Wait for RFID scan OR vision result (whichever comes first)
        try:
            await workflow.wait_condition(
                lambda: self._state.tag_scanned != "" or self._state.visual_status != "",
                timeout=timedelta(seconds=5),
            )
        except TimeoutError:
            pass

        # No RFID or unauthorized tag → stays locked, reject
        if self._state.tag_scanned not in AUTHORIZED_TAGS:
            self._state.workflow_phase = "LOCKED"
            self._state.last_event = "Unknown cat rejected — gate remains locked"
            try:
                await workflow.execute_activity(
                    pico_lock_gate,
                    PicoCommand(command="LOCK_CAPTURE", description="Foreign cat blocked"),
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    retry_policy=ACTIVITY_RETRY,
                )
            except Exception as e:
                self._state.last_event = f"Unknown cat rejected (Pico: {type(e).__name__})"
            return

        # Authorized tag found — wait briefly for vision, but RFID alone is sufficient
        self._state.last_event = f"RFID verified: {self._state.tag_scanned}"

        if not self._state.visual_status:
            try:
                await workflow.wait_condition(
                    lambda: self._state.visual_status != "",
                    timeout=timedelta(seconds=3),
                )
            except TimeoutError:
                pass  # No vision yet — proceed with RFID-only auth

        # If carrying prey → block entry
        if self._state.visual_status == "prey":
            self._state.workflow_phase = "LOCKED"
            self._state.last_event = "Prey detected — entry denied to protect home"
            try:
                await workflow.execute_activity(
                    pico_lock_gate,
                    PicoCommand(command="LOCK_CAPTURE", description="Prey blocked at door"),
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    retry_policy=ACTIVITY_RETRY,
                )
            except Exception as e:
                self._state.last_event = f"Prey detected — entry denied (Pico: {type(e).__name__})"
            return

        # Authorized + clean (or no prey detected) → open gate
        self._state.workflow_phase = "RELEASED"
        self._state.last_event = "Resident cat verified — gate opened"
        try:
            await workflow.execute_activity(
                pico_unlock_gate,
                PicoCommand(command="ACCESS_APPROVED", description="Authorized resident"),
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=ACTIVITY_RETRY,
            )
        except Exception:
            pass

    # ─── TNR MODE ────────────────────────────────────────────────────────
    async def _handle_tnr(self) -> None:
        """
        TNR mode: gate is normally OPEN (90°).
        Locks only when intact stray detected for capture.
        Ear-tipped / known cats pass through freely.
        """
        # Wait for RFID or vision classification
        try:
            await workflow.wait_condition(
                lambda: self._state.tag_scanned != "" or self._state.visual_status != "",
                timeout=timedelta(seconds=10),
            )
        except TimeoutError:
            # No identification — default to open (TNR mode is welcoming)
            self._state.workflow_phase = "RELEASED"
            self._state.last_event = "Unidentified visitor — gate stays open"
            return

        # Known RFID tag → let pass, log visit
        if self._state.tag_scanned in AUTHORIZED_TAGS:
            self._state.workflow_phase = "RELEASED"
            self._state.last_event = f"Known cat logged: {self._state.tag_scanned}"
            return

        # Ear-tipped (already neutered) or clean → let pass freely
        if self._state.visual_status in ("ear_tipped", "clean"):
            self._state.workflow_phase = "RELEASED"
            self._state.last_event = (
                "Ear-tipped cat — already neutered, gate stays open"
                if self._state.visual_status == "ear_tipped"
                else "Clean cat — gate stays open"
            )
            return

        # Intact stray or prey carrier → LOCK for TNR capture
        self._state.workflow_phase = "LOCKED"
        lock_reason = (
            "Intact stray detected — gate locked for TNR"
            if self._state.visual_status == "intact_ear"
            else "Prey carrier locked for TNR"
            if self._state.visual_status == "prey"
            else "Unidentified stray — gate locked for TNR"
        )
        self._state.last_event = lock_reason

        try:
            await workflow.execute_activity(
                pico_lock_gate,
                PicoCommand(command="LOCK_CAPTURE", description=lock_reason),
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=ACTIVITY_RETRY,
            )
        except Exception as e:
            # Activity failed but we keep LOCKED state — Pico may be offline
            self._state.last_event = f"{lock_reason} (Pico: {type(e).__name__})"

        # Await volunteer decision with safety timeout
        try:
            await workflow.wait_condition(
                lambda: self._state.human_decision != "",
                timeout=VOLUNTEER_TIMEOUT,
            )
        except TimeoutError:
            # SAGA ROLLBACK: auto-release after 4 hours
            self._state.workflow_phase = "RELEASED"
            self._state.last_event = "Saga rollback — volunteer timeout, gate released"
            try:
                await workflow.execute_activity(
                    pico_safe_release,
                    PicoCommand(
                        command="SAFE_RELEASE",
                        description="Saga compensation: 4h timeout",
                    ),
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    retry_policy=ACTIVITY_RETRY,
                )
            except Exception:
                pass
            return

        # Process volunteer decision
        if self._state.human_decision == "SAFE_RELEASE":
            self._state.workflow_phase = "RELEASED"
            self._state.last_event = "Volunteer released cat safely"
            try:
                await workflow.execute_activity(
                    pico_safe_release,
                    PicoCommand(command="SAFE_RELEASE", description="Volunteer release"),
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    retry_policy=ACTIVITY_RETRY,
                )
            except Exception:
                pass
        else:
            self._state.workflow_phase = "LOCKED"
            self._state.last_event = "Volunteer approved capture — awaiting TNR pickup"
