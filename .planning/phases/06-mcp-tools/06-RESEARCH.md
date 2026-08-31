# Phase 6: MCP Tools - Research

**Researched:** 2026-08-31
**Domain:** MCP tool surface design on `mcp==2.0.0` (`MCPServer`), composing shipped Phase 4/5 analytics into bounded, read-only, structured tool responses
**Confidence:** HIGH — every SDK behaviour claim below was verified by executing code against the installed `mcp 2.0.0` in this repo's `.venv`, and every byte figure was produced by serializing real `app.analytics.schemas` models

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Exercise Identification (affects `fitness_get_exercise_progression`, `fitness_get_personal_records`)**
- **D-01:** Both tools accept an exercise **name** (string), not the underlying
  `exercise_template_external_id`. The MCP layer resolves name → `external_id` via a
  case-insensitive exact match against `exercise_templates.title` before calling the analytics
  function. Claude must never need to know an opaque Hevy template ID exists.
- **D-02:** If the name matches **zero or more than one** template, the tool computes no
  analytics and returns a structured response listing every candidate match (name +
  `external_id`) so Claude can retry with a disambiguated call, or report "no such exercise" to
  the user. No silent auto-pick, ever — a wrong-exercise answer with no signal is worse than an
  extra round trip.
- Matching scope beyond "case-insensitive exact match on `title`" (e.g. whitespace/punctuation
  tolerance, partial/substring matching) is Claude's discretion at plan time — not discussed
  further because the two failure modes (zero match, multi match) are already fully specified by
  D-02 regardless of how permissive the match itself is.

**Time-Window Parameters**
- **D-03:** These tools take `weeks: int` (relative, ending today), not explicit dates. The MCP
  layer converts `weeks` → `start_day`/`end_day` before calling the analytics function
  underneath (all of which currently require explicit `start_day`/`end_day`). This is new
  conversion logic — it does not exist in the analytics layer today and must be built as part of
  this phase's tool code, not assumed to already exist.
- **D-04:** `weeks` is capped at a **maximum of 52**. A request above the cap is a validation
  error, not a silently truncated window — this is what makes MCP-03's "enforced size cap"
  concrete for every one of these tools: a weekly-volume series, for example, can never exceed
  52 rows.
- **D-05:** `fitness_get_plateaus` keeps its existing `lookback_weeks` parameter as-is (already
  relative-window, already built in `analytics/progression.py`) — the 52-week cap applies to it
  too for consistency, but no new conversion logic is needed for this one tool.
- **D-06:** `fitness_compare_periods` is the one exception to D-03: it keeps **explicit dates**
  for both periods (`period_a_start`/`period_a_end`/`period_b_start`/`period_b_end`, matching the
  analytics signature and the blueprint's own example verbatim). "Compare August to July" cannot
  be expressed as two `weeks=N` values relative to today.
- **D-07:** `fitness_get_body_weight_trend` and `fitness_get_recomposition_status` take **no**
  window parameter at all — their underlying analytics functions (`get_body_weight_trend`,
  `get_recomposition_status`) are already anchored on "today" with no date-range argument, and
  that is correct: neither question is meaningful for an arbitrary historical window.

**Training Summary Composition**
- **D-08:** `fitness_get_training_summary` composes, over one default window (Claude's discretion
  on the exact default — e.g. 4 weeks — at plan time):
  - Weekly training volume (from `get_weekly_volume`)
  - Per-muscle-group volume and frequency (from `get_muscle_group_volume` /
    `get_training_frequency`)
  - Current recomposition status verdict (from `get_recomposition_status`)
  This directly answers PROJECT.md's Core Value questions — "Am I progressing?", "which muscles
  are undertrained?" — in one call. It deliberately does **not** include personal records or
  plateaus: those stay on their own dedicated tools rather than duplicating data and bloating the
  one tool every conversation is likely to open with.

**Recent Workouts & Single-Workout Detail**
- **D-09:** `fitness_get_recent_workouts` returns **workout-level summaries only** — per workout:
  date, title, duration, exercise count, total hard sets, tonnage (where computable per Phase 4's
  operand-presence gate). No per-exercise or per-set breakdown in the list. This is what keeps the
  list compact regardless of how many workouts are requested.
- **D-10:** The limit is **count-based**: `limit: int` (Claude's discretion on default, e.g. 10;
  capped at e.g. 50 at plan time — the exact cap number is Claude's discretion, D-04's 52-week
  reasoning does not apply here since this isn't a weeks parameter). Count-based was chosen over
  days-based specifically because it bounds response size by construction — a days-based window
  would let a high-frequency training period return an unpredictably large list.
- **D-11 (decision, diverges from the recommended default — deliberate user choice):** A
  **12th tool**, `fitness_get_workout`, is **in scope** for this phase — full exercise/set
  breakdown for exactly one workout. This is blueprint §29's `fitness_get_workout`, which
  ROADMAP.md's Phase 6 success criterion #1 text does not name among its 11. **This is not scope
  creep** — CLAUDE.md states the blueprint is the authoritative source for "MCP tool names" and
  blueprint §29 explicitly lists `fitness_get_workout` alongside `fitness_get_recent_workouts`.
  Do not treat its absence from the ROADMAP success-criteria sentence as a reason to drop it or
  re-litigate it at planning time.
- **D-12:** `fitness_get_workout` is keyed by the **Hevy external workout id** — the same id
  `fitness_get_recent_workouts` echoes per item — not a calendar date.

**Response Size Budget (MCP-03)**
- **D-13:** Enforcement is **per-tool item caps plus a tested byte budget** — not a design
  intention left unverified. Every list-returning tool has a fixed max item count (D-04's
  52-week cap, D-10's workout limit, the already-bounded 19-group muscle taxonomy). In addition,
  a test serializes each tool's response against realistic/worst-case fixture data and asserts it
  stays under an explicit byte budget. The exact byte number (e.g. 8KB) is Claude's discretion at
  research/plan time — informed by what "compact" actually produces against real fixture data,
  not picked in the abstract during this discussion.
- **D-14:** The MCP SDK's existing `max_request_body_size` (4MB, already configured in
  `server.py`) is a separate, unrelated ceiling — a request-size limit, not a response-compactness
  guarantee — and does not substitute for D-13.

### Claude's Discretion
- Exact name-matching permissiveness beyond case-insensitive exact match (D-02 covers the failure
  modes regardless)
- Default `weeks` value per tool (D-03) and default/max `limit` for `fitness_get_recent_workouts`
  (D-10)
- Default window for `fitness_get_training_summary` (D-08)
- The exact serialized byte budget number and how it's measured (D-13)
- Tool file/package layout under `backend/app/mcp/tools/` (mirrors the existing `ping.py`
  precedent — one tool per file, or grouped — no established convention yet beyond that one file)
- Exact response shape/field naming within each tool's Pydantic model, as long as it follows the
  `_AnalyticsModel`-derived pattern already established in `analytics/schemas.py`
- Tool name for the recomposition tool: `fitness_get_recomposition_status` (aligned with
  ROADMAP.md's wording and the `get_recomposition_status` analytics function name) is the default
  unless research surfaces a reason to match blueprint's literal
  `fitness_get_recomposition_summary` instead

### Deferred Ideas (OUT OF SCOPE)
- `fitness_get_body_composition`, `fitness_get_activity_summary`, `fitness_get_recovery_summary`
  (blueprint §29) — depend on Apple Health / HealthKit data that does not exist yet. Deferred to
  milestone 2.
- Rate limiting on the MCP endpoint — explicitly Phase 7 (Production Hardening).
- New analytics calculations, auth mechanism changes, backup/restore, the coaching instructions
  document.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MCP-02 | MCP server exposes purpose-built, read-only tools covering: recent workouts, a composed training summary, weekly volume, muscle-group volume, exercise progression, personal records, plateaus, training frequency, body-weight trend, recomposition status, and period comparison | §Architecture Patterns Pattern 1 (registration), Pattern 2 (tool module shape), §Tool Inventory table — 12 tools mapped 1:1 to shipped analytics functions with concrete signatures |
| MCP-03 | MCP tools return compact, structured JSON — never raw database access or unbounded result sets | §Response Size Budget (measured bytes per tool, per-tool caps table), §Pitfall 1 (`MuscleGroupVolumeResult` at 52w is 128 KB — the 52-week cap alone does NOT satisfy MCP-03), §Pitfall 2 (the SDK duplicates every payload as a pretty-printed text block, so the wire cost is ~2.7× the structured JSON) |
| MCP-05 | No MCP tool can modify, delete, or write any data — the server is read-only in v1 | §Architecture Patterns Pattern 3 (`ToolAnnotations(read_only_hint=True)`), Pattern 4 (`postgresql_readonly=True` transaction — **verified** to raise `ReadOnlySQLTransactionError` on asyncpg at default isolation), §Don't Hand-Roll (static source guard modelled on `test_analytics_isolation.py`) |
| MCP-06 | No API keys, database credentials, or internal secrets are ever returned in an MCP tool response | §Pitfall 3 (**verified leak**: an unhandled exception in a tool body reaches Claude verbatim as `Error executing tool {name}: {str(e)}` — this is the single highest-risk finding in this phase), §Security Domain |
</phase_requirements>

---

## Summary

Phase 6 is a **composition phase with one genuine engineering problem**. Eleven of the twelve tools
are thin adapters: resolve `user_id`, convert `weeks` → dates, open a session, call one already-shipped
`app.analytics.*` function, return its already-Pydantic result. The MCP scaffolding
(`backend/app/mcp/server.py`, `context.py`, `tools/ping.py`) is proven and needs no change beyond
`mcp.add_tool(...)` calls. Zero new dependencies. Zero new SQL.

The genuine problem is **response size, and it is worse than the discussion assumed**. Two measured
findings drive most of this document:

1. **`MuscleGroupVolumeResult` over a 52-week window serializes to 128,290 bytes of structured JSON
   and ~348 KB on the wire.** D-04's 52-week cap does not bound it, because the shape is
   *weeks × 19 muscle groups*, not weeks. Even a 4-week window costs 10 KB structured / ~27 KB on
   the wire. This tool needs a shape decision, not just a parameter cap — see Pitfall 1 and the
   Open Question at the end.
2. **The SDK emits every tool payload twice** — once as `structuredContent`, and once again as a
   `pretty-printed, indent=2` JSON text block — and this is not configurable without giving up the
   published `outputSchema`. Measured: a 52-week `WeeklyVolumeResult` is 5,211 bytes of structured
   content but **14,304 bytes** of full `CallToolResult`. Any byte budget written against
   `structured_content` alone understates Claude's real context cost by ~2.7×. D-13's budget must
   be measured on the whole `CallToolResult`.

The third material finding is a security one. `mcp 2.0.0`'s `Tool.run` wraps any tool-body exception
as `ToolError(f"Error executing tool {self.name}: {e}")`, and `MCPServer._handle_call_tool` returns
`CallToolResult(content=[TextContent(text=str(e))], is_error=True)`. **The raw exception text reaches
Claude.** I verified this end-to-end: a tool raising `ValueError("postgresql://user:SECRET@host:5432/db unreachable")`
produced exactly that string in the tool result. The existing `structlog` redaction pipeline
(`app/logging.py`) does **not** cover this channel — it only covers log records. MCP-06 therefore
requires the `ping.py` bare-`except` + coarse-payload pattern on **every** tool, enforced by a test,
not by convention.

**Primary recommendation:** Build one shared `backend/app/mcp/tools/_common.py` providing
(a) `resolve_user_id()`, (b) `read_only_session(ctx)` — an async context manager that opens the
lifespan sessionmaker with `postgresql_readonly=True` and rolls back, (c) `window_from_weeks()`, and
(d) a `@safe_tool` decorator that catches every exception, logs it through structlog, and returns a
degraded-but-schema-valid payload. Then write twelve ~40-line tool modules that use nothing else.
Every cross-cutting requirement (MCP-05, MCP-06, D-03, D-04) lives in `_common.py` and is tested once.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Tool discovery / schema publication | MCP SDK (`MCPServer`) | — | `list_tools` output is generated from Python type hints; nothing in this repo builds it by hand |
| Argument validation (`weeks ≤ 52`, `limit ≤ N`) | MCP SDK (pydantic arg model) | Tool body | `Annotated[int, Field(le=52)]` lands in `inputSchema` **and** is enforced before the body runs — verified |
| `user_id` resolution | MCP layer (`app/mcp/`) | — | **Never a tool parameter** (ASVS V4 / IDOR). Analytics requires `user_id` keyword-only with no default; the MCP layer is the only place that may decide it |
| `weeks` → `start_day`/`end_day` | MCP layer (`app/mcp/tools/_common.py`) | `app/core/time.py` | D-03 is an MCP-parameter convention, not an analytics concept. `app/analytics/` signatures are explicit-date by design and 05-PATTERNS.md flags any new `core/time.py` helper as "a design-drift signal" |
| Exercise name → `external_id` (D-01/D-02) | MCP layer | `app/db/` (ORM model only) | Analytics functions take the opaque id; name resolution is a Claude-facing affordance, not arithmetic |
| All arithmetic (volume, progression, records, comparison, recomposition) | `app/analytics/` | — | Already shipped. `test_analytics_isolation.py` statically forbids analytics importing `app.mcp`; the arrow runs one way |
| Read-only enforcement | PostgreSQL transaction | MCP layer + static test | An annotation is a *hint* (SDK docs are explicit). A `READ ONLY` transaction is a guarantee |
| Secret containment in tool output | MCP layer (per-tool `except`) | `app/logging.py` (log channel only) | The SDK's error channel bypasses structlog entirely |
| Byte-budget verification | `backend/tests/` | — | D-13 is a tested property, not a code path |

---

## Standard Stack

**Zero new dependencies.** Every version below was read from this repo's installed `.venv`
via `importlib.metadata`, not from training data.

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `mcp` | **2.0.0** | `MCPServer`, `add_tool`, `ToolAnnotations`, in-memory `Client` | [VERIFIED: `importlib.metadata.version("mcp")` == `2.0.0` in `.venv`] Already pinned in `pyproject.toml`; `server.py` already built on it |
| `mcp-types` | **2.0.0** | `ToolAnnotations`, `CallToolResult`, `TextContent` | [VERIFIED: installed, pinned exactly by `mcp`] Import via `from mcp.types import ToolAnnotations` — re-exported |
| `pydantic` | **2.13.4** | Tool input/output models | [VERIFIED: installed] `_AnalyticsModel` in `analytics/schemas.py` is the established base |
| `sqlalchemy[asyncio]` | **2.0.52** | Session, `postgresql_readonly` execution option | [VERIFIED: installed] |
| `asyncpg` | **0.31.0** | Driver; enforces `READ ONLY` at the transaction | [VERIFIED: installed, and read-only enforcement tested live against `postgres:18-alpine`] |
| `structlog` | **26.1.0** | Tool-side logging through the FOUND-05 redaction chain | [VERIFIED: installed; `app/logging.py` wires it] |

### Supporting (test-only, all already installed)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pytest` | 9.1.1 | Runner; `asyncio_mode = "auto"` already set | Every test |
| `testcontainers[postgres]` | 4.15.0 | Session-scoped `postgres:18-alpine`, migrated by Alembic | Every `@pytest.mark.integration` tool test |
| `time-machine` | 3.4.0 | Freeze "today" | **Required** for every D-03 `weeks`→dates test and every D-07 anchored tool |
| `mcp.Client` | (in `mcp` 2.0.0) | In-memory tool invocation, no HTTP | Every tool test — precedent at `backend/tests/test_mcp_tools.py:45-53` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Returning a `BaseModel` (SDK builds `outputSchema` + both content blocks) | Returning a hand-built `CallToolResult` with compact text | [VERIFIED by execution] Gives full control of the text block (compact instead of `indent=2`), but **`outputSchema` becomes `null`** in `list_tools`. Losing the published output schema costs more than the bytes. **Do not do this.** |
| `Annotated[int, Field(le=52)]` on the tool signature | Bare `int` + in-body validation returning a structured error | Field constraint puts `"maximum": 52` in `inputSchema` so Claude self-corrects before calling. In-body validation lets you control the failure payload. **Recommendation: use the Field constraint** — see Pattern 6 for why the error shape is acceptable |
| `postgresql_readonly=True` per session | `SET TRANSACTION READ ONLY` via `text()` | [VERIFIED both work identically] The execution option is declarative and avoids a raw-SQL string in a package that will grow a `no text()` guard |
| One module per tool | One module per analytics domain (volume, progression, ...) | `ping.py` set the one-file precedent, but 12 files × ~40 lines each with an identical import block is more churn than value. **Recommendation: group by analytics module** — `volume.py`, `progression.py`, `records.py`, `comparison.py`, `body.py`, `workouts.py`, `summary.py` under `app/mcp/tools/`, mirroring `app/analytics/`'s own file split |

**Installation:** none. A proposed new dependency in any Phase 6 plan is a design-drift signal
(same rule 05-RESEARCH.md applied to Phase 5).

---

## Architecture Patterns

### System Architecture Diagram

```
Claude Desktop / Web / Code
        │
        │  HTTPS POST /mcp   (Authorization: Bearer <WorkOS JWT | static secret>)
        ▼
 ┌───────────────────────────────────────────────────────────────────────┐
 │ Cloud Run: one uvicorn process, one FastAPI app (app/main.py)          │
 │                                                                        │
 │   app.mount("/", mcp_app)  ──►  RequireAuthMiddleware                  │
 │                                   │ (verify_token → AccessToken)       │
 │                                   ▼                                    │
 │                              MCPServer._handle_call_tool               │
 │                                   │                                    │
 │                                   ▼                                    │
 │                          Tool.run  (pydantic arg validation)           │
 │                            │            │                              │
 │             weeks > 52 ────┘            │ valid                        │
 │             ⇒ ToolError ⇒ isError=true  ▼                              │
 │                                                                        │
 │   ┌──────────────── app/mcp/tools/*.py  (12 tools) ─────────────────┐  │
 │   │  @safe_tool  ── catches EVERY exception ────────────┐           │  │
 │   │       │                                             ▼           │  │
 │   │       │                                   log.exception(...)    │  │
 │   │       │                                   (structlog 3-layer    │  │
 │   │       │                                    redaction)           │  │
 │   │       ▼                                             │           │  │
 │   │  resolve_user_id(ctx)                               ▼           │  │
 │   │       │                                   coarse degraded       │  │
 │   │       ▼                                   payload, is_error=false│ │
 │   │  read_only_session(ctx)                                         │  │
 │   │       │  sessionmaker() + postgresql_readonly=True              │  │
 │   │       ▼                                                         │  │
 │   │  window_from_weeks(weeks, tz)  ──►  start_day / end_day         │  │
 │   │       │                                                         │  │
 │   │  resolve_exercise(name)  ──► external_id | Ambiguous(D-02)      │  │
 │   │       │                                                         │  │
 │   └───────┼─────────────────────────────────────────────────────────┘  │
 │           ▼  (in-process call, never HTTP — blueprint §37)             │
 │   ┌──────────────── app/analytics/*.py  (Phase 4/5, frozen) ────────┐  │
 │   │  get_weekly_volume · get_muscle_group_volume ·                  │  │
 │   │  get_training_frequency · get_exercise_progression ·            │  │
 │   │  get_plateaus · get_personal_records · compare_periods ·        │  │
 │   │  get_body_weight_trend · get_recomposition_status               │  │
 │   └───────┼─────────────────────────────────────────────────────────┘  │
 │           ▼  SQLAlchemy Core, READ ONLY transaction                    │
 └───────────┼────────────────────────────────────────────────────────────┘
             ▼
      PostgreSQL (Cloud SQL)  ── any INSERT/UPDATE/DELETE ⇒
                                 asyncpg.ReadOnlySQLTransactionError
             │
             ▼  Pydantic BaseModel returned by the tool
    SDK convert_result()
             ├──► structuredContent  (compact JSON, validated against outputSchema)
             └──► content[0].text    (SAME payload, pretty-printed indent=2)   ◄── ~1.5× the
                                                                                    structured size
```

### Recommended Project Structure

```
backend/app/mcp/
├── server.py            # UNCHANGED except +12 mcp.add_tool(...) calls with ToolAnnotations
├── context.py           # UNCHANGED (AppContext.sessionmaker)
├── auth.py              # UNCHANGED
└── tools/
    ├── __init__.py      # unchanged docstring
    ├── _common.py       # NEW — the whole cross-cutting surface (see Pattern 5)
    ├── schemas.py       # NEW — MCP-facing response models + ExerciseLookupFailure (D-02)
    ├── ping.py          # UNCHANGED (keep; it is the DB-connectivity canary)
    ├── workouts.py      # fitness_get_recent_workouts, fitness_get_workout
    ├── volume.py        # fitness_get_weekly_volume, fitness_get_muscle_group_volume,
    │                    #   fitness_get_training_frequency
    ├── progression.py   # fitness_get_exercise_progression, fitness_get_plateaus
    ├── records.py       # fitness_get_personal_records
    ├── comparison.py    # fitness_compare_periods
    ├── body.py          # fitness_get_body_weight_trend, fitness_get_recomposition_status
    └── summary.py       # fitness_get_training_summary

backend/tests/
├── test_mcp_tools.py          # EXTEND — keep the 4 ping tests, add per-tool tests
├── test_mcp_tool_schemas.py   # NEW — annotations, outputSchema, input caps (fast, no container)
├── test_mcp_tool_budget.py    # NEW — D-13 byte budgets (fast, no container: build models directly)
├── test_mcp_isolation.py      # NEW — static read-only/no-leak guards over app/mcp/ source
└── test_mcp_readonly.py       # NEW — @integration: a write through a tool session raises
```

Note `backend/app/mcp/tools/workouts.py` and `backend/app/mcp/tools/volume.py` have **no analog
query code today** — `fitness_get_recent_workouts` and `fitness_get_workout` are the only two
tools with no backing analytics function. See "Runtime State Inventory" equivalent under Open
Questions.

---

### Pattern 1: Tool registration with read-only annotations (MCP-05)

`add_tool` accepts an `annotations: ToolAnnotations | None` parameter.
[VERIFIED: `inspect.signature(MCPServer.add_tool)` on the installed SDK returns
`(self, fn, name=None, title=None, description=None, annotations=None, icons=None, meta=None, structured_output=None)`]

```python
# backend/app/mcp/server.py  — append after the existing fitness_ping registration
from mcp.types import ToolAnnotations

# One constant, reused for all 12. A per-tool literal is 12 chances to forget a flag.
READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    # Explicitly False/None-safe rather than omitted: the SPEC defaults for
    # destructive_hint and open_world_hint are `true`, so leaving them unset
    # advertises a destructive, open-world tool by default.
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)

mcp.add_tool(
    fitness_get_weekly_volume,
    name="fitness_get_weekly_volume",
    description="Weekly training volume (hard sets, reps, tonnage) for the last N weeks.",
    annotations=READ_ONLY,
)
```

[VERIFIED by execution] This serializes into `list_tools` as
`{"readOnlyHint": true, "destructiveHint": false, "idempotentHint": true, "openWorldHint": false}`.

> **The annotation is a hint, not a control.** The SDK docs state plainly: annotations
> "should not be relied upon for security enforcement"
> [CITED: https://py.sdk.modelcontextprotocol.io/v2/servers/tools]. Phase 6's success criterion #4
> says "annotated read-only **and** a write attempt has no surface to reach" — Pattern 4 is the
> other half.

---

### Pattern 2: The tool module shape

Every tool follows this exact skeleton. Deviations are the bug.

```python
# backend/app/mcp/tools/volume.py
"""Volume tools (MCP-02, MCP-03, MCP-05, MCP-06)."""

import datetime as dt
from typing import Annotated

from mcp.server.mcpserver import Context
from pydantic import Field

from app.analytics.volume import get_weekly_volume
from app.analytics.schemas import WeeklyVolumeResult
from app.mcp.context import AppContext
from app.mcp.tools._common import (
    MAX_WEEKS,
    read_only_session,
    resolve_user_id,
    safe_tool,
    window_from_weeks,
)


@safe_tool(degraded=lambda: WeeklyVolumeResult(weeks=[], coverage=..., freshness=...))
async def fitness_get_weekly_volume(
    ctx: Context[AppContext],
    weeks: Annotated[int, Field(ge=1, le=MAX_WEEKS, description="Weeks back from today, max 52.")] = 12,
) -> WeeklyVolumeResult:
    """Weekly training volume for the last N weeks: sessions, hard sets, reps and tonnage."""
    user_id = resolve_user_id(ctx)
    async with read_only_session(ctx) as session:
        start_day, end_day = await window_from_weeks(session, user_id=user_id, weeks=weeks)
        return await get_weekly_volume(
            session, user_id=user_id, start_day=start_day, end_day=end_day
        )
```

Four non-negotiables, each verified:

1. **`ctx` MUST be annotated `Context[AppContext]`.** Already documented in `ping.py`'s docstring:
   an unannotated `ctx` is exposed to the model as a required string argument and every call fails
   schema validation.
2. **The docstring becomes the tool description** unless `description=` is passed to `add_tool`.
   `ping.py` passes an explicit description; do the same so the Claude-facing text is reviewable in
   one file (`server.py`) rather than scattered across twelve docstrings.
3. **`user_id` is never a parameter.** It does not appear in `inputSchema`, so Claude cannot supply
   one. (If a future multi-user version needs per-request identity, the SDK's
   `Annotated[T, Resolve(fn)]` DI hides resolved params from the tool schema — but v1 does not need it.)
4. **Return the analytics `BaseModel` directly** where the size budget allows; return an MCP-specific
   projection model only where the measurements below say you must.

---

### Pattern 3: Structured output generalizes cleanly — with two documented shape rules

[VERIFIED by execution against a `_AnalyticsModel`-shaped model with nested lists, `Decimal | None`,
`StrEnum`, `dict[str, datetime | None]`, and `Literal` unions.]

Returning a Pydantic `BaseModel` produces a full `outputSchema` with `$defs` for every nested model,
correct `required` lists, and `additionalProperties: false` propagated from
`_AnalyticsModel`'s `extra="forbid"`. Nested lists of models work. Optional fields work.
`StrEnum` renders as `{"enum": [...], "type": "string"}`.

Two shape rules the planner must know:

**(a) A union return type gets wrapped in `{"result": ...}`.**
[VERIFIED] A tool annotated `-> Res | Ambiguous` publishes
`{"properties": {"result": {"anyOf": [{"$ref": "#/$defs/Res"}, {"$ref": "#/$defs/Ambiguous"}]}}, "required": ["result"]}`
and returns `structured_content == {"result": {...}}`. A single `BaseModel` return is **not** wrapped.
This is confirmed by the SDK docs: "Scalars, lists, tuples, and unions are wrapped in a result object"
[CITED: https://py.sdk.modelcontextprotocol.io/v2/servers/structured-output].

**Consequence for D-02:** do **not** annotate the progression/records tools as
`-> ExerciseProgressionResult | ExerciseLookupFailure`. That silently nests every successful response
one level deeper under `"result"`, which is a worse contract than the alternative. See Pattern 7.

**(b) `Decimal` serializes as a JSON *string*, not a number.**
[VERIFIED] `Decimal("48213.750")` → `"48213.750"`, and the schema is
`{"anyOf": [{"type": "number"}, {"type": "string", "pattern": "^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$"}, {"type": "null"}]}`.
This is correct and should be kept — it preserves exactness, which is the entire reason
`analytics/schemas.py` chose `Decimal` over `float`. But it costs 2 extra bytes per value in quotes
plus the full quantized precision (`"57.50"`, `"25.000"`), and the `anyOf` triple appears once per
distinct field in `outputSchema`. Do not "fix" it with a `float` field serializer — `test_analytics_isolation.py`
statically forbids `float` in the analytics package for exactly this reason, and the same discipline
belongs here.

---

### Pattern 4: Read-only enforced at the database, not by an annotation (MCP-05)

**[VERIFIED live against `postgres:18-alpine` + `asyncpg 0.31.0` + `sqlalchemy 2.0.52`]**

```python
# backend/app/mcp/tools/_common.py
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.mcpserver import Context
from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.context import AppContext


@asynccontextmanager
async def read_only_session(ctx: Context[AppContext]) -> AsyncIterator[AsyncSession]:
    """A session whose transaction PostgreSQL itself refuses to let write (MCP-05).

    `postgresql_readonly=True` makes asyncpg open the transaction with READ ONLY, so an
    INSERT/UPDATE/DELETE raises `asyncpg.exceptions.ReadOnlySQLTransactionError` from the
    server. This is the half of success criterion #4 that `ToolAnnotations(read_only_hint=True)`
    cannot provide -- the SDK docs say annotations "should not be relied upon for security
    enforcement".

    The rollback is unconditional. Analytics never writes, so there is nothing to commit; a
    rollback also releases the snapshot promptly rather than at pool return.
    """
    sessionmaker = ctx.request_context.lifespan_context.sessionmaker
    async with sessionmaker() as session:
        # Must precede the first query: the execution option applies at transaction START.
        await session.connection(execution_options={"postgresql_readonly": True})
        try:
            yield session
        finally:
            await session.rollback()
```

Three things I verified that contradict what the documentation would lead you to expect:

| Claim | Result |
|---|---|
| SQLAlchemy's PG docs say "some DBAPIs such as asyncpg only support readonly with SERIALIZABLE isolation" [CITED: `sqlalchemy/dialects/postgresql/base.py:227`] | **Not applicable here.** At default isolation, `SHOW transaction_read_only` returned `on` and an `INSERT` raised `ReadOnlySQLTransactionError`. asyncpg builds `START TRANSACTION ... READ ONLY` directly via `Connection.transaction(readonly=...)` (`sqlalchemy/dialects/postgresql/asyncpg.py:838-846`). **Do not add SERIALIZABLE** — it would add serialization-failure retries for no benefit |
| Does the flag leak back into the pooled connection and break `/health` or the sync CLI? | **No.** A later plain session on the same engine reported `transaction_read_only = off` and wrote successfully. The dialect resets the connection characteristic on return |
| Does `SET TRANSACTION READ ONLY` via `text()` work as an alternative? | Yes, identically. Prefer the execution option — it keeps a raw SQL string out of `app/mcp/` |

---

### Pattern 5: `_common.py` — the one place every cross-cutting rule lives

```python
# backend/app/mcp/tools/_common.py  (sketch — the planner should flesh out signatures)

import datetime as dt
import uuid
from collections.abc import Callable

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import local_day, utc_now
from app.db.models.user import User

log = structlog.get_logger()

# D-04. One constant, imported by every window-taking tool AND by the budget test.
MAX_WEEKS = 52
# D-10. Count-based, so the response size is bounded by construction.
MAX_RECENT_WORKOUTS = 25


def resolve_user_id(ctx) -> uuid.UUID:
    """The single v1 user. NEVER a tool parameter (ASVS V4 / IDOR).

    Phase 2 already resolves an AccessToken; `mcp.server.auth.middleware.auth_context
    .get_access_token()` exposes it (and its `subject`) inside a tool. v1 has exactly one
    user, so mapping subject -> user is deliberately deferred -- but the seam is HERE, in one
    function, rather than spread across twelve tools.
    """
    return DEFAULT_USER_ID


async def window_from_weeks(
    session: AsyncSession, *, user_id: uuid.UUID, weeks: int
) -> tuple[dt.date, dt.date]:
    """D-03: `weeks` relative to the user's LOCAL today -> the inclusive range analytics wants.

    `end_day` is the user's LOCAL calendar day, read from `users.timezone` -- never
    `dt.date.today()` and never the server's UTC date. At UTC+7 any instant between 17:00Z
    and 24:00Z belongs to the NEXT local day, so a UTC-derived `end_day` drops the whole of
    today's training for seven hours out of every twenty-four.

    `start_day = end_day - (weeks * 7 - 1)` days: `weeks=1` is a 7-day inclusive range, not 8.
    `get_weekly_volume` snaps outward to whole Monday weeks itself (`snap_local_week_range`),
    so the caller must NOT pre-snap -- doing it twice is how a 52-week request becomes 53 rows
    and blows the D-04 row cap the test asserts on.
    """
    tz = await session.scalar(select(User.timezone).where(User.id == user_id))
    if tz is None:
        raise ValueError("unknown user")
    end_day = local_day(utc_now(), tz)
    return end_day - dt.timedelta(days=weeks * 7 - 1), end_day
```

**Why `_common.py` and not `app/core/time.py`:** `05-PATTERNS.md` explicitly lists
`backend/app/core/time.py` under "Not modified — verify, do not touch", with the note *"Adding a
helper here is a design-drift signal."* `window_from_weeks` also needs a DB read (`users.timezone`),
which `core/time.py` deliberately never does — every function there takes `tz` as a parameter and is
pure/synchronous. Putting an `AsyncSession`-taking function there would break that property. And it
must not go in `app/analytics/`: those signatures are explicit-date by design, and
`resolve_window`/`build_window` already own date validation there.

---

### Pattern 6: Validation errors (D-04) reach Claude as `isError: true` — and that is acceptable

[VERIFIED by execution] With `weeks: Annotated[int, Field(ge=1, le=52)] = 12`:

- `inputSchema` gains `{"minimum": 1, "maximum": 52, "default": 12}` — Claude sees the bound and
  almost never violates it.
- A call with `weeks=999` is rejected by the SDK's generated argument model **before the tool body
  runs**, and returns:
  ```
  is_error: True
  content: [TextContent(text="Error executing tool fitness_get_weekly_volume: 1 validation error
    for volArguments\nweeks\n  Input should be less than or equal to 52
    [type=less_than_equal, input_value=999, input_type=int] ...")]
  structured_content: None
  ```

Two observations the planner needs:

1. **You cannot intercept this in the tool body.** Validation happens in
   `FuncMetadata.call_fn_with_arg_validation` before `fn` is invoked. If you want a
   success-shaped structured error instead, you must drop the `Field` constraint and validate
   manually — which also drops `"maximum": 52` from the published schema. **Recommendation: keep the
   `Field` constraint.** Advertising the bound prevents far more bad calls than a prettier error
   message fixes, and `is_error: true` with a self-explanatory message is a perfectly good outcome
   for a parameter Claude itself chose.
2. **The auto-generated argument model does NOT set `hide_input_in_errors`.**
   [VERIFIED: `ArgModelBase.model_config == ConfigDict(arbitrary_types_allowed=True)` at
   `mcp/server/mcpserver/utilities/func_metadata.py:63`, and there is no public hook to change it.]
   So the rejected value is echoed back. This is **not** an MCP-06 violation — the echoed value is
   the argument the model itself just sent, never server state — but it is worth a one-line comment
   so a future reviewer does not mistake it for a leak. It is also a reason to keep tool parameters
   scalar: never accept a free-form dict or a pass-through filter object whose contents you have not
   reasoned about.

The `ping.py` degrade-in-the-payload convention still applies to **runtime** failures (Pattern 8);
this pattern is only about argument validation, which the SDK owns.

---

### Pattern 7: Exercise name resolution and the D-02 disambiguation response

The query. `ExerciseTemplate` has `user_id`, `provider`, `external_id`, `title`
(`String(255)`, `nullable=False`) with a unique constraint on `(user_id, provider, external_id)`
and **no index on `title`** — a sequential scan over 463 live rows, which is irrelevant at this scale.

```python
# backend/app/mcp/tools/_common.py
from sqlalchemy import func, select
from app.db.models.exercise import ExerciseTemplate

HEVY_PROVIDER = "hevy"          # matches workouts.provider / exercise_templates.provider
MAX_CANDIDATES = 20             # bound the D-02 failure payload too


async def find_templates_by_title(
    session: AsyncSession, *, user_id: uuid.UUID, name: str
) -> list[tuple[str, str]]:
    """Case-insensitive exact match on `exercise_templates.title` (D-01).

    `func.lower(col) == bound_param`, never a Python-side f-string: `S608`/ASVS V5, and the
    same bound-parameter discipline `test_analytics_isolation.py::test_analytics_uses_no_raw_sql_text`
    enforces next door.

    Returns (title, external_id) pairs ordered by title so the D-02 candidate list is
    deterministic -- a flaky ordering is a flaky test, exactly as `analytics/schemas.py` says
    about every other list this project returns.
    """
    stmt = (
        select(ExerciseTemplate.title, ExerciseTemplate.external_id)
        .where(
            ExerciseTemplate.user_id == user_id,
            ExerciseTemplate.provider == HEVY_PROVIDER,
            func.lower(ExerciseTemplate.title) == name.strip().lower(),
        )
        .order_by(ExerciseTemplate.title, ExerciseTemplate.external_id)
        .limit(MAX_CANDIDATES + 1)
    )
    return [(t, x) for t, x in (await session.execute(stmt)).all()]
```

Note the live data makes multi-match real, not theoretical: `external_id` is unique per
`(user_id, provider, external_id)` but **`title` has no uniqueness constraint at all**, and Hevy
ships both built-in templates (8-char hex ids like `05293BCA`) and user-custom ones (full UUIDs).
A user who created a custom "Bench Press (Barbell)" alongside Hevy's own has two rows with the same
title. D-02 exists for exactly this.

**The response shape.** Three options were evaluated; recommend the third.

| Option | Shape | Verdict |
|---|---|---|
| Raise on no-match | `is_error: true` with a text message | ✗ Loses the candidate list, and `is_error` is what a *broken* tool returns |
| Union return `-> Result \| LookupFailure` | Works, **but wraps every response in `{"result": ...}`** [VERIFIED] | ✗ Penalizes the 99% success path to express the 1% failure |
| **One model, optional payload** | `Result` model with `matched: bool`, `candidates: list[ExerciseCandidate]`, and the analytics payload as `progression: ExerciseProgressionResult \| None` | ✓ **Recommended** |

```python
# backend/app/mcp/tools/schemas.py
class ExerciseCandidate(_McpModel):
    """One template that matched (or nearly matched) the requested name. D-02."""
    title: str
    exercise_template_external_id: str


class ExerciseProgressionResponse(_McpModel):
    """D-01/D-02. `progression` is populated iff EXACTLY ONE template matched.

    `matched=False` with an EMPTY `candidates` means "no such exercise"; `matched=False` with
    two or more means "be more specific". Both are ordinary successful results -- the tool did
    exactly what it was asked and reports what it found, so `is_error` stays false and no
    exception text can reach the model.
    """
    requested_name: str
    matched: bool
    candidates: list[ExerciseCandidate]
    progression: ExerciseProgressionResult | None
```

Where `_McpModel` mirrors `_AnalyticsModel`:
`ConfigDict(hide_input_in_errors=True, extra="forbid", frozen=True)`. The
`hide_input_in_errors` matters here for the same reason it does in `analytics/schemas.py`: an
output-model `ValidationError` is raised inside `convert_result`, and its message would otherwise
land in the `str(e)` that Pattern 8 is about.

---

### Pattern 8: The `@safe_tool` guard (MCP-06) — mandatory on all twelve

This is the highest-value pattern in the phase. See Pitfall 3 for the verified leak it closes.

```python
# backend/app/mcp/tools/_common.py
import functools
from collections.abc import Awaitable, Callable
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


def safe_tool(*, degraded: Callable[[], R]) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """No exception may escape a tool body. MCP-06 / T-06 (see Pitfall 3).

    `mcp 2.0.0` wraps any escaping exception as `ToolError(f"Error executing tool {name}: {e}")`
    and `MCPServer._handle_call_tool` returns it to the model as
    `CallToolResult(content=[TextContent(text=str(e))], is_error=True)` -- VERBATIM. An asyncpg
    connection error carries the full DSN (user, password, host, port, database), and structlog's
    three-layer redaction does not touch this channel because it is not a log record.

    Exactly the `ping.py` / `health.py` split, hoisted so it cannot be forgotten on tool number
    nine: the DETAIL goes to `log.exception` (which does run through the redaction pipeline), and
    the caller gets only a coarse, schema-valid degraded payload with `is_error` still false.

    `functools.wraps` is load-bearing: the SDK reads `fn.__doc__`, the return annotation and the
    parameter signature off the wrapped callable to build inputSchema/outputSchema, so a naive
    wrapper publishes `(*args, **kwargs)` and no output schema at all. VERIFY THIS IN A TEST --
    a decorator that silently erases every tool's schema is the most likely way this phase ships
    broken.
    """
    def decorate(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return await fn(*args, **kwargs)
            except Exception:  # noqa: BLE001 - see docstring; nothing may escape
                log.exception("mcp_tool_failed", tool=fn.__name__)
                return degraded()
        return wrapper
    return decorate
```

> ⚠️ **Planner: verify the `functools.wraps` claim before committing to the decorator.**
> I verified the SDK reads `fn.__doc__`, the return annotation and the signature
> (`Tool.from_function` → `func_metadata(fn, ...)` → `inspect.signature`), and `functools.wraps`
> copies `__doc__`, `__name__`, `__wrapped__` and `__module__` — and `inspect.signature` follows
> `__wrapped__` by default. I did **not** execute the decorated form end-to-end. Make
> `test_mcp_tool_schemas.py` assert that every registered tool still publishes a non-null
> `outputSchema` and the expected `inputSchema` properties; if it doesn't, drop the decorator and
> write the `try/except` inline in all twelve tools (uglier, equally correct).
>
> An acceptable alternative if the decorator misbehaves: make the *degraded* value a required part
> of each response model (e.g. every response carries `data_available: bool`), and write the
> `try/except` by hand.

---

### Pattern 9: `fitness_get_recent_workouts` / `fitness_get_workout` have no analytics analog

These two tools are the only ones in the phase that need **new query code**, because no
`app/analytics/` function returns workout-level rows. Constraints:

- They must **not** go in `app/analytics/` — that package's contract is metrics, and
  `test_analytics_isolation.py` will grow to police it.
- They must **not** be raw-table access (the "generic run-a-query tool" is explicitly Out of Scope
  in REQUIREMENTS.md). They are purpose-built projections with a fixed shape and a hard count cap.
- Recommended home: `backend/app/db/repositories/workouts.py` (the package already exists with
  `sync_state.py` as precedent) called from `app/mcp/tools/workouts.py`. This keeps the SQL where
  every other non-analytics query lives and keeps the MCP module a pure adapter.
- D-09's per-workout `hard_sets` / `tonnage_kg` must use the **same** hard-set and operand-presence
  rules Phase 4 uses (`rollup._hard_set_predicates()`: `set_type != WARMUP_SET_TYPE`, and the
  `weight_kg IS NOT NULL AND reps IS NOT NULL` gate for tonnage), or the same workout will report
  different set counts through two different tools. Reuse `_hard_set_predicates()` by import; do not
  re-derive it.
- D-12: key `fitness_get_workout` on `workouts.external_id` (a `String(64)`, unique per
  `(user_id, provider, external_id)`), and echo that same value as the `workout_id` field of every
  `fitness_get_recent_workouts` item. Do **not** echo the internal `workouts.id` UUID — it is a
  database surrogate key, and exposing it invites Claude to treat it as addressable.

---

### Anti-Patterns to Avoid

- **Making `user_id` a tool parameter.** Every analytics function takes `user_id` keyword-only with
  no default precisely so a caller must think about it. Threading that all the way out to Claude
  turns an ASVS V4 control into an IDOR. Resolve it server-side, in one function.
- **Returning `MuscleGroupVolumeResult` verbatim over a 52-week window.** 128 KB. See Pitfall 1.
- **Pre-snapping a `weeks` window to Monday boundaries before calling `get_weekly_volume`.** That
  function calls `snap_local_week_range` itself; snapping twice widens the range and a 52-week
  request returns 53 rows, failing the D-04 row assertion for a reason that looks like an off-by-one
  in the test.
- **Computing "today" as `dt.date.today()` or from a UTC timestamp.** FOUND-03/FOUND-04. Ruff's
  `DTZ` ruleset is already enabled and will catch the naive-datetime half, but not the
  wrong-timezone half. Read `users.timezone` and go through `app.core.time.local_day`.
- **A bare `except: pass` in a tool.** The degraded return value must still validate against the
  published `outputSchema`, or `convert_result` raises a *second* exception from inside the SDK — and
  that one has no guard at all.
- **Adding a new dependency.** Zero are needed.
- **Duplicating `DEFAULT_USER_ID` a third time.** It currently exists in `backend/app/cli.py:45` and
  `backend/migrations/versions/0002_seed_default_user.py:28` (the migration copy is deliberate and
  must stay). Promote the application-side constant to a shared module (`app/config.py` or a new
  `app/core/identity.py`) and have both `cli.py` and `app/mcp/` import it — do not paste a third literal.

---

## Response Size Budget (D-13, MCP-03)

### How to measure

D-13 says "a test serializes each tool's response against realistic/worst-case fixture data and
asserts it stays under an explicit byte budget." **Measure the whole `CallToolResult`**, not
`structured_content`:

```python
result = await mcp_client.call_tool("fitness_get_weekly_volume", {"weeks": 52})
size = len(result.model_dump_json(exclude_none=True).encode("utf-8"))
assert size <= BUDGET["fitness_get_weekly_volume"]
```

**Why:** [VERIFIED by execution] the SDK emits every payload **twice**. `FuncMetadata.convert_result`
builds `unstructured_content = _convert_to_content(result)` — which is
`pydantic_core.to_json(result, fallback=str, indent=2)`, i.e. **pretty-printed** — and *then* also
sets `structured_content`. Both travel to the client. The SDK docs confirm this is by design:
"Every tool result includes both text content for the model and structured content for the
application" [CITED: https://py.sdk.modelcontextprotocol.io/v2/servers/structured-output].

Measured on a 52-week `WeeklyVolumeResult`-shaped model:

| Component | Bytes |
|---|---|
| `structured_content` (compact JSON) | 5,211 |
| `content[0].text` (same data, `indent=2`) | 7,819 |
| **Full `CallToolResult` JSON** | **14,304** |

**Ratio: ~2.7× the compact structured size.** A budget written against `structured_content` alone
understates Claude's actual context cost by nearly three times.

There is no supported way to suppress the text block while keeping `outputSchema`. [VERIFIED]
Returning a hand-built `CallToolResult` gives compact text but publishes `outputSchema: null`.
`structured_output=False` removes the structured half, not the text half. Accept the 2.7× and budget
for it.

### Measured worst cases (real `app.analytics.schemas` models, realistic field values)

All figures below are bytes. "Wire" = structured + pretty-text ≈ full `CallToolResult`.
Live-data ground truth used: 19 canonical muscle groups; 119 distinct exercise templates trained
all-time; 42 templates trained in a 12-week window; 28 exercises classifiable for trends; ~327
workouts over the synced history; at most 12 distinct weights per exercise.

| Result model | Item count | Structured | Wire |
|---|---:|---:|---:|
| `WeeklyVolumeResult` | 52 weeks | 6,454 | 15,999 |
| **`MuscleGroupVolumeResult`** | **52 weeks × 19 mg** | **128,290** | **347,707** |
| `MuscleGroupVolumeResult` | 12 weeks × 19 mg | 29,810 | 80,707 |
| `MuscleGroupVolumeResult` | 4 weeks × 19 mg | 10,114 | 27,307 |
| `TrainingFrequencyResult` | 19 mg + 120 exercises | 23,590 | 54,064 |
| `TrainingFrequencyResult` | 19 mg + 30 exercises | 7,480 | 17,344 |
| `ExerciseProgressionResult` | 104 points (52 wk × 2/wk) | 25,282 | 60,019 |
| `ExerciseProgressionResult` | 26 points (12 wk × 2/wk) | 6,640 | 15,715 |
| `PlateauReport` | 40 exercises | 16,308 | 37,263 |
| `PlateauReport` | 20 exercises | 8,328 | 19,023 |
| `PersonalRecordsResult` | 4 records + 12 reps-at-weight | 1,601 | 3,940 |
| `PeriodComparisonResult` | 40 ex, no muscle groups | 19,169 | 44,070 |
| `PeriodComparisonResult` | 40 ex + 19 mg | 31,014 | 72,950 |
| `BodyWeightTrendResult` | — | 872 | 1,939 |
| `RecompositionResult` | embeds 12-wk volume (its real window) | 3,063 | 7,506 |

And for the three tools with no existing result model, measured against the projection shapes
proposed in this document:

| Proposed model | Item count | Structured | Wire |
|---|---:|---:|---:|
| `fitness_get_training_summary` (lean, see below) | 4 weeks | 3,963 | 9,502 |
| `fitness_get_training_summary` (lean) | 12 weeks | 4,764 | 11,504 |
| `fitness_get_recent_workouts` | limit=10 | 2,379 | 5,573 |
| `fitness_get_recent_workouts` | limit=25 | 5,544 | 13,013 |
| `fitness_get_recent_workouts` | limit=50 | 10,819 | 25,413 |
| `fitness_get_workout` | 7 ex × 4 sets | 4,926 | 13,177 |
| `fitness_get_workout` | 12 ex × 5 sets | 9,718 | 26,310 |
| `fitness_get_workout` | 20 ex × 6 sets | 18,490 | 50,430 |
| muscle-group volume **rolled up over the window** (19 rows, any window) | 19 | 3,255 | 7,851 |

### Recommended per-tool caps and budgets

Budget = measured worst case at the recommended cap, rounded up with ~30% headroom. All budgets are
**full `CallToolResult` bytes**.

| Tool | Parameter caps | Budget |
|---|---|---:|
| `fitness_ping` | — | 2 KB |
| `fitness_get_body_weight_trend` | none (D-07) | 4 KB |
| `fitness_get_recomposition_status` | none (D-07) | 12 KB |
| `fitness_get_personal_records` | `weeks ≤ 52`, default 52 | 8 KB |
| `fitness_get_muscle_group_volume` | **see Open Question 1** — rollup shape: any window | 12 KB |
| `fitness_get_training_summary` | `weeks ≤ 12`, default 4 | 16 KB |
| `fitness_get_recent_workouts` | `limit ≤ 25`, default 10 | 20 KB |
| `fitness_get_weekly_volume` | `weeks ≤ 52`, default 12 | 20 KB |
| `fitness_get_training_frequency` | `weeks ≤ 52`, default 12; **`exercises` list truncated to top 30 by sessions** | 20 KB |
| `fitness_get_exercise_progression` | `weeks ≤ 52`, default 12; **`points` truncated to the 60 most recent** | 24 KB |
| `fitness_get_plateaus` | `lookback_weeks ≤ 52`, default 12; **`exercises` truncated to 30**, `plateaued_only: bool = True` | 24 KB |
| `fitness_compare_periods` | each period ≤ 365 days; **`exercises`/`exercise_levels` truncated to 25 each**; `include_muscle_groups=False` default | 32 KB |
| `fitness_get_workout` | one workout; **sets truncated at 120** | 32 KB |

Three of these caps require **truncation the analytics layer does not do**
(`training_frequency.exercises`, `plateaus.exercises`, `compare_periods.exercises`). Every truncated
list must carry a `truncated: bool` + `total_available: int` alongside it, or Claude will read
"30 exercises" as "you train 30 exercises" — a wrong answer with no signal, exactly the failure mode
D-02 exists to prevent elsewhere. Note `get_exercise_trends` and `get_plateaus` already accept a
`template_external_ids: Sequence[str] | None` narrowing parameter, so truncation can be pushed into
the query rather than applied after the fact.

### Recommended `fitness_get_training_summary` shape (D-08)

Composing the four analytics results verbatim costs ~24 KB structured / ~57 KB wire at a 4-week
window — far too heavy for "the one tool every conversation opens with". The measured lean shape
(3,963 structured / 9,502 wire at 4 weeks) drops the per-week × per-muscle grid to a
**per-window muscle rollup** and drops the per-exercise frequency list entirely:

```python
class TrainingSummary(_McpModel):
    window_start: dt.date
    window_end: dt.date
    weeks: int
    sessions_per_week: Decimal
    volume_by_week: list[SummaryVolumeWeek]        # week_start, sessions, hard_sets, total_reps, tonnage_kg
    muscles: list[SummaryMuscle]                   # 19 rows: direct/indirect/weighted sets,
                                                   #   sessions, sessions_per_week, insufficient_data
    recomposition_status: RecompositionStatus
    recomposition_disclaimer: str                  # RecompositionResult.disclaimer, verbatim -- REQUIRED
    progression_signal: ProgressionSignal
    progression_verdict: TrendVerdict
    weight_trend_rate_percent_per_week: Decimal | None
    average_7d_kg: Decimal | None
    coverage: CoverageMetadata
    freshness: FreshnessMetadata
```

The `disclaimer` must be carried through verbatim. `RecompositionResult`'s docstring is explicit
that it is *"a REQUIRED FIELD, not documentation"* precisely so a Phase 6 serialization change cannot
drop it — dropping it here would be exactly the failure that docstring anticipates.

**Cost note:** this tool issues four analytics calls, and `get_recomposition_status` alone runs
`get_body_weight_trend` + `get_exercise_trends` + `get_weekly_volume` over 12 weeks. That is seven
aggregate queries in one tool call. All within one read-only transaction, which is correct (one
consistent snapshot), but the planner should budget a latency check against the live dataset — Claude's
connector timeouts are 10 s for discovery, and a slow first tool call is the worst first impression
this project can make.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---|---|---|---|
| Publishing a tool's JSON output schema | A hand-written `output_schema` dict | Return a Pydantic `BaseModel`; the SDK generates it | [VERIFIED] `$defs`, `required`, `additionalProperties: false` and enum members all derived correctly from `_AnalyticsModel` subclasses |
| Enforcing `weeks ≤ 52` | An `if weeks > 52: return ...` in twelve tool bodies | `Annotated[int, Field(ge=1, le=MAX_WEEKS)]` | Lands in `inputSchema` so Claude self-corrects, **and** is enforced before the body runs |
| Preventing writes | Code review + an annotation | `postgresql_readonly=True` on the session + a static source guard | [VERIFIED] PostgreSQL raises `ReadOnlySQLTransactionError`; the annotation is documented as a non-security hint |
| Timezone-correct "today" | `dt.date.today()`, `datetime.utcnow().date()` | `app.core.time.local_day(utc_now(), tz)` with `tz` from `users.timezone` | FOUND-03/04; at UTC+7 a UTC date is wrong for 7 hours a day, which is every morning workout |
| Local date range → UTC bounds | Hand-rolled `ZoneInfo` arithmetic | `app.core.time.local_range_bounds` (already used by `rollup.build_window`) | Keeps the index on `workouts.start_time` usable; a second copy would eventually disagree about a DST day |
| Week bucketing / gap-free week spines | A loop over `timedelta(weeks=1)` in a tool | `get_weekly_volume` already returns a gap-free ascending spine | A zero-training week is the most diagnostically interesting row; re-deriving the spine is how it goes missing |
| Muscle-group resolution | A join on `exercise_muscles` | `app.normalization.resolver.effective_muscles_bulk` (already used by analytics) | NORM-02's override rule is REPLACEMENT, not merge. A direct join is byte-identical today and starts lying at the first user correction |
| e1RM / plateau / trend math in a tool | Anything | `app.analytics.*` | `test_analytics_isolation.py::test_epley_is_computed_only_in_estimates` will fail the build, and PostgreSQL integer division makes the wrong version silently return the bare weight |
| Redacting secrets from log lines | A per-tool sanitizer | `structlog.get_logger()` + the three-layer chain in `app/logging.py` | Already covers key-name deny-list, value scrubbing, and rendered tracebacks. **But it does not cover the SDK's tool-error channel** — that needs Pattern 8 |
| Testing tools over HTTP | `TestClient` + a bearer token per test | `mcp.Client(mcp)` in-memory | Precedent + rationale already written at `backend/tests/test_mcp_tools.py:1-26`: it deliberately bypasses auth so a failure can only be the tool |

**Key insight:** almost every "hard" thing in this phase is already solved one directory over. The
correct Phase 6 plan is mostly a list of imports.

---

## Common Pitfalls

### Pitfall 1: The 52-week cap does not bound `fitness_get_muscle_group_volume`

**What goes wrong:** D-04 caps `weeks` at 52, and the discussion reasoned "a weekly-volume series can
never exceed 52 rows." That is true for `WeeklyVolumeResult`. `MuscleGroupVolumeResult`'s shape is
`weeks × muscle_groups`, so 52 weeks is **988 rows**, not 52.

**Measured:** 128,290 bytes structured / ~347,707 bytes wire. Even a 4-week window is 27 KB wire.

**Why it happens:** the cap was reasoned about at the parameter, not at the response shape. Two of
the twelve tools have a multiplicative shape (`fitness_get_muscle_group_volume` = weeks × 19;
`fitness_compare_periods` with `include_muscle_groups=True` = 19 × 3 rate objects).

**How to avoid:** see Open Question 1 — this needs a decision, and the two options are a shape change
or a much lower per-tool week cap. Do not ship the verbatim 52-week form.

**Warning signs:** any tool whose response nests a list inside a list. Grep the plan for `list[` twice
in one model.

---

### Pitfall 2: Budgeting against `structured_content` understates the payload by ~2.7×

**What goes wrong:** the obvious D-13 test is
`len(json.dumps(result.structured_content).encode()) < BUDGET`. That measures under half of what
crosses the wire.

**Why it happens:** `FuncMetadata.convert_result` unconditionally builds a second, **pretty-printed**
(`indent=2`) copy of the same payload as `content[0].text`, and both are returned. This is documented
SDK behaviour, not a bug.

**How to avoid:** assert on `len(result.model_dump_json(exclude_none=True).encode("utf-8"))`.

**Warning signs:** a budget number that looks comfortable and a Claude conversation that runs out of
context after three tool calls.

---

### Pitfall 3: An unhandled exception in a tool body sends its message text to Claude (MCP-06)

**What goes wrong — verified end-to-end:**

```
Tool body:  raise ValueError("postgresql://user:SECRET@host:5432/db unreachable")
Claude receives:
  is_error: True
  content: [TextContent(text="Error executing tool boom: postgresql://user:SECRET@host:5432/db unreachable")]
```

**Why it happens:** `Tool.run` catches `Exception` and re-raises as
`ToolError(f"Error executing tool {self.name}: {e}")`
(`mcp/server/mcpserver/tools/base.py`, final `except` block). `MCPServer._handle_call_tool` then
returns `CallToolResult(content=[TextContent(type="text", text=str(e))], is_error=True)`
(`mcp/server/mcpserver/server.py:424`). There is **no** `mask_error_details` option in `mcp 2.0.0`
(that is a FastMCP feature, and this project does not use FastMCP).

An `asyncpg` connection error carries the full DSN — user, password, host, port, database. The
existing `structlog` redaction pipeline does not see it, because this is not a log record.

`backend/tests/test_mcp_tools.py:94-121` already tests this exact leak for `fitness_ping`, against a
**real** connection to closed port 1 rather than a mock — for the stated reason that a patched
exception proves the `except` branch runs, not that a real driver error is what lands in it. Every
new tool needs the same guard and deserves the same style of test.

**How to avoid:** Pattern 8's `@safe_tool`. Then assert it statically: a test that reads every file
under `app/mcp/tools/` and fails if a public `fitness_*` coroutine is defined without the guard —
modelled on `test_analytics_isolation.py`'s source-walking approach, which already covers `app/analytics/`
and is the established convention in this repo for exactly this class of invariant.

**Warning signs:** any `raise` in a tool module. Any tool whose body calls something that can raise
and has no `try`. `ValueError("unknown user")` from `window_from_weeks` is itself an example — harmless
text, but it proves the channel is open.

---

### Pitfall 4: A union return type silently nests every successful response under `"result"`

**What goes wrong:** `-> ExerciseProgressionResult | ExerciseLookupFailure` looks like the natural way
to express D-02. It publishes a valid `anyOf` schema — and changes `structured_content` from
`{"exercise_template_external_id": ...}` to `{"result": {"exercise_template_external_id": ...}}` on
**every** call, including successes.

**Why it happens:** the SDK's `_try_create_model_and_schema` sets `wrap_output = True` for unions,
scalars, lists and tuples; only a single `BaseModel` (or TypedDict/dataclass) is returned unwrapped.
[VERIFIED by execution and confirmed in the SDK docs.]

**How to avoid:** Pattern 7's single-model-with-optional-payload shape.

**Warning signs:** a `|` in any tool's return annotation.

---

### Pitfall 5: `functools.wraps` and the SDK's signature introspection

**What goes wrong:** a decorator without `functools.wraps` publishes a tool with
`inputSchema` derived from `(*args, **kwargs)` and `outputSchema: null`, silently. The tool still
"works" over the wire; Claude just gets no schema and no argument names.

**Why it happens:** `Tool.from_function` reads `fn.__doc__`, `inspect.signature(fn)` and the return
annotation. `func_metadata` builds both the argument model and the output model from those.

**How to avoid:** `functools.wraps` (which sets `__wrapped__`, so `inspect.signature` follows through),
plus a test that asserts every registered tool has a non-null `outputSchema`. The existing
`test_ping_output_schema_requires_both_fields` is the template.

---

### Pitfall 6: Double week-snapping

**What goes wrong:** `window_from_weeks(weeks=52)` returns a 364-day range; `get_weekly_volume` then
calls `snap_local_week_range` to widen it outward to whole Monday weeks. If the request did not start
on a Monday, that is **53** week rows, and the D-04 "never more than 52 rows" assertion fails.

**Why it happens:** the snapping is invisible — it happens inside `rollup.build_window(snap_to_weeks=True)`,
two calls deep.

**How to avoid:** either compute `start_day` as the Monday `weeks-1` weeks back from this week's Monday,
or write the row assertion as `<= weeks + 1`. **Prefer the former** — Monday-anchored is what the user
means by "the last 12 weeks" anyway, and an off-by-one budget assertion is a budget assertion that will
be loosened again next time.

**Warning signs:** a `len(result.weeks) == weeks` assertion that passes on Mondays.

---

### Pitfall 7: `mcp.session_manager._has_started` and the in-memory `Client`

**What goes wrong:** the `client` fixture in `conftest.py:579` resets
`mcp.session_manager._has_started = False` per test because
`StreamableHTTPSessionManager.run()` refuses a second call per instance. Any new test module that
takes the `client` fixture inherits this; any that constructs its own app does not.

**How to avoid:** take the existing `client` fixture, exactly as `test_mcp_tools.py` does — even for
tests that only use `Client(mcp)` and never issue an HTTP request. `test_mcp_tools.py`'s existing
tests all take `client: TestClient` for precisely this reason: `mcp_lifespan` reads
`app.state.sessionmaker`, which only exists once the FastAPI lifespan has run.

---

### Pitfall 8: The conftest MCP env seeding runs at module import, not fixture time

`backend/tests/conftest.py:95-112` seeds `MCP_AUTH_SECRET`, `MCP_ALLOWED_HOSTS`, etc. at **module
scope**, with a long comment explaining that a session-scoped autouse fixture runs after collection
and is therefore too late — `app.mcp.server` is imported during collection and freezes the verifier
and the host allowlist. New test modules must not `from app.mcp.server import mcp` at module scope
unless they are prepared for that ordering; `test_mcp_tools.py` imports it **inside each test
function** for this reason. Follow that convention.

---

## Code Examples

### Registering all twelve tools (`server.py` addition)

```python
# Source: pattern verified against the installed mcp 2.0.0; mirrors the existing
# mcp.add_tool(fitness_ping, ...) call at backend/app/mcp/server.py:67-71
from mcp.types import ToolAnnotations

from app.mcp.tools.body import fitness_get_body_weight_trend, fitness_get_recomposition_status
from app.mcp.tools.comparison import fitness_compare_periods
from app.mcp.tools.progression import fitness_get_exercise_progression, fitness_get_plateaus
from app.mcp.tools.records import fitness_get_personal_records
from app.mcp.tools.summary import fitness_get_training_summary
from app.mcp.tools.volume import (
    fitness_get_muscle_group_volume,
    fitness_get_training_frequency,
    fitness_get_weekly_volume,
)
from app.mcp.tools.workouts import fitness_get_recent_workouts, fitness_get_workout

READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)

_TOOLS = (
    (fitness_get_recent_workouts, "Most recent workouts as compact summaries (no per-set detail)."),
    (fitness_get_workout, "Full exercise and set breakdown for one workout, by its Hevy id."),
    (fitness_get_training_summary, "Composed training picture: volume, per-muscle work, and recomposition status."),
    (fitness_get_weekly_volume, "Weekly hard sets, reps and tonnage."),
    (fitness_get_muscle_group_volume, "Per-muscle-group direct and indirect set volume."),
    (fitness_get_training_frequency, "Sessions per week overall, per muscle group and per exercise."),
    (fitness_get_exercise_progression, "One exercise's weight/reps/e1RM time series, by exercise name."),
    (fitness_get_personal_records, "One exercise's personal records, by exercise name."),
    (fitness_get_plateaus, "Exercises that have stopped progressing, with the window and threshold used."),
    (fitness_compare_periods, "Two explicit date periods compared, normalized per week."),
    (fitness_get_body_weight_trend, "7/14/30-day rolling body-weight averages and weekly rate."),
    (fitness_get_recomposition_status, "Recomposition verdict from weight trend and training progression."),
)

for _fn, _description in _TOOLS:
    mcp.add_tool(_fn, name=_fn.__name__, description=_description, annotations=READ_ONLY)
```

> A loop rather than twelve literal calls: it makes "every tool is annotated read-only" structurally
> true instead of twelve chances to omit `annotations=`. A test should still assert
> `all(t.annotations.read_only_hint for t in list_tools())` — the loop guarantees it today, and the
> test guarantees it after someone adds a thirteenth tool by hand.

### The D-13 budget test

```python
# Source: measurement methodology verified by executing against mcp 2.0.0
# backend/tests/test_mcp_tool_budget.py
import pytest

# Full CallToolResult bytes -- structured content PLUS the pretty-printed text block the SDK
# always duplicates it into. Budgeting on structured_content alone understates this by ~2.7x.
BUDGETS: dict[str, int] = {
    "fitness_ping": 2_048,
    "fitness_get_body_weight_trend": 4_096,
    "fitness_get_personal_records": 8_192,
    "fitness_get_recomposition_status": 12_288,
    "fitness_get_muscle_group_volume": 12_288,
    "fitness_get_training_summary": 16_384,
    "fitness_get_recent_workouts": 20_480,
    "fitness_get_weekly_volume": 20_480,
    "fitness_get_training_frequency": 20_480,
    "fitness_get_exercise_progression": 24_576,
    "fitness_get_plateaus": 24_576,
    "fitness_compare_periods": 32_768,
    "fitness_get_workout": 32_768,
}


def test_every_registered_tool_has_a_budget() -> None:
    """A tool with no budget is a tool with no MCP-03 enforcement.

    Fast (no container): asserting the KEYS match the registry is what stops tool number
    thirteen from shipping unbounded.
    """
    from app.mcp.server import mcp

    registered = {t.name for t in mcp._tool_manager.list_tools()}  # or the public list_tools()
    assert registered == set(BUDGETS), f"unbudgeted tools: {registered ^ set(BUDGETS)}"


@pytest.mark.integration
async def test_tool_response_fits_its_budget(client, worst_case_history, tool_name, args) -> None:
    from mcp import Client
    from app.mcp.server import mcp

    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool(tool_name, args)

    size = len(result.model_dump_json(exclude_none=True).encode("utf-8"))
    assert size <= BUDGETS[tool_name], (
        f"MCP-03: {tool_name} returned {size:,} bytes against a {BUDGETS[tool_name]:,} budget. "
        f"Every byte here enters Claude's context window."
    )
```

The `worst_case_history` fixture should extend `GoldenBuilder` to seed a maximal-but-realistic
history: 52 weeks of training, ~5 sessions/week, ~30 distinct templates each mapped to several
muscle groups. It belongs in `conftest.py` beside `golden_workout`, with the same
flush-and-rollback contract.

### The static read-only guard

```python
# Source: structure copied verbatim in spirit from backend/tests/test_analytics_isolation.py
# backend/tests/test_mcp_isolation.py
import re
from pathlib import Path

MCP = Path(__file__).resolve().parents[2] / "backend" / "app" / "mcp"

_SESSION_WRITE = re.compile(r"\bsession\.(?:commit|flush|add|add_all)\s*\(")
_WRITE_IMPORT = re.compile(
    r"^\s*from\s+sqlalchemy\s+import\s+.*\b(?:insert|update|delete)\b", re.MULTILINE
)
# MCP-06: no tool may interpolate an exception into anything it returns. The `except` must
# hand the exception to structlog and return a constant-shaped payload.
_EXC_IN_RETURN = re.compile(r"(?:str\(exc\)|str\(e\)|f\"[^\"]*\{(?:exc|e|err|error)\}|repr\(e\))")


def test_mcp_tools_never_write() -> None:
    """MCP-05, statically. The READ ONLY transaction is the runtime guarantee; this is the
    guarantee that a future tool does not open its own session and bypass it."""
    for path in sorted(MCP.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        assert not _SESSION_WRITE.search(source), f"MCP-05 violated in {path.name}"
        assert not _WRITE_IMPORT.search(source), f"MCP-05 violated in {path.name}"


def test_mcp_tools_never_interpolate_an_exception() -> None:
    """MCP-06 / Pitfall 3. An asyncpg connection error carries the DSN, and the SDK returns
    any escaping exception's str() to Claude verbatim."""
    for path in sorted(MCP.rglob("*.py")):
        assert not _EXC_IN_RETURN.search(path.read_text(encoding="utf-8")), (
            f"MCP-06 violated in {path.name}: the detail goes to log.exception, "
            f"the caller gets a coarse constant"
        )
```

Note the same anchored-regex discipline `test_analytics_isolation.py` documents: never a bare
substring, because prose in these modules deliberately discusses the very patterns being banned and
a substring check would fail on the sentence explaining the rule.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|---|---|---|---|
| `from mcp.server.fastmcp import FastMCP` | `from mcp.server import MCPServer` | `mcp` 2.0.0 | Already handled in Phase 2. Every pre-2026 tutorial and most model completions use the old import |
| `@mcp.tool()` decorator only | `mcp.add_tool(fn, ..., annotations=...)` **or** `@mcp.tool(annotations=...)` — identical parameters | 2.0.0 | This repo uses `add_tool`; both accept `annotations` [VERIFIED via `inspect.signature`] |
| `mcp.types` bundled in `mcp` | Split into `mcp-types` 2.0.0, re-exported through `mcp.types` | 2.0.0 | `from mcp.types import ToolAnnotations` works [VERIFIED] |
| Tool exceptions → JSON-RPC protocol error | Tool exceptions → `CallToolResult(is_error=True)` with `str(e)` | 2.0.0 | [CITED: https://py.sdk.modelcontextprotocol.io/v2/migration] Changes the leak surface: the exception text is now model-visible rather than transport-level |
| `mask_error_details` (FastMCP) | **No equivalent in `mcp` 2.0.0** | — | Guard per-tool; see Pattern 8 |

**Deprecated/outdated for this phase:**
- `mcp` 1.x session-based transport — irrelevant; `server.py` already runs `stateless_http=True`.
- The `@mcp.custom_route` decorator for a health endpoint — SDK docs warn custom routes are never
  authenticated. `/health` is already on the FastAPI side; keep it there.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|---|---|---|
| A1 | `functools.wraps` preserves everything `Tool.from_function` needs (`__doc__`, signature via `__wrapped__`, return annotation) so `@safe_tool` does not erase schemas | Pattern 8 | **HIGH** — a silently schema-less tool surface. Verified by reading `Tool.from_function` and `func_metadata`, **not** by executing the decorated form. Mitigation is a one-line test; the plan must include it |
| A2 | The live account's realistic worst case is ~52 weeks × ~5 sessions/week, ~30 distinct templates per 12-week window, ~120 all-time | Response Size Budget | MEDIUM — budgets sized too tight or too loose. Derived from `04-RESEARCH.md` ("119 distinct templates all-time"), `05-07-PLAN.md` ("42 templates trained in the live 12-week window", "28 exercises" classified) and STATE.md (327 workouts / 7,984 sets). Not re-measured against the live DB in this session |
| A3 | A typical worst-case single workout is ≤ 12 exercises × ~6 sets (~72 sets) | `fitness_get_workout` budget | LOW — 7,984 sets over 327 workouts averages 24 sets/workout, so 72 is ~3× the mean. If a real workout exceeds it, the set cap (120) catches it and the `truncated` flag reports it |
| A4 | Grouping tools by analytics module (7 files) rather than one-per-tool (12 files) is the better layout | Recommended Project Structure | LOW — pure organization; CONTEXT.md marks it Claude's discretion |
| A5 | `fitness_get_recent_workouts` / `fitness_get_workout` query code belongs in `app/db/repositories/workouts.py` | Pattern 9 | LOW — the alternative (inline in `app/mcp/tools/workouts.py`) is equally correct; the repository placement matches `sync_state.py` precedent |
| A6 | `MAX_ANALYTICS_WINDOW_DAYS = 1830` (~5 years) never binds for MCP tools, since `weeks ≤ 52` = 364 days and `compare_periods` periods are capped at 365 | Recommended caps | LOW — verified the constant exists at `rollup.py:75`; the MCP caps are strictly tighter |
| A7 | Latency of `fitness_get_training_summary` (7 aggregate queries) is acceptable | Training summary shape | MEDIUM — untested. Phase 4 measured `weekly_set_rows` at ~50 ms for 7,984 live sets; four composed calls plausibly land in the low hundreds of ms, but this was not measured |

---

## Open Questions

### 1. `fitness_get_muscle_group_volume`: shape change, or a much lower week cap? — **(RESOLVED — user selected option (a) via AskUserQuestion during /gsd-plan-phase 6; implemented in plan 06-02/06-05)**

- **What we know:** returning `MuscleGroupVolumeResult` verbatim over the D-04-permitted 52-week
  window is 128 KB structured / ~348 KB on the wire (measured). That is a straightforward MCP-03
  violation — "never unbounded result sets" in spirit if not in letter. Even 4 weeks is 27 KB wire.
- **What's unclear:** CONTEXT.md's canonical refs say tool response models *"compose these, they do
  not reshape them"* about `analytics/schemas.py`. But CONTEXT.md's Claude's-Discretion list also
  says *"Exact response shape/field naming within each tool's Pydantic model"* is discretionary as
  long as it follows the `_AnalyticsModel` pattern. These pull in opposite directions for this one tool.
- **Options:**

  | Option | Wire cost | Cost |
  |---|---|---|
  | **(a) Roll up over the window** — 19 rows regardless of window; add `sessions_per_week` per muscle so it answers "which muscles are undertrained?" directly | **7.9 KB, any window** | Reshapes. Loses the per-week muscle trend |
  | (b) Keep per-week, cap this tool at `weeks ≤ 4` | 27 KB | Composes verbatim, but a 4-week ceiling on the muscle-volume tool is a surprising asymmetry |
  | (c) Keep per-week, cap at `weeks ≤ 8`, add a `muscle_groups: list[...] \| None` filter | 54 KB unfiltered | Still heavy by default; pushes the bounding onto Claude |
  | (d) Both: rollup by default, `by_week: bool = False` opt-in capped at 4 weeks | 7.9 KB / 27 KB | Two shapes to test and document |

- **Recommendation: (a).** The tool's job is answering "which muscles are undertrained?", which is a
  window-level question, not a week-by-week one. The per-week trend for *total* volume is already
  covered by `fitness_get_weekly_volume`, and `fitness_compare_periods` covers "is this muscle up or
  down versus last block". Roll up, budget 12 KB, and note the reshape explicitly in the tool's
  docstring so the "compose, don't reshape" rule is seen to be broken deliberately and exactly once.
- **This should go to the user via `/gsd-discuss-phase` or be surfaced in the plan for confirmation** —
  it is the one place where the measured evidence contradicts a stated constraint.

### 2. Where does `DEFAULT_USER_ID` live for application code? — **(RESOLVED — implemented as recommended in plan 06-01: module constant in `app/config.py`)**

- **What we know:** it exists at `backend/app/cli.py:45` and `backend/migrations/versions/0002_seed_default_user.py:28`.
  `conftest.py:62` has a third copy, deliberately (a test asserting against a value it imports proves
  nothing). No `app/` module outside `cli.py` knows it.
- **What's unclear:** whether it becomes a `Settings` field (env-overridable), a constant in
  `app/config.py`, or a new `app/core/identity.py`.
- **Recommendation:** a plain module constant in `app/config.py` alongside `Settings`, imported by
  both `cli.py` and `app/mcp/tools/_common.py`. Not a `Settings` field — it is not configuration, it
  is a migration-fixed identity, and making it env-overridable creates a way to point production at a
  `user_id` with no `users` row behind it.

### 3. Do truncated lists need a Phase 7 follow-up? — **(RESOLVED — implemented as recommended: Python-side truncation with `truncated`/`total_available` fields, across plans 06-05/06-06/06-07; query-pushdown noted as a Phase 7 candidate, not blocking)**

- **What we know:** three tools need list truncation the analytics layer does not perform
  (`training_frequency.exercises`, `plateaus.exercises`, `compare_periods.exercises`).
- **What's unclear:** whether truncating in Python after a full query is acceptable, or whether the
  narrowing should be pushed into the query. `get_exercise_trends` and `get_plateaus` already accept
  `template_external_ids: Sequence[str] | None`, which makes the pushdown possible; `compare_periods`
  does not.
- **Recommendation:** truncate in Python in Phase 6 with an explicit `truncated`/`total_available`
  pair. The query cost is already paid and the data volume is small (single user, ~8k sets). Note it
  as a Phase 7 optimization candidate rather than blocking on it.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|---|---|---|---|---|
| Python | everything | ✓ | 3.13 (`.python-version`) | — |
| `mcp` | all tools | ✓ | 2.0.0 | — |
| `mcp-types` | `ToolAnnotations` | ✓ | 2.0.0 | — |
| `pydantic` | all response models | ✓ | 2.13.4 | — |
| `sqlalchemy` | `postgresql_readonly` execution option | ✓ | 2.0.52 | `SET TRANSACTION READ ONLY` via `text()` |
| `asyncpg` | READ ONLY transaction enforcement | ✓ | 0.31.0 | — |
| `pytest` / `pytest-asyncio` | tests | ✓ | 9.1.1 / 1.4.0 | — |
| `testcontainers[postgres]` | integration tool tests | ✓ | 4.15.0 | — |
| `time-machine` | freezing "today" for D-03/D-07 tests | ✓ | 3.4.0 | — |
| Docker | testcontainers | ✓ | verified running (`docker info` succeeded; `postgres:18-alpine` pulled and driven live during this research) | run `-m "not integration"` |
| Context7 / ctx7 CLI | SDK docs lookup | ✓ | `npx ctx7@latest` | installed SDK source is the stronger authority anyway |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none.

---

## Validation Architecture

### Test Framework

| Property | Value |
|---|---|
| Framework | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths = ["backend/tests"]`, `pythonpath = ["backend"]`, marker `integration`) |
| Quick run command | `uv run pytest backend/tests -x -q -m "not integration"` |
| Full suite command | `uv run pytest backend/tests -q --cov=backend/app` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|---|---|---|---|---|
| MCP-02 | All 12 tools are registered and discoverable with the expected names | unit (fast) | `uv run pytest backend/tests/test_mcp_tool_schemas.py::test_tool_registry_is_exactly_the_twelve -x` | ❌ Wave 0 |
| MCP-02 | Each tool returns the expected structured payload against golden fixture data | integration | `uv run pytest backend/tests/test_mcp_tools.py -x -m integration` | ✅ extend |
| MCP-02 | `fitness_get_training_summary` answers in ONE call (composes volume + muscle + frequency + recomposition) | integration | `uv run pytest backend/tests/test_mcp_tools.py::test_training_summary_composes_four_analytics -x` | ❌ Wave 0 |
| MCP-02/D-01 | Exercise name resolves to a template case-insensitively | integration | `uv run pytest backend/tests/test_mcp_tools.py::test_exercise_name_is_case_insensitive -x` | ❌ Wave 0 |
| MCP-02/D-02 | Zero-match and multi-match both return candidates with `matched=False` and `is_error=False` | integration | `uv run pytest backend/tests/test_mcp_tools.py -k disambiguat -x` | ❌ Wave 0 |
| MCP-03 | Every tool has a declared byte budget | unit (fast) | `uv run pytest backend/tests/test_mcp_tool_budget.py::test_every_registered_tool_has_a_budget -x` | ❌ Wave 0 |
| MCP-03 | Every tool's full `CallToolResult` fits its budget against worst-case history | integration | `uv run pytest backend/tests/test_mcp_tool_budget.py -x -m integration` | ❌ Wave 0 |
| MCP-03/D-04 | `weeks > 52` is rejected, and `inputSchema` advertises `maximum: 52` | unit (fast) | `uv run pytest backend/tests/test_mcp_tool_schemas.py::test_week_caps_are_published_and_enforced -x` | ❌ Wave 0 |
| MCP-03/D-10 | `limit` above the cap is rejected; a full-cap list stays in budget | integration | `uv run pytest backend/tests/test_mcp_tool_budget.py -k recent_workouts -x` | ❌ Wave 0 |
| MCP-05 | Every registered tool carries `readOnlyHint: true` | unit (fast) | `uv run pytest backend/tests/test_mcp_tool_schemas.py::test_every_tool_is_annotated_read_only -x` | ❌ Wave 0 |
| MCP-05 | No module under `app/mcp/` mutates a session or imports insert/update/delete | unit (fast) | `uv run pytest backend/tests/test_mcp_isolation.py -x` | ❌ Wave 0 |
| MCP-05 | A write attempted on a tool's session raises `ReadOnlySQLTransactionError` | integration | `uv run pytest backend/tests/test_mcp_readonly.py -x` | ❌ Wave 0 |
| MCP-06 | An unreachable database leaks no DSN fragment into any tool result | integration | `uv run pytest backend/tests/test_mcp_tools.py -k leaks_nothing -x` | ✅ extend (parametrize over all 12) |
| MCP-06 | No module under `app/mcp/` interpolates an exception into a returned value | unit (fast) | `uv run pytest backend/tests/test_mcp_isolation.py::test_mcp_tools_never_interpolate_an_exception -x` | ❌ Wave 0 |
| MCP-06 | No tool response contains any `Settings.secret_values()` string | integration | `uv run pytest backend/tests/test_secret_redaction.py -k mcp_tool -x` | ✅ extend |
| D-03 | `weeks=N` produces the correct local window under a frozen clock at `Asia/Jakarta` | unit (fast) | `uv run pytest backend/tests/test_mcp_window.py -x` | ❌ Wave 0 |
| D-03 | `weeks` window is computed from the user's LOCAL today, not UTC (17:00Z–24:00Z boundary) | unit (fast) | `uv run pytest backend/tests/test_mcp_window.py::test_evening_utc_belongs_to_next_local_day -x` | ❌ Wave 0 |
| A1 | `@safe_tool` does not erase `inputSchema`/`outputSchema` | unit (fast) | `uv run pytest backend/tests/test_mcp_tool_schemas.py::test_decorated_tools_still_publish_schemas -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `uv run pytest backend/tests -x -q -m "not integration"` — the schema,
  isolation, budget-registry and window tests are all container-free by design, so the
  fastest-feedback loop covers MCP-05, MCP-06 and D-03/D-04 statics.
- **Per wave merge:** `uv run pytest backend/tests -q --cov=backend/app`
- **Phase gate:** full suite green before `/gsd-verify-work`, plus one manual smoke against the
  deployed connector from a real Claude client (Phase 2's `02-DEPLOY-LOG.md` is the template) — the
  in-memory `Client` bypasses auth, so it cannot prove the real path.

### Wave 0 Gaps

- [ ] `backend/tests/test_mcp_tool_schemas.py` — covers MCP-02, MCP-03 (caps), MCP-05 (annotations), A1
- [ ] `backend/tests/test_mcp_tool_budget.py` — covers MCP-03 (D-13)
- [ ] `backend/tests/test_mcp_isolation.py` — covers MCP-05, MCP-06 (static)
- [ ] `backend/tests/test_mcp_readonly.py` — covers MCP-05 (runtime)
- [ ] `backend/tests/test_mcp_window.py` — covers D-03/D-04
- [ ] `backend/tests/conftest.py` — `worst_case_history` fixture (52 weeks × 5 sessions × ~30 templates),
      built on `GoldenBuilder` with the same flush-and-rollback contract
- [ ] Framework install: **none required** — pytest, pytest-asyncio, testcontainers and time-machine
      are all already in the `dev` group

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---|---|---|
| V2 Authentication | no (this phase) | Shipped in Phase 2: WorkOS AuthKit JWT via `AuthKitJWTVerifier`; static bearer as the CLI/rollback path. Phase 6 adds no auth surface |
| V3 Session Management | no | `stateless_http=True`; the 2026-07-28 transport removed protocol-level sessions |
| V4 Access Control | **yes** | `user_id` resolved server-side in `resolve_user_id()`, **never** a tool parameter. Every analytics call passes it keyword-only with no default — the existing ASVS V4 convention. `find_templates_by_title` filters on `user_id` as well as title |
| V5 Input Validation | **yes** | `Annotated[..., Field(ge=..., le=...)]` on every numeric parameter; SQLAlchemy Core expressions with bound parameters only (`func.lower(col) == name`), never string interpolation. Ruff `S` (bandit) already enabled, including `S608` |
| V6 Cryptography | no | No new crypto. `pyjwt[crypto]` handling is Phase 2's and unchanged |
| V7 Error Handling & Logging | **yes** | **The load-bearing category for this phase.** Pattern 8 + Pitfall 3: the SDK's tool-error channel returns `str(e)` to the model and bypasses structlog entirely |
| V8 Data Protection | **yes** | This is health data. MCP-03's compactness is also a data-minimization control: the tool surface returns metrics, never raw table rows, and the "generic run-a-query tool" is explicitly Out of Scope |
| V13 API & Web Service | **yes** | Bounded result sets (D-13 budgets), read-only transaction, no write surface |

### Known Threat Patterns for `mcp 2.0.0` + FastAPI + SQLAlchemy + asyncpg

| Pattern | STRIDE | Standard Mitigation |
|---|---|---|
| Exception text carrying a DSN reaches the model verbatim | Information Disclosure | `@safe_tool` (Pattern 8) + static guard + the port-1 real-connection leak test, parametrized over all 12 tools |
| `user_id` as a tool argument → cross-tenant read | Elevation of Privilege | `resolve_user_id()` server-side; `user_id` absent from every `inputSchema`; assert that in `test_mcp_tool_schemas.py` |
| A future "convenience" write tool | Tampering | `postgresql_readonly=True` transaction (server-enforced) + `readOnlyHint` + static source guard |
| SQL injection via exercise name | Tampering | `func.lower(ExerciseTemplate.title) == bound_param`; Ruff `S608`; the analytics-package `no text()` guard extended to `app/mcp/` |
| Unbounded response exhausting Claude's context / the request budget | Denial of Service | D-13 budgets on the full `CallToolResult`; per-tool item caps; `MAX_ANALYTICS_WINDOW_DAYS` upstream |
| Muscle-mapping bypass returning stale mappings after a user override | Tampering (integrity) | Never join `exercise_muscles` from `app/mcp/`; go through analytics, which goes through `effective_muscles_bulk` |
| Confused deputy — a token minted for another MCP server replayed here | Spoofing | Phase 2: `aud` bound to the Resource Indicator, `options={"require": ["exp","iss","aud"]}`. Unchanged |
| Argument-validation error echoing input | Information Disclosure (low) | Accepted: the echoed value is the model's own argument, never server state. Keep parameters scalar; never accept a pass-through object |

---

## Sources

### Primary (HIGH confidence)

- **Installed `mcp 2.0.0` source, read and executed** in this repo's `.venv` — the strongest evidence
  in this document:
  - `mcp/server/mcpserver/server.py:410-424` — `_handle_call_tool` returns `CallToolResult(content=[TextContent(text=str(e))], is_error=True)`
  - `mcp/server/mcpserver/tools/base.py` — `Tool.from_function` (signature/doc/annotation introspection), `Tool.run` (`ToolError(f"Error executing tool {self.name}: {e}")`)
  - `mcp/server/mcpserver/utilities/func_metadata.py:63,110-144,543-574` — `ArgModelBase.model_config`, `convert_result`, `_convert_to_content` (`indent=2`), `wrap_output`
  - `mcp/server/mcpserver/exceptions.py` — `ToolError`, `ResourceNotFoundError`
  - `inspect.signature(MCPServer.add_tool)` and `ToolAnnotations.model_json_schema()`
- **Live execution probes** (written and run during this research):
  - `ToolAnnotations` round-trip through `Client.list_tools()` → `{"readOnlyHint": true, ...}`
  - `Field(ge=1, le=52)` → `inputSchema` `minimum`/`maximum` + pre-body enforcement + the exact error text
  - Union return → `{"result": ...}` wrapping; single `BaseModel` → unwrapped
  - `Decimal` → JSON string + `anyOf[number, string(pattern), null]` schema
  - DSN-in-exception leak reproduced verbatim
  - Hand-built `CallToolResult` → `outputSchema: null`
  - Full `CallToolResult` byte measurement (5,211 structured / 7,819 text / 14,304 total)
- **Live PostgreSQL probe** — `postgres:18-alpine` container + `sqlalchemy 2.0.52` + `asyncpg 0.31.0`:
  `postgresql_readonly=True` at default isolation sets `transaction_read_only=on`, raises
  `asyncpg.exceptions.ReadOnlySQLTransactionError` on INSERT, and does **not** leak back into the
  pooled connection
- **Byte measurements against real `app.analytics.schemas` models** — every figure in the Response
  Size Budget tables was produced by constructing the actual shipped Pydantic models with realistic
  values and serializing them with `pydantic_core.to_json`
- `https://py.sdk.modelcontextprotocol.io/v2/servers/tools` — annotations are hints, not security controls
- `https://py.sdk.modelcontextprotocol.io/v2/servers/structured-output` — "unions are wrapped in a result object"; "Every tool result includes both text content for the model and structured content for the application"
- `https://py.sdk.modelcontextprotocol.io/v2/migration` — v1→v2 tool exception handling change
- `https://py.sdk.modelcontextprotocol.io/v2/api/mcp/server` — `add_tool` parameter reference
- **This repo's own source**, read in full: `app/mcp/{server,context,auth}.py`, `app/mcp/tools/ping.py`,
  `app/analytics/{schemas,rollup,volume,frequency,progression,records,comparison,bodyweight,recomposition,metadata}.py`,
  `app/core/time.py`, `app/logging.py`, `app/config.py`, `app/main.py`, `app/api/routes/health.py`,
  `app/db/models/{exercise,workout}.py`, `app/cli.py`,
  `backend/tests/{conftest,test_mcp_tools,test_analytics_isolation}.py`, `pyproject.toml`
- `.planning/phases/04-.../04-RESEARCH.md`, `.planning/phases/05-.../05-07-PLAN.md`,
  `05-PATTERNS.md` — live-data cardinalities (119 templates all-time, 42 per 12-week window,
  28 classified) and the "do not touch `core/time.py`" convention

### Secondary (MEDIUM confidence)

- `sqlalchemy/dialects/postgresql/base.py:204-231` — the `postgresql_readonly` docs, including the
  "asyncpg only supports readonly with SERIALIZABLE" note that my live test **contradicted** for the
  default isolation level. Recorded as a documentation-vs-behaviour discrepancy, resolved in favour
  of the observed behaviour (`asyncpg.py:838-846` builds `Connection.transaction(readonly=...)` directly)

### Tertiary (LOW confidence)

- None. Every claim in this document is backed by executed code, read source, or official SDK docs.
  No claim rests on training data alone.

---

## Metadata

**Confidence breakdown:**

| Area | Level | Reason |
|---|---|---|
| SDK behaviour (annotations, schemas, errors, unions, content duplication) | **HIGH** | Executed against the installed 2.0.0, cross-checked against official docs |
| Read-only enforcement | **HIGH** | Executed against a real PostgreSQL 18 + asyncpg, including the pool-leak check |
| Byte measurements | **HIGH** | Real `analytics/schemas.py` models, real serializer. The *item counts* are MEDIUM (A2) |
| Recommended per-tool budgets | **MEDIUM** | Arithmetic on HIGH-confidence measurements, but the worst-case item counts come from prior-phase documents rather than a fresh live-DB query |
| `@safe_tool` decorator viability | **MEDIUM** | Source-read, not executed in decorated form (A1). Mitigated by a required test |
| Architecture / file layout / helper placement | **HIGH** | Grounded in this repo's own established conventions and explicit prior-phase "do not touch" notes |
| `fitness_get_muscle_group_volume` resolution | **LOW** | Open Question 1 — the evidence is HIGH, the *decision* is not made |

**Research date:** 2026-08-31
**Valid until:** 2026-09-30 for the repo-internal findings (they are pinned by `uv.lock`).
The `mcp 2.0.0` findings are valid as long as the pin holds — a bump to 2.1 invalidates every
SDK-behaviour claim in the Pitfalls section and this document should be re-verified by re-running
the probes rather than re-read.
</content>
</invoke>
