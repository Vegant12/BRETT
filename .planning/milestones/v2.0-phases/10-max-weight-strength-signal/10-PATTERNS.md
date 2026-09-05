# Phase 10: Max-Weight Strength Signal - Pattern Map

**Mapped:** 2026-09-03
**Files analyzed:** 4 (all modified, 0 new)
**Analogs found:** 4 / 4 — this phase is entirely self-referential (every file being modified is
also its own closest analog: the pattern to follow lives a few lines away in the same file). No
RESEARCH.md exists for this phase; CONTEXT.md's canonical_refs/code_context sections are the
source of truth.

## File Classification

| Modified File | Role | Data Flow | Closest Analog | Match Quality |
|----------------|------|-----------|-----------------|---------------|
| `backend/app/analytics/schemas.py` (`PlateauResult`) | model (Pydantic response schema) | transform | `ProgressionPoint.estimated_1rm_kg` / `no_estimate_reason` in the same file (lines 265-291) | exact — same file, stated precedent in CONTEXT.md D-Discretion |
| `backend/app/analytics/progression.py` (`get_plateaus`, `PlateauResult(...)` construction) | service (pure analytics transform) | transform / CRUD-read | `get_exercise_progression`'s `ProgressionPoint(...)` construction in the same file (lines 264-283) | exact — same module, same value/reason population idiom |
| `backend/app/mcp/tools/progression.py` (`_degraded_plateaus`) | controller (MCP tool degraded-fallback constructor) | request-response | `_degraded_progression` in the same file (lines 53-67) | exact — same file, same "explicit None/false for every new field" idiom |
| `backend/tests/test_analytics_progression.py` | test | transform (pure-function + integration test pairs) | `test_recent_performance_and_historical_best_are_both_reported` (lines 1367-1389) and the `get_plateaus` integration block (lines ~1450-1780) in the same file | exact — same file, same two-tier (pure `scan_plateau` unit test + `get_plateaus` DB integration test) structure |

No file in this phase needs an analog from elsewhere in the codebase — CONTEXT.md's canonical_refs
already name the exact functions to extend, and every one of them has a sibling field/branch in
the same file that shows the shape to copy.

## Pattern Assignments

### `backend/app/analytics/schemas.py` — add the new field to `PlateauResult`

**Analog:** `ProgressionPoint` in the same file (lines 265-291), specifically its
`estimated_1rm_kg` / `no_estimate_reason` pair — this is the exact precedent CONTEXT.md's
Claude's-Discretion section names.

**Value/reason mutually-exclusive pair pattern** (`schemas.py` lines 282-291):
```python
class ProgressionPoint(_AnalyticsModel):
    """...
    ``estimated_1rm_kg`` and ``no_estimate_reason`` are MUTUALLY EXCLUSIVE and exactly one is
    populated. A number with no reason is a trusted estimate; a reason with no number says why
    there is none -- PROG-01 requires the reason and forbids a bare null.
    ...
    """

    local_day: dt.date
    workout_id: uuid.UUID
    sets: int
    total_reps: int | None
    volume_kg: Decimal | None
    volume_sets: int
    best_weight_kg: Decimal | None
    best_reps: int | None
    estimated_1rm_kg: Decimal | None
    no_estimate_reason: NoEstimateReason | None
```

**Target class to extend** (`schemas.py` lines 344-372, `PlateauResult`):
```python
class PlateauResult(_AnalyticsModel):
    """PROG-03 / D-07b for one exercise. Blueprint 21's shape, plus the window and threshold.
    ...
    """

    exercise_template_external_id: str
    title: str | None
    plateaued: bool
    plateau_duration_days: int | None
    qualifying_sessions_in_streak: int
    recent_performance_kg: Decimal | None
    historical_best_kg: Decimal | None
    confidence: PlateauConfidence
    threshold_percent: Decimal
    min_sessions: int
    min_elapsed_days: int
    lookback_start: dt.date
    lookback_end: dt.date
    # NEW FIELD GOES HERE, e.g.:
    # last_max_weight_kg: Decimal | None
    # no_max_weight_reason: <reason-type> | None   # only if Claude's-discretion call is "yes,
    #                                                 add a reason companion"
```

**Note on reason type if a companion field is added:** `NoEstimateReason` (imported from
`app.analytics.estimates`, already imported into this file at line 36) is scoped to e1RM
estimation gates (`MODALITY`, `REP_RANGE`, `MISSING_OPERAND`) — it is NOT the right enum for "no
weight recorded on the last training day" (D-08's case is "weight_kg is None", i.e. a
bodyweight/duration-only exercise, which is a *different* condition than any `NoEstimateReason`
member describes). If a reason field is added, either reuse `NoEstimateReason.MISSING_OPERAND`
only if it is semantically accurate, or evaluate whether a bare `None` is sufficient (CONTEXT.md
explicitly leaves this open — "whether a `no_max_weight_reason`-style companion field is
warranted or a bare `None` is sufficient"). Do not invent a new enum without checking whether
`_NO_WEIGHT_RANK`'s existing "no real weight" semantics in `progression.py` already cover it with
no reason needed at all (weight_kg is simply `None` on `SessionBest`, no reason code accompanies
it there either — see next section).

**Model config to inherit unchanged** (`schemas.py` lines 40-54, `_AnalyticsModel`):
```python
class _AnalyticsModel(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True, extra="forbid", frozen=True)
```
`extra="forbid"` and `frozen=True` apply automatically since `PlateauResult` already subclasses
`_AnalyticsModel` — no changes needed there, just be aware `extra="forbid"` means every field
touching `PlateauResult(...)` construction sites (there is exactly one, in `progression.py`) must
be updated in the same commit or Pydantic will raise at construction, not silently drop the field.

---

### `backend/app/analytics/progression.py` — source and populate the new field in `get_plateaus`

**Analog:** the module's own `SessionBest.best_weight_kg` field (already computed, lines 113-125)
and the ascending-by-`local_day` sort already performed for `in_window` series construction
(lines 716-729).

**Existing field this phase reuses, no new fold** (`progression.py` lines 113-125, `SessionBest`):
```python
@dataclass(slots=True)
class SessionBest:
    local_day: dt.date
    template_external_id: str
    workout_id: uuid.UUID
    title: str | None = None
    exercise_type: str | None = None
    sets: int = 0
    total_reps: int | None = None
    volume_kg: Decimal = field(default_factory=lambda: Decimal(0))
    volume_sets: int = 0
    best_weight_kg: Decimal | None = None   # <-- THIS is the entire data source for the new field
    best_reps: int | None = None
    best_e1rm_kg: Decimal | None = None
    no_estimate_reason: NoEstimateReason | None = None
```

**Where the in-window series is already sorted ascending by local_day** (`progression.py` lines
716-729, inside `get_plateaus`):
```python
for (template_external_id, day), best in sorted(bests.items(), key=lambda item: item[0][1]):
    if day < lookback_start:
        if best.best_e1rm_kg is not None:
            current = seeds.get(template_external_id)
            if current is None or best.best_e1rm_kg > current:
                seeds[template_external_id] = best.best_e1rm_kg
        continue
    # Only templates trained INSIDE the lookback are reported. ...
    in_window.setdefault(template_external_id, []).append(best)
    titles[template_external_id] = best.title
```
D-07 says: the new field's value is `series[-1].best_weight_kg` — i.e. after this existing sort,
the LAST element of each template's `in_window[template_external_id]` list, taken right before or
inside the `for template_external_id, series in sorted(in_window.items())` loop below
(`progression.py` line 734). `series[-1]` is the most recent training day inside the lookback
window for that template — NOT necessarily the same day `scan_plateau`'s streak reports as
`streak_start` or uses in `recent_performance_kg`'s mean (D-07 is explicit these can differ).

**Construction site to extend** (`progression.py` lines 734-764, the `PlateauResult(...)` call
inside `get_plateaus`):
```python
for template_external_id, series in sorted(in_window.items()):
    scan = scan_plateau(
        series,
        historical_best=seeds.get(template_external_id),
        as_of=lookback_end,
    )
    exercises.append(
        PlateauResult(
            exercise_template_external_id=template_external_id,
            title=titles.get(template_external_id),
            plateaued=scan.plateaued,
            plateau_duration_days=(
                None
                if not scan.plateaued or scan.streak_start is None
                else (lookback_end - scan.streak_start).days
            ),
            qualifying_sessions_in_streak=scan.qualifying_sessions,
            recent_performance_kg=scan.recent_performance_kg,
            historical_best_kg=scan.historical_best_kg,
            confidence=scan.confidence,
            threshold_percent=threshold_percent,
            min_sessions=PLATEAU_MIN_QUALIFYING_SESSIONS,
            min_elapsed_days=PLATEAU_MIN_ELAPSED_DAYS,
            lookback_start=lookback_start,
            lookback_end=lookback_end,
            # NEW: last_max_weight_kg=series[-1].best_weight_kg,
            # (series is already ascending by local_day per the sort above; series is
            # non-empty here because `in_window` only gets keys with >=1 appended entry)
        )
    )
```
Note `series` here is guaranteed non-empty (only populated via `.setdefault(...).append(...)`
inside the loop above, never with an empty list), so `series[-1]` is always safe with no extra
`None`-guard needed for the *list access* itself — but `series[-1].best_weight_kg` itself CAN be
`None` per D-08 (a bodyweight/duration-only exercise's most recent day), which is exactly the
"reports as `None`" case D-08 requires, satisfied automatically by reading the field as-is.

**Do NOT touch:** `PLATEAU_IMPROVEMENT_TOLERANCE`, `PLATEAU_MIN_QUALIFYING_SESSIONS`,
`PLATEAU_MIN_ELAPSED_DAYS`, `DEFAULT_PLATEAU_LOOKBACK_WEEKS`, `scan_plateau`'s state machine, or
the module docstring (lines 7-10) — all confirmed in scope per canonical_refs.

---

### `backend/app/mcp/tools/progression.py` — update `_degraded_plateaus`

**Analog:** `_degraded_progression` in the same file (lines 53-67), which shows the repo-wide
idiom for a degraded/fallback constructor: every field gets an explicit, honest default (`None`,
`False`, `[]`, `0`) — never a value that could be mistaken for real analytics output.

**Sibling degraded-constructor pattern** (`progression.py` [mcp/tools] lines 53-67):
```python
def _degraded_progression() -> ExerciseProgressionResponse:
    """The payload Claude gets when the tool body raised (MCP-06, T-06-01).

    ``data_available=False`` is the whole point: it is NOT the same claim as "you have never
    trained that exercise", which an empty ``points`` list with ``data_available=True`` would make.
    """
    return ExerciseProgressionResponse(
        data_available=False,
        requested_name="",
        matched=False,
        candidates=[],
        progression=None,
        points_truncated=False,
        total_points=0,
    )
```

**Target function to update** (`mcp/tools/progression.py` lines 146-164):
```python
def _degraded_plateaus() -> PlateauResponse:
    """The payload Claude gets when the tool body raised (MCP-06, T-06-01).

    Every window field is ``None`` rather than a plausible default: ...
    """
    return PlateauResponse(
        data_available=False,
        plateaued_only=True,
        lookback_weeks=None,
        lookback_start=None,
        lookback_end=None,
        exercises=[],
        exercises_truncated=False,
        total_exercises=0,
        coverage=None,
        freshness=None,
    )
```
This function itself needs NO new field — it builds `PlateauResponse`, whose `exercises` field is
`list[PlateauResult]` and stays `[]` in the degraded case. **The place that actually needs an
explicit new value is inside `PlateauResult`'s construction in `progression.py`'s `get_plateaus`**
(covered above), not here. CONTEXT.md's Integration Points note ("`_degraded_plateaus`'s
hand-built fallback response is the one place that needs an explicit new value (`None`)") refers
to the fact that `PlateauResult` itself requires every field populated (Pydantic, no defaults on
the model per `_AnalyticsModel`'s pattern of fully-specified fields) — but `_degraded_plateaus`
never constructs a `PlateauResult` at all (its `exercises=[]`), so **no change is actually needed
in this function** unless the new field also needs to be threaded onto `PlateauResponse` itself
(unlikely — `PlateauResponse` is a per-report wrapper, the new field lives on the per-exercise
`PlateauResult`). Verify this during planning: if the new field ends up on `PlateauResponse`
rather than only `PlateauResult`, this function DOES need the explicit new keyword added, same
idiom as every other field here (an honest `None`/`False`/`0`/`[]`).

**PlateauResponse for reference** (`mcp/tools/schemas.py` lines 139-153):
```python
class PlateauResponse(_McpModel):
    data_available: bool
    plateaued_only: bool
    lookback_weeks: int | None
    lookback_start: dt.date | None
    lookback_end: dt.date | None
    exercises: list[PlateauResult]
    exercises_truncated: bool
    total_exercises: int
    coverage: CoverageMetadata | None
    freshness: FreshnessMetadata | None
```
`fitness_get_plateaus` (same file, lines 167-227) passes `report.exercises` straight through with
no field-by-field reconstruction (per CONTEXT.md's Integration Points note), so once
`PlateauResult` carries the new field and `get_plateaus` populates it, this tool function needs
**no code change of its own** beyond `_degraded_plateaus` (if that turns out to need one, see
above).

---

### `backend/tests/test_analytics_progression.py` — extend plateau tests

**Analog:** the existing two-tier test pattern already in this file for `scan_plateau` /
`get_plateaus` — a pure-function unit test plus a DB-integration test, both already covering
`PlateauResult`'s other fields.

**Pure unit-test pattern to extend or sibling** (`test_analytics_progression.py` lines 1367-1389,
`test_recent_performance_and_historical_best_are_both_reported`):
```python
def test_recent_performance_and_historical_best_are_both_reported() -> None:
    ...
    scan = scan_plateau(
        series,
        historical_best=...,
        as_of=...,
    )
    assert scan.recent_performance_kg == ...
    assert scan.historical_best_kg == ...
```
Note: `scan_plateau` itself is untouched by this phase (it returns a `PlateauScan`, not a
`PlateauResult`, and does not carry `best_weight_kg` at all — the new field is populated in
`get_plateaus` directly from `series[-1].best_weight_kg`, bypassing `scan_plateau` entirely). So
the correct test level for the new field's logic is either:
1. A new focused unit test around the `series[-1]` selection logic if it is factored into a
   small pure helper during implementation, or
2. A `get_plateaus` integration test (see below) asserting the new field on the returned
   `PlateauResult`, since the value is computed inline in `get_plateaus` per the pattern shown
   above.

**Integration test pattern to extend** (`test_analytics_progression.py`, `get_plateaus`
DB-integration block, e.g. around lines 1592-1625):
```python
async def test_...(session: AsyncSession) -> None:
    ...
    result = await get_plateaus(session, user_id=DEFAULT_USER_ID)
    ...
    assert result.exercises[...].last_max_weight_kg == Decimal("...")
```
Follow the file's existing fixture/seeding conventions (`DEFAULT_USER_ID`, `ANALYTICS_SECOND_USER_ID`
for tenant-isolation tests) and its no-frozen-clock pattern noted in the comment above the
`get_plateaus` block ("`get_plateaus` anchors its window on the user's local TODAY, so an
unfrozen test rots within...").

**Case to add per D-08:** a bodyweight/duration-only exercise's most recent in-window day (weight
`None`) must report the new field as `None`, not `Decimal("0")` — this is the direct test-level
enforcement of the `_NO_WEIGHT_RANK` honesty rule; add it as a sibling to
`test_null_estimate_session_neither_extends_nor_breaks` (lines 1290-1318) or as a new
`get_plateaus`-level integration test.

---

## Shared Patterns

### Value/reason mutually-exclusive field pairs
**Source:** `backend/app/analytics/schemas.py`, `ProgressionPoint.estimated_1rm_kg` /
`.no_estimate_reason` (lines 282-291); same convention seen in `PersonalRecordsResult`'s
per-record-type absence pattern and `BodyWeightTrendResult`'s window-gated `None`s.
**Apply to:** the new `PlateauResult` field, if Claude's-discretion during planning decides a
reason companion is warranted. Otherwise a bare `Decimal | None` following `best_weight_kg`'s own
existing `None`-means-"no real weight, not a zero" convention in `SessionBest` is sufficient and
requires no new enum.

### `_NO_WEIGHT_RANK` / honesty-about-missing-data convention
**Source:** `backend/app/analytics/progression.py` lines 91-94 and its use inside
`best_set_per_day` (lines 194-219).
**Apply to:** the new field's `None`-vs-`Decimal("0")` handling — `weight_kg is None` on the most
recent `SessionBest` must surface as `None` on the new `PlateauResult` field, never coerced to a
literal zero. No new sentinel needs inventing; the field simply forwards `series[-1].best_weight_kg`
as-is, which is already `None` in exactly the cases D-08 cares about.

### Degraded/fallback response construction
**Source:** `backend/app/mcp/tools/progression.py`, `_degraded_progression` (lines 53-67) and
`_degraded_plateaus` (lines 146-164).
**Apply to:** any change to `_degraded_plateaus` (only needed if the new field lands on
`PlateauResponse` itself, not just `PlateauResult` — see analysis above). Every field gets an
explicit, honest default; never omit a field to fall back on a Pydantic default (there are none —
`_AnalyticsModel`/`_McpModel` fields are all required).

### Deterministic sort before "most recent" selection
**Source:** `backend/app/analytics/progression.py` lines 716-719, the `sorted(bests.items(),
key=lambda item: item[0][1])` fold that produces each template's ascending `in_window` series.
**Apply to:** the new field's source — `series[-1]` is only correct because this sort already
guarantees ascending `local_day` order; do not add a second, independent "find the most recent
day" scan.

## No Analog Found

None — every file in scope has its pattern precedent in the same file (see Pattern Assignments
above). No cross-codebase search was needed beyond the files CONTEXT.md's canonical_refs already
named.

## Metadata

**Analog search scope:** `backend/app/analytics/`, `backend/app/mcp/tools/`, `backend/tests/`
(the four files CONTEXT.md's canonical_refs section names directly; no broader glob/grep search
was necessary since every needed pattern precedent lives in the same file being modified)
**Files scanned:** 5 (`progression.py`, `schemas.py` [analytics], `progression.py` [mcp/tools],
`schemas.py` [mcp/tools, for `PlateauResponse`], `recomposition.py` [confirmation-only, confirmed
untouched — its `progression_signal` input comes from `get_exercise_trends`, which remains
e1RM-slope-based and is not modified by this phase], `estimates.py` [confirmation-only, read for
the `NoEstimateReason` convention, not modified]), plus `test_analytics_progression.py` for the
test pattern
**Pattern extraction date:** 2026-09-03
