# training-job-queue

A small FastAPI/PostgreSQL queue with independent worker processes, fenced leases,
transactional completion, and countable database effects. Phase 3 adds real seeded
chaos experiments, a sustained open-loop HTTP load test, and a documented verdict.
See [REPORT.md](REPORT.md) for measured results and their limits; the submission
design note is [DESIGN_SUMMARY.md](DESIGN_SUMMARY.md), with the full design retained.

The complete one-page Soup assignment PDF was read in Phase 1. The user's stack
and deadline govern: **November 11, 2026, 22:10 Asia/Almaty (UTC+05:00)**. Per the
user's latest Soup email update, the 40-minute live discussion has been cancelled.
No email submission has been sent by this collaboration.

## Quick start

Requires Docker with Compose v2 and internet access for the initial image build.
No external credentials or local environment files are needed.

```sh
docker compose up
```

Postgres readiness precedes a single Alembic migration service. A successful
migration precedes the API and **four independent worker containers**, one process
per container (plus Docker's tiny init for signal forwarding and child reaping).
Open http://localhost:8000/docs or GET http://localhost:8000/health.
Data persists in the Compose volume. Development-only credentials are `queue:queue`;
API and Postgres ports bind to localhost. Set `QUEUE_API_PORT` or `QUEUE_DB_PORT`
if the default 8000/55432 ports are occupied. `docker compose down` preserves data.

Exactly eight workers for Phase 3:

```sh
docker compose -f compose.yaml -f compose.eight.yaml up --build
```

Do not run both configurations concurrently against the same project. Return to
four with `docker compose up -d --wait`. Workers use `restart: unless-stopped`;
a deliberate stop stays stopped, while an unexpected process death restarts it.

## API contract

Create takes the payload directly as JSON and a required `Idempotency-Key` header
(1..200 characters, not all whitespace). Keys are global, case sensitive, and kept
for the lifetime of the database, including after cancellation/failure.

```sh
curl -i http://localhost:8000/jobs \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: example-1' \
  -d '{"duration_ms":1000,"value":7}'
curl http://localhost:8000/jobs/JOB_UUID
curl 'http://localhost:8000/jobs?limit=20'
curl -X POST http://localhost:8000/jobs/JOB_UUID/cancel
```

| Route | Contract |
| --- | --- |
| `POST /jobs` | 201 new; 200 same key and canonical payload, with current job status; 409 different payload for existing key. Defaults participate in canonical equality. |
| `GET /jobs/{id}` | 200 job or 404. |
| `GET /jobs?limit=50&cursor=...` | `items` and nullable `next_cursor`; limit 1..100. Pass returned opaque cursor for next page. Ascending `(created_at,id)` keyset; live view, not a snapshot across pages. Late commits can be missed until a new traversal. |
| `POST /jobs/{id}/cancel` | 200 cancelled, including repeats; 409 already succeeded/failed; 404 missing. |
| `GET /health` | 200 after a database round trip, otherwise 503. It does not prove worker progress. |

All job responses include ID, canonical payload, state, attempts, generation,
timestamps, result, and error. Invalid input/UUID/cursor returns 422. Expected
errors use `detail`; request validation uses FastAPI's field-detail array. Database
availability/timeouts return 503 with `Retry-After: 1`; the outcome may be uncertain.
Retry creates with the **same key and payload**, and reconcile cancellation by ID.
Unexpected integrity failures remain visible server errors rather than fake success.

Payload fields are strict (no string-to-number coercion; unknown fields rejected):

| Field | Default | Allowed |
| --- | --- | --- |
| `duration_ms` | 100 | integer 0..60000 |
| `value` | 1 | integer -1000000..1000000; result is `{"squared_value": value²}` |
| `fail_attempts` | 0 | integer 0..4; those initial attempts fail transiently |
| `fail_permanently` | false | boolean; deterministic failure |

## How it works

See [DESIGN.md](DESIGN.md) for the transaction protocol and PostgreSQL references.
Every transition uses a short READ COMMITTED transaction and its own AsyncSession.
Workers claim with `FOR UPDATE SKIP LOCKED`, commit, and execute outside database
locks. Each process starts with a fresh owner UUID; each claim increments generation.
Heartbeat and completion lock the job, then sample PostgreSQL `clock_timestamp()`
and check ownership/generation/lease/deadline. Recovery and cancellation use the
same row lock. Cancellation can end computation later, but prevents its effect
from committing if cancellation wins the transaction race.

Defaults: 10-second lease, heartbeat every 3 seconds, 120-second attempt deadline,
0.2-second polling, recovery batches of 32, maximum five committed claims, and
1/2/4/8-second retry backoff before subsequent claims. The deadline caps heartbeat
renewal. `QUEUE_LEASE_SECONDS`, `QUEUE_HEARTBEAT_SECONDS`, `QUEUE_ATTEMPT_SECONDS`,
`QUEUE_POLL_SECONDS`, and `QUEUE_RECOVERY_BATCH` configure timing; inconsistent
settings fail startup. Local development uses `QUEUE_DATABASE_URL`.

The countable effect is one `job_effects` row inserted in the same transaction as
`succeeded`. A primary key prevents duplicate effects. **Exactly-once committed
database effect does not mean exactly-once execution.** Attempts may repeat or
overlap; successful jobs have one effect, failed/cancelled jobs zero. Logs distinguish
`claim_committed`, `execution_started`, `execution_finished`, and `effect_committed`.
A crash after commit but before logging may leave a committed effect without a log;
the database is authoritative. Stale work logs `ownership_lost`, never success.

Graceful SIGTERM/SIGINT cancels active computation and tries to requeue it under
its current lease. SIGKILL cannot run cleanup: the next healthy worker recovers the
expired lease. At attempt five, either path can finish failed. Unknown claim commits
are left to recovery; unknown completion commits are reconciled by reading status.

## Development and verification

Requires Python 3.11 and uv; runtime dependencies are locked in `uv.lock` and
hash-pinned `requirements.lock` (Docker uses the latter). Tests use a **dedicated
real PostgreSQL database**, truncate it between tests, and must not run concurrently
against the same test database. The fixture rejects database names not ending `_test`.

```sh
uv sync --frozen
# Start Postgres if the full stack is not already running:
docker compose up -d db
# Once per fresh database:
docker compose exec -T db createdb -U queue queue_test
QUEUE_DATABASE_URL=postgresql+asyncpg://queue:queue@localhost:55432/queue_test \
  python3 scripts/record.py uv run --frozen alembic upgrade head
python3 scripts/record.py uv run --frozen ruff check .
python3 scripts/record.py uv run --frozen ruff format --check .
python3 scripts/record.py uv run --frozen pytest -v -W error
```

Tests default to `postgresql+asyncpg://queue:queue@localhost:55432/queue_test`.
Set `TEST_DATABASE_URL` for another isolated PostgreSQL test database, and use the
same URL as `QUEUE_DATABASE_URL` for its migrations. No SQLite fallback or skipped
integration suite is provided. Tests force blocked transactions and use events,
separate sessions, real unique violations, backend termination, and post-commit
acknowledgement failure injection. The latter injects a client exception **after a
real commit**; it does not emulate a complete network partition.

Optional negative control (expected exit 1 and one failed regression test):

```sh
python3 scripts/record.py uv run --frozen python scripts/regression_probe.py
```

This disables generation fencing in that disposable Python process only. The
normal source and running workers remain unchanged.

Small actual HTTP/process smoke check, with the default four-worker stack running:

```sh
python3 scripts/record.py uv run --frozen python scripts/smoke.py
```

It submits 11 jobs, verifies replay/conflict, success/failure/cancellation, tests
one graceful stop and one SIGKILL/restart, and checks database effects. It temporarily
stops this project's workers, captures service logs, then restores four. It leaves
its uniquely keyed jobs as evidence. This is not the Phase 3 chaos harness.

## Repository and evidence

- `src/training_queue/`: schemas/config, database/models, centralized transitions,
  HTTP API, bounded execution simulation, and worker loop.
- `alembic/`: initial immutable migration, constraints, indexes, and update guard.
- `tests/`: API, concurrency, lease/fencing, atomicity, recovery, and fault tests.
- `scripts/`: raw-output recorder, small Compose smoke check, negative control.
- `artifacts/runs/<unique-id>/`: unedited stdout/stderr, command, platform, source
  hashes, Git state/diff, and exit code. Newer runs also include source archives.
- [VERIFICATION.md](VERIFICATION.md): actual results, failures, and evidence links.
- [AI_USE.md](AI_USE.md): honest AI assistance and verification boundaries.

Always use the recorder for later verification runs; never overwrite failed
results. It records selected safe database connection coordinates, not credentials
or the entire environment. Configure secret-free logging before running workloads.
The first implementation runs have source hashes/diffs rather than full source
archives. Snapshotting service logs before Compose recreation was added after the
first smoke run; its HTTP/command output is retained, but its old worker containers'
full logs were not captured. This evidence gap is not retrospectively filled.

## Limitations and production verdict

The measured scope and production verdict are in [REPORT.md](REPORT.md). The
simulation asynchronously waits and squares an integer; it does not measure real
CPU/GPU training, external effects, or shared resource capacity. Authentication,
rate limiting, key expiry, and retention are out of scope. Direct privileged SQL
can bypass the shared cross-table transition protocol; this is a trusted application
with development database credentials, not a hardened multi-tenant deployment.
Single-Postgres durability/failover, clock jumps on the database host, arbitrary
partitions, unfair scheduling/starvation, and every possible interleaving remain
unproven. Client clock offsets cannot authorize leases; a DB wall-clock jump can
change recovery timing. Pagination is not a consistent snapshot across requests.

## Reproduce Phase 3 experiments

The experiment scripts require invocation through `scripts/record.py`. They use
only their specified Compose project and unique key namespaces; they never delete
existing jobs or volumes. Use a separate project to preserve Phase 2 data:

```sh
export QUEUE_API_PORT=18000 QUEUE_DB_PORT=55433
python3 scripts/record.py docker compose -p queue-phase3 up --build -d --wait
python3 scripts/record.py docker compose -p queue-phase3 \
  -f compose.yaml -f compose.eight.yaml up -d --wait --no-build
python3 scripts/record.py uv run --frozen python -m scripts.chaos --seed 1101
python3 scripts/record.py uv run --frozen python -m scripts.chaos --seed 2202
python3 scripts/record.py uv run --frozen python -m scripts.chaos --seed 3303
python3 scripts/record.py uv run --frozen python -m scripts.zombie --seed 5505
python3 scripts/record.py uv run --frozen python -m scripts.load --seed 4404
```

Run those commands sequentially. The tested service is http://localhost:18000;
the scripts default to PostgreSQL on localhost:55433. If overriding the project,
ports, or database, pass matching `--project`, `--base-url`, and database configuration.
`QUEUE_DATABASE_URL` overrides the experiment database address, so do not leave it
pointing at a test database or another stack. Containers are label-checked before
faults; SIGKILL targets the Python worker child and verifies a new boot UUID and
restart count. SIGSTOP/SIGCONT in the zombie check exercises a returning live process.

A full chaos run creates 10,000 distinct intended jobs; `--jobs 300 --create-rps 50`
is a small pilot, not a full run. Default full runs create at a target 200/sec,
run completion-paced replay/conflict traffic up to 50/sec, and target up to two
queued and one running cancellation every 0.5 s. Secondary traffic slows under
load. Exactly eight worker slots are maintained, with measured brief restart gaps.
Kill scheduling can slip while replacement is pending. Seeds reproduce payloads
and random choices, not every OS/transaction interleaving. Workload distributions,
drain formula, and predeclared load criteria are in [EXPERIMENTS.md](EXPERIMENTS.md).

The load test offers 100 HTTP requests/sec for 120 seconds. Its mix is 40% creates,
20% status, 10% list, 10% cancel, 10% replay, and 10% conflicting replay; retries
count toward offered traffic. Twenty setup jobs are excluded from measured rate.
API request throughput and worker job throughput are reported separately.

Each experiment retains compressed unedited HTTP/service/fault/telemetry streams,
intended manifests, read-only database snapshots, configuration/environment,
assertions, and summary. Read with `gzip -cd FILE.jsonl.gz`. `summary.json` contains
the final outcome; intermediate console events are not the final verdict.

For a separate integration-test database on the Phase 3 PostgreSQL server:

```sh
# Create once; an existing-database error means this step is already done.
python3 scripts/record.py docker compose -p queue-phase3 exec -T db \
  createdb -U queue queue_phase3_test
QUEUE_DATABASE_URL=postgresql+asyncpg://queue:queue@localhost:55433/queue_phase3_test \
  python3 scripts/record.py uv run --frozen alembic upgrade head
TEST_DATABASE_URL=postgresql+asyncpg://queue:queue@localhost:55433/queue_phase3_test \
  python3 scripts/record.py uv run --frozen pytest -v -W error
```

[artifacts/INDEX.md](artifacts/INDEX.md) indexes every Phase 2 and Phase 3 recorded
run, including failures. Regenerate derived summaries with:

```sh
python3 scripts/record.py uv run --frozen python -m scripts.summarize_experiments
uv run --frozen python -m scripts.index_evidence
python3 scripts/record.py uv run --frozen python -m scripts.verify_evidence
```

The report includes the failure-analysis matrix, exact counts, performance metrics,
limitations, reflection, and prioritized fixes. The live discussion was cancelled
according to the user's latest Soup email update. No submission email or PR has
been sent/opened. Phase 3 ends for review before submission.
