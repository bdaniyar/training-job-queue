import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError

from training_queue.models import Job, JobEffect
from training_queue.schemas import Payload
from training_queue.transitions import Conflict
from training_queue.worker import Worker


async def new_job(queue, **payload):
    job, _ = await queue.create(str(uuid4()), Payload(**payload))
    return job


async def effects(queue, job_id):
    async with queue.sessions() as session:
        return await session.scalar(
            select(func.count()).select_from(JobEffect).where(JobEffect.job_id == job_id)
        )


async def expire(queue, job_id, *, ready=False):
    # Fault injection uses DB time; no real-time sleeps or local-clock dependency.
    async with queue.sessions.begin() as session:
        await session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(lease_until=func.clock_timestamp() - text("interval '1 second'"))
        )
    if ready:
        await queue.recover()
        await make_ready(queue, job_id)


async def make_ready(queue, job_id):
    async with queue.sessions.begin() as session:
        await session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(available_at=func.clock_timestamp() - text("interval '1 second'"))
        )


async def wait_blocked(queue):
    # Observe an actual blocked DB transaction rather than hoping a sleep races.
    async with asyncio.timeout(2):
        while True:
            async with queue.sessions() as session:
                count = await session.scalar(
                    text("""
                    SELECT count(*) FROM pg_stat_activity
                    WHERE datname = current_database() AND wait_event_type = 'Lock'
                      AND pid != pg_backend_pid()
                """)
                )
            if count:
                return
            await asyncio.sleep(0.005)


async def test_parallel_claims_assign_each_job_once(queue):
    jobs = [await new_job(queue) for _ in range(12)]
    owners = [uuid4() for _ in range(12)]
    gate = asyncio.Event()

    async def claim(owner):
        await gate.wait()
        return await queue.claim(owner)

    tasks = [asyncio.create_task(claim(owner)) for owner in owners]
    gate.set()
    claimed = await asyncio.gather(*tasks)
    assert {job.id for job in claimed} == {job.id for job in jobs}
    assert len({job.owner for job in claimed}) == 12
    assert all(job.attempts == job.generation == 1 for job in claimed)


async def test_claim_skips_locked_job(queue):
    first, second = await new_job(queue), await new_job(queue)
    async with queue.sessions.begin() as session:
        await session.scalar(select(Job).where(Job.id == first.id).with_for_update())
        claimed = await queue.claim(uuid4())
        assert claimed.id == second.id
    assert (await queue.claim(uuid4())).id == first.id


async def test_idempotency_conflict_waits_and_reads_fresh_snapshot(queue):
    payload = Payload().model_dump()
    async with queue.sessions.begin() as session:
        original = Job(id=uuid4(), idempotency_key="blocked", payload=payload)
        session.add(original)
        await session.flush()
        replay = asyncio.create_task(queue.create("blocked", Payload()))
        await wait_blocked(queue)
        assert not replay.done()
    job, created = await replay
    assert job.id == original.id
    assert not created
    with pytest.raises(Conflict):
        await queue.create("blocked", Payload(value=2))


async def test_duplicate_completions_only_one_commit(queue):
    original = await new_job(queue)
    owner = uuid4()
    job = await queue.claim(owner)
    gate = asyncio.Event()

    async def complete():
        await gate.wait()
        return await queue.complete(job.id, owner, job.generation, {"value": 1})

    tasks = [asyncio.create_task(complete()) for _ in range(2)]
    gate.set()
    assert sorted(await asyncio.gather(*tasks)) == [False, True]
    assert await effects(queue, original.id) == 1
    assert (await queue.get(job.id)).state == "succeeded"


async def test_wrong_owner_cannot_finish_or_heartbeat(queue):
    await new_job(queue)
    job = await queue.claim(uuid4())
    assert not await queue.complete(job.id, uuid4(), job.generation, {})
    assert not await queue.heartbeat(job.id, uuid4(), job.generation)
    assert await effects(queue, job.id) == 0


async def test_zombie_fenced_even_if_process_owner_reused(queue):
    await new_job(queue)
    owner = uuid4()
    first = await queue.claim(owner)
    await expire(queue, first.id, ready=True)
    second = await queue.claim(owner)
    assert second.generation == first.generation + 1
    assert not await queue.complete(first.id, owner, first.generation, {"stale": True})
    assert not await queue.heartbeat(first.id, owner, first.generation)
    assert not await queue.fail(first.id, owner, first.generation, "stale failure")
    assert await queue.complete(second.id, owner, second.generation, {"winner": True})
    async with queue.sessions() as session:
        effect = await session.get(JobEffect, first.id)
        assert effect.generation == second.generation
        assert effect.result == {"winner": True}


async def test_expired_lease_cannot_be_revived_or_completed(queue):
    await new_job(queue)
    job = await queue.claim(uuid4())
    await expire(queue, job.id)
    assert not await queue.heartbeat(job.id, job.owner, job.generation)
    assert not await queue.complete(job.id, job.owner, job.generation, {})
    assert not await queue.fail(job.id, job.owner, job.generation, "late")
    assert await effects(queue, job.id) == 0


async def test_cancel_then_complete_has_no_effect(queue):
    await new_job(queue)
    job = await queue.claim(uuid4())
    cancelled = await queue.cancel(job.id)
    assert cancelled.state == "cancelled"
    assert not await queue.complete(job.id, job.owner, job.generation, {})
    assert (await queue.cancel(job.id)).finished_at == cancelled.finished_at
    assert await effects(queue, job.id) == 0


async def test_complete_then_cancel_preserves_success(queue):
    await new_job(queue)
    job = await queue.claim(uuid4())
    assert await queue.complete(job.id, job.owner, job.generation, {"ok": True})
    with pytest.raises(Conflict):
        await queue.cancel(job.id)
    assert (await queue.get(job.id)).state == "succeeded"
    assert await effects(queue, job.id) == 1


@pytest.mark.parametrize("winner", ["cancel", "complete"])
async def test_cancel_complete_race_observes_locked_winner(queue, winner, monkeypatch):
    await new_job(queue)
    job = await queue.claim(uuid4())
    locked, release = asyncio.Event(), asyncio.Event()
    original_clock = queue._clock

    async def pause_after_first_lock(session):
        if not locked.is_set():
            locked.set()
            await release.wait()
        return await original_clock(session)

    # Both sides use the actual transition functions. Pause the winner only
    # after it has the real row lock, then observe the loser blocked in Postgres.
    monkeypatch.setattr(queue, "_clock", pause_after_first_lock)

    def complete():
        return queue.complete(job.id, job.owner, job.generation, {"winner": True})

    def cancel():
        return queue.cancel(job.id)

    winning = asyncio.create_task(complete() if winner == "complete" else cancel())
    await asyncio.wait_for(locked.wait(), 1)
    loser = asyncio.create_task(cancel() if winner == "complete" else complete())
    try:
        await wait_blocked(queue)
    finally:
        release.set()
    await winning
    if winner == "complete":
        with pytest.raises(Conflict):
            await loser
        assert await effects(queue, job.id) == 1
    else:
        assert not await loser
        assert await effects(queue, job.id) == 0


async def test_multiple_recovery_sweepers_requeue_only_once(queue):
    await new_job(queue)
    job = await queue.claim(uuid4())
    await expire(queue, job.id)
    recovered = await asyncio.gather(*(queue.recover() for _ in range(4)))
    assert sum(len(rows) for rows in recovered) == 1
    current = await queue.get(job.id)
    assert current.state == "queued"
    assert current.owner is current.lease_until is current.attempt_deadline is None
    assert current.available_at > current.updated_at
    assert await effects(queue, job.id) == 0


async def test_retry_budget_exhaustion_and_backoff(queue):
    original = await new_job(queue)
    for attempt in range(1, 6):
        await make_ready(queue, original.id)
        job = await queue.claim(uuid4())
        assert job.attempts == attempt
        await expire(queue, job.id)
        await queue.recover()
        current = await queue.get(job.id)
        if attempt < 5:
            assert current.state == "queued"
            assert (current.available_at - current.updated_at).total_seconds() == 2 ** (attempt - 1)
            assert await queue.claim(uuid4()) is None
    assert current.state == "failed"
    assert current.finished_at is not None
    assert current.error == "lease expired"
    assert await effects(queue, original.id) == 0


async def test_reported_failures_retry_or_fail_permanently(queue):
    await new_job(queue)
    first = await queue.claim(uuid4())
    assert await queue.fail(first.id, first.owner, first.generation, "transient")
    assert (await queue.get(first.id)).state == "queued"
    await make_ready(queue, first.id)
    second = await queue.claim(uuid4())
    assert await queue.fail(second.id, second.owner, second.generation, "permanent", permanent=True)
    assert (await queue.get(first.id)).state == "failed"
    assert await effects(queue, first.id) == 0


async def test_effect_insert_failure_rolls_back_state(queue):
    await new_job(queue)
    job = await queue.claim(uuid4())
    async with queue.sessions.begin() as session:
        # Deliberately inject invalid state to check a real unique violation,
        # including rollback of the state update in complete().
        session.add(JobEffect(job_id=job.id, generation=job.generation, result={"injected": True}))
    with pytest.raises(IntegrityError):
        await queue.complete(job.id, job.owner, job.generation, {"new": True})
    assert (await queue.get(job.id)).state == "running"
    assert await effects(queue, job.id) == 1


async def test_state_write_failure_rolls_back_effect(queue):
    await new_job(queue)
    job = await queue.claim(uuid4())
    async with queue.sessions.begin() as session:
        await session.execute(
            text("""
            ALTER TABLE jobs ADD CONSTRAINT injected_no_success CHECK (state != 'succeeded')
        """)
        )
    try:
        with pytest.raises(IntegrityError):
            await queue.complete(job.id, job.owner, job.generation, {})
        assert (await queue.get(job.id)).state == "running"
        assert await effects(queue, job.id) == 0
    finally:
        async with queue.sessions.begin() as session:
            await session.execute(text("ALTER TABLE jobs DROP CONSTRAINT injected_no_success"))


async def test_database_clock_ignores_local_clock_and_caps_deadline(queue, monkeypatch):
    class SkewedClock:
        @staticmethod
        def now(*args, **kwargs):
            raise AssertionError("worker-local wall clock used to authorize a lease")

    monkeypatch.setattr("training_queue.transitions.datetime", SkewedClock)
    await new_job(queue)
    job = await queue.claim(uuid4())
    async with queue.sessions() as session:
        db_now = await queue._clock(session)
        assert (job.lease_until - db_now).total_seconds() <= 10
    assert await queue.heartbeat(job.id, job.owner, job.generation)
    async with queue.sessions.begin() as session:
        await session.execute(
            update(Job)
            .where(Job.id == job.id)
            .values(
                lease_until=func.clock_timestamp() + text("interval '1 second'"),
                attempt_deadline=func.clock_timestamp() + text("interval '2 seconds'"),
            )
        )
    assert await queue.heartbeat(job.id, job.owner, job.generation)
    current = await queue.get(job.id)
    assert current.lease_until == current.attempt_deadline
    assert await queue.complete(job.id, job.owner, job.generation, {})


async def test_clock_sample_after_waiting_for_lock(queue):
    await new_job(queue)
    job = await queue.claim(uuid4())
    async with queue.sessions.begin() as session:
        locked = await session.scalar(select(Job).where(Job.id == job.id).with_for_update())
        task = asyncio.create_task(queue.complete(job.id, job.owner, job.generation, {}))
        await wait_blocked(queue)
        # The blocked transaction started while the lease was valid. Its eventual
        # authorization must use the newer row and current DB time after locking.
        locked.lease_until = await queue._clock(session)
    assert not await task
    assert await effects(queue, job.id) == 0


async def test_constraints_immutable_payload_and_terminal_state(queue):
    job = await new_job(queue)
    with pytest.raises(IntegrityError):
        async with queue.sessions.begin() as session:
            await session.execute(
                update(Job).where(Job.id == job.id).values(payload={"changed": 1})
            )
    await queue.cancel(job.id)
    with pytest.raises(IntegrityError):
        async with queue.sessions.begin() as session:
            await session.execute(
                update(Job).where(Job.id == job.id).values(state="queued", finished_at=None)
            )
    with pytest.raises(IntegrityError):
        async with queue.sessions.begin() as session:
            session.add(Job(id=uuid4(), idempotency_key="bad", payload={}, state="running"))


async def test_real_worker_executes_and_commits_once(queue, capsys):
    job = await new_job(queue, value=7, duration_ms=10)
    worker = Worker(queue)
    claimed = await queue.claim(worker.owner)
    await worker.process(claimed, asyncio.Event())
    final = await queue.get(job.id)
    assert final.state == "succeeded"
    assert final.result == {"squared_value": 49}
    assert await effects(queue, job.id) == 1
    output = capsys.readouterr().out
    for event in ("execution_started", "execution_finished", "effect_committed"):
        assert event in output


async def test_worker_shutdown_releases_work_without_effect(queue):
    job = await new_job(queue, duration_ms=60_000)
    worker = Worker(queue)
    claimed = await queue.claim(worker.owner)
    stop = asyncio.Event()
    stop.set()
    await worker.process(claimed, stop)
    assert (await queue.get(job.id)).state == "queued"
    assert await effects(queue, job.id) == 0


async def test_worker_observes_running_cancellation(queue):
    queue.settings.heartbeat_seconds = 0.01
    job = await new_job(queue, duration_ms=60_000)
    worker = Worker(queue)
    claimed = await queue.claim(worker.owner)
    process = asyncio.create_task(worker.process(claimed, asyncio.Event()))
    await queue.cancel(job.id)
    await asyncio.wait_for(process, 1)
    assert (await queue.get(job.id)).state == "cancelled"
    assert await effects(queue, job.id) == 0
