---
phase: quick-260907-dsu
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/analytics/reports.py
  - backend/tests/test_analytics_reports.py
  - backend/tests/fixtures/reports/weekly_narrative.md
  - backend/tests/fixtures/reports/monthly_narrative.md
autonomous: true
requirements: [QUICK-260907-dsu]
# No ROADMAP requirement ID: this is a standalone quick task. It forward-designs the section
# slot that Phase 18 (RPT-04/RPT-05) will fill, but it implements none of Phase 18's scope.

must_haves:
  truths:
    - "build_narrative renders byte-identical output to today's for identical input, for both WEEKLY and MONTHLY"
    - "The seven narrative sections are declared as one explicit, ordered, named template rather than a single inline function body"
    - "A section can declare itself monthly-only (or weekly-only) and is skipped for the other period"
    - "Adding a period-conditional section requires adding one template entry and one builder function, editing no existing section code"
    - "build_narrative stays pure and synchronous with no new third-party dependency"
  artifacts:
    - path: "backend/app/analytics/reports.py"
      provides: "_NarrativeSection type, _NARRATIVE_TEMPLATE ordered tuple, seven private section builders, a template-driven build_narrative"
      contains: "_NARRATIVE_TEMPLATE"
    - path: "backend/tests/fixtures/reports/monthly_narrative.md"
      provides: "Pre-refactor golden snapshot of the monthly narrative"
    - path: "backend/tests/fixtures/reports/weekly_narrative.md"
      provides: "Pre-refactor golden snapshot of the weekly narrative"
    - path: "backend/tests/test_analytics_reports.py"
      provides: "Golden-snapshot equality test plus the period-conditional slot test"
      contains: "_NARRATIVE_TEMPLATE"
  key_links:
    - from: "backend/app/analytics/reports.py::build_narrative"
      to: "_NARRATIVE_TEMPLATE"
      via: "iteration over the ordered section tuple, filtered by report.period"
      pattern: "for .* in _NARRATIVE_TEMPLATE"
    - from: "backend/tests/test_analytics_reports.py"
      to: "backend/tests/fixtures/reports/*.md"
      via: "read_text comparison against build_narrative output"
      pattern: "fixtures.*reports"
---

<objective>
Restructure `build_narrative` in `backend/app/analytics/reports.py` from one long inline
f-string body into an explicit, ordered template of named sections, so the contract weekly and
monthly reports share is visible in the code shape rather than enforced only by convention and
tests. Design the template so a section can be declared for one `ReportPeriod` only — the slot
Phase 18's monthly-only physique section will occupy.

Purpose: `build_narrative` is the single field `docs/coaching-instructions.md` tells Claude to
quote directly, and Phase 18 must add a monthly-only section to it. Today that means editing a
200-line function body and hoping the seven-section order survives review. After this task,
Phase 18 adds one template entry and one builder function and touches no existing section.

Output: A template-driven `build_narrative` whose rendered output is byte-identical to today's,
proven by a golden snapshot captured from the pre-refactor code, plus a test proving the
period-conditional slot actually skips a section for the wrong period.

**This is a pure refactor.** No section is added, removed, renamed or reordered. No wording
changes. No physique section — that is Phase 18's scope and must not appear here.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/quick/260907-dsu-formalize-weekly-monthly-report-narrativ/260907-dsu-CONTEXT.md
@backend/app/analytics/reports.py
@backend/tests/test_analytics_reports.py
@backend/tests/test_analytics_isolation.py

<interfaces>
<!-- Contracts the executor needs. Extracted from the codebase — do not go hunting. -->

The seven sections, in their current committed order, with the exact heading string each emits
(`backend/app/analytics/reports.py:285-450`). The blank line before each heading is part of the
existing output and must be preserved:

```
"# {period_label} report — {window_start} to {window_end}"   <- title, NOT a section
""            "## Training"                  reports.py:290-301
""            "## Strength"                  reports.py:304-342
""            "## Body"                      reports.py:345-399
""            "## Nutrition"                 reports.py:402-403
""            "## Activity"                  reports.py:406-407
""            "## Program and recomposition" reports.py:410-440
""            "## Data quality"              reports.py:443-450
```

Existing helper that stays exactly as-is (`reports.py:213`):
```python
def _period_summary_lines(summary: ActivityPeriodSummary | NutritionPeriodSummary) -> list[str]
```

Relevant `app.analytics.schemas` members already imported by this module:
```python
class ReportPeriod(StrEnum):  # WEEKLY, MONTHLY
class ReportResult(BaseModel): ...  # period, window_start, window_end, days_in_period,
                                    # weekly_volume, muscle_volume, frequency, recomposition,
                                    # recomposition_anchor_day, pr_highlights,
                                    # plateau_highlights, plateau_lookback_weeks,
                                    # measurement_highlights, activity, nutrition,
                                    # coverage, freshness
```

The only production caller (`backend/app/mcp/tools/reports.py:243`) — its signature must not
change:
```python
return MonthlyReportResponse(**body_fields, narrative=build_narrative(capped_report))
```
`fitness_get_weekly_report` never calls `build_narrative`; `WeeklyReportResponse` deliberately
has no `narrative` field (`app/mcp/tools/schemas.py:553-559`). `build_narrative` nonetheless
supports `ReportPeriod.WEEKLY` and is tested for it — keep that.

Test fixture builder already present in the test module (`test_analytics_reports.py:412`):
```python
def _report(*, period: ReportPeriod = ReportPeriod.MONTHLY, **overrides: object) -> ReportResult
```

Static guards in `backend/tests/test_analytics_isolation.py` that scan `app/analytics/` source
and will fail the fast suite if the new code trips them:
- `_FLOAT_USE`: no `float(`, `: float`, `-> float`, `[float]` anywhere — annotate with `Decimal`
  or leave untyped; none of this refactor needs a float
- `_MCP_IMPORT` / `_INTEGRATIONS_IMPORT`: no `import app.mcp`, no `import app.integrations`
- `_RAW_SQL_TEXT`, `_SESSION_WRITE`, `_WRITE_IMPORT`: irrelevant here, but do not introduce
- Prose convention: refer to DB tables in lowercase, never by ORM class name
</interfaces>

Project config: `line-length = 100`, `target-version = "py313"`, ruff lint
`["E","F","I","UP","B","ASYNC","S","DTZ"]`, mypy in use, `asyncio_mode = "auto"`,
`pythonpath = ["backend"]`, `testpaths = ["backend/tests"]`. Pre-commit runs `ruff --fix`,
`ruff-format`, `end-of-file-fixer`, `trailing-whitespace`.

Test command used throughout (repo root, fast suite only — no container needed for
`build_narrative`):
```bash
uv run pytest backend/tests/test_analytics_reports.py -m "not integration" -q
```
</context>

<tasks>

<task type="auto">
  <name>Task 1: Capture the pre-refactor narrative as a committed golden snapshot</name>
  <files>backend/tests/fixtures/reports/monthly_narrative.md, backend/tests/fixtures/reports/weekly_narrative.md, backend/tests/test_analytics_reports.py</files>
  <action>
Build the safety net BEFORE touching `reports.py`. Byte-identical output is this task's
headline constraint and the existing tests only assert substrings — they would pass through a
reordered or subtly reworded refactor.

1. Generate both snapshots from the CURRENT, UNMODIFIED `build_narrative`, using the test
   module's own `_report()` baseline fixture (fully populated, every section non-null). Run from
   the repo root:

```bash
uv run python - <<'PY'
import pathlib, sys
sys.path.insert(0, "backend")
from app.analytics.reports import build_narrative
from app.analytics.schemas import ReportPeriod
from tests.test_analytics_reports import _report

out = pathlib.Path("backend/tests/fixtures/reports")
out.mkdir(parents=True, exist_ok=True)
for period, name in ((ReportPeriod.MONTHLY, "monthly"), (ReportPeriod.WEEKLY, "weekly")):
    text = build_narrative(_report(period=period))
    assert not any(line != line.rstrip() for line in text.splitlines()), (
        "a narrative line has trailing whitespace; the trailing-whitespace pre-commit hook "
        "would silently corrupt the golden file — store the golden as a Python literal instead"
    )
    (out / f"{name}_narrative.md").write_text(text + "\n", encoding="utf-8")
    print(name, len(text.splitlines()), "lines")
PY
```

   The trailing-whitespace assertion is not decoration: `end-of-file-fixer` and
   `trailing-whitespace` run on commit, and a corrupted golden file would turn the one test
   that guards byte-identity into a test that guards the corruption. If it fires, stop and
   switch to a triple-quoted literal in the test module.

2. Eyeball both generated files. They must contain the seven `##` headings in the documented
   order, differing from each other only in the `# Weekly report —` / `# Monthly report —`
   title line. If they differ anywhere else, the fixture is wrong — stop.

3. Add to `backend/tests/test_analytics_reports.py`, in the "Task 1: build_narrative behaviour"
   block, a module-level fixture path constant and one parametrized test:

```python
_NARRATIVE_GOLDEN_DIR = Path(__file__).resolve().parent / "fixtures" / "reports"


@pytest.mark.parametrize(
    ("period", "golden"),
    [
        (ReportPeriod.MONTHLY, "monthly_narrative.md"),
        (ReportPeriod.WEEKLY, "weekly_narrative.md"),
    ],
)
def test_the_narrative_is_byte_identical_to_the_committed_golden(
    period: ReportPeriod, golden: str
) -> None:
    """The refactor guard. The other tests in this block assert SUBSTRINGS, so a reordered,
    reworded or silently dropped section passes all of them. This one does not: it pins the
    whole rendered document, captured from the pre-refactor `build_narrative`, so any change
    to what a report renders has to be a deliberate re-capture of this file with a stated
    reason -- never a side effect of restructuring how it is rendered."""
    expected = (_NARRATIVE_GOLDEN_DIR / golden).read_text(encoding="utf-8")
    assert build_narrative(_report(period=period)) + "\n" == expected
```

   Add `from pathlib import Path` to the imports if absent (ruff `I` will order it). Do NOT
   modify or delete any existing test.
  </action>
  <verify>
    <automated>uv run pytest backend/tests/test_analytics_reports.py -m "not integration" -q</automated>
  </verify>
  <done>Both golden files exist under `backend/tests/fixtures/reports/`, contain the seven headings in order, and the new parametrized test passes against the unmodified `build_narrative`. Every pre-existing test in the file still passes, unedited.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Refactor build_narrative into an explicit named-section template</name>
  <files>backend/app/analytics/reports.py</files>
  <behavior>
    - `build_narrative(_report(period=MONTHLY))` is byte-identical to the Task 1 golden
    - `build_narrative(_report(period=WEEKLY))` is byte-identical to the Task 1 golden
    - Every pre-existing assertion in `test_analytics_reports.py` (banned-token scan, numeric
      provenance, null-figure phrases, stale suffix, verbatim disclaimer) passes unchanged
    - `build_narrative` remains a `def`, not `async def`, and opens no session
    - `_NARRATIVE_TEMPLATE` is an ordered tuple of exactly seven entries
  </behavior>
  <action>
Restructure the body of `build_narrative` only. No wording, ordering or content changes.

1. Add the section type near `_period_summary_lines`:

```python
@dataclass(frozen=True, slots=True)
class _NarrativeSection:
    """One heading plus the builder that renders its body lines, and the periods it applies to.

    `periods=None` means EVERY period -- all seven of today's sections. A section restricted to
    one period declares it explicitly, which is the slot Phase 18's monthly-only physique
    section occupies: a new entry in `_NARRATIVE_TEMPLATE` plus its own builder, editing no
    existing section's code.

    `build` is a dataclass FIELD, not a class attribute. Instance attribute lookup performs no
    descriptor binding, so `self.build(report)` calls the plain function with one argument; a
    class-level `build = _training_lines` would bind `self` and pass two.

    Builders return BODY lines only. `build_narrative` owns the blank line and the heading, so
    no builder can forget one and no two builders can disagree about the separator.
    """

    heading: str
    build: Callable[[ReportResult], list[str]]
    periods: tuple[ReportPeriod, ...] | None = None

    def applies_to(self, period: ReportPeriod) -> bool:
        return self.periods is None or period in self.periods
```

   Imports: `from collections.abc import Callable` and `from dataclasses import dataclass`.
   No third-party dependency — the module docstring's existing rule against a text-templating
   library still holds and this refactor does not weaken it.

2. Extract seven private module-level builders, each `(report: ReportResult) -> list[str]`,
   moving the existing lines VERBATIM out of `build_narrative` with no edits beyond returning a
   local `lines` list instead of appending to the outer one:
   - `_training_lines` — `reports.py:291-301` (period line, sessions/week, per-week bullets)
   - `_strength_lines` — `reports.py:305-342` (PR block, then the stalled block)
   - `_body_lines` — `reports.py:346-399` (weight-trend figures, then measurement highlights,
     including both `raise ValueError` invariant checks unchanged)
   - `_nutrition_lines` — `return _period_summary_lines(report.nutrition)`
   - `_activity_lines` — `return _period_summary_lines(report.activity)`
   - `_program_lines` — `reports.py:411-440` (anchor line, program line, status, then the
     verbatim `recomposition.disclaimer` as its own line)
   - `_data_quality_lines` — `reports.py:444-450`

   Keep every existing inline comment with the code it explains — the BODY_MEASUREMENT
   invariant comment, the "different anchor" reasoning, all of it.

3. Declare the template as an ordered module-level constant, immediately after the builders:

```python
_NARRATIVE_TEMPLATE: tuple[_NarrativeSection, ...] = (
    _NarrativeSection("## Training", _training_lines),
    _NarrativeSection("## Strength", _strength_lines),
    _NarrativeSection("## Body", _body_lines),
    _NarrativeSection("## Nutrition", _nutrition_lines),
    _NarrativeSection("## Activity", _activity_lines),
    _NarrativeSection("## Program and recomposition", _program_lines),
    _NarrativeSection("## Data quality", _data_quality_lines),
)
```

4. Reduce `build_narrative` to the title plus the loop. This exact shape reproduces today's
   output: the title is followed by a blank line, and every section is preceded by one:

```python
    period_label = report.period.value.capitalize()
    lines: list[str] = [
        f"# {period_label} report — {report.window_start.isoformat()} to "
        f"{report.window_end.isoformat()}",
    ]
    for section in _NARRATIVE_TEMPLATE:
        if not section.applies_to(report.period):
            continue
        lines.append("")
        lines.append(section.heading)
        lines.extend(section.build(report))
    return "\n".join(lines)
```

5. Extend `build_narrative`'s docstring with a short paragraph recording the new shape: the
   narrative is an ordered template of named sections; weekly and monthly share it by
   construction rather than by convention; a section may be restricted to one `ReportPeriod`;
   builders return body lines and the loop owns the heading and separator. Keep every existing
   paragraph — the determinism rule, the D-03 no-recommendation-language rule, the verbatim
   disclaimer rule and the Decimal/isoformat/`.value` rendering rules are all still load-bearing
   and now apply to the builders. Preserve the two sentences the docstring already flags as
   deliberately rephrased to avoid tripping static greps; do not "fix" their wording.

Constraints to hold while doing this: no `float` in any form (`test_analytics_isolation.py`'s
`_FLOAT_USE` regex scans this file); no new import from `app.mcp` or `app.integrations`;
`build_narrative` stays pure and synchronous; lines stay within 100 columns.
  </action>
  <verify>
    <automated>uv run pytest backend/tests/test_analytics_reports.py backend/tests/test_analytics_isolation.py -m "not integration" -q && uv run ruff check backend/app/analytics/reports.py && uv run ruff format --check backend/app/analytics/reports.py && uv run mypy backend/app/analytics/reports.py</automated>
  </verify>
  <done>`build_narrative` is the title plus a loop over `_NARRATIVE_TEMPLATE`; seven named builders hold the section bodies; both golden tests pass, meaning weekly and monthly output is byte-identical to pre-refactor; every pre-existing test passes with no edit; ruff, ruff-format and mypy are clean.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Prove the period-conditional slot Phase 18 will use</name>
  <files>backend/tests/test_analytics_reports.py</files>
  <behavior>
    - The template's headings equal the seven documented headings, in order
    - A section declared `periods=(MONTHLY,)` renders in a monthly narrative
    - The same section is absent from a weekly narrative
    - Weekly output with no extra section registered still equals the golden byte for byte
  </behavior>
  <action>
Without a test, `periods` is unexercised design and Phase 18 inherits a slot nobody has proven
works. Add two tests to the "Task 1: build_narrative behaviour" block of
`backend/tests/test_analytics_reports.py`.

1. Import `_NARRATIVE_TEMPLATE` and `_NarrativeSection` from `app.analytics.reports` alongside
   the existing `build_narrative, compose_report, resolve_report_window` import. Private-name
   imports are acceptable here for the same reason the module already imports
   `INTERPRETATION_DISCLAIMER` — the test's subject IS the internal structure.

2. Pin the template's shape and order:

```python
def test_the_template_declares_the_seven_sections_in_order() -> None:
    """The shared contract, asserted on the template itself rather than inferred from rendered
    text. `test_the_seven_section_headings_are_present` proves the headings reach the output;
    this proves there is ONE ordered declaration producing them, which is what makes weekly and
    monthly structurally identical instead of coincidentally identical."""
    assert [section.heading for section in _NARRATIVE_TEMPLATE] == [
        "## Training",
        "## Strength",
        "## Body",
        "## Nutrition",
        "## Activity",
        "## Program and recomposition",
        "## Data quality",
    ]
    assert all(section.periods is None for section in _NARRATIVE_TEMPLATE), (
        "every section shipped today applies to BOTH periods; the first period-restricted "
        "section is Phase 18's monthly-only physique block"
    )
```

3. Exercise the slot end to end with a throwaway section appended via `monkeypatch`, so
   production code gains nothing speculative and Phase 18 inherits a mechanism with a passing
   test behind it:

```python
def test_a_monthly_only_section_renders_monthly_and_is_absent_weekly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 18's forward-designed slot (ROADMAP Phase 18, success criterion 1: the monthly
    report gains a physique section the weekly report structurally cannot carry). Registers a
    throwaway monthly-only section and asserts it appears for MONTHLY and not for WEEKLY --
    proving a future section is one template entry plus one builder, with no edit to any
    existing section."""
    marker = "## Throwaway monthly-only section"
    extended = (
        *reports_module._NARRATIVE_TEMPLATE,
        _NarrativeSection(marker, lambda report: ["- monthly only"], (ReportPeriod.MONTHLY,)),
    )
    monkeypatch.setattr(reports_module, "_NARRATIVE_TEMPLATE", extended)

    monthly = build_narrative(_report(period=ReportPeriod.MONTHLY))
    weekly = build_narrative(_report(period=ReportPeriod.WEEKLY))

    assert marker in monthly
    assert "- monthly only" in monthly
    assert marker not in weekly
    # The restriction must SKIP the section, never render an empty heading for it.
    assert "- monthly only" not in weekly
```

   `monkeypatch.setattr` on the module object requires the module itself, so add
   `from app.analytics import reports as reports_module` to the imports and reference
   `reports_module._NARRATIVE_TEMPLATE` in both the tuple splat and the patch target.
   `build_narrative` must therefore read the module-global at call time — it does, since the
   loop references `_NARRATIVE_TEMPLATE` by name rather than capturing it in a default
   argument. If the patch does not take effect, that is the bug to fix, not the test.

4. Re-run the Task 1 golden tests in the same run to confirm the monkeypatch is properly torn
   down and the shipped narrative is unchanged.

Do NOT add a physique section, a `PhysiqueSection` type, or any `physique` field — Phase 18 owns
that entirely. This task only proves the slot exists.
  </action>
  <verify>
    <automated>uv run pytest backend/tests/test_analytics_reports.py backend/tests/test_analytics_isolation.py backend/tests/test_mcp_isolation.py -m "not integration" -q && uv run ruff check backend/tests/test_analytics_reports.py</automated>
  </verify>
  <done>Both new tests pass; the golden tests still pass in the same session (clean monkeypatch teardown); no physique-specific code exists anywhere in this change.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| `build_narrative` → MCP response → Claude | The narrative is the one field `docs/coaching-instructions.md` instructs Claude to quote directly; whatever it renders is read as fact by the coach |
| Committed golden fixture → test assertion | The fixture is the only artifact proving output did not change; a corrupted fixture silently disarms the guard |

No new external input, no new network or database surface: `build_narrative` is pure, takes an
already-composed `ReportResult`, and this change adds no dependency.

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-QT-01 | Tampering | `build_narrative` output changing during the restructure | mitigate | Task 1 captures the pre-refactor output as a committed golden for both periods; Task 2 must reproduce it byte for byte, and the existing banned-token and numeric-provenance tests run unchanged |
| T-QT-02 | Tampering | Golden fixture corrupted by the `trailing-whitespace` / `end-of-file-fixer` pre-commit hooks | mitigate | Task 1's generator asserts no narrative line carries trailing whitespace before writing, and appends exactly one newline that the test accounts for explicitly |
| T-QT-03 | Information disclosure | A new section builder leaking a value the structured fields do not carry | mitigate | Builders move existing lines verbatim and add none; `test_every_number_in_the_narrative_is_already_in_the_structured_fields` and the banned-token scan both run against the refactored output |
| T-QT-04 | Elevation of privilege | Template mechanism introducing a callable-from-data path (arbitrary builder injection) | accept | `_NARRATIVE_TEMPLATE` is a module-level constant of statically-declared private functions; no builder is ever resolved from request data, config or user input |
| T-QT-05 | Repudiation | Determinism lost via unordered iteration in a builder | mitigate | Builders iterate the same already-ordered model fields as today; `test_the_narrative_is_byte_identical_across_calls` and the golden comparison both cover it |
</threat_model>

<verification>
Full fast suite, from the repo root, to confirm nothing outside this module moved:

```bash
uv run pytest -m "not integration and not realfile" -q
uv run ruff check backend/app/analytics/reports.py backend/tests/test_analytics_reports.py
uv run ruff format --check backend/app/analytics/reports.py backend/tests/test_analytics_reports.py
uv run mypy backend/app/analytics/reports.py
```

Manual confirmations before the summary:
1. `git diff backend/app/mcp/` is empty — the MCP layer's call site is untouched.
2. `git diff` on `backend/tests/test_analytics_reports.py` shows ADDITIONS only for the
   pre-existing tests; no assertion was relaxed, renamed or deleted.
3. `grep -rni physique backend/app backend/tests` returns nothing from this change.
</verification>

<success_criteria>
- `build_narrative` renders byte-identical output to the pre-refactor implementation for both
  `ReportPeriod.WEEKLY` and `ReportPeriod.MONTHLY`, proven by committed golden fixtures
- The seven sections are declared once, in order, as `_NARRATIVE_TEMPLATE`; `build_narrative`'s
  body is the title plus a loop
- A section can be restricted to one `ReportPeriod` and is skipped for the other, proven by a
  passing test that registers a throwaway monthly-only section
- Adding Phase 18's physique section will require one template entry and one builder function,
  with no edit to any existing section
- No new third-party dependency; `build_narrative` stays pure and synchronous
- Every pre-existing test in `test_analytics_reports.py` passes unedited; `test_analytics_isolation.py`
  and `test_mcp_isolation.py` pass; ruff, ruff-format and mypy are clean
- No physique implementation of any kind is present
</success_criteria>

<output>
After completion, create
`.planning/quick/260907-dsu-formalize-weekly-monthly-report-narrativ/260907-dsu-SUMMARY.md`.

Record for Phase 18 specifically: the exact template entry shape a monthly-only section must
use, and the name of the test that proves the slot works.
</output>
