# AI assistance: Phase 2

AI assistance is allowed by the Soup assignment. This file describes what happened
in this collaboration; it does not claim that the developer independently reviewed
or verified the generated implementation.

## Scope of assistance

Codex read the Phase 2 request, approved DESIGN.md, README.md, repository/history,
and the complete assignment PDF previously read in Phase 1. It drafted the models,
Alembic migration, guarded transitions, Pydantic schemas, API, simulation, worker,
Compose setup, tests, evidence recorder, smoke check, and documentation. It ran the
commands whose raw output is retained in `artifacts/runs/` and prepared the commits.

The user approved the Phase 1 architecture. Phase 2 retained PostgreSQL row locks,
READ COMMITTED, database time after locking, leases with owner/generation fencing,
and atomic success/effect commits. Implementation choices added here include a
bounded typed simulation payload, database update guards, explicit session cleanup
around transaction cleanup, hash-pinned runtime dependencies, pinned container
images, and Compose init processes. DESIGN.md documents these refinements.

Primary documentation consulted: PostgreSQL's
[READ COMMITTED visibility rules](https://www.postgresql.org/docs/18/transaction-iso.html#XACT-READ-COMMITTED),
SQLAlchemy's [concurrent session guidance](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html#using-asyncsession-with-concurrent-tasks),
Docker's [startup dependencies](https://docs.docker.com/compose/how-tos/startup-order/),
[restart policies](https://docs.docker.com/engine/containers/start-containers-automatically/),
and [Compose init](https://docs.docker.com/reference/compose-file/services/#init),
plus the Linux [PID namespace manual](https://man7.org/linux/man-pages/man7/pid_namespaces.7.html).

## Corrections and evidence

AI-generated work needed corrections. The first install failed because Hatch
could not infer the package directory. The first Compose start failed because
`Queue.list` shadowed the built-in `list` during Python 3.11 annotation evaluation.
Ruff found import/style/formatting errors. These were corrected, with their original
outputs kept.

The first passing test suite emitted connection-leak warnings after injected lost
commit acknowledgements. Session cleanup was moved outside transaction cleanup;
subsequent suites passed with warnings promoted to errors. This exercised a real
PostgreSQL commit followed by an injected client exception, not a real network
partition. A separate test terminates an actual database backend before commit.

Three initial smoke runs failed in their termination checks: the in-namespace PID 1
signal did not kill the worker; a Docker kill suppressed restart as a manual stop;
and the corrected worker-child kill also killed the attached exec process with
exit 137, which the driver initially rejected. The fourth run passed after those
driver assumptions were corrected. See VERIFICATION.md and the raw logs. No failed
run was removed or rewritten. An explicit negative control disabled generation
checks in an isolated Python process and made the zombie regression fail.

## Verification boundaries

Codex verified the recorded automated tests and a small actual HTTP/Compose run.
This does not establish production readiness, 100 requests/sec capacity, full chaos
survival, database failover durability, or the behavior of real training work. No
benchmark or 10,000-job harness output was invented. No SHIP verdict was written.
The user reported cancellation of the live discussion; no email was accessed or
sent. Developer review and explanation of the protocol are still needed before
Phase 3, including independent checks the developer chooses to perform.

An engineering observation from this phase: a successful command to send a signal
does not establish that the intended worker died. Checking process restart and
claim generation was necessary to make the smoke result meaningful. Likewise, a
passing test count with cleanup warnings was insufficient evidence of correctness.
