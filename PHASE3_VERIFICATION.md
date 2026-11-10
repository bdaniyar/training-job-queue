# Phase 3 final verification ledger

These are executed checks, not proposed checks. Raw command, configuration,
source snapshot/hash, stdout, stderr, and exit status are in each run directory.
The tested application code/migrations/Compose files are unchanged from Phase 2;
`git diff` against `5e8353d` for those paths is empty. No regression fix to the
application was justified by the observed evidence.

| Check | Actual result | Evidence |
| --- | --- | --- |
| Ruff check | exit 0, all checks passed | [stdout](artifacts/runs/20261110T120006.832782Z-117cc302/stdout.txt) |
| Ruff format check | exit 0, 36 files formatted | [stdout](artifacts/runs/20261110T120007.031290Z-76423c26/stdout.txt) |
| Full pytest, isolated real PostgreSQL | exit 0, **34 passed in 1.45 s**, `-W error`, no warnings | [stdout](artifacts/runs/20261110T115457.199107Z-eb301424/stdout.txt), [stderr](artifacts/runs/20261110T115457.199107Z-eb301424/stderr.txt) |
| Fresh Phase 3 database initialization/four-worker startup | exit 0, DB initialized, migration succeeded, API healthy, four worker containers running | [raw startup](artifacts/runs/20261110T113558.214632Z-a535aa26/) |
| Eight-worker startup | exit 0, API healthy, eight workers running; experiments independently label-check eight live worker containers/boot UUIDs | [raw startup](artifacts/runs/20261110T114052.032603Z-e7d3b724/) |
| Separate new `queue_phase3_test` database | created successfully, migrated from empty to head | [create](artifacts/runs/20261110T114555.245512Z-17fba355/), [upgrade](artifacts/runs/20261110T114555.603233Z-a32d42d8/) |
| Alembic schema comparison | no new upgrade operations | [stdout](artifacts/runs/20261110T115108.643732Z-24bcea80/stdout.txt) |
| Alembic current revision | 0001 (head) | [stdout](artifacts/runs/20261110T115737.071711Z-c8e7fe5f/stdout.txt) |
| Three full chaos runs | 3 PASS, 30,000 total intended jobs; 72 actual worker kills/restarts | [report with all run links](REPORT.md) |
| Live zombie process | PASS, SIGSTOP beyond lease, generation 2 claims, old process resumes and loses ownership; one effect | [raw](artifacts/runs/20261110T115023.609584Z-9a8763e9/) |
| Sustained load | PASS, 100 offered RPS for 120 s, all 12,000 measured requests dispatched, no unexpected errors | [raw](artifacts/runs/20261110T115107.525639Z-92097597/) |
| Final application DB snapshot | 35,121 terminal jobs, 34,126 effects, zero mismatches | [SQL](artifacts/runs/20261110T115354.244209Z-2a8fad14/stdout.txt) |
| Link, gzip, totals, preservation checks | exit 0; 164 local links, 116 gzip artifacts, report totals and unchanged Phase 2 raw files/application checked | [stdout](artifacts/runs/20261110T120026.729312Z-f434d61d/stdout.txt) |
| Post-run connection snapshot | 11 application connections idle outside transactions, no idle-in-transaction connection | [SQL](artifacts/runs/20261110T115456.210962Z-a938f069/stdout.txt) |

The four-worker startup command matches the README's base configuration; the
separate-project override matches its Phase 3 reproduction instructions. Pilot,
full chaos, live zombie, load, and integration commands were actually run. No
full network-partition, DB clock-jump, failover, disk-corruption, real training,
or production soak verification is claimed. The four transport errors in chaos
seed 2202 remain unexplained and are disclosed in REPORT.md.

The complete index includes all failed lint/format checks and all retained Phase 2
runs. Derived summaries are reproducible from raw experiment files. Final artifact
checks verify Markdown file links, gzip integrity, completed recorder exit records,
report/summary totals, and preservation of tracked Phase 2 raw files. Checksums of
all final raw run files are in `artifacts/SHA256SUMS`; regenerating the derived
index/checksums does not edit any raw file. The report is a scoped assessment,
not a production certification or a claim of independent human verification.
