"""Intentionally break fencing in this process; the selected regression MUST fail.

Run through record.py. This is an opt-in negative control, never part of normal
pytest collection and never modifies source files or a running service.
"""

import pytest

from training_queue.transitions import Queue

original = Queue._owns
Queue._owns = staticmethod(
    lambda job, owner, generation, now: original(job, owner, job.generation, now)
)
raise SystemExit(
    pytest.main(["tests/test_queue.py::test_zombie_fenced_even_if_process_owner_reused", "-q"])
)
