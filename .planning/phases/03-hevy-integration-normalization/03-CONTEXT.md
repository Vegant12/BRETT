# Phase 3: Hevy Integration & Normalization - Context

**Gathered:** 2026-08-29
**Status:** Ready for planning

<domain>
## Phase Boundary

PostgreSQL becomes the trustworthy source of truth for all Hevy data — workouts, exercise templates, and body measurements — normalized to a canonical muscle taxonomy. Delivers: `HevyClient`/`HevySyncService` isolated under `backend/app/integrations/hevy/`, idempotent full + incremental sync (workouts, exercises, sets), deletion handling, a curated exercise→muscle-group mapping with an auditable manual-override layer, and a Hevy body-measurements sync.

**Explicitly NOT this phase:** Volume/frequency/progression/PR/plateau/recomposition analytics (Phase 4/5). Manual body-measurement or nutrition entry UI/endpoints (later — this phase only ships the Hevy-sourced side of body measurements). MCP tools (Phase 6). Cron/scheduling wiring for triggering sync in production (Phase 7 hardening) — this phase builds the sync service itself, not its production trigger.

</domain>

<decisions>
## Implementation Decisions

### Muscle Taxonomy & Mapping
- **D-01:** Canonical muscle-group list uses the **standard hypertrophy split** (~14-16 groups): chest, lats, traps, front delts, side delts, rear delts, biceps, triceps, forearms, quads, hamstrings, glutes, calves, abs, obliques, lower back. This satisfies NORM-01's explicit front/side/rear deltoid split requirement, which Hevy's own taxonomy does not provide.
- **D-02:** The exercise→muscle mapping is **curated, in-repo data** (Python dict or migration-seeded rows, keyed by Hevy `exercise_template_id`), not re-derived from Hevy's own template metadata on every sync. Hevy's muscle-group fields (if present in the live template payload) may seed the initial curation but the canonical mapping is authored/reviewed like code, so it doesn't silently drift if Hevy changes categorization.
- **D-03:** An exercise with no established mapping (custom Hevy exercise, or a new template not yet curated) **still syncs fully** — workout/exercise/sets persist correctly — with its muscle group(s) left null/flagged "unmapped." Sync must never block or corrupt on a mapping gap (matches HEVY-08's "failed sync must not corrupt data" spirit, extended to mapping gaps). Muscle-volume analytics (Phase 4) simply excludes unmapped exercises until curated.
- **D-04:** Manual overrides live in a **separate table** (e.g. `exercise_muscle_overrides`), not columns bolted onto `exercise_templates`. The original synced/curated mapping is never mutated; the effective mapping is computed at query time (override row present → override wins), giving NORM-02's "auditable against the original source mapping" for free.

### Body Measurements
- **D-05:** Sync **weight plus whatever other fields Hevy's `/v1/body_measurements` actually returns** (body fat %, waist, chest, arm, thigh, etc. — verify exact field set against the live API at research/plan time, not the blueprint's assumed shape). Matches REQUIREMENTS.md HEVY-07 ("weight, body fat %, waist, and other available fields").
- **D-06:** **One `body_measurements` table**, not per-source tables — columns per metric plus a `source` discriminator (`'hevy' | 'manual'`, manual entry itself is a later phase) and a nullable `external_id` (Hevy's ID when `source='hevy'`). One place to query weight/composition trends from regardless of origin.
- **D-07:** Idempotency keys on **Hevy's own measurement ID when the API provides one** — same `(user_id, source, external_id)` pattern as workouts. If research confirms Hevy has no stable per-entry ID, fall back to `(user_id, source, measured_at date, metric)` (at-most-one Hevy value per metric per calendar day, re-sync upserts). Confirm which case applies during Phase 3 research, not planning-by-assumption.

### Sync Resilience
- **D-08:** Full sync commits **per page**, with a sync-run/checkpoint record (e.g. `last_hevy_sync_cursor` per blueprint §7, or a dedicated `sync_runs` table) advancing after each successful page. A crash mid-sync leaves all prior pages committed; the next run resumes from the last checkpoint instead of restarting from page 1 — important given the pageSize=10 cap makes a full historical sync dozens-to-hundreds of requests.
- **D-09:** Deletion detection relies on the **`/v1/workouts/events` endpoint only** (blueprint §7's intended mechanism) — no periodic full-reconciliation sweep in v1. Accepted risk: an event missed due to a sync gap longer than Hevy retains events for could leave a deleted workout lingering locally; not building reconciliation now, but note it as a candidate follow-up if drift is ever observed in practice.
- **D-10:** Rate-limit handling is **reactive exponential backoff via tenacity** (already in the stack per CLAUDE.md) on 429/5xx responses, with jitter. No proactive throttling delay added upfront — the pageSize=10 cap already bounds request volume per page, and Hevy's actual limits are undocumented (STATE.md open item); whatever rate-limit headers Hevy returns during the first real sync should be logged/recorded so the real behavior gets documented empirically rather than guessed.

### Claude's Discretion
- **Hevy credential storage** (raised as a gray area, not discussed in depth): the blueprint explicitly permits an env-var secret for a single-user personal deployment ("environment secrets are acceptable for the Hevy key... structure the system so per-user credentials can be supported later"), and `Settings.hevy_api_key` already works that way since Phase 1. Default to **keeping `HEVY_API_KEY` as the env-var secret** rather than building encrypted `external_connections.encrypted_credentials` storage now — build `external_connections` (or equivalent) only as far as needed for `last_synced_at`/status bookkeeping (HEVY-09), not as a credential store, unless research surfaces a concrete reason multi-credential storage is needed sooner. This is Claude's call at research/plan time, not a locked decision — flag it back to the user if the bookkeeping-only approach turns out insufficient.
- Exact `sync_runs`/checkpoint table shape (dedicated table vs. columns on `external_connections`)
- Exact fuzzy/unmapped exercise flag representation (nullable muscle columns vs. an explicit `mapping_status` enum)
- Whether the curated exercise→muscle mapping ships as Python module data or Alembic-seeded rows (both satisfy D-02 "in-repo, curated")
- Whether dumbbell weight is per-dumbbell or combined (STATE.md open item — must be discovered empirically during the first real sync and recorded, not assumed)
- Exact tenacity retry parameters (max attempts, backoff base/cap)
- CLI/route mechanism for manually triggering a sync run in this phase (production scheduling is Phase 7; this phase just needs *a* way to invoke `HevySyncService` for verification/testing)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project scope & requirements
- `.planning/PROJECT.md` — Requirements (Active: HEVY-*, NORM-*), Constraints (provider isolation, data integrity), Key Decisions (Hevy body measurements added to Phase 3 scope)
- `.planning/REQUIREMENTS.md` — HEVY-01 through HEVY-09, NORM-01 through NORM-03 (exact acceptance criteria for this phase)
- `.planning/ROADMAP.md` Phase 3 section — goal, 5 success criteria, requirements mapping, "Hevy body measurements are synced in Phase 3 rather than entered manually" note
- `.planning/STATE.md` Blockers/Concerns — open Phase 3 items: build against the *live* Hevy schema not the blueprint's assumed one (no `rir`, no `weight_unit`, pageSize caps at 10, no stable child-object IDs, events return newest-to-oldest); undocumented rate limits and per-dumbbell-vs-combined weight ambiguity must be discovered empirically

### Source spec (authoritative for schema/architecture shape, but verify against live Hevy API — blueprint assumptions are known-stale in places)
- `BRETT blueprint.md` §5.2 "external_connections" — provider/encrypted_credentials/status/last_sync_at schema (relevant to the credential-storage discretion note above)
- `BRETT blueprint.md` §6 "Hevy Integration" — use official Hevy API docs as source of truth, not invented endpoints; isolate all Hevy logic in `backend/app/integrations/hevy/`
- `BRETT blueprint.md` §7 "Hevy Sync" — `HevyClient`/`HevySyncService`, initial + incremental sync, `last_hevy_sync_cursor`/`last_hevy_event_timestamp`, idempotency via `unique(user_id, provider, external_id)`, error handling (API errors, rate limiting, network failures, malformed responses, deleted workouts, partial syncs)
- `BRETT blueprint.md` §8 "Hevy Data Model" — `workouts`/`workout_exercises`/`sets` minimum schema (note: `rir`/`weight_unit` fields are blueprint assumptions per STATE.md, verify against live API)
- `BRETT blueprint.md` §9 "Exercise Normalization" — `exercise_templates` schema, mapping-layer example (Bench Press → chest/triceps/front_delts), manual override allowance
- `BRETT blueprint.md` §41 "Units" — kg/m/kcal/seconds/cm internal units, convert at application boundary (applies to weight/body-measurement fields synced this phase)
- `BRETT blueprint.md` §42 "Testing" → "Hevy" subsection — required test coverage: auth, pagination, incremental events, duplicate prevention, deleted workouts, API failures, rate limiting
- `BRETT blueprint.md` §44 "Observability" — sync lifecycle logging (sync started/completed/records imported), secret redaction (API keys never logged)

### Technology stack (already researched and locked — see project CLAUDE.md)
- `CLAUDE.md` §"Technology Stack" → tenacity row — retry/backoff for Hevy's pageSize=10 cap and transient failures (D-10)
- `CLAUDE.md` §"Technology Stack" → httpx2 row — Hevy API client; `pytest-httpx2`/`httpx2.MockTransport` for tests, NOT `respx`/`pytest-httpx` (incompatible)
- `CLAUDE.md` §"What NOT to Use" — SQLite for tests (use `testcontainers[postgres]`), `requirements.txt`

### Prior phase context (locked, do not re-litigate)
- `.planning/phases/01-backend-foundation/01-CONTEXT.md` D-07 — `external_connections` deliberately deferred to Phase 3 "alongside real encryption"; this phase's credential-storage discretion note (above) revisits whether encryption is actually needed given the blueprint's env-var allowance
- `backend/app/config.py` — `Settings.hevy_api_key: SecretStr | None` already exists and is wired into the three-layer secret-redaction defense (`_SECRET_FIELDS`); any new Hevy-related secret must be added the same way

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `backend/app/config.py` — `Settings.hevy_api_key` already present (unused since Phase 1), anticipated for this phase's client auth.
- `backend/app/db/base.py` — `Base`/`TimestampMixin` (named constraints for stable Alembic autogenerate, `TIMESTAMPTZ`-only timestamps per FOUND-04) — every new Hevy/muscle/body-measurement table must inherit this, not a bare `DeclarativeBase`.
- `backend/app/db/models/user.py` — `User` model with UUID PK; new tables FK to `users.id`. Note the model's own comment: "the provider-credentials table... deliberately absent [until] Phase 3 alongside real encryption" — directly relevant to the credential-storage discretion note.
- `backend/app/logging.py` — structlog + secret redaction pipeline; sync lifecycle logging (blueprint §44) should route through the existing `structlog.get_logger()` pattern, and any new secret field added to `Settings` must also be added to `_SECRET_FIELDS`.
- `backend/migrations/versions/0001_initial_schema.py`, `0002_seed_default_user.py` — established Alembic migration pattern (hand-reviewed autogenerate, explicit `op.f()` naming) to follow for the new Hevy/muscle/body-measurement tables.

### Established Patterns
- Migration 0001's docstring explicitly earmarks Phase 3 for the provider-credentials table — this phase is expected to touch `external_connections` in some form (see discretion note on scope).
- Secrets are `SecretStr`-typed in `Settings`, never a bare string, and registered in `_SECRET_FIELDS` for the log scrubber (`app/config.py:24`).

### Integration Points
- New code lives under `backend/app/integrations/hevy/` (client + sync service, per blueprint §6/§7 and PROJECT.md's provider-isolation constraint) and `backend/app/db/models/` (new SQLAlchemy models: workouts, workout_exercises, sets, exercise_templates, exercise_muscle_overrides, body_measurements, and whatever tracks sync checkpoints).
- No existing sync/scheduling infrastructure exists yet — this phase builds `HevySyncService` as a callable unit; Phase 7 decides how it's actually triggered in production (cron, etc.).

</code_context>

<specifics>
## Specific Ideas

No further specific ideas beyond the decisions above — user selected recommended defaults throughout, confirming the researched approach fit their intent for this phase.

</specifics>

<deferred>
## Deferred Ideas

- **Periodic full-reconciliation sweep for deletion detection** (D-09) — not built in v1; noted as a candidate follow-up only if event-based deletion detection is ever observed to drift in practice.
- **Encrypted per-provider credential storage** (`external_connections.encrypted_credentials`) — deferred again past this phase by default (see Claude's Discretion), since the blueprint explicitly allows an env-var secret for a single-user personal deployment. Revisit if/when the project moves toward multi-user or per-user credentials.
- Manual body-measurement and nutrition entry (schema/endpoints) — explicitly out of this phase's scope; this phase only ships the Hevy-sourced side of `body_measurements` (D-06's `source` column anticipates the later manual-entry rows).

</deferred>

---

*Phase: 03-hevy-integration-normalization*
*Context gathered: 2026-08-29*
