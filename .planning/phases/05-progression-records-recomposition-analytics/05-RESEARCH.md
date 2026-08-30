# Phase 5: Progression, Records & Recomposition Analytics - Research

**Researched:** 2026-08-30
**Domain:** Deterministic strength/body-composition analytics over PostgreSQL (Python 3.13, SQLAlchemy 2.0 async, Pydantic 2.x)
**Confidence:** HIGH for stack, live-data ground truth, and SQL/Decimal mechanics (all executed against the live 327-workout database this session). MEDIUM for the three algorithm choices that CONTEXT.md left open (empirically validated against live data here, but not user-confirmed).

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Estimated 1RM (PROG-01)**
- **D-01:** Formula is **Epley**: `1RM = weight × (1 + reps/30)`. Chosen over Brzycki (which needs a hard rep cap regardless, since its denominator `37 − reps` goes negative above 36 reps) and over an average-of-both approach (added complexity for marginal accuracy gain at typical rep ranges). Use it consistently and label every value as an estimate, per blueprint §19.
- **D-02:** The estimate is only trusted for **≤12 reps**. Above that, return `null` with an explicit reason rather than a number that looks real but isn't — most 1RM formulas' error grows fast past ~12 reps as fatigue/form breakdown stops being proportional to load.
- **D-03:** The estimate is only computed for **`exercise_type == 'weight_reps'`** (7167 of 7984 live sets). All other modalities (`bodyweight_weighted` 270, `reps_only` 503, `short_distance_weight`/`duration`/etc. ~40) return `null` with a reason — `bodyweight_weighted` was explicitly considered (joining the nearest `body_measurements.weight_kg` by date to estimate total load) and rejected: it would stack an interpolated-bodyweight guess under the 1RM estimate, and bodyweight isn't tracked per-workout, only via separate dated rows.
- **D-04:** When a session has multiple sets of the same exercise, the date's progression-series entry (weight/reps/estimated_1rm/volume) is drawn from **the set with the highest estimated 1RM that day** — not simply the heaviest weight, since a lighter set at more reps can imply more strength under Epley. This also directly informs PROG-04's PR detection: PRs are found by scanning individual qualifying sets, not by first collapsing to one per-date value.

**Trend Classification & Plateau Detection (PROG-02, PROG-03)**
- **D-05:** PROG-02 requires **at least 4 weeks** of data for a given exercise before committing to `improving` / `stable` / `declining`. Below that threshold, the verdict is `unclear` — matches blueprint §20's "do not classify progression based on a single workout," scaled to a concrete minimum.
- **D-06 (revised 2026-08-30):** PROG-03's plateau window is **adaptive session count, bounded by a calendar floor**: **4 qualifying sessions of that exercise AND at least 3 weeks elapsed** since the streak began — whichever requires more evidence. Pure session-count adaptivity (the original D-06) was too permissive for high-frequency exercises: 4 sessions of a bench press trained 3×/week is only ~9–13 days, far below blueprint §21's own explicit "3–6 weeks" floor and squarely inside the "normal day-to-day fluctuation" range §21 warns against. The floor fixes that while still letting low-frequency accessory exercises take longer than 3 weeks to accumulate 4 qualifying sessions, exactly as "depending on... training frequency" intends.
- **D-07 (revised 2026-08-30):** A session **breaks** the plateau streak only if its estimated 1RM exceeds `historical_best × 1.02` (a 2% tolerance) — not any epsilon increase over the strict historical maximum. Named module-level constant, same pattern as Phase 4's `INSUFFICIENT_DATA_SESSION_THRESHOLD`: `PLATEAU_IMPROVEMENT_TOLERANCE = Decimal("0.02")`. A strict "any new max" rule (the original D-07) has no noise tolerance: a lifter clearly trending up but bouncing within 1% of their peak (sleep, RPE variance, normal session-to-session fluctuation) would get flagged as "no progress" purely on the exact-max test — precisely the false positive §21 warns against. This still reuses PROG-01's 1RM estimate (D-01–D-04) as the single "are you stronger" measure for the whole phase, only with a tolerance band instead of a bare `>` comparison.
- **D-07a (new 2026-08-30):** Sessions with a `null` estimated 1RM (the D-02 rep-range gate or the D-03 modality gate) are **skipped** when evaluating the plateau streak — they neither extend nor break it. Without this, anyone periodizing rep ranges (a deload week, 5/3/1-style waves, a higher-rep accessory day) would have those sessions silently read as "no PR," falsely inflating the plateau streak purely because that day's modality/rep-range made an estimate untrustworthy, not because training stalled.
- **D-07b (new 2026-08-30):** Every plateau result reports `recent_performance` (mean qualifying e1RM over the window), `historical_best`, the actual window/threshold used (session count *and* elapsed weeks, per D-06), and a `confidence` derived from the qualifying-session count (e.g. `low`/`medium`/`high`) — matching blueprint §21's return shape (`plateau_duration`/`recent_performance`/`historical_best`/`confidence`) instead of a bare boolean, which the original D-06/D-07 pair implied but didn't make explicit.

**Personal Records (PROG-04)**
- **D-08:** `'dropset'` and `'failure'` set types are **eligible for all PR types** (max weight, max reps at a weight, estimated-1RM PR, volume PR, rep PR) — only `'warmup'` is excluded. A to-failure set or a dropset's heaviest (first) portion is a real, hard effort; excluding it would hide legitimate PRs, and rep PRs in particular often happen ON a to-failure set by design.
- **D-09:** When two sets tie for a PR value (same max weight, or same max reps at that weight), the PR date recorded is **the earliest date the value was first reached** — "when did I first hit this" is the standard convention, not "when did I most recently reconfirm it."

**Body Weight Rolling Averages (BODY-01)**
- **D-13:** No interpolation or carry-forward for missing days. Each 7/14/30-day average is computed from **actual `measured_on` rows only** within the window. Inventing values for unweighed days would bias the number on an assumption (linear fill? last-known-value?) that isn't a real measurement, breaking the "deterministic, explainable" bar and hiding exactly the sparsity Claude needs to see.
- **D-14:** If both a `'hevy'` and a `'manual'` row exist for the same `measured_on` date (the natural key permits this), **prefer `'manual'`** — a manual entry represents a deliberate correction of that day's number. Moot today (only `'hevy'` rows exist; manual entry is a separate, unscoped phase), but locking it now prevents silently double-counting or averaging two same-day values once manual entry ships.
- **D-15:** Each window has its **own independent coverage floor**, mirroring Phase 4's D-05 "why 2 and not something else" reasoning but recalibrated from a per-session cadence to a per-day one: **7-day window needs ≥3 measured days, 14-day needs ≥5, 30-day needs ≥10**. Below its floor, that specific window's average is `null` with `insufficient_data=true` **for that window only** — a 30-day average can be reliable while the 7-day one isn't (or vice versa), same additive relationship as Phase 4's per-muscle `insufficient_data` sitting alongside the response-level flag rather than replacing it.
- **D-16:** The **weekly rate of change** BODY-01 reports is a **smoothed 4-week trend**, not a single most-recent-week delta: `(current_7d_avg − 7d_avg_from_4_weeks_ago) / 4`. Blueprint §25's own worked example (current 7-day avg vs. the immediately preceding 7-day avg) uses a single week-over-week comparison — dominated by water retention, sodium/carb intake, and glycogen swings, which alone can move a 70–80kg person's week-over-week number by several hundred grams, large enough to false-positive against BODY-02's tight percentage thresholds below. The 4-week window matches PROG-02's own "at least 4 weeks" minimum (D-05), keeping one "minimum meaningful window" concept across the phase. Gated on D-15: `null` + `insufficient_data=true` if either the current or the 4-weeks-ago 7-day average fails its coverage floor.
- **D-17:** The raw single most-recent-week delta (blueprint §25's literal example calculation) is **still surfaced**, as a clearly separate secondary field (e.g. `latest_week_delta_kg`) alongside the smoothed `trend_rate_percent_per_week` from D-16 — visible to Claude for context, but never the figure BODY-02 classifies against.
- Coverage type note for planning: `CoverageMetadata` (Phase 4) is workout-session-grained (`sessions_in_window`) and does not transfer verbatim to a day-grained weigh-in count — plan a sibling type with the same three-field philosophy (e.g. `measured_days_in_window`, `insufficient_data`, `earliest_measurement_at`) rather than overloading the existing one.

**Recomposition Status (BODY-02)**
- **Context (not a stored field):** the user's current goal is a **lean bulk** (slow weight gain, build muscle). No `users.goal` column exists and none is being added this phase — this shapes the threshold *values* chosen below, not new schema. If the goal changes later, these constants are the ones to revisit.
- **D-10:** "Too fast" thresholds are expressed as **percent of bodyweight per week**, not a fixed kg/week number — the standard fitness-coaching convention, since a fixed kg/week doesn't scale if bodyweight moves meaningfully over the tracked period.
- **D-11:** `weight_gain_too_fast` triggers above **+0.25%/week** of bodyweight — the stricter end of the typical lean-bulk guideline (~0.25–0.5%/week), chosen to keep gains lean rather than tolerate a faster, fattier surplus. **Revised 2026-08-30:** the target rate itself is unchanged, but it is now evaluated against **D-16's smoothed 4-week trend rate**, not a single-week delta — the numeric threshold was never the problem, measuring it off one noisy week was.
- **D-12:** `weight_loss_too_fast` triggers above **−1%/week** of bodyweight even though loss isn't the current goal — any loss that fast during a bulk is a clear signal something is off (undereating, illness, a tracking error) and is worth surfacing regardless of the stated goal. **Revised 2026-08-30:** same basis change as D-11 — evaluated against D-16's smoothed trend rate.

### Claude's Discretion

- ~~Exact "no progress" plateau metric wording/edge cases~~ — **resolved 2026-08-30** by D-07/D-07a/D-07b (2% tolerance band, null-e1RM sessions skipped, explicit `recent_performance`/`historical_best`/`confidence` reporting).
- ~~BODY-01 rolling-average mechanics with data gaps~~ — **resolved 2026-08-30** by D-13–D-17 (no interpolation, source tie-break, per-window coverage floors, smoothed 4-week trend rate plus a surfaced raw single-week delta).
- **How PROG-02's trend feeds BODY-02's label alongside the weight trend.** The user explicitly deferred this and it remains open. Lean toward: weight trend (now D-16's smoothed rate) sets the primary direction/threshold check (D-10–D-12), and training-progression trend (D-05's `improving`/`stable`/`declining`/`unclear`, aggregated across tracked exercises) refines the label within that — e.g. weight roughly stable + aggregate progression `improving` → `likely_recomp_progressing`; weight stable + `declining`/`unclear` → plain `weight_stable`. Confirm the exact aggregation rule (how many/which exercises' trends count) at plan/research time; it is not locked.
- **CMP-01 period comparison scope** — which specific metrics get compared (volume, frequency, tonnage, per-muscle, progression?) beyond "normalized per week so unequal-length windows don't mislead." Not discussed as its own gray area; Phase 4's D-03 (arbitrary start/end date range, built for exactly this) is the existing building block to reuse.
- Exact Pydantic schema shapes for all new return types (following `app/analytics/schemas.py`'s established `_AnalyticsModel` base, `Decimal`-not-`float`, deterministic-ordering conventions) — including the new `BodyMeasurementCoverage`-style sibling type flagged under BODY-01 above.
- Module/function naming and file layout within `app/analytics/` (e.g. `progression.py`, `records.py`, `recomposition.py` vs. fewer/more files) — no established split yet for this phase's five requirement areas.

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope. No new capabilities were proposed; every question was about how to implement PROG-01..04, CMP-01, BODY-01, BODY-02, all already scoped to this phase by ROADMAP.md.

**Also explicitly out of scope (from CONTEXT.md `<domain>`):** MCP tool exposure (Phase 6); manual body-measurement/nutrition entry; any change to Phase 4's volume/frequency or Phase 3's muscle-mapping engine; Apple Health / steps / calories signals in recomposition status (`RECOMP-02` is v2).
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| **PROG-01** | Exercise progression time series (weight, reps, sets, estimated 1RM only where modality + rep range make it meaningful — otherwise `null` with a reason) | Pattern 1 (`estimates.py` — Epley in Decimal, two gates, reason enum); Pattern 2 (`qualifying_set_rows()` — the one set-grain aggregate); Pitfall 1 (SQL integer division silently returns the bare weight); Ground Truth §"e1RM eligibility" (4802 of 7719 hard sets qualify — 62%; the null-with-reason path is the majority-adjacent case, not an edge case) |
| **PROG-02** | Trend classified `improving`/`stable`/`declining`/`unclear` from multiple sessions | Pattern 4 (exact-Decimal OLS slope over weekly best e1RM, normalized to %/week, `TREND_STABLE_BAND_PERCENT_PER_WEEK = 0.5` derived from D-07's 2% over D-05's 4 weeks); validated on live data — 9 improving / 9 stable / 10 declining over 28 classified exercises; Pitfall 6 (`regr_slope` returns `double precision` — banned) |
| **PROG-03** | Plateau detection with configurable multi-week window, returning window + threshold used | Pattern 5 (streak scan in Python over the D-04 per-session e1RM series); **Open Question 1** — D-06 defines the *minimum evidence* but not the *maximum lookback*; unbounded history flags 44/97 exercises with 200–400-day "plateaus" on live data; a bounded lookback fixes it. Pitfall 4 (streak-start seeding), Pitfall 5 (a plateau vs a detrained exercise) |
| **PROG-04** | PRs (max weight, max reps at a weight, estimated-1RM, volume, rep PR) with dates, excluding warm-ups | Pattern 6 (per-set scan over the same `qualifying_set_rows()`); D-08/D-09 encoded as an exclusion of `'warmup'` and an `ORDER BY value DESC, date ASC` first-reached rule; Ground Truth (max 12 distinct weights per exercise → the "max reps at a weight" list is bounded and safe to return whole) |
| **CMP-01** | Compare two periods with values normalized per week | Pattern 7 (reuse `frequency.sessions_per_week()` and `rollup.weekly_set_rows()` unsnapped, per Phase 4 D-03); **the metric scope recommendation** below; Pitfall 8 (never per-week-normalize a rate, an average or a maximum — only counts and sums) |
| **BODY-01** | Rolling 7/14/30-day body-weight averages + weekly rate of change | Pattern 8 (one 35-day fetch, four windows folded in Python; `MeasurementCoverage` sibling type); **Ground Truth §"BODY-01 is `null` on live data today"** — D-16's 4-weeks-ago anchor window is empty; the primary output is legitimately `insufficient_data` until ~2026-09-06 |
| **BODY-02** | Recomposition status from weight trend + training volume + progression, framed as decision support | Pattern 9 — **the recommended aggregation rule** (net-progression score with `RECOMP_PROGRESSION_NET_BAND = 0.25`, weight direction from D-16 with a `±0.1%/week` stable dead-band, full 5×3 label matrix); Ground Truth §"body composition fields are empty" (`fat_percent` 0/123, `lean_mass_kg` 0/123, `waist_cm` 15/123 — weight + training data is all there is) |
</phase_requirements>

---

## Summary

This phase adds **no new dependency, no migration and no new architectural tier**. Everything it needs is already installed, already modelled, and already has a working Phase 4 precedent to copy: `app/analytics/` is the home, `_AnalyticsModel` is the base class, `rollup.resolve_window()` is the window guard, `metadata.build_freshness()`/`build_coverage()` are the envelope, and `test_analytics_isolation.py` will auto-cover every new module via `rglob` with no edit. The real research value is therefore not "which library" — it is (a) what the live data actually supports, (b) which of the five arithmetic rules silently produce a plausible-but-wrong number, and (c) concrete, defensible resolutions for the three things CONTEXT.md left open.

**Three findings change the plan materially.** First, **`SUM`-style Epley written in SQL is silently catastrophic**: `weight * (1 + reps/30)` in PostgreSQL uses integer division, so `reps/30` is `0` for every rep count under 30 and the "estimated 1RM" is just the bare weight — verified, `10 * (1 + 8/30)` returns `10`. Compute Epley in exactly one Python function with `Decimal`. Second, **BODY-01's headline number is `null` on today's live data**: D-16 needs a 7-day average anchored 28 days back, and the window `[2026-07-26 … 2026-08-01]` contains zero weigh-ins (there is a 52-day gap between 2026-06-15 and 2026-08-06). The correct output today is `insufficient_data`, and it stays that way until roughly 2026-09-06. Plan tests around synthetic fixtures and make the insufficient path the *first-class* path, not an afterthought. Third, **PROG-03 as literally specified in D-06 has no maximum lookback**, and running the streak over unbounded history flags 44 of 97 exercises as plateaued with durations of 200–400 days — including exercises the user stopped training months ago. D-06 defines the minimum evidence; the plan must add a caller-supplied lookback window (PROG-01's `period` / PROG-03's "configurable multi-week window" already implies one), which brings the flag rate to a coach-readable 18/29 over 12 weeks with 27–75-day durations.

For the three open discretion items, this research recommends: **PROG-02 → exact-Decimal ordinary-least-squares slope** over the weekly best-e1RM series, normalized to percent-of-mean per week, with a ±0.5%/week dead-band derived from D-07's own 2% tolerance divided by D-05's own 4-week minimum (so the two requirements cannot contradict each other by construction). Validated on live data: a clean 9/9/10 split across improving/stable/declining, no degenerate clustering. **BODY-02 → a net-progression score** `(n_improving − n_declining) / n_classified` with a ±0.25 band and a 3-exercise minimum, crossed with a five-bucket weight-direction ladder into an explicit 5×3 label matrix — one constant, symmetric, exact in `Decimal`, and every input reported alongside the label. **CMP-01 → normalize only counts and sums** (sessions, hard sets, reps, tonnage, per-muscle set counts) per week, and never normalize a rate, an average or a maximum; carry `delta_percent = None` where the baseline is zero rather than raising or reporting infinity.

**Primary recommendation:** Build one set-grain aggregate (`rollup.qualifying_set_rows()`) and one pure Epley module (`analytics/estimates.py`); derive PROG-01, PROG-02, PROG-03 and PROG-04 from that single query by folding in Python, exactly as Phase 4 derived VOL-01/02/03 from `weekly_set_rows()`. Add a bounded, caller-supplied lookback to PROG-03. Treat `insufficient_data` as the expected BODY-01/BODY-02 answer on current data and test it as such.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Set-grain retrieval + window/tenant guards | Database (PostgreSQL) | — | 889 rows / 10 ms for a 12-week window, index-safe via `ix_workouts_user_id_start_time` `[VERIFIED: EXPLAIN ANALYZE on live DB]`. Counting/filtering is SQL's job (CLAUDE.md) |
| Epley estimate + eligibility gates (D-01–D-03) | Application (pure Python) | — | It is a business rule with two gates and a reason string. In SQL it is (a) silently wrong under integer division and (b) untestable without a container |
| Best-set-per-session selection (D-04) | Application (pure Python) | — | Selecting the max *of a derived value* requires the derived value; putting it in SQL drags Epley into SQL with it |
| Trend slope, plateau streak, PR scan | Application (pure Python) | — | Ordering-dependent state machines. Window-function SQL would work but is untestable without a container and puts `double precision` in the path (`regr_slope`) |
| Rolling body-weight averages | Application (pure Python) | Database (row fetch only) | ≤35 rows per call. D-14's source tie-break and D-15's per-window floors are business rules |
| Per-week normalization (CMP-01) | Application (pure Python) | — | `frequency.sessions_per_week()` already exists and was made public *specifically* for this (`frequency.py:63-79`) |
| Freshness / coverage envelope | Application (`analytics/metadata.py`) | Database | Already built (DQ-01/DQ-02); extend, don't duplicate |
| Tool exposure / wire schema | **Phase 6 (MCP)** | — | Out of scope. This phase's function signatures + Pydantic return types **are** the contract |

---

## Project Constraints (from CLAUDE.md)

Extracted directives the planner must verify compliance against. These carry the same authority as locked CONTEXT.md decisions.

| # | Directive | Where it bites in Phase 5 |
|---|-----------|---------------------------|
| C-1 | **No pandas / no numpy.** "Pushing weekly volume and per-muscle rollups into SQL + plain Python keeps them trivially unit-testable... A dataframe layer adds ~50 MB, cold-start time, and float-comparison flakiness" | The trend-slope regression is the one place a planner might reach for numpy. Do not. The OLS slope is 4 sums and one division — see Pattern 4 |
| C-2 | **`Decimal`, never `float`,** for every summed/averaged magnitude | e1RM estimates, rolling bodyweight averages, trend slopes, per-week normalized figures. Bans `regr_slope`/`corr`/`regr_r2` (all return `double precision`) |
| C-3 | **Analytics deterministic and testable** (blueprint rule #10) | Every returned collection needs a stated sort key. Every division needs an explicit quantum |
| C-4 | **MCP tools read-only in v1; never expose API keys, DB credentials or internal tokens** through responses or logs | `test_analytics_isolation.py` already bans `session.commit/flush/add` and `insert/update/delete` imports in `app/analytics/`. Every new module inherits this |
| C-5 | **Provider isolation** — Hevy logic confined to `backend/app/integrations/hevy/` | `app/analytics/` imports nothing from `app.integrations` and nothing from `app.mcp`. Statically enforced |
| C-6 | Ruff `S` (bandit) and `DTZ` enabled repo-wide, line length 100, target py313 | `S608` blocks f-string SQL — the timezone must stay a bound parameter via `func.timezone(tz, col)`. `DTZ` blocks `date.today()` / naive `datetime.now()`; use `app.core.time.utc_now()` + `local_day()` |
| C-7 | mypy `disallow_untyped_defs = true` | Every new function, including test helpers, needs full annotations |
| C-8 | **`testcontainers[postgres]`, never SQLite for tests** — "`date_trunc`, `generate_series`, window frames and `AT TIME ZONE` behave differently or not at all" | Integration tests use the existing session-scoped `postgres:18-alpine` container fixture |
| C-9 | GSD workflow enforcement — no direct repo edits outside a GSD command | Applies to execution, not research |

---

## Standard Stack

### Core — all already installed, nothing to add

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLAlchemy (asyncio) | 2.0.52 | The set-grain aggregate and the body-measurement fetch | Already the only DB access layer; Phase 4's `rollup.py` is the template `[VERIFIED: pyproject.toml]` |
| asyncpg | 0.31.0 | Driver | Returns PostgreSQL `numeric` as `decimal.Decimal` natively — the reason C-2 works end to end `[VERIFIED: Phase 4 rollup.py:261-263 relies on it]` |
| Pydantic | 2.13.4 | New return types on `_AnalyticsModel` | Phase 6 gets `outputSchema` + `structured_content` free `[VERIFIED: pyproject.toml]` |
| PostgreSQL | 18 (`postgres:18-alpine`) | Storage | `date_trunc` + `AT TIME ZONE` + `FILTER` already used; Phase 5 adds no new SQL feature `[VERIFIED: docker-compose.yml, live container]` |
| stdlib `decimal` | 3.13 | All arithmetic | Exact under `+`, `−`, `×`; only division is inexact (see Pitfall 7) |
| stdlib `datetime` / `zoneinfo` | 3.13 | Local-day windows | `app/core/time.py` already wraps everything needed |

### Supporting — test-side, all already installed

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest + pytest-asyncio | 9.1.1 / 1.4.0 | `asyncio_mode = "auto"` | Every test `[VERIFIED: pyproject.toml]` |
| testcontainers[postgres] | 4.15.0 | Real Postgres | Every integration test (C-8) |
| **time-machine** | 3.4.0 | Freeze the clock | **Load-bearing this phase.** BODY-01/BODY-02 anchor every window on "local today"; PROG-03's `plateau_duration` is measured to now. Without a frozen clock these tests rot within days `[VERIFIED: pyproject.toml]` |
| pytest-cov | 7.1.0 | Coverage | Optional |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Python OLS slope in `Decimal` | PostgreSQL `regr_slope(y, x)` | **Rejected.** Returns `double precision` even for `numeric` inputs `[VERIFIED: pg_typeof(regr_slope(1.0::numeric, 2.0::numeric)) = double precision]`. Violates C-2, is platform-dependent at the last bits, and forces a container for every trend test |
| Python OLS slope | First-half-mean vs second-half-mean threshold | Simpler and also exact, but discards ordering, is ill-defined for an odd number of weeks, and is dominated by whichever half contains the outlier. OLS uses every point and reports a slope Claude can quote |
| Python streak scan | SQL window function (`max(...) OVER (... ROWS UNBOUNDED PRECEDING)`) | Works (this research used it for analysis), but the streak rule involves D-07a's skip semantics and a tolerance band — pushing it into SQL makes it container-only to test and duplicates the warm-up/modality gates |
| Extending `rollup.py` | A new `app/analytics/exercise_rollup.py` | Rejected: `WARMUP_SET_TYPE`, `AnalyticsWindow`, `resolve_window()` and `build_window()`'s guards all live in `rollup.py`. A second module would need a second copy of the warm-up exclusion — the exact "two copies eventually disagree" failure this codebase repeatedly guards against |
| One `schemas.py` | Per-requirement schema modules | Rejected: Phase 4's `schemas.py` docstring states it is "declared here once and imported by every other module... the contract Phase 6 codes against." Splitting it moves the contract |

**Installation:**
```bash
# Nothing to install. Verified present in .venv on 2026-08-30:
#   sqlalchemy==2.0.52  asyncpg==0.31.0  pydantic==2.13.4  pytest==9.1.1
#   pytest-asyncio==1.4.0  testcontainers==4.15.0  time-machine==3.4.0
# A proposed new dependency in any Phase-5 plan is a design-drift signal.
```

---

## Live Data Ground Truth

Every figure below was executed against the live local database (`brett-db-1`, PostgreSQL 18, 327 workouts / 463 templates / 7,984 sets / 123 body measurements) on 2026-08-30. `[VERIFIED: live SQL execution]`

### e1RM eligibility — the null-with-reason path is not an edge case

| Population | Sets | Share |
|---|---:|---:|
| All non-warm-up ("hard") sets | 7,719 | 100% |
| ...of which `exercise_type = 'weight_reps'` | 6,939 | 89.9% |
| ...**and** `reps BETWEEN 1 AND 12` **and** `weight_kg IS NOT NULL` → **e1RM eligible (D-02+D-03)** | **4,802** | **62.2%** |
| `weight_reps` but `reps > 12` → null, reason `rep_range` | 2,137 | 27.7% |
| Non-`weight_reps` modality → null, reason `modality` | 780 | 10.1% |

Set-type distribution: `normal` 6,896 · `dropset` 823 · `warmup` 265 · `failure` **0** (declared but never sent). D-08 keeps all 823 dropsets eligible for PRs.

**Rep histogram for `weight_reps` hard sets** (the decision-relevant slice):

| reps | 1–4 | 5 | 6 | 7 | 8 | 9 | **10** | **11** | **12** | 13–14 | **15** | 16–19 | **20** | 21+ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| sets | 1,131 | 521 | 357 | 350 | 537 | 168 | **592** | **103** | **1,043** | 172 | **879** | 290 | **320** | 476 |

**This validates D-02's ≤12 against the literature's usual ≤10.** `reps = 12` is the single largest bucket in the whole dataset (1,043 sets). Tightening the gate to ≤10 would discard 1,146 sets — 23.9% of all eligible sets — and would blind the analytics to this user's most-programmed rep scheme. D-02's choice is more permissive than the published guidance (see State of the Art) and it is the right call *for this data*.

### Exercise-session grain — D-07a is load-bearing

| Metric | Value |
|---|---:|
| (workout × template) exercise-sessions, all time | 2,239 |
| ...with ≥1 e1RM-qualifying set | 1,863 (83.2%) |
| ...**with zero qualifying sets** → skipped by D-07a | **376 (16.8%)** |

Without D-07a, one exercise-session in six would be silently read as "no PR" and inflate every plateau streak.

### Plateau viability, and the unbounded-lookback problem

Streak algorithm as literally specified by D-06/D-07/D-07a (running best, 2% tolerance, ≥4 qualifying sessions since the last break, ≥21 days elapsed):

| Lookback | Templates with ≥4 qualifying sessions | Flagged PLATEAU | Reported durations |
|---|---:|---:|---|
| **Unbounded (all 17 months)** | 97 | **44 (45%)** | 27–**402 days** |
| **12 weeks (`2026-06-07 →`)** | 29 | 18 (62%) | 27–75 days |
| 12 weeks, running best **seeded** from pre-window history | 29 | 22 (76%) | 27–75 days |

The unbounded run reports e.g. *"Triceps Rope Pushdown: plateaued 402 days"* for an exercise last trained 2026-05-22, and *"Lateral Raise (Cable): 299 days"* for one last trained 2026-05-08. Both are literally true under D-06 and useless as coaching. **D-06 specifies the minimum evidence, not the maximum lookback — a bounded window is required and is not currently locked.** See Open Question 1.

The **calendar floor in D-06 is nearly inert on this data and costs nothing**: only 2 of 97 templates were blocked by "≥4 sessions but <21 days." This user trains each exercise ≈1×/week (top templates: 11 sessions over 74–75 days), so 4 sessions already spans ~4 weeks. Keep the floor — it is a free guard against a future frequency change, exactly as D-06 intends.

### PROG-02 feasibility

| Metric | Value |
|---|---:|
| Distinct weeks with training in the last 12 weeks | 13 |
| Templates trained in the last 12 weeks | 42 |
| ...with ≥4 distinct training weeks (D-05 gate) | 32 |
| ...classifiable by the recommended rule (≥4 weekly e1RM points) | 28 |

**Rep-range spread within a single exercise** (last 12 weeks, qualifying sets only) is `min 5 → max 12` with a standard deviation of 1.9–2.4 reps for every high-frequency template. Epley's multiplier ranges 1.167 (5 reps) to 1.400 (12 reps) — a 20% swing at constant true strength. D-04's "best e1RM of the day" absorbs most of it; D-07's 2% tolerance and D-05's 4-week minimum absorb the rest. This is the single largest noise source in PROG-02/PROG-03 and must be named in the shipped docstrings.

### PROG-04 cardinality

Distinct `weight_kg` values per template among hard sets: **mean 5.0, max 12**. The "max reps at a weight" PR list is therefore bounded at ~12 rows per exercise — safe to return in full without a cap (MCP-03's "never unbounded result sets" is satisfied by the data shape, but state the bound in the docstring).

### `rpe` is 100% empty

**0 of 7,719** hard sets carry an `rpe` value. Blueprint §19's progression-series field (`rir` in the blueprint, `rpe` in the live schema) has no data behind it. Recommendation: **omit RPE from PROG-01's return type entirely** rather than shipping a field that is `None` on every row for every user forever. If the planner prefers to include it for forward-compatibility, the docstring must say "0 of 7,719 live sets carry one" so nobody builds a feature on it.

### Body-composition fields are effectively empty — BODY-02 has weight + training only

| Field | Non-null rows / 123 |
|---|---|
| `weight_kg` | **123 / 123** |
| `waist_cm` | 15 / 123 (most recent 2026-08-25, previous 2026-05-19 — a 3-month gap) |
| `fat_percent` | **0 / 123** |
| `lean_mass_kg` | **0 / 123** |

Blueprint §24's "combines body weight, waist, body fat if available" resolves to **weight + training data**. Do not design BODY-02 around a body-fat input. Waist is too sparse (2 usable points in 6 months) to trend.

### BODY-01 returns `insufficient_data` on live data today — this is correct, not a bug

Weigh-ins per month: `2025-11` 1 · `2026-02` 6 · `2026-03` 20 · `2026-04` 14 · `2026-05` 8 · `2026-06` 2 · `2026-07` **0** · `2026-08` 19. There is a **52-day gap between 2026-06-15 and 2026-08-06**.

Evaluating D-13–D-17 with `today = 2026-08-29` (the latest measurement):

| Window | Range | Measured days | D-15 floor | Result |
|---|---|---:|---:|---|
| 7-day | 2026-08-23 → 08-29 | 6 | ≥3 | ✅ **65.650 kg** |
| 14-day | 2026-08-16 → 08-29 | 10 | ≥5 | ✅ **65.460 kg** |
| 30-day | 2026-07-31 → 08-29 | 19 | ≥10 | ✅ **65.221 kg** |
| **D-16 anchor** (7-day, 4 weeks back) | 2026-07-26 → 08-01 | **0** | ≥3 | ❌ **`null`, `insufficient_data = true`** |
| D-17 prior week (7-day, 1 week back) | 2026-08-16 → 08-22 | 4 | ≥3 | ✅ 65.175 kg → `latest_week_delta_kg = +0.475` |

**Consequences the planner must design for:**
1. `trend_rate_percent_per_week` is `null` today → **BODY-02 returns `insufficient_data` today**, by D-11/D-12's revised basis.
2. The earliest date the D-16 anchor clears its floor is ≈ **2026-09-06** (anchor window `2026-08-03 → 08-09` holds 4 measurements: Aug 6, 7, 8, 9).
3. **Every BODY-01/BODY-02 test must use synthetic fixtures under `time-machine`.** A test written against live data would assert `null` today and break silently the week the data fills in.
4. D-17's raw delta *is* available today (+0.475 kg / week) — which is exactly why D-17 exists, and exactly why D-16 does not classify off it. If it were the classifier, `+0.475 kg` on 65.65 kg = **+0.72%/week**, nearly 3× D-11's threshold, from one week of glycogen noise.

For reference, the earliest *valid* 4-week comparison once data allows: 7-day avg ending 2026-08-09 = 64.775 kg (4 days) → `(65.650 − 64.775) / 4 = +0.219 kg/week` = **+0.333%/week** → `weight_gain_too_fast` under D-11. Plausible and actionable.

---

## Architecture Patterns

### System Architecture Diagram

```
                        ┌──────────────────────────────────────────────────┐
   caller               │  Phase 6 MCP tools  ·  CLI  ·  tests             │
   (Phase 6, not here)  │  owns the AsyncSession + the transaction          │
                        └──────────────────────┬───────────────────────────┘
                                               │ session (positional), everything else kw-only
                                               ▼
  ┌────────────────────────────────────────────────────────────────────────────────────┐
  │                            app/analytics/  (read-only, no commits)                  │
  │                                                                                     │
  │   PROG-01/02/03      PROG-04         CMP-01           BODY-01          BODY-02      │
  │   progression.py     records.py      comparison.py    bodyweight.py    recomposition│
  │        │                 │                │                │             .py │      │
  │        │                 │                │                │                 │      │
  │        └────────┬────────┘                │                │      ┌──────────┘      │
  │                 │                         │                │      │ (composes both) │
  │                 ▼                         ▼                │      │                 │
  │        ┌─────────────────┐      ┌───────────────────┐      │      │                 │
  │        │ estimates.py    │      │ frequency.py      │      │      │                 │
  │        │ PURE. Epley +   │      │ sessions_per_week │      │      │                 │
  │        │ D-02/D-03 gates │      │ (already public)  │      │      │                 │
  │        │ + reason enum   │      └───────────────────┘      │      │                 │
  │        └─────────────────┘                                 │      │                 │
  │                 ▲                         ▲                ▼      ▼                 │
  │                 │                         │        ┌──────────────────────┐         │
  │   ┌─────────────┴─────────────────────────┴──┐     │ measurement fetch    │         │
  │   │        rollup.py  (EXTENDED)             │     │ 35-day span, ONE     │         │
  │   │  resolve_window()  ← window + tz guards  │     │ query, D-14 dedupe   │         │
  │   │  weekly_set_rows() ← Phase 4, for CMP-01 │     │ + D-15 floors in     │         │
  │   │  qualifying_set_rows()  ← NEW, set grain │     │ Python               │         │
  │   └──────────────────────┬───────────────────┘     └──────────┬───────────┘         │
  │                          │                                     │                    │
  │   ┌──────────────────────┴─────────────────────────────────────┴──────────┐         │
  │   │   metadata.py (EXTENDED)  build_freshness · build_coverage            │         │
  │   │                       + build_measurement_coverage (NEW, day-grained) │         │
  │   └───────────────────────────────────────────────────────────────────────┘         │
  │                                        │                                            │
  │   schemas.py (EXTENDED) — every public return type, frozen _AnalyticsModel          │
  └────────────────────────────────────────┼────────────────────────────────────────────┘
                                           ▼
              ┌────────────────────────────────────────────────────────────┐
              │ PostgreSQL 18                                              │
              │  workouts ▸ workout_exercises ▸ workout_sets               │
              │  exercise_templates (exercise_type = the D-03 gate)        │
              │  body_measurements (measured_on = Date, weight_kg only)    │
              │  sync_state (workouts · exercise_templates ·               │
              │              body_measurements → DQ-01 freshness)          │
              └────────────────────────────────────────────────────────────┘

  DATA FLOW for a progression question:
    caller → progression.get_exercise_progression(session, user_id=, template=, start=, end=)
      → rollup.resolve_window()          [validate tz, clamp span, → UTC half-open bounds]
      → rollup.qualifying_set_rows()     [ONE indexed query, set grain, warm-ups excluded]
      → estimates.estimate_1rm(w, r, t)  [Decimal Epley or (None, reason)]  ← per set, in Python
      → fold to (local_date → best set)  [D-04: max by e1RM, tie → more reps]
      → PROG-01 series ─┬─ PROG-02 weekly-max → OLS slope → verdict
                        └─ PROG-03 streak scan → plateau verdict
      → metadata.build_freshness/build_coverage
      → frozen Pydantic result
```

### Recommended Project Structure

```
backend/app/analytics/
├── __init__.py          # UNCHANGED  (docstring already covers new modules)
├── schemas.py           # EXTENDED   — all new return types (one contract module)
├── metadata.py          # EXTENDED   — + FRESHNESS_RESOURCES_BODY, MeasurementCoverage builders
├── rollup.py            # EXTENDED   — + qualifying_set_rows() at set grain
├── volume.py            # UNCHANGED  (Phase 4)
├── frequency.py         # UNCHANGED  (Phase 4; sessions_per_week() reused by CMP-01)
├── estimates.py         # NEW  pure  — Epley + D-02/D-03 gates + reason enum. No session.
├── progression.py       # NEW        — PROG-01, PROG-02, PROG-03 (shared e1RM series)
├── records.py           # NEW        — PROG-04
├── comparison.py        # NEW        — CMP-01
├── bodyweight.py        # NEW        — BODY-01
└── recomposition.py     # NEW        — BODY-02 (composes bodyweight + progression)

backend/tests/
├── test_analytics_estimates.py      # NEW  unit, FAST suite (no container) — Epley + gates
├── test_analytics_progression.py    # NEW  integration — PROG-01/02/03
├── test_analytics_records.py        # NEW  integration — PROG-04
├── test_analytics_comparison.py     # NEW  integration — CMP-01
├── test_analytics_bodyweight.py     # NEW  integration + unit — BODY-01
├── test_analytics_recomposition.py  # NEW  integration — BODY-02
├── test_analytics_isolation.py      # UNCHANGED — rglob auto-covers every new module
└── conftest.py                      # EXTENDED — + a body_measurement builder on GoldenBuilder
```

**Why PROG-01/02/03 share one module.** All three consume the identical artefact: the per-(exercise, local date) best-qualifying-set series produced by D-04. Splitting them into three files means three importers of a private series builder or three copies of it. `progression.py` with one internal `_e1rm_series()` and three public functions is the honest shape. `records.py` is separate because PROG-04 works at *set* grain (D-04's last sentence explicitly says PRs are found by scanning individual sets, not the collapsed per-date series).

**Why `estimates.py` is separate and pure.** It takes no session, does no I/O, and holds D-01/D-02/D-03 in ~30 lines. That makes it fast-suite testable (no container), which matters because it is the one function every other Phase-5 number depends on. Same rationale as `frequency.sessions_per_week()` being public and pure.

**Why `rollup.py` is extended rather than joined by a sibling.** `WARMUP_SET_TYPE`, `AnalyticsWindow`, `build_window()`'s span clamp and timezone validation, and `resolve_window()`'s `users.timezone` read all live there. A second module would need a second warm-up exclusion — the failure mode `rollup.py`'s own docstring warns about.

---

### Pattern 1: Epley in one pure Python function (PROG-01 / D-01–D-03)

```python
# backend/app/analytics/estimates.py
# Source: D-01/D-02/D-03; formula per Epley (1985), the industry-standard linear model.
# Gate values verified against live data: 4,802 of 7,719 hard sets qualify (62.2%).

from decimal import Decimal
from enum import StrEnum

# D-02. Epley's error grows fast past ~12 reps as fatigue stops being proportional to load.
# 12 rather than the literature's usual 10 is a DATA-DRIVEN choice: reps=12 is this account's
# single largest bucket (1,043 of 6,939 weight_reps hard sets) and reps=11 adds 103 more.
# Cutting at 10 would discard 23.9% of otherwise-eligible sets and blind the analytics to the
# user's most-programmed rep scheme.
MAX_TRUSTED_REPS = 12

# D-03. An EXACT-MATCH gate, not an allow-list to be extended. exercise.py's column comment
# warns against hardcoding a modality allow-list; this is the one place a modality string is
# compared at all, and it compares against exactly one value.
E1RM_EXERCISE_TYPE = "weight_reps"

# Quantized at the boundary, in ONE place, matching frequency.py's `_RATE_QUANTUM` rationale:
# 100 kg x 7 reps is 123.3333333333333333333333333 unquantized -- a number no coach reads and
# no test asserts on stably. Three decimals mirrors `workout_sets.weight_kg` Numeric(7, 3).
_E1RM_QUANTUM = Decimal("0.001")

_THIRTY = Decimal(30)


class NoEstimateReason(StrEnum):
    """Why `estimated_1rm` is None. A REASON, never a bare null -- PROG-01 requires it."""

    MODALITY = "modality_not_weight_reps"
    REP_RANGE = "reps_above_trusted_range"
    MISSING_OPERAND = "missing_weight_or_reps"


def estimate_1rm(
    *, weight_kg: Decimal | None, reps: int | None, exercise_type: str | None
) -> tuple[Decimal | None, NoEstimateReason | None]:
    """Epley estimate, or (None, reason). Exactly one of the two is populated.

    Order of the gates is deliberate: modality first, because "we do not estimate 1RM for
    bodyweight work at all" is a more useful explanation than "your reps were too high" for a
    set that would have failed both.

    NEVER write this in SQL. `weight_kg * (1 + reps / 30)` in PostgreSQL uses INTEGER division
    for `reps / 30`, yielding 0 for every rep count below 30, so the "estimate" silently
    becomes the bare weight. Verified: `SELECT 10 * (1 + 8/30)` returns `10`.
    """
    if exercise_type != E1RM_EXERCISE_TYPE:
        return None, NoEstimateReason.MODALITY
    if weight_kg is None or reps is None:
        return None, NoEstimateReason.MISSING_OPERAND
    if reps < 1 or reps > MAX_TRUSTED_REPS:
        return None, NoEstimateReason.REP_RANGE
    # Decimal throughout. `Decimal(reps) / _THIRTY` is inexact for most rep counts (7/30
    # repeats), but it is DETERMINISTIC under a fixed context and quantized immediately, so two
    # runs and two machines agree exactly.
    return (weight_kg * (Decimal(1) + Decimal(reps) / _THIRTY)).quantize(_E1RM_QUANTUM), None
```

**Worked values** `[VERIFIED: executed in the project venv]` — at 100.000 kg: 1 rep → `103.333`, 7 reps → `123.333`, 8 reps → `126.667`, 12 reps → `140.000`.

---

### Pattern 2: The one set-grain aggregate (serves PROG-01, 02, 03, 04)

```python
# Add to backend/app/analytics/rollup.py, beside weekly_set_rows().
# Source: verified by EXPLAIN (ANALYZE, BUFFERS) against the live database, PostgreSQL 18.
#   12-week window, all exercises: 889 rows, 10.07 ms, Bitmap Index Scan on
#   ix_workouts_user_id_start_time (40 of 327 workouts) -> Nested Loop into
#   uq_workout_sets_workout_exercise_id_set_index. All-time worst case: 7,719 rows, 17 ms.

@dataclass(frozen=True, slots=True)
class QualifyingSetRow:
    """One non-warm-up set, with the local day it belongs to and its modality.

    Set grain, NOT the (week, workout, template) grain of `SetRollupRow`. PROG-04 must scan
    individual sets (D-04), and D-04's "highest estimated 1RM that day" cannot be computed from
    a pre-aggregated row. This is a DIFFERENT question from Phase 4's, so it is a different
    aggregate -- do not try to serve both from one.

    `exercise_type` is carried so `estimates.estimate_1rm` never needs a second query, and so a
    None (template not synced locally) is naturally treated as "not weight_reps".
    """

    workout_id: uuid.UUID
    local_day: dt.date
    template_external_id: str
    exercise_type: str | None
    set_type: str
    weight_kg: Decimal | None
    reps: int | None


async def qualifying_set_rows(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    window: AnalyticsWindow,
    template_external_ids: Sequence[str] | None = None,
) -> list[QualifyingSetRow]:
    """Every non-warm-up set in the window, at set grain, ordered deterministically.

    There is deliberately no row cap, for the same reason `weekly_set_rows` has none: the guard
    is MAX_ANALYTICS_WINDOW_DAYS applied by `build_window` before anything is materialised. A
    silent truncation is a wrong answer; an over-wide request is a refused one.
    """
    local_day = cast(func.timezone(window.tz, Workout.start_time), Date)

    predicates = [
        # T-04-02: the tenant predicate leads. `user_id` is keyword-only with no default.
        Workout.user_id == user_id,
        # BARE column on both sides of the range -- this is what keeps
        # ix_workouts_user_id_start_time usable. Wrapping it in AT TIME ZONE was measured in
        # Phase 4 as a Seq Scan removing 299 of 327 rows.
        Workout.start_time >= window.utc_start,
        Workout.start_time < window.utc_end,
        # EXCLUSION of warmup, never an allow-list of 'normal'. 823 live dropset sets (D-08
        # keeps every one of them PR-eligible) and a `failure` type that is declared but has
        # never been sent would both be silently dropped by an allow-list.
        *_hard_set_predicates(),
    ]
    if template_external_ids is not None:
        predicates.append(
            WorkoutExercise.exercise_template_external_id.in_(list(template_external_ids))
        )

    stmt = (
        select(
            Workout.id,
            local_day.label("local_day"),
            WorkoutExercise.exercise_template_external_id.label("template_id"),
            ExerciseTemplate.exercise_type,
            WorkoutSet.set_type,
            WorkoutSet.weight_kg,
            WorkoutSet.reps,
        )
        .select_from(WorkoutSet)
        .join(WorkoutExercise, WorkoutExercise.id == WorkoutSet.workout_exercise_id)
        .join(Workout, Workout.id == WorkoutExercise.workout_id)
        # LEFT join: `workout_exercises.exercise_template_external_id` is a plain string, not an
        # FK (workout.py:117-121). A workout may reference a template that is not synced
        # locally, and an inner join would silently drop those sets from every Phase-5 number.
        # The tenant predicate is repeated on the template because Hevy's built-in template ids
        # are GLOBAL -- omitting it attaches another user's modality to this user's set.
        .outerjoin(
            ExerciseTemplate,
            and_(
                ExerciseTemplate.external_id
                == WorkoutExercise.exercise_template_external_id,
                ExerciseTemplate.user_id == user_id,
            ),
        )
        .where(*predicates)
        # Deterministic ordering is a repo-wide rule. `local_day` first because every fold in
        # this phase is chronological, and a plateau streak read out of order is a wrong answer
        # rather than a flaky one.
        .order_by(
            WorkoutExercise.exercise_template_external_id,
            local_day,
            Workout.id,
            WorkoutSet.set_index,
        )
    )
    ...
```

**Note on `cast(..., Date)`.** Phase 4's `rollup.py:206-211` documents that `date_trunc` over a timestamp-without-time-zone yields a *naive datetime*, which never compares equal to a `datetime.date` key. The same trap applies to `func.timezone(...)` — cast to `Date` explicitly or every Python-side dict keyed on the day will silently produce two entries per day.

---

### Pattern 3: The D-04 per-session series

```python
# backend/app/analytics/progression.py (internal)

def _best_set_per_day(
    rows: Sequence[QualifyingSetRow],
) -> dict[tuple[str, dt.date], SessionBest]:
    """D-04: one entry per (template, local day), from the set with the highest e1RM.

    Pure and synchronous -- no session, no I/O -- so D-04's tie-break and D-07a's skip
    semantics are unit-testable with no container. Same split as Phase 4's `_fold_week_totals`.

    THE TIE-BREAK IS PART OF THE SPEC, not an implementation detail: at equal e1RM, prefer the
    set with MORE reps. Epley maps (60 kg x 10) and (66 kg x 5) to different values, but genuine
    ties happen constantly on machine stacks with fixed increments. Preferring more reps is the
    conservative reading -- more total work for the same estimate.

    `sets`, `total_reps` and `volume_kg` accumulate over ALL hard sets that day (PROG-01 asks
    for weight, reps AND sets), while `best_*` describes only the selected set. Do not conflate
    them: "you did 4 sets" and "your best set was 100 kg x 5" are different facts.

    A day whose sets ALL fail the e1RM gates still produces an entry, with `best_e1rm = None`
    and a `reason`. D-07a's skip is applied by the PLATEAU scanner reading that None -- it is
    not applied here, because PROG-01 must still report the weight/reps/sets it saw.
    """
```

Return type sketch:

```python
@dataclass(frozen=True, slots=True)
class SessionBest:
    local_day: dt.date
    workout_id: uuid.UUID
    sets: int                       # all hard sets that day for this template
    total_reps: int | None
    volume_kg: Decimal | None       # sum(weight x reps) over sets with both operands
    tonnage_sets: int               # population the volume was computed over (Phase 4 rule)
    best_weight_kg: Decimal | None  # from the SELECTED set
    best_reps: int | None
    best_e1rm_kg: Decimal | None
    no_estimate_reason: NoEstimateReason | None
```

---

### Pattern 4: PROG-02 trend classification — exact-Decimal OLS slope **(RECOMMENDED — resolves a discretion item)**

```python
# backend/app/analytics/progression.py
# Source: ordinary least squares, closed form. Validated against the live database:
# 28 classifiable exercises over the last 12 weeks split 9 improving / 9 stable / 10 declining
# -- a well-spread distribution with no degenerate clustering at any boundary.

# D-05: fewer than 4 distinct TRAINING WEEKS for this exercise -> `unclear`, never a guess.
MIN_TREND_WEEKS = 4

# The dead-band, DERIVED rather than invented: D-07 tolerates a 2% e1RM band before calling a
# session an improvement, and D-05 sets 4 weeks as the minimum meaningful window. 2% / 4 weeks
# = 0.5%/week. Using the same underlying number means PROG-02 and PROG-03 cannot contradict
# each other by construction -- an exercise cannot be "improving" at a rate PROG-03's tolerance
# would refuse to call an improvement.
TREND_STABLE_BAND_PERCENT_PER_WEEK = Decimal("0.5")

_SLOPE_QUANTUM = Decimal("0.0001")
_PERCENT_QUANTUM = Decimal("0.01")


def _weekly_slope(points: Sequence[tuple[int, Decimal]]) -> Decimal | None:
    """Least-squares slope of y over x. EXACT until the final division.

    x is the week OFFSET from the window start (0, 1, 2, ...), not a compressed index over the
    weeks that happen to have data. A three-week training gap must widen the x-gap; compressing
    it would make a stalled month look like continuous progress.

    y is the week's BEST qualifying e1RM (max over that week's `SessionBest.best_e1rm_kg`), not
    the mean: the mean is dragged down by a deliberately light day, and PROG-02 is asking "is
    your ceiling rising", which is the same question PROG-03 asks with a different window.

    numerator and denominator are both exact -- x are ints, y are Decimals, and Decimal +/-/*
    are exact. The DENOMINATOR depends only on which week offsets are present, so it is an
    integer for every window: tests can assert an exact expected slope without a tolerance.

    numpy would do this in one call and is BANNED (CLAUDE.md: float comparison flakiness, ~50 MB,
    cold-start cost, for four sums).
    """
    n = len(points)
    if n < 2:
        return None
    sum_x = sum(x for x, _ in points)
    sum_y = sum((y for _, y in points), Decimal(0))
    sum_xy = sum((Decimal(x) * y for x, y in points), Decimal(0))
    sum_xx = sum(x * x for x, _ in points)
    denominator = Decimal(n * sum_xx - sum_x * sum_x)
    if denominator == 0:  # every point in the same week -- no slope exists
        return None
    return ((Decimal(n) * sum_xy - Decimal(sum_x) * sum_y) / denominator).quantize(_SLOPE_QUANTUM)


def classify_trend(points: Sequence[tuple[int, Decimal]]) -> tuple[TrendVerdict, Decimal | None]:
    """D-05 + the dead-band. Returns the verdict AND the normalized rate that produced it.

    Normalizing by the window MEAN (not by the first point) is what makes the band comparable
    across a 7 kg cable extension and a 160 kg leg press. Normalizing by the FIRST point would
    make the verdict depend on which week the window happened to start in.
    """
    if len({x for x, _ in points}) < MIN_TREND_WEEKS:
        return TrendVerdict.UNCLEAR, None
    slope = _weekly_slope(points)
    mean = sum((y for _, y in points), Decimal(0)) / Decimal(len(points))
    if slope is None or mean == 0:
        return TrendVerdict.UNCLEAR, None
    rate = (Decimal(100) * slope / mean).quantize(_PERCENT_QUANTUM)
    if rate >= TREND_STABLE_BAND_PERCENT_PER_WEEK:
        return TrendVerdict.IMPROVING, rate
    if rate <= -TREND_STABLE_BAND_PERCENT_PER_WEEK:
        return TrendVerdict.DECLINING, rate
    return TrendVerdict.STABLE, rate
```

**Live-data validation** `[VERIFIED: executed against the live database, 12-week window]` — a representative slice of the 28 classified exercises:

| Exercise | weeks | mean e1RM | %/week | verdict |
|---|---:|---:|---:|---|
| Face Pull | 7 | 32.50 | +3.46 | improving |
| Overhead Press (Barbell) | 11 | 45.92 | +1.51 | improving |
| Bench Press (Barbell) | 11 | 92.91 | +0.79 | improving |
| Romanian Deadlift (Barbell) | 9 | 84.78 | +0.48 | **stable** (just inside the band) |
| Leg Press Horizontal (Machine) | 9 | 166.78 | +0.02 | stable |
| Chest Fly (Machine) | 11 | 53.82 | −0.13 | stable |
| Landmine Row | 7 | 62.57 | −0.51 | **declining** (just outside) |
| Lat Pulldown (Cable) | 9 | 89.04 | −1.30 | declining |
| Rear Delt Reverse Fly (Machine) | 9 | 36.15 | −2.84 | declining |

Totals: **9 improving / 9 stable / 10 declining**. The band lands between real clusters rather than splitting one.

---

### Pattern 5: PROG-03 plateau streak scan

```python
# backend/app/analytics/progression.py
# D-06 / D-07 / D-07a / D-07b, executed as a Python state machine over the D-04 series.

PLATEAU_MIN_QUALIFYING_SESSIONS = 4              # D-06
PLATEAU_MIN_ELAPSED_DAYS = 21                    # D-06's 3-week calendar floor
PLATEAU_IMPROVEMENT_TOLERANCE = Decimal("0.02")  # D-07, the exact name CONTEXT.md specifies


def detect_plateau(series: Sequence[SessionBest], *, historical_best: Decimal | None) -> Plateau:
    """Scan forward. A session BREAKS the streak iff e1rm > running_best * (1 + tolerance).

    D-07a: sessions with `best_e1rm_kg is None` are SKIPPED entirely -- they neither extend nor
    break. On live data 376 of 2,239 exercise-sessions (16.8%) have no qualifying set, so
    without this a deload week or a high-rep accessory day silently inflates every streak.

    `running_best` is SEEDED from `historical_best` (all-time, computed before the window)
    rather than from the first in-window session. Otherwise truncating the lookback manufactures
    a fake "improvement" on the first session in the window -- it is an improvement over nothing,
    not over the lifter's actual history -- and understates every streak that started earlier.

    D-07b: the return carries `recent_performance` (mean qualifying e1RM over the streak),
    `historical_best`, the window ACTUALLY used (qualifying sessions AND elapsed days, both, per
    D-06) and a `confidence` from the qualifying-session count. Never a bare boolean: a lifter
    at 68% of their all-time best is DETRAINED, not plateaued, and only the pair of numbers
    makes the two distinguishable (Pitfall 5).
    """
```

Recommended `confidence` ladder, derived from the existing thresholds rather than invented:

| Qualifying sessions in the streak | `confidence` |
|---|---|
| < 4 (below D-06) | verdict is not "plateau" at all — `plateaued = false`, `confidence = "low"` |
| 4–5 | `low` |
| 6–9 | `medium` |
| ≥ 10 | `high` |

---

### Pattern 6: PROG-04 PR scan (per set, not per session)

```python
# backend/app/analytics/records.py
# D-08: only 'warmup' is excluded -- 'dropset' (823 live sets) and 'failure' (declared, never
# sent) are fully PR-eligible. Already handled upstream by `_hard_set_predicates()`.
# D-09: on a tie, the EARLIEST date wins -- "when did I first hit this".

# Every PR is `max(value)` then `min(date) where value == max`. Expressed as a single sort key
# so the tie-break cannot be forgotten at one of the five call sites:
#     key = (value, -date.toordinal())   ->  max() gives highest value, earliest date
```

Five PR types, each with its eligible population:

| PR type | Value | Eligible sets | Notes |
|---|---|---|---|
| Max weight | `weight_kg` | any hard set with `weight_kg IS NOT NULL` | Not gated on modality or reps — a heaviest-ever weight is a fact regardless of Epley |
| Max reps at a weight | `reps` per distinct `weight_kg` | as above, `reps IS NOT NULL` | ≤12 distinct weights per exercise on live data → return the whole list, sorted by `weight_kg` descending |
| Estimated-1RM PR | `estimate_1rm(...)` | **only** sets passing D-02+D-03 | The one PR type that inherits the gates. Sets with `None` are simply absent from this PR's population |
| Volume PR (session) | `sum(weight_kg × reps)` over the exercise-session | sets with both operands | Session grain, not set grain. Carry `tonnage_sets` so a partial computation is visible (Phase 4's rule) |
| Rep PR | `max(reps)` regardless of weight | `reps IS NOT NULL` | Deliberately un-gated on reps — this is the PR that lives at 20+ reps, and D-02's ≤12 must not touch it |

**Do not apply D-02's rep cap to the rep PR or the max-weight PR.** D-02 gates *the Epley estimate*, not the raw observation. On live data, applying it would hide the 320 sets at exactly 20 reps and every 15-rep set (879 of them).

---

### Pattern 7: CMP-01 per-week normalization **(RECOMMENDED SCOPE — resolves a discretion item)**

```python
# backend/app/analytics/comparison.py
# Reuse, do not re-derive: `frequency.sessions_per_week()` was made PUBLIC in Phase 4
# specifically for this (frequency.py:71-74 says so in its docstring).
```

**Window handling:** resolve both periods with `snap_to_weeks=False` (Phase 4's D-03). Frequency does not snap because it divides by the true window length, and that is precisely the property CMP-01 needs: a 4-week period against a 23-day period must both be expressed per week, not both widened to whole weeks.

**Recommended metric scope** — everything Phase 4 already computes, plus the phase-5 intensity figure:

| Metric | Grain | Per-week normalized? | Source |
|---|---|---|---|
| `sessions` | window | **yes** | `frequency.sessions_per_week()` |
| `hard_sets` | window | **yes** | `rollup.weekly_set_rows()` folded whole-window |
| `total_reps` | window | **yes** (`None`-preserving) | same |
| `tonnage_kg` + `tonnage_sets` | window | **yes** (`None`, never `0`) | same |
| `direct_sets` / `indirect_sets` / `weighted_sets` per muscle group | window × muscle | **yes** | `rollup.fold_window_by_muscle()` |
| `sessions` per exercise | window × exercise | **yes** | `rollup.fold_window_by_template()` |
| `best_e1rm_kg` per exercise | window × exercise | **NO — never divide** | `progression._best_set_per_day()` |

**The load-bearing rule:** per-week normalization applies to **counts and sums only**. A maximum (best e1RM), a rate (sessions/week — already normalized) and an average are all destroyed by dividing by weeks. CMP-01's requirement text says "values normalized per week so unequal-length windows don't produce misleading deltas"; dividing an e1RM by 4 produces a *more* misleading delta, not a less misleading one. Encode this structurally: give the comparison row type a `normalized: bool` field, or use two distinct row types (`RateComparison` vs `LevelComparison`), so a future metric cannot be added to the wrong bucket by accident.

**Delta shape:** each row carries `period_a_per_week`, `period_b_per_week`, `delta_per_week` and `delta_percent: Decimal | None`. `delta_percent` is `None` when the baseline is zero — a real case (an exercise trained in period B and not period A). Do not raise, do not report a sentinel, and do not silently substitute zero.

**Coverage:** report `CoverageMetadata` for **both** periods independently. A comparison where period A has 1 session is not a comparison, and a single response-level coverage block cannot express that.

---

### Pattern 8: BODY-01 rolling averages (D-13–D-17)

```python
# backend/app/analytics/bodyweight.py
# ONE query. Every window BODY-01 needs is inside [anchor - 34 days, anchor]:
#   current 7d   = [anchor-6,  anchor]
#   prior 7d     = [anchor-13, anchor-7]   (D-17's raw week-over-week delta)
#   current 14d  = [anchor-13, anchor]
#   current 30d  = [anchor-29, anchor]
#   D-16 anchor  = [anchor-34, anchor-28]  <- the widest reach back
# 35 rows maximum. Fetch once, fold five ways in Python.

# D-15's per-window floors. Independent by design: a 30-day average can be trustworthy while
# the 7-day one is not. Recalibrated from Phase 4's per-SESSION cadence to a per-DAY one.
MEASURED_DAY_FLOORS: Mapping[int, int] = {7: 3, 14: 5, 30: 10}

# D-16. Four weeks, matching D-05's "minimum meaningful window" so the phase carries one
# concept and not two.
TREND_ANCHOR_WEEKS = 4
```

**The anchor day is `local_day(utc_now(), user.timezone)`, never `date.today()`** — Ruff's `DTZ` rules ban the latter repo-wide, and `measured_on` is a calendar `Date` that must be compared in the user's local calendar (FOUND-03).

**D-14 dedupe, in Python:**
```python
# Prefer 'manual' over 'hevy' for the same measured_on. In Python rather than SQL DISTINCT ON
# because it is a business rule, and because the whole population is <= 35 rows. Moot today
# (0 manual rows exist) and locked now so it cannot silently become a double-count later.
by_day: dict[dt.date, BodyMeasurementRow] = {}
for row in rows:                      # ORDER BY measured_on, source  -> 'hevy' before 'manual'
    if row.source == MANUAL_SOURCE or row.measured_on not in by_day:
        by_day[row.measured_on] = row
```

**D-16 → percent/week.** D-16's formula yields **kg/week**; D-10–D-12's thresholds are **percent of bodyweight per week**. The conversion is not in CONTEXT.md and the planner must state it explicitly:

```
rate_kg_per_week      = (current_7d_avg - anchor_7d_avg) / TREND_ANCHOR_WEEKS
rate_percent_per_week = 100 * rate_kg_per_week / current_7d_avg
```

Denominator = **`current_7d_avg`**, not the anchor and not their mean. Rationale: "percent of bodyweight" naturally means percent of *present* bodyweight, it is the figure the user would compute by hand, and it is the more conservative choice while gaining (a larger denominator yields a smaller percentage, so the strict D-11 threshold is not tripped by the arithmetic alone). Both windows are already gated by D-15, so the denominator is never a low-confidence number when the rate exists at all.

Gating: `rate_*` is `None` with `insufficient_data = true` if **either** the current or the anchor 7-day window fails its floor (D-16 says so explicitly). D-17's `latest_week_delta_kg` has its own independent gate on the prior-week window.

**Recommended sibling coverage type** (the one CONTEXT.md flagged):

```python
class MeasurementCoverage(_AnalyticsModel):
    """DQ-02 for day-grained weigh-ins. A SIBLING of CoverageMetadata, not a subclass.

    `CoverageMetadata.sessions_in_window` counts WORKOUTS. Overloading it with a weigh-in count
    would make `insufficient_data` mean two different things in one response -- and BODY-02
    carries both, because it reads training data and body-weight data.
    """

    window_days: int
    measured_days_in_window: int
    insufficient_data: bool
    earliest_measurement_at: dt.date | None
```

`earliest_measurement_at` is a `dt.date`, not a `datetime` — `measured_on` is a calendar date (body.py's module docstring is explicit that inventing a time of day would be wrong).

Freshness: add `FRESHNESS_RESOURCES_BODY = (RESOURCE_BODY_MEASUREMENTS,)` to `metadata.py`. The constant already exists in `sync_state.SYNC_RESOURCES` `[VERIFIED: sync_state.py:25]`. BODY-02 needs **all three** resources (`workouts`, `exercise_templates`, `body_measurements`) because it reads both sides.

---

### Pattern 9: BODY-02 recomposition status **(RECOMMENDED RULE — resolves the explicitly-open discretion item)**

The one thing CONTEXT.md left genuinely unresolved. The recommendation below follows its stated lean (weight sets the direction, progression refines within it) and makes the aggregation rule concrete.

**Step 1 — aggregate the per-exercise trends into one net score.**

```python
# backend/app/analytics/recomposition.py

# A whole-body verdict must not turn on one accessory lift. Three is the smallest number for
# which a majority exists at all.
RECOMP_MIN_CLASSIFIED_EXERCISES = 3

# Symmetric, ONE constant, exact in Decimal (an integer ratio). "More than a quarter of your
# classified exercises are net-improving" is a sentence a coach can check by counting.
RECOMP_PROGRESSION_NET_BAND = Decimal("0.25")


def aggregate_progression(verdicts: Sequence[TrendVerdict]) -> AggregateProgression:
    """Net score over exercises PROG-02 was able to classify.

    `unclear` exercises are EXCLUDED from the denominator, not counted as `stable`. Counting
    them as stable would let a mostly-untracked training block dilute a real signal toward
    "stable" -- which is the one verdict that carries no information.

    Plurality was rejected: on live data (9 improving / 9 stable / 10 declining over 28
    exercises) plurality returns `declining` off a one-exercise margin. The net score returns
    `stable`, which is the honest reading of a 9-vs-10 split.
    """
    classified = [v for v in verdicts if v is not TrendVerdict.UNCLEAR]
    if len(classified) < RECOMP_MIN_CLASSIFIED_EXERCISES:
        return AggregateProgression(verdict=TrendVerdict.UNCLEAR, ...)
    improving = sum(1 for v in classified if v is TrendVerdict.IMPROVING)
    declining = sum(1 for v in classified if v is TrendVerdict.DECLINING)
    net = Decimal(improving - declining) / Decimal(len(classified))
    ...
```

`[VERIFIED against live data]`: 28 classified → improving 9, declining 10 → `net = -1/28 = -0.036` → aggregate **`stable`**. Correct and unsurprising.

**Step 2 — bucket the weight direction.** D-11 and D-12 give the two outer thresholds; a symmetric dead-band is needed for "stable", which is not a number CONTEXT.md supplies:

```python
WEIGHT_GAIN_TOO_FAST_PERCENT_PER_WEEK = Decimal("0.25")    # D-11
WEIGHT_LOSS_TOO_FAST_PERCENT_PER_WEEK = Decimal("-1.00")   # D-12
# The "stable" dead-band. NOT in CONTEXT.md -- see Assumptions Log A2. 0.1%/week is ~65 g/week
# at this user's bodyweight, comfortably below what a 7-day average can resolve from 3-6
# weigh-ins, and it is 1/10 of D-11's own threshold rather than an independent invention.
WEIGHT_STABLE_BAND_PERCENT_PER_WEEK = Decimal("0.10")
```

**Step 3 — the label matrix.** Rows are the weight bucket, columns are the aggregate progression. Only blueprint §26's seven enum values are used; no new value is introduced.

| Weight rate (D-16, %/week) | agg `improving` | agg `stable` | agg `declining` / `unclear` |
|---|---|---|---|
| `> +0.25` | `weight_gain_too_fast` | `weight_gain_too_fast` | `weight_gain_too_fast` |
| `+0.10 … +0.25` (on-target lean bulk) | `likely_muscle_gain` | `likely_muscle_gain` | `likely_muscle_gain` |
| `−0.10 … +0.10` (stable) | **`likely_recomp_progressing`** | `weight_stable` | `weight_stable` |
| `−1.00 … −0.10` (losing) | **`likely_recomp_progressing`** | `likely_fat_loss` | `likely_fat_loss` |
| `< −1.00` | `weight_loss_too_fast` | `weight_loss_too_fast` | `weight_loss_too_fast` |
| rate is `null` (D-15/D-16 gate) | `insufficient_data` | `insufficient_data` | `insufficient_data` |

Three properties worth defending to the user at plan time:

1. **The too-fast rows ignore progression deliberately.** D-11/D-12 are safety signals. "You are gaining 0.6%/week" needs saying whether or not your bench is going up — a fast gain with improving lifts is still a fattier bulk than intended.
2. **`likely_recomp_progressing` requires `improving`** and appears only in the stable and losing rows. That is textbook recomposition — weight flat or slightly down while strength rises — and matches the published tracking convention that strength is the *leading* indicator while tape and scale are lagging `[CITED: gainframe.app/blog/body-recomposition-tracker]`.
3. **The on-target-gain row returns `likely_muscle_gain` regardless of progression**, because §26's enum has no "gaining on target but lifts flat" member and mapping it to `weight_stable` would be factually false. The nuance is not lost: `progression_signal` (verdict + `improving`/`stable`/`declining`/`unclear` counts + net score) is a **required, always-populated** field of the result, so Claude reading `likely_muscle_gain` alongside `progression.aggregate = "declining"` can say "you're gaining at a lean-bulk rate but your lifts are going backwards — that gain is probably not muscle." That is the decision-support framing BODY-02 asks for. See Open Question 2.

**Step 4 — the disclaimer is structural, not prose.** REQUIREMENTS.md BODY-02 and blueprint §26 both demand "explicitly framed as decision support rather than a medical or diagnostic claim." Encode it as a literal field on the return type so it cannot be dropped by a Phase-6 serialization change:

```python
INTERPRETATION_DISCLAIMER = (
    "Decision support from body-weight trend and training progression only. "
    "Not a medical or diagnostic claim, and not a body-composition measurement."
)
```

`app/analytics/` producing this one fixed string is **not** a violation of the "no backend-generated coaching prose" exclusion in REQUIREMENTS.md — it is a constant safety label, not a generated insight. State that distinction in the module docstring so a future reviewer does not delete it.

---

### Anti-Patterns to Avoid

- **Writing Epley in SQL.** Integer division makes it silently return the bare weight. See Pitfall 1.
- **`regr_slope` / `corr` / `regr_r2` / `stddev` on floats.** `regr_slope` returns `double precision` even for `numeric` inputs `[VERIFIED]`. Violates C-2. (`avg()` and `stddev_samp()` over `numeric` *do* return `numeric` and are safe.)
- **Importing numpy or pandas.** Explicitly rejected by CLAUDE.md. Four sums and one division do not need a dataframe.
- **Applying D-02's ≤12 rep cap to the rep PR or the max-weight PR.** D-02 gates the *estimate*, not the observation.
- **A second copy of the warm-up exclusion.** Use `rollup._hard_set_predicates()`; `WARMUP_SET_TYPE` has exactly one definition.
- **Interpolating or carrying forward missing weigh-in days.** D-13 forbids it, and on this data it would fabricate a 52-day gap into a smooth line.
- **Collapsing all of BODY-02 to `insufficient_data` when progression is unclear.** Only a `null` weight rate does that; a weight-only verdict is still a valid answer.
- **Per-week-normalizing an e1RM, a rate or an average in CMP-01.** Counts and sums only.
- **Returning a bare boolean from PROG-03.** D-07b requires the four-field shape.
- **Inner-joining `exercise_templates`.** `workout_exercises.exercise_template_external_id` is a plain string, not an FK; an inner join silently drops sets for unsynced templates.
- **Snapping CMP-01's periods to whole weeks.** Frequency's D-03 rule applies: divide by the true length instead.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---|---|---|---|
| Local-day / local-week bucketing | `datetime` + `timedelta` arithmetic in the new modules | `app/core/time.py` (`local_day`, `local_day_bounds`, `local_range_bounds`, `local_week_start`, `local_week_spine`) | At UTC+7 every instant 17:00Z–24:00Z belongs to the *next* local day. A second copy of this arithmetic disagrees with Phase 4 on exactly the DST and week-boundary cases nobody tests |
| Window validation + timezone read | A new `start_day`/`end_day` guard | `rollup.resolve_window()` / `build_window()` | Already enforces `end < start`, `MAX_ANALYTICS_WINDOW_DAYS`, IANA timezone validation (ASVS V5) and the `users.timezone` read (FOUND-03) |
| Per-week rate arithmetic | `sessions / (days / 7)` inline | `frequency.sessions_per_week()` | Public and pure *specifically for CMP-01* (frequency.py:71-74). Handles the exact-Decimal division, the quantum and the zero-day guard |
| Warm-up exclusion | `set_type == 'normal'` | `rollup._hard_set_predicates()` / `WARMUP_SET_TYPE` | An allow-list drops 823 live dropsets (12% of hard sets) and would silently drop `failure` the day it first appears |
| Freshness / coverage envelope | New per-module metadata builders | `metadata.build_freshness()` / `build_coverage()` (+ one new day-grained sibling) | DQ-01 forbids `last_error`, `status` and both cursors from crossing this boundary; that filtering already exists in exactly one place |
| Muscle resolution (if CMP-01 compares per-muscle) | A join to `exercise_muscles` | `rollup.resolve_row_muscles()` → `resolver.effective_muscles_bulk()` | The override rule is REPLACEMENT, not merge. A join is byte-identical today (zero override rows) and starts lying the first time a mapping is corrected. `test_analytics_isolation.py` bans the ORM class names outright |
| Least-squares slope | numpy / statistics.linear_regression | ~8 lines of `Decimal` (Pattern 4) | `statistics.linear_regression` returns floats; numpy is banned; the closed form is exact until the final division and needs no dependency |
| Freezing time in tests | Hand-injected `now` parameters everywhere | `time-machine` 3.4.0 | Already installed. BODY-01/02 and PROG-03 are all anchored on "now"; a `now` parameter threaded through every signature is API pollution that Phase 6 then has to ignore |
| Building workout fixtures | Raw inserts per test | `conftest.py::golden_workout` (`GoldenBuilder`) | Flush-and-rollback, survives assertion failures, invisible to `test_migrations.py`'s separate-connection `count(*) == 1` assertion. **Extend it with a `body_measurement()` method** rather than writing a second builder |

**Key insight:** every one of the above already exists in this repo with a docstring explaining a bug it prevents. In a codebase this heavily commented, hand-rolling is not just duplication — it is a documented regression.

---

## Common Pitfalls

### Pitfall 1: `weight * (1 + reps/30)` in SQL silently returns the bare weight

**What goes wrong:** PostgreSQL's `integer / integer` is integer division. `reps / 30` is `0` for every rep count below 30, so the "estimated 1RM" equals the weight lifted.
**Verified:**
```sql
SELECT 10 * (1 + 8/30)          AS wrong;  -- 10          <- looks like a plausible weight
SELECT 10 * (1 + 8::numeric/30) AS right;  -- 12.666...   <- correct
```
**Why it happens:** the wrong version is syntactically valid, returns a number of the right magnitude and the right units, and every downstream comparison (`>`, `max`) still works. Nothing errors.
**How to avoid:** compute Epley in exactly one Python function (Pattern 1). If any SQL must ever do it, cast: `reps::numeric / 30`.
**Warning signs:** an e1RM equal to the weight for a multi-rep set; a plateau streak that never breaks; PROG-02 slope tracking weight exactly.

### Pitfall 2: PROG-03 with no maximum lookback reports 400-day plateaus

**What goes wrong:** D-06 specifies minimum evidence but no maximum window. Run over all 17 months of history, the streak scan flags **44 of 97 templates** with durations up to **402 days**, including exercises last trained three months ago `[VERIFIED: live SQL]`.
**Why it happens:** "no new e1RM PR since X" is unbounded by construction. An exercise abandoned after a peak stays "plateaued" forever.
**How to avoid:** give PROG-03 a caller-supplied lookback (PROG-01's `period` argument and the requirement's own "configurable multi-week window" both imply one). Default 12 weeks brings it to 18/29 flagged with 27–75-day durations. Seed the running best from all-time history so the truncation does not manufacture a fake improvement on the first in-window session (Pitfall 4).
**Warning signs:** any `plateau_duration_days` above ~120; any plateau reported for an exercise whose last session predates the window.

### Pitfall 3: PROG-02 and PROG-03 disagree, and both are right

**What goes wrong:** on live data, Overhead Press is `improving` (+1.51%/week over 11 weeks) **and** plateaued (4 qualifying sessions / 27 days since 2026-08-01). Triceps Pushdown is the same. Claude reading both will report a contradiction.
**Why it happens:** they answer different questions over different windows — "is the trend up across the whole window" vs "has the ceiling moved recently."
**How to avoid:** both return types must carry their window explicitly (PROG-03 already must, per PROG-03's requirement text and D-07b; make PROG-02 do the same — `window_start`, `window_end`, `weeks_with_data`). The derived dead-band (Pattern 4: 2% ÷ 4 weeks = 0.5%/week) makes them share one underlying tolerance, which is the structural half of the fix; explicit windows are the reporting half.
**Warning signs:** a Phase-6 tool that returns a trend verdict and a plateau flag without either window.

### Pitfall 4: Truncating the lookback manufactures a fake improvement

**What goes wrong:** if the running best is seeded from `NULL` and the first in-window session therefore "breaks" the streak, every streak restarts at the window edge. On live data this moved 6 exercises from a correct full-window plateau to a shorter, later streak start.
**Why it happens:** `prev_best IS NULL → breaks` reads as "improved over nothing."
**How to avoid:** compute `historical_best` over all history strictly before the window (a separate scalar query, or a wider fetch), and seed the scan with it. Then the first in-window session breaks only if it genuinely beats the lifter's real history.
**Warning signs:** `plateau_duration_days` that changes when the caller widens the lookback but the training did not change; a streak that always starts within a few days of the window start.

### Pitfall 5: A plateau and a detrained exercise look identical without both numbers

**What goes wrong:** live data, 12-week window — Leg Extension's `recent_performance` is **68.2%** of its `historical_best`; Rear Delt Reverse Fly is 73.8%; Bicep Curl 80.2%. Labelling any of these "plateaued" is misleading. The lifter is not stuck at their ceiling; they are training well below a ceiling set in a different block.
**Why it happens:** "no new PR" is true both for someone grinding at 99% of their best and for someone who deloaded to 68%.
**How to avoid:** D-07b's `recent_performance` + `historical_best` pair is exactly the fix — ship both, always, and never a bare boolean. Consider surfacing the ratio as a first-class field so Claude does not have to divide.
**Warning signs:** a plateau result whose `recent_performance / historical_best` is below ~0.85 being narrated as "you've stalled."

### Pitfall 6: `regr_slope` returns `double precision`, silently

**What goes wrong:** `SELECT pg_typeof(regr_slope(1.0::numeric, 2.0::numeric))` → `double precision` `[VERIFIED]`. asyncpg hands that back as a Python `float`. It then multiplies into a percentage and gets compared against a `Decimal` band.
**Why it happens:** the inputs are `numeric`, so the return type looks like it should be too. `avg()` and `stddev_samp()` over `numeric` *do* return `numeric`, which makes the exception easy to miss.
**How to avoid:** Pattern 4's Python implementation. If a plan ever proposes SQL regression, it is a C-2 violation.
**Warning signs:** a `float` anywhere in `app/analytics/`; a trend test that needs `pytest.approx`.

### Pitfall 7: `Decimal` division is inexact — quantize at every boundary

**What goes wrong:** `Decimal("100.000") * (1 + Decimal(7)/Decimal(30))` = `123.3333333333333333333333333` (28 significant digits, the default context precision). PostgreSQL's `numeric` division yields ~20 decimal places instead. The two **differ**, so a value computed in SQL and a value computed in Python will not compare equal.
**Why it happens:** `Decimal` is exact for `+ − ×` but not for `/`; the result length depends on `getcontext().prec`, which is process-global and mutable.
**How to avoid:** one quantum constant per quantity, applied at the boundary, exactly as `frequency._RATE_QUANTUM` does. Recommended: e1RM `Decimal("0.001")` (mirrors `weight_kg`'s `Numeric(7,3)`), percentages `Decimal("0.01")`, slopes `Decimal("0.0001")`. Never compute the same quantity in both SQL and Python.
**Warning signs:** a test comparing an un-quantized `Decimal` for equality; any e1RM with more than 3 decimal places crossing a function boundary.

### Pitfall 8: Per-week-normalizing the wrong metric in CMP-01

**What goes wrong:** dividing a maximum, an average or an already-per-week rate by the number of weeks. `best_e1rm / 4` is meaningless; `sessions_per_week / 4` is wrong by a factor of the window length.
**Why it happens:** "normalize everything per week" is a natural reading of CMP-01's text, and the resulting numbers still look like numbers.
**How to avoid:** structural separation — two row types, or a `normalized: bool` field the constructor requires. Counts and sums only.
**Warning signs:** an e1RM in the comparison output that is a quarter of the value the progression endpoint reports for the same exercise.

### Pitfall 9: Epley across a 5–12 rep spread is noisy at constant strength

**What goes wrong:** every high-frequency template on live data spans `reps 5 → 12` with a standard deviation of 1.9–2.4 reps. Epley's multiplier ranges 1.167 → 1.400 across that span, a **20% swing** with no change in actual strength. A heavy triple day and a light twelve day produce visibly different e1RM.
**Why it happens:** Epley is a linear approximation calibrated near a single rep range; it is not rep-invariant.
**How to avoid:** D-04's max-per-day absorbs most of it (the best set usually sits at the same end of the range); D-07's 2% tolerance and D-05's 4-week minimum absorb the rest. **Name this in the shipped docstrings** so nobody later "fixes" a 3% week-to-week wobble that is entirely rep-scheme noise. Do not add per-rep-range normalization — that is `AN-V1X` territory.
**Warning signs:** a trend verdict that flips when one high-rep session is added.

### Pitfall 10: BODY-01's headline number is `null` right now

**What goes wrong:** the D-16 anchor window `[2026-07-26 … 2026-08-01]` contains **zero** weigh-ins. `trend_rate_percent_per_week` is `null`, so BODY-02 returns `insufficient_data`.
**Why it happens:** a genuine 52-day logging gap (2026-06-15 → 2026-08-06).
**How to avoid:** nothing to avoid — this is the correct output. Design for it: make `insufficient_data` a first-class tested path; build every BODY test on synthetic fixtures under `time-machine`; do not write a test that asserts a non-null rate against live data, because it will start passing for the wrong reason around 2026-09-06.
**Warning signs:** a BODY test that passes without a frozen clock; any temptation to relax D-15's floors to make live data produce a number.

### Pitfall 11: `func.timezone(...)` without `cast(..., Date)` produces naive datetimes

**What goes wrong:** the expression yields a naive `datetime`, which never compares equal to the `datetime.date` keys every Python-side fold uses — producing two entries per day with no error.
**Why it happens:** Phase 4 hit this exact trap with `date_trunc` (`rollup.py:206-211`). The `timezone()` form has the same behaviour.
**How to avoid:** `cast(func.timezone(window.tz, Workout.start_time), Date)`, always. And keep `tz` a **bound parameter** — Ruff `S608` and `test_analytics_isolation.py`'s `text(` ban both enforce it.
**Warning signs:** a per-day dict with more keys than there are training days.

### Pitfall 12: `date.today()` is banned and would be wrong anyway

**What goes wrong:** Ruff's `DTZ` ruleset (enabled repo-wide) rejects it, and it returns the *server's* calendar day, not the user's. At UTC+7 those differ for 7 hours a day.
**How to avoid:** `local_day(utc_now(), tz)` where `tz` comes from `users.timezone` via `resolve_window()`.

### Pitfall 13: `rpe` is empty and `fat_percent` / `lean_mass_kg` are empty

**What goes wrong:** designing PROG-01 around blueprint §19's RPE/RIR field or BODY-02 around blueprint §24's body-fat input produces fields that are `None` for every row, forever.
**Verified:** `rpe` 0 / 7,719 hard sets. `fat_percent` 0 / 123. `lean_mass_kg` 0 / 123. `waist_cm` 15 / 123 with a 3-month gap between the two most recent values.
**How to avoid:** omit RPE from PROG-01's return type (or ship it with the count in the docstring). Design BODY-02 on weight + training only, which is what CONTEXT.md already assumes.

---

## Code Examples

### Extending `GoldenBuilder` with body measurements

```python
# backend/tests/conftest.py -- add a method to the EXISTING GoldenBuilder class, not a new
# builder. Same flush-and-rollback contract: the fixture never commits, the analytics function
# under test reads through the SAME session and sees the flushed rows, and the finally-block
# rollback leaves the session-scoped container untouched even when an assertion fails mid-test.

    async def body_measurement(
        self,
        *,
        measured_on: dt.date,
        weight_kg: Decimal | None,
        source: str = "hevy",
        user_id: uuid.UUID = DEFAULT_USER_ID,
    ) -> None:
        """One body_measurements row. `weight_kg` is Decimal, never float (C-2).

        `source` is a parameter with a 'hevy' default so a D-14 tie-break test can write both
        a 'hevy' and a 'manual' row for the same date -- which the natural key
        (user_id, source, measured_on) permits and which is the whole reason D-14 exists.
        """
        await self._session.execute(
            insert(BodyMeasurement).values(
                id=uuid.uuid4(),
                user_id=user_id,
                source=source,
                external_id=None,
                measured_on=measured_on,
                weight_kg=weight_kg,
            )
        )
        await self._session.flush()
```

### Freezing the clock for a BODY-01 test

```python
# Every BODY-01/BODY-02 and PROG-03 test needs this. Without it the window that a fixture
# targets slides out from under it within days, and the failure looks like an algorithm bug.

import time_machine

@time_machine.travel("2026-08-30T02:00:00+00:00", tick=False)
async def test_rolling_averages_gate_independently(...) -> None:
    # 02:00 UTC is 09:00 in Asia/Jakarta -- deliberately an instant where the UTC day and the
    # local day AGREE, so the test isolates the coverage rule. A second test should pick an
    # instant where they DISAGREE (e.g. 2026-08-29T18:00:00+00:00 -> local 2026-08-30) to prove
    # the anchor day is local_day(utc_now(), tz) and not the UTC date.
```

### Function signature convention (repo-wide, non-negotiable)

```python
# Session positional, everything else keyword-only. Verified across resolver.py, sync_state.py,
# metadata.py, volume.py, frequency.py, rollup.py, workouts.py, templates.py, body.py.
# `user_id` has NO default: ASVS V4 -- the schema is multi-user-ready, so forgetting it must be
# a TypeError and never a cross-tenant read that a single-user test suite cannot see.
# Nothing in app/analytics/ commits; the CALLER owns the transaction.

async def get_exercise_progression(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    exercise_template_external_id: str,
    start_day: dt.date,
    end_day: dt.date,
) -> ExerciseProgressionResult: ...
```

### Recommended new schema types (sketch, all on `_AnalyticsModel`)

```python
# backend/app/analytics/schemas.py -- ONE contract module (Phase 4's docstring says so).

class ProgressionPoint(_AnalyticsModel):
    """One local day of one exercise. `estimated_1rm_kg` and `no_estimate_reason` are
    MUTUALLY EXCLUSIVE and exactly one is populated -- the SyncReport docstring idiom."""
    local_day: dt.date
    sets: int
    best_weight_kg: Decimal | None
    best_reps: int | None
    total_reps: int | None
    volume_kg: Decimal | None
    volume_sets: int
    estimated_1rm_kg: Decimal | None
    no_estimate_reason: NoEstimateReason | None

class ExerciseProgressionResult(_AnalyticsModel):
    """PROG-01. `points` ascending by local_day. Days with no training are ABSENT, not zero
    rows -- unlike Phase 4's week spine, because 'you did not do this exercise on Tuesday' is
    not a diagnostically interesting zero, it is every non-training day."""
    exercise_template_external_id: str
    title: str | None
    exercise_type: str | None
    points: list[ProgressionPoint]
    coverage: CoverageMetadata
    freshness: FreshnessMetadata

class ExerciseTrend(_AnalyticsModel):
    """PROG-02. Carries the window and the rate that produced the verdict, not just the label
    -- see Pitfall 3."""
    exercise_template_external_id: str
    title: str | None
    verdict: TrendVerdict
    rate_percent_per_week: Decimal | None
    weeks_with_data: int
    window_start: dt.date
    window_end: dt.date

class PlateauResult(_AnalyticsModel):
    """PROG-03 / D-07b. Blueprint 21's shape, plus the window and threshold PROG-03's
    requirement text explicitly demands be returned alongside the result."""
    exercise_template_external_id: str
    title: str | None
    plateaued: bool
    plateau_duration_days: int | None
    qualifying_sessions_in_streak: int
    recent_performance_kg: Decimal | None
    historical_best_kg: Decimal | None
    confidence: PlateauConfidence
    threshold_percent: Decimal          # PLATEAU_IMPROVEMENT_TOLERANCE * 100
    min_sessions: int
    min_elapsed_days: int
    lookback_start: dt.date
    lookback_end: dt.date

class BodyWeightTrendResult(_AnalyticsModel):
    """BODY-01. Each window carries its OWN coverage (D-15) -- independent floors."""
    anchor_day: dt.date
    average_7d_kg: Decimal | None
    average_14d_kg: Decimal | None
    average_30d_kg: Decimal | None
    coverage_7d: MeasurementCoverage
    coverage_14d: MeasurementCoverage
    coverage_30d: MeasurementCoverage
    trend_rate_kg_per_week: Decimal | None       # D-16, smoothed over 4 weeks
    trend_rate_percent_per_week: Decimal | None  # D-16 -> D-10's percent basis
    trend_anchor_coverage: MeasurementCoverage   # the 4-weeks-ago 7-day window
    latest_week_delta_kg: Decimal | None         # D-17, SECONDARY, never classified against
    freshness: FreshnessMetadata

class RecompositionResult(_AnalyticsModel):
    """BODY-02. `disclaimer` is a REQUIRED field, not documentation -- see Pattern 9 step 4."""
    status: RecompositionStatus
    disclaimer: str
    weight_trend: BodyWeightTrendResult
    progression: AggregateProgression       # verdict + counts + net score, ALWAYS populated
    training_volume: WeeklyVolumeResult | None
    freshness: FreshnessMetadata
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|---|---|---|---|
| Epley / Brzycki as the universal e1RM formula | Same formulas, but with an explicit rep-range trust boundary; a 2025 "Verro" multi-variable non-linear model claims better accuracy | 2025 | **No action.** D-01 locks Epley. The trust boundary is the part that matters and D-02 already has one. A non-linear proprietary model would break the "deterministic and explainable" bar |
| "≤12 reps is fine for e1RM" | Published guidance converges on **≤10 reps**; a 2006 prediction-accuracy study recommends no more than 10 for linear models `[CITED: strengthjourneys.xyz, arvo.guru]` | ongoing | D-02's 12 is *more permissive* than current guidance. Justified here by data (reps=12 is this account's largest bucket; ≤10 would discard 23.9% of eligible sets) but the tension should be visible in the docstring — see Open Question 3 |
| Fixed kg/week bulk targets | **Percent of bodyweight per week**; 0.25–0.5%/week for lean bulking, with 0.16%/wk ≈ 85% lean mass and 0.38%/wk ≈ 65% lean mass `[CITED: macrofactor.com/bulking-calculator, thebodybuildingdietitians.com]` | established | Confirms D-10 and D-11. D-11's +0.25% sits at the conservative end of the published band, exactly as CONTEXT.md claims |
| Scale weight as the recomp signal | Multi-stream: **strength is the leading indicator**, scale/tape/photos are lagging `[CITED: gainframe.app/blog/body-recomposition-tracker]` | ongoing | Directly supports Pattern 9's structure — weight sets the direction bucket, progression refines within it, and `likely_recomp_progressing` requires improving strength |
| `float`/`double` statistics in SQL | Exact `Decimal` in application code for anything money-like or test-asserted | long-established | Bans `regr_slope` here |

**Deprecated / outdated in this project's context:**
- Blueprint §8's `rir` field — Hevy sends `rpe`, and 0 of 7,719 live sets carry one.
- Blueprint §25's literal week-over-week rate calculation — retained as D-17's secondary field, superseded as the classifier by D-16.
- Blueprint §24's body-fat and waist inputs — no data (0/123 and 15/123 respectively).

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|---|---|---|
| **A1** | PROG-03 should take a **caller-supplied lookback window** (default 12 weeks). D-06 does not say this; it specifies minimum evidence only. | Pitfall 2, Open Question 1 | **High.** Without it, 45% of exercises are flagged with 200–400-day durations and PROG-03's output is not usable coaching. This is the single most important unlocked decision in the phase |
| **A2** | `WEIGHT_STABLE_BAND_PERCENT_PER_WEEK = ±0.10%/week` as the "weight stable" dead-band for BODY-02 | Pattern 9 step 2 | Medium. CONTEXT.md gives the two outer thresholds but no stable band, and §26's enum requires one to distinguish `weight_stable` from `likely_muscle_gain`/`likely_fat_loss`. 0.10 is 1/10 of D-11, not an independent number, but it is not user-confirmed |
| **A3** | `TREND_STABLE_BAND_PERCENT_PER_WEEK = 0.5%/week`, derived as D-07's 2% ÷ D-05's 4 weeks | Pattern 4 | Medium. The derivation is principled and the live-data split is clean (9/9/10), but the user has not seen it. A different band shifts which exercises read as `stable` |
| **A4** | `RECOMP_PROGRESSION_NET_BAND = 0.25` with a 3-exercise minimum, `unclear` exercises excluded from the denominator | Pattern 9 step 1 | Medium. This is the exact rule CONTEXT.md left open and explicitly asked to be confirmed at plan time |
| **A5** | The on-target-gain row maps to `likely_muscle_gain` regardless of progression, with the nuance carried by a required `progression_signal` field | Pattern 9 step 3 | Medium. §26's seven-value enum has no better member; the alternative is adding an eighth value, which changes the blueprint's contract |
| **A6** | `rate_percent_per_week` uses `current_7d_avg` as the denominator | Pattern 8 | Low. Alternatives (anchor avg, mean of both) differ by <1% of the rate at this user's magnitudes, but the choice must be stated or two implementations will disagree |
| **A7** | RPE should be omitted from PROG-01's return type entirely | Pitfall 13, Ground Truth | Low. Reversible; the only cost of including it is a permanently-null field |
| **A8** | Module split: `estimates.py` / `progression.py` / `records.py` / `comparison.py` / `bodyweight.py` / `recomposition.py`, with `rollup.py`, `schemas.py`, `metadata.py` extended | Recommended Project Structure | Low. CONTEXT.md explicitly delegates layout to Claude's discretion |
| **A9** | PROG-02's `y` is the week's **best** qualifying e1RM (not the mean) and `x` is the true week offset (not a compressed index) | Pattern 4 | Low–medium. Using the mean would drag the slope down on deliberately light weeks; compressing x would hide training gaps |
| **A10** | D-04's tie-break at equal e1RM prefers **more reps** | Pattern 3 | Low. D-04 does not specify a tie-break and ties are common on fixed-increment machine stacks. Any deterministic rule works; this one must be stated so it is not accidental |

---

## Open Questions

1. **What is PROG-03's maximum lookback?** *(the big one)*
   - What we know: D-06 fixes the minimum evidence (4 qualifying sessions AND ≥21 days). Live data shows unbounded history flags 44/97 exercises with durations up to 402 days, including exercises abandoned months ago; a 12-week bound gives 18/29 at 27–75 days.
   - What's unclear: whether the user wants a fixed default, a caller parameter, or both; and what the default should be.
   - Recommendation: a required `lookback_weeks` parameter with a **12-week default**, echoed back in `PlateauResult.lookback_start`/`lookback_end` (PROG-03's requirement text already demands the window be returned). Confirm the default with the user at plan time; it is cheap to change and expensive to get wrong.

2. **Is `likely_muscle_gain` the right label for on-target gain with flat or declining lifts?**
   - What we know: blueprint §26's enum has exactly seven values and no better fit; `weight_stable` would be factually false.
   - What's unclear: whether the user would rather see `weight_gain_too_fast` (over-warning), an eighth enum value, or the recommended mapping with the nuance in `progression_signal`.
   - Recommendation: ship the recommended mapping. It never overstates — the label says "gaining at a rate consistent with muscle gain," and the always-present progression counts let Claude qualify it.

3. **Should D-02's rep cap stay at 12, given published guidance says 10?**
   - What we know: literature converges on ≤10 for linear 1RM models. This account's largest single rep bucket is exactly 12 (1,043 sets); reps 11–12 together are 1,146 sets = 23.9% of all otherwise-eligible sets.
   - What's unclear: whether the user prefers coverage (12) or estimate fidelity (10).
   - Recommendation: **keep 12** — D-02 is locked, the data strongly supports it, and dropping to 10 would make e1RM unavailable for the user's most-programmed scheme. Record the tension in `estimates.py`'s docstring so it is a known trade-off rather than an oversight.

4. **Does CMP-01 need per-muscle comparison rows, or only whole-window totals?**
   - What we know: `rollup.fold_window_by_muscle()` makes per-muscle nearly free, and MCP-02 lists "period comparison" as one tool.
   - What's unclear: response size versus MCP-03's "compact, structured JSON." 16 muscle groups × 3 figures × 2 periods = 96 numbers plus deltas.
   - Recommendation: include per-muscle, but behind a `include_muscle_groups: bool = False` parameter so Phase 6 can choose. Never present a cross-muscle total (Phase 4's Pitfall 11 carries forward unchanged).

5. **Should `PROG-02`'s aggregate be exposed as its own public function, or only inside `recomposition.py`?**
   - Recommendation: expose `get_exercise_trends(...)` publicly (Phase 6's MCP-02 lists "exercise progression" as a tool) and have `recomposition.py` call it. One computation, two consumers, no duplicate definition of "improving".

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|---|---|---|---|---|
| Python | everything | ✓ | 3.13 (`requires-python = ">=3.13,<3.14"`) | — |
| PostgreSQL (local dev) | live-data verification, manual checks | ✓ | 18 (`brett-db-1`, `postgres:18-alpine`, `localhost:5432`) | — |
| Docker | `testcontainers` integration suite | ✓ | running (2 containers up) | — |
| SQLAlchemy / asyncpg / Pydantic | all analytics | ✓ | 2.0.52 / 0.31.0 / 2.13.4 | — |
| pytest + pytest-asyncio + testcontainers | tests | ✓ | 9.1.1 / 1.4.0 / 4.15.0 | — |
| **time-machine** | BODY-01/02 and PROG-03 clock freezing | ✓ | 3.4.0 | none needed |
| Ruff / mypy | lint + types | ✓ | 0.16.4 / 2.3.1 | — |
| Live synced data (327 workouts, 123 measurements) | ground truth | ✓ | synced through 2026-08-29 | — |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none.
**Note:** the fast suite currently runs **206 passed, 163 deselected in 0.94 s** `[VERIFIED: .venv/bin/python -m pytest -q -m "not integration", 2026-08-30]`. New fast-suite tests (`test_analytics_estimates.py`) must not materially slow this.

---

## Validation Architecture

### Test Framework

| Property | Value |
|---|---|
| Framework | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"` — no decorator needed) |
| Config file | `pyproject.toml` → `[tool.pytest.ini_options]` (`testpaths = ["backend/tests"]`, `pythonpath = ["backend"]`, marker `integration`) |
| Quick run command | `.venv/bin/python -m pytest -q -m "not integration"` |
| Full suite command | `.venv/bin/python -m pytest -q` |
| Measured baseline | **206 passed, 163 deselected in 0.94 s** (fast suite, 2026-08-30) `[VERIFIED: local execution]` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|---|---|---|---|---|
| PROG-01/D-01 | Epley exact values: 100 kg × {1,7,8,12} → {103.333, 123.333, 126.667, 140.000} | unit (**fast**) | `pytest backend/tests/test_analytics_estimates.py -k epley -x` | ❌ Wave 0 |
| PROG-01/D-02 | reps 12 → estimate; reps 13 → `None` + `REP_RANGE` (both sides of the boundary) | unit (**fast**) | `pytest backend/tests/test_analytics_estimates.py -k rep_gate -x` | ❌ Wave 0 |
| PROG-01/D-03 | `bodyweight_weighted` / `reps_only` / `None` type → `None` + `MODALITY`, never a number | unit (**fast**) | `pytest backend/tests/test_analytics_estimates.py -k modality -x` | ❌ Wave 0 |
| PROG-01 | Epley is never computed in SQL (regression guard for Pitfall 1) | unit (static) | `pytest backend/tests/test_analytics_isolation.py -k formula -x` | ❌ Wave 0 |
| PROG-01/D-04 | Session with 60×10 and 70×5: the series entry is the higher-e1RM set (80.0 vs 81.67 → 70×5) | integration | `pytest backend/tests/test_analytics_progression.py -k best_set -x` | ❌ Wave 0 |
| PROG-01/D-04 | Tie at equal e1RM resolves to the higher-rep set, deterministically | integration | `pytest backend/tests/test_analytics_progression.py -k tie_break -x` | ❌ Wave 0 |
| PROG-01 | A day where every set is >12 reps still returns a point, with sets/reps/volume and a reason | integration | `pytest backend/tests/test_analytics_progression.py -k reason -x` | ❌ Wave 0 |
| PROG-02/D-05 | 3 training weeks → `unclear`; 4 → a committed verdict (both sides of the boundary) | integration | `pytest backend/tests/test_analytics_progression.py -k min_weeks -x` | ❌ Wave 0 |
| PROG-02 | OLS slope is exact `Decimal` — asserted without `approx` on a hand-computed fixture | unit (**fast**) | `pytest backend/tests/test_analytics_progression.py -k slope_exact -x` | ❌ Wave 0 |
| PROG-02 | Dead-band both sides: +0.49%/wk → `stable`, +0.51%/wk → `improving`, −0.51%/wk → `declining` | unit (**fast**) | `pytest backend/tests/test_analytics_progression.py -k dead_band -x` | ❌ Wave 0 |
| PROG-02 | A three-week training gap widens the x-gap (does not compress to consecutive indices) | unit (**fast**) | `pytest backend/tests/test_analytics_progression.py -k week_offset -x` | ❌ Wave 0 |
| PROG-03/D-06 | 3 qualifying sessions → not plateaued; 4 + ≥21 days → plateaued; 4 in 13 days → **not** (calendar floor) | integration | `pytest backend/tests/test_analytics_progression.py -k plateau_window -x` | ❌ Wave 0 |
| PROG-03/D-07 | +1.5% over historical best does **not** break the streak; +2.5% does | integration | `pytest backend/tests/test_analytics_progression.py -k tolerance -x` | ❌ Wave 0 |
| PROG-03/D-07a | A null-e1RM session (15 reps, or a `reps_only` day) neither extends nor breaks the streak | integration | `pytest backend/tests/test_analytics_progression.py -k skip_null -x` | ❌ Wave 0 |
| PROG-03/D-07b | Result carries `recent_performance`, `historical_best`, session count, elapsed days, threshold and confidence — never a bare bool | integration | `pytest backend/tests/test_analytics_progression.py -k plateau_shape -x` | ❌ Wave 0 |
| PROG-03 | `historical_best` is seeded from **before** the lookback (Pitfall 4): widening the lookback does not move the streak start | integration | `pytest backend/tests/test_analytics_progression.py -k seeded -x` | ❌ Wave 0 |
| PROG-03 | `plateau_duration_days` is measured to a **frozen** now, not to the last session | integration | `pytest backend/tests/test_analytics_progression.py -k duration -x` | ❌ Wave 0 |
| PROG-04/D-08 | A `dropset` set sets a PR; a `warmup` set with a higher weight does not | integration | `pytest backend/tests/test_analytics_records.py -k set_type -x` | ❌ Wave 0 |
| PROG-04/D-09 | The same max reached on two dates records the **earlier** date | integration | `pytest backend/tests/test_analytics_records.py -k tie_earliest -x` | ❌ Wave 0 |
| PROG-04 | All five PR types present; rep PR and max-weight PR are **not** gated by D-02's ≤12 | integration | `pytest backend/tests/test_analytics_records.py -k pr_types -x` | ❌ Wave 0 |
| PROG-04 | "Max reps at a weight" returns one row per distinct weight, sorted descending by weight | integration | `pytest backend/tests/test_analytics_records.py -k per_weight -x` | ❌ Wave 0 |
| CMP-01 | A 28-day period vs a 14-day period with identical weekly training yields a **zero** delta per week | integration | `pytest backend/tests/test_analytics_comparison.py -k unequal_length -x` | ❌ Wave 0 |
| CMP-01 | Periods are **not** snapped to whole weeks (Phase 4 D-03 carried forward) | integration | `pytest backend/tests/test_analytics_comparison.py -k no_snap -x` | ❌ Wave 0 |
| CMP-01 | `delta_percent` is `None` (not zero, not an exception) when the baseline period is zero | integration | `pytest backend/tests/test_analytics_comparison.py -k zero_baseline -x` | ❌ Wave 0 |
| CMP-01 | Best e1RM is compared as a level and is **never** divided by weeks (Pitfall 8) | integration | `pytest backend/tests/test_analytics_comparison.py -k level_not_rate -x` | ❌ Wave 0 |
| CMP-01 | Both periods carry independent `CoverageMetadata` | integration | `pytest backend/tests/test_analytics_comparison.py -k coverage -x` | ❌ Wave 0 |
| BODY-01/D-13 | A 4-day gap is not interpolated: the average is over measured days only | integration | `pytest backend/tests/test_analytics_bodyweight.py -k no_interpolation -x` | ❌ Wave 0 |
| BODY-01/D-14 | A `'manual'` row wins over a same-date `'hevy'` row; neither is double-counted | integration | `pytest backend/tests/test_analytics_bodyweight.py -k source_tiebreak -x` | ❌ Wave 0 |
| BODY-01/D-15 | Per-window floors, each side of each boundary: 2 vs 3 days (7d), 4 vs 5 (14d), 9 vs 10 (30d) | integration | `pytest backend/tests/test_analytics_bodyweight.py -k floors -x` | ❌ Wave 0 |
| BODY-01/D-15 | A 30-day average can be non-null while the 7-day one is null (independence) | integration | `pytest backend/tests/test_analytics_bodyweight.py -k independent -x` | ❌ Wave 0 |
| BODY-01/D-16 | Smoothed rate = `(cur7 − anchor7)/4`; `null` when **either** window fails its floor | integration | `pytest backend/tests/test_analytics_bodyweight.py -k smoothed -x` | ❌ Wave 0 |
| BODY-01/D-17 | `latest_week_delta_kg` is present and is **different** from the smoothed rate on noisy fixtures | integration | `pytest backend/tests/test_analytics_bodyweight.py -k latest_week -x` | ❌ Wave 0 |
| BODY-01/FOUND-03 | The anchor day is the **local** day: a `2026-08-29T18:00:00Z` clock reads as local 2026-08-30 | integration | `pytest backend/tests/test_analytics_bodyweight.py -k local_anchor -x` | ❌ Wave 0 |
| BODY-02/D-11 | +0.26%/wk → `weight_gain_too_fast`; +0.24%/wk → not (both sides) | integration | `pytest backend/tests/test_analytics_recomposition.py -k gain_threshold -x` | ❌ Wave 0 |
| BODY-02/D-12 | −1.01%/wk → `weight_loss_too_fast`; −0.99%/wk → not | integration | `pytest backend/tests/test_analytics_recomposition.py -k loss_threshold -x` | ❌ Wave 0 |
| BODY-02 | Weight stable + aggregate `improving` → `likely_recomp_progressing`; + `declining` → `weight_stable` | integration | `pytest backend/tests/test_analytics_recomposition.py -k matrix -x` | ❌ Wave 0 |
| BODY-02 | `null` weight rate → `insufficient_data`, regardless of progression | integration | `pytest backend/tests/test_analytics_recomposition.py -k insufficient -x` | ❌ Wave 0 |
| BODY-02 | Fewer than 3 classified exercises → aggregate `unclear`, and a weight-only label is still returned | integration | `pytest backend/tests/test_analytics_recomposition.py -k min_exercises -x` | ❌ Wave 0 |
| BODY-02 | `disclaimer` is populated on every response | integration | `pytest backend/tests/test_analytics_recomposition.py -k disclaimer -x` | ❌ Wave 0 |
| DQ-01 | Every new response carries `FreshnessMetadata`; BODY-* includes `body_measurements` | integration | `pytest backend/tests/test_analytics_metadata.py -k body_freshness -x` | ⚠️ extend |
| DQ-01/MCP-06 | No `last_error`, status, cursor, DSN or credential appears in any new return model | unit (**fast**) | `pytest backend/tests/test_analytics_metadata.py -k no_leak -x` | ⚠️ extend |
| DQ-02 | `MeasurementCoverage` reports `measured_days_in_window` and `earliest_measurement_at` | integration | `pytest backend/tests/test_analytics_metadata.py -k measurement_coverage -x` | ⚠️ extend |
| ASVS V4 | Two users' data: user A's progression, PRs and body weight never include user B's rows | integration | `pytest backend/tests/test_analytics_progression.py -k tenant -x` | ❌ Wave 0 |
| C-2 | No `float` literal or annotation in any `app/analytics/` module | unit (static, **fast**) | `pytest backend/tests/test_analytics_isolation.py -k no_float -x` | ⚠️ extend |
| Architecture | `app/analytics/` imports nothing from `app.mcp` / `app.integrations`; no writes; no raw `text(` | unit (static, **fast**) | `pytest backend/tests/test_analytics_isolation.py -x` | ✅ auto-covers new modules via `rglob` |
| Regression | Fast suite stays green and fast | unit | `.venv/bin/python -m pytest -q -m "not integration"` | ✅ 206 passing / 0.94 s |

### Sampling Rate

- **Per task commit:** `.venv/bin/python -m pytest -q -m "not integration"` (0.94 s baseline — `test_analytics_estimates.py` and the pure trend/fold tests must land in this suite, not the container one)
- **Per wave merge:** `.venv/bin/python -m pytest -q` (full suite, container-backed)
- **Phase gate:** full suite green + `ruff check` + `mypy` before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `backend/tests/test_analytics_estimates.py` — PROG-01 D-01/D-02/D-03 (fast suite, no container)
- [ ] `backend/tests/test_analytics_progression.py` — PROG-01/02/03
- [ ] `backend/tests/test_analytics_records.py` — PROG-04
- [ ] `backend/tests/test_analytics_comparison.py` — CMP-01
- [ ] `backend/tests/test_analytics_bodyweight.py` — BODY-01
- [ ] `backend/tests/test_analytics_recomposition.py` — BODY-02
- [ ] `backend/tests/conftest.py` — add `GoldenBuilder.body_measurement()` (flush + rollback, never commit)
- [ ] `backend/tests/test_analytics_isolation.py` — extend with a `no_float` guard and a "no Epley in SQL" guard
- [ ] `backend/tests/test_analytics_metadata.py` — extend for `MeasurementCoverage` and body freshness
- [ ] Framework install: **none needed** — pytest, pytest-asyncio, testcontainers and time-machine are installed and already used by 369 existing tests

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---|---|---|
| V2 Authentication | no | Handled at the MCP boundary (Phase 2, WorkOS AuthKit OAuth 2.1 + CIMD). Analytics functions are internal and never see a token |
| V3 Session Management | no | MCP v2 transport is stateless; no session state in analytics |
| V4 Access Control | **yes** | **Every query must filter `Workout.user_id == user_id` / `BodyMeasurement.user_id == user_id`, and the `exercise_templates` join must carry its own tenant predicate** — Hevy's built-in template ids are *global*, so an unqualified template join attaches another user's modality to this user's set (this is the trap `frequency._template_titles` already documents at `frequency.py:88-93`). `user_id` stays keyword-only with no default so omission is a `TypeError`. Add an explicit two-user isolation test for progression, records and body weight |
| V5 Input Validation | **yes** | The timezone string reaches SQL as a bound parameter via `func.timezone(tz, col)` — never f-strings (Ruff `S608`; `test_analytics_isolation.py` bans `text(` outright). Date ranges are validated by `build_window()` (rejects `end < start`, clamps to `MAX_ANALYTICS_WINDOW_DAYS = 1830`). **New for Phase 5:** `exercise_template_external_id` becomes a caller-supplied filter — pass it as a bound parameter via `.in_()`, never interpolated, and it must not widen the tenant scope |
| V6 Cryptography | no | No cryptographic operation in this phase |
| V7 Error Handling & Logging | **yes** | Every `ValueError` message raised here will be logged. Follow `rollup.build_window()`'s convention: name the failure, carry **no** date value, **no** user id, **no** bodyweight and **no** exercise title. FOUND-05 |
| V8 Data Protection | **yes** | This phase handles the most sensitive data in the project — body weight and body composition. `_AnalyticsModel`'s `hide_input_in_errors=True` exists precisely so a Pydantic `ValidationError` cannot render a bodyweight into a log line. Every new model must inherit it (automatic via `_AnalyticsModel`). DQ-01's rule holds: only `last_synced_at` crosses the freshness boundary — never `last_error`, `status`, `cursor_page` or `cursor_timestamp` |
| V13 API / MCP-03 | **yes** | Result sizes are bounded by construction: PR-per-weight lists are ≤12 rows on live data; the window clamp bounds every series. If CMP-01 gains per-muscle rows, gate them behind a parameter rather than always returning 96+ numbers |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---|---|---|
| SQL injection via the timezone string or a template id | Tampering | SQLAlchemy bound parameters only; Ruff `S608`; static `text(` ban in `test_analytics_isolation.py` |
| Cross-tenant read from a forgotten `user_id` predicate | Information Disclosure | Keyword-only `user_id` with no default; tenant predicate leads every `WHERE`; explicit two-user isolation test |
| Health data leaking into logs via a validation error | Information Disclosure | `hide_input_in_errors=True` on `_AnalyticsModel`; error messages carry no values |
| Sync internals (cursors, error text) leaking to Claude | Information Disclosure | `build_freshness()` reads only `last_synced_at`; enforced in one place |
| Unbounded result set exhausting the MCP context | DoS | `MAX_ANALYTICS_WINDOW_DAYS` clamp before materialization; bounded PR list cardinality |
| A write path appearing in a read-only package | Tampering | `test_analytics_isolation.py` bans `session.commit/flush/add/add_all` and `insert/update/delete` imports; `rglob` auto-covers new modules |

---

## Sources

### Primary (HIGH confidence)

- **Live database execution**, `brett-db-1` PostgreSQL 18, 2026-08-30 — every figure in "Live Data Ground Truth", the plateau/trend simulations, `EXPLAIN (ANALYZE, BUFFERS)` timings, `pg_typeof(regr_slope(...))`, and the integer-division proof. This is the strongest evidence in this document.
- **Repository source**, read directly this session: `backend/app/analytics/{schemas,metadata,rollup,volume,frequency,__init__}.py`, `backend/app/core/time.py`, `backend/app/db/models/{workout,exercise,body}.py`, `backend/tests/{conftest,test_analytics_isolation}.py`, `pyproject.toml`, `docker-compose.yml`.
- **`.venv` execution**, 2026-08-30 — Decimal precision behaviour; fast-suite baseline (`206 passed, 163 deselected in 0.94s`).
- `.planning/phases/05-progression-records-recomposition-analytics/05-CONTEXT.md` — every locked decision, quoted verbatim above.
- `.planning/phases/04-volume-frequency-analytics/04-RESEARCH.md` and `04-PATTERNS.md` — the Phase 4 precedents this phase mirrors.
- `CLAUDE.md` — stack, "What NOT to Use", the Decimal and no-pandas rules.

### Secondary (MEDIUM confidence)

- [macrofactor.com — How Fast To Gain Weight When Bulking](https://macrofactor.com/bulking-calculator/) — 0.25–0.5%/week lean-bulk band; lean-mass fractions at 0.16% and 0.38%/week. Corroborates D-10/D-11.
- [The Bodybuilding Dietitians — How Fast Should You Bulk or Cut?](https://www.thebodybuildingdietitians.com/blog/how-fast-should-you-bulk-or-cut-evidence-based-guidelines) — same band, independent source.
- [GainFrame — Body Recomposition Tracker](https://gainframe.app/blog/body-recomposition-tracker/) — strength as the leading indicator, scale/tape as lagging; the "flat weight + rising strength" recomp signature behind Pattern 9.
- [Arvo — Epley & Brzycki Formulas Explained](https://arvo.guru/resources/one-rep-max-formulas) and [Strength Journeys — Epley Formula Calculator](https://www.strengthjourneys.xyz/calculator/epley-formula-1rm-calculator) — Epley reliability degrades above 10 reps; a 2006 prediction-accuracy study recommends ≤10 for linear models. The basis for Open Question 3.

### Tertiary (LOW confidence — flagged, not relied upon)

- [Verro — the Verro e1RM formula](https://www.verrotraining.com/blog/maximize-your-training-accuracy-the-verro-e1rm-formula) — a 2025 proprietary non-linear alternative claiming better accuracy than Epley. Vendor-authored, no independent validation found. **Not recommended** — D-01 locks Epley, and a non-linear proprietary model would fail the "deterministic and explainable" bar.

---

## Metadata

**Confidence breakdown:**

| Area | Level | Reason |
|---|---|---|
| Standard stack | **HIGH** | Zero new dependencies; every version read from `pyproject.toml` and confirmed installed |
| Live data ground truth | **HIGH** | Every number executed against the live database this session and reproduced in-document |
| SQL / Decimal mechanics | **HIGH** | Integer division, `regr_slope` return type, index plan and timings all verified by execution |
| Architecture / module layout | **HIGH** | Directly mirrors Phase 4's shipped, reviewed structure; CONTEXT.md delegates layout explicitly |
| PROG-02 trend algorithm | **MEDIUM** | Mathematically exact and empirically well-behaved on live data (9/9/10), but the dead-band constant is derived, not user-confirmed (A3) |
| PROG-03 lookback bound | **MEDIUM** | The *problem* is verified (44/97 flagged, 402-day durations); the *fix* is a recommendation the user has not approved (A1) |
| BODY-02 aggregation rule | **MEDIUM** | The rule CONTEXT.md explicitly asked to be settled at research time. Principled, symmetric, live-data-checked — but unconfirmed (A4, A5) |
| Pitfalls | **HIGH** | 10 of 13 verified by direct execution; the remainder inherited from Phase 4's own verified list |

**Research date:** 2026-08-30
**Valid until:** 2026-09-29 (30 days — stable stack, no fast-moving dependency). **One exception:** the "BODY-01 returns `insufficient_data` today" finding expires around **2026-09-06**, when the D-16 anchor window first clears its coverage floor on live data. Re-run the BODY-01 ground-truth query if planning slips past that date.
