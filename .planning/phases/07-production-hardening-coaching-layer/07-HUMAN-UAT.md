---
status: resolved
phase: 07-production-hardening-coaching-layer
source: [07-VERIFICATION.md]
started: 2026-09-01T14:21:03Z
updated: 2026-09-01T14:30:00Z
---

## Current Test

[complete]

## Tests

### 1. Coaching UAT staleness/sparsity guardrail (ROADMAP Phase 7 criterion #4, second clause)
expected: With `docs/coaching-instructions.md` loaded in a Claude Project attached to the BRETT connector, a question that genuinely outruns the available data or targets a sparse slice (e.g. the plan's fallback freshness question — "When was my data last synced, and how confident should I be in the last 4 weeks?" — or a question about a rarely-trained exercise/muscle group) makes Claude surface the coverage/freshness limitation unprompted, citing a specific field (`coverage.earliest_data_at`, `coverage.insufficient_data`, `coverage.sessions_in_window`, or `freshness.resources`), before giving a verdict.
result: passed

The original 52-week window probe couldn't force this (synced history exceeds 52 weeks, and `MAX_WEEKS=52` is a hard schema cap so no larger window can be requested). Ran the plan's own fallback probe instead: "When was my data last synced, and how confident should I be in the last 4 weeks?" Claude cited the exact sync timestamp (freshness), `coverage.sessions_in_window` (9), and per-muscle `insufficient_data` flags (traps), explicitly distinguishing "sync is current" from "trend sample is thin" — the exact behavior the coaching document requires. Full transcript recorded in `07-COACH-VERIFICATION.md` § Follow-up: Freshness Probe.

## Summary

total: 1
passed: 1
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps
