# Raw verification runs

Generated index only; raw files are unedited. Times in IDs are UTC.

| Run | Exit | Command (full command in metadata) |
| --- | --- | --- |
| [20261110T100139.771626Z-4d3f7910](runs/20261110T100139.771626Z-4d3f7910/metadata.json) | 0 | `docker info --format {{json .ServerVersion}}` |
| [20261110T100250.982787Z-53a9389c](runs/20261110T100250.982787Z-53a9389c/metadata.json) | 1 | `uv sync` |
| [20261110T100553.674829Z-f9dae8d4](runs/20261110T100553.674829Z-f9dae8d4/metadata.json) | 0 | `uv sync --python 3.11` |
| [20261110T100800.015651Z-2c3a85f0](runs/20261110T100800.015651Z-2c3a85f0/metadata.json) | 0 | `uv export --frozen --no-dev --no-emit-project --output-file requirements.lock --quiet` |
| [20261110T100808.668782Z-44d0944b](runs/20261110T100808.668782Z-44d0944b/metadata.json) | 1 | `uv run --frozen ruff check .` |
| [20261110T100808.668797Z-bcb2b127](runs/20261110T100808.668797Z-bcb2b127/metadata.json) | 1 | `docker compose up --build -d --wait` |
| [20261110T100911.579194Z-28c0ca75](runs/20261110T100911.579194Z-28c0ca75/metadata.json) | 1 | `uv run --frozen ruff check --fix .` |
| [20261110T100912.054749Z-8b4a1112](runs/20261110T100912.054749Z-8b4a1112/metadata.json) | 0 | `uv run --frozen ruff format .` |
| [20261110T100917.368015Z-fd578bc6](runs/20261110T100917.368015Z-fd578bc6/metadata.json) | 0 | `uv run --frozen ruff check .` |
| [20261110T100933.920869Z-19ce8648](runs/20261110T100933.920869Z-19ce8648/metadata.json) | 0 | `docker compose logs --no-color --timestamps` |
| [20261110T100934.340295Z-6857f185](runs/20261110T100934.340295Z-6857f185/metadata.json) | 0 | `docker compose exec -T db createdb -U queue queue_test` |
| [20261110T100934.692439Z-6d1b47cb](runs/20261110T100934.692439Z-6d1b47cb/metadata.json) | 0 | `uv run --frozen alembic upgrade head` |
| [20261110T100946.737967Z-ac8aff00](runs/20261110T100946.737967Z-ac8aff00/metadata.json) | 0 | `uv run --frozen pytest -v` |
| [20261110T100947.890144Z-39ff9fcd](runs/20261110T100947.890144Z-39ff9fcd/metadata.json) | 0 | `docker compose up --build -d --wait` |
| [20261110T101017.265336Z-ca836b87](runs/20261110T101017.265336Z-ca836b87/metadata.json) | 0 | `uv run --frozen pytest -v -W error` |
| [20261110T101018.246049Z-67681a26](runs/20261110T101018.246049Z-67681a26/metadata.json) | 1 | `uv run --frozen python scripts/regression_probe.py` |
| [20261110T101025.253964Z-0baf3a45](runs/20261110T101025.253964Z-0baf3a45/metadata.json) | 0 | `uv run --frozen pytest -v -W error` |
| [20261110T101128.365695Z-f6b100a2](runs/20261110T101128.365695Z-f6b100a2/metadata.json) | 0 | `docker compose up --build -d --wait` |
| [20261110T101155.739813Z-b6f72927](runs/20261110T101155.739813Z-b6f72927/metadata.json) | 1 | `uv run --frozen python scripts/smoke.py` |
| [20261110T101156.884850Z-ca812218](runs/20261110T101156.884850Z-ca812218/metadata.json) | 0 | `uv run --frozen alembic check` |
| [20261110T101219.202976Z-4b55ea76](runs/20261110T101219.202976Z-4b55ea76/metadata.json) | 1 | `uv run --frozen ruff check .` |
| [20261110T101219.518565Z-445440d2](runs/20261110T101219.518565Z-445440d2/metadata.json) | 1 | `uv run --frozen ruff format --check .` |
| [20261110T101242.896876Z-b7597a18](runs/20261110T101242.896876Z-b7597a18/metadata.json) | 0 | `docker compose exec -T --index 1 worker python -c from pathlib import Path; print(Path("/proc/1/cmdline").read_bytes()); print(...` |
| [20261110T101243.343493Z-839795b9](runs/20261110T101243.343493Z-839795b9/metadata.json) | 0 | `docker compose logs --no-color --timestamps` |
| [20261110T101313.692714Z-f55d1da8](runs/20261110T101313.692714Z-f55d1da8/metadata.json) | 0 | `uv run --frozen ruff format .` |
| [20261110T101313.997315Z-02700d74](runs/20261110T101313.997315Z-02700d74/metadata.json) | 0 | `uv run --frozen ruff check .` |
| [20261110T101314.152457Z-a0ec3cfa](runs/20261110T101314.152457Z-a0ec3cfa/metadata.json) | 1 | `uv run --frozen python scripts/smoke.py` |
| [20261110T101519.299768Z-8ca88dcc](runs/20261110T101519.299768Z-8ca88dcc/metadata.json) | 0 | `uv run --frozen ruff format .` |
| [20261110T101519.640811Z-6af2b06f](runs/20261110T101519.640811Z-6af2b06f/metadata.json) | 0 | `docker compose up --build -d --wait` |
| [20261110T101532.234047Z-5c54648d](runs/20261110T101532.234047Z-5c54648d/metadata.json) | 0 | `uv pip freeze` |
| [20261110T101532.575390Z-e7f3224d](runs/20261110T101532.575390Z-e7f3224d/metadata.json) | 0 | `docker compose version` |
| [20261110T101549.363304Z-763fb03c](runs/20261110T101549.363304Z-763fb03c/metadata.json) | 1 | `uv run --frozen python scripts/smoke.py` |
| [20261110T101550.520900Z-00fb0e12](runs/20261110T101550.520900Z-00fb0e12/metadata.json) | 0 | `docker image inspect postgres:18 --format {{json .RepoDigests}}` |
| [20261110T101609.557355Z-649b8cbf](runs/20261110T101609.557355Z-649b8cbf/metadata.json) | 1 | `uv run --frozen ruff check .` |
| [20261110T101609.951839Z-71953fed](runs/20261110T101609.951839Z-71953fed/metadata.json) | 0 | `uv run --frozen pytest -v -W error` |
| [20261110T101625.127796Z-209c9c90](runs/20261110T101625.127796Z-209c9c90/metadata.json) | 0 | `uv run --frozen ruff format .` |
| [20261110T101625.446762Z-8c7acb0f](runs/20261110T101625.446762Z-8c7acb0f/metadata.json) | 0 | `uv run --frozen python scripts/smoke.py` |
| [20261110T101647.335080Z-8827d701](runs/20261110T101647.335080Z-8827d701/metadata.json) | 0 | `uv run --frozen ruff check .` |
| [20261110T101647.691448Z-c087703c](runs/20261110T101647.691448Z-c087703c/metadata.json) | 0 | `uv run --frozen ruff format --check .` |
| [20261110T101659.947682Z-a3714ad8](runs/20261110T101659.947682Z-a3714ad8/metadata.json) | 0 | `docker compose -f compose.yaml -f compose.eight.yaml up -d --wait --no-build` |
| [20261110T101713.851958Z-66942ccf](runs/20261110T101713.851958Z-66942ccf/metadata.json) | 0 | `docker compose ps --format json` |
| [20261110T101734.087362Z-a5f8b677](runs/20261110T101734.087362Z-a5f8b677/metadata.json) | 0 | `python3 -c import json, subprocess; rows = [json.loads(line) for line in subprocess.check_output(["docker", "compose", "ps", "-...` |
| [20261110T101734.531604Z-24568303](runs/20261110T101734.531604Z-24568303/metadata.json) | 0 | `docker compose logs --no-color --timestamps` |
| [20261110T101734.774364Z-4bf22fd5](runs/20261110T101734.774364Z-4bf22fd5/metadata.json) | 0 | `docker compose up -d --wait --no-build` |
| [20261110T101735.945497Z-a76457c3](runs/20261110T101735.945497Z-a76457c3/metadata.json) | 0 | `uv run --frozen pytest -v -W error` |
| [20261110T101756.217730Z-f8c10d44](runs/20261110T101756.217730Z-f8c10d44/metadata.json) | 0 | `docker compose exec -T db psql -U queue -d queue --set ON_ERROR_STOP=1 --echo-all` |
| [20261110T101756.671658Z-eb107395](runs/20261110T101756.671658Z-eb107395/metadata.json) | 0 | `uv run --frozen alembic current --verbose` |
| [20261110T102013.367332Z-fb3aba1e](runs/20261110T102013.367332Z-fb3aba1e/metadata.json) | 0 | `docker compose ps --all` |
| [20261110T102013.740337Z-55d76c0b](runs/20261110T102013.740337Z-55d76c0b/metadata.json) | 0 | `curl --fail-with-body --silent --show-error http://localhost:8000/health` |
| [20261110T113558.214632Z-a535aa26](runs/20261110T113558.214632Z-a535aa26/metadata.json) | 0 | `docker compose -p queue-phase3 up --build -d --wait` |
| [20261110T114043.852531Z-f1fe2df6](runs/20261110T114043.852531Z-f1fe2df6/metadata.json) | 1 | `uv run --frozen ruff check --fix .` |
| [20261110T114044.938076Z-0a5f9051](runs/20261110T114044.938076Z-0a5f9051/metadata.json) | 0 | `uv run --frozen ruff format .` |
| [20261110T114052.032603Z-e7d3b724](runs/20261110T114052.032603Z-e7d3b724/metadata.json) | 0 | `docker compose -p queue-phase3 -f compose.yaml -f compose.eight.yaml up -d --wait --no-build` |
| [20261110T114053.226551Z-352c98a3](runs/20261110T114053.226551Z-352c98a3/metadata.json) | 0 | `uv run --frozen pytest -v -W error` |
| [20261110T114118.930722Z-4f0d9cf2](runs/20261110T114118.930722Z-4f0d9cf2/metadata.json) | 1 | `uv run --frozen ruff check .` |
| [20261110T114119.333111Z-73ea0cab](runs/20261110T114119.333111Z-73ea0cab/metadata.json) | 0 | `uv run --frozen python -m scripts.chaos --seed 99 --jobs 300 --create-rps 50` |
| [20261110T114131.084873Z-367eba86](runs/20261110T114131.084873Z-367eba86/metadata.json) | 0 | `uv run --frozen ruff format .` |
| [20261110T114131.383898Z-06f1d4cc](runs/20261110T114131.383898Z-06f1d4cc/metadata.json) | 0 | `uv run --frozen ruff check .` |
| [20261110T114215.795112Z-2c402311](runs/20261110T114215.795112Z-2c402311/metadata.json) | 0 | `uv run --frozen ruff format .` |
| [20261110T114216.329047Z-1ad53347](runs/20261110T114216.329047Z-1ad53347/metadata.json) | 0 | `uv run --frozen python -m scripts.chaos --seed 1101` |
| [20261110T114441.815358Z-5c076178](runs/20261110T114441.815358Z-5c076178/metadata.json) | 0 | `uv run --frozen ruff format .` |
| [20261110T114447.707913Z-ee1a8fe5](runs/20261110T114447.707913Z-ee1a8fe5/metadata.json) | 0 | `uv run --frozen python -m scripts.chaos --seed 2202` |
| [20261110T114448.902522Z-61736f79](runs/20261110T114448.902522Z-61736f79/metadata.json) | 1 | `uv run --frozen ruff check .` |
| [20261110T114530.228934Z-d7120984](runs/20261110T114530.228934Z-d7120984/metadata.json) | 0 | `uv run --frozen ruff format .` |
| [20261110T114530.641949Z-f64aa81e](runs/20261110T114530.641949Z-f64aa81e/metadata.json) | 0 | `uv run --frozen ruff check .` |
| [20261110T114555.245512Z-17fba355](runs/20261110T114555.245512Z-17fba355/metadata.json) | 0 | `docker compose -p queue-phase3 exec -T db createdb -U queue queue_phase3_test` |
| [20261110T114555.603233Z-a32d42d8](runs/20261110T114555.603233Z-a32d42d8/metadata.json) | 0 | `uv run --frozen alembic upgrade head` |
| [20261110T114637.084260Z-0eeeb393](runs/20261110T114637.084260Z-0eeeb393/metadata.json) | 0 | `uv run --frozen pytest -v -W error` |
| [20261110T114748.485476Z-04e89474](runs/20261110T114748.485476Z-04e89474/metadata.json) | 0 | `uv run --frozen python -m scripts.chaos --seed 3303` |
| [20261110T114957.825513Z-80290b79](runs/20261110T114957.825513Z-80290b79/metadata.json) | 0 | `uv run --frozen ruff format .` |
| [20261110T114958.154982Z-15fd246d](runs/20261110T114958.154982Z-15fd246d/metadata.json) | 1 | `uv run --frozen ruff check .` |
| [20261110T115023.609584Z-9a8763e9](runs/20261110T115023.609584Z-9a8763e9/metadata.json) | 0 | `uv run --frozen python -m scripts.zombie --seed 5505` |
| [20261110T115024.737376Z-a28df824](runs/20261110T115024.737376Z-a28df824/metadata.json) | 0 | `uv run --frozen python -m scripts.summarize_experiments` |
| [20261110T115107.525639Z-92097597](runs/20261110T115107.525639Z-92097597/metadata.json) | 0 | `uv run --frozen python -m scripts.load --seed 4404` |
| [20261110T115108.643732Z-24bcea80](runs/20261110T115108.643732Z-24bcea80/metadata.json) | 0 | `uv run --frozen alembic check` |
| [20261110T115317.580916Z-2368eaa9](runs/20261110T115317.580916Z-2368eaa9/metadata.json) | 1 | `uv run --frozen ruff check .` |
| [20261110T115317.942705Z-88639925](runs/20261110T115317.942705Z-88639925/metadata.json) | 1 | `uv run --frozen ruff format --check .` |
| [20261110T115353.491808Z-d0517098](runs/20261110T115353.491808Z-d0517098/metadata.json) | 0 | `uv run --frozen ruff format .` |
| [20261110T115353.945241Z-13b097fd](runs/20261110T115353.945241Z-13b097fd/metadata.json) | 0 | `uv run --frozen python -m scripts.summarize_experiments` |
| [20261110T115354.244209Z-2a8fad14](runs/20261110T115354.244209Z-2a8fad14/metadata.json) | 0 | `docker compose -p queue-phase3 exec -T db psql -U queue -d queue --set ON_ERROR_STOP=1 -c BEGIN TRANSACTION ISOLATION LEVEL REP...` |
| [20261110T115456.210962Z-a938f069](runs/20261110T115456.210962Z-a938f069/metadata.json) | 0 | `docker compose -p queue-phase3 exec -T db psql -U queue -d queue --set ON_ERROR_STOP=1 -c SELECT application_name,state,count(*...` |
| [20261110T115456.793097Z-f14bdce1](runs/20261110T115456.793097Z-f14bdce1/metadata.json) | 0 | `uv run --frozen ruff format .` |
| [20261110T115457.199107Z-eb301424](runs/20261110T115457.199107Z-eb301424/metadata.json) | 0 | `uv run --frozen pytest -v -W error` |
| [20261110T115736.474363Z-f6e2699e](runs/20261110T115736.474363Z-f6e2699e/metadata.json) | 0 | `uv run --frozen ruff check .` |
| [20261110T115736.866554Z-468fa9ac](runs/20261110T115736.866554Z-468fa9ac/metadata.json) | 0 | `uv run --frozen ruff format --check .` |
| [20261110T115737.071711Z-c8e7fe5f](runs/20261110T115737.071711Z-c8e7fe5f/metadata.json) | 0 | `uv run --frozen alembic current --verbose` |
| [20261110T115845.373350Z-670c0c5a](runs/20261110T115845.373350Z-670c0c5a/metadata.json) | 0 | `docker compose -p queue-phase3 ps --all` |
| [20261110T115845.854459Z-de094735](runs/20261110T115845.854459Z-de094735/metadata.json) | 0 | `docker compose ps --all` |
| [20261110T115846.118828Z-2bd6f659](runs/20261110T115846.118828Z-2bd6f659/metadata.json) | 0 | `curl --fail-with-body --silent --show-error http://localhost:18000/health` |
| [20261110T115846.308693Z-cd4309ec](runs/20261110T115846.308693Z-cd4309ec/metadata.json) | 0 | `uv run --frozen python -m scripts.summarize_experiments` |
| [20261110T115926.997552Z-d041603c](runs/20261110T115926.997552Z-d041603c/metadata.json) | 0 | `uv run --frozen python -` |
| [20261110T120006.406501Z-0043b9c7](runs/20261110T120006.406501Z-0043b9c7/metadata.json) | 0 | `uv run --frozen ruff format .` |
| [20261110T120006.832782Z-117cc302](runs/20261110T120006.832782Z-117cc302/metadata.json) | 0 | `uv run --frozen ruff check .` |
| [20261110T120007.031290Z-76423c26](runs/20261110T120007.031290Z-76423c26/metadata.json) | 0 | `uv run --frozen ruff format --check .` |
| [20261110T120026.729312Z-f434d61d](runs/20261110T120026.729312Z-f434d61d/metadata.json) | 0 | `uv run --frozen python -m scripts.verify_evidence` |
