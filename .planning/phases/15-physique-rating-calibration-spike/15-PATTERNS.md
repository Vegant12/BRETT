# Phase 15: Physique Rating Calibration Spike - Pattern Map

**Mapped:** 2026-09-08
**Files analyzed:** 3 (all `.planning/` markdown artifacts — this phase ships zero `backend/` code, per CONTEXT.md `<code_context>` and RESEARCH.md's Standard Stack: "no `app/analytics/physique.py` or physique schema exists yet")
**Analogs found:** 3 / 3

> **Taxonomy note:** This phase's deliverables are GSD process artifacts (a PLAN.md, its SUMMARY.md,
> and a spike-record markdown file), not application code. The standard role vocabulary
> (controller/service/model/...) does not fit cleanly, so roles below are GSD-specific
> (`plan-document`, `summary-document`, `spike-record`) rather than forced into an ill-fitting
> application-layer label. Data-flow values are chosen for their nearest conceptual match.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `.planning/phases/15-physique-rating-calibration-spike/15-01-PLAN.md` (and optional `15-02-PLAN.md` if collection/analysis are split — RESEARCH.md "Recommended Plan/Deliverable Structure") | plan-document (GSD) | event-driven (checkpoint-gated: human-action pause → main-context `Task`-tool fan-out → sequential anchored chain → auto write-up) | `.planning/milestones/v2.0-phases/13-health-analytics-reports-coaching-style/13-01-PLAN.md` | exact (same shape: a spike plan with one `checkpoint:human-action` task feeding one `auto` record-the-outcome task) |
| `.planning/phases/15-physique-rating-calibration-spike/15-01-SUMMARY.md` (and `15-02-SUMMARY.md` if split) | summary-document (GSD) | batch (post-hoc structured write-up of already-completed task execution) | `.planning/milestones/v2.0-phases/13-health-analytics-reports-coaching-style/13-01-SUMMARY.md` | exact (same phase-13 spike-plan lineage, same frontmatter schema, same section set) |
| `.planning/phases/15-physique-rating-calibration-spike/15-SPIKE-RESULT.md` | spike-record (audit-trail document) | batch (aggregates N=10 raw model-call outputs into descriptive statistics + a dated verdict + named constants) | `.planning/milestones/v2.0-phases/13-health-analytics-reports-coaching-style/13-SPIKE-RESULT.md` | exact — CONTEXT.md and RESEARCH.md both name this file explicitly as the format to mirror ("same evidentiary shape") |

## Pattern Assignments

### `.planning/phases/15-physique-rating-calibration-spike/15-01-PLAN.md` (plan-document, event-driven)

**Analog:** `.planning/milestones/v2.0-phases/13-health-analytics-reports-coaching-style/13-01-PLAN.md`

**Frontmatter pattern** (lines 1-26):
```yaml
---
phase: 13-health-analytics-reports-coaching-style
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - .planning/phases/13-health-analytics-reports-coaching-style/13-SPIKE-RESULT.md
autonomous: false
requirements: [RPT-03]

must_haves:
  truths:
    - "The user has created a real Claude Desktop scheduled task against BRETT's live connector and reported whether it could call an MCP tool at all."
    - "The outcome is written down as a dated record, whether it worked or failed."
    - "If the failure reproduced, the exact subagent-delegation preamble text is drafted and ready for D-13's conditional insertion."
  artifacts:
    - path: ".planning/phases/13-health-analytics-reports-coaching-style/13-SPIKE-RESULT.md"
      provides: "The dated capability-spike record the coaching-doc rewrite (plan 13-09) reads"
      contains: "## Spike 1"
  key_links:
    - from: "13-SPIKE-RESULT.md"
      to: "docs/coaching-instructions.md (plan 13-09)"
      via: "plan 13-09 reads the recorded outcome and writes the user-facing consequence line"
      pattern: "13-SPIKE-RESULT"
---
```
Apply directly for Phase 15: `phase: 15-physique-rating-calibration-spike`, `files_modified: [.planning/phases/15-physique-rating-calibration-spike/15-SPIKE-RESULT.md]`, **`autonomous: false`** is load-bearing here (same reason 13-01 sets it — a `checkpoint:human-action` task means the plan cannot run unattended), `requirements: [PHYS-12]`.

**Checkpoint:human-action task schema** (lines 69-135) — this is the exact tag set this repo's plans use (not the abbreviated form shown in RESEARCH.md's illustrative Code Examples section — use this real one):
```xml
<task type="checkpoint:human-action" gate="blocking">
  <name>Task 1: Run a real Claude Desktop scheduled task against BRETT's live connector</name>
  <read_first>
    - .planning/phases/13-health-analytics-reports-coaching-style/13-CONTEXT.md (D-12, D-13)
    - .planning/phases/13-health-analytics-reports-coaching-style/13-RESEARCH.md (Pitfall 5)
  </read_first>
  <what-built>
    Nothing was built. ...
  </what-built>
  <how-to-verify>
    This step requires the user's own Claude Desktop client ...
    1. ...
    2. ...
  </how-to-verify>
  <acceptance_criteria>
    - The user has reported one of exactly three verdicts: `PASS`, `FAIL-NO-SCHEMA`, or `FAIL-NO-ATTACH`
    - ...
  </acceptance_criteria>
  <files>(none — this task builds nothing; ...)</files>
  <action>PAUSE and hand the &lt;how-to-verify&gt; steps to the user verbatim. Do not simulate ...
until the user has reported a verdict. ...</action>
  <verify>
    <automated>MISSING — human-gated by D-12; no automated substitute exists. Verified by the user's reported verdict, which Task 2 records and asserts on.</automated>
  </verify>
  <done>The user has reported one of PASS / FAIL-NO-SCHEMA / FAIL-NO-ATTACH, with the scheduled run's verbatim reply.</done>
  <resume-signal>Report the verdict (PASS / FAIL-NO-SCHEMA / FAIL-NO-ATTACH), the run's reply text, and — if it failed — the workaround outcome.</resume-signal>
</task>
```
For Phase 15's photo-attachment checkpoint, reuse every tag: `<how-to-verify>` becomes the D-01 instructions ("provide an absolute file path or drag-and-drop — do NOT paste with Ctrl+V, per RESEARCH.md Pitfall 2"), `<acceptance_criteria>` becomes "a real, `ls`-verified absolute path was provided and copied into this session's scratchpad," `<action>` is the literal "PAUSE" instruction (same imperative RESEARCH.md's Architecture Pattern 1 requires so the segment router treats this as a genuine human-action gate, not an `auto` task in disguise).

**Auto task schema — record-outcome-into-markdown pattern** (lines 137-224):
```xml
<task type="auto">
  <name>Task 2: Record the spike outcome as a dated artifact</name>
  <files>.planning/phases/13-health-analytics-reports-coaching-style/13-SPIKE-RESULT.md</files>
  <read_first>
    - .planning/phases/13-health-analytics-reports-coaching-style/13-CONTEXT.md (D-12, D-13)
    - .planning/phases/13-health-analytics-reports-coaching-style/13-RESEARCH.md (Pitfall 5, the eight issue numbers)
  </read_first>
  <action>
Create `.planning/.../13-SPIKE-RESULT.md` with this exact structure (fill the bracketed values from Task 1's reported outcome):

```markdown
# Phase 13 — RPT-03 Scheduled-Task Spike Record
...
| Verdict | [PASS \| FAIL-NO-SCHEMA \| FAIL-NO-ATTACH] |
...
**Reading:** [one paragraph. If PASS: ... If FAIL-NO-SCHEMA: ... If FAIL-NO-ATTACH: ...]
```

Do NOT edit `docs/coaching-instructions.md` in this plan. ...
  </action>
  <verify>
    <automated>test -f .../13-SPIKE-RESULT.md && grep -q "## Spike 1" .../13-SPIKE-RESULT.md && grep -qE "PASS|FAIL-NO-SCHEMA|FAIL-NO-ATTACH" .../13-SPIKE-RESULT.md</automated>
  </verify>
  <acceptance_criteria>
    - `13-SPIKE-RESULT.md` exists
    - It contains the literal strings `## Spike 1`, `## D-13 preamble draft`, and `## Spike 2`
    - The Verdict row contains exactly one of `PASS`, `FAIL-NO-SCHEMA`, `FAIL-NO-ATTACH` — not a placeholder bracket
    - The Date run row contains a real ISO date, not `[YYYY-MM-DD]`
    - `grep -c "\[" 13-SPIKE-RESULT.md` shows no remaining unfilled `[A | B]` placeholder in the table rows
  </acceptance_criteria>
  <done>The spike outcome is a committed, dated artifact ...</done>
</task>
```
Apply for Phase 15's write-up task: `<verify><automated>` should `grep` for the literal section headers Phase 15's spike record must contain (e.g. `## Blind Condition`, `## Anchored Condition`, `## Recommended Constants`) and assert no bracketed placeholder survives, exactly as 13-01's does for its own headers.

**Task-tool-dependent step sequencing (the load-bearing structural pattern, not from a prior PLAN.md but required by RESEARCH.md's verified framework read):** every task that spawns a blind-rating or anchored-chain subagent (`Task(subagent_type="general-purpose", ...)`) MUST appear in the task list **after** the `checkpoint:human-action` task, in the same or a later segment, never before it and never in a plan with zero checkpoints — `execute-plan.md`'s segment router only resumes in the MAIN context (which has the `Task` tool) for segments following `decision`/`human-action`. Getting this ordering wrong produces a plan that fails at execution time with a missing-tool error (RESEARCH.md Pitfall 1, Architecture Pattern 1).

---

### `.planning/phases/15-physique-rating-calibration-spike/15-0X-SUMMARY.md` (summary-document, batch)

**Analog:** `.planning/milestones/v2.0-phases/13-health-analytics-reports-coaching-style/13-01-SUMMARY.md`

**Frontmatter pattern** (lines 1-35):
```yaml
---
phase: 13-health-analytics-reports-coaching-style
plan: 01
subsystem: testing
tags: [mcp, scheduled-tasks, spike, claude-desktop, fitness_ping]

requires: []
provides:
  - "13-SPIKE-RESULT.md: dated PASS record for the RPT-03 scheduled-task capability spike"
  - "D-13 preamble draft (marked NOT ELIGIBLE) available for plan 13-09 to reuse without re-drafting"
affects: [13-09-coaching-doc-rewrite]

tech-stack:
  added: []
  patterns: []

key-files:
  created:
    - .planning/phases/13-health-analytics-reports-coaching-style/13-SPIKE-RESULT.md
  modified: []

key-decisions:
  - "RPT-03 scheduled-task spike verdict is PASS: ..."

patterns-established: []
requirements-completed: [RPT-03]

duration: 6min
completed: 2026-09-05
---
```
For Phase 15: `subsystem: analytics` (or `research`), `tags: [physique, calibration-spike, subagent-isolation, anchoring-bias]`, `provides: ["15-SPIKE-RESULT.md: dated record of blind + anchored rating movement, with recommended constants for Phase 16/17"]`, `affects: [16-*-schema, 17-*-analytics-physique]`, `requirements-completed: [PHYS-12]`.

**Body-section pattern** (lines 37-95): `# Phase X Plan Y: <title> Summary` one-liner, `## Performance`, `## Accomplishments`, `## Task Commits`, `## Files Created/Modified`, `## Decisions Made`, `## Deviations from Plan`, `## Issues Encountered`, `## User Setup Required`, `## Next Phase Readiness`, closing `## Self-Check: PASSED` block listing every artifact path and commit hash the plan produced. Reuse this section set verbatim; the only Phase-15-specific care point is **Pitfall 5** below — do not let `## Issues Encountered` or `## Decisions Made` describe the photo itself or its filesystem source path (D-02).

---

### `.planning/phases/15-physique-rating-calibration-spike/15-SPIKE-RESULT.md` (spike-record, batch)

**Analog:** `.planning/milestones/v2.0-phases/13-health-analytics-reports-coaching-style/13-SPIKE-RESULT.md`

**Header/purpose pattern** (lines 1-6):
```markdown
# Phase 13 — RPT-03 Scheduled-Task Spike Record

**Purpose:** the durable record ROADMAP.md success criterion #4 requires — "the outcome, working
or broken with a documented workaround, is written into docs/coaching-instructions.md rather
than assumed." This file is the raw evidence; plan 13-09 writes the one-line user-facing
consequence into `docs/coaching-instructions.md` from it.
```
Phase 15 equivalent: state PHYS-12 and name ROADMAP success criterion #4 ("Phase 16's observation schema is not started until this result exists") plus which downstream files consume it (Phase 16 schema, Phase 17 `analytics/physique.py`).

**Per-condition dated-table pattern** (lines 8-18, repeated per spike):
```markdown
## Spike 1 — capability probe with `fitness_ping` (before report tools existed)

| Field | Value |
|---|---|
| Date run | 2026-09-05 |
| Client | Claude Desktop (D-12) |
| Connector | BRETT live remote MCP connector |
| Tool called | `fitness_ping` |
| Verdict | PASS |
| Subagent-delegation workaround | N/A |
```
Phase 15 needs two such tables — one per muscle group in the **blind** condition (Date run, Muscle group, 5 raw ratings, mode, range, exact-agreement count, Verdict) and one for the **anchored** condition (Date run, Muscle group, 5-step chain R1..R5, first-vs-last diff, monotonic-direction count, Verdict).

**Raw-quoted-output pattern** (lines 19-22):
```markdown
**Scheduled run's actual reply:**

> The database field returned by fitness_ping is: 'connected'. This is a routine health check
> with a normal, healthy result — no issue to flag.
```
Apply per rating call: quote each of the 10 raw subagent outputs verbatim in a blockquote, never paraphrased — this is what makes the record evidentiary rather than a summary (13-SPIKE-RESULT.md's own "Reading" paragraph explicitly leans on the exact-string match as proof the call was real, not guessed; Phase 15's raw quotes serve the identical evidentiary function).

**"Reading" paragraph pattern** (lines 24-32, and the longer example at lines 100-108):
```markdown
**Reading:** The eight community reports in 13-RESEARCH.md Pitfall 5 do not reproduce against
this connector as of this date. The scheduled session's reply quoted the exact string
`fitness_ping`'s implementation ... returns on a successful DB round-trip — ... — which is strong
corroborating evidence the tool schema actually reached the scheduled session and a real call was
made, rather than the model guessing a plausible-sounding value from memory ...
```
Every "Reading" paragraph: (a) states the concrete evidence, (b) explains why that evidence rules out an alternative (uninformative/guessed) explanation, (c) states what remains open. Phase 15's Reading paragraphs should follow the same three-part shape for both the blind-condition scatter and the anchored-condition drift, and explicitly use the language RESEARCH.md's Pattern 3 specifies: "a ratchet's signature is: blind condition shows scatter with no direction, anchored condition shows a one-directional staircase" — contrast, not a p-value.

**Operational-context-with-discarded-attempts pattern** (lines 76-98): 13-SPIKE-RESULT.md keeps a record of two FAILED prior attempts (stale revision, migration lag) even though they were "discarded from the formal verdict," because they are informative background and corroborate the eventual PASS reading. Apply the same posture if the Phase 15 smoke-test call (RESEARCH.md Open Question 1's recommended single-call dry run before committing to all 10) fails or needs retrying — record it as discarded-but-informative context, not silently omit it.

**Status/verdict line pattern**: `Status: **PASS**.` / `Status: NOT ELIGIBLE — the spike passed, do not add this` — a bare, bolded, one-line verdict immediately under each section heading, before the evidence table. Phase 15's record needs this for both the blind-condition verdict (e.g., ratchet not observed) and the anchored-condition verdict (ratchet observed / not observed, D-08's framing).

---

### Named-constant-with-rationale idiom (D-09's required output shape)

**Analog:** `backend/app/analytics/recomposition.py`

**Pattern** (lines 77-91):
```python
# D-11. The stricter end of the published 0.25-0.5%/week lean-bulk band, chosen to keep gains lean
# rather than tolerate a faster, fattier surplus. Evaluated against D-16's SMOOTHED rate.
WEIGHT_GAIN_TOO_FAST_PERCENT_PER_WEEK = Decimal("0.25")

# D-12. Deliberately asymmetric: loss is not the goal, but a loss this fast during a bulk is a
# clear signal something is off -- undereating, illness, or a tracking error -- and is worth
# surfacing regardless of the stated goal.
WEIGHT_LOSS_TOO_FAST_PERCENT_PER_WEEK = Decimal("-1.00")

# The "weight stable" dead-band. CONTEXT.md supplies the two OUTER thresholds but not this one,
# and blueprint 26's enum needs it to distinguish `weight_stable` from `likely_muscle_gain` and
# `likely_fat_loss`. One tenth of D-11's own threshold rather than an independent invention: at
# this user's ~65 kg that is ~65 g/week, comfortably below what a 7-day average over 3-6 weigh-ins
# can resolve, so a narrower band would classify measurement noise as a direction.
WEIGHT_STABLE_BAND_PERCENT_PER_WEEK = Decimal("0.10")
```
And (lines 93-104):
```python
# D-20. A whole-body verdict must not turn on one accessory lift; three is the smallest number for
# which a majority exists at all.
RECOMP_MIN_CLASSIFIED_EXERCISES = 3

# D-20. Symmetric, ONE constant, exact in Decimal because it compares against an integer ratio.
# "More than a quarter of your classified exercises are net-improving" is a sentence a coach can
# check by counting.
RECOMP_PROGRESSION_NET_BAND = Decimal("0.25")

# The window the progression signal and the context volume are read over. Matches PROG-03's D-19
# default so "am I recomping" and "am I plateaued" describe the same block of training.
RECOMP_LOOKBACK_WEEKS = 12
```
And the required-field disclaimer idiom (lines 108-111):
```python
INTERPRETATION_DISCLAIMER = (
    "Decision support from body-weight trend and training progression only. "
    "Not a medical or diagnostic claim, and not a body-composition measurement."
)
```

**Every constant follows the same three-part comment shape:** (1) a decision-ID or spike reference, (2) the concrete number/observation that justifies the value, (3) why THIS number and not a nearby alternative — often by relating it arithmetically to another named constant (`WEIGHT_STABLE_BAND` = "one tenth of D-11's own threshold") rather than inventing an independent value.

**Apply to `15-SPIKE-RESULT.md`'s "Recommended Constants" section as PROSE-WRAPPED CODE, not real Python** (D-09, since no `.py` file exists in this phase — Phase 16/17 copy this block verbatim into real code later):
```python
# PHYS-12 spike (2026-MM-DD, 15-SPIKE-RESULT.md): 5 blind ratings on one unchanged photo-set
# showed <describe actual observed movement>. The anchored 5-step chain <describe observed
# first-vs-last diff and monotonic-direction count>. Set above the largest elapsed interval at
# which spurious movement was still observed in <condition>, with margin for real photos varying
# more than this session's fixed set.
PHYSIQUE_MIN_ELAPSED_DAYS = <value from actual spike data>
```
The bracketed placeholders must be filled from the REAL spike run, never invented — same discipline 13-01-PLAN.md's `<acceptance_criteria>` enforces via its "no remaining `[A | B]` placeholder" grep check.

## Shared Patterns

### Checkpoint-routing for Task-tool-dependent steps
**Source:** RESEARCH.md Architecture Pattern 1 (verified this session against `~/.claude/get-shit-done/workflows/execute-plan.md`'s segment-routing table and `~/.claude/agents/gsd-executor.md`'s frontmatter, which lacks `Task`)
**Apply to:** `15-01-PLAN.md` (and any split `15-02-PLAN.md`) — every task spawning an isolated blind-rating or anchored-chain subagent must be sequenced in a segment that follows the plan's `checkpoint:human-action` task, never before it, never in a plan with zero checkpoints.
```
| Checkpoints in plan | Pattern | Where segments run |
|---|---|---|
| None | A | Entire plan in a spawned gsd-executor (no Task tool) |
| Only human-verify | B | Segments after human-verify → spawned gsd-executor; after decision/human-action → MAIN |
| Contains decision | C | Entire plan runs in MAIN |
```

### Never leak a real filesystem path or photo description into a committed artifact
**Source:** RESEARCH.md Common Pitfall 5, CONTEXT.md D-02
**Apply to:** `15-01-PLAN.md`'s task `<action>`/`<how-to-verify>` prose, and `15-0X-SUMMARY.md`'s `## Issues Encountered`/`## Decisions Made` sections. Log only "photo received, copied to session scratchpad, rated" — never the literal source path (e.g. `/Users/.../Desktop/progress-photo.jpg`) or any descriptive content about the photo itself in any file destined for `git commit`. The raw quoted MODEL OUTPUT (ordinal ratings + reasoning text) is fine and required — it is not the same thing as a filesystem path or photo content.

### Manual-only test mapping (already pre-populated by `gsd-phase-validator`)
**Source:** `.planning/phases/15-physique-rating-calibration-spike/15-VALIDATION.md` (already exists; frontmatter `nyquist_compliant: false`, `wave_0_complete: false`)
**Apply to:** the planner should assign concrete Plan/Wave numbers into 15-VALIDATION.md's `Per-Task Verification Map` table (currently `TBD (planner assigns)`) rather than re-deriving the manual-only classification — PHYS-12 is already marked `manual` with `N/A` automated command, mirroring `13-RESEARCH.md`'s RPT-03 precedent.

### Muscle-group taxonomy reference for D-05's ~5-group sample
**Source:** `backend/app/normalization/muscles.py` lines 26-47 (`CanonicalMuscleGroup`, 19 values: `chest, lats, upper_back, traps, lower_back, front_delts, side_delts, rear_delts, biceps, triceps, forearms, abs, obliques, quads, hamstrings, glutes, calves, abductors, adductors`)
**Apply to:** the plan's rating-subagent prompt content — CONTEXT.md's suggested subset (`chest, lats, biceps, abs, side_delts`) is a valid mix of visually-obvious (chest, biceps) and subtler (side_delts) groups; RESEARCH.md Pitfall 6 flags `abductors`/`adductors` as PHYS-02-documented "permanently not-assessable from standard photos" — never include either in the sample.

## No Analog Found

None — all three files in scope have an exact-match analog already in the repo (Phase 13's spike lineage covers the plan/summary/spike-record trio; `recomposition.py` covers the constant-with-rationale idiom this phase's prose output must mirror).

## Metadata

**Analog search scope:** `.planning/milestones/v2.0-phases/13-health-analytics-reports-coaching-style/` (spike-record precedent, named explicitly by CONTEXT.md and RESEARCH.md), `backend/app/analytics/recomposition.py` (constant-with-rationale precedent, named explicitly by CONTEXT.md D-09 and RESEARCH.md Code Examples), `backend/app/normalization/muscles.py` (taxonomy reference for D-05), plus a repo-wide `grep -rl "checkpoint:"` sweep across `.planning/**/*PLAN.md` to confirm the real (not paraphrased) task-tag schema used for `checkpoint:human-action` and `auto` tasks in this codebase.
**Files scanned:** 3 read in full (`13-01-PLAN.md`, `13-01-SUMMARY.md`, `13-SPIKE-RESULT.md`) + 1 read in full (`recomposition.py`) + 1 partial read (`muscles.py` enum) + 1 pre-existing artifact reviewed (`15-VALIDATION.md`, already generated for this phase).
**Pattern extraction date:** 2026-09-08
