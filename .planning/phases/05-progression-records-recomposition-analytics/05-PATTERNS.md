# Phase 5: Progression, Records & Recomposition Analytics - Pattern Map

**Mapped:** 2026-08-30
**Files analyzed:** 19 (6 new app modules, 3 extended app modules, 6 new test files, 3 extended test files, 1 optional docstring edit)
**Analogs found:** 18 / 19 (one *partial* — `bodyweight.py`; see "No Analog Found")

> **The one-sentence summary for the planner.** Unlike Phase 4 — which had to invent the SQL
> aggregate from scratch — Phase 5 has a **complete, shipped, reviewed precedent for every single
> file it creates**, sitting in the same directory. `progression.py`, `records.py` and
> `comparison.py` are structurally `volume.py`/`frequency.py` with a different fold in the middle;
> `estimates.py` is `frequency.sessions_per_week()` grown to 30 lines; the new `schemas.py` types
> are more `_AnalyticsModel` subclasses in the module that already holds them; `qualifying_set_rows()`
> is `weekly_set_rows()` at a finer grain in the same file. The **only** thing with no analog
> anywhere in `backend/app/` is reading `body_measurements` — no application module has ever
> queried that table (verified by grep: `BodyMeasurement` appears only under `app/db/models/`
> and `app/integrations/hevy/`, the write path analytics may not import). For that one file,
> RESEARCH.md Pattern 8 is the source, with `metadata.py`'s windowed-scalar-read shape as the
> structural template.

---

## File Classification

### New — application code

| New File | Role | Data Flow | Closest Analog | Match Quality |
|----------|------|-----------|----------------|---------------|
| `backend/app/analytics/estimates.py` | utility (pure, no session) | transform | `backend/app/analytics/frequency.py:57-79` (`_RATE_QUANTUM` + `sessions_per_week`) + `backend/app/normalization/muscles.py:50-57` (`StrEnum`) | **exact** |
| `backend/app/analytics/progression.py` | service (query + pure fold) | batch aggregate → transform | `backend/app/analytics/volume.py` (whole file: `_WeekTotals` → `_fold_week_totals` → `get_weekly_volume`) | **exact** |
| `backend/app/analytics/records.py` | service (query + pure scan) | batch aggregate → transform | `backend/app/analytics/frequency.py:106-175` (`get_training_frequency` composition) | **exact** |
| `backend/app/analytics/comparison.py` | service (two windows + reuse) | batch aggregate → transform | `backend/app/analytics/frequency.py:106-175` — the *only* unsnapped-window consumer, and the function CMP-01 literally reuses | **exact** |
| `backend/app/analytics/bodyweight.py` | service (row fetch + pure fold) | batch → transform | `backend/app/analytics/metadata.py:67-109` (windowed scalar reads) + `frequency.py:57-79` (quantum) — *no module has ever read `body_measurements`* | **partial** |
| `backend/app/analytics/recomposition.py` | service (composition only) | transform (no SQL of its own) | `backend/app/analytics/volume.py:204-286` (`get_muscle_group_volume` — composes window + aggregate + two folds + envelope) | role-match |

### Extended — application code

| Modified File | Change | Closest In-File Analog | Match Quality |
|---------------|--------|------------------------|---------------|
| `backend/app/analytics/rollup.py` | `+ QualifyingSetRow`, `+ qualifying_set_rows()` at set grain | `SetRollupRow` `:154-174` and `weekly_set_rows()` `:192-266` **in the same file** | **exact** |
| `backend/app/analytics/schemas.py` | `+ ~10 return types`, `+ 4 StrEnums`, `+ MeasurementCoverage` | `CoverageMetadata` `:70-80`, `MuscleGroupVolume` `:102-119`, `TrainingFrequencyResult` `:157-169` **in the same file** | **exact** |
| `backend/app/analytics/metadata.py` | `+ FRESHNESS_RESOURCES_BODY`, `+ FRESHNESS_RESOURCES_ALL`, `+ MEASURED_DAY_FLOORS`, `+ build_measurement_coverage()` | `FRESHNESS_RESOURCES_MUSCLE` `:58-59`, `is_insufficient()` `:62-64`, `build_coverage()` `:139-154` **in the same file** | **exact** |
| `backend/app/analytics/__init__.py` | *(optional)* widen the docstring's requirement list from `VOL-01..03` to include `PROG-*`/`CMP-01`/`BODY-*` | itself `:1` | **exact** |

> RESEARCH.md says `__init__.py` is UNCHANGED. Its first line currently reads *"Deterministic
> volume and frequency analytics (VOL-01..03, DQ-01, DQ-02)"*, which will be stale after this
> phase. Planner's call — but if it is edited, note that `test_analytics_isolation.py` reads
> every file in this package as text and its docstring already deliberately avoids the ORM class
> names; keep that convention.

### New — tests

| New File | Role | Data Flow | Closest Analog | Match Quality |
|----------|------|-----------|----------------|---------------|
| `backend/tests/test_analytics_estimates.py` | test (unit, **fast suite** — no marker) | pure | `backend/tests/test_analytics_frequency.py:100-110` (`test_sessions_per_week_arithmetic_is_exact`, markerless by design) | **exact** |
| `backend/tests/test_analytics_progression.py` | test (integration + fast unit) | container-backed + pure | `backend/tests/test_analytics_frequency.py` (whole file) | **exact** |
| `backend/tests/test_analytics_records.py` | test (integration) | container-backed | `backend/tests/test_analytics_frequency.py` | **exact** |
| `backend/tests/test_analytics_comparison.py` | test (integration) | container-backed | `backend/tests/test_analytics_frequency.py` | **exact** |
| `backend/tests/test_analytics_bodyweight.py` | test (integration + fast unit) | container-backed + pure, **`time-machine` frozen** | `backend/tests/test_analytics_frequency.py` (shape) — *no existing test freezes the clock* | role-match |
| `backend/tests/test_analytics_recomposition.py` | test (integration) | container-backed, frozen clock | same as above | role-match |

### Extended — tests

| Modified File | Change | Closest In-File Analog | Match Quality |
|---------------|--------|------------------------|---------------|
| `backend/tests/conftest.py` | `+ GoldenBuilder.body_measurement()` | `GoldenBuilder.template()` `:337-385` (Core `insert` + `flush`, kwargs-only, `user_id` default) | **exact** |
| `backend/tests/test_analytics_isolation.py` | `+ no-float guard`, `+ no-Epley-in-SQL guard` | `_RAW_SQL_TEXT` `:44` + `test_analytics_uses_no_raw_sql_text` `:126-140` **in the same file** | **exact** |
| `backend/tests/test_analytics_metadata.py` | `+ MeasurementCoverage`, `+ body freshness`, `+ leak guard on new models` | `test_*` around `_LEAK_SENTINEL` `:63+` and the `FRESHNESS_RESOURCES_MUSCLE` cases **in the same file** | **exact** |

### Not modified — verify, do not touch

| File | Why the planner should confirm it stays untouched |
|------|--------------------------------------------------|
| `backend/app/analytics/volume.py` | CONTEXT.md `<domain>`: "Any change to volume/frequency (Phase 4, already complete)… this phase consumes both, it doesn't modify them" |
| `backend/app/analytics/frequency.py` | Same. `sessions_per_week()` is already public *for CMP-01* (`frequency.py:71-74` says so). CMP-01 **calls** it; it does not change it |
| `backend/app/core/time.py` | `local_range_bounds()`, `local_day()`, `utc_now()`, `local_week_spine()` already cover every window Phase 5 needs. Adding a helper here is a design-drift signal |
| `backend/app/normalization/*` | Phase 3 muscle engine. Consumed via `rollup.resolve_row_muscles()` only |
| `backend/app/db/models/*` | **No migration this phase.** `BodyMeasurement` already has `weight_kg` + `measured_on`; `WorkoutSet` already has everything e1RM needs |
| `pyproject.toml` | **Zero new dependencies.** RESEARCH.md: "A proposed new dependency in any Phase-5 plan is a design-drift signal" |

---

## Pattern Assignments

### `backend/app/analytics/estimates.py` (utility, pure transform)

**Analog:** `backend/app/analytics/frequency.py:57-79` — the repo's only existing *public, pure,
session-free, quantized* analytics function. Copy its four properties exactly: module-level
quantum constant with a "why this number" comment, `Decimal` throughout, a raise-don't-guess
guard, and a docstring that says why it is public.

**Quantum-constant pattern** (`frequency.py:57-60`):
```python
# Two places, matching blueprint 23's own `2.0x/week` example. Unquantized division returned
# Decimal('3.1612903225806452') against the live database -- a number no coach would read and no
# test could assert on stably.
_RATE_QUANTUM = Decimal("0.01")
```
→ Phase 5 writes `_E1RM_QUANTUM = Decimal("0.001")` (mirrors `workout_sets.weight_kg`
`Numeric(7,3)`), and `progression.py` writes `_SLOPE_QUANTUM = Decimal("0.0001")` /
`_PERCENT_QUANTUM = Decimal("0.01")`. **One quantum per quantity, applied at the boundary,
never two copies.**

**Pure-public-function pattern** (`frequency.py:63-79`):
```python
def sessions_per_week(sessions: int, days: int) -> Decimal:
    """Exact sessions-per-week over an arbitrary INCLUSIVE local-day span.

    ``Decimal`` throughout, never binary floating point: 10 days is exactly 10/7 weeks, and
    binary floating point would make two arithmetically identical rates compare unequal.

    Public rather than private so Phase 5's CMP-01 per-week normalization reuses this one
    definition instead of re-deriving it, and so the formula stays unit-testable with no
    container.

    A window of zero days is a caller bug, not a zero rate -- raising beats returning a number
    that silently divides by nothing. The message carries no user data because it will be logged.
    """
    if days <= 0:
        raise ValueError("window length must be positive")
    weeks = Decimal(days) / Decimal(7)
    return (Decimal(sessions) / weeks).quantize(_RATE_QUANTUM)
```

**Enum pattern** (`backend/app/normalization/muscles.py:19, 50-57`):
```python
from enum import StrEnum


class MuscleRole(StrEnum):
    """How hard a muscle works in an exercise. NORM-03 stores the role, never the weight."""

    DIRECT = "direct"
    INDIRECT = "indirect"
```
→ `NoEstimateReason` lives here (it is an *input-side* business rule, next to the gates that
produce it). `TrendVerdict`, `PlateauConfidence` and `RecompositionStatus` are **return-contract**
values and belong in `schemas.py` beside the models that carry them — see the note there.

**Target code:** RESEARCH.md Pattern 1 is complete and executable; copy it verbatim including the
"NEVER write this in SQL" paragraph.

---

### `backend/app/analytics/rollup.py` — EXTENDED (`qualifying_set_rows`)

**Analog:** `weekly_set_rows()` at `rollup.py:192-266`, **in the same file**. The new function is
the same statement at a finer grain with no `GROUP BY`.

**Row dataclass pattern** (`rollup.py:154-174`):
```python
@dataclass(frozen=True, slots=True)
class SetRollupRow:
    """One (local week, workout, exercise template) group of non-warmup sets.

    ``tonnage_sets`` sits beside ``tonnage_kg`` deliberately. SQL ``SUM`` skips NULL products
    without a warning, so an unguarded tonnage figure is a real number computed over a silently
    smaller population -- 543 of 7,719 live non-warmup sets produce a NULL product. ...
    """

    week_start: dt.date
    workout_id: uuid.UUID
    template_external_id: str
    hard_sets: int
    total_reps: int | None
    tonnage_sets: int
    tonnage_kg: Decimal | None
```
→ `QualifyingSetRow` is `frozen=True, slots=True` with the same "why this grain and not the
obvious one" docstring paragraph.

**The four load-bearing query mechanics to copy verbatim** (`rollup.py:206-250`):
```python
    # `cast(..., Date)` is NOT cosmetic. `date_trunc` over a timestamp-without-time-zone yields
    # a NAIVE datetime, which never compares equal to the `datetime.date` week keys the spine
    # and the folds use -- the merge would then silently produce two entries per week.
    #
    # `func.timezone(tz, col)` keeps the timezone a BOUND PARAMETER (T-04-01). Never f-string it.
    week = cast(func.date_trunc("week", func.timezone(window.tz, Workout.start_time)), Date)
    ...
        .where(
            # T-04-02: the tenant predicate leads, and `user_id` is keyword-only with no default,
            # so forgetting it is a TypeError rather than a cross-tenant read.
            Workout.user_id == user_id,
            # The column stays BARE on the left of both comparisons -- that is what keeps
            # `ix_workouts_user_id_start_time` usable. Converting the column's timezone here
            # instead was measured as a Seq Scan removing 299 of 327 rows.
            Workout.start_time >= window.utc_start,
            Workout.start_time < window.utc_end,
            *_hard_set_predicates(),
        )
        # Deterministic ordering is a repo-wide rule (`resolver.py`, `hevy/sync.py`);
        # dict-iteration order is a flaky test waiting to happen.
        .order_by(week, Workout.id, WorkoutExercise.exercise_template_external_id)
```
1. `cast(func.timezone(window.tz, Workout.start_time), Date)` — **the same trap, without
   `date_trunc`** (RESEARCH Pitfall 11). Phase 5 needs a local **day**, not a week.
2. Tenant predicate leads the `WHERE`.
3. `Workout.start_time` stays **bare** on both range comparisons.
4. `*_hard_set_predicates()` — **reuse it, never re-spell the warm-up exclusion.**
   `WARMUP_SET_TYPE` (`rollup.py:60`) has exactly one definition and D-08 depends on it being an
   *exclusion* (823 live dropsets stay PR-eligible).

**No-row-cap docstring** (`rollup.py:202-204`) — copy the paragraph verbatim; the guard is
`MAX_ANALYTICS_WINDOW_DAYS` at `build_window()`, not a `LIMIT`.

**Driver-value pass-through** (`rollup.py:259-263`):
```python
            total_reps=int(row.total_reps) if row.total_reps is not None else None,
            tonnage_sets=row.tonnage_sets,
            # Left exactly as the driver returns it: `Decimal | None`, never coerced. `None`
            # means "no set in this group had both operands", which is not zero kilograms.
            tonnage_kg=row.tonnage_kg,
```

**New for Phase 5, no in-file analog:** the `outerjoin` to `ExerciseTemplate` carrying its own
tenant predicate. The nearest precedent is `frequency._template_titles` (`frequency.py:82-103`),
whose docstring already documents *why* the tenant predicate is repeated on templates:
```python
    """Titles for the templates in the window, in ONE query.

    A workout can reference a template that does not exist locally -- ``workout_exercises``
    stores a plain string, deliberately not a foreign key, so an unsynced or upstream-deleted
    template must not block anything. Missing templates simply have no title.

    T-04-02: the tenant predicate is explicit here as well as on the workout aggregate. Template
    ids are shared across users -- Hevy's built-in ids are global -- so omitting it would let one
    user's exercise title be attached to another user's frequency row.
    """
```
→ `qualifying_set_rows()` must **`outerjoin`, never `join`** (RESEARCH anti-pattern list), and the
join condition carries `ExerciseTemplate.user_id == user_id`. Full statement in RESEARCH Pattern 2.

---

### `backend/app/analytics/schemas.py` — EXTENDED (model, transform)

**Analog:** the file itself. Every new type subclasses `_AnalyticsModel` (`schemas.py:36-50`) —
which is where `hide_input_in_errors=True`, `extra="forbid"` and `frozen=True` come from, and
those are ASVS V8 controls for **body-weight data**, the most sensitive numbers in the project.

**Base class — do not redeclare, just subclass** (`schemas.py:36-50`):
```python
class _AnalyticsModel(BaseModel):
    """Shared config for every analytics return type.

    ``hide_input_in_errors`` for the same reason ``hevy/schemas.py`` sets it: a ValidationError
    would otherwise render ``input_value=...`` -- weekly tonnage, workout counts, body-composition
    adjacent numbers -- into a message that could reach a log line (FOUND-05).
    ...
    """

    model_config = ConfigDict(hide_input_in_errors=True, extra="forbid", frozen=True)
```

**Sibling-coverage-type pattern** — `CoverageMetadata` (`schemas.py:70-80`) is the type
`MeasurementCoverage` sits *beside*, never subclasses:
```python
class CoverageMetadata(_AnalyticsModel):
    """DQ-02. Exactly D-06's three fields -- do not add a fourth.

    ``earliest_data_at`` is what lets Claude tell "you did not train in this window" apart from
    "your synced history does not reach back that far". Echoing the requested date range back
    here was explicitly considered and NOT selected; do not add it.
    """

    sessions_in_window: int
    insufficient_data: bool
    earliest_data_at: dt.datetime | None
```
→ `MeasurementCoverage` mirrors the three-field philosophy at **day grain**
(`window_days`, `measured_days_in_window`, `insufficient_data`, `earliest_measurement_at: dt.date | None`)
and carries the "why a sibling and not a subclass" paragraph from RESEARCH Pattern 8.
Note `earliest_measurement_at` is a `dt.date`, not `dt.datetime` — `measured_on` is a calendar
date and `body.py`'s module docstring is explicit that inventing a time of day would be wrong.

**Additive per-row flag pattern** — `MuscleGroupVolume` (`schemas.py:102-119`) is the precedent
for BODY-01's per-window `insufficient_data` sitting *alongside* a response-level one:
```python
    ``sessions`` and ``insufficient_data`` are U-03: they are per-muscle and additive to, not a
    replacement for, the response-level ``CoverageMetadata``. They exist so "plenty of chest data
    but only one rear-delt session" is expressible.
```
→ D-15's "a 30-day average can be reliable while the 7-day one isn't" is the *same relationship*.
Reuse the wording so a reviewer recognises the pattern.

**Ordering-contract-in-the-docstring pattern** (`schemas.py:157-163`):
```python
class TrainingFrequencyResult(_AnalyticsModel):
    """VOL-03 over the RAW requested range (D-03) -- deliberately not week-snapped.

    ``muscle_groups`` is sorted by ``muscle_group.value``; ``exercises`` by
    ``exercise_template_external_id``. Never dict-iteration order: a flaky ordering is a flaky
    test, and Phase 6 will diff these between runs.
    """
```
→ Every Phase-5 list field states its sort key in the docstring: `points` ascending by
`local_day`; PR-per-weight rows descending by `weight_kg`; comparison rows by
`exercise_template_external_id`; exercise trends by `exercise_template_external_id`.

**Where the enums go.** `TrendVerdict`, `PlateauConfidence`, `RecompositionStatus` are **return
contract** and belong in `schemas.py` next to the models that carry them (the module docstring
at `:1-5` says this file is "the contract Phase 6 codes against"). `NoEstimateReason` belongs in
`estimates.py` next to the gates that produce it, and is *imported into* `schemas.py` — the same
direction as `schemas.py:33` already importing `CanonicalMuscleGroup` from `app.normalization`.

**Target shapes:** RESEARCH.md "Recommended new schema types" (Pattern list at lines 1136-1214)
gives all of them.

---

### `backend/app/analytics/metadata.py` — EXTENDED (service, request-response)

**Analog:** the file itself. Three concrete additions, each with an in-file template.

**Resource tuple** (`metadata.py:55-59`):
```python
# Which bookkeeping rows actually feed a given answer (DQ-01). A per-muscle number is only as
# fresh as the STALER of the two: the muscle map comes from exercise_templates, so a stale
# template sync silently changes every per-muscle figure with no error anywhere in the stack.
FRESHNESS_RESOURCES_WORKOUTS: tuple[str, ...] = (RESOURCE_WORKOUTS,)
FRESHNESS_RESOURCES_MUSCLE: tuple[str, ...] = (RESOURCE_WORKOUTS, RESOURCE_EXERCISE_TEMPLATES)
```
→ `+ FRESHNESS_RESOURCES_BODY = (RESOURCE_BODY_MEASUREMENTS,)` for BODY-01, and a three-resource
tuple for BODY-02 (it reads *both* sides). `RESOURCE_BODY_MEASUREMENTS` already exists at
`app/db/repositories/sync_state.py:26` and is already in `SYNC_RESOURCES` — import it, do not
re-spell the string.

**Threshold constant + one-line predicate** (`metadata.py:49-64`):
```python
# D-05. One session cannot support a "per week" rate or a trend claim; two is the minimum for
# that arithmetic to mean anything. ONE constant, reused by volume, frequency, their per-muscle
# rows and every test -- a second copy is how the response-level flag and a row-level flag would
# eventually disagree about the same window.
INSUFFICIENT_DATA_SESSION_THRESHOLD = 2
...
def is_insufficient(sessions: int) -> bool:
    """DQ-02 / D-05: fewer than two sessions is not enough to believe a per-week figure."""
    return sessions < INSUFFICIENT_DATA_SESSION_THRESHOLD
```
→ This is **the named pattern CONTEXT.md D-07 explicitly points at** for
`PLATEAU_IMPROVEMENT_TOLERANCE`. D-15's floors follow the same "ONE constant, one comment saying
why this number and not another" rule, but as a `Mapping[int, int]` keyed by window length
(`MEASURED_DAY_FLOORS = {7: 3, 14: 5, 30: 10}`). The lookup-table-with-a-rationale-comment form
is already used at `app/normalization/exercise_map.py:50-53` — a module-level
`MappingProxyType`-wrapped mapping with a comment explaining the keys.

**Windowed-count builder** (`metadata.py:139-154`) — the exact shape `build_measurement_coverage`
copies:
```python
async def build_coverage(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    utc_start: dt.datetime,
    utc_end: dt.datetime,
) -> CoverageMetadata:
    """DQ-02 / D-06's three fields, exactly. Do not add a fourth."""
    sessions = await sessions_in_window(
        session, user_id=user_id, utc_start=utc_start, utc_end=utc_end
    )
    return CoverageMetadata(
        sessions_in_window=sessions,
        insufficient_data=is_insufficient(sessions),
        earliest_data_at=await earliest_workout_at(session, user_id=user_id),
    )
```
**Caveat for the planner:** `build_measurement_coverage` takes **local dates**, not UTC instants —
`measured_on` is a `Date` column. Do **not** thread `utc_start`/`utc_end` through it by analogy;
that is the one place the copy breaks.

**All-time floor query** (`metadata.py:99-109`) — the template for `earliest_measurement_at`,
including *why it is not window-scoped*:
```python
async def earliest_workout_at(session: AsyncSession, *, user_id: uuid.UUID) -> dt.datetime | None:
    """The user's oldest synced workout, across ALL time -- deliberately not window-scoped.

    D-06: this is what separates "you did not train in that window" from "your synced history
    does not reach back that far". Scoping it to the window would make the two identical and
    the field pointless.
    """
    result: dt.datetime | None = await session.scalar(
        select(func.min(Workout.start_time)).where(Workout.user_id == user_id)
    )
    return result
```

**The DQ-01 deny-list is non-negotiable** (`metadata.py:130-135`) — every new response inherits it:
```python
        # ONLY the last-synced timestamp is read off the row. MCP-06: the row's stored error
        # text, its run status and its two resume cursors are internal bookkeeping that must
        # never reach anything Claude can read...
        # Forbidden here: last_error, status, cursor_page, cursor_timestamp -- operator CLI only.
```

---

### `backend/app/analytics/progression.py` (service, batch aggregate → transform)

**Analog:** `backend/app/analytics/volume.py` — **the closest structural match in the phase**.
`volume.py` is *exactly* the shape PROG-01/02/03 need: a mutable accumulator dataclass, a pure
synchronous fold, and public async functions that do nothing but compose window → aggregate →
fold → envelope.

**Mutable accumulator pattern** (`volume.py:96-108`):
```python
@dataclass(slots=True)
class _WeekTotals:
    """Accumulator for one local week. Intermediate; the frozen Pydantic model is the result.

    Mutable for the same reason ``rollup.MuscleBucket`` is: it is folded into, never returned.
    ``schemas.py``'s models are the frozen ones a caller ever sees.
    """

    hard_sets: int = 0
    total_reps: int | None = None
    tonnage_sets: int = 0
    tonnage_kg: Decimal = field(default_factory=lambda: Decimal(0))
    session_ids: set[uuid.UUID] = field(default_factory=set)
```
→ `SessionBest` is the Phase-5 equivalent. RESEARCH Pattern 3 sketches it as `frozen=True`; either
is defensible, but **state the choice** — if it accumulates `sets`/`total_reps`/`volume_kg` across
the day's sets it must be mutable during the fold, exactly like `_WeekTotals`.

**Pure fold pattern** (`volume.py:111-134`) — copy the docstring's first paragraph and the
`None`-preserving accumulation:
```python
def _fold_week_totals(rows: Sequence[SetRollupRow]) -> dict[dt.date, _WeekTotals]:
    """Collapse (week, workout, template) rows into per-week totals.

    Pure and synchronous -- no session, no I/O -- so every rule here is unit-testable with no
    container, which is the whole reason the aggregate stops at this grain.

    ``total_reps`` stays ``None`` until some row actually reports reps, so a week whose only sets
    are duration holds returns ``None`` rather than a confident ``0``. ...
    """
    weeks: dict[dt.date, _WeekTotals] = {}
    for row in rows:
        totals = weeks.setdefault(row.week_start, _WeekTotals())
        totals.hard_sets += row.hard_sets
        if row.total_reps is not None:
            totals.total_reps = (totals.total_reps or 0) + row.total_reps
        ...
```
→ `_best_set_per_day()` (D-04) and `_weekly_slope()` / `classify_trend()` (PROG-02) and
`detect_plateau()` (PROG-03) are **all** pure and synchronous for this reason — that is what puts
the slope/dead-band/streak tests in the **0.94 s fast suite** instead of behind Docker.

**Public function composition pattern** (`volume.py:137-201`) — the skeleton for
`get_exercise_progression`:
```python
async def get_weekly_volume(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    start_day: dt.date,
    end_day: dt.date,
) -> WeeklyVolumeResult:
    """VOL-01: hard sets, reps and modality-aware tonnage per whole local week.
    ...
    Takes the session positionally and everything else keyword-only, matching
    ``app/db/repositories/``. ``user_id`` has no default: ASVS V4, the schema is
    multi-user-ready, so forgetting it must be a ``TypeError`` and never a cross-tenant read.
    The caller owns the transaction; nothing here writes.
    """
    window = await resolve_window(
        session, user_id=user_id, start_day=start_day, end_day=end_day, snap_to_weeks=True,
    )
    # ONE aggregate, folded once. Re-querying per figure defeats the reason the grain is this
    # fine...
    rows = await weekly_set_rows(session, user_id=user_id, window=window)
    folded = _fold_week_totals(rows)
    ...
    return WeeklyVolumeResult(
        weeks=weeks,
        coverage=await build_coverage(
            session, user_id=user_id, utc_start=window.utc_start, utc_end=window.utc_end
        ),
        freshness=await build_freshness(
            session, user_id=user_id, resources=FRESHNESS_RESOURCES_WORKOUTS
        ),
    )
```

**Two deliberate divergences from the analog the planner must call out in the plan:**

1. **`snap_to_weeks=False`.** PROG-01/02/03 are per-*day* series and per-*exercise* windows, not
   comparable week buckets. `volume.py` snaps (U-01); `frequency.py:120-122` does not, and its
   docstring `:114-119` explains when each applies. Progression follows **frequency**, not volume.
2. **No gap-free spine.** `volume.py:169-173` projects onto `local_week_spine` because a
   zero-training week is diagnostically interesting. `ExerciseProgressionResult.points` does the
   opposite — RESEARCH's own docstring: *"Days with no training are ABSENT, not zero rows… 'you did
   not do this exercise on Tuesday' is not a diagnostically interesting zero, it is every
   non-training day."* **Do not copy the spine.** Copy `local_week_spine`'s week enumeration only
   for PROG-02's x-axis week offsets, where a training gap must widen the gap (A9).

**Freshness selection** (`volume.py:195-200` vs `frequency.py:169-174`): progression needs
`FRESHNESS_RESOURCES_MUSCLE` (both `workouts` **and** `exercise_templates`) because `exercise_type`
— the D-03 gate — comes from the templates table. A stale template sync silently changes every
e1RM eligibility decision. This is exactly the reasoning at `volume.py:195-197`.

**Target code:** RESEARCH Patterns 3, 4, 5.

---

### `backend/app/analytics/records.py` (service, batch aggregate → transform)

**Analog:** `backend/app/analytics/frequency.py:106-175` (`get_training_frequency`) — the
composition shape for "one aggregate, several derived lists, sorted by a stated key, plus a
titles lookup".

**Titles lookup — reuse the concept, not the private function** (`frequency.py:82-103`):
`_template_titles` is private to `frequency.py`. `records.py`, `progression.py` and `comparison.py`
all need it. **Do not copy it three times.** Options for the planner, in order of preference:
(a) `qualifying_set_rows()` already carries `exercise_type` from the template join — extend the
same `outerjoin` to also select `ExerciseTemplate.title`, which costs nothing and removes the
second query entirely; (b) promote `_template_titles` to `rollup.py` as a shared helper. Either
way there must be **exactly one** implementation — this is the same "two copies eventually
disagree" rule `rollup.py`'s docstring and `resolver.py`'s delegation pattern already encode.

**Sorted-output pattern** (`frequency.py:142-162`):
```python
    # Sorted by a stated key, never dict-iteration order -- Phase 6 will diff these between
    # runs, and a flaky ordering is a flaky test.
    muscle_groups = [
        MuscleGroupFrequency(...)
        for group in sorted(muscle_sessions, key=lambda muscle_group: muscle_group.value)
    ]
    exercises = [
        ExerciseFrequency(
            exercise_template_external_id=external_id,
            title=titles.get(external_id),
            ...
        )
        for external_id in sorted(exercise_sessions)
    ]
```
→ PR-per-weight rows sort **descending by `weight_kg`** (RESEARCH Pattern 6); the exercise list
sorts ascending by `exercise_template_external_id`. Spell the key out; `titles.get(...)` (never
`titles[...]`) preserves the `None` title for an unsynced template.

**The single-sort-key tie-break (D-09)** has no repo analog — it is new. RESEARCH Pattern 6:
```python
# Every PR is `max(value)` then `min(date) where value == max`. Expressed as a single sort key
# so the tie-break cannot be forgotten at one of the five call sites:
#     key = (value, -date.toordinal())   ->  max() gives highest value, earliest date
```
The *structural-not-reviewed* justification for that shape is the same argument
`rollup.MuscleBucket`'s docstring makes at `:295-298` ("The numbers still look plausible, which is
why this has to be structural rather than reviewed") — reuse the wording.

---

### `backend/app/analytics/comparison.py` (service, two windows + reuse)

**Analog:** `backend/app/analytics/frequency.py:106-175`. CMP-01 is literally "call
`get_training_frequency`'s machinery twice and diff", and `sessions_per_week()` was made public
*for this file*.

**Unsnapped window — the decision and its rationale** (`frequency.py:114-122`):
```python
    """VOL-03: sessions per week overall, per muscle group and per exercise (D-03).

    The window is resolved WITHOUT week snapping: the raw requested range IS the window, and the
    rate divides by its true length. Weekly volume widens its range outward instead (U-01)
    because its buckets have to be comparable to one another; a rate does not.
    """
    window = await resolve_window(
        session, user_id=user_id, start_day=start_day, end_day=end_day, snap_to_weeks=False
    )
```
→ Both CMP-01 periods resolve with `snap_to_weeks=False`. RESEARCH: *"a 4-week period against a
23-day period must both be expressed per week, not both widened to whole weeks."*

**Reuse, never re-derive** (`frequency.py:71-74`, quoted in the analog above): `sessions_per_week`
is *already documented as CMP-01's* per-week normalizer. Importing it is the pattern; writing
`count / (days / 7)` inline is the anti-pattern.

**Two independent envelopes.** `frequency.py` builds one `coverage`; CMP-01 builds **two**, one per
period (RESEARCH Pattern 7: *"A comparison where period A has 1 session is not a comparison, and a
single response-level coverage block cannot express that"*). The per-row/per-window additive-flag
precedent is `MuscleGroupVolume`'s U-03 note (`schemas.py:108-111`).

**`None`-preserving arithmetic** (`volume.py:126-132`, `volume.py:184-186`):
```python
        if row.total_reps is not None:
            totals.total_reps = (totals.total_reps or 0) + row.total_reps
...
                # None, never 0: "we could not compute tonnage for this week" is a different
                # fact from "tonnage was zero", and VOL-01's "where the modality supports it"
                # is exactly this distinction.
                tonnage_kg=totals.tonnage_kg if totals.tonnage_sets else None,
```
→ CMP-01's `delta_percent` is `None` when the baseline is zero. Same rule, same reasoning, and the
comment should say so.

**Structural guard, no analog:** the counts-and-sums-only rule (Pitfall 8) needs a `normalized: bool`
field or two distinct row types. The nearest repo precedent for "make the wrong thing
unrepresentable rather than reviewed" is `rollup.MuscleBucket.session_ids` being a `set`
(`rollup.py:287-304`).

---

### `backend/app/analytics/bodyweight.py` (service, row fetch + pure fold) — **PARTIAL ANALOG**

**No module under `backend/app/` has ever read `body_measurements` for analysis.** Verified:
`BodyMeasurement` appears only under `app/db/models/` (`body.py`, `__init__.py`) and
`app/integrations/hevy/` (`body.py`, `sync.py`, `client.py`, `schemas.py` — the write path, which
`app/analytics/` is statically forbidden from importing). This is the one file the planner should treat as new ground and lean on
RESEARCH Pattern 8 for.

**What still transfers, exactly:**

**Windowed tenant-scoped read** (`metadata.py:67-96`):
```python
async def sessions_in_window(
    session: AsyncSession, *, user_id: uuid.UUID, utc_start: dt.datetime, utc_end: dt.datetime,
) -> int:
    """...
    `user_id` is keyword-only with no default: ASVS V4 -- the schema is multi-user-ready, so an
    unscoped count is a cross-tenant disclosure a single-user suite cannot see.
    """
    count = await session.scalar(
        select(func.count()).select_from(Workout).where(
            Workout.user_id == user_id,
            Workout.start_time >= utc_start,
            Workout.start_time < utc_end,
        )
    )
```
→ `BodyMeasurement.user_id == user_id` leads the `WHERE`; `measured_on` is compared as a **`Date`**
against two `dt.date` bounds (inclusive/inclusive or half-open — **state which**, and test both
edges). No `func.timezone` and no `cast` here: `measured_on` is already a calendar date, so
`rollup.py`'s timezone machinery does **not** apply to the *rows*. It applies only to picking the
anchor day.

**The anchor day** — `app/core/time.py:21-28` and `:62-64`:
```python
def utc_now() -> dt.datetime:
    """The only sanctioned source of "now". Always aware, always UTC. ..."""
    return dt.datetime.now(dt.UTC)

def local_day(ts: dt.datetime, tz: str) -> dt.date:
    """The user's local calendar day that this instant falls on. FOUND-03."""
    return to_local(ts, tz).date()
```
→ `anchor = local_day(utc_now(), window.tz)`. **Never `date.today()`** — Ruff `DTZ` bans it
repo-wide and it returns the server's calendar day (Pitfall 12). The `tz` comes from
`resolve_window()`'s `users.timezone` read (`rollup.py:141-151`), never a constant — that function's
docstring is the canonical statement of why.

**One fetch, folded N ways** — the rule from `volume.py:162-164`:
```python
    # ONE aggregate, folded once. Re-querying per figure defeats the reason the grain is this
    # fine, and re-deriving a window total by summing these per-week session counts would
    # double-count every workout -- call the whole-window fold on the same rows instead.
```
→ One 35-day fetch `[anchor-34, anchor]`, folded five ways (7d / 14d / 30d / prior-7d / anchor-7d).
≤35 rows. Do not issue five queries.

**Quantum** — reuse `frequency._RATE_QUANTUM`'s *pattern*, not its constant: bodyweight averages
mirror `body_measurements.weight_kg`'s `Numeric(6,2)`, so `Decimal("0.01")`; the percent-per-week
rate also `Decimal("0.01")`. Divisions are the only inexact `Decimal` operation (Pitfall 7) —
quantize at the boundary, once per quantity.

**D-14 dedupe in Python, not `DISTINCT ON`** — RESEARCH Pattern 8's snippet. The justification
form is the repo's standard one: it is a *business rule*, and business rules live in pure Python so
they are testable without a container (`rollup.py:30-33` states this as the file-layout principle).

---

### `backend/app/analytics/recomposition.py` (service, composition only)

**Analog:** `backend/app/analytics/volume.py:204-286` (`get_muscle_group_volume`) — the repo's only
"compose several already-built pieces and assemble one result" function.

**Reuse-don't-reimplement comment** (`volume.py:237-239`):
```python
    # Reused, never re-implemented: the per-week `sessions` count is the same distinct-workout
    # figure VOL-01 reports, and a second copy is how the two would eventually disagree.
    week_totals = _fold_week_totals(rows)
```
→ `recomposition.py` calls `bodyweight.get_body_weight_trend()` and
`progression.get_exercise_trends()` (RESEARCH Open Question 5 recommends making the latter public
for exactly this reason: *"One computation, two consumers, no duplicate definition of
'improving'"*). It writes **no SQL of its own** except the freshness envelope.

**Three-resource freshness** — extend the `volume.py:281-285` comment form:
```python
        # BOTH resources, unlike VOL-01: the muscle map comes from exercise_templates, so a
        # stale template sync silently changes every number in this response with no error.
```
→ BODY-02 needs **all three** (`workouts`, `exercise_templates`, `body_measurements`) because it
reads both sides.

**The label matrix has no code analog** — it is new. The nearest *structural* precedent for a
module-level lookup table with a rationale comment is `app/normalization/exercise_map.py:50-53`:
```python
# NORM-01. Keys are normalize_title() output.
# Values are the deltoid head(s) Hevy's flat 'shoulders' expands to for that movement; the
# role (direct/indirect) is inherited from whether Hevy listed it as primary or secondary.
DELTOID_SPLIT_BY_TITLE: Mapping[str, tuple[CanonicalMuscleGroup, ...]] = MappingProxyType(
```
→ If the 5×3 matrix is expressed as data rather than nested `if`s, use `MappingProxyType` and a
comment stating what the keys and values mean. Whichever form, the three constants
(`WEIGHT_GAIN_TOO_FAST_PERCENT_PER_WEEK`, `WEIGHT_LOSS_TOO_FAST_PERCENT_PER_WEEK`,
`WEIGHT_STABLE_BAND_PERCENT_PER_WEEK`) follow `INSUFFICIENT_DATA_SESSION_THRESHOLD`'s
"ONE constant + why this number and not another" comment form (`metadata.py:49-53`).

**The `disclaimer` field** is a required model field, not a docstring (RESEARCH Pattern 9 step 4).
No analog — flag it in the plan's acceptance criteria so a reviewer does not delete it as
"backend-generated prose".

---

### `backend/tests/conftest.py` — EXTENDED (`GoldenBuilder.body_measurement`)

**Analog:** `GoldenBuilder.template()` at `conftest.py:337-385`, in the same class.

**Method shape to copy** (`conftest.py:337-368, 384-385`):
```python
    async def template(
        self,
        *,
        external_id: str,
        exercise_type: str = "weight_reps",
        title: str | None = None,
        muscles: Sequence[tuple[CanonicalMuscleGroup, MuscleRole]] = (),
        user_id: uuid.UUID = DEFAULT_USER_ID,
    ) -> str:
        """One ``exercise_templates`` row plus its canonical ``exercise_muscles`` base set.
        ...
        """
        await self._session.execute(
            insert(ExerciseTemplate).values(
                id=uuid.uuid4(),
                user_id=user_id,
                ...
            )
        )
        ...
        await self._session.flush()
        return external_id
```
Copy exactly: keyword-only params, `user_id: uuid.UUID = DEFAULT_USER_ID`, explicit Core `insert`,
`await self._session.flush()` and **never `commit`** — the class docstring at `:305-315` explains
why (the analytics function under test shares the same session and sees flushed-not-committed
rows), and `golden_workout`'s `finally: await session.rollback()` (`:492-505`) is what keeps the
session-scoped container clean.

**`Decimal`-not-`float` in the fixture** (`conftest.py:283-287`):
```python
    ``weight_kg`` is a ``Decimal``, never a ``float``: these sum into tonnage,
    and binary floating point would make two arithmetically identical weekly
    totals compare unequal.
```
→ Same for `body_measurement(weight_kg: Decimal | None)`.

**New for Phase 5:** `source: str = "hevy"` must be a *parameter*, because D-14's tie-break test
writes both a `'hevy'` and a `'manual'` row for the same `measured_on` — which the natural key
`(user_id, source, measured_on)` permits and which is the entire reason D-14 exists.

**Fixture-id collision rule** (`conftest.py:63-73`): the container is session-scoped and shared.
Phase 5's test modules each need their own id prefix (`PROG-*`, `PR-*`, `CMP-*`, `BW-*`,
`RECOMP-*`), distinct from `VOL-*` / `FREQ-*` / `ROLLUP-*` / `RESOLVER-*` / `hevy-*`. Body-measurement
rows have no external id, so their isolation comes from `ANALYTICS_SECOND_USER_ID` or from the
rollback alone — **state which in the plan.**

---

### `backend/tests/test_analytics_estimates.py` (test, unit — **fast suite, no marker**)

**Analog:** `test_analytics_frequency.py:100-110`, and the reason it is markerless is stated in
that file's docstring at `:16-20`:
```python
The `sessions_per_week` arithmetic tests carry NO integration marker on purpose. The rate
formula is the piece Phase 5's CMP-01 will reuse, and it must stay verifiable when Docker is
not running -- the same argument `test_normalization_mapping.py` makes for its `apply_weights`
tests.
```

**Exact-value assertion pattern** (`test_analytics_frequency.py:100-110`):
```python
def test_sessions_per_week_arithmetic_is_exact() -> None:
    """10 days is exactly 10/7 weeks, and the rate is quantized before anyone sees it.

    `Decimal` and never binary floating point: two arithmetically identical rates have to
    compare equal, and `0.68` is what a coach reads where the raw quotient is
    `0.6774193548387097`.
    """
    assert sessions_per_week(3, 10) == Decimal("2.10")
    assert sessions_per_week(2, 7) == Decimal("2.00")
    ...
```
→ Epley: `100.000 kg × {1, 7, 8, 12}` → `{103.333, 123.333, 126.667, 140.000}` (verified in the
project venv). **Never `pytest.approx`** — an approx in `app/analytics/` test code is the warning
sign for Pitfall 6 (a `float` leaked in). The same applies to `_weekly_slope`'s exact-Decimal tests.

---

### `test_analytics_progression.py` / `_records.py` / `_comparison.py` / `_bodyweight.py` / `_recomposition.py` (test, integration)

**Analog:** `backend/tests/test_analytics_frequency.py` — whole file, structurally.

**Module docstring names the defect under test** (`test_analytics_frequency.py:1-20`) — copy the
form: state the counter-intuitive rule, then name the *specific measured wrong number* the test
would catch, then name which test is load-bearing and which is its partner ("without it, 'always
return 1' passes"). Phase-5 pairs that need the same treatment: D-06's session floor **and** its
calendar floor; D-07's tolerance (+1.5% doesn't break, +2.5% does); D-15's per-window floors on
both sides of each boundary.

**Module-level fixture constants with a "why this date" comment**
(`test_analytics_frequency.py:52-72`):
```python
# A 7-day window (Mon 2026-08-24 .. Sun 2026-08-30) for the dedup tests, and a deliberately
# NON-multiple-of-7 10-day window for the rate test -- D-03 says the range is arbitrary, and a
# 7-day-only test would pass against an implementation that divided by whole weeks.
_WEEK_START = dt.date(2026, 8, 24)
...
# Jakarta is UTC+7, so 02:00Z is 09:00 local on the same day -- comfortably inside the local day
# each constant is named for, and never at risk of sliding into its neighbour.
_MONDAY = dt.datetime(2026, 8, 24, 2, 0, tzinfo=dt.UTC)
```

**Integration test body** (`test_analytics_frequency.py:123-155`):
```python
@pytest.mark.integration
async def test_per_muscle_sessions_dedup_within_one_workout(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """THE load-bearing test: three hamstring exercises in one workout is ONE session. ..."""
    await _seed_hamstring_templates(golden_workout)
    await golden_workout.workout(start_time=_MONDAY, exercises=[...])

    result = await get_training_frequency(
        session, user_id=DEFAULT_USER_ID, start_day=_WEEK_START, end_day=_WEEK_END
    )

    assert hamstrings[0].sessions == 1, (
        "per-muscle sessions were SUMMED instead of de-duplicated. One workout containing three "
        "hard sets ... -- summing inflated hamstrings 2 -> 8 (4.0x) ... on real data"
    )
    # Guard against a vacuous pass: three exercises really were written.
    assert len(result.exercises) == 3
```
Copy all four properties: `@pytest.mark.integration`; both `session` and `golden_workout`
(the latter owns the rollback even when a test writes no workouts); the **explanatory assertion
message** on the load-bearing assert; and the **anti-vacuous-pass guard** at the end.

**Cross-tenant test** — `ANALYTICS_SECOND_USER_ID` (`conftest.py:63-67`) plus
`GoldenBuilder.user()` (`:321-335`). Phase 5 needs one for progression, one for records and one for
body weight (ASVS V4). The reason a single-user suite cannot catch it is stated at
`conftest.py:322-326`.

**NEW for Phase 5, no repo analog: `time-machine`.** `time-machine==3.4.0` is installed
(`pyproject.toml:33`) but **zero tests use it today** (verified by grep). BODY-01, BODY-02 and
PROG-03's `plateau_duration_days` are all anchored on "now". RESEARCH gives the form:
```python
import time_machine

@time_machine.travel("2026-08-30T02:00:00+00:00", tick=False)
async def test_rolling_averages_gate_independently(...) -> None:
    # 02:00 UTC is 09:00 in Asia/Jakarta -- deliberately an instant where the UTC day and the
    # local day AGREE, so the test isolates the coverage rule. A second test should pick an
    # instant where they DISAGREE (e.g. 2026-08-29T18:00:00+00:00 -> local 2026-08-30) to prove
    # the anchor day is local_day(utc_now(), tz) and not the UTC date.
```
Note `tick=False`. The UTC-vs-local-day-agree/disagree pairing is the same discipline
`test_analytics_frequency.py:70-72` applies to its `02:00Z` constants.

---

### `backend/tests/test_analytics_isolation.py` — EXTENDED

**Analog:** the file itself. It already auto-covers every new Phase-5 module via `rglob`
(`:54-60`) with **no edit required** — the two additions are new *guards*, not new coverage.

**Guard shape to copy** (`:39-51` and `:126-140`):
```python
# S608 belt-and-braces: no hand-built SQL string may reach the driver from this package. ...
_RAW_SQL_TEXT = re.compile(r"(?<![\w.])(?:(?:sa|sqlalchemy)\.)?text\s*\(")
...
def test_analytics_uses_no_raw_sql_text() -> None:
    """..."""
    for path in _analytics_modules():
        source = path.read_text(encoding="utf-8")
        assert not _RAW_SQL_TEXT.search(source), (
            f"T-04-01 violated: {path.relative_to(REPO_ROOT)} builds raw SQL with text(). ..."
        )
```

**The convention that makes this work** (`:17-21`) — critical for the new guards:
```python
Every check is an ANCHORED REGEX or a CamelCase class identifier, never a bare substring.
`app/analytics/__init__.py` states these very rules in prose, so a substring check would fail on
the sentence documenting the boundary -- the trap already recorded at
`test_hevy_isolation.py:88-93`.
```
→ A naive `no_float` guard matching the word `float` will fire on `estimates.py`'s own docstring
("never binary floating point", "Decimal, never float"). Anchor it: match `\bfloat\s*\(` and
`:\s*float\b` / `->\s*float\b`, not the bare word. Likewise the "no Epley in SQL" guard must not
match the docstring paragraph that *warns* about it — key it on the SQL construct
(`func.` near `/ 30`, or a `reps` column inside an arithmetic expression), or invert it and assert
`estimates.estimate_1rm` is the only site computing `/ 30`.

**Guard-on-the-guards** (`:63-71`) — `test_the_walk_actually_finds_files` already exists; consider
bumping its `>= 2` floor now that the package will hold 11 modules.

---

### `backend/tests/test_analytics_metadata.py` — EXTENDED

**Analog:** the file itself. Its docstring (`:7-14`) states the rule the new tests must follow:
```python
The structural test that pins `FreshnessMetadata`'s field set deliberately carries NO
integration marker. "No credential, error text or internal cursor reaches Claude" is a security
guarantee, and a security guarantee must never become skippable because Docker is not running
```
→ The DQ-01/MCP-06 no-leak assertion must be extended to **every new Phase-5 return model** and
must stay in the **fast suite**. The `_LEAK_SENTINEL` machinery (`:63+`) and the `_SentinelFailure`
opt-in exception are already built — extend, do not rebuild.

Also (`:15-18`): *"Every container-backed test takes `golden_workout` even when it only writes
`sync_state` rows, because that fixture owns the `finally: await session.rollback()`."*

---

## Shared Patterns

### 1. Module docstring convention — every new file
**Source:** `rollup.py:1-34`, `volume.py:1-60`, `metadata.py:1-31`, `frequency.py:1-26`.
**Apply to:** all 6 new app modules and all 6 new test modules.

The shape, without exception: open with the requirement ids the module satisfies, then enumerate
the **counter-intuitive rules** in bold, each with (a) what the obvious alternative is, (b) the
*specific measured wrong number* it produces, and (c) why no reviewer would catch it. E.g.
`rollup.py:8-11`: *"Aggregating `workout_id` away inflated hamstring frequency from 2 to 8 (4.0x)
on one real training week."* Phase 5 has its own verified figures to use — RESEARCH's Live Data
Ground Truth section supplies them (4,802/7,719 e1RM-eligible; 376/2,239 sessions skipped by D-07a;
44/97 templates flagged at 402 days unbounded; `SELECT 10 * (1 + 8/30)` returns `10`).
**Do not ship a Phase-5 module whose docstring omits Pitfall 9** (Epley's 20% multiplier swing
across a 5→12 rep spread) — RESEARCH explicitly asks for it "in the shipped docstrings" so nobody
later "fixes" rep-scheme noise.

### 2. Function signature convention — non-negotiable
**Source:** verified identical across `metadata.py`, `rollup.py`, `volume.py`, `frequency.py`,
`resolver.py`, `sync_state.py`, `workouts.py`, `templates.py`, `body.py`.
**Apply to:** every new public async function.
```python
async def get_exercise_progression(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    exercise_template_external_id: str,
    start_day: dt.date,
    end_day: dt.date,
) -> ExerciseProgressionResult: ...
```
Session **positional**; everything else **keyword-only**; `user_id` has **no default** (ASVS V4 —
omission must be a `TypeError`, never a cross-tenant read a single-user suite cannot see); the
caller owns the transaction; nothing commits. Stated at `volume.py:150-153` and `metadata.py:84-85`.

### 3. Decimal, never float — and never `float` in a return type
**Source:** `schemas.py:12-14`, `rollup.py:27-28`, `volume.py:130-132`, `frequency.py:71-74`.
**Apply to:** every e1RM, slope, percent, average and delta.
```python
            # Decimal, never binary floating point: two arithmetically identical weekly totals
            # must compare equal, or "did my tonnage change this week?" becomes a coin flip.
```
Bans `regr_slope` / `corr` / `regr_r2` in SQL (all return `double precision`) and bans
`statistics.linear_regression` (returns floats). `avg()` and `stddev_samp()` over `numeric` are
safe. Divisions are the only inexact `Decimal` operation — one quantum per quantity, at the
boundary. Warning sign: a `pytest.approx` in a Phase-5 test.

### 4. Deterministic ordering on every returned collection
**Source:** `rollup.py:247-249`, `frequency.py:142-143`, `schemas.py:160-163`, `volume.py:246-251`.
**Apply to:** progression points, PR lists, comparison rows, exercise trends, plateau lists.
```python
        # Deterministic ordering is a repo-wide rule (`resolver.py`, `hevy/sync.py`);
        # dict-iteration order is a flaky test waiting to happen.
```
For Phase 5 this is stronger than a test-stability concern: **a plateau streak read out of order is
a wrong answer, not a flaky one.** `qualifying_set_rows()` orders
`(template_id, local_day, workout_id, set_index)` for exactly that reason.

### 5. Tenant predicate leads, and the template join carries its own
**Source:** `rollup.py:234-236`, `metadata.py:84-85`, `frequency.py:91-93`.
**Apply to:** `qualifying_set_rows()`, the body-measurement fetch, any title lookup.
Hevy's built-in template ids are **global**. An unqualified `exercise_templates` join attaches
another user's `exercise_type` to this user's set — which in Phase 5 changes the D-03 e1RM gate,
not just a display title. This is a *correctness* bug as well as a disclosure one.

### 6. Reuse the existing machinery — the "Don't Hand-Roll" list
**Apply to:** every plan action.

| Need | Call this | Never |
|---|---|---|
| Window validation, tz read, span clamp | `rollup.resolve_window()` / `build_window()` | a new guard |
| Warm-up exclusion | `rollup._hard_set_predicates()` / `WARMUP_SET_TYPE` | `set_type == 'normal'` |
| Local day / week / range bounds | `app.core.time.*` | `datetime` + `timedelta` inline |
| Per-week rate | `frequency.sessions_per_week()` | `count / (days / 7)` |
| Freshness / coverage | `metadata.build_freshness()` / `build_coverage()` | a per-module builder |
| Muscle resolution | `rollup.resolve_row_muscles()` → `effective_muscles_bulk()` | a join (statically banned) |
| Body-measurement fixtures | extend `GoldenBuilder` | a second builder class |
| Least-squares slope | ~8 lines of `Decimal` | numpy / `statistics` / `regr_slope` |

### 7. Lint / type gates every new file must pass
**Source:** `pyproject.toml`.
- Ruff `line-length = 100`, `target-version = "py313"`, `select = ["E","F","I","UP","B","ASYNC","S","DTZ"]`.
  `S608` blocks f-string SQL (tz stays a bound param via `func.timezone`); `DTZ` blocks
  `date.today()` and naive `datetime.now()`.
- `known-first-party = ["app"]` — import blocks are isort-ordered stdlib / third-party / `app` / `tests`.
- mypy `disallow_untyped_defs = true` — **every** function including test helpers is annotated;
  `warn_unused_ignores = true` means a stale `# type: ignore` fails the build.
- `per-file-ignores` gives `backend/tests/*` `S101/S105/S106` only; app code gets no such relief.

### 8. Test suite mechanics
**Source:** `pyproject.toml` `[tool.pytest.ini_options]`, `conftest.py:1-23`.
- `asyncio_mode = "auto"` — no `@pytest.mark.asyncio` decorator.
- `@pytest.mark.integration` on **anything touching the container**; markerless tests must run with
  Docker stopped. Baseline to protect: **206 passed, 163 deselected in 0.94 s**.
- Fast suite: `.venv/bin/python -m pytest -q -m "not integration"`. Full: `.venv/bin/python -m pytest -q`.
- Schema comes from `alembic upgrade head` only (FOUND-02). **No migration in this phase.**

### 9. Dependencies — nothing to add
`sqlalchemy 2.0.52`, `asyncpg 0.31.0`, `pydantic 2.13.4`, `pytest 9.1.1`, `pytest-asyncio 1.4.0`,
`testcontainers 4.15.0`, `time-machine 3.4.0` are all installed. A new dependency in any Phase-5
plan is a design-drift signal. pandas/numpy are explicitly banned by CLAUDE.md.

---

## No Analog Found

| File / concern | Role | Data Flow | Reason | What the planner should use instead |
|---|---|---|---|---|
| `backend/app/analytics/bodyweight.py` — the `body_measurements` read | service | batch → transform | **No application module has ever queried this table for analysis.** `BodyMeasurement` appears only under `app/db/models/` and the Hevy write path in `app/integrations/hevy/` (which analytics is statically forbidden from importing). Also the first `Date`-column window in the codebase — `rollup.py`'s whole timezone apparatus does not apply to the rows | RESEARCH Pattern 8 (complete). Structural shell from `metadata.py:67-109`; window/tz only for the anchor day |
| BODY-02's 5×3 label matrix | business rule | transform | No classification matrix exists anywhere in the repo | RESEARCH Pattern 9 steps 1-4. Table form modelled on `exercise_map.py:50-53`'s `MappingProxyType` |
| `time-machine` clock freezing in tests | test | — | Installed but used by **zero** tests today | RESEARCH's "Freezing the clock for a BODY-01 test" snippet, incl. `tick=False` and the agree/disagree UTC-vs-local pairing |
| The PR single-sort-key tie-break (D-09) | business rule | transform | New | RESEARCH Pattern 6's `key = (value, -date.toordinal())` |
| PROG-03's maximum lookback | **open decision** | — | **A1 — the single most important unlocked decision in the phase.** D-06 fixes minimum evidence, not maximum lookback. Unbounded → 44/97 exercises flagged at up to 402 days | Not a pattern question. See "Cross-Cutting Risks" #1 |

---

## Cross-Cutting Risks the Planner Should Route Into Plan Actions

1. **PROG-03's lookback is unresolved (RESEARCH A1, Open Question 1).** This is a *decision*, not a
   pattern. Recommendation on the table: `lookback_weeks` parameter, 12-week default, echoed back
   in `PlateauResult.lookback_start`/`lookback_end`. **Surface it to the user before writing the
   plan action** — it changes the public signature and every plateau test fixture.
2. **Three more unconfirmed constants** (A2 `WEIGHT_STABLE_BAND = 0.10`, A3
   `TREND_STABLE_BAND = 0.5`, A4 `RECOMP_PROGRESSION_NET_BAND = 0.25` + 3-exercise minimum). Each is
   derived rather than invented, each is one line to change, and each shifts verdicts. Bundle them
   into one confirmation alongside #1.
3. **`_template_titles` will be copied three times unless the plan prevents it.** Decide the single
   home in the plan (preferably: select `ExerciseTemplate.title` in `qualifying_set_rows()`'s
   existing outerjoin), not in the third file that needs it.
4. **The Epley-in-SQL trap is one keystroke away and silent.** `weight * (1 + reps/30)` returns the
   bare weight. Both the static guard (`test_analytics_isolation.py`) and the docstring warning in
   `estimates.py` are required — neither alone is enough.
5. **BODY-01/BODY-02 return `insufficient_data` on live data today** and will start returning a
   number around **2026-09-06**. Every BODY test must be synthetic + frozen-clock; a test written
   against live data would assert `null` today and start passing for the wrong reason next week.
   Make `insufficient_data` the first-class tested path.
6. **PROG-02 and PROG-03 will disagree on live data and both be right** (Overhead Press:
   `improving` +1.51%/week *and* plateaued 27 days). Both return types must carry their window
   explicitly. Route this into the schema plan action, not a docstring afterthought.
7. **RESEARCH expires 2026-09-29**, and its BODY-01 ground-truth section expires **2026-09-06**.
   If planning slips past that date, re-run the BODY-01 coverage query before writing fixtures.

---

## Metadata

**Analog search scope:** `backend/app/analytics/` (5 modules, 1,008 lines — the primary analog set),
`backend/app/core/time.py`, `backend/app/normalization/{muscles,exercise_map,resolver}.py`,
`backend/app/db/models/{body,workout,exercise}.py`,
`backend/app/db/repositories/sync_state.py`, `backend/tests/{conftest,test_analytics_*}.py`,
`pyproject.toml`.

**Files read in full:** `analytics/schemas.py`, `analytics/metadata.py`, `analytics/rollup.py`,
`analytics/volume.py`, `analytics/frequency.py`, `analytics/__init__.py`, `core/time.py`,
`tests/test_analytics_isolation.py`, `db/models/body.py` (head).
**Files read in part:** `tests/conftest.py`, `tests/test_analytics_frequency.py`,
`tests/test_analytics_metadata.py`, `normalization/exercise_map.py`, `normalization/muscles.py`,
`db/repositories/sync_state.py`.

**Greps run:** `BodyMeasurement` across `backend/app/` (6 files, all under `db/models/` or
`integrations/hevy/`, none in `analytics/`);
`time_machine` across `backend/` (0 hits); `StrEnum` across `normalization/`.

**Pattern extraction date:** 2026-08-30
