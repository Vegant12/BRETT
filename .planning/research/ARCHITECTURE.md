# Architecture Research: v2.1 Longitudinal Physique Analysis

**Domain:** Integrating a second MCP write path + a new analytics domain + a monthly-only report
section into an already-shipped, heavily-guarded Python/FastAPI/SQLAlchemy/MCP backend (BRETT).
**Researched:** 2026-09-05
**Confidence:** HIGH — every claim below is grounded in code actually read (files and line
numbers cited throughout), not in the milestone's prose description of itself.

This is not greenfield research. BRETT already has a strict, test-enforced architecture (read-only
MCP boundary, analytics/MCP isolation, one write path). The job here is to find the EXACT points
that architecture must be touched, and to recommend the ONE way to touch each of them that amends
the existing guards deliberately rather than weakening them — per the milestone's own framing.

---

## 1. System Overview — where physique analysis lands

```
┌───────────────────────────────────────────────────────────────────────────┐
│  Claude (vision + conversation)                                           │
│  - looks at photos attached in-conversation (BRETT never sees them)       │
│  - calls a READ tool FIRST for prior context (steered by docs, not forced)│
│  - calls the WRITE tool ONCE with new ratings + bounded free-text notes   │
└───────────────────────────────┬───────────────────────────────────────────┘
                                 │ MCP (stateless HTTP, read_only_hint per tool)
┌───────────────────────────────▼───────────────────────────────────────────┐
│  app/mcp/tools/                                                           │
│  ┌───────────────────────┐   ┌────────────────────────────────────────┐  │
│  │ physique.py  (NEW)     │   │ reports.py  (MODIFIED)                 │  │
│  │ - fitness_get_latest_  │   │ - _report_body_fields() gains a        │  │
│  │   physique_observation │   │   monthly-only physique projection     │  │
│  │   (READ_ONLY)           │   │ - fitness_get_monthly_report only      │  │
│  │ - fitness_log_physique_ │   │                                        │  │
│  │   observation           │   └────────────────────────────────────────┘  │
│  │   (2nd write path,      │                                              │
│  │   APPEND_ONLY_WRITE)    │   server.py (MODIFIED): registers the new    │
│  └───────────┬─────────────┘   tool(s), a SECOND non-READ_ONLY            │
│              │                 ToolAnnotations object                    │
├──────────────┼─────────────────────────────────────────────────────────── │
│  app/analytics/physique.py  (NEW)                                        │
│  - get_physique_diff(): improved/unchanged/regressed per muscle          │
│  - get_physique_training_correlation(): joins ratings x get_muscle_group_│
│    volume by CanonicalMuscleGroup -- "underdeveloped AND undertrained"   │
│  - imported by BOTH physique.py's read tool AND reports.py's monthly     │
│    section -- one implementation, never two copies of the join           │
├───────────────────────────────────────────────────────────────────────────┤
│  app/db/repositories/physique.py  (NEW, mirrors programs.py)             │
│  - insert_observation() -- the ONLY module allowed to INSERT into the    │
│    two new tables                                                        │
│  - get_latest_observation(), get_observation_history()                  │
├───────────────────────────────────────────────────────────────────────────┤
│  app/db/models/physique.py  (NEW) -- physique_observations +             │
│  physique_ratings, migration 0007                                       │
└───────────────────────────────────────────────────────────────────────────┘
```

**What never appears in this diagram, on purpose:** an image, an upload endpoint, object storage,
a vision call from the backend. The milestone's defining constraint (PROJECT.md, milestone
"Shape decided at the gate") is structural here, not a policy note — there is no code path in this
design that could receive image bytes even by accident, because no new endpoint of any kind is
added outside `app/mcp/`.

---

## 2. Question 1 — The second write path, file by file

### 2.1 What actually enforces "exactly one write module" today

Two test modules matter, and they are **not** the ones a first pass suggests:

- `backend/tests/test_mcp_readonly.py` tests the RUNTIME control (`read_only_session`'s
  `postgresql_readonly=True`, proven against a real Postgres). It says nothing about which module
  is allowed to write — no allowlist logic lives there.
- `backend/tests/test_mcp_isolation.py` is where the actual guard lives:
  - `_WRITE_ALLOWLIST = frozenset({"program_switch.py"})` — line 79.
  - `test_mcp_never_writes` (lines 138–171): for every module under `app/mcp/` **not** in
    `_WRITE_ALLOWLIST`, asserts no `session.commit/flush/add/add_all` call
    (`_SESSION_WRITE`, line 48); for **every** module regardless of allowlist status, asserts no
    `from sqlalchemy import ... insert|update|delete` (`_WRITE_IMPORT`, line 49–51); then at
    lines 166–171, `assert len(_WRITE_ALLOWLIST) == 1`.
  - `test_the_write_allowlist_holds_exactly_one_module` (lines 174–184): re-asserts
    `_WRITE_ALLOWLIST == frozenset({"program_switch.py"})` and `len(...) == 1`.
  - `test_only_one_module_opens_a_writable_session` (lines 187–197): scans every `app/mcp/` module
    except `_common.py` for the literal substring `"writable_session("` and asserts the set of
    matches equals `{"program_switch.py"}`.
  - `test_every_tool_module_guards_its_public_tools` (lines 262–310): asserts the walk finds
    **exactly 19** `async def fitness_*` coroutines (line 305), each immediately preceded by
    `@safe_tool(`.

A second, separate assumption lives in `backend/tests/test_mcp_tool_schemas.py`, and this is the
one most likely to be missed because it was not in the files list under `test_mcp_isolation.py`'s
name:

- `WRITE_TOOLS = frozenset({"fitness_switch_training_program"})` (line ~135).
- `test_annotations_are_an_exact_partition` (lines ~142–199) asserts `len(WRITE_TOOLS) == 1`, that
  `read_only_false == WRITE_TOOLS` (a correct partition, fine to extend), **and then loops over
  every name in `read_only_false` asserting `destructiveHint is True` and `idempotentHint is
  False` for ALL of them** (lines ~186–194). This is a **uniform-shape assumption**: it currently
  hard-codes "every write tool looks like `program_switch`." It will break the moment a second
  write tool ships with `destructive_hint=False`, which is exactly what this milestone specifies.
- `test_tool_registry_is_exactly_the_twenty` (line 110) and `EXPECTED_TOOLS` (lines 37–ff.) also
  need the new tool name(s) added and the count/name updated.

### 2.2 Widening the guard to exactly two named modules, without weakening it

Per file, in order:

1. **`backend/tests/test_mcp_isolation.py`**
   - Line 79: `_WRITE_ALLOWLIST = frozenset({"program_switch.py", "physique.py"})`.
   - Lines 166–171: bump `assert len(_WRITE_ALLOWLIST) == 1` → `== 2`, with the comment amended
     to say "exactly TWO modules under app/mcp/ may write" — keep the assertion's shape (an exact
     count on a named set), only its value changes. `_WRITE_IMPORT`'s ban stays absolute and
     unconditional for both modules — this is the property that must never relax.
   - Lines 174–184: rename `test_the_write_allowlist_holds_exactly_one_module` →
     `test_the_write_allowlist_holds_exactly_two_modules`; update both assertions to the new
     frozenset and `== 2`. The rename is itself an example of "amend deliberately" — the old name
     would be a false claim about the invariant it tests.
   - Lines 187–197: rename `test_only_one_module_opens_a_writable_session` →
     `test_only_the_allowlisted_modules_open_a_writable_session`; assert
     `opens_writable == {"program_switch.py", "physique.py"}`.
   - Line 305: bump the literal tool count from 19 to whatever the final tool count is (20 if only
     the write tool is added; 21 or 22 if the prior-observation read tool and/or the
     cross-reference read tool are added as separate tools — see §5). Update the trailing
     comment's running history in the same style already used there (Plan 12-04, 13-06, 13-09).

2. **`backend/tests/test_mcp_tool_schemas.py`**
   - `EXPECTED_TOOLS`: add the new tool name(s).
   - `test_tool_registry_is_exactly_the_twenty`: rename to reflect the new count (mirrors the
     `test_mcp_isolation.py` rename above — the "twenty" in the name is a claim, not a label).
   - `WRITE_TOOLS`: add the physique write tool's registered name;
     `assert len(WRITE_TOOLS) == 1` → `== 2`.
   - **The uniform-annotation loop must be restructured, not just extended.** Replace the blanket
     `for name in read_only_false: assert destructiveHint is True, idempotentHint is False` with a
     per-tool expected-annotations mapping:
     ```python
     EXPECTED_WRITE_ANNOTATIONS: dict[str, dict[str, bool]] = {
         "fitness_switch_training_program": {"destructiveHint": True, "idempotentHint": False},
         "fitness_log_physique_observation": {"destructiveHint": False, "idempotentHint": False},
     }
     ```
     and assert each tool's dumped annotations match its own entry. This is the deliberate
     amendment: the partition property ("every tool is read-only XOR in a named, reviewed
     exception set") is preserved exactly; the *previously accidental* assumption that every
     exception looks alike is what's being corrected, and correcting it is what this milestone's
     "amend deliberately" instruction is for.
   - Add a sibling to `test_the_write_tool_publishes_explicit_write_annotations` (T-12-07) for the
     new tool, asserting its four flags explicitly by name, same pattern.

3. **`backend/app/mcp/tools/_common.py`** — no test changes, but `writable_session`'s docstring
   (lines 174–195) says "Used by exactly one module" (line 189) and `read_only_session`'s sibling
   framing — update the prose to "used by exactly the two allowlisted modules." No code change:
   `writable_session` (lines 174–194) is already generic — it takes `ctx`, opens a plain (not
   read-only) session, and does not commit. It needs zero modification to serve a second caller.

4. **`backend/app/mcp/tools/physique.py`** (new module) — must follow `program_switch.py`'s
   pattern exactly for the parts that are load-bearing:
   - Import `writable_session`, `resolve_user_id`, `safe_tool` from `_common.py` (never
     `read_only_session` — same "must not be reachable from this module" discipline
     `program_switch.py`'s docstring states at lines 16–18).
   - Must **not** import `insert`/`update`/`delete`/`sqlalchemy` directly (banned unconditionally
     by `_WRITE_IMPORT` for every module). The actual `INSERT` statements live in
     `app/db/repositories/physique.py`, mirroring `programs.py`'s `close_period_and_open_new`/
     `issue_switch_token` pattern (`app/db/repositories/programs.py:19–24`'s own docstring states
     this rule generally: "this is the ONE place under `app/` outside the integrations layer that
     constructs a `program` write" — the physique milestone needs the equivalent sentence for its
     own repository module).
   - The commit is the LAST statement before return (PITFALLS #15's discipline, restated at
     `program_switch.py:171–175` and `:235–239`) — for the SAME reason it matters for
     `program_switch.py`: `safe_tool` degrades any exception to `UNKNOWN`/an "unclear" payload,
     and an exception *after* a successful commit must never be reported in a way that invites a
     retry that double-inserts an append-only row.

5. **`backend/app/mcp/server.py`** — the concrete gating difference the milestone specifies
   (single-call, append-only, `destructive_hint=False`) requires a **second** `ToolAnnotations`
   constant, not reuse of `WRITE_TOOL` (`server.py:278–283`, `read_only_hint=False,
   destructive_hint=True, idempotent_hint=False, open_world_hint=False`):
   ```python
   # Distinct from WRITE_TOOL: this tool is NOT destructive (it appends a row to a longitudinal
   # log; it never changes how anything else is classified) and it is NOT idempotent (calling it
   # twice with the same arguments legitimately produces two rows -- two observations on the same
   # day are a real, permitted case, not a duplicate to be suppressed).
   APPEND_ONLY_WRITE_TOOL = ToolAnnotations(
       read_only_hint=False,
       destructive_hint=False,
       idempotent_hint=False,
       open_world_hint=False,
   )
   ```
   Registered OUTSIDE the `_TOOLS` loop (server.py:258–259), in its own `mcp.add_tool(...)` block
   immediately after the existing `WRITE_TOOL` registration (server.py:285–294) — same reasoning
   already documented there: adding it to `_TOOLS` would hand it `READ_ONLY` and misrepresent a
   tool that writes. Any new READ tool(s) (prior-observation, cross-reference) go **inside** the
   `_TOOLS` tuple with the shared `READ_ONLY` annotation, exactly like every other read tool.

### 2.3 Recommendation

Widen `_WRITE_ALLOWLIST` to exactly `{"program_switch.py", "physique.py"}`, bump every count
assertion by exactly one (never delete an assertion, only its literal), and — the part easy to
miss — **fix `test_mcp_tool_schemas.py`'s uniform-write-annotation assumption into a per-tool
mapping**, because the milestone's own design (non-destructive vs. destructive) breaks the current
code's implicit "all write tools look like `program_switch`" premise. This is not optional
cleanup; without it, `test_annotations_are_an_exact_partition` fails the moment the new tool is
registered with truthful annotations.

**Rejected alternative:** reusing `program_switch.py`'s two-call token pattern for physique's
write tool. Rejected because the milestone explicitly specifies single-call, and because the token
pattern exists to force a *human* confirmation before an *irreversible, classification-changing*
state transition — properties physique logging does not have (see §4).

---

## 3. Question 2 — The monthly-only report split

### 3.1 The existing precedent, already shipped

`backend/app/mcp/tools/schemas.py:484–572` already solves almost this exact problem, one layer up
the stack, for `narrative`:

```python
class _ReportBody(_McpModel):      # everything BOTH periods share
    ...
class WeeklyReportResponse(_ReportBody):
    """Deliberately has NO `narrative` field."""
class MonthlyReportResponse(_ReportBody):
    """`narrative` is D-14 ... `None` exactly when `data_available` is False."""
    narrative: str | None
```

This is the wire-layer precedent for "same sections, one extra field, monthly only." The physique
section should follow it exactly at the wire layer. The open design question is the ANALYTICS
layer, where — unlike the wire layer — there is currently only **one** `ReportResult`
(`app/analytics/schemas.py:1002–1053`) composed by **one** `compose_report()`
(`app/analytics/reports.py:104–210`) for both periods.

### 3.2 Evaluating the three options

**Option B — separate monthly-only extension model** (e.g., `MonthlyReportResult(ReportResult)`).
Rejected. `compose_report()`'s signature returns one declared type; a subclass would force either
two composer functions (fragmenting the "one composer, two windows" property `reports.py`'s
docstring states as the whole point of the module, lines 1–34) or a runtime `isinstance` dance at
every call site including `test_analytics_reports.py`'s single `_report()` fixture builder. It
buys nothing an Optional field doesn't, at the cost of duplicating the composer.

**Option C — a conditional branch inside `compose_report`.** This isn't really a distinct third
option — some conditional has to exist regardless of where the field lives, since something must
decide not to run physique queries for `WEEKLY`. Read as its own recommendation, it's underspecified
(a branch producing *what*, stored *where*?) — folded into Option A below.

**Option A — Optional field on `ReportResult`, populated only when `period is MONTHLY` (recommended).**
Add `physique: PhysiqueSection | None` to `ReportResult`, populated inside `compose_report()`:

```python
physique = (
    await get_physique_report_section(session, user_id=user_id, weeks=REPORT_PLATEAU_LOOKBACK_WEEKS)
    if period is ReportPeriod.MONTHLY
    else None
)
```

This is a one-line branch inside the existing composer — no new function signature, no subclass,
and it matches `RecompositionResult`'s own precedent for "sometimes-null, explained by an adjacent
fact rather than a second flag": `previous_program`/`program_switched_on` are `None` exactly when
`program_switch_in_window` is `False` (`schemas.py:960–969`) — here, `physique` is `None` exactly
when `report.period` (already a field on the same model) is `WEEKLY`. No new boolean is needed;
the explanation is already on the object.

**The one thing this option must get right:** `physique` being `None` must mean **only** "this is
a weekly report." It must never also mean "the call failed" (that's `ReportResult` not existing at
all — degradation happens entirely at the MCP layer, see §3.3) or "the user has no observations
yet" (that must be a fact **inside** `PhysiqueSection`, e.g. `has_observations: bool`, mirroring
`BodyMeasurementTrendResult`'s own `coverage.insufficient_data` pattern rather than nulling the
whole section — the same discipline `body_measurements.py:89–103`'s `staleness()` uses to keep
"no reading" and "stale reading" as two independent, nameable facts instead of one overloaded
`None`).

### 3.3 The wire layer

Mirror `narrative` exactly: add `physique: PhysiqueReportSection | None` to `MonthlyReportResponse`
only (`app/mcp/tools/schemas.py:562–572`), never to `_ReportBody`, never to `WeeklyReportResponse`.
`_degraded_body_fields()` (`app/mcp/tools/reports.py:152–192`) needs **no new key** for the shared
dict — it already omits `narrative` and lets `_degraded_monthly()` (line 199–200) append
`narrative=None` on top. Do the identical thing: `_degraded_monthly()` becomes
`MonthlyReportResponse(**_degraded_body_fields(), narrative=None, physique=None)`. This preserves
the existing "every `_ReportBody` field, emptied rather than partially filled" contract
(docstring, lines 152–158) without touching `_ReportBody` at all.

### 3.4 `build_narrative`'s determinism contract

`build_narrative` (`app/analytics/reports.py:238–452`) is called **only** from
`fitness_get_monthly_report` (`app/mcp/tools/reports.py:216–243`) — never from the weekly tool —
so it will always receive a `ReportResult` whose `physique` field is populated (barring the
"no observations yet" case handled inside the section, §3.2). Add one new block, following the
exact idiom every other section already uses (StrEnum via `.value`, `Decimal` via `str()`,
`dt.date` via `.isoformat()`, a null figure as an explicit word never a bare `0`) — see §4 for what
that block may and may not contain.

### 3.5 What `test_analytics_reports.py` constrains

- `_report()` and its per-section helpers (module-level, hand-built `ReportResult` fixtures) will
  need a `_physique()` helper alongside `_recomposition()` etc., following the same
  fixed-arbitrary-date convention (`dt.date.fromisoformat(...)`, never the positional constructor —
  module docstring, lines 10–14).
  `test_the_narrative_contains_no_recommendation_language` and
  `test_every_number_in_the_narrative_is_already_in_the_structured_fields` (lines 684–718) must be
  run with a fixture that reaches the physique branch, exactly as they are currently built to
  reach "every branch" (records present, a plateau present, a program switch present — see the
  docstring at line 686).
- `test_the_weekly_window_agrees_with_the_mcp_layers_week_window`-style anti-drift tests are not
  directly implicated (physique carries no window of its own beyond the observation's own date),
  but a **new** assertion is worth adding here: that `WeeklyReportResponse` genuinely has no
  `physique` attribute at all (a `hasattr`/model-field-set check), the same structural guarantee
  `WeeklyReportResponse`'s own docstring claims for `narrative` today by omission alone.

### Recommendation

**Option A: an Optional `physique` field on `ReportResult`, populated by a one-line period
conditional inside `compose_report()`, mirrored at the wire layer by adding `physique` to
`MonthlyReportResponse` only** — exactly the pattern already shipped for `narrative`. Reject the
separate-model option as unnecessary duplication of the composer; treat "conditional inside
compose_report" not as a competing option but as the correct implementation detail of Option A.

---

## 4. Question 3 — `build_narrative`'s determinism contract and physique's ordinal/textual ratings

### 4.1 The two load-bearing tests, precisely

`backend/tests/test_analytics_reports.py`:
- `_BANNED_NARRATIVE_TOKENS` (lines 101–110): `"should", "recommend", "suggest", "consider",
  "advise", "deload", "aim for", "you need", "try "` (trailing space deliberate). Checked via
  `token not in build_narrative(report).lower()` for every token (lines 684–697).
- The numeric-provenance check (lines 700–718): every match of `_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")`
  (line 118) found in `build_narrative(report)`'s output must already be a substring of
  `report.model_dump_json()`.

### 4.2 What an ordinal, StrEnum-rendered rating does to each check

**The banned-token scan is blind to fabricated words, not just recommendation words.** It only
matches its ten fixed literal tokens. A muscle-group rating rendered via `.value` (e.g.
`report.physique.ratings[i].rating.value`) is a bare enum word with no digits — it simply never
touches `_NUMBER_RE`, exactly like `recomposition.status.value` and `progression.verdict.value`
already do not (lines 436–439 render these the same way today with no special-casing). Ordinal
ratings are **not a new risk category for the numeric check** — they are outside its domain
entirely, the same way every other StrEnum field in this report already is.

**The numeric-provenance check has a real loophole once free text enters the model.** If a
`leanness_notes`/`conditioning_notes`/`symmetry_notes` string field is added to `PhysiqueSection`
and ANY part of `build_narrative` prints it, two things happen simultaneously:
1. The note is Claude's own prose, generated in-conversation, not backend-computed. Its content is
   outside this codebase's control by construction (the milestone's own framing: "Claude is the
   analyst, BRETT is the ledger").
2. `report.model_dump_json()` will trivially contain the note's text VERBATIM, because the note
   is a field on the serialized model. So any number the note happens to contain (e.g. "abs look
   maybe 10% leaner") would pass the provenance check — not because the number was validated as
   backend-computed, but because the note field's own presence in the JSON dump makes anything
   inside it "provable." **The check would report green while the property it exists to enforce is
   silently defeated.**
3. The banned-token scan is a fixed, closed list of ten strings. It was written to catch this
   *codebase's* recommendation language, not to police arbitrary third-party prose. A model could
   write "you should get a check-up" in a symmetry note (medical, off-topic, not even a training
   recommendation) and neither test would catch it, because neither test is designed to validate
   free text — they are designed to validate a small, fixed, deterministic template.

### 4.3 What the physique narrative section may and may not say

**May say** (all sourced from already-computed, already-typed fields on `report.physique`,
following the identical rendering discipline every other section uses):
- Each rated muscle group's canonical name and rating word (`CanonicalMuscleGroup.value`,
  `PhysiqueRating.value`) — words, never invented labels.
- The diff verdict per muscle (improved / unchanged / regressed), also a StrEnum `.value`.
- The cross-reference flag/label ("underdeveloped and undertrained"), rendered from a stored
  boolean or StrEnum field on the cross-reference result — never computed inline in
  `build_narrative` (see §5).
- Any **precomputed aggregate count** that is itself a field on the physique analytics result
  (e.g. `improved_count`, `regressed_count`) — never a `sum()`/`len()` performed inline inside
  `build_narrative` over a list, even though that arithmetic is trivial. The rule
  `build_narrative`'s own docstring states ("introduces nothing... never a new computation") does
  not carve out an exception for simple arithmetic; the counting must happen in
  `analytics/physique.py`, where it is unit-testable against known fixtures, exactly like every
  other figure in this report.
- The observation date, via `.isoformat()`.

**May not say:**
- **Claude's free-text notes, verbatim or in any paraphrased form, anywhere in `build_narrative`'s
  output.** This is the recommendation, not a caveat: the determinism/banned-token/numeric-
  provenance contract is a property of code this project controls and tests against fixed
  fixtures; it cannot be honestly extended to cover prose this project does not generate and
  cannot re-validate on every future banned-word list update. The notes remain fully available to
  Claude — they travel to the model as **structured JSON fields** on the tool/report response
  (`leanness_notes: str | None` etc.), so Claude can read and relay them in its own conversational
  answer — they are simply never re-emitted inside BRETT's own deterministic markdown, the same
  way `disclaimer` is the one field allowed to travel verbatim specifically *because* it is a
  fixed backend-authored constant (`RecompositionResult`'s docstring, `schemas.py:939–944`) —
  Claude's free text has no equivalent "fixed constant" property and must not be given the same
  verbatim-travel treatment.
- Any newly-derived ratio, percentage, or count not already a named field.
- Any of the ten banned tokens, in any section — unchanged, and now doubly relevant since the
  cross-reference finding ("underdeveloped AND undertrained") is one accidental word choice away
  from reading as a recommendation ("you should train X more") if phrased loosely. Render it as an
  observation ("chest: underdeveloped rating, also below-median direct volume this window"),
  never as advice.

### 4.4 A gap worth naming for the roadmapper

Neither existing test can catch a **fabricated rating word** (e.g., a typo'd or hand-coded label
that doesn't match `report.physique`'s real value) the way the numeric check catches a fabricated
number, precisely because `_NUMBER_RE` only looks at digits. Recommend adding one new assertion
alongside the existing two: every physique rating/verdict token rendered in the narrative must
match the corresponding `.value` read directly off `report.physique`'s own fields (a structural
equality check, not a regex over the whole string) — the word-level equivalent of the
numeric-provenance test, scoped to the one new section that introduces ordinal/textual content.

---

## 5. Question 4 — Prior-observation-as-context

### 5.1 Why `program_switch.py`'s two-call token does not transfer

The token exists to solve one specific problem: **a bare boolean confirmation is not a real gate**
because the model can set it `true` on the first call (`program_switch.py:9–14`, PITFALLS #13).
The token forces a *human* to see a warning and *decide* before an *irreversible,
classification-changing* state transition — the impersonation risk is that Claude switches the
active program in one shot with no human ever confirming a real intent.

Physique observation has neither property:
- The milestone explicitly scopes the write tool as **single-call, append-only** (PROJECT.md,
  "Target features" bullet). A token-relay pattern requires a first no-op call by construction —
  contradicting "single-call" as a design constraint, not merely as an efficiency preference.
- The write is **not destructive** (§2.2's annotation choice: `destructive_hint=False`). A wrong
  or drifted rating is one row in a longitudinal series, correctable by the next observation — not
  a threshold change that silently reclassifies twelve weeks of past recomposition verdicts the
  way a program switch does (`program.py` module docstring, lines 1–8, is explicit that THIS is
  the harm a mutable value would cause).
- The risk being mitigated ("drift" — Claude rating progressively looser over successive
  observations with no memory of its own prior scale) is a **data-quality** problem, not a
  **security/consent** problem. A cryptographic single-use nonce is the right tool for "did a human
  really agree to this," not for "does the model have the context it needs to be consistent with
  itself."

### 5.2 The shape that actually solves drift

Nothing can force an MCP client to call tool A before tool B — the question's own framing is
correct, and `program_switch.py`'s token doesn't get around this either: it forces order **between
two calls of the same tool**, not between two *different* tools. There is no mechanism in the MCP
spec (nor in this SDK) for a server to require tool X was called before tool Y is even reachable,
short of not registering Y until X has run in this session — which stateless HTTP transport rules
out entirely (`server.py`'s own module docstring: "Stateless request/response; protocol-level
sessions removed").

Given that hard limit, the practical, honestly-scoped design is a **dedicated read tool**,
documented as the required precursor two ways at once:

1. **A purpose-built read tool**, e.g. `fitness_get_latest_physique_observation`, following
   `programs.py`'s exact shape (`app/mcp/tools/programs.py:38–67`,
   `fitness_get_training_program`) — takes no arguments, reads the single most recent observation
   (all rated muscle groups + their ratings + the observed_on date), registered `READ_ONLY` inside
   `_TOOLS` like every other read tool.
2. **Steered, not forced, at two documentation surfaces that already exist and are already
   drift-guarded:**
   - The write tool's own description string (the text `server.py` passes to `mcp.add_tool(...)`,
     e.g. "Call `fitness_get_latest_physique_observation` first so ratings are relative to the
     last observation, not absolute" — the same style `fitness_switch_training_program`'s
     description already uses to steer multi-step behavior, `server.py:288–291`).
   - `docs/coaching-instructions.md`, which PROJECT.md records is "drift-guarded against the live
     tool registry" (Phase 7/13 validated bullets) — this is where the actual behavioral contract
     for the model lives today (`fitness_switch_training_program is the only tool that writes; it
     needs two calls..." is already an instruction there per `server.py`'s `_INSTRUCTIONS`
     constant, lines ~85–98). Add the equivalent sentence for physique's read-before-write
     sequencing.

3. **Optional secondary confirmation, after the fact, at no extra call cost:** because
   `writable_session` opens a plain (non-read-only) session, the write tool's OWN handler can, in
   the same transaction, query the observation it just inserted alongside the prior one and return
   both (or the already-computed diff, if `analytics/physique.py`'s diff function is called here
   too) in its response — so the user/Claude gets an immediate "here's what changed since last
   time" echo. This is a nice confirmation UX; it is explicitly **not** the drift mitigation, since
   by the time this tool is called Claude has already produced its rating. It answers a different
   question ("was this recorded correctly") not the one drift mitigation is about ("did Claude
   have the right anchor before rating").

### Recommendation

**A dedicated, purpose-built read tool (`fitness_get_latest_physique_observation`), documented as
the required precursor in both the write tool's own description and
`docs/coaching-instructions.md`.** This is a soft, documentation-level guarantee, not a
cryptographic one — and that asymmetry with `program_switch.py` is correct, not a compromise: the
token pattern is proportionate to an irreversible, classification-changing, single-user-confirmed
action; physique logging is an append-only data point where the cost of an occasional
drift-affected rating is low and self-correcting on the next observation. Applying the token
pattern here would be over-engineering relative to the actual risk, and would violate the
milestone's own "single-call" scoping to boot.

**Rejected alternative:** returning prior context as a field on the *write* tool's own response.
Rejected because by the time the write tool is called, Claude has already produced the rating in
its arguments — a prior-observation field on that response arrives too late to inform the rating
it's meant to calibrate; it can only ever serve the secondary "confirm what was recorded" purpose
in §5.2.3, which is not what "rates relative to it" requires.

---

## 6. Question 5 — The cross-reference ("underdeveloped AND undertrained")

### 6.1 The project's own precedent for exactly this shape

`RecompositionResult` already pairs two independently-computed signals from two different
analytics domains (body-weight trend + training progression) inside ONE composed result, and
`mcp/tools/reports.py`'s own comment states the reason explicitly (lines 121–122): *"Reported
BESIDE the status, not folded into it... a real disagreement between the label and the signal is
exactly what Claude needs to see."* `get_recomposition_status` (composed in its own module,
`analytics/recomposition.py`, not bolted onto `bodyweight.py` or `progression.py`) is the direct
precedent: cross-domain composition is analytics' job, done once, in a module named for the
composed concept, not left to the caller to join.

The same reasoning applies here. "Is the underdeveloped muscle also the undertrained one?" is a
**deterministic join over two already-computed structured datasets** (stored ratings +
`get_muscle_group_volume`'s output) keyed on the shared 19-value `CanonicalMuscleGroup` taxonomy —
it requires no vision, no subjective judgment, and no new "recommendation." It is data composition,
not coaching advice, and the D-03 "no recommendation language" rule (which the report's own
docstring is careful to scope to *language*, not to *data joins* — "This is composed DATA. Claude
synthesizes the recommendation from it," `schemas.py:1010–1013`) does not forbid it.

### 6.2 Where it should NOT live

**Not left to Claude to correlate across two tool responses.** The project's own anti-pattern
language (`ReportResult`'s docstring cites "ARCHITECTURE.md's Anti-Pattern #9 ('report tools as a
fourth copy of the analytics arithmetic')") is about backend code re-deriving numbers, but the
underlying value — one deterministic, tested implementation of a fact, reused everywhere it's
needed — argues just as strongly against making the MODEL re-derive a join every time by
eyeballing two JSON blobs. A join over 19 rows is exactly the kind of "arithmetic" this project
consistently keeps server-side and unit-tested (see `roll_up_muscles`, `app/mcp/tools/volume.py:81–101`,
for the parallel case of folding per-week-per-muscle data into one deterministic 19-row structure
"so the 19-row invariant is unit-testable with no container behind it").

**Not a bespoke join buried inside `reports.py`.** `reports.py`'s own docstring is explicit that
it "owns no arithmetic... each number was computed by a function under `app/analytics/` that
already has its own tests" (lines 1–9). A physique×volume join computed inline in `compose_report`
would be exactly the "fourth copy of the analytics arithmetic" its own Anti-Pattern #9 warns
against, since a future physique-specific MCP tool would need the identical join and would either
duplicate it or reach back into `reports.py` for it (an inversion of the dependency direction the
whole codebase enforces one way).

### 6.3 Recommendation

**A new composed function inside `analytics/physique.py` itself** —
`get_physique_training_correlation(session, *, user_id, weeks)` — that internally calls
`get_muscle_group_volume` (`analytics/volume.py`) and the latest stored ratings (via
`db/repositories/physique.py`), joins them by `CanonicalMuscleGroup`, and returns a structured
list carrying, per muscle group: the rating, the diff verdict, the volume/undertrained signal, and
a boolean/label for "underdeveloped and undertrained." This keeps `physique.py` the single home
for everything physique-domain (diff analytics + the cross-reference), matches
`recomposition.py`'s precedent of a dedicated module for a cross-domain composition, and is
importable by BOTH a new physique read tool (any time) and `reports.py`'s monthly-only section
(reusing the same function, never re-deriving it) — the identical "one implementation, imported
twice" discipline `_report_body_fields()` and `roll_up_muscles` already demonstrate elsewhere in
this codebase.

**Rejected alternative:** exposing raw ratings and raw volume as two separate fields and letting
Claude eyeball the correlation. Rejected because it reintroduces exactly the risk the project's own
`RecompositionResult` design already solved once (a disagreement between two signals is precisely
the thing worth computing explicitly, not hoping the reader notices) and produces two different
"is this muscle undertrained" answers if the report's own thresholds for "undertrained" (from
`get_muscle_group_volume`/`roll_up_muscles`) and Claude's ad hoc reading of the JSON ever diverge.

---

## 7. Question 6 — Data model and build order

### 7.1 The two existing precedents, and which one applies

| | `body_measurements` (`db/models/body.py`) | `health_daily_metrics` (`db/models/health.py`) |
|---|---|---|
| Shape | WIDE: one row per `(user, source, measured_on)`, all 17 metrics as columns | NARROW: one row per `(user, source, metric, source_name, local_day)` |
| Why wide/narrow | Hevy's API "returns one object per calendar date carrying all 17 metrics" in one call — the source is atomic per day (`body.py:7–11`) | Multiple apps write different subsets of metrics on the same day, and coverage is inherently partial per source (`health.py:1–34`) |
| Taxonomy changes | A new metric = a new column = a migration | A new metric = a new string value = no migration |

Physique observations are structurally like `health_daily_metrics`, not `body_measurements`:
**coverage is inherently partial.** A given photo set may show the front but not the back, so a
single observation may rate 12 of 19 muscle groups, not all 19 — the same "not everything arrives
together" property that made `health_daily_metrics` narrow rather than wide. A 19-column wide row
would need 19 nullable columns and would not extend cleanly if the canonical taxonomy ever grows
(muscles.py's own comment on `CanonicalMuscleGroup`, lines 23–25, already flags that changing the
enum "costs a data migration of `exercise_muscles`" — a wide physique table would inherit the same
fragility for no benefit, since every other muscle-group-shaped result in this codebase, e.g.
`MuscleGroupVolume`, `MuscleGroupFrequency`, `roll_up_muscles`'s output, is already a **list of
narrow rows**, one per group).

### 7.2 Recommended table shape

**Two tables**, migration `0007` (next after `0006_user_program_history.py`):

```python
class PhysiqueObservation(Base, TimestampMixin):
    """One point-in-time observation session (one set of photos, one sitting)."""
    __tablename__ = "physique_observations"

    id: Mapped[uuid.UUID]
    user_id: Mapped[uuid.UUID]              # FK -> users.id, CASCADE
    observed_on: Mapped[dt.date]            # local day (D-13 discipline), like ProgramPeriod.started_on
    leanness_notes: Mapped[str | None]      # bounded String(N), Claude-authored, never re-emitted in build_narrative
    conditioning_notes: Mapped[str | None]
    symmetry_notes: Mapped[str | None]
    # No `ended_on`: this is a point-in-time snapshot like BodyMeasurement, not an
    # effective-dated interval like ProgramPeriod -- nothing here is ever "closed."

class PhysiqueRating(Base, TimestampMixin):
    """One muscle group's rating within one observation. Narrow, like HealthDailyMetric."""
    __tablename__ = "physique_ratings"

    id: Mapped[uuid.UUID]
    observation_id: Mapped[uuid.UUID]       # FK -> physique_observations.id, CASCADE
    user_id: Mapped[uuid.UUID]              # DENORMALIZED, see below
    muscle_group: Mapped[str]               # CanonicalMuscleGroup.value, String(16) -- string, never a native ENUM,
                                             # matching ProgramPeriod.program's own convention
    rating: Mapped[str]                     # ordinal PhysiqueRating(StrEnum).value, String(16)

    __table_args__ = (
        UniqueConstraint("observation_id", "muscle_group", ...),   # one rating per group per observation
        Index(..., "user_id", "muscle_group", "observed_on-via-join"...),
    )
```

**`user_id` is deliberately denormalized onto `physique_ratings`**, not reached only via a join to
the header table. This mirrors `health_daily_metrics` keeping `user_id` on the same granular row
rather than requiring a join for every query — both the diff function (`get_physique_diff`) and
the cross-reference join (`get_physique_training_correlation`, §6.3) need to filter/aggregate
directly on `physique_ratings` by `(user_id, muscle_group)` across many observations; forcing a
join to the header table for every such query for a fact that never changes per observation is
pure overhead with no integrity benefit (the FK to `physique_observations.id` already pins the
row to one observation and one user via that observation).

Rating values belong in a new ordinal `StrEnum` (call it `PhysiqueDevelopmentRating` or similar —
exact member names are a requirements decision, not an architecture one), stored as a plain string
column exactly like `TrainingProgram`/`ProgramPeriod.program` — **never** a native Postgres `ENUM`
type, matching the codebase's uniform convention of "Python StrEnum + `String(N)` column" seen in
every model touched during this research (`program.py`, `body.py`, `health.py`). Free-text notes
must be genuinely bounded (`String(N)`, not `Text`) per the milestone's own "bounded free-text"
requirement — this is a schema-level enforcement of that bound, not merely a convention.

No third table is needed for either the prior-observation read tool or the cross-reference: both
are pure queries over these two tables (plus, for the cross-reference, a join against the existing
`exercise_muscles`/volume machinery) — no new storage.

### 7.3 Build order, with real dependencies

**0. Pre-deploy migration safety, first, before any physique code.** PROJECT.md's own Active
requirements rank this "Highest-value fix carried into the next milestone," and it is a genuine
dependency, not just a priority call: this milestone adds its own new migration (`0007`), and
shipping it with the exact same unguarded `scripts/deploy-cloud-run.sh` that has already let
production run behind deployed code three times this year (Phase 8's `0004` vs `0005`, the Phase 9
operator `DATABASE_URL` mistake, the Phase 13 `0005` vs `0006` `UndefinedTableError`) would very
plausibly reproduce the exact same failure a fourth time, this time on a milestone whose entire
point is a new table. Concretely: `scripts/deploy-cloud-run.sh` (read in full — lines 1–58) runs
`gcloud run deploy` with **no migration step of any kind** — there is no `--pre-deploy-command` or
equivalent invocation of `alembic upgrade head` anywhere in the script today. Add either a
pre-deploy hook that runs `alembic upgrade head` against `DATABASE_URL` before the `gcloud run
deploy` call, or an enforced `alembic current` vs `alembic heads` pre-flight that aborts the script
on mismatch (`backend/tests/test_cloud_run_deploy.py` already establishes the pattern of asserting
facts about this script statically — a new test there should assert the migration step exists,
the same way `_REQUIRED_FLAGS` currently guards `gcloud`'s own flags, lines 54–64). This must land
and be proven (a real deploy exercising it) before phase 3 below ships its own migration to
production.

1. **Data model + migration** (`db/models/physique.py`, `migrations/versions/0007_...py`) —
   foundational; nothing below can be built against real rows without it.

2. **Repository layer** (`db/repositories/physique.py`) — mirrors `programs.py`'s shape: one
   `insert_observation(session, *, user_id, observed_on, ratings, notes)` write function (the
   ONLY place that constructs the two tables' `insert()` statements), plus
   `get_latest_observation(session, *, user_id)` and `get_observation_history(session, *, user_id,
   limit)` read functions. Depends on step 1's models existing.

3. **Analytics layer** (`analytics/physique.py`) — `get_physique_diff()` (improved / unchanged /
   regressed per muscle, comparing the two most recent observations' ratings) and
   `get_physique_training_correlation()` (§6.3's cross-reference, importing
   `analytics/volume.py::get_muscle_group_volume`). Both read-only, both provable against
   `test_analytics_isolation.py`'s existing static guards with zero new exemptions needed (no
   `app.mcp` import, no session write, no raw SQL text, no `float`). Depends on step 2's read
   functions.

4. **Widen the MCP write/annotation guards** (§2.2, all three test files) — done as its own
   reviewable step, deliberately separated from the tool code it enables, mirroring how Phase 12
   treated the original guard narrowing as a first-class, individually-reviewed change rather than
   a side effect of adding `program_switch.py`.

5. **MCP tools** (`mcp/tools/physique.py`): the write tool
   (`fitness_log_physique_observation`, `writable_session`, calling step 2's insert function) and
   the read tool(s) (`fitness_get_latest_physique_observation` for §5's precursor;
   optionally a second read tool exposing step 3's diff/cross-reference, or fold both into one
   `fitness_get_physique_progress` read tool — a genuinely open naming/count question for the
   roadmapper, not an architecture one). Register in `server.py` with the new
   `APPEND_ONLY_WRITE_TOOL` annotation for the write tool and `READ_ONLY` for the read tool(s).
   Depends on steps 3 and 4.

6. **Monthly report integration** (§3): `ReportResult.physique` field + `compose_report()`'s
   period conditional (`analytics/reports.py`), `build_narrative`'s new "## Physique" section
   under §4's constraints, `MonthlyReportResponse.physique` field mirroring `narrative`
   (`mcp/tools/schemas.py`), `_degraded_body_fields()`/`_degraded_monthly()` updated
   (`mcp/tools/reports.py`). Depends on step 3 (needs the analytics functions to call) — does
   **not** strictly depend on step 5 (the report can call `analytics/physique.py` directly without
   the standalone MCP tools existing yet), but building step 5 first gives real, testable
   observation data to compose the report against rather than only hand-built fixtures.

7. **`docs/coaching-instructions.md` update** — required in the same phase as step 5, since
   PROJECT.md records this document as drift-guarded against the live tool registry; the new
   tool names must appear, and this is where §5.2's "call the read tool first" steering text
   actually lives for the model to see it.

8. **Production deploy of migration `0007`**, exercised through step 0's now-fixed pre-deploy
   mechanism — the first real-world proof that the mechanism built in step 0 actually prevents the
   failure mode it was built for, closing the loop PROJECT.md names explicitly.

**Dependency summary:** 0 blocks 8 only (but should be done first regardless, as standing debt
independent of this feature) → 1 blocks 2 → 2 blocks 3 → {3, 4} block 5 → 3 blocks 6 → {5} should
precede 6 for testing convenience but does not strictly gate it → 7 ships alongside 5 → 8 requires
0 and 1 both complete.

---

## Sources

All findings above are grounded in the following files, read in full or in the cited sections —
no external documentation was needed for this research; the questions are entirely about this
repository's own established conventions:

- `.planning/PROJECT.md` — milestone scope, shipped history, the exact three-times-behind-schema
  incidents cited in §7.3 — **HIGH** (primary source document, authored by/for this project)
- `backend/app/analytics/reports.py`, `backend/app/mcp/tools/reports.py` — `compose_report`,
  `build_narrative`, `_report_body_fields`, `_degraded_body_fields` — **HIGH** (read in full)
- `backend/app/mcp/tools/program_switch.py`, `backend/app/db/repositories/programs.py`,
  `backend/app/db/models/program.py` — the only existing write path, read in full — **HIGH**
- `backend/app/mcp/tools/_common.py`, `backend/app/mcp/server.py` — `read_only_session`,
  `writable_session`, `safe_tool`, tool registration and annotation objects, read in full — **HIGH**
- `backend/tests/test_mcp_isolation.py`, `backend/tests/test_mcp_readonly.py`,
  `backend/tests/test_analytics_isolation.py`, `backend/tests/test_mcp_tool_schemas.py`,
  `backend/tests/test_analytics_reports.py`, `backend/tests/test_migrations.py`,
  `backend/tests/test_cloud_run_deploy.py` — every guard cited by name and line number was read
  directly, not inferred — **HIGH**
- `backend/app/analytics/schemas.py`, `backend/app/normalization/muscles.py` — `ReportResult`,
  `RecompositionResult`, `CanonicalMuscleGroup` (the 19-value taxonomy), `BodyMeasurementTrendResult`
  — **HIGH**
- `backend/app/analytics/body_measurements.py`, `backend/app/db/models/body.py`,
  `backend/app/db/models/health.py` — the wide-vs-narrow precedent analyzed in §7.1 — **HIGH**
- `scripts/deploy-cloud-run.sh` — read in full; confirmed no migration step exists today — **HIGH**
- `backend/migrations/versions/` directory listing — confirmed `0006_user_program_history.py` is
  head, so the new migration is `0007` — **HIGH**
