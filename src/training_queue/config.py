from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QUEUE_")

    database_url: str = "postgresql+asyncpg://queue:queue@localhost:55432/queue"
    lease_seconds: float = Field(default=10, gt=0, le=60)
    heartbeat_seconds: float = Field(default=3, gt=0)
    attempt_seconds: float = Field(default=120, gt=0, le=600)
    poll_seconds: float = Field(default=0.2, gt=0, le=10)
    recovery_batch: int = Field(default=32, ge=1, le=100)

    @model_validator(mode="after")
    def check_timing(self):
        if self.heartbeat_seconds >= self.lease_seconds / 2:
            raise ValueError("heartbeat_seconds must be less than half the lease")
        if self.attempt_seconds < self.lease_seconds:
            raise ValueError("attempt_seconds must be at least lease_seconds")
        return self
