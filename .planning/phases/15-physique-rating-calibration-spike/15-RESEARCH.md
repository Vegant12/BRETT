# Phase 15: Physique Rating Calibration Spike - Research

**Researched:** 2026-09-08
**Domain:** LLM-as-rater measurement methodology + GSD execution-model mechanics (subagent isolation, checkpoint routing, tool availability) — NOT a backend/library domain. This phase ships no `backend/` code.
**Confidence:** MEDIUM overall — HIGH on the GSD execution-mechanics findings (verified by reading the actual framework source), MEDIUM on the measurement-design recommendations (reasoned + literature-cross-checked, not empirically run), LOW on anything about how the live rating calls will actually behave (that's the spike's entire purpose — it is intentionally unknown until run)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Photo Readiness & Timing**
- **D-01:** The user has real progress photos ready. The spike runs live in a **future session**
  during this phase's plan execution — the plan must include an explicit step that pauses and
  asks the user to attach/provide the photo(s) at that point. Do not assume photos are already
  available when planning starts.
- **D-02:** Photos reach the rating calls via this session's private scratchpad directory only —
  never committed to the repo, never referenced in planning docs beyond the ephemeral scratchpad
  path, and discarded when the session ends. This applies the project's "BRETT never stores an
  image" posture to the spike itself, not just to production code.

**Sample Design & Rigor**
- **D-03:** One real photo-set (e.g., front/back/side from the same real session) is rated
  repeatedly — not multiple photo-sets from different times. Since nothing changes between
  calls, any rating movement observed IS the noise/drift signal being measured.
- **D-04:** 5 independent **blind** repeat ratings of the same unchanged photo-set, plus a
  5-step **anchored** chain where each call is fed the previous call's rating as "prior
  observation" — mirroring exactly how PHYS-07 will work in production.
- **D-05:** A representative subset of ~5 of the 19 `CanonicalMuscleGroup` values gets rated per
  call, not all 19 — e.g. chest, lats, biceps, abs, side_delts, mixing easy-to-assess and
  subtle/ambiguous groups. Exact picks are Claude's discretion at execution time.
- **D-06:** Each blind rating is a fully isolated subagent (`Agent` tool) call with its own fresh
  context, reading only the photo file from the scratchpad. Blindness is structurally guaranteed
  by context isolation. The anchored chain deliberately feeds each step's prompt the previous
  step's rating output as explicit "prior observation" text.

**What the Spike's Constants Govern**
- **D-07:** The spike's findings have authority ONLY over two open constants: (a) a recommended
  minimum-elapsed-time floor, and (b) confirming or refining PHYS-01's anchor wording. PHYS-01's
  5-level count and PHYS-09's pure-ordinal-diff design stay locked regardless of findings.
- **D-08:** If the spike finds a real self-reinforcing ratchet in the anchored chain, the record
  documents it as an **accepted, monitored risk** and recommends an instruction-level mitigation
  (derive each rating primarily from the photo, treat prior observation as a sanity check, not a
  target). This belongs in the eventual write-tool description and/or
  `docs/coaching-instructions.md` (Phase 17/18 territory). It does NOT trigger a schema/write-tool
  design change, does NOT promote PHYS-F01 out of deferred status, and does NOT block Phase 16.
- **D-09:** Recommended values are expressed as **named constants with concrete values and
  rationale** — matching `recomposition.py`'s `RECOMP_LOOKBACK_WEEKS`/`RECOMP_PROGRESSION_NET_BAND`
  pattern (a comment explaining why, then the literal value) — e.g. a documented
  `PHYSIQUE_MIN_ELAPSED_DAYS` value. Phase 16/17 should be able to copy these directly.

### Claude's Discretion
- Exact prompt wording given to each rating subagent, and how the anchored-chain prompt frames
  "prior observation" text, as long as it faithfully mirrors what PHYS-07's production read tool
  will eventually return.
- Which 5 (or so) muscle groups specifically get rated (D-05).
- Layout/structure of the spike record's tables, as long as it matches `13-SPIKE-RESULT.md`'s
  evidentiary rigor (dated, verdict stated, raw model output quoted, reasoning shown).
- "Spike execution mechanics" was not separately selected for deep discussion; the isolated-
  `Agent()`-call design proposed during gray-area presentation is adopted as the working approach.

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope. No scope-creep attempts arose during this discussion.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PHYS-12 | Before the observation schema is finalized, a spike measures actual rating movement across repeated, blind and anchored calls on the same photo set. Its results set the diff thresholds and any elapsed-time floor. The spike explicitly tests whether PHYS-07's anchoring mitigation causes a self-reinforcing ratchet a slow drift no adjacent-pair diff can detect. | **Architecture Patterns** (checkpoint-routing fix that makes isolated subagent calls executable at all; blind+anchored data-flow diagram); **Common Pitfalls** (tool-restriction gotcha, image-ingestion mechanics, anti-pattern #10 tension); **Code Examples** (constant-with-rationale template, checkpoint XML, Task-call template); **State of the Art** (anchoring-bias literature quantifying why D-08's "accepted risk" framing, not a prompt fix, is the honest conclusion); **Don't Hand-Roll** (why formal reliability coefficients don't fit this design, what to report instead) |
</phase_requirements>

## Summary

Phase 15 is not a library-integration phase — there is nothing to `pip install`. The two things a
planner actually needs are (1) a sound-enough measurement design for a spike (not a powered study),
and (2) a correct understanding of how this specific GSD/Claude Code execution environment routes
plan tasks to subagents, because that routing has a hard, verified consequence: **the standard
`gsd-executor` agent that normally runs a PLAN.md's `auto` tasks does not have the `Task` tool in
its permitted toolset**, and therefore cannot itself spawn the isolated blind-rating subagents
D-06 requires. This is not a hypothetical risk — it is confirmed by reading
`~/.claude/agents/gsd-executor.md`'s frontmatter (`tools: Read, Write, Edit, Bash, Grep, Glob,
mcp__context7__*` — no `Task`) against `~/.claude/agents/gsd-debug-session-manager.md`, which
DOES list `Task` and does use it to spawn a further subagent, proving the omission is a deliberate
allowlist restriction, not a platform limitation.

The fix is not a workaround Claude has to invent — it already exists in GSD's own plan-execution
routing. `execute-plan.md`'s segment-routing table resumes plan execution **in the main
(orchestrating) context — not a spawned subagent — for any task segment that follows a
`checkpoint:decision` or `checkpoint:human-action`**. Phase 15 already needs a
`checkpoint:human-action` for D-01's photo-attachment pause. If the plan places every Task-tool-
dependent step (the 5 blind calls, the 5-step anchored chain) in the segment immediately following
that checkpoint, those steps execute in a context that has full tool access, including `Task`. Get
this sequencing right and the phase is straightforwardly executable with existing GSD machinery.
Get it wrong (e.g. put the rating collection in an earlier `auto` segment, or in a plan with no
checkpoints at all) and the plan will fail at execution time with a missing-tool error the plan
author will have no way to anticipate from the PLAN.md text alone.

The second load-bearing finding concerns image mechanics: a photo pasted inline into a Claude Code
CLI session (`Ctrl+V`) becomes a `[Image #N]` chip that lives only in that conversation's turn — it
is NOT a filesystem path, and a freshly-spawned, isolated Task-tool subagent has no way to see it.
Only a real file path (typed directly, or produced by drag-and-drop, which — per a documented
Claude Code CLI bug/behavior — inserts a raw path as text rather than an inline image on several
terminals) is independently readable by an isolated subagent's `Read` tool. The plan must instruct
the human to provide a path-addressable file, then have the (main-context) session copy it into the
session's private scratchpad directory via `Bash cp`, and pass that scratchpad path — not today's
scratchpad path, which is session-specific and will be stale by execution time — to each subagent.

The third finding is about the measurement design itself: with one fixed photo-set rated 5 times,
this is a single-specimen repeatability study, not a multi-subject reliability study. Formal
coefficients (Cohen's kappa, ICC) assume multiple subjects and do not apply. The right "good
enough for a spike" metrics are exactly what the phase's own research questions already point to:
mode, range, and exact-agreement count per muscle group for the blind condition; first-vs-last
comparison and monotonic-direction counting for the anchored condition. External literature on LLM
anchoring bias (found this session, dated 2026, arXiv) independently corroborates the concern
D-08 already assumes: prior-score-as-context measurably and systematically shifts subsequent
judgments (one 2026 paper measured -0.706 points / -22.29 percentage points for Claude-4.5-Sonnet
specifically), and prompt-level mitigations (explicit warnings, chain-of-thought) are shown
ineffective or actively counterproductive. This means D-08's "accepted, monitored risk plus an
instruction-level note" framing is the empirically honest conclusion, not an undersold one — the
spike should expect to find *some* drift and should not be surprised if an instruction-only fix
does little, because the literature says instruction-only fixes generally don't work here.

**Primary recommendation:** Structure the plan so every Task-tool-dependent step is sequenced
after a `checkpoint:human-action` (satisfying both D-01 and the tool-availability constraint in
one move), resolve the scratchpad path dynamically at execution time, use plain descriptive
statistics (not fabricated formal coefficients) for the write-up, and write the recommended
constants directly into the spike record using `recomposition.py`'s exact
comment-then-constant idiom so Phase 16/17 can copy them verbatim.

## Architectural Responsibility Map

This phase has no web-app tiers (browser/API/DB) — its "architecture" is which GSD execution
context runs which step. This is the table that actually matters for planning correctness:

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Pause for photo attachment (D-01) | Main/orchestrating session (via `checkpoint:human-action`) | — | No CLI/API can fetch a user's private photo; this is a legitimate human-action gate, not automatable |
| Copy photo(s) into session scratchpad (D-02) | Main/orchestrating session (`Bash cp`) | — | Must happen once, from wherever the user's file landed, before any subagent needs the path; trivial for whichever context runs it, so keep it in the same segment as the checkpoint that unblocks it |
| Spawn 5 isolated blind-rating subagents (D-06) | Main/orchestrating session (has `Task` tool) | — | `gsd-executor` (the delegated subagent that runs ordinary `auto` tasks) does NOT have `Task` in its allowlist — verified against its frontmatter. This step is architecturally impossible inside a delegated `gsd-executor` segment |
| Run the 5-step anchored chain (D-06) | Main/orchestrating session (has `Task` tool) | — | Same constraint; additionally requires sequential (not parallel) execution since each step's prompt depends on the previous step's output |
| Record raw quoted outputs + write spike-record analysis (D-09) | Delegated `gsd-executor` (Write/Edit/Bash are sufficient) | Main session (if already there) | Pure file-writing and arithmetic on already-collected text — no `Task` tool needed, so this CAN run as a normal `auto` segment once the raw ratings exist as plain text in the plan's working context |
| Consuming the resulting constants | Phase 16 (`app/db/models` / schema) and Phase 17 (`app/analytics/physique.py`) | — | Out of this phase's scope; noted for completeness per the Integration Points already in CONTEXT.md |

## Standard Stack

**No new dependencies.** This phase produces no `backend/` code, no migration, no MCP surface
change (CONTEXT.md `<code_context>`: "no `app/analytics/physique.py` or physique schema exists
yet"). The "stack" relevant here is entirely the GSD/Claude Code execution environment already in
use for every phase — `Task` tool, `Read` tool (image-capable), the checkpoint protocol, and the
session-scratchpad convention. Nothing to install, nothing to pin a version of.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Isolated `Task`-tool subagent per blind rating (D-06, locked) | Same conversation, instructed to "rate fresh, ignore prior context" | Rejected by the user at discussion time (`15-DISCUSSION-LOG.md` Q "Should each blind rating be a fully isolated subagent call?") — a prompting convention is not structural blindness and the literature found this session shows prompt-level anchoring mitigations are unreliable anyway |
| `subagent_type="general-purpose"` for the rating calls | A dedicated custom `gsd-*` agent type | No existing `gsd-*` agent is designed as a blank visual rater; inventing one is out of proportion to a one-phase spike. `general-purpose` is Claude Code's documented full-capability default subagent type and is the pragmatic choice here — see Common Pitfalls for the tension this creates with GSD's own anti-pattern #10 |
| Plain descriptive stats (mode/range/exact-agreement count) | Cohen's kappa / intraclass correlation | ICC and kappa require multiple *subjects*; this design has one subject (one fixed photo-set) rated multiple times, which is a repeatability question, not an inter-rater-reliability question. Computing a kappa here would be dressing up N=1 data with a formula that doesn't apply — worse than reporting honestly, not better |

## Architecture Patterns

### System Architecture Diagram — data flow through this phase's execution

```
                         ┌─────────────────────────────┐
                         │  User (has real photos, D-01) │
                         └───────────────┬───────────────┘
                                         │ provides file path
                                         │ (typed path or drag-drop —
                                         │  NOT Ctrl+V inline paste, see Pitfall 2)
                         ┌───────────────▼───────────────┐
                         │ checkpoint:human-action         │
                         │ "attach/provide photo file(s)"  │
                         └───────────────┬───────────────┘
                                         │ resumes in MAIN context
                                         │ (execute-plan.md segment routing:
                                         │  after decision/human-action → MAIN,
                                         │  which HAS the Task tool)
                         ┌───────────────▼───────────────┐
                         │ MAIN: Bash cp → THIS session's  │
                         │ scratchpad dir (resolved NOW,   │
                         │ not hardcoded from planning time)│
                         └───────────────┬───────────────┘
                                         │ scratchpad photo path
                         ┌───────────────┴───────────────┐
                         │                                 │
              ┌──────────▼─────────┐          ┌───────────▼───────────┐
              │ BLIND CONDITION      │          │ ANCHORED CONDITION      │
              │ 5x Task() calls,     │          │ 5x Task() calls, SEQUENTIAL,│
              │ fully independent,   │          │ each fed prior step's   │
              │ fresh context each,  │          │ rating text as "prior   │
              │ same photo path,     │          │ observation" context    │
              │ same ~5-muscle prompt│          │ (mirrors PHYS-07)       │
              └──────────┬─────────┘          └───────────┬───────────┘
                         │ raw quoted ratings                │ raw quoted ratings
                         │ (5 independent draws)              │ (1 ordered chain, R1..R5)
                         └───────────────┬─────────────────┘
                                         ▼
                         ┌─────────────────────────────┐
                         │ ANALYSIS (can run as normal    │
                         │ delegated gsd-executor `auto`  │
                         │ segment — no Task tool needed) │
                         │  - per-muscle mode/range/exact- │
                         │    agreement count (blind)      │
                         │  - first-vs-last diff + monotonic│
                         │    direction count (anchored)    │
                         └───────────────┬───────────────┘
                                         ▼
                         ┌─────────────────────────────┐
                         │ 15-SPIKE-RESULT.md             │
                         │ (named constants + rationale,   │
                         │  raw quotes, dated verdict —    │
                         │  matches 13-SPIKE-RESULT.md)    │
                         └───────────────┬───────────────┘
                                         ▼
                     Phase 16 schema  +  Phase 17 analytics/physique.py
                     consume constants directly (PHYSIQUE_MIN_ELAPSED_DAYS,
                     confirmed/refined PHYS-01 anchor wording)
```

### Recommended Plan/Deliverable Structure

There is no `src/` tree for this phase. The equivalent structure is the plan-and-deliverable
layout:

```
.planning/phases/15-physique-rating-calibration-spike/
├── 15-RESEARCH.md              # this file
├── 15-01-PLAN.md                # checkpoint:human-action (photos) → MAIN segment:
│                                  copy to scratchpad, 5 blind Task() calls, 5-step
│                                  anchored Task() chain, record raw outputs verbatim
├── 15-01-SUMMARY.md             # produced by execution; must NOT contain any real
│                                  filesystem path outside the scratchpad, per D-02
└── 15-SPIKE-RESULT.md           # the actual deliverable ROADMAP success criterion #1
                                    requires — dated table, verdict, raw quotes,
                                    named constants + rationale (D-09)
```

A single plan is plausible here (unlike Phase 13's 10 plans) because the phase produces no
production code — but if the planner splits collection from analysis into two plans, the SECOND
plan (pure arithmetic + file writing over already-collected text) needs no checkpoint and no
`Task` tool, so it can run as an ordinary autonomous `gsd-executor` segment (Pattern A) with no
special handling.

### Pattern 1: Route Task-tool-dependent steps through the checkpoint-routing side-effect

**What:** `execute-plan.md`'s segment-routing table (read directly from the framework source this
session) is:

| Checkpoints in plan | Pattern | Where segments run |
|---|---|---|
| None | A | Entire plan in a spawned `gsd-executor` (restricted tools — **no `Task`**) |
| Only `human-verify` | B | Segments after none/`human-verify` → spawned `gsd-executor`. Segments after `decision`/`human-action` → **MAIN** |
| Contains `decision` | C | Entire plan runs in MAIN |

**When to use:** Any GSD plan step that needs a tool the delegated `gsd-executor` doesn't have
(here: `Task`). This is exactly Phase 15's situation.

**Example (task-sequencing, not literal code):**
```xml
<!-- Source: read from ~/.claude/get-shit-done/workflows/execute-plan.md this session -->

<task type="checkpoint:human-action" gate="blocking">
  <action>Provide the progress photo file(s) for the calibration spike</action>
  <instructions>
    I need a real photo (front/back/side from one session is fine — D-03 says one photo-set,
    rated repeatedly). Please either:
    1. Type the absolute file path in your reply, or
    2. Drag the file into this terminal (it will insert as a path — that is expected and fine)
    Do NOT paste with Ctrl+V — an inline pasted image is not a filesystem path and an isolated
    rating subagent cannot read it (see Common Pitfalls in 15-RESEARCH.md).
  </instructions>
  <verification>I will `ls` the path you give me and copy it into this session's scratchpad</verification>
  <resume-signal>Paste the absolute file path</resume-signal>
</task>

<!-- Everything below this line executes in MAIN because it follows a human-action checkpoint -->

<task type="auto">
  <name>Copy photo(s) into this session's private scratchpad</name>
  <action>
    Resolve THIS session's scratchpad directory (do not reuse a path from an earlier session —
    it is session-specific and will not exist). `mkdir -p` a physique-spike subdirectory inside
    it, `cp` the user-provided file(s) there.
  </action>
  <verify>`ls` the scratchpad subdirectory shows the copied file(s)</verify>
</task>

<task type="auto">
  <name>5 independent blind ratings</name>
  <action>
    For i in 1..5: spawn a Task-tool subagent (subagent_type="general-purpose" — see Common
    Pitfalls for why this deviates from anti-pattern #10 deliberately). Prompt: the scratchpad
    photo path, instructions to rate ~5 named muscle groups on the fixed 5-level scale, no
    mention of any other call. Record the FULL raw output verbatim before starting the next call.
  </action>
</task>
```

### Pattern 2: Anchored-chain sequencing must be strictly sequential, not parallel

**What:** The 5-step anchored chain (D-04/D-06) requires step N+1's prompt to contain step N's
actual output text. This is a data dependency, not just an ordering preference — parallelizing
these calls (e.g., firing all 5 at once and stitching later) would silently break the entire
premise of the anchoring test, since there would be no real "prior observation" for the model to
anchor to.

**When to use:** Any step in the plan building the anchored chain. Contrast explicitly with the
blind condition, which IS embarrassingly parallel (5 independent calls with no data dependency
between them) — the plan can (but need not) run those concurrently.

### Pattern 3: Detecting a ratchet that adjacent-pair diffs would miss

**What:** Production's `analytics/physique.py` (PHYS-09) will only ever diff two *adjacent*
observations. A slow, monotonic drift can be invisible at every single adjacent step (each step
reads "unchanged" or a plausible one-level "improved") while still being a real, cumulative,
spurious trend across the whole chain. Two concrete, spike-appropriate (not fabricated-statistics)
analyses catch this that an adjacent-only view cannot:

1. **First-vs-last comparison.** Run the SAME ordinal-diff function PHYS-09 will use directly
   between rating 1 and rating 5 of the anchored chain. If it reads "improved" or "regressed"
   despite the underlying photo never changing, that is direct evidence of a drift the
   adjacent-pair-only production design would never surface (each of the 4 intermediate diffs
   could individually read "unchanged").
2. **Monotonic-direction counting.** For each of the ~5 rated muscle groups, count how many of the
   4 step-to-step transitions in the anchored chain move in the same direction (all up, or all
   flat-or-up) versus how many are genuinely mixed (some up, some down). Compare this against the
   BLIND condition's five independent draws for the same muscle group, which have no sequential
   dependency and should show pure scatter if the underlying rating process is stable. A ratchet's
   signature is: blind condition shows scatter with no direction, anchored condition shows a
   one-directional staircase. This contrast — not a p-value — is the evidence a reviewer should
   expect (this matches the phase's own research question about avoiding "fabricated p-values").

**Source:** Reasoned from first principles (this is a within-reach experimental-design question,
not something requiring a citation), cross-checked against 2026 LLM-anchoring-bias literature
found this session — see State of the Art — which independently confirms that when sequential
anchoring bias is real, it shows up as a *systematic, one-directional* shift, not merely increased
variance, which is exactly what monotonic-direction counting is built to detect.

### Anti-Patterns to Avoid
- **Delegating the blind/anchored rating calls to a bare `auto` task with no preceding
  checkpoint:** This will fail at execution time — the spawned `gsd-executor` has no `Task` tool.
  There is no error-recovery path for this the plan author can script around after the fact; it
  must be prevented by task ordering at plan-writing time.
- **Hardcoding today's scratchpad path into the PLAN.md:** The scratchpad directory is
  session-specific (visible in this very research session's own system reminder) and will not
  exist, or will belong to the wrong session, by the time this plan executes in a future session.
  The plan must instruct the executing agent to resolve its OWN current scratchpad path at
  execution time.
- **Treating the blind condition's 5 draws as if they came from 5 different "raters":** They are 5
  independent draws from the same model under the same instructions on the same unchanged input.
  Framing this as inter-rater reliability (implying multiple distinct judges) misdescribes the
  design; it is single-instrument repeatability. Say so plainly in the record rather than importing
  reliability-statistics vocabulary that implies a different (and here, inapplicable) study design.
- **Computing a fabricated p-value or confidence interval to look rigorous:** The phase's own
  research questions explicitly warn against this. With N=5 non-independent-sample draws on one
  specimen, any p-value would misrepresent the actual evidentiary weight. Report counts and modes
  instead — an honest N=5 is more useful to Phase 16/17 than a spurious-precision statistic.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Structural blindness between repeat ratings | A prompting convention ("pretend this is your first time seeing this") inside one shared conversation | D-06's isolated `Task`-tool subagent per call (already locked) | The 2026 anchoring-bias literature found this session shows prompt-level mitigations (explicit warnings, chain-of-thought) are unreliable or actively counterproductive; only genuine context separation reliably removes the anchor |
| Getting a photo into an isolated subagent's view | Embedding image bytes/base64 directly in the `Task` prompt string | A real filesystem path inside the session scratchpad, read via the subagent's own `Read` tool call | `Task` prompts are text; there is no verified mechanism in this environment for passing binary/image payloads through a `Task` call's prompt argument. A path is the only mechanism confirmed to work (this is also literally how the `Read` tool is documented to work) |
| Reliability measurement | A hand-rolled Cohen's kappa/ICC calculation shoehorned onto N=1-specimen data | Plain mode, range, and exact-agreement-count per muscle group (blind); first-vs-last diff + monotonic-direction count (anchored) | Kappa/ICC are defined for multiple subjects rated by multiple raters; using them here would misapply a formula outside its assumptions, producing a number that looks rigorous but measures nothing real |
| Deciding whether a checkpoint routes to MAIN vs a subagent | Reinventing checkpoint semantics inside the PLAN.md's prose (e.g. writing "please run this in the main session" as a note, hoping the executor honors it) | The `checkpoint:human-action` type itself, placed immediately before the Task-tool-dependent segment | This routing behavior is already built into `execute-plan.md`'s segment parser — it triggers on checkpoint TYPE, not on prose instructions inside a task's `<action>` field |

**Key insight:** every apparent "build vs. reuse" decision in this phase resolves the same way —
GSD's existing checkpoint/segment-routing mechanism and the model's own `Read`-tool image support
already solve the mechanical problems; the only genuine, unavoidable "build" work is the plan's
prompt wording and the analysis arithmetic, both of which are explicitly Claude's discretion per
CONTEXT.md.

## Common Pitfalls

### Pitfall 1: `gsd-executor` cannot spawn the isolated rating subagents D-06 requires
**What goes wrong:** A plan with a plain `auto` task saying "spawn 5 isolated Task-tool subagents
to rate the photo blind" will be handed to a spawned `gsd-executor`, which does not have `Task` in
its tool allowlist (`~/.claude/agents/gsd-executor.md` frontmatter: `tools: Read, Write, Edit,
Bash, Grep, Glob, mcp__context7__*`). The task will fail or the executor will improvise something
that isn't actually isolated (e.g., reading the photo itself and writing 5 slightly-reworded
ratings in the same context, defeating D-06 entirely, likely without flagging this as a deviation
since "I did something plausible" doesn't always get self-reported as a blocker).
**Why it happens:** GSD deliberately restricts `gsd-executor`'s toolset (this is the same
mechanism behind the documented Context7-MCP-stripping bug referenced in multiple agent files —
`tools:` frontmatter restrictions have real, enforced effects, not just documentation value).
**How to avoid:** Sequence every `Task`-dependent step in the segment immediately following a
`checkpoint:human-action` (or `checkpoint:decision`), per `execute-plan.md`'s routing table, so
those steps execute in MAIN context instead of a spawned `gsd-executor`. See Architecture Pattern 1.
**Warning signs:** If the plan's checkpoint for photo-attachment is placed AFTER the rating-
collection tasks, or if the plan has zero checkpoints at all, this pitfall is live.

### Pitfall 2: An inline-pasted image is not a file path an isolated subagent can read
**What goes wrong:** If the human-action checkpoint's instructions allow `Ctrl+V` clipboard paste,
the photo becomes an `[Image #N]` chip inside the current conversation turn — visible to the
top-level session, but NOT independently accessible to a freshly-spawned `Task`-tool subagent,
which has no shared memory with the parent conversation (that lack of shared memory is precisely
D-06's blindness guarantee — it cuts both ways).
**Why it happens:** Clipboard-paste in Claude Code CLI is documented (found this session) to embed
the image inline rather than write it to a stable path, and this behavior is platform-dependent
(reliable on macOS, known to silently fail on Windows/WSL).
**How to avoid:** The checkpoint's `<instructions>` should explicitly ask for a typed absolute file
path or drag-and-drop (which — per a documented Claude Code CLI behavior/bug — inserts the raw
path as text on several terminals, which is actually the outcome this design wants). Verify with
`ls` before proceeding, exactly as the `checkpoint:human-action` schema's `<verification>` field
is meant to be used.
**Warning signs:** If the checkpoint text tells the user to "paste a screenshot," this pitfall is
live; "give me the file path, or drag the file in" is the safe instruction.

### Pitfall 3: Using `general-purpose` as the rating subagent's type creates a tension with GSD's own anti-pattern #10
**What goes wrong:** `references/universal-anti-patterns.md` rule 10 states: "NEVER use non-GSD
agent types (`general-purpose`, `Explore`, `Plan`, `Bash`, `feature-dev`, etc.) — ALWAYS use
`subagent_type: gsd-{agent}`." No existing `gsd-*` agent is designed to be a blank visual rater, so
literal compliance would mean inventing a new, permanent `gsd-*` agent definition for a one-phase
spike, which is disproportionate.
**Why it happens:** Anti-pattern #10 was written for GSD's own internal orchestration (planning,
executing, researching) where a project-aware, audit-logged persona is exactly what's wanted. This
spike's rating calls are experimental instruments measuring how a NEUTRAL, non-project-aware model
call behaves — the anti-pattern's stated rationale ("GSD agents have project-aware prompts, audit
logging, workflow context") does not straightforwardly apply to a call that specifically should
NOT be contaminated by GSD workflow framing.
**How to avoid:** Document the choice of `subagent_type="general-purpose"` in the plan as a
deliberate, narrow exception to anti-pattern #10, scoped explicitly to this phase's measurement
calls, with the one-line justification above. Do not silently violate the anti-pattern without
comment, and do not over-engineer a new permanent agent type to satisfy it literally.
**Warning signs:** A plan-checker or reviewer flagging "why is this using `general-purpose`" with
no accompanying justification in the plan text.

### Pitfall 4: `general-purpose` subagents automatically receive this repo's `CLAUDE.md`
**What goes wrong:** Per Claude Code's documented subagent context model, a `general-purpose`
subagent receives "CLAUDE.md and memory hierarchy" automatically. This means every rating call
(blind and anchored alike) is implicitly primed with BRETT's project framing (fitness coach
persona, tech-stack context, etc.), not a neutral image classifier's framing.
**Why it happens:** This is standard Claude Code subagent context injection, not something the
plan does deliberately.
**How to avoid:** This is likely a feature, not a bug, here — CONTEXT.md wants the spike to mirror
"exactly how PHYS-07 will work in production," and production ratings will also happen inside a
Claude-as-coach context. Because CLAUDE.md content is IDENTICAL and constant across all 10 calls
(5 blind + 5 anchored), it cannot differentially bias one condition relative to the other — it is
a controlled constant, not a confound. Note this explicitly in the spike record so a future reader
doesn't mistake it for an oversight.
**Warning signs:** None operationally — this is a documentation-completeness pitfall, not an
execution one.

### Pitfall 5: Committed artifacts (SUMMARY.md, the spike record) must never leak a real filesystem path or identifying photo description
**What goes wrong:** GSD's standard flow commits `SUMMARY.md` and the spike-record file to git
(`commit_docs: true` in this repo's config). If a task casually logs "copied
`/Users/name/Desktop/progress-photo-front.jpg` to scratchpad" into a committed file, that violates
D-02's "never referenced in planning docs beyond the ephemeral scratchpad path."
**Why it happens:** Standard GSD executor behavior is to document what it did, including file
paths, as a matter of course (this is normally desirable for auditability).
**How to avoid:** Explicitly instruct the plan's tasks to log only that a photo was provided and
processed (e.g., "photo received, copied to session scratchpad, rated"), never the literal source
path or any descriptive content about the photo itself, in any file destined for a git commit.
Keep the raw quoted MODEL OUTPUT (ordinal ratings + structural reasoning text) in the spike record
— that's required for evidentiary rigor per `13-SPIKE-RESULT.md`'s precedent and is not the same
thing as photo content or a filesystem path.
**Warning signs:** Any absolute path outside `.planning/` appearing in a `git diff` for this phase.

### Pitfall 6: Don't waste a rating slot on a muscle group that's permanently not-assessable
**What goes wrong:** PHYS-02 already establishes `abductors` and `adductors` as "expected to be
permanently not-assessable from standard photos." Including either in the ~5-group spike sample
would burn a call slot on a group that structurally cannot produce a meaningful ordinal signal.
**Why it happens:** Picking groups without cross-referencing the muscle taxonomy's documented
photo-assessability notes.
**How to avoid:** Use CONTEXT.md's own suggested subset (chest, lats, biceps, abs, side_delts) or
an equivalent mix of visually-obvious (chest, biceps) and genuinely-ambiguous-but-assessable
(side_delts, obliques) groups — never the two structurally-excluded ones.
**Warning signs:** `abductors`/`adductors` appearing in the spike's rated-groups list.

## Code Examples

### The exact constant-with-rationale idiom the spike record's output constants must follow
```python
# Source: backend/app/analytics/recomposition.py, read directly this session (lines 77-100)

# D-11. The stricter end of the published 0.25-0.5%/week lean-bulk band, chosen to keep gains lean
# rather than tolerate a faster, fattier surplus. Evaluated against D-16's SMOOTHED rate.
WEIGHT_GAIN_TOO_FAST_PERCENT_PER_WEEK = Decimal("0.25")

# The "weight stable" dead-band. CONTEXT.md supplies the two OUTER thresholds but not this one,
# and blueprint 26's enum needs it to distinguish `weight_stable` from `likely_muscle_gain` and
# `likely_fat_loss`. One tenth of D-11's own threshold rather than an independent invention: at
# this user's ~65 kg that is ~65 g/week, comfortably below what a 7-day average over 3-6 weigh-ins
# can resolve, so a narrower band would classify measurement noise as a direction.
WEIGHT_STABLE_BAND_PERCENT_PER_WEEK = Decimal("0.10")
```

The pattern that MUST be reproduced in `15-SPIKE-RESULT.md` for D-09's constants: a comment block
that (a) states the concrete measured behavior that justifies the number, (b) explains WHY that
number and not a nearby alternative, (c) references the deciding evidence by name. For example
(illustrative form only — the actual VALUE must come from the real spike, not be invented here):

```python
# PHYS-12 spike (2026-MM-DD, 15-SPIKE-RESULT.md): 5 blind ratings on one unchanged photo-set
# showed <describe actual observed movement — e.g. "0/5 muscle groups moved more than one level;
# exact agreement 4/5 or better on N of 5 groups">. The anchored 5-step chain <describe observed
# first-vs-last diff and monotonic-direction count>. Set above the largest elapsed interval at
# which spurious movement was still observed in <condition>, with margin for real photos varying
# more than this session's fixed set.
PHYSIQUE_MIN_ELAPSED_DAYS = <value from actual spike data>
```

### Checkpoint + main-context-routing task sequencing (GSD-native, not custom)
```xml
<!-- Source: pattern derived from ~/.claude/get-shit-done/references/checkpoints.md
     (checkpoint:human-action schema) + ~/.claude/get-shit-done/workflows/execute-plan.md
     (segment routing table), both read directly this session -->

<task type="checkpoint:human-action" gate="blocking">
  <action>Provide the progress photo file(s) for the physique rating calibration spike</action>
  <instructions>
    One real photo-set (front/back/side from a single session is fine, per D-03). Reply with
    the absolute file path, or drag the file into this terminal window.
  </instructions>
  <verification>I will `ls` the given path and copy it into this session's scratchpad directory</verification>
  <resume-signal>Provide the absolute file path</resume-signal>
</task>

<!-- Everything after this checkpoint resumes in MAIN context (has Task tool) per execute-plan.md's
     "After decision/human-action → MAIN" segment-routing rule. -->
```

## State of the Art

| Old/naive assumption | Current evidence (2026) | When surfaced | Impact on this phase |
|--------------------|--------------------------|----------------|----------------------|
| "Tell the model not to be biased by the prior score and it won't be" | A 2026 arXiv study ("Anchoring Bias in LLM-as-a-Judge Systems: Prior Scores Compromise Evaluation Independence") found explicit warning prompts achieve only ~6.7% reduction in the bias, and chain-of-thought reasoning WORSENS numeric anchoring by ~47.7% in absolute magnitude; 7 of 8 tested models showed statistically significant anchoring | This session, via WebSearch + WebFetch | D-08's "accepted, monitored risk + instruction-level mitigation, not a structural fix" framing should be read as realistic, not as an undersold compromise — the literature says a structural fix (i.e., not feeding prior context at all) is the only thing shown to reliably work, and that's explicitly NOT what PHYS-07 does (PHYS-07 deliberately returns prior observation as context) |
| "Self-review/self-correction in one context is basically the same as a fresh look" | "Cross-Context Review: Improving LLM Output Quality by Separating Production and Review Sessions" (arXiv, found this session) shows genuinely isolated contexts (not same-session self-critique) measurably improve independence of judgment | This session, via WebSearch + WebFetch | Directly validates D-06's isolated-`Task`-call design for the BLIND condition — this is not an arbitrary rigor preference, it matches a documented, effective mitigation pattern in the literature |
| "Reliability of a rating scale = compute a kappa" | Kappa/ICC require multiple subjects × multiple raters; a single fixed photo-set rated repeatedly by the same model is a repeatability (test-retest), not inter-rater-reliability, design — percentage agreement and descriptive spread are the standard treatment for this case per general measurement-methodology literature | This session, via WebSearch | The spike record should report mode/range/exact-agreement counts, not a fabricated kappa — matches the phase's own stated research question almost verbatim |

**Deprecated/outdated:** None — this is a fast-moving, primary-literature area (most sources found
are 2026 preprints); treat any specific numeric finding above as illustrative of magnitude and
direction, not as a number to cite as settled science.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | A `Task`-tool subagent spawned with `subagent_type="general-purpose"` and given a file path in its prompt can independently call `Read` on that path and view the image, exactly as the top-level session's own `Read` tool does | Architecture Patterns, Common Pitfalls 2/4, Code Examples | If wrong, the entire isolated-subagent design (D-06) needs a different mechanism (e.g., the main session reads the photo itself and somehow forwards a description — which would NOT be structurally blind). Verify with a single live test call early in execution, before running all 10 calls, so a design problem surfaces on call 1, not call 10 |
| A2 | Segments following a `checkpoint:human-action` in a GSD plan execute in the MAIN/orchestrating context (with full tool access including `Task`), not in a spawned `gsd-executor` | Summary, Architecture Pattern 1, Pitfall 1 | This is read directly from `execute-plan.md`'s routing table and is HIGH confidence as a framework-behavior claim, but it has not been empirically observed in THIS repo for a nested-Task-tool scenario. If the router behaves differently in practice (e.g. resumes with a fresh `gsd-executor` anyway), the plan needs a fallback: the FIRST task in that segment should defensively check for `Task`-tool availability and escalate immediately (not after burning several calls) if it's absent |
| A3 | `general-purpose` subagents automatically receive this repo's `CLAUDE.md` and therefore carry identical BRETT/coaching framing across all 10 rating calls, making it a controlled constant rather than a confound | Common Pitfalls 4 | If subagent context injection actually varies per-call (e.g. only sometimes includes CLAUDE.md, or truncates it differently), the "controlled constant" argument weakens and the spike record should note this as a limitation rather than dismiss it |
| A4 | Drag-and-drop of an image file into the Claude Code CLI terminal inserts a raw, independently-readable file path (rather than an inline, non-path-addressable image chip) on the user's actual platform (macOS, per this repo's `env` block) | Pitfall 2, Code Examples | If macOS drag-and-drop instead behaves like `Ctrl+V` (inline chip, no path), the checkpoint's fallback instruction — ask for a typed path directly — is the one to rely on; the plan should offer both, with "type the path" as the guaranteed-to-work option |

## Open Questions

1. **Does this specific Claude Code CLI build actually grant `Task`-tool access to the MAIN
   context that resumes after a `checkpoint:human-action`, with no additional restriction?**
   - What we know: `execute-plan.md`'s routing table explicitly names this as the "MAIN" route,
     and MAIN is described elsewhere as having full, unrestricted tool access (it is the
     top-level orchestrating agent, not a `tools:`-restricted subagent definition).
   - What's unclear: whether any additional restriction (e.g. a plugin/permission-mode setting)
     could still block a fresh `Task` call from MAIN in this particular installation.
   - Recommendation: the plan's first post-checkpoint task should be a cheap, single `Task`-tool
     smoke-test call (e.g., spawn one subagent, ask it to read the photo and report back one
     muscle group's rating) before committing to all 10 calls — fail fast and visibly if the
     mechanism doesn't work as expected, rather than discovering it after burning most of the
     budget.

2. **What exact prompt wording should the anchored chain use to present "prior observation," so
   it faithfully mirrors PHYS-07's eventual production behavior?**
   - What we know: PHYS-07 will be "a read tool [that] returns the most recent prior
     observation — ratings, notes and confounder metadata" (REQUIREMENTS.md), and this is
     explicitly Claude's discretion at execution time (CONTEXT.md).
   - What's unclear: PHYS-07's actual return-value SHAPE doesn't exist yet (Phase 16/17 haven't
     built the schema) — the spike is calibrating a mechanism whose eventual real interface is
     still undesigned.
   - Recommendation: approximate a plausible shape now (muscle-group ratings as a short list, plus
     a one-line qualitative note per group), note in the spike record that this is an
     approximation of PHYS-07's not-yet-designed exact schema, and flag for Phase 17 that if the
     real schema differs meaningfully in HOW MUCH context it exposes (e.g. richer notes vs. bare
     ratings), the anchoring magnitude measured here may not transfer exactly.

3. **Should `PHYSIQUE_MIN_ELAPSED_DAYS` interact with PHYS-F01 (deferred) at all?**
   - What we know: D-07 explicitly limits this spike's authority to "a recommended minimum-
     elapsed-time floor" as an open constant, while PHYS-F01 (a hard floor that refuses/flags a
     too-close observation) is explicitly deferred and D-08 says finding a ratchet does NOT
     promote PHYS-F01 out of deferred status.
   - What's unclear: whether "recommended... floor" means an enforced constant somewhere in
     Phase 16/17's code, or purely a documented number with no code path checking it (since
     PHYS-F01, the actual enforcement mechanism, is deferred).
   - Recommendation: the spike record should state explicitly which of these two it means —
     most likely a documented constant with NO enforcement yet (consistent with D-08's "does NOT
     trigger... promoting PHYS-F01 out of deferred status") — so Phase 16/17's planners don't
     accidentally build enforcement that oversteps this phase's stated authority.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `Task` tool in MAIN/orchestrating context | Spawning 10 isolated rating subagents (D-06) | ✓ (by design — MAIN is the unrestricted top-level context) | — | If unavailable (Open Question 1), no fallback exists that preserves structural blindness; would require re-discussing D-06 with the user |
| `Task` tool in delegated `gsd-executor` context | N/A — deliberately NOT relied upon | ✗ (verified via frontmatter) | — | Route these steps to MAIN instead (Architecture Pattern 1) — this IS the fallback, already designed in |
| `Read` tool image support (PNG/JPG) | Every rating subagent reading the scratchpad photo | ✓ (documented tool behavior, consistent across every agent definition read this session) | — | — |
| User has real, ready photos | D-01 | Unconfirmed until the future execution session — CONTEXT.md states the user affirmed readiness at discussion time | — | `checkpoint:human-action` already the correct mechanism if not actually ready when the plan reaches that step |
| macOS `Ctrl+V` clipboard image paste | NOT recommended for this design (Pitfall 2) | ✓ reliable on macOS per this session's WebSearch findings | — | Prefer typed path or drag-and-drop regardless — avoids the dependency entirely |
| Session-scratchpad directory | D-02 | ✓ (present in every session per the standing system reminder) | — | — |

**Missing dependencies with no fallback:** None identified — the one theoretical gap (Open
Question 1) has an explicit early-detection recommendation (smoke-test call) rather than a true
blocking dependency.

**Missing dependencies with fallback:** `gsd-executor`'s missing `Task` tool — fallback is
re-routing via checkpoint segment placement (already the primary recommendation, not a
degraded-mode fallback).

## Validation Architecture

This phase produces zero application code, so the standard pytest-based Requirements→Test Map
does not apply in the usual sense. `13-RESEARCH.md`'s precedent for a manual-only spike
requirement (RPT-03) is the model to follow: mark PHYS-12 `manual-only` with no automated command,
same as that phase did for its own live-connector spike.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 + pytest-asyncio 1.4.0 (project-wide convention; not exercised by this phase — no code changes) |
| Config file | `backend/pyproject.toml` (unchanged by this phase) |
| Quick run command | N/A — no code to run |
| Full suite command | `uv run pytest` (should still pass, unchanged, since nothing in `backend/` is touched — worth a single confirmatory run at phase close to prove this phase truly made zero code changes) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PHYS-12 | Spike measures rating movement (blind + anchored), documents ratchet risk, states recommended constants | manual-only | N/A — human-gated by D-01's photo-attachment pause; the "test" is `15-SPIKE-RESULT.md`'s own evidentiary rigor (raw quotes, dated verdict) reviewed by the plan-checker/verifier, not an automated assertion | N/A |

### Sampling Rate
- **Per task commit:** N/A (no code)
- **Per wave merge:** `uv run pytest` — confirms this phase changed zero backend behavior (a full green run with no new/changed tests is itself the expected, correct outcome)
- **Phase gate:** `15-SPIKE-RESULT.md` exists, is dated, states a verdict, quotes raw model output for both conditions, and states concrete named constants — this document's completeness IS the phase gate (ROADMAP success criterion #4: "Phase 16's observation schema is not started until this result exists")

### Wave 0 Gaps
None — existing test infrastructure is untouched and sufficient; there is no test infrastructure
gap because there is no code to test.

## Security Domain

No new API/auth/DB surface (ASVS's usual categories are not applicable — no code ships). The one
real, live security-relevant concern is data handling of a privacy-sensitive artifact (a real body
photo), which this project already treats as a milestone-gate-level constraint ("BRETT never
stores an image" — `.planning/PROJECT.md`).

| Concern | Applies | Standard Control |
|---------|---------|-------------------|
| Sensitive-data minimization (photo never persisted beyond the ephemeral session) | Yes | Session-scratchpad-only handling (D-02), never written to any git-tracked path — enforced by plan-writing discipline (Pitfall 5), not by code, since no code exists in this phase |
| Sensitive-data leakage into committed artifacts | Yes | `SUMMARY.md`/spike-record tasks must log only that a photo was processed, never the literal source path or descriptive photo content (Pitfall 5) |
| Injection/auth/session categories (V2-V6) | No | Not applicable — no MCP tool, no HTTP endpoint, no database write in this phase |

### Known Threat Patterns for this phase's stack
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| A real filesystem path or photo description accidentally committed to git via a SUMMARY.md or spike-record file | Information Disclosure | Explicit plan-writing discipline (never log source paths/photo descriptions in committed files); a human review of the final `git diff` before committing this phase's artifacts is a reasonable manual gate given there's no automated test for "no image content leaked" |

## Sources

### Primary (HIGH confidence — verified by direct file read this session)
- `~/.claude/agents/gsd-executor.md` frontmatter — confirms `tools:` list has no `Task`
- `~/.claude/agents/gsd-debug-session-manager.md` — confirms `Task` IS a grantable GSD-agent tool, and is used for real nested subagent spawning (`Task(..., subagent_type="gsd-debugger", ...)`), proving `gsd-executor`'s omission is deliberate
- `~/.claude/get-shit-done/workflows/execute-plan.md` — segment-routing table (`parse_segments`, `segment_execution`, `execute` steps) — the "None→A, Verify-only→B (subagent unless preceded by decision/human-action, then MAIN), Decision→C (all MAIN)" routing rule
- `~/.claude/get-shit-done/references/checkpoints.md` — `checkpoint:human-action` schema and the golden rule ("if it has CLAUDE/API, Claude does it; user only does what requires human judgment")
- `~/.claude/get-shit-done/references/universal-anti-patterns.md` rule 10 — the `gsd-{agent}`-only subagent-type rule this phase's design has to knowingly, narrowly deviate from
- `.planning/milestones/v2.0-phases/13-health-analytics-reports-coaching-style/13-SPIKE-RESULT.md` and `13-RESEARCH.md`'s Validation Architecture section — the evidentiary format and manual-only test-mapping precedent this phase mirrors
- `backend/app/analytics/recomposition.py` — the exact constant-with-rationale-comment idiom (`WEIGHT_GAIN_TOO_FAST_PERCENT_PER_WEEK`, `WEIGHT_STABLE_BAND_PERCENT_PER_WEEK`, `RECOMP_LOOKBACK_WEEKS`)
- `backend/app/normalization/muscles.py` — the 19-value `CanonicalMuscleGroup` enum
- `.planning/phases/15-physique-rating-calibration-spike/15-CONTEXT.md` and `15-DISCUSSION-LOG.md` — locked decisions and the alternatives considered at discussion time
- `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`, `.planning/STATE.md` — PHYS-12 text, phase success criteria, milestone-gate decisions

### Secondary (MEDIUM confidence — WebSearch/WebFetch, cross-checked against multiple results)
- "Anchoring Bias in LLM-as-a-Judge Systems: Prior Scores Compromise Evaluation Independence" (arXiv 2608.25869, fetched this session) — quantified anchoring magnitude, ineffective prompt-level mitigations
- "Cross-Context Review: Improving LLM Output Quality by Separating Production and Review Sessions" (arXiv 2603.12123, fetched this session) — validates context-isolation as an effective mitigation mechanism
- "Anchors in the Machine: Behavioral and Attributional Evidence of Anchoring Bias in LLMs" (arXiv 2511.05766) — corroborating secondary source on LLM anchoring generally
- Claude Code CLI image-attachment behavior (Ctrl+V vs. drag-and-drop vs. typed path; macOS vs. Windows/WSL reliability) — multiple 2026 blog/guide sources plus a GitHub issue (`anthropics/claude-code#48153`) describing the drag-and-drop-inserts-a-path behavior
- General-purpose subagent context injection (receives CLAUDE.md, git status, full tool capability) — multiple 2026 Claude Code subagent guide sources, cross-checked against this repo's own observed agent-definition conventions

### Tertiary (LOW confidence — single-source or reasoned-not-verified)
- Percentage-agreement (≥70%) as a common informal threshold in test-retest ordinal-scale literature — single PMC source, offered as a reference point only, not a bar this spike is required to clear
- The specific recommendation to use `subagent_type="general-purpose"` for the rating calls — this is a reasoned recommendation given no `gsd-*` agent fits, not something confirmed against an authoritative "this is the correct choice" source; flag for the planner/user to confirm rather than treat as settled

## Metadata

**Confidence breakdown:**
- GSD execution-mechanics findings (tool restriction, checkpoint routing): HIGH — verified by direct source reads of the actual framework files in use
- Image-ingestion mechanics (path vs. inline paste): MEDIUM — corroborated by multiple 2026 sources and a filed GitHub issue, but not independently tested in this exact environment
- Measurement-design recommendations (mode/range/exact-agreement, first-vs-last, monotonic count): MEDIUM — sound methodology reasoning, cross-checked against literature, but the actual numbers this design will produce are LOW confidence by definition (that unknown IS the spike's purpose)
- Standard stack: N/A — no new dependencies

**Research date:** 2026-09-08
**Valid until:** Treat the GSD execution-mechanics findings as valid until the GSD framework version changes (check `gsd-executor.md`'s frontmatter again if `~/.claude/get-shit-done` has been updated since this date). Treat the anchoring-bias literature as current for roughly 90 days — this is an actively-moving research area.
