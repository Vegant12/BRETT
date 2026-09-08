# Phase 15 — PHYS-12 Physique Rating Calibration Spike Record

**Purpose:** the durable record ROADMAP.md Phase 15 success criterion #1 requires. It measures
how much a Claude-produced 5-level ordinal muscle-development rating moves across repeated
**blind** calls on an unchanged real photo-set (test-retest noise), and across an **anchored**
chain that mirrors PHYS-07's prior-observation-as-context mitigation (success criterion #2:
does that mitigation produce a self-reinforcing ratchet?). Success criterion #4 blocks Phase
16's observation schema until this file exists. Phase 16's schema and Phase 17's
`app/analytics/physique.py` consume the `## Recommended Constants` section verbatim.

**Authority of this record (D-07):** it may set (a) a recommended minimum-elapsed-time floor and
(b) confirmation or refinement of PHYS-01's anchor wording. PHYS-01's 5-level count and
PHYS-09's pure-ordinal-diff design (no arithmetic beyond ordinal comparison) stay locked
regardless of what this spike found.

## Method

Pre-registered on 2026-09-08, **before any rating call output was collected**, so the analysis in
plan 15-02 cannot be reverse-fitted to the data.

| Field | Value |
|---|---|
| Date run | 2026-09-08 |
| Specimen | ONE real photo-set (1-3 shots from a single session), unchanged across all calls (D-03) |
| Photo handling | Session scratchpad only; never committed, deleted after the last call (D-02) |
| Rated groups (D-05) | `chest`, `lats`, `biceps`, `abs`, `side_delts` |
| Excluded groups | `abductors`, `adductors` — PHYS-02 permanently not-assessable from standard photos |
| Blind condition (D-04, D-06) | 5 independent `Task(subagent_type="general-purpose")` calls, fresh context each, no knowledge of each other |
| Anchored condition (D-04, D-06) | 5 sequential calls: A1 unanchored (seed), A2-A5 each fed the previous step's full rating output as "prior observation" text — 4 anchored transitions |
| Total real calls | 10 (plus 1 discarded smoke test) |
| Statistics | Mode, range, exact-agreement count (blind); first-vs-last ordinal diff, monotonic-direction count (anchored). **No kappa, no ICC, no p-value** — this is a single-specimen repeatability design, not a multi-subject reliability study; those formulas do not apply and a fabricated one would misrepresent N=5 |

### Ordinal index

`Minimal`=1, `Emerging`=2, `Developed`=3, `Well-Developed`=4, `Standout`=5, `Not Assessable`=NA.

### Pre-registered ratchet decision rule

Applied per muscle group by plan 15-02, to the anchored chain R1..R5:

- `anchored_travel` = index(R5) − index(R1)
- `opposing_count` = of the 4 step-to-step transitions, how many move opposite in sign to `anchored_travel`
- `blind_range` = max index − min index across the 5 blind draws for the same group

Verdicts:

- **RATCHET-OBSERVED** — at least one group has `|anchored_travel| >= 1` AND `opposing_count == 0`
  AND `blind_range == 0` for that same group. (The blind condition was perfectly stable on this
  group while the anchored chain walked one direction — the movement cannot be base noise.)
- **RATCHET-INCONCLUSIVE** — at least one group has `|anchored_travel| >= 1` AND
  `opposing_count == 0`, but `blind_range >= 1` for that group. (The anchored walk is not
  distinguishable from the blind condition's own scatter at N=5.)
- **RATCHET-NOT-OBSERVED** — no group meets either condition above.

Blind-condition verdict:

- **BLIND-STABLE** — every rated group has `blind_range <= 1` AND its modal level was returned
  by at least 3 of the 5 draws.
- **BLIND-NOISY** — any rated group fails either half of that.

### Exact rating prompt (blind condition, verbatim)

```text
You are rating a set of physique progress photos for a personal fitness tracking system.

Read the image file(s) at these absolute paths using your Read tool:
<ABSOLUTE_SCRATCHPAD_PATH_1>
<ABSOLUTE_SCRATCHPAD_PATH_2 if present>
<ABSOLUTE_SCRATCHPAD_PATH_3 if present>

Rate exactly these five muscle groups, in this order:
chest, lats, biceps, abs, side_delts

Use this fixed 5-level ordinal scale. Do not invent intermediate levels, do not use
half-steps, do not use numbers other than these names:

1. Minimal - the group shows little visible development; its outline is not apparent
   in this photo set.
2. Emerging - the group's outline is visible but shallow; shape is suggested rather
   than defined.
3. Developed - the group has clear shape and visible separation from adjacent groups.
4. Well-Developed - the group is clearly fuller or more defined than the average group
   on THIS person's own body.
5. Standout - the group is among the most developed on THIS person's own body; it is
   the group a viewer would notice first.

Levels 4 and 5 are defined relative to THIS SAME PERSON's own body only. Never compare
against another person, an athlete, a competitor, or any population standard.

If the photo set does not show a group well enough to place it on the scale, answer
`Not Assessable` for that group and give a one-line reason instead of a level.

Describe ONLY muscle development. Do not describe or mention the background, clothing,
face, hair, tattoos, location, or any other identifying feature.

Reply with exactly these five lines and nothing else - no preamble, no summary, no
caveats:

chest: <level name or Not Assessable> - <one sentence, 20 words maximum>
lats: <level name or Not Assessable> - <one sentence, 20 words maximum>
biceps: <level name or Not Assessable> - <one sentence, 20 words maximum>
abs: <level name or Not Assessable> - <one sentence, 20 words maximum>
side_delts: <level name or Not Assessable> - <one sentence, 20 words maximum>
```

### Exact anchoring block (anchored condition, prepended to the same prompt for A2..A5)

```text
PRIOR OBSERVATION - the most recent physique observation on record for this person,
recorded approximately 30 days ago:

<the previous step's five verbatim rating lines>

Use it as context for how this person was previously assessed.

---
```

The anchoring block deliberately carries NO mitigation instruction. D-08's proposed mitigation
("derive each rating primarily from the photo; treat the prior observation as a sanity check,
not a target") is what this spike RECOMMENDS if a ratchet appears — including it in the prompt
would measure the mitigated system rather than the PHYS-07 system as currently specified. The
anchored calls are also never told the photo is the same photo, because in production it never
would be.

## Mechanism Smoke Test

One throwaway `Task(subagent_type="general-purpose")` call, discarded from the sample, run
before the 10 real calls to verify 15-RESEARCH.md Assumption A1 (a spawned subagent can
independently `Read` an image at a path) and Open Question 1 (`Task` is actually available in
the post-checkpoint MAIN context).

| Field | Value |
|---|---|
| Verdict | SMOKE-PASS |

**Raw reply:**

> IMAGE-VISIBLE: shirtless man standing

## Blind Condition: Raw Output

5 independent isolated `Task(subagent_type="general-purpose")` calls, byte-identical prompts,
same unchanged photo-set, no shared context. Raw output quoted verbatim — never paraphrased.

### B1

> chest: Emerging - Chest shows a slight rounded mound but lacks fullness or separation from surrounding tissue.
> lats: Emerging - Back view shows a mild taper from shoulders to waist without visible width or separation.
> biceps: Emerging - Relaxed arm shows a modest rounded shape without a distinct peak or separation.
> abs: Emerging - A faint centerline is visible on the torso but no distinct segmented definition.
> side_delts: Emerging - Shoulders show a rounded cap that blends into the upper arm without clear separation.

### B2

> chest: Emerging - Chest shows a slight rounded shape but no visible separation from surrounding muscle in these photos.
> lats: Minimal - Back view shows little taper from shoulders to waist; outline is not clearly apparent here.
> biceps: Emerging - Upper arm shows a slight rounded bulge but shape is not clearly defined in these photos.
> abs: Emerging - A faint central abdominal line is visible but no segment separation appears in these photos.
> side_delts: Emerging - Shoulder caps show slight rounding but lack defined separation from chest and arms.

### B3

> chest: Emerging - A slight pectoral mound is visible in the front view, but no separation or defined shape.
> lats: Minimal - The back view shows no visible V-taper or lat outline beneath the skin surface.
> biceps: Minimal - Arms are shown relaxed in every photo, showing little visible bulge or muscle shape.
> abs: Minimal - The front-view torso appears smooth with no visible abdominal separation or definition.
> side_delts: Not Assessable - No photo shows arms raised or flexed to reveal deltoid shape or rounding.

### B4

> chest: Minimal - Chest appears flat with no visible pectoral shape or separation from surrounding tissue in this photo set.
> lats: Minimal - Back appears narrow with little visible width or taper in the rear-view photo.
> biceps: Minimal - Arms show no visible muscle bulge or definition at rest across these photos.
> abs: Emerging - Stomach shows a faint centerline but no distinct segmented shape in this photo set.
> side_delts: Emerging - Shoulders show a slightly rounded cap, though shape remains shallow in these photos.

### B5

> chest: Emerging - Outline visible but shallow; pecs show slight shape without clear separation from surrounding tissue.
> lats: Not Assessable - Skin markings across the back obscure the detail needed to judge lat width or taper.
> biceps: Emerging - Arms show mild shape in relaxed poses, but no flexed view confirms further definition.
> abs: Emerging - A faint centerline is visible on a flat stomach, but no clear muscle separation shows.
> side_delts: Developed - The shoulder shows a rounded, capped shape, fuller than the flatter chest and abs.

### Blind condition rating matrix

| Muscle group | B1 | B2 | B3 | B4 | B5 |
|---|---|---|---|---|---|
| chest | Emerging | Emerging | Emerging | Minimal | Emerging |
| lats | Emerging | Minimal | Minimal | Minimal | Not Assessable |
| biceps | Emerging | Emerging | Minimal | Minimal | Emerging |
| abs | Emerging | Emerging | Minimal | Emerging | Emerging |
| side_delts | Emerging | Emerging | Not Assessable | Emerging | Developed |

(Level names only, transcribed from the verbatim blocks above. Mode / range / exact-agreement
counts are computed in `## Blind Condition: Analysis` by plan 15-02.)

## Blind Condition: Analysis

Status: **BLIND-STABLE**

Single-instrument repeatability, not inter-rater reliability: these are 5 independent draws from
the same model under byte-identical instructions on one unchanged photo-set, not 5 distinct
judges. No kappa, no ICC and no p-value is reported — those assume multiple subjects and would
dress N=5 single-specimen data in a formula that measures nothing here.

| Muscle group | B1 | B2 | B3 | B4 | B5 | Mode | Modal count /5 | Range (levels) |
|---|---|---|---|---|---|---|---|---|
| chest | Emerging | Emerging | Emerging | Minimal | Emerging | Emerging | 4/5 | 1 |
| lats | Emerging | Minimal | Minimal | Minimal | Not Assessable | Minimal | 3/5 | 1 |
| biceps | Emerging | Emerging | Minimal | Minimal | Emerging | Emerging | 3/5 | 1 |
| abs | Emerging | Emerging | Minimal | Emerging | Emerging | Emerging | 4/5 | 1 |
| side_delts | Emerging | Emerging | Not Assessable | Emerging | Developed | Emerging | 3/5 | 1 |

- **Mode** = the most frequently returned level. On a tie, list both and mark the modal count as
  the tied count.
- **Modal count /5** = exact-agreement count: how many of the 5 draws returned the mode.
- **Range (levels)** = `max index − min index`. `Not Assessable` draws are excluded from range and
  counted separately in a `NA count` note under the table if any occurred.

**NA count:** lats 1/5 (B5, occluded per the raw output); side_delts 1/5 (B3, no flexed/raised-arm
view available per the raw output).

**Reading:** The largest range observed is 1 level, tied across all five rated groups — no group
showed a 2-or-greater spread across its 5 draws. The lowest modal count is 3/5, tied across lats,
biceps and side_delts (chest and abs each held 4/5). This rules out a perfectly noiseless
instrument — every group's range is exactly one step, never zero — but because no group's range
reaches 2, a one-level adjacent-pair change on this unchanged photo-set is indistinguishable from
this instrument's own rater noise; a real PHYS-09 diff of exactly one level, on data this thin,
cannot by itself be trusted as evidence of a real physique change. What remains open: N=5 draws on
one specimen, one photo-set, and one model version bounds how far this generalizes — a different
body, a lower-quality photo set, or a different model snapshot could plausibly show a wider (or
narrower) range than the 1-level ceiling observed here.

## Anchored Condition: Raw Output

5 sequential isolated `Task(subagent_type="general-purpose")` calls on the same unchanged
photo-set. A1 is unanchored (independent seed). A2-A5 each received the immediately preceding
step's five verbatim rating lines as `PRIOR OBSERVATION ... approximately 30 days ago`, using
the anchoring block pre-registered in `## Method`. No call was told the photo was unchanged.
Raw output quoted verbatim.

### A1 (seed, unanchored)

> chest: Minimal - Pec outline is flat with no visible lower-chest line or separation from the shoulder in the front view.
> lats: Minimal - Back shows no visible taper or width; no lat outline is apparent beneath the skin.
> biceps: Minimal - Arms show almost no bulge or peak in either the front or side-profile view.
> abs: Emerging - A faint vertical midline is visible but no segmented shape or separation is present.
> side_delts: Minimal - Shoulders appear narrow and sloped, with no visible rounding or cap at the deltoid.

### A2 (anchored to A1)

> chest: Minimal - Pec outline remains flat with no visible separation from the shoulder in the front-facing view.
> lats: Minimal - Back view shows straight sides with no taper or width, no lat outline beneath the skin.
> biceps: Minimal - Arms show little bulge or peak across the front, back, and side-profile views.
> abs: Emerging - A faint vertical midline is visible on the torso but no segmented shape appears.
> side_delts: Minimal - Shoulders appear narrow and sloped, with no visible cap at the deltoid in front view.

### A3 (anchored to A2)

> chest: Minimal - Pec area remains flat in the front view with no visible separation from the shoulder.
> lats: Minimal - Back view shows straight sides with no taper or visible lat width beneath the skin.
> biceps: Minimal - Arms show little bulge or peak in relaxed front, back, and side-profile positions.
> abs: Emerging - A faint vertical midline is visible on the torso but no segmented shape appears.
> side_delts: Minimal - Shoulders appear narrow and sloped, with no visible cap at the deltoid in front view.

### A4 (anchored to A3)

> chest: Minimal - Pec area remains flat with no visible separation from the shoulder or upper abdomen in front views.
> lats: Minimal - Back view shows straight sides with no visible taper or width beneath the skin.
> biceps: Minimal - Arms show little bulge or peak in relaxed front, back, and side positions.
> abs: Emerging - A faint vertical midline is visible but no segmented shape appears on the torso.
> side_delts: Minimal - Shoulders appear narrow and sloped, with no visible cap at the deltoid.

### A5 (anchored to A4)

> chest: Minimal - Pec area remains flat with no visible separation from shoulder or upper abdomen in front or side views.
> lats: Minimal - Back view shows straight sides with no visible taper or width beneath the skin.
> biceps: Minimal - Arms show little bulge or peak in relaxed front, back, and side positions.
> abs: Emerging - A faint vertical midline is visible on the front view but no segmented shape appears.
> side_delts: Minimal - Shoulders appear narrow and sloped in front and side views, with no visible deltoid cap.

### Anchored chain rating matrix

| Muscle group | A1 | A2 | A3 | A4 | A5 |
|---|---|---|---|---|---|
| chest | Minimal | Minimal | Minimal | Minimal | Minimal |
| lats | Minimal | Minimal | Minimal | Minimal | Minimal |
| biceps | Minimal | Minimal | Minimal | Minimal | Minimal |
| abs | Emerging | Emerging | Emerging | Emerging | Emerging |
| side_delts | Minimal | Minimal | Minimal | Minimal | Minimal |

(Level names only. First-vs-last diff and monotonic-direction counts are computed in
`## Anchored Condition: Analysis` by plan 15-02, using the decision rule pre-registered in
`## Method`.)

## Anchored Condition: Analysis

Apply the decision-rule arithmetic pre-registered in `## Method` before any data existed.

| Muscle group | A1 | A2 | A3 | A4 | A5 | anchored_travel (R5−R1) | same-direction transitions /4 | opposing_count /4 | blind_range (from blind condition) |
|---|---|---|---|---|---|---|---|---|---|
| chest | Minimal | Minimal | Minimal | Minimal | Minimal | 0 | 4/4 | 0/4 | 1 |
| lats | Minimal | Minimal | Minimal | Minimal | Minimal | 0 | 4/4 | 0/4 | 1 |
| biceps | Minimal | Minimal | Minimal | Minimal | Minimal | 0 | 4/4 | 0/4 | 1 |
| abs | Emerging | Emerging | Emerging | Emerging | Emerging | 0 | 4/4 | 0/4 | 1 |
| side_delts | Minimal | Minimal | Minimal | Minimal | Minimal | 0 | 4/4 | 0/4 | 1 |

`anchored_travel = 0` for every group, so there is no non-zero sign for a transition to agree or
disagree with. Convention applied: a flat (zero-magnitude) A_i→A_{i+1} step counts toward
"same-direction transitions" when the overall travel is itself flat, and `opposing_count` counts
only transitions that move opposite in sign to a *non-zero* travel. All 20 of the 20 total
transitions across the 5 groups (4 transitions × 5 groups) were flat, so every group reads 4/4
same-direction and 0/4 opposing under that convention.

**PHYS-09 first-vs-last check.** Applying the ordinal diff PHYS-09 will use (improved /
unchanged / regressed / not-comparable) directly between A1 and A5, on a photo-set that never
changed:

| Muscle group | PHYS-09 verdict A1 → A5 | Any single adjacent transition that would also read non-`unchanged`? |
|---|---|---|
| chest | unchanged | No — all 4 adjacent transitions (A1→A2, A2→A3, A3→A4, A4→A5) also read unchanged |
| lats | unchanged | No — all 4 adjacent transitions also read unchanged |
| biceps | unchanged | No — all 4 adjacent transitions also read unchanged |
| abs | unchanged | No — all 4 adjacent transitions also read unchanged |
| side_delts | unchanged | No — all 4 adjacent transitions also read unchanged |

The second column is the point of the whole exercise: a group whose A1→A5 diff is non-`unchanged`
while every adjacent transition reads `unchanged` is a drift production's adjacent-pair-only
design would never surface. No group in this run is in that state — every group's A1→A5 diff
agrees with every one of its own adjacent transitions.

**Reading:** The contrast RESEARCH.md Pattern 3 specifies explicitly as a ratchet's signature —
"blind condition shows scatter with no direction, anchored condition shows a one-directional staircase" — is ABSENT in this run. Every one of the 5 anchored groups returned the identical
level across all 5 sequential steps (`anchored_travel = 0`, `opposing_count = 0/4` on every group,
and there is no direction present to call "one-directional"), while the blind condition — which
has no sequential dependency at all — showed strictly more spread than the anchored chain
(`blind_range = 1` on every group, versus the anchored chain's own range of 0). This rules out a
ratchet in this specific run: the anchored chain was not merely non-directional, it was flatter
than the instrument's own baseline noise floor. No p-value is reported. What remains open: a flat
result at N=5 on one specimen, using an anchoring block that approximates a not-yet-designed
PHYS-07 schema (see `## Scope and Limitations`), bounds how far "not observed here" generalizes —
a longer chain, a different specimen, or a richer real `PRIOR OBSERVATION` payload could still
produce the ratchet this run did not.

## Ratchet Verdict

Status: **RATCHET-NOT-OBSERVED**

Determined by the rule pre-registered in `## Method`, restated here for the reader:

- RATCHET-OBSERVED — some group has `|anchored_travel| >= 1` AND `opposing_count == 0` AND
  `blind_range == 0`.
- RATCHET-INCONCLUSIVE — some group has `|anchored_travel| >= 1` AND `opposing_count == 0`, but
  `blind_range >= 1` for that group.
- RATCHET-NOT-OBSERVED — no group meets either.

**Groups that triggered the verdict:** none — every one of the 5 rated groups (chest, lats,
biceps, abs, side_delts) has `anchored_travel = 0`, so no group satisfies `|anchored_travel| >= 1`
under either positive rule.

**What this answers (ROADMAP success criterion #2):** whether PHYS-07's prior-observation-as-
context mitigation produces a self-reinforcing ratchet — a slow drift no adjacent-pair diff can
detect because every individual month-to-month comparison still looks reasonable. In this N=5 run,
no such drift appeared: the anchored chain was perfectly flat on all 5 muscle groups, and even the
blind condition's own repeat-measure scatter (range 1 on every group) exceeded the anchored
chain's own range of 0. This run gives no evidence of a self-reinforcing ratchet from PHYS-07's
design.

**Corroborating external evidence (15-RESEARCH.md State of the Art):** 2026 LLM-as-judge
anchoring literature independently reports that prior-score context measurably and
systematically shifts subsequent judgments, that explicit warning prompts reduce it only
marginally, and that chain-of-thought prompting can make numeric anchoring worse. Whatever this
N=5 run found, the literature's direction of effect is the prior a Phase 16/17 reader should
carry — a RATCHET-NOT-OBSERVED here is evidence of "not detectable at N=5 on this specimen," not
evidence of "does not exist."

## D-08 Instruction-Level Mitigation Draft

pending -- written by plan 15-02

## Recommended Constants

pending -- written by plan 15-02

## Scope and Limitations

pending -- written by plan 15-02
