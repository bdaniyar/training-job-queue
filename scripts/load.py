"""Open-loop offered HTTP load, separate API/worker capacity, predeclared criteria."""

import argparse
import asyncio
import random
import time

from scripts.experiment import Experiment, common_arguments, emit, percentile


async def main(args):
    rng = random.Random(args.seed)
    async with Experiment(args, "load") as run:
        count = round(args.rps * args.seconds)
        plan = [
            {
                "category": "setup",
                "payload": {
                    "duration_ms": 100,
                    "value": i,
                    "fail_attempts": 0,
                    "fail_permanently": False,
                },
            }
            for i in range(20)
        ]
        for i in range(count):
            if i % 10 < 4:
                plan.append(
                    {
                        "category": "load",
                        "payload": {
                            "duration_ms": 1000 if rng.random() < 0.05 else 100,
                            "value": i,
                            "fail_attempts": 0,
                            "fail_permanently": False,
                        },
                    }
                )
        run.plan(plan)
        keys = list(run.intended)
        for key in keys[:20]:
            await run.create(key)
        setup_requests = run.request_count
        setup_statuses = run.statuses.copy()
        latency_offset = len(run.latencies)
        lag_offset = len(run.lags)
        offered_started = time.perf_counter()
        run.summary.update(
            offered_start=offered_started,
            offered_seconds=args.seconds,
            target_rps=args.rps,
            scheduled_requests=count,
            mix={
                "create": 40,
                "status": 20,
                "list": 10,
                "cancel": 10,
                "replay": 10,
                "conflict": 10,
            },
            retries_count_toward_rps=True,
        )
        run.save("load-plan.json", run.summary)
        emit("load_started", **run.summary)
        next_key = 20
        pending = set()
        tasks = []
        dispatched = []
        dropped = 0
        unexpected = []

        async def send(index, scheduled, create_key):
            slot = index % 10
            operation, method, path = "", "GET", "/jobs"
            key, payload = None, None
            expected = {200}
            if slot < 4:
                operation, method, key = "create", "POST", create_key
                payload = run.intended[key]
                expected = {201}
            else:
                existing = rng.choice(list(run.identifiers))
                job_id = run.identifiers[existing]
                if slot in (4, 5):
                    operation, path = "status", f"/jobs/{job_id}"
                elif slot == 6:
                    operation, path = "list", "/jobs?limit=20"
                elif slot == 7:
                    operation, method, path = "cancel", "POST", f"/jobs/{job_id}/cancel"
                    expected = {200, 409}
                else:
                    operation, method, key = (
                        ("replay" if slot == 8 else "conflict"),
                        "POST",
                        existing,
                    )
                    payload = run.intended[key].copy()
                    if slot == 9:
                        payload["value"] += 1
                        expected = {409}
            dispatched.append(time.perf_counter())
            status, body = await run.request(
                operation, method, path, key=key, payload=payload, scheduled=scheduled
            )
            if slot < 4 and status in (200, 201):
                run.identifiers[key] = body["id"]
            if status not in expected:
                unexpected.append({"index": index, "operation": operation, "status": status})

        for index in range(count):
            scheduled = offered_started + index / args.rps
            await asyncio.sleep(max(0, scheduled - time.perf_counter()))
            key = None
            if index % 10 < 4:
                key = keys[next_key]
                next_key += 1
            if len(pending) >= 512:
                dropped += 1
                continue
            task = asyncio.create_task(send(index, scheduled, key))
            tasks.append(task)
            pending.add(task)
            task.add_done_callback(pending.discard)
        await asyncio.gather(*tasks)
        finished = time.perf_counter()
        latencies = run.latencies[latency_offset:]
        lags = run.lags[lag_offset:]
        measured_statuses = run.statuses - setup_statuses
        await run.drain(60)
        await asyncio.sleep(0.5)
        await run.validate()
        samples = [s for s in run.samples if offered_started <= s["monotonic"] <= finished]
        depths = [s["states"].get("queued", 0) + s["states"].get("running", 0) for s in samples]
        late = [s for s in samples if s["monotonic"] >= offered_started + args.seconds / 2]
        growth = 0
        if len(late) >= 2:

            def depth(sample):
                return sample["states"].get("queued", 0) + sample["states"].get("running", 0)

            growth = (depth(late[-1]) - depth(late[0])) / (
                late[-1]["monotonic"] - late[0]["monotonic"]
            )
        dispatch_span = dispatched[-1] - dispatched[0] + 1 / args.rps
        criteria = {
            "dispatched_99_percent": len(dispatched) >= count * 0.99,
            "dispatch_rps_99_to_101": 99 <= len(dispatched) / dispatch_span <= 101,
            "unexpected_error_ratio_under_1_percent": len(unexpected) / count < 0.01,
            "p95_under_250ms": percentile(latencies, 95) < 250,
            "p99_under_1000ms": percentile(latencies, 99) < 1000,
            "dispatch_lag_p99_under_100ms": percentile(lags, 99) < 100,
            "backlog_growth_at_most_1_per_second": growth <= 1,
            "max_depth_at_most_200": max(depths, default=0) <= 200,
            "drain_within_60_seconds": run.summary["drain_seconds"] <= 60,
            "database_invariants": not run.summary["assertions_failed"],
        }
        run.summary.update(
            scheduled_requests=count,
            setup_requests=setup_requests,
            measured_requests=run.request_count - setup_requests,
            dispatched=len(dispatched),
            dropped=dropped,
            dispatch_rps=len(dispatched) / dispatch_span,
            completed_rps=sum(n for status, n in measured_statuses.items() if status.isdigit())
            / (finished - offered_started),
            successful_rps=(len(latencies) - len(unexpected)) / (finished - offered_started),
            measured_statuses=dict(measured_statuses),
            unexpected=unexpected,
            measured_latency_ms={f"p{p}": percentile(latencies, p) for p in (50, 95, 99)},
            measured_dispatch_lag_ms={f"p{p}": percentile(lags, p) for p in (50, 95, 99)},
            backlog_growth_per_second=growth,
            max_depth=max(depths, default=0),
            acceptance=criteria,
            worker_terminal_rps=(
                sum(samples[-1]["states"].get(s, 0) for s in ("succeeded", "failed", "cancelled"))
                - sum(samples[0]["states"].get(s, 0) for s in ("succeeded", "failed", "cancelled"))
            )
            / (samples[-1]["monotonic"] - samples[0]["monotonic"])
            if len(samples) > 1
            else 0,
            worker_effect_rps=(
                samples[-1]["states"].get("succeeded", 0) - samples[0]["states"].get("succeeded", 0)
            )
            / (samples[-1]["monotonic"] - samples[0]["monotonic"])
            if len(samples) > 1
            else 0,
        )
        run.summary["outcome"] = "PASS" if all(criteria.values()) else "FAIL"
        assert all(criteria.values()), "load failed predeclared acceptance criteria"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    common_arguments(parser)
    parser.add_argument("--rps", type=float, default=100)
    parser.add_argument("--seconds", type=float, default=120)
    asyncio.run(main(parser.parse_args()))
