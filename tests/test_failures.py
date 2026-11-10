import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import DBAPIError

from training_queue.models import Job, JobEffect
from training_queue.schemas import Payload
from training_queue.transitions import QueueUnavailable


async def test_ambiguous_create_commit_reconciles_by_key(queue):
    session_class = queue.sessions.class_.sync_session_class

    def lost_ack(session):
        raise OSError("injected lost acknowledgement AFTER actual PostgreSQL commit")

    event.listen(session_class, "after_commit", lost_ack, once=True)
    try:
        with pytest.raises(QueueUnavailable):
            await queue.create("uncertain-create", Payload())
    finally:
        event.remove(session_class, "after_commit", lost_ack)
    job, created = await queue.create("uncertain-create", Payload())
    assert not created
    assert job.state == "queued"


async def test_ambiguous_completion_commit_is_read_not_blindly_replayed(queue):
    job, _ = await queue.create("uncertain-complete", Payload())
    claimed = await queue.claim(uuid4())
    session_class = queue.sessions.class_.sync_session_class

    def lost_ack(session):
        raise OSError("injected lost acknowledgement AFTER actual PostgreSQL commit")

    event.listen(session_class, "after_commit", lost_ack, once=True)
    try:
        with pytest.raises(QueueUnavailable):
            await queue.complete(job.id, claimed.owner, claimed.generation, {"ok": True})
    finally:
        event.remove(session_class, "after_commit", lost_ack)
    assert (await queue.get(job.id)).state == "succeeded"
    assert not await queue.complete(job.id, claimed.owner, claimed.generation, {"ok": True})
    async with queue.sessions() as session:
        assert (await session.get(JobEffect, job.id)).result == {"ok": True}


async def test_server_disconnect_rolls_back_uncommitted_completion(queue):
    job, _ = await queue.create("disconnect", Payload())
    claimed = await queue.claim(uuid4())
    async with queue.sessions() as session:
        await session.begin()
        locked = await session.scalar(select(Job).where(Job.id == job.id).with_for_update())
        now = await queue._clock(session)
        queue._release(locked, "succeeded", now)
        locked.result = {"uncommitted": True}
        session.add(JobEffect(job_id=job.id, generation=claimed.generation, result=locked.result))
        await session.flush()
        pid = await session.scalar(text("SELECT pg_backend_pid()"))
        async with queue.sessions.begin() as killer:
            assert await killer.scalar(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})
        with pytest.raises(DBAPIError):
            await session.commit()
        await session.rollback()
    assert (await queue.get(job.id)).state == "running"
    async with queue.sessions() as session:
        assert await session.get(JobEffect, job.id) is None


async def test_deadlock_retry_uses_new_transaction(queue):
    # Have PostgreSQL raise its real retryable SQLSTATE once. This tests the
    # retry plumbing; full multi-row deadlock schedules are outside our protocol.
    attempts = 0
    pids = []

    async def operation(session):
        nonlocal attempts
        attempts += 1
        pids.append(await session.scalar(text("SELECT txid_current()")))
        if attempts == 1:
            await session.execute(text("DO $$ BEGIN RAISE deadlock_detected; END $$"))
        return "ok"

    assert await queue._transaction(operation) == "ok"
    assert attempts == 2
    assert len(set(pids)) == 2


async def test_retryable_failure_is_bounded(queue):
    attempts = 0

    async def operation(session):
        nonlocal attempts
        attempts += 1
        await session.execute(text("DO $$ BEGIN RAISE serialization_failure; END $$"))

    with pytest.raises(QueueUnavailable):
        await queue._transaction(operation)
    assert attempts == 3


async def test_shutdown_cancels_heartbeat_and_execution_without_leaking_tasks(queue):
    from training_queue.worker import Worker

    await queue.create("shutdown", Payload(duration_ms=60_000))
    worker = Worker(queue)
    stop = asyncio.Event()
    running = asyncio.create_task(worker.run(stop))
    async with asyncio.timeout(2):
        while True:
            jobs, _ = await queue.list_jobs(1)
            if jobs[0].state == "running":
                break
            await asyncio.sleep(0.005)
    stop.set()
    await asyncio.wait_for(running, 2)
    assert (await queue.get(jobs[0].id)).state == "queued"
