# Phase 4: Volume & Frequency Analytics - Pattern Map

**Mapped:** 2026-08-30
**Files analyzed:** 13 (9 new, 4 modified)
**Analogs found:** 13 / 13 (one *partial* — see "No Analog Found")

> **The one-sentence summary for the planner.** This phase adds **no new architectural tier**.
> `app/analytics/` is a sibling of `app/normalization/`, and every module in it can copy an
> existing file almost structurally: `resolver.py` for the session-taking read module,
> `hevy/sync.py::resource_status` for the metadata reader, `hevy/schemas.py` + `ping.py` for the
> Pydantic return types, `test_hevy_isolation.py` for the boundary test. The **only** thing with
> no precedent anywhere in `backend/app/` is the SQL aggregate itself — `GROUP BY`,
> `date_trunc`, `FILTER (WHERE ...)`, `cast(..., Date)` and `func.timezone` appear in **zero**
> lines of application code today (verified by grep across `backend/app/**/*.py`). For that one
> thing, RESEARCH.md Patterns 1–4 are the source, and they were executed against a live
> Postgres 18.6 rather than recalled.

---

## File Classification

### New — application code

| New File | Role | Data Flow | Closest Analog | Match Quality |
|----------|------|-----------|----------------|---------------|
| `backend/app/analytics/__init__.py` | package init | — | `backend/app/normalization/__init__.py` | **exact** |
| `backend/app/analytics/schemas.py` | model (public return types) | transform | `backend/app/integrations/hevy/schemas.py` (module shape) + `backend/app/mcp/tools/ping.py:24-28` (BaseModel as a return type) | role-match |
| `backend/app/analytics/metadata.py` | service (repository read) | request-response | `backend/app/integrations/hevy/sync.py:75-120` (`resource_status`) | **exact** |
| `backend/app/analytics/volume.py` | service (query + pure fold) | batch aggregate → transform | `backend/app/normalization/resolver.py` (shape) — *aggregate half has no analog* | partial |
| `backend/app/analytics/frequency.py` | service (query + pure fold) | batch aggregate → transform | `backend/app/analytics/volume.py` (written first, this wave) → falls back to `resolver.py` | partial |

### Modified — application code

| Modified File | Role | Change | Closest Analog | Match Quality |
|---------------|------|--------|----------------|---------------|
| `backend/app/core/time.py` | utility | add `local_range_bounds(start_day, end_day, tz)` | `local_day_bounds()` **in the same file**, `:73-83` | **exact** |
| `backend/app/db/models/exercise.py` | model (docstring only) | correct the stale `exercise_type` vocabulary at `:60-64` | itself (`workout.py:154-157` is the correct-comment exemplar) | **exact** |

### New — tests

| New File | Role | Data Flow | Closest Analog | Match Quality |
|----------|------|-----------|----------------|---------------|
| `backend/tests/test_analytics_volume.py` | test (integration) | container-backed | `backend/tests/test_normalization_mapping.py` | **exact** |
| `backend/tests/test_analytics_frequency.py` | test (integration) | container-backed | `backend/tests/test_normalization_mapping.py` | **exact** |
| `backend/tests/test_analytics_metadata.py` | test (integration + unit) | container-backed + pure | `backend/tests/test_sync_state.py` | **exact** |
| `backend/tests/test_analytics_isolation.py` | test (static, **fast suite**) | file-I/O over committed source | `backend/tests/test_hevy_isolation.py` | **exact** |

### Modified — tests

| Modified File | Role | Change | Closest Analog | Match Quality |
|---------------|------|--------|----------------|---------------|
| `backend/tests/conftest.py` | test fixture | add a `golden_workout` builder (flush + rollback) | existing `session` fixture `:223-229` + `backend/app/integrations/hevy/workouts.py:82-173` (Core insert shape) | composite |
| `backend/tests/test_time.py` | test (unit) | add `local_range_bounds` cases | `test_local_day_bounds_is_half_open_utc` **in the same file**, `:243-253` | **exact** |

### Not modified — verify, do not touch

| File | Why the planner should confirm it stays untouched |
|------|--------------------------------------------------|
| `backend/app/normalization/resolver.py` | CONTEXT.md: "this phase consumes `resolver.py`, it doesn't modify it" |
| `backend/app/normalization/exercise_map.py` | Same boundary. D-01 removed the only reason to touch it (no unilateral exception list) |
| `backend/app/db/models/__init__.py` | **No new models this phase** — nothing to register. (Contrast Phase 3, where every new model needed a line here.) |
| `backend/migrations/versions/*` | No schema change. If a plan proposes a migration, the design drifted |
| `pyproject.toml` | RESEARCH: **zero** new dependencies. A proposed dep is a drift signal |

---

## Pattern Assignments

### `backend/app/analytics/__init__.py` (package init)

**Analog:** `backend/app/normalization/__init__.py` (whole file, 7 lines)

**Copy this exactly, substituting the boundary being asserted:**

```python
"""Provider-neutral exercise normalization.

This package deliberately sits OUTSIDE ``app/integrations/hevy/``. HEVY-05 confines Hevy's
request/response code to that directory; the canonical muscle taxonomy is not Hevy's -- it is
the project's, and a second provider must be able to feed the same tables. Nothing here may
import from ``app.integrations``.
"""
```

**Why the wording matters here specifically:** `backend/tests/test_hevy_isolation.py:88-93`
documents that its boundary check is a **regex on import statements**, not a substring scan,
*precisely so* a package that states its own rule in prose does not fail the test that enforces
it. The new `test_analytics_isolation.py` must inherit that regex approach for the same reason
— see the shared pattern below.

**Docstring content to state:** analytics is a sibling of `normalization/` and `core/`; it
imports nothing from `app.integrations` **and nothing from `app.mcp`** (the second half is
new — CONTEXT.md's "lives outside MCP handlers"); Phase 6 depends on this one-directional
arrow, not the reverse.

---

### `backend/app/analytics/schemas.py` (model, transform)

**Analogs:** two, deliberately — the repo has exactly two Pydantic-model modules.

**Primary (module shape + Decimal discipline):** `backend/app/integrations/hevy/schemas.py`
**Secondary (BaseModel as a function return type):** `backend/app/mcp/tools/ping.py:24-28`

**Shared-config base-class pattern** (`hevy/schemas.py:24-32`):

```python
class _HevyModel(BaseModel):
    """Shared config for every wire model.

    ``extra="ignore"`` on purpose, and asymmetrically so: Hevy ADDING a field must not break
    a sync -- they ship whenever they like -- while Hevy RENAMING or REMOVING one must break
    it loudly, here, rather than letting a silent `None` reach the database.
    """

    model_config = ConfigDict(hide_input_in_errors=True, extra="ignore")
```

**Carry across:** the private `_AnalyticsModel(BaseModel)` base with a `model_config`. Keep
`hide_input_in_errors=True` — the rationale at `hevy/schemas.py:12-14` ("a ValidationError
would otherwise render `input_value=...` — workout titles and body-composition numbers — into
a message that could reach a log line, FOUND-05") applies verbatim to a model holding weekly
tonnage. `extra="ignore"` does **not** carry across: these are internal return types, not a
wire mirror, so prefer the strict default (or `extra="forbid"`).

**Decimal field declaration** (`hevy/schemas.py:45-55`):

```python
    index: int
    type: str
    weight_kg: Decimal | None = None
    reps: int | None = None
```

`Decimal | None`, never `float`, for every summed magnitude — `weighted_sets`, `tonnage_kg`,
`sessions_per_week`. C-4 / RESEARCH "Anti-Patterns".

**Imports block to copy** (`hevy/schemas.py:17-21`):

```python
import datetime as dt
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
```

Note `import datetime as dt` — the repo-wide spelling (also `core/time.py:17`,
`resolver.py`-adjacent modules, `sync_state.py:11`). Never `from datetime import datetime`.

**Return-type-is-a-BaseModel pattern** (`mcp/tools/ping.py:24-28`):

```python
class PingResult(BaseModel):
    """Returning a BaseModel auto-populates outputSchema and structuredContent."""

    status: str
    database: str
```

That one-line docstring **is the Phase-6 justification** RESEARCH cites for choosing Pydantic
over a frozen dataclass. Restate it in `schemas.py`'s module docstring.

**The alternative the repo also uses — frozen dataclass** (`resolver.py:37-48`,
`muscles.py:151-157`, `hevy/sync.py:47-57`):

```python
@dataclass(frozen=True, slots=True)
class EffectiveMuscle:
    """One resolved (muscle, role) pair with the provenance the caller should believe.
    ...
    """

    muscle_group: CanonicalMuscleGroup
    role: MuscleRole
    source: MappingSource
```

Every result-carrying type in `app/` that is *not* crossing a wire uses
`@dataclass(frozen=True, slots=True)`. RESEARCH breaks the tie toward Pydantic on the Phase-6
hand-off. **If the planner picks dataclasses instead, this is the exact form to copy** — and
note `hevy/sync.py:59-72` (`SyncReport`) for the "exactly one of these fields is populated"
docstring idiom, which the volume/frequency result types will need for
`tonnage_kg is None` vs `Decimal("0.000")`.

**Field-naming rule specific to this phase (Pitfall 11).** One template maps to up to 9
muscle groups, so per-muscle set totals legitimately exceed the week's hard-set count. Name the
field so the grain is unambiguous and say so in the class docstring — the repo precedent for
"name it so the wrong reading is impossible" is `workout.py:70-79`
(`provider_created_at` "distinct from this row's `created_at`").

---

### `backend/app/analytics/metadata.py` (service, request-response)

**Analog:** `backend/app/integrations/hevy/sync.py:75-120` — `resource_status()`. This is the
closest match in the repo: a free async function that loops `SYNC_RESOURCES`, calls
`get_sync_state()` per resource, and returns a list of frozen result objects including the
never-synced case.

**Full analog body** (`hevy/sync.py:75-120`, abridged to the load-bearing parts):

```python
async def resource_status(
    sessionmaker: async_sessionmaker[AsyncSession], *, user_id: uuid.UUID
) -> list[ResourceStatus]:
    """HEVY-09, in one call and WITHOUT a transport.

    Returns one entry for every member of `SYNC_RESOURCES`, including resources that have
    never run -- "never synced" is the answer to "when was this last synced", and omitting
    the row would make it indistinguishable from "the resource does not exist".

    Sorted by resource so the report is deterministic and diffable between runs.
    """
    entries: list[ResourceStatus] = []
    async with sessionmaker() as session:
        for resource in sorted(SYNC_RESOURCES):
            state = await get_sync_state(
                session, user_id=user_id, provider=PROVIDER_HEVY, resource=resource
            )
            if state is None:
                entries.append(ResourceStatus(resource=resource, last_synced_at=None, ...))
                continue
            entries.append(ResourceStatus(resource=resource, last_synced_at=state.last_synced_at, ...))
    return entries
```

**Three deltas from the analog, all deliberate:**

1. **Take `session: AsyncSession`, not `sessionmaker`.** `resource_status` opens its own session
   because it is called from a CLI. Analytics takes a live `AsyncSession` — RESEARCH calls this
   "load-bearing": it matches every repository in `backend/app/` *and* it is what makes the
   flush-and-rollback golden fixture see the rows. Copy the signature convention from
   `resolver.py:111-116` instead:

   ```python
   async def effective_muscles_bulk(
       session: AsyncSession,
       *,
       user_id: uuid.UUID,
       template_external_ids: Sequence[str],
   ) -> dict[str, list[EffectiveMuscle]]:
   ```

2. **Return `last_synced_at` and nothing else from the `SyncState` row.** `ResourceStatus`
   (`hevy/sync.py:47-57`) carries `last_error`, `status`, `cursor_page`, `cursor_timestamp` —
   correct for an operator CLI, **forbidden** here. C-6 / MCP-06 / ASVS V8: analytics return
   types reach Claude. `sync_state.last_error` is populated by `format_sync_error`
   (`sync_state.py:44-56`), whose whole job is bounding what leaks — do not undo that by
   forwarding the field.

3. **Per-resource breakdown, not one collapsed timestamp** (RESEARCH A4, resolving CONTEXT.md's
   discretion item). The analog already does this and states why at `hevy/sync.py:96-108`.

**Constants import block to copy** (`hevy/sync.py:24-29`):

```python
from app.db.repositories.sync_state import (
    PROVIDER_HEVY,
    RESOURCE_WORKOUTS,
    SYNC_RESOURCES,
    get_sync_state,
)
```

Always the `RESOURCE_*` constants, never a bare `"workouts"` string — `sync_state.py:21-30`
exists so a typo'd resource returns `None` forever instead of failing.

**Threshold-constant pattern** (`sync_state.py:36`, `muscles.py:134-139`):

```python
_MAX_ERROR_LEN = 500
```
```python
DEFAULT_ROLE_WEIGHTS: Mapping[MuscleRole, Decimal] = MappingProxyType(
    {
        MuscleRole.DIRECT: Decimal("1.0"),
        MuscleRole.INDIRECT: Decimal("0.5"),
    }
)
```

D-05's threshold gets one module-level constant
(`INSUFFICIENT_DATA_SESSION_THRESHOLD = 2`), public (no leading underscore) so
`volume.py`, `frequency.py` and the tests all import the same number. RESEARCH Open Question 1
wants Phase 6 to reuse it too.

---

### `backend/app/analytics/volume.py` (service, batch aggregate → transform)

**Analog for module shape, signatures, and the pure-Python half:**
`backend/app/normalization/resolver.py`
**Analog for the SQL aggregate: NONE — use RESEARCH Patterns 1 and 2 verbatim** (see "No Analog
Found").

**Module docstring pattern** (`resolver.py:1-18`) — this is the single most transferable thing
in the file:

```python
"""Effective muscle mapping: curated base overridden by manual corrections (NORM-02, NORM-03).

**The resolution rule, and it is not the obvious one.** If ANY override row exists for a
template, the override set REPLACES the base set entirely. If none exists, the base applies.

A per-row merge -- the intuitive design -- would let a user add a muscle or change a role but
never REMOVE one, so the most common correction there is ("this exercise does not actually
work rear delts") would be unexpressible. ...

Provider-neutral by construction: this module imports nothing from ``app.integrations``. ...
"""
```

The invariant: **requirement ID first, then the counter-intuitive rule, then the concrete
failure the rule prevents.** For `volume.py` the material is already written — RESEARCH
Pitfalls 3, 5, 6 and 12 each supply a measured failure with a live-data number
(543/7,719 NULL-product sets; 4.0× hamstring inflation; 823 dropped dropsets; 48 zero-weight
sets). Quote the numbers into the docstring and the inline comments; the repo does this
everywhere (`workouts.py:150-152` "Measured at 44x faster than row-by-row for 12,000 rows").

**Imports block** (`resolver.py:20-34`) — the shape, including isort grouping
(`known-first-party = ["app"]`, `pyproject.toml:68-71`):

```python
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.exercise import ExerciseMuscle, ExerciseMuscleOverride, ExerciseTemplate
from app.normalization.muscles import (
    CanonicalMuscleGroup,
    MappingSource,
    MuscleRole,
    role_weight,
)
```

For `volume.py` the third-party line becomes
`from sqlalchemy import Date, and_, cast, func, select` — **all four of `Date`, `and_`, `cast`,
`func.timezone` are first uses in `backend/app/`.** Verified: grep for `date_trunc`, `group_by`,
`func.sum`, `func.timezone`, `cast(` across `backend/app/**/*.py` returns only *docstring
mentions* in `core/time.py:4,68`.

**Signature convention — mandatory, verified across `resolver.py`, `sync_state.py`,
`workouts.py`, `templates.py`, `body.py`, `events.py`:** positional `session`, keyword-only
everything else.

```python
async def effective_muscles_bulk(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    template_external_ids: Sequence[str],
) -> dict[str, list[EffectiveMuscle]]:
```

**Delegate-so-there-is-one-implementation pattern** (`resolver.py:97-108`):

```python
async def effective_muscles(
    session: AsyncSession, *, user_id: uuid.UUID, template_external_id: str
) -> list[EffectiveMuscle]:
    """The mapping Phase 4 should use for one template.

    Delegates to `effective_muscles_bulk` so the replacement rule has exactly one
    implementation; a second copy here is how the two would eventually disagree.
    """
```

Apply this to `get_weekly_volume` (VOL-01) and `get_muscle_group_volume` (VOL-02): VOL-02 is
VOL-01's rows plus a fan-out. Write the aggregate **once** as a private
`_weekly_volume_rows(...)` and have both public functions call it. Same reasoning as
`hevy/sync.py:227-233` (`status()` delegating to `resource_status`).

**Pure-function-called-in-a-loop pattern** (`resolver.py:275-287`) — the function this phase
must call, with the docstring that names this phase as its caller:

```python
def apply_weights(
    muscles: Sequence[EffectiveMuscle],
    weights: Mapping[MuscleRole, Decimal] | None = None,
) -> dict[CanonicalMuscleGroup, Decimal]:
    """NORM-03: turn roles into weights at QUERY time.

    Defaults to 1.0 direct / 0.5 indirect. Pure and synchronous on purpose -- Phase 4 calls
    it inside aggregation loops and it must not touch a session.

    `Decimal`, never `float`: these multiply into tonnage sums, and binary floating point
    would make two arithmetically identical weekly totals compare unequal.
    """
    return {muscle.muscle_group: role_weight(muscle.role, weights) for muscle in muscles}
```

**The Python fan-out half should itself be a pure module-level function** taking plain rows and
a resolved mapping, so it is unit-testable with no container (C-1: "trivially unit-testable" is
the whole point). `resolver.py:57-95` shows the repo's private-pure-helper style
(`_sort_key`, `_muscle_group`, `_muscle_role`, `_mapping_source`) — small, single-purpose,
each with a docstring naming what breaks.

**Fail-loudly-on-bad-stored-data pattern** (`resolver.py:61-75`) — reuse the *shape* if any
enum-ish string is converted:

```python
def _muscle_group(value: str) -> CanonicalMuscleGroup:
    """Convert a stored string, or fail loudly.

    T-03-31: a value outside the taxonomy means a taxonomy change landed without a data
    migration. Dropping the row instead would shrink every per-muscle volume figure with no
    error anywhere in the stack -- a data-integrity failure that reads as a training slump.
    The message names the column and the value and NOT the user, because it will be logged.
    """
```

Note the last sentence: **error messages must not carry user data.** Applies to
`local_range_bounds`'s `ValueError` and to any range-clamp rejection (ASVS V5).

**Column semantics the aggregate must honour, quoted from the schema it reads**
(`workout.py:152-172`):

```python
    # Stored VERBATIM as Hevy sends it: 'normal' | 'warmup' | 'dropset' | 'failure'.
    # Coercing to an is_warmup boolean would discard the dropset/failure distinction
    # that Phase 5's PR detection needs. VOL-01 excludes exactly `set_type == 'warmup'`.
    set_type: Mapped[str] = mapped_column(String(16), nullable=False)

    # Numeric, never Float. Phase 4 sums thousands of these into tonnage and
    # 0.1 + 0.2 != 0.3 in binary floating point. Numeric(7,3) round-trips as an
    # exact Decimal. Hevy sends per-set weight already normalised to kilograms.
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(7, 3), nullable=True)
```

**The index this phase was promised** (`workout.py:81-90`):

```python
    __table_args__ = (
        UniqueConstraint(
            "user_id", "provider", "external_id", name="uq_workouts_user_provider_external_id"
        ),
        # Phase 4 filters every volume query by user and date window.
        Index("ix_workouts_user_id_start_time", "user_id", "start_time"),
    )
```

The `WHERE` clause must keep `Workout.start_time` **bare** on the left of both comparisons or
this index goes unused (RESEARCH Pitfall 2, `EXPLAIN`-verified: Seq Scan, 299 of 327 rows
removed).

**Structured logging** (`hevy/workouts.py:25,45` and `hevy/sync.py:21,36`):

```python
import structlog

log = structlog.get_logger()
```

Module-level, always that exact name, `snake_case` event names. Analytics is a read path — log
sparingly, counts only. The prohibition is concrete: `hevy/workouts.py:214-218` logs
`reason=type(exc).__name__` and explains why the exception text itself is forbidden ("Rendering
a DataError reproduces the offending bound parameter values -- i.e. this user's workout titles
and weights -- straight into a log line").

---

### `backend/app/analytics/frequency.py` (service, batch aggregate → transform)

**Analog:** `backend/app/analytics/volume.py` (same wave — plan the dependency), falling back
to `backend/app/normalization/resolver.py` for module shape.

Everything in the `volume.py` entry above applies unchanged: module docstring form, signature
convention, `import datetime as dt`, `Decimal` discipline, `log = structlog.get_logger()`,
bare-column `WHERE`.

**The one thing that is genuinely its own:** the `sessions_per_week` quantization. There is no
repo analog for `Decimal.quantize` — grep confirms zero uses in `backend/app/`. Use RESEARCH
Pattern 3 verbatim:

```python
days = (end_date - start_date).days + 1          # inclusive local-day span
weeks = Decimal(days) / Decimal(7)
sessions_per_week = (Decimal(len(session_ids)) / weeks).quantize(Decimal("0.01"))
```

Unquantized division returned `Decimal('3.1612903225806452')` against the live database.

**The de-duplication rule (Pitfall 5 — the most dangerous finding in the phase):** accumulate
`workout_id` into a Python `set()`, never a counter. Measured inflation up to **4.0×** on real
data. The `resolver.py:176-179` idiom is the closest structural precedent for a
"fold-into-a-dict-keyed-accumulator" loop:

```python
    resolved: dict[str, list[EffectiveMuscle]] = {}
    for template_id in requested:
        # The replacement rule, in one line: presence of ANY override wins outright.
        chosen = overrides.get(template_id) or base.get(template_id) or []
        resolved[template_id] = sorted(chosen, key=_sort_key)
    return resolved
```

Note `sorted(...)` on the way out. `resolver.py:51-58` explains why the sort key is spelled out
rather than left to enum ordering ("so renaming a role cannot silently reorder every Phase 4
result"), and `hevy/sync.py:94` sorts resources "so the report is deterministic and diffable
between runs." **Every analytics result list must come back deterministically ordered** —
weeks ascending, muscle groups by a stated key. A dict-iteration-order result is a flaky test
waiting to happen.

---

### `backend/app/core/time.py` — MODIFIED (utility, transform)

**Analog:** `local_day_bounds()`, `backend/app/core/time.py:73-83` — the function directly above
where the new one goes.

```python
def local_day_bounds(day: dt.date, tz: str) -> tuple[dt.datetime, dt.datetime]:
    """Half-open ``[start, end)`` UTC range covering one local day.

    Use this to FILTER in SQL. It compares the raw timestamp column against
    two constants, so an index on that column is usable -- unlike wrapping the
    column in ``AT TIME ZONE``, which forces a sequential scan.
    """
    zone = ZoneInfo(tz)
    start_local = dt.datetime.combine(day, dt.time.min, tzinfo=zone)
    end_local = start_local + dt.timedelta(days=1)
    return start_local.astimezone(dt.UTC), end_local.astimezone(dt.UTC)
```

**Copy:** the `tuple[dt.datetime, dt.datetime]` return type, the "Half-open ``[start, end)``"
docstring opener, the index rationale, and — critically — **implement the new function in terms
of the old one** rather than repeating the `ZoneInfo` arithmetic. RESEARCH Pattern 4 does
exactly that (`start_utc, _ = local_day_bounds(start_day, tz)`;
`_, end_utc = local_day_bounds(end_day, tz)`), which inherits for free the DST-nonexistent-
midnight correctness verified for `America/Santiago` 2026-09-06 and `Asia/Beirut` 2026-03-29.
Same reasoning as `resolver.py:103-104` ("a second copy here is how the two would eventually
disagree").

**Guard pattern** (`core/time.py:31-40`, `43-54`):

```python
def _require_aware(ts: dt.datetime) -> dt.datetime:
    """Fail loudly on naive datetimes.

    FOUND-04 is enforced by a guard, not a convention. Silently assuming UTC
    for a naive input is how a local-time value ends up mis-bucketed with no
    error anywhere in the stack.
    """
    if ts.tzinfo is None or ts.tzinfo.utcoffset(ts) is None:
        raise ValueError("naive datetime rejected: all timestamps must be timezone-aware UTC")
    return ts
```

The new function needs the `end_day < start_day` guard in this style — a `ValueError` with a
message that names the failure and carries no user data.

**Module docstring is already correct and must not be weakened** (`core/time.py:1-15`). It
already declares itself the single route for every day/week grouping — which is *why*
`local_range_bounds` belongs here rather than in `app/analytics/` (resolves CONTEXT.md's
discretion item; RESEARCH agrees).

**`validate_timezone()` (`core/time.py:43-54`) already exists and must be called** before the
tz string reaches `func.timezone(tz, col)` (ASVS V5). Its docstring literally anticipates this
phase: "would otherwise surface as a `ZoneInfoNotFoundError` from inside an aggregate query."

---

### `backend/app/db/models/exercise.py` — MODIFIED (docstring only)

**Analog:** `backend/app/db/models/workout.py:154-157` — the exemplar of an accurate,
consequence-naming column comment.

**The stale text** (`exercise.py:60-64`):

```python
    # Hevy's `type`, stored verbatim: weight_reps | reps_only | bodyweight_reps |
    # bodyweight_assisted_reps | duration | weight_duration | distance_duration |
    # short_distance_weight. This is the modality signal PROG-01 (Phase 5) needs to decide
    # whether an estimated 1RM is meaningful at all. Persist it now or resync everything later.
    exercise_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
```

Three listed values (`bodyweight_reps`, `bodyweight_assisted_reps`, `weight_duration`) occur in
**zero** live rows; four occurring values (`bodyweight_weighted`, `bodyweight_assisted`,
`floors_duration`, `steps_duration`) are unlisted. RESEARCH "Live Data Ground Truth" has the
verified table.

**Planner instruction:** make this an **explicitly listed task**, not an incidental edit
(RESEARCH Open Question 3). It is a Phase-3 artifact; the CONTEXT.md boundary names
`resolver.py`/`exercise_map.py`, not this docstring, so it is in scope — but it should be
visible in the plan. Add the "**do not hardcode a modality allow-list from this comment —
branch on operand presence**" warning while there, in the `workout.py:154-156` style.

---

### `backend/tests/conftest.py` — MODIFIED (test fixture, data setup)

**Analogs — three, composed:**
1. `backend/tests/conftest.py:208-229` — the existing `engine` / `session` fixture pair
2. `backend/app/integrations/hevy/workouts.py:82-173` — the Core-insert shape to mirror
3. `backend/tests/test_time.py:188-211` — the flush-then-rollback rule, documented in prose

**Existing fixture pattern to extend** (`conftest.py:208-229`):

```python
@pytest_asyncio.fixture
async def engine(postgres_url: str) -> AsyncEngine:
    """A per-test engine.

    One engine per fixture scope, never a module-level global: a global binds
    its pool to whichever event loop imported it, and pytest-asyncio gives each
    test a fresh loop.
    """
    engine = create_async_engine(postgres_url)
    try:
        yield engine  # type: ignore[misc]
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncSession:
    """A per-test ORM session bound to the migrated container."""
    maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with maker() as db_session:
        yield db_session  # type: ignore[misc]
```

Copy: `@pytest_asyncio.fixture` (not `@pytest.fixture`) for async fixtures; the
`try/yield/finally` shape; the `# type: ignore[misc]` on the yield (mypy's
`disallow_untyped_defs` plus the generator-vs-return mismatch — the repo already carries this
suppression twice, do not invent a different workaround).

**Never-commit rule, stated in prose at `conftest.py:1-12` and enforced by
`test_time.py:19-24`:**

```python
The Postgres container is session-scoped and shared, and ``test_migrations``
asserts ``count(*) == 1`` on ``users`` plus the seeded ``Asia/Jakarta`` value.
The two tests here that mutate state therefore never commit -- they roll back
in a ``finally``, which is strictly stronger than a compensating UPDATE
because it also survives an assertion failure mid-test.
```

And the concrete implementation (`test_time.py:194-211`):

```python
    user_id = uuid.uuid4()
    try:
        user = User(id=user_id, timezone="Asia/Jakarta", created_at=NEAR_MIDNIGHT_UTC)
        session.add(user)
        await session.flush()
        session.expire(user)
        ...
    finally:
        await session.rollback()
```

**`golden_workout` must be flush-and-rollback, not commit-and-delete.** Two reasons, both
verified in the existing suite: (a) rollback survives a mid-test assertion failure;
(b) `test_migrations.py`'s `count(*) == 1` assertion on `users` reads from a *separate*
connection and cannot see uncommitted rows. The commit-and-clean alternative is what
`test_normalization_mapping.py:83-94` and `test_sync_state.py:53-69` do — correct for *those*
modules because they test commit semantics; wrong here.

**Insert shape to mirror** (`hevy/workouts.py:149-172`) — explicit Core statements, `executemany`
for sets:

```python
        if exercise.sets:
            # executemany: a list of dicts as the SECOND argument to session.execute().
            # Measured at 44x faster than row-by-row for 12,000 rows; `sets` is by far the
            # highest-cardinality table this sync writes.
            await session.execute(
                insert(WorkoutSet),
                [
                    {
                        "id": uuid.uuid4(),
                        "workout_exercise_id": exercise_id,
                        "set_index": s.index,
                        "set_type": s.type,
                        "weight_kg": s.weight_kg,
                        "reps": s.reps,
                        ...
                    }
                    for s in exercise.sets
                ],
            )
```

**Where fixtures live** (`conftest.py:1-12` + `test_mcp_auth.py:74-79`): shared **fixtures**
go in `conftest.py`; shared **constants** are deliberately duplicated per module with a comment
explaining why ("test modules in this repo do not import each other, and a shared fixture file
would hide which envelope a given assertion actually sent"). So: `golden_workout` → `conftest.py`;
`INSUFFICIENT_DATA_SESSION_THRESHOLD`-style expected values → restated per test module.

**Existing shared constant that IS imported:** `DEFAULT_USER_ID` from
`tests.conftest` (`conftest.py:40`, imported by `test_sync_state.py:35` and
`test_normalization_mapping.py:40`). Use it.

---

### `backend/tests/test_analytics_volume.py` and `test_analytics_frequency.py` (test, integration)

**Analog:** `backend/tests/test_normalization_mapping.py` — closest in the repo: integration
tests over a provider-neutral pure-domain module, with fast-suite unit tests for the pure
functions in the same file.

**Module docstring pattern** (`test_normalization_mapping.py:1-15`):

```python
"""Effective muscle mapping: override-replaces-base, and the audit that proves it (NORM-02).

The rule under test is not the intuitive one. A per-row merge would let a user add a muscle or
change its role but never REMOVE one, ...

`test_base_rows_survive_an_override_unchanged` is the load-bearing one: it asserts `created_at`
as well as the triples, so an implementation that "helpfully" rewrote the base rows to match
the override would fail even if every value happened to line up.

The two `apply_weights` tests are pure and deliberately carry no integration marker -- NORM-03
should stay verifiable when Docker is not running.
"""
```

Carry across all three moves: (1) state the counter-intuitive rule; (2) **name the load-bearing
test and say what it would catch**; (3) explain which tests deliberately carry no `integration`
marker. For `test_analytics_volume.py` the load-bearing test is
`override_changes_answer` (Pitfall 4 — the only thing standing between this phase and a latent
wrong answer once `exercise_muscle_overrides` stops being empty).

**Non-colliding-fixture-ids convention** (`test_normalization_mapping.py:42-53`):

```python
# Distinct from the ids `test_hevy_templates.py` writes: the container is session-scoped and
# shared, so overlapping ids would make one module's cleanup delete the other's fixtures.
BASE_TEMPLATE = "RESOLVER-BASE"
OTHER_TEMPLATE = "RESOLVER-OTHER"
BARE_TEMPLATE = "RESOLVER-BARE"

SECOND_USER_ID = uuid.UUID("00000000-0000-0000-0000-0000000009e2")
```

Analytics fixtures need their own prefix (e.g. `ANALYTICS-*`) and their own second-user UUID.
`SECOND_USER_ID` is also the template for the **cross-tenant isolation test** ASVS V4 requires —
two users' workouts in the window, assert `user_id` scoping.

**Parametrized boundary-table test** (`test_time.py:62-83`) — the model for the week-boundary
and two-timezone fixtures:

```python
@pytest.mark.integration
@pytest.mark.parametrize(
    ("utc_iso", "expected_day"),
    [
        ("2026-08-23T16:30:00+00:00", dt.date(2026, 8, 23)),
        ("2026-08-23T17:00:00+00:00", dt.date(2026, 8, 24)),  # exact Jakarta midnight
        ("2026-08-23T23:30:00+00:00", dt.date(2026, 8, 24)),  # "near midnight UTC"
        ("2026-08-24T00:30:00+00:00", dt.date(2026, 8, 24)),
    ],
)
async def test_local_day_uses_user_timezone(
    session: AsyncSession, utc_iso: str, expected_day: dt.date
) -> None:
```

Note: `async def test_...` with **no** `@pytest.mark.asyncio` (`asyncio_mode = "auto"`,
`pyproject.toml:54`), `-> None` on every test (`disallow_untyped_defs`), and the boundary table
transcribed into the module docstring above it.

**Read the timezone from the database, never hardcode the argument**
(`test_time.py:15-18, 50-55`):

```python
async def _user_timezone(session: AsyncSession) -> str:
    """Read the tz from the database -- the FOUND-03 source of truth."""
    tz = (await session.execute(sa.text("select timezone from users"))).scalar_one()
    assert isinstance(tz, str)
    return tz
```

"Hardcoding the argument would make these tests pass even if the column were ignored entirely."
This is the exact mechanism RESEARCH's `two_timezones` fixture needs.

**Flip-the-timezone test with belt-and-braces cleanup** (`test_time.py:85-110`) — copy whole:

```python
    try:
        await session.execute(
            sa.text("update users set timezone = :tz"), {"tz": "America/New_York"}
        )
        ...
    finally:
        # Belt: undo the value. Braces: discard the whole transaction, so the
        # shared container is untouched even if an assertion above failed.
        await session.execute(sa.text("update users set timezone = :tz"), {"tz": "Asia/Jakarta"})
        await session.rollback()
```

**Bound parameters only, never f-string SQL** (`test_time.py:113-141`) — Ruff `S608`, and the
test that already asserts Python and SQL bucketing agree
(`test_python_and_sql_bucketing_agree`) is the precedent the new aggregate inherits.

**Guard-against-vacuous-pass idiom** (`test_time.py:183`, `test_hevy_isolation.py:39-48`):

```python
    # Guard against a vacuous pass if the schema were empty.
    assert rows, "no timestamp columns found -- the schema is not migrated"
```

Every analytics test that folds rows into buckets needs one: an empty result set makes
`assert all(...)` trivially true. RESEARCH Pitfall 11's "assert the inequality deliberately"
test is the same instinct.

**Fast-suite discipline:** the pure fan-out function and `sessions_per_week` arithmetic get
tests with **no** `@pytest.mark.integration`, exactly as `apply_weights` does
(`test_normalization_mapping.py:12-14`). Baseline to protect: **177 passed, 114 deselected in
0.94 s**.

---

### `backend/tests/test_analytics_metadata.py` (test, integration + unit)

**Analog:** `backend/tests/test_sync_state.py` — same subject matter (`sync_state` rows), same
split between container-backed tests and fast-suite redaction guards.

**Module docstring** (`test_sync_state.py:1-8`):

```python
"""Per-resource sync bookkeeping (HEVY-09, D-08).

The integration tests run against the real Postgres container because the whole point
of `ensure_sync_state` is the `ON CONFLICT` clause, which has no meaning outside
PostgreSQL. The two `format_sync_error` tests need no database and stay in the fast
suite -- they are the T-03-12 redaction guard, and that one should never be skippable
because Docker is not running.
"""
```

**Carry across verbatim in spirit:** the DQ-01 *no-leak* test must be a **fast-suite unit test**
— "that one should never be skippable because Docker is not running" applies exactly to
"no `last_error`, no DSN, no credential appears in any analytics return model."

**Non-colliding provider constant** (`test_sync_state.py:37-44`):

```python
# Deliberately NOT "hevy": these rows share a session-scoped container with every other
# integration test, and the cleanup below keys on this value. A test that wrote real
# `provider='hevy'` bookkeeping could delete a row a later test depended on.
_PROVIDER = "test-provider"

# Fixed and aware. Ruff's DTZ rules reject a naive literal, and `complete_sync` rejects
# one at runtime -- which `test_naive_last_synced_at_is_rejected` relies on.
_SYNCED_AT = dt.datetime(2026, 8, 29, 6, 0, tzinfo=dt.UTC)
```

**Cleanup fixture with rollback-before-delete** (`test_sync_state.py:53-69`):

```python
@pytest_asyncio.fixture
async def bookkeeping(session: AsyncSession) -> AsyncIterator[AsyncSession]:
    """A session whose `sync_state` rows are removed afterwards, pass or fail."""
    try:
        yield session
    finally:
        # Roll back anything the test left uncommitted before issuing the DELETE:
        # a failed statement poisons the transaction, and the cleanup would then
        # fail too and mask the real assertion error.
        await session.rollback()
        await session.execute(
            sa.delete(SyncState).where(
                SyncState.user_id == DEFAULT_USER_ID,
                SyncState.provider == _PROVIDER,
            )
        )
        await session.commit()
```

**Per-resource independence test** (`test_sync_state.py:108-120`) is the direct DQ-01
precedent — it already asserts three resources carry three independent `last_synced_at`
values, with the docstring "A single `last_synced_at` on a connections table would report the
newest of the three for all of them, which is precisely the staleness Claude must be able to
see." That is RESEARCH A4's argument, already in the suite.

**No-leak assertion technique** — the strongest example is
`test_hevy_end_to_end.py:74-76` + `:477-521`:

```python
# One workout title and two body-composition values, exactly as the fixtures carry them.
# `test_no_health_data_reaches_the_log_stream` asserts none of the three survives into a line.
HEALTH_DATA_IN_FIXTURES = ("Push Day", "80.5", "18.5")
```

```python
    for value in HEALTH_DATA_IN_FIXTURES:
        assert value not in scanned, f"T-03-46 violated: {value!r} reached the log stream"
```

For the analytics no-leak test, seed a distinctive `sync_state.last_error` (the
`test_hevy_end_to_end.py:70` idiom: "Distinctive on purpose, so a leak is unambiguous rather
than a coincidence") and assert it is absent from `model_dump_json()` of every return model.

---

### `backend/tests/test_analytics_isolation.py` (test, static — fast suite)

**Analog:** `backend/tests/test_hevy_isolation.py` — near-perfect, copy the whole file's
structure.

**Module docstring** (`test_hevy_isolation.py:1-15`):

```python
"""HEVY-05: nothing Hevy-shaped escapes `app/integrations/hevy/`.

Static assertions over committed source: no container, no network, and deliberately no
integration marker -- a boundary violation must fail the FAST suite on the commit that
introduces it, not after a deploy.

The boundary is what makes Hevy replaceable. ... if a Pydantic Hevy model is imported by
`db/`, `normalization/` or (later) `analytics/`, that change stops being a one-package problem.
"""
```

Note the docstring **already names `analytics/`** as a future member of the protected set.

**Walk + regex, not substring** (`test_hevy_isolation.py:17-36`):

```python
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APP = REPO_ROOT / "backend" / "app"
HEVY_PKG = APP / "integrations" / "hevy"

# Matched at the START of a line (modulo indentation) so a mention inside a docstring or a
# comment -- of which there are several, deliberately -- is not read as an import.
_HTTPX2_IMPORT = re.compile(r"^\s*(?:import httpx2|from httpx2)", re.MULTILINE)
_INTEGRATIONS_IMPORT = re.compile(r"^\s*(?:import|from)\s+app\.integrations", re.MULTILINE)
```

Add `_MCP_IMPORT = re.compile(r"^\s*(?:import|from)\s+app\.mcp", re.MULTILINE)`. **The regex
form is mandatory, not stylistic**: `analytics/__init__.py`'s docstring will state the rule in
prose, and a substring check would fail on the sentence documenting the boundary — exactly the
trap `test_hevy_isolation.py:88-93` records.

**Guard on the guards** (`test_hevy_isolation.py:39-48`):

```python
def test_the_walk_actually_finds_files() -> None:
    """A guard on the guards: an empty walk would make every test below vacuously true.

    If `APP` were ever wrong -- a moved package, a renamed directory -- `rglob` returns
    nothing and four boundary tests pass while checking nothing at all.
    """
    outside = _app_modules_outside_hevy()

    assert len(outside) > 10, f"the walk found only {len(outside)} modules under {APP}"
```

**Mandatory.** Without it a mistyped `APP / "analytics"` makes every boundary assertion pass.

**Per-boundary test with a consequence-naming message** (`test_hevy_isolation.py:82-100`):

```python
def test_normalization_does_not_import_integrations() -> None:
    """The exercise -> muscle-group mapping is provider-NEUTRAL and must stay that way. ..."""
    for path in sorted((APP / "normalization").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        assert not _INTEGRATIONS_IMPORT.search(source), (
            f"HEVY-05 violated: {path.relative_to(REPO_ROOT)} imports app.integrations. "
            f"The normalization layer is provider-neutral by design"
        )
```

Two new tests in this shape: `test_analytics_does_not_import_integrations` and
`test_analytics_does_not_import_mcp`. A third worth adding, from RESEARCH Pitfall 4's warning
sign ("any `exercise_muscles` table name appearing in an `app/analytics/` module"):
assert the strings `ExerciseMuscle` / `exercise_muscles` do not appear in
`app/analytics/*.py` — that is a **static guarantee the resolver is being used**, cheap and
in the fast suite.

**Consider extending `test_hevy_isolation.py` instead of only adding a new file** — its
`_app_modules_outside_hevy()` walk (`:30-36`) uses `rglob` "so a new subpackage must be covered
by this boundary the moment it exists, without anyone remembering to add it here." Creating
`app/analytics/` therefore auto-extends the existing HEVY-05 coverage with **no edit at all**.
Verify that stays green; do not duplicate it.

---

### `backend/tests/test_time.py` — MODIFIED (test, unit)

**Analog:** `test_local_day_bounds_is_half_open_utc`, same file, `:243-253`:

```python
def test_local_day_bounds_is_half_open_utc() -> None:
    """Index-friendly filter bounds: the range must be UTC and half-open."""
    start, end = local_day_bounds(dt.date(2026, 8, 24), "Asia/Jakarta")
    assert start == dt.datetime(2026, 8, 23, 17, 0, tzinfo=dt.UTC)
    assert end == dt.datetime(2026, 8, 24, 17, 0, tzinfo=dt.UTC)
    assert start.utcoffset() == dt.timedelta(0)
    assert end.utcoffset() == dt.timedelta(0)
    # Half-open: the end bound is the *next* day's start, never inclusive.
    assert local_day(start, "Asia/Jakarta") == dt.date(2026, 8, 24)
    assert local_day(end, "Asia/Jakarta") == dt.date(2026, 8, 25)
```

Mirror it for `local_range_bounds`: exact UTC literals, both offsets asserted zero, half-openness
asserted through `local_day()` rather than by arithmetic, plus a
`pytest.raises(ValueError)` case for `end_day < start_day` in the style of
`test_naive_datetime_rejected` (`:214-223`) and `test_validate_timezone` (`:255-258`).

Add to the existing import block (`test_time.py:35-42`) rather than creating a second one.

---

## Shared Patterns

### 1. Module docstring convention — every new file

**Source:** `backend/app/core/time.py:1-15`, `backend/app/normalization/resolver.py:1-18`,
`backend/app/db/models/workout.py:1-14`, `backend/app/integrations/hevy/sync.py:1-14`
**Apply to:** all 5 new `app/analytics/` modules and all 4 new test modules

The invariant, unchanged from 03-PATTERNS.md and still true of every file in the repo:
**name the requirement ID, state the counter-intuitive rule, then name concretely what breaks.**
Not one module opens with "This module contains the X class."

This phase has unusually good raw material: RESEARCH's Pitfalls carry *measured* failure
numbers (543/7,719 sets; 4.0×; 823 dropsets; 48 zero-weight sets; 299 rows removed by filter).
The repo already writes in this register — `hevy/workouts.py:150-152` says "Measured at 44x
faster than row-by-row for 12,000 rows." **Quote the numbers.**

### 2. Function signature convention — non-negotiable

**Source:** `resolver.py:97-99, 111-116, 215-222, 256-258`, `sync_state.py:88-89, 101-102,
154-162`, `hevy/workouts.py:82-84, 176, 198-200`

```python
async def f(session: AsyncSession, *, user_id: uuid.UUID, ...) -> T:
```

Positional `session`, keyword-only everything else, `AsyncSession` (never `async_sessionmaker`,
never an engine, never `Settings`). Verified across six modules. Two consequences:
(a) it matches every repository in the codebase; (b) it is what makes the flush-and-rollback
golden fixture visible to the function under test — a function that opened its own session would
run in a different transaction and see none of the fixture rows.

**Never commit inside these functions.** `sync_state.py:1-9`: "Every function takes an
`AsyncSession` and never commits. The CALLER owns the transaction."

### 3. Structured logging

**Source:** `backend/app/integrations/hevy/sync.py:21,36`, `backend/app/mcp/tools/ping.py:14,21`,
`backend/app/api/routes/health.py:9,14`
**Apply to:** `volume.py`, `frequency.py`, `metadata.py` (sparingly — this is a read path)

```python
import structlog

log = structlog.get_logger()
```

Module-level, always that exact name. `snake_case` event names as the first positional arg,
structured kwargs after: `log.info("hevy_sync_all_completed", mode=resolved, templates=..., ...)`
(`hevy/sync.py:212-218`).

**Counts and identifiers only, never row contents.** The rule is spelled out at
`hevy/sync.py:209-211`: "COUNTS and the mode, never a title, a weight or a measurement. This
line is written on every successful run, so anything that reached it would reach the log sink on
every run." And `hevy/workouts.py:214-218` for the exception case:
`reason=type(exc).__name__`, never `str(exc)`.

Suggested events if any: `analytics_weekly_volume_completed` with `week_count` / `duration_ms`.

### 4. Degrade-don't-leak on driver exceptions

**Source:** `backend/app/api/routes/health.py:30-38`, `backend/app/mcp/tools/ping.py:34-43`

```python
    except Exception:  # noqa: BLE001 - any failure to reach the DB must degrade, not error
        # Mirrors health.py: the detail goes to the log (which runs through the
        # redaction pipeline); the caller gets only the coarse state. Connection
        # errors carry the DSN, host, and driver internals (T-02-09, FOUND-05).
        log.exception("mcp_ping_db_check_failed")
        database = "error"
```

Note the mandatory inline reason on the `# noqa: BLE001` (Ruff `B` rule). ASVS V7 for this
phase: an asyncpg exception can carry the DSN. Analytics must not return raw driver text to a
caller. **But** do not over-apply — an aggregate that fails should propagate, not silently
return zeros; the pattern is about *what reaches the caller*, not about swallowing errors.

### 5. Decimal, never float — and never `float` in a return type

**Source:** `backend/app/db/models/workout.py:159-162`, `backend/app/normalization/muscles.py:142-148`,
`backend/app/normalization/resolver.py:283-286`, `backend/app/integrations/hevy/schemas.py:38-42`

Four independent modules state the same rule with the same justification. `Decimal * int` stays
exact; Postgres `SUM(numeric)` and Python `sum(..., Decimal(0))` were verified to produce
identical values *and identical string representations* over 7,176 live sets.

Pitfall 8 adds one nuance the models do not: `Numeric(7,3)`'s declared precision on an
*aggregate* is cosmetic — the safety comes from asyncpg's `result_processor` returning `None`.
If a computed aggregate needs a documented precision, pass it explicitly:
`func.sum(expr, type_=Numeric(18, 3))`.

### 6. Deterministic ordering on every returned collection

**Source:** `resolver.py:51-58` (`_ROLE_ORDER` spelled out), `resolver.py:179` (`sorted(chosen, key=_sort_key)`),
`resolver.py:206-211` ("Sorted so a curation report is stable between runs and diffable"),
`hevy/sync.py:94` (`for resource in sorted(SYNC_RESOURCES)`)

```python
# DIRECT before INDIRECT. Spelled out rather than relying on the enum values sorting
# alphabetically ("direct" < "indirect" only by luck), so renaming a role cannot silently
# reorder every Phase 4 result.
_ROLE_ORDER: Mapping[MuscleRole, int] = {MuscleRole.DIRECT: 0, MuscleRole.INDIRECT: 1}
```

That comment names *this phase* as the victim of getting it wrong. Weeks ascending, muscle
groups by a stated key, exercises by a stated key. Never dict-iteration order.

### 7. Test suite mechanics

**Source:** `pyproject.toml:53-59`, `backend/tests/conftest.py:149-168`

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["backend/tests"]
pythonpath = ["backend"]
markers = [
    "integration: test requires a live Postgres container (deselect with -m 'not integration')",
]
```

- `async def test_...` needs **no** decorator; `@pytest_asyncio.fixture` for async fixtures.
- Container-touching tests need `@pytest.mark.integration` (C-3).
- Container is `postgres:18-alpine`, `driver="asyncpg"`, migrated by a real
  `alembic upgrade head` **subprocess** (`conftest.py:156-167`), not `metadata.create_all`.
- Baseline fast suite to protect: **177 passed, 114 deselected in 0.94 s**.
- `backend/tests/*` waives `S101`, `S105`, `S106` (`pyproject.toml:74`).
- Shared session-scoped container: every committing test needs `finally`-block cleanup, and
  every fixture that can avoid committing **should** (`test_time.py:19-24`).

### 8. Lint / type gates every new file must pass

**Source:** `pyproject.toml:61-86`

```toml
[tool.ruff]
line-length = 100
target-version = "py313"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "ASYNC", "S", "DTZ"]

[tool.ruff.lint.isort]
known-first-party = ["app"]
```

```toml
[tool.mypy]
python_version = "3.13"
disallow_untyped_defs = true
mypy_path = "backend"
```

Consequences specific to this phase:
- **`S608`** — no f-string SQL. The timezone reaches SQL via `func.timezone(tz, col)`, a **bound
  parameter**. `test_time.py:118-119` already documents the rule for tests.
- **`DTZ`** — no naive datetime construction. Every literal needs `tzinfo=dt.UTC`
  (`test_sync_state.py:42-44`); the deliberate exceptions carry `# noqa: DTZ001` with a reason
  (`test_time.py:217-223`).
- **`disallow_untyped_defs`** — every function, fixture and helper fully annotated; `-> None`
  on tests.
- **`B` / `BLE001`** — bare-except suppressions need an inline reason
  (`ping.py:38`, `health.py:35`).
- **No new `[[tool.mypy.overrides]]`** — zero new dependencies this phase.

### 9. Dependencies — nothing to add

**Source:** `pyproject.toml:6-51`, RESEARCH "Environment Availability"

Every library is pinned and installed. **This phase adds zero entries to `pyproject.toml`.** If a
plan proposes a dependency, that is a signal the design drifted from CLAUDE.md's
"SQL aggregates + plain Python" (contrast Phase 3, where `tenacity` and the `httpx2` group-move
were both required).

---

## No Analog Found

One item, and it is the phase's genuinely new tier.

| File / concern | Role | Data Flow | Reason | Use instead |
|---|---|---|---|---|
| The SQL aggregate inside `backend/app/analytics/volume.py` and `frequency.py` | service (query construction) | batch aggregate | **Verified by grep across `backend/app/**/*.py`: `group_by`, `date_trunc`, `func.sum`, `.filter(`, `func.timezone` and `cast(` appear in zero lines of application code.** The only `func.count` in the repo is a bare `select(func.count()).select_from(Workout)` at `hevy/workouts.py:301-307`. There is no `FILTER (WHERE ...)`, no `AT TIME ZONE`, no grouped query anywhere to copy. | **RESEARCH.md Pattern 1** (full statement, with its rendered SQL and observed result types) and **Pattern 2** (the Python fan-out), both executed against live PostgreSQL 18.6 with this repo's pinned SQLAlchemy 2.0.52 + asyncpg 0.31.0. Take the module *shape* from `resolver.py` and the *statement* from RESEARCH. Do not reach for a web example: SQLAlchemy 1.x `session.query(...)` style is wrong here (RESEARCH "State of the Art"). |

Everything else in the phase has a real analog. Notably **absent** from this list, unlike Phase 3:
no new dependency, no new model, no new migration, no new entrypoint, no new exception hierarchy,
no new fixture directory.

---

## Cross-Cutting Risks the Planner Should Route Into Plan Actions

1. **Pitfall 4 is a *pattern* risk, not just a correctness risk.** The pure-SQL muscle join
   produces byte-identical output today (all 16 muscle groups verified) because
   `exercise_muscle_overrides` has 0 rows. A reviewer comparing the two would see no difference.
   The enforcement is the `override_changes_answer` test **plus** the static assertion in
   `test_analytics_isolation.py` that `exercise_muscles` never appears in `app/analytics/*.py`.
   Plan both; either alone can be worked around.

2. **`app/analytics/` auto-inherits the HEVY-05 boundary** via
   `test_hevy_isolation.py:30-36`'s `rglob`. Creating the package extends an existing test with
   no edit — confirm it stays green rather than duplicating the assertions.

3. **The `exercise_type` docstring fix (`exercise.py:60-64`) must be an explicit plan task**, not
   an incidental edit. It is a Phase-3 artifact; RESEARCH Open Question 3 argues in scope, and the
   CONTEXT.md boundary names `resolver.py`/`exercise_map.py`, not this file.

4. **Two RESEARCH assumptions want a user call at plan review, and both change the return shape:**
   A3 (snap weekly-volume windows outward to whole local weeks; frequency keeps the raw range) and
   A5 / Open Question 1 (response-level `insufficient_data` per D-06 **plus** a per-row `sessions`
   count). Deciding these after `schemas.py` is written costs a rewrite of every test's expected
   value.

5. **`conftest.py` is edited by this phase and is imported by every test module in the suite.**
   The `golden_workout` fixture must not commit and must not collide with the seeded single user
   (`test_migrations.py` asserts `count(*) == 1` on `users` from a separate connection). Plan the
   fixture before the tests that consume it.

6. **Cross-tenant scoping is untestable by accident in a single-user suite** (ASVS V4). A
   `SECOND_USER_ID` isolation test is required, and
   `test_normalization_mapping.py:53, 83-94` already has the create-and-clean-up-a-second-user
   pattern to copy.

7. **`volume.py` → `frequency.py` is a real dependency** if the shared `_weekly_volume_rows`
   aggregate lives in `volume.py`. Either sequence the plans, or extract the shared aggregate into
   a third private module before parallelizing.

---

## Metadata

**Analog search scope:** `backend/app/` (41 modules), `backend/tests/` (26 modules + conftest),
`backend/migrations/`, `pyproject.toml`, `.planning/phases/03-*/03-PATTERNS.md`

**Files scanned:** 68 Python files + `pyproject.toml`; full reads of `core/time.py`,
`normalization/resolver.py`, `normalization/muscles.py`, `normalization/__init__.py`,
`db/repositories/sync_state.py`, `db/models/workout.py`, `db/models/exercise.py` (head),
`db/models/__init__.py`, `integrations/hevy/schemas.py`, `integrations/hevy/workouts.py`,
`integrations/hevy/sync.py`, `mcp/tools/ping.py`, `api/routes/health.py`, `tests/conftest.py`,
`tests/test_time.py`, `tests/test_hevy_isolation.py`, and partial reads of
`tests/test_sync_state.py`, `tests/test_normalization_mapping.py`, `tests/test_hevy_end_to_end.py`,
`tests/test_mcp_auth.py`, `app/cli.py`

**Grep verifications performed:** `group_by|func.sum|date_trunc|.filter(|func.timezone|cast(`
over `backend/app/**/*.py` (zero hits outside docstrings); `func.count` (one hit);
`BaseModel` (two modules)

**Project skills:** none found — `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`,
`.github/skills/` all absent. Conventions extracted from `CLAUDE.md` and from the code itself.

**Pattern extraction date:** 2026-08-30

---

*Phase: 04-volume-frequency-analytics*
