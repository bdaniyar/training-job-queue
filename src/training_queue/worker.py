"""One worker process, one active job, separately sessioned heartbeats."""

import asyncio
import json
import signal
from datetime import UTC, datetime
from uuid import UUID, uuid4

from training_queue.config import Settings
from training_queue.db import make_database
from training_queue.execution import SimulationError, execute
from training_queue.models import Job
from training_queue.schemas import Payload
from training_queue.transitions import Queue, QueueUnavailable


def log(event: str, owner: UUID, job: Job | None = None, **details):
    record = {"time": datetime.now(UTC).isoformat(), "event": event, "owner": str(owner)}
    if job:
        record.update(job_id=str(job.id), generation=job.generation, attempt=job.attempts)
    print(json.dumps(record | details, default=str), flush=True)


class Worker:
    def __init__(self, queue: Queue, owner: UUID | None = None):
        self.queue = queue
        self.owner = owner or uuid4()

    async def _heartbeat(self, job: Job):
        while True:
            await asyncio.sleep(self.queue.settings.heartbeat_seconds)
            if not await self.queue.heartbeat(job.id, self.owner, job.generation):
                return

    async def process(self, job: Job, stop: asyncio.Event):
        log("execution_started", self.owner, job)
        execution = asyncio.create_task(execute(Payload.model_validate(job.payload), job.attempts))
        heartbeat = asyncio.create_task(self._heartbeat(job))
        shutdown = asyncio.create_task(stop.wait())
        tasks = {execution, heartbeat, shutdown}
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            # Cancel the unused tasks and finish their DB cleanup before transitioning.
            for task in tasks - done:
                task.cancel()
            await asyncio.gather(*(tasks - done), return_exceptions=True)
            if shutdown in done:
                released = await self.queue.fail(
                    job.id, self.owner, job.generation, "graceful worker shutdown"
                )
                log("shutdown_released" if released else "ownership_lost", self.owner, job)
            elif heartbeat in done:
                heartbeat.result()  # DB failures propagate; never call them success.
                log("ownership_lost", self.owner, job)
            else:
                try:
                    result = execution.result()
                except SimulationError as exc:
                    accepted = await self.queue.fail(
                        job.id, self.owner, job.generation, str(exc), permanent=exc.permanent
                    )
                    log("failure_recorded" if accepted else "ownership_lost", self.owner, job)
                else:
                    log("execution_finished", self.owner, job)
                    committed = await self.queue.complete(
                        job.id, self.owner, job.generation, result
                    )
                    log("effect_committed" if committed else "ownership_lost", self.owner, job)
        except QueueUnavailable:
            # No blind write replay. A read may reconcile completion, but an
            # uncertain claim is never executed; its lease is recovered instead.
            log("database_outcome_uncertain", self.owner, job)
            try:
                current = await self.queue.get(job.id)
                log(
                    "reconciled",
                    self.owner,
                    job,
                    state=current.state,
                    current_generation=current.generation,
                )
            except QueueUnavailable:
                log("reconciliation_unavailable", self.owner, job)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def run(self, stop: asyncio.Event):
        log("worker_started", self.owner)
        while not stop.is_set():
            try:
                for job_id, state, generation in await self.queue.recover():
                    log(
                        "recovered",
                        self.owner,
                        job_id=str(job_id),
                        state=state,
                        generation=generation,
                    )
                if stop.is_set():
                    break
                job = await self.queue.claim(self.owner)
                if job is not None:
                    log("claim_committed", self.owner, job)
                    await self.process(job, stop)
                    continue
            except QueueUnavailable:
                # Unknown claim COMMIT may have succeeded. Do not execute or
                # repeat that claim by ID; recovery will account for it.
                log("database_outcome_uncertain", self.owner)
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.queue.settings.poll_seconds)
            except TimeoutError:
                pass
        log("worker_stopped", self.owner)


async def main():
    settings = Settings()
    engine, sessions = make_database(settings.database_url)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    try:
        await Worker(Queue(sessions, settings)).run(stop)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
