---
phase: 06-mcp-tools
plan: 11
subsystem: testing
tags: [mcp, integration-tests, security, secret-redaction, disambiguation, fixtures]

# Dependency graph
requires:
  - phase: 06-mcp-tools (plan 06-03)
    provides: the committed_history fixture and the GoldenBuilder API (template/workout/body_measurement)
  - phase: 06-mcp-tools (plan 06-09)
    provides: all thirteen tools registered on the live MCPServer, each wrapped in @safe_tool
  - phase: 02-deploy-connector-auth-spike
    provides: fitness_ping, the in-memory Client(mcp) pattern and the DEAD_DB_URL leak idiom
  - phase: 01-backend-foundation
    provides: Settings.secret_values() and the three-layer structlog redaction chain
provides:
  - "Behavioural coverage for every one of the thirteen registered MCP tools against committed seeded data"
  - "_seed_reference_history — the reusable reference training history (5 templates, 6 workouts, 30 weigh-ins, 3 sync_state rows)"
  - "MINIMAL_TOOL_ARGUMENTS — the minimal valid call for every registered tool, exported and consumed by two suites"
  - "The DSN-leak test parametrized over all thirteen tools, with the registry asserted equal so a fourteenth tool cannot be skipped"
  - "test_a_raising_tool_would_leak_without_the_guard — the leak channel documented by a test that asserts it exists"
  - "test_mcp_tool_response_contains_no_configured_secret — every tool's full result scanned for every configured secret"
affects: [06-10 response-budget tests, any future tool addition, phase 6 validation]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "A module-level `async def` seeding helper rather than a fixture, so a test that must run against an EMPTY database cannot acquire history through fixture ordering"
    - "One dead-database sessionmaker swap, thirteen tool calls, failures COLLECTED into a list so one leaking tool cannot hide another"
    - "An exported argument table (MINIMAL_TOOL_ARGUMENTS) asserted equal to the live registry, making 'all thirteen' structural instead of a hand-maintained list"
    - "A test that asserts a vulnerability EXISTS, on a throwaway server, so a guard's justification is verified rather than remembered"

key-files:
  created: []
  modified:
    - backend/tests/test_mcp_tools.py
    - backend/tests/test_secret_redaction.py

key-decisions:
  - "fitness_ping is exempted from the `data_available is False` degrade assertion and asserted against its own `database=error` contract instead — D-08's canary predates the field and has no `data_available` in its schema"
  - "MINIMAL_TOOL_ARGUMENTS is exported from test_mcp_tools.py and imported by test_secret_redaction.py rather than duplicated; two copies of 'the minimal call for every tool' is one copy that silently stops covering a tool"
  - "The comparison tool's leak-test dates are VALID and forward-ordered on purpose: the range guard runs before a session is opened, so an invalid pair would degrade without ever touching the dead database"
  - "The reference history is anchored on utc_now(), never a fixed date — a fixed anchor ages out of every weeks=N window and every assertion then measures an empty response and passes for the wrong reason"
  - "The secret-redaction case asserts is_error is False per tool before scanning, so the scan cannot pass on thirteen degraded placeholders"

patterns-established:
  - "Behavioural MCP tests take `committed_history` and never `golden_workout` — a tool opens its own session and cannot see flushed-but-uncommitted rows"
  - "Warm-up exclusion is asserted against BOTH the working-set total and the total-including-warm-ups, so the passing number means 'warm-ups were excluded' rather than 'a number came back'"

requirements-completed: [MCP-02, MCP-06]

# Metrics
duration: 34min
completed: 2026-08-31
---

# Phase 6 Plan 11: Behavioural and Leak Coverage for the MCP Tool Surface Summary

**`test_mcp_tools.py` grew from four ping tests to twenty-two, covering every one of the thirteen registered tools against committed seeded data, proving both D-02 name-resolution failure modes on both name-taking tools, proving `fitness_get_training_summary` answers in one call, and proving all thirteen tools degrade against a dead database with no DSN fragment, no traceback and no driver name — plus one case in the redaction suite that scans every tool's full result for every `Settings.secret_values()` string.**

## What Was Built

### `backend/tests/test_mcp_tools.py` — 4 tests → 22

**`_seed_reference_history(builder, session)`** is the shared history every behavioural test commits. Deliberately a module-level `async def` and *not* a pytest fixture: a test that needs history says so by calling it, and the leak suite — which must run against an empty database — cannot acquire it by accident through fixture ordering.

| Seeded | Shape |
|---|---|
| Templates | `MCP-BENCH` (`weight_reps`, "Bench Press (Barbell)", chest direct + triceps indirect), `MCP-SQUAT` (`weight_reps`, quads direct), `MCP-PULL` (`reps_only`, lats direct), and **`MCP-LAT1` + `MCP-LAT2` sharing the title "Lateral Raise"** |
| Workouts | 6, at day offsets `(17, 14, 10, 7, 4, 1)` back from an anchor computed from `utc_now()`; each carries a bench warm-up + 2 working sets at climbing weight, 2 squat sets, 2 pull-up sets |
| Body | 30 daily weigh-ins ending on the anchor day, in `Decimal` |
| Freshness | `sync_state` rows for all three resources, written through `complete_sync` |

The two same-titled `Lateral Raise` templates are the D-02 multi-match case and are real on live data: `exercise_templates.title` carries no uniqueness constraint, and Hevy ships both built-in templates (8-char hex ids) and user-custom ones (full UUIDs) that can spell an exercise identically.

Counts are named constants (`REFERENCE_HARD_SETS = 36`, `REFERENCE_SETS_INCLUDING_WARMUPS = 42`) rather than literals in assertions, so a test asserts against the same number the fixture wrote.

The sixteen behavioural tests:

| Test | Proves |
|---|---|
| `test_recent_workouts_returns_summaries_with_ids` | D-09. `limit=3` returns 3, newest first, every row carrying a non-empty `workout_id` |
| `test_get_workout_fetches_the_id_the_list_echoed` | D-12. The list → detail navigation path, end to end |
| `test_get_workout_reports_not_found_without_erroring` | `found=False` with `data_available=True` — an answer, not an outage |
| `test_weekly_volume_excludes_warmups` | VOL-01. `hard_sets` sums to 36, and is asserted **not** to be 42 |
| `test_muscle_group_volume_returns_all_nineteen_groups` | VOL-02. 19 rows; calves is a zero row with `insufficient_data=True`; chest is non-zero |
| `test_training_frequency_reports_per_muscle_and_per_exercise` | VOL-03. `sessions_per_week` plus both non-empty lists |
| `test_exercise_name_is_case_insensitive` | D-01. `"bench press (barbell)"` resolves and returns points |
| `test_unknown_exercise_name_returns_no_candidates` | D-02 zero-match: `is_error=False`, `matched=False`, `candidates == []` |
| `test_ambiguous_exercise_name_returns_every_candidate` | D-02 multi-match / T-06-12: both `MCP-LAT1` and `MCP-LAT2` returned, `progression=None` |
| `test_personal_records_resolves_by_name_too` | The same D-02 contract on the second name-taking tool, both halves |
| `test_plateaus_reports_its_window_and_threshold` | PROG-03. Window echoed, and every row carries `threshold_percent`/`min_sessions`/`min_elapsed_days` |
| `test_compare_periods_normalizes_per_week` | CMP-01. `period_a`/`period_b` present; every `totals` row carries both per-week keys |
| `test_compare_periods_rejects_a_reversed_period_without_erroring` | T-06-05. A refused range is a payload, never an exception |
| `test_body_weight_trend_returns_rolling_averages` | BODY-01. `anchor_day` present, at least one rolling average non-null |
| `test_recomposition_status_carries_its_disclaimer` | T-06-09. A non-empty **string**, not merely a present key |
| `test_training_summary_composes_four_analytics` | MCP-02's "one call" / T-06-20. All six elements in one response |

Every assertion runs against `result.structured_content` rather than `result.content[0].text` — returning a `BaseModel` is what populates it, so asserting on it also exercises the output-schema path.

`test_ping_output_schema_requires_both_fields` was re-indexed from `tools[0]` to `{tool.name: tool for tool in tools}["fitness_ping"]`. It passed before only because `fitness_ping` happens to be registered first; with thirteen tools that is an accident, not an assertion.

### The leak suite

`test_ping_degradation_leaks_nothing` is replaced by **`test_every_tool_degradation_leaks_nothing`**. One `app.state.sessionmaker` swap to a real connection against closed port 1, one `Client(mcp)` context, thirteen calls. Per tool it checks four things, and **collects** failures rather than asserting inline so one leaking tool cannot hide another:

- none of `nobody`, `nopass`, `127.0.0.1`, `nodb`, `asyncpg`, `Traceback`, `psycopg`, `ConnectionRefused`, `sqlalchemy` appears in `f"{structured_content}{content}"`
- `is_error is False` — `@safe_tool` degrades, it does not error
- `structured_content is not None`
- `structured_content["data_available"] is False` (see Deviation 1 for `fitness_ping`)

The registry is asserted **equal** to `MINIMAL_TOOL_ARGUMENTS`, so a fourteenth tool registered without an entry fails here instead of being silently skipped.

**`test_a_raising_tool_would_leak_without_the_guard`** documents the channel instead of assuming it. A throwaway tool on a *separate* `MCPServer` raises `ValueError("postgresql://user:SECRET@host:5432/db unreachable")`, and the test asserts `"SECRET@host"` **is** present in the result. It asserts the leak exists on purpose. If it ever starts failing, the SDK has changed its error handling and `@safe_tool`'s justification must be re-verified rather than assumed away. It is the one test in this module that needs no container.

### `backend/tests/test_secret_redaction.py`

**`test_mcp_tool_response_contains_no_configured_secret`** drives all thirteen tools through `Client(mcp)` against the healthy container, asserts each returned `is_error=False`, concatenates every `structured_content` and `content` into one string, and asserts no value from `Settings.secret_values()` appears in it.

Deliberately run against a *healthy* database: the exception channel already has its own coverage in `test_mcp_tools.py`. What this closes is the other direction — a secret arriving through an ordinary, successful path, which raises nothing for `@safe_tool` to catch and which the structlog chain cannot see because a tool result is not a log record.

## Findings

**All thirteen tools degrade cleanly.** With the sessionmaker pointed at closed port 1, every tool returns `is_error=False` and a schema-valid payload; twelve carry `data_available=False` and `fitness_ping` carries `database="error"`. No DSN component, driver name or traceback appears in any of the twenty-six rendered channels.

**The leak channel is still open in `mcp 2.0.0`.** `test_a_raising_tool_would_leak_without_the_guard` passes, which means an unguarded tool's exception message still reaches the model verbatim. `@safe_tool` remains load-bearing, and this is now a measured fact with a test behind it rather than a claim in a docstring.

**D-02 holds on both name-taking tools.** `"Lateral Raise"` matching two templates returns `matched=False` with both external ids and no analytics, on `fitness_get_exercise_progression` **and** `fitness_get_personal_records`. Neither auto-picks.

**Suite cost.** Full suite 620 → **638 passed in 16.13 s**. Fast suite 373 → **374 passed in 1.04 s** — seventeen of the eighteen new tests are integration-marked, and the one that is not (`test_a_raising_tool_would_leak_without_the_guard`) needs no container.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Bug] `fitness_ping` cannot satisfy the plan's uniform `data_available is False` assertion**
- **Found during:** Task 2
- **Issue:** The plan specifies that the leak test assert `structured_content["data_available"] is False` for each of the thirteen tools. `fitness_ping`'s response model has no `data_available` field at all — D-08's canary predates it and reports connectivity as a value, so its degrade contract is `{"status": "ok", "database": "error"}`. Applied literally, the loop would raise `KeyError` on the first tool and the test would fail for a reason unrelated to any leak.
- **Fix:** `fitness_ping` stays in the leak scan (all nine markers, `is_error`, non-null structured content) and is asserted against its own documented contract; the other twelve get the `data_available is False` assertion. The branch carries a comment naming why. The plan's acceptance criterion `grep '"data_available"] is False'` still matches.
- **Files modified:** `backend/tests/test_mcp_tools.py`
- **Commit:** `00eff6e`

**2. [Rule 2 — Missing critical functionality] `MINIMAL_TOOL_ARGUMENTS` asserted equal to the live registry**
- **Found during:** Task 2
- **Issue:** The plan describes building "the minimal valid arguments for each of the thirteen tools" as a literal table. A hand-maintained table silently stops covering any tool added or renamed later — precisely the failure `test_mcp_tool_schemas.py`'s exact-registry assertion exists to prevent one layer up. Without the check, the phase's central security claim quietly narrows from "all thirteen" to "the thirteen someone remembered".
- **Fix:** Both the leak test and the secret-redaction test assert `{tool.name for tool in list_tools()} == set(MINIMAL_TOOL_ARGUMENTS)`, with a symmetric-difference message.
- **Files modified:** `backend/tests/test_mcp_tools.py`, `backend/tests/test_secret_redaction.py`
- **Commit:** `00eff6e`

**3. [Rule 2 — Missing critical functionality] `is_error is False` asserted in the secret scan**
- **Found during:** Task 2
- **Issue:** The plan's secret-redaction case only scans the concatenated results. If every tool errored against the healthy container the scan would still pass — degraded placeholders are the responses *least* likely to carry a secret. Green while proving nothing, which is the exact failure mode that module's own docstring warns about.
- **Fix:** Each of the thirteen results is asserted `is_error is False` before its text joins the scan.
- **Files modified:** `backend/tests/test_secret_redaction.py`
- **Commit:** `00eff6e`

**4. [Rule 3 — Blocking] `MINIMAL_TOOL_ARGUMENTS` exported rather than duplicated**
- **Found during:** Task 2
- **Issue:** Both suites need the same thirteen minimal calls. Two copies is one copy that stops covering a tool the day a signature changes, and the divergence would be invisible — both suites would still be green.
- **Fix:** Defined once in `test_mcp_tools.py` and imported inside the redaction test's function body (matching that module's lazy-import discipline around `app.main`). Documented at the definition.
- **Files modified:** `backend/tests/test_mcp_tools.py`, `backend/tests/test_secret_redaction.py`
- **Commit:** `00eff6e`

### Notes on Fixture Choice

The plan's task 1 says each test takes `client` and `committed_history`. Each also takes `session` — `committed_history` yields a `GoldenBuilder` but the caller owns the commit (that is the fixture's stated contract, so `GoldenBuilder`'s flush-only behaviour stays intact for every Phase 4/5 test that shares it), and the commit needs the session. Not a deviation; the fixture's docstring already requires it.

The comparison tool's leak-test dates are valid and forward-ordered rather than arbitrary. `fitness_compare_periods` validates its range *before* opening a session, so an invalid pair would return `data_available=False` without ever reaching the dead database — the test would then be asserting that a tool which never ran leaked nothing.

## Verification

| Check | Result |
|---|---|
| `uv run pytest backend/tests/test_mcp_tools.py backend/tests/test_secret_redaction.py -q` | **36 passed** in 4.49 s |
| `uv run pytest backend/tests -q` (full, incl. integration) | **638 passed** in 16.13 s |
| `uv run pytest backend/tests -x -q -m "not integration"` | **374 passed** in 1.04 s |
| `uv run pytest backend/tests/test_mcp_tools.py -k leak -q` | 2 passed, 19 deselected |
| `uv run pytest backend/tests/test_secret_redaction.py -k mcp_tool -q` | 1 passed, 14 deselected |
| `uv run ruff check backend/tests` | All checks passed |
| `uv run ruff format --check` on both files | Already formatted |
| `grep -c 'tools\[0\]' backend/tests/test_mcp_tools.py` | `0` |
| `grep -c 'from app.mcp.server import mcp' backend/tests/test_mcp_tools.py` | `21` (≥ 16 required) |
| `grep -c 'DEAD_DB_URL' backend/tests/test_mcp_tools.py` | `4` (≥ 2 required) |
| `git diff --stat pyproject.toml uv.lock` | no change |

## Success Criteria

- [x] Every one of the thirteen tools has at least one integration test asserting real structured content against committed seeded data
- [x] Both D-02 failure modes return `is_error=False`, `matched=False` and the candidate list, on both name-taking tools
- [x] `fitness_get_training_summary` proven to carry volume, 19 muscle rows, a progression verdict, a recomposition status and a non-empty disclaimer in one call
- [x] Against a dead database, all thirteen tools return `is_error=False` and a degraded payload with no DSN fragment, traceback or driver name (`fitness_ping` via `database="error"`, the other twelve via `data_available=False`)
- [x] No configured secret value appears in any tool response
- [x] `tools[0]` positional indexing is gone from the file

## Known Stubs

None. This plan added tests only — no source file under `backend/app/` was touched, and no test asserts against a placeholder value.

## Threat Flags

None. No network endpoint, auth path, file access pattern or schema change was introduced. The one new file-level construct is a throwaway `MCPServer` built inside a single test function and never mounted, never served and never given a lifespan.

## Commits

| Commit | Message |
|---|---|
| `2752d7c` | `test(06-11): cover every MCP tool against seeded history` |
| `00eff6e` | `test(06-11): prove no tool leaks a DSN or a configured secret` |

## For the Next Plan

- **Adding a fourteenth tool now requires four edits**, all of which fail loudly if forgotten: `server.py`'s `_TOOLS`, `EXPECTED_TOOLS` in `test_mcp_tool_schemas.py`, the `== 12` count in `test_mcp_isolation.py`, and `MINIMAL_TOOL_ARGUMENTS` in `test_mcp_tools.py`.
- **`_seed_reference_history` is reusable** by any later plan needing committed training history with a known hard-set count, a climbing progression series and a deliberate name collision. It returns the anchor `datetime`, so date-taking tools can be driven relative to it.
- **`test_a_raising_tool_would_leak_without_the_guard` is a tripwire on the SDK, not on this repo.** A failure there is an upgrade signal: re-verify `@safe_tool`'s justification against the new `mcp` behaviour before concluding anything.

## Self-Check: PASSED

Both modified files and the SUMMARY exist on disk; both commit hashes (`2752d7c`, `00eff6e`) resolve in `git log`.
