---
status: partial
phase: 07-production-hardening-coaching-layer
source: [07-VERIFICATION.md]
started: 2026-09-01T14:21:03Z
updated: 2026-09-01T14:21:03Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. Coaching UAT staleness/sparsity guardrail (ROADMAP Phase 7 criterion #4, second clause)
expected: With `docs/coaching-instructions.md` loaded in a Claude Project attached to the BRETT connector, a question that genuinely outruns the available data or targets a sparse slice (e.g. the plan's fallback freshness question — "When was my data last synced, and how confident should I be in the last 4 weeks?" — or a question about a rarely-trained exercise/muscle group) makes Claude surface the coverage/freshness limitation unprompted, citing a specific field (`coverage.earliest_data_at`, `coverage.insufficient_data`, `coverage.sessions_in_window`, or `freshness.resources`), before giving a verdict.
result: [pending]

Context: The original UAT (plan 07-10) tried to force this with "compare my training over the last 52 weeks," but the tester's actual synced history (327 workouts, ~80 weeks of data) exceeds that window, so Claude answered normally with no data gap to flag — this is not a failure, the guardrail was simply never exercised. `MAX_WEEKS=52` is a hard schema-enforced cap (`backend/app/mcp/tools/_common.py`), so no larger `weeks` value can be requested to force a gap; a different kind of probe (freshness-focused or sparsity-focused) is needed instead.

## Summary

total: 1
passed: 0
issues: 0
pending: 1
skipped: 0
blocked: 0

## Gaps
