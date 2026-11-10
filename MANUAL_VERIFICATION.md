# Developer manual verification — 2026-11-10

This is a **developer-led exploratory check**, performed separately from Codex's automated test runs. The developer used FastAPI Swagger UI at `http://localhost:8000/docs` and a PostgreSQL `psql` session in the default Docker Compose stack. The database reported PostgreSQL **18.6**. These checks were completed after the Phase 3 harness and reports.

## Checks performed

1. Created a regular job with idempotency key `manual-test-001`, simulated duration 5,000 ms, and value 7. Checked its status through the API and then in PostgreSQL. The final state was `succeeded`, with one attempt and generation 1; its effect contains `{"squared_value": 49}`.
2. Created a longer-running job with key `manual-cancel-001` and exercised cancellation via the API. PostgreSQL showed the terminal state `cancelled`, with no committed effect.
3. Created a transient-failure job with key `manual-retry-001`, value 5 and one configured failed attempt. PostgreSQL showed `succeeded` on generation 2; its effect contains `{"squared_value": 25}`.
4. Exercised API creation/status and idempotency-key replay and conflicting-payload paths through Swagger during this manual walkthrough. These HTTP responses were not archived as a separate machine-readable run, so the directly retained manual evidence is the PostgreSQL output below.

## Directly observed SQL evidence

The developer ran:

```sh
docker compose exec db psql -U queue -d queue
```

For the ordinary success case:

```sql
SELECT id, idempotency_key, state, attempts, generation
FROM jobs WHERE idempotency_key = 'manual-test-001';
```

Observed:

```text
bc83c858-8c7b-4334-9235-cd3c0be3aa55 | manual-test-001 | succeeded | 1 | 1
```

To inspect all three side effects:

```sql
SELECT j.idempotency_key, j.state, e.generation, e.result
FROM jobs j
LEFT JOIN job_effects e ON e.job_id = j.id
WHERE j.idempotency_key IN (
  'manual-test-001', 'manual-cancel-001', 'manual-retry-001'
);
```

Observed (copied from the developer's terminal transcript):

```text
manual-test-001   | succeeded | 1 | {"squared_value": 49}
manual-cancel-001 | cancelled |   |
manual-retry-001  | succeeded | 2 | {"squared_value": 25}
(3 rows)
```

## Interpretation and limits

This directly checks the normal success, cancellation without a committed effect, and transient failure/retry paths for three manually created jobs. It also supports the developer's conceptual review of the separation between API requests, durable queue state, worker execution, and the database effect.

It **does not** establish full concurrency correctness, all possible crash interleavings, genuine exactly-once execution, or 100 RPS production readiness. The 34 PostgreSQL-backed tests, three 10,000-job chaos runs, live zombie scenario, and load measurements were executed by **Codex** and are documented with their original raw output in `PHASE3_VERIFICATION.md`, `REPORT.md`, and `artifacts/INDEX.md`. They were not independently rerun by the developer.

This file records the manual observations without inventing screenshots or additional raw logs.
