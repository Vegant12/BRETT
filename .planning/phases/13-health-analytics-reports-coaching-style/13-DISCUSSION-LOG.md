# Phase 13: Health Analytics, Reports & Coaching Style - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-04
**Phase:** 13-health-analytics-reports-coaching-style
**Areas discussed:** Report composition & anchoring, Activity & nutrition trend design,
Coaching doc rewrite strategy, Scheduled-task verification & fallback, Monthly report markdown
form (user-raised)

---

## Report Composition & Anchoring

| Option | Description | Selected |
|--------|-------------|----------|
| Closed-period + labelled today's verdict | Closed-period Mon–Sun/calendar-month figures; today's recomposition verdict carried alongside, clearly labelled | ✓ |
| Add optional anchor_day parameter | Real change to two functions whose docstrings currently forbid a caller-supplied end date | |

**User's choice:** Closed-period + labelled today's verdict (D-01)

| Option | Description | Selected |
|--------|-------------|----------|
| Summary spine + PRs + plateaus + measurements + nutrition | Reuse training_summary's spine, add narrow highlights, per PITFALLS #18 | ✓ |
| Training-only (no nutrition/measurements) | Smallest, cheapest payload; Claude calls other tools separately | |

**User's choice:** Summary spine + narrow extras (D-02)

| Option | Description | Selected |
|--------|-------------|----------|
| No recommendations field — Claude synthesizes | Report returns data only; Claude writes the advice | ✓ |
| Structured recommendation flags | Backend computes classification flags | |

**User's choice:** No recommendations field (D-03)

| Option | Description | Selected |
|--------|-------------|----------|
| Same sections, wider window only | One composer, a window parameter distinguishes weekly/monthly | ✓ |
| Different section emphasis | Monthly drops/adds sections vs. weekly | |

**User's choice:** Same sections, window parameter only (D-04)

**Notes:** All four recommended options accepted without modification.

---

## Activity & Nutrition Trend Design

| Option | Description | Selected |
|--------|-------------|----------|
| Rolling averages, bodyweight.py-style | Daily-measured-data shape, matches HEALTH-12's wording | ✓ |
| Latest-vs-N-days-ago, body_measurements.py-style | Built for sparse, every-few-weeks data | |

**User's choice:** Rolling averages for activity (D-05)

| Option | Description | Selected |
|--------|-------------|----------|
| Same rolling-average design as activity | Matches NUTR-04's wording | ✓ |
| Flag as research gap, decide floor at planning time | Lock shape now, confirm coverage floors later | |

**User's choice:** Same rolling-average design as activity, WITH the coverage-floor caveat carried into the decision as an explicit research gap (D-06) — both aspects of the recommended option were kept.

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — dedicated fitness_get_activity_trend tool | Matches one-tool-per-analytics-slice pattern | ✓ |
| No — activity surfaces only through reports | Saves a tool, but no direct answer path | |

**User's choice:** Dedicated activity-trend tool (D-07)

| Option | Description | Selected |
|--------|-------------|----------|
| One response, all 7 values always | Calories + 6 macros naturally asked about together | ✓ |
| Metric-selector parameter, one macro at a time | Matches body-measurement-trend's selector pattern | |

**User's choice:** All 7 values, one response (D-08)

---

## Coaching Doc Rewrite Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Full rewrite from scratch | PITFALLS #19's explicit recommendation | ✓ |
| Incremental edit — append + trim | Lower risk, harder to hit a genuinely tighter doc | |

**User's choice:** Full rewrite from scratch (D-09)

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, as a last-resort belt, never load-bearing | Only for genuinely optional context | ✓ |
| No — stay under 9,000 chars no matter what | Simpler mental model, cut scope instead | |

**User's choice:** Last-resort belt only (D-10)

| Option | Description | Selected |
|--------|-------------|----------|
| Explicit answer-length guidance + trim examples/tables | Builds on existing "smallest set of numbers" line | ✓ |
| Just tighten wording, keep structure/examples | Less room for mandatory new content | |

**User's choice:** Explicit guidance + trims (D-11)

---

## Scheduled-Task Verification & Fallback

| Option | Description | Selected |
|--------|-------------|----------|
| Claude Desktop | Where the existing verified coaching Project already lives | ✓ |
| Claude mobile or web | Whichever client the user actually uses day-to-day | |

**User's choice:** Claude Desktop (D-12)

| Option | Description | Selected |
|--------|-------------|----------|
| Only if the spike reproduces the failure | Don't spend tight character budget preemptively | ✓ |
| Add it proactively either way | Two closed "not planned" issues is decent evidence | |

**User's choice:** Only if reproduced (D-13)

---

## Monthly Report Markdown Form (user-raised, not from the original gray-area set)

The user asked: "I would like monthly report to be generated as a markdown file."

| Option | Description | Selected |
|--------|-------------|----------|
| A markdown string field in the JSON response | Still read-only, no new infrastructure | ✓ |
| BRETT writes an actual .md file somewhere | New write/storage infrastructure | |

**User's choice:** Markdown string field (D-14, part 1)

| Option | Description | Selected |
|--------|-------------|----------|
| Monthly only, as described | Matches the user's exact request | ✓ |
| Both weekly and monthly | Broader consistency | |

**User's choice:** Monthly only (D-14, part 2)

| Option | Description | Selected |
|--------|-------------|----------|
| Data restated only — no editorializing | Deterministic template, consistent with D-03 | ✓ |
| Some interpretive framing OK | Narrates existing classifications in prose | |

**User's choice:** Data restated only (D-14, part 3)

---

## Claude's Discretion

- Partial data availability / degradation behavior in reports (follow existing `safe_tool`
  pattern)
- Exact report freshness envelope resource list across the two providers
- Whether activity/nutrition report sections share the closed-period window or use independent
  rolling windows
- Exact `MAX_REPORT_*` budget cap numbers (measured, not estimated)
- Exact markdown narrative template headings/structure
- Nutrition coverage floors, once research measures real data

## Deferred Ideas

- BRETT writing an actual `.md` file to disk/storage (declined — new infrastructure, conflicts
  with read-only-MCP constraint)
- Structured backend-computed recommendation flags (declined — Claude synthesizes instead)
- `anchor_day` parameter on `get_body_weight_trend`/`get_recomposition_status` (declined)
- Metric-selector parameter on the nutrition-trend tool (declined)
- Different section emphasis for monthly vs. weekly report (declined)
- Proactively adding the scheduled-task subagent-delegation workaround regardless of spike
  outcome (declined)
- Three further gray areas were surfaced (partial data availability, multi-provider freshness
  resource list, shared-vs-independent report windows) but the user chose not to discuss them
  further in this session — see Claude's Discretion in CONTEXT.md.
