---
phase: 08-apple-health-nutrition-ingest
plan: 04
subsystem: integrations
tags: [health-auto-export, apple-health, nutrition, pydantic, auth, provider-isolation, tdd]

# Dependency graph
requires:
  - phase: 08-apple-health-nutrition-ingest
    plan: 01
    provides: "hae_fixture() loader + three real-shape HAE payload fixtures; HealthDailyMetric model"
  - phase: 03-hevy-integration
    provides: "the provider-isolation pattern: hevy/__init__.py boundary docstring, _HevyModel wire quarantine, payload-free error taxonomy, test_hevy_isolation.py static guards"
  - phase: 02-deploy-connector-auth-spike
    provides: "StaticTokenVerifier's bytes-compare reasoning, reproduced in auth.py"
provides:
  - "METRIC_REGISTRY: 12 verified HAE wire names in a MappingProxyType allowlist, with canonical unit, accepted units, aggregation and kind"
  - "to_canonical(): kJ->kcal, mi->km, g->mg; an unknown OR empty unit is a rejected datapoint"
  - "HAEPayload/HAEData/HAEMetric/HAEDataPoint wire quarantine, every datapoint field optional"
  - "parse_hae_datetime(): tz-aware, 24h/12h/U+202F/ISO variants -- SHARED WITH PHASE 9"
  - "HAEError/HAEPayloadError/HAEDateFormatError/UnknownUnitError, none carrying a quantity"
  - "verify_bearer(): constant-time bytes compare, fails closed on an empty secret"
  - "test_health_auto_export_isolation.py: the Pitfall N-5 guards for the new package"
affects: [08-05, 08-06, 08-07, 08-08, 09-historical-backfill]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Inverted isolation guard: an INBOUND integration forbids HTTP clients INSIDE the package, where the outbound Hevy guard forbids them outside"
    - "Every wire field optional so payload validation is TOTAL -- the drop decision moves to the normalizer, one datapoint at a time"
    - "U+202F written as a source-level escape with a test assertion that it has not been normalised away"

key-files:
  created:
    - backend/app/integrations/health_auto_export/__init__.py
    - backend/app/integrations/health_auto_export/errors.py
    - backend/app/integrations/health_auto_export/registry.py
    - backend/app/integrations/health_auto_export/schemas.py
    - backend/app/integrations/health_auto_export/auth.py
    - backend/tests/test_health_auto_export_schema.py
    - backend/tests/test_health_ingest_auth.py
    - backend/tests/test_health_auto_export_isolation.py
  modified: []

key-decisions:
  - "The 12 metric names are duplicated as literals in the test rather than imported -- importing METRIC_REGISTRY would make the drift guard assert that it equals itself"
  - "HAEMetric.name is a free-form str, not a Literal over the registry: an unlisted metric must PARSE and then be dropped by name (D-04), or it costs the recognised metrics beside it"
  - "The U+202F narrow-no-break-space is written as an escape in BOTH the parser and the test, and the test asserts it has not degraded into a duplicate of the plain-space case"
  - "REQUIREMENTS.md deliberately left unmodified -- HEALTH-06/07 and NUTR-02 are also claimed by plans 03, 05, 07 and 08, and nothing ingests yet"

patterns-established:
  - "Inverting a borrowed guard rather than copying it: direction of data flow decides whether the assertion belongs inside or outside the package"
  - "A structural source assertion (secrets.compare_digest present, exactly two encode calls) as a stand-in for a timing property that cannot be unit-tested reliably"
  - "Total validation at the wire boundary, partial rejection at the normalizer -- the blast radius of a malformed element is one datapoint, never one window"

requirements-completed: []

# Metrics
duration: 17min
completed: 2026-09-02
---

# Phase 8 Plan 04: Health Auto Export Core Summary

**The twelve verified HAE wire names, their unit conversions and their quarantine models exist in one sealed, dependency-free package — so the `dietary_`-prefix trap that D-04 would have swallowed in silence now fails a test instead.**

## Performance

- **Duration:** ~17 min
- **Started:** 2026-09-02T08:22:29Z
- **Completed:** 2026-09-02T08:38:59Z
- **Tasks:** 3 of 3 (all TDD, six commits in strict RED → GREEN alternation)
- **Files created:** 8 (5 source, 3 test), 1,156 lines
- **Tests added:** 54 (34 schema/registry, 15 auth, 5 isolation)

## Accomplishments

- **The naming trap is now a test, not a comment.** HAE's `dietary_` prefix is inconsistent — `dietary_energy` and `dietary_sugar` carry it, `protein`/`carbohydrates`/`total_fat`/`fiber`/`sodium` do not. Under D-04 a misspelling produces a log line and no failure, so `test_nutrition_names_do_not_carry_a_spurious_dietary_prefix` asserts both directions: the five wrong spellings are absent *and* the five right ones are present. A one-directional check would have passed on an empty registry.
- **Unit conversion cannot silently degrade.** `to_canonical` rejects an empty `wire_unit` on the same path as an unknown one. That is the plan's sharpest instruction and the least obvious: assuming the canonical unit when the metric-level `units` field is missing produces a plausible number that is quietly wrong, which is this project's stated primary risk.
- **Payload validation is total.** Every wire field is optional, so a heart-rate metric carrying `Min`/`Max`/`Avg` and no `qty` — a metric BRETT does not even want — parses cleanly instead of destroying a whole day of steps *and* nutrition. HAE has no documented retry, so a rejected batch is permanent loss.
- **The isolation guard is inverted, not copied.** Hevy's guard forbids `httpx2` *outside* its package because that integration is outbound. This one is inbound, so the stronger assertion applies *inside*: no HTTP client anywhere in the package. Pitfall N-5 is real — the Hevy guards are path-scoped and covered none of this.
- **Full fast suite green: 472 passed**, up from 418 at the wave-1 base.

## Task Commits

| Task | Gate | Commit | Message |
|------|------|--------|---------|
| 1 | RED | `099cee6` | `test(08-04)`: failing registry contract tests |
| 1 | GREEN | `a25da90` | `feat(08-04)`: package boundary, error taxonomy, metric registry |
| 2 | RED | `4cc95cb` | `test(08-04)`: failing wire-model and date-parser tests |
| 2 | GREEN | `fe0dba9` | `feat(08-04)`: wire-quarantine models and the shared date parser |
| 3 | RED | `d9e2ce5` | `test(08-04)`: failing bearer-verifier tests and the isolation guard |
| 3 | GREEN | `d02a15c` | `feat(08-04)`: the HAE webhook bearer verifier |

## TDD Gate Compliance

All three tasks show a `test(...)` commit immediately followed by a `feat(...)` commit. Every RED phase was verified failing before implementation — all three failed as `ModuleNotFoundError` at collection, since each task's module did not yet exist. No REFACTOR commit was needed; `ruff format` was applied inside each gate rather than after it.

One caveat recorded honestly: the five static assertions in `test_health_auto_export_isolation.py` were **already satisfied** the moment they were written, because they read committed source rather than calling new code. They are regression guards, not behaviour specifications, and the genuine RED for Task 3 was `verify_bearer` not existing. This is noted rather than hidden — a reader comparing the commits should not conclude the guards were retrofitted to pass.

## Files Created

- `backend/app/integrations/health_auto_export/__init__.py` — boundary docstring. Records *why* the boundary exists in HAE's specific terms: units are a per-metric user preference inside the phone app, converted on-device at export time, so the wire format can change with no version bump and nothing to notice it by. States the one-directional rule explicitly.
- `backend/app/integrations/health_auto_export/errors.py` — four classes. `HAEPayloadError` takes **no constructor argument at all**, so no future caller can interpolate a payload into it. `UnknownUnitError` carries the metric name and a 32-char-truncated unit and never the quantity. The word `qty` does not appear in the file.
- `backend/app/integrations/health_auto_export/registry.py` — the 12-entry `MappingProxyType` allowlist plus `to_canonical`. The naming-trap comment block is reproduced verbatim from the plan; `weight_body_mass` appears exactly once, on a comment line, recording that its absence is deliberate (D-01).
- `backend/app/integrations/health_auto_export/schemas.py` — the four wire models and `parse_hae_datetime`. Documents the two places the vendor's own TypeScript interface disagrees with real device output (`units` is metric-level, `source` is genuinely absent for gait metrics).
- `backend/app/integrations/health_auto_export/auth.py` — `verify_bearer`. Reproduces `app/mcp/auth.py`'s bytes-compare comment, which is as load-bearing as the code: it is the only place the latin-1/`TypeError`/500 chain is written down.
- `backend/tests/test_health_auto_export_schema.py` — 34 tests across both contracts.
- `backend/tests/test_health_ingest_auth.py` — 15 tests. The non-ASCII case is asserted **without** `pytest.raises`, so a regression to the `str` overload escapes as an uncaught `TypeError` rather than being absorbed as an expected rejection.
- `backend/tests/test_health_auto_export_isolation.py` — 5 guards including the inversion and the guard-on-the-guards.

## Decisions Made

- **The metric set is duplicated as literals in the test.** `EXPECTED_METRICS` is written out by hand rather than imported, following `test_mcp_tool_schemas.py`'s `EXPECTED_TOOLS`. Importing the constant would make the drift guard assert that the registry equals itself — green through any rename, which is precisely the failure D-04 makes invisible.
- **`HAEMetric.name` stays a free-form `str`.** A `Literal` over the twelve registry names would be tighter typing and the wrong behaviour: an unlisted metric must parse and *then* be dropped by name, because failing validation on it would take the recognised metrics in the same payload down with it. This is D-04 implemented structurally.
- **`data` is the only required field in the module.** Its absence means a broken envelope or something that is not HAE at all — the one failure that should reject the request rather than be salvaged. Everything below it is optional.
- **REQUIREMENTS.md left unmodified.** `HEALTH-06`, `HEALTH-07` and `NUTR-02` are claimed by plans 08-03, 08-05, 08-07 and 08-08 as well as this one, and this plan makes them *possible* rather than satisfying them — nothing ingests yet. Marking them complete now would record a requirement as met while the code that meets it is unwritten. It is also a shared file the orchestrator owns.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Bug] `strptime` in a loop trips ruff's `DTZ007`, which the repo enforces**

- **Found during:** Task 2
- **Issue:** This repo selects `DTZ` in `[tool.ruff.lint]`. `DTZ007` flags `datetime.strptime` unless it can statically see `%z` in the format string — and the plan's parser (correctly) iterates `_HAE_DATE_FORMATS`, so the format is a loop variable ruff cannot inspect. The plan's code as written does not lint clean in this repo.
- **Fix:** A narrow `# noqa: DTZ007` on that single line with a comment recording *why* it is safe — every format in the tuple ends in `%z`, and an offset-less result is rejected two lines later. The suppression is scoped to one call, not the file.
- **Files modified:** `backend/app/integrations/health_auto_export/schemas.py`
- **Verification:** `ruff check backend/app/integrations/health_auto_export` — all checks passed
- **Committed in:** `fe0dba9`

**2. [Rule 2 — Missing critical functionality] The U+202F constant was written as a literal, exactly as the plan warned**

- **Found during:** Task 2 (and again in Task 3's test file)
- **Issue:** The plan is emphatic that U+202F must be written as an escape "never as a literal … a bare U+202F in source is invisible in every diff and every review". Writing the file emitted **actual U+202F characters** into three places — the parser constant, the narrow-space test, and a non-ASCII auth test input — while looking, in every rendering available to me, like ordinary spaces. The failure mode the plan predicted happened during the act of implementing the warning about it.
- **Fix:** A scripted, verified replacement in each case, converting every literal to a backslash-escape (U+202F, U+2019, U+1F600 all spelled out in source) escape, plus a post-condition asserting **zero** literal U+202F characters remain in the source. The narrow-space test additionally gained two guard assertions — that the constant is still present in the constructed string, and that the string is not equal to its plain-space twin — so the test fails loudly rather than silently degrading into a duplicate of the test above it.
- **Files modified:** `backend/app/integrations/health_auto_export/schemas.py`, `backend/tests/test_health_auto_export_schema.py`, `backend/tests/test_health_ingest_auth.py`
- **Verification:** a scan for `ord(c) > 127` across all three files reports no literal non-ASCII outside the intentionally-Unicode fixture data
- **Committed in:** `fe0dba9`, `4cc95cb`, `d9e2ce5`

**3. [Rule 2 — Missing critical functionality] Added tests the plan's behaviour list implied but did not enumerate**

- **Found during:** Tasks 1–3
- **Issue:** Several stated behaviours had no obvious single assertion: "an unrecognised unit is never a silently stored raw number" is only meaningful if `mi→km` is also covered; "fails closed on an empty secret" is only meaningful if `Bearer ` with an empty remainder is covered too.
- **Fix:** Added `test_unit_conversion_miles_to_kilometres`, `test_every_metric_declares_a_known_kind_and_aggregation`, `test_units_are_read_from_the_metric_level_not_the_datapoint`, `test_the_date_stays_a_raw_wire_string`, `test_parse_hae_datetime_rejects_a_naive_timestamp`, `test_no_input_shape_makes_the_verifier_raise` (11 hostile header shapes including a 100 KB one), and a 5-case parametrized near-miss-secret test.
- **Files modified:** the three test files
- **Verification:** 54 tests pass; `-k unit_conversion` collects 8 against the required ≥ 5
- **Committed in:** `099cee6`, `4cc95cb`, `d9e2ce5`

---

**Total deviations:** 3 auto-fixed (1 × Rule 1, 2 × Rule 2). No Rule 4 architectural decisions arose.
**Impact on plan:** No scope creep and no interface change. Every signature in the plan's `<interfaces>` block ships exactly as specified, so plans 08-05, 08-06 and 08-07 build against what they were promised.

## Issues Encountered

- **The worktree arrived on the WRONG base, as the prompt warned.** `git merge-base HEAD e058fcf` returned `b1d3eef` (`chore: finalize STATE.md after v1.0 milestone close`) — equal to HEAD, meaning this worktree was created from the old milestone-close commit and was an *ancestor* of the required base, missing all of wave 1. Hard-reset to `e058fcfb2296dd8e412b1cb7e94d4278b402c5ae` and confirmed `git rev-parse HEAD` matched before touching anything. Safe: fresh worktree, `git status` clean. **This is now three sibling executors in a row hitting the same defect — it is systematic, not incidental, and worth fixing in the worktree-creation step rather than in each agent's startup check.**
- **No `.venv` in the worktree.** `uv run --frozen --group dev` bootstrapped 78 packages from cache in ~13s. As 08-01 noted, `[tool.uv] default-groups = []` means `--group dev` is required.
- **`git clean` was never run**, per the destructive-git prohibition. No blanket resets after the single startup correction.

## Deferred Issues

1. **`backend/tests/conftest.py` still fails `ruff format --check`** at the two pre-existing `_mcp_purge_statements` spots 08-01 documented. Confirmed still present and still out of scope; this plan does not touch that file. One `ruff format backend/tests/conftest.py` fixes it, and it will trip the `ruff-format` pre-commit hook for anyone committing that file without `--no-verify`. Recommend the orchestrator clear it once, centrally, rather than in a plan diff.
2. **`test_metric_registry_is_exactly_the_expected_set` will need updating in Phase 9 if the backfill ingests a metric the webhook does not.** The guard is deliberately an equality assertion, so that update is a conscious edit rather than a silent widening — noted so it reads as intended rather than as an obstacle.
3. **Assumption A1 remains open**, unchanged by this plan: that HAE's *webhook* sends `source: "Hevy"` (the app name) rather than a device name. The registry cannot settle it; only a captured payload from a real training day can.

## Known Stubs

None. Every function in this plan is fully implemented; there are no placeholder returns, no `TODO`/`FIXME` markers, and no component wired to empty data. The `units: str = ""` default and the empty-list datapoint defaults are documented behavioural decisions (a units-less metric must be rejected per datapoint rather than per payload), not unimplemented paths.

## User Setup Required

None — no external service configuration required by this plan. `verify_bearer` takes the secret as an argument; wiring it to configuration and to a route is plan 08-07's work.

## Next Phase Readiness

**Ready.** Every contract the downstream plans were promised exists at the promised signature:

- **08-05 (normalize/allowlist)** can `from app.integrations.health_auto_export.registry import METRIC_REGISTRY, to_canonical` and `from ...schemas import HAEPayload, parse_hae_datetime`. The D-04 drop decision has everything it needs: `METRIC_REGISTRY` is the allowlist, `MetricSpec.kind` routes to D-03's two `sync_state` resources, and `UnknownUnitError` is the per-datapoint rejection signal.
- **08-07 (ingest endpoint)** can `from app.integrations.health_auto_export.auth import verify_bearer` and append its `integration`-marked HTTP half to `test_health_ingest_auth.py`. `BAD_TOKEN = "wrong-ingest-token-7b2e-must-not-be-echoed"` is defined at module scope for `test_401_leaks_nothing` to assert against.
- **Phase 9 (historical backfill)** must call `parse_hae_datetime` and must not write a second parser. `export.xml`, `records.csv` and the webhook JSON share this format; two parsers would produce two shapes and the historical trend would silently disagree with the ongoing one. The docstring says so in capitals.

**One caution for 08-05:** the registry is keyed on HAE's wire names and `test_hae_registry_is_not_imported_outside_the_package` enforces that those names stay inside this package. The normalizer lives *inside* `health_auto_export/`, so it may import freely — but whatever it hands outward must already be BRETT's vocabulary, not HAE's.

## Self-Check: PASSED

- All 8 claimed files verified present on disk.
- All 6 claimed commit hashes verified in `git log`: `099cee6`, `a25da90`, `4cc95cb`, `fe0dba9`, `d9e2ce5`, `d02a15c`.
- `uv run pytest -m "not integration"` — **472 passed**, 290 deselected.
- The three plan files together — **54 passed**.
- `mypy backend/app/integrations/health_auto_export` — success, 5 source files.
- `ruff check` and `ruff format --check` clean on all 8 files.
- Registry read-out confirms `12` and the exact expected sorted name list.
- No shared orchestrator artifacts modified: `git status` clean, and `STATE.md`, `ROADMAP.md` and `REQUIREMENTS.md` are untouched by every commit in this plan.

---
*Phase: 08-apple-health-nutrition-ingest*
*Completed: 2026-09-02*
