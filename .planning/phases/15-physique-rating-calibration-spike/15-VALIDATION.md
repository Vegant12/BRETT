---
phase: 15
slug: physique-rating-calibration-spike
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-09-08
---

# Phase 15 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 + pytest-asyncio 1.4.0 (project-wide convention; not exercised by this phase — no code changes) |
| **Config file** | `backend/pyproject.toml` (unchanged by this phase) |
| **Quick run command** | N/A — no code to run |
| **Full suite command** | `uv run pytest` (should stay green, unchanged — a single confirmatory run at phase close proves this phase made zero backend code changes) |
| **Estimated runtime** | ~90 seconds (existing full suite; no new tests added by this phase) |

---

## Sampling Rate

- **After every task commit:** N/A — no code produced by this phase's tasks
- **After every plan wave:** `uv run pytest` — confirms this phase changed zero backend behavior (a full green run with no new/changed tests is itself the expected, correct outcome)
- **Before `/gsd-verify-work`:** `15-SPIKE-RESULT.md` must exist, be dated, state a verdict for both the blind and anchored conditions, quote raw model output, and state concrete named constants — this document's completeness IS the phase gate (ROADMAP success criterion #4: "Phase 16's observation schema is not started until this result exists")
- **Max feedback latency:** ~90 seconds (pytest confirmation run)

---

## Per-Task Verification Map

| Plan | Wave | Requirement | Objective | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|------|------|-------------|-----------|-----------------|-----------|-------------------|-------------|--------|
| 15-01 (collect) -> 15-02 (analyse) | 1 -> 2 | PHYS-12 | Spike measures rating movement (5 blind + 5-step anchored calls on a fixed photo-set), tests for a self-reinforcing ratchet, documents concrete recommended constants | Photo never persisted beyond the session scratchpad (D-02); no source path or photo description logged in committed artifacts | manual | N/A — human-gated by D-01's photo-attachment pause; the "test" is `15-SPIKE-RESULT.md`'s own evidentiary rigor (raw quotes, dated verdict, stated constants) reviewed by the plan-checker/verifier, not an automated assertion | N/A | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Plan/Wave assigned 2026-09-08. PHYS-12 spans both plans: `15-01-PLAN.md` (wave 1, `autonomous: false`) collects the evidence behind a `checkpoint:human-action` photo gate, and `15-02-PLAN.md` (wave 2, autonomous) analyses it and writes the constants. The two plans share `15-SPIKE-RESULT.md`, which is why they are in different waves rather than parallel. This phase has exactly one requirement and it is manual-only end to end, so there is nothing an automated Wave 0 stub could cover.*

*Per-plan automated checks do exist even though the requirement is manual: every task in both plans carries an `<automated>` verify that greps `15-SPIKE-RESULT.md` for the literal section headers, verdict tokens and filled-in constants, plus a leak guard (`grep -rE "^/Users/|^/home/|/private/tmp/claude-"` must return no match) and, in `15-02` Task 3, the `uv run pytest` / `git diff --name-only backend/` zero-code-change confirmation this document's Sampling Rate calls for.*

---

## Wave 0 Requirements

*None — existing test infrastructure covers all phase requirements. This phase adds zero backend code, so there is no automated coverage gap to seed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|--------------------|
| 5 independent blind repeat ratings of the same unchanged real photo-set, each an isolated `Task`-tool subagent call with fresh context (plan 15-01, Task 3) | PHYS-12 | Human-gated: requires the user's own real progress photos, attached mid-execution via a `checkpoint:human-action` pause (D-01); no automated substitute exists for measuring how a live Claude call actually rates a real photo | At the plan's photo-attachment checkpoint, the user provides an absolute path to the photo(s) in this session's private scratchpad. The plan then issues 5 separate isolated subagent calls, each reading only the photo path and rating the same ~5 `CanonicalMuscleGroup` values (D-05) with zero memory of prior calls (D-06). Record each raw rating output into `15-SPIKE-RESULT.md`'s blind-condition table. |
| 5-step anchored chain where each call is fed the previous call's rating as explicit "prior observation" context (plan 15-01, Task 4) | PHYS-12 | Same as above — human-gated, requires the real photo; additionally requires deliberately breaking blindness in a controlled way to mirror PHYS-07's production read-tool behavior, which cannot be simulated without a live model call | Immediately following the blind condition (same photo, same session), issue 5 sequential subagent calls where each prompt includes the previous step's rating as "prior observation" text. Record each raw rating output into `15-SPIKE-RESULT.md`'s anchored-condition table, then analyze first-vs-last delta and monotonic-direction count to detect a ratchet no adjacent-pair diff would catch (ROADMAP success criterion #2). |
| Recommended constants (diff thresholds, any `PHYSIQUE_MIN_ELAPSED_DAYS` floor, confirmed/refined PHYS-01 anchor wording) stated with rationale (plan 15-02, Task 2) | PHYS-12 | Judgment call synthesizing the blind + anchored results — not a value any automated command computes | Once both conditions are recorded, the plan's final task writes named constants with a rationale comment (mirroring `backend/app/analytics/recomposition.py`'s `RECOMP_LOOKBACK_WEEKS` pattern) directly into `15-SPIKE-RESULT.md`, so Phase 16/17 can copy them verbatim. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies (this phase: all tasks are manual, no Wave 0 gap exists to depend on)
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify (N/A — phase is manual end-to-end by nature, not by gap)
- [ ] Wave 0 covers all MISSING references (none exist)
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
