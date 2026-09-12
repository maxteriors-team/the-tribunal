"""Rehearsal execution inside the single backend-api process, not a separate queue."""

import asyncio
import uuid

from app.db.session import system_session
from app.services.ai.roleplay.execution import claim_runs, execute_step, recover_stale_runs
from app.workers.base import BaseWorker, WorkerRegistry


class RoleplayWorker(BaseWorker):
    POLL_INTERVAL_SECONDS = 2
    COMPONENT_NAME = "roleplay_worker"
    MAX_CONCURRENCY = 3

    async def _process_items(self) -> None:
        async with system_session("roleplay worker recovers and claims rehearsal steps") as db:
            await recover_stale_runs(db)
            slots = self._max_concurrency - len(self._inflight)
            if slots <= 0:
                return
            claims = await claim_runs(db, slots)
        # Keep polling/heartbeats responsive while paid calls take >30 seconds.
        # BaseWorker.stop drains these bounded tasks, then cancels remaining work.
        for run_id, token in claims:
            task = asyncio.create_task(self._execute(run_id, token))
            self._inflight.add(task)
            task.add_done_callback(self._inflight.discard)

    async def _execute(self, run_id: uuid.UUID, token: uuid.UUID) -> None:
        try:
            async with system_session("roleplay worker executes a claimed rehearsal step") as db:
                await execute_step(db, run_id, token)
            self.record_items_processed()
        except Exception as exc:
            # Database outages leave the durable claim for stale recovery.
            self.logger.warning(
                "rehearsal_worker_failed", run_id=str(run_id), error_type=type(exc).__name__
            )


registry = WorkerRegistry(RoleplayWorker)
