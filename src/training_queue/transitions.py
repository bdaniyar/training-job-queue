"""The only application write path. Locks, guards, and effects live together here."""

import asyncio
import random
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import TypeVar
from uuid import UUID, uuid4

from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeout
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from training_queue.config import Settings
from training_queue.models import Job, JobEffect
from training_queue.schemas import Cursor, Payload

T = TypeVar("T")
TERMINAL = {"succeeded", "failed", "cancelled"}


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


class QueueUnavailable(Exception):
    """Outcome may be uncertain. Reconcile via key/ID before attempting more work."""


def sqlstate(exc: DBAPIError) -> str | None:
    return getattr(exc.orig, "sqlstate", None)


class Queue:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], settings: Settings):
        self.sessions = sessions
        self.settings = settings

    async def _transaction(self, operation: Callable[[AsyncSession], Awaitable[T]]) -> T:
        # Retry only errors for which PostgreSQL guarantees transaction abort.
        for attempt in range(3):
            try:
                # Keep session cleanup OUTSIDE transaction exit: an exception
                # raised during COMMIT must still return/invalidate its connection.
                async with self.sessions() as session:
                    async with session.begin():
                        value = await operation(session)
                return value  # context exit COMMITTED before returning to caller
            except DBAPIError as exc:
                if sqlstate(exc) in {"40001", "40P01"} and attempt < 2:
                    await asyncio.sleep(random.uniform(0.01, 0.05) * (attempt + 1))
                    continue
                if sqlstate(exc) and sqlstate(exc).startswith("23"):
                    raise  # Integrity violations are bugs, not successful replays.
                raise QueueUnavailable("database operation unavailable; reconcile outcome") from exc
            except (TimeoutError, PoolTimeout, OSError) as exc:
                raise QueueUnavailable("database operation unavailable; reconcile outcome") from exc
        raise AssertionError("unreachable")

    @staticmethod
    async def _clock(session: AsyncSession) -> datetime:
        return await session.scalar(select(func.clock_timestamp()))

    @staticmethod
    async def _lock(session: AsyncSession, job_id: UUID) -> Job:
        job = await session.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if job is None:
            raise NotFound("job not found")
        return job

    @staticmethod
    def _owns(job: Job, owner: UUID, generation: int, now: datetime) -> bool:
        return (
            job.state == "running"
            and job.owner == owner
            and job.generation == generation
            and job.lease_until > now
            and job.attempt_deadline > now
        )

    @staticmethod
    def _release(job: Job, state: str, now: datetime) -> None:
        job.state = state
        job.owner = job.lease_until = job.attempt_deadline = None
        job.updated_at = now
        job.finished_at = now if state in TERMINAL else None

    @classmethod
    def _retry_or_fail(cls, job: Job, now: datetime, reason: str, permanent: bool = False):
        job.error = reason
        if permanent or job.attempts >= 5:
            cls._release(job, "failed", now)
        else:
            cls._release(job, "queued", now)
            job.available_at = now + timedelta(seconds=min(2 ** (job.attempts - 1), 30))

    async def create(self, key: str, payload: Payload) -> tuple[Job, bool]:
        if not key.strip() or len(key) > 200:
            raise ValueError("idempotency key must contain 1..200 nonblank characters")
        canonical = Payload.model_validate(payload).model_dump(mode="json")

        async def operation(session):
            job = await session.scalar(
                insert(Job)
                .values(id=uuid4(), idempotency_key=key, payload=canonical)
                .on_conflict_do_nothing(index_elements=[Job.idempotency_key])
                .returning(Job)
            )
            if job is not None:
                return job, True
            # A conflicting INSERT can see a winner absent from its own snapshot.
            # READ COMMITTED gives this NEXT statement a fresh snapshot.
            job = await session.scalar(select(Job).where(Job.idempotency_key == key))
            if job is None:
                raise QueueUnavailable("idempotency winner missing; retry same key")
            if job.payload != canonical:
                raise Conflict("idempotency key already used with a different payload")
            return job, False

        return await self._transaction(operation)

    async def get(self, job_id: UUID) -> Job:
        async def operation(session):
            job = await session.get(Job, job_id)
            if job is None:
                raise NotFound("job not found")
            return job

        return await self._transaction(operation)

    async def list_jobs(
        self, limit: int, cursor: Cursor | None = None
    ) -> tuple[list[Job], str | None]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be 1..100")

        async def operation(session):
            query = select(Job).order_by(Job.created_at, Job.id).limit(limit + 1)
            if cursor:
                query = query.where(
                    tuple_(Job.created_at, Job.id) > tuple_(cursor.created_at, cursor.id)
                )
            rows = list((await session.scalars(query)).all())
            more = len(rows) > limit
            rows = rows[:limit]
            next_cursor = (
                Cursor(created_at=rows[-1].created_at, id=rows[-1].id).encode() if more else None
            )
            return rows, next_cursor

        return await self._transaction(operation)

    async def claim(self, owner: UUID) -> Job | None:
        async def operation(session):
            job = await session.scalar(
                select(Job)
                .where(
                    Job.state == "queued",
                    Job.attempts < 5,
                    Job.available_at <= func.clock_timestamp(),
                )
                .order_by(Job.available_at, Job.created_at, Job.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if job is None:
                return None
            now = await self._clock(session)  # AFTER acquiring the row lock
            if job.state != "queued" or job.attempts >= 5 or job.available_at > now:
                return None
            job.attempts += 1
            job.generation += 1
            job.state, job.owner, job.updated_at = "running", owner, now
            job.attempt_deadline = now + timedelta(seconds=self.settings.attempt_seconds)
            job.lease_until = min(
                now + timedelta(seconds=self.settings.lease_seconds), job.attempt_deadline
            )
            job.error = None
            return job

        return await self._transaction(operation)

    async def heartbeat(self, job_id: UUID, owner: UUID, generation: int) -> bool:
        async def operation(session):
            job = await self._lock(session, job_id)
            now = await self._clock(session)
            if not self._owns(job, owner, generation, now):
                return False
            job.lease_until = min(
                now + timedelta(seconds=self.settings.lease_seconds), job.attempt_deadline
            )
            job.updated_at = now
            return True

        return await self._transaction(operation)

    async def complete(self, job_id: UUID, owner: UUID, generation: int, result: dict) -> bool:
        async def operation(session):
            job = await self._lock(session, job_id)
            now = await self._clock(session)
            if not self._owns(job, owner, generation, now):
                return False
            session.add(JobEffect(job_id=job.id, generation=generation, result=result))
            self._release(job, "succeeded", now)
            job.result, job.error = result, None
            # Flush errors propagate; neither write survives a failed commit.
            await session.flush()
            return True

        return await self._transaction(operation)

    async def fail(
        self, job_id: UUID, owner: UUID, generation: int, reason: str, *, permanent: bool = False
    ) -> bool:
        async def operation(session):
            job = await self._lock(session, job_id)
            now = await self._clock(session)
            if not self._owns(job, owner, generation, now):
                return False
            self._retry_or_fail(job, now, reason, permanent)
            return True

        return await self._transaction(operation)

    async def recover(self) -> list[tuple[UUID, str, int]]:
        async def operation(session):
            rows = (
                await session.scalars(
                    select(Job)
                    .where(Job.state == "running", Job.lease_until <= func.clock_timestamp())
                    .order_by(Job.lease_until, Job.id)
                    .limit(self.settings.recovery_batch)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            now = await self._clock(session)
            recovered = []
            for job in rows:
                if job.state == "running" and job.lease_until <= now:
                    self._retry_or_fail(job, now, "lease expired")
                    recovered.append((job.id, job.state, job.generation))
            return recovered

        return await self._transaction(operation)

    async def cancel(self, job_id: UUID) -> Job:
        async def operation(session):
            job = await self._lock(session, job_id)
            now = await self._clock(session)
            if job.state == "cancelled":
                return job
            if job.state in TERMINAL:
                raise Conflict(f"cannot cancel a {job.state} job")
            self._release(job, "cancelled", now)
            return job

        return await self._transaction(operation)
