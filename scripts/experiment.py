"""Shared evidence and independent database oracle for the real HTTP experiments."""

import asyncio
import gzip
import importlib.metadata
import json
import math
import os
import platform
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import asyncpg
import httpx


def utc():
    return datetime.now(UTC).isoformat()


def emit(event, **fields):
    print(json.dumps({"time": utc(), "event": event, **fields}, default=str), flush=True)


def percentile(values, percent):
    if not values:
        return None
    return sorted(values)[max(0, math.ceil(len(values) * percent / 100) - 1)]


def workload(count, seed):
    import random

    rng = random.Random(seed)
    categories = [
        ("short", 8000, None, 0, False),
        ("medium", 1200, 100, 0, False),
        ("long", 400, 1000, 0, False),
        ("heartbeat", 100, 4000, 0, False),
        ("transient", 200, 20, 1, False),
        ("permanent", 100, 20, 0, True),
    ]
    plan = []
    for category, number, duration, failures, permanent in categories:
        for _ in range(number):
            plan.append(
                {
                    "category": category,
                    "payload": {
                        "duration_ms": duration
                        if duration is not None
                        else rng.choice([0, 5, 10, 20]),
                        "value": len(plan) % 101,
                        "fail_attempts": failures,
                        "fail_permanently": permanent,
                    },
                }
            )
    rng.shuffle(plan)
    return plan[:count]


class JsonLines:
    def __init__(self, path):
        self.stream = gzip.open(path, "wt", encoding="utf8")

    def write(self, value):
        self.stream.write(json.dumps(value, default=str, separators=(",", ":")) + "\n")
        self.stream.flush()

    def close(self):
        self.stream.close()


class Experiment:
    def __init__(self, args, kind):
        if "QUEUE_RUN_DIR" not in os.environ:
            raise RuntimeError("invoke through scripts/record.py so failures retain evidence")
        self.args, self.kind = args, kind
        self.directory = Path(os.environ["QUEUE_RUN_DIR"])
        self.namespace = f"{kind}-{args.seed}-{uuid4().hex[:12]}-"
        self.started = utc()
        self.requests = JsonLines(self.directory / "http.jsonl.gz")
        self.telemetry = JsonLines(self.directory / "telemetry.jsonl.gz")
        self.events = JsonLines(self.directory / "faults.jsonl.gz")
        self.intended = {}
        self.acknowledged = set()
        self.terminal_observed = {}
        self.cancelled_ack = set()
        self.identifiers = {}
        self.statuses = Counter()
        self.operations = Counter()
        self.latencies = []
        self.lags = []
        self.http_errors = []
        self.request_count = 0
        self.log_events = []
        self.samples = []
        self.kills = []
        self.client = httpx.AsyncClient(
            base_url=args.base_url,
            timeout=10,
            limits=httpx.Limits(max_connections=128, max_keepalive_connections=64),
        )
        self.compose = [
            "docker",
            "compose",
            "-p",
            args.project,
            "-f",
            "compose.yaml",
            "-f",
            "compose.eight.yaml",
        ]
        self.pool = None
        self.collectors = []
        self.log_process = None
        self.stop_monitor = asyncio.Event()
        self.monitor_task = None
        self.summary = {
            "kind": kind,
            "seed": args.seed,
            "namespace": self.namespace,
            "outcome": "FAIL",
            "started_at": self.started,
        }

    def save(self, name, value):
        (self.directory / name).write_text(json.dumps(value, indent=2, default=str) + "\n")

    async def command(self, *command, allowed=(0,)):
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        async with asyncio.timeout(30):
            stdout, stderr = await process.communicate()
        record = {
            "time": utc(),
            "command": command,
            "exit_code": process.returncode,
            "stdout": stdout.decode(errors="replace"),
            "stderr": stderr.decode(errors="replace"),
        }
        self.events.write(record)
        if process.returncode not in allowed:
            raise RuntimeError(f"command failed: {command[:3]}, exit {process.returncode}")
        return record["stdout"]

    async def inspect(self, ids):
        template = (
            '{"id":{{json .Id}},"name":{{json .Name}},"image":{{json .Image}},'
            '"project":{{json (index .Config.Labels "com.docker.compose.project")}},'
            '"service":{{json (index .Config.Labels "com.docker.compose.service")}},'
            '"state":{"Running":{{.State.Running}},"StartedAt":{{json .State.StartedAt}}},'
            '"restarts":{{.RestartCount}}}'
        )
        raw = await self.command("docker", "inspect", "--format", template, *ids)
        safe = [json.loads(line) for line in raw.splitlines()]
        for item in safe:
            assert item["project"] == self.args.project
            assert item["service"] == "worker"
        return safe

    async def owner(self, container):
        raw = await self.command("docker", "logs", container)
        owners = []
        for line in raw.splitlines():
            if line.startswith("{"):
                record = json.loads(line)
                if record.get("event") == "worker_started":
                    owners.append(record["owner"])
        return owners[-1] if owners else None

    async def __aenter__(self):
        try:
            return await self.start()
        except BaseException as exc:
            await self.__aexit__(type(exc), exc, exc.__traceback__)
            raise

    async def start(self):
        self.pool = await asyncpg.create_pool(
            self.args.database_url.replace("postgresql+asyncpg://", "postgresql://"),
            min_size=1,
            max_size=3,
            command_timeout=10,
            server_settings={"application_name": "queue-experiment", "timezone": "UTC"},
        )
        ids = (await self.command(*self.compose, "ps", "-q", "worker")).splitlines()
        workers = await self.inspect(ids)
        assert len(workers) == 8 and all(x["state"]["Running"] for x in workers)
        self.workers = workers
        self.stats_ids = (await self.command(*self.compose, "ps", "-q")).splitlines()
        self.worker_owners = {}
        for worker in workers:
            owner = await self.owner(worker["id"])
            assert owner, "worker has not logged its process-start UUID"
            self.worker_owners[worker["id"]] = owner
        self.save(
            "environment.json",
            {
                "platform": platform.platform(),
                "cpu_count": os.cpu_count(),
                "dependencies": {
                    name: importlib.metadata.version(name)
                    for name in ("httpx", "asyncpg", "sqlalchemy", "fastapi")
                },
                "docker": json.loads(
                    await self.command(
                        "docker",
                        "info",
                        "--format",
                        '{"version":{{json .ServerVersion}},"cpus":{{.NCPU}},'
                        '"memory_bytes":{{.MemTotal}},"os":{{json .OperatingSystem}},'
                        '"architecture":{{json .Architecture}}}',
                    )
                ),
                "workers": workers,
                "worker_owners": self.worker_owners,
                "postgres": await self.pool.fetchval("SELECT version()"),
                "config": {k: v for k, v in vars(self.args).items() if k != "database_url"},
                "lease_seconds": 10,
                "heartbeat_seconds": 3,
                "attempt_seconds": 120,
            },
        )
        # Preserve bytes before parsing. --follow stays attached across process restarts.
        self.log_process = await asyncio.create_subprocess_exec(
            *self.compose,
            "logs",
            "--follow",
            "--timestamps",
            "--no-color",
            "--since",
            self.started,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def collect(stream, name, parse):
            with gzip.open(self.directory / name, "wb") as output:
                while line := await stream.readline():
                    output.write(line)
                    if parse and b"{" in line:
                        try:
                            entry = json.loads(line[line.index(b"{") :])
                            if "event" in entry:
                                self.log_events.append(entry)
                        except (ValueError, UnicodeError):
                            pass  # raw line remains available for independent inspection

        self.collectors = [
            asyncio.create_task(collect(self.log_process.stdout, "services.stdout.txt.gz", True)),
            asyncio.create_task(collect(self.log_process.stderr, "services.stderr.txt.gz", False)),
        ]
        self.monitor_task = asyncio.create_task(self.monitor())
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc and self.intended and self.pool:
            try:
                await self.validate()
            except Exception as validation_error:
                self.summary["failure_snapshot_error"] = str(validation_error)
        self.stop_monitor.set()
        if self.monitor_task:
            await self.monitor_task
        if self.log_process:
            self.log_process.terminate()
            await self.log_process.wait()
            await asyncio.gather(*self.collectors)
        self.summary.update(
            ended_at=utc(),
            requests=self.request_count,
            operations=dict(self.operations),
            statuses=dict(self.statuses),
            http_errors=self.http_errors,
            latency_ms={f"p{p}": percentile(self.latencies, p) for p in (50, 95, 99)},
            dispatch_lag_ms={f"p{p}": percentile(self.lags, p) for p in (50, 95, 99)},
        )
        if exc:
            self.summary["failure"] = f"{exc_type.__name__}: {exc}"
        self.save("summary.json", self.summary)
        emit("experiment_finished", **self.summary)
        self.requests.close()
        self.telemetry.close()
        self.events.close()
        await self.client.aclose()
        if self.pool:
            await self.pool.close()

    def plan(self, items):
        manifest = JsonLines(self.directory / "intended.jsonl.gz")
        for i, item in enumerate(items):
            key = self.namespace + str(i)
            self.intended[key] = item["payload"]
            manifest.write({"key": key, **item})
        manifest.close()

    async def request(self, operation, method, path, *, key=None, payload=None, scheduled=None):
        started = time.perf_counter()
        lag = max(0, (started - scheduled) * 1000) if scheduled is not None else 0
        self.request_count += 1
        self.operations[operation] += 1
        self.lags.append(lag)
        record = {
            "time": utc(),
            "operation": operation,
            "method": method,
            "path": path,
            "key": key,
            "payload": payload,
            "dispatch_lag_ms": lag,
        }
        try:
            response = await self.client.request(
                method, path, headers={"Idempotency-Key": key} if key else None, json=payload
            )
            body = response.json()
            record.update(status=response.status_code, body=body)
            self.statuses[str(response.status_code)] += 1
            if isinstance(body, dict) and body.get("id"):
                job_id = body["id"]
                self.acknowledged.add(job_id)
                if body.get("state") in {"succeeded", "failed", "cancelled"}:
                    previous = self.terminal_observed.setdefault(job_id, body["state"])
                    assert previous == body["state"], "observed terminal state changed"
                if path.endswith("/cancel") and body.get("state") == "cancelled":
                    self.cancelled_ack.add(job_id)
            return response.status_code, body
        except httpx.HTTPError as exc:
            self.statuses["transport_error"] += 1
            self.http_errors.append({"operation": operation, "error": type(exc).__name__})
            record["error"] = type(exc).__name__
            return 0, None
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            self.latencies.append(elapsed)
            self.requests.write(record | {"latency_ms": elapsed})

    async def create(self, key):
        for attempt in range(5):
            status, body = await self.request(
                "create" if attempt == 0 else "create_retry",
                "POST",
                "/jobs",
                key=key,
                payload=self.intended[key],
            )
            if status in (200, 201):
                self.identifiers[key] = body["id"]
                return
            assert status in (0, 503), f"unexpected create HTTP {status}"
            await asyncio.sleep(0.1 * (attempt + 1))
        raise AssertionError("create retries exhausted; intended key remains in manifest")

    async def sample(self):
        async with self.pool.acquire() as connection:
            states = {
                row["state"]: row["n"]
                for row in await connection.fetch(
                    "SELECT state, count(*) n FROM jobs "
                    "WHERE idempotency_key LIKE $1 GROUP BY state",
                    self.namespace + "%",
                )
            }
            connections = [
                dict(row)
                for row in await connection.fetch("""
                SELECT application_name, state, wait_event_type, count(*) n
                FROM pg_stat_activity WHERE datname = current_database()
                GROUP BY application_name, state, wait_event_type
            """)
            ]
        sample = {
            "time": utc(),
            "monotonic": time.perf_counter(),
            "states": states,
            "connections": connections,
        }
        self.samples.append(sample)
        self.telemetry.write(sample)
        return states

    async def monitor(self):
        number = 0
        while not self.stop_monitor.is_set():
            try:
                await self.sample()
                if number % 10 == 0:
                    ids = self.stats_ids
                    stats = await self.command(
                        "docker", "stats", "--no-stream", "--format", "{{json .}}", *ids
                    )
                    self.telemetry.write({"time": utc(), "docker_stats": stats})
                number += 1
            except Exception as exc:
                self.telemetry.write({"time": utc(), "monitor_error": type(exc).__name__})
            try:
                await asyncio.wait_for(self.stop_monitor.wait(), 1)
            except TimeoutError:
                pass

    async def drain(self, seconds):
        emit("drain_started", deadline_seconds=seconds)
        started = time.perf_counter()
        async with asyncio.timeout(seconds):
            while True:
                states = await self.sample()
                if sum(states.values()) == len(self.intended) and not (
                    states.get("queued", 0) + states.get("running", 0)
                ):
                    self.summary["drain_seconds"] = time.perf_counter() - started
                    return
                await asyncio.sleep(0.5)

    async def validate(self):
        async with self.pool.acquire() as connection:
            async with connection.transaction(isolation="repeatable_read", readonly=True):
                snapshot = await connection.fetchval("SELECT pg_current_snapshot()::text")
                jobs = [
                    dict(row)
                    for row in await connection.fetch(
                        "SELECT * FROM jobs WHERE idempotency_key LIKE $1 ORDER BY created_at, id",
                        self.namespace + "%",
                    )
                ]
                effects = [
                    dict(row)
                    for row in await connection.fetch(
                        """
                    SELECT e.* FROM job_effects e JOIN jobs j ON j.id = e.job_id
                    WHERE j.idempotency_key LIKE $1 ORDER BY e.job_id
                """,
                        self.namespace + "%",
                    )
                ]
        for name, rows in (
            ("database-jobs.jsonl.gz", jobs),
            ("database-effects.jsonl.gz", effects),
        ):
            output = JsonLines(self.directory / name)
            for row in rows:
                output.write(row)
            output.close()
        by_key = {row["idempotency_key"]: row for row in jobs}
        by_id = {str(row["id"]): row for row in jobs}
        counts = Counter(str(row["job_id"]) for row in effects)
        effect_map = {str(row["job_id"]): row for row in effects}
        failures = []

        def check(condition, message):
            if not condition:
                failures.append(message)

        check(len(jobs) == len(self.intended) == len(by_key), "job count/unique key mismatch")
        check(set(by_key) == set(self.intended), "missing or additional intended keys")
        check(self.acknowledged <= set(by_id), "acknowledged ID missing")
        for key, row in by_key.items():
            job_id = str(row["id"])
            check(json.loads(row["payload"]) == self.intended.get(key), f"payload changed: {key}")
            check(row["state"] in {"succeeded", "failed", "cancelled"}, f"not terminal: {job_id}")
            check(counts[job_id] <= 1, f"multiple effects: {job_id}")
            check(
                (counts[job_id] == 1) == (row["state"] == "succeeded"),
                f"effect/state mismatch: {job_id}",
            )
            if job_id in effect_map:
                effect = effect_map[job_id]
                check(effect["generation"] == row["generation"], f"stale generation: {job_id}")
                expected = {"squared_value": self.intended[key]["value"] ** 2}
                check(
                    json.loads(effect["result"]) == json.loads(row["result"]) == expected,
                    f"wrong result: {job_id}",
                )
            if job_id in self.terminal_observed:
                check(row["state"] == self.terminal_observed[job_id], f"terminal changed: {job_id}")
            if job_id in self.cancelled_ack:
                check(row["state"] == "cancelled", f"cancelled ack changed: {job_id}")
        ids = set(by_id)
        events = [event for event in self.log_events if event.get("job_id") in ids]
        log_counts = Counter(event["event"] for event in events)
        claims = Counter(
            (event["job_id"], event["generation"])
            for event in events
            if event["event"] == "claim_committed"
        )
        check(all(n == 1 for n in claims.values()), "duplicate same-generation claim log")
        self.summary.update(
            snapshot=snapshot,
            intended_jobs=len(self.intended),
            jobs=len(jobs),
            effects=len(effects),
            states=dict(Counter(row["state"] for row in jobs)),
            failed_reasons=dict(Counter(row["error"] for row in jobs if row["state"] == "failed")),
            committed_claims=sum(row["attempts"] for row in jobs),
            retries=sum(max(0, row["attempts"] - 1) for row in jobs),
            cancelled_acknowledgements=len(self.cancelled_ack),
            worker_log_counts=dict(log_counts),
            assertions_failed=failures,
        )
        for kill in self.kills:
            kill["final_jobs"] = [
                {
                    "id": str(by_id[item["id"]]["id"]),
                    "state": by_id[item["id"]]["state"],
                    "generation": by_id[item["id"]]["generation"],
                    "killed_generation": item["generation"],
                }
                for item in kill.get("affected_jobs", [])
                if item["id"] in by_id
            ]
        self.save("kills.json", self.kills)
        validation = self.summary | {"outcome": "FAIL" if failures else "PASS"}
        self.save("invariants.json", validation)
        emit("database_validation", **validation)
        assert not failures, f"database invariant failures: {failures[:5]}"


def common_arguments(parser):
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--project", default="queue-phase3")
    parser.add_argument("--base-url", default="http://localhost:18000")
    parser.add_argument(
        "--database-url",
        default=os.environ.get(
            "QUEUE_DATABASE_URL", "postgresql://queue:queue@localhost:55433/queue"
        ),
    )
