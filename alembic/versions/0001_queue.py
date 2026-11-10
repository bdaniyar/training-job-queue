"""Jobs, countable effects, and immutable identity/payload/terminal rows."""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE jobs (
            id uuid PRIMARY KEY,
            idempotency_key varchar(200) NOT NULL UNIQUE,
            payload jsonb NOT NULL,
            state varchar(16) NOT NULL DEFAULT 'queued',
            attempts integer NOT NULL DEFAULT 0,
            generation integer NOT NULL DEFAULT 0,
            owner uuid,
            lease_until timestamptz,
            attempt_deadline timestamptz,
            available_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            finished_at timestamptz,
            result jsonb,
            error text,
            CONSTRAINT state CHECK (state IN ('queued','running','succeeded','failed','cancelled')),
            CONSTRAINT key_length CHECK (length(idempotency_key) BETWEEN 1 AND 200),
            CONSTRAINT payload_object CHECK (jsonb_typeof(payload) = 'object'),
            CONSTRAINT attempts CHECK (attempts BETWEEN 0 AND 5 AND generation = attempts),
            CONSTRAINT queued_budget CHECK (state != 'queued' OR attempts < 5),
            CONSTRAINT running_attempt CHECK (state != 'running' OR attempts > 0),
            CONSTRAINT ownership CHECK (
                (state = 'running' AND owner IS NOT NULL AND lease_until IS NOT NULL
                    AND attempt_deadline IS NOT NULL AND lease_until <= attempt_deadline) OR
                (state != 'running' AND owner IS NULL AND lease_until IS NULL
                    AND attempt_deadline IS NULL)),
            CONSTRAINT finished CHECK (
                (state IN ('succeeded','failed','cancelled')) = (finished_at IS NOT NULL)),
            CONSTRAINT result CHECK ((state = 'succeeded') = (result IS NOT NULL)),
            CONSTRAINT failed_reason CHECK (state != 'failed' OR error IS NOT NULL)
        )
    """)
    op.execute("""
        CREATE TABLE job_effects (
            job_id uuid PRIMARY KEY REFERENCES jobs(id),
            generation integer NOT NULL CONSTRAINT positive_generation CHECK (generation > 0),
            result jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp()
        )
    """)
    op.execute("CREATE INDEX ix_jobs_listing ON jobs (created_at, id)")
    op.execute("""
        CREATE INDEX ix_jobs_queued ON jobs (available_at, created_at, id) WHERE state = 'queued'
    """)
    op.execute("CREATE INDEX ix_jobs_running ON jobs (lease_until, id) WHERE state = 'running'")
    op.execute("""
        CREATE FUNCTION guard_job_update() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
               OR NEW.payload IS DISTINCT FROM OLD.payload
               OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'job identity and payload are immutable' USING ERRCODE = '23514';
            END IF;
            IF OLD.state IN ('succeeded','failed','cancelled') AND NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION 'terminal jobs are immutable' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER jobs_guard BEFORE UPDATE ON jobs
        FOR EACH ROW EXECUTE FUNCTION guard_job_update()
    """)


def downgrade():
    op.execute("DROP TABLE job_effects")
    op.execute("DROP TABLE jobs")
    op.execute("DROP FUNCTION guard_job_update()")
