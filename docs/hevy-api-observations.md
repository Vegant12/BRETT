# Hevy API — Observed Behaviour

First recorded: 2026-08-30
Method: full + incremental sync against the live API from `python -m app.cli sync-hevy`.
Source of truth for anything NOT observed here: the live OpenAPI document at
https://api.hevyapp.com/docs/ — Hevy's own preamble warns the structure may change without
notice.

## Rate limiting

No `429` and no `ratelimit-*` / `retry-after` header was observed across 52 requests in the
full sync (~38 seconds) or across 19 requests in the immediately following incremental sync
(~11 seconds). The client's `_log_rate_limit_headers` hook fired on every response; it recorded
nothing. Hevy's live OpenAPI document mentions no rate limit, and this first real sync did not
surface one either — RESEARCH assumption A4 (429 is the rate-limit status) is **unconfirmed
either way**, since no limit was hit to observe the status code on. The existing
`wait_exponential_jitter` + `stop_after_attempt(5)` retry policy is the only defense in place;
nothing here contradicts keeping it.

## Pagination and ordering

- `/v1/workouts` paginates at 10 per page as documented (`pageSize=10`), 33 pages for 327
  workouts.
- `/v1/exercise_templates` paginates at 100 per page, 5 pages for 463 templates.
- `/v1/body_measurements` paginates at 10 per page, 13 pages for 123 rows, and page 14
  returned `404` (confirmed directly) — the documented pagination terminator.
- `/v1/workouts/count` returned `{"workout_count": 327}`, matching the local row count exactly.
  No `hevy_workout_count_mismatch` was logged.
- **Page ordering (RESEARCH assumption A3): CONFIRMED newest-first.** Compared directly against
  the raw API: page 1's ten `start_time` values are strictly descending and its minimum
  (`2026-08-08T04:06:37Z`) is later than page 2's maximum (`2026-08-07T04:32:41Z`). `/v1/workouts`
  pages arrive newest-to-oldest, consistent with `/v1/workouts/events`.
- Built-in template IDs are not strictly 8-character hex: 448 of 463 match `^[0-9A-F]{8}$`,
  12 are full UUIDs (custom templates), and 3 are 8-character alphanumeric codes containing
  non-hex letters (`4288G454`, `9373FSD1`, `32HKJ34K`). Treat template IDs as opaque strings,
  not as hex specifically.

## Dumbbell weight semantics

Candidate exercise for comparison: **Romanian Deadlift (Dumbbell)**, session "Lower 2",
2026-08-29, three working sets with `weight_kg = 26.000` (reps 15, 12, 12).

Verdict: **PENDING — see task 3.**

## Body-measurement units and field coverage

123 rows synced across 13 pages. Non-null coverage per column (of 123 rows): `weight_kg` 123,
`waist_cm` 15, `right_bicep_cm` 3, `left_bicep_cm` 1. All other columns (`lean_mass_kg`,
`fat_percent`, `neck_cm`, `shoulder_cm`, `chest_cm`, `left_forearm_cm`, `right_forearm_cm`,
`abdomen_cm`, `hips_cm`, `left_thigh_cm`, `right_thigh_cm`, `left_calf_cm`, `right_calf_cm`)
are null for every row this account has recorded — this account simply doesn't track most of
them, not a sync defect.

Most recent `waist_cm` value: `80.00` on `2026-08-25`.

Verdict (are the unsuffixed fields really centimetres): **PENDING — see task 3.**

## Exercise template inventory

463 total templates. `equipment` breakdown after the schema fix below: machine 151, none 106,
barbell 76, dumbbell 72, other 17, kettlebell 13, resistance_band 13, plate 8, suspension 7.

**Schema bug found and fixed during this validation run.** `HevyExerciseTemplate` declared a
field named `equipment_category`, but the live API's wire field is `equipment`. Because
`_HevyModel` sets `extra="ignore"` with no alias generator, the mismatch did not raise — it
silently dropped the real field and left `equipment_category` (and therefore the
`exercise_templates.equipment_category` column) `None` for all 463 rows on the first sync,
even though every unit test passed against a hand-written fixture that happened to use the
wrong-but-matching key. Confirmed directly against a live `/v1/exercise_templates` response:

```json
{"id": "3BC06AD3", "title": "21s Bicep Curl", "primary_muscle_group": "biceps",
 "equipment": "barbell", "is_custom": false}
```

Fixed in `backend/app/integrations/hevy/schemas.py` (field renamed to `equipment`, matching the
wire) and `backend/app/integrations/hevy/templates.py` (maps `template.equipment` into the
`equipment_category` DB column, which keeps its more descriptive internal name). The fixture
`backend/tests/fixtures/hevy/exercise_templates_page1.json` was corrected to the real key so
future fixture-based tests catch this class of drift. Full suite re-verified green (281 tests),
`mypy`/`ruff` clean, and a second live full sync confirmed the column now populates correctly.

This was found by this plan's own live-validation purpose (D-11) working exactly as intended:
a hand-written fixture matched the *wrong* field name the code expected, so no mocked test could
ever have caught it.

## Unmapped templates

77 of 463 templates (16.6%) have no mapped canonical muscle group. All fall into three expected
buckets:

- **24 `cardio`** templates (Running, Cycling, Rowing Machine, Swimming, etc.) — no discrete
  muscle group applies.
- **45 `full_body`** templates (compound Olympic lifts — Clean, Snatch, Thruster — plus
  calisthenics like Burpee, Mountain Climber, Farmers Walk) — legitimately full-body, not a
  gap in the taxonomy.
- **4 `neck`** templates (Lying Neck Curls/Extension, weighted and unweighted) — `neck` is a
  Hevy primary-muscle-group value with no canonical mapping, per plan 03-03's finding that
  D-01's amended 19-group canonical list excludes `neck`.
- **2 `shoulders`** templates with no override yet (`Press Up`, `Single Arm Lateral Raise
  (Dumbbell)`) and **1 `other`** (`Stretching`).

This list — all 77 external IDs, titles, and muscle/equipment attributes — is what plan 03-12
curates against the user's real exercise inventory.

## Errors and skipped records

No `hevy_workout_skipped`, `hevy_template_skipped`, or `hevy_body_measurement_skipped` events
were logged in either the full or incremental run. No transient failures occurred, so
per-page-commit resumability (ROADMAP criterion 3) was not exercised by this run — it remains
verified only by the mocked resilience test suite (`test_hevy_resilience.py`), not by a real
interruption.

## Sync timings

- **Full sync:** 52 HTTP requests (5 template pages + 1 count + 33 workout pages + 13 body
  pages) in ~38 seconds. Result: 463 templates, 327 workouts, 123 body-measurement rows.
- **Incremental sync (run immediately after):** 19 requests (5 template pages, re-synced in
  full since templates have no incremental endpoint; 1 events page — 0 events, since nothing
  changed in the 5-minute window; 13 body pages, also re-synced in full) in ~11 seconds.
  `workouts=0` in the completion log, confirming the incremental path correctly did no workout
  work when nothing changed.
- `sync-status` after both runs: all three resources (`workouts`, `exercise_templates`,
  `body_measurements`) report a recent `last_synced_at` and `idle` status.
