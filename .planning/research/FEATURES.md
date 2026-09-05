# Feature Research

**Domain:** Longitudinal physique / body-composition visual assessment, as a structured-data ledger fed by a vision-capable LLM analyst (not a computer-vision pipeline, not a stored-photo app)
**Milestone:** BRETT v2.1 — Longitudinal Physique Analysis
**Researched:** 2026-09-05
**Confidence:** MEDIUM-HIGH overall. HIGH for what is structurally decided already (read from `.planning/PROJECT.md` and the existing codebase patterns this feature must fit). MEDIUM for the rating-scale design (grounded in psychometric literature on ordinal-scale granularity plus bodybuilding judging convention, but there is no published, validated instrument for "rate regional muscular development from a monthly progress photo" — this recommendation is a synthesis, not a citation of an existing standard). MEDIUM for muscle-visibility classification (anatomical/pose reasoning cross-checked against bodybuilding posing guides, not a formal study). LOW→MEDIUM for photo-based body-fat-percent accuracy claims, sourced but with a caveat noted inline.

---

## 0. Read First: What Is Already Decided (do not re-litigate)

Per `.planning/PROJECT.md`'s milestone gate (2026-09-05), these are fixed inputs to this research, not open questions:

- BRETT never receives or stores an image. Claude analyzes photos attached in-conversation; only structured observations persist.
- Ratings are keyed on the existing 19-value `CanonicalMuscleGroup` taxonomy (`backend/app/normalization/muscles.py`), plus bounded free-text notes on **leanness, conditioning and symmetry** (this phrasing — three named qualitative axes, not per-muscle — is already chosen).
- The prior observation is returned as context at analysis time so Claude rates *relative to itself*, not from scratch. This is called out as "the feature's load-bearing design decision" — the rating-scale recommendation below is built to serve this, not to work in isolation.
- Diff analytics (`analytics/physique.py`) produce **improved / unchanged / regressed** per muscle group — a 3-state ordinal comparison, already decided, computed from stored rows only.
- Physique appears in the **monthly report only**; weekly is deliberately excluded. Section 4 below independently corroborates this from the progress-photo literature.
- Ratings are labelled as subjective model output, following the `RecompositionResult.disclaimer` pattern in `backend/app/analytics/recomposition.py` (a required field carrying a fixed disclaimer string verbatim, not generated prose).
- The read-only MCP guard is amended, narrowed to named modules — the same posture `program_switch.py` took in Phase 12, not a general re-opening of write access.

Everything below works **within** this shape. It does not propose reopening any of it.

---

## 1. Rating Scale Design (the core deliverable of this research)

### 1.1 How real practitioners actually assess physique visually

**IFBB/NPC bodybuilding judging** is instructive for *what dimensions matter*, but its *scoring mechanism* is the wrong model to copy directly.

- Judged dimensions, consistently across NPC/IFBB rule sets and independent explainers: **muscle mass/size, symmetry (left-right balance, upper/lower proportion, front/back balance), conditioning (leanness, muscle separation, vascularity, skin tone), and separation/definition between muscle groups** ([BarBend](https://barbend.com/news/how-bodybuilding-is-judged/), [NPC News Online official rules](https://npcnewsonline.com/official-bodybuilding-rules/)). MEDIUM confidence — consistent across multiple independent sources, not a primary IFBB rulebook fetch.
- Critically, judging is **comparative placement, not absolute point-scoring**. Each judge ranks competitors 1st/2nd/3rd/etc. in a single round; placings are summed across 5–9 judges with high/low trimmed, and the lowest total wins ([BarBend scoring explainer](https://barbend.com/news/how-scoring-in-bodybuilding-works/); [tenuncuerpo10](https://www.tenuncuerpo10.com/en/2026/04/how-do-judges-score-at-ifbb-championships-learn-how-the-scoring-system-works/)). MEDIUM confidence.
- **Why this matters for BRETT and why it does NOT transfer directly:** IFBB's reliability comes from **averaging many independent judges' relative rankings of the same lineup at the same instant**, which cancels individual judge bias. BRETT has **one rater (Claude), one subject, evaluated once a month, months apart**. There is no lineup to rank against and no second judge to average with. Copying the *scoring shape* (comparative placement across competitors) is meaningless here; copying the *dimension list* (mass/symmetry/conditioning/separation) is useful and is reflected in the recommended scale and free-text fields below.

**Visual body-fat-percentage estimation** has a documented, non-trivial error band, and it degrades further outside laboratory conditions:

- Trained observers repeatedly exposed to known body-composition subjects can estimate percent body fat to within roughly **±3–5% of criterion (lab) measurements**, but **inter-rater variability of ~2.7% mean difference between two trained raters** was documented even under those favorable conditions, and the original study's own conclusion was that **skinfold/lab methods are preferable to visual inspection** ([PubMed: Bolonchuk et al., "The validity of visual estimations of percent body fat in lean males"](https://pubmed.ncbi.nlm.nih.gov/1569858/) — MEDIUM confidence; full text was not accessible past the abstract listing during this research, so treat the exact percentages as reported by secondary summarization rather than independently re-verified from the primary text).
- Modern computer-vision/AI 2D-photo methods do better in controlled studies — mean errors around **2–4%** against DEXA/BIA in some trials ([Nature npj Digital Medicine, AI 2D-photo body fat study](https://www.nature.com/articles/s41746-024-01380-6); [Nature npj Digital Medicine, smartphone adiposity validation](https://www.nature.com/articles/s41746-022-00628-3)) — MEDIUM confidence, and these are purpose-built CV models trained and validated against a specific pose/lighting protocol and a criterion measurement, which is a materially different setup from an LLM eyeballing a phone photo taken in a bathroom.
- **The takeaway that matters for BRETT:** even the *best-documented, purpose-built, validated* methods carry multi-percentage-point error, and the *closest analogue to what Claude would actually be doing* (a single trained human, one photo, no criterion feedback loop) is the noisiest case in the literature. There is no basis to claim a numeric body-fat percentage from a progress photo with any defensible error bound. This directly informs the anti-feature recommendation in Section 5.

**Published ordinal scales for regional muscular development, specifically:** none were found. This is a genuine gap, not an oversight — searches for a validated clinical or sports-science instrument scoring *regional* (per-muscle-group) visual development from photographs turned up nothing resembling a peer-reviewed scale. The closest real-world analogues are:
- Consumer fitness apps' bespoke scales — e.g., GainFrame's per-muscle-area rating on a 4-level **Needs Work → Developing → Strong → Elite** progression across ~12 muscle areas, feeding into a separate 1–100 composite "physique score" with named tiers (Starting/Building/Solid/Impressive/Elite) ([GainFrame blog](https://gainframe.app/blog/best-progress-photo-apps/), [GainFrame product page](https://gainframe.app/)) — MEDIUM confidence (vendor's own marketing copy, not a validated instrument). This is useful prior art for granularity (4 levels) but its top-anchor language ("Elite," a 1–100 score) is explicitly the kind of population-relative, gamified framing Section 5 recommends BRETT avoid.
- The IFBB/NPC comparative system above, which is not adaptable to single-rater, no-lineup use.

**Ordinal scale granularity vs. rater reliability — what the measurement literature says:**

- Across multiple independent psychometric reviews, the consistent finding is that **reliability and validity improve as categories increase from very few up through roughly 7, with the biggest gains happening between 2 and 4–5 categories, and returns flattening from 7 onward** — one review states inter-rater reliability "increases from two-point to seven-point scales," with 7-category scales behaving "functionally interchangeable with as many as 100 ordered categories" ([ResearchGate: Optimal Number of Response Categories in Rating Scales](https://www.researchgate.net/publication/12546546_Optimal_Number_of_Response_Categories_in_Rating_Scales_Reliability_Validity_Discriminating_Power_and_Respondent_Preferences); [ScienceDirect, same study](https://www.sciencedirect.com/science/article/abs/pii/S0001691899000505); [ResearchGate: Effect of Number of Response Categories on Reliability and Validity](https://www.researchgate.net/publication/236979916_Effect_of_the_Number_of_Response_Categories_on_the_Reliability_and_Validity_of_Rating_Scales)). MEDIUM confidence — consistent finding across several independent papers summarized via search, not independently re-derived from primary data.
- The practical consensus is **4–7 well-anchored, semantically explicit categories** as the reliability-optimizing range; below 4 loses discriminating power, above 7 adds negligible signal and risk of noise ([arXiv, Likert scale response-category error paper](https://arxiv.org/pdf/2502.02846)).
- **Important caveat for extrapolating to this feature:** every one of these studies concerns *self-report survey* Likert scales or *trained human raters with a feedback/calibration loop*, evaluating a fresh stimulus each time. BRETT's situation is different in two ways that both argue for the **lower end** of that range, not the upper end: (1) the rater is a single LLM instance per session with no calibration training and no ground truth to check itself against, and (2) confounding variance from photo conditions (Section 3) is large relative to the true month-to-month signal, so finer gradations are more likely to encode noise (lighting, pump, angle) than real change. There is no published research validating this extrapolation — it is reasoned from the cited granularity literature plus the project's own established pattern of preferring coarse, defensible categories over precise-looking numbers with unstated error bars (`recomposition.py`'s explicit rejection of numeric body-fat/waist inputs; `body_measurements.py`'s independent `insufficient_data`/`is_stale` booleans rather than one blended confidence score).

### 1.2 The concrete recommended scale

**Per-muscle-group development level — a 5-point ordinal scale, absolute at each observation, diffed ordinally across observations.**

| Level | Name | Definition |
|---|---|---|
| 1 | Minimal | No discernible shape or separation beyond baseline muscle tone at this leanness. The region reads as smooth/flat relative to the rest of this person's own physique. |
| 2 | Emerging | Some shape or fullness is visible, but with little to no separation from adjacent muscle groups; outline is soft/rounded rather than distinct. |
| 3 | Developed | Clear, unmistakable shape and size. Separation from at least one bordering muscle group is visible under this photo's lighting/leanness. The region is a normal, present feature of the physique — not a flaw and not a highlight. |
| 4 | Well-Developed | Pronounced size and shape with separation visible on multiple borders. Striations or vascularity may be visible if leanness allows. The region reads as one of this physique's stronger/more complete areas. |
| 5 | Standout | Exceptional size and definition **relative to the rest of this same person's physique** — the most prominent, complete-looking region in these photos. Never a comparison to other people, population norms, or competitive standards (see Section 5, anti-feature: comparative-to-others judgments). |
| — | Not Assessable | First-class non-answer, not a forced guess. Used when the submitted photo set does not include an angle/pose that shows this region (see Section 2 table), or the region is obscured by clothing, lighting, or pose in this specific submission. Carries a short `not_assessable_reason` rather than silently defaulting to a numeric level — this mirrors `body_measurements.py`'s pattern of treating "we have nothing" as its own explicit signal rather than encoding it as a fabricated value. |

**Why 5, not 3, 7, or 10, and why absolute-per-observation rather than pure relative-delta:**

- **Not 3.** Three collapses too much: it cannot distinguish "just starting to show" from "clearly developed but not a strong point," which is exactly the distinction a monthly ledger over a year needs to be useful at all. It would also make the improved/unchanged/regressed diff nearly binary (almost everything reads "unchanged" because there's nowhere to move without crossing a huge gap), defeating the purpose of tracking at this cadence.
- **Not 7 or 10.** Per Section 1.1, the reliability gains of finer granularity assume a calibrated rater with a feedback loop and low measurement noise. Here the rater is uncalibrated (no external ground truth ever checks a Claude rating) and the measurement noise from photo confounders (Section 3) is large. A 10-point scale invites Claude to produce false precision — a level-6-vs-7 distinction that reflects lighting or pump state, not six additional weeks of hypertrophy. Given 19 muscle groups rated every month, a wider scale also multiplies the surface area for session-to-session drift: 19 independent fine judgments per month compounds inconsistency faster than 19 coarse ones.
- **Not a pure relative delta (e.g., "+1/0/-1 vs last time") stored as the primitive.** PROJECT.md already specifies per-muscle-group *development ratings*, i.e., an absolute value at each observation, with the diff computed downstream in `analytics/physique.py` — this preserves a real, independently-meaningful ledger (you can ask "what was my chest rated at in March" without needing every intermediate delta), and the diff itself becomes a trivial, deterministic ordinal comparison (`current_level > prior_level` → improved, `==` → unchanged, `<` → regressed, either side `None` → not comparable) with **zero new arithmetic and no model call in the analytics path** — matching the milestone's own stated constraint.
- **The prior-observation-context design decision is what makes an absolute 5-point scale defensible despite having only one uncalibrated rater.** Feeding Claude its own prior rating and notes before asking for a new one converts "rate this in isolation" (where drift is severe) into "does this look more, the same, or less developed than what I described last time" (an anchored comparative judgment, much closer to what the granularity literature's better-performing designs actually test). The scale's level *language* should be handed to Claude verbatim as part of the tool description or coaching instructions — the same way `INTERPRETATION_DISCLAIMER` in `recomposition.py` travels as a literal constant rather than being regenerated — so the anchors do not drift wording month to month even though the rater (a stateless LLM call) has no persistent memory between sessions.

**Whole-body qualitative notes — bounded free text, not scored:**

Per PROJECT.md's own phrasing, leanness, conditioning and symmetry are **notes**, not per-muscle numeric axes. Recommendation: three separate bounded free-text fields (not one blob), each capped (a concrete number: **300 characters** is proposed here, unsourced but consistent with the project's discipline of measured, budgeted response sizes rather than open-ended prose — see Phase 13's "within MEASURED byte budgets" precedent for report tools):

- `leanness_notes` — qualitative only ("visibly leaner through the midsection than last observation, less noticeable in the upper body" — never a numeric body-fat estimate; see anti-feature 5.1).
- `conditioning_notes` — vascularity, muscle "hardness"/fullness, skin tone/definition as a qualitative snapshot.
- `symmetry_notes` — left/right or upper/lower balance observations, which the 19-value taxonomy cannot represent on its own since it has no left/right split.

This is deliberately the IFBB dimension list (mass → captured by the per-muscle levels; symmetry, conditioning → captured by these two notes fields; separation → folded into the per-muscle level definitions above) reduced to what a single monthly rater can say honestly without inventing false numeric precision.

---

## 2. Muscle-Group Photo Visibility — all 19 canonical groups

Source for the taxonomy: `backend/app/normalization/muscles.py` (`CanonicalMuscleGroup`, 19 values, read directly for this research). Source for pose/visibility reasoning: bodybuilding posing guides describing what each mandatory pose reveals ([Garage Gym Reviews](https://www.garagegymreviews.com/bodybuilding-poses), [StrengthLog](https://www.strengthlog.com/bodybuilding-poses/)), cross-checked against standard progress-photo guidance recommending **three relaxed angles — front, side, back** — rather than flexed competition poses for routine monthly tracking ([SET FOR SET](https://www.setforset.com/blogs/news/how-to-take-progress-pics), [Five Starr Physique](https://fivestarrphysique.com/progress-photo-guidelines/)). None of the 19 groups is an anatomically deep/obscured muscle in the way a psoas or rotator-cuff would be ([NCBI/StatPearls on psoas](https://www.ncbi.nlm.nih.gov/books/NBK535418/), used as the "genuinely invisible" reference point) — Hevy's taxonomy and this project's split are already built from superficial, trainable, hypertrophy-relevant muscle groups, so "not assessable" below always means *occluded by pose/clothing/angle in a normal photo set*, never *anatomically invisible*.

MEDIUM confidence throughout this table — reasoned from posing-guide descriptions and anatomy, not from a controlled study rating real photos.

| Canonical Muscle Group | Visibility from standard relaxed photos (front/side/back) | Classification | Angle(s) needed | Notes |
|---|---|---|---|---|
| `chest` | Clearly visible, front and side | **Reliably assessable** | Front, side | Best of the 19; front-relaxed alone usually suffices. |
| `lats` | Visible front (width, "V-taper") and back (width/thickness) | **Reliably assessable** | Front, back | Back view shows more; front alone underrepresents lat development. |
| `upper_back` (rhomboids/mid-traps) | Only visible from a back angle, and subtle even then unless quite lean | **Partially assessable** | Back (required) | Frequently indistinct from `traps`/`lats` in a relaxed, non-flexed back photo; low resolution of judgment without a flexed rear pose most users won't take monthly. |
| `traps` | Visible from front (neck-to-shoulder line) and back (thickness) | **Reliably assessable** | Front, back | Upper-trap slope reads clearly in a relaxed front photo even without flexing. |
| `lower_back` (erectors) | Only visible from behind, and only shows real definition at low body-fat | **Partially assessable** | Back (required) | Body-fat- and lighting-dependent even when the angle is right; expect frequent "not assessable" at higher body-fat percentages, which is a correct answer, not a gap. |
| `front_delts` | Clearly visible from front | **Reliably assessable** | Front | |
| `side_delts` | Clearly visible from front and side (drives shoulder "width") | **Reliably assessable** | Front, side | |
| `rear_delts` | Only visible from behind; easy to miss even in a back photo unless shoulders are slightly turned or the arm hangs away from the torso | **Partially assessable** | Back (required) | The single most commonly-skipped region in typical progress-photo sets — most people's "back relaxed" photo does not reveal rear-delt shape distinctly. |
| `biceps` | Visible in any arm-uncovered photo, more so with a slight arm flex | **Reliably assessable** | Front or side (arms visible) | Fully relaxed arms understate biceps peak/shape vs. a flexed pose — see Section 3's flex-state confound. |
| `triceps` | On the back of the upper arm — poorly shown by a front-relaxed pose, better from the side or back | **Partially assessable** | Side, back | Front-only photo sets systematically under-assess this group; needs at least a side angle with the arm visible. |
| `forearms` | Visible in almost any photo with bare arms | **Reliably assessable** | Any (arms visible) | Development differences are real but visually subtle month to month. |
| `abs` | Visible from front, extremely leanness-dependent | **Reliably assessable (leanness-dependent)** | Front | The single most confound-sensitive group: bloating, hydration, pump, and whether the subject is actively bracing the midsection all change apparent visibility more than a month of real training does (see Section 3). |
| `obliques` | Visible from front and especially side/three-quarter angles, similarly leanness-dependent | **Reliably assessable (leanness-dependent)** | Front, side | |
| `quads` | Clearly visible front, given shorts/no leg covering | **Reliably assessable** | Front, side | Conditional on clothing — see Section 3 clothing note. |
| `hamstrings` | On the back of the thigh — invisible from front, only shown by a back angle with legs uncovered | **Partially assessable** | Back (required, legs uncovered) | Standard relaxed standing photos (even a "back relaxed" one) often show hamstrings only faintly since the pose isn't designed to reveal them; a slight one-leg-back stance or three-quarter turn helps but isn't standard practice for a home progress photo. |
| `glutes` | Only visible from behind, and clothing-dependent | **Partially assessable** | Back (required), clothing-dependent | Most people's back-relaxed progress photos are taken in gym shorts that fully cover this region — visibility here says as much about the user's clothing choice as their photo protocol. |
| `calves` | Visible front, side, and back given shorts | **Reliably assessable** | Front, side, or back | Most consistently visible lower-body group regardless of angle chosen, given legs uncovered. |
| `abductors` (outer hip/glute medius region) | Blends visually into the quad/glute outline; not a distinct visible bulge for the overwhelming majority of people at any normal training level, and typically covered by shorts even when uncovered elsewhere | **Not assessable** | — | Structurally the same problem the codebase's own comment about `full_body`/D-03 describes for volume: attempting to rate a value here would manufacture a number nobody can actually see, not report a real observation. |
| `adductors` (inner thigh) | Inner thigh; essentially never a distinct, separately-identifiable visual feature in a standing photo at any angle, and almost universally covered by clothing | **Not assessable** | — | Same reasoning as `abductors`. |

**Standard angle set recommended for the photo protocol (Section 3): front-relaxed, side-relaxed, back-relaxed — three photos, not the full 8-pose competition posing routine.** This is consistent with mainstream progress-photo guidance for non-competitors ([SET FOR SET](https://www.setforset.com/blogs/news/how-to-take-progress-pics)), and covers 15 of 19 groups fully or partially; the remaining gaps (`abductors`, `adductors`, and the leanness-conditional read on `abs`/`obliques`/`lower_back`) are not solved by adding more angles — they are solved by `Not Assessable` being a legitimate, expected, first-class answer.

---

## 3. Photo Protocol & Standardization — what moves apparent physique independent of real change

Progress-photo guides converge on a consistent list of controllable confounders ([SET FOR SET](https://www.setforset.com/blogs/news/how-to-take-progress-pics), [Five Starr Physique](https://fivestarrphysique.com/progress-photo-guidelines/), [Gymnoteplus](https://www.gymnoteplus.com/blog/how-to-take-progress-photos), [MacroFactor's progress-photo tips](https://help.macrofactorapp.com/en/articles/117-tips-for-taking-good-progress-photos)). MEDIUM confidence — consistent across many independent fitness-industry sources, not a controlled study, but the physiological mechanisms cited (glycogen/water loading, vasodilation from exercise) are well-established and uncontroversial.

| Variable | Documented effect on apparent physique | Independent of real change? |
|---|---|---|
| **Pump state** (photo taken right after training vs. rested) | Recently-trained muscle is vasodilated and glycogen/fluid-shifted into the tissue, looking measurably larger and more vascular for roughly an hour or more post-exercise | Yes — this is the single most commonly cited distortion in every guide reviewed |
| **Glycogen/carbohydrate intake in the prior 1–2 days** | Low-carb days flatten muscle appearance (less intramuscular glycogen and associated water); high-carb days fill it out, sometimes reducing visible separation via subcutaneous water | Yes |
| **Hydration / sodium intake** | Water retention (high sodium, poor sleep, certain supplements) smooths visible definition, especially abs/obliques | Yes |
| **Time of day** | Water and food shift through the day; a fasted morning photo is the most repeatable baseline cited across every guide | Yes, if inconsistent between sessions |
| **Lighting angle and quality** | Side/angled or harsh lighting creates shadow-based definition that isn't structural; flat/frontal lighting can wash out real definition. One guide notes you "can look 10 pounds lighter or heavier" purely from lighting choice | Yes, and a large effect |
| **Camera distance and height, and lens distortion** | A closer/wider-angle shot systematically distorts proportions (perspective foreshortening) differently from a photo taken from further back with the same framing | Yes |
| **Pose / flex state** | Actively flexing (even lightly) shows dramatically more shape and separation than fully relaxed, especially for abs and biceps; being consistent about "relaxed" vs. "lightly flexed" between sessions matters more than which one is chosen | Yes — and directly interacts with the per-muscle scale in Section 1.2, since a level-3 relaxed and a level-3-lightly-flexed rating are not the same claim |
| **Clothing** | Baggy or dark clothing obscures the exact outlines the taxonomy needs (this is why `glutes`/`hamstrings` are "partially assessable" rather than "reliably assessable" in Section 2) | Not itself a real-vs-apparent confound, but a coverage confound — it changes what's assessable, not what's true |

**Implication for what an observation should record as metadata (not part of the rating itself):** the observation schema should carry a small, bounded set of self-reported confounder flags/fields alongside the ratings, so a future comparison can be honest about them rather than silently treating two photos as equivalent when they weren't taken under equivalent conditions. Concretely:

- `photo_angles_present` (which of front/side/back were actually submitted this time — drives which muscle groups can even be attempted, per Section 2's table)
- `pose_state` (e.g., relaxed vs. lightly flexed — bounded enum, not free text, since Section 1.2's scale depends on this being comparable)
- A short free-text `conditions_note` field for anything the user or Claude flags as unusual this time (e.g., "day after a high-sodium meal," "photo taken immediately post-workout") — this is where the confounders above get honestly logged rather than silently absorbed into the rating

This is the same category of design BRETT already uses in `body_measurements.py` — `is_stale` and `insufficient_data` are **independent, non-collapsed signals** specifically so "we cannot compare" and "this is old news" stay distinguishable. Confounder metadata here plays the analogous role: "the rating changed" and "the conditions were comparable" must stay two separate, inspectable facts, not one blended verdict.

**Corroboration of the milestone's monthly-only decision:** multiple independent guides converge on "**photos taken less than two weeks apart rarely show visible change**" and recommend a minimum interval in the 2–4 week range, with clearly noticeable change more reliably visible at a 1–3 month remove ([Gymnoteplus](https://www.gymnoteplus.com/blog/how-to-take-progress-photos)); separately, visible (not just physiological) muscle change is generally reported to need roughly **6–12 weeks of consistent training** to show up clearly in comparison photos at all, with 3–6 months being described as a more credible window for unambiguous change. This independently supports (it does not merely restate) the milestone gate's decision to exclude physique from the weekly report and include it only monthly — a weekly cadence would be comparing photos at an interval the literature says is below the noise floor for real, visible change.

---

## 4. Longitudinal Comparison as a User-Facing Feature

How existing apps present physique change over time, and what makes it feel meaningful:

- **PeakBFF**: weekly check-ins (photo + optional weight + note) in one private timeline, with a before/after **slider** comparison between any two check-ins ([PeakBFF review, via GainFrame](https://www.peakbff.com/blog/en/best-private-progress-photo-app)).
- **GainFrame**: a "Smart Filter" side-by-side comparison plus derived trend lines (monthly body-fat trend, FFMI trajectory) and a composite score that "goes up as your physique improves," alongside the 12-area Needs Work→Elite muscle map described in Section 1.1 ([GainFrame](https://gainframe.app/blog/best-progress-photo-apps/)).
- **LocalOne Gym Pics**: privacy-first, on-device-only storage, automatic timestamping, no scoring — a pure timeline/album, explicitly positioned against apps that compute anything from the photo ([LocalOneLabs](https://localonelabs.com/pages/blog/best-fitness-progress-photo-apps)).
- The recurring theme across every reviewed app: **"a proper tracker extracts something from the photo you can compare across time — body fat percentage, a score, a measurement, or a written analysis — rather than just being a photo album."** ([GainFrame](https://gainframe.app/blog/best-progress-photo-apps/)) — this is exactly the gap BRETT's structured-observation approach fills, and exactly why "just store the photos" (which BRETT explicitly does not do) would not have been a feature at all.

**What makes a comparison feel meaningful rather than noisy**, synthesized from the above plus Section 3's confounder list:
1. **A stated, honest baseline** — showing what changed *and* what conditions might explain a non-change (this is what `photo_angles_present`/`pose_state`/`conditions_note` metadata is for).
2. **Comparing to the user's own history, not a population score.** GainFrame's 1–100 "Elite" framing is the opposite of this and is called out as an anti-feature below.
3. **An interval long enough to exceed the noise floor** — the monthly-only decision, corroborated in Section 3.
4. **Cross-referencing against a mechanism, not just restating the photo** — BRETT's planned cross-reference of "is the underdeveloped area also the undertrained one?" against `fitness_get_muscle_group_volume` is a materially stronger comparison feature than anything found in the reviewed consumer apps, none of which have real per-muscle training-volume data to cross-reference against. This is a genuine, evidence-grounded differentiator (Section 5).

---

## Feature Landscape

### Table Stakes (Required for This Milestone to Deliver Its Stated Value)

| Feature | Why Expected | Complexity | Notes |
|---|---|---|---|
| Structured per-muscle-group rating on the 19-value `CanonicalMuscleGroup` taxonomy | PROJECT.md requirement; without it there is nothing to diff or report | LOW | Reuses the existing enum in `backend/app/normalization/muscles.py` verbatim — no new taxonomy |
| A defined, documented rating scale with fixed level anchors (Section 1.2) | A badly-designed or undocumented scale makes every stored value meaningless the moment wording drifts between sessions | LOW–MEDIUM | The scale text itself should live as a constant travelling verbatim into the tool schema/coaching instructions, mirroring `INTERPRETATION_DISCLAIMER` in `recomposition.py` |
| `Not Assessable` as a first-class per-muscle state, not a forced numeric guess | 2 of 19 groups (`abductors`, `adductors`) and several conditional groups (Section 2) are routinely unobservable; forcing a number manufactures noise | LOW | Mirrors `insufficient_data`/`is_stale` pattern already established in `body_measurements.py` |
| Bounded free-text notes: `leanness_notes`, `conditioning_notes`, `symmetry_notes` | Explicitly named in PROJECT.md's Active requirements | LOW | Cap each field (proposed: 300 chars) to keep monthly report byte budgets predictable, per Phase 13's precedent |
| Confounder/context metadata per observation (`photo_angles_present`, `pose_state`, `conditions_note`) | Without it, a comparison can't distinguish real change from a lighting/pump/pose difference (Section 3) | LOW–MEDIUM | Small bounded enum/text fields, not a full protocol form |
| Single-call, append-only, non-destructive MCP write tool | PROJECT.md requirement; BRETT's second-ever write path | MEDIUM | Should follow the two-call confirm-gate precedent from `fitness_switch_training_program` only if a mistaken write is genuinely costly to reverse — since this is append-only and non-destructive (a bad observation can simply be superseded next month, not corrected in place), a lighter single-call gate without a confirmation-token round trip is likely appropriate; the "second write tool cannot pass by being skipped" guard-test pattern from Phase 12 still applies |
| Prior-observation retrieval as context at analysis (write) time | PROJECT.md's stated load-bearing design decision; also directly required by the anchored-judgment reasoning in Section 1.2 | MEDIUM | The retrieval is a read, so it can reuse existing read-path patterns; the write tool's handler composes a read before performing the write |
| Deterministic diff (improved/unchanged/regressed) per muscle group, `analytics/physique.py` | PROJECT.md requirement; must be arithmetic-only per the project's "analytics is deterministic and testable" rule | LOW | A 3-way ordinal comparison plus `None`-handling for `Not Assessable` — no model call, no image, matches the constraint verbatim |
| Cross-reference against `fitness_get_muscle_group_volume` | PROJECT.md requirement ("is the underdeveloped area also the undertrained one?") | LOW–MEDIUM | Existing tool/analytics function, called by name, not re-derived |
| Subjective-output disclaimer traveling verbatim on every physique-touching response | Matches the `RecompositionResult.disclaimer` required-field pattern already established for exactly this kind of decision-support-not-diagnosis output | LOW | Same shape as `INTERPRETATION_DISCLAIMER` |
| Monthly-only report integration, `_report_body_fields` split | PROJECT.md requirement, explicit about the split being deliberate | MEDIUM | Corroborated independently by Section 3's interval findings — not just a policy choice, a well-founded one |
| Narrowed read-only guard amendment | Matches the Phase 12 `program_switch.py` precedent; `test_mcp_readonly.py`'s "a second write tool cannot pass by being skipped" assertion needs updating per PROJECT.md | LOW | Named-module narrowing, not a general re-opening |

### Differentiators (Genuine Competitive/Personal Advantage, Evidence-Grounded)

| Feature | Value Proposition | Complexity | Notes |
|---|---|---|---|
| Cross-referencing visible development against real per-muscle training volume | No consumer progress-photo app reviewed (PeakBFF, GainFrame, LocalOne) has real structured training-volume data to cross-reference against — this is only possible because BRETT already has `fitness_get_muscle_group_volume` | LOW (given the dependency already exists) | Directly answers "is this undertrained or just genuinely lagging" rather than only "is this bigger than last time" |
| Anchored/relative rating methodology via prior-observation context | Directly mitigates the single-rater, no-calibration-loop weakness the granularity literature (Section 1.1) flags as a real risk; no reviewed consumer app does this — they either compute a CV-derived score fresh each time (GainFrame) or store nothing but raw photos (LocalOne) | MEDIUM | This is the milestone's own stated design decision; documenting *why* it's the right call (Section 1.2) is this research's contribution |
| Zero photo storage / zero retention | A privacy differentiator versus every reviewed photo-storing competitor, and it is what makes the milestone's `--allow-unauthenticated` Cloud Run deployment defensible for this data category at all | Already decided, N/A to re-cost | Framed here as a differentiator, not a constraint, because it is genuinely unusual among physique-tracking products |
| Deterministic, reproducible diff logic instead of a recomputed "score" | Matches the project's own "analytics must be deterministic and testable" rule; GainFrame's composite score, by contrast, is presumably recomputed by its CV pipeline and not guaranteed stable/reproducible in the same way | LOW | Genuine technical differentiator versus the CV-based competitors, though it is enabled by BRETT's narrower, honest scope (ratings, not photos) rather than a superior algorithm |

### Anti-Features (Explicitly Should NOT Be Built)

| Feature | Why It Looks Appealing | Why It's Problematic | Alternative |
|---|---|---|---|
| **Precise numeric body-fat-percentage estimation from a photo** | Feels like the "real" number users actually want; several competitor apps (GainFrame) advertise it | Even validated, purpose-built computer-vision methods carry 2–4% documented error against DEXA in controlled trials; trained human visual estimation carries ~3–5% error and ~2.7% inter-rater disagreement even under favorable conditions ([PubMed](https://pubmed.ncbi.nlm.nih.gov/1569858/), [Nature npj Digital Medicine](https://www.nature.com/articles/s41746-024-01380-6)). An LLM eyeballing one uncontrolled phone photo, with no criterion measurement to ever check itself against, is the *worst-case* setup in this literature, not a favorable one. A precise-looking number here would carry unstated, unbounded error and directly contradicts the project's own established posture in `recomposition.py`, which explicitly refuses to treat body fat as an input specifically because there is no trustworthy data for it | Keep leanness strictly qualitative (`leanness_notes` free text). If a real number is ever wanted, it already exists as a measured value: `fitness_get_body_measurement_trend`'s `fat_percent` column, sourced from actual body-composition scans, not a photo guess |
| **A composite whole-body physique score (e.g., 1–100, with tiers like "Elite")** | Gamification is engaging; GainFrame's model demonstrates market appetite for it | A single blended number hides exactly the information this feature exists to preserve (which muscle groups moved, which didn't), invites chasing a number rather than reading the underlying ratings, and the tier language itself ("Elite") is inherently a population-relative aesthetic judgment — the same category of comparison the coaching philosophy in `docs/coaching-instructions.md` avoids ("You are decision support... you do not diagnose") | Report the per-muscle levels and the improved/unchanged/regressed diff directly; no aggregation into one score |
| **Aesthetic or comparative-to-others judgments** ("how does this compare to a typical lifter," "rate this out of 10," proportion-ideal comparisons like Adonis/golden-ratio scoring) | Sounds like useful context or motivation | This is precisely the mechanism implicated in body-checking research: repeated visual self-scrutiny against an external standard is associated with worsening body dissatisfaction and negative affect in studies of body-checking behavior, and is a recognized feature of body dysmorphic disorder presentations ([Renfrew Center](https://renfrewcenter.com/what-is-body-checking-body-dysmorphia-signs/); [PMC longitudinal body-checking study](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11671019/)). Explicitly out of place in a tool whose own instructions already state "you are decision support, not a clinician" | Level 5 ("Standout") in Section 1.2 is deliberately defined as relative to *this same person's own physique only* — the scale structurally forbids population comparison at the definition level, not just by convention |
| **Encouraging frequent (weekly or more) photo check-ins for physique specifically** | Feels like "more data is better," and matches how some competitor apps (PeakBFF) default to weekly check-ins | Section 3 shows sub-2-week intervals fall below the real-change noise floor, so frequent re-rating would mostly encode confounder noise as apparent "regression," which is both dishonest data and a documented risk factor: increased self-photographing/checking frequency is linked to worsening body-image outcomes in at-risk individuals ([PMC](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11671019/)) | The milestone's own monthly-only decision is correct and independently corroborated (Section 3) — do not add a weekly or on-demand physique check-in path even as an option |
| **Separate numeric axes per muscle group (mass, symmetry, conditioning, separation as 4 independent scores × 19 groups)**, mirroring full IFBB judging criteria literally | Looks more "complete" / more like real judging | IFBB's multi-axis precision is reliable *because 5–9 independent judges' rankings are averaged*, cancelling individual noise — a mechanism this single-rater, single-subject, monthly system structurally cannot reproduce. 76 numbers a month from one uncalibrated rater is manufactured precision, not more signal | One composite per-muscle development level (Section 1.2) plus the three whole-body qualitative note fields already covers the IFBB dimension list at a granularity a single rater can actually sustain honestly |
| **Gamification elements (streaks, badges, "physique score" that goes up)** | Increases engagement in consumer apps | Not requested; for a personal, single-user coaching tool explicitly framed as decision support, streak/badge mechanics create exactly the compulsive-check-in incentive structure the body-checking research warns against, for no stated user benefit | None needed — the monthly report cadence and the diff narrative already provide the "did this improve" answer without a gamified wrapper |
| **Storing or retaining the analyzed photo, even temporarily (e.g., for a future "show me the actual photo diff")** | Would enable a visual side-by-side, which reviewed competitor apps treat as a core feature | Already excluded at the milestone gate for good reason: it turns BRETT into a store of the single most privacy-sensitive data category it could hold, on a Cloud Run service deployed `--allow-unauthenticated`, with no object storage, retention policy, or image-handling code existing anywhere in the system today | Structured observations only; if a visual side-by-side is ever wanted, that is the user's own photo library, not BRETT's job |

---

## Feature Dependencies

```
CanonicalMuscleGroup enum (existing, backend/app/normalization/muscles.py)
    └──required by──> Per-muscle rating schema (Section 1.2)
                           └──required by──> MCP write tool (physique observation)
                                                  └──required by──> Prior-observation retrieval (read-before-write)
                                                  └──required by──> analytics/physique.py diff logic
                                                                         └──required by──> Monthly report physique section
                                                                         └──required by──> Cross-reference vs fitness_get_muscle_group_volume

fitness_get_muscle_group_volume (existing, Phase 4)
    └──required by──> Cross-reference feature (Section 4 differentiator)

_report_body_fields split (existing shared projection)
    └──must be split before──> Monthly-only physique section can exist without also appearing weekly

Read-only guard amendment (narrowed, per Phase 12 precedent)
    └──required by──> MCP write tool (physique observation)

RecompositionResult.disclaimer pattern (existing, recomposition.py)
    └──pattern reused by──> Physique observation subjective-output disclaimer (required field)

body_measurements.py's independent is_stale/insufficient_data signals (existing pattern)
    └──pattern reused by──> Not-Assessable / confounder-metadata design (Section 1.2, Section 3)
```

### Dependency Notes

- **The rating schema must exist before the write tool can be built**, and the write tool must exist before there is more than one observation to diff — this is a strict phase-ordering chain, not parallelizable within itself.
- **The prior-observation retrieval is not optional infrastructure** — per Section 1.2, it is the mechanism that makes an absolute, single-rater ordinal scale defensible at all. Building the write tool without it and adding it later would mean re-litigating whether the scale itself is even sound.
- **The cross-reference feature depends only on already-shipped capability** (`fitness_get_muscle_group_volume`), so it carries no new research risk of its own — its only dependency is that physique observations exist to cross-reference.
- **The monthly/weekly split depends on `_report_body_fields` being deliberately divided first**, per PROJECT.md's own note that it is currently one shared projection — this is a structural prerequisite, not a policy flag.

---

## MVP Definition (This Milestone)

### Launch With (v2.1)

- [ ] 5-level ordinal per-muscle rating (Section 1.2) with `Not Assessable` as a first-class value, on all 19 `CanonicalMuscleGroup` values
- [ ] Three bounded whole-body free-text fields: leanness, conditioning, symmetry
- [ ] Minimal confounder metadata: `photo_angles_present`, `pose_state`, `conditions_note`
- [ ] Single-call, append-only MCP write tool, with prior-observation context returned/considered at write time
- [ ] `analytics/physique.py` deterministic diff: improved/unchanged/regressed per muscle group, `None`-safe for `Not Assessable`
- [ ] Cross-reference against `fitness_get_muscle_group_volume`
- [ ] Monthly report physique section only, disclaimer field required and verbatim
- [ ] Read-only guard narrowed to the new module, guard test updated per Phase 12 precedent

### Add After Validation (not this milestone, only if the above proves insufficient in real use)

- [ ] Widening the free-text notes if 300 characters proves too tight in practice (a tuning decision, not a design one)
- [ ] A `fitness_get_physique_history` read tool exposing raw per-observation history beyond what the monthly report surfaces, if the user wants to ask ad hoc questions between monthly reports

### Explicitly Not Planned (see Anti-Features table for reasoning)

- [ ] Numeric body-fat-percentage estimation from photos
- [ ] Composite whole-body physique score
- [ ] Comparative-to-others or population-relative judgments of any kind
- [ ] Weekly (or more frequent) physique check-ins
- [ ] Per-muscle multi-axis (mass/symmetry/conditioning/separation) numeric scoring
- [ ] Gamification (streaks, badges, score-that-goes-up framing)
- [ ] Any photo storage or retention, temporary or otherwise

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---|---|---|---|
| Per-muscle 5-level rating + Not Assessable | HIGH | LOW | P1 |
| Bounded whole-body qualitative notes | HIGH | LOW | P1 |
| Confounder metadata fields | MEDIUM | LOW | P1 |
| MCP write tool w/ prior-observation context | HIGH | MEDIUM | P1 |
| `analytics/physique.py` diff logic | HIGH | LOW | P1 |
| Cross-reference vs. muscle-group volume | HIGH | LOW–MEDIUM | P1 |
| Monthly report integration | HIGH | MEDIUM | P1 |
| Read-only guard amendment | HIGH (structural, not user-facing) | LOW | P1 |
| Ad hoc physique-history read tool | MEDIUM | LOW–MEDIUM | P2 (only if monthly report proves insufficient) |

---

## Competitor Feature Analysis

| Feature | GainFrame | PeakBFF | LocalOne Gym Pics | BRETT's Approach |
|---|---|---|---|---|
| Photo storage | Stores/analyzes photos server-side (implied by CV scoring) | Private timeline, stores photos | On-device only, privacy-first | **None — zero image storage or retention, by design** |
| Rating granularity | 4-level (Needs Work→Elite) per muscle area, ~12 areas | None (photo album + slider only) | None | 5-level per muscle group, all 19 canonical groups, plus explicit Not-Assessable |
| Composite score | Yes, 1–100 with named tiers | No | No | **Explicitly excluded (anti-feature)** |
| Numeric body-fat estimate | Yes (CV-derived) | Unclear/not primary feature | No | **Explicitly excluded (anti-feature)**; real measured `fat_percent` already exists via `fitness_get_body_measurement_trend` when available |
| Cross-reference to real training data | No (no training-volume data available to these apps) | No | No | **Yes — the genuine differentiator**, via `fitness_get_muscle_group_volume` |
| Rating methodology | Fresh CV inference each time (no stated anchoring to prior result) | N/A (no rating) | N/A | **Anchored to prior observation**, explicitly to reduce single-rater drift |
| Cadence | Weekly check-ins (PeakBFF); unclear cadence (GainFrame) | Weekly | User-driven, unstructured | **Monthly only**, independently corroborated by the visible-change interval literature (Section 3) |

---

## Sources

**Bodybuilding judging criteria:**
- [BarBend — How Bodybuilding is Judged](https://barbend.com/news/how-bodybuilding-is-judged/) — MEDIUM
- [BarBend — How Bodybuilding Scoring Works](https://barbend.com/news/how-scoring-in-bodybuilding-works/) — MEDIUM
- [NPC News Online — Official Bodybuilding Rules](https://npcnewsonline.com/official-bodybuilding-rules/) — MEDIUM
- [tenuncuerpo10 — How IFBB judges score](https://www.tenuncuerpo10.com/en/2026/04/how-do-judges-score-at-ifbb-championships-learn-how-the-scoring-system-works/) — MEDIUM

**Visual/photo body-fat estimation accuracy:**
- [PubMed — Bolonchuk et al., validity of visual estimation of percent body fat](https://pubmed.ncbi.nlm.nih.gov/1569858/) — MEDIUM (abstract-level access only during this research)
- [Nature npj Digital Medicine — AI 2D-photo body fat estimation](https://www.nature.com/articles/s41746-024-01380-6) — MEDIUM
- [Nature npj Digital Medicine — smartphone camera adiposity validation](https://www.nature.com/articles/s41746-022-00628-3) — MEDIUM

**Ordinal/Likert scale granularity and rater reliability:**
- [ResearchGate — Optimal Number of Response Categories in Rating Scales](https://www.researchgate.net/publication/12546546_Optimal_Number_of_Response_Categories_in_Rating_Scales_Reliability_Validity_Discriminating_Power_and_Respondent_Preferences) — MEDIUM
- [ScienceDirect — same study](https://www.sciencedirect.com/science/article/abs/pii/S0001691899000505) — MEDIUM
- [ResearchGate — Effect of Number of Response Categories on Reliability and Validity](https://www.researchgate.net/publication/236979916_Effect_of_the_Number_of_Response_Categories_on_the_Reliability_and_Validity_of_Rating_Scales) — MEDIUM
- [arXiv — Likert scales and measurement error vs. response categories](https://arxiv.org/pdf/2502.02846) — MEDIUM

**Progress photo protocol / confounders:**
- [SET FOR SET — How to Take Progress Pics](https://www.setforset.com/blogs/news/how-to-take-progress-pics) — MEDIUM
- [Five Starr Physique — Progress Photo Guidelines](https://fivestarrphysique.com/progress-photo-guidelines/) — MEDIUM
- [Gymnoteplus — How to Take Gym Progress Photos That Show Real Change](https://www.gymnoteplus.com/blog/how-to-take-progress-photos) — MEDIUM
- [MacroFactor — Tips for Taking Good Progress Photos](https://help.macrofactorapp.com/en/articles/117-tips-for-taking-good-progress-photos) — MEDIUM

**Posing / muscle-group visibility:**
- [Garage Gym Reviews — 8 Mandatory Bodybuilding Poses](https://www.garagegymreviews.com/bodybuilding-poses) — MEDIUM
- [StrengthLog — 8 Mandatory Bodybuilding Poses](https://www.strengthlog.com/bodybuilding-poses/) — MEDIUM
- [NCBI StatPearls — Psoas Major (anatomical depth reference)](https://www.ncbi.nlm.nih.gov/books/NBK535418/) — HIGH (reference anatomy text)

**Longitudinal comparison / competitor apps:**
- [GainFrame — Best Progress Photo Apps 2026](https://gainframe.app/blog/best-progress-photo-apps/) — MEDIUM (vendor content)
- [GainFrame product site](https://gainframe.app/) — MEDIUM (vendor content)
- [PeakBFF via GainFrame comparison](https://www.peakbff.com/blog/en/best-private-progress-photo-app) — LOW–MEDIUM (vendor/secondary)
- [LocalOneLabs — Best Progress Photo Apps for iPhone](https://localonelabs.com/pages/blog/best-fitness-progress-photo-apps) — LOW–MEDIUM (vendor content)

**Wellbeing / anti-feature justification:**
- [The Renfrew Center — What is Body Checking? Body Dysmorphia Signs](https://renfrewcenter.com/what-is-body-checking-body-dysmorphia-signs/) — MEDIUM (clinical treatment center publication)
- [PMC — Longer-term consequences of increased body checking in women at risk for eating disorders](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11671019/) — HIGH (peer-reviewed study)

**Project-internal sources (read directly for this research):**
- `.planning/PROJECT.md` — milestone scope, shipped-feature inventory, decided design shape
- `backend/app/normalization/muscles.py` — the 19-value `CanonicalMuscleGroup` taxonomy
- `backend/app/analytics/recomposition.py` — the `RecompositionResult.disclaimer` required-field pattern, and the project's existing precedent for refusing unreliable body-fat inputs
- `backend/app/analytics/body_measurements.py` — the `is_stale`/`insufficient_data` independent-signal pattern, and the latest-vs-earliest comparison shape
- `docs/coaching-instructions.md` — the coaching voice ("decision support, not a clinician") this feature's disclaimers and framing must match

---
*Feature research for: BRETT v2.1 Longitudinal Physique Analysis*
*Researched: 2026-09-05*
