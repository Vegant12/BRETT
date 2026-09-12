# Phase 18: Monthly Report Physique Integration - Pattern Map

**Mapped:** 2026-09-12
**Files analyzed:** 6 (4 modified, 0 new production modules, 2 test files modified/extended)
**Analogs found:** 6 / 6 (all analogs are sibling sections/fields inside the SAME files being
modified — this phase is pure composition, no new architectural shape)

**No RESEARCH.md exists for this phase** (composition-only, no new dependencies). Every pattern
below is drawn directly from the codebase, per the phase brief's instruction to root the analog
search in Phase 17's freshly-landed physique analytics and the existing `recomposition` /
`plateau_highlights` / `narrative` precedents in the report layer.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog (same file, different section) | Match Quality |
|---|---|---|---|---|
| `backend/app/analytics/schemas.py` (add `PhysiqueSection`, extend `ReportResult`) | model (Pydantic result type) | CRUD (read/compose) | `RecompositionResult` embedding + `ReportResult`'s existing `recomposition`/`plateau_highlights` fields, same file | exact |
| `backend/app/analytics/reports.py` (`compose_report` — one conditional + 3 calls) | service (composition) | CRUD (read, join) | `compose_report`'s existing `recomposition`/`plateaus` calls, same function | exact |
| `backend/app/analytics/reports.py` (`_physique_lines` builder + `_NARRATIVE_TEMPLATE` entry) | transform (narrative renderer) | transform | `_program_lines` + its `_NarrativeSection` registration, same file | exact |
| `backend/app/mcp/tools/reports.py` (`_report_body_fields` split; `capped_report` extension) | controller (MCP tool / projection) | request-response | `plateau_highlights` filter+cap block in `_report_body_fields`, same function | exact |
| `backend/app/mcp/tools/schemas.py` (`MonthlyReportResponse.physique` field; `WeeklyReportResponse` stays untouched) | model (MCP wire schema) | request-response | `MonthlyReportResponse.narrative` field + its docstring, same file | exact |
| `backend/tests/test_analytics_reports.py` (extend `_report()`, add physique fixtures/tests) | test | transform | Existing `_recomposition()`/`_plateau_highlights()` fixture helpers + `test_a_program_switch_in_window_names_the_previous_program_and_date` style narrative assertions, same file | exact |
| `backend/tests/test_mcp_tool_schemas.py` (new `hasattr`/`model_fields` structural test) | test | request-response | File's existing schema-surface assertion style (e.g. `test_no_tool_publishes_a_user_id_argument`) | role-match |

No files require an analog from outside these two analytics/mcp modules — this phase is
compose-only against Phase 17's already-built `analytics/physique.py` and
`db/repositories/physique.py`, which are consumed unchanged (see Shared Patterns below).

## Pattern Assignments

### `backend/app/analytics/schemas.py` — add `PhysiqueSection`

**Analog:** `ReportResult` itself (`backend/app/analytics/schemas.py:1003-1056`), specifically how
it embeds `RecompositionResult`, `PlateauReport` whole rather than projecting them, and
`PhysiqueDiffResult`/`PhysiqueVolumeCrossReference` (`schemas.py:1059-1146`), which already exist
from Phase 17 and need no changes — only a new wrapper model referencing them.

**Docstring convention to copy** (the "why embed whole" rationale, `schemas.py:1017-1020`):
```python
class ReportResult(_AnalyticsModel):
    """...
    Each of those three carries its own window in its own fields, which is why they are
    embedded whole rather than projected: a reader must be able to see that the verdict
    beside this week's volume is not a verdict about this week.
    ...
    """
```

**Model shape to add** (new class, placed after `PhysiqueVolumeCrossReference` at the bottom of
the module, following `_AnalyticsModel` conventions — `frozen=True`, `extra="forbid"`,
`hide_input_in_errors=True` inherited automatically):
```python
class PhysiqueSection(_AnalyticsModel):
    """RPT-04/D-01: the monthly report's physique block, embedded whole per ReportResult's own
    rule -- the cross-reference's 12-week volume window anchors on `observed_on`, not on the
    report window, and a flat projection would silently drop that anchor.

    `diff` is None when fewer than two non-superseded observations exist (D-12: still renders,
    with an explicit "first recorded observation" line). `cross_reference` is None only when
    zero observations exist at all -- exactly the case in which `PhysiqueSection` itself is None
    on `ReportResult` (D-11), so in practice this field is never None when the section exists.
    """

    latest_observed_on: dt.date
    latest_pose_state: PoseState
    latest_photo_angles_present: list[str]
    latest_conditions_note: str | None
    diff: PhysiqueDiffResult | None
    cross_reference: PhysiqueVolumeCrossReference
```
(Exact field set and names are Claude's discretion per CONTEXT.md — this is illustrative of the
shape D-01/D-05 require: embed the two Phase 17 results whole, carry header + confounders only
from the observation, no `ratings` list, no Claude-authored notes fields per D-09 unless CONTEXT.md
is revisited. `PoseState` is already imported by `app/mcp/tools/schemas.py` from
`app.db.models.physique` — the analytics layer will need the same import, matching how
`PhysiqueDiffResult`/`PhysiqueMuscleDiff` already import `PhysiqueRatingLevel` from that module at
`schemas.py:39`.)

**Extend `ReportResult`** (`schemas.py:1040-1056`) with one new field, appended after `freshness`
(field order in this file mirrors declaration/assembly order elsewhere, e.g.
`plateau_highlights` immediately follows `pr_highlights` because both come from the same part of
`compose_report`):
```python
    physique: PhysiqueSection | None
```
Update the class docstring's "Two anchors, both named" section to name physique's fourth anchor,
matching how the existing docstring calls out plateau/measurement/recomposition anchors by name
(`schemas.py:1011-1020`).

---

### `backend/app/analytics/reports.py` — `compose_report` (one conditional, three calls)

**Analog:** the existing `recomposition` and `plateaus` calls inside `compose_report`
(`reports.py:150-157`), which already demonstrate "call an unrelated-window analytics function
inside the same session, carry the result through untouched":

```python
    # Once, with NO window argument. Its `active_program`, `program_started_on`,
    # `program_switch_in_window`, `previous_program` and `program_switched_on` are the report's
    # program context, read verbatim -- not re-derived from the db repository layer.
    recomposition = await get_recomposition_status(session, user_id=user_id)

    # The FULL report, uncapped and unfiltered here. Filtering to `plateaued=True` and capping
    # is the MCP layer's presentation decision (plan 13-09), and `PlateauReport` carries the
    # window fields that keep the different anchor visible.
    plateaus = await get_plateaus(
        session, user_id=user_id, lookback_weeks=REPORT_PLATEAU_LOOKBACK_WEEKS
    )
```

**Pattern to copy for the physique block** — monthly-only conditional, three Phase 17/16 calls
inside the same transaction, added right before the `ReportResult(...)` construction:
```python
    physique: PhysiqueSection | None = None
    if period is ReportPeriod.MONTHLY:
        latest_observation = await get_latest_observation(session, user_id=user_id)
        if latest_observation is not None:
            diff = await get_latest_physique_diff(session, user_id=user_id)
            cross_reference = await get_physique_volume_cross_reference(
                session, user_id=user_id
            )
            physique = PhysiqueSection(
                latest_observed_on=latest_observation.observed_on,
                latest_pose_state=latest_observation.pose_state,
                latest_photo_angles_present=list(latest_observation.photo_angles_present),
                latest_conditions_note=latest_observation.conditions_note,
                diff=diff,
                cross_reference=cross_reference,  # never None once an observation exists
            )
```
Note `get_latest_physique_diff`/`get_physique_volume_cross_reference` each independently query for
the latest observation internally (`app/analytics/physique.py:167`, `:187`) — the discretionary
call to `get_latest_observation` above is what CONTEXT.md's Integration Points section
acknowledges as "not shareable" extra cost; do not try to eliminate the redundant read, it is
already named and accepted in CONTEXT.md.

**Add the import block** alongside the other analytics imports at the top of `reports.py`
(`reports.py:43-58`), following the existing grouping-by-module style:
```python
from app.analytics.physique import get_latest_physique_diff, get_physique_volume_cross_reference
from app.analytics.schemas import (
    ...
    PhysiqueSection,
    ...
)
from app.db.repositories.physique import get_latest_observation
```
This is a NEW cross-module import (`app/analytics/reports.py` importing from
`app/db/repositories/`) — check it against precedent: `reports.py` does not currently import any
`db/repositories/` module directly (it composes only from other `app/analytics/` functions). Verify
whether `test_analytics_isolation.py` permits `app.analytics` → `app.db.repositories` (it already
must, since `app/analytics/physique.py` itself imports `app.db.repositories.physique` at
`physique.py:67-71`, and `test_analytics_isolation.py` per the canonical refs only forbids `app.analytics` → `app.mcp`). No new isolation risk — `get_latest_observation` is the same repository
function `physique.py` already calls.

Add `physique=physique` to the `ReportResult(...)` constructor call at `reports.py:192-212`.

---

### `backend/app/analytics/reports.py` — narrative builder (`_physique_lines` + template entry)

**Analog 1 — the anchor-naming pattern:** `_program_lines` (`reports.py:391-423`), specifically its
opening anchor line:
```python
def _program_lines(report: ReportResult) -> list[str]:
    lines: list[str] = []
    recomposition = report.recomposition
    lines.append(
        f"- As of {report.recomposition_anchor_day.isoformat()} — a different anchor from the "
        f"{report.window_start.isoformat()} to {report.window_end.isoformat()} period above."
    )
    ...
    lines.append(recomposition.disclaimer)
    return lines
```
D-07 says the physique block's anchor line must make the same move, naming
`report.physique.latest_observed_on` (or the diff's `later_observed_on`) against
`window_start`/`window_end`.

**Analog 2 — the plateau-style filtered list rendering:** `_strength_lines`'s plateau section
(`reports.py:299-321`), which is the direct precedent for iterating `IMPROVED`/`REGRESSED` rows
and printing "none" when the filtered list is empty:
```python
    plateaued = [ex for ex in report.plateau_highlights.exercises if ex.plateaued]
    lines.append(...)
    if plateaued:
        for ex in plateaued:
            ...
            lines.append(f"  - {label}: {duration} days, {weight_part}")
    else:
        lines.append("  - none")
```
Note: by the time `build_narrative` runs, `report.physique.diff.muscle_groups` has ALREADY been
filtered to `IMPROVED`/`REGRESSED` by the MCP layer's `capped_report` mechanism (D-03) — the
narrative builder itself does NOT filter; it renders whatever `report.physique.diff` carries,
exactly as `_strength_lines` renders `report.plateau_highlights.exercises` filtered upstream in the
`compose_report`/MCP boundary... **correction, read carefully**: `_strength_lines` filters
IN-LINE (`plateaued = [ex for ex in ... if ex.plateaued]`) because `compose_report` passes the FULL
`PlateauReport` through `build_narrative` is called on `capped_report`, whose `plateau_highlights`
field was ALREADY replaced with the capped/filtered list by
`fitness_get_monthly_report`'s `model_copy`. So `_strength_lines`' own `if ex.plateaued` filter is
effectively a no-op belt-and-braces at narrative time since `capped_report.plateau_highlights.exercises`
is already only-plateaued. Follow the SAME belt-and-braces habit for physique: the narrative
builder can safely assume `report.physique.diff.muscle_groups` (on the `capped_report` it receives)
is already filtered to changed groups, but there is no harm mirroring `_strength_lines`' own
redundant filter for defence-in-depth if the planner prefers it.

**Analog 3 — null-figure-as-word for D-12's "first recorded observation" line:** the `_body_lines`
null-rendering convention (`reports.py:326-349`):
```python
    avg_7d = (
        "not enough weigh-ins"
        if weight_trend.average_7d_kg is None
        else f"{weight_trend.average_7d_kg} kg"
    )
```
Mirror this exactly for `report.physique.diff is None`: render an explicit sentence (e.g.
"- First recorded observation — no prior to compare against.") rather than omitting the line or
printing a bare falsy value.

**Analog 4 — verbatim disclaimer, own line, at block end:** `_program_lines`' last line
(`reports.py:422`): `lines.append(recomposition.disclaimer)`. Physique's disclaimer field
(`report.physique.cross_reference.disclaimer` or `report.physique.diff.disclaimer` — both carry
the identical `PHYSIQUE_RATING_DISCLAIMER` string per `physique.py:152` and `:232`) renders once,
the same way, at the very end of `_physique_lines`.

**Template registration pattern** — `_NarrativeSection` dataclass and `_NARRATIVE_TEMPLATE` tuple
(`reports.py:240-263`, `:442-450`):
```python
@dataclass(frozen=True, slots=True)
class _NarrativeSection:
    heading: str
    build: Callable[[ReportResult], list[str]]
    periods: tuple[ReportPeriod, ...] | None = None

    def applies_to(self, period: ReportPeriod) -> bool:
        return self.periods is None or period in self.periods
```
Add the new builder function `_physique_lines(report: ReportResult) -> list[str]` beside the other
`_*_lines` functions, then register it as the 8th, monthly-only entry:
```python
_NARRATIVE_TEMPLATE: tuple[_NarrativeSection, ...] = (
    _NarrativeSection("## Training", _training_lines),
    ...
    _NarrativeSection("## Data quality", _data_quality_lines),
    _NarrativeSection("## Physique", _physique_lines, (ReportPeriod.MONTHLY,)),
)
```
This is EXACTLY the mechanism `test_a_monthly_only_section_renders_monthly_and_is_absent_weekly`
(`test_analytics_reports.py:773-795`) already proves works, using a throwaway
`_NarrativeSection(marker, lambda report: [...], (ReportPeriod.MONTHLY,))` fixture.

**D-13's empty-section skip (`build_narrative`'s loop, `reports.py:516-521`):**
```python
    for section in _NARRATIVE_TEMPLATE:
        if not section.applies_to(report.period):
            continue
        lines.append("")
        lines.append(section.heading)
        lines.extend(section.build(report))
```
Per CONTEXT.md's discretion note, the simplest no-op-provable change (option (a) in the
Claude's Discretion list) is to skip a section whose builder would have nothing to say — since
EVERY existing builder is documented to always return ≥1 line for a populated report (D-13's
"provably a no-op" test constraint), the cleanest addition is a period+data guard specific to
physique rather than a generic "empty body" check that risks silently swallowing a future bug in
one of the seven existing builders. E.g. extend the loop's condition or add a
`report.physique is not None` case directly ahead of calling `_physique_lines`, and keep
`_physique_lines` itself total (never returning `[]`) so the "seven shipped sections always render"
invariant is unaffected. `_NarrativeSection.applies_to` is a good extension point if the planner
chooses option (b) from CONTEXT.md (a predicate over the whole `ReportResult`, not just `period`).

---

### `backend/app/mcp/tools/reports.py` — `_report_body_fields` split + `capped_report` extension

**Analog:** the plateau filter block, verbatim precedent for D-02/D-03 (`reports.py:80-89`,
mcp tools):
```python
    # Plateau highlights: filtered to PLATEAUED exercises FIRST, then capped. So
    # `plateau_highlights_total` is the number of plateaued exercises, not the number scanned --
    # the two are different claims, and the wrong one reads as "you have 30 stalled lifts" for
    # what is really "of the 30 exercises analysed, this many are stuck".
    plateaued = [exercise for exercise in report.plateau_highlights.exercises if exercise.plateaued]
    (
        plateau_highlights,
        plateau_highlights_truncated,
        plateau_highlights_total,
    ) = truncate(plateaued, MAX_REPORT_PLATEAU_HIGHLIGHTS)
```
Physique's analog is D-02's filter (no `truncate()` call per D-06 — carried whole, no cap):
```python
    physique_diff_groups = (
        [
            group
            for group in report.physique.diff.muscle_groups
            if group.verdict in (PhysiqueDiffVerdict.IMPROVED, PhysiqueDiffVerdict.REGRESSED)
        ]
        if report.physique is not None and report.physique.diff is not None
        else None
    )
```
D-03 specifies this filter runs at the MCP layer, NOT in `_report_body_fields`'s shared
projection — but per D-03/CONTEXT.md's "the shared part stays shared, and `physique` is added only
at the monthly call site" (Integration Points, CONTEXT.md line 311-312), meaning
`_report_body_fields` itself is likely NOT the right place; instead follow the model of
`_degraded_monthly` adding `narrative=None` as a keyword ON TOP of the shared
`_degraded_body_fields()` dict (`reports.py:199-200`, mcp tools):
```python
def _degraded_monthly() -> MonthlyReportResponse:
    return MonthlyReportResponse(**_degraded_body_fields(), narrative=None)
```
i.e. `physique` should be assembled and filtered inside `fitness_get_monthly_report` itself (or a
small monthly-only helper called from it), NOT inside the shared `_report_body_fields`, exactly
mirroring how `narrative` is computed only in `fitness_get_monthly_report`
(`reports.py:216-243`, mcp tools) and never touches `fitness_get_weekly_report`.

**The `capped_report` extension point** (`reports.py:233-242`, mcp tools) — this is the SINGLE
most load-bearing excerpt for this phase per D-03:
```python
    capped_report = report.model_copy(
        update={
            "pr_highlights": report.pr_highlights.model_copy(
                update={"records": body_fields["pr_highlights"]}
            ),
            "plateau_highlights": report.plateau_highlights.model_copy(
                update={"exercises": body_fields["plateau_highlights"]}
            ),
        }
    )
    return MonthlyReportResponse(**body_fields, narrative=build_narrative(capped_report))
```
D-03 requires extending this SAME `model_copy` call with a third key:
```python
    capped_report = report.model_copy(
        update={
            "pr_highlights": ...,
            "plateau_highlights": ...,
            "physique": (
                report.physique.model_copy(
                    update={
                        "diff": report.physique.diff.model_copy(
                            update={"muscle_groups": physique_diff_groups}
                        )
                        if report.physique.diff is not None
                        else None
                    }
                )
                if report.physique is not None
                else None
            ),
        }
    )
```
This is what makes `build_narrative` narrate the SAME filtered list the JSON `physique` field
carries — the exact bug class `WR-01` (referenced in
`test_monthly_narrative_respects_the_same_plateau_cap_as_the_structured_field`,
`test_mcp_tools.py:1426-1459`) fixed for plateaus; physique must not reintroduce it.

**`_degraded_body_fields()` extension** (`reports.py:152-192`, mcp tools) — add `"physique": None`
to the dict returned there, matching every other field's degraded-empty convention, OR (per D-14,
which puts `physique=None` alongside `narrative=None` rather than in the SHARED degraded dict since
`WeeklyReportResponse` has no `physique` field at all) add it only in `_degraded_monthly()`:
```python
def _degraded_monthly() -> MonthlyReportResponse:
    return MonthlyReportResponse(**_degraded_body_fields(), narrative=None, physique=None)
```
This is D-14's literal instruction ("added to `_degraded_monthly` exactly as `narrative=None`
already is") — do NOT add `physique` to `_degraded_body_fields()` / `_ReportBody`, because that
dict is shared with `_degraded_weekly()` and `WeeklyReportResponse` must not have the field at all
(criterion #1's structural absence).

---

### `backend/app/mcp/tools/schemas.py` — `MonthlyReportResponse.physique` field

**Analog:** `MonthlyReportResponse.narrative` and its docstring, and `WeeklyReportResponse`'s
docstring stating the exclusion (`schemas.py:555-575`):
```python
class WeeklyReportResponse(_ReportBody):
    """RPT-01: Monday of the current local week through today.

    Deliberately has NO ``narrative`` field. D-14 scopes the markdown narrative to the
    monthly report only, at the user's explicit request -- a weekly answer is short enough
    that a prose restatement beside the structured fields is duplicated context, not help.
    """


class MonthlyReportResponse(_ReportBody):
    """RPT-02: the first of the current local calendar month through today.

    ``narrative`` is D-14: a markdown string generated server-side by
    ``analytics/reports.py::build_narrative``, a DETERMINISTIC template restating the same
    data the structured fields above already carry. Not free-form text, not AI-authored, and
    carrying no recommendation language -- ``test_analytics_reports.py`` asserts all three.
    ``None`` exactly when ``data_available`` is False.
    """

    narrative: str | None
```
Copy this pattern exactly for `physique`, on `MonthlyReportResponse` only:
```python
class MonthlyReportResponse(_ReportBody):
    """...
    ``physique`` is RPT-04: the Phase 17 physique diff and volume cross-reference, embedded
    whole, filtered to changed muscle groups (D-02/D-03). ``None`` when the user has never
    logged an observation -- the SAME value ``WeeklyReportResponse`` would carry if it had the
    field at all, so a structural (`hasattr`/`model_fields`) check is what proves the weekly
    absence, never the value (D-11).
    """

    narrative: str | None
    physique: PhysiqueSection | None
```
And add `PhysiqueSection` to the `from app.analytics.schemas import (...)` block at the top of
`schemas.py:38-64`, matching how `PhysiqueRatingLevel`/`PoseState` are already imported from
`app.db.models.physique` at `schemas.py:65` for the write/read tools' schemas.

**`WeeklyReportResponse` stays completely untouched** — this IS the pattern: its docstring already
states the exclusion rule for `narrative`, and criterion #1 wants the identical structural
guarantee for `physique`. No edit needed to `WeeklyReportResponse` itself.

---

### `backend/tests/test_analytics_reports.py` — fixtures and new tests

**Analog for a new result-type fixture helper:** `_recomposition()` (`test_analytics_reports.py:401-416`)
and `_plateau_highlights()` — both build a fully-populated default instance with `**overrides`
merge:
```python
def _recomposition(**overrides: object) -> RecompositionResult:
    base: dict[str, object] = {
        "status": RecompositionStatus.LIKELY_MUSCLE_GAIN,
        ...
    }
    base.update(overrides)
    return RecompositionResult(**base)  # type: ignore[arg-type]
```
Add a `_physique_section(**overrides)` helper of the same shape, and extend `_report()`
(`test_analytics_reports.py:419-448`) to include a default `"physique": _physique_section()` (for
MONTHLY) — note `_report()` takes `period` as a keyword with a `MONTHLY` default already, so the
existing WEEKLY-period tests that call `_report(period=ReportPeriod.WEEKLY)` will need to either
override `physique=None` or rely on a conditional default inside `_report()` itself, mirroring how
`ReportResult`'s real `compose_report` only ever populates `physique` for `MONTHLY`.

**Analog for a narrative content assertion:** `test_a_program_switch_in_window_names_the_previous_program_and_date`
(`test_analytics_reports.py:701-711`) — the exact shape a new
`test_physique_anchor_line_names_a_different_date_than_the_report_window` or similar should take:
```python
def test_a_program_switch_in_window_names_the_previous_program_and_date() -> None:
    switched_on = dt.date.fromisoformat("2026-05-15")
    report = _report(
        recomposition=_recomposition(
            program_switch_in_window=True,
            previous_program=TrainingProgram.CUT,
            program_switched_on=switched_on,
        )
    )
    narrative = build_narrative(report)
    assert f"switched from cut on {switched_on.isoformat()}" in narrative
```

**Analog for D-10's word-provenance test:** `test_every_number_in_the_narrative_is_already_in_the_structured_fields`
(`test_analytics_reports.py:730-750`) is the numeric twin; a new
`test_every_rating_word_in_the_narrative_is_already_in_the_structured_fields`-style test should
read `.value` off `report.physique`'s own enum fields (verdicts, rating levels) — NOT off
`PhysiqueRatingLevel`/`PhysiqueDiffVerdict` class members directly — per D-10's explicit rejection
of the weaker enum-class-scan variant. Structure it the same way: collect the set of legal words
from the report instance, tokenize the rendered block, assert every rating/verdict word rendered is
`in` that set.

**`test_the_template_declares_the_seven_sections_in_order`** (`test_analytics_reports.py:753-770`)
MUST be updated in the same commit — both the heading list (append `"## Physique"`) and the
`all(section.periods is None ...)` assertion (must become an assertion that exactly one section —
physique — has `periods == (ReportPeriod.MONTHLY,)` and the rest have `periods is None`). This is
flagged as an expected-to-fail-on-arrival test in CONTEXT.md's Tripwires section.

**Exclude notes fields from the provenance dump (D-09):** wherever
`report.model_dump_json()` is called for the numeric-provenance test, D-09 requires excluding
`leanness_notes`, `conditioning_notes`, `symmetry_notes`, `conditions_note` — but those live on
`PhysiqueObservationView` / possibly `PhysiqueSection`, not on `ReportResult` directly. If
`PhysiqueSection` does NOT carry those fields at all (design choice per D-09's "no Claude-authored
free-text field renders... they travel as structured JSON fields on `PhysiqueSection`" — meaning
they DO belong on `PhysiqueSection` per RPT-05 criterion #3), then
`test_every_number_in_the_narrative_is_already_in_the_structured_fields` must call
`report.model_dump_json(exclude={"physique": {"latest_conditions_note", ...}})` (Pydantic nested
exclude syntax) rather than the current bare `report.model_dump_json()` at line 742. This is new
work with no direct in-repo analog (the existing test never excludes anything) — the closest
precedent is Pydantic's own nested `exclude` dict syntax, not a codebase pattern.

---

### `backend/tests/test_mcp_tool_schemas.py` — structural absence test

**Analog:** the file's existing schema-surface-assertion style, e.g.
`test_no_tool_publishes_a_user_id_argument` (structural/negative assertions about a model's
declared surface rather than about return values). No exact `hasattr`-on-a-response-model
precedent exists yet in this file — this is the first structural field-absence test of its kind —
but the file's whole purpose statement ("asserts the TOOL SURFACE ... does not assert what any
tool returns") makes it the correct home per CONTEXT.md's canonical refs.

**Pattern to write:**
```python
def test_weekly_report_response_has_no_physique_field() -> None:
    """Criterion #1: the weekly report is STRUCTURALLY incapable of carrying a physique
    section -- a hasattr/model-field-set check, not omission by convention (D-11's
    consequence: a None physique on the monthly report no longer proves weekly)."""
    from app.mcp.tools.schemas import MonthlyReportResponse, WeeklyReportResponse

    assert "physique" not in WeeklyReportResponse.model_fields
    assert "physique" in MonthlyReportResponse.model_fields
```
`model_fields` (Pydantic v2 class attribute, a `dict[str, FieldInfo]`) is the correct mechanism —
matches the `WeeklyReportResponse`/`MonthlyReportResponse` docstrings' own framing ("Deliberately
has NO ``narrative`` field") and needs no `hasattr` on an instance since these are class-level
Pydantic field declarations.

## Shared Patterns

### Composed, never computed (whole-file discipline)
**Source:** `backend/app/analytics/schemas.py:1004-1009` (`ReportResult` docstring)
**Apply to:** `PhysiqueSection` and every new field/function this phase adds.
```python
"""**Composed, never computed.** Every field below is another analytics function's return
value, carried through. ``analytics/reports.py`` owns the WINDOW and the ASSEMBLY and
nothing else..."""
```
No new arithmetic anywhere in this phase — `get_latest_physique_diff`,
`get_physique_volume_cross_reference`, `get_latest_observation` are called exactly as Phase 17
built them, unchanged.

### No recommendation language / banned-token discipline
**Source:** `backend/tests/test_analytics_reports.py:109-119` (`_BANNED_NARRATIVE_TOKENS`)
**Apply to:** `_physique_lines`.
```python
_BANNED_NARRATIVE_TOKENS: tuple[str, ...] = (
    "should", "recommend", "suggest", "consider", "advise", "deload", "aim for",
    "you need", "try ",
)
```
CONTEXT.md's Tripwires section flags that `"try "` is a substring of `"symmetry "` — since D-09
keeps symmetry notes out of the narrative entirely this should not fire, but any future `Symmetry:`
label in `_physique_lines` would trip this check with a misleading failure message.

### Verbatim disclaimer on its own line
**Source:** `backend/app/analytics/reports.py:422` (`_program_lines`)
**Apply to:** `_physique_lines`'s final line — `PHYSIQUE_RATING_DISCLAIMER`
(`backend/app/db/models/physique.py:81-85`), read off `report.physique.cross_reference.disclaimer`
or `.diff.disclaimer` (identical string on both), never retyped or paraphrased.

### Null figures render as explicit words, never a bare 0/omission
**Source:** `backend/app/analytics/reports.py:326-349` (`_body_lines`)
**Apply to:** D-12's "first recorded observation" line when `report.physique.diff is None`.

### `_AnalyticsModel`/`_McpModel` shared config (frozen, extra=forbid, hide_input_in_errors)
**Source:** `backend/app/analytics/schemas.py:43-57`, `backend/app/mcp/tools/schemas.py:69-84`
**Apply to:** `PhysiqueSection` (inherits `_AnalyticsModel` automatically by living in
`schemas.py` and subclassing it) — no new config needed, just correct subclassing.

### `model_copy(update={...})` for narrative/JSON consistency
**Source:** `backend/app/mcp/tools/reports.py:233-242` (mcp tools) — the `capped_report` mechanism
**Apply to:** the `physique` field's filtered `diff.muscle_groups`, exactly as already documented
above in Pattern Assignments. This is the SINGLE most important shared pattern in this phase — get
it wrong and the narrative silently disagrees with the JSON field beside it (the WR-01 bug class).

### `_degraded_*` factories return a fresh, fully-populated "nothing happened" object
**Source:** `backend/app/mcp/tools/reports.py:152-201` (mcp tools) — `_degraded_body_fields`,
`_degraded_weekly`, `_degraded_monthly`
**Apply to:** `_degraded_monthly`'s `physique=None` addition (D-14).

## No Analog Found

None. Every file this phase touches is an existing file with an existing, directly-analogous
section (recomposition/plateau/narrative) inside the SAME module. This is expected for a
composition-only phase with no new architectural shape — see the phase brief's framing: "no new
analytics arithmetic, any new SQL, or any new MCP tool."

## Metadata

**Analog search scope:** `backend/app/analytics/` (`reports.py`, `schemas.py`, `physique.py`),
`backend/app/mcp/tools/` (`reports.py`, `schemas.py`, `physique.py`), `backend/app/db/models/physique.py`,
`backend/app/db/repositories/physique.py`, `backend/tests/test_analytics_reports.py`,
`backend/tests/test_mcp_tool_schemas.py`, `backend/tests/test_mcp_tools.py`
**Files scanned (read in full or in relevant excerpt):** 9 production modules, 3 test modules
**Pattern extraction date:** 2026-09-12
