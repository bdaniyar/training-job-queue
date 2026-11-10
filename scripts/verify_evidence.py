"""Check local evidence, report totals, gzip CRCs, and Phase 2 preservation."""

import gzip
import json
import os
import re
import subprocess
from pathlib import Path

BASE = "5e8353db4cfcc215bc12120e0e1f2cf60576800a"


def main():
    checked = 0
    for path in [*Path(".").glob("*.md"), Path("artifacts/INDEX.md")]:
        for link in re.findall(r"\]\(([^)]+)\)", path.read_text()):
            if link.startswith(("http:", "https:")):
                continue
            target = link.split("#")[0]
            if target:
                assert (path.parent / target).exists(), (str(path), target)
                checked += 1
    compressed = list(Path("artifacts/runs").rglob("*.gz"))
    for path in compressed:
        with gzip.open(path, "rb") as stream:
            while stream.read(1024 * 1024):
                pass
    current = Path(os.environ.get("QUEUE_RUN_DIR", "/nonexistent")).resolve()
    for run in Path("artifacts/runs").iterdir():
        if run.resolve() != current:
            result = json.loads((run / "result.json").read_text())
            assert isinstance(result["exit_code"], int), run
    items = json.loads(Path("artifacts/phase3-summary.json").read_text())
    full = [x for x in items if x["kind"] == "chaos" and x["jobs"] == 10000]
    assert len(full) == 3 and all(x["outcome"] == "PASS" for x in full)
    expected = {
        "jobs": 30000,
        "kills": 72,
        "verified_restarts": 72,
        "effects": 29074,
        "retries": 598,
    }
    for name, total in expected.items():
        assert sum(x[name] for x in full) == total, name
    assert sum(x["states"]["cancelled"] for x in full) == 630
    assert sum(x["states"]["failed"] for x in full) == 296
    load = next(x for x in items if x["kind"] == "load")
    assert load["measured_requests"] == 12000 and load["outcome"] == "PASS"
    assert all(load["acceptance"].values())
    old = subprocess.check_output(
        [
            "git",
            "diff",
            "--name-only",
            "--diff-filter=DMR",
            BASE,
            "--",
            "artifacts/runs",
        ],
        text=True,
    )
    assert not old, old
    app = subprocess.check_output(
        [
            "git",
            "diff",
            "--name-only",
            BASE,
            "--",
            "src",
            "alembic",
            "Dockerfile",
            "compose.yaml",
            "compose.eight.yaml",
        ],
        text=True,
    )
    assert not app, app
    subprocess.run(["git", "merge-base", "--is-ancestor", BASE, "HEAD"], check=True)
    print(
        f"PASS: {checked} local links, {len(compressed)} gzip artifacts, completed raw runs, "
        "report totals, unchanged application, and Phase 2 preservation."
    )


if __name__ == "__main__":
    main()
