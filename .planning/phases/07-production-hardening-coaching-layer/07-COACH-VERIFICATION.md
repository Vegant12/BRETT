---
phase: 07-production-hardening-coaching-layer
verified: 2026-09-01T13:47:01Z
status: passed
score: 3/4 criteria verified (Truth 4 PARTIAL — the guardrail was never exercised; see Gaps)
overrides_applied: 0
---

# Phase 7: Coaching Layer UAT (D-09)

Verifies ROADMAP Phase 7 success criterion #4: "The coaching system-prompt/instructions document
exists, and with it loaded Claude answers 'Am I progressing?' and 'Which muscles are
undertrained?' from real synced data, correctly flagging stale or sparse data when present."

**This is a human-verified checkpoint, not a claim inferred from code.** No automated test in
this repo can observe a Claude Project's behaviour; the automatable half of COACH-01 is
`backend/tests/test_coaching_doc.py`, which proves only that the document names real tools.

**Redaction rule for this file:** no credential value, no connection string and no
`Authorization` header value is ever recorded. Transcript excerpts are quoted for their tool
choices and their metadata handling, not for the training data they contain.

**Status:** `passed`, with one criterion honestly short of it. Task 1 (preconditions) is recorded
below. Task 2 — the UAT itself, a `checkpoint:human-verify` — ran on 2026-09-01 and its result is
recorded from *Setup* onward. Truths 1, 2 and 3 are `VERIFIED`. **Truth 4 is `PARTIAL`**: the
staleness guardrail was never exercised, because the premise that made step 5 a reliable probe —
"the synced history does not stretch back 52 weeks" — turned out to be false. That is a defect in
the UAT's test design, not evidence that the coaching document fails at that behaviour, and it is
recorded as `PARTIAL` rather than rounded up (T-07-56).

## Preconditions (verified 2026-09-01)

Every row was run against the live system on 2026-09-01, between 13:05Z and 13:09Z. Nothing here
is quoted from a prior plan's record: the earlier plans' claims are what these commands were run
to re-confirm, per the plan's "confirm each, do not assume".

| # | Precondition | Command | Observed | Pass/Fail |
|---|---|---|---|---|
| 1 | `MCP_AUTH_MODE` is `authkit` | `gcloud run services describe brett --region=us-central1 --format='json(spec.template.spec.containers[0].env)'` | `MCP_AUTH_MODE = authkit`. Both secret bindings intact — `DATABASE_URL` ← `brett-database-url:latest`, `MCP_AUTH_SECRET` ← `brett-mcp-auth-secret:latest` (names only, no values read). `MCP_RESOURCE_URL = https://brett-792870654598.us-central1.run.app/mcp`, `MCP_ALLOWED_HOSTS` names both assigned hostnames, `RATE_LIMIT_PER_MINUTE=30`, `RATE_LIMIT_BURST=30` | **PASS** |
| 2 | Live revision | `gcloud run services describe brett --region=us-central1 --format='value(status.latestReadyRevisionName,status.url)'` plus `--format='json(status.traffic)'` | **`brett-00009-fsm`**, `latestRevision: true`, **100%** of traffic. This is 07-09's flip-back revision, so the UAT tests the post-rotation service, not the pre-rotation one | **PASS** |
| 3 | Last sync execution succeeded, timestamp | `gcloud run jobs executions list --job=brett-sync-hevy --region=us-central1 --limit=1 --format='value(metadata.name,metadata.creationTimestamp,status.succeededCount)'` | `brett-sync-hevy-6vl4w` · `2026-09-01T11:23:41.953676Z` · `succeededCount 1`. Read at `2026-09-01T13:05:35Z` → **1 h 42 min old**, well inside the 12-hour bound | **PASS** |
| 4 | Scheduler `ENABLED`, `0 */6 * * *`, `Asia/Jakarta` | `gcloud scheduler jobs describe brett-sync-hevy-6h --location=us-central1 --format='value(schedule,timeZone,state)'` | `0 */6 * * *` · `Asia/Jakarta` · **`ENABLED`** — all three exactly as specified | **PASS** |
| 5 | `test_coaching_doc.py` green | `uv run pytest backend/tests/test_coaching_doc.py -x -q` | `4 passed in 0.49s`, exit `0`. The document still names only tools that exist in the live registry | **PASS** |
| 6 | Full suite green | `uv run pytest backend/tests -q` | **`687 passed in 34.29s`**, exit `0` (`FULL_SUITE_EXIT=0` captured explicitly). Up from the 683 recorded in `07-DEPLOY-RECORD.md`, consistent with the test modules added by plans 07-07 through 07-09 | **PASS** |

**All six PASS, so the plan proceeds.** Any FAIL here would have stopped it: a UAT run against a
stale revision or an unsynced database proves nothing.

### Two supporting facts, confirmed rather than assumed

- **Production holds real data.** `07-06-DEPLOY-RECORD.md` recorded `data_available: false` as an
  honest FAIL and named this plan as the second, unskippable gate on that fact. Plan 07-07 closed
  it: **327 workouts, 463 exercise templates, 125 body measurements** are in production Postgres
  (`hevy_sync_all_completed mode=full workouts=327 templates=463 body=125`). The workout and
  template counts match `docs/hevy-api-observations.md` exactly. The UAT is therefore being asked
  to read a populated database, which is the precondition that made 07-06's checkpoint fail.
- **The endpoint answers anonymously right now.** `GET /health` → `200`
  `{"status":"ok","database":"connected"}`; `GET /.well-known/oauth-protected-resource/mcp` → `200`
  with `resource` byte-identical to `MCP_RESOURCE_URL` and a single `authorization_servers` entry
  naming the real AuthKit tenant. Both anonymous, so neither required reading a secret.

### BLOCKER FOUND IN TASK 1 — `minScale` has regressed to `0` again

**This must be resolved before Task 2 runs, and it is not a theoretical risk.**

The service annotations on `brett-00009-fsm` read:

```
run.googleapis.com/maxScale: "2"
run.googleapis.com/minScale: (absent — i.e. 0)
```

This is the exact regression `07-06-DEPLOY-RECORD.md` § *Deviations* predicted:
`scripts/deploy-cloud-run.sh` passes `--min="${BRETT_MIN_INSTANCES:-0}"` unconditionally, so
plan 07-09's flip-back deploy silently cleared the `--min=1` that had been restored by hand after
the 07-06 deploy. The follow-up to fix the script was deferred, so the regression recurred exactly
as predicted.

**Measured evidence, not inference.** The first anonymous `GET /health` of this session took:

```
[HTTP 200 in 16.213946s]     <- cold start
[HTTP 200 in 0.442104s]      <- warm, immediately after
```

**16.2 seconds against Claude's documented 10-second discovery budget.** `02-DEPLOY-LOG.md`
measured a 7.53 s cold start and concluded on that basis alone that `--min=1` is "a **hard
prerequisite** for any Claude connector test". Task 2 *is* a Claude connector test, and the
observed cold start is now more than twice the budget. At `--min=0`, if the service scales to zero
before the developer opens Claude, the connector will present as "Couldn't reach the MCP server"
for reasons that have nothing to do with the coaching document — and a failed UAT would be
attributed to the wrong cause.

**Attempted fix, and its outcome.** The restoring command needs no rebuild and was pre-authorised
by the developer on 2026-08-27 (recorded twice in `02-DEPLOY-LOG.md`):

```bash
gcloud run services update brett --project=brett-fitness --region=us-central1 --min=1
```

**BLOCKED** — denied by this session's permission classifier, the same denial
`07-06-DEPLOY-RECORD.md` records against the identical command. The denial was respected rather
than worked around. **The developer must run it before starting Task 2**, then confirm:

```bash
gcloud run services describe brett --project=brett-fitness --region=us-central1 \
  --format='json(metadata.annotations)'
#   expect: "run.googleapis.com/minScale": "1"
#           "run.googleapis.com/maxScale": "2"
```

Only `--min` may appear on that `update` command line: `gcloud run services update` removes any
env or secret flag it does not list, which would drop `DATABASE_URL` and `500` the next request
(T-02-18).

#### RESOLVED before Task 2 ran

The orchestrator ran the command directly — not this agent, the same division of labour
`07-06-SUMMARY.md` records for the identical fix:

```bash
gcloud run services update brett --project=brett-fitness --region=us-central1 --min=1
```

Read back afterwards: **`minScale: "1"`, `maxScale: "2"`**, and every env var and secret binding
still intact (checked explicitly, because `gcloud run services update` drops what it is not
handed). **The UAT below therefore ran against a warm, min-1 service**, and a "couldn't reach the
MCP server" failure could not have been mistaken for a coaching-document failure.

This is the **second** occurrence of this regression, both predicted by `07-06-SUMMARY.md`
§ *Deferred Items* item 1. The root cause is unchanged and still unfixed:
`scripts/deploy-cloud-run.sh` hardcodes `--min="${BRETT_MIN_INSTANCES:-0}"`. See § *Gaps and
honest limitations*.

### Note on step 5's premise — record what actually happens, do not assume the setup

The plan's step 5 forces the staleness/sparsity case by asking for a **52-week** window, on the
stated premise that "history does NOT stretch back 52 weeks". **That premise was not verifiable
from the artifacts in this repo during Task 1** — `docs/hevy-api-observations.md` records no
earliest-workout date, and 327 workouts at a typical 4-sessions-per-week cadence would span
roughly 80 weeks, which would *exceed* 52.

This is recorded as an open question rather than resolved in either direction, and it changes
nothing about how step 5 is run — it only changes how its result is read:

- If the 52-week question **does** trip `coverage.earliest_data_at` / `coverage.insufficient_data`,
  Truth 4 is satisfied directly.
- If it **does not**, that is not a failure of Truth 4. It means the synced history is longer than
  assumed, and the plan's own fallback probe applies: *"When was my data last synced, and how
  confident should I be in the last 4 weeks?"* Record which probe was used and why.

Either way, record `coverage.earliest_data_at` as Claude reports it — that single value settles the
premise for every future reader.

#### Outcome: the premise was wrong, and the doubt recorded here was correct

Step 5 ran and Claude answered the 52-week question **normally, flagging no limitation at all**.
The most economical reading — and the one consistent with the ~80-week span this section
estimated — is that the synced history reaches back **past** 52 weeks, so no coverage or freshness
gap existed for Claude to surface. `coverage.earliest_data_at` was not separately reported by the
tester, so the premise is settled by inference (Claude had no limitation to report) rather than by
reading the field directly. The fallback probe this section named was **not** asked.

The consequence is recorded in Truth 4 as `PARTIAL`, and it is a specific kind of partial: **the
guardrail was not observed to fail — it was never invoked.**

## Setup

**Run on 2026-09-01 by the developer, in a real Claude Project, against the live service.**

| Item | What was done | Source |
|---|---|---|
| Project | A Claude Project was used for the whole UAT — every question below was asked inside it, not in a bare conversation | developer report |
| Connector | The **BRETT custom connector** was attached to that Project and reachable: tool calls were issued and returned across all three questions | developer report |
| Custom instructions | `docs/coaching-instructions.md` (124 lines) was pasted into the Project's **custom instructions** — Project-level and once, per D-08, not per conversation | developer report |
| Truncation | **None reported.** The developer raised no length limit and no truncated paste; the summary given was "everything was clean". Recorded as *not reported* rather than as *confirmed untruncated* — the tester was not asked to diff the pasted text against the file | developer report (absence of) |
| Service under test | Revision **`brett-00009-fsm`** at 100% traffic, `MCP_AUTH_MODE=authkit`, `minScale=1` restored (see the resolved blocker above) | preconditions table, rows 1–2 |

**A note on the evidence's grain.** What follows is the developer's structured report across two
rounds of questions, not a verbatim transcript. Where a detail was not reported it is written down
as unreported. Nothing below is reconstructed, inferred from the code, or filled in from what the
document says *should* happen.

## Observable Truths (ROADMAP criterion #4)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | The document exists and names only real tools | **VERIFIED** | Two independent legs. *Automated:* `uv run pytest backend/tests/test_coaching_doc.py -x -q` → `4 passed in 0.49s`, exit `0` (precondition row 5), which is the only half of COACH-01 a test can reach — it proves every tool name in `docs/coaching-instructions.md` exists in the live registry. *Human-verified checkpoint:* the document was then loaded into a real Claude Project and driven through three questions with no tool-not-found error and no failed call — the developer's words were that Claude "was able to call each corresponding tool and without error". The second leg is a human-verified checkpoint, not a claim inferred from code |
| 2 | "Am I progressing?" is answered from real data, opening with fitness_get_training_summary | **VERIFIED** | **This row is a human-verified checkpoint, not a claim inferred from code.** Asked verbatim in the Project. The developer confirmed both halves explicitly and separately: (a) **`fitness_get_training_summary` was the tool Claude called first, before any other tool** — the opener the document's mapping table (line 55) specifies; (b) the answer **cited real numbers from the returned data**, not generic training statements. No automated test in this repo can observe either fact; both come from the developer watching the conversation |
| 3 | "Which muscles are undertrained?" is answered from real data, distinguishing direct from indirect sets | **VERIFIED** | **This row is a human-verified checkpoint, not a claim inferred from code.** Asked verbatim in the Project. The developer confirmed all three halves: (a) **`fitness_get_muscle_group_volume` was called** — the mapping the document specifies at line 56; (b) the answer **distinguished direct sets from indirect sets** rather than presenting one combined figure, which is the specific failure mode `docs/coaching-instructions.md:102` forbids ("Never sum `direct_sets` across muscle groups into one number") — no cross-muscle total was presented; (c) **specific muscle groups were named**, not a vague summary. Observable only by reading the conversation, which is what the developer did |
| 4 | A window that outruns the data makes Claude surface coverage/freshness unprompted | **PARTIAL — the guardrail was never exercised** | **This row is a human-verified checkpoint, not a claim inferred from code — and what it observed is that the probe did not apply.** The step-5 question ("Compare my training over the last 52 weeks — am I progressing over that whole period?") was asked verbatim. **Claude answered normally and flagged no limitation.** The plan's premise — "the synced history is shorter than 52 weeks, so `coverage.earliest_data_at` and/or `coverage.insufficient_data` should fire" — did not hold: 327 workouts at a typical cadence span roughly 80 weeks, the doubt Task 1 recorded in advance. **No metadata field was cited, because there was no coverage or freshness gap to cite** — so this row cannot name one, and it is not marked VERIFIED on the strength of a question that had nothing to surface. Equally it is **not FAILED**: nothing was observed going wrong. The guardrail is *untested*. `52` is also the hard `MAX_WEEKS` cap in `backend/app/mcp/tools/_common.py:58`, so **no `weeks` value can outrun this dataset** — the probe as designed cannot work here at any window size. See § *Gaps and honest limitations* for what would actually exercise it |

**Score: 3/4 criteria verified.** Truth 4 is `PARTIAL` and is deliberately not rounded up
(T-07-56). The distinction that matters to a future reader: Truths 2 and 3 are the two questions
ROADMAP criterion #4 names by name, and both passed on their first and only attempt, with the
right tool and the right behavioural distinction. Truth 4's guardrail remains an unobserved
behaviour rather than a broken one.

## Transcript

Reconstructed from the developer's structured report, gathered over two rounds of questions. It is
a faithful record of **what was reported**, not a verbatim transcript — the developer was not
asked to paste the conversation, and this file does not invent the parts that were never captured.
Per the redaction rule above, tool choices and metadata handling are recorded; the training figures
Claude quoted are deliberately not.

### Step 2 — "List every tool you can reach through the BRETT connector, by name."

- **Reported count:** not explicitly re-stated as a number by the tester in this session, though
  tool calls across all three questions succeeded without error. The expected count is 13
  (established independently by 07-06's human round-trip and by 07-09 row 7's `curl`, which counted
  13 against this same revision) — **but 13 is not recorded here as an observation of this session,
  because the tester never said it.**
- What *is* established for this session: the tool surface was reachable, and every tool the three
  criterion questions required was present and callable.

### Step 3 — "Am I progressing?"

| | Reported |
|---|---|
| Tools called, in order | **`fitness_get_training_summary` first**, ahead of any other tool. Arguments not reported; whether further tools followed in the same turn was not reported |
| Opener correct? | **Yes** — matches the document's mapping (`docs/coaching-instructions.md:55`) |
| Answer from real data? | **Yes** — the developer confirmed the answer cited actual numbers from the tool response, not generalities |
| Metadata handling | **Not reported.** Whether Claude mentioned `coverage.sessions_in_window` or freshness in this turn was not captured — this is a genuine gap in the record, not a negative finding |
| Errors | None |

### Step 4 — "Which muscles are undertrained?"

| | Reported |
|---|---|
| Tools called | **`fitness_get_muscle_group_volume`**. Arguments and ordering relative to any other call not reported |
| Direct vs indirect | **Distinguished.** The developer confirmed the answer separated direct from indirect sets and did **not** present a single combined total — the behaviour `docs/coaching-instructions.md:102` exists to prevent |
| Specific muscle groups named? | **Yes.** Which of the 19 taxonomy groups were named was not captured |
| Metadata handling | Not reported |
| Errors | None |

### Step 5 — "Compare my training over the last 52 weeks — am I progressing over that whole period?"

| | Reported |
|---|---|
| Tools called | **Not reported by name for this turn.** The developer's overall statement covers it — "each corresponding tool" was called "without error" — but no specific tool was named for step 5, so none is recorded |
| Limitation surfaced? | **No — and correctly so.** Claude answered normally and flagged no limitation |
| Field cited | **None** — there was no coverage or freshness signal to cite |
| Interpretation | The synced history extends past 52 weeks, so the window did not outrun the data. This is the premise failing, not the guardrail failing |
| Fallback probe | **Not asked.** The plan's second probe ("When was my data last synced, and how confident should I be in the last 4 weeks?") was not used, so `freshness.resources` handling is also unobserved |
| Errors | None |

## Observations for later tuning

Recorded as evidence for a future decision. **Not acted on** — retuning tool budgets is explicitly
outside this phase's boundary.

| Observation | What was reported |
|---|---|
| **429 rate limiting** | **None. Zero 429s across all three questions** — stated explicitly by the developer. `RATE_LIMIT_PER_MINUTE=30` / `RATE_LIMIT_BURST=30` (precondition row 1) were not approached closely enough to fire, at whatever per-turn call volume this session produced (T-07-59) |
| **Per-turn tool-call counts** | **Not captured as numbers.** The developer was asked for them and reported behaviour rather than counts. The floor established per turn: **≥1** for step 3 (`fitness_get_training_summary`, confirmed first), **≥1** for step 4 (`fitness_get_muscle_group_volume`), **≥1** for step 5 (unnamed). Recorded as a floor because that is what the evidence supports; an exact count is not available and is not invented |
| **Latency** | No slow response reported. The developer's summary was "everything was clean" |
| **Truncation / oversized responses** | **None reported.** No visibly truncated tool response in any turn |

**On the three Phase-6 over-budget tools — explicitly NOT retuned here.** `deferred-items.md`
D-06-10-A (Phase 6) records three of thirteen tools measuring over their research budgets:
`fitness_compare_periods` at **59,582 bytes** against a 32,768 budget,
`fitness_get_exercise_progression` at 28,685 against 24,576, and `fitness_get_plateaus` at 28,350
against 24,576. **None of them is retuned by this plan** (T-07-60 — retuning changes shipped tool
behaviour and is outside this phase's boundary).

**And this UAT produced no evidence either way.** `fitness_compare_periods` — the worst offender,
and the tool step 5's "compare my training over…" phrasing might have been expected to reach — was
**not among the tools the tester named as exercised in this session**, and no oversized or
truncated response was observed for anything that did run. So D-06-10-A stands exactly where Phase
6 left it: an open measurement, neither corroborated nor contradicted by real coaching traffic. A
future UAT that deliberately drives `fitness_compare_periods` with `include_muscle_groups=True`
would be the cheap way to get that evidence.

## Gaps and honest limitations

**1. Truth 4 is untested, not passed — this is the main limitation of this record.**

The staleness/sparsity guardrail — "give no verdict when `coverage.insufficient_data` is true";
"use `coverage.earliest_data_at` before concluding the user stopped training"
(`docs/coaching-instructions.md:87-88`) — **has still never been observed firing.** Step 5 was
designed to force it and could not, because the dataset is larger than the plan assumed. To be
plain about what this is and is not:

- It is **not** evidence the coaching document fails at this behaviour. Nothing was observed
  failing.
- It **is** a defect in the UAT's test design, predicted in advance by Task 1's "Note on step 5's
  premise" section and now confirmed.
- The document's instruction for this case is untested prose. It may work perfectly; nobody has
  looked.

**Recommended follow-up, and a correction to the obvious suggestion.** The intuitive fix — ask for
a deliberately impossible window such as "compare my training over the last 200 weeks" — **will not
work**, and that is worth writing down so it is not attempted twice. `MAX_WEEKS = 52`
(`backend/app/mcp/tools/_common.py:58`) is a hard cap enforced both by Pydantic (`le=MAX_WEEKS`)
and by `week_window()` (`raise ValueError("weeks outside the permitted range")`). A 200-week request
produces an **argument-validation error**, which is a different behaviour entirely from a coverage
signal — and would test the wrong thing. Since the history exceeds the maximum requestable window,
**no `weeks` value can outrun this dataset.** What would actually exercise the guardrail:

- **The plan's own fallback probe**, never asked: *"When was my data last synced, and how confident
  should I be in the last 4 weeks?"* This targets `freshness.resources`, which does not depend on
  window length. Cheapest option, and it exercises the freshness half.
- **A sparse slice rather than a long window.** Ask about a rarely-performed exercise
  (`fitness_get_exercise_progression`) or a muscle group with few or no direct sets, where
  `coverage.insufficient_data` / per-muscle `insufficient_data` fires on its own terms.
- Either should be run **before ROADMAP criterion #4's staleness clause is treated as closed.**
  Criterion #4's two named questions are closed; its "correctly flagging stale or sparse data when
  present" clause is not.

**2. 07-RESEARCH.md assumption A4: NOT DETERMINABLE from this session.**

A4 (`07-RESEARCH.md:949`) holds that Claude's connector does not currently inject
`DiscoverResult.instructions` into its system prompt, and notes it would be "observable for free
during D-09". **It was not observed** — separating a server-supplied `instructions` string from the
Project's pasted custom instructions requires transcript-level introspection (asking Claude what
guidance it holds, or A/B-ing the Project with and without the paste), and **the developer was not
asked to perform either.** Recorded as *not determinable from this session*, per the plan's
explicit instruction not to guess. A4 remains open. What *is* known is that the Project's custom
instructions were sufficient on their own: the tool mappings at lines 55–56 of the document were
followed exactly in steps 3 and 4.

**3. The custom-instructions paste: no truncation reported.**

The developer reported no length limit and no truncation, and described the session as clean.
Recorded as *not reported* rather than *confirmed*: nobody diffed the pasted text against the
124-line file. If a future session sees Claude ignore a rule from the document's later sections,
verifying the paste completed is the first thing to check.

**4. The record's grain is a developer report, not a transcript.**

Tool *arguments*, exact per-turn call *counts*, the specific muscle groups named, and Claude's
metadata commentary in steps 3 and 4 were all never captured. The behavioural facts that ROADMAP
criterion #4 turns on were confirmed explicitly and one at a time; the surrounding detail was not.
A future UAT should paste the conversation (with training figures redacted per the rule at the top
of this file) rather than answering questions about it afterwards.

**5. Nothing Claude did needed preventing.**

No behaviour was reported that `docs/coaching-instructions.md` should have stopped — no
cross-muscle total, no verdict given on absent data, no failed or hallucinated tool name. There is
no document-defect follow-up from this session.

**6. `scripts/deploy-cloud-run.sh` still silently resets `--min` to 0 on every deploy.**

Not a UAT finding, but this plan is where it surfaced for the **second** time and it belongs in the
honest-limitations list. The script hardcodes `--min="${BRETT_MIN_INSTANCES:-0}"`, so plan 07-09's
deploy wiped the `--min=1` restored by hand after 07-06 — exactly as `07-06-SUMMARY.md` § *Deferred
Items* item 1 predicted. It was fixed by hand again before this UAT (see the resolved blocker
above), and the measured cold start this session was **16.2 s against Claude's 10-second discovery
budget**, more than double. **The script-level fix is still outstanding** and should default
`BRETT_MIN_INSTANCES` to `1` or read and preserve the live value. Until then every operator must
export `BRETT_MIN_INSTANCES=1` before running that script, and every connector test must re-check
`minScale` first.
