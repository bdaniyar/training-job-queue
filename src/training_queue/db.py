from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def make_database(url: str):
    engine = create_async_engine(
        url,
        isolation_level="READ COMMITTED",
        pool_size=3,
        max_overflow=2,
        pool_timeout=5,
        pool_pre_ping=True,
        connect_args={
            "timeout": 5,
            "command_timeout": 6,
            "server_settings": {
                "timezone": "UTC",
                "lock_timeout": "2s",
                "statement_timeout": "5s",
                "idle_in_transaction_session_timeout": "5s",
                "application_name": "training-queue",
            },
        },
    )
    return engine, async_sessionmaker(engine, expire_on_commit=False)
