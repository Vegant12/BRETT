# Pitfalls Research

**Domain:** Personal fitness data backend (third-party API sync → normalized PostgreSQL → analytics) exposed to an LLM via a remote MCP server
**Researched:** 2026-08-23
**Confidence:** HIGH for Hevy API surface (read directly from the live OpenAPI spec), HIGH for MCP transport/auth (official spec + SDK docs + closed Anthropic issue), MEDIUM for analytics-semantics and Render operational details, LOW where explicitly flagged

**Baseline:** Blueprint §7 (Hevy sync), §31–33 (permissions/auth/privacy), §42–44 (testing/observability) already say "be idempotent," "use bearer token," "don't log health data." This document goes past that: it names the *specific* mechanisms in the current Hevy API and the current MCP spec that make those instructions insufficient or, in one case, unimplementable as written.

---

## The three findings that change the plan

Read these before anything else. Each contradicts or materially tightens something in `PROJECT.md` / the blueprint.

1. **Claude's custom-connector UI cannot send a static bearer token.** `PROJECT.md` Key Decisions records "MCP auth = bearer token for v1, not OAuth." Anthropic's connector UI exposes only OAuth Client ID / Client Secret; the feature request to add an `Authorization: Bearer` field ([anthropics/claude-ai-mcp#112](https://github.com/anthropics/claude-ai-mcp/issues/112)) is **closed as not planned**. This decision must be revisited in Phase 4, not Phase 5. (Pitfall 1)
2. **Hevy's max `pageSize` is 10** on `/v1/workouts` and `/v1/workouts/events` (default 5). Every sync-cost assumption in the blueprint is off by an order of magnitude. (Pitfall 3)
3. **The MCP spec had a breaking revision on 2026-07-28** — 26 days before this research — removing the `initialize` handshake, `Mcp-Session-Id`, and the GET stream. The Python SDK shipped `2.0.0` the same day, renaming `FastMCP` → `MCPServer`. Any MCP code written from model training data will be v1-shaped. (Pitfall 10)

---

## Ground truth: the live Hevy API surface

Fetched and parsed from `https://api.hevyapp.com/docs/swagger-ui-init.js` on 2026-08-23 (the Swagger UI page itself renders no content to fetchers; the embedded `swaggerDoc` object is the real spec). **Confidence: HIGH** — this is the authoritative document, not a blog summary.

| Fact | Value | Why it matters |
|------|-------|----------------|
| Auth | `api-key` **header**, `format: uuid` | Not `Authorization: Bearer`. A generic HTTP client wrapper will get this wrong. |
| API version | `0.0.1` | Self-described as unstable (see disclaimer below) |
| `GET /v1/workouts` | `page` (≥1), `pageSize` **default 5, max 10** | 500 workouts = 50 requests minimum |
| `GET /v1/workouts/events` | `page`, `pageSize` **max 10**, `since` (default `1970-01-01T00:00:00Z`); **"Events are ordered from newest to oldest"** | Cursor advancement is order-sensitive — see Pitfall 4 |
| `GET /v1/exercise_templates` | `pageSize` **max 100** | Different limit from everything else |
| `GET /v1/body_measurements` | `pageSize` default 10, **max 10**; documents a **404 "Page not found"** response | Paging past the end 404s rather than returning `[]` |
| List response envelope | `{ page, page_count, workouts[] }` / `{ page, page_count, events[] }` | `page_count` is available — use it, don't loop until empty |
| `GET /v1/workouts/count` | `{ workout_count }` | Free reconciliation oracle (Pitfall 3) |
| Event shapes | `{type:"updated", workout:{...full workout...}}` or `{type:"deleted", id, deleted_at}` | Updated events carry the **full** workout — no refetch needed |
| Rate limits | **Not documented anywhere in the spec** | Must be discovered empirically; assume 429 exists and handle it |

**Object model (exact):**

- `Workout`: `id`, `title`, `routine_id`, `description`, `start_time`, `end_time`, `updated_at`, `created_at`, `exercises[]`
- `Exercise` (within workout): `index`, `title`, `notes`, `exercise_template_id`, `supersets_id` (nullable number), `sets[]` — **no `id`**
- `Set`: `index`, `type` (`normal` | `warmup` | `dropset` | `failure`), `weight_kg` (nullable), `reps` (nullable), `distance_meters` (nullable), `duration_seconds` (nullable), `rpe` (nullable), `custom_metric` (nullable) — **no `id`, no `rir`, no `weight_unit`**
- `ExerciseTemplate`: `id`, `title`, `type`, `primary_muscle_group`, `secondary_muscle_groups[]`, `equipment_category`, `is_custom`
- `MuscleGroup` enum (20): `abdominals, shoulders, biceps, triceps, forearms, quadriceps, hamstrings, calves, glutes, abductors, adductors, lats, upper_back, traps, lower_back, chest, cardio, neck, full_body, other`
- Exercise `type` enum (8): `weight_reps, reps_only, bodyweight_reps, bodyweight_assisted_reps, duration, weight_duration, distance_duration, short_distance_weight`
- `EquipmentCategory` enum (9): `none, barbell, dumbbell, kettlebell, machine, plate, resistance_band, suspension, other`

**Hevy's own disclaimer, verbatim from the spec's `info.description`:** *"we make no guarantees that we won't completely change the structure or abandon the project entirely so use it at your own risk."* This is the strongest possible argument for the blueprint's provider-isolation constraint — treat it as a hard requirement, not a preference.

**Endpoints the blueprint doesn't mention but that exist:** `/v1/body_measurements` (GET/POST/PUT — weight, lean mass, fat %, neck, shoulder, chest, biceps L/R, forearms L/R, abdomen, waist, hips, thighs L/R, calves L/R), `/v1/exercise_history/{exerciseTemplateId}`, `/v1/user/info`, `/v1/routines`, `/v1/routine_folders`. See Pitfall 9 — the "manual entry only" body-measurements decision is now questionable.

---

## Critical Pitfalls

### Pitfall 1: Designing MCP auth around a static bearer token Claude cannot send

**What goes wrong:**
Phase 4 builds a clean bearer-token-authenticated MCP server. It passes every local test (MCP Inspector, `claude mcp add --transport http --header "Authorization: Bearer …"`, `mcp-remote`). Phase 5 deploys to Render, and then the Claude custom-connector dialog offers **Name**, **Remote MCP server URL**, and — under advanced settings — **OAuth Client ID** and **OAuth Client Secret**. There is no header field. The connector either connects with no auth at all (if the server allows it) or fails, and the "read-only MCP server exposed to Claude over HTTPS with bearer-token auth" acceptance criterion is unreachable on the mobile/web surfaces the project explicitly targets.

**Why it happens:**
Three different Claude surfaces have three different auth capabilities, and they get conflated:
- **Claude Code / Desktop local config / `mcp-remote` / Cursor** — arbitrary headers, bearer tokens fine.
- **Claude.ai custom connector (web, mobile, Desktop connectors UI)** — OAuth only.
- **`static_headers`** — exists, but is beta and described as an *organization administrator* entering the value, i.e. Team/Enterprise-shaped, not a personal Pro/Max account.

All the tutorials and local dev loops use the first category. The project's target ("Desktop/Web/Mobile custom connector") is the second.

**How to avoid:**
Decide the auth strategy in **Phase 4**, before deployment, from these three options:

| Option | Effort | Works on web/mobile connector? | Notes |
|--------|--------|-------------------------------|-------|
| **Minimal single-user OAuth 2.1 shim** (recommended) | ~1 day | Yes | Serve `/.well-known/oauth-protected-resource` (RFC 9728), `/.well-known/oauth-authorization-server`, a `/register` DCR endpoint, `/authorize` (single hardcoded password prompt), `/token` issuing a short-lived signed JWT audience-bound to your MCP URL. The MCP Python SDK ships `create_protected_resource_routes()`, `TokenVerifier`, and `BearerAuthBackend` — you implement the AS half only. Precedent: the public `hevy-mcp` server built exactly this "for Claude.ai and remote clients unable to send fixed headers." |
| **Bearer token + desktop-only** | ~0 | No | Keep `TokenVerifier` bearer auth, connect via Claude Code / `mcp-remote` with `--header`. Ships fastest, forfeits the mobile/web goal. |
| **Secret in the URL path** (`/mcp/<128-bit-token>`) | ~0 | Yes | The blueprint explicitly forbids relying on this alone (§32), and it's right: URLs leak into proxy logs, crash reports, and screenshots. Only defensible as a *second* factor layered under a bearer/OAuth check. |

Structure the code so the token-verification seam is a single `TokenVerifier` implementation — then swapping "static secret compare" for "verify JWT signature + audience" is a one-file change.

**Warning signs:**
- The Phase 4 exit criterion says "verified with MCP Inspector" and never says "verified from claude.ai on mobile."
- Anyone writes "we'll paste the token into Claude's connector settings" in a plan doc.
- The deployment checklist has no step that exercises the actual connector-add flow.

**Phase to address:** **Phase 4** (design + build the auth mechanism), verified in **Phase 5** (real connector add from a phone).

---

### Pitfall 2: Treating "unique(user_id, provider, external_id)" as sufficient idempotency

**What goes wrong:**
The unique constraint is on `workouts`. It prevents duplicate *workouts*. It does nothing for `workout_exercises` and `sets`, and **Hevy's API gives those objects no stable identifier at all** — only a positional `index` inside the parent. So a re-sync of an edited workout does one of:
- naive insert → the workout now has 2× the exercises and 2× the sets → every volume number silently doubles;
- upsert keyed on `(workout_id, order_index)` → works until the user *reorders* or *deletes* an exercise in Hevy, at which point set data from exercise #3 gets grafted onto exercise #2, and the stale trailing exercise #4 is orphaned but still counted;
- delete-then-insert without a transaction → a crash mid-sync leaves a workout with zero exercises, which analytics reads as a real (empty) training session.

**Why it happens:**
"Idempotent sync" gets interpreted as "don't duplicate the top-level record." Nobody checks whether the child objects have IDs — and in Hevy's case they emphatically don't (verified: `Set` and `Exercise` schemas have no `id` property).

**How to avoid:**
- Model the workout as an **immutable-by-value aggregate**: on any create-or-update, inside **one transaction**, `DELETE FROM workout_exercises WHERE workout_id = :id` (with `ON DELETE CASCADE` to `sets`) then re-insert all children from the payload, then update the parent row and its `source_updated_at`.
- Never let child rows be the target of a partial write. One transaction per workout, committed atomically. A batch of 10 workouts should be 10 transactions, not one — a single malformed workout must not roll back nine good ones.
- Store `updated_at` from Hevy as `source_updated_at`. Skip the child rewrite entirely when `payload.updated_at <= source_updated_at` — this makes re-runs cheap as well as correct.
- Keep the raw JSON payload (a `jsonb` column or a `sync_raw_payloads` table). When analytics disagree with the Hevy app six months from now, this is the only way to tell whether the bug is in ingestion or in the math.
- **Test explicitly:** sync a workout, mutate the fixture (remove the middle exercise, reorder two, change one set's weight), re-sync, assert exact child-row counts and values. Then re-sync the *unchanged* fixture 3× and assert byte-identical DB state.

**Warning signs:**
- Total tonnage jumps by a clean multiple after a re-sync.
- `SELECT workout_id, COUNT(*) FROM workout_exercises GROUP BY 1 HAVING COUNT(*) > 20` returns rows.
- Any workout with `COUNT(exercises) = 0`.
- The sync service has an `update_workout()` that touches child tables outside a transaction block.

**Phase to address:** **Phase 2**. Add a persistent invariant check (Pitfall 14) that runs after every sync.

---

### Pitfall 3: Sync architecture built on an assumed page size (real max: 10)

**What goes wrong:**
The natural design — "full sync on first run, then re-fetch recent pages hourly" — assumes pages of 50–100. Hevy caps `pageSize` at **10** (default **5**) on `/v1/workouts` and `/v1/workouts/events`. A 600-workout history is 60 sequential HTTPS round-trips. If Phase 2 is built as "just re-fetch everything every sync" because the initial sync felt fast enough in testing with 20 workouts, the hourly job later hammers an undocumented rate limit, and the failure surfaces in production as a partially-synced database.

**Why it happens:**
`pageSize` limits are read once during exploration, then the number is forgotten. Nobody re-checks it when designing the *scheduled* job. Combined with no documented rate limit, there's no forcing function to think about request volume.

**How to avoid:**
- Hard-code `pageSize=10` and treat request count as a first-class design constraint. Full sync ≈ `ceil(workout_count / 10)` requests — get `workout_count` from `/v1/workouts/count` first and **log the planned request count before starting**.
- **Never full-sync on a schedule.** Full sync is a one-time bootstrap plus a manual `--force` escape hatch. Scheduled syncs go through `/v1/workouts/events` only.
- Build the HTTP client with, from day one: a bounded concurrency of 1–2 (not 10 — you don't know the rate limit), `Retry-After`-aware 429 handling, exponential backoff with jitter on 429/5xx/timeouts, a total-attempt ceiling, and a hard cap on pages per run.
- Since rate limits are undocumented, **discover them**: log every response's status and any `X-RateLimit-*` / `Retry-After` headers on the first real full sync, and write the observed behaviour into `integrations/hevy/README.md`. This is a deliverable, not a side effect.
- Blueprint §38 suggests "every 1–6 hours." For a single user who trains ~4×/week, **every 6 hours is plenty**; hourly buys nothing and multiplies rate-limit exposure by 6.

**Warning signs:**
- `pageSize` appears as a configurable with a default above 10 (Hevy returns **400 "Invalid page size"**).
- Sync duration grows linearly with total history rather than staying flat.
- The scheduled job's request count doesn't drop after the first run.

**Phase to address:** **Phase 2**.

---

### Pitfall 4: Losing events forever by advancing the cursor against a newest-first, paginated feed

**What goes wrong:**
`/v1/workouts/events?since=T` returns events **ordered newest to oldest**, paginated. The obvious loop is:

```
page 1 → process events → record newest event timestamp as new cursor → page 2 → ...
```

Page 1 holds the *newest* events. If you persist the cursor from page 1 and then crash (or hit a 429, or the process is killed by Render's deploy) before draining pages 2..N, the cursor has moved past events you never processed. They are **permanently unreachable** — the next run asks for events since a later timestamp. Silent, unrecoverable data loss with no error in the logs.

A second, subtler variant: this is **offset** pagination over a feed that grows at the front. If the user finishes a workout while you're on page 3, everything shifts one slot toward older, and one event slides from page 3 to page 4 *after you've already read page 3* — you skip it.

**Why it happens:**
Every incremental-sync tutorial assumes an append-only, oldest-first, cursor-paginated feed. Hevy's is the inverse, and the ordering is stated in one clause of an endpoint description that's easy to skim past.

**How to avoid:**
- **Two-phase: drain, then commit.** Capture `now_utc` *before* the first request. Fetch **all** pages 1..`page_count` into memory (events are small; even a large backlog is trivial). Only after the last page succeeds, apply them to the DB and set `last_hevy_event_cursor = now_utc` in the **same transaction**. Any failure → apply nothing, cursor unchanged, next run retries the whole window. This is safe precisely because event application is idempotent (Pitfall 2).
- **Apply oldest-first.** Reverse the collected list before applying so that update-then-delete for the same workout resolves in real-world order. Applying newest-first would resurrect a deleted workout.
- **Deduplicate by workout id, last-write-wins**, when the same workout appears in multiple events in one window.
- **Overlap the window.** Set the cursor to `now_utc - 5 minutes`, not `now_utc`. Re-processing a few events is free (idempotent); missing one is not. This also absorbs clock skew between your server and Hevy's.
- **Never trust `page_count` to stay constant mid-drain.** If `page_count` grows between requests, restart the drain rather than continuing.
- **Test:** a fake Hevy that returns 3 pages and raises on page 2 → assert cursor unchanged and DB unchanged. A fake that inserts a new event between page 1 and page 2 → assert nothing is lost.

**Warning signs:**
- The cursor is written inside the pagination loop rather than after it.
- Workouts exist in the Hevy app but not in your DB, with no error in sync logs.
- Sync logs show `records_imported: 0` on runs where you know you trained.
- A "repair" or "backfill" script starts appearing in the repo — that's the recovery for this bug, and it means it already happened.

**Phase to address:** **Phase 2**. This is the single highest-value test in the whole project.

---

### Pitfall 5: Hard-deleting on `deleted` events

**What goes wrong:**
A `{type:"deleted", id, deleted_at}` event arrives; the sync `DELETE`s the workout row. Three problems compound:
1. **Historical analytics silently rewrite themselves.** "Weekly volume in March" changes retroactively because a March workout was deleted in August. Claude has already told the user things based on the old numbers, and there is no record that the data moved.
2. **Nothing is auditable.** You cannot answer "did we ever have this workout, or did sync never fetch it?" — which is exactly the question you need when debugging Pitfall 4.
3. **PR detection breaks catastrophically.** Deleting the workout that held a personal record silently demotes the PR, and if PRs are cached/materialized, the cache and the base data disagree with no way to detect it.

Meanwhile the *inverse* mistake: if you never call the events endpoint (full-resync-only strategy), deleted workouts are **never** discovered — `/v1/workouts` simply stops listing them, and a naive upsert-only full sync leaves them in your DB forever as phantom training sessions.

**Why it happens:**
"Handle deletions" reads as "delete the row." And the phantom-workout variant happens because the deletion path is the least-exercised branch — you have to actually delete a workout in the Hevy app to test it, which nobody does by accident.

**How to avoid:**
- **Soft delete.** `deleted_at TIMESTAMPTZ NULL` on `workouts`. Every analytics query filters `WHERE deleted_at IS NULL`. Put this filter in one shared base query / SQLAlchemy criteria so it cannot be forgotten in the ninth analytics function.
- Record the deletion in the sync log with the workout's date, so "why did March change?" is answerable.
- Handle **delete-before-create**: a `deleted` event may arrive for a workout you never synced (created and deleted between two sync runs). Insert a tombstone row rather than no-op'ing, so the event is not re-applied and the history is complete.
- **Test the full lifecycle explicitly** with a mock Hevy: create → sync → update → sync → delete → sync → assert soft-deleted and excluded from all analytics → re-sync same events → assert stable.

**Warning signs:**
- `db.delete(workout)` anywhere in the sync service.
- Any analytics query on `workouts` without a `deleted_at` predicate.
- Historical weekly-volume numbers that differ between two runs on the same date range.

**Phase to address:** **Phase 2** (soft delete + lifecycle test), enforced in **Phase 3** (every analytics query).

---

### Pitfall 6: Modeling fields Hevy doesn't have, and discarding the ones it does

**What goes wrong:**
The blueprint's `sets` table (§8) specifies `weight`, `weight_unit`, `reps`, `distance`, `duration`, `rir`, `rpe`. Against the live spec:

- **`rir` does not exist.** Hevy's `Set` has `rpe` only. An `rir` column will be 100% NULL forever — and worse, "hard sets" analytics designed around RIR (the standard definition: a set within ~4 reps of failure) is **not implementable** from this data source. Design volume analytics around `set.type` and `rpe`, or around raw set counts, and be explicit that RIR is unavailable.
- **`weight_unit` does not exist.** Hevy always returns `weight_kg`. A `weight_unit` column invites someone to write conversion code that runs on data that's already normalized — a silent 2.2× error waiting to happen. Drop it; the blueprint's own §41 says internal storage is kg.
- **Fields that *do* exist and are missing from the blueprint model:** `supersets_id` (needed to interpret set density and rest), exercise-level `notes` (the user's own training observations — genuinely valuable coaching context), `custom_metric`, `routine_id` (lets you say "you've drifted from your program"), `set.index`, `exercise.index`, and the exercise-type/equipment metadata on templates.
- **`set.type` is the one field everything depends on** and it's easy to store as an untyped string and then never filter on it (see Pitfall 8).

**Why it happens:**
The blueprint's schema was written from a mental model of what a workout logger *should* expose, then treated as authoritative. The `PROJECT.md` requirement "built against current official Hevy API docs (not invented endpoints)" correctly guards endpoints — but not fields.

**How to avoid:**
- Generate Pydantic models **directly from the OpenAPI spec** (`datamodel-code-generator` against the extracted `swaggerDoc`, or hand-write to match it exactly), then let the DB schema follow the Pydantic models. The saved spec is at hand — commit a copy to `integrations/hevy/openapi-snapshot.json` and diff against the live one in CI so field changes surface as a test failure rather than a runtime `KeyError`.
- Use `extra="forbid"` on the Hevy response models in tests (so new upstream fields are *noticed*) and `extra="ignore"` in production (so they don't break sync). Log a warning when unknown fields appear.
- Keep the raw `jsonb` payload — it makes "we didn't model that field" a migration rather than a re-sync.
- Where the blueprint and the spec disagree, **the spec wins**; record the deviation in the Key Decisions table so it isn't re-litigated.

**Warning signs:**
- A column that is NULL for every row after a full sync.
- Any unit-conversion code inside `integrations/hevy/`.
- `KeyError` / `ValidationError` on real data after passing all tests against hand-written fixtures.

**Phase to address:** **Phase 2**.

---

### Pitfall 7: Building exercise normalization by string-matching names when Hevy already gives you the mapping

**What goes wrong:**
`PROJECT.md` specifies "an exercise normalization layer mapping exercise **names** to canonical muscle groups." Name-matching is fragile in exactly the ways that matter: `"Bench Press (Barbell)"` vs `"Bench Press (Dumbbell)"` vs `"Incline Bench Press (Smith Machine)"` vs a user-renamed custom exercise vs the emoji-and-parenthesis conventions Hevy uses. You end up with a hand-maintained regex table that silently drops any exercise it doesn't recognize — and *dropped* exercises don't error, they just make a muscle group look undertrained. Claude then confidently advises the user to add chest volume they're already doing.

Meanwhile, `GET /v1/exercise_templates` returns `primary_muscle_group` and `secondary_muscle_groups[]` **for every exercise, including custom ones**, drawn from a fixed 20-value enum — and every workout exercise carries a stable `exercise_template_id` pointing at it.

**Why it happens:**
The exercise-normalization requirement was written before the template endpoint was examined. Also `exercise.title` is right there in the workout payload, so name-based mapping is the path of least resistance.

**How to avoid:**
- **Key on `exercise_template_id`, never on the title.** Titles are display strings; the template ID is the join key.
- **Seed the mapping table from `/v1/exercise_templates`** (`pageSize=100`, so this is cheap) and store `primary_muscle_group`, `secondary_muscle_groups`, `type`, `equipment_category`, `is_custom`. Keep the blueprint's manual-override capability as a *nullable override column* layered on top of the Hevy-sourced defaults — you get correctness by default and the ability to disagree (e.g. reclassifying a movement's secondary emphasis) without maintaining the base mapping by hand.
- **Fail loud on unmapped templates.** An exercise whose `exercise_template_id` has no template row must raise a visible warning and appear in a `SELECT` you actually run — never be silently excluded from volume.
- Re-sync exercise templates as part of the scheduled job (new custom exercises appear whenever the user creates one mid-workout); an unmapped ID discovered during workout sync should trigger an on-demand `GET /v1/exercise_templates/{id}`.
- Use Hevy's 20-value `MuscleGroup` enum as your canonical vocabulary rather than inventing one. It already distinguishes `lats` / `upper_back` / `traps` / `lower_back`, which is the granularity muscle-group volume analysis needs.

**Warning signs:**
- Any `re.match` / `LIKE '%bench%'` in the normalization layer.
- A muscle group with implausibly low volume (usually means its exercises fell through the mapping).
- The count of distinct `exercise_template_id` in `workout_exercises` exceeds the count of rows in your templates table.

**Phase to address:** **Phase 2** (sync templates), consumed in **Phase 3**.

---

### Pitfall 8: Volume math that ignores set type, null weights, and the 8 exercise types

**What goes wrong:**
`volume = SUM(weight_kg * reps)` is the default implementation and it is wrong in at least five ways against real Hevy data:

1. **Warm-up sets are included.** Hevy tags them (`set.type = 'warmup'`), and the training-science consensus is unambiguous that light warm-ups shouldn't count toward volume. Including them inflates tonnage by 20–40% and, worse, makes tonnage *fluctuate with warm-up habits* rather than with training.
2. **`weight_kg` is nullable.** For `bodyweight_reps` (pull-ups, dips, push-ups) it's null or zero → `NULL * reps = NULL`, and `SUM` silently skips it. Your entire back and chest calisthenics volume evaluates to zero. Claude reports "your lats are undertrained."
3. **`bodyweight_assisted_reps`** logs the *assistance* weight. Multiplying it into tonnage adds volume in proportion to how much help you needed — the metric runs backwards.
4. **`duration`, `distance_duration`, `weight_duration`, `short_distance_weight`, `reps_only`** have no meaningful `weight × reps`. Five of Hevy's eight exercise types don't fit the formula.
5. **`dropset` and `failure` sets** are real working sets and should count, but conflating them with `normal` sets distorts set-count-based metrics.

Because this produces *numbers* rather than errors, it passes tests written against hand-crafted barbell-only fixtures, ships, and then Claude presents wrong analysis with full confidence — which is worse than no analysis at all.

**Why it happens:**
`sets × reps × weight` is the textbook definition, and the blueprint (§17) says "training volume" without defining it. Test fixtures are always barbell bench press.

**How to avoid:**
- **Write down the definition before writing the code**, in `docs/analytics-definitions.md`, and expose it: every MCP tool response should carry a `methodology` string or a documented tool description so Claude can explain what "volume" means when asked.
- **Compute two metrics, not one:**
  - `hard_sets` — count of sets where `type IN ('normal','dropset','failure')`. This works for **all 8 exercise types** and is the more defensible primary metric.
  - `tonnage_kg` — `SUM(weight_kg * reps)` restricted to `type IN ('normal','dropset','failure')` **and** exercise `type IN ('weight_reps','weight_duration','short_distance_weight')`. Report it as `NULL`/absent for other types rather than 0.
- **Bodyweight handling:** either exclude bodyweight exercises from tonnage entirely (honest) or impute using logged body weight from `body_measurements` (better, but then say so in the methodology and mark it as estimated). Never let them silently contribute 0.
- **Never emit `0` where you mean "not applicable."** Zero means "did nothing"; null means "not measurable." Claude will interpret 0 as a training gap.
- **Golden-fixture tests:** hand-compute expected values for a fixture set that includes a barbell exercise with warm-ups, a bodyweight exercise, an assisted exercise, a duration-only exercise, a dropset, and a superset. Assert exact numbers. This is the single test that protects every downstream metric.
- **Unverified assumption to validate against real data (LOW confidence):** whether Hevy stores dumbbell exercise weight *per dumbbell* or as a *combined* total. If per-dumbbell (likely), dumbbell tonnage is half of true tonnage and dumbbell-vs-barbell progression comparisons are invalid. Verify against your own account in Phase 2 and record the finding.

**Warning signs:**
- Total volume for a bodyweight-heavy session is 0 or NULL.
- Any muscle group whose volume is exactly 0 across all weeks.
- Weekly tonnage that correlates with warm-up count rather than working sets.
- `SUM(weight_kg * reps)` appearing without a `set_type` filter beside it.

**Phase to address:** **Phase 3**. Add the fixture-diversity requirement to the phase's exit criteria.

---

### Pitfall 9: Two sources of truth for body weight

**What goes wrong:**
`PROJECT.md` scopes body measurements to manual entry. But Hevy's API has a full `/v1/body_measurements` resource (weight, lean mass, fat %, and 15 circumference fields) — and the user, who owns a Hevy Pro subscription, is plausibly already logging weight there. If both paths exist, the weight-trend analytic (7/14/30-day moving averages) reads from a table that has some days from Hevy and some typed into BRETT, with no conflict rule. Moving averages over an inconsistently-populated series produce trend lines that flip sign depending on which source happened to have data that week — and recomposition-status classification is built directly on top of that trend.

Additionally, Hevy's `PUT /v1/body_measurements/{date}` documents **"All fields are overwritten; omitted fields are set to null"** — a write path that silently destroys data. (Not a v1 concern since MCP is read-only, but a trap for milestone 2.)

**Why it happens:**
The blueprint predates (or overlooked) the body-measurements endpoint, so "manual entry" was the only option considered. The endpoint's existence changes the calculus.

**How to avoid:**
- **Decide the source-of-truth policy in Phase 1, when the schema is designed**, not in Phase 3 when the trend math breaks. Model `body_measurements` with `(user_id, source, measured_on)` unique and an explicit precedence order (`hevy` > `manual`, or vice versa) resolved in a single view/query — the same shape the blueprint already uses for workouts.
- Ask the user whether they log weight in Hevy. If yes, **sync it in Phase 2** — it's one more paginated endpoint against an already-built client, and it removes a manual-entry chore that will otherwise be skipped, leaving the recomposition analytics data-starved.
- Weight-trend analytics must handle **irregular sampling** regardless of source: a "7-day average" over 2 data points is not a 7-day average. Return the sample count alongside every trend value, and refuse to classify recomposition status below a minimum sample threshold rather than emitting a confident label from 2 points.
- Note the `POST` → **409 on existing date** behaviour and the destructive `PUT` semantics in `integrations/hevy/README.md` now, so milestone 2 doesn't rediscover them by overwriting real measurements.

**Warning signs:**
- Weight-trend output changes materially when a single measurement is added.
- Recomposition status flips between adjacent runs.
- Two rows for the same date with different weights.

**Phase to address:** **Phase 1** (schema + precedence), **Phase 2** (optional Hevy sync), **Phase 3** (sample-count guards).

---

### Pitfall 10: Building against MCP knowledge that is one breaking revision stale

**What goes wrong:**
The MCP spec's **current revision is `2026-07-28`** — released 26 days before this research. It removed the `initialize`/`initialized` handshake, removed protocol-level sessions (`Mcp-Session-Id`), removed the GET stream endpoint and `Last-Event-ID` resumability, and deprecated Roots, Sampling, and Logging. The Python SDK shipped **`mcp` 2.0.0 on the same day**, renaming the high-level server class from `FastMCP` to `MCPServer` (`from mcp.server import MCPServer`, previously `from mcp.server.fastmcp import FastMCP`).

Any MCP server code an assistant writes from memory will be v1/`FastMCP`-shaped. If you `pip install mcp` unpinned today you get 2.0.0 and the code won't import. If you pin to 1.x you get an SDK aligned with a superseded spec revision — and, critically, **you don't know which revision Claude's connector infrastructure currently speaks**, so you need the SDK's dual-era compatibility handling rather than a hand-rolled transport.

**Why it happens:**
This is the training-data-as-hypothesis failure mode in its purest form: MCP is churning faster than any model's cutoff, and the transport is exactly the layer where a stale mental model produces "connects locally, fails from Claude."

**How to avoid:**
- **Pin `mcp` exactly** in `pyproject.toml` (`mcp==2.0.0` or whatever is current at Phase 4 start) and record the pinned version + spec revision in the Key Decisions table.
- **Do not hand-roll the transport.** Let the SDK own protocol-version negotiation and backward compatibility with the `2025-03-26`…`2025-11-25` era. The SDK has an explicit "legacy clients" code path; use it.
- **Re-read the SDK docs at the start of Phase 4** rather than trusting any code in this repo's planning docs (including this file). Verify: the class name, `streamable_http_app()`'s signature, `stateless_http`, and `TransportSecuritySettings`.
- Have the MCP server report its protocol/SDK version on a plain `/health` route so a mismatch is diagnosable from outside.
- Assume this will churn again. Keep MCP tool handlers as thin adapters over the analytics layer (blueprint already requires analytics to live outside MCP handlers — enforce it) so an SDK migration touches one directory.

**Warning signs:**
- `from mcp.server.fastmcp import FastMCP` in new code.
- Any unpinned `mcp` dependency.
- Code that manually constructs `initialize` responses or manages `Mcp-Session-Id`.
- Handshake works in MCP Inspector (which tracks the newest spec) but fails from Claude, or vice versa.

**Phase to address:** **Phase 4**, first task.

---

### Pitfall 11: Mounting the MCP app in FastAPI without wiring its lifespan (and the localhost-only default)

**What goes wrong:**
Two failure modes, both of which pass local smoke tests and then break:

1. **"Task group is not initialized."** `mcp.streamable_http_app()` ships its own lifespan that starts the session manager. **Mounting it inside a parent FastAPI/Starlette app disables that lifespan.** Every request then fails at runtime. The SDK's own troubleshooting page documents this exact error. Fix: the *host* app's lifespan must enter `mcp.session_manager.run()`. This is directly relevant because the blueprint (§45) plans to run `fitness-api` and `fitness-mcp` in one service.
2. **Works on localhost, 4xx on Render.** The SDK's DNS-rebinding protection is **on by default** and, per the SDK docs, the app "only responds to requests addressed to localhost" unless you configure `TransportSecuritySettings(allowed_hosts=[...])`. On Render the `Host` header is `brett-xyz.onrender.com`, so every request is rejected — after a green deploy, with no application error.

Related, from the spec: servers **MUST** validate the `Origin` header and return **403** when it's present and invalid. Anthropic's connector traffic originates from Anthropic's cloud, not the user's browser, so an over-tight `allowed_origins` list is another way to lock out the only client you care about.

**Why it happens:**
Both defaults are *correct security defaults for local stdio-adjacent servers* and both become wrong the moment you deploy behind a hostname. Neither produces a startup error — they fail at request time, after "deploy succeeded."

**How to avoid:**
- Parent-app lifespan **must** wrap `async with mcp.session_manager.run(): yield`. If you ever mount two MCP servers, the shared lifespan enters both.
- Set `TransportSecuritySettings(allowed_hosts=["<your-host>", "<your-host>:*"])` from an env var (`MCP_ALLOWED_HOSTS`) so local, preview, and production differ by config, not code. Include both the bare host and the `:*` wildcard-port form — the SDK docs call this out explicitly.
- Be **permissive on `allowed_origins`** (or leave it unset) for a non-browser client; Anthropic's IP ranges and Origin behaviour aren't something you control. Alternatively, if Render's proxy already normalises `Host`, `enable_dns_rebinding_protection=False` plus your own auth is a documented, defensible choice — just make it a deliberate one.
- Ordering matters: define your own routes **before** the `Mount`, or the MCP app swallows them.
- Add a Phase 5 exit criterion that is a real HTTP call from outside your network — `curl` a `tools/list` against the deployed HTTPS URL with a correct `Accept: application/json, text/event-stream` and `MCP-Protocol-Version` header — not just "the deploy is green."

**Warning signs:**
- `RuntimeError: Task group is not initialized` in Render logs.
- 400/403 on `/mcp` from the internet while `curl localhost` works in a local container.
- `/health` returns 200 but `/mcp` doesn't.

**Phase to address:** **Phase 4** (lifespan), **Phase 5** (transport security + external verification).

---

### Pitfall 12: Proxy buffering, cold starts, and the 60-second initialize window

**What goes wrong:**
Remote MCP over Streamable HTTP is a long-lived-response protocol running through a reverse proxy. Three interacting failures:

1. **Buffering.** Reverse proxies (nginx and friends) buffer responses by default; an SSE response gets held in a buffer instead of streamed. The MCP spec says servers **SHOULD** send `X-Accel-Buffering: no` when initiating an SSE stream, precisely for this. Symptom: the connector hangs and eventually times out, with a perfectly healthy server.
2. **Cold starts.** Render's **free web services spin down after 15 minutes of inactivity and take roughly a minute to spin back up**. Claude cancels the connection if the server doesn't respond to its opening request within about 60 seconds. A connector you use twice a day will be cold nearly every time — so the *first* tool call of every session lands in the worst case, and the user experiences BRETT as "the connector that never works."
3. **Idle timeouts** on quiet connections, plus VPN/zero-trust agents that selectively break long-lived HTTPS streams while normal web traffic looks fine.

**Why it happens:**
Everything is tested locally where there's no proxy, no spin-down, and no timeout. "It's just HTTPS" hides that this is a streaming protocol.

**How to avoid:**
- **Use a paid Render instance type for the MCP service.** This is the cheapest possible fix for the highest-frequency user-visible failure. If cost is a real constraint, a cron-based keepalive ping every 10 minutes is a workaround — but it also burns the 750 free instance-hours/month allowance, so it isn't actually free.
- Emit `X-Accel-Buffering: no` on SSE responses (verify the SDK does this; add it via middleware if not).
- Keep tool handlers **fast** — target well under 5 seconds. All analytics should be plain SQL over indexed columns. Don't trigger a Hevy sync inside a tool call (Pitfall 15).
- Make DB connection acquisition cheap on cold start: modest pool size, `pool_pre_ping=True` (Render Postgres will drop idle connections), and no heavyweight work in the app lifespan.
- **Verify from a phone on cellular**, not just from your laptop, as a Phase 5 exit criterion. That's the path that exercises Anthropic's cloud → Render, cold.

**Warning signs:**
- Connector works immediately after a deploy, fails hours later.
- Intermittent "connection failed"/timeout in Claude with no corresponding error in Render logs (the request never arrived, or the response never flushed).
- Any tool handler that does network I/O.

**Phase to address:** **Phase 5**.

---

### Pitfall 13: Feeding Claude raw data instead of answers

**What goes wrong:**
`fitness_get_recent_workouts(limit=20)` returns every set of every exercise. Twenty workouts × 6 exercises × 4 sets × ~10 JSON fields is thousands of tokens of near-identical structure. Real limits: **Claude Code rejects tool results above ~25,000 tokens** (`MAX_MCP_OUTPUT_TOKENS`), and Claude Desktop caps around **150,000 characters**, with truncation that is lossy and position-biased — it keeps the beginning and drops the rest, so the *newest* or *oldest* data (whichever you sorted last) silently vanishes and Claude reasons over a partial series without knowing it.

Separately, **15 tools with verbose JSON schemas is itself a context cost** paid on every single conversation turn, before any data is fetched. Overlapping tools (`fitness_get_training_summary` vs `fitness_get_weekly_volume` vs `fitness_compare_periods`) also make tool *selection* unreliable — the model picks the wrong one, gets a plausible answer, and never realises.

**Why it happens:**
The tool list in the blueprint (§29) is a data-model inventory, not a task inventory. And "return structured JSON" gets read as "return the rows."

**How to avoid:**
- **Aggregate server-side. Always.** The whole point of the analytics layer is that the MCP returns *computed* values. `fitness_get_weekly_volume` returns ~12 rows of `{week_start, hard_sets, tonnage_kg}`, not sets.
- Every list-returning tool gets a **`limit` with a sane default and a hard server-side maximum**, and returns a `truncated: true` flag plus `total_available` when it clips — so Claude *knows* it's looking at a subset and can say so.
- **Budget tokens explicitly:** target < 2,000 tokens per tool response; treat > 5,000 as a bug. Add a test that asserts serialized response size for a realistic dataset — cheap to write, catches this permanently.
- **Compact JSON shapes:** short key names, ISO dates as strings, round floats to 1–2 decimals (`117.30000000000001` kg of tonnage is noise), omit null fields rather than emitting `"rpe": null` thousands of times.
- **Start with 6–8 tools, not 15.** Ship the ones that answer the two questions in the Core Value statement ("Am I progressing?", "Which muscles are undertrained?") and add more only when a real conversation demonstrably needs one. Make tool descriptions crisply non-overlapping and state *when to use this instead of that*.
- Keep one deliberately verbose escape hatch (`fitness_get_workout(workout_id)`) for drill-down, and make the summary tools return IDs so Claude can drill down on demand. That's the pattern that keeps context small without losing fidelity.

**Warning signs:**
- "MCP tool response exceeds maximum allowed tokens" in Claude.
- Claude summarising 20 workouts but only ever mentioning the first few.
- A tool handler that does `.all()` on a query with no limit.
- Two tools whose descriptions you can't distinguish in one sentence each.

**Phase to address:** **Phase 4**.

---

### Pitfall 14: Silent staleness — Claude answering confidently from a database that stopped syncing

**What goes wrong:**
The Render cron job fails (bad deploy, expired Hevy key, rate limit, the cursor bug in Pitfall 4). Nothing is on fire: the API is up, the MCP responds, tools return well-formed JSON. But the data is three weeks old. The user asks "am I progressing?" and Claude answers, fluently and completely wrongly, from stale data — and there is nothing in the response that would let it know or hedge.

This is the most dangerous failure in the whole system because **every safety property of the design is intact** and the output is still wrong. A read-only MCP can't corrupt anything; it can still mislead.

**Why it happens:**
Sync is a background job with no user-facing surface. Failures are logged, and nobody reads logs for a personal project. The blueprint's `last_synced_at` requirement (§39) exists but is easy to implement as a display field rather than a guardrail.

**How to avoid:**
- **Every tool response carries freshness, unconditionally.** Not a separate `fitness_get_data_freshness` tool that Claude has to think to call — an envelope field on every response: `{"data_as_of": "...", "hevy_last_synced_at": "...", "staleness_hours": 62, "stale": true}`.
- **Make staleness loud when it matters.** If `staleness_hours > 24`, prepend a human-readable warning string to the response content so it lands in Claude's context as text, not just as a field it might ignore. Encode the expected behaviour in the fitness-coach system prompt too ("if `stale` is true, say so before answering").
- Track **three distinct timestamps** and don't conflate them: `last_sync_attempted_at`, `last_sync_succeeded_at`, `last_source_data_at`. A job that runs every 6 hours and fails every time has a recent *attempt* and an ancient *success*.
- Persist a `sync_runs` table (started, finished, status, records imported/updated/deleted, error class, correlation id) and expose the last N through an admin endpoint. This is also your forensic record when Pitfall 4 or 5 bites.
- **Post-sync invariant checks** that fail loudly: `workout_count` from `/v1/workouts/count` vs `COUNT(*) WHERE deleted_at IS NULL`; zero workouts with zero exercises; zero sets with `reps IS NULL AND duration_seconds IS NULL AND distance_meters IS NULL`. A mismatch means sync is broken *now*, not in three weeks.
- One outbound alert (email/webhook/ntfy) on N consecutive sync failures. For a personal project this is the difference between finding out in an hour and finding out in a month.

**Warning signs:**
- `last_synced_at` exists in the DB but appears in no tool response.
- No record of *failed* syncs anywhere — only successful ones write rows.
- Nobody can answer "when did sync last succeed?" without SSH'ing into Render.

**Phase to address:** **Phase 2** (sync run tracking + invariant checks), **Phase 4** (freshness in every response), **Phase 5** (alerting).

---

### Pitfall 15: Triggering sync from an MCP tool call

**What goes wrong:**
It's tempting to make `fitness_get_recent_workouts` "refresh first, then read" so data is always current. This puts 5–60 seconds of paginated third-party HTTP inside a request that Claude will abandon at its timeout, makes the read path fail whenever Hevy is down or rate-limiting, lets concurrent tool calls run overlapping syncs against a shared cursor (the exact race Pitfall 4's two-phase commit assumes doesn't happen), and converts an explicitly read-only MCP surface into one with a write side-effect — undermining the security argument in blueprint §31 that read-only is what makes remote exposure acceptable.

**Why it happens:**
It's the obvious fix for Pitfall 14, and it feels like better UX.

**How to avoid:**
- **Sync is a scheduled job. Tools read committed state only.** Period. Enforce it structurally: the MCP tool module should not import the Hevy client at all — a lint rule or an import test can make this permanent.
- Solve freshness by *reporting* it (Pitfall 14), not by fetching on read.
- If manual refresh is genuinely needed, expose it as an authenticated **REST** endpoint on the API service (`POST /admin/sync/hevy`) that the user can hit from a browser or shortcut — not as an MCP tool.
- Guard the sync job with a DB advisory lock so overlapping runs (cron overlap, manual + scheduled) can't interleave.

**Warning signs:**
- `from app.integrations.hevy import ...` inside `app/mcp/`.
- Tool p95 latency above a couple of seconds.
- Sync-related errors surfacing as tool errors in Claude.

**Phase to address:** **Phase 4** (structural boundary), **Phase 2** (advisory lock).

---

### Pitfall 16: Timezone and week-boundary bugs that make every time-bucketed metric subtly wrong

**What goes wrong:**
Everything in this system is time-bucketed — weekly volume, 7/14/30-day averages, training frequency, period comparison, plateau windows. Failure modes:

- **Grouping by UTC day.** A 19:00 Jakarta workout is 12:00 UTC (fine), but a 06:00 Jakarta session is 23:00 UTC the *previous* day. Sessions land in the wrong week, and "training frequency" undercounts or double-counts.
- **`date_trunc('week', ...)` in Postgres is ISO (Monday-start)** and operates on whatever timezone the input is in. Mixing `date_trunc` on UTC timestamps with a user-facing Monday-start week gives boundaries that are 7 hours off — so a Sunday-night or Monday-morning session hops weeks.
- **Asia/Jakarta has no DST**, which makes `+07:00` *work* during development. That's the trap: it lulls you into hard-coding an offset, and the code becomes silently wrong for any other user (and the blueprint explicitly requires configurability).
- **Workouts spanning midnight.** `start_time` and `end_time` can straddle a local day boundary. Pick `start_time` as the canonical bucketing timestamp and apply it *everywhere*, or two metrics will disagree about which day a session belongs to.
- **"Last 8 weeks"** — is week 1 the current (partial) week? A partial current week always looks like a volume drop, which plateau detection happily reports as a plateau.

**Why it happens:**
Timezone handling is written once, early, in one query, and then copy-pasted into eight more analytics functions. Testing happens in the user's own timezone where the bug is invisible.

**How to avoid:**
- **Store UTC (`TIMESTAMPTZ`), bucket in local.** One shared helper: `local_day(ts) = (ts AT TIME ZONE :user_tz)::date`, and `local_week(ts)` built on it. Every analytics query calls the helper. Zero raw `date_trunc` calls outside it.
- Put `timezone` on the `users` table with a default of `Asia/Jakarta`, and read it — never a constant, never an env var used as the source of truth.
- Define the week start **once** (Monday) in `docs/analytics-definitions.md` and make it a parameter of the helper.
- **Exclude or explicitly flag the current partial week** in every trend/plateau calculation. Return `{week_start, is_partial: true}` so Claude can discount it.
- **Test with adversarial fixtures:** a workout at 23:30 local on a Sunday, one at 00:15 local on a Monday, one starting 23:45 and ending 00:50. Assert exact bucket assignment. Also run the whole analytics suite with `user_tz = America/Los_Angeles` (UTC−8, *with* DST) — if any number changes in a way you can't explain, the helper is being bypassed somewhere.

**Warning signs:**
- Any `AT TIME ZONE 'UTC'`, `date_trunc('week', ...)`, or `+7` outside the shared helper.
- Weekly volume showing a sharp drop in the most recent week, every time you look.
- Training frequency for a known 4-day week reporting 3 or 5.

**Phase to address:** **Phase 1** (user timezone in schema, helper module), **Phase 3** (every analytic uses it).

---

### Pitfall 17: Underestimating what it means to pipe personal health data into an LLM

**What goes wrong:**
Read-only + HTTPS + a token is the *transport* security story. It is not the *data* security story. Specific exposures for this system:

1. **Free text from Hevy flows straight into Claude's context.** `workout.title`, `workout.description`, and `exercise.notes` are user-authored strings that BRETT will faithfully relay. Any instruction-shaped text in them is read by Claude as content. In a single-user, self-authored system this is low-likelihood — but the mitigation is nearly free, and the field is *not* fully self-authored if routines are ever imported or shared.
2. **The lethal trifecta.** The recognised risk pattern is an agent that can simultaneously (a) read untrusted external content, (b) access sensitive data, and (c) communicate outward. Enabling the BRETT connector supplies (b). The same Claude conversation typically has web search (a) and other connectors (c). Read-only-ness on BRETT's side does not prevent BRETT's data from being exfiltrated *by* another tool in the same session. This is the strongest argument for keeping the exposed data minimal and for not enabling BRETT alongside browsing tools in the same conversation when discussing sensitive detail.
3. **Data leaves your control on every tool call.** Body weight, body-fat percentage, waist measurements, and training history enter Anthropic's infrastructure and conversation history. That's an accepted, deliberate trade for this project — but it should be a *recorded* decision, and it argues directly for data minimisation.
4. **Health-adjacent inference.** `PROJECT.md` correctly frames recomposition status as decision-support, not medical/diagnostic. That framing has to live in the tool descriptions and response payloads, not only in a system prompt the user might not attach — because the system prompt is optional and the tool description is not.
5. **Log leakage.** Blueprint §33/§44 say don't log health data or secrets. The paths that actually leak in practice are the ones nobody classifies as "logging": unhandled exception tracebacks containing the DB DSN with password, `httpx` debug logging echoing the `api-key` header, FastAPI validation errors echoing request bodies, and error responses returned to Claude that include a stack trace.

**Why it happens:**
"Read-only" is treated as a complete security argument. It closes the *integrity* hole and leaves the *confidentiality* one wide open.

**How to avoid:**
- **Minimise at the tool boundary.** Return only what answers the question. Body-fat percentage and circumference measurements should be returned by tools that *need* them, not bundled into a general summary.
- **Neutralise free text**: cap `title`/`description`/`notes` length (e.g. 200 chars), strip control characters, and clearly delimit them as data in the response (e.g. nest under a `user_text` key rather than interleaving with computed fields). Consider omitting `description`/`notes` from list tools entirely and exposing them only in the single-workout drill-down.
- **Never build tool output by string-formatting user text into a sentence.** Emit structured JSON and let Claude do the prose.
- **Scrub logs structurally, not by discipline:** a logging filter that redacts `api-key`, `authorization`, `password`, and any `postgres://` URL; `httpx` log level pinned above DEBUG in production; a global exception handler that returns a correlation ID to the caller and logs the detail server-side. Add a test that asserts the configured secret string never appears in captured log output during a full sync.
- **Bound the token's blast radius:** short-lived tokens (if OAuth) or a rotatable secret, per-IP + per-token rate limiting on `/mcp`, and a documented revocation procedure (rotate `MCP_AUTH_SECRET` in Render → connector must re-auth). Verify revocation actually works before trusting it.
- **Record in Key Decisions** that health data is intentionally exposed to Anthropic's infrastructure, so it's a decision rather than an oversight.

**Warning signs:**
- Tool responses that include fields no tool description mentions.
- A Render log line containing `postgres://` or a UUID that looks like the Hevy key.
- Error responses to Claude containing file paths or stack traces.
- No rate limit on `/mcp` (the blueprint requires one — verify it exists and is actually reachable, i.e. applied before auth so it also throttles unauthenticated probes).

**Phase to address:** **Phase 1** (log scrubbing, exception handler), **Phase 4** (minimisation, text neutralisation, rate limiting), **Phase 5** (rotation/revocation drill).

---

### Pitfall 18: Deploying the source of truth onto storage that expires

**What goes wrong:**
Render's **free PostgreSQL databases expire 30 days after creation**, with a 14-day grace period before the database *and its data* are deleted. Blueprint §2.3 makes PostgreSQL the source of truth for the entire platform. Thirty days after a "let's just get it deployed" Phase 5, the source of truth is gone.

The damage is partly recoverable (re-sync from Hevy) and partly not: manual body measurements, manual nutrition entries, exercise-mapping overrides, and sync history exist only in your database. Hevy has none of it.

**Why it happens:**
Free tier is chosen for a personal project during Phase 1 local setup, and the expiry clock starts at *creation*, silently, weeks before anything depends on it.

**How to avoid:**
- **Provision paid Postgres from the start** if BRETT is meant to persist. It's the cheapest line item in the project and the only one holding irreplaceable data.
- Regardless of tier: a **scheduled `pg_dump` to object storage**, and — this is the part people skip — **one verified restore** into a scratch database before Phase 5 is called done. An untested backup is not a backup.
- Treat the DB as the system of record for the derived/manual data and Hevy as the system of record for workouts. Write down which is which; it determines what a restore actually costs.
- Also watch: free web services get **750 instance-hours per workspace per month**, after which free services are suspended. Two always-on free services will exhaust that.

**Warning signs:**
- A free-tier Postgres instance older than ~20 days with production data in it.
- No `pg_dump` anywhere in the repo or Render cron config.
- Nobody can state what is lost if the DB disappears tonight.

**Phase to address:** **Phase 1** (provision correctly), **Phase 5** (backup + verified restore as an exit criterion).

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Full re-sync every run instead of the events endpoint | Skips all cursor logic; trivially "idempotent" | 10× request volume against an undocumented rate limit; deletions are **never** detected (phantom workouts accumulate forever) | Only as a manual `--force` repair path, never as the scheduled job |
| Hard delete on `deleted` events | One line of code | Historical analytics silently rewrite; deletions become un-auditable; PR caches desync | Never |
| Analytics logic inside MCP tool handlers | One less layer; faster to demo | Untestable without an MCP client; an SDK upgrade (which just happened, see Pitfall 10) rewrites your business logic; blocks reuse by a future iOS app | Never — the blueprint already forbids it; enforce with an import test |
| `SUM(weight_kg * reps)` with no set-type or exercise-type filter | Ships in an hour; looks right on barbell fixtures | Every downstream metric (progression, plateau, muscle balance, recomp status) inherits the error; Claude reports it confidently | Never — this is the load-bearing calculation |
| `rir` / `weight_unit` columns "for later" | Schema feels future-proof | Permanently-NULL columns invite conversion code that runs on already-normalized data; misleads future readers into thinking RIR analytics are possible | Never — add via migration if the API ever gains them |
| Skipping the raw-payload column | Smaller rows, simpler model | The only way to distinguish an ingestion bug from a math bug, six months later, is gone | Never — `jsonb` is cheap at this scale |
| Free Render Postgres | Zero cost | Data deleted at 30 days + 14 grace (Pitfall 18) | Only for a throwaway preview environment with no real data |
| Free Render web service for MCP | Zero cost | 15-min spin-down + ~60s cold start vs Claude's ~60s initialize window → the connector feels broken (Pitfall 12) | For the API service maybe; for the MCP service, no |
| Secret-in-URL as the MCP auth mechanism | Works with Claude's connector UI today, zero code | Blueprint §32 forbids it; leaks via proxy logs, screenshots, crash reports; no revocation short of changing the URL and re-adding the connector | Only layered *under* real auth, never alone |
| Hardcoding `+07:00` for Jakarta | Correct output today (no DST) | Silently wrong for any other timezone; violates the configurability requirement; discovered only when someone else uses it | Never — the helper costs 5 lines |
| Shipping all 15 blueprint tools at once | Feels complete | Schema bloat on every turn; overlapping tools cause wrong selection; 15 surfaces to keep correct | Never — start with 6–8 |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Hevy auth | `Authorization: Bearer <key>` | `api-key: <uuid>` header — a *custom header*, and the value is UUID-formatted |
| Hevy pagination | `pageSize=100` | Max **10** on workouts/events/routines/folders/measurements (400 "Invalid page size" otherwise); **100** only on `exercise_templates` |
| Hevy pagination loop | Loop until an empty page | Use the `page_count` field in the response envelope; note `/v1/body_measurements` documents a **404** for out-of-range pages |
| Hevy events ordering | Assume oldest-first, advance cursor per page | **Newest-first.** Drain all pages, apply oldest-first, commit cursor once, with a 5-minute overlap |
| Hevy events cursor | `since = timestamp of last event seen` | `since = (time captured before the run) − 5 min`, written only on full success |
| Hevy child objects | Upsert exercises/sets by `(parent, index)` | No stable IDs exist — delete-and-reinsert children inside one transaction |
| Hevy exercise identity | Match on `exercise.title` | Match on `exercise_template_id`; get muscle groups from `/v1/exercise_templates`, not a hand-built name table |
| Hevy set semantics | Treat all sets equally | Filter on `set.type` (`normal`/`warmup`/`dropset`/`failure`); branch on the template's exercise `type` (8 values) |
| Hevy rate limits | Assume none (spec documents none) | Assume they exist: concurrency 1–2, `Retry-After`-aware 429 backoff, and **log observed limits** into the integration README |
| Hevy body measurements `PUT` | Partial update | **"All fields are overwritten; omitted fields are set to null"** — read-modify-write, or don't write at all (v1 is read-only anyway) |
| Hevy API stability | Treat as a stable contract | `version: 0.0.1`; Hevy's own docs say they may "completely change the structure or abandon the project entirely." Snapshot the OpenAPI spec, diff in CI, isolate in `integrations/hevy/` |
| Claude custom connector | Paste a bearer token into connector settings | Not possible — OAuth-only UI ([#112](https://github.com/anthropics/claude-ai-mcp/issues/112), closed as not planned). Implement a minimal OAuth 2.1 shim or accept desktop-only |
| MCP Python SDK | `from mcp.server.fastmcp import FastMCP` | `from mcp.server import MCPServer` in `mcp` 2.x — and **pin the version** |
| MCP mounted in FastAPI | Just `app.mount("/mcp", mcp.streamable_http_app())` | Mounting disables the MCP lifespan — the host lifespan must enter `mcp.session_manager.run()` |
| MCP transport security | Leave defaults; deploy | Default DNS-rebinding protection responds to **localhost only** — set `TransportSecuritySettings(allowed_hosts=["host", "host:*"])` |
| MCP + reverse proxy | Assume SSE streams through | Send `X-Accel-Buffering: no`; test through the real proxy, not localhost |
| MCP client compatibility | Require a strict `Accept` header | The spec requires clients to send `application/json, text/event-stream`; **many clients don't**, and strict servers return 406. Be lenient on input, correct on output |
| MCP protocol version | Hand-roll the handshake | The `2026-07-28` revision removed `initialize`, sessions, and the GET stream — let the SDK handle multi-era negotiation |
| Render start command | `uvicorn app:app` | `--host 0.0.0.0 --port $PORT` — without `0.0.0.0` Render cannot reach the container even though startup logs look fine |
| Render Postgres | Use the free tier for real data | Free DBs expire 30 days after creation (+14-day grace, then deleted). Use `pool_pre_ping=True` for dropped idle connections |
| Alembic on Render | Run migrations at app startup | Run in a release/pre-deploy command; startup migrations race across multiple workers and can deadlock |

---

## Performance Traps

Expected scale is one user, a few hundred to a few thousand workouts, ~100k sets over a decade. Postgres will not break a sweat. The traps that matter here are **latency-under-cold-start** and **context-window**, not throughput.

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| N+1 queries in MCP tool handlers (workout → exercises → sets via lazy loading) | Tool call takes seconds; hundreds of queries per call | `selectinload`/`joinedload`, or aggregate in SQL and never materialize ORM objects for analytics | ~50 workouts in one response — i.e. immediately |
| Recomputing 12 weeks of volume from raw sets on every call | Tool latency creeps up; worsens as history grows | Aggregate in SQL with proper indexes; add a materialized view or a `weekly_volume_cache` table only if measured latency demands it | ~2–3 years of history, or sooner on a cold/small Render instance |
| Missing indexes on the analytics access paths | Sequential scans; latency grows linearly with history | Index `workouts(user_id, start_time)` (with `deleted_at`), `workout_exercises(workout_id)`, `sets(workout_exercise_id)`, `workout_exercises(exercise_template_id)`. `EXPLAIN ANALYZE` the three heaviest analytics queries as a Phase 3 exit criterion | ~1,000 workouts |
| Unbounded tool responses | 25k-token rejection or silent truncation | Hard server-side limits + `truncated`/`total_available` flags (Pitfall 13) | ~20 full workouts in one response |
| Tool-schema bloat (15 tools × verbose schemas) | Context consumed before any data is fetched; wrong tool selected | 6–8 tools, terse descriptions, minimal schemas | Immediately — it's a fixed per-turn cost |
| Cold start + connection pool warm-up inside Claude's ~60s initialize window | Intermittent connector failures with no server-side error | Paid instance or keepalive; small pool; `pool_pre_ping`; no heavy lifespan work | Every 15 minutes of idle on Render free |
| Sequential full sync at `pageSize=10` | Bootstrap takes minutes; risks job timeouts | Bounded concurrency (1–2), resumable page cursor, request-count logging | ~500 workouts |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Relying on an unguessable `/mcp` URL as the only auth | URLs leak via proxy logs, screenshots, crash reports; no revocation path | Real auth (OAuth shim or bearer) **plus** optionally a path secret; never the path alone (blueprint §32) |
| Non-constant-time comparison of the MCP secret | Timing side channel on a public endpoint | `hmac.compare_digest`, never `==` |
| Rate limiting applied *after* auth | Unauthenticated attackers can brute-force the token unthrottled | Rate limit by IP **before** the auth check; separately limit per authenticated token |
| Accepting a token not issued for this server (if OAuth) | Token replay across services; the spec **forbids** passthrough | Validate the `aud`/resource claim against your own MCP URL (RFC 8707 resource indicators); reject tokens minted for anything else |
| No `Origin` validation | DNS-rebinding class attacks | Spec: servers **MUST** validate `Origin` and return **403** when present and invalid — the SDK's `TransportSecuritySettings` does this; configure it, don't disable it blindly |
| Hevy `api-key` echoed in debug logs or error responses | Full read/**write** access to the user's Hevy account leaks (the API has POST/PUT endpoints) | `httpx` log level above DEBUG in prod; a redaction log filter; a test asserting the secret never appears in captured logs |
| DB DSN in an unhandled traceback | Database credentials leak to logs, or to Claude via an error response | Global exception handler returning a correlation ID only; detail logged server-side |
| Health data in application logs "for debugging" | Sensitive data persisted in a third-party log store indefinitely | Log counts, IDs, and durations — never sample values (blueprint §44) |
| Trusting Hevy free text as safe | Instruction-shaped content in `title`/`description`/`notes` reaches the model as context | Length-cap, strip control chars, nest under a clearly-data key, omit from list tools |
| Enabling BRETT alongside browsing/other connectors in a session handling sensitive detail | Lethal trifecta: sensitive data + untrusted content + an exfiltration channel in one context | Minimise what tools return; document the risk; treat "read-only" as insufficient on its own |
| Adding a write tool "just for nutrition entry" | Every write tool is a new destructive surface reachable via prompt injection | v1 stays read-only (blueprint §31). Manual entry goes through the REST API, not MCP |
| No secret-rotation procedure | A leaked token can't be revoked in practice | Document and **rehearse** rotation in Phase 5; confirm the connector actually loses access |
| `.env` or the OpenAPI snapshot containing a real key committed | Permanent credential exposure in git history | `.gitignore` + a pre-commit secret scanner; the Hevy key is a UUID, which is greppable |

---

## UX Pitfalls

"User" here means the user *via Claude*. The UX surface is the shape of the tool responses.

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| No freshness in responses | Claude confidently analyses three-week-old data; trust in the whole system collapses on discovery | Freshness envelope on **every** response + a loud warning above a staleness threshold (Pitfall 14) |
| `0` used for "not applicable" | "Your lats are undertrained" when the user does pull-ups every session | Emit `null`/omit, plus an explicit `not_applicable_reason` where useful |
| Metrics with no stated methodology | User can't reconcile BRETT's numbers with the Hevy app's and assumes BRETT is broken | Ship `docs/analytics-definitions.md`; put the definition in the tool description; return a `methodology` field |
| Confident output from insufficient data | "You've plateaued" from 3 data points; "you're recomping" from 2 weigh-ins | Return `sample_size` / `weeks_of_data`; refuse to classify below a threshold and say why |
| Partial current week counted as a real week | Every check-in looks like a volume decline; plateau detection fires constantly | Exclude or flag `is_partial` on the current week |
| Recomposition status phrased as a diagnosis | Health advice framed with unearned authority | Keep the decision-support framing in the tool description and payload, not just an optional system prompt |
| Overlapping tools with vague descriptions | Claude picks the wrong tool and answers a subtly different question | 6–8 tools with mutually exclusive, task-shaped descriptions stating when *not* to use them |
| Silently truncated lists | Claude reasons over a subset believing it's the whole | `truncated: true` + `total_available` + a drill-down ID so it can fetch more deliberately |
| Sync failures visible only in Render logs | User discovers the outage weeks later | Alert on N consecutive failures; expose `last_sync_succeeded_at` through the freshness envelope |

---

## "Looks Done But Isn't" Checklist

- [ ] **Hevy sync:** often missing the *deletion* path — verify by deleting a real workout in the Hevy app, running sync, and asserting it's soft-deleted and excluded from analytics.
- [ ] **Hevy sync:** often missing *mid-pagination failure* handling — verify with a mock that raises on page 2: cursor unchanged, DB unchanged, next run recovers everything.
- [ ] **Hevy sync:** often missing *edit* handling — verify by editing a synced workout in Hevy (remove one exercise, reorder two, change a weight), re-syncing, and asserting exact child-row state with no orphans or duplicates.
- [ ] **Idempotency:** often only asserted for workout count — verify total set count and total tonnage are byte-identical after 3 consecutive syncs.
- [ ] **Rate limiting:** often untested because it never fired in dev — verify with a mock returning 429 + `Retry-After` that the client backs off and completes rather than aborting mid-sync.
- [ ] **Exercise normalization:** often silently drops unmapped exercises — verify `SELECT DISTINCT exercise_template_id FROM workout_exercises` has zero rows without a template mapping, and that an unmapped ID raises a visible warning.
- [ ] **Analytics:** often tested only on barbell fixtures — verify against a fixture set including bodyweight, assisted-bodyweight, duration-only, dropset, warm-up-heavy, and superset workouts.
- [ ] **Analytics:** often timezone-correct only in the dev timezone — verify the whole suite with `user_tz = America/Los_Angeles` and with workouts at 23:30 / 00:15 local.
- [ ] **Analytics:** often silently wrong on partial weeks — verify the current week is excluded or flagged in every trend/plateau output.
- [ ] **MCP auth:** often verified only with MCP Inspector or `--header` — verify by **adding the connector in claude.ai and calling a tool from a phone**.
- [ ] **MCP auth:** often missing the negative test — verify a request with no token, a wrong token, and an expired token each returns 401 (with a `WWW-Authenticate` challenge if OAuth) and leaks nothing.
- [ ] **MCP transport:** often only tested on localhost — verify `curl` from outside your network against the deployed HTTPS URL with a correct `Accept` and `MCP-Protocol-Version` header returns a valid `tools/list`.
- [ ] **MCP transport:** often missing the cold-start case — verify a tool call after 20+ minutes of idle succeeds within Claude's timeout.
- [ ] **MCP responses:** often unbounded — verify serialized response size for the largest realistic dataset is under budget for every tool, with an automated assertion.
- [ ] **MCP responses:** often missing freshness — verify **every** tool response includes `data_as_of` / staleness, including error responses where meaningful.
- [ ] **Secrets:** often leak through debug logging — verify with a test that captures all log output during a full sync + tool call and asserts the Hevy key, DB password, and MCP secret never appear.
- [ ] **Deployment:** often missing migrations in the release step — verify a fresh deploy against an empty database succeeds end to end.
- [ ] **Deployment:** often missing a *verified* backup — verify a `pg_dump` actually restores into a scratch database.
- [ ] **Scheduled sync:** often never observed running unattended — verify the cron job has run successfully at least 3 consecutive times, unattended, before calling Phase 5 done.
- [ ] **End-to-end:** often stops at "the tool returns JSON" — verify the blueprint §43 test really runs mock-Hevy → sync → Postgres → analytics → MCP tool → asserted value in one test.

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Duplicate child rows from bad upsert (P2) | LOW | Truncate `workout_exercises`/`sets`, re-run full sync from `/v1/workouts` (workouts survive; nothing is lost because Hevy is the source of record for these) |
| Events skipped by premature cursor advance (P4) | LOW–MEDIUM | Reset `last_hevy_event_cursor` far back (or to epoch) and re-drain; idempotency makes replay safe. **This is why the two-phase commit is worth building — the recovery only works if idempotency holds.** |
| Phantom (undeleted) workouts from full-sync-only (P5) | LOW | Reconcile: fetch all IDs via `/v1/workouts`, soft-delete local rows not present. Do this as a periodic audit anyway |
| Wrong volume definition shipped (P8) | MEDIUM | Analytics are computed, not stored — fix the query and everything recomputes. Cost is trust: any conclusion Claude previously stated is suspect, and the user has to be told |
| Bearer-token auth unusable with the connector (P1) | MEDIUM | Add the OAuth shim (~1 day) *or* fall back to desktop-only. Cheap now, expensive after Phase 5 is declared done and the plan says "connected via connector" |
| MCP SDK/spec version mismatch (P10) | LOW–MEDIUM | Pin and upgrade; low **only if** tool handlers are thin adapters over the analytics layer. If business logic lives in handlers, this becomes a rewrite |
| Free Postgres expired and deleted (P18) | **HIGH** | Workouts: re-syncable from Hevy. Manual measurements, nutrition, exercise overrides, sync history: **unrecoverable without a backup.** This is the only genuinely irreversible failure in the project |
| Hevy API breaking change (their stated possibility) | MEDIUM | Contained to `integrations/hevy/` **if** provider isolation held; the OpenAPI snapshot diff tells you exactly what changed. Sprawled assumptions turn this into a project-wide refactor |
| Secret leaked in logs/git (P17) | MEDIUM–HIGH | Rotate the Hevy key at hevy.com, rotate `MCP_AUTH_SECRET`, re-add the connector. Git history requires rewriting or repo replacement |
| Timezone bug found after months of use (P16) | MEDIUM | Fix the helper and recompute (analytics are derived, so no data migration) — but every past conclusion is invalidated |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| 16 — Timezone / week boundaries | **Phase 1** | Analytics suite passes with `user_tz = America/Los_Angeles`; adversarial midnight-straddling fixtures assert exact buckets |
| 9 — Body-weight source of truth | **Phase 1** (schema), Phase 2 (optional sync) | `(user_id, source, measured_on)` unique constraint exists; precedence resolved in one place |
| 17 — Log leakage (partial) | **Phase 1** | Test captures all log output during sync + tool call; asserts no secret/DSN/health-sample appears |
| 18 — Expiring Postgres | **Phase 1** (provision), Phase 5 (backup) | Paid DB tier confirmed; `pg_dump` restored into a scratch DB successfully |
| 2 — Child-row idempotency | **Phase 2** | 3× re-sync → byte-identical set count and tonnage; edit-and-resync fixture asserts exact child state |
| 3 — pageSize=10 / rate limits | **Phase 2** | Scheduled job makes O(events) not O(history) requests; 429 mock test passes; observed limits documented in `integrations/hevy/README.md` |
| 4 — Events cursor / ordering | **Phase 2** | Failure-on-page-2 mock → cursor and DB unchanged; new-event-mid-drain mock → nothing lost |
| 5 — Soft delete | **Phase 2** | Full create/update/delete lifecycle test; grep confirms every analytics query filters `deleted_at IS NULL` |
| 6 — Schema matches the real API | **Phase 2** | Pydantic models generated from / diffed against the committed OpenAPI snapshot in CI; no all-NULL columns after full sync |
| 7 — Exercise normalization | **Phase 2** | Zero `exercise_template_id` values without a template mapping; no name-based matching in the codebase |
| 14 — Silent staleness (tracking) | **Phase 2** | `sync_runs` table records failures; post-sync invariant check compares `/v1/workouts/count` to local count |
| 8 — Volume math | **Phase 3** | Golden fixtures covering all 8 exercise types + warm-ups + dropsets + supersets, hand-computed expected values |
| 15 — No sync in tool calls (analytics separation) | **Phase 3/4** | Import test: `app/mcp/` does not import `app/integrations/` |
| 1 — Connector auth mechanism | **Phase 4** (design), Phase 5 (verify) | Tool call succeeds from claude.ai **on a phone**, through the real connector-add flow |
| 10 — SDK/spec version | **Phase 4** | `mcp` pinned exactly; SDK docs re-read at phase start; version recorded in Key Decisions |
| 11 — Lifespan + transport security | **Phase 4** (lifespan), Phase 5 (hosts) | No "Task group is not initialized"; external `curl` to the deployed `/mcp` returns valid `tools/list` |
| 13 — Response size / tool sprawl | **Phase 4** | Automated per-tool response-size assertion; ≤8 tools at launch with non-overlapping descriptions |
| 14 — Freshness in responses | **Phase 4** | Every tool response carries `data_as_of`; forced-stale test produces a visible warning |
| 17 — Data minimisation / text neutralisation / rate limiting | **Phase 4** | Response fields audited against tool descriptions; free-text capped and nested; rate limit fires before auth |
| 12 — Proxy buffering / cold start | **Phase 5** | Tool call after 20 min idle succeeds; verified from cellular, not LAN |
| 17 — Rotation / revocation | **Phase 5** | Rotation rehearsed; connector confirmed to lose access |
| 14 — Alerting | **Phase 5** | Cron runs unattended 3× successfully; a forced failure produces an actual alert |

**Phase-ordering implication:** the auth decision (Pitfall 1) is the only item that can invalidate the plan's *stated* deliverable, and it lands in Phase 4. Consider spiking it early — a 30-minute experiment adding a trivial "hello world" MCP server as a Claude custom connector, during or immediately after Phase 1, de-risks the entire back half of the roadmap and would let Phase 4 be scoped correctly.

---

## Sources

**Primary / authoritative (HIGH confidence)**

- Hevy public API OpenAPI specification — extracted 2026-08-23 from `https://api.hevyapp.com/docs/swagger-ui-init.js` (the embedded `swaggerDoc`; the Swagger UI HTML at `https://api.hevyapp.com/docs/` renders no content to fetchers). Source of all endpoint, parameter, limit, and schema facts above. Recommend committing a snapshot to `integrations/hevy/openapi-snapshot.json`.
- MCP specification, versioning page — https://modelcontextprotocol.io/specification/versioning (current revision **2026-07-28**)
- MCP specification 2026-07-28, Streamable HTTP transport — https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http (Origin MUST/403, `Accept` requirement, `X-Accel-Buffering: no`, removal of sessions/GET stream/`Last-Event-ID`, backward-compatibility rules)
- MCP Python SDK v2 documentation, via Context7 (`/websites/py_sdk_modelcontextprotocol_io_v2`) — ASGI mounting + lifespan, `TransportSecuritySettings`, `TokenVerifier` / `BearerAuthBackend`, `create_protected_resource_routes`, `stateless_http`, `FastMCP` → `MCPServer` migration
- PyPI `mcp` package metadata — 2.0.0 released 2026-07-28; 1.9.4 released 2025-06-12
- Anthropic Help Center, "Get started with custom connectors using remote MCP" — https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp (OAuth-only auth; connections originate from Anthropic's cloud IP ranges)
- anthropics/claude-ai-mcp issue #112, "Cannot configure Authorization: Bearer for custom remote MCP" — https://github.com/anthropics/claude-ai-mcp/issues/112 (**closed as not planned**)

**Corroborating (MEDIUM confidence)**

- Sunpeak, "Claude Connector Authentication: How OAuth Works and When You Need It" (July 2026) — https://sunpeak.ai/blogs/claude-connector-oauth-authentication/ (401 + `WWW-Authenticate` discovery, PRM probing fallback, `static_headers` beta scoped to org administrators)
- WorkOS, "The biggest MCP spec update ships July 28" — https://workos.com/blog/mcp-2026-spec-agent-authentication (six authorization requirements; breaking changes vs 2025-11-25)
- chrisdoc/hevy-mcp — https://github.com/chrisdoc/hevy-mcp (independent confirmation: implemented OAuth 2.1 specifically for "Claude.ai and remote clients unable to send fixed headers"; also notes Hevy exposes no delete endpoints)
- anthropics/claude-code issue #45368 and related client issues — the `Accept: application/json, text/event-stream` / HTTP 406 interop class of bug across multiple MCP clients
- anthropics/claude-code issues #9152, #45770 — tool result caps (~25,000 tokens, `MAX_MCP_OUTPUT_TOKENS`); Claude Desktop ~150,000-character cap
- Render free-tier documentation and 2026 pricing summaries — 15-minute spin-down, ~1-minute spin-up, 750 instance-hours/month, free Postgres 1 GB expiring 30 days after creation with a 14-day grace period
- MCP connection-troubleshooting write-ups — ~60-second initialize timeout, proxy SSE buffering, idle timeouts, ZTNA/VPN interference
- Training-volume methodology references (JTS, Cressey, N1 Training) — warm-up sets excluded from volume; hard sets (≤4 RIR) as the practical proxy; tonnage-only measurement is misleading across differing set/rep schemes

**Unverified — validate during execution (LOW confidence)**

- Whether Hevy stores dumbbell `weight_kg` per dumbbell or as a combined total (Pitfall 8). Verify against the user's own account during Phase 2 and record the answer.
- Hevy's actual rate limits — undocumented. Discover empirically during the first full sync and document.
- Whether `GET /v1/workouts` guarantees a stable sort order (the spec states ordering only for `/v1/workouts/events`). Assume it does not; reconcile with `/v1/workouts/count`.
- Which MCP protocol revision Anthropic's connector infrastructure currently negotiates. Log the received `MCP-Protocol-Version` on first connection and record it.

---
*Pitfalls research for: personal fitness data backend + remote MCP server*
*Researched: 2026-08-23*
