---
phase: 03-hevy-integration-normalization
plan: 11
subsystem: integration
tags: [hevy, live-validation, schema-fix, observability]

requires:
  - phase: 03-hevy-integration-normalization
    provides: complete Hevy sync (client, schemas, workout/template/body/event sync, CLI) built and green against mocked responses
provides:
  - A real full sync and a real incremental sync run against the live Hevy API, both proven end-to-end
  - docs/hevy-api-observations.md — empirical record of rate limits, pagination/ordering, dumbbell semantics, body-measurement units, template inventory, unmapped templates, errors, timings
  - Fix for a live-only schema bug (HevyExerciseTemplate.equipment_category → equipment) invisible to every mocked test
  - Both open Phase 3 STATE.md blockers closed: dumbbell weight is per-dumbbell, body-measurement unsuffixed fields are centimetres
affects: [03-12, phase-4-analytics]

tech-stack:
  added: []
  patterns:
    - "Live-API validation as its own checkpoint-gated plan, run after the full mocked implementation is green — catches wire-schema drift no fixture can"

key-files:
  created:
    - docs/hevy-api-observations.md
  modified:
    - backend/app/integrations/hevy/schemas.py
    - backend/app/integrations/hevy/templates.py
    - backend/tests/fixtures/hevy/exercise_templates_page1.json
    - .planning/STATE.md

key-decisions:
  - "Dumbbell weight_kg is stored and used as-is, per-dumbbell — no correction factor. Confirmed directly against the Hevy app."
  - "Body-measurement unsuffixed fields (waist, abdomen, hips, four limb fields) are centimetres — confirmed directly against the Hevy app, no unit conversion needed."
  - "Fixed the equipment/equipment_category schema mismatch immediately rather than only documenting it, since it silently nulled a real column for all 463 templates and blocked this very plan's own dumbbell-discriminator query."

patterns-established:
  - "When a live-API validation plan finds a code defect, fix it in place, re-verify the full suite, and re-sync to confirm the fix — don't just log it as a finding for a later phase."

requirements-completed: [HEVY-01, HEVY-02, HEVY-07, HEVY-09]

duration: ~50min (interactive, spanning two human checkpoints)
completed: 2026-08-30
---

# Phase 3: Live Hevy API Validation Summary

**Ran the sync against the real Hevy API, confirmed both previously-undocumented semantics by direct comparison with the app, and fixed a schema bug that only live data could expose.**

## Performance

- **Duration:** ~50 min wall clock, spanning two human checkpoints (API key provisioning, app comparison)
- **Tasks:** 3/3 (checkpoint:human-action, auto, checkpoint:human-verify)
- **Files modified:** 4 (2 code, 1 fixture, 1 doc created, STATE.md)

## Accomplishments

- Full sync: 327 workouts, 463 exercise templates, 123 body-measurement rows, 52 requests, ~38s, zero errors or skips.
- Incremental sync immediately after: 0 new events, correctly did zero workout work, ~11s.
- Confirmed `/v1/workouts` pages arrive newest-first (RESEARCH assumption A3).
- Confirmed `/v1/workouts/count` (327) matches the local row count exactly.
- Found and fixed a live-only schema bug: `HevyExerciseTemplate.equipment_category` never matched the real wire field `equipment`, so the column was silently `null` for every template despite all mocked tests passing (the hand-written fixture used the same wrong key).
- **Dumbbell weight verdict: per-dumbbell.** Confirmed against the Hevy app for Romanian Deadlift (Dumbbell), 2026-08-29, `weight_kg=26.0` — the app shows 26 kg per dumbbell. No correction factor needed.
- **Body-measurement unit verdict: centimetres.** Confirmed against the Hevy app for the most recent `waist_cm=80.00` (2026-08-25) entry.
- Spot-check of a recent workout against the app: matched.

## Task Commits

1. **Task 1: Supply a real Hevy API key** — no code commit (human action: `.env` created locally, gitignored, never committed; local Postgres migrated to head via `alembic upgrade head`)
2. **Task 2: Run the live full + incremental sync and record what the API actually does** — `c108fa3` (feat: observations doc + equipment schema fix)
3. **Task 3: Confirm dumbbell weight semantics and body-measurement units against the Hevy app** — verdicts recorded in this SUMMARY and in `.planning/STATE.md`; writing them into `docs/hevy-api-observations.md`'s `PENDING` markers is plan 03-12 task 1's job, per this plan's own instructions

**Plan metadata:** (this commit)

## Files Created/Modified

- `docs/hevy-api-observations.md` — the empirical record; all 8 required sections filled, dumbbell/units sections marked `PENDING — see task 3` per this plan's own content rules (03-12 fills them in)
- `backend/app/integrations/hevy/schemas.py` — `HevyExerciseTemplate.equipment_category` renamed to `equipment`, matching the live wire field, with a docstring explaining why the mismatch didn't raise
- `backend/app/integrations/hevy/templates.py` — upsert now reads `template.equipment` into the `equipment_category` DB column (DB keeps its more descriptive internal name)
- `backend/tests/fixtures/hevy/exercise_templates_page1.json` — corrected `equipment_category` key to `equipment` so future fixture-based tests exercise the real wire shape
- `.planning/STATE.md` — closed the two open Phase 3 blockers (live-schema assumptions, dumbbell/units), added a new narrower open item noting rate limits remain genuinely unobserved (no request in this sync ever hit one)

## Decisions Made

- Applied the equipment-field fix immediately rather than deferring it, since the bug blocked this plan's own dumbbell-discriminator query (`equipment_category == 'dumbbell'`) and silently corrupted a real DB column with zero test coverage to catch it.
- Left the two `PENDING` markers in `docs/hevy-api-observations.md` unedited, per the plan's explicit instruction that writing the final verdicts into that file is plan 03-12 task 1's job — this SUMMARY and STATE.md carry the verbatim verdicts for that plan to consume.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 — Real code bug found via live validation] `equipment_category` wire-field mismatch**
- **Found during:** Task 2, while building the dumbbell candidate query (`equipment_category == 'dumbbell'` returned zero rows against 463 real templates)
- **Issue:** `HevyExerciseTemplate` declared `equipment_category: str | None = None`, but a live `/v1/exercise_templates` response shows the field is actually named `equipment`. `_HevyModel`'s `extra="ignore"` swallowed the real field silently instead of raising, and the hand-written test fixture from plan 03-01 happened to use the same wrong key, so all mocked tests passed regardless.
- **Fix:** Renamed the Pydantic field to `equipment` in `schemas.py`, updated the DB-mapping line in `templates.py` to read `template.equipment`, corrected the fixture key, re-ran the full suite (281 passed) and `mypy`/`ruff` (clean), then re-ran a live full sync to confirm `equipment_category` now populates correctly (`machine` 151, `none` 106, `barbell` 76, `dumbbell` 72, `other` 17, `kettlebell` 13, `resistance_band` 13, `plate` 8, `suspension` 7).
- **Files modified:** `backend/app/integrations/hevy/schemas.py`, `backend/app/integrations/hevy/templates.py`, `backend/tests/fixtures/hevy/exercise_templates_page1.json`
- **Verification:** `uv run pytest` (281 passed), `uv run mypy backend/app` (clean, 41 files), `uv run ruff check .` (clean), live re-sync confirmed `equipment_category` distribution above.
- **Committed in:** `c108fa3`

---

**Total deviations:** 1 auto-fixed (Rule 2 — genuine schema-drift bug, only detectable via live data).
**Impact on plan:** Necessary fix, not scope creep — the plan's own Task 2 instructions require using `equipment_category == 'dumbbell'` as the discriminator, and the bug made that impossible before the fix. This is exactly the class of defect D-11's live-validation plan exists to catch.

## Issues Encountered

Two setup snags during Task 1, both resolved and worth carrying forward for future local-setup docs:
1. `docker compose up -d db` fails with `no such service: #` if an inline `# comment` is appended to the command in an interactive zsh session (zsh doesn't strip trailing comments by default). Run the bare command.
2. `alembic upgrade head` run from `backend/` fails with `database_url: Field required` because `pydantic-settings`' `env_file=".env"` resolves relative to the process's CWD, so it looks for `backend/.env` (doesn't exist) rather than the repo-root `.env`. Fix: pass `DATABASE_URL` as an explicit env var on the command, matching how `backend/tests/conftest.py` already invokes alembic as a subprocess with `cwd=BACKEND_DIR` and an explicit `env={**os.environ, "DATABASE_URL": ...}`.

## User Setup Required

None further — the user has already provisioned a real `HEVY_API_KEY` in a local, gitignored `.env` and migrated their local Postgres to head. Nothing here requires repeating for later phases; production data loading (if any) is explicitly deferred to Phase 7 per this plan's own instructions.

## Next Phase Readiness

Plan 03-12 (exercise curation) is unblocked: the 77-item unmapped-template list (with external IDs, titles, primary muscle groups, and now-correct equipment categories) is recorded in `docs/hevy-api-observations.md`'s "Unmapped templates" section, ready for curation against the user's real exercise inventory. 03-12 task 1 also needs to replace the two `PENDING` markers in that file with the verdicts recorded here.

No blockers for Phase 4 (analytics): dumbbell tonnage and body-composition trend calculations can proceed without a unit-conversion or per-dumbbell/combined correction step, since both were confirmed to already need none.

---
*Phase: 03-hevy-integration-normalization*
*Completed: 2026-08-30*
