---
phase: 09-historical-apple-health-backfill
plan: 01
subsystem: testing
tags: [apple-health, healthkit, xml, pytest, fixtures, unicode, hevy-exclusion]

# Dependency graph
requires:
  - phase: 08-apple-health-nutrition-ingest
    provides: "METRIC_REGISTRY (the 12 allowlisted wire metrics), is_hevy_sourced / _HEVY_SOURCE_ALIASES, the HAE fixture-loader convention in conftest.py, and device_capture.json — the live-verified webhook source vocabulary this plan pins against"
provides:
  - "backend/tests/fixtures/hae/export_sample.xml — a synthetic Apple Health export carrying 21 Records across all 12 in-scope HealthKit identifiers, both U+2019 device names, the Hevy exclusion cases, an unrecognized type, two malformed records, plus 1 Workout with a nested WorkoutStatistics and 1 ActivitySummary"
  - "conftest.hae_xml_fixture(name) -> Path — the XML fixture loader every later Phase 9 plan's tests import"
  - "The `realfile` pytest marker, so the opt-in test against the user's gitignored 191 MB export.xml can be deselected and never runs in CI"
  - "Six fixture-integrity tests pinning the DOCTYPE/no-ENTITY shape, the four element shapes, the U+2019 source names, and the backfill/webhook source_name subset relation"
  - "A corrected Pitfall N-3 section in normalize.py stating the live-verified source-vocabulary convergence and its natural-key consequence"
affects: [09-02, 09-03, 09-04, 09-05, 09-06, 09-07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "XML fixtures are loaded BY PATH, never pre-parsed: the module under test owns the parse, because Phase 9's whole memory argument is about HOW the file is read"
    - "U+2019 lives as a literal only in data files (.xml/.json, read with explicit encoding='utf-8') and as a \\u2019 escape in .py test code"
    - "ruff S314 on stdlib XML parsing is silenced with a documented `noqa` citing RESEARCH Pitfall 6, never by adding defusedxml"

key-files:
  created:
    - backend/tests/fixtures/hae/export_sample.xml
    - backend/tests/test_health_auto_export_backfill.py
    - .planning/phases/09-historical-apple-health-backfill/deferred-items.md
  modified:
    - backend/tests/conftest.py
    - pyproject.toml
    - backend/app/integrations/health_auto_export/normalize.py

key-decisions:
  - "HEALTH-10 is NOT marked complete by this plan: all seven Phase 9 plans carry the same requirement id, and 09-01 ships only the test bed — no backfill module exists yet"
  - "ruff S314 resolved with a documented `noqa` rather than defusedxml, per RESEARCH Pitfall 6 (defusedxml's last release is 2021-03-08, staler than the python-jose CLAUDE.md already refuses, for zero real protection on a local user-owned file)"
  - "normalize.py's Pitfall N-3 section now uses LITERAL U+2019 rather than the \\u2019 escape it previously carried, because the prose is now quoting live-verified byte-identical strings and the plan's own verification greps the raw source for them"
  - "The whole-tree `ruff format --check backend` failure was diagnosed as pre-existing (18 untouched files) and deferred rather than fixed, to keep 18 unrelated files out of a Phase 9 diff"

patterns-established:
  - "Fixture-integrity tests: a fixture that other plans' assertions depend on gets its own test file pinning its shape, so an editor silently normalising it fails the fast suite rather than quietly changing what a later test asserts"
  - "Synthetic-health-data provenance: every committed quantity is hand-invented and round; a test asserts the absence of high-precision values, since >4 decimal places is the real export's fingerprint"

requirements-completed: []

# Metrics
duration: 16min
completed: 2026-09-03
---

# Phase 9 Plan 01: Backfill Test Bed Summary

**A 21-record synthetic Apple Health `export.xml` fixture plus its path loader, the `realfile` marker, and six integrity tests that pin the two U+2019 source strings success criterion #3 depends on — and the `normalize.py` docstring correction that stops the next reader concluding criterion #3 is unachievable.**

## Performance

- **Duration:** ~16 min
- **Started:** 2026-09-03T04:44Z
- **Completed:** 2026-09-03T05:00Z
- **Tasks:** 3
- **Files modified:** 6 (3 created, 3 modified)

## Accomplishments

- **The fixture Phase 9 could not be tested without.** The real `export.xml` is 191 MB of gitignored health data. `backend/tests/fixtures/hae/export_sample.xml` reproduces its *shape* — the DOCTYPE internal subset (with zero `ENTITY` declarations), the `Record` attribute order, all twelve in-scope `HKQuantityTypeIdentifier*` strings with their real `unit=` spellings, a non-leaf `Record` with a `MetadataEntry` child, and the four non-`Record` shapes — while every quantity in it is hand-invented.
- **The Pitfall 3 trap is now reproducible.** The fixture carries a `<Workout sourceName="Hevy">` with a nested `<WorkoutStatistics type="HKQuantityTypeIdentifierActiveEnergyBurned" sum="228">` that has no `sourceName` of its own. That is the element which would let Hevy's own workout energy in through the back door if plan 09-02's parser keys on `type=` instead of on `elem.tag == "Record"` — and `is_hevy_sourced(None)` returns `False` by design, so the existing predicate would *not* catch it.
- **Success criterion #3 is now guarded rather than assumed.** `test_fixture_source_names_match_the_live_webhook_capture` asserts the `source` strings in `device_capture.json` are a subset of the fixture's `sourceName` values. `source_name` sits inside the natural key, so backfill and webhook agreeing byte-for-byte is the only reason an overlapping metric-day is one row and not two. RESEARCH assumption A3 (the user does not rename their phone) now has a detector.
- **The stale claim that made criterion #3 look impossible is gone.** `normalize.py` said *"The webhook sends `"iPhone"`; `export.xml` says `"Vegant’s iPhone"`"*. Taken at face value that means the two paths can never collide. The corrected section states the measured convergence, explains the natural-key consequence, and adds the rule that the backfill must pass `source_name` through verbatim.
- **Assumption A1 closed as MOOT**, matching STATE.md's 2026-09-03 entry — with the exclusion predicate explicitly kept load-bearing for the pre-2025 period Phase 9 imports.

## Task Commits

Each task was committed atomically:

1. **Task 1: Write the synthetic export.xml fixture** — `bb48d5d` (test)
2. **Task 2: XML fixture loader, realfile marker, and fixture-integrity tests** — `cebc73c` (test)
3. **Task 3: Correct normalize.py's stale Pitfall N-3 docstring** — `ce2d59e` (docs)

**Plan metadata:** see the final `docs(09-01)` commit.

## Files Created/Modified

- `backend/tests/fixtures/hae/export_sample.xml` — the synthetic export. 21 `Record`s (all 12 in-scope identifiers, both U+2019 device names, 3 Hevy-sourced records, 1 unrecognized type, 2 malformed D-07 cases), 1 `Workout` + nested `WorkoutStatistics`, 1 `ActivitySummary`. Carries a header comment recording the synthetic-quantity rule and the U+2019 warning.
- `backend/tests/test_health_auto_export_backfill.py` — six fixture-integrity tests. Deliberately imports nothing from the (not-yet-existing) reader module, so the file is collectable today.
- `backend/tests/conftest.py` — adds `hae_xml_fixture(name) -> Path` directly below `hae_fixture`, with the same provenance-docstring convention.
- `pyproject.toml` — registers the `realfile` marker. One line, inside `[tool.pytest.ini_options] markers`; no dependency added, `uv.lock` untouched (this phase is stdlib-only).
- `backend/app/integrations/health_auto_export/normalize.py` — docstring only, lines 21–57. No code changed; `_HEVY_SOURCE_ALIASES` byte-for-byte unchanged.
- `.planning/phases/09-historical-apple-health-backfill/deferred-items.md` — records the pre-existing whole-tree `ruff format` drift.

## Decisions Made

- **`requirements-completed: []`, not `[HEALTH-10]`.** All seven Phase 9 plans carry `requirements: [HEALTH-10]`. This plan ships the test bed only — no `backfill.py`, no CLI subcommand, no row ever written. Checking HEALTH-10 off in `REQUIREMENTS.md` now would be a false completion claim that the phase verifier would (correctly) reject. `requirements mark-complete` was deliberately not run.
- **`noqa: S314` over `defusedxml`.** RESEARCH Pitfall 6 already worked this through and the same `noqa` will appear in plan 09-02's reader. The suppression carries a docstring explaining the disposition rather than a bare comment.
- **Literal U+2019 in `normalize.py`'s docstring.** The section previously used the `’` escape. It now quotes strings whose byte-identity is the whole point, and the plan's own verification greps the raw source for them, so the literal is what belongs there. Behaviour is identical either way — `__doc__` holds the same characters.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] XML comments containing `--` made the fixture unparseable**
- **Found during:** Task 1 (fixture verification)
- **Issue:** Four of the explanatory comments I wrote used ` -- ` as an em-dash substitute, following the surrounding Python docstring house style. `--` is illegal inside an XML comment, and `ET.parse` failed with `not well-formed (invalid token): line 91, column 19`. The plan's mandated verbatim header comment was unaffected.
- **Fix:** Reworded the four comments to use `,` or `:` instead of ` -- `. No content lost.
- **Files modified:** `backend/tests/fixtures/hae/export_sample.xml`
- **Verification:** `ET.parse` succeeds; all Task 1 acceptance criteria pass (21 Records, 4 `sourceName="Hevy"`, 1 `sum="228"` on the `WorkoutStatistics` line, zero `<!ENTITY`, zero ASCII `V's iPhone`).
- **Committed in:** `bb48d5d` (Task 1 commit)

**2. [Rule 3 - Blocking] ruff S314 rejected the stdlib XML parse**
- **Found during:** Task 2 (`uv run ruff check backend pyproject.toml`)
- **Issue:** The project selects ruff's `S` (bandit) rules. `S314` fires on `ET.parse`, which the plan's test design requires. RESEARCH flagged this as "a hard gate" but the plan's action text did not carry the resolution forward.
- **Fix:** Added `# noqa: S314 -- see RESEARCH Pitfall 6` with a helper docstring recording *why* it is accepted (input is a locally-exported user-owned file; expat resolves no external entities by default; `defusedxml`'s last release predates the staleness CLAUDE.md already rejects `python-jose` for; and `test_fixture_parses_and_declares_no_entities` pins the document as declaring none).
- **Files modified:** `backend/tests/test_health_auto_export_backfill.py`
- **Verification:** `uv run ruff check backend pyproject.toml` exits 0.
- **Committed in:** `cebc73c` (Task 2 commit)

**3. [Rule 1 - Bug] Literal U+2019 leaked into the Python test file**
- **Found during:** Task 2 (checking the plan's own acceptance criterion `grep -c "V’s iPhone" …backfill.py` == 0)
- **Issue:** The plan's action text shows `DEVICE_CURRENT = "V’s iPhone"` with a literal U+2019, while its acceptance criteria forbid a literal U+2019 anywhere in a `.py` file. Written as-is, the constants would have been exactly the fragile thing the file exists to guard against.
- **Fix:** Converted both constants to `"V’s iPhone"` / `"Vegant’s iPhone"` escapes, and reworded one docstring that quoted the literal. Runtime values are unchanged.
- **Files modified:** `backend/tests/test_health_auto_export_backfill.py`
- **Verification:** `grep -c '’' backend/tests/test_health_auto_export_backfill.py` == 0; all six tests pass.
- **Committed in:** `cebc73c` (Task 2 commit)

**4. [Rule 1 - Bug] Module docstring tripped its own acceptance grep**
- **Found during:** Task 2 (checking `grep -c "health_auto_export.backfill" …backfill.py` == 0)
- **Issue:** The docstring explained that the file deliberately does *not* import `app.integrations.health_auto_export.backfill`. That prose contains the very string the acceptance criterion greps for.
- **Fix:** Reworded to "the reader module (`backfill.py`, inside the HAE package)". The point survives; the grep passes.
- **Files modified:** `backend/tests/test_health_auto_export_backfill.py`
- **Verification:** grep returns 0; fast suite green.
- **Committed in:** `cebc73c` (Task 2 commit)

### Out of Scope — Deferred, Not Fixed

**`uv run ruff format --check backend` exits 1 on 18 pre-existing files.** The plan's `<verification>` block lists this command. It fails, but on 18 files none of which this plan touched — all unmodified in the working tree, so the drift is committed state. Cause: `.pre-commit-config.yaml` runs `ruff-format` as a pre-commit hook, and pre-commit passes it only the files staged in that commit, so a file whose formatting drifted before it was last touched is never re-checked. Both files this plan touched pass `ruff format --check` individually. Full detail and a recommendation are in `deferred-items.md`.

---

**Total deviations:** 4 auto-fixed (2 blocking, 2 bugs) + 1 out-of-scope item deferred
**Impact on plan:** All four auto-fixes were required to satisfy the plan's own acceptance criteria — two were syntax/lint gates, two were internal contradictions between the plan's illustrative code and its stated greps. No scope creep; no behaviour changed.

## Issues Encountered

- **The Edit tool silently escapes literal U+2019.** Writing `’` through `Edit` produced `’` in `normalize.py`, which would have failed the plan's verification (it greps the *raw source*). Resolved with a byte-level `str.replace` via a short Python script. Worth knowing for any later Phase 9 plan that touches these strings — verify with `grep -c '’' <file>` after editing, never assume.
- **`requirements mark-complete` deliberately not run.** See Decisions Made. This is intentional, not an omission.

## Known Stubs

- `backend/tests/test_health_auto_export_backfill.py` covers **fixture integrity only**. The behavioural tests the RESEARCH test-map names for this file — `test_mapping_is_total`, `test_naming_traps`, `test_non_record_elements_never_ingested`, `test_hevy_active_energy_excluded`, `test_dry_run_writes_nothing`, `test_malformed_record_does_not_abort` — are **absent by design**: they require the reader module, which plan **09-02** creates. The plan states this explicitly ("this plan's file must not import … which does not exist until plan 09-02"). The fixture already carries every element these will need, so 09-02 adds tests, not fixture data.
- `test_backfill_idempotency.py` (integration, SC#3) and `test_backfill_real_export.py` (behind the new `realfile` marker, SC#1) do not exist yet. The `realfile` marker shipped here specifically so the latter can be written without CI ever trying to run it.

## User Setup Required

None — no external service configuration required. No dependency was added and `uv.lock` is untouched.

## Next Phase Readiness

**Ready for plan 09-02.** Everything its tests need to import now exists:

- `hae_xml_fixture("export_sample")` returns the fixture path.
- The fixture exercises every branch 09-02's parser must have: the `elem.tag == "Record"` guard (Pitfall 3), the allowlist drop (`WalkingSpeed`, `BodyMass`, `WaistCircumference`), the `is_hevy_sourced` exclusion (`ActiveEnergyBurned` from `Hevy`), the multi-point-day case that Pitfall 4 says must not warn, the two-source-names-stay-two-rows case, and both D-07 malformed shapes.
- The `# noqa: S314` precedent and its justification are already written down, so 09-02's `ET.iterparse` call does not have to re-litigate it.

**Carried concerns:**

- `ruff format --check backend` is red on 18 pre-existing files (see `deferred-items.md`). Any Phase 9 plan whose verification block includes that command will hit the same wall; it should be read as pre-existing until someone runs the one-shot reformat.
- RESEARCH assumption A3 stands: if the user renames their phone between now and the backfill run, `test_fixture_source_names_match_the_live_webhook_capture` is the only thing that will notice. It compares the fixture against `device_capture.json`, so a rename requires **both** files to be updated together.

## Self-Check: PASSED

All 7 claimed files exist on disk and all 3 task commits resolve in `git log`.

| Claim | Result |
|---|---|
| `backend/tests/fixtures/hae/export_sample.xml` | FOUND |
| `backend/tests/test_health_auto_export_backfill.py` | FOUND |
| `backend/tests/conftest.py` | FOUND |
| `pyproject.toml` | FOUND |
| `backend/app/integrations/health_auto_export/normalize.py` | FOUND |
| `.planning/phases/09-historical-apple-health-backfill/deferred-items.md` | FOUND |
| `.planning/phases/09-historical-apple-health-backfill/09-01-SUMMARY.md` | FOUND |
| commit `bb48d5d` | FOUND |
| commit `cebc73c` | FOUND |
| commit `ce2d59e` | FOUND |

Plan `<verification>` block, re-run at completion:

| Check | Result |
|---|---|
| `uv run pytest -m 'not integration' -q` | PASS — 536 passed, 322 deselected |
| `uv run pytest --markers` lists `integration` and `realfile` | PASS — both present |
| `uv run ruff check backend pyproject.toml` | PASS — all checks passed |
| `uv run ruff format --check backend` | **FAIL — pre-existing, 18 untouched files; deferred (see `deferred-items.md`). Both files this plan touched pass individually.** |
| `uv run mypy backend/app` | PASS — no issues in 73 source files |
| `backend/tests/test_health_auto_export_isolation.py` still passes | PASS — no new import crossed the HAE boundary |

---
*Phase: 09-historical-apple-health-backfill*
*Completed: 2026-09-03*
