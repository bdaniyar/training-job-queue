# AI assistance: Phases 2 and 3

AI assistance is allowed by the Soup assignment. This file distinguishes Codex's implementation and automated verification from the developer's subsequent manual checks. It does not claim independent authorship of AI-generated code, independent reruns of the full chaos/load suite, or broader production certification.

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
sent. At the end of Phase 2, independent developer verification remained to be performed; the developer's later manual checks are recorded below.

An engineering observation from this phase: a successful command to send a signal
does not establish that the intended worker died. Checking process restart and
claim generation was necessary to make the smoke result meaningful. Likewise, a
passing test count with cleanup warnings was insufficient evidence of correctness.

## Phase 3 assistance and verification

Codex reread the complete original PDF, Phase 2 documents/code/tests/recorder, and
created the Phase 3 branch from the supplied Phase 2 commit. It implemented the
seeded HTTP/SIGKILL harness, read-only snapshot oracle, open-loop load generator,
live SIGSTOP/SIGCONT zombie check, helper tests, summary/index tools, and reports.
It ran all recorded automated checks and experiments. The developer separately performed the exploratory checks recorded below, but did not rerun the full automated, chaos, or load-testing suites.

The transaction protocol and deployed application code were retained. Three full
10,000-job chaos runs passed their final invariants. One smaller pilot showed that
aggressive cancellation preempted every transient retry, so cancellation intensity
was reduced before full runs to exercise retries and longer work more meaningfully.
The pilot is retained, not counted as a full run. Four create transport errors in
seed 2202 were reconciled by same-key retries; their root cause remains unproven.
The report treats them as an availability warning, not a concurrency fix or a
fabricated network-partition test. No application exception was found at those
times in captured logs. Deliberately induced SQL errors in the integration-test
database are identified separately from chaos failures.

Additional corrections addressed Ruff findings, load-task exception collection,
HTTP-response versus attempt-completion counting, safe environment/inspect capture,
and event-driven waiting for the resumed worker's ownership-lost log. The recorder
now passes an evidence-directory path to experiments and records selected relevant
configuration/dependency versions. Compressed raw streams remain separate from
derived summaries; previous raw artifacts were not rewritten.

The production verdict and actual load measurements are in REPORT.md. Any
interpretation of the four transport failures, harness overhead, or production
capacity beyond the measured workload is explicitly limited. Database clock jumps,
real network partitions, failover durability, and realistic CPU/GPU training remain
untested. The user's update cancelling the live discussion governs over the PDF's
older statement. At the end of Phase 3 no email or PR had been sent/opened; subsequent submission preparation is separate from the recorded experiment evidence.

## Independent developer manual walkthrough (November 10, 2026)

After Codex completed Phase 3, the developer independently interacted with the
running FastAPI service through Swagger UI (`http://localhost:8000/docs`), including
creation/status inspection, idempotency-key replay/conflict, a successful job, a
cancellation, and a transient-retry scenario. The developer also opened the real
Docker Compose PostgreSQL database using `psql` and inspected both `jobs` and
`job_effects` with their own SQL queries.

The developer-supplied terminal transcript directly confirms:

- `manual-test-001`: `succeeded`, attempts/generation `1/1`, committed
  effect `{\"squared_value\": 49}`.
- `manual-cancel-001`: `cancelled`, no committed effect row.
- `manual-retry-001`: `succeeded` at generation 2, committed effect
  `{\"squared_value\": 25}`.

The developer discussed and reviewed the key ideas behind the implementation:
separating HTTP ingestion from independent workers, durable queue state in
PostgreSQL, atomic result/state commits, row locks for competing transitions,
and leases/recovery for worker failures. This is a conceptual review, not a claim
of a full independent source-code audit or authorship.

The exact SQL commands and copied observed rows are preserved in
[MANUAL_VERIFICATION.md](MANUAL_VERIFICATION.md). The Swagger results were observed
interactively, not exported as raw machine-readable artifacts. The chaos,
performance, automated concurrency, and SIGKILL tests were run by Codex and are
reported separately with raw evidence. No unperformed verification is attributed
to the developer.
