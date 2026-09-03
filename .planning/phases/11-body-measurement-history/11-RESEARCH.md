# Phase 11: Body Measurement History - Research

**Researched:** 2026-09-03
**Domain:** Analytics function + MCP tool for circumference/composition trend comparison (Python 3.13, SQLAlchemy 2.0 async, Pydantic 2, MCP Python SDK 2.0.0)
**Confidence:** HIGH (this is an internal-pattern-extension phase against an already-shipped codebase; every claim below is either read directly from the repo or verified against the live production database)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** BODY-03 (manual measurement write path) and BODY-04 (the per-column source-merge fix
  that path would trigger) are **dropped from Phase 11 and from v2.0 entirely** — not deferred to
  a later phase. The user's actual workflow is Hevy-only.
- **D-02:** Hevy's body-measurement sync (`backend/app/integrations/hevy/body.py`,
  `upsert_body_measurement`) already writes every one of the 17 `body_measurements` columns
  (weight + 16 circumference/composition fields) on every sync, with `source='hevy'`. **No
  ingestion-side code changes are needed in Phase 11.**
- **D-03:** Because no manual rows will ever be written under this scope, `_dedupe_by_day`'s
  row-grain "manual wins" precedence bug stays **dormant**. No source-precedence merge logic, no
  multi-source regression test.
- **D-04:** ROADMAP.md, REQUIREMENTS.md, PROJECT.md already rewritten to match this reversal.
  BODY-03/BODY-04 marked dropped.
- **D-05:** Calculation approach is **latest reading vs. earliest reading inside a fixed 90-day
  window** — NOT BODY-01's 7/14/30-day rolling-average design. Real coverage is too thin for a
  rolling-average shape to ever return an answer for anything but weight.
- **D-06:** The window is a **fixed 90 days** — not all-time, not 180 days.
- **D-07:** A **new, lower coverage floor** tailored to spot-check metrics is required — do not
  reuse `MEASURED_DAY_FLOORS` (3/5/10) unchanged. Extend the floor concept (`is_measurement_insufficient`/
  `build_measurement_coverage`), do not replace it. **Exact floor value(s) are Claude's Discretion.**
- **D-08:** The response must separately flag **staleness** — when the "latest" reading itself is
  old — distinct from "insufficient data entirely." A metric with 2+ readings that are all months
  old must not be presented as a fresh, current comparison.
- **D-09:** Architecture is **one generic metric-parameterized analytics function + one MCP
  tool**, not 16 near-duplicate functions. The metric selector must be a `StrEnum` (matching
  `PersonalRecordType`/`TrendVerdict`/`RecompositionStatus`), not a free string — an unrecognized
  metric name should raise, not silently return nothing.
- **D-10:** All 16 non-weight `body_measurements` columns are in scope: 14 circumference fields
  plus `fat_percent` and `lean_mass_kg`.

### Claude's Discretion

- Exact numeric floor(s) for "sufficient data" on spot-check metrics (D-07) — calibrate against
  live data. A floor of "0 readings" must never be treated as sufficient.
- Exact MCP tool name (e.g. `fitness_get_body_measurement_trend`) and its Pydantic response
  schema field names.
- Whether the new function lives in `bodyweight.py` (renamed/extended) or a new sibling module.
- Whether `fitness_get_training_summary`/`fitness_get_recomposition_status` should reference the
  new tool's existence anywhere, or stay fully standalone — leaning standalone.

### Deferred Ideas (OUT OF SCOPE)

- **Manual measurement entry** (formerly BODY-03) and its source-merge fix (formerly BODY-04) —
  dropped, not deferred to a specific future phase.
- **CLI UX decisions made before the scope reversal** (per-field flags, CSV bulk import, sanity
  validation) — captured for the record only; moot unless manual entry is ever revived.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| BODY-05 | System calculates trend/comparison analytics across circumference and composition measurements, not weight-only as today. Latest-vs-earliest in a 90-day window, staleness flagged separately from insufficient data. | Full architecture below: new `analytics/body_measurements.py` module, `BodyMeasurementMetric` StrEnum, extended `MEASURED_DAY_FLOORS`, new `fitness_get_body_measurement_trend` MCP tool. Floor and staleness threshold calibrated against live production data (see "Live Data Coverage Audit"). |

(BODY-03, BODY-04 explicitly dropped per CONTEXT.md D-01 — not addressed by this research.)
</phase_requirements>

## Summary

Phase 11's remaining scope (BODY-05 only) is a straight structural extension of the exact pattern
`fitness_get_body_weight_trend` (BODY-01, Phase 6) already established, with one deliberate
divergence: the calculation is a two-point latest-vs-earliest comparison over a fixed 90-day
window, not a rolling average, because live production data proves the rolling-average shape
would return `insufficient_data` for every one of the 16 metrics almost all the time. No schema
migration, no ingestion change, no new dependency — every table, sync path, and MCP scaffolding
piece this phase needs already exists and already ships weight data through an identical pipeline.

The one number CONTEXT.md leaves to research/planning — the coverage floor — is now calibrated
against a live `psql` query against the production database (see below): even `waist_cm`, the
best-covered non-weight metric in the account, has only **2** readings in the trailing 90 days as
of today (2026-09-03), and 13 of the 16 in-scope columns have **zero** readings in the table's
entire ~4-year history. A floor of anything above 2 would make this tool return
`insufficient_data` for essentially every real call. **Recommended floor: 2** (the mathematical
minimum for a two-point comparison to mean anything at all, and it is also what the best-tracked
real metric currently clears). This is an `[ASSUMED]` design choice — no external authority
governs it — but it is grounded in a live measurement, not a guess.

**Primary recommendation:** Add a new sibling module `app/analytics/body_measurements.py`
containing one generic `get_body_measurement_trend(session, *, user_id, metric)` function; add
`BodyMeasurementMetric` (StrEnum) and `BodyMeasurementTrendResult` to `app/analytics/schemas.py`;
extend (never replace) `MEASURED_DAY_FLOORS` in `app/analytics/metadata.py` with a `{90: 2}`
entry and add one new column-generic `earliest_metric_measurement_at` helper beside the existing
weight-only `earliest_measurement_at`; add one new MCP tool `fitness_get_body_measurement_trend`
in `app/mcp/tools/body.py`, registered in `app/mcp/server.py` exactly like its BODY-01 sibling.
Six existing structural/regression tests (detailed below) must each get one new entry or they
will fail the moment the tool is registered — this is not optional cleanup, it is how this
codebase enforces "no undocumented tool" and "no unbudgeted tool" as hard gates.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Metric selector validation (reject unknown metric names) | API / Backend (MCP tool input schema, Pydantic `StrEnum`) | — | D-09 requires raising on an unrecognized name; the MCP SDK's Pydantic-derived `inputSchema` enforces this BEFORE the tool body runs — no application-level branch needed |
| Two-point (latest vs. earliest) comparison calculation | API / Backend (`app/analytics/body_measurements.py`) | — | Pure SQL + Python fold, same tier as every other `app/analytics/` function; never in the MCP tool layer (composition only) |
| Coverage floor / staleness classification | API / Backend (`app/analytics/metadata.py`) | — | Shared `MEASURED_DAY_FLOORS` mapping and `MeasurementCoverage` type already live here; this phase adds to that one place, not a parallel one |
| Response shaping / MCP wire contract | API / Backend (`app/mcp/tools/schemas.py`, `app/mcp/tools/body.py`) | — | Compose-never-restate rule: the MCP response embeds the analytics result verbatim, exactly like `BodyWeightTrendResponse` |
| Persistence of the underlying data | Database / Storage (`body_measurements` table) | — | Already populated by Hevy sync (Phase 7); zero schema or ingestion changes this phase |
| Claude-facing documentation of the new tool | N/A (docs) | — | `docs/coaching-instructions.md` — required by a live drift-guard test (`test_coaching_doc.py`), not optional polish |

## Standard Stack

No new dependencies. This phase adds application code only, using packages already in
`pyproject.toml`/`uv.lock`:

| Library | Version (installed, verified via `.venv`) | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLAlchemy | 2.0.x (async) | Query the `body_measurements` table generically by column | Already the project's only ORM/query layer |
| Pydantic | 2.x | `StrEnum`-based tool input schema, response models | Already how every MCP tool/analytics result is typed |
| `mcp` (Python SDK) | 2.0.0 | Tool registration, auto-generated `inputSchema`/`outputSchema` from a `StrEnum`-typed parameter | Verified locally: a `StrEnum` field inside a Pydantic model produces a proper `{"enum": [...], "type": "string"}` JSON Schema fragment (see Code Examples) — the SDK builds `inputSchema` the same way |
| pytest / pytest-asyncio / time-machine / testcontainers[postgres] | already pinned | New unit + integration tests, same patterns as `test_analytics_bodyweight.py` | No alternative considered; this is the only test stack in the repo |

**Installation:** none required.

**Version verification:** Not applicable — no new package. Verified instead that `StrEnum` inside
a Pydantic `BaseModel` correctly emits a JSON Schema `enum` (see Code Examples §1), which is the
load-bearing mechanism D-09's "must raise on an unknown metric" leans on.

## Architecture Patterns

### System Architecture Diagram

```
Claude (model)
   │  calls tool with metric="waist_cm" (StrEnum-constrained by inputSchema)
   ▼
MCP transport (POST /mcp, Streamable HTTP)
   │
   ▼
fitness_get_body_measurement_trend(ctx, metric)      [app/mcp/tools/body.py]
   │  @safe_tool(degraded=...)  — any exception → degraded payload, never raw text to Claude
   │  resolve_user_id(ctx)      — server-side, never from tool args
   │  read_only_session(ctx)    — Postgres READ ONLY transaction
   ▼
get_body_measurement_trend(session, user_id, metric)  [app/analytics/body_measurements.py]
   │  1. resolve local anchor day (via resolve_window, same throwaway-probe trick as BODY-01)
   │  2. SELECT measured_on, <column> FROM body_measurements
   │        WHERE user_id=..., <column> IS NOT NULL,
   │              measured_on BETWEEN anchor-89 AND anchor
   │        ORDER BY measured_on
   │  3. fold: measured_days = len(rows); earliest = rows[0]; latest = rows[-1]
   │  4. earliest_metric_measurement_at(session, user_id, column)  [app/analytics/metadata.py, NEW]
   │  5. build_measurement_coverage(window_days=90, measured_days, earliest_ever)
   │        — reuses existing MeasurementCoverage type; floor comes from
   │          MEASURED_DAY_FLOORS[90] (NEW entry, added not replacing 7/14/30)
   │  6. delta = latest.value - earliest.value  IFF NOT coverage.insufficient_data
   │  7. is_stale = (anchor - latest.measured_on).days > MEASUREMENT_STALE_AFTER_DAYS
   │        — computed whenever ANY reading exists in the window, independent of the floor
   ▼
BodyMeasurementTrendResult                              [app/analytics/schemas.py, NEW]
   │  embedded WHOLE into
   ▼
BodyMeasurementTrendResponse                             [app/mcp/tools/schemas.py, NEW]
   │  data_available: bool, trend: BodyMeasurementTrendResult | None
   ▼
structured_content back to Claude
```

### Recommended Project Structure

```
backend/app/analytics/
├── bodyweight.py          # UNTOUCHED — BODY-01, rolling averages, weight only
├── body_measurements.py   # NEW — BODY-05, one generic latest-vs-earliest function
├── metadata.py            # EXTENDED — new floor entry + one new helper function
├── schemas.py             # EXTENDED — new StrEnum + new result model

backend/app/mcp/tools/
├── body.py                 # EXTENDED — new tool sits beside fitness_get_body_weight_trend
├── schemas.py               # EXTENDED — new response wrapper

backend/app/mcp/
├── server.py                # EXTENDED — import + register the new tool

backend/tests/
├── test_analytics_bodyweight.py         # UNTOUCHED
├── test_analytics_body_measurements.py  # NEW — mirrors bodyweight's test file, own assertions
├── test_mcp_tools.py                    # EXTENDED — MINIMAL_TOOL_ARGUMENTS + 1 behavioral test
├── test_mcp_tool_schemas.py             # EXTENDED — EXPECTED_TOOLS
├── test_mcp_tool_budget.py              # EXTENDED — BUDGETS + WORST_CASE_ARGS
├── conftest.py                          # EXTENDED — GoldenBuilder.body_measurement() needs
                                          #   new kwargs for non-weight columns (see Pitfall 1)

docs/
├── coaching-instructions.md  # EXTENDED — new tool row, or a drift-guard test fails (see Pitfall 2)
```

### Pattern 1: Generic column selection via `StrEnum` value == column name

**What:** `BodyMeasurementMetric` StrEnum members' *values* are set to the exact
`BodyMeasurement` column names (`"waist_cm"`, `"fat_percent"`, etc.), so the analytics function
resolves the SQLAlchemy attribute with `getattr(BodyMeasurement, metric.value)` — one line, no
hand-maintained second name→column mapping that could drift from `db/models/body.py`.

**When to use:** Exactly this phase's D-09 requirement — one function covering N near-identical
columns without N near-duplicate functions or an inline dict a future column rename could miss.

**Example (verified locally against installed Pydantic 2, this session):**
```python
from enum import StrEnum
from pydantic import BaseModel, Field
from typing import Annotated

class BodyMeasurementMetric(StrEnum):
    WAIST_CM = "waist_cm"
    NECK_CM = "neck_cm"
    # ... 14 more, one per non-weight column

class Args(BaseModel):
    metric: Annotated[BodyMeasurementMetric, Field(description="which metric")]

# Args.model_json_schema() confirmed to emit:
# {"$defs": {"BodyMeasurementMetric": {"enum": ["waist_cm", "neck_cm", ...], "type": "string"}}, ...}
```
This is the exact mechanism `mcp 2.0.0` uses to build `inputSchema` from a tool function's type
hints (per `_common.py`'s own documented claim that the SDK "builds the tool's schema from
`fn.__doc__`, the return annotation and `inspect.signature`"). A caller passing
`metric="not_a_real_column"` is therefore rejected by the SDK's own schema validation before the
tool body ever runs — satisfying D-09's "must raise on an unrecognized metric" with zero
application code.

```python
# app/analytics/body_measurements.py
column = getattr(BodyMeasurement, metric.value)
stmt = (
    select(BodyMeasurement.measured_on, column)
    .where(
        BodyMeasurement.user_id == user_id,
        column.is_not(None),
        BodyMeasurement.measured_on >= anchor - dt.timedelta(days=WINDOW_DAYS - 1),
        BodyMeasurement.measured_on <= anchor,
    )
    .order_by(BodyMeasurement.measured_on)
)
```

### Pattern 2: Extend the coverage-floor mapping, never replace it (D-07)

**What:** `MEASURED_DAY_FLOORS` in `app/analytics/metadata.py` is currently
`MappingProxyType({7: 3, 14: 5, 30: 10})`. Add a fourth entry, `90: <floor>`, in the same
structure. `is_measurement_insufficient(window_days=90, measured_days=n)` and
`build_measurement_coverage(window_days=90, ...)` then work for BODY-05 with **zero** changes to
either function's body — they already key off `MEASURED_DAY_FLOORS.get(window_days)` generically.

**When to use:** Any time a new window length needs its own floor. This is the sanctioned
extension point; do not fork `is_measurement_insufficient`.

```python
# app/analytics/metadata.py — the only line this pattern requires changing
MEASURED_DAY_FLOORS: Mapping[int, int] = MappingProxyType({7: 3, 14: 5, 30: 10, 90: 2})
```

### Pattern 3: A new column-generic "earliest ever" helper, sibling to the weight-only one

**What:** `earliest_measurement_at` (existing, in `metadata.py`) is hardcoded to
`BodyMeasurement.weight_kg IS NOT NULL` implicitly (it selects `min(measured_on)` with no column
filter at all — it actually returns the earliest row of ANY kind, not weight-specific; re-read
below). A new metric needs "earliest day THIS METRIC was ever recorded," which needs a
column-scoped `WHERE <column> IS NOT NULL` predicate the existing function does not have.

**Correction to research goal #2's assumption:** `earliest_measurement_at` as written today has
**no column filter at all** — it is `select(func.min(BodyMeasurement.measured_on)).where(user_id
== ...)`, full stop. It happens to be correct for BODY-01 only because every real row that exists
today also has `weight_kg` populated (D-02: Hevy writes all 17 columns per sync date, though many
are NULL). For BODY-05, this matters: a metric's true "earliest ever" must filter on that
specific column being non-null, or a waist-only historical row (if one ever existed) would be
missed and an all-columns row would be over-counted. **Do not reuse `earliest_measurement_at`
as-is for BODY-05 — add a new, column-parameterized sibling function.**

```python
# app/analytics/metadata.py — NEW function, alongside earliest_measurement_at
async def earliest_metric_measurement_at(
    session: AsyncSession, *, user_id: uuid.UUID, column: InstrumentedAttribute
) -> dt.date | None:
    """The user's oldest synced reading of ONE specific metric, across all time.

    Sibling to earliest_measurement_at, not a replacement: that function is BODY-01's and stays
    weight-shaped. This one is column-generic because BODY-05 covers 16 different columns, each
    with its own (usually much sparser) history.
    """
    result: dt.date | None = await session.scalar(
        select(func.min(BodyMeasurement.measured_on)).where(
            BodyMeasurement.user_id == user_id, column.is_not(None)
        )
    )
    return result
```

### Anti-Patterns to Avoid

- **Reusing `bodyweight.py`'s rolling-average shape "for consistency":** D-05 explicitly forbids
  this. Live data makes it impossible — 13 of 16 metrics have zero rows ever; a 3/5/10-measured-day
  floor never clears for them, and even `waist_cm` (the best-covered) fails a 30-day floor of 10
  most of the time (16 readings across ~1,450 days, median 14-day gap but with a real 119-day
  gap on record).
- **16 separate analytics functions / 16 separate MCP tools:** D-09 forbids this explicitly.
- **A free-string `metric` parameter with an if/elif dispatch:** D-09 requires a `StrEnum`; a
  free string can't be validated by the MCP SDK's own schema layer and would need a hand-rolled
  "unknown metric" branch that duplicates what `StrEnum` gets for free.
- **Treating `insufficient_data=True` and `is_stale=True` as mutually exclusive or as the same
  flag:** D-08 requires them to be independent. A metric can have 2+ readings (not insufficient)
  that are both 4 months old (stale) — both must be representable simultaneously. A metric can
  also have 0 readings in the window (insufficient, `is_stale` should read `False`/not applicable
  since there is no "latest" to be stale) or exactly 1 reading (insufficient for a *comparison*,
  but that 1 reading's own age is still worth surfacing — see the Result Shape recommendation).
- **Quantizing the delta to extra decimal places (bodyweight.py's `_WEIGHT_QUANTUM` pattern):**
  Do not copy this. The source columns are already `Numeric(6,2)`/`Numeric(5,2)`; a plain
  `Decimal` subtraction of two 2-decimal-place values is already exact at 2 decimal places. The
  `_WEIGHT_QUANTUM = Decimal("0.001")` trick in `bodyweight.py` exists specifically because that
  module *averages* N readings (introducing new precision); BODY-05 never averages, so there is
  nothing to over-round.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Validating the metric name against the 16 allowed columns | A manual `if metric not in {...}: raise` check inside the tool body | A `StrEnum`-typed tool parameter | The MCP SDK already rejects an invalid enum value at the schema layer (verified this session); duplicating that check in Python is a second place the list of 16 names can drift from `db/models/body.py` |
| "Is this window's data trustworthy" | A bespoke boolean inline in the new module | `build_measurement_coverage`/`is_measurement_insufficient` from `metadata.py`, extended with a `{90: floor}` entry | This is precisely the sanctioned extension point (D-07); forking it creates two coverage concepts that can silently disagree |
| Read-only DB session, exception leak guard, response truncation bookkeeping | Anything custom | `read_only_session`, `safe_tool`, `resolve_user_id` from `app/mcp/tools/_common.py` | Already the mandatory cross-cutting layer every one of the other 13 tools uses; this phase adds a 14th, not a new pattern |

**Key insight:** Every piece of infrastructure this phase needs (read-only transactions, coverage
floors, freshness envelopes, StrEnum-based closed choices, response truncation, exception
guarding) already exists in this codebase from Phases 4–6 and is designed to be extended by
adding entries/functions, not by forking files. The actual net-new code is small: one query
function, one new StrEnum, one new result/response pair, one new tool wrapper, one registration
line, and the mandatory test-suite touch points below.

## Live Data Coverage Audit

Queried directly against the production Neon Postgres instance (`DATABASE_URL` in `.env`) via
`psql`, 2026-09-03. **[VERIFIED: production database, live query]**

### All-time coverage per column (127 total `body_measurements` rows, 2022-09-14 → 2026-09-03)

| Column | Non-null rows (all time) | In-scope? |
|---|---|---|
| `weight_kg` | 127 | BODY-01 only, unaffected by this phase |
| `waist_cm` | 16 | Yes — best-covered non-weight metric by far |
| `right_bicep_cm` | 4 | Yes |
| `left_bicep_cm` | 2 | Yes |
| `lean_mass_kg`, `fat_percent`, `neck_cm`, `shoulder_cm`, `chest_cm`, `left_forearm_cm`, `right_forearm_cm`, `abdomen_cm`, `hips_cm`, `left_thigh_cm`, `right_thigh_cm`, `left_calf_cm`, `right_calf_cm` | **0** | Yes — 13 of 16 in-scope columns have never once been recorded in this account |

### `waist_cm` gap statistics (the one column with enough data to characterize)

16 readings, min gap 3 days, max gap **119 days**, mean gap 34.5 days, **median gap 14 days**.

### Readings inside the trailing 90-day window as of today (2026-09-03)

| Metric | Readings in last 90 days | Latest reading | Days since latest |
|---|---|---|---|
| `weight_kg` | 25 | 2026-09-03 | 0 |
| `waist_cm` | 2 | 2026-09-03 | 0 |
| `right_bicep_cm` | 2 | 2026-09-03 | 0 |

**Implication for the coverage floor (D-07):** A floor of 3+ (matching BODY-01's 7-day floor)
would make `fitness_get_body_measurement_trend(metric="waist_cm")` — the single best-case
call this tool will ever receive on this account's real data — return `insufficient_data=True`
today. **Recommended floor: 2.** This is simultaneously (a) the mathematical minimum for a
latest-vs-earliest comparison to be meaningful at all (1 reading has no "earliest" distinct from
"latest"), and (b) exactly what the best-covered real metric clears right now. A floor of 2 will
still report `insufficient_data=True` for 13 of the 16 in-scope metrics on this account's current
data — that is the honest, correct answer (D-07 explicitly forbids treating 0 readings as
sufficient), not a design failure.

**Implication for staleness (D-08):** No authoritative source governs this threshold —
`[ASSUMED]`, flagged in the Assumptions Log below. Recommendation: **30 days**. Rationale: this is
roughly 2x the real median gap (14 days) between `waist_cm` readings, so a metric the user is
actively tracking at its historical cadence will not spuriously flag as stale, while a metric
that has gone quiet for a meaningful fraction of the 90-day window will. This is a judgment call,
not a measured fact — planning should treat it as adjustable, and it is exactly the kind of
number `BodyMeasurementTrendResult` should echo back as a field (matching the "every response
echoes its own thresholds" convention already established by `PlateauResult`), not hide in a
comment.

## Recommended Result Shape

Following the mutually-exclusive value/reason convention (`ProgressionPoint.estimated_1rm_kg`/
`no_estimate_reason`) where it applies, and the "every threshold is a field" convention
(`PlateauResult`):

```python
# app/analytics/schemas.py — NEW
class BodyMeasurementMetric(StrEnum):
    """BODY-05. Values are the EXACT BodyMeasurement column names (db/models/body.py) — the
    analytics layer resolves the SQLAlchemy attribute via getattr(BodyMeasurement, metric.value),
    so this enum and the ORM model can never silently drift apart on a name."""
    NECK_CM = "neck_cm"
    SHOULDER_CM = "shoulder_cm"
    CHEST_CM = "chest_cm"
    LEFT_BICEP_CM = "left_bicep_cm"
    RIGHT_BICEP_CM = "right_bicep_cm"
    LEFT_FOREARM_CM = "left_forearm_cm"
    RIGHT_FOREARM_CM = "right_forearm_cm"
    ABDOMEN_CM = "abdomen_cm"
    WAIST_CM = "waist_cm"
    HIPS_CM = "hips_cm"
    LEFT_THIGH_CM = "left_thigh_cm"
    RIGHT_THIGH_CM = "right_thigh_cm"
    LEFT_CALF_CM = "left_calf_cm"
    RIGHT_CALF_CM = "right_calf_cm"
    FAT_PERCENT = "fat_percent"
    LEAN_MASS_KG = "lean_mass_kg"


class BodyMeasurementTrendResult(_AnalyticsModel):
    """BODY-05. Latest reading vs. earliest reading inside a fixed 90-day window (D-05, D-06).

    `latest_value`/`latest_measured_on` are populated whenever AT LEAST ONE reading exists in the
    window, independent of `coverage.insufficient_data` -- a single stale reading is still worth
    surfacing on its own (D-08). `earliest_value`/`earliest_measured_on`/`delta_value` are
    populated ONLY when `coverage.insufficient_data` is False: an "earliest" equal to the single
    "latest" reading would silently misreport delta=0 as "no change" rather than "one data point".
    """
    metric: BodyMeasurementMetric
    window_days: int              # 90, echoed (D-06's own "every threshold is a field" rule)
    anchor_day: dt.date
    coverage: MeasurementCoverage  # window_days=90, floor from MEASURED_DAY_FLOORS[90]
    latest_value: Decimal | None
    latest_measured_on: dt.date | None
    earliest_value: Decimal | None
    earliest_measured_on: dt.date | None
    delta_value: Decimal | None    # latest - earliest; None iff coverage.insufficient_data
    is_stale: bool
    days_since_latest_reading: int | None
    stale_after_days: int          # the threshold itself, echoed (D-08 + PlateauResult convention)
    freshness: FreshnessMetadata
```

```python
# app/mcp/tools/schemas.py — NEW
class BodyMeasurementTrendResponse(_McpModel):
    """BODY-05 for MCP. `trend` is the analytics result verbatim, matching BodyWeightTrendResponse."""
    data_available: bool
    trend: BodyMeasurementTrendResult | None
```

## Code Examples

### The MCP tool (mirrors `fitness_get_body_weight_trend` exactly, plus one parameter)

```python
# app/mcp/tools/body.py — NEW, sits beside fitness_get_body_weight_trend
from typing import Annotated
from pydantic import Field

from app.analytics.body_measurements import get_body_measurement_trend
from app.analytics.schemas import BodyMeasurementMetric


def _degraded_measurement_trend() -> BodyMeasurementTrendResponse:
    return BodyMeasurementTrendResponse(data_available=False, trend=None)


@safe_tool(degraded=_degraded_measurement_trend)
async def fitness_get_body_measurement_trend(
    ctx: Context[AppContext],
    metric: Annotated[
        BodyMeasurementMetric,
        Field(description="Which circumference or composition metric to compare, e.g. 'waist_cm'."),
    ],
) -> BodyMeasurementTrendResponse:
    """Latest-vs-earliest 90-day comparison for one circumference or composition metric
    (14 circumference fields, plus fat_percent and lean_mass_kg) — never weight, which
    fitness_get_body_weight_trend already covers.
    """
    user_id = resolve_user_id(ctx)
    async with read_only_session(ctx) as session:
        trend = await get_body_measurement_trend(session, user_id=user_id, metric=metric)
    return BodyMeasurementTrendResponse(data_available=True, trend=trend)
```

### Registration (`app/mcp/server.py`)

```python
from app.mcp.tools.body import (
    fitness_get_body_measurement_trend,   # NEW
    fitness_get_body_weight_trend,
    fitness_get_recomposition_status,
)
# ... inside _TOOLS tuple, alongside the existing body-weight-trend entry:
(
    fitness_get_body_measurement_trend,
    "Latest-vs-earliest 90-day comparison for one circumference or composition metric, "
    "with staleness and coverage.",
),
```

## Common Pitfalls

### Pitfall 1: `GoldenBuilder.body_measurement()` cannot seed non-weight columns today

**What goes wrong:** The existing test fixture builder
(`backend/tests/conftest.py:450-487`) — `async def body_measurement(self, *, measured_on,
weight_kg, source="hevy", user_id=DEFAULT_USER_ID)` — has **no parameter for any of the 16
non-weight columns**. Every existing call site only ever sets `weight_kg`. Writing a new
integration test against `get_body_measurement_trend` for, say, `waist_cm` is impossible with the
current fixture signature.

**Why it happens:** The builder was written for BODY-01 (Phase 6), before BODY-05 existed as a
concept; nobody needed to seed a circumference value yet.

**How to avoid:** Extend `GoldenBuilder.body_measurement()` with new optional keyword parameters
covering at least two representative non-weight columns (recommend one circumference field, e.g.
`waist_cm`, and one composition field, e.g. `fat_percent`, to prove the generic function truly
generalizes across the two SQLAlchemy column types/precisions involved — `Numeric(6,2)` vs.
`Numeric(5,2)`) — or a single generic `**metric_values: Decimal | None` kwarg mapped onto the
insert. Either shape works; the plan must pick one and specify the exact new signature, because
every BODY-05 integration test depends on it existing first.

**Warning signs:** Any BODY-05 plan wave that writes integration tests without first touching
`conftest.py` will fail immediately at fixture-call time, not at assertion time — a clear signal
this was missed.

### Pitfall 2: The coaching-doc drift guard will fail the moment the tool is registered, regardless of which phase "owns" documenting it

**What goes wrong:** `backend/tests/test_coaching_doc.py::test_every_registered_tool_appears_in_the_document`
asserts, structurally, that every tool name in the live MCP registry (minus the `fitness_ping`
canary) appears somewhere in `docs/coaching-instructions.md`. COACH-03 (formally: "document the
v2.0 tools... consistent with the existing tool-registry drift-guard test") is assigned to Phase
13 in REQUIREMENTS.md's traceability table — but the test itself does not know or care which
phase is "supposed" to document a tool. It runs against whatever is currently registered.

**Why it happens:** The test was written as a structural, phase-agnostic guard (by design — see
its own docstring: "A tool Claude is never told about is a tool Claude will not reach for").
Registering `fitness_get_body_measurement_trend` in Phase 11 without adding at least one mention
of it to `docs/coaching-instructions.md` breaks this test in CI/local runs immediately, weeks
before Phase 13 would otherwise touch that file.

**How to avoid:** Phase 11's plan must include a minimal addition to
`docs/coaching-instructions.md` — at minimum, one row in the "Which tool answers which question"
table (mirroring the `fitness_get_body_weight_trend` row at line 63) and one example question
near line 120. This does not need to be COACH-03's full treatment (which will likely expand and
polish it in Phase 13); it only needs to satisfy the drift guard's "nothing missing" assertion.
**A companion guard, `test_every_tool_the_document_names_exists_in_the_registry`, means the tool
name written into the doc must be spelled EXACTLY as registered** (`fitness_get_body_measurement_trend`
or whatever exact name the plan locks in) — a typo fails the opposite direction.

**Warning signs:** `pytest backend/tests/test_coaching_doc.py` failing with "COACH-01 violated:
...which the live MCP registry does not serve" (typo direction) or "...all twelve analytics tools
are documented" / listing the new tool as undocumented (missing-entry direction).

### Pitfall 3: Three more structural regression tests must be touched, or they fail on the next full-suite run

**What goes wrong:** Beyond the coaching doc, three more tests assert an exact, hand-maintained
set/mapping of tool names that a new registration will violate:

1. `backend/tests/test_mcp_tool_schemas.py` — `EXPECTED_TOOLS` frozenset (currently 13 names,
   asserted exactly via `test_tool_registry_is_exactly_the_thirteen`).
2. `backend/tests/test_mcp_tool_budget.py` — `BUDGETS` dict and `WORST_CASE_ARGS` dict, both
   asserted to cover exactly the registered tool set
   (`test_every_registered_tool_has_a_budget`). The new tool needs a measured byte budget (follow
   the file's own methodology: measure `structured_content` + text content together at the
   worst-case argument, add ~30% headroom — do not guess a number).
3. `backend/tests/test_mcp_tools.py` — `MINIMAL_TOOL_ARGUMENTS` dict, asserted exactly via
   `test_every_tool_degradation_leaks_nothing` (this dict is also imported and reused by
   `test_secret_redaction.py`, so one edit here covers both).

**Why it happens:** All three are deliberate "a fourteenth tool must not be silently unmeasured/
undocumented/uncovered" guards — the same defensive pattern as the coaching-doc test, applied to
three different concerns (registry shape, response-size budget, exception-leak coverage).

**How to avoid:** The plan must explicitly list all four files (this pitfall's three, plus the
coaching doc) as touch points in the same wave that registers the new tool, not as an
afterthought. None of the four requires new test *logic* to be invented — each is a one-entry
addition to an existing table/dict, following the existing entry's exact shape for the sibling
`fitness_get_body_weight_trend` tool.

**Warning signs:** Running the full test suite (not just a new test file) after implementing the
tool and getting failures with messages like "Registered but unexpected: {...}" or "Registered but
unbudgeted: {...}" — these are the intended fast-fail signal, not surprises to debug.

### Pitfall 4: `earliest_measurement_at` (existing) is NOT what it sounds like for a per-metric question

**What goes wrong:** Research goal #2 asked to extract `earliest_measurement_at`'s exact
behavior. On inspection, it has **no column filter** — it returns the earliest `measured_on` for
ANY row belonging to the user, not "earliest row where weight was recorded" and certainly not
"earliest row where `waist_cm` was recorded." It happens to read correctly for BODY-01 today only
because, on this account, every synced row also carries a weight (Hevy writes `weight_kg` on
essentially every sync). For BODY-05, reusing this function as-is for, say, `waist_cm`'s "earliest
ever" would be wrong the moment a future row exists with some other field but not `waist_cm`.

**Why it happens:** It was written for exactly one caller (BODY-01) under an assumption that held
for that caller's specific column but was never actually asserted as an invariant of the table.

**How to avoid:** Add the new `earliest_metric_measurement_at(session, *, user_id, column)`
sibling function (see Pattern 3 above) rather than repurposing the existing one. Do not modify
`earliest_measurement_at` itself — CONTEXT.md's canonical refs are explicit that BODY-01 "must
remain unmodified/unregressed."

**Warning signs:** A test that seeds a row with `waist_cm` set but `weight_kg` NULL, then asserts
`earliest_metric_measurement_at` for `waist_cm` returns that row's date while
`earliest_measurement_at` (BODY-01's) does not have to — this is exactly the scenario that would
catch a wrongly-reused function.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"`), config in `pyproject.toml` `[tool.pytest.ini_options]` |
| Config file | `pyproject.toml` (`testpaths = ["backend/tests"]`, `pythonpath = ["backend"]`) |
| Quick run command | `pytest -m "not integration" backend/tests/test_analytics_body_measurements.py` (pure-Python business-rule tests, no container) |
| Full suite command | `pytest backend/tests` (runs `integration`-marked tests against `testcontainers[postgres]`) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| BODY-05 | Two-point delta computed correctly, exact `Decimal` | unit | `pytest backend/tests/test_analytics_body_measurements.py -k delta -x` | ❌ Wave 0 |
| BODY-05 | Floor (`{90: 2}`) gates `insufficient_data` at the boundary | integration | `pytest -m integration backend/tests/test_analytics_body_measurements.py -k floor -x` | ❌ Wave 0 |
| BODY-05 | `is_stale`/`days_since_latest_reading` computed independent of `insufficient_data` (2+ old readings; 1 old reading; 1 fresh reading; 0 readings) | integration | `pytest -m integration backend/tests/test_analytics_body_measurements.py -k stale -x` | ❌ Wave 0 |
| BODY-05 | Unrecognized metric name rejected by the MCP tool's own input schema (not a 500, not a silent empty result) | integration (MCP `Client`) | `pytest -m integration backend/tests/test_mcp_tools.py -k body_measurement_trend -x` | ❌ Wave 0 |
| BODY-05 | Existing BODY-01 tool (`fitness_get_body_weight_trend`) unchanged — success criterion #3 | integration | `pytest -m integration backend/tests/test_analytics_bodyweight.py backend/tests/test_mcp_tools.py -k body_weight_trend -x` | ✅ (already exists, run as a regression check, no new file needed) |
| — (structural) | New tool appears in `EXPECTED_TOOLS`, `BUDGETS`, `WORST_CASE_ARGS`, `MINIMAL_TOOL_ARGUMENTS`, and `docs/coaching-instructions.md` | unit/integration (schema/doc drift guards) | `pytest backend/tests/test_mcp_tool_schemas.py backend/tests/test_mcp_tool_budget.py backend/tests/test_coaching_doc.py` | ✅ (existing tests, will fail until the 4 touch points from Pitfall 2/3 are made) |

### Sampling Rate
- **Per task commit:** `pytest -m "not integration" backend/tests/test_analytics_body_measurements.py`
- **Per wave merge:** `pytest backend/tests` (full suite, container-backed)
- **Phase gate:** Full suite green, including the four structural drift-guard files listed above,
  before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `backend/tests/test_analytics_body_measurements.py` — new file, mirrors
  `test_analytics_bodyweight.py`'s structure (pure-Python dedupe/window tests with no marker,
  integration tests with `@pytest.mark.integration` + `time_machine.travel`), covers REQ BODY-05
- [ ] `backend/tests/conftest.py` — `GoldenBuilder.body_measurement()` needs new kwargs for at
  least one circumference column and one composition column (Pitfall 1) — every integration test
  above depends on this
- [ ] No new test framework install needed — pytest/testcontainers/time-machine already pinned

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Recommended coverage floor of **2** measured days for the 90-day window | Live Data Coverage Audit, Recommended Result Shape | If too low, a single reading could pass as a "trend" for a metric where the delta is really noise; if too high (anything ≥3), the tool returns `insufficient_data` for nearly every real call on the only account this project currently serves, defeating BODY-05's purpose. Low risk either way since it's an easily-tunable constant, but it is a genuine design judgment, not a measured fact. |
| A2 | Recommended staleness threshold of **30 days** since the latest in-window reading | Live Data Coverage Audit, Recommended Result Shape | No authority governs "how old is too old" for a tape-measure reading; a wrong number either over-flags actively-tracked metrics as stale or under-flags genuinely abandoned tracking. Directly affects D-08's success criterion #2. Should be confirmed with the user or left clearly adjustable (echoed as `stale_after_days` on the response, per the recommended shape) rather than buried. |
| A3 | Centimetre unit for all 14 circumference columns | Inherited from `db/models/body.py`'s own docstring ("assumption Hevy does not document") | Pre-existing assumption from Phase 7, not introduced by this research; unaffected by BODY-05's calculation, since a two-point delta is unit-agnostic — it is only wrong if Hevy's actual unit differs, which is already a known open item from an earlier phase, not new here. |

**If this table is empty:** N/A — see entries above; A3 is inherited/pre-existing rather than
newly introduced by this phase's research.

## Open Questions

1. **Exact staleness threshold (A2) and exact floor (A1) — final numbers**
   - What we know: Both must be ≥ the mathematical/logical minimum (floor ≥ 2; staleness > 0
     days), and both are calibrated against real production data in this document.
   - What's unclear: Whether the user has an intuition for "how old is too old" that differs from
     the 30-day recommendation — this is exactly the kind of number CONTEXT.md flagged as
     Claude's Discretion precisely because no external standard exists.
   - Recommendation: Plan should lock in the numbers above (floor=2, stale_after_days=30) as
     defaults, since both are echoed as response fields (`stale_after_days`) rather than
     hardcoded invisibly — a future adjustment is a one-constant change, not a schema migration.

2. **Exact tool name**
   - What we know: CONTEXT.md's discretion note suggests `fitness_get_body_measurement_trend`;
     this document uses that name throughout for concreteness.
   - What's unclear: Nothing blocking — this is a naming call with no functional consequence, and
     changing it later only touches the same handful of files this research already enumerates
     (registry, schemas test, budget test, minimal-args test, coaching doc).
   - Recommendation: Lock in `fitness_get_body_measurement_trend` unless the planner has a
     stronger alternative; it matches the `fitness_get_body_weight_trend` naming convention
     exactly (singular metric, `_trend` suffix).

## Environment Availability

Skipped — this phase has no new external dependencies. It reads from the same Postgres database
every other analytics function and MCP tool already reads from, via the same SQLAlchemy async
engine already configured. `psql` access to the live production database (used only for this
research's data audit, not needed at runtime) was available in this environment via `.env`'s
`DATABASE_URL` and is not a phase dependency.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V4 Access Control | Yes | `user_id` resolved server-side via `resolve_user_id(ctx)`, never a tool argument (existing `_common.py` pattern, reused unchanged) — the tenant predicate leads every query, matching every other analytics function in this codebase |
| V5 Input Validation | Yes | `metric` parameter constrained to a closed `StrEnum` at the MCP schema layer (D-09) — an unrecognized value is rejected before any code runs, not sanitized/coerced |
| V6 Cryptography | No | No secrets, tokens, or cryptographic material touched by this phase |
| V2/V3 Authentication/Session | No | Unaffected — this phase adds a read-only tool behind the same `read_only_session`/bearer-token auth every other tool already uses; no new auth surface |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Cross-tenant data disclosure (reading another user's body measurements) | Information Disclosure | `user_id` in the `WHERE` clause of every query, sourced from `resolve_user_id(ctx)` server-side (already the pattern for all 13 existing tools; this phase's new query follows it identically) |
| Internal error/DSN leak through a tool's error text | Information Disclosure | `@safe_tool` decorator — any exception is logged via `structlog` (redacted) and replaced with a coarse `data_available=False` payload before reaching Claude; verified as the mandatory pattern for all tools, reused unchanged |
| SQL injection via a model-supplied string | Tampering | Not reachable here: the only "string" input is the closed `StrEnum` `metric`, resolved to a column via `getattr` on a fixed, hardcoded set of 16 attribute names — never string-formatted into SQL |

## Sources

### Primary (HIGH confidence)
- Direct file reads: `backend/app/analytics/bodyweight.py`, `backend/app/analytics/metadata.py`,
  `backend/app/analytics/schemas.py`, `backend/app/db/models/body.py`,
  `backend/app/mcp/tools/body.py`, `backend/app/mcp/tools/_common.py`,
  `backend/app/mcp/tools/schemas.py`, `backend/app/mcp/server.py`,
  `backend/tests/test_analytics_bodyweight.py`, `backend/tests/test_mcp_tools.py`,
  `backend/tests/test_mcp_tool_schemas.py`, `backend/tests/test_mcp_tool_budget.py`,
  `backend/tests/test_coaching_doc.py`, `backend/tests/conftest.py` (GoldenBuilder),
  `docs/coaching-instructions.md`, `pyproject.toml`, `.planning/config.json` — all read in full or
  in the relevant section this session.
- Live production database query via `psql "$DATABASE_URL"` (Neon Postgres), 2026-09-03 — exact
  per-column row counts, gap statistics, and 90-day-window coverage for every in-scope column.
- Live local verification: `Args.model_json_schema()` against an installed Pydantic 2 + `StrEnum`
  model in the project's own `.venv`, confirming the JSON Schema enum mechanism D-09 relies on.

### Secondary (MEDIUM confidence)
- None — this research required no external/web sources; the entire domain is internal to the
  already-shipped codebase and a live database query.

### Tertiary (LOW confidence)
- None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies; every piece verified present and pinned already
- Architecture: HIGH — directly extends a shipped, tested pattern (BODY-01/Phase 6) with one
  documented calculation-shape divergence (D-05), itself directly justified by a live data query
- Pitfalls: HIGH for the four structural-test pitfalls (each verified by reading the actual test
  assertions this session) — MEDIUM for the exact floor/staleness numeric recommendations
  (data-grounded but ultimately a judgment call, flagged in the Assumptions Log)

**Research date:** 2026-09-03
**Valid until:** Effectively indefinite for the architecture (internal pattern, not
version-dependent) — the live data coverage numbers should be treated as a point-in-time snapshot;
re-verify the floor recommendation against fresh data if planning is deferred more than ~90 days.
