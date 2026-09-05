---
phase: 08-apple-health-nutrition-ingest
verified: 2026-09-03T11:00:00Z
status: passed
score: 5/5 roadmap success criteria verified (4/4 08-08 must_haves satisfied, one closed as MOOT with disclosed reasoning rather than literally confirmed)
overrides_applied: 0
---

# Phase 8: Apple Health & Nutrition Ingest Verification Report

**Phase Goal:** Apple Health activity and nutrition data flows from the user's phone into BRETT continuously — authenticated, deduplicated, and free of Hevy re-exports.
**Verified:** 2026-09-03T11:00:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A real Health Auto Export run from the user's phone lands steps, active/basal energy, distance, flights climbed, calories and the six macros in BRETT — verified against the live deployment | ✓ VERIFIED | `08-08-SUMMARY.md` Task 3: `health_ingest_completed`, `rows_upserted=23, rows_skipped=0`; all 12 `METRIC_REGISTRY` keys landed for 2026-09-02 (11/12 for the partial day, `sodium` genuinely not logged yet). Setup doc §9 records the same observation independently. `backend/app/integrations/health_auto_export/registry.py` confirms exactly 12 registry entries (5 activity + 7 nutrition) matching the claimed list |
| 2 | A POST with no credential or a wrong credential is rejected, writes nothing, returns no detail about why | ✓ VERIFIED | `backend/app/integrations/health_auto_export/auth.py` (constant-time `compare_digest`, fail-closed on unset secret) backed by `test_health_ingest_auth.py`. Live: setup doc §9 rows 2-3 — `cmp` reports the no-credential and wrong-credential bodies byte-identical, token appears 0 times in body/headers/logs |
| 3 | Re-sending an overlapping export window leaves row counts and every computed daily value unchanged | ✓ VERIFIED | `upsert_health_metric` (`ingest.py:129-173`) uses unconditional REPLACE semantics on `ON CONFLICT`, justified in the module docstring against RESEARCH Pitfall N-2. `test_health_ingest_idempotency.py` (10 tests, all passing) covers exact-redelivery, overlapping-window, two-sources, fractional-count, partial-failure cases. Live: setup doc §9 Task-3 check 5 — repeat export left 23/23 rows and `sum(sample_count)` unchanged |
| 4 | Apple Health workouts and Hevy-originated body-mass rows never enter BRETT's training/body data — Claude's volume, frequency, body-weight numbers are identical before/after Apple Health data exists | ✓ VERIFIED | `test_health_ingest_isolation.py` — 6 tests including `test_apple_health_ingest_changes_no_hevy_number`, `test_no_apple_health_row_lands_in_body_measurements`, `test_workout_count_is_unchanged_by_ingest`, `test_no_hevy_sourced_row_lands_in_health_daily_metrics`. `normalize.py`'s `is_hevy_sourced()` filters at ingest; migration 0005 docstring confirms no workout table and no new `body_measurements.source` value were added by design (D-01/D-02) |
| 5 | Claude can see when Apple Health data last arrived, reported separately from Hevy's last sync, through the existing freshness envelope | ✓ VERIFIED | `analytics/metadata.py` — `PROVIDER_APPLE_HEALTH` × `(RESOURCE_ACTIVITY, RESOURCE_NUTRITION)` are distinct entries in `FRESHNESS_RESOURCES`. `ingest_payload` advances only the resources actually present in a delivery (`_KIND_TO_RESOURCE`, D-03), so nutrition doesn't falsely read fresh off an activity-only delivery. Live: setup doc plan verify step confirmed two independent timestamps against Hevy's unchanged three |

**Score:** 5/5 roadmap success criteria verified

### 08-08 Plan-Level Must-Haves (frontmatter)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| A | Deployed service accepts a real HAE run and stores all activity+nutrition metrics | ✓ VERIFIED | Same as SC#1 above |
| B | No-credential POST rejected, writes nothing, no detail | ✓ VERIFIED | Same as SC#2 above |
| C | Exact Hevy `source` string is known and recorded — Assumption A1 is closed | ⚠ CLOSED-AS-MOOT (accepted) | See "Assumption A1" analysis below — not a code gap |
| D | Device's required configuration is written down as a prerequisite | ✓ VERIFIED | `docs/health-auto-export-setup.md` §3 states Aggregate Data as a "correctness prerequisite, not a preference," with the mechanism spelled out |

### Assumption A1 — Closed as MOOT, evaluated

The plan (`08-08-PLAN.md` lines 397-460) anticipated only two outcomes for A1: CONFIRMED (event fires) or REFUTED (event doesn't fire, meaning the string-match predicate has the wrong spelling — remediable by reading `source_name` from the stored rows and adding the real spelling to `_HEVY_SOURCE_ALIASES`). What actually happened is a third case the plan didn't anticipate: the event didn't fire, **and** an independent check (the user reading the native Health app's own source list for `active_energy` on the exported training day) confirmed Hevy is not a source at all for that metric — there was no Hevy-originated data present in the delivery for the predicate to either match or miss.

This is verified as reasonable, not glossed over:
- It is disclosed as MOOT explicitly (not silently reported as CONFIRMED, which would overstate confidence in `_HEVY_SOURCE_ALIASES`'s spelling).
- It is corroborated by an independent data source (native Health app UI) rather than inferred solely from the log event's absence, which is the correct diagnostic — the plan's own binary logic would have misclassified this case as REFUTED and sent a future reader hunting for a spelling that doesn't exist.
- It is consistent with a prior finding (D-01: Hevy's body-mass HealthKit write-back "stops in May 2025").
- The predicate (`_HEVY_SOURCE_ALIASES = frozenset({"hevy"})`) was correctly left unchanged — there was no observed spelling to add, and changing it without evidence would be worse than leaving it.
- The exclusion predicate remains load-bearing for Phase 9's `export.xml` backfill (which does cover the period Hevy demonstrably wrote to HealthKit — 52/79 body-mass, 218/221 workouts, per D-01/D-02).
- The residual risk (predicate untested against a live Hevy-sourced datapoint) is explicitly tracked as Deferred Issue 4 in `08-08-SUMMARY.md` and as a "New open item" in `.planning/STATE.md`'s Blockers section — not silently dropped.

**Conclusion:** must-have C is not literally satisfied (the exact string is not known, because there was nothing live to observe), but the phase's actual goal — HEALTH-08 exclusion correctness — is not compromised: `is_hevy_sourced()` is unit-tested against the `export.xml`-confirmed spelling (`"hevy"`, casefolded) via `test_health_auto_export_normalize.py -k hevy` (17 tests, all passing), the predicate is currently vacuously safe (nothing to exclude), and the gap in live coverage is honestly tracked for the case it later matters. Treated as **verified-with-caveat**, not a gap requiring a closure plan.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `docs/health-auto-export-setup.md` | Device-side prerequisite doc, no credential value | ✓ VERIFIED | 270+ lines, 9 sections, exists, contains "Daily" 6+ times, `health_ingest_multi_point_day`, `api/v1/ingest/health-auto-export`, no `bearer [a-z0-9_-]{20,}` pattern. "Aggregation interval" wording fully corrected to "Aggregate Data" (only remaining occurrence is inside the corrected explanatory text itself, not a live instruction) |
| `backend/tests/fixtures/hae/device_capture.json` | One real payload from the user's phone | ✓ VERIFIED (disclosed as reconstructed) | Exists, valid JSON, round-trips through `HAEPayload`/`normalize_payload` per SUMMARY self-check. Disclosed as reconstructed (qty values synthetic; HAE has no export-request-body feature) rather than presented as a literal capture — an honest limitation, not a hidden one |
| `backend/migrations/versions/0005_health_daily_metrics.py` | `health_daily_metrics` table | ✓ VERIFIED | Present, matches model, applied to production (`alembic current` → `0005 (head)` per live verification) |
| `backend/app/api/routes/health_ingest.py` | Webhook route | ✓ VERIFIED, WIRED | Registered via `app.include_router(health_ingest.router)` at `main.py:104`, **before** `app.mount("/", mcp_app)` at `main.py:112` — correct ordering per PITFALLS #1 |
| `backend/app/integrations/health_auto_export/ingest.py` | Idempotent upsert | ✓ VERIFIED | REPLACE-semantics upsert with `updated_at` fix applied (`c183ffd`); regression test present and passing |
| `backend/app/integrations/health_auto_export/normalize.py` | Hevy exclusion, unit conversion | ✓ VERIFIED | `is_hevy_sourced()`, `_HEVY_SOURCE_ALIASES` present and tested |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `docs/health-auto-export-setup.md` | `backend/app/integrations/health_auto_export/normalize.py` | Daily/Aggregate-Data prerequisite → `health_ingest_multi_point_day` drift alarm | ✓ WIRED (observed live) | Two real device exports with the toggle on produced zero `multi_point_day` events, per setup doc §9 and SUMMARY |
| `health_ingest.py` route | `ingest_payload` | Direct call, single service (blueprint §37 compliant) | ✓ WIRED | No HTTP round-trip; route parses and calls `ingest_payload` in-process |
| `ingest_payload` | `analytics/metadata.py` freshness envelope | `ensure_sync_state`/`complete_sync` with `(PROVIDER_APPLE_HEALTH, resource)` | ✓ WIRED | `_KIND_TO_RESOURCE` table-driven, total (KeyError on unmapped kind rather than silent default) |

### Code Review Findings (08-REVIEW.md)

| Finding | Severity | Status | Verification |
|---------|----------|--------|---------------|
| WR-01: `updated_at` frozen at row creation on upsert | warning | ✓ FIXED | `ingest.py:170` now includes `"updated_at": func.now()` in the `set_` dict. New test `test_updated_at_advances_on_a_resync` (`test_health_ingest_idempotency.py:338`) directly reads `created_at`/`updated_at` across two real deliveries, asserting `created_at` fixed and `updated_at` strictly advances. Verified non-vacuous per review's own revert-and-confirm-fail check |
| IN-01: docstring overstated response field count | info | ✓ FIXED | `health_ingest.py` docstring corrected "five" → "four integer counts" |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|--------------|--------|----------|
| HEALTH-06 | 08-08 (Task 3) | Apple Health activity syncs via HAE webhook | ✓ SATISFIED | Live device export landed all 5 activity metrics |
| HEALTH-07 | 08-04 | Bearer-token authentication | ✓ SATISFIED | `auth.py` + `test_health_ingest_auth.py`; live 401 contract confirmed |
| HEALTH-08 | 08-05 | Excludes Hevy-originated workouts/body-mass | ✓ SATISFIED | `is_hevy_sourced()`, no workout table added, isolation tests pass; A1 caveat noted above (does not block requirement) |
| HEALTH-09 | 08-06 | Idempotent sync | ✓ SATISFIED | REPLACE-semantics upsert, 10 idempotency tests, live repeat-export confirmation |
| HEALTH-11 | 08-02 | Freshness surfaced via existing envelope | ✓ SATISFIED | `(provider, resource)` pairs, D-03 independent advancement |
| NUTR-02 | 08-08 (Task 3) | Nutrition syncs via same webhook | ✓ SATISFIED | Live device export landed all 7 nutrition metrics |
| NUTR-03 | 08-06 | Nutrition idempotency | ✓ SATISFIED | Same idempotency suite covers nutrition rows explicitly |
| NUTR-05 | 08-02 | Nutrition freshness via envelope | ✓ SATISFIED | Same D-03 mechanism as HEALTH-11 |

No orphaned requirements: `.planning/REQUIREMENTS.md`'s traceability table maps exactly these 8 IDs to Phase 8, all marked `[x]` Complete, matching the plan frontmatter's `requirements-completed` fields across 08-02 through 08-08.

### Anti-Patterns Found

None blocking. Scan of the phase's touched files (`health_ingest.py`, `ingest.py`, `normalize.py`, `auth.py`, `registry.py`, `schemas.py`, `errors.py`) found no placeholder returns, no empty handlers, no hardcoded-empty stubs. The one real bug found by code review (WR-01) was already fixed and regression-tested before this verification ran.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full backend test suite | `uv run pytest -q` | 852 passed | ✓ PASS (matches SUMMARY/REVIEW claim exactly) |
| Health/ingest-scoped tests | `uv run pytest -q -k "health or ingest or hae"` | 170 passed | ✓ PASS |
| Route registered before catch-all mount | `grep -n "include_router\|app.mount" main.py` | `include_router` at line 104, `mount` at line 112 | ✓ PASS |
| `updated_at` fix present in code | Read `ingest.py:164-172` | `"updated_at": func.now()` present in `set_` dict | ✓ PASS |
| Metric registry has exactly 12 metrics | Read `registry.py` | 5 activity + 7 nutrition = 12 | ✓ PASS |
| A1 predicate spelling matches export.xml source | `test_health_auto_export_normalize.py -k hevy` | 17 passed | ✓ PASS |

Live device/Cloud Run behavior (curl against the production endpoint, actual phone export) was not independently re-triggered — per task instructions, the SUMMARY's live evidence (log excerpts, byte-identical `cmp` output, database row counts, migration state) was treated as credible since nothing in the codebase contradicts it, and the claimed artifacts/tests that would regress if the claims were false are present and passing.

### Human Verification Required

None. The phase's blocking human-verify checkpoint (Task 3: real device export) was already completed in this session per `08-08-SUMMARY.md`, with live evidence recorded in both the SUMMARY and `docs/health-auto-export-setup.md` §9. No further human action is needed to close this phase.

### Gaps Summary

No blocking gaps. One item (Assumption A1's exact Hevy source-string spelling) could not be settled because there is currently no live Hevy-sourced datapoint in this user's Apple Health data to observe — this is an external-world fact, not a defect in the implementation, and it is honestly disclosed with a tracked follow-up (Deferred Issue 4) rather than silently assumed safe. The one real code bug found during this phase's review (`updated_at` not advancing on upsert) was fixed and regression-tested in the same session, verified above.

A secondary structural risk was surfaced and tracked (not fixed, correctly deferred): `scripts/deploy-cloud-run.sh` has no migration step, which is now a documented second occurrence of deploy/schema drift. This is recorded in `.planning/STATE.md`'s Blockers section and `08-08-SUMMARY.md`'s Deferred Issues, explicitly flagged for resolution before Phase 9's deploy. This is appropriately a Phase 9 (or dedicated infra) concern, not a Phase 8 gap — Phase 8's own deploy succeeded once the drift was diagnosed and fixed live.

`.planning/ROADMAP.md`'s Phase 8 checkboxes (`- [ ]` for the phase and for 08-08-PLAN.md) have not yet been updated to reflect Task 3's completion — this is expected pre-verification tracking staleness for the orchestrator to update alongside this VERIFICATION.md, not a code or documentation defect.

---

*Verified: 2026-09-03T11:00:00Z*
*Verifier: Claude (gsd-verifier)*
