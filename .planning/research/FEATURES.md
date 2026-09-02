# Feature Research

**Domain:** Personal fitness / body-recomposition data platform (v2.0 milestone: Apple Health ingestion, max-weight strength tracking, periodic reports, body measurements, training programs)
**Researched:** 2026-09-02
**Confidence:** HIGH for capability #1 (verified against vendor docs, vendor reference server source, two independent third-party implementations, **and the user's own 191 MB `export.xml`**); MEDIUM-HIGH for #2–#5 (industry convention + published coaching guidelines, which vary by source)

---

## Executive Note: Read This Before The Tables

Two findings dominate this milestone and are drawn from **the user's actual Apple Health export**
(`/Volumes/.../BRETT/export.xml`, HealthKit Export Version 14, `ExportDate 2026-08-26 10:09:33 +0700`,
191,257,897 bytes, 438,649 `<Record>` elements). These are not guesses — they are counts run against
the file.

### Finding A — Apple Health workouts are 97% Hevy duplicates

```
Workout elements by sourceName:      218  "Hevy"
                                       3  "Foodvisor"
                                       2  "Gymverse"
                                       1  "Zing"
Workout activity types:              221  HKWorkoutActivityTypeTraditionalStrengthTraining
                                       3  HKWorkoutActivityTypeOther
```

BRETT already has 327 workouts synced directly from the Hevy API. Ingesting Apple Health workouts —
from either `export.xml` or the Health Auto Export `workouts` array — would **double-count training
volume, sessions, and frequency** for the same sessions BRETT already owns at higher fidelity (Apple
Health has no per-set weight/rep data for strength training; Hevy does). The same duplication exists
for body data: all 8 `WaistCircumference` records and the early `BodyMass` records carry
`sourceName="Hevy"`, and BRETT already holds 125 `body_measurements` rows from the Hevy API.

**Consequence:** "ingest Apple Health workouts" is an anti-feature, not a feature. Apple Health's job
in BRETT is the data Hevy *cannot* provide (steps, active energy, sleep), not a second copy of the
data Hevy already provides.

### Finding B — The recovery/sleep data the milestone assumes does not exist

```
HKQuantityTypeIdentifierHeartRate                     0
HKQuantityTypeIdentifierRestingHeartRate              0
HKQuantityTypeIdentifierHeartRateVariabilitySDNN      0
HKQuantityTypeIdentifierVO2Max                        0
HKQuantityTypeIdentifierAppleExerciseTime             0
HKQuantityTypeIdentifierBodyFatPercentage             0
HKQuantityTypeIdentifierLeanBodyMass                  0
HKQuantityTypeIdentifierBodyMassIndex                 0

HKCategoryTypeIdentifierSleepAnalysis              2411   ALL value="HKCategoryValueSleepAnalysisInBed"
                                                          range 2022-03-20 .. 2024-11-30  (STOPPED ~21 months ago)
                                                          0 records in 2025, 0 in 2026
ActivitySummary                                    1443   2022-09-14 .. 2026-08-26
                                                          activeEnergyBurned populated
                                                          appleExerciseTime=0, appleStandHours=0 on every row
StepCount                                         48261   2022-03-10 .. 2026-08-26, sub-daily (5-10 min) buckets
                                                          two sourceNames ("Vegant's iPhone", "V's iPhone")
```

The user is **iPhone-only, no Apple Watch**. There is no heart-rate history of any kind, so resting
HR, HRV, VO2 max and Apple exercise time cannot be backfilled and will not arrive via Health Auto
Export either unless a Watch is purchased. Sleep exists only as undifferentiated `InBed` intervals
(no Core/REM/Deep/Asleep stages — those require a Watch) and stopped entirely on 2024-11-30.

**Consequence:** PROJECT.md's Active requirement "Health analytics extension: activity/sleep/recovery
trends" must be re-scoped to **activity only** (steps, active energy, distance, flights) plus an
optional sleep path that will be empty at launch. Building sleep-stage or HRV-based recovery
analytics now means shipping code with no data and no test fixtures except synthetic ones.

---

## Capability #1 — Apple Health Ingestion via Health Auto Export

### The Verified Payload Contract

**Sources (all HIGH confidence):** vendor help centre pages last updated 2026-08-23; the vendor's own
open-source reference server (`HealthyApps/health-auto-export-server`, TypeScript/Mongoose models read
directly); and two independent third-party implementations that agree on field names
(`meltforce/FreeReps` spec doc, `korosuke613/vitalbridge` metric table). Cross-checked against
`irvinlim/apple-health-ingester` Go structs for historical/version quirks.

#### Transport

| Property | Verified value |
|---|---|
| Method | `POST` only, to a user-entered full URL (`http://` or `https://`) |
| Content-Type | `application/json` for JSON, `multipart/form-data` for CSV (set automatically by the app) |
| Auth | **User-configured custom headers.** Docs name `X-API-Key: <key>` and `Authorization: Bearer <token>` explicitly. No OAuth, no signing, no HMAC. |
| Automatic headers | `automation-name`, `automation-id`, `automation-aggregation`, `automation-period`, `session-id` — confirmed in vendor docs **and** independently in the FreeReps spec |
| Export version | `Version 1` (legacy) / `Version 2` (current, recommended) — a per-automation setting |
| Batching | `Batch Requests` toggle (JSON only) splits one export across multiple POSTs |
| Payload size | Vendor warns "possibly several hundred megabytes"; the vendor's own reference server sets `express.json({ limit: '200mb' })` |
| Timeout | User-selectable request timeout in the app |
| Retry | **None documented.** Failures are recorded in in-app Activity Logs and that is all. |
| Requires | Premium subscription (API Export is a paid feature) |

#### Top-level shape

```json
{
  "data": {
    "metrics": [],
    "workouts": [],
    "symptoms": [],
    "ecg": [],
    "heartRateNotifications": [],
    "stateOfMind": [],
    "cycleTracking": [],
    "medications": []
  }
}
```

Only the arrays matching the automation's selected Data Type are present. A BRETT ingest endpoint must
treat every array as optional.

#### Metric shapes (four distinct ones — this is the normalizer's real job)

```json
// 1. Standard quantity — the overwhelming majority
{ "name": "step_count", "units": "count",
  "data": [ { "qty": 8500, "date": "2024-02-06 14:30:00 -0800", "source": "Apple Watch" } ] }

// 2. Heart rate — CAPITALIZED keys, no qty
{ "name": "heart_rate", "units": "bpm",
  "data": [ { "date": "2024-02-06 14:30:00 -0800", "Min": 65, "Avg": 72, "Max": 85 } ] }

// 3. Blood pressure — no qty
{ "name": "blood_pressure", "units": "mmHg",
  "data": [ { "date": "2024-02-06 14:30:00 -0800", "systolic": 120, "diastolic": 80 } ] }

// 4a. Sleep, Summarize Data = ON  (detect via presence of "totalSleep"; "date" is DATE-ONLY)
{ "name": "sleep_analysis", "units": "hr",
  "data": [ { "date": "2024-02-06", "totalSleep": 7.5, "asleep": 7.0, "core": 3.5,
              "deep": 1.5, "rem": 2.0,
              "sleepStart": "2024-02-05 23:00:00 -0800", "sleepEnd": "2024-02-06 06:30:00 -0800",
              "inBed": 8.0, "inBedStart": "...", "inBedEnd": "..." } ] }

// 4b. Sleep, Summarize Data = OFF  (detect via presence of "startDate")
{ "name": "sleep_analysis", "units": "hr",
  "data": [ { "startDate": "...", "endDate": "...", "qty": 0.5, "value": "Core" } ] }
//   value ∈ Awake | Asleep | In Bed | Core | REM | Deep | Unspecified
```

`source` is documented as "String, **when available**" and the vendor adds: *"On iOS 27+, `source` may
be omitted [for] cumulative and heart rate data due [to] iOS changes affecting performance."* Never
key on `source`.

#### Workouts Version 2

Required: `id` (String UUID), `name`, `start`, `end`, `duration` (seconds).
Optional, all as nested `{ "qty": n, "units": "..." }` objects: `activeEnergyBurned`, `totalEnergy`,
`intensity` (MET), `distance`, `speed`/`avgSpeed`/`maxSpeed`, `elevationUp`/`elevationDown`,
`temperature`, `humidity`, `stepCadence`, `flightsClimbed`, plus `location` (`Indoor|Outdoor|Pool|Open
Water`) and `isIndoor` (Boolean). Time-series arrays (`heartRateData`, `heartRateRecovery`,
`stepCount`, `activeEnergy`, …) carry `{date, qty|Min/Avg/Max, units, source?}` per point. `route[]`
carries lat/lon/altitude/course/speed + accuracies + `timestamp`. Version 1 has **no `id`** — a
critical difference for idempotency.

#### The three parsing landmines

1. **Timestamps are NOT ISO 8601.** Format is `yyyy-MM-dd HH:mm:ss Z`, e.g.
   `"2024-02-06 14:30:00 -0800"`. `datetime.fromisoformat` will reject it. Worse, the
   `irvinlim/apple-health-ingester` parser maintains a fallback list because the app emits 12-hour
   forms when the device has *Settings → General → Date & Time → 24-Hour Time* off, **and newer iOS
   versions insert a narrow no-break space (U+202F) before AM/PM**:
   Go layouts, written here with the narrow space ESCAPED so it survives copy-paste:
   `"2006-01-02 15:04:05 -0700"` (24h), `"2006-01-02 3:04:05 PM -0700"` (12h, ASCII space),
   and `"2006-01-02 3:04:05\u202fPM -0700"` (12h, U+202F NARROW NO-BREAK SPACE before AM/PM).
   Lowercase `pm` variants of the last two also occur. A parser that only handles the ASCII-space
   form will fail on newer iOS with a message that reads like a corrupt payload.
   Aggregated sleep's `date` is date-only (`"2024-02-06"`), a fifth format.
2. **Units follow the user's in-app Unit Preferences, not a fixed system.** Distance is `mi` *or*
   `km`; speed `mph` *or* `kmph`; temperature `degF` *or* `degC`; elevation `ft` *or* `m`; body mass
   `kg` *or* `lb`. BRETT's internal units are kg/m/kcal/s/cm, so the `units` field must be read and
   converted at the boundary. Hard-coding kg will silently corrupt weight trend if the phone's locale
   ever changes.
3. **Metric names are not a stable enum.** The vendor's own sources disagree:

   | Concept | Vendor server enum | Vendor help-centre prose | Community implementations |
   |---|---|---|---|
   | Body weight | `weight_body_mass` | `weight_&_body_mass` | `weight_body_mass` (×2, independent) |
   | VO2 max | `vo2max` | — | `vo2_max` (×2) |
   | Walking HR | `walking_heart_rate` | — | `walking_heart_rate_average` |

   Two independent third-party parsers plus the vendor's server code agree on `weight_body_mass`, so
   that is the working assumption — but the normalizer must be an **allowlist map with a logged
   unknown-name path**, never a strict enum that 500s. Ground truth is one Manual Export away.

#### Delivery reliability — the constraint that shapes the whole design

Vendor documentation, verbatim: *"Apps are not allowed to access health data while iPhone is locked.
Automations will only run during periods when your device is unlocked. This is a limitation imposed by
Apple which cannot be circumvented."* Plus: *"Background tasks will typically need to complete within
30 seconds"*; automations may not run under Low Power Mode, disabled Background App Refresh, or system
resource pressure; and there is **no retry**. Sync Cadence is "select a number and interval" but the
docs state plainly it "is not an exact schedule and does not guarantee that the app will open or run in
the background at that interval."

Two failure messages the vendor documents are worth designing against because they mean *nothing was
uploaded*: `"No health data was found in this date range, so nothing was uploaded."` and `"Health data
could not be fully read. The device may have locked during the export. Nothing was uploaded."`

### Table Stakes — Apple Health Ingestion

| Feature | Why Expected | Complexity | Notes / dependency |
|---------|--------------|------------|--------------------|
| `POST /api/v1/ingest/health-auto-export` webhook receiver | The only delivery mechanism HAE offers | LOW | New route under `app/api/routes/`. Must be excluded from the MCP OAuth path; it needs its own shared-secret header check |
| Static shared-secret header auth on the ingest route | HAE supports only fixed custom headers — no OAuth, no signing | LOW | `Authorization: Bearer <secret>` or `X-API-Key`. Compare with `hmac.compare_digest`. New Secret Manager entry alongside `MCP_AUTH_SECRET`. **Rate-limit it** — the existing token-bucket middleware currently exempts only `/health` and discovery |
| Idempotent upsert on `(source, metric, local_day)` | HAE re-sends overlapping windows on every `Default` / `Previous 7 Days` run, and has no dedup of its own | MEDIUM | Mirrors the Hevy sync's idempotency guarantee. `session-id` header gives per-request identity but **not** per-datapoint identity — do not use it as the dedup key |
| Multi-shape metric parser (qty / Min-Avg-Max / systolic-diastolic / sleep-aggregated / sleep-raw) | Four shapes exist in one array; a single Pydantic model cannot cover them | MEDIUM | Discriminate on `name` for `heart_rate` / `blood_pressure`, and on **key presence** for sleep (`totalSleep` ⇒ aggregated, `startDate` ⇒ raw) |
| Tolerant timestamp parser covering all five documented formats | `fromisoformat` fails on every one of them | LOW | Ordered format list with memoised last-success, exactly as the Go reference implementation does. **Include the U+202F variants** |
| Unit conversion at the boundary driven by the payload's `units` field | Payload units follow device locale; BRETT stores kg/cm/kcal/s | LOW | Extends the existing "convert at the application boundary only" constraint. Reject rather than guess on an unrecognised unit string |
| Unknown-metric tolerance (log + skip, never 500) | Metric names demonstrably vary across HAE versions and doc sources | LOW | A 500 makes HAE mark the run failed with no retry — data is lost permanently |
| `sync_state` rows for the new resources | Every analytics response already carries a per-resource `last_synced_at` envelope | LOW | **Direct reuse:** `SyncState` is keyed `(user_id, provider, resource)`. Add `provider='apple_health'` + resources. Then `FRESHNESS_RESOURCES_*` in `metadata.py` extends without structural change |
| Large-body handling | Vendor warns of "several hundred megabytes"; their own server allows 200 MB | MEDIUM | Cloud Run's request limit and BRETT's own body cap must be set deliberately. Instruct the user to enable **Batch Requests** and narrow metric selection — a config-side mitigation is far cheaper than a streaming parser |
| Ingest observability (accepted/skipped/unknown counts per request) | HAE gives the user only in-app Activity Logs; without server-side counts, silent partial ingestion is invisible | LOW | Structured log via existing `structlog` setup + correlation ID. **Deny-list applies:** never log raw health samples |

### Table Stakes — One-Time `export.xml` Backfill

| Feature | Why Expected | Complexity | Notes / dependency |
|---------|--------------|------------|--------------------|
| Streaming XML parse (`iterparse` + `elem.clear()`) | The real file is 191 MB / 438,649 records; `ElementTree.parse` will load the whole DOM | MEDIUM | Offline CLI (`app/cli.py`), never an HTTP endpoint. Not on the Cloud Run request path at all |
| **Source-aware exclusion** of `sourceName="Hevy"` records | 218/224 workouts, all 8 waist records and the early body-mass records are Hevy re-exports of data BRETT already owns | LOW-but-critical | This single filter is the difference between a correct backfill and permanently double-counted history |
| Daily aggregation of sub-daily quantity records in `Asia/Jakarta` | Step/energy records are 5–10 minute buckets; analytics is local-day grained | MEDIUM | **Reuses `app/analytics/rollup.py::resolve_window` timezone apparatus and `app/core/time.py::local_day`.** Do not introduce a second timezone path |
| Cross-source overlap handling for the two iPhone `sourceName`s | 40,452 records from "Vegant's iPhone" + 7,809 from "V's iPhone"; the Health app dedups in its UI, the raw XML does not | MEDIUM | Naive summation over an overlap window inflates step counts. Prefer-one-source-per-day is the cheap correct answer |
| Dry-run / idempotent re-run | A 191 MB import that half-succeeds must be safely repeatable | LOW | Same upsert path as the webhook; the constraint "never corrupt existing data on partial/failed sync" already applies |

### Differentiators — Apple Health

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Steps + active energy as **non-training activity load** in recomposition | Explains a stalled bulk (NEAT crept up) or a faster-than-target cut without touching the training data. This is genuinely new signal Hevy cannot supply | MEDIUM | Feeds `recomposition.py` as *context*, exactly as `training_volume` already does — **not** as a classifier input. `RecompositionResult` already has the precedent |
| Weight from non-Hevy sources (Foodvisor writes daily weigh-ins to Apple Health) | The most recent `BodyMass` records in the real export come from Foodvisor, not Hevy — genuinely additional weigh-ins that would densify the sparse trend | LOW | `BodyMeasurement.source` is `String(16)` with a `(user_id, source, measured_on)` unique key, so a third source slots in with **no migration**. But see the `_dedupe_by_day` warning under Dependencies |
| Ingest health-check / "last delivery" surfaced to Claude | Given no retry and unlock-gated background execution, silent stoppage is the *expected* failure mode, not an edge case | LOW | `SyncState.last_synced_at` for `apple_health` flows into the existing freshness envelope for free |

### Anti-Features — Apple Health

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Ingest the `data.workouts` array | It is right there in the payload and the app offers it | **97% of them are Hevy re-exports.** Double-counts sessions, volume, and frequency against data BRETT already has at per-set fidelity. Apple Health strength workouts carry no weights or reps at all | Select **Health Metrics only** in the HAE automation. Leave `workouts` unparsed and log a warning if it arrives |
| Sleep-stage (Core/REM/Deep) analytics | The payload schema has the fields | **Zero stage data exists.** All 2,411 sleep records are undifferentiated `InBed`, and they stop at 2024-11-30. Stages require an Apple Watch the user does not own | Parse and store `inBed` duration only. Ship stage columns nullable if you must, populate nothing, and do not build analytics on them |
| HRV / resting-HR "recovery score" | It is the headline feature of every recovery app | **Zero records of either type in 4.5 years of history**, and none will arrive without a Watch. A recovery score computed from nothing is a fabricated number in a health context | Drop "recovery" from the milestone. Re-scope the requirement to "activity trends". Revisit if a Watch appears |
| Ingest every one of the 150+ supported metrics | "Store it all, decide later" | The vendor explicitly warns this kills the automation: *"Even empty data types will have a performance impact"* and large exports get **killed by iOS**, producing zero deliveries | Allowlist ~6 metrics: `step_count`, `active_energy`, `walking_running_distance`, `flights_climbed`, `weight_body_mass`, `sleep_analysis` |
| Second-or-minute Time Grouping | Maximum fidelity | Vendor: fine-grained queries "can take a long time to run and clash with system limitations." BRETT's analytics is local-day grained — sub-daily rows are storage and parse cost for zero analytical gain | `Time Grouping = Day`, `Summarize Data = ON` |
| A generic "Apple Health" table storing arbitrary `(name, value, unit, ts)` | Future-proof, schema-free | Pushes every unit, dedup and shape decision into query time — where `bodyweight.py`'s Decimal discipline and the `insufficient_data` floors cannot reach it | Typed columns per ingested metric, same as `BodyMeasurement` does for its 17 |
| Ingesting nutrition (`dietary_*`) because the payload offers it | 95 `DietaryEnergyConsumed` records exist in the export; Foodvisor is actively writing | PROJECT.md Out of Scope is explicit: **no nutrition work in v2.0**, automatic or manual | Leave it. Revisit at the next milestone boundary |

---

## Capability #2 — Max-Weight-Lifted as the Primary Strength Signal

### What the ecosystem actually does

Hevy — the app the user trains in — already presents exactly this framing. Its exercise-performance
graph is metric-switchable across **Heaviest Weight, One Rep Max, Best Set Volume, Session Volume,
Total Reps**, and its *Set Records* chart deliberately shows *"the heaviest weight you've lifted for
that specific number of repetitions"* rather than a percentage of 1RM. Hevy distinguishes a **true**
1RM (an actual single) from a **projected** one. Most competing trackers (Strong, IronLedger,
1RM.fit) default to estimated 1RM because it enables percentage-based programming — which BRETT does
not do. Rippling that back: **max weight is the metric the user sees in his own app**, and estimated
1RM is a derived convenience for a use case BRETT has no requirement for.

The coaching-literature counterpart is "top set" tracking: the heaviest working set of a session,
trended over time, with reps recorded alongside so a load increase at equal-or-more reps reads as
progress and a load increase at fewer reps reads as ambiguous.

| Feature | Category | Complexity | Notes / dependency |
|---------|----------|------------|--------------------|
| Max-weight series per (exercise, local day) | Table stakes | MEDIUM | `progression.py` currently picks the day's headline set by **highest estimated 1RM** (its module docstring defends this explicitly: 60 kg×10 → e1RM 80.0 beats 70 kg×5 → 81.7). Switching the selector to max weight is a small code change with a **large behavioural blast radius** |
| Reps carried alongside every max-weight point | Table stakes | LOW | Without reps, 100 kg×1 and 100 kg×8 are the same point and a deload reads as maintenance. `ProgressionPoint` already reports weight, reps and set count |
| Max-weight trend classification (improving/stable/declining) | Table stakes | MEDIUM | Reuses the existing least-squares slope machinery — but the **dead-band must be re-derived**. The current 2% tolerance was tuned to Epley e1RM noise across a 5–12 rep spread; max weight is a step function moving in plate increments (often 2.5 kg ≈ 2–4% at this user's loads), so a 2% band would classify a single plate jump as a trend |
| Plateau detection on max weight | Table stakes | MEDIUM | Same window/threshold reporting contract as today. **Removes** `D-07a`'s "skip days with no e1RM-qualifying set" complication: 376/2,239 exercise-sessions (16.8%) currently produce no e1RM but *every* set has a weight, so coverage improves |
| e1RM retained as a labelled secondary field | Table stakes | LOW | PROJECT.md is explicit that e1RM "stays available… not removed". `PersonalRecordType.ESTIMATED_1RM` and `estimates.py`'s gating stay untouched |
| "Heaviest weight at N reps" record table | Differentiator | LOW | **Already built.** `RepsAtWeightRecord` exists in `schemas.py` precisely because "max reps at a given weight" is a list keyed by weight rather than a scalar. This is Hevy's Set Records chart, already in BRETT |
| Per-exercise "is this a real PR or a rep-scheme artefact" annotation | Differentiator | MEDIUM | The honest answer to max-weight's biggest weakness. A new top-set weight at 1 rep after weeks of 8s is not unambiguous progress |
| Dual-signal disagreement surfaced rather than hidden | Differentiator | LOW | The module already ships the precedent: PROG-02 and PROG-03 disagree on Overhead Press (improving over 11 weeks *and* plateaued over the last 4 sessions) and both return their window as a field. Max-weight vs e1RM disagreement is the same pattern, and it is exactly the case where a coach adds value |
| Deleting e1RM outright | **Anti-feature** | — | Contradicts PROJECT.md; discards the gating work in `estimates.py`; and e1RM is the better signal precisely when a lifter progresses by adding reps at fixed load — which is most accessory work |
| Auto-switching between max-weight and e1RM per exercise | **Anti-feature** | — | A metric that silently changes definition per exercise makes "am I progressing?" unanswerable and untestable. Pick one primary, report the other |
| Warm-up sets counting toward max weight | **Anti-feature** | — | Already handled: `records.py` excludes warm-ups. Keep that exclusion on the new path — a regression here is silent and plausible-looking |

**Blast-radius warning for the roadmap:** `recomposition.py` consumes `get_exercise_trends` and folds
28 exercises into a net score against a ±0.25 band, producing the whole-body recomposition verdict.
Changing the trend metric changes that verdict. The live-data baseline documented in the module (9
improving / 9 stable / 10 declining) is the regression fixture — capture the new distribution
deliberately rather than discovering it in production.

---

## Capability #3 — Weekly / Monthly Reports

### Convention from coaching practice

The industry-standard weekly check-in converges on four blocks — **training compliance / adherence**,
**energy & recovery**, **nutrition**, **body-weight trend** (near-universally a *7-day average*, never
a raw scale reading) — closed by **one clear focus for the coming week**. The most-cited framing
reduces this to three signals: *adherence* (did reality match the plan), *obstacles* (what got in the
way), *agency* (what the client will change). MacroFactor's analytics dashboard is the algorithmic
version: trend weight (weighted moving average), rate of change, adherence rate, and how those relate
to each other — deliberately never the raw scale number.

Weekly vs monthly is a **window difference, not a content difference**: weekly reports on adherence
and short-horizon noise; monthly reports on trend, PRs, measurement deltas, and program fit.

| Feature | Category | Complexity | Notes / dependency |
|---------|----------|------------|--------------------|
| `fitness_get_weekly_report` composing existing analytics | Table stakes | MEDIUM | Pure composition. Every input exists: `get_weekly_volume`, `get_training_frequency`, `get_exercise_trends`, `get_personal_records`, `get_body_weight_trend`, `get_recomposition_status` |
| `fitness_get_monthly_report` — same sections, longer window | Table stakes | LOW | Once weekly exists, monthly is a window parameter plus a different section emphasis. **Do not build two composers** |
| Period-over-period deltas in every section | Table stakes | LOW | **`compare_periods` already does per-week-normalised two-period comparison** — the hardest part is built |
| Explicit adherence/consistency section | Table stakes | LOW | Sessions completed vs the period's own baseline. `frequency.py` supplies overall and per-muscle frequency |
| Trend-based body-weight reporting, never raw scale | Table stakes | LOW | **Already correct.** `bodyweight.py` reports 7/14/30-day averages and a 4-week *smoothed* rate, and its docstring documents why the raw single-week delta (+0.72%/week from glycogen noise on live data) must never be classified against |
| Freshness + coverage envelope on the report | Table stakes | LOW | Non-negotiable for a composed payload: a report that silently mixes fresh volume with 52-day-stale weigh-ins is worse than no report. `FRESHNESS_RESOURCES_ALL` already exists |
| One-focus-for-next-period framing | Differentiator | LOW | This is **prompt work in `docs/coaching-instructions.md`, not backend work.** REQUIREMENTS.md excludes backend-generated coaching prose, and that exclusion should hold |
| A `period_label` / explicit window on the payload | Differentiator | LOW | Same argument the progression module already makes: a verdict without its window is a contradiction waiting to be narrated |
| Token-budgeted payload | Differentiator | MEDIUM | A report composing 6 analytics results is by far the largest MCP response BRETT will emit. The existing tools already return "compact, budgeted structured JSON" — the report needs its own explicit budget, likely with per-section caps |
| Backend cron that *pushes* reports | **Anti-feature** | — | MCP has no push channel; a backend scheduler would have nowhere to deliver. Already decided: Claude's own scheduled-tasks feature (verified to exist, with MCP connector access in scheduled runs) drives cadence |
| Backend-generated narrative prose | **Anti-feature** | — | Duplicates Claude's job, is untestable, and drifts from `coaching-instructions.md`. Return structured numbers; let Claude write |
| Storing generated report snapshots | **Anti-feature** | — | Introduces a write path and a staleness class for zero benefit — analytics is deterministic, so any report is exactly reproducible from its window. Would also breach the "one narrow write tool" constraint |
| A separate tool per report section | **Anti-feature** | — | 13 tools already; the point of a report is *one* call. Section tools already exist individually |

---

## Capability #4 — Body Measurements Beyond Weight

### Convention

Standard at-home protocols track **neck, chest, waist, hip, mid-arm, thigh, calf** plus height and
weight. Waist is treated as the single strongest indicator of central fat; limb circumferences (arm,
thigh, calf) as lean-mass proxies. The WHO waist protocol is midpoint between the lowest rib and the
iliac crest, at the end of a normal expiration, tape on skin. The dominant methodological message
across sources is that **consistency beats precision** — technique variance between measurements
swamps real change at short horizons, which is why measurement cadence is conventionally
weekly-to-monthly rather than daily, and why comparison is presented as period-over-period deltas
rather than as a smoothed daily curve.

BRETT's `body_measurements` table **already has all 17 columns**: `weight_kg`, `lean_mass_kg`,
`fat_percent`, and 14 circumferences including bilateral bicep/forearm/thigh/calf. Nothing writes
`source='manual'` yet, and `bodyweight.py` reads only `weight_kg`.

| Feature | Category | Complexity | Notes / dependency |
|---------|----------|------------|--------------------|
| Manual-entry write path | Table stakes | MEDIUM | **Zero schema work** — `source` is already `'hevy' \| 'manual'` with a `(user_id, source, measured_on)` unique key, and `external_id` is already nullable. The open question is *where the write lives*: an authenticated `/api/v1` endpoint, or the CLI. The MCP write budget is spent on program-switching |
| Trend + period comparison across circumference columns | Table stakes | MEDIUM | **Generalise, do not fork.** `get_body_weight_trend` is weight-specific in three places: `_dedupe_by_day` returns `dict[date, Decimal]`, `_window_average` takes that mapping, and `BodyWeightTrendResult` names weight fields. The right shape is a per-metric fold reusing the same window/floor logic |
| Per-metric `insufficient_data` floors | Table stakes | LOW | **Already the established pattern** — `build_measurement_coverage(window_days, measured_days, earliest_measurement_at)` is metric-agnostic today, and D-15's "each window has its own floor, and they are independent" generalises directly to "each metric has its own coverage" |
| No interpolation, no carry-forward | Table stakes | LOW | **Already decided (D-13) and even more important here.** Waist has 15 of 123 rows with a three-month gap; a filled line would fabricate a recomposition trend out of nothing |
| Sparse-metric honesty | Table stakes | LOW | Live counts: `fat_percent` 0/123, `lean_mass_kg` 0/123, `waist_cm` 15/123. `recomposition.py`'s docstring already states "Do not design a body-fat input into this module." Manual entry may change that — but only *after* rows exist |
| Waist-to-weight divergence as a recomposition signal | Differentiator | MEDIUM | The classic recomp read: waist down while weight flat/up. Genuinely valuable *and* directly aligned with Core Value — but strictly gated on the user actually logging waist. Do not enter the label matrix until data density supports it |
| Bilateral asymmetry surfacing (L vs R bicep/thigh/calf) | Differentiator | LOW | The schema uniquely supports it; almost no tracker reports it. Cheap once the generic per-metric fold exists |
| Longer default window for circumferences than for weight | Differentiator | LOW | Weight uses 7/14/30-day windows because weigh-ins are near-daily. Circumference is measured monthly at best — a 7-day waist window will be empty ~90% of the time and reads as a bug |
| Auto-deriving body fat % from circumferences (Navy formula) | **Anti-feature** | — | An estimate presented beside real measurements in a health context, with error bars wider than the change being tracked. `recomposition.py`'s existing `disclaimer` discipline exists precisely to avoid this class of claim |
| Progress photos | **Anti-feature** | — | Binary blobs, storage cost, and a serious privacy surface on a service exposed to an LLM connector. Not in scope; not a data problem BRETT solves |
| A `body_measurement_metrics` EAV table | **Anti-feature** | — | 17 typed `Numeric` columns already exist and carry the Decimal precision `bodyweight.py` depends on. EAV would trade that for `Numeric`-vs-`float` ambiguity and a join |

**One concrete trap:** `_dedupe_by_day` prefers `'manual'` over `'hevy'` (D-14) and treats a manual row
as authoritative *for the whole day*. Its docstring flags this as currently moot ("zero `'manual'` rows
exist"). The moment manual entry ships, a manual row recording **only a waist measurement** on a day
that also has a Hevy weigh-in will, under the current logic, suppress that day's weight —
`_dedupe_by_day` adds the manual row to `seen_manual` and skips later rows for that day. The
`weight_kg is None` guard drops the row from `by_day` but the day is still marked seen. **This is a
live latent bug that manual entry activates.**

---

## Capability #5 — Bulk / Cut / Recomp Program Modeling

### Convention: published rate bands

Sources disagree, and the disagreement is itself the finding. Rate bands are expressed as **% of
bodyweight per unit time**, which is what `bodyweight.py` already computes.

| Mode | Commonly published band | Notes |
|---|---|---|
| Cut | **0.5–1.0 % BW / week** loss (mainstream) | 0.25 %/wk for lean athletes in late contest prep; 1.5–2 %/wk tolerated at higher body fat or in a short mini-cut. Faster is associated with lean-mass loss and rebound |
| Lean bulk | **0.25–0.5 % BW / week** (Helms, novice) | Helms scales by training age: novice 0.25–0.5 %/wk, **intermediate 0.1–0.2 %/wk**, advanced 0.05–0.1 %/wk. Other evidence-based sources frame the whole thing as **0.5–1 % BW / month** (≈ 0.12–0.25 %/wk) |
| Recomp | **≈ 0 %, weight flat within a small band** | Intake within ~5–15 % of maintenance, protein 1.6–2.2 g/kg, 3–4 progressive sessions/week. Strength is the leading indicator; scale and tape lag |

BRETT's current hardcoded `WEIGHT_GAIN_TOO_FAST_PERCENT_PER_WEEK = 0.25` sits at the **top** of Helms'
novice band and roughly **2× the intermediate band** — defensible, but it is a novice-calibrated
threshold applied to a user with 327 logged workouts. Worth a deliberate decision when the constants
become data.

| Feature | Category | Complexity | Notes / dependency |
|---------|----------|------------|--------------------|
| `training_programs` as real rows with mode + thresholds | Table stakes | MEDIUM | Replaces five module-level constants in `recomposition.py`. New table + Alembic migration (0005+). `users` has **no `goal` column** today — deliberately so |
| An **active-program** concept with history | Table stakes | MEDIUM | "Am I progressing?" over a 12-week window can straddle a program switch. A single `users.active_program` FK loses that; a program row with `started_on`/`ended_on` keeps it. `RECOMP_LOOKBACK_WEEKS = 12` makes straddling the common case, not the edge case |
| Program-aware thresholds injected into the classifier | Table stakes | MEDIUM | `_weight_bucket()` reads three module constants; it must read the active program's values. **Keep `classify_recomposition` pure** — pass thresholds as arguments. That preserves the 24-combination table-driven test |
| Direction-aware labels per mode | Table stakes | MEDIUM | `_MATRIX_ROWS` encodes bulk semantics: `WEIGHT_LOSS_TOO_FAST` fires at −1.00 %/wk, which is *inside the normal cut band*. Under a cut, −0.8 %/wk is on target, not a safety warning. **The matrix needs a per-mode variant, or `RecompositionStatus` needs members the current 7-member enum lacks** |
| Confirm-gated MCP write tool (two-call: warn, then `confirm=true`) | Table stakes | MEDIUM | Already decided. This is the **only** write tool. Needs: idempotency, an audit trail, program-name validation, and a first-call response that states what changes. Note MCP tool annotations (`readOnlyHint`, `destructiveHint`) are *advisory* — the two-call contract is what actually enforces confirmation, which is exactly why it was chosen |
| Program echoed in every recomposition/report response | Table stakes | LOW | Without it, "you're gaining too fast" is unfalsifiable — the reader cannot tell which threshold produced it. `RecompositionResult.disclaimer` is the precedent for a required explanatory field |
| Program-scoped period comparison ("this cut vs last cut") | Differentiator | MEDIUM | Program history makes this nearly free once `compare_periods` accepts program-derived windows. High coaching value |
| Program-appropriate volume expectations | Differentiator | HIGH | Volume maintenance during a cut vs progressive overload during a bulk. Genuinely useful and genuinely hard to make deterministic — a strong candidate for **deferral**, and a phase that would need its own research |
| Transition guidance ("this cut has run 14 weeks") | Differentiator | MEDIUM | Duration is a fact BRETT can state from `started_on`. Whether to advise a diet break is coaching judgment → prompt layer, not backend |
| A general MCP write API | **Anti-feature** | — | PROJECT.md constrains v2.0 to exactly one narrow write tool. Every added write is new attack surface on a health dataset reachable through an LLM connector |
| Auto-detecting the program from the weight trend | **Anti-feature** | — | Circular: the program supplies the thresholds that classify the trend. Inferring it from the trend makes the verdict self-fulfilling and impossible to falsify |
| Calorie/macro targets on the program row | **Anti-feature** | — | Nutrition is explicitly Out of Scope for v2.0. Storing targets BRETT can never verify against intake produces confident numbers with no feedback loop |
| Program-driven changes to volume/frequency *analytics* | **Anti-feature** | — | Programs should change **interpretation** (thresholds, labels), never **measurement**. Hard sets are hard sets. Blurring this makes historical comparison across programs meaningless |
| Arbitrary user-defined program modes | **Anti-feature** | — | Three named modes were chosen. Free-form modes mean free-form thresholds, and `_LABEL_MATRIX`'s exhaustive-KeyError safety property depends on a closed set |

---

## Feature Dependencies

```
[HAE webhook receiver + shared-secret auth]
    └──requires──> [sync_state rows for provider='apple_health']
                       └──enables──> [freshness envelope covers Apple Health]

[export.xml backfill CLI]
    └──requires──> [same normalizer + upsert path as the webhook]
    └──requires──> [source-aware Hevy exclusion filter]   <-- HARD BLOCKER, not optional

[Activity analytics (steps / active energy)]
    └──requires──> [HAE ingestion]  AND  [local-day aggregation via rollup.py]
    └──enhances──> [recomposition status]   (as CONTEXT, never a classifier input)

[Max-weight progression]
    └──replaces──> [e1RM-keyed day-headline selection in progression.py]
    └──requires──> [re-derived dead-band; the 2% e1RM tolerance does NOT transfer]
    └──changes───> [get_exercise_trends]
                       └──changes──> [recomposition.py aggregate_progression]
                                          └──changes──> [fitness_get_recomposition_status output]

[Manual body-measurement entry]
    └──requires──> [a write path outside MCP]  (the MCP write budget is spent on programs)
    └──requires──> [_dedupe_by_day latent-bug fix]   <-- activated by the first manual row
    └──unblocks──> [multi-metric trend + comparison]
                       └──enables──> [waist-vs-weight divergence signal]

[Training programs as data]
    └──requires──> [training_programs table + migration]
    └──requires──> [threshold injection into classify_recomposition (keep it pure)]
    └──requires──> [per-mode label matrix variants]      <-- the underestimated piece
    └──requires──> [confirm-gated MCP write tool]
    └──enables───> [program-scoped period comparison]

[Weekly / monthly report tools]
    └──requires──> [everything above]   <-- reports COMPOSE; they must be LAST
    └──requires──> [an explicit token budget]

[Ingest workouts from Apple Health] ──CONFLICTS──> [Hevy sync]
     97% overlap by sourceName. Mutually exclusive; Hevy wins on fidelity.

[Sleep-stage / HRV recovery analytics] ──CONFLICTS──> [reality]
     0 records exist. No data path without an Apple Watch.
```

### Dependency Notes

- **Reports depend on everything, so they sequence last.** A report built before the max-weight switch
  reports the old strength metric; built before programs, it reports novice-bulk thresholds to a
  cutting user. Building reports early guarantees rewriting them.
- **Max-weight and programs both terminate in `recomposition.py`.** Max-weight changes the
  `progression_signal` axis; programs change the `weight_bucket` axis. Landing both in one phase means
  a verdict change with two simultaneous causes and no clean regression baseline. **Sequence them into
  separate phases.**
- **The Hevy exclusion filter blocks the backfill, not the webhook.** Going-forward HAE deliveries can
  be scoped to Health Metrics only (no `workouts` array selected at all). The 191 MB historical file
  has no such switch — the filter must exist in code before the first import runs.
- **Manual entry activates a dormant `_dedupe_by_day` defect.** Fix it in the same phase that ships the
  write path, not afterwards; the failure mode is a silently-suppressed weigh-in that produces a
  plausible-looking wrong average.

---

## MVP Definition

### Launch With (v2.0 core)

- [ ] HAE webhook receiver, shared-secret auth, rate-limited, idempotent upsert — the whole Apple Health thesis rests on it
- [ ] Multi-shape metric normalizer + tolerant timestamp parser + units conversion — without these the payload cannot be read at all
- [ ] Metric allowlist (`step_count`, `active_energy`, `walking_running_distance`, `flights_climbed`, `weight_body_mass`, `sleep_analysis` as `inBed` only)
- [ ] `sync_state` + freshness coverage for `apple_health` — the existing envelope contract must not develop a hole
- [ ] `export.xml` backfill CLI **with the `sourceName="Hevy"` exclusion filter** — one-shot, streaming, dry-runnable
- [ ] Max-weight-primary progression, trend and plateau, e1RM retained as labelled secondary — the milestone's headline requirement
- [ ] `training_programs` table + program-aware `recomposition.py` thresholds + confirm-gated write tool
- [ ] Manual body-measurement write path + the `_dedupe_by_day` fix
- [ ] Generic per-metric measurement trend/comparison across weight + circumference columns
- [ ] `fitness_get_weekly_report` / `fitness_get_monthly_report` (one composer, two windows)
- [ ] `docs/coaching-instructions.md` tightened toward concise answers, drift-guarded against the new tool registry

### Add After Validation (v2.x)

- [ ] Activity load (steps / active energy) as **context** in recomposition — trigger: 4+ weeks of clean daily HAE deliveries
- [ ] Waist-vs-weight divergence signal — trigger: ≥8 waist measurements spanning ≥8 weeks
- [ ] Program-scoped comparison ("this cut vs last cut") — trigger: two completed programs exist
- [ ] Bilateral asymmetry reporting — trigger: user actually logs L/R measurements
- [ ] Max-weight vs e1RM disagreement annotation — trigger: real disagreement observed on live data

### Future Consideration (v3+)

- [ ] Sleep-stage and HRV recovery analytics — **blocked on hardware**, not on effort
- [ ] Program-appropriate volume expectations — high complexity, needs its own research phase
- [ ] Nutrition of any kind — explicitly Out of Scope; the `dietary_*` metrics in the export are a temptation to resist
- [ ] Native iOS HealthKit app — superseded by HAE; only revisit on Apple Developer Program enrollment

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| HAE webhook + normalizer + idempotent upsert | HIGH | MEDIUM | P1 |
| Max-weight-primary progression | HIGH | MEDIUM | P1 |
| Training programs + confirm-gated switch tool | HIGH | MEDIUM | P1 |
| `export.xml` backfill **with Hevy exclusion** | MEDIUM | MEDIUM | P1 |
| Manual measurement entry + `_dedupe_by_day` fix | HIGH | MEDIUM | P1 |
| Multi-metric measurement trend/comparison | HIGH | MEDIUM | P1 |
| Weekly/monthly report tools | HIGH | MEDIUM | P1 (sequenced last) |
| Coaching-instructions tightening | MEDIUM | LOW | P1 |
| Activity (steps/energy) trends | MEDIUM | MEDIUM | P2 |
| Activity as recomposition context | MEDIUM | LOW | P2 |
| Waist-vs-weight divergence | HIGH | MEDIUM | P2 (data-gated) |
| Program-scoped comparison | MEDIUM | MEDIUM | P2 |
| Bilateral asymmetry | LOW | LOW | P3 |
| Sleep `inBed` duration trend | LOW | LOW | P3 (data-gated; 21 months stale) |
| Sleep stages / HRV / recovery score | — | — | **Cut — no data** |
| Apple Health workout ingestion | — | — | **Cut — 97% duplicate** |

---

## Competitor Feature Analysis

| Feature | Hevy | MacroFactor | Coaching platforms (TrueCoach / HubFit class) | BRETT's approach |
|---------|------|-------------|-----------------------------------------------|------------------|
| Strength progression metric | Switchable: Heaviest Weight, 1RM (true *or* projected), Best Set Volume, Session Volume, Total Reps. Set-record chart shows heaviest weight **per rep count**, not %1RM | n/a | e1RM, RPE-adjusted | **Max weight primary, e1RM secondary** — matches what the user already sees in Hevy, and `RepsAtWeightRecord` already implements Hevy's set-record concept |
| Body-weight reporting | Raw + charted | **Weighted moving average trend weight**; all decisions keyed off trend, never scale | 7-day average in check-ins | Already correct: 7/14/30-day averages + 4-week smoothed rate, raw week delta surfaced but never classified against |
| Periodic report | In-app stats screens | Weekly algorithmic check-in that adjusts targets | Structured weekly form, coach replies with adjustments + one focus | Structured MCP payload; **Claude writes the narrative**, backend ships only numbers |
| Body measurements | 17 fields, syncs to Apple Health | Weight only | Free-text + photos | Same 17 fields **already in schema**; adds manual entry + per-metric trend with independent coverage floors |
| Program modes | None | Goal-driven calorie targets | Coach sets phase manually | Three closed modes as data, per-mode thresholds, confirm-gated switch |
| Data honesty | Shows what exists | Explicit trend-vs-scale distinction | Coach judgment | **The differentiator:** freshness + coverage envelope + `insufficient_data` on every response, and a required disclaimer on interpretive verdicts |

BRETT's actual competitive position is not feature count — it is that every number carries its window,
its coverage, and its freshness, so an LLM narrating it cannot confidently overstate a thin dataset.
No consumer app does this because no consumer app has an LLM reading its output.

---

## Sources

**Health Auto Export — HIGH confidence**
- https://help.healthyapps.dev/en/health-auto-export/export-format/health-metrics/ — metric shapes, all four variants, `yyyy-MM-dd HH:mm:ss Z`, iOS 27 `source` omission (page dated 2026-08-23)
- https://help.healthyapps.dev/en/health-auto-export/export-format/workouts/ — Workouts V1 vs V2, every optional field, route schema (2026-08-23)
- https://help.healthyapps.dev/en/health-auto-export/export-format/ — top-level array list
- https://help.healthyapps.dev/en/health-auto-export/automations/rest-api/ — POST-only, custom headers, the six automatic headers, Export Version, Date Range options, Summarize Data, Time Grouping, Batch Requests, Sync Cadence, unlock requirement, 30 s background budget, payload-size warning, Activity Log error strings (2026-08-23)
- https://help.healthyapps.dev/en/health-auto-export/automations/ — best-effort background execution, iOS limiting factors
- https://help.healthyapps.dev/en/health-auto-export/getting-started/supported-data/ — supported metric confirmation
- `HealthyApps/health-auto-export-server` (vendor's own reference server) — `IngestData.ts`, `Metric.ts`, `Workout.ts`, `MetricName.ts`, `app.ts`, `middleware/auth.ts` read directly. Authoritative for exact field names, the 200 MB body limit, and the full metric-name enum

**Health Auto Export — MEDIUM confidence (independent corroboration)**
- `meltforce/FreeReps` `server/specs/hae-rest-api.md` — independently documents the six automatic headers and `weight_body_mass`
- `korosuke613/vitalbridge` README — independent metric-name table, confirms `weight_body_mass`, shows `vo2_max` / `walking_heart_rate_average` naming drift
- `irvinlim/apple-health-ingester` `pkg/healthautoexport/types.go` — the five timestamp formats including the U+202F narrow-NBSP variants, and the aggregated/unaggregated sleep discrimination strategy

**User's own data — HIGHEST confidence (primary evidence)**
- `/Volumes/Samsung SSD 990 EVO Plus Media 1/Documents/GitHub/BRETT/export.xml` — 191,257,897 bytes, HealthKit Export Version 14, `ExportDate 2026-08-26 10:09:33 +0700`. All counts in this document (438,649 Records; 224 Workouts of which 218 `sourceName="Hevy"`; 79 BodyMass; 8 WaistCircumference; 2,411 SleepAnalysis all `InBed`, 2022-03-20→2024-11-30; 48,261 StepCount 2022-03-10→2026-08-26; 1,443 ActivitySummary; zero HeartRate/RestingHeartRate/HRV/VO2Max/AppleExerciseTime/BodyFatPercentage/LeanBodyMass/BMI) were produced by running `grep -c` against this file on 2026-09-02

**BRETT codebase — HIGHEST confidence (read directly)**
- `backend/app/analytics/bodyweight.py`, `recomposition.py`, `progression.py`, `metadata.py`, `schemas.py`
- `backend/app/db/models/body.py`, `sync_state.py`, `user.py`
- `backend/app/mcp/tools/` (13-tool registry)

**Strength metric convention — MEDIUM confidence**
- https://help.hevyapp.com/hc/en-us/articles/35649367857175 and https://www.hevyapp.com/features/exercise-performance/ — Hevy's record types; set-record chart shows heaviest weight per rep count, not %1RM; true vs projected 1RM
- Comparative app reviews (JEFIT, Strong, 1RM.fit, IronLedger) — e1RM is the market default because it enables percentage-based programming, which BRETT does not do

**Rate bands — MEDIUM confidence (sources genuinely disagree; the disagreement is reported above)**
- https://www.thebodybuildingdietitians.com/blog/how-fast-should-you-bulk-or-cut-evidence-based-guidelines — cut 0.5–1 %/wk (0.25 lean, 1.5–2 high-BF); bulk 0.5–1 % **per month**
- Eric Helms' published recommendations, secondary reporting (Legion, MesoStrength, Bony to Beastly) — bulk 0.25–0.5 %/wk novice, 0.1–0.2 %/wk intermediate, 0.05–0.1 %/wk advanced. **LOW-MEDIUM** — secondary sources, not the primary text
- Recomp framing (RippedBody, RecompAI and similar) — flat weight, 5–15 % of maintenance, 1.6–2.2 g/kg protein, strength as leading indicator. **LOW-MEDIUM**

**Report structure — MEDIUM confidence**
- HubFit, Gymkee, CheckinHQ, Coached check-in templates — the four-block structure and the adherence/obstacles/agency framing
- https://help.macrofactorapp.com/en/articles/21-weight-trend and MacroFactor dashboard docs — trend weight as weighted moving average; every decision keyed off trend, never scale

**Body measurement protocol — MEDIUM-HIGH confidence**
- https://www.measurement-toolkit.org/anthropometry/objective-methods/simple-measures-circumference — WHO waist protocol, which circumferences proxy fat vs lean mass, tension-controlled tape
- SiPhox / BodySpec / NHS trust guides — the standard six-site home protocol; consistency-over-precision

**Report delivery mechanism — MEDIUM confidence**
- https://code.claude.com/docs/en/scheduled-tasks and https://support.claude.com/en/articles/13854387 — Claude scheduled tasks exist, are persistent, and scheduled runs have MCP connector access. Confirms PROJECT.md's decision that no BRETT-side scheduler is needed

---

## Gaps and Open Questions

1. **`weight_body_mass` vs `weight_&_body_mass` is not settled by documentation.** Three sources say the
   former, the vendor's own prose says the latter. **Resolvable in five minutes**: run one Manual
   Export from the app to a request-bin and read the real key. Do this before writing the normalizer.
2. **Which HAE metrics actually contain data on this device is unknown.** The `export.xml` evidence
   shows what *historically* exists, but HAE reads live HealthKit — and Foodvisor is actively writing
   `BodyMass` and `dietary_*`. The same Manual Export answers this.
3. **The max-weight dead-band has no empirical basis yet.** The current 2% was derived from Epley noise
   across a 5–12 rep spread. Max weight moves in plate increments. The correct band must be derived
   from the live plate-increment distribution — likely a phase-research task.
4. **Per-mode label-matrix design is under-specified.** `RecompositionStatus` has 7 members chosen for a
   bulk. Whether cut/recomp need new members or only re-mapped rows is a real design decision, not an
   implementation detail.
5. **Where the manual-measurement write lives is undecided.** MCP is spending its one write on program
   switching. An authenticated `/api/v1` endpoint and a CLI command are both viable and have different
   security surfaces.
6. **Cloud Run request-size limits vs HAE payload size unverified.** Vendor warns "several hundred
   megabytes." Whether Batch Requests plus a tight metric allowlist keeps every delivery under the
   platform limit needs measuring against a real export, not assuming.

---
*Feature research for: personal fitness / body-recomposition data platform, v2.0 milestone*
*Researched: 2026-09-02*
