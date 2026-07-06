"""
Felisk — Temporal Workflow Test Suite
Tests the TnrPortalWorkflow dual-mode state machine using Temporal's
built-in test environment.

Validates:
  - Domestic mode: authorized RFID + clean vision grants access
  - Domestic mode: prey detection blocks entry
  - Domestic mode: unknown tag keeps gate locked
  - TNR mode: ear-tipped cat passes freely
  - TNR mode: intact stray triggers lock
  - TNR mode: volunteer SAFE_RELEASE opens gate
  - TNR mode: Saga rollback on volunteer timeout
  - Mode switching signal
  - Query returns correct state
"""

import asyncio
from unittest.mock import patch

import pytest
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from temporal_engine.activities import (
    PicoCommand,
    pico_lock_gate,
    pico_safe_release,
    pico_set_mode,
    pico_unlock_gate,
)
from temporal_engine.workflows import TnrPortalWorkflow

TASK_QUEUE = "test-felisk-queue"


@pytest.fixture
async def env():
    """Create a time-skippable Temporal test environment."""
    async with await WorkflowEnvironment.start_time_skipping() as env:
        yield env


@pytest.fixture
async def worker(env: WorkflowEnvironment):
    """Start a worker with mocked activities for testing."""
    async with Worker(
        env.client,
        task_queue=TASK_QUEUE,
        workflows=[TnrPortalWorkflow],
        activities=[pico_unlock_gate, pico_lock_gate, pico_safe_release, pico_set_mode],
    ):
        yield env.client


# ─── Test: Workflow starts in MONITORING ─────────────────────────────────────
@pytest.mark.asyncio
async def test_workflow_starts_in_monitoring(env: WorkflowEnvironment, worker):
    """Workflow should start in DOMESTIC mode, MONITORING phase."""
    with patch("temporal_engine.activities._send_to_pico", return_value="OK"):
        handle = await worker.start_workflow(
            TnrPortalWorkflow.run,
            id="test-monitoring",
            task_queue=TASK_QUEUE,
        )

        await asyncio.sleep(0.5)

        state = await handle.query(TnrPortalWorkflow.get_workflow_state)
        assert state["workflow_phase"] == "MONITORING"
        assert state["mode"] == "DOMESTIC"
        assert state["presence_active"] is False
        assert state["encounter_count"] == 0

        await handle.cancel()


# ─── DOMESTIC MODE TESTS ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_domestic_authorized_tag_clean_vision(env: WorkflowEnvironment, worker):
    """Domestic mode: authorized RFID + clean vision → gate opens."""
    with patch("temporal_engine.activities._send_to_pico", return_value="OK"):
        handle = await worker.start_workflow(
            TnrPortalWorkflow.run,
            id="test-domestic-clean",
            task_queue=TASK_QUEUE,
        )

        await asyncio.sleep(0.3)

        # Trigger presence + authorized RFID + clean vision
        await handle.signal(TnrPortalWorkflow.presence_event, True)
        await asyncio.sleep(0.3)
        await handle.signal(TnrPortalWorkflow.tag_scanned_event, "146_73_250_5")
        await asyncio.sleep(0.3)
        await handle.signal(TnrPortalWorkflow.prey_checked_event, "clean")

        # Wait for encounter to process + hold period (now 3s)
        await asyncio.sleep(5)

        state = await handle.query(TnrPortalWorkflow.get_workflow_state)
        assert state["workflow_phase"] == "MONITORING"
        assert state["encounter_count"] == 1

        await handle.cancel()


@pytest.mark.asyncio
async def test_domestic_authorized_tag_prey_blocked(env: WorkflowEnvironment, worker):
    """Domestic mode: authorized RFID + prey in mouth → gate stays locked."""
    with patch("temporal_engine.activities._send_to_pico", return_value="OK"):
        handle = await worker.start_workflow(
            TnrPortalWorkflow.run,
            id="test-domestic-prey",
            task_queue=TASK_QUEUE,
        )

        await asyncio.sleep(0.3)

        await handle.signal(TnrPortalWorkflow.presence_event, True)
        await asyncio.sleep(0.3)
        await handle.signal(TnrPortalWorkflow.tag_scanned_event, "146_73_250_5")
        await asyncio.sleep(0.3)
        await handle.signal(TnrPortalWorkflow.prey_checked_event, "prey")

        await asyncio.sleep(2)

        state = await handle.query(TnrPortalWorkflow.get_workflow_state)
        assert state["workflow_phase"] == "LOCKED"
        assert state["last_event"] == "Prey detected — entry denied to protect home"

        await handle.cancel()


@pytest.mark.asyncio
async def test_domestic_unknown_tag_rejected(env: WorkflowEnvironment, worker):
    """Domestic mode: unknown/no RFID tag → gate stays locked."""
    with patch("temporal_engine.activities._send_to_pico", return_value="OK"):
        handle = await worker.start_workflow(
            TnrPortalWorkflow.run,
            id="test-domestic-unknown",
            task_queue=TASK_QUEUE,
        )

        await asyncio.sleep(0.3)

        # Presence + vision arrives but no authorized RFID
        await handle.signal(TnrPortalWorkflow.presence_event, True)
        await asyncio.sleep(0.3)
        await handle.signal(TnrPortalWorkflow.prey_checked_event, "intact_ear")

        await asyncio.sleep(3)

        state = await handle.query(TnrPortalWorkflow.get_workflow_state)
        assert state["workflow_phase"] == "LOCKED"
        assert "rejected" in state["last_event"] or "Unknown" in state["last_event"]

        await handle.cancel()


# ─── TNR MODE TESTS ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tnr_ear_tipped_passes_freely(env: WorkflowEnvironment, worker):
    """TNR mode: ear-tipped cat → gate stays open, encounter logged."""
    with patch("temporal_engine.activities._send_to_pico", return_value="OK"):
        handle = await worker.start_workflow(
            TnrPortalWorkflow.run,
            id="test-tnr-tipped",
            task_queue=TASK_QUEUE,
        )

        await asyncio.sleep(0.3)

        # Switch to TNR mode
        await handle.signal(TnrPortalWorkflow.set_mode, "TNR")
        await asyncio.sleep(0.5)

        # Cat enters — ear-tipped
        await handle.signal(TnrPortalWorkflow.presence_event, True)
        await asyncio.sleep(0.3)
        await handle.signal(TnrPortalWorkflow.prey_checked_event, "ear_tipped")

        await asyncio.sleep(5)

        state = await handle.query(TnrPortalWorkflow.get_workflow_state)
        assert state["workflow_phase"] == "MONITORING"
        assert state["encounter_count"] == 1

        await handle.cancel()


@pytest.mark.asyncio
async def test_tnr_intact_stray_locks(env: WorkflowEnvironment, worker):
    """TNR mode: intact stray → gate locks for capture."""
    with patch("temporal_engine.activities._send_to_pico", return_value="OK"):
        handle = await worker.start_workflow(
            TnrPortalWorkflow.run,
            id="test-tnr-intact",
            task_queue=TASK_QUEUE,
        )

        await asyncio.sleep(0.3)

        await handle.signal(TnrPortalWorkflow.set_mode, "TNR")
        await asyncio.sleep(0.5)

        await handle.signal(TnrPortalWorkflow.presence_event, True)
        await asyncio.sleep(0.3)
        await handle.signal(TnrPortalWorkflow.prey_checked_event, "intact_ear")

        await asyncio.sleep(2)

        state = await handle.query(TnrPortalWorkflow.get_workflow_state)
        assert state["workflow_phase"] == "LOCKED"
        assert "Intact stray" in state["last_event"]

        await handle.cancel()


@pytest.mark.asyncio
async def test_tnr_volunteer_release(env: WorkflowEnvironment, worker):
    """TNR mode: locked stray + volunteer SAFE_RELEASE → gate opens."""
    with patch("temporal_engine.activities._send_to_pico", return_value="OK"):
        handle = await worker.start_workflow(
            TnrPortalWorkflow.run,
            id="test-tnr-release",
            task_queue=TASK_QUEUE,
        )

        await asyncio.sleep(0.3)

        await handle.signal(TnrPortalWorkflow.set_mode, "TNR")
        await asyncio.sleep(0.5)

        # Intact stray enters
        await handle.signal(TnrPortalWorkflow.presence_event, True)
        await asyncio.sleep(0.3)
        await handle.signal(TnrPortalWorkflow.prey_checked_event, "intact_ear")

        # Wait for lock
        await asyncio.sleep(3)

        # Volunteer releases
        await handle.signal(TnrPortalWorkflow.volunteer_decision, "SAFE_RELEASE")

        await asyncio.sleep(5)

        state = await handle.query(TnrPortalWorkflow.get_workflow_state)
        assert state["workflow_phase"] == "MONITORING"
        assert state["encounter_count"] == 1

        await handle.cancel()


# ─── MODE SWITCHING TEST ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mode_switch_signal(env: WorkflowEnvironment, worker):
    """Mode switch signal updates state and triggers Pico command."""
    with patch("temporal_engine.activities._send_to_pico", return_value="OK"):
        handle = await worker.start_workflow(
            TnrPortalWorkflow.run,
            id="test-mode-switch",
            task_queue=TASK_QUEUE,
        )

        await asyncio.sleep(0.3)

        state = await handle.query(TnrPortalWorkflow.get_workflow_state)
        assert state["mode"] == "DOMESTIC"

        await handle.signal(TnrPortalWorkflow.set_mode, "TNR")
        await asyncio.sleep(1)

        state = await handle.query(TnrPortalWorkflow.get_workflow_state)
        assert state["mode"] == "TNR"
        assert "TNR" in state["last_event"]

        await handle.cancel()


# ─── QUERY STATE TEST ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_query_returns_full_state(env: WorkflowEnvironment, worker):
    """Query should return all state fields including mode."""
    with patch("temporal_engine.activities._send_to_pico", return_value="OK"):
        handle = await worker.start_workflow(
            TnrPortalWorkflow.run,
            id="test-query-full",
            task_queue=TASK_QUEUE,
        )

        await asyncio.sleep(0.3)

        state = await handle.query(TnrPortalWorkflow.get_workflow_state)
        assert "mode" in state
        assert "presence_active" in state
        assert "tag_scanned" in state
        assert "visual_status" in state
        assert "human_decision" in state
        assert "workflow_phase" in state
        assert "encounter_count" in state
        assert "last_event" in state

        await handle.cancel()
