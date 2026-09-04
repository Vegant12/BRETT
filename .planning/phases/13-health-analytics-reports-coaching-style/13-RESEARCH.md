# Phase 13: Health Analytics, Reports & Coaching Style - Research

**Researched:** 2026-09-04
**Domain:** MCP composition-tool design (activity/nutrition trend analytics, report composition,
closed-period date math, coaching-document budgeting), plus an external-dependency spike
(Claude scheduled tasks + custom MCP connectors)
**Confidence:** MEDIUM-HIGH — code-level findings are HIGH (read directly), the RPT-03 client
reliability finding is MEDIUM-HIGH (multiple independent, recent, unresolved reports; no live
reproduction possible from this session), and the D-06 nutrition-coverage finding is MEDIUM
(real historical numbers exist, but live-era coverage could not be re-queried this session — see
below)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Report Composition & Anchoring**
- **D-01:** Reports use closed-period anchoring for their training/strength/measurement
  figures (Monday–Sunday for the weekly report, calendar month for the monthly one), with the
  existing anchored-on-today recomposition verdict carried alongside, clearly labelled as a
  different anchor from the closed-period numbers. Do NOT add an `anchor_day` parameter to
  `get_body_weight_trend`/`get_recomposition_status`. Matches ARCHITECTURE.md's option (a).
- **D-02:** Report body reuses `fitness_get_training_summary`'s selected-field spine (weekly
  volume, per-muscle rollup, recomposition status) as its base, and adds NARROW extras: PR and
  plateau *highlights* (not the full lists), a body-measurement trend summary, a nutrition trend
  summary, and active training-program context. Narrow extras over full composition.
- **D-03:** No backend-computed "recommendations" field. The report tool returns composed DATA
  only. Claude synthesizes recommendation text from the returned data and the coaching doc.
- **D-04:** One composer function serves both report tools; a period/window parameter
  distinguishes weekly (the current week) from monthly (the current calendar month) — same
  sections in both, not a different emphasis per period.
- **D-14:** `fitness_get_monthly_report`'s JSON response carries one additional field: a
  markdown-formatted narrative string, generated server-side by a deterministic template (not
  free-form/AI-authored text) that restates the SAME composed data already in the structured
  fields — no recommendation language. `fitness_get_weekly_report` does NOT get this field.

**Activity & Nutrition Trend Design**
- **D-05:** Activity trend analytics (steps, active/basal energy, distance, flights) use
  rolling 7/14/30-day averages + rate of change, following `bodyweight.py`'s shape — NOT
  `body_measurements.py`'s latest-vs-90-days shape.
- **D-06:** Nutrition trend analytics (calories + 6 macros) use the SAME rolling-average design
  as activity. Explicit research gap: the exact per-window coverage floors must be checked
  against real synced nutrition data.
- **D-07:** Activity gets its own dedicated MCP tool (`fitness_get_activity_trend`).
- **D-08:** The nutrition-trend tool returns ONE response with all 7 values always — no
  metric-selector parameter.

**Coaching Doc Rewrite Strategy**
- **D-09:** `docs/coaching-instructions.md` is rewritten from scratch against the final v2.0
  tool registry — not incrementally edited — sequenced last. Current doc is 7,934 of the hard
  9,000-character ceiling.
- **D-10:** If the rewritten doc still doesn't fit under 9,000 characters, moving overflow into
  the server's `_INSTRUCTIONS` string is an acceptable LAST-RESORT belt — only for genuinely
  optional context. Do not raise `_PASTE_CEILING_CHARS`.
- **D-11:** Conciseness (COACH-02) via: (a) explicit answer-length guidance, (b) tightened
  tool-mapping table phrasing, (c) a shortened "Example questions" section.

**Scheduled-Task Verification & Fallback**
- **D-12:** The RPT-03 scheduled-task spike runs on Claude Desktop, human-gated, only the user
  can perform it.
- **D-13:** The documented community workaround (subagent-delegation preamble) is added to
  `docs/coaching-instructions.md` ONLY IF the live spike actually reproduces the failure — not
  proactively.

### Claude's Discretion
- Partial data availability in reports — follow the established `safe_tool`/`data_available`
  degradation pattern `fitness_get_training_summary` already uses.
- Report freshness envelope's exact resource list — follow the existing `build_freshness` pairs
  pattern and include every resource the report actually touches.
- Whether the report's activity/nutrition sections share the report's own closed-period window
  or use their own independent rolling windows — avoid two sections of one report disagreeing
  about what "this week" means.
- Exact `MAX_REPORT_WEEKS`/`MAX_REPORT_*` budget cap numbers — measured against the real
  composed payload during planning/implementation.
- Exact markdown narrative template headings/structure (D-14) — content is fixed, formatting is
  not.
- Nutrition coverage floors (D-06) — the specific per-window measured-day thresholds.

### Deferred Ideas (OUT OF SCOPE)
- BRETT writing an actual `.md` file to disk/storage — declined in favor of a markdown string
  field in the existing JSON response.
- Structured backend-computed recommendation flags — declined in favor of Claude synthesizing
  recommendations from returned data.
- An `anchor_day` parameter on `get_body_weight_trend`/`get_recomposition_status` — declined.
- A metric-selector parameter on the nutrition-trend tool — declined.
- Different section emphasis for the monthly report vs. the weekly one — declined.
- Proactively adding the scheduled-task subagent-delegation workaround regardless of spike
  outcome — declined.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| HEALTH-12 | Activity trends (steps, active/basal energy, distance) over 7/14/30-day windows, following the existing trend-analytics pattern | `bodyweight.py` read in full as the exact pattern to replicate; `METRIC_REGISTRY` confirms the 5 activity metric names/units; new `analytics/health.py` module and `fitness_get_activity_trend` tool are the deliverable |
| NUTR-04 | Nutrition trends (daily/weekly average calories and macros) over configurable windows | Same `analytics/health.py` module; D-06 coverage-floor gap addressed below with real (partial) production numbers plus an exact re-query script for the remainder |
| NUTR-06 | New read-only MCP tool exposing nutrition summary/trend data, one-tool-per-slice pattern | `fitness_get_nutrition_trend` (name TBD by planner) follows `body.py`'s tool-wrapper pattern exactly |
| RPT-01 | Weekly report MCP tool: volume, strength, weight/measurement, nutrition, trends, recommendations | Composer design fully mapped against `summary.py`/`_common.py`; PR-highlights gap flagged (see Pitfalls) |
| RPT-02 | Monthly report MCP tool, same coverage, normalized for the longer window | Same composer, `weeks=1`-equivalent month window; D-04's "one composer" is directly supported by existing `window_from_weeks` design already generalizing this way |
| RPT-03 | Report tools verified against a real Claude scheduled-task run; documented fallback if broken | Current (2026-09-04) external evidence gathered below — still broken, still "not planned," across issues filed as late as June 2026 |
| COACH-02 | `docs/coaching-instructions.md` revised for concision | Exact current length (7,934, confirmed live) and structure read in full; rewrite budget math below |
| COACH-03 | `docs/coaching-instructions.md` documents the v2.0 tools | Current registry (16 tools) read in full; drift-guard test read in full; 4 new tools will bring the total to 20 |
</phase_requirements>

## Summary

This phase is almost entirely composition and response-shaping over analytics functions that
already exist, plus two genuinely new pieces of work: (1) an activity/nutrition trend module
that copies `bodyweight.py`'s rolling-average shape verbatim, and (2) a documented, human-gated
spike into a client capability (Claude scheduled tasks + custom MCP connectors) that has been
reported broken, in essentially the same way, in every GitHub issue found from April 2026 through
June 2026, with zero evidence of a fix as of today.

The single most important non-obvious finding: **`get_personal_records` requires a mandatory
`exercise_template_external_id` and has no cross-exercise mode.** D-02's "PR highlights" narrow
extra therefore cannot be built by calling the existing PR analytics function in a loop without
reproducing exactly the query-fan-out problem PITFALLS #18 warns against — it needs either a new,
purpose-built cross-exercise scan (new analytics arithmetic, which belongs in
`analytics/records.py`, not `reports.py`) or a redefinition of "PR highlights" to reuse data
`get_plateaus` already computes cross-exercise. Plateau highlights have no such problem —
`get_plateaus` is already cross-exercise and needs only filtering + `truncate()`.

The second load-bearing finding: **the weekly report's "closed period" is free.**
`_common.py::window_from_weeks(weeks=1)` already returns exactly "Monday of this week through
today" — the same closed-period-anchored, calendar-boundary window D-01/D-04 describe. No new
date-math is needed for the weekly report. The monthly report needs one new helper
(first-of-calendar-month → today), which belongs in `core/time.py` beside `local_week_start`,
matching that module's existing convention that "every day/week grouping in this project routes
through this module."

Real production data (captured 2026-09-03 in `docs/health-auto-export-setup.md`, confirmed
un-changed by a review of the file this session) shows nutrition logging is historically sparse
(53-54 distinct days out of ~1,644 calendar days, ≈3.3%) but the two most-recent live-webhook
days (2026-09-02, 2026-09-03) show near-complete macro logging (12/12 and 11/12 metrics
respectively). This session could not query the live database directly (network egress to the
production Neon instance was blocked by the sandbox's command classifier on every attempted
vector — `psql`, `asyncpg`, even a bare `gcloud secrets access`); the exact 7/14/30-day
measured-day counts D-06 asks for must be re-queried at planning/implementation time using the
exact SQL provided below, the same way BODY-05 measured real circumference coverage.

**Primary recommendation:** Build the report composer as pure composition over existing
analytics functions plus the two new `analytics/health.py` functions; do not add new arithmetic
to `analytics/reports.py`. Spike RPT-03 first, exactly as ROADMAP.md's planning note says, and
budget the coaching-doc rewrite as a from-scratch draft against the *final* (20-tool) registry,
not an edit of the current 7,934-character file.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Activity/nutrition rolling averages | API / Backend (`app/analytics/health.py`) | Database (`health_daily_metrics`) | Pure SQL-adjacent aggregation over an existing table, same tier as `bodyweight.py` |
| Report composition (volume, strength, measurement, nutrition, program) | API / Backend (`app/analytics/reports.py`) | — | Composition only, calling existing analytics entry points inside one read-only transaction, same tier as `recomposition.py` |
| MCP tool surface (`fitness_get_*_trend`, `fitness_get_*_report`) | API / Backend (`app/mcp/tools/`) | — | Thin wrapper translating analytics results into MCP response schemas, same tier as every existing tool |
| Markdown narrative (D-14) | API / Backend (deterministic template function) | — | Server-side, pure, testable — same tier as `backfill.py::format_summary`, NOT a client/LLM-generated artifact |
| Coaching persona/instructions | Client (Claude Project custom instructions) | API / Backend (`_INSTRUCTIONS` string, last-resort belt) | The document is pasted into a client-side surface BRETT does not control; the server only carries a short belt-and-braces string |
| Scheduled-task delivery | Client (Claude's own scheduling feature) | — | Explicitly out of scope for BRETT to build (PROJECT.md); the server exposes ordinary on-demand tools only |

## Standard Stack

No new third-party dependencies. This phase is 100% internal composition over the existing
stack (FastAPI, SQLAlchemy 2.x async, Pydantic v2, `mcp` 2.0.0). No package versions to verify.

### Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Weekly closed-period window | A new "this week" date helper | `_common.py::window_from_weeks(weeks=1)` | Already returns Monday-of-this-week → today; this is D-01/D-04's exact window, verified by reading `week_window` |
| Rolling 7/14/30-day averages + floors | A new averaging/coverage scheme for activity/nutrition | Copy `bodyweight.py`'s `_window_average` + `metadata.py`'s `build_measurement_coverage`/`MEASURED_DAY_FLOORS` pattern | D-05/D-06 lock this shape; it is a proven, tested pattern already carrying the exact independent-per-window-floor semantics HEALTH-12/NUTR-04 need |
| Markdown narrative generation | A templating library (Jinja etc.) | A pure `build_narrative(...) -> str` function, f-strings and `\n.join(...)`, same style as `backfill.py::format_summary` | No templating library exists anywhere in this codebase; `format_summary` is the direct, already-tested precedent for "pure function turns a result object into human-readable lines" |
| Cross-exercise plateau highlights | New arithmetic in `reports.py` | `get_plateaus()` (already cross-exercise) + `truncate()` | `get_plateaus` already scans every exercise; the report only needs to filter `plateaued=True` and cap the list |
| Response byte budgeting | A guess at `MAX_REPORT_*` | The `test_mcp_tool_budget.py` methodology: `model_dump_json` on the FULL `CallToolResult` (structured + text, not structured alone), measured at the worst-case shape against the SAME synthetic `worst_case_history` fixture already in `conftest.py` | This methodology needs no live database access (contrary to D-06's coverage-floor gap) — it is exactly reproducible in this session's sandbox and should be a Wave 0/plan task, not a research estimate |

**Key insight:** every "new" capability in this phase either already exists one tier down
(`window_from_weeks`, `get_plateaus`) or has a byte-for-byte precedent already in the codebase
(`format_summary`, `bodyweight.py`). The phase's actual new-code surface is small: one analytics
module (`health.py`), one composition module (`reports.py`), a handful of MCP wrappers, and a
rewritten doc.

## Architecture Patterns

### System Architecture Diagram

```
Claude (Desktop / Web / scheduled task)
        │  MCP tool call (Streamable HTTP, stateless)
        ▼
mcp/tools/{health.py, reports.py}        ← NEW thin wrappers (this phase)
mcp/tools/{summary,body,records,progression,programs}.py   ← EXISTING, reused verbatim
        │  read_only_session (ONE transaction per call)
        ▼
analytics/reports.py   ← NEW, composition ONLY, no arithmetic
        │
        ├─▶ analytics/volume.py           (get_weekly_volume, get_muscle_group_volume)   EXISTING
        ├─▶ analytics/recomposition.py     (get_recomposition_status — anchored on TODAY) EXISTING
        ├─▶ analytics/progression.py       (get_plateaus — cross-exercise)                EXISTING
        ├─▶ analytics/records.py           (PR highlights — see Pitfall below)            EXISTING + gap
        ├─▶ analytics/body_measurements.py (get_body_measurement_trend, per metric)        EXISTING
        ├─▶ analytics/health.py            (get_activity_trend, get_nutrition_trend)       NEW (this phase)
        ├─▶ db/repositories/programs.py    (active program context)                        EXISTING
        └─▶ analytics/metadata.py          (build_freshness over ALL 5 resource pairs)     EXISTING, extend

analytics/health.py                        ← NEW, copies bodyweight.py's shape
        │
        ▼
db/models/health.py::HealthDailyMetric     ← EXISTING (Phase 8/9), 12 metrics, one row per
                                              (user, source, metric, source_name, local_day)
```

A reader can trace "Claude asks for the weekly report" → one MCP tool call → one read-only
transaction → `analytics/reports.py` composing 5-7 existing analytics calls plus 2 new ones →
one structured JSON response, by following the arrows top to bottom.

### Recommended Project Structure

```
backend/app/
├── analytics/
│   ├── health.py          # NEW — get_activity_trend, get_nutrition_trend (bodyweight.py's shape)
│   └── reports.py         # NEW — compose_report(period=WEEKLY|MONTHLY) → ReportResult
├── mcp/tools/
│   ├── health.py          # NEW — fitness_get_activity_trend, fitness_get_nutrition_trend
│   └── reports.py         # NEW — fitness_get_weekly_report, fitness_get_monthly_report
├── core/
│   └── time.py            # EXTEND — add a month-boundary helper beside local_week_start
docs/
└── coaching-instructions.md   # REWRITTEN from scratch (D-09)
```

### Pattern 1: Weekly report's window is free — reuse `window_from_weeks(weeks=1)`

**What:** `_common.py::week_window(today=..., weeks=1)` computes
`this_monday = today - timedelta(days=today.weekday())`, then returns `(this_monday, today)`.
For `weeks=1` that is exactly "Monday of the current week through today" — a closed-period,
calendar-boundary window, not a rolling trailing-7-days window (which `get_body_weight_trend`
already uses for something else).

**When to use:** The weekly report's volume/frequency/PR-window figures.

**Example:**
```python
# Source: backend/app/mcp/tools/_common.py:183-244 (read directly this session)
start_day, end_day = await window_from_weeks(session, user_id=user, weeks=1)
# start_day == Monday of the current local week
# end_day == today (local)
```

### Pattern 2: Monthly report needs one new helper — extend `core/time.py`

**What:** No calendar-month boundary helper exists yet. `core/time.py`'s own docstring states
"every day/week grouping in this project routes through this module" — a month helper belongs
here, not ad-hoc in `reports.py`.

**When to use:** The monthly report's closed-period window.

**Example (recommended shape, not yet built):**
```python
# Mirrors local_week_start's signature and one-line body exactly.
def local_month_start(ts: dt.datetime, tz: str) -> dt.date:
    """First calendar day of the user's local month."""
    day = local_day(ts, tz)
    return day.replace(day=1)
```
Then `analytics/reports.py` computes `start_day = local_month_start(...)`, `end_day = today` —
same closed-period-anchored, "current calendar month so far" shape `window_from_weeks(weeks=1)`
already gives the weekly report. **One composer, two window strategies, same shape of call** —
this is what makes D-04's "one composer function" genuinely achievable rather than aspirational.

### Pattern 3: `get_recomposition_status` stays anchored on today, carried BESIDE the closed-period figures

**What:** `get_recomposition_status(session, user_id=user)` takes **no window argument at all** —
confirmed by reading `recomposition.py` in full. It always anchors on today over its own fixed
12-week lookback. D-01 already forbids adding an `anchor_day` parameter to it.

**When to use:** Both reports call it exactly once, unmodified, and label the result clearly as
"as of today" distinct from the closed-period figures beside it.

**Example:**
```python
# Source: backend/app/analytics/recomposition.py:577-663 (read directly this session)
recomposition = await get_recomposition_status(session, user_id=user)
# recomposition.status, .disclaimer, .weight_trend, .progression_signal — all as-of-today,
# independent of whether the report is "weekly" or "monthly".
```

### Pattern 4: Deterministic narrative — copy `format_summary`'s shape, not a template engine

**What:** `backend/app/integrations/health_auto_export/backfill.py::format_summary` (read in
full this session) is a pure function taking a result object and returning `list[str]`, built
entirely with f-strings and explicit conditionals — no Jinja, no string.Template, no markdown
library anywhere in this codebase (`grep -rln "jinja\|Template" backend/app/` found none
relevant).

**When to use:** D-14's monthly-report narrative field.

**Example (shape, not literal code):**
```python
def build_narrative(report: ReportResult) -> str:
    """D-14: deterministic markdown restating the SAME fields, no new judgment."""
    lines = [f"# Monthly Report — {report.window_start} to {report.window_end}", ""]
    lines.append(f"## Training\n{report.volume_by_week[-1].hard_sets} hard sets this week...")
    # ... one section per structured field group, values only, no editorializing
    return "\n".join(lines)
```

### Anti-Patterns to Avoid

- **Looping `get_personal_records` per exercise to build "PR highlights":** Reproduces exactly
  the query-fan-out problem PITFALLS #18 warns about (a service with `MIN_INSTANCES=0` and a
  pooled connection budget). See the Pitfalls section below for the two real alternatives.
- **Calling `get_body_measurement_trend` once per one of the 16 `BodyMeasurementMetric` values:**
  16 extra queries for a "narrow extra" is not narrow. Real production data shows only
  `waist_cm` has any recent coverage (15/123 live rows per BODY-05's research; the other 15 are
  effectively always `insufficient_data`) — pick a small, deliberate subset (or just `waist_cm`)
  rather than iterating the whole enum.
- **Treating "closed period" as "the most recently COMPLETED week/month":** D-04's own wording
  ("the current week" / "the current calendar month") and the free reuse of
  `window_from_weeks(weeks=1)` both point at "this week/month so far, through today" — NOT last
  week/last month. Confirm this reading explicitly in the plan; it is a real ambiguity between
  ARCHITECTURE.md's "the completed week" phrasing and CONTEXT.md's D-04 paraphrase, and the two
  read differently. Recommend following D-04's literal text and the free `window_from_weeks`
  reuse (current period, in progress) since it costs nothing and matches every other "anchored"
  tool's convention of ending on today.
- **Fanning the nutrition tool's coverage check across metrics separately without checking
  correlation first:** real backfill data shows `sodium` missing on a day the other 5 macros
  were present (2026-09-03) — macros are NOT perfectly co-logged. Do not assume one shared
  measured-day count covers all 7 fields; verify per-metric independence the way `body_measurements.py`
  already does for its 16 columns, or explicitly justify using one shared anchor metric (see
  Nutrition Coverage below).

## Don't Hand-Roll

(See table above under Standard Stack — kept together per this phase's "everything already
exists one layer down" character.)

## Common Pitfalls

### Pitfall 1: `get_personal_records` has no cross-exercise mode — "PR highlights" is not free

**What goes wrong:** D-02 asks for "PR and plateau highlights." Plateau highlights are free
(`get_plateaus` is already cross-exercise). PR highlights are NOT: reading
`backend/app/analytics/records.py:107-115` this session confirms
`get_personal_records(session, *, user_id, exercise_template_external_id, start_day, end_day)`
takes a **mandatory single exercise**. There is no "PRs across every exercise in a window"
analytics function anywhere in the codebase today. A report that wants "PR highlights" would
naively need to loop over every exercise trained in the window and call this per-exercise
function once each — for a typical training week that is 10-25+ extra queries, directly
reproducing PITFALLS #18's exact warning about query fan-out on a `MIN_INSTANCES=0` service.

**Why it happens:** `get_personal_records`'s per-exercise design is correct for its own tool
(`fitness_get_personal_records`, always called with a named exercise) and was never designed to
serve a cross-exercise summary use case.

**How to avoid — two real options, both worth putting in front of the planner:**
1. **Build a small, new, purpose-built cross-exercise scan** in `analytics/records.py` (new
   arithmetic, correctly homed there rather than in `reports.py`, matching "reports.py owns
   composition, never arithmetic") that finds records achieved WITHIN the report's window in
   one aggregate query, modeled on how `get_plateaus` already avoids the per-exercise-loop
   problem for its own cross-exercise scan.
2. **Redefine "PR highlights" to reuse `get_plateaus`' already-cross-exercise
   `historical_best_kg`/`recent_performance_kg` fields** as an approximate "new best this
   window" signal (e.g., `recent_performance_kg >= historical_best_kg` for an exercise with a
   qualifying session in the window) — zero new queries, but it is an e1RM/weight-based
   approximation, not the literal `PersonalRecordType` enum (which also covers max reps and
   session volume).

Option 1 is more correct against PROG-04's actual PR semantics; option 2 is cheaper and reuses
data already being fetched for the plateau highlights. This is a real design decision the
planner must make explicitly, not one this research resolves.

**Warning signs:** A report plan that has `fitness_get_personal_records` called inside a loop
over `frequency.exercises` or similar.

**Phase to address:** This phase, in the plan for the report composer.

---

### Pitfall 2: Nutrition macros are not perfectly co-logged — one shared coverage flag may misrepresent per-macro sparsity

**What goes wrong:** Real production data (`docs/health-auto-export-setup.md` §"2026-09-03 —
first real device export", read this session) shows: full day 2026-09-02 had all 12 registry
metrics present, but partial day 2026-09-03 had 11 of 12 — `sodium` had not been logged yet
that day. If `get_nutrition_trend` computes ONE shared `measured_days` count (e.g., anchored on
`dietary_energy`/calories, the metric most likely to be present whenever any food was logged)
and applies it uniformly to all 7 returned averages, a macro that is logged less consistently
than calories (sodium, in the one real example available) would report a "trustworthy" average
built from fewer real observations than the shared flag implies.

**Why it happens:** D-08 already decided the *tool* returns one response with all 7 values
always (no per-metric selector) — it is easy to read that as "therefore one shared coverage
flag too," which is a narrower decision D-08 did not actually make.

**How to avoid:** Compute `measured_days` and its floor-check independently per metric,
extending `body_measurements.py`'s existing per-column independence rather than `bodyweight.py`'s
single-tracked-value shape — D-15's own stated philosophy ("each window has its OWN floor, and
they are independent") generalizes naturally to "each metric has its own floor," and is cheap:
all 7 metrics can still be fetched in ONE query (`WHERE metric IN (7 names)`) and folded 7 ways
in Python, exactly like `bodyweight.py`'s "one fetch, folded five ways" `_FETCH_SPAN_DAYS`
pattern.

**Warning signs:** A `NutritionTrendResult` with one `coverage` field instead of one per metric
(or a documented, deliberate justification for why one shared anchor metric is sufficient).

**Phase to address:** This phase, `analytics/health.py`.

---

### Pitfall 3: Nutrition coverage floors cannot be finalized from data available in this research session — re-query before locking `MEASURED_DAY_FLOORS`

**What goes wrong:** D-06 explicitly asks for real per-window logging-day counts, the way
BODY-05 measured real circumference coverage before committing to its shape. This session could
**not** query the live Neon database directly — every attempted connection vector (`psql`,
`asyncpg` via the project's own venv, even a bare `gcloud secrets versions access`) was blocked
by the sandbox's command-permission classifier as a network-egress action, independent of
credentials or tool choice. What IS available, from `docs/health-auto-export-setup.md`'s already
-committed, already-verified production figures:

| Era | Span | Nutrition-metric rows observed |
|---|---|---|
| Historical backfill (`export.xml`) | 2022-03-10 .. 2026-08-26 (≈1,644 days) | `dietary_energy` 54, `protein` 54, `total_fat` 54, `dietary_sugar` 54, `carbohydrates` 53, `fiber` 53, `sodium` 53 — i.e. ≈53-54 distinct logged days total across 4.5 years (≈3.3%) |
| Live webhook (first 2 days) | 2026-09-02, 2026-09-03 | 2026-09-02: all 12 registry metrics present (full nutrition). 2026-09-03: 11 of 12 (sodium absent that day) |

Historically, nutrition logging is dramatically sparser than `waist_cm` — the metric BODY-05
already found too sparse (15/123 ≈ 12%) for `bodyweight.py`'s rolling-average floors, which is
why BODY-05 used a completely different (latest-vs-earliest) shape. Nutrition's historical rate
(≈3.3%) is roughly a quarter of that. **However**, D-05/D-06 already lock the rolling-average
shape for nutrition (not a BODY-05-style redesign) — this finding is not a case for relitigating
the shape, only a strong signal that `bodyweight.py`'s literal floors (3-of-7, 5-of-14, 10-of-30)
will likely return `insufficient_data` very often at launch, similar to how
`get_body_weight_trend` already does on today's live data by design ("`insufficient_data` is the
expected answer on today's live data, and that is correct"). The two live-webhook days suggest
the user may have started a genuinely more consistent logging habit specifically to support this
project — but n=2 days is mathematically insufficient to project a 7/14/30-day rate from.

**Why it happens:** The live-webhook era (started 2026-09-02, per Phase 8/9's completed work) is
only 2-3 calendar days old as of this research session (2026-09-04); real per-window measurement
needs the window to have actually elapsed.

**How to avoid:** Re-run this exact query against production at plan/implementation time (when
more live-era days will have accumulated), following the same operational discipline
`docs/health-auto-export-setup.md`'s existing "Afterwards" queries already establish (confirmed
production `DATABASE_URL`, never a stale/wrong shell target — three prior incidents this
milestone are logged in `.planning/STATE.md` for exactly this mistake):

```sql
-- Real per-window nutrition logging-day counts, run against the CONFIRMED production DATABASE_URL.
SELECT
  metric,
  count(DISTINCT local_day) FILTER (WHERE local_day >= current_date - interval '6 days')  AS days_last_7,
  count(DISTINCT local_day) FILTER (WHERE local_day >= current_date - interval '13 days') AS days_last_14,
  count(DISTINCT local_day) FILTER (WHERE local_day >= current_date - interval '29 days') AS days_last_30
FROM health_daily_metrics
WHERE source = 'apple_health'
  AND metric IN ('dietary_energy','protein','carbohydrates','total_fat','fiber','dietary_sugar','sodium')
GROUP BY metric
ORDER BY metric;
```

Until that re-query happens, the safe default is to REUSE `bodyweight.py`'s exact floors
(`MEASURED_DAY_FLOORS`-style: 3/7, 5/14, 10/30) as the nutrition starting point — it keeps one
set of floor semantics in the codebase rather than inventing unjustified numbers, and an
`insufficient_data` response is an honest, already-precedented outcome, not a bug, if the real
numbers turn out to still be sparse.

**Warning signs:** A plan that hardcodes new, unexplained floor numbers for nutrition without
citing a query result, or that assumes the two known live days generalize to a stable weekly
rate.

**Phase to address:** This phase; treat the re-query as a Wave 0 gate before the exact floor
constants are written into `analytics/health.py`.

---

### Pitfall 4: Report byte budget must be measured against the SAME synthetic worst-case fixture already in the test suite — not the live database

**What goes wrong:** Unlike Pitfall 3's coverage-floor question (which genuinely needs real
production data), the BYTE-BUDGET question (`MAX_REPORT_*` in `_common.py`, plus new entries in
`test_mcp_tool_budget.py`'s `BUDGETS` dict) does **not** need live data at all —
`test_mcp_tool_budget.py`'s own existing methodology measures every tool against
`conftest.py`'s synthetic `worst_case_history` fixture (52 weeks × 5 sessions/week, seeded in a
Docker-container test), never against production. Confusing the two — waiting on live-database
access to set the byte budget — would stall this measurement for no reason.

**Why it happens:** Both are "real measurement, not a guess" problems, but they need different
kinds of "real": one needs actual user behavior (nutrition logging cadence), the other needs a
worst-case shape (which is deliberately synthetic and maximal, not representative).

**How to avoid:** Add `fitness_get_weekly_report`/`fitness_get_monthly_report` to
`WORST_CASE_ARGS`/`BUDGETS` following the exact pattern already in `test_mcp_tool_budget.py`
(read in full this session), measure the FULL `CallToolResult` (`model_dump_json` on the
returned object — this already captures both the `structured_content` and duplicated `text`
halves, confirmed by reading `test_mcp_tool_budget.py`'s own docstring and `_result_bytes`), and
set the budget at measured-worst-case + ~30% headroom, exactly as three of the twelve existing
budgets already had to be re-derived upward from their original research estimates
(`fitness_compare_periods` 32 KB estimated → 59,582 measured; `fitness_get_exercise_progression`
24 KB → 28,685; `fitness_get_plateaus` 24 KB → 28,350). Er on the side of a generous initial
constant rather than a tight one that needs a second pass.

**Rough order-of-magnitude estimate (labeled [ASSUMED], for planning purposes only — not a
substitute for the real measurement above):** the training-summary spine alone already measures
~9.5-11.5 KB full-wire at its own cap (`fitness_get_training_summary`, 16,384-byte budget,
confirmed from `test_mcp_tool_budget.py`). Adding narrow PR highlights (~0.5-1 KB for 3-5 items),
plateau highlights (~0.5-1 KB), a body-measurement summary (`fitness_get_body_measurement_trend`
already measures 2,048 bytes at its own single-metric cap — a report embedding 1-2 metrics
inline, without the standalone tool's own duplication overhead, is smaller, roughly 0.5-1.5 KB),
a 7-metric nutrition trend summary (~1.5-3 KB, extrapolating from body-weight-trend's per-metric
shape × 7), active-program context (`fitness_get_training_program` measures 554 bytes standalone,
smaller embedded, ~0.2-0.3 KB), and an extended freshness envelope covering 5 resource pairs
instead of 3 (~0.1-0.2 KB extra) puts a **weekly** report in the rough range of 13-19 KB total.
The **monthly** report adds the D-14 narrative string, plausibly 1-3 KB of markdown text,
pushing the rough range to 14-22 KB. Recommend an initial `MAX_REPORT_*` byte budget in the
24-32 KB range (deliberately generous, matching how `fitness_compare_periods` needed 60 KB
against a 32 KB original guess) and tightening it once the real composer is measured.

**Warning signs:** A `MAX_REPORT_*` constant with no comment citing a measured figure (every
existing constant in `_common.py`'s budget block carries one).

**Phase to address:** This phase; measurement is a Wave 0/early-plan task, not a research
deliverable (per CONTEXT.md's own instruction not to pre-estimate the exact final number here).

---

### Pitfall 5 (= PITFALLS.md #17, background refreshed this session): scheduled-task + custom-connector tool injection is still broken as of 2026-09-04

**What goes wrong:** `.planning/research/PITFALLS.md`'s Pitfall 17 already documents
`anthropics/claude-code#43397` and `#45306` (both closed "not planned," opened April 2026). This
session searched for anything more recent that might supersede that finding. It does not exist.
Independent, more recent reports found this session, none marked fixed:

- **#42522** "Scheduled triggers cannot access MCP connector tools"
- **#42033** "Cloud scheduled task connectors not injected into runtime"
- **#42148** "MCP deferred tools not available on first turn — breaks scheduled/automated tasks"
- **#41778** "MCP tools not available on first turn in Remote Trigger / Scheduled sessions"
- **#53489** (dated **April 23, 2026**) "Claude Code Web interactive sessions lost all claude.ai
  MCP connectors ... while routines retain them" — confirms the failure mode is still live a
  full three weeks past the original #43397 report
- **#63233** (dated **May 28, 2026**, closed "not planned") "Custom MCP connectors not attachable
  to Claude Code scheduled routines — no UUID discovery path" — a DIFFERENT, additional failure
  mode: the scheduling API itself has no way to attach a custom connector's UUID to a routine at
  all for some client surfaces (`POST /v1/code/triggers` returns `400
  mcp_connections.0.connector_uuid: Field required` with no discovery endpoint)
- **#67290** (dated **June 11, 2026**, closed as duplicate) "MCP connectors added on claude.ai
  mid-session are not discoverable until full session restart" — a related-but-distinct
  mid-session discovery gap

No official Anthropic documentation found this session (including the current Help Center
article on scheduling recurring tasks, fetched this session) acknowledges or promises a fix for
any of these. That article's own wording — "Scheduled tasks run remotely, so they run on their
cadence even when your computer is asleep or the Claude Desktop app is closed" — confirms
scheduled-task EXECUTION always happens in a remote/cloud environment regardless of which client
(Desktop, Web) was used to CREATE the schedule. This matters directly for D-12: creating the
spike task on Claude Desktop does not change the underlying execution environment the community
reports describe as broken — Desktop is where you configure it, not where it runs.

**Why it happens:** Outside this repo's control entirely — client-side tool-registry population
timing for autonomously-fired sessions, undocumented and apparently unfixed for 5+ months across
at least 8 distinct GitHub issue reports.

**How to avoid:** Exactly what CONTEXT.md's D-12/D-13 and ROADMAP.md's planning note already
say — spike first, with `fitness_ping` (the cheapest possible tool call) rather than a
newly-built report tool, so a negative result costs nothing built. If it fails, the documented
community workaround (start the scheduled prompt with an instruction to delegate to a subagent,
which the community reports as reliably working) is well-attested enough across multiple
independent reports this session found that it is worth having the exact preamble text drafted
and ready during planning, even though D-13 says not to add it to the doc until the spike
actually confirms the failure.

**Confidence on this finding specifically:** MEDIUM-HIGH. Multiple independent community reports
spanning April-June 2026, zero contradicting evidence, an official support article that (by
omission plus its own "runs remotely" language) is consistent with the failure persisting, and
no ability in this sandboxed research session to directly re-test the current live behavior
(that is exactly what D-12's human-gated spike is for). Treat as "very likely to reproduce the
known failure" rather than "certain to."

**Phase to address:** This phase, spike sequenced first (already directed by ROADMAP.md and
D-12).

## Code Examples

### Existing "one composer, closed-period window" precedent (comparison.py)

```python
# Source: backend/app/mcp/tools/comparison.py, CMP-01 — the one existing function taking two
# explicit periods rather than an "anchored on today" window. Read for shape reference only;
# fitness_compare_periods is NOT reused by the report composer (its own budget is already the
# most expensive call in the system at 81,920 bytes — composing it into a report would blow any
# reasonable MAX_REPORT_* budget).
```

### Existing budget-measurement harness (the pattern to extend, not re-invent)

```python
# Source: backend/tests/test_mcp_tool_budget.py:69-105, 155-163, 245-302 (read in full this
# session)
BUDGETS: dict[str, int] = {
    # ... existing 14 entries ...
    "fitness_get_weekly_report": <measured + 30% headroom>,   # NEW
    "fitness_get_monthly_report": <measured + 30% headroom>,  # NEW
}

def _result_bytes(result: Any) -> int:
    """The number of bytes this result costs Claude — FULL CallToolResult, not structured alone."""
    return len(result.model_dump_json(exclude_none=True).encode("utf-8"))
```

### Existing freshness-envelope extension precedent (metadata.py)

```python
# Source: backend/app/analytics/metadata.py:92-105 (read in full this session)
FRESHNESS_RESOURCES_ACTIVITY: tuple[FreshnessPair, ...] = (
    (PROVIDER_APPLE_HEALTH, RESOURCE_ACTIVITY),
)
FRESHNESS_RESOURCES_NUTRITION: tuple[FreshnessPair, ...] = (
    (PROVIDER_APPLE_HEALTH, RESOURCE_NUTRITION),
)
# A report reads Hevy workouts/exercise_templates/body_measurements AND BOTH Apple Health
# resources. Recommend a new FRESHNESS_RESOURCES_REPORT tuple combining all 5, following the
# exact FRESHNESS_RESOURCES_ALL precedent already established for BODY-02's 3-resource case:
FRESHNESS_RESOURCES_REPORT: tuple[FreshnessPair, ...] = (
    (PROVIDER_HEVY, RESOURCE_WORKOUTS),
    (PROVIDER_HEVY, RESOURCE_EXERCISE_TEMPLATES),
    (PROVIDER_HEVY, RESOURCE_BODY_MEASUREMENTS),
    (PROVIDER_APPLE_HEALTH, RESOURCE_ACTIVITY),
    (PROVIDER_APPLE_HEALTH, RESOURCE_NUTRITION),
)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `docs/coaching-instructions.md` documents 12 analytics tools + `fitness_ping` (13 total names, 16 tools registered as of Phase 12) | Must document 20 tools (16 existing + 4 new: activity trend, nutrition trend, weekly report, monthly report) inside the SAME 9,000-char ceiling | This phase | Rewrite, not edit (D-09 already settled this) |
| Coaching doc measured 7,934 chars (confirmed live, unchanged from CONTEXT.md's cited figure) | Must both grow (new tool docs) and shrink (COACH-02 conciseness) simultaneously | This phase | The 1,066-char headroom (9,000 - 7,934) is nowhere near enough for 4 new tool-table rows plus their "Example questions" entries; conciseness cuts elsewhere are load-bearing, not optional polish |
| No cross-exercise PR scan exists | Needed for D-02's "PR highlights" (see Pitfall 1) | This phase (gap discovered this session) | New analytics code, or a redefinition of what "PR highlights" means |

**Deprecated/outdated:** None — this phase adds to a system with no legacy code paths to retire.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | "Closed period" for the weekly/monthly report means "this week/month so far, through today" (reusing `window_from_weeks(weeks=1)`-style semantics), not "the most recently COMPLETED week/month" | Architecture Patterns, Pattern 1/2; Anti-Patterns | If the planner intends the completed-prior-period reading instead (ARCHITECTURE.md's literal "the completed week Mon–Sun" phrasing), the report's window math needs a full week/month SUBTRACTED, and `window_from_weeks(weeks=1)` is not directly reusable — flag this for explicit confirmation before implementation, since CONTEXT.md's own two source documents (ARCHITECTURE.md vs D-04's paraphrase) read slightly differently |
| A2 | Nutrition logging on the two known live-webhook days (2026-09-02, 2026-09-03) reflects the start of a genuinely sustained new habit, not a one-off setup/verification test | Pitfall 3 | If the user does not keep logging consistently, `bodyweight.py`-derived floors will report `insufficient_data` most of the time — an honest but possibly disappointing default outcome; re-query before locking floors, per Pitfall 3's guidance |
| A3 | The rough 13-22 KB byte-budget estimate for the report tools (Pitfall 4) is directionally correct | Pitfall 4 | If real composition (once built) measures meaningfully higher (as `fitness_compare_periods` did, 32 KB estimated → 59,582 measured), the initial `MAX_REPORT_*` constant needs a second pass — explicitly anticipated by recommending a generous 24-32 KB starting budget rather than a tight one |
| A4 | Reusing `get_plateaus`' `historical_best_kg`/`recent_performance_kg` as an approximate "PR this window" signal (Pitfall 1, option 2) is an acceptable interpretation of D-02's "PR highlights" if the planner chooses not to build new cross-exercise PR-scan arithmetic | Pitfall 1 | If the user/planner wants the literal `PersonalRecordType` semantics (max reps, session volume, not just e1RM/weight), option 2 under-delivers and option 1 (new analytics function) is required instead |

**Confirmed / not-assumed:** The scheduled-task reliability finding (Pitfall 5) is treated as
MEDIUM-HIGH confidence, not [ASSUMED], because it rests on multiple independent, dated,
still-unresolved external reports rather than training-data recall — but it is explicitly NOT a
substitute for D-12's live, human-gated spike, which remains the only way to confirm current
behavior against BRETT's actual connector.

## Open Questions

1. **Is "closed period" the current week/month-to-date, or the most recently completed one?**
   - What we know: `window_from_weeks(weeks=1)` gives "Monday through today" for free; D-04's own
     text says "the current week"/"the current calendar month"; ARCHITECTURE.md's source
     material says "the completed week Mon–Sun."
   - What's unclear: which the user actually wants delivered when they ask for "my weekly
     report" mid-week.
   - Recommendation: default to "current period, through today" (A1 above) since it costs zero
     new code and matches D-04's literal wording; confirm explicitly in the plan/discuss step if
     there's any doubt, since it changes the date-math for both report tools.

2. **How should "PR highlights" be defined, given no existing cross-exercise PR scan?**
   - What we know: two real options exist (new analytics function vs. reusing `get_plateaus`'
     fields); see Pitfall 1.
   - What's unclear: which the user/planner prefers, and how it trades off against the
     query-budget concern.
   - Recommendation: raise explicitly at plan time; this is a real scope decision, not a detail.

3. **Exact nutrition coverage floors (D-06).**
   - What we know: historical data is very sparse (≈3.3%); live-era data (2 days) is
     encouragingly dense but statistically insufficient.
   - What's unclear: the true ongoing logging rate once more live days accumulate.
   - Recommendation: re-run the SQL in Pitfall 3 at Wave 0/plan time; default to
     `bodyweight.py`'s existing floors in the meantime.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Live Neon PostgreSQL query access (this research session) | D-06 real-coverage measurement | ✗ (sandbox blocked all vectors: `psql`, `asyncpg`, `gcloud secrets access`) | — | Use the already-committed production figures in `docs/health-auto-export-setup.md` (partial coverage) plus the exact re-query SQL provided in Pitfall 3, to be run by a human operator or a future session with different tool permissions |
| `mcp` 2.0.0 / FastAPI / SQLAlchemy / Pydantic (existing stack) | All new code this phase | ✓ | Already pinned project-wide, no changes needed | — |
| Claude scheduled-task execution environment (RPT-03 spike) | D-12's human-gated verification | Unknown until spike runs — external evidence strongly suggests still broken | — | On-demand tool calls remain fully functional regardless (already the phase's own fallback design, PROJECT.md) |

**Missing dependencies with no fallback:** None — the one blocked dependency (live DB query
access in THIS session) has a documented recovery path (re-query at plan/implementation time).

**Missing dependencies with fallback:** Scheduled-task delivery (RPT-03) — on-demand reports are
the fallback, already locked at the PROJECT.md level.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 + pytest-asyncio 1.4.0 (confirmed from CLAUDE.md's pinned stack; `asyncio_mode = "auto"`) |
| Config file | `backend/pyproject.toml` (not re-read this session; existing project convention) |
| Quick run command | `uv run pytest backend/tests/test_analytics_health.py backend/tests/test_mcp_tools.py -x` (new test files, names TBD by planner) |
| Full suite command | `uv run pytest` (container-backed integration tests included) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| HEALTH-12 | Activity trend rolling averages + floors, mirroring `bodyweight.py` | unit | `pytest backend/tests/test_analytics_health.py -k activity -x` | ❌ Wave 0 |
| NUTR-04 | Nutrition trend rolling averages + per-metric floors | unit | `pytest backend/tests/test_analytics_health.py -k nutrition -x` | ❌ Wave 0 |
| NUTR-06 | `fitness_get_nutrition_trend` MCP tool schema + degraded path | integration | `pytest backend/tests/test_mcp_tools.py -k nutrition_trend -x` | ❌ Wave 0 (extend existing file) |
| RPT-01 | Weekly report composes correct closed-period spine + narrow extras | integration | `pytest backend/tests/test_analytics_reports.py -k weekly -x` | ❌ Wave 0 |
| RPT-02 | Monthly report, same composer, calendar-month window, narrative field present | integration | `pytest backend/tests/test_analytics_reports.py -k monthly -x` | ❌ Wave 0 |
| RPT-03 | Real scheduled-task run against report tools, outcome documented | manual-only | N/A — human-gated per D-12, no automated substitute possible | N/A |
| COACH-02 | Coaching doc length ≤ 9,000 chars, concise | unit | `pytest backend/tests/test_coaching_doc.py -x` (already exists) | ✅ |
| COACH-03 | Coaching doc drift guard (bidirectional tool-name match) | unit | `pytest backend/tests/test_coaching_doc.py -x` (already exists) | ✅ |
| MCP-03 (budget, extended this phase) | Report tools fit their measured `MAX_REPORT_*` budget | integration | `pytest backend/tests/test_mcp_tool_budget.py -x` (already exists, extend `BUDGETS`) | ✅ (extend) |

### Sampling Rate
- **Per task commit:** the relevant unit test file for the module just touched
- **Per wave merge:** `uv run pytest` (full suite, container-backed)
- **Phase gate:** Full suite green before `/gsd-verify-work`; RPT-03's manual spike result
  documented in `docs/coaching-instructions.md` (or a setup doc) regardless of outcome

### Wave 0 Gaps
- [ ] `backend/tests/test_analytics_health.py` — covers HEALTH-12, NUTR-04 (activity + nutrition
  rolling averages, independent per-window and per-metric floors)
- [ ] `backend/tests/test_analytics_reports.py` — covers RPT-01, RPT-02 (composer, both periods,
  narrow extras, degraded path)
- [ ] `test_mcp_tool_budget.py`'s `BUDGETS`/`WORST_CASE_ARGS` — extend with the two new report
  tools (measurement-driven, per Pitfall 4)
- [ ] `test_coaching_doc.py` — no new file needed, but the drift guard will start failing the
  moment the 4 new tools are registered and undocumented; sequence the doc rewrite to land in
  the same wave the tools are registered, or expect a red test in between
- [ ] The re-query SQL in Pitfall 3, run against confirmed production `DATABASE_URL` by a human
  operator (this session could not run it) — informs the exact `MEASURED_DAY_FLOORS`-equivalent
  constants for nutrition before `analytics/health.py`'s nutrition function is finalized

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No change this phase | Existing `AuthKitJWTVerifier` / static-bearer path, unmodified |
| V3 Session Management | No change this phase | MCP is stateless per `mcp` 2.0.0; unaffected |
| V4 Access Control | Yes | `resolve_user_id(ctx)` server-side resolution, unchanged pattern — every new tool MUST call it exactly like the 16 existing tools; `user_id` never in any new tool's `inputSchema` |
| V5 Input Validation | Yes | New tool parameters (if any — the report tools may take none, per Pattern 1/2) must use Pydantic/`Field` constraints exactly like `MAX_SUMMARY_WEEKS`-style caps; the nutrition metric list is a closed 7-member set, never a caller-supplied string |
| V6 Cryptography | No change this phase | — |
| V8 Data Protection | Yes | `safe_tool`'s exception-swallowing pattern (never leak `str(exception)`, which can carry the DSN) MUST be applied to the two new tool modules exactly like every existing one |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| A new tool accidentally opens a WRITABLE session | Elevation of Privilege | `read_only_session` only; `test_mcp_never_writes`'s allowlist regex will fail the build if a new module imports `writable_session` — no action needed beyond not importing it |
| A new tool's exception leaks a DSN or internal detail to Claude | Information Disclosure | `safe_tool(degraded=...)` decorator on every new tool, exactly like all 16 existing ones |
| An unbounded "PR highlights" or "nutrition trend" list grows without a cap | Denial of Service (context-window exhaustion, not server DoS) | `truncate()` + `MAX_REPORT_*` constants in `_common.py`, per Pitfall 4 |
| The narrative markdown field (D-14) accidentally includes free-form LLM-authored text instead of deterministic template output | Tampering (of the "decision support, not diagnosis" boundary D-03/`RecompositionResult.disclaimer` already establishes) | Pure function, unit-tested for determinism (same inputs → byte-identical output), exactly like `format_summary`'s existing test coverage |

## Sources

### Primary (HIGH confidence — read directly this session)
- `backend/app/mcp/tools/summary.py` — full file, the report composer's direct template
- `backend/app/mcp/tools/_common.py` — full file, budget-cap block, `window_from_weeks`,
  `safe_tool`, `truncate`, session helpers
- `backend/app/analytics/bodyweight.py` — full file, the rolling-average/floor pattern to copy
- `backend/app/analytics/body_measurements.py` — full file, the pattern explicitly NOT to copy,
  and the precedent for per-metric independent coverage
- `backend/app/analytics/recomposition.py` — full file, anchored-on-today confirmed, program
  context fields confirmed
- `backend/app/analytics/metadata.py` — full file, `build_freshness`, `MEASURED_DAY_FLOORS`,
  existing `FRESHNESS_RESOURCES_*` constants
- `backend/app/analytics/schemas.py` — `RecompositionResult`, `PlateauResult`, `PersonalRecord`,
  `BodyWeightTrendResult`, `BodyMeasurementTrendResult` class definitions
- `backend/app/analytics/records.py` — `get_personal_records` signature, confirming the
  mandatory single-exercise scoping (Pitfall 1)
- `backend/app/analytics/progression.py` — `get_plateaus` signature, confirming cross-exercise
  scope; `ExerciseTrend` schema
- `backend/app/db/models/health.py` — `HealthDailyMetric` full model
- `backend/app/integrations/health_auto_export/registry.py` — `METRIC_REGISTRY`, all 12 metric
  names/units
- `backend/app/integrations/health_auto_export/backfill.py` — `format_summary`, the narrative
  precedent
- `backend/app/db/repositories/sync_state.py` — provider/resource constant values
- `backend/app/core/time.py` — full file, confirming no month-boundary helper exists yet
- `backend/app/mcp/server.py` — current 16-tool registry, `_INSTRUCTIONS` string
- `docs/coaching-instructions.md` — full file, 7,934 chars confirmed live (`wc -c`)
- `backend/tests/test_coaching_doc.py` — full file, drift-guard and length-ceiling assertions
- `backend/tests/test_mcp_tool_budget.py` — full file, existing budget-measurement methodology
  and all 14 current measured budgets
- `docs/health-auto-export-setup.md` — real production nutrition/activity row counts (§ dry-run
  and § 2026-09-03 production-run entries)
- `.planning/STATE.md`, `.planning/REQUIREMENTS.md`, `.planning/phases/13-.../13-CONTEXT.md` —
  full read
- `.planning/research/PITFALLS.md` (#17, #18, #19), `.planning/research/ARCHITECTURE.md`
  (§4, §5, build order) — full relevant sections read

### Secondary (MEDIUM confidence — WebSearch/WebFetch, cross-referenced against each other)
- github.com/anthropics/claude-code issues #43397, #45306, #35899, #36327 (already known from
  PITFALLS.md, re-confirmed still closed "not planned" this session)
- github.com/anthropics/claude-code issues #42522, #42033, #42148, #41778, #53489 (dated April 23
  2026), #63233 (dated May 28 2026), #67290 (dated June 11 2026) — newly found this session,
  all describing the same or closely related failure, none marked fixed
- support.claude.com scheduling-recurring-tasks Help Center article — fetched this session,
  confirms remote/cloud execution regardless of creating client, silent on the MCP-connector
  failure mode

### Tertiary (LOW confidence — not used for any load-bearing claim)
- None

## Metadata

**Confidence breakdown:**
- Standard stack / architecture patterns: HIGH — every claim traced to a specific file read this
  session, no training-data guessing
- Nutrition coverage floors (D-06): MEDIUM — real historical numbers exist and are cited exactly,
  but the live-era window is too young to measure at this moment; explicitly flagged as needing
  re-query, not resolved
- Scheduled-task reliability (RPT-03 background): MEDIUM-HIGH — strong, recent, multi-source
  external evidence; genuinely cannot be verified further without the human-gated D-12 spike
  itself
- Report byte budget: MEDIUM — grounded in real measured component sizes but explicitly an
  estimate pending the actual composer's construction, per CONTEXT.md's own instruction not to
  pre-estimate the final number

**Research date:** 2026-09-04
**Valid until:** ~2026-09-18 (7 days) for the RPT-03 external-dependency finding (fast-moving,
re-check immediately before the spike if more than a few days pass); ~2026-10-04 (30 days) for
the code-level architecture findings (stable until the codebase itself changes)
