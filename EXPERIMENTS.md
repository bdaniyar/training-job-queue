# Phase 3 plan recorded before measurements

All commands run through `scripts/record.py`. Use project `queue-phase3`, API port
18000, PostgreSQL port 55433, and its own persistent volume. Do not delete the
Phase 2 project or database. Each experiment has a unique idempotency-key namespace.

Chaos: three target runs, seeds 1101/2202/3303, each 10,000 intended jobs,
200 distinct creates/sec, concurrent 50 replay/conflict requests/sec (80/20 split),
and cancellation batches of up to two queued and one running job every 0.5 s.
The 300-job pilot used ten queued/four running and preempted all transient retries;
the smaller cancellation batches preserve a more representative mix in full runs.
Eight worker slots, random
worker-child SIGKILL every approximately 2 s while creates/actions are active.
Verify container labels, target PID/start ticks, old/new boot UUIDs, start time,
and RestartCount. Restart gaps are measured; eight slots cannot mean eight live
processes at the instant one is killed. No overlapping kill while replacement is pending.

Exact distribution per full run: 8,000 short (0/5/10/20 ms), 1,200 medium (100 ms),
400 long (1 s), 100 heartbeat-length (4 s), 200 transient (20 ms, fail first attempt),
100 permanent failures (20 ms). Seed shuffles submission order and random choices.
Cancellations may preempt planned failures. Committed claim attempts, execution
logs, retries, effects, terminal outcomes, and HTTP request categories are separate.

After producers stop, stop fault injection and drain within:
`ceil(3 * nominal_serial_work_seconds / 8 + 5 * (10 + max_job_seconds) + 15 + 30)`.
Here nominal work includes the planned transient retries; 10 is the lease, 5 the
claim budget, 15 the total retry backoff, and 30 extra seconds for polling/HTTP.
The factor 3 is a conservative engineering budget, not a liveness theorem.
Any deadline expiry is a failed run. Final validation uses one read-only,
REPEATABLE READ snapshot with raw job/effect rows retained.

Load: seed 4404, 100 offered HTTP requests/sec for 120 s (12,000 scheduled
requests), no worker kills. Every ten requests: four creates, two status reads,
one list, one cancel, one same-key replay, one conflicting-payload replay. All
replays count toward offered RPS. A 20-job setup fixture is outside the measured
rate. New jobs take 100 ms, with 5% taking 1 s; this defines the tested capacity,
not real training performance. Use an open-loop scheduler; record scheduler delay,
request latency, completion rate, all statuses/errors/timeouts, and dropped requests.

Project-specific acceptance criteria, NOT Soup-specified thresholds:
- at least 99% of scheduled requests actually dispatched;
- achieved dispatch rate 99..101 RPS; unexpected errors/timeouts < 1%;
- p95 end-to-end request latency < 250 ms and p99 < 1 s;
- p99 dispatch lag < 100 ms (load generator must keep up);
- no sustained backlog growth (> 1 queued/running job/sec over the second half),
  maximum queued/running depth <= 200, drain <= 60 s;
- all final database invariants pass.

Collect Docker CPU/memory samples, PostgreSQL connection/wait/transaction counts,
queue depth and completed jobs over time. Database counts indicate pressure; they
do not directly measure SQLAlchemy's internal pool wait histogram. A SHIP decision
requires more than meeting these limited criteria; absent realistic workload,
durability/failover, and sustained multi-host evidence, DON'T SHIP is defensible.
No results are asserted in this pre-measurement plan.
