# Training job queue: Phase 1 design

**Implemented in Phase 2; capacity remains unmeasured.** Python 3.11+, FastAPI, async SQLAlchemy,
PostgreSQL, Alembic, pytest, Ruff; one modular monolith with independent worker
processes. PostgreSQL provides row locking and atomic effect/state commits in one
store; Redis/Celery would add another coordination boundary without a requirement.
Compose will start Postgres, one migration service, the API, and four workers;
chaos configuration uses eight. Work is bounded simulated computation outside transactions.

## Model and invariants

`jobs`: UUID `id`, globally unique nonempty `idempotency_key`, validated immutable
JSONB `payload`, `state`, `attempts` (initially 0), `generation` (initially 0),
nullable `owner` (UUID per worker process start), `lease_until`, `attempt_deadline`,
`available_at`, `created_at`, `updated_at`, nullable `finished_at`, result/error.
All timestamps are `timestamptz`. Checks restrict states to queued/running/succeeded/
failed/cancelled, attempts to 0..5, and nonnegative generation; ownership and both
deadlines exist iff running, and `finished_at` exists iff terminal. Partial indexes
cover queued `(available_at, created_at, id)` and running `(lease_until, id)`;
`(created_at, id)` supports listing.

`job_effects`: `job_id` primary key/FK to jobs, winning generation, result, database
commit-operation timestamp. One inserted row is the actual countable effect;
timestamps are not asserted to be exact commit times. No job/key/effect deletion
or key expiry in this assignment.

Committed invariants: one job per key; at most one effect per job; succeeded iff one effect
exists; queued/running/failed/cancelled have zero effects; terminal states never
change; only the current owner/generation with a valid lease may finish or report
an execution error. Recovery instead requires an expired lease.
Uniqueness is database-enforced; cross-table consistency depends on the shared
transaction protocol below. No arbitrary application writes bypass that protocol.

## Transaction protocol

Use **READ COMMITTED**, short transactions, and a separate AsyncSession per task.
Every existing-job mutation locks that job first (`FOR UPDATE`), reads its current
state, then samples PostgreSQL `clock_timestamp()` in a subsequent statement and
rechecks guards. Never authorize from cached ORM state, client time, or `now()`
(which is frozen at transaction start). Configure lock/statement/idle-transaction
timeouts; rollback on errors. Locks serialize decisions for each job; they are
never held during simulated training.

| Operation | Under the job lock, then commit |
| --- | --- |
| Claim | Select one eligible queued row ordered by available time/creation/id with `LIMIT 1 FOR UPDATE SKIP LOCKED`; recheck eligibility and attempts < 5 using fresh DB time. Increment attempts and generation, set running/owner, deadline = time + 120 s, lease = time + 10 s. Execute only after commit. |
| Heartbeat | Every ~3 s, require running, matching owner/generation, lease > DB time and deadline > DB time. Extend lease to min(time + 10 s, deadline). Zero matching rows means stop/discard work; an expired lease cannot be revived. |
| Complete | Require the same ownership/time guards. Insert the effect with a plain INSERT and set succeeded/result/finished time, clearing ownership/deadlines, **in one transaction**. An unexpected unique conflict rolls everything back and is reported, never hidden as success. |
| Error | With the same guards, deterministic errors or attempt 5 become failed; transient errors become queued with DB-time backoff `min(2^(attempts-1), 30)` seconds. Clear ownership/deadlines; insert no effect. |
| Recover | Each worker polls expired running rows in bounded `SKIP LOCKED` batches before claiming; recheck expiry under lock. Requeue with the same backoff, or mark failed at attempt 5. Clear ownership/deadlines; insert no effect. Concurrent sweepers are safe. |
| Cancel | Lock queued/running job, set cancelled/finished time and clear ownership/deadlines. Already cancelled is a successful repeat; succeeded/failed returns conflict; missing returns 404. No lease required for client cancellation. |

Expiry makes recovery eligible; a finishing transaction that already validated
its lease under lock may commit after wall-clock expiry. Recovery cannot change
ownership while that lock is held. A lease detects silence, not death. The
generation fences a returning zombie even
if a process name is reused. The 120 s cap prevents heartbeats from preserving a
hung attempt forever. These are initial tuning values, not measured guarantees.

Cancellation is immediate in the database; computation may stop later but cannot
commit an effect. Cancel and complete contend on the same row: whichever commits
first decides the terminal outcome. Rejected/stale operations have no side effects.

## Requests and crash recovery

Create validates/canonicalizes payload, then `INSERT ... ON CONFLICT (idempotency_key)
DO NOTHING RETURNING id`. On conflict, a **separate statement** reads the winner
at READ COMMITTED: identical canonical payload returns the same job (201 new,
200 replay with current status); different payload returns 409. Never overwrite
payload or precheck uniqueness. Respond only after commit. GET returns committed
status or 404. List uses a bounded keyset cursor `(created_at, id)`; it is a live
view, not a snapshot across pages (late commits can be missed until a new traversal).

Crash before any commit rolls back that transaction. After claim commit, a crash
leaves a lease that another worker recovers. After computation but before completion
commit, there is no effect and work may repeat. Completion commit persists both
effect and success, even if the acknowledgement is lost; reconnect/read state
before deciding what to do, including ownership checks after an uncertain claim
commit. Lost create/cancel acknowledgements are retried by
key/job ID. Retry deadlock/serialization failures at most three times with jitter
in a fresh transaction; ambiguous commits require reconciliation, not blind replay.

**Exactly-once committed database effect is not exactly-once execution.** Attempts
may overlap or repeat; successful jobs have exactly one effect, failed/cancelled
jobs none. Liveness requires available Postgres and a surviving/restarted worker;
finite retries eventually fail repeatedly crashing jobs rather than lose them.
External file/API effects are outside this guarantee. Worker clock skew does not
decide ownership; DB clock jumps can affect recovery timing, while locking and
fencing still prevent competing commits. Single-DB durability/failover and load
capacity remain unproven. Structure, validation phases, and evidence policy follow
in [README.md](README.md).

## Phase 2 implementation details

The architecture above is retained. The simulation payload is strict and immutable:
`duration_ms` (0..60000, default 100), `value` (-1000000..1000000, default 1),
`fail_attempts` (0..4, default 0), and `fail_permanently` (default false). Execution
asynchronously waits, optionally reports a transient/permanent failure, and returns
`squared_value`. It performs no durable writes; only guarded completion inserts
the effect. This bounded simulation does not represent CPU/GPU training performance.

Additional database guards reject changes to job identity, payload, creation time,
or a terminal row. Checks require generation = attempts, running attempts > 0,
queued attempts < 5, lease <= deadline, and result iff succeeded. These strengthen
the approved invariants without moving concurrency decisions out of PostgreSQL.

SIGTERM/SIGINT stop claims and cancel execution/heartbeat tasks, then attempt a
guarded transient failure/requeue (or fail at attempt 5); abrupt death leaves the
lease for recovery. Both consume the already-committed claim attempt. An uncertain
claim is conservatively abandoned to recovery rather than executed; an uncertain
completion is read back and logged. Only PostgreSQL-guaranteed transaction aborts
are automatically retried. Session cleanup encloses transaction cleanup so a commit
exception cannot bypass connection return. Queue timing settings are configurable,
with heartbeat < half the lease and deadline >= lease; five claims remains a DB constraint.
Compose uses `init: true` for signal forwarding/reaping. It also permits the smoke
check to kill the Python child rather than signal a protected PID-namespace init
or deliberately stop the container through Docker (which suppresses restart).

Protocol references: PostgreSQL [queue locking](https://www.postgresql.org/docs/18/sql-select.html#SQL-FOR-UPDATE-SHARE),
[READ COMMITTED conflict visibility](https://www.postgresql.org/docs/18/transaction-iso.html#XACT-READ-COMMITTED),
and [database clocks](https://www.postgresql.org/docs/18/functions-datetime.html#FUNCTIONS-DATETIME-CURRENT).
