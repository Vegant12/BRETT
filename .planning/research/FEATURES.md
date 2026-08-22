# Feature Research

**Domain:** Personal fitness data backend + read-only remote MCP server acting as the data substrate for an AI body-recomposition coach
**Researched:** 2026-08-23
**Confidence:** HIGH for Hevy API surface (live OpenAPI spec fetched today) and volume-counting methodology (2025 meta-regression); MEDIUM for competitor analytics feature sets (vendor marketing pages + review sites); MEDIUM for MCP tool-design token economics (industry write-ups, not a spec).

---

## Scope Note (read this first)

This document is scoped to **v1 = backend-only**: Hevy sync → PostgreSQL → analytics → read-only remote MCP.

Anything requiring iOS/HealthKit or nutrition auto-import lives in the clearly marked
[Deferred to Milestone 2](#deferred-to-milestone-2-healthkit--nutrition) section. It is **deferred, not dropped** —
schema and analytics interfaces should leave room for it.

### Two findings that change v1 scope

Both verified directly against `https://api.hevyapp.com/docs/` (swagger spec parsed 2026-08-23, HIGH confidence):

**1. Hevy exposes `GET /v1/body_measurements`.** It returns `date, weight_kg, lean_mass_kg, fat_percent, neck_cm,
shoulder_cm, chest_cm, left/right_bicep_cm, left/right_forearm_cm, abdomen, waist, hips, left/right_thigh,
left/right_calf`. PROJECT.md currently assumes body measurements are manual-entry-only in v1 and that weight
automation waits for HealthKit. **That assumption is wrong.** If the user logs weight in Hevy, body-weight trend and
recomposition status become *automatic* in v1 with no Apple Developer account. This promotes weight trend
(T8) and recomp status (T11) from "depends on manual discipline" to "real features."

**2. Hevy's muscle taxonomy cannot answer the user's own example question.** The `MuscleGroup` enum is:
`abdominals, shoulders, biceps, triceps, forearms, quadriceps, hamstrings, calves, glutes, abductors, adductors,
lats, upper_back, traps, lower_back, chest, cardio, neck, full_body, other`. There is **one** `shoulders` bucket — no
front/side/rear delt split. The blueprint (§18) requires `front_delts / side_delts / rear_delts` and §36 lists
*"How many sets am I doing for side delts?"* as a target question. Passing Hevy's `primary_muscle_group` straight
through **cannot** answer it. The exercise normalization layer is therefore not a nice-to-have mapping convenience —
it is a hard prerequisite for the flagship "which muscles are undertrained?" use case.

---

## Feature Landscape

### Layer 0 — Analytics Substrate (invisible, but everything above it is wrong without it)

These are not features a user would name. They are the correctness preconditions. Every one of them is a place
where a naive implementation produces plausible-looking numbers that are silently wrong — the worst possible
failure mode for a system whose entire value is "Claude stops guessing."

| Feature | Why Required | Complexity | Notes |
|---------|--------------|------------|-------|
| **Hard-set classification** | Hevy `set.type ∈ {normal, warmup, dropset, failure}`. Counting warmups as working sets inflates every volume number, and warmup sets will generate false PRs and false "declining" signals. | LOW | Default: `normal` + `failure` count as 1 hard set; `warmup` excluded; `dropset` configurable (recommend 0.5 or "attach to parent set"). Make the policy an explicit, documented, testable constant — not an implicit filter buried in a query. |
| **Exercise → canonical muscle mapping w/ delt-head split** | Hevy has one `shoulders` bucket (see above). Also needed to merge custom exercises and to override Hevy's occasionally odd secondary assignments. | MEDIUM | Seed from `GET /v1/exercise_templates` (`primary_muscle_group`, `secondary_muscle_groups`, `equipment_category`, `is_custom`), then apply a BRETT-owned override table. ~30-60 exercises will realistically need hand-mapping for a single user. Store `source_muscle` alongside `canonical_muscle` so overrides are auditable. |
| **Fractional set counting (direct 1.0 / indirect 0.5), configurable** | Pelland et al. 2025 (*Sports Medicine*, 67 studies / 2,058 participants) found the fractional method — indirect work counted at 50% — had the strongest evidence vs. direct-only or total counting (Bayes Factors 9.48–54.84). This is the blueprint's §18 choice and it is the evidence-backed one. | LOW-MED | Store direct and indirect *separately* and let the weight be applied at query time. Never persist only the blended number — the coach needs to see `triceps: direct 6, indirect 8` to reason about it. Expose the weight used in the response. |
| **Exercise modality awareness** | Hevy `exercise.type ∈ {weight_reps, reps_only, bodyweight_reps, bodyweight_assisted_reps, duration, weight_duration, distance_duration, short_distance_weight}`. Volume load and e1RM are meaningless or actively misleading for most of these. Pull-ups logged as `bodyweight_reps` carry `weight_kg = 0` or added-weight-only → volume load ≈ 0 and PR detection breaks. | MEDIUM | Gate every metric on modality: e1RM only for `weight_reps` (and only 1–10 rep sets); volume load only where a load exists; for `bodyweight_reps`, optionally add bodyweight from the Hevy body-measurement series (available in v1) and label it `estimated`. Return `metric_not_applicable` rather than `0` — a zero is a lie an LLM will repeat. |
| **Local-timezone week bucketing** | Asia/Jakarta is UTC+7; a Monday-evening workout stored in UTC lands on the wrong ISO week if bucketed naively. Every weekly number depends on this. | LOW | Convert to user tz, then bucket. Pick and document a week boundary (recommend ISO week, Monday start) and return `week_start` explicitly in payloads. Configurable, not hard-coded. |
| **Data freshness + coverage metadata** | Blueprint §39. An LLM cannot distinguish "you trained zero legs" from "sync is 9 days stale" unless you tell it. | LOW | Per-source `last_synced_at`, plus per-response `weeks_covered`, `sessions_in_window`, `rpe_coverage_pct`. See [What the AI Coach Layer Actually Needs](#what-the-ai-coach-layer-actually-needs). |

---

### Table Stakes (the coaching use case does not work without these)

Benchmarked against Hevy Pro, Strong Premium, Boostcamp, and RP Hypertrophy. Every one of these exists in at
least two of those products; several exist in all four. Missing any of them means Claude has to fall back to
guessing, which is precisely the failure the project exists to eliminate.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Recent workouts + single workout detail** | Every tracker has a history view. Claude needs raw ground truth to sanity-check its own aggregates and to answer "what did I do Tuesday?" | LOW | Keep it paginated and bounded. Default to a small `limit` (5–10 workouts) and a compact per-set shape. This is the tool most likely to blow the context window if unbounded. |
| **Weekly training volume** (sessions, hard sets, reps, volume load, duration) | Hevy Pro, Strong Premium, Boostcamp, TrainHeroic all ship this. It is the baseline "am I doing enough" number. | LOW-MED | Blueprint §17 is right that volume load (`sets × reps × kg`) is *not* comparable across exercises — never let it be the headline for a hypertrophy question. Return it, label it, and lead with hard sets. |
| **Per-muscle-group weekly volume with direct/indirect split** | Hevy ships a muscle-distribution chart and sets-per-muscle-per-week; RP's entire methodology is built on it. This is the single most-used input for "which muscles are undertrained?" | MEDIUM | Depends on the canonical mapping + fractional counting substrate. Output shape should be `{muscle, direct_sets, indirect_sets, weighted_sets, reps, sessions_hit}` per week. |
| **Exercise progression time series** | Strong (1RM progression graphs), Boostcamp (e1RM curve from top sets), Hevy (per-exercise weight progression). Universal. | MEDIUM | Per blueprint §19: `date, weight, reps, sets, estimated_1rm, volume, rpe`. Define "top set" explicitly (heaviest working set? best e1RM set?) and be consistent — inconsistency here makes trend detection noise. |
| **Estimated 1RM (labelled as an estimate, gated by rep range)** | Present in Strong, Boostcamp, and essentially every serious tracker. It is the standard cross-session strength normalizer when weight and reps both move. | LOW | Epley (`w × (1 + r/30)`) is the common default. Accuracy is ±5% at 2–10 reps, degrades to ±15–20% above 10 reps, and is not recommended at 15+ reps or on isolation lifts where local endurance dominates. **Enforce this:** return `null` + a reason outside the valid band rather than a confident wrong number. Also do not compute from fatigued back-off sets. |
| **Personal record detection** | Automatic PR detection is standard (Boostcamp explicitly tracks max weight, max volume, max reps, lifetime bests, and an e1RM curve). | MEDIUM | Blueprint §22: max weight, max reps at a given weight, e1RM PR, volume PR, rep PR — each with a date. **PR hygiene matters:** exclude warmup sets, gate e1RM PRs on the valid rep band, and treat a rep-PR at a lighter weight as a distinct record class rather than a headline "new PR." |
| **Progressive-overload classification** (improving / stable / declining / unclear) | This is the direct answer to the project's #1 question, "Am I progressing?" No mainstream app returns a *verdict* — they return a chart and make you interpret it. For an MCP consumer the verdict is the product. | MEDIUM-HIGH | Blueprint §20: must use multiple weeks, never a single session. Recommend a slope over e1RM (or top-set load for non-`weight_reps`) across ≥3 data points, with a minimum-sessions gate producing `unclear`/`insufficient_data`. Return the slope and n, not just the label. |
| **Plateau / stall detection** | The other half of the same question. Common practitioner definition: a sustained lack of measurable progress for **at least 3–4 weeks**, because 1–2 down sessions are normal variation. | MEDIUM-HIGH | Blueprint §21: configurable 3–6 week window, return `exercise, plateau_duration, recent_performance, historical_best, confidence`. **Also return the window and threshold used** so the coach can explain and the user can challenge it. Frequency-aware: a lift trained 1×/week needs a longer window than one trained 3×/week. |
| **Training frequency** (sessions/wk, per-muscle, per-exercise) | Standard in Hevy/Strong advanced stats. Also the denominator that makes plateau windows and volume-per-session meaningful. | LOW | Blueprint §23. Worth noting for the coach's benefit: Pelland 2025 found frequency had negligible independent effect on hypertrophy *once weekly volume is matched* — so frequency is best framed as a volume-distribution/recovery lever, not a growth lever in itself. |
| **Body weight trend** (7/14/30-day rolling averages + weekly rate of change) | Blueprint §25. Universally understood that single weigh-ins are noise. | LOW-MED | **Now feasible in v1 via `GET /v1/body_measurements`** — no HealthKit required. Also express rate as **% of bodyweight per week**, not just kg: the actionable reference bands are ~0.25–0.5%/wk for a lean gain and ~0.5–1%/wk for a cut. Handle sparse/irregular weigh-ins explicitly (gaps, not interpolation-by-stealth). |
| **Period comparison** (current window vs previous window, with deltas) | Blueprint §30/§36: "Compare my last 4 weeks to the previous 4 weeks." | MEDIUM | **Normalize to per-week rates**, not raw totals — otherwise an 8-week vs 3-week comparison produces a garbage conclusion that the LLM will state confidently. Compute the deltas server-side; do not ship two blobs and hope. |
| **Recomposition status classification** | Blueprint §26. The synthesis metric the whole project is named for. | MEDIUM | v1 inputs: weight trend + waist/measurements (both from Hevy) + training volume + strength progression. Classes: `likely_recomp_progressing, likely_muscle_gain, likely_fat_loss, weight_stable, weight_gain_too_fast, weight_loss_too_fast, insufficient_data`. **Explicitly decision-support, not diagnostic** — and never claim body-fat % accuracy the measurement method doesn't support. Will get materially better in Milestone 2 with calories/protein/steps. |

---

### Differentiators (meaningfully better coaching, not just parity)

Ranked roughly by leverage-per-unit-effort. Note the framing: BRETT is not competing with Hevy on charts — Hevy
already has a muscle heatmap and volume graphs and will always beat a personal project on UI. BRETT competes on
being the only place where this data is **machine-readable, decision-ready, and reasoned over conversationally**.
That's the moat: not the model, but what the model is allowed to see.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **`fitness_get_training_summary` — one pre-composed coach briefing** | **Highest-leverage feature in the project.** Bundles freshness + last-N-weeks volume by muscle + top progressing lifts + stalled lifts + recent PRs + weight trend into one call. Without it, answering "analyze my last 8 weeks" costs 6–8 sequential tool round-trips, each re-serializing schemas into context. | MEDIUM | Pure composition over existing analytics — near-zero new logic, large UX and token win. Make the window a parameter (`weeks`, default 8). Keep it under a few KB of JSON. |
| **Volume landmark context (MEV/MAV/MRV bands per muscle)** | Turns "chest: 9 sets" into "chest: 9 sets, below your 12-set target." Without a reference band, Claude invents thresholds from training data — inconsistently, session to session. This is RP's entire product wrapped in one field. | LOW-MED | Store as **user-configurable per-muscle targets**, not hard-coded science. Common practitioner bands: MV ≈ 6 sets/wk, MAV ≈ 12–20 sets/wk, MRV ≈ 18–25+ and highly individual. Caveat honestly: Pelland 2025 found returns *diminish* (sets 11–18 ≈ 70% efficiency, 19+ ≈ 50%) but found **no absolute ceiling** — so MRV is a fatigue heuristic, not a measured growth cliff. Label the field `target_band` with a `source: user_configured`. |
| **Muscle-group balance ratios** | Directly answers "am I balanced / what's neglected" — the question Hevy's heatmap gestures at but never quantifies. Push-dominance is common even in elite athletes (15–22% push>pull in elite throwers), and anterior-dominant patterns with neglected stabilizers are the standard imbalance. | LOW-MED | Compute push:pull, quad:hamstring, chest:upper-back, and side/rear-delt share of total shoulder volume. Report as ratios **plus the raw sets** so the coach can sanity-check. Frame as training-distribution observations, **not** injury-risk predictions. |
| **Stimulus-quality metrics from RPE** | Distinguishes "20 junk sets" from "12 hard sets." Volume without proximity-to-failure is a number that flatters bad training. Boostcamp's edge over Strong is literally that it takes RPE seriously. | LOW | Hevy sets carry `rpe` (nullable, values ~6–10). Derive `rir ≈ 10 − rpe`. Report `mean_rpe`, `pct_sets_rpe_gte_8`, and critically **`rpe_coverage_pct`** — if the user only logs RPE on 20% of sets, every RPE-derived number is a sample, and the coach must be told so. Note: the Hevy API has **no `rir` field**; the blueprint's §8 `rir` column must be derived or manual. |
| **Automatic body-measurement sync from Hevy** | Unlocks weight trend + recomp status + bodyweight-aware volume load in v1 with zero HealthKit dependency. Also gives waist/hips — the best cheap recomp signal when scale weight is flat. | LOW-MED | `GET /v1/body_measurements` (paginated, pageSize max 10). Model it as a *provider* behind the same `body_measurements` table so manual entry and a future HealthKit feed coexist without a schema change. |
| **Explicit uncertainty on every analytic** | The difference between a coach and a hallucination generator. `confidence`, `n_observations`, `insufficient_data: true`, `reason`. | LOW | Costs almost nothing, prevents the single most damaging failure mode: Claude asserting "your bench is stalling" from two data points. Should be a shared response envelope, not per-tool ad-hoc fields. |
| **Exercise substitution / equivalence grouping** | "Bench Press (Barbell)" vs "Bench Press (Smith)" vs "Bench Press (Dumbbell)" fragment into three flatlined series when the user is actually progressing. Produces false plateaus. | MEDIUM | Group by `movement_pattern + primary_muscle`, keep variants distinguishable, and let progression run at both levels. Also needed for fuzzy name resolution when Claude passes `exercise="Bench Press"`. |
| **"What should I progress next" candidate ranking** | Answers blueprint §36's "Which exercises should I focus on progressing next week?" deterministically. | MEDIUM | Rank by: recently stable-but-not-declining + trained frequently enough + RPE headroom + not already at a recent PR. **Return ranked candidates with the reasons as data.** Do not return a recommendation sentence — leave the judgement call and the phrasing to Claude. |
| **Routine adherence (planned vs actual)** | `GET /v1/routines` + `/v1/routine_folders` exist. Answers "am I actually running my program?" — a question no volume chart can answer, and a very common real cause of "why am I not progressing." | MEDIUM | Genuinely useful but not required for the core loop. Good v1.x candidate. |
| **Session density / duration trends** | `start_time`/`end_time` + `supersets_id` are already synced. Cheap signal for "workouts getting longer for the same work" (a fatigue/focus indicator). | LOW | Nice-to-have. Low value alone, decent value bundled into the training summary. |

---

### Anti-Features (seem good, actively harmful here)

The governing principle: **BRETT is a data layer, not an app.** Most of what makes a consumer fitness app good
makes an MCP server bad. A second principle: **Claude is the coach.** Anything that duplicates judgement,
narrative, or motivation in the backend is redundant at best and a source of contradiction at worst.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Gamification: streaks, badges, XP, achievements** | Every consumer fitness app has them; they feel like "engagement." | There is no UI to display them and no user to motivate other than one person who already opted into a self-built analytics backend. Worse: streak logic creates a data-model incentive to train when a deload is the correct call — the opposite of what a recomposition coach should encourage. | Report `sessions_per_week` and consistency as plain numbers. If encouragement is wanted, it belongs in the coach system prompt, where it can be contextual. |
| **Push notifications / proactive nudges / scheduled check-ins** | "The coach should reach out when I miss a week." | MCP is request-response; the server cannot initiate a Claude conversation. Building it means a scheduler, a delivery channel (email/APNs), and a whole new failure surface — for a single user who can just ask. | Surface staleness and gaps (`days_since_last_workout`, `last_synced_at`) so Claude flags them the moment a conversation starts. |
| **Social feed, friends, sharing, leaderboards** | Hevy's actual growth engine. | Single-user by definition, and it would mean exposing personal health data over a public surface. Direct conflict with the project's data-privacy constraints (§33). | Nothing. Hevy already does this; BRETT doesn't need to. |
| **Write/mutation MCP tools (log a workout, edit sets, delete)** | Tempting because the Hevy API genuinely supports `POST /v1/workouts`, `PUT /v1/workouts/{id}`, `POST /v1/routines`, `POST /v1/body_measurements` — it's *right there*. | An LLM with write access to your training log can silently corrupt years of history, and a remote MCP endpoint with a bearer token becomes a high-value target rather than a low-value one. Explicitly excluded by PROJECT.md and blueprint §31. | Read-only in v1. Mark every tool `readOnlyHint: true`. If writes are ever added, scope them to a separate endpoint with separate credentials and per-mutation confirmation. |
| **Generic "run a query" / "get all workouts" / raw-table tools** | Maximum flexibility, minimum server code — let Claude figure it out. | Blows the context window (a year of sets is hundreds of KB), pushes arithmetic onto the component worst at arithmetic, makes results non-reproducible, and re-opens the whole SQL-injection/data-exfiltration surface the purpose-built-tool design was chosen to close. Blueprint §29 and rule #4 forbid it. | Purpose-built tools with bounded, parameterized windows. If a genuinely new question appears, add a tool. |
| **Backend-generated natural-language "insights" / coaching prose** | Feels like the product is smarter; other AI fitness apps ship canned insight strings. | Claude *is* the narrative layer. Backend prose is untestable, will contradict Claude's own reasoning in the same response, wastes tokens, and defeats "analytics must be deterministic and testable" (rule #10). | Return structured verdicts + the evidence (`status`, `slope`, `n`, `threshold_used`). Claude writes the sentence. |
| **Composite "readiness" / "recovery" / "fatigue" scores in v1** | RP, Whoop, TrainHeroic all have one; it looks authoritative. | v1 has **no** sleep, HRV, or resting HR (all Milestone 2). A readiness score built from training volume alone is a repackaged volume number wearing a lab coat — and an LLM will treat the single number as ground truth and stop looking at the inputs. | Defer to Milestone 2. Even then, expose the *indicators* separately (blueprint §28 explicitly says "recovery indicators," not conclusions). |
| **ACWR / training monotony / training strain** | Legitimate sport-science metrics; sound rigorous. | Developed for team field sports on session-RPE and GPS load, and their validity as injury-risk predictors is actively contested in the literature. They need a daily-load stream BRETT doesn't have in v1, and there is no injury-prediction mandate here. High complexity, contested payoff, easy to over-trust. | Weekly hard sets per muscle + weekly rate-of-change. Simpler, defensible, sufficient for hypertrophy decisions. |
| **Estimated 1RM everywhere** | It's the universal strength number; every app shows it. | Meaningless for `duration`, `distance_duration`, `reps_only`; unreliable above 10 reps (±15–20%) and not recommended at 15+; poor on isolation lifts where local endurance dominates; and garbage when computed off a fatigued 4th back-off set. Producing a number anyway teaches Claude to trust a fiction. | Gate on modality + rep band + set position. Return `null` with `reason: "reps_out_of_valid_range"`. For excluded exercises, track top-set load × reps and rep-PRs instead. |
| **Body-fat % from tape/BMI formulas presented as a measurement** | Hevy's `fat_percent` field exists; Navy-tape formulas are easy. | Method-dependent error dwarfs the change being tracked over a recomp timescale. Blueprint §24 warns about this explicitly. An LLM will happily narrate "you lost 2% body fat" from measurement noise. | Store whatever the user provides with a `method`/`source` field. Trend **waist and weight** — both directly measured, both far more reliable — and let body-fat % be a soft corroborating signal at most. |
| **TDEE / calorie / macro recommendation engine in v1** | Recomposition is famously nutrition-driven, so it feels essential. | v1 nutrition is manual-entry only and will be sparse. A metabolic model built on sparse self-reported intake produces confident numbers from bad data. This is a whole product, not a feature. | Store manual nutrition. Expose `avg_daily_calories`, `avg_protein_g`, and **`days_logged`**. Let Claude reason about adequacy given the coverage. Revisit in Milestone 2. |
| **Live Hevy fetch on MCP request** | "Always fresh data," no sync job to maintain. | Contradicts "PostgreSQL is the source of truth" (§2.3). `GET /v1/workouts` has **pageSize max 10** — a year of history is dozens of round-trips per question. Adds Hevy latency and rate limits to every Claude turn, and makes analytics non-reproducible. | Scheduled sync (1–6h per §38) + `last_synced_at` on every response. Optionally one explicit `refresh` path, never implicit. |
| **Charts, images, heatmaps, or rendered visuals from MCP** | Hevy's muscle heatmap is its most-loved feature. | It's a *UI* feature. An MCP consumer cannot use a PNG, and generating one costs tokens and dependencies for zero analytical gain. | Return the numbers. Claude renders tables or artifacts if the user wants a visual. |
| **A tool per question** (40+ narrow tools) | Feels tidy and self-documenting. | Tool definitions cost ~100–500 tokens *each* and are re-serialized into context on every turn; large MCP setups routinely burn 30–50% of the context window before any work happens. | ~11–13 well-parameterized tools for v1 (the blueprint's 15 minus the Milestone-2 activity/recovery ones). Add parameters, not tools. |

---

## Feature Dependencies

```
Hevy sync (workouts + sets + exercise_templates)
    │
    ├──> Hard-set classification (set.type filter)
    │        └──> Weekly training volume ─────────────────┐
    │                                                     │
    ├──> Exercise normalization (canonical muscle map)    │
    │        │    + delt-head split                       │
    │        └──> Fractional set counting (1.0 / 0.5)     │
    │                 └──> Per-muscle weekly volume ──────┤
    │                          ├──> Muscle balance ratios │
    │                          ├──> Volume landmark bands │
    │                          └──> Muscle-group frequency│
    │                                                     │
    ├──> Exercise modality gating (exercise.type)         │
    │        └──> Estimated 1RM (weight_reps, 1-10 reps)  │
    │                 ├──> PR detection (e1RM PR class) ──┤
    │                 └──> Exercise progression series    │
    │                          ├──> Overload classification
    │                          │        └──> Plateau detection
    │                          │                 └──> "What to progress next"
    │                          └──> Exercise substitution grouping
    │                                    └──(prevents false)──> Plateau detection
    │                                                     │
    └──> Training frequency ──(sets plateau window)──> Plateau detection
                                                          │
Hevy body_measurements sync                               │
    └──> Weight trend (7/14/30d + %BW/wk)                 │
             └──> Recomposition status <───(training volume + progression)
                                                          │
Local-tz week bucketing ──(required by ALL weekly metrics)┘
    │
Period comparison ──(re-runs every weekly metric over two windows)
    │
Data freshness + coverage metadata ──(wraps every response)
    │
fitness_get_training_summary ──(composes: volume + muscle volume + progression
                                 + plateaus + PRs + weight trend + freshness)
```

### Dependency Notes

- **Everything requires local-timezone week bucketing.** Asia/Jakarta is UTC+7. Get this wrong and every weekly
  number is subtly off, with no visible symptom. Build and test it first, in the same phase as the data model.
- **Per-muscle volume requires exercise normalization, which requires the delt-head split.** This is the longest
  pole in the analytics phase and the one with irreducible manual work (hand-mapping the user's actual exercise
  list). It cannot be parallelized away, and the flagship question depends on it.
- **Plateau detection requires progression, which requires a consistent "top set" definition and e1RM gating.**
  Three layers deep. Sequencing violation here means plateau detection gets built on an unstable definition and
  has to be redone.
- **Plateau detection also requires training frequency** — a lift trained once a week needs a longer plateau
  window than one trained three times a week, or you'll flag normal cadence as a stall.
- **Exercise substitution grouping *prevents defects in* plateau detection** rather than adding capability. If
  it's deferred, plateau detection will emit false positives for anyone who rotates variants. Worth knowing the
  tradeoff explicitly rather than discovering it from a wrong answer.
- **Recomposition status is a true synthesis node** — it needs weight trend AND training volume AND strength
  progression. It must be the *last* analytic implemented in v1, and it must degrade to `insufficient_data`
  cleanly when any input is thin.
- **Volume landmark bands and muscle balance ratios are cheap adapters on per-muscle volume.** Once that node
  exists, both are small. Good candidates to bundle into the same phase.
- **`fitness_get_training_summary` depends on nearly everything**, so it belongs in the MCP phase, not the
  analytics phase — it's composition, not computation.
- **Anything RPE-derived degrades gracefully but never blocks.** `rpe` is nullable in Hevy. Treat coverage as a
  reported quantity, never a hard dependency.

---

## MVP Definition

### Launch With (v1 — backend + read-only MCP)

- [ ] **Hevy workout/set/exercise-template sync** — the whole system is downstream of this
- [ ] **Hard-set classification** — without it every volume number is inflated by warmups
- [ ] **Exercise normalization with delt-head split** — required for the flagship "undertrained muscles" question
- [ ] **Fractional set counting (configurable 1.0/0.5)** — evidence-backed, and the direct/indirect split is what makes the number interpretable
- [ ] **Local-tz week bucketing** — silent-corruption risk if deferred
- [ ] **Weekly training volume** — baseline metric
- [ ] **Per-muscle weekly volume (direct/indirect)** — the most-used coaching input
- [ ] **Exercise progression + modality-gated e1RM** — answers "am I progressing" at the lift level
- [ ] **PR detection with PR hygiene** — the most motivating, most trivially-wrong metric
- [ ] **Progressive-overload classification** — the verdict the coach needs, not a chart
- [ ] **Plateau detection (configurable window, confidence, threshold echoed)** — the other half of the core question
- [ ] **Training frequency** — needed on its own and as a denominator elsewhere
- [ ] **Hevy body-measurement sync + weight trend (7/14/30d, %BW/wk)** — newly feasible in v1, no HealthKit needed
- [ ] **Recomposition status (decision-support framing)** — the project's namesake synthesis
- [ ] **Period comparison, per-week normalized** — explicitly listed in blueprint §36
- [ ] **Data freshness + coverage envelope on every response** — the anti-hallucination guardrail
- [ ] **`fitness_get_training_summary`** — highest leverage-per-effort feature in the project
- [ ] **Read-only MCP tools, bearer auth, `readOnlyHint` annotations** — the delivery surface

### Add After Validation (v1.x)

- [ ] **Volume landmark bands (MEV/MAV/MRV)** — trigger: once you've seen Claude invent inconsistent set targets across two conversations
- [ ] **Muscle balance ratios** — trigger: after per-muscle volume is trusted and you start asking comparative questions
- [ ] **Stimulus-quality / RPE metrics** — trigger: once `rpe_coverage_pct` is consistently above ~50%
- [ ] **Exercise substitution grouping** — trigger: the first false plateau caused by a variant swap
- [ ] **"What to progress next" ranking** — trigger: after plateau detection has proven accurate on real data
- [ ] **Routine adherence (planned vs actual)** — trigger: when "am I following my program" becomes a recurring question
- [ ] **Session density / duration trends** — trigger: bundle into the training summary when convenient
- [ ] **Bodyweight-aware volume load for `bodyweight_reps`** — trigger: once the weight series from Hevy is dense enough to interpolate honestly

### Deferred to Milestone 2 (HealthKit / nutrition)

Explicitly **deferred, not dropped**. Schema and analytics interfaces should accommodate these without a rewrite —
in particular, `health_samples`, a provider-agnostic `body_measurements` source column, and a nutrition provider seam.

- [ ] **Activity analysis** (steps, active energy, exercise minutes, 7/30-day trends) — blueprint §27; requires HealthKit
- [ ] **Recovery indicators** (sleep duration/consistency, resting HR, HRV) — blueprint §28; requires HealthKit. Note: this is the *only* honest foundation for a readiness metric
- [ ] **Sleep → training-performance correlation** — blueprint §36 lists "How has my sleep affected my training?"; impossible in v1
- [ ] **Apple Health workouts** (cardio and non-Hevy sessions) — needed for total energy expenditure and for a complete training picture
- [ ] **Nutrition auto-import provider** — v1 is manual entry only; auto-import is what makes calorie/protein analytics trustworthy
- [ ] **Full recomposition analytics** combining calories + protein + steps + activity with weight and training — blueprint §24; the v1 version is a deliberately reduced form
- [ ] **HealthKit body weight / body fat as an additional source** — largely obviated in v1 by Hevy `body_measurements`, but still valuable for density (daily smart-scale weigh-ins) and as a fallback
- [ ] **Composite readiness score** — only defensible once sleep/HRV/RHR exist, and even then framed as indicators (§28)

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Hevy sync (workouts/sets/templates) | HIGH | MEDIUM | P1 |
| Hard-set classification | HIGH | LOW | P1 |
| Local-tz week bucketing | HIGH | LOW | P1 |
| Exercise normalization + delt-head split | HIGH | MEDIUM | P1 |
| Fractional set counting | HIGH | LOW | P1 |
| Per-muscle weekly volume | HIGH | MEDIUM | P1 |
| Weekly training volume | HIGH | LOW | P1 |
| Exercise progression + gated e1RM | HIGH | MEDIUM | P1 |
| Progressive-overload classification | HIGH | MEDIUM | P1 |
| Plateau detection | HIGH | MEDIUM | P1 |
| PR detection (with hygiene) | MEDIUM | MEDIUM | P1 |
| Training frequency | MEDIUM | LOW | P1 |
| Hevy body-measurement sync | HIGH | LOW | P1 |
| Weight trend (7/14/30d, %BW/wk) | HIGH | LOW | P1 |
| Period comparison (per-week normalized) | HIGH | MEDIUM | P1 |
| Freshness + coverage envelope | HIGH | LOW | P1 |
| `fitness_get_training_summary` | HIGH | MEDIUM | P1 |
| Recomposition status | MEDIUM | MEDIUM | P1 |
| Read-only MCP tools + bearer auth | HIGH | MEDIUM | P1 |
| Volume landmark bands (MEV/MAV/MRV) | HIGH | LOW | P2 |
| Muscle balance ratios | MEDIUM | LOW | P2 |
| RPE / stimulus-quality metrics | MEDIUM | LOW | P2 |
| Exercise substitution grouping | MEDIUM | MEDIUM | P2 |
| "What to progress next" ranking | MEDIUM | MEDIUM | P2 |
| Routine adherence | MEDIUM | MEDIUM | P3 |
| Session density trends | LOW | LOW | P3 |
| Activity / recovery / sleep analytics | HIGH | HIGH | P3 (M2) |
| Nutrition auto-import | MEDIUM | HIGH | P3 (M2) |

**Priority key:**
- P1: Must have for v1 launch
- P2: Should have, add once v1 is validated against real data
- P3: Future consideration / Milestone 2

---

## What the AI Coach Layer Actually Needs

The question "what should the data layer give an AI coach, as opposed to a UI?" has a fairly sharp answer, and it
is mostly the *inverse* of what a UI wants. A chart's job is to present evidence and let a human infer. An MCP
tool's job is to present the inference and attach the evidence — because the consumer is a system that is
excellent at reasoning over conclusions and unreliable at arithmetic over hundreds of rows.

The competitive point is worth stating plainly: the moat is not the model. It's what the model is allowed to see.
A general chatbot sees a paragraph the user typed; BRETT lets Claude see the real training history. Every design
decision below protects the fidelity of that view.

**1. Verdicts, not rows.**
Claude will miscount 400 sets and state the wrong total with total confidence. Return
`{status: "improving", slope_kg_per_week: 0.42, n_sessions: 9, window_weeks: 8}` — not nine sessions of raw sets
and an implied "you figure it out." Blueprint rule #11 (no calculation in MCP handlers) is the same principle
applied one layer down.

**2. Comparability computed server-side.**
Never ship two windows and expect correct delta arithmetic. Normalize to per-week rates, put both periods and the
computed delta in one payload. Raw totals across unequal windows are the single easiest way to produce a
confidently wrong coaching claim.

**3. Denominators and coverage, always.**
`weeks_covered`, `sessions_in_window`, `sets_excluded_warmup`, `rpe_coverage_pct`, `days_since_last_workout`.
Without these, "zero leg volume" is indistinguishable from "sync is stale" or "the window was 3 days long," and
the model will pick the most narratively satisfying interpretation.

**4. Uncertainty as a first-class field.**
`confidence: low`, `insufficient_data: true`, `reason: "only_2_sessions_in_window"`. An LLM given a number will
use it. An LLM given a number plus `confidence: low` will hedge appropriately. This is close to free and it is
the highest-value guardrail in the design.

**5. Thresholds and parameters echoed back.**
If plateau detection used a 4-week window and a 2% slope threshold, say so in the response. It lets Claude
*explain* ("I'm calling this a stall because there's been no e1RM improvement in 5 weeks") rather than assert, and
it lets the user push back on the rule instead of on the conclusion.

**6. Stable IDs plus fuzzy resolution, with the resolution echoed.**
Claude will pass `exercise="bench press"`. Resolve it, and return `resolved_exercise: {id, canonical_name,
matched_from: "bench press", alternatives: [...]}`. Silent mis-resolution ("I analyzed your bench" — it analyzed
dumbbell bench) is a nasty, invisible failure mode.

**7. Units, timezone, and week convention in the payload.**
`units: "kg"`, `timezone: "Asia/Jakarta"`, `week_start: "2026-08-17"`, `week_convention: "iso_monday"`. Never make
the model infer these. Internal storage is kg/m/kcal/s/cm per §41; state it rather than relying on convention.

**8. Freshness on every response.**
`last_synced_at` per source (§39) so Claude can say "as of your last sync, 40 minutes ago" and can proactively
flag stale data instead of silently reasoning over a 10-day-old picture.

**9. Token discipline as a design constraint, not an optimization.**
Tool definitions cost roughly 100–500 tokens each and are re-serialized every turn; large multi-server setups
routinely consume 30–50% of context before work begins. Practically: ~11–13 tools for v1, bounded defaults on
every list-returning tool, field filtering so responses carry only what's needed, and one composed summary tool
to collapse the common multi-call pattern.

**10. No prose, no narrative, no encouragement.**
Structured JSON only. The coaching voice, the framing, and the judgement live in the system prompt (§34) where
they can be revised without a deploy and where they can't contradict the numbers in the same response.

**11. Determinism.**
The same question next week must produce the same numbers for the same window. A coach that quietly contradicts
its own prior assessment is worse than no coach. This is why analytics must live outside MCP handlers, be pure
functions over the DB, and be unit-tested against known workouts (§42).

**12. `readOnlyHint: true` on every tool.**
Both a real safety property and a signal to the client. Reinforces §31 at the protocol level rather than only in
the implementation.

---

## Competitor Feature Analysis

| Feature | Hevy (Pro) | Strong (Premium) | Boostcamp | RP Hypertrophy | BRETT's Approach |
|---------|-----------|------------------|-----------|----------------|------------------|
| Volume charts | Yes — volume + muscle distribution chart, muscle heatmap | Yes — volume graphs, volume/frequency analytics | Yes — volume + muscle engagement | Yes — volume is the core model | JSON only, no charts. Claude renders if asked |
| Sets per muscle/week | Yes (coarse groups incl. single `shoulders`) | Yes | Yes | Yes, against MEV/MAV/MRV | Yes, with **delt-head split** + direct/indirect fractional split |
| Estimated 1RM | Limited | Yes — 1RM progression over time | Yes — e1RM curve from top sets | Used implicitly for load prescription | Yes, **gated** on modality + rep band + set position; `null` with a reason otherwise |
| PR detection | Yes — PRs over time (Pro) | Yes — PRs and progression | Yes — max weight/volume/reps, lifetime bests | Not the focus | Yes, all five classes, with warmup exclusion and rep-PR treated as a distinct class |
| RPE / RIR | Logged (`rpe` field, nullable) | Notably absent | Yes — free tier | Core to autoregulation | Derived RIR from RPE + **explicit coverage %** |
| Progression verdict ("am I progressing?") | No — chart only | No — chart only | No — chart only | Partially, via performance feedback | **Yes — an explicit classification.** This is the gap all four leave open |
| Plateau detection | No (blog article only) | No | No | Indirect, via mesocycle progression | **Yes — explicit, configurable window, confidence, threshold echoed** |
| Volume landmarks (MEV/MAV/MRV) | No | No | No | Yes — the whole product | Yes as **user-configured target bands**, honestly labelled as heuristics |
| Muscle balance ratios | Heatmap implies it, doesn't quantify | No | Muscle engagement view | Implicit in landmarks | **Yes — quantified push:pull, quad:ham, delt-head share** |
| Body measurements | Yes, incl. API access | Yes | Yes | Yes | Synced from Hevy in v1; HealthKit adds density in M2 |
| Programmatic/API access | Yes (Pro) — full REST API | CSV export only | No | No | **This is the entire premise** — normalized data behind an MCP surface |
| Conversational analysis | No | No | No | No | **The differentiator.** None of them let you ask a question in natural language against your own history |

**Reading of the landscape:** the four leading products converge almost exactly on the blueprint's table-stakes
list — volume, muscle-group volume, progression, PRs, frequency, body measurements. That convergence is strong
evidence the blueprint's §17–§23 analytics list is the right set; it is not an idiosyncratic choice.

Where they *all* stop is the same place: they render evidence and leave interpretation to the user. None returns
"improving / stable / declining." None detects plateaus. Hevy itself is reviewed as strong for logging but
"limited analytics that restrict meaningful progression" with no periodization support. That gap — evidence
without verdict — is precisely the gap an MCP-exposed analytics layer plus a reasoning model fills, and it's why
BRETT should not spend a single hour trying to out-chart Hevy.

---

## Sources

**Hevy API (HIGH confidence — live OpenAPI spec parsed 2026-08-23)**
- https://api.hevyapp.com/docs/ — endpoints, `MuscleGroup` enum, `CustomExerciseType` enum, `Set`/`Exercise`/`ExerciseTemplate`/`BodyMeasurement`/`Workout`/`ExerciseHistoryEntry` schemas, pagination limits (`/v1/workouts` pageSize max 10; `/v1/exercise_templates` max 100; `/v1/body_measurements` max 10). Note the API self-describes as unstable ("we make no guarantees that we won't completely change the structure") and Pro-only — reinforcing blueprint §6's provider-isolation requirement.

**Volume methodology (HIGH confidence — peer-reviewed meta-regression)**
- Pelland et al. 2025, *Sports Medicine*, DOI 10.1007/s40279-025-02344-w — 67 studies / 2,058 participants; fractional set counting (indirect at 0.5) had strongest evidential support (BF 9.48–54.84); hypertrophy dose-response ~70% efficiency at sets 11–18 and ~50% at 19+ with no identified ceiling; strength gains functionally plateau near ~4 fractional sets; frequency had negligible independent effect at matched volume. https://pubmed.ncbi.nlm.nih.gov/41343037/ · https://fitchef.com/studies/training-volume-sets-per-week-study/

**Competitor analytics (MEDIUM confidence — vendor pages + review sites)**
- https://www.hevyapp.com/features/sets-per-muscle-group-per-week/ · https://www.hevyapp.com/features/training-chart/ · https://www.hevyapp.com/features/gym-performance/
- https://repreturn.com/strong-app-review/ · https://www.strong.app/
- https://www.boostcamp.app/blogs/strong-vs-boostcamp-best-workout-app
- https://support.trainheroic.com/hc/en-us/sections/17996111205645-Analytics-Reporting-and-Activity
- https://strengthlab360.com/blogs/reviews-and-tests/hevy-workout-app-review-is-this-workout-tracker-enough-for-serious-athletes (Hevy analytics limitations)

**Volume landmarks & periodization (MEDIUM confidence — practitioner sources, explicitly heuristic)**
- https://rpstrength.com/blogs/articles/training-volume-landmarks-muscle-growth (MV/MEV/MAV/MRV definitions)
- https://arvo.guru/resources/methods/rp-training (mesocycle structure, deload cadence)
- Bell et al., *A Practical Approach to Deloading* — deloads averaged 6.4 ± 1.7 days every 5.6 ± 2.3 weeks. https://shura.shu.ac.uk/35313/3/Bell-APracticalApproach(AM).pdf

**1RM estimation limits (MEDIUM confidence — multiple concurring sources)**
- https://arvo.guru/resources/one-rep-max-formulas · https://maxcalculator.com/guides/1rm-formulas — Epley/Brzycki forms, ±5% at 2–10 reps, ±15–20% above 10, not recommended at 15+, degraded on isolation lifts and fatigued sets

**Plateau definition (MEDIUM confidence — practitioner consensus, no formal algorithm in literature)**
- https://www.hevyapp.com/gym-plateau/ · https://www.barbellmedicine.com/blog/training-expectations-understanding-stalls/ — ≥3–4 weeks of no measurable progress; 1–2 sessions is normal variation

**Recomposition rates (MEDIUM confidence — practitioner consensus)**
- https://www.thebodybuildingdietitians.com/blog/how-fast-should-you-bulk-or-cut-evidence-based-guidelines — ~0.25–0.5% BW/week gain; ~0.5–1% BW/week loss

**Muscle balance (MEDIUM confidence — peer-reviewed but different population)**
- https://pmc.ncbi.nlm.nih.gov/articles/PMC11359276/ — elite throwers showed 15% (F) / 22% (M) push>pull strength bias; caution generalizing to a recreational lifter

**ACWR / monotony validity (MEDIUM confidence — supports the anti-feature call)**
- https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12286412/ · https://www.frontiersin.org/journals/sports-and-active-living/articles/10.3389/fspor.2021.661200/full — developed for team field sports; predictive validity for injury actively contested

**MCP tool design & token economics (MEDIUM confidence — industry engineering write-ups)**
- https://pydantic.dev/articles/engineering-mcp-tools-for-token-efficiency · https://kansei-link.com/en/insights/mcp-tool-schema-design-guide-2026.html · https://www.mindstudio.ai/blog/optimize-mcp-server-token-usage — ~100–500 tokens per tool definition; 30–50% of context consumed by tool schemas in large setups; field filtering cuts payload tokens 80–90%; `readOnlyHint` annotations

**AI coaching grounding (MEDIUM confidence)**
- https://arxiv.org/pdf/2405.06061 (GPTCoach) · https://arxiv.org/pdf/2604.23830 (user tensions with AI-generated fitness feedback) · https://gainframe.app/blog/ai-fitness-coach-vs-chatgpt/ ("the moat is what the model is allowed to see")

---
*Feature research for: personal fitness analytics backend + read-only remote MCP coaching layer*
*Researched: 2026-08-23*
