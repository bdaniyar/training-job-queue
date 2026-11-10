import asyncio
from uuid import uuid4


async def test_concurrent_duplicate_posts_and_payload_canonicalization(client):
    gate = asyncio.Event()

    async def create(payload):
        await gate.wait()
        return await client.post("/jobs", json=payload, headers={"Idempotency-Key": "same"})

    tasks = [asyncio.create_task(create({} if i % 2 else {"value": 1})) for i in range(10)]
    gate.set()
    responses = await asyncio.gather(*tasks)
    assert [response.status_code for response in responses].count(201) == 1
    assert [response.status_code for response in responses].count(200) == 9
    assert len({response.json()["id"] for response in responses}) == 1
    conflict = await client.post("/jobs", json={"value": 2}, headers={"Idempotency-Key": "same"})
    assert conflict.status_code == 409


async def test_status_cancel_and_keyset_pagination(client):
    ids = []
    for i in range(7):
        response = await client.post(
            "/jobs", json={"value": i}, headers={"Idempotency-Key": f"job-{i}"}
        )
        assert response.status_code == 201
        ids.append(response.json()["id"])
    seen, params = [], {"limit": 3}
    while True:
        response = await client.get("/jobs", params=params)
        assert response.status_code == 200
        page = response.json()
        seen.extend(job["id"] for job in page["items"])
        if not page["next_cursor"]:
            break
        params["cursor"] = page["next_cursor"]
    assert seen == ids
    status = await client.get(f"/jobs/{ids[0]}")
    assert status.json()["state"] == "queued"
    assert (await client.post(f"/jobs/{ids[0]}/cancel")).json()["state"] == "cancelled"
    assert (await client.post(f"/jobs/{ids[0]}/cancel")).status_code == 200
    assert (await client.get(f"/jobs/{uuid4()}")).status_code == 404
    assert (await client.post(f"/jobs/{uuid4()}/cancel")).status_code == 404
    assert (await client.get("/health")).json() == {"status": "ok"}


async def test_invalid_requests(client):
    assert (await client.post("/jobs", json={})).status_code == 422
    for headers, body in [
        ({"Idempotency-Key": " "}, {}),
        ({"Idempotency-Key": "a"}, {"duration_ms": 60_001}),
        ({"Idempotency-Key": "a"}, {"value": "2"}),
        ({"Idempotency-Key": "a"}, {"extra": True}),
    ]:
        assert (await client.post("/jobs", json=body, headers=headers)).status_code == 422
    assert (await client.get("/jobs", params={"limit": 101})).status_code == 422
    assert (await client.get("/jobs", params={"cursor": "bad!"})).status_code == 422
    assert (await client.get("/jobs/not-a-uuid")).status_code == 422
