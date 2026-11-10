"""Real HTTP/Postgres/worker-child SIGKILL experiment. No application writes."""

import argparse
import asyncio
import json
import math
import random
import time

from scripts.experiment import Experiment, common_arguments, emit, utc, workload

PROBE = """
import json
from pathlib import Path
for path in Path('/proc').glob('[0-9]*/cmdline'):
    try:
        if path.read_bytes().split(bytes([0]))[:3] == [b'python', b'-m', b'training_queue.worker']:
            pid = int(path.parent.name)
            assert pid != 1
            ticks = (path.parent/'stat').read_text().split()[21]
            print(json.dumps({'pid': pid, 'start_ticks': ticks}))
            break
    except FileNotFoundError:
        continue
else:
    raise RuntimeError('no worker child found')
"""


async def inject_kills(run, done):
    rng = random.Random(run.args.seed + 91)
    next_kill = time.perf_counter() + run.args.kill_interval
    while not done.is_set():
        try:
            await asyncio.wait_for(done.wait(), max(0, next_kill - time.perf_counter()))
            break
        except TimeoutError:
            pass
        current = await run.inspect([worker["id"] for worker in run.workers])
        live = [worker for worker in current if worker["state"]["Running"]]
        assert len(live) == 8, "worker slots were not restored before next kill"
        selected = rng.choice(live)
        container = selected["id"]
        old_owner = await run.owner(container)
        probe = json.loads(await run.command("docker", "exec", container, "python", "-c", PROBE))
        affected = [
            dict(row)
            for row in await run.pool.fetch(
                """
            SELECT id::text, generation, state, lease_until, clock_timestamp() AS observed_at
            FROM jobs WHERE owner::text = $1 AND state = 'running'
        """,
                old_owner,
            )
        ]
        kill = {
            "time": utc(),
            "container": container,
            "name": selected["name"],
            "old_owner": old_owner,
            "old_process": probe,
            "old_started_at": selected["state"]["StartedAt"],
            "old_restart_count": selected["restarts"],
            "affected_jobs": affected,
            "schedule_lag_seconds": time.perf_counter() - next_kill,
            "terminated_and_replaced": False,
        }
        run.kills.append(kill)
        run.events.write({"kill_attempt": kill.copy()})
        # Exact target child and start ticks; do not signal PID 1 or host processes.
        command = (
            "import os,signal; from pathlib import Path; "
            f"pid={probe['pid']}; assert pid != 1; "
            'ticks=Path(f"/proc/{pid}/stat").read_text().split()[21]; '
            f"assert ticks == {probe['start_ticks']!r}; "
            'print("SIGKILL",pid,flush=True); os.kill(pid,signal.SIGKILL)'
        )
        await run.command("docker", "exec", container, "python", "-c", command, allowed=(0, 137))
        replacement_started = time.perf_counter()
        async with asyncio.timeout(12):
            while True:
                after = (await run.inspect([container]))[0]
                if (
                    after["state"]["Running"]
                    and after["restarts"] > selected["restarts"]
                    and after["state"]["StartedAt"] != selected["state"]["StartedAt"]
                ):
                    new_owner = await run.owner(container)
                    if new_owner and new_owner != old_owner:
                        new_probe = json.loads(
                            await run.command("docker", "exec", container, "python", "-c", PROBE)
                        )
                        break
                await asyncio.sleep(0.1)
        kill.update(
            new_owner=new_owner,
            new_process=new_probe,
            new_restart_count=after["restarts"],
            new_started_at=after["state"]["StartedAt"],
            replacement_seconds=time.perf_counter() - replacement_started,
            terminated_and_replaced=True,
        )
        run.events.write({"kill_verified": kill.copy()})
        emit(
            "kill_verified",
            number=len(run.kills),
            container=selected["name"],
            old_owner=old_owner,
            new_owner=new_owner,
            affected=affected,
            replacement_seconds=kill["replacement_seconds"],
        )
        next_kill = max(next_kill + run.args.kill_interval, time.perf_counter() + 0.01)


async def duplicate_requests(run, done):
    rng = random.Random(run.args.seed + 31)
    index = 0
    while not done.is_set():
        if run.identifiers:
            key = rng.choice(list(run.identifiers))
            payload = run.intended[key].copy()
            conflicting = index % 5 == 0
            if conflicting:
                payload["value"] += 1
            status, body = await run.request(
                "conflict" if conflicting else "replay", "POST", "/jobs", key=key, payload=payload
            )
            assert status == (409 if conflicting else 200), f"duplicate HTTP {status}"
            if not conflicting:
                assert body["id"] == run.identifiers[key]
            index += 1
        await asyncio.sleep(1 / run.args.duplicate_rps)


async def cancellations(run, done):
    rng = random.Random(run.args.seed + 71)
    while not done.is_set():
        for state, limit in [("queued", 2), ("running", 1)]:
            rows = await run.pool.fetch(
                """
                SELECT id::text FROM jobs WHERE idempotency_key LIKE $1 AND state = $2 LIMIT 100
            """,
                run.namespace + "%",
                state,
            )
            targets = rng.sample(list(rows), min(limit, len(rows)))
            for row in targets:
                status, _ = await run.request(
                    f"cancel_{state}", "POST", f"/jobs/{row['id']}/cancel"
                )
                assert status in (200, 409), f"cancel HTTP {status}"
        await asyncio.sleep(0.5)


async def main(args):
    items = workload(args.jobs, args.seed)
    async with Experiment(args, "chaos") as run:
        run.plan(items)
        counts = {}
        for item in items:
            counts[item["category"]] = counts.get(item["category"], 0) + 1
        serial_seconds = sum(
            item["payload"]["duration_ms"] / 1000 * (1 + item["payload"]["fail_attempts"])
            for item in items
        )
        drain_seconds = math.ceil(3 * serial_seconds / 8 + 5 * (10 + 4) + 15 + 30)
        config = vars(args) | {
            "distribution": counts,
            "drain_deadline_seconds": drain_seconds,
            "namespace": run.namespace,
            "nominal_serial_seconds": serial_seconds,
        }
        config.pop("database_url")
        run.save("workload.json", config)
        emit("chaos_started", **config)
        done = asyncio.Event()
        started = time.perf_counter()
        # Fail-fast TaskGroup cancels producers and injection on any assertion.
        async with asyncio.TaskGroup() as group:
            group.create_task(inject_kills(run, done))
            group.create_task(duplicate_requests(run, done))
            group.create_task(cancellations(run, done))
            semaphore = asyncio.Semaphore(128)

            async def create(key):
                async with semaphore:
                    await run.create(key)

            producers = []
            for index, key in enumerate(run.intended):
                await asyncio.sleep(max(0, started + index / args.create_rps - time.perf_counter()))
                producers.append(group.create_task(create(key)))
            await asyncio.gather(*producers)
            done.set()
        run.summary["injection_seconds"] = time.perf_counter() - started
        run.summary["kills"] = len(run.kills)
        run.summary["verified_restarts"] = sum(k["terminated_and_replaced"] for k in run.kills)
        await run.drain(drain_seconds)
        # Allow stdout pipes to deliver already-written completion records before counting logs.
        await asyncio.sleep(0.5)
        await run.validate()
        assert len(run.kills) > 0, "no actual kills in scenario"
        assert all(k["terminated_and_replaced"] for k in run.kills)
        run.summary["outcome"] = "PASS"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    common_arguments(parser)
    parser.add_argument(
        "--jobs", type=int, default=10000, choices=range(1, 10001), metavar="1..10000"
    )
    parser.add_argument("--create-rps", type=float, default=200)
    parser.add_argument("--duplicate-rps", type=float, default=50)
    parser.add_argument("--kill-interval", type=float, default=2)
    asyncio.run(main(parser.parse_args()))
