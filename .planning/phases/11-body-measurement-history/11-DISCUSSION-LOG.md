# Phase 11: Body Measurement History - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-03
**Phase:** 11-body-measurement-history
**Areas discussed:** Write path & CLI UX (superseded by scope reversal), Same-day manual
re-entry semantics (dropped — moot), Source precedence ordering (dropped — moot), Circumference/
composition trend shape (BODY-05)

---

## Write path & CLI UX (pre-reversal)

Asked before the scope reversal, on the assumption that manual entry (BODY-03) was in scope.

| Question | Options presented | Selected |
|---|---|---|
| Write path | CLI only (recommended) / New HTTP route | User did not pick either — asked whether Hevy's app already captures this data instead |
| Single-entry flag design | One flag per metric (recommended) / Generic `--field name=value` | One flag per metric |
| Bulk import file format | CSV (recommended) / JSON | CSV |
| Validation | Basic sanity checks (recommended) / No validation | Basic sanity checks |

**User's response to the write-path question:** "Manual measurements are recorded through Hevy,
is it not possible to obtain data through the app?" — this triggered the scope-reversal
discussion below rather than a direct pick.

**Outcome:** These three answered sub-questions (flag design, bulk format, validation) are
preserved for the record but are **moot** — manual entry was dropped from scope entirely before
any of them could matter. See "Scope Reversal" below.

---

## Scope Reversal — Manual entry dropped

Claude explained: Hevy's app already supports logging every one of the 17 body-measurement
fields, and BRETT already syncs them automatically (`backend/app/integrations/hevy/body.py`).
The `source='manual'` column exists for data that never touches Hevy — historical backfill,
corrections, or a metric tracked outside Hevy entirely.

**User's clarifying reply:** "I dont need manual entry just need to get normal hevy measurements
into BRETT, and allow Claude to access those measurement data."

| Question | Options presented | Selected |
|---|---|---|
| Drop BODY-03/BODY-04 entirely, scope down to BODY-05 only? | Yes, drop manual entry (recommended) / Keep BODY-03/04, but low priority | Yes, drop manual entry |

**Notes:** This mirrors Phase 10's own scope-reversal precedent (`10-CONTEXT.md`) — a major
narrowing decided mid-discussion, with ROADMAP.md/REQUIREMENTS.md/PROJECT.md rewritten in the
same session to match rather than left to drift.

---

## Same-day manual re-entry semantics

**Not discussed** — dropped as moot once manual entry (BODY-03) was removed from scope. No
manual rows will ever be written, so there is no same-day conflict to resolve.

---

## Source precedence ordering

**Not discussed** — dropped as moot for the same reason. `_dedupe_by_day`'s existing alphabetical
ordering stays exactly as it is today (harmless, since `body_measurements` only ever has one
source, `'hevy'`).

---

## Circumference/composition trend shape (BODY-05)

| Question | Options presented | Selected |
|---|---|---|
| Calculation approach | Rolling averages, same shape as weight / Latest value + delta since earliest-in-window (recommended) | Latest value + delta since earliest-in-window |
| Coverage floors | New, lower floor for spot-check metrics (recommended) / Reuse existing 3/5/10 floors unchanged | New, lower floor for spot-check metrics |
| Architecture | One generic metric-parameterized function + tool (recommended) / Per-metric typed results | One generic metric-parameterized function + tool |
| Metric scope | All 16 non-weight columns (recommended) / A curated subset | All 16 non-weight columns |
| Comparison window width | 90 days (recommended) / 180 days / No fixed window (all-time earliest vs. latest) | 90 days |
| Staleness flag | Yes, flag stale latest readings (recommended) / No, just insufficient_data or a value | Yes, flag stale latest readings |

**Notes:** All six picks were the recommended option. Reasoning throughout: live data is sparse
(waist 15/123 days, fat%/lean-mass 0/123 days), so BODY-01's rolling-average design would almost
always return `insufficient_data` for these metrics — a different calculation shape was needed
for the tool to ever produce a real answer.

---

## Claude's Discretion

- Exact numeric floor(s) for the spot-check coverage check (calibrate in research/planning
  against live data).
- Exact MCP tool name and Pydantic response field names.
- Whether the new analytics function lives in `bodyweight.py` or a new sibling module.
- Whether aggregate responses (`fitness_get_training_summary`,
  `fitness_get_recomposition_status`) reference the new tool at all (leaning no).

## Deferred Ideas

- Manual measurement entry (BODY-03) and the per-column source-merge fix (BODY-04) — dropped
  entirely from v2.0, not deferred to a specific future phase. Would need re-evaluating from
  scratch if a real future need appears (e.g. a smart scale syncing only to Apple Health).
