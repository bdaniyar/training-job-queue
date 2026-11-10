-- Read committed application data in one consistent snapshot, without mutating it.
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SELECT version();
SELECT version_num FROM alembic_version;
SELECT state, count(*) AS jobs FROM jobs GROUP BY state ORDER BY state;
SELECT count(*) AS jobs, count(e.job_id) AS effects,
       count(*) FILTER (WHERE (j.state = 'succeeded') <> (e.job_id IS NOT NULL))
           AS state_effect_mismatches,
       count(*) FILTER (WHERE e.job_id IS NOT NULL AND
           (e.generation <> j.generation OR e.result <> j.result)) AS stale_or_wrong_effects
FROM jobs j LEFT JOIN job_effects e ON e.job_id = j.id;
SELECT j.id, j.state, j.attempts, j.generation, count(e.job_id) AS effects
FROM jobs j LEFT JOIN job_effects e ON e.job_id = j.id
GROUP BY j.id ORDER BY j.created_at, j.id;
COMMIT;
