from collections import Counter

from scripts.experiment import percentile, workload
from training_queue.schemas import Payload


def test_seeded_workload_has_exact_distribution_and_valid_bounded_payloads():
    jobs = workload(10000, 1101)
    assert len(jobs) == 10000
    assert Counter(job["category"] for job in jobs) == {
        "short": 8000,
        "medium": 1200,
        "long": 400,
        "heartbeat": 100,
        "transient": 200,
        "permanent": 100,
    }
    for job in jobs:
        assert Payload.model_validate(job["payload"]).duration_ms <= 4000
    assert jobs == workload(10000, 1101)
    assert jobs != workload(10000, 2202)


def test_nearest_rank_percentiles_include_tail_and_handle_empty_samples():
    assert percentile([], 99) is None
    assert percentile([1], 99) == 1
    assert percentile(list(range(1, 101)), 50) == 50
    assert percentile(list(range(1, 101)), 95) == 95
    assert percentile(list(range(1, 101)), 99) == 99
