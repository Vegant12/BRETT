# Phase 13: Health Analytics, Reports & Coaching Style - Pattern Map

**Mapped:** 2026-09-04
**Files analyzed:** 17 (10 new, 7 modified)
**Analogs found:** 17 / 17

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `backend/app/analytics/health.py` (NEW) | service (analytics) | transform (rolling-average fold) | `backend/app/analytics/bodyweight.py` | exact |
| `backend/app/analytics/reports.py` (NEW) | service (composition) | CRUD/composition (read + compose, no arithmetic) | `backend/app/analytics/recomposition.py` | exact |
| `backend/app/analytics/records.py` (MODIFY — new cross-exercise scan, if Pitfall 1 option 1 chosen) | service (analytics) | transform (aggregate scan) | `backend/app/analytics/progression.py::get_plateaus` | role-match |
| `backend/app/analytics/metadata.py` (MODIFY — add `FRESHNESS_RESOURCES_REPORT`) | utility (constants) | transform | same file, existing `FRESHNESS_RESOURCES_*` constants | exact |
| `backend/app/analytics/schemas.py` (MODIFY — add `ActivityTrendResult`, `NutritionTrendResult`, `ReportResult`) | model (Pydantic schema) | transform | same file, `BodyWeightTrendResult`/`RecompositionResult` | exact |
| `backend/app/core/time.py` (MODIFY — add `local_month_start`) | utility | transform | same file, `local_week_start` | exact |
| `backend/app/mcp/tools/health.py` (NEW) | controller (MCP tool) | request-response | `backend/app/mcp/tools/body.py` | exact |
| `backend/app/mcp/tools/reports.py` (NEW) | controller (MCP tool) | request-response (composition) | `backend/app/mcp/tools/summary.py` | exact |
| `backend/app/mcp/tools/schemas.py` (MODIFY — add response models) | model (Pydantic schema) | request-response | same file, `TrainingSummaryResponse`/`BodyWeightTrendResponse` | exact |
| `backend/app/mcp/tools/_common.py` (MODIFY — add `MAX_REPORT_*`) | utility (cross-cutting) | request-response | same file, existing budget-cap block | exact |
| `backend/app/mcp/server.py` (MODIFY — register 4 new tools) | config (tool registry) | request-response | same file, `_TOOLS` tuple + loop | exact |
| `docs/coaching-instructions.md` (REWRITTEN) | config (client-side doc) | — | same file, previous version | exact (self-analog) |
| `backend/tests/test_analytics_health.py` (NEW) | test | transform | `backend/tests/test_analytics_bodyweight.py` | exact |
| `backend/tests/test_analytics_reports.py` (NEW) | test | request-response/composition | `backend/tests/test_analytics_recomposition.py` | exact |
| `backend/tests/test_mcp_tools.py` (MODIFY — new tool tests) | test | request-response | same file, `test_body_weight_trend_returns_rolling_averages` etc. | exact |
| `backend/tests/test_mcp_tool_budget.py` (MODIFY — extend `BUDGETS`/`WORST_CASE_ARGS`) | test | batch (measurement) | same file, existing pattern | exact |
| `backend/tests/test_coaching_doc.py` (unchanged, must keep passing) | test | — | same file | exact |

## Pattern Assignments

### `backend/app/analytics/health.py` (NEW — service, transform)

**Analog:** `backend/app/analytics/bodyweight.py` (full file read)

**Imports pattern** (bodyweight.py:39–58):
```python
import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.metadata import (
    FRESHNESS_RESOURCES_ACTIVITY,  # or _NUTRITION — already defined in metadata.py:96-101
    build_freshness,
    build_measurement_coverage,
    earliest_measurement_at,       # health.py needs its OWN per-metric variant, see Pitfall 2
    is_measurement_insufficient,
)
from app.analytics.rollup import resolve_window
from app.analytics.schemas import ActivityTrendResult, NutritionTrendResult  # NEW schemas
from app.core.time import local_day, utc_now
from app.db.models.health import HealthDailyMetric
```

**Core "one fetch, folded N ways" pattern** (bodyweight.py:210–244, the `_FETCH_SPAN_DAYS` +
`_window_average` shape):
```python
# ONE fetch covering every window, folded five ways (bodyweight.py's own comment). health.py's
# fetch spans 29 days (30-day window, no D-16-style 4-week anchor needed — D-05/D-06 do not ask
# for a smoothed rate, only 7/14/30-day averages + "rate of change").
rows = await _rows_for_window(
    session, user_id=user_id, source=..., metric=..., start_day=anchor - dt.timedelta(days=29),
    end_day=anchor,
)
by_day = _fold_by_day(rows)  # dict[dt.date, Decimal]

avg_7, days_7 = _window_average(by_day, end_day=anchor, window_days=7)
avg_14, days_14 = _window_average(by_day, end_day=anchor, window_days=14)
avg_30, days_30 = _window_average(by_day, end_day=anchor, window_days=30)

coverage_7 = build_measurement_coverage(window_days=7, measured_days=days_7, earliest_measurement_at=earliest)
coverage_14 = build_measurement_coverage(window_days=14, measured_days=days_14, earliest_measurement_at=earliest)
coverage_30 = build_measurement_coverage(window_days=30, measured_days=days_30, earliest_measurement_at=earliest)
```

**Per-metric independent coverage (Pitfall 2)** — do NOT copy `bodyweight.py`'s single-tracked-
value shape verbatim for nutrition; instead follow `body_measurements.py`'s per-column
independence discipline while keeping ONE query per window (all 7 nutrition metrics via
`WHERE metric IN (...)`), folded 7 ways in Python — the same "one fetch, folded N ways" idea
`bodyweight.py` already established, just widened from 5 folds to 7×3=21 (7 metrics × 3 windows).

**Query shape to copy** (bodyweight.py `_weight_rows`, lines 97–126) — adapt the WHERE clause to
`HealthDailyMetric`'s natural key:
```python
async def _rows_for_window(
    session: AsyncSession, *, user_id: uuid.UUID, metric: str, start_day: dt.date, end_day: dt.date
) -> list[HealthDailyMetricRow]:
    result = await session.execute(
        select(HealthDailyMetric.local_day, HealthDailyMetric.value)
        .where(
            HealthDailyMetric.user_id == user_id,           # tenant predicate leads (T-04-02)
            HealthDailyMetric.source == "apple_health",
            HealthDailyMetric.metric == metric,
            HealthDailyMetric.local_day >= start_day,
            HealthDailyMetric.local_day <= end_day,
        )
        .order_by(HealthDailyMetric.local_day)
    )
    return [...]
```
NOTE: `HealthDailyMetric`'s natural key also includes `source_name` — HEALTH-08 requires
excluding Hevy's own HealthKit write-back for `active_energy` specifically (see
`backend/app/db/models/health.py` module docstring, lines 7–15). A `source_name != 'Hevy'`
predicate (or equivalent) is very likely needed for `active_energy` and should be verified
against `backend/app/integrations/health_auto_export/registry.py`'s ingest/normalize logic
before finalizing the WHERE clause — this is a genuine per-metric nuance `bodyweight.py` has no
analog for, since `body_measurements` has no multi-source contamination problem.

**Metric names/units — read from the registry, never re-derive:**
```python
# Source: backend/app/integrations/health_auto_export/registry.py:42-59
# Activity: step_count (count), active_energy (kcal), basal_energy_burned (kcal),
#           walking_running_distance (km), flights_climbed (count)
# Nutrition: dietary_energy (kcal), protein (g), carbohydrates (g), total_fat (g),
#            fiber (g), dietary_sugar (g), sodium (mg)
```

**Anchor-day probe idiom** (bodyweight.py:198–208, also used identically in `progression.py`
and `body_measurements.py` — copy verbatim, it is the established idiom for "resolve tz before
computing the anchor day"):
```python
probe_day = local_day(utc_now(), "UTC")
tz = (
    await resolve_window(
        session, user_id=user_id, start_day=probe_day, end_day=probe_day, snap_to_weeks=False,
    )
).tz
anchor = local_day(utc_now(), tz)
```

**Freshness pattern** (bodyweight.py:291–293):
```python
freshness=await build_freshness(session, user_id=user_id, resources=FRESHNESS_RESOURCES_ACTIVITY),
# nutrition function uses FRESHNESS_RESOURCES_NUTRITION — both already exist in metadata.py:96-101
```

**What NOT to copy** — `body_measurements.py`'s latest-vs-earliest-90-day shape (D-05/D-06
explicitly reject it for activity/nutrition). Keep that file only as the precedent for
*documenting a measured, deliberate coverage floor* (its `STALE_AFTER_DAYS` comment style),
not for its arithmetic shape.

---

### `backend/app/analytics/reports.py` (NEW — service, composition only)

**Analog:** `backend/app/analytics/recomposition.py` (full file read) for the "composition, no
new SQL beyond the envelope" discipline, plus `backend/app/mcp/tools/summary.py`'s docstring for
the "narrow extras, one transaction" budget discipline.

**Composition-only pattern** (recomposition.py:1–2, module docstring):
```python
"""Recomposition status (BODY-02). Composition only -- no SQL of its own beyond the envelope.

Calls ``bodyweight.get_body_weight_trend`` and ``progression.get_exercise_trends`` rather than
re-deriving either. One computation with two consumers beats two definitions of "improving"...
"""
```
`reports.py` must follow this exact discipline: it imports and calls `get_weekly_volume`,
`get_muscle_group_volume`, `get_recomposition_status`, `get_plateaus`, `get_body_measurement_trend`,
the new `get_activity_trend`/`get_nutrition_trend`, and `get_active_period`/`get_recent_periods`
— it computes NO new arithmetic itself (D-02, D-03, Anti-Pattern #9 in ARCHITECTURE.md).

**Reused-verbatim active-program context** (recomposition.py:596–621) — the report should reuse
`RecompositionResult`'s already-resolved `active_program`, `program_switch_in_window`,
`previous_program` fields (call `get_recomposition_status` once, read these off the result)
rather than re-querying `db/repositories/programs.py` a second time in the same transaction:
```python
recomposition = await get_recomposition_status(session, user_id=user)
# recomposition.active_program, .program_switch_in_window, .previous_program — read verbatim,
# per CONTEXT.md's canonical_refs: "reports surface RecompositionResult's active-program field
# verbatim... no new logic needed here."
```

**One-transaction composition pattern** (summary.py:112–127, the direct template for
`fitness_get_weekly_report`/`fitness_get_monthly_report`, NOT for `reports.py` itself — the MCP
tool wrapper owns the transaction, `reports.py`'s `compose_report` function takes an already-open
`session`):
```python
async with read_only_session(ctx) as session:
    start_day, end_day = await window_from_weeks(session, user_id=user, weeks=weeks)  # weekly
    # OR: start_day, end_day = local_month_start(...), await local_today(...)          # monthly
    report = await compose_report(session, user_id=user, start_day=start_day, end_day=end_day, period=...)
```

**PR highlights — the two real options (Pitfall 1), pick one explicitly in the plan:**
- Option 1 (new arithmetic, correctly homed in `analytics/records.py`): a new
  `get_recent_records(session, *, user_id, start_day, end_day) -> list[PersonalRecord]`
  cross-exercise scan, modeled on how `get_plateaus` (progression.py:642-786) already avoids a
  per-exercise loop — one aggregate query across all templates, folded once.
- Option 2 (zero new queries): reuse `get_plateaus`' already-cross-exercise
  `historical_best_kg`/`recent_performance_kg` fields as an approximate "new best this window"
  signal. Reads `PlateauResult` (progression.py's `PlateauReport.exercises`) which the report is
  already fetching for plateau highlights anyway.

**Plateau highlights — free, model this on `truncate()`** (`_common.py:319-330`):
```python
plateaus = await get_plateaus(session, user_id=user, lookback_weeks=..., template_external_ids=None)
highlighted, truncated, total = truncate(
    [p for p in plateaus.exercises if p.plateaued], limit=<small N, e.g. 5>
)
```

**Deterministic narrative template (D-14)** — copy the SHAPE of `format_summary`, not its
content:

**Source:** `backend/app/integrations/health_auto_export/backfill.py:812-826` (docstring) +
`:831-869` (body):
```python
def format_summary(summary: BackfillSummary, *, path: Path) -> list[str]:
    """... A pure function returning a list so ``cli.py`` stays a thin dispatcher, so the block is
    testable without capturing stdout..."""
    lines = [
        f"Apple Health backfill — {headline}",
        f"file: {path.name}",
        (f"records: {scan.records_total} total" f" = {normalized.datapoints_seen} in-scope" ...),
        ...
    ]
    if summary.first_day is None or summary.last_day is None:
        lines.append("date range: (no rows)")
    else:
        lines.append(f"date range: {summary.first_day.isoformat()} .. {summary.last_day.isoformat()}")
    return lines
```
`reports.py`'s `build_narrative(report: ReportResult) -> str` should be an f-string/`"\n".join(...)`
pure function taking the ALREADY-COMPOSED `ReportResult` and restating its fields — no template
engine (none exists anywhere in this codebase; confirmed by `grep -rln "jinja\|Template"
backend/app/` returning nothing relevant), no new judgment, no recommendation language (D-03/D-14).

---

### `backend/app/mcp/tools/health.py` (NEW — controller, request-response)

**Analog:** `backend/app/mcp/tools/body.py` (full file read) — the direct template for a
no-window analytics-anchored-on-today tool, adapted to add ONE parameter neither existing tool
has (activity/nutrition trends are anchored on today too, per D-05/D-06's "following
`bodyweight.py`'s shape").

**Degraded-factory pattern** (body.py:53–61):
```python
def _degraded_trend() -> ActivityTrendResponse:
    """"I could not reach the data" payload. ``data_available=False`` is NOT the same claim as
    "you have not been active" -- without the flag the two are byte-identical and Claude would
    narrate an outage as a rest day.

    Built by a factory rather than held as a module constant so each failure gets a fresh object
    and no caller can mutate the placeholder the next one receives (``safe_tool``'s contract).
    """
    return ActivityTrendResponse(data_available=False, trend=None)
```

**Tool + verbatim-embedding pattern** (body.py:64–74):
```python
@safe_tool(degraded=_degraded_trend)
async def fitness_get_activity_trend(ctx: Context[AppContext]) -> ActivityTrendResponse:
    """Activity trend anchored on today: 7/14/30-day rolling averages and rate of change for
    steps, active/basal energy, distance and flights climbed."""
    user_id = resolve_user_id(ctx)
    async with read_only_session(ctx) as session:
        trend = await get_activity_trend(session, user_id=user_id)
    return ActivityTrendResponse(data_available=True, trend=trend)
```

**D-08's "no metric selector" nutrition tool** — unlike `fitness_get_body_measurement_trend`
(body.py:121-148), which takes a `metric: BodyMeasurementMetric` `Field(...)` parameter,
`fitness_get_nutrition_trend` takes NO parameters at all (like
`fitness_get_body_weight_trend`/`fitness_get_recomposition_status`) — it always returns all 7
values. Model the nutrition tool on body.py's zero-argument pair, not its one-argument pair.

---

### `backend/app/mcp/tools/reports.py` (NEW — controller, request-response/composition)

**Analog:** `backend/app/mcp/tools/summary.py` (full file read) — this IS the model the
canonical_refs explicitly name: "one read-only transaction around every composed call, a
`_degraded_*` factory for `safe_tool`, verbatim-echoed disclaimer fields."

**Full tool shape to copy** (summary.py:84–172):
```python
@safe_tool(degraded=_degraded_summary)
async def fitness_get_weekly_report(ctx: Context[AppContext]) -> WeeklyReportResponse:
    """..."""
    user = resolve_user_id(ctx)
    async with read_only_session(ctx) as session:                      # ONE transaction
        start_day, end_day = await window_from_weeks(session, user_id=user, weeks=1)  # FREE, see Pattern 1 below
        report = await compose_report(session, user_id=user, start_day=start_day, end_day=end_day)
    return WeeklyReportResponse(data_available=True, ...)
```
`fitness_get_monthly_report` is IDENTICAL except for the window computation
(`local_month_start(...)` instead of `window_from_weeks(weeks=1)`) and the extra `narrative`
field (D-14) — this is what makes D-04's "one composer function" concretely achievable.

**Weekly window is FREE — do not write new date math for it:**
```python
# Source: backend/app/mcp/tools/_common.py:235-244 (window_from_weeks) and :183-202 (week_window)
start_day, end_day = await window_from_weeks(session, user_id=user, weeks=1)
# weeks=1 => this_monday = today - timedelta(days=today.weekday()); returns (this_monday, today)
# — exactly D-01/D-04's closed-period, calendar-boundary window. NO new helper needed here.
```

**Monthly window needs ONE new helper in `core/time.py`, beside `local_week_start`:**
```python
# Mirrors local_week_start's signature and one-line body exactly (core/time.py:67-70):
def local_month_start(ts: dt.datetime, tz: str) -> dt.date:
    """First calendar day of the user's local month."""
    day = local_day(ts, tz)
    return day.replace(day=1)
```

**Recomposition status stays anchored on today, called ONCE, unmodified** — never pass it a
window argument (D-01 forbids adding one to `get_recomposition_status`):
```python
# Source: backend/app/analytics/recomposition.py:577-587 (signature) — takes NO window at all.
recomposition = await get_recomposition_status(session, user_id=user)
```

---

### `backend/app/mcp/tools/schemas.py` (MODIFY — add response models)

**Analog:** same file, `TrainingSummaryResponse` (417–447) for the report responses,
`BodyWeightTrendResponse`/`BodyMeasurementTrendResponse` (178–199) for the trend responses.

**Trend response pattern to copy exactly:**
```python
class ActivityTrendResponse(_McpModel):
    """HEALTH-12 for MCP. ``trend`` is the analytics result verbatim, per-window coverage and
    all -- a collapsed single coverage flag would hide that a 30-day average can be trustworthy
    while the 7-day one is not."""
    data_available: bool
    trend: ActivityTrendResult | None


class NutritionTrendResponse(_McpModel):
    """NUTR-06 for MCP. Per Pitfall 2, ``trend`` carries INDEPENDENT per-metric coverage --
    never one shared flag across the 7 macros."""
    data_available: bool
    trend: NutritionTrendResult | None
```

**Report response pattern** (modeled on `TrainingSummaryResponse`, summary.py's docstring
discipline about what is deliberately excluded):
```python
class WeeklyReportResponse(_McpModel):
    data_available: bool
    window_start: dt.date | None
    window_end: dt.date | None
    # ... narrow-extras fields per D-02: volume_by_week, muscles, recomposition_status/
    # disclaimer/progression fields (SAME spine as TrainingSummaryResponse), pr_highlights,
    # plateau_highlights, body_measurement_summary, nutrition_summary, active_program context,
    # coverage, freshness


class MonthlyReportResponse(_McpModel):
    # Identical fields to WeeklyReportResponse PLUS:
    narrative: str | None   # D-14 — monthly ONLY, weekly does NOT get this field
```

---

### `backend/app/mcp/tools/_common.py` (MODIFY — add `MAX_REPORT_*`)

**Analog:** same file's existing budget-cap block (lines 50–99).

**Pattern to follow exactly** — every constant carries a comment citing WHY, and per Pitfall 4
the exact number must be a MEASURED figure (test_mcp_tool_budget.py methodology), not a guess:
```python
# D-02/D-14 + Pitfall 4. [MEASURED against test_mcp_tool_budget.py's worst_case_history fixture
# at the report's full composed shape -- see that file's own re-derivation precedent for
# fitness_compare_periods/fitness_get_exercise_progression/fitness_get_plateaus, all of which
# were re-measured upward from a research estimate]. A generous STARTING range per Pitfall 4 is
# 24-32 KB; DO NOT hardcode this without running the measurement.
MAX_REPORT_PR_HIGHLIGHTS = <N>       # narrow extra, not the full fitness_get_personal_records list
MAX_REPORT_PLATEAU_HIGHLIGHTS = <N>  # narrow extra, not the full fitness_get_plateaus list
```

---

### `backend/app/analytics/metadata.py` (MODIFY — add `FRESHNESS_RESOURCES_REPORT`)

**Analog:** same file, `FRESHNESS_RESOURCES_ALL` (metadata.py:86–90) and the two ALREADY-PRESENT
Phase 8 bundles `FRESHNESS_RESOURCES_ACTIVITY`/`FRESHNESS_RESOURCES_NUTRITION` (96–101) — these
exist already and do not need to be added, only combined.

**Pattern to copy** (this exact 5-resource tuple is already drafted in RESEARCH.md's Code
Examples section, sourced from metadata.py:92-105):
```python
FRESHNESS_RESOURCES_REPORT: tuple[FreshnessPair, ...] = (
    (PROVIDER_HEVY, RESOURCE_WORKOUTS),
    (PROVIDER_HEVY, RESOURCE_EXERCISE_TEMPLATES),
    (PROVIDER_HEVY, RESOURCE_BODY_MEASUREMENTS),
    (PROVIDER_APPLE_HEALTH, RESOURCE_ACTIVITY),
    (PROVIDER_APPLE_HEALTH, RESOURCE_NUTRITION),
)
```
Provider/resource constants are already defined in `backend/app/db/repositories/sync_state.py`:
`PROVIDER_HEVY = "hevy"`, `PROVIDER_APPLE_HEALTH = "apple_health"`,
`RESOURCE_WORKOUTS/EXERCISE_TEMPLATES/BODY_MEASUREMENTS/ACTIVITY/NUTRITION` (lines 21–42) —
import them, never re-declare string literals.

---

### `backend/app/mcp/server.py` (MODIFY — register 4 new tools)

**Analog:** same file — the existing import block, `_TOOLS` tuple and registration loop.

**Import pattern** (server.py:41–61):
```python
from app.mcp.tools.health import fitness_get_activity_trend, fitness_get_nutrition_trend
from app.mcp.tools.reports import fitness_get_monthly_report, fitness_get_weekly_report
```

**Registration pattern** (server.py:165–230, add 4 tuples to `_TOOLS`, description style
matches existing terse one-liners):
```python
_TOOLS: tuple[tuple[Callable[..., Any], str], ...] = (
    # ... existing 14 ...
    (fitness_get_activity_trend, "7/14/30-day rolling activity averages: steps, active/basal energy, distance, flights climbed."),
    (fitness_get_nutrition_trend, "7/14/30-day rolling nutrition averages: calories and all 6 macros, independent per-metric coverage."),
    (fitness_get_weekly_report, "This week's training, strength, measurement, nutrition and program picture in one call."),
    (fitness_get_monthly_report, "This month's full picture, same sections as the weekly report, plus a markdown narrative."),
)
```
All 4 are READ-ONLY (`annotations=READ_ONLY`, the shared object at server.py:135–140) — registered
in the loop, NOT alongside `fitness_switch_training_program`'s separate `WRITE_TOOL` registration.

---

### `docs/coaching-instructions.md` (REWRITTEN — config, no data flow)

**Analog:** the file's own current version (full file read, 7,934 chars) — rewritten from
scratch per D-09, but the STRUCTURE (Role → Core objectives → The data rule → Decision framework
→ tool-mapping table → metadata-envelope table → units/framing → Example questions) is the
established shape to preserve, per D-11's "tighten, don't restructure" instruction.

**Tool-mapping table row pattern to extend** (coaching-instructions.md:53–70, one row per tool,
required params bolded):
```
| "How active have I been?" / "am I hitting my step goal?" | `fitness_get_activity_trend` | *(none)* |
| "How's my nutrition been?" / "am I hitting my macros?" | `fitness_get_nutrition_trend` | *(none)* |
| "Give me my weekly report" | `fitness_get_weekly_report` | *(none)* |
| "Give me my monthly report" | `fitness_get_monthly_report` | *(none)* |
```

**Metadata-envelope table** (coaching-instructions.md:82–95) must gain the 2 new
`freshness.resources` keys (`activity`, `nutrition`) in its first row's parenthetical list.

**Drift-guard constraint** — `backend/tests/test_coaching_doc.py` (full file read):
`_TOOL_TOKEN = re.compile(r"fitness_[a-z_]+")` scans the WHOLE document (not just the table) and
asserts bidirectionally against the live registry; `_PASTE_CEILING_CHARS = 9_000` is a hard
ceiling on `len(doc)`. Every one of the 4 new tool names MUST appear at least once, and the
rewritten doc's total character count must stay ≤ 9,000. D-10's last-resort belt (moving
overflow into `server.py`'s `_INSTRUCTIONS`, lines 79–91) is the escape hatch if needed.

---

### `backend/tests/test_mcp_tool_budget.py` (MODIFY — extend `BUDGETS`/`WORST_CASE_ARGS`)

**Analog:** same file, its own existing pattern (lines 69–121, `BUDGETS` dict;
`WORST_CASE_ARGS` dict below it).

**Pattern to copy exactly** — measure first, comment the measurement, never guess:
```python
BUDGETS: dict[str, int] = {
    # ... existing 14 ...
    # [MEASURED against worst_case_history at <period>=... on <date>] + ~30% headroom, per this
    # file's own re-derivation precedent (fitness_compare_periods 32KB est -> 59,582 measured).
    "fitness_get_activity_trend": <measured>,
    "fitness_get_nutrition_trend": <measured>,
    "fitness_get_weekly_report": <measured>,
    "fitness_get_monthly_report": <measured>,
}
WORST_CASE_ARGS: dict[str, dict[str, object]] = {
    # ... existing ...
    "fitness_get_activity_trend": {},
    "fitness_get_nutrition_trend": {},
    "fitness_get_weekly_report": {},
    "fitness_get_monthly_report": {},
}
```
`test_every_budgeted_tool_has_worst_case_arguments` (referenced in the file's own docstring)
will fail the build if a new tool is budgeted without a `WORST_CASE_ARGS` entry — this is
already-existing enforcement, not new code to write.

---

### `backend/tests/test_analytics_health.py` (NEW — test)

**Analog:** `backend/tests/test_analytics_bodyweight.py` (module not fully read this pass, but
its target module `bodyweight.py` was read in full — the test file mirrors that module's public
surface: `_window_average`, `_dedupe_by_day`, `get_body_weight_trend`, each floor boundary
tested on both sides, `insufficient_data` paths, frozen-clock fixtures per that module's own
docstring warning about live-data-dependent test flakiness). Structure test cases as: pure-function
unit tests for the fold/average helpers (no container), then container-backed tests for
`get_activity_trend`/`get_nutrition_trend` against seeded `HealthDailyMetric` rows.

---

### `backend/tests/test_analytics_reports.py` (NEW — test)

**Analog:** `backend/tests/test_analytics_recomposition.py` (target module `recomposition.py`
read in full — composition-heavy module, so its test file's likely shape is: seed workouts +
body measurements + program history, call `get_recomposition_status`, assert the composed
result's fields). `reports.py`'s test file follows the same "seed everything, call the composer
once, assert every section" shape, PLUS assert `build_narrative`'s determinism (same inputs →
byte-identical output, per the Security Domain table's Tampering mitigation).

---

## Shared Patterns

### Read-only session + resolve_user_id (applies to ALL new MCP tools)
**Source:** `backend/app/mcp/tools/_common.py:108–157`
```python
user_id = resolve_user_id(ctx)   # NEVER a tool parameter (ASVS V4, IDOR)
async with read_only_session(ctx) as session:   # PostgreSQL READ ONLY transaction
    ...
```

### `safe_tool` exception guard (applies to ALL new MCP tools)
**Source:** `backend/app/mcp/tools/_common.py:280–316`
```python
@safe_tool(degraded=_degraded_x)
async def fitness_get_x(ctx: Context[AppContext]) -> XResponse:
    ...
```
Every new tool needs its own `_degraded_x()` factory function (never a module-level constant),
returning `data_available=False` with every other field `None`/empty.

### `truncate()` for any bounded list inside the report
**Source:** `backend/app/mcp/tools/_common.py:319–330`
```python
capped, was_truncated, total = truncate(items, limit=MAX_REPORT_X)
# response model MUST carry both `was_truncated` and `total` alongside `capped`
```

### `build_freshness` — per-resource, never collapsed
**Source:** `backend/app/analytics/metadata.py:180–213`
```python
freshness=await build_freshness(session, user_id=user_id, resources=FRESHNESS_RESOURCES_REPORT)
```

### Anchor-day-via-tz-probe idiom (any NEW analytics function anchored on "today")
**Source:** `backend/app/analytics/bodyweight.py:198–208` (identical idiom also in
`progression.py:665–678` and `body_measurements.py:162–172`)
```python
probe_day = local_day(utc_now(), "UTC")
tz = (await resolve_window(session, user_id=user_id, start_day=probe_day, end_day=probe_day, snap_to_weeks=False)).tz
anchor = local_day(utc_now(), tz)
```

### Composition-only discipline for `reports.py`
**Source:** `backend/app/analytics/recomposition.py` module docstring (lines 1–2) and
`get_recomposition_status`'s own body (calls `get_body_weight_trend` + `get_exercise_trends` +
`get_weekly_volume`, computes nothing new beyond classification). Every number in
`analytics/reports.py`'s output must trace to an EXISTING analytics function's return value — no
new SQL, no new arithmetic, per D-02/D-03 and ARCHITECTURE.md's Anti-Pattern #9.

### `safe_tool`'s never-leak-internals rule (V8 Data Protection, applies everywhere)
**Source:** `backend/app/mcp/tools/_common.py:280–316` docstring — `str(exception)` can carry
the DSN; nothing escapes a tool body uncaught. Applies identically to the 4 new tool modules.

## No Analog Found

None. Every new file in this phase has a direct, recently-modified precedent already in the
codebase (per RESEARCH.md's own framing: "every 'new' capability in this phase either already
exists one tier down... or has a byte-for-byte precedent already in the codebase").

One GENUINE gap, not a missing analog but a missing FUNCTION: no existing analytics function
performs a cross-exercise PR scan (`get_personal_records` is single-exercise only — see Pitfall 1
above). If the plan chooses Option 1 (new arithmetic), that specific function has no direct
analog in `records.py` and should be modeled on `progression.py::get_plateaus`'s cross-exercise
aggregate-and-fold shape instead (documented above under `reports.py`'s Pattern Assignment).

## Metadata

**Analog search scope:** `backend/app/analytics/`, `backend/app/mcp/tools/`, `backend/app/core/`,
`backend/app/db/models/`, `backend/app/db/repositories/`, `backend/app/integrations/health_auto_export/`,
`backend/tests/`, `docs/`
**Files read in full this session:** `mcp/tools/summary.py`, `mcp/tools/_common.py`,
`mcp/tools/body.py`, `mcp/tools/programs.py`, `mcp/server.py`, `mcp/tools/schemas.py` (partial,
targeted sections), `analytics/bodyweight.py`, `analytics/body_measurements.py`,
`analytics/metadata.py`, `analytics/recomposition.py`, `analytics/records.py`,
`analytics/progression.py`, `analytics/schemas.py` (partial, targeted sections), `core/time.py`,
`db/models/health.py`, `db/repositories/sync_state.py` (grep), `integrations/health_auto_export/registry.py`,
`integrations/health_auto_export/backfill.py` (partial, `format_summary`), `docs/coaching-instructions.md`,
`backend/tests/test_coaching_doc.py` (partial), `backend/tests/test_mcp_tool_budget.py` (partial)
**Pattern extraction date:** 2026-09-04
