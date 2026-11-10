"""Derive a compact summary from retained raw experiments; never edit raw runs."""

import gzip
import json
from collections import Counter
from datetime import datetime
from pathlib import Path


def summarize(path):
    result = json.loads((path / "summary.json").read_text())
    samples = [json.loads(line) for line in gzip.open(path / "telemetry.jsonl.gz", "rt")]
    states = [item for item in samples if "states" in item]
    result["run_directory"] = str(path)
    result["max_active_depth"] = max(
        (s["states"].get("queued", 0) + s["states"].get("running", 0) for s in states), default=0
    )
    result["max_app_connections"] = max(
        (
            sum(
                row["n"]
                for row in item["connections"]
                if row["application_name"] == "training-queue"
            )
            for item in states
        ),
        default=0,
    )
    result["max_idle_in_transaction"] = max(
        (
            sum(row["n"] for row in item["connections"] if row["state"] == "idle in transaction")
            for item in states
        ),
        default=0,
    )
    result["max_lock_waiters"] = max(
        (
            sum(row["n"] for row in item["connections"] if row["wait_event_type"] == "Lock")
            for item in states
        ),
        default=0,
    )
    result["monitor_errors"] = [item for item in samples if "monitor_error" in item]
    resources = {}
    for sample in samples:
        if "docker_stats" not in sample:
            continue
        for line in sample["docker_stats"].splitlines():
            row = json.loads(line)
            name = row["Name"]
            resource = resources.setdefault(
                name, {"max_cpu_percent": 0, "memory_usage_samples": []}
            )
            resource["max_cpu_percent"] = max(
                resource["max_cpu_percent"], float(row["CPUPerc"].rstrip("%"))
            )
            resource["memory_usage_samples"].append(row["MemUsage"])
            usage = row["MemUsage"].split(" / ")[0]
            for unit, multiplier in (("GiB", 1024), ("MiB", 1), ("KiB", 1 / 1024)):
                if usage.endswith(unit):
                    memory = float(usage.removesuffix(unit)) * multiplier
                    resource["max_memory_mib"] = max(resource.get("max_memory_mib", 0), memory)
                    break
    result["resources"] = resources
    kills_path = path / "kills.json"
    if kills_path.exists():
        kills = json.loads(kills_path.read_text())
        times = [datetime.fromisoformat(k["time"]).timestamp() for k in kills]
        gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
        result["kill_intervals_seconds"] = {
            "min": min(gaps, default=0),
            "max": max(gaps, default=0),
            "mean": sum(gaps) / len(gaps) if gaps else 0,
        }
        result["max_replacement_seconds"] = max(
            (k["replacement_seconds"] for k in kills), default=0
        )
        result["killed_job_outcomes"] = dict(
            Counter(
                ("new_generation" if row["generation"] > row["killed_generation"] else row["state"])
                for kill in kills
                for row in kill.get("final_jobs", [])
            )
        )
    return result


def main():
    results = [
        summarize(path.parent) for path in sorted(Path("artifacts/runs").glob("*/summary.json"))
    ]
    Path("artifacts/phase3-summary.json").write_text(json.dumps(results, indent=2) + "\n")
    for item in results:
        print(
            json.dumps(
                {
                    key: item.get(key)
                    for key in (
                        "run_directory",
                        "kind",
                        "seed",
                        "outcome",
                        "jobs",
                        "kills",
                        "verified_restarts",
                        "retries",
                        "states",
                        "effects",
                        "requests",
                        "measured_requests",
                        "dispatch_rps",
                        "completed_rps",
                        "measured_latency_ms",
                        "max_active_depth",
                        "max_app_connections",
                        "max_lock_waiters",
                        "failed_reasons",
                        "http_errors",
                        "kill_intervals_seconds",
                        "max_replacement_seconds",
                    )
                }
            )
        )


if __name__ == "__main__":
    main()
