from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, Header, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import text

from training_queue.config import Settings
from training_queue.db import make_database
from training_queue.schemas import Cursor, JobOut, JobPage, Payload
from training_queue.transitions import Conflict, NotFound, Queue, QueueUnavailable


def create_app(settings: Settings | None = None, queue: Queue | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        engine = None
        if queue is None:
            engine, sessions = make_database(settings.database_url)
            app.state.queue = Queue(sessions, settings)
        else:
            app.state.queue = queue
        try:
            yield
        finally:
            if engine:
                await engine.dispose()

    app = FastAPI(title="Training Job Queue", lifespan=lifespan)
    # Also permits dependency-injected tests without running the server lifespan.
    if queue is not None:
        app.state.queue = queue

    @app.exception_handler(NotFound)
    async def not_found(request, exc):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(QueueUnavailable)
    async def unavailable(request, exc):
        return JSONResponse(
            status_code=503,
            content={"detail": "database unavailable; outcome may be uncertain; retry same key/ID"},
            headers={"Retry-After": "1"},
        )

    @app.get("/health")
    async def health(request: Request):
        async def check(session):
            await session.execute(text("SELECT 1"))

        await request.app.state.queue._transaction(check)
        return {"status": "ok"}

    @app.post("/jobs", response_model=JobOut, status_code=201)
    async def create(
        payload: Payload,
        request: Request,
        response: Response,
        idempotency_key: Annotated[str, Header(min_length=1, max_length=200, pattern=r".*\S.*")],
    ):
        job, created = await request.app.state.queue.create(idempotency_key, payload)
        response.status_code = 201 if created else 200
        return job

    @app.get("/jobs", response_model=JobPage)
    async def list_jobs(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: Annotated[str | None, Query(max_length=512)] = None,
    ):
        try:
            decoded = Cursor.decode(cursor) if cursor else None
        except ValueError:
            return JSONResponse(status_code=422, content={"detail": "invalid pagination cursor"})
        jobs, next_cursor = await request.app.state.queue.list_jobs(limit, decoded)
        return JobPage(items=[JobOut.model_validate(job) for job in jobs], next_cursor=next_cursor)

    @app.get("/jobs/{job_id}", response_model=JobOut)
    async def get_job(job_id: UUID, request: Request):
        return await request.app.state.queue.get(job_id)

    @app.post("/jobs/{job_id}/cancel", response_model=JobOut)
    async def cancel(job_id: UUID, request: Request):
        return await request.app.state.queue.cancel(job_id)

    return app


app = create_app()
