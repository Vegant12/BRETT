# Phase 6: MCP Tools - Context

**Gathered:** 2026-08-31
**Status:** Ready for planning

<domain>
## Phase Boundary

Claude can reach every analytic Phase 4/5 already computes through purpose-built, read-only MCP
tools that return compact structured JSON instead of raw data. This phase composes existing
analytics functions into a tool surface — it does not add new analytics, does not touch auth
(Phase 2 already proved WorkOS OAuth end-to-end), and does not add rate limiting or hardening
(Phase 7).

**Explicitly NOT this phase:** New analytics calculations, auth mechanism changes, rate limiting,
backup/restore, the coaching instructions document (all Phase 7). Apple Health-dependent blueprint
tools (`fitness_get_body_composition`, `fitness_get_activity_summary`,
`fitness_get_recovery_summary`) are out of scope — no HealthKit data exists to back them; deferred
to milestone 2 alongside the iOS app.

</domain>

<decisions>
## Implementation Decisions

### Exercise Identification (affects `fitness_get_exercise_progression`, `fitness_get_personal_records`)
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

### Time-Window Parameters (affects `fitness_get_weekly_volume`, `fitness_get_muscle_group_volume`, `fitness_get_training_frequency`, `fitness_get_exercise_progression`, `fitness_get_personal_records`)
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

### Training Summary Composition
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

### Recent Workouts & Single-Workout Detail
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
  ROADMAP.md's Phase 6 success criterion #1 text does not name among its 11 (it lists "recent
  workouts, training summary, weekly volume, muscle-group volume, exercise progression, personal
  records, plateaus, training frequency, body-weight trend, recomposition status, and period
  comparison"). **This is not scope creep** — CLAUDE.md states the blueprint is the authoritative
  source for "MCP tool names" and blueprint §29 explicitly lists `fitness_get_workout` alongside
  `fitness_get_recent_workouts`. Do not treat its absence from the ROADMAP success-criteria
  sentence as a reason to drop it or re-litigate it at planning time.
- **D-12:** `fitness_get_workout` is keyed by the **Hevy external workout id** — the same id
  `fitness_get_recent_workouts` echoes per item — not a calendar date. This makes the natural
  flow "list recent workouts, then fetch one by its id" unambiguous; a date-keyed lookup would
  need a same-day-multiple-workouts policy that an id-keyed one avoids entirely.

### Response Size Budget (MCP-03)
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

### Folded Todos
None — `todo match-phase` returned zero matches for Phase 6.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` §"Phase 6: MCP Tools" — goal, 5 success criteria, requirements
  (MCP-02, MCP-03, MCP-05, MCP-06), depends on Phase 2 + Phase 5
- `.planning/REQUIREMENTS.md` — MCP-02 (tool coverage list), MCP-03 (compact/bounded JSON,
  never raw DB access), MCP-05 (read-only, no write surface), MCP-06 (no secrets in tool
  responses)
- `.planning/PROJECT.md` §"Active" — the literal tool-name list this phase's "Active"
  requirement bullet already commits to; §"Core Value" — the two questions
  (`fitness_get_training_summary` / D-08 is built to answer these directly)
- `BRETT blueprint.md` §29 "MCP Server" — the full tool list including `fitness_get_workout`
  (D-11) and the three Apple-Health-dependent tools this phase explicitly excludes
- `BRETT blueprint.md` §30 "Tool Design" — `weeks=N` / explicit-date parameter examples that
  D-03/D-06 are built against; "do not return huge amounts of raw data unless explicitly
  requested" (the basis for D-09's workout-summary-not-full-detail choice)
- `BRETT blueprint.md` §31 "MCP Read/Write Permissions" — the read-only requirement MCP-05
  formalizes

### MCP scaffolding already built (Phase 2 — reuse, do not rebuild)
- `backend/app/mcp/server.py` — `MCPServer` assembly, `TransportSecuritySettings`,
  `mcp.add_tool()` registration pattern; every Phase 6 tool registers here the same way
  `fitness_ping` does
- `backend/app/mcp/context.py` — `AppContext` dataclass (currently just `sessionmaker`); every
  real tool reads `ctx.request_context.lifespan_context.sessionmaker` to open a session, same as
  `fitness_ping`
- `backend/app/mcp/tools/ping.py` — the one existing tool; the return-a-`BaseModel`
  auto-`outputSchema` pattern and the `Context[AppContext]` annotation requirement (an
  unannotated `ctx` breaks schema validation) apply to every new tool
- `CLAUDE.md` §"The FastAPI + MCP Integration Pattern" — `ctx.request_context.lifespan_context`
  DI pattern, "MCP should call internal service functions rather than making HTTP requests back
  into the same application" (why every tool calls `app.analytics.*` directly, in-process)
- `.planning/phases/02-deploy-connector-auth-spike/02-CONTEXT.md` D-05/D-08 — records that the
  scaffolding built in Phase 2 was deliberately the *real* structure, not disposable; this phase
  only adds tools to it

### Analytics layer being composed (Phase 4/5 — reuse, do not re-derive)
- `backend/app/analytics/schemas.py` — every return type (`WeeklyVolumeResult`,
  `MuscleGroupVolumeResult`, `TrainingFrequencyResult`, `ExerciseProgressionResult`,
  `PlateauReport`, `PersonalRecordsResult`, `PeriodComparisonResult`, `BodyWeightTrendResult`,
  `RecompositionResult`) — tool response models compose these, they do not reshape them
- `backend/app/analytics/volume.py` — `get_weekly_volume`, `get_muscle_group_volume`
  (`start_day`/`end_day` keyword-only, `user_id` no default — ASVS V4)
- `backend/app/analytics/frequency.py` — `get_training_frequency` (same signature shape)
- `backend/app/analytics/progression.py` — `get_exercise_progression` (needs
  `exercise_template_external_id` — D-01's resolution target), `get_plateaus` (already takes
  `lookback_weeks`), `get_exercise_trends`
- `backend/app/analytics/records.py` — `get_personal_records` (needs
  `exercise_template_external_id`)
- `backend/app/analytics/comparison.py` — `compare_periods` (explicit dates both periods, D-06)
- `backend/app/analytics/bodyweight.py` — `get_body_weight_trend` (no date args, D-07)
- `backend/app/analytics/recomposition.py` — `get_recomposition_status` (no date args, D-07)
- `backend/app/db/models/exercise.py` — `ExerciseTemplate.title` / `.external_id` — the columns
  D-01/D-02's name lookup queries against

### Auth (already resolved in Phase 2 — not this phase's concern)
- `.planning/PROJECT.md` Key Decisions — MCP connector auth = OAuth 2.1 via WorkOS AuthKit,
  resource-server-only; static bearer remains the Claude Code CLI / rollback path

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `backend/app/mcp/server.py` / `context.py` / `tools/ping.py` — the entire tool-registration
  scaffolding (lifespan, `AppContext`, `mcp.add_tool()`) is built and proven; this phase adds
  tools to it, no new plumbing
- Every analytics function listed above — pure composition, no new SQL or calculation logic
  needed anywhere in this phase per CLAUDE.md's "pandas/numpy... SQL aggregates + plain Python"
  rule (same spirit applies to MCP tools: compose, don't recompute)

### Established Patterns
- `user_id` keyword-only, no default, on every analytics function (ASVS V4) — every MCP tool
  must supply it explicitly; there is currently exactly one user (Phase 1's seeded default user),
  but the pattern must not be bypassed
- Structured Pydantic `BaseModel` return → SDK auto-populates `outputSchema`/`structuredContent`
  (established in `ping.py`) — every new tool follows this, never returns a bare dict
- Bare `except` + degrade-to-coarse-status for external/DB failures (`health.py`, `ping.py`) —
  the same "detail to log, coarse status to caller" split applies to any new tool's failure path
- `structlog` + secret redaction already wired (`FOUND-05`) — MCP-06 is satisfied by routing any
  new logging through the existing `log = structlog.get_logger()` pattern, not a new mechanism

### Integration Points
- New tool files go in `backend/app/mcp/tools/`, registered in `server.py` via
  `mcp.add_tool(...)` the same way `fitness_ping` is registered — no new mount point or wiring
  needed
- The `weeks` → `start_day`/`end_day` conversion (D-03) is new code with no existing home yet —
  likely a small helper near the MCP tools rather than inside `app/analytics/` (analytics stays
  pure/explicit-date per its existing signatures) or `app/core/time.py` (Claude's discretion,
  informed by where `local_day`/`utc_now` already live)

</code_context>

<specifics>
## Specific Ideas

No further specific ideas beyond the decisions above — this was a scope-definition discussion
(parameter conventions, tool composition, size enforcement) rather than a source of new freeform
requirements.

</specifics>

<deferred>
## Deferred Ideas

- `fitness_get_body_composition`, `fitness_get_activity_summary`, `fitness_get_recovery_summary`
  (blueprint §29) — depend on Apple Health / HealthKit data that does not exist yet (no synced
  source). Deferred to milestone 2 alongside the iOS HealthKit app, per PROJECT.md's Out of Scope
  section — not re-litigated in this discussion.
- Rate limiting on the MCP endpoint — explicitly Phase 7 (Production Hardening), already noted as
  deferred in Phase 2's context; not re-raised here.

### Reviewed Todos (not folded)
None — `todo match-phase` returned zero pending todos for Phase 6.

</deferred>

---

*Phase: 06-mcp-tools*
*Context gathered: 2026-08-31*
