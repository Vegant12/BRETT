# Quick Task 260907-dsu: Formalize weekly/monthly report narrative as a reusable section template - Context

**Gathered:** 2026-09-07
**Status:** Ready for planning

<domain>
## Task Boundary

`build_narrative()` in `backend/app/analytics/reports.py` already renders both
`fitness_get_weekly_report` and `fitness_get_monthly_report` through one deterministic function
with the same section order (Training, Strength, Body, Nutrition, Activity, Program and
recomposition, Data quality) — the two report types are already structurally identical today.
The user wants this restructured from one long inline function into an explicit, reusable
"template" of named sections, so the shared contract is visible in the code shape rather than
only enforced by convention/tests. This is a refactor of `build_narrative`'s internal structure
— it does not change what any report currently renders (weekly/monthly output must stay
byte-identical to today's for identical input data), and it must forward-design a slot for
Phase 18's upcoming monthly-only physique section.

</domain>

<decisions>
## Implementation Decisions

### What "adjustment" means
- Formalize the template as reusable structure: refactor `build_narrative`'s inline f-string
  list into an explicit named-sections template (e.g. a list of section-builder
  functions/objects) so weekly and monthly visibly share one contract instead of one long
  function body.
- This is NOT a content change (no new/reordered/renamed sections) and NOT primarily a test-only
  change — the structure of the code itself must change to make the shared template explicit.

### Phase 18 physique-section exception
- Design the template now to support an optional, monthly-only section (the physique section
  Phase 18 will add to `fitness_get_monthly_report` per `ROADMAP.md`'s Phase 18 success
  criteria: "a physique section... populated via a one-line period conditional inside
  compose_report — `physique: PhysiqueSection | None` on `ReportResult`... while
  `fitness_get_weekly_report`'s response has no `physique` attribute at all").
- The template mechanism should let a section be conditionally included per `ReportPeriod`
  (e.g. monthly-only) without Phase 18 having to restructure the template again — it only needs
  to add its own section entry.
- Do NOT implement the physique section itself in this quick task — that's Phase 18's scope.
  This task only ensures the template *shape* has room for a period-conditional section.

### Claude's Discretion
- Exact mechanism (list of `(name, builder_fn)` tuples, small dataclass, ordered dict, etc.) —
  pick whatever fits the existing deterministic/no-templating-library constraint documented in
  `build_narrative`'s own docstring (D-14: "No third-party text-templating library anywhere in
  this codebase").
- Whether section builder functions live as private module-level functions or nested closures —
  pick whichever keeps `test_analytics_reports.py`'s existing assertions (banned-token scan,
  numeric-provenance check) working unchanged against the joined output.
- Naming of the template/section abstraction.

</decisions>

<specifics>
## Specific Ideas

No specific code shape was dictated beyond the constraints above — open to a straightforward
Python approach (e.g. `_SECTIONS: list[tuple[str, Callable[[ReportResult], list[str]]]]`) as long
as:
1. Weekly and monthly reports for identical input data render byte-identical output to today's
   `build_narrative` (this is a refactor, not a behavior change).
2. A future section can declare itself monthly-only (or weekly-only) and be skipped for the
   other period without editing unrelated section code.
3. `build_narrative` stays pure/synchronous with no new dependency.

</specifics>

<canonical_refs>
## Canonical References

- `backend/app/analytics/reports.py` — current `build_narrative` implementation and its D-14
  docstring (no-templating-library constraint, determinism/no-recommendation-language rules).
- `.planning/ROADMAP.md` — Phase 18: "Monthly Report Physique Integration" success criteria,
  specifically the `physique: PhysiqueSection | None` / weekly-has-no-`physique`-attribute
  requirement this template must be able to accommodate later.
- `backend/tests/test_analytics_reports.py` — existing narrative assertions (banned-token scan,
  numeric-provenance check) that must keep passing unchanged.

</canonical_refs>
