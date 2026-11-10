# Training job queue — submission design note

A Python/FastAPI modular monolith uses PostgreSQL for both queue state and the
countable side effect. Independent worker processes share the same transition
module. Compose starts PostgreSQL, one Alembic migration service, the API, and
four workers by default; an override runs eight. No second broker is needed.

**Data and request identity.** Each job stores an immutable validated simulation
payload, a unique idempotency key, state, attempts, claim generation, owner UUID,
lease/deadline timestamps, result/error, and lifecycle timestamps. A separate
`job_effects` row, keyed uniquely by job ID, is the actual durable effect.
Concurrent creates use `INSERT ... ON CONFLICT DO NOTHING`; a subsequent READ
COMMITTED statement reads the committed winner. Equal canonical payloads return
that job; conflicting payloads return 409. Keys are retained indefinitely.

**Claim and ownership.** A short READ COMMITTED transaction selects eligible queued
work with `FOR UPDATE SKIP LOCKED`. After locking, it samples PostgreSQL's
`clock_timestamp()`, increments attempts and generation, assigns a process-start
UUID, and commits running ownership. Training starts only after commit and holds
no database locks. Each concurrent operation has its own AsyncSession.

**Leases and recovery.** The initial lease is 10 seconds, renewed every 3 seconds
only by the current owner/generation while unexpired, capped by a 120-second
attempt deadline. Workers sweep expired leases under the same row-lock protocol.
An expired job is requeued with backoff; the fifth exhausted claim becomes failed.
A lease detects silence, not death. A resumed old worker cannot renew an expired
lease or publish a stale result after a newer generation takes ownership. Client
wall clocks never decide lease validity; database clock jumps remain a limitation.

**Completion and cancellation.** Completion locks the job, samples fresh database
time, and checks state, owner, generation, lease, and deadline. It inserts the
unique effect and marks succeeded in one transaction. Cancellation locks the same
row and immediately marks queued/running work cancelled. If cancellation commits
first, later completion is rejected; if success commits first, cancellation returns
409. Terminal rows are immutable. Computation may stop after cancellation, but
cannot commit its effect. Database constraints guard uniqueness and row shape;
cross-table consistency depends on this shared transaction protocol.

**Crash boundary and guarantee.** Before commit, all writes roll back. After claim
commit, abandoned work needs lease recovery. After completion commit, success and
effect survive even if the acknowledgement is lost. Unknown outcomes are read
back or retried by the original idempotency key; they are never assumed rolled
back. Execution can repeat or overlap. The guarantee is **exactly one committed
PostgreSQL effect for each succeeded job**, zero for failed/cancelled jobs—not
exactly-once execution or external API/file effects. Liveness assumes available
PostgreSQL and healthy/restarted workers. Tests and production limits are in
[REPORT.md](REPORT.md); the full retained design is [DESIGN.md](DESIGN.md).
