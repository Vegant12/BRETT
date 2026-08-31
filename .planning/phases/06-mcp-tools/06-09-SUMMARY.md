---
phase: 06-mcp-tools
plan: 09
subsystem: api
tags: [mcp, tool-registration, annotations, schemas, isolation, security, static-analysis]

# Dependency graph
requires:
  - phase: 06-mcp-tools (plan 06-01)
    provides: _common.py — safe_tool (functools.wraps), read_only_session, resolve_user_id, the cap constants
  - phase: 06-mcp-tools (plan 06-04)
    provides: workouts.py — fitness_get_recent_workouts, fitness_get_workout
  - phase: 06-mcp-tools (plan 06-05)
    provides: volume.py — fitness_get_weekly_volume, fitness_get_muscle_group_volume, fitness_get_training_frequency
  - phase: 06-mcp-tools (plan 06-06)
    provides: progression.py + records.py — fitness_get_exercise_progression, fitness_get_plateaus, fitness_get_personal_records
  - phase: 06-mcp-tools (plan 06-07)
    provides: comparison.py + body.py — fitness_compare_periods, fitness_get_body_weight_trend, fitness_get_recomposition_status
  - phase: 06-mcp-tools (plan 06-08)
    provides: summary.py — fitness_get_training_summary
  - phase: 02-deploy-connector-auth-spike
    provides: the MCPServer instance, AuthSettings, TransportSecuritySettings and fitness_ping
provides:
  - "All thirteen tools registered on the live MCPServer, each carrying one shared READ_ONLY ToolAnnotations object"
  - "test_mcp_tool_schemas.py — container-free proof of the registry, annotations, published schemas and window caps"
  - "test_mcp_isolation.py — static source guards over app/mcp/ for writes, raw SQL, exception interpolation, floats, @safe_tool coverage and provider imports"
  - "RESEARCH assumption A1 discharged: @safe_tool erases no input or output schema"
affects: [06-10 response-budget and read-only tests, 06-11 behavioural tests, any future tool addition]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "One shared ToolAnnotations object applied in a registration LOOP, so 'every tool is read-only' is structurally true rather than N chances to omit a kwarg"
    - "Static boundary guards run over a CODE-ONLY projection of the source (tokenize-based comment/string blanking, offsets preserved) so a module may document the pattern it bans"
    - "Container-free MCP schema tests via a fixture that wires app.state.sessionmaker over an engine that is never dialled"

key-files:
  created:
    - backend/tests/test_mcp_tool_schemas.py
    - backend/tests/test_mcp_isolation.py
  modified:
    - backend/app/mcp/server.py
    - backend/tests/test_mcp_mount.py
    - backend/tests/test_mcp_auth.py

key-decisions:
  - "READ_ONLY is one module-level ToolAnnotations reused by all thirteen registrations; destructive_hint and open_world_hint are set EXPLICITLY because the spec defaults are true"
  - "Registration is a loop over a _TOOLS tuple keyed on _fn.__name__, not thirteen literal add_tool calls"
  - "required_scopes=None is now a recorded decision (T-06-16), not a leftover: every tool is read-only, so there is nothing to gate, and adding a scope would force re-consent on the working Phase 2 connector"
  - "_TOOLS is typed Callable[..., Any], not the plan's object — mypy rejects object.__name__ and add_tool(object)"
  - "test_mcp_tool_schemas.py uses a container-free fixture rather than the plan's `client`; only the one test that CALLS a tool is marked integration"
  - "The isolation guards match against a code-only projection rather than raw text, because _common.safe_tool's docstring quotes the exact leak expressions it exists to prevent"

patterns-established:
  - "Exact-registry assertions live in one place (test_mcp_tool_schemas); auth and mount tests assert membership only, so a new tool touches one test not four"
  - "A hardcoded expected tool COUNT beside the per-tool decorator check, so a new tool cannot ship unguarded and unnoticed"

requirements-completed: [MCP-02, MCP-03, MCP-05, MCP-06]

# Metrics
duration: 38min
completed: 2026-08-31
---

# Phase 6 Plan 09: Tool Registration and Surface Guards Summary

**All twelve Phase 6 tools registered beside `fitness_ping` through a single loop applying one shared `READ_ONLY` annotation object, plus sixteen new tests that pin the published surface — thirteen names, non-null output schemas, absent `user_id`, all eight window caps — and statically forbid `app/mcp/` from writing, building raw SQL, interpolating an exception, or shipping a tool without `@safe_tool`.**

## What Was Built

### `backend/app/mcp/server.py` — the registration

`READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)` is defined once and passed to every `add_tool` call. The two negative flags are set explicitly rather than omitted: the MCP spec defaults for `destructiveHint` and `openWorldHint` are **`true`**, so a tool registered without annotations advertises the exact opposite of what this project guarantees.

The twelve new tools go through a loop over a `_TOOLS: tuple[tuple[Callable[..., Any], str], ...]` of `(callable, description)` pairs, registered as `mcp.add_tool(_fn, name=_fn.__name__, description=_description, annotations=READ_ONLY)`. A loop rather than twelve literal calls so "every tool is annotated read-only" is *structurally* true. `fitness_ping` keeps its own explicit registration — it is the Phase 2 canary and reads differently from the Phase 6 block — and gained `annotations=READ_ONLY` so the claim holds across all thirteen.

`mcp.streamable_http_app(...)` is still the last statement in the module, verified by importing it: `type(mcp_app).__name__` is `Starlette`.

The stale `# Scope design belongs with the real tool set in Phase 6` comment is gone. `required_scopes=None` stays, and the replacement comment records *why* (T-06-16): every tool is read-only, so there is no privileged operation to gate; a scope the server never varies its behaviour on is a claim rather than a control, and adding one would force the working Phase 2 connector to re-consent for no security gain.

### `backend/tests/test_mcp_tool_schemas.py` (356 lines, 9 tests)

Nine assertions about what Claude actually receives:

| Test | Guards |
|---|---|
| `test_tool_registry_is_exactly_the_thirteen` | MCP-02. Exact set, with a symmetric-difference message so a rename reads as a rename |
| `test_every_tool_is_annotated_read_only` | MCP-05 / T-06-03. `readOnlyHint` true, `destructiveHint` and `openWorldHint` false, on all thirteen |
| `test_decorated_tools_still_publish_schemas` | **RESEARCH assumption A1.** Non-empty `outputSchema`, and no `args`/`kwargs`/`ctx` in `inputSchema` |
| `test_no_tool_publishes_a_user_id_argument` | ASVS V4 / T-06-02 |
| `test_no_tool_publishes_an_exercise_template_id_argument` | D-01 |
| `test_window_caps_are_published` | D-04/D-08/D-10. All eight `(tool, param) -> maximum` pairs, plus `minimum: 1` |
| `test_a_request_above_the_cap_is_rejected_before_the_body_runs` | T-06-05, the one integration test here |
| `test_every_tool_has_a_description` | A description under 20 characters is a tool Claude will not choose correctly |
| `test_ping_is_still_registered_first_class` | D-08, both output fields required |

### `backend/tests/test_mcp_isolation.py` (271 lines, 7 tests)

Container-free, deliberately **not** marked `integration` — a boundary violation must fail the fast suite on the commit that introduces it. Carries `_SESSION_WRITE`, `_WRITE_IMPORT`, `_RAW_SQL_TEXT`, `_FLOAT_USE` and `_INTEGRATIONS_IMPORT` across from `test_analytics_isolation.py` verbatim, and adds `_EXC_IN_RETURN` (MCP-06) and `_PUBLIC_TOOL`.

`test_every_tool_module_guards_its_public_tools` walks every `^async def fitness_\w+(` under `app/mcp/tools/` (excluding `ping.py`, `_common.py`, `schemas.py`), asserts the preceding non-blank line starts with `@safe_tool(`, and asserts the walk found **exactly 12** of them.

`ping.py` is the single, commented exemption from the raw-SQL guard — its `text("SELECT 1")` is a literal with no bound values and it is the connectivity canary.

## Findings

**RESEARCH assumption A1 is CONFIRMED — `@safe_tool` erases nothing.** This was the highest-risk claim in the phase and the reason plan 06-09 exists. Measured across all thirteen registered tools: every one publishes a non-empty `outputSchema`, and every one publishes its real named arguments —

```
fitness_get_recent_workouts        ['limit']
fitness_get_workout                ['workout_id']
fitness_get_exercise_progression   ['exercise_name', 'weeks']
fitness_get_plateaus               ['lookback_weeks', 'plateaued_only']
fitness_compare_periods            ['period_a_start', 'period_a_end', 'period_b_start',
                                    'period_b_end', 'include_muscle_groups']
```

No `args`, no `kwargs`, no `ctx` anywhere. `functools.wraps` in `_common.safe_tool` is doing its job, and the contingency plan (drop the decorator, inline `try`/`except` twelve times) is not needed.

**All eight window caps reach the published schema**, e.g. `fitness_get_weekly_volume.weeks` → `{"minimum": 1, "maximum": 52, "default": 12, ...}` and `fitness_get_training_summary.weeks` → `{"minimum": 1, "maximum": 12, "default": 4, ...}`. `weeks=999` is rejected with `is_error=True` and `structured_content is None`, before the tool body runs.

**The fast suite stayed fast.** 358 tests in 0.97 s before this plan; **373 in 1.02 s** after, with 15 of the 16 new tests in it and still no container.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking] `_TOOLS` typed `Callable[..., Any]`, not the plan's `object`**
- **Found during:** Task 1
- **Issue:** The plan specified `_TOOLS: tuple[tuple[object, str], ...]`. mypy rejects it twice — `"object" has no attribute "__name__"` and `Argument 1 to "add_tool" has incompatible type "object"`.
- **Fix:** `Callable[..., Any]`, which is `add_tool`'s own parameter type. Verified mypy resolves `__name__` on it.
- **Files modified:** `backend/app/mcp/server.py`
- **Commit:** `1b0f36e`

**2. [Rule 1 — Bug] `test_mcp_mount.py::test_exactly_one_tool_registered` invalidated**
- **Found during:** Task 1
- **Issue:** Asserted `[tool.name for tool in tools] == ["fitness_ping"]`. Task 1's own acceptance criteria require this file to pass. `test_ping_tool_hides_ctx_from_the_model` in the same file also indexed `tools[0]`.
- **Fix:** Renamed to `test_ping_is_registered` and reduced to a membership check; the exact-registry claim *moved* to `test_mcp_tool_schemas.py` rather than disappearing. The `ctx` test now looks the ping tool up by name.
- **Files modified:** `backend/tests/test_mcp_mount.py`
- **Commit:** `1b0f36e`

**3. [Rule 1 — Bug] `test_mcp_auth.py::test_accepts_valid_bearer` invalidated**
- **Found during:** final verification
- **Issue:** Same failure mode — asserted the `tools/list` response equalled `["fitness_ping"]`. Integration-marked, so it survived the fast suite and only surfaced on the full run. No plan in this phase owns this file.
- **Fix:** Membership check. The test is about auth reaching the tool surface, not about which tools exist.
- **Files modified:** `backend/tests/test_mcp_auth.py`
- **Commit:** `9109279`

**4. [Rule 3 — Blocking] Isolation guards run over a code-only projection, not raw source**
- **Found during:** Task 3
- **Issue:** The plan supplied `_EXC_IN_RETURN = re.compile(r"str\(exc\)|str\(e\)|repr\(e\)|repr\(exc\)|\{(?:exc|e|err|error)[!:}]")` while its own header instruction demanded "every check is an ANCHORED REGEX ... because `_common.safe_tool`'s docstring quotes the SDK's `str(e)` behaviour verbatim". Both are true and they contradict each other: `str(e)` has no line position to anchor on, and `_common.py:264-265` really does contain `TextContent(text=str(e))` and `ToolError(f"Error executing tool {name}: {e}")` inside a docstring. Applied to raw source the guard fails on the sentence documenting the rule.
- **Fix:** `_code_only(source)` uses `tokenize` to blank every `COMMENT`, `STRING` and `FSTRING_MIDDLE` token, replacing each non-whitespace character with a space so line and column offsets survive and the anchored multiline regexes still mean what they say. Since Python 3.12 an f-string's *interpolation* tokenizes as ordinary `{` / NAME / `}`, so `return f"failed: {e}"` is still caught while the docstring quoting it is not. All guards run over the projection uniformly. Verified against three synthetic cases: documenting prose clean, `f"failed: {e}"` caught, `str(exc)` caught.
- **Files modified:** `backend/tests/test_mcp_isolation.py`
- **Commit:** `7dbdcbc`

**5. [Rule 3 — Blocking] `test_mcp_tool_schemas.py` uses a container-free fixture, not `client`**
- **Found during:** Task 2
- **Issue:** The plan's task 2 opens "Container-free where possible" and then requires "every test takes the `client` fixture". `client` depends on the session-scoped `postgres_url` testcontainer. Eight non-integration tests taking it would have pulled a Postgres container into a fast suite that currently runs 358 tests in 0.97 s with no container at all — directly against the plan's own verification line, "full fast suite green".
- **Fix:** A local `_mcp_state` fixture modelled on `test_mcp_mount.py`'s `mcp_server` fixture: it wires `app.state.sessionmaker` over an engine that is never dialled, which is all `mcp_lifespan` needs, because `tools/list` issues no query. The one test that actually *calls* a tool keeps `@pytest.mark.integration` and the `client` fixture, exactly as the plan specified. The plan's other constraints are preserved: `from app.mcp.server import mcp` appears 10 times (in-function, one per test plus the fixture's sibling import), and `grep -c '^from app.mcp'` is 0.
- **Files modified:** `backend/tests/test_mcp_tool_schemas.py`
- **Commit:** `ce60f18`

### Not Deviations

`backend/tests/test_mcp_tools.py`'s `tools[0]` indexing is **untouched** and still passing — `fitness_ping` remains first in registration order. Plan 06-11 explicitly owns re-indexing it by name (`grep -c 'tools\[0\]' ... returns 0` is one of its acceptance criteria), so fixing it here would have collided with that plan.

## Verification

| Check | Result |
|---|---|
| `uv run pytest backend/tests -x -q -m "not integration"` | **373 passed** in 1.02 s |
| `uv run pytest backend/tests -q` (full, incl. integration) | **620 passed** in 16.42 s |
| `uv run pytest backend/tests/test_mcp_tool_schemas.py -q` | 9 passed |
| `uv run pytest backend/tests/test_mcp_isolation.py backend/tests/test_analytics_isolation.py -q` | 15 passed |
| `uv run ruff check backend/app backend/tests` | All checks passed |
| `uv run mypy backend/app/mcp` | Success, 15 source files |
| `python -c "from app.mcp.server import mcp_app; print(type(mcp_app).__name__)"` | `Starlette` |
| `len(mcp._tool_manager.list_tools())` | `13`, every one carrying `READ_ONLY` |
| `git diff --stat pyproject.toml uv.lock` | no change |

## Success Criteria

- [x] Thirteen tools registered on `mcp`, every one carrying `READ_ONLY`
- [x] `streamable_http_app()` is still the last statement in `server.py`
- [x] Every tool publishes a non-null `outputSchema` and named arguments — `@safe_tool` erases nothing
- [x] No tool publishes `user_id` or `exercise_template_external_id`
- [x] All eight window/limit caps appear as `maximum`, and `weeks=999` is rejected with `is_error=True` before any tool body runs
- [x] Static guards over `app/mcp/` pass for writes, raw SQL, exception interpolation, floats, `@safe_tool` coverage (exactly 12) and provider imports

## Known Stubs

None. Every tool registered here is fully wired to its analytics or repository function; there are no hardcoded empty values, placeholder text, or unwired data sources in this plan's changes.

## Threat Flags

None. This plan added no network endpoint, auth path, file access or schema change. It made an existing surface — the MCP tool registry — *narrower*, by publishing bounds and read-only hints and by adding static guards over the package.

## Commits

| Commit | Message |
|---|---|
| `1b0f36e` | `feat(06-09): register the twelve Phase 6 tools with a shared READ_ONLY annotation` |
| `ce60f18` | `test(06-09): assert the published tool surface -- registry, annotations, schemas, caps` |
| `7dbdcbc` | `test(06-09): static guards over the app/mcp/ boundary` |
| `9109279` | `fix(06-09): stop test_accepts_valid_bearer pinning the whole tool registry` |

## For the Next Plan

- **06-10** can rely on all thirteen tools being discoverable through `Client(mcp)` and on `EXPECTED_TOOLS` in `test_mcp_tool_schemas.py` as the single source of truth for the registry.
- **06-11** still owns re-indexing `test_mcp_tools.py` off `tools[0]`; that test passes today only because `fitness_ping` is registered first.
- **Adding a fourteenth tool now requires three edits**, by design: register it in `server.py`'s `_TOOLS`, add its name to `EXPECTED_TOOLS`, and raise the `== 12` count in `test_mcp_isolation.py`. Two of the three fail loudly if forgotten.

## Self-Check: PASSED

All five source files and the SUMMARY exist on disk; all four commit hashes resolve in `git log`.
