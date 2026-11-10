# training-job-queue
Fault-tolerant training job queue with FastAPI, PostgreSQL, and concurrent workers.

Phase 1 contains a proposed [design](DESIGN.md), with no application code yet.
There are no endpoints, workers, migrations, Compose configuration, or test/chaos
results. `docker compose up` is the planned startup command; it does not work yet.

## Assignment and starting point

Read the complete one-page `Soup-Task-04-Backend-Engineer(1).pdf` supplied locally
from Downloads on November 10, 2026. It is not copied into this repository.
The PDF requests design before code, at least four workers, 10,000-job chaos runs
with eight workers, raw output including failures, a 100 requests/sec verdict,
reflection, AI disclosure, and a later live discussion. It permits any stack and
Postgres or SQLite and gives a relative 48-hour deadline. The user's explicit
Python/PostgreSQL stack and **November 11, 2026, 22:10 Asia/Almaty (UTC+05:00)**
deadline govern this collaboration. The document's email submission instruction
is a deliverable requirement, not authorization to send an email in Phase 1.

Initial inspection: clean `main` at `b07000e`, matching the remote tree; only this
short README and a general Python `.gitignore` were tracked. No application,
dependency manifest, tests, database setup, or repository/ancestor `AGENTS.md`
was found. Phase 1 changes only this README and adds DESIGN.md; `.gitignore`
remains unchanged.

Unspecified by the assignment: exact payload/result schema and simulated job
duration, endpoint paths/status codes, retry/lease settings, key retention/scope,
cancellation race policy, pagination consistency, authentication, and performance
acceptance thresholds/environment. DESIGN.md proposes the concurrency policies;
the initial payload will be a small validated simulation configuration, with its
exact fields and workload distribution agreed before implementation. Lease and
attempt limits require validation against that workload. A finite retry budget
means a repeatedly killed job may legitimately finish failed; "no lost jobs"
means every committed job is accounted for, not that every job succeeds.

## Proposed structure and setup roadmap

```text
src/training_queue/
  api.py, schemas.py, config.py    # HTTP contract and configuration
  db.py, models.py                 # engine/sessions and persistence model
  transitions.py                  # all guarded job/effect transactions
  worker.py, execution.py          # process loop and bounded simulation
alembic/                          # schema, constraints, indexes
tests/                            # unit, real-Postgres integration, concurrency
scripts/chaos.py                   # workload, process kills, reconciliation
artifacts/runs/<run-id>/           # immutable raw evidence and run metadata
compose.yaml, Dockerfile, pyproject.toml, dependency lockfile
DESIGN.md, README.md, REPORT.md, AI_USE.md
```

1. **Review this design.** Stop here in Phase 1; confirm the missing workload and
   acceptance details before building it. No application or performance tests
   have been run, and there is no evidence to support a SHIP claim.
2. **Persistence and startup.** Add pinned dependencies, Alembic migrations,
   constraints, transaction functions, and Compose. Postgres health precedes a
   single migration service; successful migration precedes API/four independent
   worker processes. Persist database data and configure worker restarts. Document
   fresh setup and an override that starts exactly eight workers for chaos.
3. **API and execution.** Add create/status/list/cancel, the worker loop, heartbeat,
   recovery, and bounded simulation. Test against real Postgres, never SQLite as
   a substitute for locking behavior. Give each process its own bounded pool and
   each concurrent coroutine its own session; budget API, worker, and harness
   connections against the database limit.
4. **Deterministic failure checks.** Use barriers and separate sessions/processes
   to force simultaneous claims; kill before/after claim/effect/commit; resume an
   expired worker after a newer claim; exercise both cancel/complete orderings,
   concurrent same/different-payload key retries, heartbeat/recovery races, retry
   exhaustion, and READ COMMITTED visibility after an INSERT conflict. Verify
   application clock offsets do not affect leases, and test DB-clock jumps in an
   isolated environment if feasible; otherwise disclose that gap. Exercise a hung
   attempt, database disconnects/unknown commit outcomes, and transaction timeouts.
5. **Chaos and load evidence.** Create 10,000 distinct intended jobs, eight live
   worker slots, random SIGKILL roughly every two seconds with replacement, while
   replaying keys and cancelling jobs concurrently. Record seed, scheduling and
   actual kill times, request outcomes, worker boot UUID/generation/claim events,
   and database transition outcomes. Track intended keys separately from HTTP
   acknowledgements and reconcile ambiguous requests by retrying the same keys.
   After injection ends, let survivors drain within a documented timeout derived
   from workload, leases, and retry budget; timeout is a failed run. In one database
   snapshot assert every intended key maps to exactly one job, every acknowledged
   ID exists, all jobs are terminal, each succeeded job has exactly one effect,
   and every other job has zero. Verify cancelled acknowledgements stay cancelled,
   effects reference the winning generation, and no stale generation committed.
   Logs distinguish overlapping execution from multiple valid ownership claims.
6. **Verdict and reflection.** Run repeatable 100 HTTP requests/sec tests with a
   stated create/read/list/cancel mix, duration, hardware, execution durations,
   and whether retries count toward offered load. Report achieved throughput,
   errors, p50/p95/p99, queue growth/drain, DB/pool pressure, and recovery latency.
   Agree latency/error/backlog thresholds before judging. Report SHIP/DON'T SHIP
   with evidence and first fixes; record surprises, concerns, harness blind spots,
   and number of all attempted runs. Do not prewrite live-discussion answers.

## Evidence and AI use

Before every later lint/test/benchmark/chaos invocation, allocate a unique run
directory and capture command, commit, dirty diff, configuration, dependency
versions, environment/hardware, seed, timestamps, exit code, and unedited
stdout/stderr (including failures and interrupted runs). Preserve service logs,
request history, and invariant-query output; keep derived summaries separate.
Use `.txt`/`.jsonl` because the existing `.gitignore` ignores `*.log`. Ensure raw
artifacts are tracked or durably archived and linked; never overwrite or delete
failed evidence. Disable secret logging at the source rather than edit results.
The harness cannot prove every interleaving, arbitrary network partitions,
failover/disk durability, real training behavior, or performance on other hardware.

Phase 1 used Codex to inspect the repository, extract and visually review the full
PDF, consult PostgreSQL documentation, and draft these files. Proposed accepted
design choices are row locks, leases with generation fencing, and an atomic
database effect/success commit. Only document/repository consistency is reviewed
in this phase; runtime correctness and performance remain unverified. No personal
verification by the developer is claimed. Later AI_USE.md should record suggestions
accepted/rejected, human checks, and changes or rework as they actually happen.
