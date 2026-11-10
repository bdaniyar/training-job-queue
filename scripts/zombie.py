"""Freeze a real worker beyond its lease, then resume it after a newer claim."""

import argparse
import asyncio
import json

from scripts.chaos import PROBE
from scripts.experiment import Experiment, common_arguments, emit, utc


async def main(args):
    async with Experiment(args, "zombie") as run:
        run.plan(
            [
                {
                    "category": "frozen",
                    "payload": {
                        "duration_ms": 4000,
                        "value": 17,
                        "fail_attempts": 0,
                        "fail_permanently": False,
                    },
                }
            ]
        )
        key = next(iter(run.intended))
        await run.create(key)
        job_id = run.identifiers[key]
        frozen = None
        try:
            async with asyncio.timeout(5):
                while True:
                    old = await run.pool.fetchrow("SELECT * FROM jobs WHERE id::text = $1", job_id)
                    if old["state"] == "running":
                        break
                    await asyncio.sleep(0.02)
            owner = str(old["owner"])
            container = next(cid for cid, boot in run.worker_owners.items() if boot == owner)
            probe = json.loads(
                await run.command("docker", "exec", container, "python", "-c", PROBE)
            )
            pid = probe["pid"]
            await run.command(
                "docker",
                "exec",
                container,
                "python",
                "-c",
                f"import os,signal; assert {pid} != 1; os.kill({pid},signal.SIGSTOP)",
            )
            frozen = (container, pid)
            state = await run.command(
                "docker",
                "exec",
                container,
                "python",
                "-c",
                f'from pathlib import Path; print(Path("/proc/{pid}/status").read_text())',
            )
            assert "State:\tT" in state, "worker was not actually stopped"
            emit(
                "worker_frozen",
                container=container,
                pid=pid,
                owner=owner,
                job_id=job_id,
                generation=old["generation"],
                time=utc(),
            )
            async with asyncio.timeout(25):
                while True:
                    current = await run.pool.fetchrow(
                        "SELECT * FROM jobs WHERE id::text = $1", job_id
                    )
                    if current["generation"] > old["generation"]:
                        break
                    await asyncio.sleep(0.05)
            assert str(current["owner"]) != owner
            await run.command(
                "docker",
                "exec",
                container,
                "python",
                "-c",
                f"import os,signal; os.kill({pid},signal.SIGCONT)",
            )
            frozen = None
            emit(
                "worker_resumed",
                job_id=job_id,
                old_generation=old["generation"],
                current_generation=current["generation"],
                current_owner=str(current["owner"]),
            )
            await run.drain(20)
            # Wait for actual stale worker's ownership_lost log as well as final DB state.
            async with asyncio.timeout(5):
                while not any(
                    e.get("event") == "ownership_lost"
                    and e.get("owner") == owner
                    and e.get("job_id") == job_id
                    for e in run.log_events
                ):
                    run.log_changed.clear()
                    await run.log_changed.wait()
            await run.validate()
            assert run.summary["effects"] == 1
            run.summary.update(
                outcome="PASS",
                old_generation=old["generation"],
                winning_generation=current["generation"],
                old_owner=owner,
                replacement_owner=str(current["owner"]),
            )
        finally:
            if frozen:
                container, pid = frozen
                await run.command(
                    "docker",
                    "exec",
                    container,
                    "python",
                    "-c",
                    f"import os,signal; os.kill({pid},signal.SIGCONT)",
                )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    common_arguments(parser)
    asyncio.run(main(parser.parse_args()))
