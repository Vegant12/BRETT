# Phase 11: Body Measurement History - Pattern Map

**Mapped:** 2026-09-03
**Files analyzed:** 11 (1 new module, 8 extended, 2 new test-adjacent — see table)
**Analogs found:** 11 / 11 (every file has a same-repo analog; this phase is a pure structural
extension of the BODY-01/Phase 6 pattern, not new territory)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `backend/app/analytics/body_measurements.py` (NEW) | service (analytics) | CRUD (read, aggregate/fold) | `backend/app/analytics/bodyweight.py` | exact (same role, same tier; calculation shape deliberately diverges per D-05 — see below) |
| `backend/app/analytics/metadata.py` (EXTENDED) | utility (coverage/freshness helpers) | transform | itself (extend in place) | exact — add one `MEASURED_DAY_FLOORS` entry + one new sibling function, do not fork |
| `backend/app/analytics/schemas.py` (EXTENDED) | model (Pydantic result types) | transform | itself (extend in place) — pattern source: `PersonalRecordType`/`TrendVerdict`/`RecompositionStatus` (StrEnum) and `ProgressionPoint`/`PlateauResult` (value/reason, threshold-echo) | exact |
| `backend/app/mcp/tools/body.py` (EXTENDED) | controller (MCP tool) | request-response | `fitness_get_body_weight_trend` in the same file | exact — no-argument-tools shape does NOT apply here (this tool takes `metric`); closest same-file sibling with an argument is `fitness_get_exercise_progression` (see below) for the "typed enum argument" shape |
| `backend/app/mcp/tools/schemas.py` (EXTENDED) | model (MCP wire response) | transform | `BodyWeightTrendResponse` in the same file | exact |
| `backend/app/mcp/tools/_common.py` (EXTENDED — likely no change needed, verify) | utility (cross-cutting MCP scaffolding) | n/a | itself — `MAX_*` budget constant block | exact (only touched if a new cap constant is needed; D-09's `StrEnum` already bounds the `metric` argument, so likely zero new lines here) |
| `backend/app/mcp/server.py` (EXTENDED) | config (tool registry) | event-driven (registration) | itself — `_TOOLS` tuple entry for `fitness_get_body_weight_trend` | exact |
| `backend/tests/conftest.py` (EXTENDED — `GoldenBuilder.body_measurement`) | test fixture | file I/O (DB seed) | itself — extend the existing method signature | exact |
| `backend/tests/test_analytics_body_measurements.py` (NEW) | test | CRUD (unit + integration) | `backend/tests/test_analytics_bodyweight.py` | exact |
| `backend/tests/test_mcp_tools.py`, `test_mcp_tool_schemas.py`, `test_mcp_tool_budget.py`, `test_coaching_doc.py` (EXTENDED) | test (structural drift guards) | request-response | themselves — one dict/frozenset entry each, following the existing `fitness_get_body_weight_trend` entry | exact |
| `docs/coaching-instructions.md` (EXTENDED) | config (doc) | n/a | itself — table row + example-question line for `fitness_get_body_weight_trend` | exact |

## Pattern Assignments

### `backend/app/analytics/body_measurements.py` (NEW — service, CRUD/aggregate)

**Analog:** `backend/app/analytics/bodyweight.py` (structural pattern only — D-05 explicitly
forbids copying its rolling-average CALCULATION shape; copy its plumbing: module docstring
posture, `resolve_window`-then-real-window anchor trick, read-only/keyword-only session
conventions, coverage composition, freshness composition).

**Imports pattern** (`bodyweight.py` lines 39–58):
```python
import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.metadata import (
    FRESHNESS_RESOURCES_BODY,
    build_freshness,
    build_measurement_coverage,
    earliest_measurement_at,
    is_measurement_insufficient,
)
from app.analytics.rollup import resolve_window
from app.analytics.schemas import BodyWeightTrendResult
from app.core.time import local_day, utc_now
from app.db.models.body import BodyMeasurement
```
For the new module: swap `earliest_measurement_at` for the NEW `earliest_metric_measurement_at`
(to be added to `metadata.py`, see Pattern below — do NOT reuse the weight-only one, see
RESEARCH.md Pitfall 4), and import `BodyMeasurementMetric`/`BodyMeasurementTrendResult` from
`schemas.py` instead of `BodyWeightTrendResult`.

**Local-day anchor pattern — copy VERBATIM** (`bodyweight.py` lines 190–208, the throwaway-probe
trick):
```python
probe_day = local_day(utc_now(), "UTC")
tz = (
    await resolve_window(
        session,
        user_id=user_id,
        start_day=probe_day,
        end_day=probe_day,
        snap_to_weeks=False,
    )
).tz
anchor = local_day(utc_now(), tz)
```
This is the ONLY sanctioned way to get the user's local "today" inside `app/analytics/` (the MCP
layer has its own equivalent, `_common.local_today`, but analytics must not import from `mcp`).

**Query pattern — generic column selection (per RESEARCH.md Pattern 1, verified against this
session's read of `bodyweight.py`'s `_weight_rows`)**, modeled on `_weight_rows` (`bodyweight.py`
lines 97–126) but parameterized on `column = getattr(BodyMeasurement, metric.value)` instead of
the hardcoded `BodyMeasurement.weight_kg`:
```python
result = await session.execute(
    select(BodyMeasurement.measured_on, column)
    .where(
        BodyMeasurement.user_id == user_id,  # tenant predicate leads, T-04-02
        column.is_not(None),
        BodyMeasurement.measured_on >= anchor - dt.timedelta(days=WINDOW_DAYS - 1),
        BodyMeasurement.measured_on <= anchor,
    )
    .order_by(BodyMeasurement.measured_on)
)
```

**Coverage/floor composition pattern** (`bodyweight.py` lines 232–243, adapted to ONE window
instead of four):
```python
coverage = build_measurement_coverage(
    window_days=90, measured_days=measured_days, earliest_measurement_at=earliest_ever
)
```

**Freshness composition pattern — copy verbatim call shape** (`bodyweight.py` lines 291–293):
```python
freshness=await build_freshness(
    session, user_id=user_id, resources=FRESHNESS_RESOURCES_BODY
),
```
`FRESHNESS_RESOURCES_BODY` already exists in `metadata.py` (line 79) and is metric-agnostic (it
tracks the `body_measurements` sync resource as a whole) — reuse unchanged, no new constant
needed.

**Anti-patterns explicitly called out by CONTEXT.md/RESEARCH.md — do NOT copy from `bodyweight.py`:**
- Do NOT copy the rolling-average/`_window_average` fold shape (D-05: two-point latest-vs-earliest
  instead).
- Do NOT copy `_WEIGHT_QUANTUM = Decimal("0.001")` quantization — the source columns are already
  `Numeric(6,2)`/`Numeric(5,2)` and BODY-05 never averages, so a plain `Decimal` subtraction is
  already exact (RESEARCH.md Anti-Patterns section).
- Do NOT copy `_dedupe_by_day`'s manual-wins tie-break — D-03 says this stays dormant; BODY-05
  has no manual rows to dedupe against (every row is `source='hevy'`).

---

### `backend/app/analytics/metadata.py` (EXTENDED)

**Analog:** itself — extend in place, do not fork.

**Floor-extension pattern** (`metadata.py` line 115, the exact line to extend):
```python
MEASURED_DAY_FLOORS: Mapping[int, int] = MappingProxyType({7: 3, 14: 5, 30: 10})
```
becomes (per RESEARCH.md's calibrated recommendation, floor=2):
```python
MEASURED_DAY_FLOORS: Mapping[int, int] = MappingProxyType({7: 3, 14: 5, 30: 10, 90: 2})
```
`is_measurement_insufficient` (lines 222–232) and `build_measurement_coverage` (lines 235–257)
need ZERO code changes — they already key off `MEASURED_DAY_FLOORS.get(window_days)` generically.

**New sibling helper — copy `earliest_measurement_at`'s shape, add a column parameter**
(`metadata.py` lines 260–273, the function to clone-and-extend):
```python
async def earliest_measurement_at(session: AsyncSession, *, user_id: uuid.UUID) -> dt.date | None:
    """The user's oldest synced weigh-in, across ALL time -- deliberately not window-scoped."""
    result: dt.date | None = await session.scalar(
        select(func.min(BodyMeasurement.measured_on)).where(BodyMeasurement.user_id == user_id)
    )
    return result
```
New sibling (add beside it, per RESEARCH.md Pattern 3 — verbatim recommended implementation):
```python
async def earliest_metric_measurement_at(
    session: AsyncSession, *, user_id: uuid.UUID, column: InstrumentedAttribute
) -> dt.date | None:
    """The user's oldest synced reading of ONE specific metric, across all time."""
    result: dt.date | None = await session.scalar(
        select(func.min(BodyMeasurement.measured_on)).where(
            BodyMeasurement.user_id == user_id, column.is_not(None)
        )
    )
    return result
```
Requires a new import: `from sqlalchemy.orm import InstrumentedAttribute` (or reuse whatever
attribute-typing convention the codebase already uses for `getattr(Model, name)` patterns — check
`body_measurements.py`'s own import once written, since it resolves the same attribute).

**Do NOT modify:** `earliest_measurement_at` itself (BODY-01 must stay unregressed —
CONTEXT.md canonical refs are explicit); `INSUFFICIENT_DATA_SESSION_THRESHOLD` and the
session-grained `build_coverage`/`is_insufficient` pair (those serve VOL/PROG tools, not BODY-05).

---

### `backend/app/analytics/schemas.py` (EXTENDED)

**Analog:** itself — `PersonalRecordType`/`TrendVerdict`/`RecompositionStatus` for the `StrEnum`
pattern; `ProgressionPoint` for the mutually-exclusive value/reason pair; `PlateauResult` for the
"every threshold is a field" convention; `MeasurementCoverage` (already exists) and
`BodyWeightTrendResult` for the sibling result-model shape.

**StrEnum pattern to copy** (`schemas.py` lines 228–239, `PersonalRecordType`):
```python
class PersonalRecordType(StrEnum):
    """PROG-04's five record types. ``value`` units differ per type -- see ``PersonalRecord``."""

    MAX_WEIGHT = "max_weight"
    MAX_REPS = "max_reps"
    ESTIMATED_1RM = "estimated_1rm"
    SESSION_VOLUME = "session_volume"
```
New enum follows this shape exactly, with member VALUES set to the literal `BodyMeasurement`
column names (per D-09/RESEARCH.md Pattern 1 — this is the load-bearing mechanism that lets
`getattr(BodyMeasurement, metric.value)` resolve the column with zero second mapping):
```python
class BodyMeasurementMetric(StrEnum):
    """BODY-05. Values are the EXACT BodyMeasurement column names (db/models/body.py)."""
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
```

**Threshold-echo + sibling-coverage pattern to copy** (`schemas.py` lines 534–565,
`BodyWeightTrendResult` — the direct structural sibling):
```python
class BodyWeightTrendResult(_AnalyticsModel):
    anchor_day: dt.date
    average_7d_kg: Decimal | None
    ...
    coverage_7d: MeasurementCoverage
    ...
    freshness: FreshnessMetadata
```
New result model (per RESEARCH.md's "Recommended Result Shape" — already fully drafted there,
treat as the concrete target, not just inspiration):
```python
class BodyMeasurementTrendResult(_AnalyticsModel):
    metric: BodyMeasurementMetric
    window_days: int              # 90, echoed
    anchor_day: dt.date
    coverage: MeasurementCoverage
    latest_value: Decimal | None
    latest_measured_on: dt.date | None
    earliest_value: Decimal | None
    earliest_measured_on: dt.date | None
    delta_value: Decimal | None
    is_stale: bool
    days_since_latest_reading: int | None
    stale_after_days: int         # 30, echoed — PlateauResult's "every threshold is a field" rule
    freshness: FreshnessMetadata
```

**Class location:** add both immediately after `MeasurementCoverage` (line 242) and before
`ProgressionPoint` (line 265), or immediately after `BodyWeightTrendResult` (line 565) — either
placement keeps BODY-01/BODY-05 grouped; prefer the latter since it's the direct sibling.

---

### `backend/app/mcp/tools/body.py` (EXTENDED — controller, request-response)

**Analog:** `fitness_get_body_weight_trend` in the same file for the overall shape
(`safe_tool`/`resolve_user_id`/`read_only_session`/degraded-factory conventions); note this new
tool takes an ARGUMENT (`metric`), which `fitness_get_body_weight_trend` does not — for the
`Annotated[..., Field(...)]` typed-argument shape, the closer analog is
`fitness_get_exercise_progression`'s `exercise_name` parameter (not read this session, but the
mechanism is identical to any Pydantic-typed MCP tool arg already in the codebase; the concrete
target is already fully drafted in RESEARCH.md's "Code Examples" section — treat it as the
implementation, not just a reference).

**Full pattern — copy structure, not text** (`body.py` lines 35–56, `_degraded_trend` +
`fitness_get_body_weight_trend`):
```python
def _degraded_trend() -> BodyWeightTrendResponse:
    return BodyWeightTrendResponse(data_available=False, trend=None)


@safe_tool(degraded=_degraded_trend)
async def fitness_get_body_weight_trend(ctx: Context[AppContext]) -> BodyWeightTrendResponse:
    """Body-weight trend anchored on today: ..."""
    user_id = resolve_user_id(ctx)
    async with read_only_session(ctx) as session:
        trend = await get_body_weight_trend(session, user_id=user_id)
    return BodyWeightTrendResponse(data_available=True, trend=trend)
```

**New tool — RESEARCH.md's drafted target (use as-is unless planning finds a reason to diverge):**
```python
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
New imports needed at top of `body.py`: `from typing import Annotated`, `from pydantic import
Field`, `from app.analytics.body_measurements import get_body_measurement_trend`,
`from app.analytics.schemas import BodyMeasurementMetric`, and add
`BodyMeasurementTrendResponse` to the existing `from app.mcp.tools.schemas import (...)` line
(`body.py` line 28).

---

### `backend/app/mcp/tools/schemas.py` (EXTENDED)

**Analog:** `BodyWeightTrendResponse` in the same file (lines 175–182):
```python
class BodyWeightTrendResponse(_McpModel):
    """BODY-01 for MCP. ``trend`` is the analytics result verbatim, per-window coverage and all."""

    data_available: bool
    trend: BodyWeightTrendResult | None
```
New sibling (also drafted in RESEARCH.md — use as target):
```python
class BodyMeasurementTrendResponse(_McpModel):
    """BODY-05 for MCP. `trend` is the analytics result verbatim, matching BodyWeightTrendResponse."""
    data_available: bool
    trend: BodyMeasurementTrendResult | None
```
Add `BodyMeasurementTrendResult` to the existing `from app.analytics.schemas import (...)` block
(lines 36–54) alongside `BodyWeightTrendResult`. Compose-never-restate rule applies (module
docstring rule 1, lines 6–12): embed the analytics result whole, never re-derive fields.

---

### `backend/app/mcp/tools/_common.py` (verify-only — likely no change)

**Analog:** the `MAX_*` constant block (lines 47–96). D-09's `StrEnum`-typed `metric` argument is
validated entirely by the MCP SDK's own schema layer (RESEARCH.md Pattern 1) — there is no list
to truncate and no window count to cap for this tool, so this file most likely needs NO new
constant. If planning determines a cap constant IS needed (unlikely), follow the existing
naming/comment convention: one named constant with a one-line "why this number" comment, e.g. the
`MAX_WEEKS` block (lines 56–58).

---

### `backend/app/mcp/server.py` (EXTENDED — config, registration)

**Analog:** itself — the existing `fitness_get_body_weight_trend` import and `_TOOLS` tuple entry.

**Import pattern** (`server.py` lines 41–44):
```python
from app.mcp.tools.body import (
    fitness_get_body_weight_trend,
    fitness_get_recomposition_status,
)
```
becomes:
```python
from app.mcp.tools.body import (
    fitness_get_body_measurement_trend,
    fitness_get_body_weight_trend,
    fitness_get_recomposition_status,
)
```

**Registration pattern** (`server.py` lines 204–212, the `_TOOLS` tuple entries for the body
tools):
```python
(
    fitness_get_body_weight_trend,
    "7/14/30-day rolling body-weight averages and the smoothed weekly rate of change.",
),
(
    fitness_get_recomposition_status,
    "Recomposition verdict from the body-weight trend and training progression, "
    "with its disclaimer.",
),
```
Add a new tuple entry (RESEARCH.md's drafted description, insert alongside the other body tools):
```python
(
    fitness_get_body_measurement_trend,
    "Latest-vs-earliest 90-day comparison for one circumference or composition metric, "
    "with staleness and coverage.",
),
```
No other change to `server.py` — the `for _fn, _description in _TOOLS: mcp.add_tool(...)` loop
(lines 215–216) registers it automatically with `READ_ONLY` annotations.

---

### `backend/tests/conftest.py` — `GoldenBuilder.body_measurement` (EXTENDED — test fixture)

**Analog:** itself (lines 450–487) — extend the existing method's signature; this is
RESEARCH.md's Pitfall 1, and every BODY-05 integration test depends on it existing first.

**Current signature to extend:**
```python
async def body_measurement(
    self,
    *,
    measured_on: dt.date,
    weight_kg: Decimal | None,
    source: str = "hevy",
    user_id: uuid.UUID = DEFAULT_USER_ID,
) -> None:
    ...
    await self._session.execute(
        insert(BodyMeasurement).values(
            id=uuid.uuid4(),
            user_id=user_id,
            source=source,
            external_id=None,
            measured_on=measured_on,
            weight_kg=weight_kg,
        )
    )
    await self._session.flush()
```
RESEARCH.md recommends adding at least two new optional kwargs (one circumference column, e.g.
`waist_cm`, one composition column, e.g. `fat_percent`) to prove the generic analytics function
across both `Numeric(6,2)`/`Numeric(5,2)` column types — OR a single generic
`**metric_values: Decimal | None` kwarg mapped onto the insert. The plan must pick one exact
shape; both are valid extensions of this exact method, following its existing keyword-only,
`Decimal`-typed convention (never `float`, matching the docstring's own stated reason).

---

### `backend/tests/test_analytics_body_measurements.py` (NEW — test)

**Analog:** `backend/tests/test_analytics_bodyweight.py` in full — mirror its structure:
- Module docstring stating the frozen-clock rationale (lines 1–26) and which test is
  "load-bearing" (this file's load-bearing test should cover D-08's "insufficient vs stale are
  independent" claim, mirroring `test_windows_gate_independently`'s role here).
- `_row`/`_seed`/`_uniform` helper pattern (lines 62–95) — offset-based fixture builders, not
  literal dates, so windows read in the same frame they're defined in.
- Pure-Python business-rule tests carry NO `@pytest.mark.integration`; DB-touching tests do
  (module docstring lines 18–21).
- Exact `Decimal` equality throughout, no tolerance helpers (lines 23–25).
- Imports pattern (lines 28–50):
```python
import datetime as dt
import uuid
from collections.abc import Sequence
from decimal import Decimal

import pytest
import time_machine
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.bodyweight import (...)
from app.analytics.metadata import MEASURED_DAY_FLOORS
from app.analytics.schemas import BodyWeightTrendResult, MeasurementCoverage
from tests.conftest import (
    ANALYTICS_SECOND_USER_ID,
    DEFAULT_USER_ID,
    GoldenBuilder,
)
```
New file swaps the `bodyweight`/`BodyWeightTrendResult` imports for `body_measurements`/
`BodyMeasurementTrendResult`/`BodyMeasurementMetric`.

---

### `backend/tests/test_mcp_tools.py`, `test_mcp_tool_schemas.py`, `test_mcp_tool_budget.py`, `test_coaching_doc.py` (EXTENDED — structural drift guards)

**These four are NOT optional cleanup — each is a hard gate that fails the moment the tool is
registered (RESEARCH.md Pitfalls 2 and 3).** Each needs exactly one new entry, following the
`fitness_get_body_weight_trend` entry's exact shape in each file.

**1. `test_mcp_tool_schemas.py` — `EXPECTED_TOOLS`** (lines 37–53):
```python
EXPECTED_TOOLS = frozenset(
    {
        "fitness_ping",
        ...
        "fitness_get_body_weight_trend",
        "fitness_get_recomposition_status",
    }
)
```
Add `"fitness_get_body_measurement_trend"` to the set. If the tool declares an `EXPECTED_CAPS`
entry (it does NOT need one — `metric` is a `StrEnum`, not a numeric window — no change needed to
`EXPECTED_CAPS`, lines 59–70).

**2. `test_mcp_tool_budget.py` — `BUDGETS` and `WORST_CASE_ARGS`** (lines 69–111):
```python
BUDGETS: dict[str, int] = {
    ...
    "fitness_get_body_weight_trend": 4_096,
    ...
}
WORST_CASE_ARGS: dict[str, dict[str, object]] = {
    ...
    "fitness_get_body_weight_trend": {},
    ...
}
```
Add `"fitness_get_body_measurement_trend": {"metric": "waist_cm"}` (or whichever member the plan
picks as worst-case — likely irrelevant since payload size doesn't vary meaningfully across
members) to `WORST_CASE_ARGS`, and a MEASURED byte budget to `BUDGETS` — follow the file's own
methodology (comment at lines 61–64): measure `structured_content` + text content at the
worst-case argument via `_result_bytes` (lines 139–146), add ~30% headroom, do not guess.

**3. `test_mcp_tools.py` — `MINIMAL_TOOL_ARGUMENTS`** (lines 91–110):
```python
MINIMAL_TOOL_ARGUMENTS: dict[str, dict[str, object]] = {
    ...
    "fitness_get_body_weight_trend": {},
    "fitness_get_recomposition_status": {},
}
```
Add `"fitness_get_body_measurement_trend": {"metric": "waist_cm"}` (any valid enum member — this
dict is also imported by `test_secret_redaction.py`, so this one edit covers both). Also add one
behavioral integration test mirroring `test_body_weight_trend_returns_rolling_averages` (lines
927–949):
```python
@pytest.mark.integration
async def test_body_weight_trend_returns_rolling_averages(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    from mcp import Client
    from app.mcp.server import mcp

    await _seed_reference_history(committed_history, session)

    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool("fitness_get_body_weight_trend", {})

    assert result.is_error is False
    payload = result.structured_content
    assert payload is not None
    assert payload["data_available"] is True
    trend = payload["trend"]
    ...
```

**4. `test_coaching_doc.py`** — no dict edit; requires `docs/coaching-instructions.md` to name the
new tool exactly once. This test file itself needs NO code change — it is a phase-agnostic
structural guard (module docstring). Only the doc changes (see below).

---

### `docs/coaching-instructions.md` (EXTENDED — doc, per RESEARCH.md Pitfall 2)

**Analog:** the existing `fitness_get_body_weight_trend` row (line 63) and example-question line
(line 120).

**Table row pattern** (line 63):
```
| "Has my weight trend changed?" / "am I gaining too fast?" | `fitness_get_body_weight_trend` | *(none)* |
```
Add a new row immediately after it, e.g.:
```
| "How has my waist/chest/[circumference] changed?" | `fitness_get_body_measurement_trend` | **`metric`** |
```
The tool name must be spelled EXACTLY as registered (`fitness_get_body_measurement_trend`) — a
typo fails `test_every_tool_the_document_names_exists_in_the_registry` in the opposite direction
from a missing entry.

**Example-question pattern** (lines 120–121):
```
- "Has my weight trend changed?" → `fitness_get_body_weight_trend`
- "Is my weight increasing too quickly?" → `fitness_get_body_weight_trend`
```
Add at least one line, e.g.:
```
- "Has my waist changed over the last few months?" → `fitness_get_body_measurement_trend`
```

**Character budget guard:** `test_the_document_fits_a_project_custom_instruction_paste` caps the
whole document at 9,000 characters (`test_coaching_doc.py` line 47) — keep the new content
minimal (one table row + one example line), not COACH-03's full future treatment.

## Shared Patterns

### `safe_tool` / `read_only_session` / `resolve_user_id` (MCP cross-cutting layer)
**Source:** `backend/app/mcp/tools/_common.py` lines 105–290
**Apply to:** `fitness_get_body_measurement_trend` — no new pattern needed, this is the 14th tool
reusing an already-mandatory layer. `safe_tool` guarantees no exception (and no DSN-carrying
error text) reaches Claude (lines 254–290); `read_only_session` opens a Postgres `READ ONLY`
transaction at the server (lines 123–154); `resolve_user_id` resolves the tenant server-side,
never from a tool argument (lines 105–120).

### Coverage-floor extension point (never fork)
**Source:** `backend/app/analytics/metadata.py` — `MEASURED_DAY_FLOORS` (line 115),
`is_measurement_insufficient` (lines 222–232), `build_measurement_coverage` (lines 235–257)
**Apply to:** `body_measurements.py` — add `90: 2` to the mapping; call the two functions
unchanged. Do NOT write a parallel coverage concept for BODY-05.

### `StrEnum` closed-choice + MCP schema-layer validation
**Source:** `backend/app/analytics/schemas.py` lines 176–239 (`TrendVerdict`,
`PlateauConfidence`, `ProgressionSignal`, `RecompositionStatus`, `PersonalRecordType`)
**Apply to:** `BodyMeasurementMetric` — an unrecognized `metric` value is rejected by the MCP
SDK's own `inputSchema` validation before the tool body runs; no manual `if metric not in {...}`
branch needed (verified this session per RESEARCH.md's local `Args.model_json_schema()` check).

### "Every threshold/window is a response field, never a comment"
**Source:** `backend/app/analytics/schemas.py` — `PlateauResult` (lines 344–383, especially
`threshold_percent`/`min_sessions`/`min_elapsed_days`/`lookback_start`/`lookback_end`) and
`BodyWeightTrendResult` (`anchor_day`)
**Apply to:** `BodyMeasurementTrendResult.window_days` (90) and `.stale_after_days` (30, per
RESEARCH.md's calibrated recommendation) must be fields on the response, not hardcoded invisibly.

### Compose-never-restate (MCP response wraps analytics result whole)
**Source:** `backend/app/mcp/tools/schemas.py` module docstring rule 1 (lines 6–12); every
`*Response` model in that file embeds its `app/analytics/schemas.py` counterpart as a field rather
than re-deriving fields.
**Apply to:** `BodyMeasurementTrendResponse.trend: BodyMeasurementTrendResult | None` — embed
whole, exactly like `BodyWeightTrendResponse.trend`.

### `data_available: bool` on every response
**Source:** `backend/app/mcp/tools/schemas.py` module docstring rule 2 (lines 14–17); every
`_McpModel` subclass.
**Apply to:** `BodyMeasurementTrendResponse.data_available` — `False` means the server could not
reach the data (via `safe_tool`'s degraded factory), never "no measurements exist for this
metric" (which is instead `trend.coverage.insufficient_data = True` with
`data_available = True`).

## No Analog Found

None. Every file this phase touches has a direct, same-repo, same-tier analog because Phase 11 is
architecturally a straight structural extension of the BODY-01/Phase 6 pattern (per RESEARCH.md's
own framing) — the only genuine novelty is the two-point latest-vs-earliest calculation shape
inside `body_measurements.py`, which has no existing analog in this codebase and must be written
fresh per D-05/D-06 (see RESEARCH.md's Architecture Patterns / "System Architecture Diagram"
section for the full calculation walkthrough — steps 1–7 — since there is no code to point at for
this specific fold).

## Metadata

**Analog search scope:** `backend/app/analytics/`, `backend/app/mcp/tools/`, `backend/app/mcp/`,
`backend/app/db/models/`, `backend/tests/` (all files listed in CONTEXT.md's canonical refs and
RESEARCH.md's Primary Sources, read in full this session)
**Files scanned:** 13 (bodyweight.py, metadata.py, schemas.py x2 [analytics + mcp/tools],
body.py x2 [mcp/tools + db/models], _common.py, server.py, conftest.py, test_analytics_bodyweight.py,
test_mcp_tool_schemas.py, test_mcp_tool_budget.py, test_mcp_tools.py, test_coaching_doc.py,
docs/coaching-instructions.md)
**Pattern extraction date:** 2026-09-03
