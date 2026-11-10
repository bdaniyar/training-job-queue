"""Deliberately replaceable, bounded work; it has NO durable side effects."""

import asyncio

from training_queue.schemas import Payload


class SimulationError(Exception):
    def __init__(self, *, permanent: bool):
        super().__init__(
            "simulated permanent failure" if permanent else "simulated transient failure"
        )
        self.permanent = permanent


async def execute(payload: Payload, attempt: int) -> dict:
    await asyncio.sleep(payload.duration_ms / 1000)
    if payload.fail_permanently or attempt <= payload.fail_attempts:
        raise SimulationError(permanent=payload.fail_permanently)
    return {"squared_value": payload.value**2}
