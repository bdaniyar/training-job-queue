"""Small real HTTP/Compose verification, NOT the Phase 3 chaos harness.

Temporarily stops worker containers belonging to this Compose project, exercises
one graceful stop and one abrupt process death, then restores four workers.
Run with: python scripts/record.py uv run --frozen python scripts/smoke.py
"""

import asyncio
import json
import subprocess
from uuid import uuid4

import httpx
from sqlalchemy import select

from training_queue.config import Settings
from training_queue.db import make_database
from training_queue.models import Job, JobEffect


def docker(*args, allowed_codes=(0,)):
    command = ["docker", *args]
    print(json.dumps({"command": command}), flush=True)
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    print(result.stdout, end="", flush=True)
    print(result.stderr, end="", flush=True)
    print(json.dumps({"command_exit_code": result.returncode}), flush=True)
    if result.returncode not in allowed_codes:
        result.check_returncode()
    return result.stdout.strip()


async def main():
    engine, sessions = make_database(Settings().database_url)
    prefix = f"smoke-{uuid4()}"
    ids = []
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=10) as client:

        async def request(method, path, **kwargs):
            response = await client.request(method, path, **kwargs)
            print(
                json.dumps(
                    {
                        "method": method,
                        "path": path,
                        "status": response.status_code,
                        "body": response.json(),
                    }
                ),
                flush=True,
            )
            return response

        async def create(name, **payload):
            response = await request(
                "POST", "/jobs", json=payload, headers={"Idempotency-Key": f"{prefix}-{name}"}
            )
            assert response.status_code == 201
            ids.append(response.json()["id"])
            return response.json()

        async def wait_state(job_id, states):
            async with asyncio.timeout(30):
                while True:
                    response = await client.get(f"/jobs/{job_id}")
                    response.raise_for_status()
                    body = response.json()
                    if body["state"] in states:
                        print(json.dumps({"observed": body}), flush=True)
                        return body
                    await asyncio.sleep(0.05)

        try:
            assert (await request("GET", "/health")).status_code == 200
            workers = docker("compose", "ps", "-q", "worker").splitlines()
            assert len(workers) == 4, f"expected four worker containers, got {len(workers)}"
            for i in range(6):
                await create(str(i), value=i - 2, duration_ms=20)
            replay = await request(
                "POST",
                "/jobs",
                json={"value": -2, "duration_ms": 20},
                headers={"Idempotency-Key": f"{prefix}-0"},
            )
            assert replay.status_code == 200 and replay.json()["id"] == ids[0]
            assert (
                await request(
                    "POST", "/jobs", json={"value": 99}, headers={"Idempotency-Key": f"{prefix}-0"}
                )
            ).status_code == 409
            permanent = await create("permanent", fail_permanently=True)
            transient = await create("transient", fail_attempts=1)
            cancelled = await create("cancel", duration_ms=60_000)
            assert (await request("POST", f"/jobs/{cancelled['id']}/cancel")).status_code == 200
            for job_id in ids[:6]:
                assert (await wait_state(job_id, {"succeeded"}))["attempts"] == 1
            assert (await wait_state(permanent["id"], {"failed"}))["attempts"] == 1
            assert (await wait_state(transient["id"], {"succeeded"}))["attempts"] == 2
            assert (await wait_state(cancelled["id"], {"cancelled"}))["result"] is None
            assert (await request("GET", "/jobs", params={"limit": 2})).status_code == 200

            # Isolate one actual process so the stop/crash targets are unambiguous.
            docker("compose", "stop", "worker")
            container = workers[0]
            docker("start", container)
            graceful = await create("graceful", duration_ms=1500)
            await wait_state(graceful["id"], {"running"})
            docker("stop", "--timeout", "10", container)
            released = await wait_state(graceful["id"], {"queued"})
            assert released["attempts"] == 1
            docker("start", container)
            assert (await wait_state(graceful["id"], {"succeeded"}))["attempts"] == 2

            abrupt = await create("abrupt", duration_ms=1500)
            before = await wait_state(abrupt["id"], {"running"})
            restart_before = int(docker("inspect", "--format", "{{.RestartCount}}", container))
            # Compose's init process is PID 1. Kill only its Python worker child,
            # so Docker sees a real crash rather than a deliberate container stop.
            docker(
                "exec",
                container,
                "python",
                "-c",
                "import os, signal; from pathlib import Path; "
                "pid = next(int(p.parent.name) for p in Path('/proc').glob('[0-9]*/cmdline') "
                "if p.read_bytes().split(bytes([0]))[:3] == "
                "[b'python', b'-m', b'training_queue.worker']); "
                "assert pid != 1; print('killing worker child', pid, flush=True); "
                "os.kill(pid, signal.SIGKILL)",
                allowed_codes=(0, 137),  # exec can die too when init exits after its child
            )
            abandoned = await request("GET", f"/jobs/{abrupt['id']}")
            assert abandoned.json()["state"] == "running"
            assert abandoned.json()["generation"] == before["generation"]
            final = await wait_state(abrupt["id"], {"succeeded"})
            assert final["generation"] == before["generation"] + 1
            assert (
                int(docker("inspect", "--format", "{{.RestartCount}}", container)) > restart_before
            )

            async with sessions() as session:
                jobs = (
                    await session.scalars(select(Job).where(Job.idempotency_key.startswith(prefix)))
                ).all()
                effects = (
                    await session.scalars(
                        select(JobEffect).where(JobEffect.job_id.in_([job.id for job in jobs]))
                    )
                ).all()
            by_job = {effect.job_id: effect for effect in effects}
            assert len(jobs) == len(ids) == 11
            for job in jobs:
                effect = by_job.get(job.id)
                assert job.state in {"succeeded", "failed", "cancelled"}
                assert (effect is not None) == (job.state == "succeeded")
                if effect:
                    assert effect.generation == job.generation
                    assert effect.result == job.result
            print(
                json.dumps(
                    {
                        "smoke": "passed",
                        "jobs": len(jobs),
                        "effects": len(effects),
                        "succeeded": sum(j.state == "succeeded" for j in jobs),
                        "failed": sum(j.state == "failed" for j in jobs),
                        "cancelled": sum(j.state == "cancelled" for j in jobs),
                    }
                ),
                flush=True,
            )
        finally:
            try:
                # Snapshot before any Compose recreation removes container logs.
                docker("compose", "logs", "--timestamps", "--no-color")
            finally:
                try:
                    docker("compose", "up", "-d", "--wait", "worker")
                finally:
                    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
