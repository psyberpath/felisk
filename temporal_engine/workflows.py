"""
Felisk — Temporal Workflow: TnrPortalWorkflow
Long-running durable workflow managing the TNR portal state machine.
Loops continuously, processing one animal encounter per cycle.
Uses signals for event ingestion, queries for state inspection,
and the Saga pattern for safe rollback on timeout or fault.
"""

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from temporal_engine.activities import (
        PicoCommand,
        pico_lock_gate,
        pico_safe_release,
        pico_unlock_gate,
    )


# ─── Constants ───────────────────────────────────────────────────────────────
TASK_QUEUE = "felisk-task-queue"
VOLUNTEER_TIMEOUT = timedelta(hours=4)
ACTIVITY_TIMEOUT = timedelta(seconds=10)
ACTIVITY_RETRY = RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=1))

# Max encounters before continue-as-new (prevents unbounded history growth)
MAX_ENCOUNTERS = 50

# Authorized RFID tags (matching felisk.py firmware authorized_felines list)
AUTHORIZED_TAGS: set[str] = {"A1B2C3D4", "DEADBEEF", "CAFEBABE", "146_73_250_5"}


# ─── State Container ─────────────────────────────────────────────────────────
@dataclass
class PortalState:
    presence_active: bool = False
    tag_scanned: str = ""
    visual_status: str = ""  # "clean", "prey", "intact_ear", "ear_tipped"
    human_decision: str = ""  # "APPROVE_CAPTURE", "SAFE_RELEASE"
    workflow_phase: str = "IDLE"  # IDLE, MONITORING, LOCKED, RELEASED
    encounter_count: int = 0


# ─── Workflow Definition ─────────────────────────────────────────────────────
@workflow.defn
class TnrPortalWorkflow:
    """
    Long-running Felisk TNR Portal workflow.
    Loops continuously — always alive to accept signals from sensors,
    the vision node, and the operator dashboard.
    Uses continue_as_new after MAX_ENCOUNTERS to prevent history overflow.
    """

    def __init__(self) -> None:
        self._state = PortalState()

    # ─── Signals ─────────────────────────────────────────────────────────
    @workflow.signal
    async def presence_event(self, detected: bool) -> None:
        """HC-SR04 presence detection signal from Pico W."""
        if isinstance(detected, str):
            self._state.presence_active = detected.lower() in ("true", "1", "yes")
        else:
            self._state.presence_active = bool(detected)

    @workflow.signal
    async def tag_scanned_event(self, tag_uid: str) -> None:
        """RFID tag scan result from Pico W."""
        self._state.tag_scanned = tag_uid

    @workflow.signal
    async def prey_checked_event(self, visual_status: str) -> None:
        """YOLOv8 classification result from the vision node."""
        self._state.visual_status = visual_status

    @workflow.signal
    async def volunteer_decision(self, decision: str) -> None:
        """TNR volunteer decision from web dashboard."""
        self._state.human_decision = decision

    # ─── Queries ─────────────────────────────────────────────────────────
    @workflow.query
    def get_workflow_state(self) -> dict:
        """Return current workflow state for dashboard polling."""
        return {
            "presence_active": self._state.presence_active,
            "tag_scanned": self._state.tag_scanned,
            "visual_status": self._state.visual_status,
            "human_decision": self._state.human_decision,
            "workflow_phase": self._state.workflow_phase,
            "encounter_count": self._state.encounter_count,
        }

    # ─── Reset state between encounters ──────────────────────────────────
    def _reset_encounter(self) -> None:
        """Clear per-encounter state, keeping the workflow alive."""
        self._state.presence_active = False
        self._state.tag_scanned = ""
        self._state.visual_status = ""
        self._state.human_decision = ""
        self._state.workflow_phase = "MONITORING"

    async def _hold_result(self) -> None:
        """Hold final state visible for 5s so the dashboard catches it."""
        await workflow.sleep(5)

    # ─── Main Run Logic ──────────────────────────────────────────────────
    @workflow.run
    async def run(self) -> str:
        """
        Long-running workflow loop:
        Each cycle handles one animal encounter, then resets for the next.
        After MAX_ENCOUNTERS, uses continue_as_new to stay healthy.
        """
        while self._state.encounter_count < MAX_ENCOUNTERS:
            self._state.workflow_phase = "MONITORING"

            # Wait until presence is detected or a volunteer override arrives
            await workflow.wait_condition(
                lambda: self._state.presence_active or self._state.human_decision != ""
            )

            # ── Handle this encounter ────────────────────────────────────
            await self._handle_encounter()

            # ── Hold result visible, then reset for next animal ──────────
            await self._hold_result()
            self._state.encounter_count += 1
            self._reset_encounter()

        # After MAX_ENCOUNTERS, continue-as-new to prevent history overflow
        workflow.continue_as_new()

    async def _handle_encounter(self) -> None:
        """Process a single animal encounter through the full pipeline."""

        # ── Wait briefly for RFID tag scan ───────────────────────────────
        try:
            await workflow.wait_condition(
                lambda: self._state.tag_scanned != "",
                timeout=timedelta(seconds=5),
            )
        except TimeoutError:
            pass

        # ── Authorized tag → unlock gate ─────────────────────────────────
        if self._state.tag_scanned in AUTHORIZED_TAGS:
            self._state.workflow_phase = "RELEASED"
            try:
                await workflow.execute_activity(
                    pico_unlock_gate,
                    PicoCommand(command="ACCESS_APPROVED", description="Authorized RFID tag"),
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    retry_policy=ACTIVITY_RETRY,
                )
            except Exception:
                pass
            return

        # ── No RFID match — wait for vision classification ───────────────
        try:
            await workflow.wait_condition(
                lambda: self._state.visual_status != "",
                timeout=timedelta(seconds=10),
            )
        except TimeoutError:
            # No vision result — lock for safety
            pass

        # ── Vision says clean or ear-tipped → safe to release ────────────
        if self._state.visual_status in ("clean", "ear_tipped"):
            self._state.workflow_phase = "RELEASED"
            try:
                await workflow.execute_activity(
                    pico_unlock_gate,
                    PicoCommand(
                        command="ACCESS_APPROVED",
                        description=f"Vision verified: {self._state.visual_status}",
                    ),
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    retry_policy=ACTIVITY_RETRY,
                )
            except Exception:
                pass
            return

        # ── Prey detected or intact stray → lock gate for TNR ────────────
        self._state.workflow_phase = "LOCKED"
        try:
            await workflow.execute_activity(
                pico_lock_gate,
                PicoCommand(
                    command="LOCK_CAPTURE",
                    description=f"TNR lock: {self._state.visual_status or 'unidentified'}",
                ),
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=ACTIVITY_RETRY,
            )
        except Exception:
            self._state.workflow_phase = "RELEASED"
            return

        # ── Await volunteer decision with 4-hour safety timeout ──────────
        try:
            await workflow.wait_condition(
                lambda: self._state.human_decision != "",
                timeout=VOLUNTEER_TIMEOUT,
            )
        except TimeoutError:
            # ── SAGA ROLLBACK: Timeout → safe release ────────────────────
            self._state.workflow_phase = "RELEASED"
            try:
                await workflow.execute_activity(
                    pico_safe_release,
                    PicoCommand(
                        command="SAFE_RELEASE",
                        description="Saga rollback: volunteer timeout (4h)",
                    ),
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    retry_policy=ACTIVITY_RETRY,
                )
            except Exception:
                pass
            return

        # ── Process volunteer decision ───────────────────────────────────
        if self._state.human_decision == "APPROVE_CAPTURE":
            self._state.workflow_phase = "LOCKED"
        else:
            self._state.workflow_phase = "RELEASED"
            try:
                await workflow.execute_activity(
                    pico_safe_release,
                    PicoCommand(
                        command="SAFE_RELEASE",
                        description=f"Volunteer: {self._state.human_decision}",
                    ),
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    retry_policy=ACTIVITY_RETRY,
                )
            except Exception:
                pass
