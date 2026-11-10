# Soup training-job queue — Phase 3 report

## 1. Executive summary

**Production verdict: DON'T SHIP for an unrestricted 100 RPS production workload.**
The bounded simulation service passed three full 10,000-job chaos runs and the
predeclared two-minute 100 RPS mixed HTTP workload. That supports this tested
profile, not arbitrary training duration, request mixes, or database failure modes.
Four unexplained HTTP transport errors during one chaos run also need investigation.

Full chaos totals: **30,000 jobs; 72 SIGKILLs and verified restarts; 598 retries;
630 cancelled; 296 failed; 29,074 succeeded/effect rows; zero invariant failures.**
All 296 failures were intentionally configured permanent failures. No full run
failed or timed out. The separate 300-job pilot, live zombie check, and load run
are counted separately below. Every earlier Phase 2 failure remains retained.

The measured load dispatched all 12,000 scheduled requests: **99.982 dispatched
RPS, 99.980 completed RPS, p50/p95/p99 4.55/7.96/22.50 ms, zero unexpected errors or
timeouts**, maximum active queue depth 21, and 1.04 s post-load drain. All declared
criteria passed. The live discussion was cancelled per the user's latest email
update; at the time of these experiments, no email submission or PR had been made.

## 2. System architecture and delivery semantics

FastAPI and independent Python workers share PostgreSQL and one guarded transition
module. Claims use READ COMMITTED and row locks with SKIP LOCKED. A committed claim
assigns a process-start UUID and increasing generation. All ownership decisions use
database time sampled after locking. Heartbeats renew only current unexpired
leases, capped by an attempt deadline. Other workers recover expired leases.

Completion inserts the unique job effect and marks success in one transaction.
Cancellation uses the same row lock and terminal states cannot change. Unique keys
and canonical payload comparison make HTTP retries safe. A lost acknowledgement
does not imply rollback; read/retry by the original key or reconcile by job ID.
The application, migrations, and container configuration remain unchanged from
Phase 2. Changes in this phase are experiment/evidence tools, tests, and documents.

**Teaching note:** the guarantee is exactly one *committed PostgreSQL effect* per
successful job, not exactly-once execution. The live zombie experiment logged two
execution starts and two execution finishes, but only one effect commit.
[Submission design note](DESIGN_SUMMARY.md); [full design](DESIGN.md).

## 3. Chaos test methodology

The actual HTTP API, PostgreSQL 18.6, and eight worker containers ran in the separate
`queue-phase3` Compose project, API port 18000, database port 55433, with a new
persistent volume. Phase 2's application database and artifacts were preserved.
Each experiment used a unique key namespace and an intended manifest independent
of HTTP acknowledgements. Jobs were never inserted directly by the harness.

The harness label-checks containers, records the worker-child PID/start ticks,
process UUID, container start time, RestartCount, and any running job observed just
before signalling. It SIGKILLs only the Python child, not PID 1 or unrelated host
processes. A kill counts only after a changed start time, increased restart count,
new worker UUID, and a live worker child establish replacement. Eight slots are
maintained; the replacement gap necessarily has fewer live processes. The next
kill waits for replacement, with a 12 s replacement deadline.

Replay/conflict traffic and queued/running cancellations run concurrently with
creates and random kills. All HTTP attempts and bounded create retries are logged.
After injection ends, survivors drain. Validation reads jobs/effects together in
one read-only REPEATABLE READ PostgreSQL snapshot, retaining every row and checking
keys, counts, payloads, acknowledged IDs, terminal observations/cancellation acks,
effect counts, winning generation, and independently calculated squared results.

## 4. Number of complete and failed runs

| Scenario | Seed | Jobs | Outcome | Evidence |
| --- | ---: | ---: | --- | --- |
| Pilot, stronger cancellation | 99 | 300 | PASS | [raw](artifacts/runs/20261110T114119.333111Z-73ea0cab/) |
| Full chaos 1 | 1101 | 10,000 | PASS | [raw](artifacts/runs/20261110T114216.329047Z-1ad53347/) |
| Full chaos 2 | 2202 | 10,000 | PASS, four reconciled transport errors | [raw](artifacts/runs/20261110T114447.707913Z-ee1a8fe5/) |
| Full chaos 3 | 3303 | 10,000 | PASS | [raw](artifacts/runs/20261110T114748.485476Z-04e89474/) |
| Live frozen/resumed worker | 5505 | 1 | PASS | [raw](artifacts/runs/20261110T115023.609584Z-9a8763e9/) |
| Sustained mixed 100 RPS | 4404 | 4,820 including setup | PASS | [raw](artifacts/runs/20261110T115107.525639Z-92097597/) |

Exactly **three complete full chaos runs, zero failed full chaos runs**, one pilot,
one live zombie scenario, and one sustained load run were performed in Phase 3.
Raw Ruff failures/intermediate checks are indexed too. These counts do not relabel
or hide the three failed Phase 2 smoke-driver runs in VERIFICATION.md.

## 5. Workload and failure-injection configuration

The [pre-measurement plan](EXPERIMENTS.md) was committed before the full runs/load.
Per full run: 8,000 jobs at a seeded choice of 0/5/10/20 ms; 1,200 at 100 ms;
400 at 1 s; 100 at 4 s; 200 transient jobs at 20 ms that fail their first attempt;
100 permanent failures at 20 ms. Values and complete immutable payloads are in
`intended.jsonl.gz`. Cancellations may preempt planned failures/retries.

Creates target 200/sec. Secondary traffic is completion-paced, up to 50 duplicate
POSTs/sec (80% replay, 20% conflicting payload), plus up to two queued and one
running cancellation every 0.5 s. It is not an independently guaranteed offered
rate: actual secondary traffic slowed, especially in seed 2202. The pilot used
10 queued/4 running cancellations per batch and preempted all transient retries;
the lower intensity for full runs exercised retries and longer work more usefully.

Lease/heartbeat/deadline are 10/3/120 s, five claims maximum, with 1/2/4/8 s retry
backoff. Drain budget is `ceil(3 * nominal_serial_work / 8 + 5*(10+4) + 15 + 30)`:
490/491/490 seconds for the three seeds. It is an engineering deadline, not a
mathematical bound under arbitrary failures; expiry would fail the run. Actual
post-injection drains were 82.74/84.28/80.40 s.

Mean observed kill intervals were 2.000/2.220/2.011 s. Across full runs the smallest
was 1.630 s and largest 3.800 s; replacement waits caused schedule slip. Maximum
replacement delays were 1.27/2.99/1.82 s. Raw kill records contain scheduled lag,
old/new identities, process details, affected jobs, and final generations.

## 6. Actual chaos results and invariant assertions

| Seed | Kills/restarts | Claims = execution-start logs | Retries | Succeeded = effects | Cancelled | Failed | HTTP attempts |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1101 | 25/25 | 10,026 | 196 | 9,643 | 259 | 98 | 11,847 |
| 2202 | 23/23 | 10,139 | 208 | 9,794 | 106 | 100 | 10,501 |
| 3303 | 24/24 | 10,020 | 194 | 9,637 | 265 | 98 | 11,835 |
| Total | **72/72** | **30,185** | **598** | **29,074** | **630** | **296** | **34,183** |

HTTP attempts comprise 30,000 original creates, four create retries after transport
errors, 2,810 same-key replays, 703 conflicting-payload POSTs, and 666 cancellation
requests. HTTP outcomes: 30,000 × 201; 3,440 × 200; 739 × 409; four transport errors.
The 630 cancellation acknowledgements remained cancelled. Claims are committed
attempts, retries count attempts beyond the first, execution starts come from logs,
and effects come from PostgreSQL. Their observed agreement is not a requirement
that logs always survive a crash immediately after commit.

Every full-run snapshot had exactly 10,000 intended keys/jobs, no extra duplicates,
no changed payloads, no missing acknowledged IDs, no queued/running jobs, no effects
on failed/cancelled jobs, and exactly one matching effect per succeeded job. Terminal
HTTP observations matched final state. No failure was caused by retry-budget
exhaustion in these full runs; that behavior is separately covered by integration tests.
Peak queued/running counts were 6,030/6,025/5,643 during the 200-create/sec burst.

Of 72 kill samples, 61 observed an active job before signalling and 11 did not.
For those 61 sampled jobs, final outcomes were 33 cancelled, 12 newer generations,
and 16 succeeded under the sampled generation. The latter can complete between
the pre-signal read and actual kill; that is not evidence of a stale commit. The
sampling window cannot perfectly attribute every killed attempt. Raw logs plus
deterministic fencing tests supply complementary evidence.

Seed 2202's four `RemoteProtocolError`s occurred around 11:44:57 UTC and were
reconciled with bounded same-key create retries. Captured API logs show no matching
application exception. Cause is **not established**; keepalive/network turnover or
load-generator scheduling are hypotheses, not findings. The correctness run passed
because reconciliation and final invariants succeeded, not because transport errors
were ignored. Intentional SQL error messages later in the server logs belong to
separate `queue_phase3_test` tests, not those HTTP failures.

The final whole-Phase-3 database snapshot, including pilot/zombie/load, had **35,121
jobs: 34,126 succeeded/effects, 696 cancelled, 299 planned failures, zero state/effect
or generation/result mismatches**, with no queued/running jobs.
[Raw final SQL](artifacts/runs/20261110T115354.244209Z-2a8fad14/stdout.txt).

## 7. Silent failure investigation matrix

The PostgreSQL tests use separate transactions, events/barriers, blocked-transaction
observation, and real constraint failures. [Final suite evidence](artifacts/runs/20261110T114637.084260Z-0eeeb393/stdout.txt)
contains named tests; the final verification ledger below records the last run too.

| Scenario | Trigger and expected invariant | Actual observation/evidence | Result |
| --- | --- | --- | --- |
| Double claim | Pause real claim after locking the only job; second worker must get no job. Also race 12 claims. | `test_two_workers_one_job_only_locked_winner_claims`, parallel-claim/skip-locked tests; distinct generations in chaos logs. | PASS |
| Zombie | SIGSTOP live worker > lease, let another worker claim generation 2, then SIGCONT; old result must not commit. | [Live run](artifacts/runs/20261110T115023.609584Z-9a8763e9/): two executions, old owner logs ownership_lost, one generation-2 effect. Direct stale-complete/heartbeat/failure tests reject generation 1 even with reused owner. | PASS |
| Cancel/complete | Pause actual winning transition under row lock and block loser, forcing both acquisition orders. | Both orderings pass; cancellation-first inserts no effect; success-first preserves success and returns 409 to cancel. 630 chaos cancellation acks remain cancelled. | PASS |
| Idempotent retries | Concurrent same-key POSTs, conflicting payloads, and bounded retries after uncertain transport. | Same payload returns one ID, conflicts 409, immutable payloads; 30,000 unique full-run jobs. | PASS |
| READ COMMITTED | Block INSERT conflict behind uncommitted winner, then read in next statement. | Fresh winner is visible; payload conflict rejected. `test_idempotency_conflict_waits_and_reads_fresh_snapshot`. | PASS |
| Atomic rollback | Force effect unique violation and state constraint failure; terminate a real backend before commit. | Neither half of completion survives rollback; integrity violations remain visible. | PASS |
| App/worker clock assumptions | Poison local wall-clock access while claiming, renewing and completing against real PG; wait on a held lock before lease recheck. | DB-clock operations pass; expired authorization is rejected; heartbeat capped at deadline. Logs can use local wall time, ownership cannot. | PASS |
| Database clock jumps | Would require isolated clock control or a separately validated clock-injection setup. | Not changed: container wall clock shares the Docker VM used by other retained services. Changing it would affect unrelated tests/data. | NOT TESTED |
| Unknown commit | Raise client exception after an actual committed create/completion. | Read-back/replay finds one job/effect. Injection is not proof of a real network partition. | PASS for injected lost acknowledgement |
| Terminal immutability | Attempt payload/terminal mutation, repeat cancel, compare observed terminal states with snapshots. | DB guard rejects mutation; observed terminal states stay consistent. | PASS |

The original negative control that removes fencing fails its zombie regression as
expected; Phase 2 raw failure remains linked in VERIFICATION.md. No actual application
concurrency defect was established in Phase 3, so no speculative redesign/fix was made.

## 8. 100 RPS load test methodology and results

An open-loop scheduler offered 100 requests/sec for 120 s, counting duplicate
retries toward that rate. Mix: 40% create, 20% status, 10% list, 10% cancel, 10%
same-key replay, 10% conflicting replay. Twenty setup creates are excluded from
measured traffic. New work is 100 ms, with a seeded 5% taking 1 s. No kills run
concurrently. Responses/statuses, dispatch lag, latencies, queue/connection samples,
and Docker CPU/memory observations are retained, not inferred from one short burst.

Environment: macOS arm64 client; Docker Desktop Engine 28.3.2 with **8 vCPUs and
8,218,316,800 bytes RAM**; PostgreSQL 18.6; Python 3.11; locked Python dependencies
and image digests. The retained Phase 2 four-worker stack remained mostly idle on
the same host, so this is not a dedicated production host or cross-host network test.
Configuration and exact dependency versions are in the run's `environment.json`.

| Metric | Actual measurement |
| --- | ---: |
| Offered/scheduled | 100 RPS, 120 s, 12,000 requests |
| Dispatched / dropped | 12,000 / 0 |
| Dispatch / HTTP completion RPS | 99.982 / 99.980 |
| Expected-outcome completion RPS | 99.980 |
| p50 / p95 / p99 request latency | 4.55 / 7.96 / 22.50 ms |
| p99 dispatch lag | 4.49 ms |
| HTTP status distribution | 201: 4,800; 200: 4,817; 409: 2,383 |
| Unexpected statuses / transport errors / timeouts | 0 / 0 / 0 |
| Worker terminal throughput / successful effect throughput | 39.945 / 39.884 jobs/sec |
| Maximum queued + running | 21 |
| Second-half endpoint backlog slope | +0.119 jobs/sec |
| Post-load drain | 1.04 s |
| Final job states (including 20 setup) | 4,809 succeeded, 11 cancelled |
| Final database assertions | PASS; 4,809 effects |

409s are expected conflicts or terminal cancellation rejections; they are not all
successful cancellations. The small positive backlog slope is an endpoint estimate
on a bounded, fluctuating queue, not proof of indefinite linear growth.

Predeclared project criteria all passed: >=99% dispatch, 99..101 dispatched RPS,
<1% unexpected errors/timeouts, p95 <250 ms, p99 <1 s, p99 dispatch lag <100 ms,
second-half growth <=1 job/sec, maximum active queue <=200, drain <=60 s, and valid
final invariants. These thresholds are project choices, not Soup's published SLOs.

Sampled Docker CPU maxima: API **39.60%**, DB **12.13%**, individual workers
**4.17..7.10%**; these are Docker's reported percentages, not continuous worst-case
measurements. API memory samples were approximately **67.1..67.8 MiB**, DB
**100.4..103 MiB**, workers **45.6..46.8 MiB**. No monitor errors were reported.
App connection count peaked at **11**; no sampled lock waiters. Up to four sessions
were sampled briefly idle in transaction during multi-statement operations. This
sampling does not measure SQLAlchemy's internal pool checkout wait distribution or
prove absence of short stalls. Afterward, all 11 app connections were idle outside
transactions. [Raw connection snapshot](artifacts/runs/20261110T115456.210962Z-a938f069/stdout.txt).
API/worker engines each allow three pooled plus two overflow connections; the
experiment's separate pool permits three. No pool-timeout HTTP errors were observed.

## 9. Production verdict: DON'T SHIP

The declared toy-profile criteria passed. **I would not ship an unrestricted
production service with a generic promise of 100 RPS.** This test includes only
40 new jobs/sec with short waiting-based work. Execution duration is an independent
capacity dimension: even ignoring DB overhead, eight slots and 145 ms mean service
time imply roughly 55 jobs/sec, not 100 new jobs/sec. That is a capacity estimate,
not a measured saturation limit. Allowed jobs can take up to 60 s, and the current
service accepts an unbounded durable backlog without a wait-time or overload policy.
The chaos bursts already produced queues of about 6,000 jobs.

Further blockers are the unexplained transport errors, absent realistic-work and
longer sustained measurements, and untested database outage/failover/durability.
This is a negative readiness verdict with positive, explicitly scoped evidence—not
a claim that 100 RPS failed the measured HTTP workload.

## 10. Highest-priority fixes before production

1. Specify workload/service-time distribution and queue-wait SLO; add admission
   limits/backpressure and capacity alerts based on arrival rate, worker service
   rate, backlog age, and drain budget. Verify overload behavior under that contract.
2. Diagnose the four dropped HTTP connections with request correlation, client/server
   connection lifecycle evidence, and targeted replay. Do not assume they were
   caused by worker kills, keepalive, or an application race without evidence.
3. Test actual DB unavailability and ambiguous commits through network faults;
   rehearse persistent-volume recovery, backup/restore, failover, and required data-loss
   objectives. Preserve the atomic effect/state boundary through those tests.
4. Repeat sustained and soak measurements on representative execution and deployment
   hardware/network, with pool-wait and transaction-duration metrics. Establish
   operational ownership, retention, credentials/privileges, and recovery procedures.

## 11. Limitations and blind spots of the harness

Three seeds and 30,000 jobs do not exhaust transaction schedules or quantify rare
failure probability. Seeds reproduce manifests/random draws, not exact timings;
completion-paced secondary actions depend on response timing. Synchronous gzip
logging, parsing historical worker logs to find boot IDs, Docker commands, and a
shared host can perturb the experiment. Chaos latencies are not a clean benchmark.
The open-loop load's small measured dispatch lag supports generator adequacy for
that separate run, not for all future loads.

Killed jobs can finish in the gap between a DB sample and signal. SIGKILL cannot
return as a zombie; the separate freeze/resume check covers that failure shape.
Snapshots prove final consistency and consistency with observed acknowledgements,
not a complete temporal audit of every unobserved state. Logs may be lost between
commit and print; PostgreSQL is authoritative. The harness trusts its own oracle,
known schema, and bounded payload semantics. It does not prove correctness against
privileged arbitrary SQL, external side effects, CPU/GPU hangs, disk corruption,
partitions, cross-region replication, database clock jumps, or every restart storm.

## 12. What surprised us during testing

The useful surprise was that a run could preserve every job/effect invariant while
still losing HTTP connections. Retrying by key handled the uncertainty, but that
is not the same as explaining the availability failure. Another lesson was that
aggressive cancellation made the pilot look healthy while removing all retry
coverage; reducing it produced hundreds of real retries. Finally, the resumed
zombie visibly finished computation while its stale result was rejected. These
are observations from Codex's automated work, not a claim of independent human
verification or a fabricated personal reflection by the developer.

## 13. Open engineering concerns

The strongest unproven boundary is PostgreSQL durability/availability and behavior
under sustained overload or long real training work. The database clock can jump;
fencing protects competing ownership commits but recovery timing changes. Repeated
crashes may exhaust five attempts and legitimately fail a job; no claim is made
that every job must succeed. Fairness/starvation, stale clients, log completeness,
retention, and production pool sizing still need explicit operational decisions.
Authentication was outside the assignment; its absence is not being used to
invalidate the correctness tests. The transport-error cause remains open.

## 14. Evidence links and final verification

- [Pre-measurement configuration and criteria](EXPERIMENTS.md).
- [Complete Phase 2 + Phase 3 raw run index](artifacts/INDEX.md); stdout/stderr and
  exit codes are unedited, including failed checks and earlier smoke attempts.
- [Derived experiment metrics](artifacts/phase3-summary.json), reproducible with
  `python -m scripts.summarize_experiments`; this is separate from raw streams.
- Full-run directories above include configuration, environment/dependencies,
  intended manifests, every HTTP record, verified kills and old/new identities,
  worker/service logs, telemetry, raw DB rows, invariant results, and final summary.
  Gzip preserves original bytes/JSON records; all artifacts are tracked in Git.
- [Phase 2 verification and its retained failures](VERIFICATION.md).
- [AI assistance disclosure](AI_USE.md); [reproduction commands](README.md).
- [Subsequent developer-led manual API and SQL checks](MANUAL_VERIFICATION.md)
  (distinct from Codex's automated chaos and performance runs).

Final checks are listed in [PHASE3_VERIFICATION.md](PHASE3_VERIFICATION.md), including
Ruff, full pytest, clean migrations/schema comparison, actual four/eight-worker
startup, SQL invariants, link/artifact integrity, and the limits of what was run.
