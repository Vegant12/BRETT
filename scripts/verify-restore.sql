-- Restore-drill comparison query (D-02, ROADMAP Phase 7 criterion #3).
--
-- Run against BOTH the production branch and a branch made from a past timestamp,
-- then `diff` the two outputs. Identical output is the proof that the restore lost
-- nothing.
--
-- A count alone is not proof: an identical count over corrupted rows passes. Each
-- arm therefore carries an md5 over `string_agg(..., ORDER BY <pk>)`, and both
-- halves of that are load-bearing:
--
--   * the aggregated value is `md5(x::text)` -- the WHOLE row, every column of it,
--     not just an identifier. A digest over identifiers alone would pass just as
--     happily over rows whose contents had rotted, which is the very failure the
--     digest is here to catch.
--   * the ordering is the primary key: unique, NOT NULL, and `uuid` comparison
--     carries no collation dependency, so two byte-identical databases cannot
--     disagree about it. Ordering on a text column would make the answer depend on
--     the database's collation instead. Without an explicit ordering inside the
--     aggregate call Postgres defines none at all, and the same database can
--     digest differently on two consecutive runs.
--
-- The two `SET` statements below pin the session formatting that `x::text` depends
-- on. They change no data. Without them, two psql invocations with a differing
-- session `TimeZone` would render every timestamptz differently and report a
-- mismatch between a branch and the parent it was copied from.
--
-- READ ONLY, and deliberately so: this is run by hand, as an operator, against real
-- health data. `backend/tests/test_verify_restore_sql.py` fails the fast suite if a
-- write verb, an unordered aggregate, a connection string, or a newly mapped table
-- missing from this file ever appears.
--
--   psql "$PROD_DSN"  -f scripts/verify-restore.sql > /tmp/prod.txt
--   psql "$DRILL_DSN" -f scripts/verify-restore.sql > /tmp/drill.txt
--   diff /tmp/prod.txt /tmp/drill.txt
--
-- The full procedure, the real-incident variant, and the record of the first drill
-- are in docs/runbook-backup-restore.md.

SET TimeZone TO 'UTC';
SET DateStyle TO 'ISO, MDY';

  SELECT 'users' AS t, count(*) AS n,
         md5(string_agg(md5(x::text), ',' ORDER BY x.id)) AS digest
    FROM users x
UNION ALL
  SELECT 'workouts', count(*),
         md5(string_agg(md5(x::text), ',' ORDER BY x.id))
    FROM workouts x
UNION ALL
  SELECT 'workout_exercises', count(*),
         md5(string_agg(md5(x::text), ',' ORDER BY x.id))
    FROM workout_exercises x
UNION ALL
  SELECT 'workout_sets', count(*),
         md5(string_agg(md5(x::text), ',' ORDER BY x.id))
    FROM workout_sets x
UNION ALL
  SELECT 'exercise_templates', count(*),
         md5(string_agg(md5(x::text), ',' ORDER BY x.id))
    FROM exercise_templates x
UNION ALL
  SELECT 'exercise_muscles', count(*),
         md5(string_agg(md5(x::text), ',' ORDER BY x.id))
    FROM exercise_muscles x
UNION ALL
  SELECT 'exercise_muscle_overrides', count(*),
         md5(string_agg(md5(x::text), ',' ORDER BY x.id))
    FROM exercise_muscle_overrides x
UNION ALL
  SELECT 'body_measurements', count(*),
         md5(string_agg(md5(x::text), ',' ORDER BY x.id))
    FROM body_measurements x
UNION ALL
  SELECT 'health_daily_metrics', count(*),
         md5(string_agg(md5(x::text), ',' ORDER BY x.id))
    FROM health_daily_metrics x
UNION ALL
  SELECT 'sync_state', count(*),
         md5(string_agg(md5(x::text), ',' ORDER BY x.id))
    FROM sync_state x
UNION ALL
  SELECT 'user_program_history', count(*),
         md5(string_agg(md5(x::text), ',' ORDER BY x.id))
    FROM user_program_history x
UNION ALL
  SELECT 'program_switch_tokens', count(*),
         md5(string_agg(md5(x::text), ',' ORDER BY x.id))
    FROM program_switch_tokens x
ORDER BY 1;
