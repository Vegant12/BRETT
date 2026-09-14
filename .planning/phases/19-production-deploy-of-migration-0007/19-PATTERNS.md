# Phase 19: Production Deploy of Migration 0007 - Pattern Map

**Mapped:** 2026-09-14
**Files analyzed:** 4 (2 tracking docs to modify, 1 plan-document to author, 1 optional result-record to author)
**Analogs found:** 4 / 4

## Context

This phase writes **zero application code**. RESEARCH.md's "Recommended Plan Structure" names
only `.planning/STATE.md` and `.planning/REQUIREMENTS.md` as files this phase modifies, plus the
phase's own `19-01-PLAN.md` (a GSD plan-document, not application code) and, optionally, a
result-record file analogous to `15-SPIKE-RESULT.md` to hold the verbatim deploy log / smoke-test
response as durable evidence. `docs/runbook-deploy.md` is **read and followed, not modified** —
14-03-SUMMARY.md explicitly says it "is ready for Phase 19 ... to follow verbatim."

The one genuinely unusual planning problem this phase has — writing `autonomous: false`,
human-executed, runbook-style tasks in a codebase whose otherwise-universal convention is
`autonomous: true` / `type="auto"` — already has a **precise, proven analog**: Phase 15's
`15-01-PLAN.md`. Use it verbatim as the task-tag template; do not invent a new
`autonomous: false` / `read_first` / `acceptance_criteria` field convention, because the GSD
framework itself (`~/.claude/get-shit-done/workflows/execute-plan.md`,
`~/.claude/get-shit-done/references/checkpoints.md`) already defines the correct tag:
`type="checkpoint:human-action"`.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `19-01-PLAN.md` (and optionally `19-02-PLAN.md`) | plan-document (GSD) | event-driven (checkpoint-gated: auto pre-flight → `checkpoint:human-action` deploy trigger → `checkpoint:human-action` MCP smoke test → auto record-result) | `.planning/phases/15-physique-rating-calibration-spike/15-01-PLAN.md` | exact — same shape: a plan whose main work is impossible to run unattended in this sandbox, gated by `checkpoint:human-action` tasks, with a final `auto` task recording the outcome |
| `.planning/STATE.md` | tracking-doc | CRUD (in-place field update, not append) | Commit `c876593` ("docs(phase-18): complete phase execution") — the prior phase's own STATE.md diff | exact — same file, same section shape, most recent example |
| `.planning/REQUIREMENTS.md` | tracking-doc | CRUD (checkbox flip + traceability table row edit) | Commit `c876593`'s `.planning/REQUIREMENTS.md` diff | exact — same file, same two edit sites (requirement checkbox, traceability table row) |
| `19-DEPLOY-RESULT.md` (optional — only if the planner wants a durable evidentiary record of the deploy log / smoke-test response, mirroring the spike-record pattern) | result-record (GSD artifact) | event-driven / write-once (pre-registered structure, filled in by execution) | `.planning/phases/15-physique-rating-calibration-spike/15-SPIKE-RESULT.md` | role-match — same "pre-registered structure, verbatim-quoted evidence, redaction discipline" pattern, applied to a deploy log instead of rating output |

## Pattern Assignments

### `19-01-PLAN.md` (plan-document, checkpoint-gated runbook)

**Analog:** `.planning/phases/15-physique-rating-calibration-spike/15-01-PLAN.md` (frontmatter + Task 1), cross-checked against the GSD framework's own checkpoint-type reference.

**Why this analog and not a from-scratch design:** Phase 15 hit the identical structural problem this phase has — real-world work (a photo; here, a credentialed `gcloud` call) that this agent's sandbox cannot perform, requiring a human-executed gate rather than an `auto` task — and it is the only prior plan in this repo that uses `autonomous: false` and `checkpoint:human-action` for real. `14-03-PLAN.md` (the phase that built the deploy script and runbook) is **not** a usable analog for the checkpoint shape: every one of its tasks is `type="auto"` / `autonomous: true`, because at that time nothing in the plan touched a live secret — it only wrote tests against a stubbed `gcloud`.

**Frontmatter pattern** (from `15-01-PLAN.md` lines 1-11):
```yaml
---
phase: 15-physique-rating-calibration-spike
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - .planning/phases/15-physique-rating-calibration-spike/15-SPIKE-RESULT.md
autonomous: false
requirements: [PHYS-12]
---
```
For Phase 19, the equivalent is:
```yaml
---
phase: 19-production-deploy-of-migration-0007
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - .planning/STATE.md
  - .planning/REQUIREMENTS.md
autonomous: false
requirements: [DEPLOY-05]
---
```
`autonomous: false` at the plan level is load-bearing (15-PATTERNS.md line 56: "a `checkpoint:human-action` task means the plan cannot run unattended") — set it the moment the plan contains even one `checkpoint:human-action` task.

**The exact human-action task shape to reuse** (from `15-01-PLAN.md` lines 102-161, condensed to the load-bearing tags):
```xml
<task type="checkpoint:human-action" gate="blocking">
  <name>Task N: <the one thing requiring a human, e.g. "Run the deploy" or "Confirm the live MCP tool call">
  <read_first>
    - <files the human/operator needs to have read first — e.g. docs/runbook-deploy.md>
  </read_first>
  <what-built>
    <state plainly what Claude already automated/prepared, and WHY this specific step cannot be
    automated in this sandbox — mirror 15-01-PLAN.md's own honesty: "Nothing was built... this is
    a genuine human-action gate, not automatable work being handed to a human.">
  </what-built>
  <how-to-verify>
    <exact commands the human runs, verbatim, and exactly what output confirms success — for
    Phase 19 this is docs/runbook-deploy.md Step 4-5's commands and the four-line log-ordering
    check>
  </how-to-verify>
  <acceptance_criteria>
    - <mechanically checkable claims about what the human must report back>
  </acceptance_criteria>
  <files>(none — this task builds nothing and writes nothing to the repo)</files>
  <action>PAUSE and hand the &lt;how-to-verify&gt; text to the user verbatim. Do NOT attempt to
  run <the blocked command> yourself even wrapped differently — see 19-RESEARCH.md Pitfall 1.</action>
  <verify>
    <automated>MISSING — human-gated; no automated substitute exists.</automated>
  </verify>
  <done>&lt;the single observable fact that proves this step happened&gt;</done>
  <resume-signal>&lt;exactly what the human should paste back — e.g. "the deploy script's full
  stdout/stderr" or "the JSON response from the tool call">
</task>
```
This is the same tag vocabulary GSD's own reference defines for this exact scenario
(`~/.claude/get-shit-done/references/checkpoints.md`, `<type name="human-action">`):
*"Use ONLY for: Authentication gates — Claude tried CLI/API but needs credentials (this is NOT a
failure)... Do NOT use for pre-planned manual work: Deploying (use CLI - auth gate if needed)"* —
i.e. the framework's own guidance is: attempt the automated path first (the plan's auto
pre-flight task should still literally try `gcloud run services describe`, `alembic heads`,
etc., since those succeed in-sandbox per RESEARCH.md's Environment Availability table), and only
gate the two steps that concretely hit the classifier (`gcloud secrets versions access` inside
the deploy script; the OAuth-authenticated MCP call) behind `checkpoint:human-action`.

**Segment-ordering constraint carried over from the same analog** (15-01-PLAN.md lines 163-168,
generalizes beyond the `Task`-tool-specific reason): once a plan contains a
`checkpoint:human-action`, everything textually after it resumes in a context that has full
tool access again — so put the pre-flight (auto, safe) tasks *before* the human-action tasks, and
the final "record the result" (auto) task *after* them, exactly as 15-01-PLAN.md orders Task 1
(human-action) before Tasks 2-4 (auto), and as RESEARCH.md's own Recommended Plan Structure
already proposes for Phase 19 (Task 1 auto pre-flight → Task 2 human-action deploy → Task 3
human-action smoke test → Task 4 auto record-result).

**`<action>` "PAUSE" imperative** (15-01-PLAN.md line 150-155): the action block for a
`checkpoint:human-action` task must contain the literal instruction to PAUSE and must not describe
work Claude will silently do instead — this is what makes the segment router treat it as a real
gate rather than an `auto` task in disguise (per `checkpoints.md`'s own distinction).

---

### `.planning/STATE.md` (tracking-doc, in-place field update)

**Analog:** the diff `docs(phase-18): complete phase execution` (commit `c876593`) applied to this exact file when Phase 18 completed.

**Exact edit sites and their format** (from the real diff):
```yaml
# Frontmatter block — three fields move together on every phase completion:
stopped_at: Phase 18 complete, ready to plan Phase 19        # was: Phase 18 context gathered
last_updated: "2026-09-12T04:50:15.133Z"                     # ISO-8601, refreshed
last_activity: 2026-09-12                                     # date only, no time
progress:
  total_phases: 6
  completed_phases: 5        # incremented
  total_plans: 16
  completed_plans: 16        # incremented to match total once phase's plans are all done
  percent: 100                # completed_plans / total_plans, this milestone
```
```markdown
**Current focus:** Phase 19 — production-deploy-of-migration-0007
...
## Current Position

Milestone: v2.1 Longitudinal Physique Analysis
Phase: 19
Plan: Not started
Status: Ready to plan
Last activity: 2026-09-12 -- Phase 18 complete (3/3 plans, verification passed 11/11 must-haves)

Progress: [████████──] 83% — 5/6 v2.1 phases complete
```
For Phase 19's own completion, the analogous edit is: bump `completed_phases` to `6`, `percent`
recomputes for whatever the *next* milestone's total is (or this v2.1 milestone closes — check
whether this is the milestone's last phase before writing the field, since `ROADMAP.md` lists
Phase 19 as the sixth and final v2.1 phase), replace `**Current focus:**` and `## Current
Position` with milestone-close language rather than "ready to plan Phase 20" (there is no Phase
20 defined yet) — mirror how a milestone boundary was previously written by inspecting the v2.0→v2.1
transition commits (`3022628`, `4dddb26`) if a full milestone-close write-up is in scope, or defer
that to a separate `/gsd-close-milestone`-style step if this phase's own convention doesn't cover it.

**Session Continuity pattern** (STATE.md lines 145-149, update on every phase transition):
```markdown
## Session Continuity

Last session: 2026-09-12T03:13:21.300Z
Stopped at: Phase 18 context gathered
Resume: `/gsd-discuss-phase 16` (Phase 14 is already complete — do not re-run its discuss step).
```
Update `Last session`, `Stopped at`, and `Resume` to reflect Phase 19's actual completion state
and whatever the next real action is (milestone close, or `/gsd-discuss-phase` for a not-yet-
planned next phase).

---

### `.planning/REQUIREMENTS.md` (tracking-doc, checkbox + traceability edit)

**Analog:** the same `c876593` diff applied to `.planning/REQUIREMENTS.md`.

**Exact edit pattern** (from the real diff — two sites, always edited together):
```diff
- [ ] **DEPLOY-05**: This milestone's new migration reaches production through the fixed pipeline, proving DEPLOY-04 works rather than asserting it
+ [x] **DEPLOY-05**: This milestone's new migration reaches production through the fixed pipeline, proving DEPLOY-04 works rather than asserting it
```
```diff
| DEPLOY-04 | Phase 14 | Complete |
- | DEPLOY-05 | Phase 19 | Planned |
+ | DEPLOY-05 | Phase 19 | Complete |
```
Two mechanical rules evident from this and the sibling `RPT-04`/`RPT-05` edits in the same
commit: (1) the checkbox and the traceability-table `Status` column are flipped **in the same
commit**, never separately — do not close one without the other; (2) the requirement's own
description text is never edited when it is marked complete, only the leading `[ ]`→`[x]`.

**Where DEPLOY-05 sits in the file today** (lines 47-48, unmodified until this phase closes it):
```markdown
- [x] **DEPLOY-04**: `scripts/deploy-cloud-run.sh` gains a migration step, or an enforced `alembic current` versus `alembic heads` pre-flight that fails the deploy on drift, plus a documented single source of truth for the production `DATABASE_URL`. Production ran a schema behind deployed code three separate times during v2.0, each caught only during live verification
- [ ] **DEPLOY-05**: This milestone's new migration reaches production through the fixed pipeline, proving DEPLOY-04 works rather than asserting it
```
and the traceability row (line 114):
```markdown
| DEPLOY-05 | Phase 19 | Planned |
```

---

### `19-DEPLOY-RESULT.md` (optional result-record, if the planner adds one)

**Analog:** `.planning/phases/15-physique-rating-calibration-spike/15-SPIKE-RESULT.md`.

**Why an analog exists for a file RESEARCH.md doesn't explicitly name:** RESEARCH.md's Recommended
Plan Structure Task 2/3 say "capture/paste back the deploy log" and "paste back the response" but
does not specify *where that evidence lives permanently*. Phase 15 already established this
project's convention for exactly this situation — a checkpoint-gated plan whose real evidentiary
output is external, human-supplied text — by writing it into a pre-registered, structured
markdown record rather than only into the ephemeral `SUMMARY.md`. If the planner wants Phase 19's
deploy log and MCP response to be durably inspectable (not just summarized), reuse this shape:

**Structure pattern** (from `15-SPIKE-RESULT.md`'s pending-section skeleton, `15-01-PLAN.md` lines 235-407):
```markdown
# Phase 19 — DEPLOY-05 Production Deploy Record

**Purpose:** <what ROADMAP/REQUIREMENTS criterion this discharges>

## Method
<what will be run, pre-registered before execution — the exact runbook steps and expected log
ordering, copied from docs/runbook-deploy.md Step 5>

## Deploy Log (verbatim, redacted)
pending -- written by the human-action task once the operator pastes back the deploy output

## MCP Smoke Test (verbatim)
pending -- written by the human-action task once the operator pastes back the tool-call response

## Result
pending -- PASS/FAIL against the acceptance criteria
```

**Redaction discipline to carry over verbatim** (15-01-PLAN.md's own acceptance criteria, lines
417-430, and the STRIDE entry T-15-01, lines 667): any file this phase writes must be grepped for
credential-shaped strings before being treated as done. For Phase 19 the equivalent check —
already spelled out in `docs/runbook-deploy.md`'s own verification block — is:
```bash
! grep -qE 'postgres(ql)?(\+asyncpg)?://[^ )`]*:[^ )`]*@' <file>
```
Apply this same grep to `19-DEPLOY-RESULT.md` (or wherever the pasted deploy log lands) before
committing it — a pasted deploy log could theoretically contain a DSN if an operator's terminal
echoed one, even though the script itself never prints one.

## Shared Patterns

### Runbook to follow verbatim (read-only reference, not a file this phase writes)
**Source:** `docs/runbook-deploy.md` (all 124 lines; see especially the numbered "## The deploy
procedure" section, lines 58-91, and the "## What an abort looks like" table, lines 93-100)
**Apply to:** the `<how-to-verify>` block of the deploy-trigger `checkpoint:human-action` task —
quote its Step 4-5 commands and the four-line log-ordering check character-for-character rather
than re-deriving them:
```bash
# Step 3 (pre-deploy review, required before every real deploy):
cd backend && DATABASE_URL="$(gcloud secrets versions access latest \
  --project="$BRETT_GCP_PROJECT" --secret="brett-database-url")" \
  uv run alembic history -r current:head

# Step 4 (the deploy itself):
BRETT_GCP_PROJECT=brett-fitness ./scripts/deploy-cloud-run.sh

# Step 5 — confirm this exact log ordering:
#   DEPLOY-04: using Secret Manager brett-database-url:latest in project brett-fitness
#   <alembic upgrade head output>
#   at head: ['0007']
#   <gcloud run deploy build/deploy output, ending in a new revision serving 100% traffic>
```
The abort table (`docs/runbook-deploy.md` lines 96-100) is the exact acceptance-check vocabulary
for a FAIL outcome — reuse its three message strings verbatim in the task's
`<acceptance_criteria>` so a human operator's pasted-back failure output can be matched
mechanically rather than re-interpreted.

### MCP tool-call envelope proven against this production service (read-only reference)
**Source:** `docs/runbook-secret-rotation.md` Step 6, adapted in `19-RESEARCH.md`'s "Code
Examples" section (lines 222-241) for `tools/call` on `fitness_get_latest_physique_observation`.
**Apply to:** the MCP-smoke-test `checkpoint:human-action` task's `<how-to-verify>` block — do not
hand-derive a new JSON-RPC envelope; the mandatory `params._meta` block and the four required
headers (`MCP-Protocol-Version`, `Mcp-Method`, `Mcp-Name`, `Content-Type`/`Accept`) are exactly
as RESEARCH.md quotes them, and RESEARCH.md's own Pitfall/Anti-Pattern notes ("omit `_meta` and
the server answers `-32602` inside a 200") are the failure mode to name in
`<acceptance_criteria>`.

### Expected PASS response shape (read-only reference)
**Source:** `backend/app/mcp/tools/physique.py::fitness_get_latest_physique_observation` and
`backend/app/mcp/tools/schemas.py::LatestPhysiqueObservationResponse`, quoted in `19-RESEARCH.md`
lines 243-252.
**Apply to:** the smoke-test task's `<acceptance_criteria>` — the PASS shape is
`{"data_available": true, "observation": null, "rating_scale": <non-empty>, "disclaimer":
<non-empty>}`, and `observation: null` must be written into the acceptance criteria as the
*expected* value (per RESEARCH.md Common Pitfall 4), not treated as an ambiguous/failing result.

### Checkpoint-type selection discipline (framework-level, not repo-level)
**Source:** `~/.claude/get-shit-done/references/checkpoints.md`, `<type name="human-action">` and
`<type name="human-verify">` sections.
**Apply to:** every task in `19-01-PLAN.md` that touches `gcloud`, the deploy script, or a live
MCP call. Use `checkpoint:human-action` (not `checkpoint:human-verify`) specifically because the
work itself — not merely its visual/behavioral confirmation — must be done by a human in their own
terminal/client; this matches the framework's own stated scope ("Authentication gates — Claude
tried CLI/API but needs credentials (this is NOT a failure)"). Do not downgrade these to
`checkpoint:human-verify`, which presumes Claude already performed the underlying action.

## No Analog Found

None. Every file this phase is expected to touch (per RESEARCH.md's Recommended Plan Structure)
has a concrete, recently-used analog in this repo.

## Metadata

**Analog search scope:** `.planning/STATE.md`, `.planning/REQUIREMENTS.md`, `docs/runbook-deploy.md`,
`docs/runbook-secret-rotation.md`, `.planning/phases/14-deploy-pipeline-migration-safety/*.md`,
`.planning/phases/15-physique-rating-calibration-spike/*.md`, `.planning/phases/17-*/`,
`.planning/phases/18-*/`, `~/.claude/get-shit-done/workflows/execute-plan.md`,
`~/.claude/get-shit-done/references/checkpoints.md`, git history of `.planning/STATE.md` and
`.planning/REQUIREMENTS.md` (`git log --oneline -- .planning/STATE.md .planning/REQUIREMENTS.md`).
**Files scanned:** 19-RESEARCH.md, STATE.md, REQUIREMENTS.md, docs/runbook-deploy.md,
14-03-PLAN.md, 15-01-PLAN.md, 15-PATTERNS.md (partial), checkpoints.md (partial), commit
`c876593` diff.
**Pattern extraction date:** 2026-09-14
