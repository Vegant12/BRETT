---
phase: 08-apple-health-nutrition-ingest
plan: 02
subsystem: analytics
tags: [freshness, sync-state, apple-health, nutrition, metadata, postgres, sqlalchemy]

# Dependency graph
requires:
  - phase: 03-hevy-integration-normalization
    provides: "`sync_state` table and its provider-neutral repository helpers (HEVY-09, D-08)"
  - phase: 04-volume-frequency-analytics
    provides: "`build_freshness` and the DQ-01 freshness envelope every analytics response carries"
provides:
  - "`build_freshness` takes explicit `(provider, resource)` pairs and has no provider default (RESEARCH Pitfall 7 closed)"
  - "`PROVIDER_APPLE_HEALTH`, `RESOURCE_ACTIVITY`, `RESOURCE_NUTRITION`, `APPLE_HEALTH_RESOURCES` sync-state constants"
  - "`FRESHNESS_RESOURCES_ACTIVITY`, `FRESHNESS_RESOURCES_NUTRITION`, `FRESHNESS_RESOURCES_APPLE_HEALTH` bundles for Phase 13 tools to consume"
  - "`FreshnessPair` type alias — the (provider, resource) tuple every freshness bundle is now made of"
  - "Regression guards proving activity and nutrition freshness are independent of each other and of Hevy's three resources"
affects: [08-06-health-ingest-sync-state, 13-health-mcp-tools, nutrition-analytics, activity-analytics]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Freshness bundles are tuples of (provider, resource) pairs, never bare resource names"
    - "Apple Health resources live in a SEPARATE frozenset from SYNC_RESOURCES so Hevy-only fixtures cannot seed them"

key-files:
  created: []
  modified:
    - backend/app/db/repositories/sync_state.py
    - backend/app/analytics/metadata.py
    - backend/tests/test_analytics_metadata.py
    - backend/tests/test_sync_state.py

key-decisions:
  - "`build_freshness` output stays keyed by the BARE resource name, not a `provider:resource` composite — guarded by a disjointness test rather than a response-shape change, so no existing MCP tool payload moved"
  - "`SYNC_RESOURCES` was left byte-identical and `APPLE_HEALTH_RESOURCES` added as a separate frozenset, because `conftest.py`'s `worst_case_history` iterates the former with `provider=PROVIDER_HEVY` hardcoded"
  - "The two new Apple Health sync-state tests flush rather than commit, so real `provider='hevy'` rows cannot outlive the test and collide with the Hevy sync tests sharing the session-scoped container"

patterns-established:
  - "FreshnessPair: freshness bundles carry their own provider, so one call can answer across providers"
  - "Non-vacuity probe: a throwaway reconstruction of the pre-change function proves a regression guard actually fails against the old behaviour"

requirements-completed: [HEALTH-11, NUTR-05]

# Metrics
duration: 19min
completed: 2026-09-02
---

# Phase 8 Plan 02: Pair-Based Freshness & Apple Health Sync-State Constants Summary

**`build_freshness` now takes explicit `(provider, resource)` pairs with no Hevy default, and Apple Health's `activity` and `nutrition` are two independently-tracked freshness resources**

## Performance

- **Duration:** ~19 min
- **Started:** 2026-09-02T07:16:00Z
- **Completed:** 2026-09-02T07:35:00Z
- **Tasks:** 3 of 3
- **Files modified:** 4

## Accomplishments

- **Closed RESEARCH Pitfall 7.** The `provider: str = PROVIDER_HEVY` default is gone. Every
  freshness lookup now names its provider explicitly as part of the resource pair, so an Apple
  Health resource can no longer be silently answered from Hevy's bookkeeping row.
- **D-03 implemented as two resources, not one.** `activity` and `nutrition` arrive in the same
  Health Auto Export POST but hold separate `sync_state` rows, so a nutrition-logging app that
  stops writing to HealthKit reports `None` instead of inheriting activity's "fresh" timestamp.
- **Zero response-shape churn.** `FreshnessMetadata.resources` is untouched and still keyed by
  the bare resource name. All 687 pre-existing tests pass unchanged, including the MCP tool
  schema drift guards and `test_freshness_model_cannot_carry_sync_state_internals`.
- **The Pitfall 7 guard was proven non-vacuous empirically**, not assumed — see TDD Gate
  Compliance below.
- **No call-site edits were needed.** All 8 application call sites pass `FRESHNESS_RESOURCES_*`
  bundle constants rather than literal resource lists, so converting the bundles to pairs made
  every caller correct with no diff. This was verified by grep and by mypy, not assumed.

## Task Commits

Each task was committed atomically:

1. **Task 1: Apple Health provider and resource constants** — `771db5b` (feat)
2. **Task 2: build_freshness takes (provider, resource) pairs** — `1526f8a` (feat)
3. **Task 3: independence and key-uniqueness guards** — `dd37759` (test)

## Files Created/Modified

- `backend/app/db/repositories/sync_state.py` — added `PROVIDER_APPLE_HEALTH`,
  `RESOURCE_ACTIVITY`, `RESOURCE_NUTRITION` and the separate `APPLE_HEALTH_RESOURCES` frozenset.
  `SYNC_RESOURCES` untouched. A comment records that `String(32)` covers all three new values so
  no migration is needed.
- `backend/app/analytics/metadata.py` — added the `FreshnessPair` alias, converted all four
  existing bundles to pairs, added the three Apple Health bundles, and removed the provider
  default from `build_freshness` (loop is now `for provider, resource in sorted(resources)`).
- `backend/tests/test_analytics_metadata.py` — 4 new cases (2 integration, 2 markerless).
- `backend/tests/test_sync_state.py` — 2 new integration cases covering the five-pair grid and
  the activity/nutrition split.

## Decisions Made

- **Bare resource key retained over a composite key.** A `provider:resource` composite would have
  changed every MCP tool response shape, `test_mcp_tool_schemas.py`, and
  `docs/coaching-instructions.md` — none in this phase's scope. The safety property the composite
  would have bought is instead enforced by `test_resource_names_are_unique_across_providers`,
  which fails loudly with the overlapping names if a future provider ever reuses one (T-08-07).
- **The two new `test_sync_state.py` cases flush instead of commit.** That file's `bookkeeping`
  fixture only deletes rows for its stand-in `_PROVIDER`, so committing real `provider='hevy'`
  rows for `DEFAULT_USER_ID` would outlive the test and collide with the Hevy sync tests sharing
  the session-scoped container. Flushing keeps the real provider constants under test (which a
  stand-in provider could not) while the fixture's rollback discards everything.
- **`FRESHNESS_RESOURCES_APPLE_HEALTH` was deliberately not wired into any existing tool.** A
  training-volume answer does not become stale because a nutrition app stopped logging.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Applied `ruff format` to `metadata.py`**
- **Found during:** Task 2 (bundle conversion)
- **Issue:** The plan's literal bundle formatting left `FRESHNESS_RESOURCES_BODY` split across
  three lines where `ruff format` collapses it to one 100-char line. `ruff-format` is a
  pre-commit hook, so the commit would have been reformatted out from under the plan's text.
- **Fix:** Ran `uv run ruff format backend/app/analytics/metadata.py`. Only the new lines moved;
  `git diff --stat` confirmed no pre-existing code was touched.
- **Files modified:** `backend/app/analytics/metadata.py`
- **Verification:** `uv run ruff format --check backend/app/analytics` → 12 files already formatted
- **Committed in:** `1526f8a` (Task 2 commit)

**2. [Rule 1 - Bug] Reworded a new comment that defeated the Pitfall 7 regression guard**
- **Found during:** Task 2 verification
- **Issue:** The explanatory comment I added above `FreshnessPair` contained the prose
  `provider='hevy'` within four lines of the token `build_freshness`. That tripped the plan's own
  guard, `! grep -rn "build_freshness" backend/app -A4 | grep "provider="`, which is meant to
  catch a call site re-introducing an explicit provider argument. A guard that reports a false
  positive on a comment is a guard the next reader learns to ignore.
- **Fix:** Reworded to "looked up under the Hevy provider", and added a note explaining why the
  keyword-argument form is deliberately not written in prose there.
- **Files modified:** `backend/app/analytics/metadata.py`
- **Verification:** `grep -rn "build_freshness" backend/app -A4 | grep -c "provider="` → 0
- **Committed in:** `1526f8a` (Task 2 commit)

**3. [Rule 1 - Bug] Removed an unnecessary `# type: ignore[unreachable]`**
- **Found during:** Task 3
- **Issue:** I added `# type: ignore[unreachable]` to a `nutrition.last_synced_at` reference in an
  assertion message. mypy does not narrow there, so the ignore was unused and `warn_unused_ignores
  = true` flagged it.
- **Fix:** Changed the message to interpolate `{nutrition!r}` and dropped the ignore.
- **Files modified:** `backend/tests/test_sync_state.py`
- **Verification:** `uv run mypy backend/tests/test_sync_state.py` reports no errors in that file
  (the 6 remaining errors are pre-existing in `conftest.py`, which is outside mypy's normal scope
  — the project runs mypy over `backend/app/`).
- **Committed in:** `dd37759` (Task 3 commit)

---

**Total deviations:** 3 auto-fixed (2 bugs in my own new code, 1 blocking tooling conflict)
**Impact on plan:** All three are corrections to work introduced by this plan, not scope creep.
No planned behaviour changed. The plan's task list, file list and acceptance criteria were
followed exactly.

### Plan Predictions That Held

The plan listed 9 files under `files_modified` but predicted the 8 call sites would need no edit
("converting the bundles to pairs makes them correct with **no edit**. Verify this rather than
assume it"). Verified: `grep` found zero explicit `provider=` arguments at any call site, and
mypy over `backend/app/analytics` and `backend/app/mcp` passed with no `Sequence[str]` left
behind. `volume.py`, `frequency.py`, `progression.py`, `bodyweight.py`, `records.py`,
`comparison.py`, `recomposition.py` and `mcp/tools/workouts.py` are therefore untouched by this
plan.

## TDD Gate Compliance

Task 3 carried `tdd="true"`, but the plan sequences implementation (Tasks 1–2) **before** its
test task, so a conventional RED could not be observed — the guards pass the moment they are
written. Rather than record a hollow gate, the RED state was demonstrated empirically:

A throwaway probe (`backend/tests/test_zz_red_probe.py`, created, run, and deleted before any
commit) reconstructed the pre-Task-2 `build_freshness` — bare resource names plus the
`provider=PROVIDER_HEVY` default — seeded `('hevy','workouts')` and `('apple_health','activity')`
at distinct timestamps, and asserted the same expectation
`test_apple_health_and_hevy_resources_resolve_per_provider` makes. It **failed** exactly as
predicted:

```
Differing items:
{'activity': None} != {'activity': datetime.datetime(2026, 8, 30, 7, 31, 52, tzinfo=timezone.utc)}
```

That is Pitfall 7 reproduced against a live database: a real, current Apple Health row reported
as never-synced. The guard is therefore proven non-vacuous. Gate commits in git log:
`test(08-02)` at `dd37759` follows `feat(08-02)` at `771db5b`/`1526f8a` — the plan's ordering,
not RED→GREEN ordering. Flagged here rather than silently accepted.

## Known Stubs

**None that block this plan's goal.** One intentional forward declaration:

| Item | File | Reason |
|------|------|--------|
| `FRESHNESS_RESOURCES_ACTIVITY` / `_NUTRITION` / `_APPLE_HEALTH` have no production caller yet | `backend/app/analytics/metadata.py:90-99` | Intentional and stated in the plan objective: "This plan touches no Apple Health *data* — plan 08-06 is what advances the two new rows", and Phase 13's activity/nutrition MCP tools are what consume the bundles. Adding them to an existing tool's bundle was explicitly forbidden by the plan. The bundles are fully exercised by the new tests, so they are verified code, not dead code. |

## Threat Flags

None. No new network endpoint, auth path, file-access pattern or schema change was introduced.
The threat register's four `mitigate` dispositions are all implemented and test-guarded:

| Threat ID | Mitigation | Guard |
|-----------|------------|-------|
| T-08-06 (spoofed provider) | Provider default deleted | `test_build_freshness_has_no_provider_default`, `test_apple_health_and_hevy_resources_resolve_per_provider` |
| T-08-07 (key collision) | Bare-name key + disjointness assertion | `test_resource_names_are_unique_across_providers` |
| T-08-08 (sync_state internals leak) | Loop still reads only `last_synced_at` | `test_freshness_model_cannot_carry_sync_state_internals`, `test_freshness_never_leaks_last_error` (both left intact, neither relaxed) |
| T-08-09 (fabricated Hevy rows) | `SYNC_RESOURCES` byte-identical; separate `APPLE_HEALTH_RESOURCES` | `grep -A3 "^SYNC_RESOURCES" ... ` returns 0 Apple Health references |

## Deferred Issues

- **`backend/app/mcp/server.py` fails `ruff format --check`** — pre-existing on the phase base
  commit `d688789` and untouched by this plan (`git diff --stat HEAD -- backend/app/mcp/server.py`
  is empty). `ruff format` wants to collapse the `fitness_get_muscle_group_volume` description at
  `server.py:180-181` onto one line. Out of scope per the scope boundary; logged to
  `.planning/phases/08-apple-health-nutrition-ingest/deferred-items.md`. One-line fix when a
  future plan touches that file.

## Issues Encountered

None beyond the three auto-fixed deviations above. No architectural decisions were required, no
checkpoints were hit, and no authentication gates were encountered.

## Verification

Every gate in the plan's `<verification>` block was run and passed:

```
uv run pytest                                          # 693 passed (687 baseline + 6 new)
uv run pytest -m "not integration"                     # 403 passed, 290 deselected
uv run pytest test_analytics_metadata.py test_sync_state.py -x   # 35 passed
uv run mypy backend/app/analytics backend/app/mcp      # no issues in 27 source files
uv run ruff check backend/app/analytics backend/app/mcp backend/app/db/repositories  # clean
! grep -rn "provider: str = PROVIDER_HEVY" backend/app/analytics/metadata.py         # clean
! grep -rn "build_freshness" backend/app -A4 | grep "provider="                      # clean
```

Success criteria:

- [x] `build_freshness` takes `Sequence[FreshnessPair]` and has no `provider` parameter at all
- [x] The three Apple Health bundles exist and reference `PROVIDER_APPLE_HEALTH`
- [x] The four sync-state constants exist; `SYNC_RESOURCES` is byte-identical to before
- [x] Every pre-existing test passes with no assertion on a response key changed
- [x] Activity/nutrition independence proven; cross-provider name collision guarded

## Requirements Status — REQUIREMENTS.md deliberately NOT updated

This plan declares `requirements: [HEALTH-11, NUTR-05]`, but **plan 08-06 declares the same two
IDs** (`requirements: [HEALTH-09, NUTR-03, HEALTH-11, NUTR-05]`) and is the plan that actually
advances the two Apple Health `sync_state` rows. Both requirements are phrased as an outcome —
"Apple Health / nutrition data freshness **is surfaced** through the same freshness/coverage
envelope" — and nothing surfaces it until 08-06 writes the rows and Phase 13 exposes them.

08-02 built the mechanism that makes that outcome possible and closed the correctness bug that
would have made it silently wrong. Marking HEALTH-11 and NUTR-05 complete now would report a
user-visible capability that does not yet exist, which is precisely the failure mode this project
treats as its primary risk. `REQUIREMENTS.md` is therefore left untouched; 08-06 should mark both.

This also avoids a three-way merge conflict on a shared file across the wave's parallel worktrees.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- **Plan 08-06 can proceed.** The two Apple Health `sync_state` rows it will advance now have
  named constants and no migration blocker (`String(32)` covers `apple_health`, `activity` and
  `nutrition`).
- **Phase 13's activity and nutrition MCP tools can proceed.** `FRESHNESS_RESOURCES_ACTIVITY`,
  `FRESHNESS_RESOURCES_NUTRITION` and `FRESHNESS_RESOURCES_APPLE_HEALTH` are ready to drop into a
  response envelope, and mixed-provider bundles (`FRESHNESS_RESOURCES_WORKOUTS +
  FRESHNESS_RESOURCES_ACTIVITY`) are proven to resolve per provider in a single call.
- **One thing to remember downstream:** any new provider must not reuse an existing resource name.
  `test_resource_names_are_unique_across_providers` enforces this and its failure message spells
  out both remedies.

## Self-Check: PASSED

All four modified source files exist on disk. All three task commits (`771db5b`, `1526f8a`,
`dd37759`) are present in `git log`. The temporary RED probe
(`backend/tests/test_zz_red_probe.py`) was confirmed deleted and never committed — no commit in
this plan contains a file deletion (`git diff --diff-filter=D` empty for all three), and the
working tree has no untracked files.

---
*Phase: 08-apple-health-nutrition-ingest*
*Completed: 2026-09-02*
