# Phase 2 verification

All times inside raw artifacts are UTC; work occurred November 10, 2026. This is
core-service verification, not a benchmark, production verdict, or full chaos run.
Source commits: `d1b6111` (persistence/transitions) and `02f49fd` (API/workers/Compose).
Earlier runs were against the dirty Phase 1 checkout; metadata contains source
hashes and Git state/diffs, with source archives added during the phase. The final
suite records source commit `02f49fd` and the then-current test hashes.

Environment: macOS arm64; local Python 3.11.9; PostgreSQL 18.6 in Docker;
Docker Engine 28.3.2; Compose v2.38.2-desktop.1. The actual Docker/runtime build
versions and image digests appear in raw build logs. Resolved Python dependency
versions are in [the freeze output](artifacts/runs/20261110T101532.234047Z-5c54648d/stdout.txt)
and the lockfiles. The API/worker runtime uses Python 3.11 in the pinned image.

## Final automated checks

| Command | Actual result | Raw output |
| --- | --- | --- |
| `uv run --frozen ruff check .` | exit 0, All checks passed | [stdout](artifacts/runs/20261110T101647.335080Z-8827d701/stdout.txt) |
| `uv run --frozen ruff format --check .` | exit 0, 20 files already formatted | [stdout](artifacts/runs/20261110T101647.691448Z-c087703c/stdout.txt) |
| `uv run --frozen pytest -v -W error` | exit 0, **31 passed in 1.49 s**, no warnings | [stdout](artifacts/runs/20261110T101735.945497Z-a76457c3/stdout.txt), [stderr](artifacts/runs/20261110T101735.945497Z-a76457c3/stderr.txt) |
| Clean `queue_test` database: `uv run --frozen alembic upgrade head` | exit 0 | [run](artifacts/runs/20261110T100934.692439Z-6d1b47cb/) |
| `uv run --frozen alembic check` against `queue_test` | exit 0, no new upgrade operations | [stdout](artifacts/runs/20261110T101156.884850Z-ca812218/stdout.txt) |
| `uv run --frozen alembic current --verbose` | exit 0, revision 0001 (head) | [stdout](artifacts/runs/20261110T101756.671658Z-eb107395/stdout.txt) |

Each command was invoked through `python3 scripts/record.py`; relevant database
overrides are captured without credentials in its metadata. Migration used a
newly created real database, not ORM `create_all` or SQLite. Default Compose also
ran the migration successfully during its first initialization.

The suite covers concurrent claims, skipping held row locks, simultaneous duplicate
POSTs and conflicting payloads, a blocked conflicting INSERT followed by a fresh
snapshot, duplicate/stale/wrong-owner completion, both actual cancel/complete lock
orderings, expired heartbeat rejection, recovery sweepers, retry exhaustion/backoff,
atomic rollback on either state/effect failure, immutable payload/terminal guards,
DB-clock authorization after lock waits, deadline capping, simulation, shutdown,
cancellation, post-commit uncertainty, real backend termination, bounded retries,
and status/pagination/validation endpoints. Events pause the real winning transition
while `pg_stat_activity` confirms the loser is blocked.

Retry plumbing tests use PostgreSQL-raised SQLSTATEs; they do not create a genuine
multi-row deadlock. Application clock authorization is tested with a poisoned
local wall clock; PostgreSQL host clock changes are not tested. A deterministic
negative control removes generation checking only in a disposable process:
`uv run --frozen python scripts/regression_probe.py` exited 1 with **one failed
zombie test**, as intended. [Raw failure](artifacts/runs/20261110T101018.246049Z-67681a26/stdout.txt).

## Actual Docker, HTTP, and database checks

`docker compose up --build -d --wait` built the images, initialized PostgreSQL,
completed migrations, started the API, and ran four worker containers.
[Successful startup](artifacts/runs/20261110T101519.640811Z-6af2b06f/).
The eight-worker override also started successfully, and an assertion counted
exactly eight running worker containers. [Startup](artifacts/runs/20261110T101659.947682Z-a3714ad8/),
[count](artifacts/runs/20261110T101734.087362Z-a5f8b677/stdout.txt).
Default configuration restored four workers. [Restore output](artifacts/runs/20261110T101734.774364Z-4bf22fd5/).

The small HTTP/process smoke check was attempted **four times: three failed driver
runs, one passing run**. These are not full chaos runs. The passing command,
`uv run --frozen python scripts/smoke.py`, exited 0. It confirmed health, creation
(201), same-key replay (200), payload conflict (409), status/list, cancellation,
six ordinary successes, one permanent failure, one transient retry, graceful
release/retry, and abrupt worker death/restart/recovery. Its 11 jobs finished as
**9 succeeded, 1 failed, 1 cancelled, with 9 effect rows**.
[Full raw HTTP, commands, and service logs](artifacts/runs/20261110T101625.446762Z-8c7acb0f/).

SIGTERM requeued the active job with no effect and it later succeeded on attempt 2.
SIGKILL of the Python child left the job running on generation 1; Docker restarted
the container (RestartCount increased), recovery requeued its expired lease, and
generation 2 succeeded with one effect. The kill step's exec exit 137 is expected
because the container's init exits when its child dies; the driver still separately
asserts restart, generation, state, and effect invariants.

A subsequent REPEATABLE READ, read-only snapshot accounted for **all 44 jobs**
created across the four smoke attempts: 36 succeeded, 4 failed, 4 cancelled,
36 effects, 0 state/effect mismatches, 0 stale-generation/result mismatches,
and no queued/running jobs. Every row and per-job effect count is retained.
[Raw SQL and results](artifacts/runs/20261110T101756.217730Z-f8c10d44/stdout.txt).
This is evidence for this small workload, not proof for arbitrary failures or load.

## Failures and limitations retained

- [First dependency installation](artifacts/runs/20261110T100250.982787Z-53a9389c/)
  failed package discovery; explicit Hatch package selection fixed it.
- [First Compose start](artifacts/runs/20261110T100808.668797Z-bcb2b127/)
  failed API health. [Service logs](artifacts/runs/20261110T100933.920869Z-19ce8648/)
  exposed the `list` annotation shadowing; renaming the method fixed import.
- [First suite](artifacts/runs/20261110T100946.737967Z-ac8aff00/)
  passed 31 tests but emitted two connection cleanup warnings. Moving explicit
  session cleanup outside transaction exit fixed them; later suites used `-W error`.
- [First smoke](artifacts/runs/20261110T101155.739813Z-b6f72927/)
  signalled PID 1 from inside its namespace and did not kill the worker. Its
  unchanged-generation assertion failed. Full old worker logs were not captured
  before the restore recreated containers; HTTP and command output remains.
- [Second smoke](artifacts/runs/20261110T101314.152457Z-a0ec3cfa/)
  used Docker kill, suppressing automatic restart as a manual stop. With all other
  workers intentionally stopped, the wait timed out. Cleanup restored healthy
  workers, which later recovered the job. Service logs were preserved before restore.
- [Third smoke](artifacts/runs/20261110T101549.363304Z-763fb03c/)
  correctly killed the worker child, but incorrectly treated attached exec exit
  137 as an unexpected driver error. The fourth run accepts that code solely for
  the kill command and verifies actual recovery.
- All Ruff failures and intermediate positive runs remain in the
  [complete run index](artifacts/INDEX.md). An earlier positive suite and the
  negative control were launched close together against the shared test database;
  the final authoritative suite ran separately. Run test commands sequentially.

No known unresolved core failure was observed in the final checks. This is not
a claim that there are no bugs. Full repeated chaos, real network partitions,
DB clock jumps/failover/durability, retention/security hardening, and measured
100 requests/sec behavior remain unverified. The real-work execution and latency/
error/backlog acceptance thresholds must be specified before the Phase 3 verdict.
