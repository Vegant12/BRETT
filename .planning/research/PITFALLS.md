# Pitfalls Research — v2.1 Longitudinal Physique Analysis

**Domain:** Adding model-generated (VLM/LLM subjective) longitudinal observations to an existing
deterministic, SQL-first fitness-analytics system with a read-only MCP surface and one prior
confirm-gated write tool.
**Researched:** 2026-09-05
**Confidence:** MEDIUM overall — HIGH on everything traceable to this repo's own code and tests
(recomposition.py, body_measurements.py, test_mcp_isolation.py, test_analytics_reports.py,
logging.py); MEDIUM on VLM/LLM rating-consistency and anchoring claims, sourced to academic
literature rather than to a controlled test of *this* model on *this* task, which does not yet
exist and which Pitfall 1 recommends running before the schema is locked.

This file assumes familiarity with `.planning/research/PITFALLS.md`'s v2.0 predecessor (not
duplicated here) — in particular its Pitfalls #13–16, which established the confirmation-token
pattern, the write-guard narrowing pattern, the `safe_tool` three-state result pattern, and the
append-only-history-over-mutable-column pattern. Every one of those precedents is reused, not
reinvented, below; the new pitfalls are where reuse is *not* enough.

---

## Critical Pitfalls

### Pitfall 1: The vision model does not agree with itself, and there is no ground truth to check it against

**What goes wrong:**
Asked to rate the same physique twice — same photos, same day, fresh context — a VLM will not
return identical per-muscle-group ratings on a 19-value taxonomy. This is not a BRETT-specific
risk; it is a documented property of LLM/VLM judgment. "Rating Roulette: Self-Inconsistency in
LLM-as-a-Judge Frameworks" (arXiv:2510.27106, Oct 2025) reports low intra-rater reliability
across repeated runs on subjective scoring tasks — "almost arbitrary in the worst case." The same
line of work notes a genuine trade-off BRETT cannot dodge: forcing `temperature=0` for
reproducibility can *degrade* agreement with a plausible human rating, while sampling at
`temperature=1` and aggregating improves accuracy but destroys the very reproducibility a
byte-identical, testable system wants (MEDIUM confidence — general LLM-judge literature, not a
BRETT-specific or vision-specific measurement).

BRETT has no independent ground truth to reconcile this against. Unlike a workout set (kg × reps,
checkable against the Hevy app) or a nutrition macro (checkable against Apple Health), a physique
rating's only possible check is a photo BRETT has deliberately chosen never to store. Once the
rating is written, there is nothing left in the system to re-derive it from or audit it against —
the observation *is* the record, permanently, from that point on.

Sources of drift beyond pure sampling noise, specific to this feature's multi-month lifetime:
- **Model version changes.** The user's Claude Project will be served by whatever model version
  Anthropic runs on a given month. A rating taken in September under one model and one taken in
  December under a newer model are not directly comparable, and nothing in the stored schema
  says which model produced which row.
- **Photo condition variance.** Lighting, angle, camera, pose, time of day (pre/post-workout
  pump, hydration, sodium/carb timing) all move a physique rating independent of any real
  change — variance the user does not control turn-by-turn and BRETT cannot see, since it never
  receives the photo.
- **Conversational framing.** The exact wording of the request, what else is in context, and how
  the prior observation is presented can all shift the rating, because the rating is produced by
  a general-purpose conversational model, not a calibrated instrument.

**Why it happens:**
The milestone's own design (PROJECT.md) already reduces variance the smart way — relative rating
against the prior observation rather than absolute rating from scratch — but that mitigation
targets *inter-session* variance (comparing month N to month N+1), not *intra-session*
reproducibility (would this exact request, run twice, produce the same output). No test in this
codebase's tradition (byte-identical narrative, deterministic classification, container-verified
analytics) can be applied to the rating-production step itself, because that step happens inside
Claude's conversation, outside BRETT's process, with no BRETT-side determinism lever to pull.

**How to avoid:**
- **Run a self-consistency spike before finalizing the schema or the write tool's contract.**
  This is the milestone's central, retirable-with-evidence risk — the same shape as Phase 2's
  auth spike and Phase 13's RPT-03 scheduled-task spike. Concretely: submit the same 2–3 sets of
  progress photos to Claude for physique rating multiple times (same session, fresh sessions,
  different phrasing of the request), with and without a synthetic "prior observation" context,
  and record how much the per-muscle rating and the free text move. This produces the number that
  should set the diff analytics' "improved/regressed" thresholds in Pitfall 4's sibling module
  (`analytics/physique.py`) rather than guessing at a semantically meaningful step size on a
  19-value taxonomy.
- **Persist provenance with every observation**, not just the rating: which model surfaced it
  (from context available at write time, or a fixed schema version if the model identity is not
  reliably obtainable), and the raw timestamp. This does not fix drift, but it makes a
  model-version discontinuity a queryable fact instead of an invisible one — the same posture
  `source_name` takes for Health Auto Export vs Hevy write-back (v2.0 Pitfall #7/#8 precedent).
- **Never present a rating with implied numeric precision it cannot support.** A 19-value
  taxonomy is already coarse by design; treat it as ordinal, never as an interval scale a diff
  can average or interpolate on (this is also Pitfall 4's concern, from the analytics side).
- **Do not build a false-precision confidence score.** A model-reported "confidence: high" on its
  own rating is not evidence of accuracy — VLMs are not calibrated instruments, and manufacturing
  a confidence field would give the illusion of a QA mechanism this design does not have.

**Warning signs:**
Two observations logged minutes apart (a user re-running the analysis to "check") disagree on a
muscle group's rating. A rating changes direction (improved → regressed → improved) across three
consecutive monthly observations with no plausible physiological cause. The free-text notes for
two consecutive months contradict each other on a directly observable fact (e.g., one month notes
"visible ab separation," the next says "no visible abs" with no intervening cut).

**Phase to address:** A dedicated spike phase, before the physique write tool or schema is
finalized — this is the milestone's highest-uncertainty question and should be retired with
evidence the way v2.0's RPT-03 was, not assumed.

---

### Pitfall 2: The anchoring mitigation is also a ratchet — the second-order risk the milestone accepted without a bound

**What goes wrong:**
Feeding the prior observation as context is a real and well-motivated mitigation for one failure
mode (absolute-rating drift across sessions with no memory) — but it trades that failure mode for
a different one: **anchoring the model on its own prior output**. A rater told "last time you
said this muscle group was a 7" is now primed to answer "still about a 7, maybe a shade better,"
regardless of what the current photo actually shows, because relative judgment against a stated
anchor is exactly the psychological effect the technique is named for. Sequential-judgment
research on repeated subjective ratings (face attractiveness, ringtone agreeableness — Yu &
Zhang, PMC5995378) documents both contrastive and *assimilative* sequential effects, and notes the
assimilative effect specifically "is strengthened by response repetition" — i.e., by exactly the
pattern of feeding the same rater its own last answer, repeatedly, that this design is built
around (MEDIUM confidence — psychology-of-judgment literature on repeated ratings generally, not
a study of this exact VLM-anchoring setup). A closely analogous applied finding: sequential
context effects have been documented in radiologists' diagnostic interpretation of successive
mammograms (PMC5858736) — a domain chosen deliberately close to this one, since it is also
"look at an image, judge a body, informed by what was just seen or said before."

**The specific second-order failure this produces: a slow ratchet.** If each monthly rating is
nudged at most one step from the last — which is exactly what a well-behaved, cautious anchored
rater would do — then twelve consecutive one-step nudges in the same direction are
indistinguishable, month to month, from twelve *accurate* one-step improvements. Every individual
comparison looks reasonable (a coach being appropriately conservative, not overclaiming a big
jump off one photo) while the cumulative year-over-year claim silently drifts arbitrarily far from
what an independent rater looking at month 1 and month 12 side by side would actually say. This is
the physique-rating analogue of a "boiling frog": no single narrative sentence is wrong, but the
composed twelve-month story is unmoored from ground truth and nothing in the system would notice,
because BRETT never holds the two photos to re-compare directly, and no analytics function in
`app/analytics/physique.py` would have a signal to catch it — pairwise `improved/unchanged/
regressed` diffs are exactly the computation that is blind to a slow monotonic ratchet, since
every adjacent pair passes.

This is worse, not better, than pure noise. Noise (Pitfall 1) is at least *unbiased* — it
averages toward the truth over many observations. A ratchet is *biased* — it accumulates in one
direction and does not self-correct, and the direction it accumulates in is influenced by
whatever the user's phrasing or mood implies about what they hope to hear, since the model is a
conversational partner, not a blinded rater.

**Why it happens:**
The anchor was chosen to solve a real problem (an unanchored rater re-deriving a rating from zero
every month is itself high-variance and possibly worse) and the tradeoff was accepted at the
milestone gate as "the feature's load-bearing design decision" without, at gate time, a
corresponding bound on how far the anchor may drift before it must be checked against something
outside the anchor chain. A mitigation for one failure mode was adopted without asking what new
failure mode it introduces — the same category of near-miss v2.0 caught for
`confirm: bool` (PITFALLS v2.0 #13: a fix for the "no confirmation at all" problem that was itself
not actually a gate).

**How to avoid — periodic re-anchoring, plus a bounded-drift detector:**
- **Never carry the anchor forward indefinitely without a reset.** Establish a maximum number of
  consecutive anchored (relative) observations — e.g., after N months of relative rating, the next
  observation must be rated blind (no prior-observation context passed), producing an independent
  data point the ratchet cannot have biased. Treat the gap between the last anchored rating and
  this fresh blind rating as the re-anchoring signal: a large jump reveals how far the chain had
  drifted; a small one is reassuring evidence the chain tracked reality.
- **Cross-reference against an independently-measured, non-model signal wherever one exists.**
  This system already has one: `fitness_get_muscle_group_volume` (per-muscle direct/indirect
  training volume) and `fitness_get_body_measurement_trend` (waist_cm, measured). A muscle group
  reported as "steadily improving" for six consecutive months while its training volume is flat
  or declining, or while body weight/waist trend shows no plausible mass gain, is a coherence
  check a ratchet would fail even though no single physique observation would. This is squarely
  what the milestone's own "cross-reference physique observations against
  fitness_get_muscle_group_volume" feature should be scoped to catch, not just to narrate — design
  it to SURFACE the disagreement (as a flag Claude can see and question the user about), not
  merely to co-display two numbers.
- **Bound the per-observation step size structurally, and make the bound visible.** If the
  taxonomy allows a rating to move by at most one step per observation (a plausible product
  decision to prevent single-photo overclaiming), that same rule is the thing that makes a
  twelve-step ratchet possible. If this bound is adopted, pair it with the periodic blind
  re-anchor above — a step-size cap with no periodic reset is a ratchet with a guaranteed floor
  under how fast it can happen and no ceiling on how far it goes.
- **Never let `build_narrative` describe a rating trend across more than the two most recent
  observations as if it were a continuous verified improvement.** "Improved every month for a
  year" is a much stronger and more falsifiable claim than "improved since last month" — the
  former needs an average-of-first-half-vs-average-of-second-half framing at minimum, not a
  chained string of one-step deltas, mirroring how `body_measurements.py`'s BODY-05 deliberately
  chose latest-vs-earliest over a rolling average for a similarly untrustworthy long chain of
  sparse comparisons (see Pitfall 6).

**Warning signs:** A muscle group whose rating has moved in the same direction for four or more
consecutive observations with no corresponding volume or weight-trend signal. A user expressing
surprise that a "steady improvement" narrative doesn't match how they feel looking in the mirror.
No test or analytics function in the codebase computes anything using more than adjacent-pair
history.

**Phase to address:** The physique-analytics phase (`analytics/physique.py`) should implement the
cross-reference-as-coherence-check from day one, not as a "nice to have" narrative addition. The
periodic-blind-re-anchor policy is a product/prompt-level decision that belongs in the same
spike as Pitfall 1 — it cannot be validated without first knowing how much a blind rating differs
from an anchored one on the same photos.

---

### Pitfall 3: A rating sitting beside a measurement in one report reads as equally authoritative to both the model and the human

**What goes wrong:**
The monthly report will place `weekly_volume.hard_sets` (a count from stored Hevy sets),
`body_weight_trend.trend_rate_kg_per_week` (a rolling average of scale readings), and a physique
observation's per-muscle rating in the same document, under headings of equal visual weight. For
the human reading it, an opinion with a timestamp inherits the report's ambient credibility —
everything else in it has been true so far. For Claude *composing or discussing* the report, the
risk is sharper: the coaching instructions' central rule is "never substitute general training
knowledge for the user's actual data, and never estimate a number a tool can return" — a rule
written entirely around the assumption that every number the tool returns is data-in-the-measured
sense. Nothing in `docs/coaching-instructions.md` today distinguishes "cite this figure with full
confidence" from "cite this figure as what a model said it saw," because no such figure has ever
existed in this system before.

This codebase already has exactly the right precedent for the fix, applied to a different kind of
uncertainty. `RecompositionResult.disclaimer` (`app/analytics/recomposition.py`) is documented as
"a REQUIRED FIELD, not documentation, so that a Phase 6 serialization change cannot drop it" — a
fixed, verbatim, non-generated string that travels with the verdict everywhere it goes, precisely
because a recomposition status is *decision support, never a diagnosis* and needs to say so on
every appearance, not just in a docstring. A physique rating needs the identical treatment for a
related but distinct reason: it is not decision support that might be wrong, it is *model output
that is definitionally an opinion*, and conflating "here is a number I am confident about" with
"here is what a vision model said it saw in a photo, once, this month" is the actual failure this
pitfall names.

**How other systems handle this:** provenance-tagging literature on AI-generated vs
human-authored content (data-provenance standards work, NTIA's AI-output-disclosure framework)
converges on tagging generation/annotation provenance as metadata that travels with the value, not
as prose the reader must remember to apply. One directly sobering finding from user-facing
labeling research: "labeling messages as AI-generated does not reduce their persuasive effects"
(PMC12887897) — a disclaimer sentence alone, once read, does not reliably change how much weight
a reader gives the content that follows it. This argues for *structural* separation (its own
report section, its own response field, a rating that cannot be quoted without its accompanying
disclaimer field the way `RecompositionResult.disclaimer` already cannot), not merely a caveat
sentence trusted to do the whole job.

**Why it happens:** Every other value in this system earned its trust the hard way — it is
either read directly off a device (Hevy sets, Apple Health steps) or computed deterministically
from device-read values with a documented formula. Extending the report's "everything here is a
number, present it as one" convention to a rating that has neither property is the path of least
resistance, and the report composer's existing `_report_body_fields` sees no structural difference
between a `Decimal` and a `PhysiqueRating` — both are just fields on a dataclass to it.

**How to avoid:**
- Give the physique section its own **required, non-optional disclaimer field**, worded to name
  what it is (a vision-model opinion from a photo, not a measurement), following
  `RecompositionResult.disclaimer`'s exact pattern: a module-level constant, never model-generated
  prose, asserted present by a test the way `test_the_disclaimer_appears_verbatim_on_its_own_line`
  already asserts for recomposition.
- **Label every rated field by construction, not by convention** — e.g., a wrapper type or a
  consistent field-naming scheme (`*_rating`, never `*_score` or `*_percent`, which read as
  measured) so a future reader of the schema, not just the narrative, can tell rated from measured
  apart at a glance.
- Update `docs/coaching-instructions.md`'s metadata-envelope table (the one governing
  `freshness`/`coverage`/`data_available`) with a new row for the physique disclaimer, with the
  same "surface this before the answer, not after" instruction the recomposition disclaimer
  already gets, and add physique to `test_coaching_doc.py`'s drift guard the same way every other
  tool is covered.
- In the narrative itself, use a distinct verb register for rated content versus measured content
  — "logged as," "rated as," "noted as" for physique; "measured," "recorded," "totaled" for
  everything else — enforceable the same mechanical way the banned-recommendation-token scan
  already works (see Pitfall 4).

**Warning signs:** A physique rating printed in the narrative with no distinguishing language from
a measured figure on the same line. A user or Claude citing a physique rating with the same
confidence as a body-weight trend in the same sentence. The disclaimer field being optional
(`| None = None`) rather than required.

**Phase to address:** Schema design, at the point `PhysiqueObservation`/`PhysiqueReport` types are
defined — the disclaimer must be a required field from the first migration, not bolted on after
the report-integration phase discovers the ambiguity live.

---

### Pitfall 4: The determinism contract breaks in ways specific to rated, textual content — not the ways it has been tested against before

**What goes wrong:**
`build_narrative` is enforced pure, byte-identical, free of recommendation language, and free of
any number not already present in the structured data
(`test_the_narrative_is_byte_identical_across_calls`,
`test_the_narrative_contains_no_recommendation_language`,
`test_every_number_in_the_narrative_is_already_in_the_structured_fields`, all in
`backend/tests/test_analytics_reports.py`). A physique section threatens all three, by different
mechanisms than anything the narrative has handled before:

1. **Byte-identical is trivially satisfiable and therefore not the useful part of the guarantee.**
   `build_narrative` restating a *stored* rating and a *stored* free-text note twice will of
   course produce the same bytes twice — it's the same input dict rendered by the same pure
   function. The test will pass immediately and prove nothing new. The actual risk is upstream of
   `build_narrative`: if `compose_report` (or the physique write tool) ever calls the model again
   at *read* time — to "refresh" a rating, to summarize multiple observations into new prose, to
   generate a friendlier phrasing of a stored note — purity is gone, because two calls to
   `compose_report` on the same underlying rows can now legitimately return different bytes. The
   design as scoped avoids this (persist once at write time, read back verbatim at report time),
   but it is exactly the kind of scope creep a future "make the note read better" request would
   reach for, and it is precisely the boundary `test_build_narrative_is_synchronous_and_pure`
   exists to hold.
2. **Free text is the banned-token scan's actual test.** `_BANNED_NARRATIVE_TOKENS` (`should`,
   `recommend`, `suggest`, `consider`, `advise`, `deload`, `aim for`, `you need`, `try `) was
   written against numbers-and-labels prose the backend itself composes. A user-attached physique
   note is bounded free text *produced by a model, at write time, about a person's body* — a
   fundamentally more likely place for advisory language to slip in ("consider adding volume to
   lagging delts") than anything the deterministic analytics layer has ever emitted. If that note
   is stored verbatim and later restated by `build_narrative`, the scan will genuinely and
   correctly fail — which is the *right* outcome, but only if the constraint is enforced where it
   is cheap to fix: **at write time**, not discovered for the first time when a stray monthly
   report fails CI. The write tool itself should scan and reject (or truncate/strip) recommendation
   language in the free-text notes before persisting, using the identical token list the narrative
   test already has, so the two enforcement points cannot drift apart.
3. **Numeric provenance breaks the moment free text contains any number.** A plausible, entirely
   reasonable note — "waist looks like it's dropped maybe an inch, upper body noticeably fuller"
   — contains no formal number, but "an inch" is one bad phrasing choice away from "waist down
   ~2.5cm," which is a number the structured fields do not carry (there is no
   `PhysiqueObservation.waist_delta_cm` — that number belongs to `fitness_get_body_measurement_trend`,
   a different tool entirely) and `test_every_number_in_the_narrative_is_already_in_the_structured_fields`
   would correctly flag it as a number the narrative introduced that the structured data does not
   support. **Bound the free-text notes to qualitative language only, enforced at write time** —
   either a schema-level constraint (reject notes containing digit sequences, mirroring
   `_NUMBER_RE`) or an instruction to the model at generation time backed by the same rejection as
   a backstop, never trusted alone.
4. **The disclaimer-verbatim pattern must be replicated exactly, not approximated.** Pitfall 3's
   physique disclaimer needs its own
   `test_the_physique_disclaimer_appears_verbatim_on_its_own_line`-shaped test from day one,
   because a narrative-generation refactor six months from now has no way to know a second
   disclaimer needs the same protection `INTERPRETATION_DISCLAIMER` already has unless a test says
   so.

**Why it happens:** The determinism guards were designed and hardened entirely against
backend-generated, numeric, formulaic prose. Physique observations are the first content in the
system's history that is (a) free text, (b) written by a model, and (c) about a subjective
judgment. Every existing guard generalizes almost, but not quite, cleanly to this new shape, and
"almost" is where a real report ships a banned word or an orphan number the first time a user's
note happens to phrase things unluckily.

**How to avoid:** Enforce the free-text constraints (no banned tokens, no bare numbers, length
cap) **in the write tool**, at persistence time, not only downstream in the narrative test suite —
the write tool is the one place a rejection can still ask the model to rephrase before anything is
committed; the narrative test can only fail a build months later on a note already in the
database. Reuse `_BANNED_NARRATIVE_TOKENS` and `_NUMBER_RE` (or extract them to a shared module
both the write tool and the test suite import) so the two checks are provably the same check, not
two lists someone forgot to keep in sync.

**Warning signs:** A physique note stored with a number in it. A CI failure on
`test_every_number_in_the_narrative_is_already_in_the_structured_fields` traced back to a physique
note weeks after it was written, rather than caught at write time. Any code path where
`compose_report` or the physique section performs an `await` into anything other than
`app/analytics/`/`app/db/repositories/` — a model call hiding inside report composition.

**Phase to address:** The write-tool phase owns the write-time constraint; the report-integration
phase owns extending the existing narrative test suite with physique-specific fixtures that
exercise a banned-token note and an over-numeric note as red-test regressions, not just green-path
happy cases.

---

### Pitfall 5: `_report_body_fields` is one shared projection, and physique is deliberately not shared

**What goes wrong:**
PROJECT.md already names this exactly: "`_report_body_fields` must be split on purpose. It is
currently ONE shared projection, which is what makes 'the same sections in both reports' true
rather than a convention; monthly-only physique breaks that deliberately." Reading
`app/mcp/tools/reports.py` confirms the mechanism: `_report_body_fields(report)` builds one dict
consumed by both `WeeklyReportResponse(**_report_body_fields(report))` and
`MonthlyReportResponse(**body_fields, ...)` — a single function whose entire value is that weekly
and monthly cannot silently diverge in what they include. The natural, minimal-diff way to add a
field is to add one line inside `_report_body_fields`. That is exactly the change that ships
physique data into the **weekly** report too, contradicting the explicit "weekly report
deliberately excluded" requirement, and it would ship silently — nothing in the existing test
suite asserts weekly *excludes* fields monthly has, because until now there were none to exclude.

**Why it happens:** The shared-projection function is the path of least resistance for "add a new
field to the report," and every existing field in it genuinely does belong in both reports. There
is no established pattern in this codebase yet for "a monthly-only addition," because this is the
first one.

**How to avoid:** Keep `_report_body_fields` unchanged as the *shared* projection, and add
physique assembly as a separate step applied only inside the monthly branch of the tool
registration (`fitness_get_monthly_report`), never inside the shared function. Add a test that
specifically builds a weekly report against a user/window with physique observations present in
the database and asserts the weekly response contains no physique field at all — a
positive-exclusion test, not just an absence of a positive-inclusion test, mirroring how
`test_both_periods_return_the_same_sections` already exists as the parallel positive-inclusion
check for the shared fields today (that test will need updating to assert physique is the
documented *exception* to "same sections," not silently broken by it).

**Warning signs:** A diff that adds a `physique` key inside `_report_body_fields`'s return dict.
A green `test_both_periods_return_the_same_sections` after physique ships, with no update — that
test passing unchanged is itself the warning sign, since it means physique was either added to
both or added to neither, and the requirement calls for neither of those.

**Phase to address:** The report-integration phase, as its first task before any physique field is
wired in — get the split right before there is anything to leak.

---

### Pitfall 6: Sparse, irregular photo cadence breaks the diff analytics the same way it broke BODY-05, with one more failure mode BODY-05 didn't have

**What goes wrong:**
BODY-05 (`app/analytics/body_measurements.py`) already lived through this exact class of problem
and the fix is directly precedented: real body-measurement coverage was so sparse (waist 15/123
days, body fat 0/123) that a rolling-average-with-a-measured-day-floor design — the shape
`bodyweight.py` uses — would return `insufficient_data` almost universally, so BODY-05 chose a
latest-vs-earliest comparison over a fixed 90-day window instead, with staleness and
insufficient-data reported as two *independent* signals rather than one collapsed flag.

Physique observations will be sparser still — plausibly monthly at best, since taking and
submitting progress photos is a manual, deliberate user action with no automatic sync behind it
at all (unlike body measurements, which ride in on every Hevy sync). The specific cadences named
in the question, and how each must be handled without a false claim:

- **One observation ever.** There is no prior to diff against and no meaningful "improved /
  unchanged / regressed" to report. The analytics function must return an explicit
  `insufficient_data`/no-comparison state per muscle group — mirroring
  `BodyMeasurementTrendResult`'s `earliest_value=None` when `coverage.insufficient_data` — never a
  default "unchanged," which would misreport "we have nothing to compare" as "nothing changed."
  This is the single most likely first-month state after the feature ships and must be a
  first-class tested path, the same way `recomposition.py`'s own module docstring flags
  `insufficient_data` as "the expected answer on live data today ... a first-class tested path."
- **Two observations four days apart.** Both technically exist and a diff is computable, but four
  days is not enough time for any real muscle-group development change to occur — any reported
  "improved" here is measuring photo/lighting/pump variance and Pitfall 1's noise floor, not
  physiological change. A minimum-elapsed-time gate is needed (analogous to
  `RECOMP_MIN_CLASSIFIED_EXERCISES`'s "three is the smallest number for which a majority exists at
  all," or `PlateauResult.min_elapsed_days`) — a diff computed from two observations closer
  together than some floor (plausibly weeks, tunable) should report as unable to attribute a real
  change rather than silently rendering the model's noise as a verdict.
- **Two observations eight months apart.** A real diff is computable and the elapsed time is
  clearly long enough for genuine change — but eight months is also long enough that Pitfall 1's
  drift/model-version risk and Pitfall 2's ratchet risk (if anchored) both apply at their worst.
  This case should be reported *with* its actual elapsed-time context surfaced prominently (the
  same way BODY-05 surfaces `days_since_latest_reading` and `is_stale` as visible facts, not
  buried internals) — an eight-month gap is meaningfully different context from a one-month gap
  and Claude should be able to say so, not treat every "improved" verdict identically regardless
  of how much time backs it.

**The failure mode BODY-05 did not have:** BODY-05's inputs are Decimal measurements — a
subtraction of two precise numbers is always exact and always meaningful once the floor clears.
Physique ratings are ordinal categories on a 19-value taxonomy; "improved" is not a subtraction,
it is a directional comparison on an enum, and the analytics function must define — as data, the
same way `recomposition.py`'s label matrices are data rather than nested ifs — exactly which
taxonomy transitions count as improved/unchanged/regressed, with no silent default for an
unexpected pair. A closed taxonomy makes this enumerable and testable (mirroring
`classify_recomposition`'s 76-pair-tested label matrices), but only if it is built that way
deliberately rather than as an ad hoc `>`/`<` comparison on whatever underlying representation
the taxonomy uses.

**Why it happens:** It is tempting to copy `bodyweight.py`'s rolling-average shape for "yet
another trend function" out of consistency with the rest of the analytics module, exactly the
temptation BODY-05's own module docstring warns against copying uncritically ("Deliberately NOT
`bodyweight.py`'s rolling-average shape").

**How to avoid:** Design `analytics/physique.py` around BODY-05's precedent from the start:
latest-vs-prior (not a rolling window), independent `insufficient_data`/`is_stale`-shaped signals,
an explicit minimum-elapsed-time floor for calling a two-point diff meaningful, and a closed,
tested transition table for taxonomy-to-taxonomy comparisons. Treat "zero observations" and "one
observation" and "two observations too close together" as three distinct, separately tested
`insufficient_data` paths, not one.

**Warning signs:** A diff function that returns "unchanged" as its default/else branch rather than
as an explicit taxonomy-transition result. A single observation producing a non-null "trend."
Copy-pasted code from `bodyweight.py`'s rolling-average window logic anywhere in
`analytics/physique.py`.

**Phase to address:** The physique-analytics phase, informed directly by whatever real cadence
the user's actual photo-submission habit turns out to be (unknown until the feature ships — treat
the assumed minimum-elapsed-time floor as `[ASSUMED]` and documented the way BODY-05's
`STALE_AFTER_DAYS` is, a one-constant change if wrong).

---

### Pitfall 7: Widening the read-only guard from one allowlisted module to two is where the guard's whole design gets tested for real

**What goes wrong:**
`test_mcp_isolation.py`'s `_WRITE_ALLOWLIST` is a `frozenset` asserted to contain **exactly one**
entry (`program_switch.py`), with three separate tests locking that in from different angles
(`test_mcp_never_writes`'s trailing assertion, `test_the_write_allowlist_holds_exactly_one_module`,
`test_only_one_module_opens_a_writable_session`). This milestone's physique write tool is a second
module that must commit. The mechanical part — add the module's filename to the frozenset,
raise the length assertion to 2 — is trivial and is *not* the risk. The risk is what "amendment,
not relaxation" (PROJECT.md's own stated posture) actually requires beyond that one-line change,
and which of the surrounding guarantees a lazy version of this change would quietly drop:

- **A distinct, correctly-shaped `ToolAnnotations`.** v2.0 Pitfall #14 already documented that
  `program_switch.py`'s tool needed `read_only_hint=False, destructive_hint=True,
  idempotent_hint=False`, registered *outside* the shared `_TOOLS` read-only loop, with
  `test_every_tool_is_annotated_read_only` updated to assert the exact partition by name. A
  physique write is **not destructive** in the same sense a program switch is (it does not change
  a governing state that alters every future classification) but it **is not idempotent** either —
  calling it twice creates two observations, not one updated one (see Pitfall 9). The temptation
  is to copy `program_switch.py`'s annotations wholesale; the correct move is to derive this
  tool's own annotations from its own actual properties and update the partition assertion to
  name three groups (N read-only, this tool, program_switch), not stretch a boolean check to
  "two tools aren't read-only."
- **`writable_session`, not `read_only_session`.** `program_switch.py`'s own docstring states it
  "must NOT import the read-only session helper from `_common`... importing that helper here would
  be a standing invitation to reach for the wrong one." The same sentence must be true, verbatim,
  of the physique write module, and `test_only_one_module_opens_a_writable_session`'s assertion
  needs to grow from `{"program_switch.py"}` to `{"program_switch.py", "physique_observations.py"}`
  (or whatever the module is named) — an assertion that fails loudly, by name, if a second module
  is missed.
- **The write import ban keeps applying with NO allowlist**, exactly as it does today
  (`_WRITE_IMPORT`'s regex has no exemption list at all — it is checked against every module,
  allowlisted for `_SESSION_WRITE` or not). The physique write tool must, like `program_switch.py`,
  call into `app/db/repositories/` for the actual `insert`, never construct one under `app/mcp/`
  itself.
- **Confirm the append-only, non-destructive framing is actually true at the schema level, not
  just in the tool's docstring.** "Append-only" is a real property only if there is no `UPDATE`
  or `DELETE` path anywhere reachable from this tool or any other — worth a schema-level backstop
  (no `updated_at`-triggering mechanism, a table with `INSERT`-only grants if the deployment
  target's permission model supports it) rather than resting entirely on "the code doesn't call
  update."

**What distinguishes a correct amendment from a quiet relaxation, concretely:** a correct
amendment leaves `test_mcp_never_writes`, `test_the_write_allowlist_holds_exactly_one_module` (now
"...exactly two..."), and `test_only_one_module_opens_a_writable_session` all *still asserting an
exact, named, closed set* — the tests keep their shape and grow their membership by exactly one,
deliberately, in the same commit that adds the tool. A quiet relaxation is any change that makes
one of these tests structurally *more permissive* — turning `frozenset({"a", "b"})` into a length
check, or `== {"a", "b"}` into `.issuperset({"a"})`, or deleting one of the three tests because
"it's basically the same as the other one now." The moment a length or membership assertion
becomes a pattern-match or a subset check, a third write tool arriving later stops being a red
test and starts being silently accepted — which is the exact failure v2.0 Pitfall #14 named and
which this milestone is the first real chance to get wrong by generalizing carelessly.

**Why it happens:** The existing tests were written and correctly reviewed for the "exactly one"
case; extending them to "exactly two" requires touching hard-coded literals in three places, and
the fastest-looking fix — loosening the assertion shape instead of listing both names — looks
identical in a diff review unless the reviewer is specifically looking for it.

**How to avoid:** Treat the frozenset/exact-membership assertions in `test_mcp_isolation.py` as
themselves requiring a code-review checklist item: "does every guard still name every allowed
module explicitly, with no assertion weakened to a superset/pattern check." Write the new tool's
own docstring to state, the way `program_switch.py`'s already does, exactly which guard it is
allowlisted in and why, so grepping for the tool's filename surfaces the guard's location.

**Warning signs:** A diff touching `test_mcp_isolation.py` that changes an `==` to an `in`, a
`frozenset` to a `set`, or a length assertion to a range. Any of the three write-guard tests
deleted rather than extended.

**Phase to address:** The physique write-tool phase, as an explicit success criterion ("the
write-guard tests grow from one named module to two named modules, with no assertion shape
loosened") — not left implicit.

---

### Pitfall 8: A single-call, autonomous, append-only write tool has no built-in defense against duplicate observations

**What goes wrong:**
`program_switch.py` is deliberately **two calls** — the first call is inert (it only issues a
token), and the state-changing call requires that exact server-issued token back, which is what
makes a model unable to switch a program by accident or on a single confused turn. This
milestone's write tool is explicitly scoped as **single-call**, because a confirmation-token
round-trip makes little sense for "record what I observed in this photo" — there is no dangerous
state transition to gate the way there is for a program switch, and demanding user confirmation
for logging an observation would be friction with no matching safety benefit.

But "single-call" reintroduces exactly the failure category the two-call design was built to
prevent, in a different shape: **nothing stops the model from calling the tool twice for the same
underlying photo submission.** A user attaches photos and says "rate my physique" — the model
runs a vision analysis, then calls the write tool. If that response is ambiguous, if the model
second-guesses itself, if the conversation is retried, or if `safe_tool`'s exception-wrapping
(v2.0 Pitfall #15's precedent) fires *after* a successful commit, the natural model behavior is to
call the write tool again "to be safe" — producing two observations for one real event, which
directly corrupts Pitfall 6's diff analytics (a same-day duplicate is not a real second data
point, but nothing distinguishes it from one) and directly worsens Pitfall 2's ratchet risk (a
duplicate anchors the *next* month's rating on an artificially reinforced value).

**A second, more serious version of the same problem: hallucinated ratings with no photo at all.**
Because BRETT never receives the image, it has **no way to verify a photo was actually attached**
to the conversation that produced a call to this tool. A model can call the write tool with a
plausible-looking rating and note in a conversation where the user never sent a photo — through
misunderstanding ("rate how I'm doing" interpreted as "rate my physique" with no image present),
through the model filling in from memory of a much earlier photo, or, in the worst case,
through the model fabricating an entirely invented physique assessment because it has been asked a
question it wants to be helpful about. There is no field BRETT can check, no signature, no
metadata — the backend's entire epistemic access to "was there really a photo" is the model's own
say-so.

**How to make "there was really a photo" verifiable when the backend never sees the photo:**
This is a hard constraint the milestone accepted deliberately (no image storage, no upload
endpoint), so full verification is out of reach by design — but partial mitigations exist and
should be treated as required, not optional:
- **Require the tool call to include an explicit, structured attestation field** — e.g., a
  required `photo_count: int` (≥1) or `photo_description` free-text field the model must populate
  from what it actually saw (a rough description of framing/pose), not just the ratings
  themselves. This does not prove a photo existed, but it raises the cost of hallucination (a
  model fabricating ratings must also fabricate a plausible photo description, which is a
  different and harder failure than just picking numbers) and gives a human reviewer something
  concrete to sanity-check against their own memory of what they actually sent ("I sent a
  front-relaxed shot, why does this say back-double-biceps").
- **Update `docs/coaching-instructions.md` with an explicit, unambiguous instruction**: this tool
  may be called **only** in direct, immediate response to photos the user has just attached in
  the current turn, never from memory of an earlier conversation, never speculatively, and never
  when the user's message does not include an image. This is a prompt-level control, not a
  backend control, and it is exactly as strong as every other prompt-level control in this
  document — meaningful but not a security boundary, the same honest framing this codebase
  already gives `ctx.elicit()` in v2.0 Pitfall #13.
- **Rate-limit or flag rapid repeat calls at the write-tool level**, independent of the
  general MCP rate limiter: if a second observation for the same user lands within an
  implausibly short window of the first (minutes, not the same day generally, since a user might
  legitimately retake photos), treat it as a probable duplicate and require the model to
  explicitly acknowledge overwriting/adding-to rather than silently accepting it as a distinct
  data point. "Append-only" should not mean "duplicate-blind" — append-only governs whether old
  rows are ever destroyed, not whether obviously-redundant new rows are accepted uncritically.
- **Make the tool's response, on success, explicitly restate what was just recorded** (the exact
  ratings, the exact note, the timestamp) so the model's own next sentence to the user is a
  natural cross-check point — a wrong or hallucinated write is much more likely to be caught
  immediately by the user reading it back than discovered months later in a report.

**Why it happens:** Single-call, low-friction write tools are the correct design for a
genuinely low-stakes, frequent, append-only action — the design intent is sound. The risk is not
that single-call is the wrong choice; it is that single-call plus autonomous-invocation plus
image-blind-backend is a combination this codebase has never had to defend before, and none of
the existing write-tool guards (`safe_tool`, the token gate, `writable_session`) were built with
"is this call even legitimate" in scope — they all assume the call itself was warranted and only
guard *how* it is executed.

**Warning signs:** Two physique observations for the same user with timestamps minutes apart. A
physique observation with a note that does not plausibly describe a photo (generic, templated
language). A conversation transcript where the write tool is called with no image visibly attached
to the triggering user turn.

**Phase to address:** The physique write-tool phase — the attestation field and the
coaching-instructions constraint are both success criteria for that phase, not follow-up polish.

---

### Pitfall 9: `safe_tool`'s exception-swallowing needs the same three-state treatment `program_switch.py` got, for a different reason

**What goes wrong:**
v2.0 Pitfall #15 established that `safe_tool` wrapping a write tool can turn a *successful* write
whose response serialization later fails into a payload the model reads as failure — inviting a
retry that double-applies. `program_switch.py` solved this with a three-state result
(`applied`/`not_applied`/`unknown`) and a same-transaction token-consumption pattern.

The physique write tool needs the identical discipline, but the *consequence* of getting it wrong
is different in kind, not just degree, from the program-switch case: a duplicated program switch
is a state that can be read back and corrected (call the read tool, see the actual program, switch
again if needed) — the system has a canonical single source of truth for "what program am I on
right now." A duplicated physique observation has **no equivalent correction path**, because
"append-only" means there is no canonical "current state" to read back and reconcile against —
every row is permanent history, and Pitfall 6 and Pitfall 2 already establish that duplicate or
falsely-anchored rows actively corrupt the longitudinal analysis, not just the current-moment
answer. An `unknown`-state response after a possible-but-unconfirmed commit is *more* dangerous
here than for program switching, because the natural model recovery move — "let me just check
what was recorded" — requires a read tool over the physique history, which does not exist unless
this milestone builds one (the milestone's stated scope is a write tool plus diff analytics plus
report integration; a dedicated `fitness_get_physique_history` read tool is not explicitly listed
and should be, precisely so `unknown`-state recovery has somewhere to go).

**How to avoid:**
- Apply the identical three-state `safe_tool` pattern from `program_switch.py`, with the `unknown`
  path's message explicitly instructing the model to check the current physique history before
  writing again — which only works if a read tool exists for it to check against.
- **Add a read tool over physique observation history as part of this milestone**, not as
  a future nice-to-have, specifically so an `unknown`-state write has a legitimate, low-risk
  recovery action, mirroring how the program-switch `unknown` path relies on
  `fitness_get_training_program` already existing.
- Make the write's commit the last statement in the transaction, exactly as
  `program_switch.py`'s docstring requires of itself, minimizing the post-commit failure window.

**Warning signs:** A write tool with no corresponding read tool. An `unknown`-state degraded
response whose reason text does not name a specific recovery action.

**Phase to address:** The physique write-tool phase should ship the read tool alongside the write
tool for exactly this reason, even though the milestone's headline feature is the write path.

---

### Pitfall 10: Free-text physique notes are the one place in this system where stored data is about the user's body, in words, forever

**What goes wrong:**
BRETT's stated privacy design for this milestone is strong and correctly scoped — no image ever
reaches the backend, which removes the single largest privacy liability a physique-tracking
feature could have. But this correctly leaves a **residual** surface that the milestone's own
framing ("removes most of the data-security surface") could be read as dismissing rather than
managing: the bounded free-text notes ("leanness, conditioning and symmetry") are themselves a
description of the user's body, stored in plain structured columns, and — per this codebase's own
existing logging design — **fully subject to the same flows every other piece of data goes
through**: they can appear in structlog output (tool-call argument/result logging), in MCP tool
responses (the exact channel physique data is meant to travel through), in the monthly report
narrative (verbatim, per this milestone's own design), and in Cloud Run's log sink, all with the
service deployed `--allow-unauthenticated` for the HTTP surface generally.

`app/logging.py`'s two structural redaction layers (`censor_keys`'s deny-list `DENY_KEYS`, and
`make_value_scrubber`'s known-secret-value scrub) are both built for **credential-shaped**
secrets — API keys, tokens, DSNs, passwords. Neither layer has any concept of "this string
describes something sensitive about the user's body" — that is not a key-name pattern
(`censor_keys` matches on key names like `api_key`, `password`) nor a known-fixed-value pattern
(`make_value_scrubber` matches specific secret string values known at config time). A physique
note is free-form text whose sensitivity is about its *content*, which neither existing layer is
designed to detect, and which — correctly — should probably not be redacted from logs the way a
credential is, since a completely redacted log line is useless for debugging a real bug in this
feature. This is a real, load-bearing tension, not a bug to "just fix" by extending the deny-list.

**Why it happens:** The existing redaction pipeline was built entirely against the threat model
of "a credential must never leak," which is the correct threat model for API keys and tokens and
was correctly and thoroughly solved for it (three ordering-constrained layers, tested). Physique
notes introduce a genuinely different threat model — not "this must never appear anywhere" but
"this should not appear more places than necessary, and should never appear in a place with wider
access than the user's own MCP conversation" — and the existing pipeline was never asked to solve
that problem, so nothing in it will notice the new data category needs a different policy.

**How to avoid:**
- **Do not attempt to extend `DENY_KEYS`/`make_value_scrubber` to redact physique note content** —
  that would make the feature's own core output invisible in its own logs, which is the wrong
  tradeoff for a single-user personal project's debuggability.
- **Instead, scope what actually logs.** Audit the write tool and the report composer for whether
  tool-call argument/result logging (if any exists at `structlog` call sites in `app/mcp/tools/`)
  includes full free-text note content at INFO level, versus logging only metadata (user id,
  timestamp, muscle group, whether a note was present) at INFO and reserving full content for
  DEBUG or omitting it from logs entirely. This is a scoping decision, not a redaction mechanism —
  the right target is "logs contain enough to debug a stuck request, not a second copy of the
  user's full physique history."
- **Confirm Cloud Run's log retention/access model** matches the sensitivity of what is now
  flowing through it — this was true before this milestone too (workout data, nutrition data are
  already personal), but physique notes are qualitatively the most personal free text this system
  will have ever produced, and it's worth an explicit check that log access is not broader than
  the same operator access every other log line already has, rather than assuming so.
- **The bounded length on free-text notes (already a stated design constraint) is itself a
  mitigation** — bound it deliberately short enough that it stays a qualitative descriptor
  ("visible ab separation, delts noticeably fuller") and cannot become an essay-length personal
  reflection, which both serves Pitfall 4's numeric/tone constraints and limits how much sensitive
  free text exists per row.

**Warning signs:** A structlog call site logging a full tool-call payload at INFO for the physique
write tool, visible the same way any other tool's args currently are. No documented answer to
"who can read Cloud Run logs for this service" existing anywhere in the deployment docs.

**Phase to address:** The physique write-tool phase, as a logging-scope review alongside the tool
implementation — not a separate security pass after the fact.

---

### Pitfall 11: A system that rates a person's body every month and reports regressions is a wellbeing hazard, not just a feature

**What goes wrong:**
This is a real engineering constraint with design consequences, not a caveat to append. A monthly
"regressed" verdict on a muscle group — especially one produced by the noisy, potentially-biased
process Pitfalls 1 and 2 describe — can land as a demoralizing, decontextualized judgment on a
person's body from what reads as an authoritative system, at a cadence (monthly, indefinitely)
that most human coaching relationships would never sustain without a great deal of context and
rapport the tool call itself cannot supply. The specific failure modes worth designing against:

- **A single noisy "regressed" rating (Pitfall 1) reported with the same flat confidence as
  everything else in the report** can read as a confirmed fact about the user's body when it may
  be nothing more than a lighting difference between two photos.
- **A report that leads with or foregrounds a regression**, the way `docs/coaching-instructions.md`
  currently instructs Claude to "lead with the answer in one or two sentences," could mean the
  answer a user gets, unprompted, to "how was this month" opens with a claim their body got worse
  — which is a materially different experience from opening with "your bench went up 5kg," even
  though both are structurally "the answer."
- **This is the one domain in the whole system where "decision support, never a diagnosis" (the
  recomposition disclaimer's own framing) is not enough**, because a recomposition verdict is
  about training/eating behavior a user can act on immediately, while a physique rating is about
  a body a user cannot change on any comparable timescale — the same caveat sentence does less
  work here.
- **Comparison-shopping against an idealized standard is a risk the 19-value taxonomy itself must
  guard against.** If the taxonomy or its labels imply an aesthetic ideal (e.g., anchored on
  competitive bodybuilding development) rather than the user's own trajectory, every monthly
  rating becomes a comparison against a standard the user never chose to be held to, which is a
  distinct harm from comparing this month to last month.

**Design choices that mitigate this, several already implied by the milestone's own scoping and
worth making explicit requirements rather than incidental outcomes:**
- **Monthly-only, never weekly** (already decided, PROJECT.md) — this is itself the primary
  mitigation against an oppressive cadence, and should not be revisited without re-examining this
  pitfall specifically.
- **Relative-to-self framing, never relative-to-ideal** — the taxonomy and the coaching
  instructions should frame every rating and every diff strictly against the user's own prior
  observation, never against a population norm or an implied aesthetic target. This is a natural
  extension of the milestone's existing "rate relative to last observation, not absolutely" design
  decision, but it needs to be stated as a requirement for the *labels and prompt*, not just the
  *mechanism*.
- **Never let a physique regression stand alone without its coherence check.** Pitfall 2's
  cross-reference against training volume is also a wellbeing mitigation, not just an accuracy
  one: "regressed, and your training volume for that muscle also dropped 40% this month" is a
  legibly explicable, actionable fact; "regressed" alone, unexplained, is just a verdict.
  `docs/coaching-instructions.md` should instruct Claude to never report a physique regression
  without checking and surfacing the corresponding volume/training context in the same answer.
- **Frame uncertainty honestly and specifically, following this codebase's existing convention** —
  the coverage/freshness envelope pattern already trains Claude to say "we don't have enough data
  to say" rather than force a confident verdict; the physique disclaimer (Pitfall 3) should
  explicitly license the same move: a single ambiguous or borderline photo-based observation is
  allowed to be reported as "no clear change," not forced into improved/regressed.
- **Give the user, not just the system, control over whether this section runs at all.** Given
  this is a single-user personal project and not a product with an opt-out UX to design, the
  practical version of this control is: the feature is invoked, not automatic — physique
  observations only enter the system when the user chooses to attach photos and ask for a rating,
  never on a schedule the way weekly/monthly reports otherwise auto-populate from continuously
  synced data. This should be an explicit, stated design constraint (not merely a fact that falls
  out of "photos are attached in conversation"): the monthly report's physique section should
  render an honest "no observation this period" rather than prompting or nagging for one.

**Why it happens:** Every other analytics module in this system reports on training, nutrition,
and body-composition numbers that are behaviorally and clinically well-trodden ground for how to
present without inducing anxiety (rate-of-change framing, decision-support disclaimers, the
"too fast"/"stable"/"on target" ladders already tuned for exactly this in `recomposition.py`).
Physique appearance rating has no equivalent design tradition inside this codebase to draw on, so
the instinct is to treat it as "one more analytics section" and apply the same report-composition
pattern without asking whether the same presentation norms actually transfer.

**How to avoid:** Treat this pitfall's mitigations as testable, phase-owned requirements — "the
coaching instructions never report a physique regression without volume context in the same
answer" is exactly as verifiable by the existing drift-guard-style test pattern
(`test_coaching_doc.py`) as any other instruction in that document already is.

**Warning signs:** A monthly report narrative that states a regression with no accompanying
volume/training context anywhere in the same response. Physique ratings auto-requested or implied
as expected on a cadence rather than purely user-initiated.

**Phase to address:** The report-integration phase for the narrative-framing rules; the
coaching-instructions update (likely the same phase, given this project's precedent of updating
`docs/coaching-instructions.md` in the same phase new tools ship) for the "always pair a
regression with context" instruction.

---

### Pitfall 12: The cross-reference feature can manufacture a causal story two independently-noisy signals do not support

**What goes wrong:**
"Is the underdeveloped area also the undertrained one?" is a genuinely valuable question and a
good use of existing data — but it is a comparison between two signals of very different
reliability: `fitness_get_muscle_group_volume` is deterministic, measured, well-tested data; a
physique rating is the single noisiest, least-verifiable signal in the entire system (Pitfalls 1
and 2). A report or narrative sentence that says "your delts are underdeveloped, and delt volume
is also low" reads as a confirmed causal finding, when what actually happened is one reliable
number and one unreliable opinion happened to point the same direction this month — which,
given enough muscle groups checked every month, will sometimes happen by chance alone even if the
rating were pure noise. The inverse is just as important to handle honestly: when the two signals
*disagree* (rated as underdeveloped, but volume is actually high, or vice versa), that disagreement
is informative — Pitfall 2 already names it as a ratchet-detection signal — but only if the
narrative reports it as "these two signals disagree" rather than quietly preferring the one
that produces a tidier story.

**How to avoid:** Frame the cross-reference in both the analytics response and the narrative as a
**correlation observation to consider**, explicitly and structurally distinct from a verdict —
report both numbers, name the disagreement when there is one, and do not let the composed sentence
imply the volume number *caused* or *explains* the rating unless the disagreement/agreement
framing itself is the entire content of the sentence ("rated underdeveloped and also the
lowest-volume muscle group this period" is fine; "underdeveloped because undertrained" is not,
and is itself banned-recommendation-adjacent causal language worth adding to Pitfall 4's token
scan consideration).

**Warning signs:** Narrative language using "because," "due to," or "as a result of" to connect a
physique rating and a volume figure.

**Phase to address:** The physique-analytics phase, when the cross-reference computation itself is
designed — the framing constraint belongs in the same function that produces the comparison, not
left to be caught later in the narrative layer.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|--------------------|-----------------|------------------|
| Skip the self-consistency spike (Pitfall 1) and ship the schema/write tool directly | Faster to a working demo | The taxonomy, diff thresholds and step-size caps are all calibrated on a guess rather than a measurement, and a wrong calibration is a schema migration to fix later | Never — this is the milestone's central risk and the cheapest moment to measure it is before anything depends on the answer |
| Copy `program_switch.py`'s two-call token pattern onto the physique write tool "to be consistent" | Reuses a proven pattern, less design work | Adds real friction (a confirmation round-trip) to a low-stakes, frequent action with no matching safety benefit, and trains the user to click through confirmations, weakening the pattern's value where it actually matters (program switching) | Never for this tool; the milestone correctly scoped it single-call — the debt to avoid is the opposite one (see Pitfall 8's mitigations instead) |
| Add physique fields directly inside `_report_body_fields` for a quick first cut | Fastest path to "it shows up in the monthly report" | Ships into the weekly report too, violating a stated requirement, and the fix later is a compatibility-breaking response-shape change once a client has seen the wrong shape | Never — see Pitfall 5 |
| Let the write tool's free-text validation be "ask the model nicely in the prompt" with no backend rejection | No extra code | The banned-token and numeric-provenance guards WILL eventually fail on a real user note, discovered as a CI red herring months after the note was written, with no easy way to retroactively fix already-stored rows under an append-only design | Acceptable only as a stopgap alongside a tracked task to add the backend check before the append-only property makes stored violations permanent |
| Reuse `MEASURED_DAY_FLOORS`-style constants from body measurements for the physique elapsed-time floor without re-deriving them | Saves a calibration decision | Body measurement gaps and photo-submission gaps have no reason to share a cadence; borrowing the constant borrows an assumption that was tuned for a different data source | Acceptable only as an explicitly `[ASSUMED]`, documented placeholder pending real usage data, exactly as D-06's nutrition-floor reuse already is elsewhere in this codebase |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|------------------|--------------------|
| Monthly report composer (`compose_report`) | Calling a model from inside report composition to "refresh" or reformat a stored rating, breaking `build_narrative`'s purity/determinism guarantee | Read stored observations verbatim; all model interaction happens once, at write time, never at read/report time |
| `docs/coaching-instructions.md` drift guard (`test_coaching_doc.py`) | Adding the new tool(s) to the registry without updating the coaching doc, or updating the doc without the corresponding tool-name/parameter accuracy the drift guard checks | Update the coaching doc in the same phase the tool ships, following the project's own established precedent (every prior phase that shipped a tool did this) |
| `app/mcp/tools/schemas.py` response budgeting | Treating physique observation history as unbounded in a read tool's response the way full PR/plateau lists were deliberately NOT done in the report tools | Cap and roll up, following `MAX_REPORT_PR_HIGHLIGHTS`/`roll_up_muscles`'s precedent, if a read tool over history is added (Pitfall 9) |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|-----------------|
| A physique-history read tool with no window/limit, growing one row per month forever | Slow response, growing payload, eventually exceeds Claude's connector budgets | Bound the read tool the same way every other list-shaped tool in this system already is (default/limit pattern from `fitness_get_recent_workouts`) | Not urgent given monthly cadence (12 rows/year), but worth designing correctly from the first version rather than retrofitting |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Treating "no image stored" as "no privacy work needed" | Free-text notes about the user's body flow through logs, MCP responses and reports with no equivalent redaction/scoping review that credentials get | Explicit logging-scope review (Pitfall 10) as a phase deliverable, not an assumption |
| Loosening `test_mcp_isolation.py`'s exact-membership write-guard assertions to admit a second module more easily | A third write tool later passes the guard by accident, silently | Keep every guard an exact, named, closed set (Pitfall 7) |
| No attestation or plausibility check on write-tool calls | A hallucinated or duplicated physique observation is indistinguishable from a real one once written, under an append-only design with no correction path | Structured attestation field, coaching-doc constraint, duplicate-window flag (Pitfall 8) |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|--------------|-------------------|
| A physique regression reported with the same flat, confident tone as a measured figure | Demoralizing, feels like an authoritative verdict on the user's body from noisy input | Distinct disclaimer, distinct verb register, paired volume/training context (Pitfalls 3, 11) |
| A twelve-month "steady improvement" narrative built from chained one-step deltas | False confidence in a trend that may be a ratchet artifact, not real progress | Periodic blind re-anchor, cross-reference coherence check, no long-chain trend narration beyond adjacent pairs (Pitfall 2) |
| The report nagging or implying an observation is "due" this month | Turns a voluntary, low-stakes feature into an obligation | Honest "no observation this period," never a prompt to submit one (Pitfall 11) |

## "Looks Done But Isn't" Checklist

- [ ] **Write-guard update:** Often looks done at "frozenset has two entries now" — verify all
      three write-guard tests were updated with the module's exact name, none loosened to a
      pattern/subset check (Pitfall 7).
- [ ] **Determinism contract:** Often looks done at "byte-identical test passes" — verify the
      free-text banned-token and numeric-provenance checks were exercised against a red-test
      fixture containing a violation, not just a clean happy-path fixture (Pitfall 4).
- [ ] **Report split:** Often looks done at "monthly report shows physique" — verify a weekly
      report against the same user/window explicitly does NOT contain a physique field, asserted
      by a positive-exclusion test (Pitfall 5).
- [ ] **Disclaimer:** Often looks done at "narrative mentions this is a model rating" — verify the
      disclaimer is a required schema field, present even in the `insufficient_data` path, and
      asserted verbatim by a dedicated test the way `INTERPRETATION_DISCLAIMER` already is
      (Pitfall 3).
- [ ] **Sparse-data handling:** Often looks done at "diff works when there are two observations" —
      verify zero-observation, one-observation, and too-close-together-observation paths are each
      explicitly tested, not merely not-crashing (Pitfall 6).
- [ ] **Coaching doc:** Often looks done at "tool is listed in the table" — verify the physique
      tool's row states the photo-must-be-attached constraint and the cross-reference-before-
      reporting-regression instruction, not just the call signature (Pitfalls 8, 11).
- [ ] **Self-consistency evidence:** Often looks done at "the design has an anchoring mitigation" —
      verify the spike actually measured how much the rating moves across repeated/blind/anchored
      calls on the same photos, with the result recorded the way `13-SPIKE-RESULT.md` records
      v2.0's spike, before the schema's step-size/threshold constants are finalized (Pitfall 1).

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|-----------------|-------------------|
| Physique fields leaked into the weekly report (Pitfall 5) | LOW | Move the assembly step out of `_report_body_fields` into the monthly-only branch; add the missing exclusion test; no data was corrupted, only over-exposed in one response shape |
| A stored free-text note contains banned/numeric language, caught after the fact (Pitfall 4) | MEDIUM | Append-only means the row cannot be silently edited without breaking the "never mutate history" property — the honest fix is a data migration that flags the row as excluded-from-narrative (a boolean, not a deletion) so `build_narrative` skips it while the historical record stays intact |
| A duplicate observation from a retried write (Pitfall 8) | MEDIUM | Requires a documented manual-correction path even under "append-only" — e.g., a `superseded_by`/`voided` marker rather than deletion, preserving the append-only audit trail while letting analytics exclude the duplicate; this needs to be designed in from the start, not improvised once the first duplicate actually happens |
| The write-guard tests were loosened to admit the second module less strictly (Pitfall 7) | LOW | Revert to exact-membership assertions; this is a pure code-review catch with no data consequence if caught before merge |
| Evidence emerges post-ship that the anchored rating chain has ratcheted (Pitfall 2) | HIGH | No clean fix — the historical chain cannot be re-rated without new photos of the past, which do not exist. The only real recovery is starting a fresh, explicitly-blind anchor point going forward and being honest in the narrative that pre-reset history should be read with reduced confidence. This is the strongest argument for treating Pitfall 2's periodic re-anchor as a day-one requirement rather than a later fix |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|--------------------|-----------------|
| 1. Rater self-inconsistency, no ground truth | Spike, before schema/write-tool design locks | A recorded spike result (same shape as `13-SPIKE-RESULT.md`) measuring rating movement across repeated/blind calls on fixed photos |
| 2. Anchoring ratchet | Physique-analytics phase (cross-reference-as-coherence-check); spike informs the re-anchor cadence | A test asserting the diff function flags N consecutive same-direction moves with no corroborating volume signal; a documented periodic-blind-reanchor policy |
| 3. Rating stored/displayed as if measured | Schema-design step of the write-tool phase | A required, non-optional disclaimer field asserted present by a dedicated test, on every response shape including `insufficient_data` |
| 4. Determinism contract breakage (purity, banned tokens, numeric provenance) | Write-tool phase (write-time enforcement) + report-integration phase (test fixtures) | Red-test fixtures containing a banned-token note and an over-numeric note, both rejected at write time; shared token/number-pattern source between write tool and narrative test |
| 5. `_report_body_fields` shared-projection leak | Report-integration phase, first task | A positive-exclusion test: weekly report for a user/window with physique data present contains no physique field |
| 6. Sparse/irregular cadence traps | Physique-analytics phase | Explicit, separately tested zero/one/too-close-together observation paths; documented `[ASSUMED]` minimum-elapsed-time constant |
| 7. Write-guard widening correctness | Write-tool phase, explicit success criterion | All three write-guard tests grow to name two modules exactly, none loosened in shape |
| 8. Duplicate/hallucinated writes | Write-tool phase | Attestation field present in schema; coaching-doc instruction restricting the tool to photo-attached turns; duplicate-window flag behavior tested |
| 9. `safe_tool` three-state result + missing read path | Write-tool phase | Read tool over physique history ships alongside the write tool; `unknown`-state message names the read tool as the recovery action |
| 10. Free-text logging/privacy scope | Write-tool phase, logging-scope review | Explicit statement of what logs at what level for this tool; no full-note-content logging at INFO by default |
| 11. Wellbeing design consequences | Report-integration phase (framing) + coaching-doc update | Coaching-doc drift-guard test covers the "never report a regression without volume context" instruction; monthly-only and user-initiated-only constraints preserved |
| 12. Cross-reference manufacturing false causation | Physique-analytics phase | Narrative/response framing test rejecting causal language (`because`, `due to`) around the cross-reference |

### Suggested phase-ordering consequences

Pitfall 1's spike should run **before** any other phase in this milestone, for the same reason
Phase 2's auth spike and Phase 13's RPT-03 spike ran before the features that depended on their
answers: the taxonomy's step size, the diff analytics' thresholds, the minimum-elapsed-time floor,
and the re-anchor cadence (Pitfalls 1, 2, 6) are all downstream of a number this spike is the
cheapest place to produce. Building the schema first and hoping the spike's findings fit into it
risks a second migration.

The write-tool phase (Pitfalls 3, 4 write-time half, 7, 8, 9, 10) should ship the read tool
alongside the write tool, contrary to how the milestone scope currently reads (write tool, then
analytics, then report) — Pitfall 9 explains why a write-only first phase leaves an `unknown`-state
recovery path with nowhere to go.

The physique-analytics phase (Pitfalls 2 coherence check, 6, 12) should not be scoped as "just the
diff" — the cross-reference is load-bearing for both the accuracy story (Pitfall 2) and the honesty
story (Pitfall 12), not a bonus feature to add if time permits.

The report-integration phase (Pitfalls 4 test-fixture half, 5, 11) inherits the most mature
existing guard-rail machinery in the codebase (`test_analytics_reports.py`'s determinism suite) and
should extend it with physique-specific red-test fixtures as its first task, before wiring the
section into `compose_report` for real.

## Sources

- This repository, read directly: `.planning/PROJECT.md`, `.planning/MILESTONES.md`,
  `.planning/research/PITFALLS.md` (v2.0, Pitfalls #13–16 specifically),
  `backend/app/analytics/recomposition.py`, `backend/app/analytics/body_measurements.py`,
  `backend/app/mcp/tools/reports.py`, `backend/app/logging.py`, `backend/tests/test_mcp_isolation.py`,
  `backend/tests/test_mcp_readonly.py`, `backend/tests/test_analytics_reports.py`,
  `backend/app/mcp/tools/program_switch.py`, `docs/coaching-instructions.md` — **HIGH confidence**,
  all claims about this codebase's existing guards, tests and precedents are read from the source,
  not inferred.
- "Rating Roulette: Self-Inconsistency in LLM-As-A-Judge Frameworks," arXiv:2510.27106 (Oct 2025),
  also ACL Findings EMNLP 2025 — intra-rater reliability, temperature/reproducibility tradeoff —
  **MEDIUM confidence** (general LLM-judge literature, not a study of this project's specific
  vision-rating task).
- Yu, S. & Zhang, T., "Sequential biases on subjective judgments: Evidence from face
  attractiveness and ringtone agreeableness judgment," PMC5995378 — assimilative sequential
  effects strengthened by response repetition — **MEDIUM confidence** (psychology-of-judgment
  literature, applied here by close analogy, not a study of VLM rating specifically).
- "Modeling sequential context effects in diagnostic interpretation of screening mammograms,"
  PMC5858736 — sequential context effects in repeated image-based diagnostic judgment, the closest
  found analogue to "rate a body from a photo, informed by what was judged last time" —
  **MEDIUM confidence**.
- "Labeling messages as AI-generated does not reduce their persuasive effects," PMC12887897 —
  motivates structural (not merely textual-disclaimer) provenance separation — **MEDIUM
  confidence**.
- Data-provenance standards discussion (IAPP, NTIA AI-output-disclosure framework, general
  industry sources found via search) — general framing for provenance-as-metadata rather than
  provenance-as-prose — **LOW/MEDIUM confidence**, industry/policy commentary rather than a
  controlled study.
- No source was found — and none is claimed — for a controlled measurement of *this specific*
  model's self-consistency or anchoring behavior on physique-photo rating specifically; Pitfall 1
  explicitly recommends producing that evidence via a project-run spike rather than relying on the
  general literature above, which is directionally supportive but not a substitute for a direct
  measurement.

---
*Pitfalls research for: BRETT v2.1 Longitudinal Physique Analysis*
*Researched: 2026-09-05*
