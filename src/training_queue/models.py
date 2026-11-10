import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "state IN ('queued','running','succeeded','failed','cancelled')", name="state"
        ),
        CheckConstraint("length(idempotency_key) BETWEEN 1 AND 200", name="key_length"),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_object"),
        CheckConstraint("attempts BETWEEN 0 AND 5 AND generation = attempts", name="attempts"),
        CheckConstraint("state != 'queued' OR attempts < 5", name="queued_budget"),
        CheckConstraint("state != 'running' OR attempts > 0", name="running_attempt"),
        CheckConstraint(
            "(state = 'running' AND owner IS NOT NULL AND lease_until IS NOT NULL "
            "AND attempt_deadline IS NOT NULL AND lease_until <= attempt_deadline) OR "
            "(state != 'running' AND owner IS NULL AND lease_until IS NULL "
            "AND attempt_deadline IS NULL)",
            name="ownership",
        ),
        CheckConstraint(
            "(state IN ('succeeded','failed','cancelled')) = (finished_at IS NOT NULL)",
            name="finished",
        ),
        CheckConstraint("(state = 'succeeded') = (result IS NOT NULL)", name="result"),
        CheckConstraint("state != 'failed' OR error IS NOT NULL", name="failed_reason"),
        Index(
            "ix_jobs_queued",
            "available_at",
            "created_at",
            "id",
            postgresql_where=text("state = 'queued'"),
        ),
        Index("ix_jobs_running", "lease_until", "id", postgresql_where=text("state = 'running'")),
        Index("ix_jobs_listing", "created_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="queued")
    attempts: Mapped[int] = mapped_column(nullable=False, server_default="0")
    generation: Mapped[int] = mapped_column(nullable=False, server_default="0")
    owner: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    error: Mapped[str | None] = mapped_column(Text)


class JobEffect(Base):
    __tablename__ = "job_effects"
    __table_args__ = (CheckConstraint("generation > 0", name="positive_generation"),)

    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"), primary_key=True)
    generation: Mapped[int] = mapped_column(nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )
