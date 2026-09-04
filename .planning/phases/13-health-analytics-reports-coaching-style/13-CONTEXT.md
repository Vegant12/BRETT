# Phase 13: Health Analytics, Reports & Coaching Style - Context

**Gathered:** 2026-09-04
**Status:** Ready for planning

<domain>
## Phase Boundary

Claude can answer activity and nutrition questions from real Apple Health data over
configurable windows, and one call each returns a complete weekly or monthly report
(training + strength + measurements + nutrition + program context + trends), inside measured
latency/size budgets. A real Claude scheduled-task run against the report tools is verified
(working, or broken with a documented, non-blocking workaround), and
`docs/coaching-instructions.md` is rewritten to cover the full v2.0 tool registry while
becoming more concise, not less.

This phase does NOT include: further Apple Health ingest changes (Phase 8, done), the
historical backfill (Phase 9, done), any change to strength classification (Phase 10, done),
body-measurement trend analytics (Phase 11, done, reused here as an input), or any change to
program-switching mechanics (Phase 12, done, reused here as an input).

</domain>

<decisions>
## Implementation Decisions

### Report Composition & Anchoring

- **D-01:** Reports use closed-period anchoring for their training/strength/measurement
  figures (Monday–Sunday for the weekly report, calendar month for the monthly one), with the
  existing anchored-on-today recomposition verdict carried alongside, clearly labelled as a
  different anchor from the closed-period numbers. Do NOT add an `anchor_day` parameter to
  `get_body_weight_trend`/`get_recomposition_status` — their docstrings currently argue against
  a caller-supplied end date, and that reasoning stands. Matches ARCHITECTURE.md's option (a)
  recommendation.
- **D-02:** Report body reuses `fitness_get_training_summary`'s selected-field spine (weekly
  volume, per-muscle rollup, recomposition status) as its base, and adds NARROW extras: PR and
  plateau *highlights* (not the full lists `fitness_get_personal_records`/`fitness_get_plateaus`
  already return), a body-measurement trend summary, a nutrition trend summary, and active
  training-program context. Per PITFALLS #18: narrow extras over full composition, reusing the
  spine rather than composing every full analytics result and trimming afterwards.
- **D-03:** No backend-computed "recommendations" field. The report tool returns composed DATA
  only, exactly like every other analytics tool — no arithmetic-adjacent judgment calls baked
  into the payload. Claude synthesizes the actual recommendation text using the returned data
  and `docs/coaching-instructions.md`'s existing decision framework.
- **D-04:** One composer function serves both report tools; a period/window parameter
  distinguishes weekly (the current week) from monthly (the current calendar month) — same
  sections in both, not a different emphasis per period. Matches FEATURES.md: "once weekly
  exists, monthly is a window parameter... do not build two composers."
- **D-14:** `fitness_get_monthly_report`'s JSON response carries one additional field: a
  markdown-formatted narrative string, generated server-side by a deterministic template (not
  free-form/AI-authored text) that restates the SAME composed data already in the structured
  fields — headings, numbers, existing trend/verdict labels (e.g. `RecompositionStatus`,
  `TrendVerdict`) — with NO recommendation language or new editorializing, consistent with D-03.
  `fitness_get_weekly_report` does NOT get this field — monthly only, per explicit request.
  Deterministic and testable like every other response shape in this codebase; exact heading
  structure is planning's call.

### Activity & Nutrition Trend Design

- **D-05:** Activity trend analytics (steps, active/basal energy, distance, flights) use
  rolling 7/14/30-day averages + rate of change, following `bodyweight.py`'s shape — NOT
  `body_measurements.py`'s latest-vs-90-days shape. Activity data arrives daily from the phone
  (unlike sparse circumference readings), and HEALTH-12's own wording ("7/14/30-day windows,
  following the existing trend-analytics pattern") names the daily-measured-data pattern.
- **D-06:** Nutrition trend analytics (calories + 6 macros) use the SAME rolling-average design
  as activity for NUTR-04's "daily/weekly average calories and macros" wording. **Explicit
  research gap, not a guess dressed as a decision** (same discipline as Phase 8's D-05): the
  exact per-window coverage floors (how many logged days a window needs before it's trustworthy)
  must be checked against real synced nutrition data during planning/research, the way BODY-05
  measured real circumference coverage before committing to its shape — nutrition logging
  consistency has not been measured yet for this phase.
- **D-07:** Activity gets its own dedicated MCP tool (`fitness_get_activity_trend`), matching
  the one-tool-per-analytics-slice pattern already used for volume, frequency, body-weight
  trend, body-measurement trend, and now nutrition (NUTR-06). A bare "how active have I been?"
  question needs a direct answer path, not only a full report call.
- **D-08:** The nutrition-trend tool returns ONE response with all 7 values (calories +
  protein + carbs + fat + fiber + sugar + sodium) always — no metric-selector parameter, unlike
  `fitness_get_body_measurement_trend`'s `StrEnum` selector. Nutrition values are naturally
  asked about together ("how's my nutrition been?"), unlike body measurements' 16 largely
  independent columns.

### Coaching Doc Rewrite Strategy

- **D-09:** `docs/coaching-instructions.md` is rewritten from scratch against the final v2.0
  tool registry — not incrementally edited — sequenced after every new v2.0 tool exists (this
  phase is last by construction). Per PITFALLS #19's explicit recommendation. Current doc is
  7,934 of the hard 9,000-character ceiling (`test_coaching_doc.py::_PASTE_CEILING_CHARS`) and
  must gain activity/nutrition/report tool documentation while becoming MORE concise — an
  append-and-trim approach was rejected as unlikely to reach a genuinely tighter document.
- **D-10:** If the rewritten doc still doesn't fit under 9,000 characters, moving overflow into
  the server's `_INSTRUCTIONS` string (`server.py:76-86`) is an acceptable LAST-RESORT belt —
  but only for genuinely optional context, never anything an answer's correctness depends on,
  since whether Claude's custom connector actually injects `instructions` into the model's
  system prompt is UNVERIFIED. Prefer fitting entirely under 9,000 chars; do not raise
  `_PASTE_CEILING_CHARS`.
- **D-11:** Conciseness (COACH-02) is made concrete via: (a) explicit answer-length guidance
  building on the doc's existing "Prefer the smallest set of numbers that answers the question"
  line, (b) tightened tool-mapping table phrasing, and (c) a shortened "Example questions"
  section keeping only entries that add real guidance beyond what the table already states.

### Scheduled-Task Verification & Fallback

- **D-12:** The RPT-03 scheduled-task spike runs on Claude Desktop — the client where the
  existing verified coaching Project (Phase 7) already lives, and which the user actually uses.
  This is a human-gated step only the user can perform (like Phase 8/9's device-verification
  checkpoints) — a real scheduled task must be created against BRETT's live connector, not
  simulated.
- **D-13:** The documented community workaround (a preamble instructing the scheduled prompt to
  delegate to a subagent, per the closed "not planned" GitHub issues) is added to
  `docs/coaching-instructions.md` ONLY IF the live spike actually reproduces the "tool schemas
  never reach the agent" failure — not proactively. Conserves the tight character budget (D-09)
  for a workaround that may not even be needed against this specific setup. If the spike
  succeeds outright, no preamble is added. If it fails and stays unfixable within this phase,
  RPT-03 is still satisfied by documenting the failure and the on-demand fallback (already
  decided at the PROJECT.md level: reports stay on-demand-only, not blocking the phase).

### Claude's Discretion

- **Partial data availability in reports** — what a report returns when one input source is
  missing entirely (e.g. no Apple Health data has ever synced) or sparse for the window (e.g. a
  lapsed nutrition-logging stretch). Follow the established `safe_tool`/`data_available`
  degradation pattern `fitness_get_training_summary` already uses — degrade gracefully and flag
  what's missing, do not refuse the whole call over one missing section. Not discussed in depth
  because the existing degradation pattern already covers the shape of the answer.
- **Report freshness envelope's exact resource list** — which `(provider, resource)` pairs a
  report's `freshness` field names, given it reads both Hevy and Apple Health data. Follow the
  existing `build_freshness` pairs pattern (Phase 8's D-03: `apple_health`/`activity` and
  `apple_health`/`nutrition` as separate resources) and include every resource the report
  actually touches.
- **Whether the report's activity/nutrition sections share the report's own closed-period
  window or use their own independent rolling windows** — planning's call; avoid producing two
  sections of the same report that visibly disagree about what "this week" means.
- **Exact `MAX_REPORT_WEEKS`/`MAX_REPORT_*` budget cap numbers** — measured against the real
  composed payload during planning/implementation, per PITFALLS #18, not estimated here.
- **Exact markdown narrative template headings/structure (D-14)** — follow the tool-mapping
  table's existing terse style; content is fixed (D-14), exact formatting is not.
- **Nutrition coverage floors (D-06)** — the specific per-window measured-day thresholds, once
  research measures real coverage.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` §"Activity Analytics" (HEALTH-12), §"Nutrition" (NUTR-04,
  NUTR-06), §"Reports" (RPT-01, RPT-02, RPT-03), §"Coaching Response Style" (COACH-02, COACH-03)
- `.planning/ROADMAP.md` §"Phase 13: Health Analytics, Reports & Coaching Style" — goal, success
  criteria, and the four planning notes (run the scheduled-task spike first; `reports.py` owns
  composition never arithmetic; closed-period anchoring called out as needing an explicit
  phase-context decision — resolved above as D-01; measured, not estimated, budgets; activity
  data as recomposition context never a classifier input)
- `.planning/PROJECT.md` §Active — the HEALTH-12/NUTR-04/NUTR-06/RPT-01–03/COACH-02 bullets, and
  the "Weekly/monthly reports" Key Decisions row (on-demand MCP tools driven by Claude's own
  scheduled-tasks feature, not a BRETT-side scheduler)

### Research (2026-09-02) — read in full; note what's superseded
- `.planning/research/PITFALLS.md` #17 (scheduled-task client capability is documented-broken,
  closed "not planned" — the spike's whole rationale), #18 (report tool fan-out blows both the
  context and cold-start budget — the "narrow extras over full composition" guidance behind
  D-02), #19 (the coaching doc's character-budget crunch — the numbers and rewrite
  recommendation behind D-09/D-10/D-11)
- `.planning/research/ARCHITECTURE.md` §"4. Health analytics + reports" (the closed-period
  anchoring decision table, options (a)/(b), recommendation (a) — this is D-01) and its
  Anti-Pattern #9 ("report tools as a fourth copy of the analytics arithmetic" — behind D-02/D-03)
- `.planning/research/FEATURES.md` — report-tool table-stakes entries ("one composer, two
  windows" — behind D-04)
- `.planning/research/SUMMARY.md` — phase-5-of-5 framing, confirms reports/coaching-style is
  last by construction

  **Superseded/stale parts of this research, do NOT follow:** `ARCHITECTURE.md`'s component
  table and sequencing section were written 2026-09-02, before four rounds of scope reversal.
  Ignore: `progression.py` becoming "max-weight primary" (reversed, Phase 10 — e1RM still
  classifies, max weight is display-only); `training_programs`/mutable-column framing and a
  program-independent shared label matrix (reversed, Phase 12 — append-only
  `user_program_history` plus THREE separate explicit per-program matrices, not one shared
  abstraction); any `body_measurements` third-source or manual-entry framing (dropped, Phase 11);
  a separate `health_workouts` table (never built, Phase 8 D-02). This research also predates
  nutrition being pulled into v2.0 scope entirely (Phase 8's D-05 already flags this) — it has NO
  coverage of nutrition trend design, which is why D-06 above is flagged as a fresh research gap
  rather than assumed from this document.

### Superseded/resolved context from prior phases
- `.planning/phases/08-apple-health-nutrition-ingest/08-CONTEXT.md` — D-03 (the two-resource
  `apple_health`/`activity` + `apple_health`/`nutrition` freshness split this phase's reports
  read) and D-05 (the nutrition-wire-format research-gap precedent D-06 above follows)
- `.planning/phases/12-training-programs-confirm-gated-write-tool/12-CONTEXT.md` — D-04–D-06
  (the three explicit per-program label matrices — reports surface `RecompositionResult`'s
  active-program field verbatim, D-10's straddle caveat, no new logic needed here)

### Code this phase touches or must not regress
- `backend/app/mcp/tools/summary.py` — the model to copy for `mcp/tools/reports.py`: one
  read-only transaction around every composed call, a `_degraded_*` factory for `safe_tool`,
  verbatim-echoed disclaimer fields
- `backend/app/mcp/tools/_common.py` — `MAX_SUMMARY_WEEKS` and the budget-cap block (add
  `MAX_REPORT_*` here, per PITFALLS #18), `read_only_session`, `safe_tool`, `truncate`,
  `window_from_weeks`
- `backend/app/analytics/bodyweight.py` — the rolling-average/floor/smoothed-rate shape D-05/D-06
  follow for activity and nutrition trends
- `backend/app/analytics/body_measurements.py` — the shape explicitly NOT followed for activity/
  nutrition (D-05/D-06); still the precedent for how a "Claude's Discretion" per-metric coverage
  floor gets documented when research measures it
- `backend/app/db/models/health.py` — `HealthDailyMetric`, the `(user, source, metric,
  source_name, local_day)` natural key activity/nutrition analytics read
- `backend/app/integrations/health_auto_export/registry.py` — `METRIC_REGISTRY`, the 12 wire
  metric names and canonical units (`kcal`, `g`, `mg`, `km`, `count`) analytics must read from,
  never re-derive
- `backend/app/analytics/metadata.py` — `build_freshness`, `FRESHNESS_RESOURCES_BODY`-style
  resource-list constants; the report's freshness envelope composes from here
- `backend/app/analytics/recomposition.py`, `backend/app/analytics/schemas.py` —
  `RecompositionResult`'s active-program and straddle-caveat fields (Phase 12), read verbatim by
  the report, not re-derived
- `docs/coaching-instructions.md` — the document being rewritten (D-09); read it in full before
  drafting the replacement, not just this context's summary of it
- `backend/tests/test_coaching_doc.py` — `_PASTE_CEILING_CHARS = 9_000`, the bidirectional
  drift guard (every `fitness_*` token must exist in the live registry and vice versa) the
  rewritten doc must still pass

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `fitness_get_training_summary`'s exact composition shape (one read-only transaction, selected
  fields not full results, a `_degraded_*` factory) — the direct template for the report tools.
- `analytics/bodyweight.py`'s rolling-average + floor + smoothed-rate-of-change fold — the
  direct template for `analytics/health.py`'s activity and nutrition trend functions.
- `_common.truncate()` — reuse for any list inside the report (PR/plateau highlights) so a cap
  is never silent.
- `RecompositionResult`'s active-program and straddle-caveat fields (Phase 12) — the report
  surfaces these verbatim rather than re-querying program state itself.

### Established Patterns
- One computation, two consumers: `analytics/reports.py` composes, never computes — the same
  rule `recomposition.py` follows composing `bodyweight` + `progression` + `volume`.
- One-tool-per-analytics-slice: every new analytics capability in this codebase gets its own
  dedicated MCP tool (volume, frequency, body-weight trend, body-measurement trend, and now
  activity, nutrition) — D-07 extends this rather than breaking it.
- Measured, not estimated, budgets: every `MAX_*` cap in `_common.py` exists because a real
  payload was measured against it, never guessed in advance.

### Integration Points
- `mcp/tools/reports.py` → `analytics/reports.py` → existing `analytics/*` functions
  (`volume`, `frequency`, `recomposition`, `records`, `body_measurements`, and the new
  `health.py`) — composition only, no new arithmetic.
- `analytics/health.py` → `db/models/health.HealthDailyMetric` — direct read, same guards as
  every other analytics module (no `float`, no `text()`, no writes).

</code_context>

<specifics>
## Specific Ideas

- The user specifically wants `fitness_get_monthly_report` to return a markdown-formatted
  narrative report (D-14) — not a file BRETT writes to disk, but a string field in the same
  structured JSON response every other tool returns, so it costs no new infrastructure and stays
  read-only. Weekly report stays pure structured JSON.
- The narrative field restates the same data already in the structured fields — no new
  recommendation content, consistent with D-03's "no backend recommendations field" decision.

</specifics>

<deferred>
## Deferred Ideas

- **BRETT writing an actual `.md` file to disk/storage** — considered and declined (D-14) in
  favor of a markdown string field in the existing JSON response. Would require new write/
  storage infrastructure that conflicts with "MCP otherwise stays read-only" and the explicit
  out-of-scope note against BRETT-side report delivery infrastructure. Not pursued.
- **Structured backend-computed recommendation flags** — considered and declined (D-03) in
  favor of Claude synthesizing recommendations from returned data.
- **An `anchor_day` parameter on `get_body_weight_trend`/`get_recomposition_status`** —
  considered and declined (D-01) in favor of closed-period figures with today's verdict labelled
  alongside.
- **A metric-selector parameter on the nutrition-trend tool** — considered and declined (D-08)
  in favor of always returning all 7 values in one response.
- **Different section emphasis for the monthly report vs. the weekly one** — considered and
  declined (D-04) in favor of one composer function with a window parameter only.
- **Proactively adding the scheduled-task subagent-delegation workaround** regardless of the
  spike's outcome — considered and declined (D-13) in favor of adding it only if the live spike
  actually reproduces the failure.
- Three additional gray areas were surfaced (partial data availability in reports, the report's
  multi-provider freshness resource list, whether activity/nutrition sections share the report's
  closed-period window) but the user chose not to discuss them further — they're captured under
  Claude's Discretion above rather than lost.

</deferred>

---

*Phase: 13-health-analytics-reports-coaching-style*
*Context gathered: 2026-09-04*
