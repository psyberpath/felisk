"""
Felisk — Temporal Worker
Connects to the local Temporal server and registers the
TnrPortalWorkflow and all Pico W activities on 'felisk-task-queue'.
"""

import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from temporal_engine.activities import (
    pico_lock_gate,
    pico_safe_release,
    pico_unlock_gate,
)
from temporal_engine.workflows import TnrPortalWorkflow

TASK_QUEUE = "felisk-task-queue"
TEMPORAL_ADDRESS = "localhost:7233"


async def main() -> None:
    """Start the Temporal worker."""
    client = await Client.connect(TEMPORAL_ADDRESS)

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[TnrPortalWorkflow],
        activities=[pico_unlock_gate, pico_lock_gate, pico_safe_release],
    )

    print(f"[WORKER] Felisk Temporal worker started on queue '{TASK_QUEUE}'")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
