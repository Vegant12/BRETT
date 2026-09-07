---
phase: 14-deploy-pipeline-migration-safety
plan: 01
subsystem: infra
tags: [alembic, migrations, deploy-safety, postgres, testcontainers, pytest]

# Dependency graph
requires: []
provides:
  - "backend/app/db/migration_preflight.py: check_at_head(run, *, database_url) predicate comparing alembic current vs alembic heads"
  - "python -m app.db.migration_preflight entrypoint: exit 0 at head, exit 1 on drift or unset DATABASE_URL"
  - "backend/tests/test_migration_preflight.py: fast unit coverage + 3 @pytest.mark.integration drift-rehearsal tests"
affects: ["14-02 (wires scripts/deploy-cloud-run.sh to this predicate)", "14-03 (static assertions grepping for app.db.migration_preflight)"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Predicate extraction: shell out to alembic via subprocess (never check=True), never reimplement revision-resolution logic by hand"
    - "Longest-first secret redaction mirroring Settings.secret_values ordering rule, reused via app.logging.REDACTED"
    - "Fail-closed empty-set guard: bool(head_revs) and current_revs == head_revs, not just equality"

key-files:
  created:
    - backend/app/db/migration_preflight.py
    - backend/tests/test_migration_preflight.py
  modified: []

key-decisions:
  - "Split Task 1 (module + fast unit tests) and Task 2 (integration drift rehearsal) into two atomic commits, matching the plan's task boundaries exactly"
  - "Reworded a docstring from literal 'check=True' to 'does not raise on a nonzero exit' to avoid a false-positive match against the plan's own `grep -n check=True` acceptance check"

patterns-established:
  - "check_at_head(run, *, database_url) takes an injectable AlembicRunner so both a fake runner (fast tests) and the real subprocess closure (integration tests, and eventually the deploy script) exercise identical logic"

requirements-completed: [DEPLOY-04]

# Metrics
duration: ~15min
completed: 2026-09-07
---

# Phase 14 Plan 01: Migration Pre-flight Predicate Summary

**Extracted `alembic current` vs `alembic heads` comparison into an importable, redaction-safe predicate (`app.db.migration_preflight`) and proved it detects drift against a real Postgres container downgraded one revision behind head.**

## Performance

- **Duration:** ~15 min (base commit 11:31 -> final commit 11:46, Asia/Jakarta)
- **Started:** 2026-09-07T04:31:16Z
- **Completed:** 2026-09-07T04:46:00Z
- **Tasks:** 2/2 completed
- **Files modified:** 2 (both new)

## Accomplishments
- `backend/app/db/migration_preflight.py` exports `PreflightResult`, `parse_revisions`, `redact`, `build_runner`, `check_at_head`, `main` and runs as `python -m app.db.migration_preflight`
- Fail-closed logic: an empty head set (broken `script_location`, alembic missing) is never read as "in sync" — `ok = bool(head_revs) and current_revs == head_revs`
- Every error-path string is redacted through `redact()` before it can reach stdout/stderr, using the exact longest-first ordering `Settings.secret_values` documents
- A real Postgres container, downgraded from head (`0006`) to `0005` via `alembic downgrade -1`, drives three `@pytest.mark.integration` tests: drift detected with concrete revision ids named, recovery once `alembic upgrade head` reapplies, and the actual `python -m app.db.migration_preflight` subprocess exiting 1 with no DSN or password in its combined stdout+stderr
- `scripts/` was not touched — confirmed by `grep -rn "app.db.migration_preflight" scripts/` returning nothing, exactly as this plan requires (wiring is plan 14-02)

## Task Commits

Each task was committed atomically:

1. **Task 1: Build the migration pre-flight predicate module** - `a966fcb` (feat)
2. **Task 2: Rehearse the predicate against a real drifted database** - `d3ab3df` (test)

_Note: Task 1 was `tdd="true"` in the plan, but its verification loop (write module, write fast unit tests, run, all green on the first pass — no red-phase failures) meant a single `feat` commit was correct; the module and its fast tests are logically inseparable given the plan's own acceptance criteria checking both files together._

## Files Created/Modified
- `backend/app/db/migration_preflight.py` — the pre-flight predicate: `PreflightResult` (frozen dataclass), `parse_revisions`, `redact`, `build_runner`, `check_at_head`, `main`, with a `python -m` entrypoint
- `backend/tests/test_migration_preflight.py` — 14 fast unit tests (parsing, redaction, fail-closed comparison, `main`'s unset-`DATABASE_URL` path) plus 3 `@pytest.mark.integration` drift-rehearsal tests against a real container

## Decisions Made
- Kept the predicate as a small Python module shelling out to `alembic` via `subprocess.run(sys.executable, "-m", "alembic", ...)`, matching `conftest.py`'s own `alembic` fixture shape exactly, rather than a shell function in `deploy-cloud-run.sh` — this composes directly with the existing pytest fixtures and needs no `gcloud` binary to unit-test (CONTEXT.md left this boundary to the planner/executor; this was the "easier to unit-test" branch of that discretion)
- Split Task 1's file writes into "module + fast tests only" first, verified, committed, then appended Task 2's three integration tests as a second commit — this matches the plan's `<files>` declaration for each task and keeps each commit's diff scoped to exactly one task's acceptance criteria

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Docstring line matched the plan's own literal `check=True` acceptance grep**
- **Found during:** Task 1 verification
- **Issue:** `build_runner`'s docstring said "no `check=True`, because..." — a truthful description of the behavior, but the plan's acceptance criterion `grep -n "check=True" backend/app/db/migration_preflight.py` returns nothing` would fail against this literal string match in a comment, even though no code line actually passes `check=True`
- **Fix:** Reworded to "does not raise on a nonzero exit" — same meaning, no longer a literal match
- **Files modified:** `backend/app/db/migration_preflight.py`
- **Verification:** `grep -n "check=True" backend/app/db/migration_preflight.py` now returns nothing (exit 1); ruff/mypy/tests all still pass
- **Committed in:** `a966fcb` (part of Task 1 commit — caught before commit, not a follow-up fix)

---

**Total deviations:** 1 auto-fixed (1 bug — a self-inflicted acceptance-criterion false positive, not a functional issue)
**Impact on plan:** Cosmetic only. No behavior changed; the module's actual `subprocess.run` call already omitted `check=True` from the first draft.

## Issues Encountered
None — Docker was available in this environment so all three `@pytest.mark.integration` drift-rehearsal tests ran against a real `testcontainers` Postgres instance rather than being skipped.

## User Setup Required
None — no external service configuration required. This plan deliberately does not touch `scripts/deploy-cloud-run.sh` (that is plan 14-02) and introduces no new environment variables.

## Next Phase Readiness
- `app.db.migration_preflight.check_at_head` / `build_runner` / `main` are ready for plan 14-02 to wire into `scripts/deploy-cloud-run.sh` before its `exec gcloud run deploy` line
- Plan 14-03's static assertions can grep for `app.db.migration_preflight` in the deploy script once 14-02 lands
- Verified clean: `uv run pytest backend/tests -m "not integration" -q` — 650 passed, 11 skipped, 442 deselected (no regression); `uv run pytest backend/tests/test_migrations.py -q` — 3 passed (shared container correctly restored to head by `restore_schema` after both destructive drift tests); `uv run ruff check backend/` and `uv run mypy backend/app/db/migration_preflight.py` both clean

---
*Phase: 14-deploy-pipeline-migration-safety*
*Completed: 2026-09-07*

## Self-Check: PASSED

- FOUND: backend/app/db/migration_preflight.py
- FOUND: backend/tests/test_migration_preflight.py
- FOUND: .planning/phases/14-deploy-pipeline-migration-safety/14-01-SUMMARY.md
- FOUND: a966fcb (feat commit, Task 1)
- FOUND: d3ab3df (test commit, Task 2)
