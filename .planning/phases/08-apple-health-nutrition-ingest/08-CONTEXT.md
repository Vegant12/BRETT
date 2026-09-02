# Phase 8: Apple Health & Nutrition Ingest - Context

**Gathered:** 2026-09-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Apple Health activity data (steps, active/basal energy, distance, flights climbed) and nutrition data
(calories + six macros) flow from the user's phone into BRETT continuously, via a Health Auto Export
webhook receiver — authenticated, idempotent, and free of Hevy re-exports (Apple Health workouts and
Hevy-originated body-mass rows never enter BRETT's training or body data).

This phase does NOT include: the one-time `export.xml` historical backfill (Phase 9), health/nutrition
*analytics* — trend calculations, MCP tools (Phase 13), max-weight strength signal, body-measurement
history beyond what this phase's schema enables, or training programs. Those are separate phases.

</domain>

<decisions>
## Implementation Decisions

### Apple Health body-mass scope
- **D-01:** Exclude ALL Apple Health body-mass records from ingestion in Phase 8, not just Hevy-sourced
  ones. `body_measurements` stays a two-source table (`hevy`, `manual`) exactly as it is today — no
  `apple_health` source is added to it. Rationale: the user's real export shows 52/79 Apple BodyMass rows
  are Hevy duplicates and the data stops in May 2025 (no recency value); adding a third source would make
  `bodyweight._dedupe_by_day`'s precedence three-valued, which the research flags as a real correctness
  risk that belongs in Phase 11's `_dedupe_by_day` fix, not bolted on here. This is narrower than
  PROJECT.md's literal "body weight/composition where not already Hevy-sourced" phrasing — a deliberate
  scope tightening the user confirmed during discussion, not an oversight.

### Apple Health workouts scope
- **D-02:** Do not build a `health_workouts` table in Phase 8. Apple Health workouts are excluded from
  ingestion entirely (the ingest's metric/type allowlist simply never admits the `workouts` array) — no
  quarantined "coverage cross-check" table. Rationale: 218/221 of the user's real Apple Health workouts are
  Hevy re-exports; the 3 non-Hevy ones add negligible value against the cost of a new table + a static
  guard test to keep it out of training analytics forever. If a coverage cross-check is ever wanted, it's a
  future-phase addition, not part of Phase 8's success criteria.

### Freshness / sync-state granularity
- **D-03:** Track activity and nutrition freshness as two **separate** `sync_state` resources under
  `provider='apple_health'` — e.g. `resource='activity'` and `resource='nutrition'` — each with its own
  `last_synced_at`. Do not collapse them into one combined `apple_health` resource. Rationale: both come
  through the same webhook POST, but they can go stale independently (nutrition-logging app stops writing
  to HealthKit while steps keep flowing, or vice versa) — a combined resource would report "fresh" on a
  partial failure. Directly implements Pitfall 7's fix and satisfies HEALTH-11/NUTR-05 for each data kind
  independently. `analytics/metadata.build_freshness` must gain the `(provider, resource)` pairs signature
  change either way (Pitfall 7); this decision fixes what the resource names actually are.

### Unlisted / unexpected metric handling
- **D-04:** When a payload includes a metric name outside the ingest's fixed allowlist (e.g. the user
  toggles on a new Apple Health data type in the automation), silently drop that metric and continue
  processing the rest of the payload normally — do not reject the whole request. Rationale: Health Auto
  Export has no documented retry; rejecting an entire batch over one unrecognized metric would lose the
  *entire* window's activity AND nutrition data, not just the unexpected part. Matches the vendor's own
  guidance that "ingest everything" is what breaks the automation. A follow-up decision for planning: emit
  a structured log line (e.g. `health_ingest_unrecognized_metric`) when this happens, so a phone-side
  misconfiguration is discoverable in logs rather than silently invisible forever — this is Claude's
  discretion on implementation, but the *behavior* (log, don't reject) is locked.

### Nutrition wire format — explicit research gap
- **D-05:** The project's existing v2.0 research (`SUMMARY.md`, `ARCHITECTURE.md`, `FEATURES.md`,
  `PITFALLS.md`, `STACK.md`, all dated 2026-09-02) was written when nutrition was still Out of Scope for
  v2.0 (`FEATURES.md:247,493` explicitly say "no nutrition work in v2.0"). The decision to fold nutrition
  into Phase 8 via the same Health Auto Export pipeline (NUTR-02, superseding NUTR-01) was made the same
  day but **after** that research ran — so unlike the activity metrics (steps/energy/distance/flights,
  verified with HIGH confidence against the vendor docs and the user's real export), the exact Health Auto
  Export field names, units, and shape for calories + the six macros (protein, carbs, fat, fiber, sugar,
  sodium) are **not yet verified**. `gsd-phase-researcher` must resolve this before planning writes
  concrete schemas/normalizer code:
  - Exact HAE metric names for `dietary_energy` (calories) and the six macros (the export has 95
    `DietaryEnergyConsumed` records from a Foodvisor-style app — a real reference point, not zero data)
  - Units per macro (grams vs. milligrams for sodium, in particular)
  - Whether Hevy ever writes anything nutrition-adjacent to Apple Health (expected: no — Hevy is a workout
    app — but confirm rather than assume, the same discipline the body-mass/workout exclusion research
    applied)
  - Whether the same shared allowlist-and-normalize pipeline used for activity metrics extends cleanly to
    nutrition metrics, or whether nutrition needs its own normalizer function (likely yes to reuse — same
    `{"name", "units", "data": [...]}` metric shape per `ARCHITECTURE.md`, but confirm)

### Claude's Discretion
- Webhook auth header scheme: use `Authorization: Bearer <token>` with `secrets.compare_digest` on bytes,
  copying `mcp/auth.py::StaticTokenVerifier` exactly (established pattern, not re-litigated).
- Exact log field names/shapes for the `health_ingest_unrecognized_metric` warning event (D-04).
- Rate-limit bucket capacity/refill values for the new `/api/v1/ingest/*` path (separate bucket per
  Pitfall 2 is locked; the specific numbers are a planning-time tuning decision).
- Whether the ingest route lives at `/api/v1/ingest/health-auto-export` or another specific path, as long
  as it's registered above `app.mount("/", mcp_app)` in `main.py` (Pitfall 1).
- `body_measurements.source` for `hevy`/`manual` is unaffected by this phase (D-01 means no new source is
  added there); if a future phase does add `apple_health` as a third source, use `'apple_health'` (12
  chars) per Pitfall 8, never `'health_auto_export'` (18 chars, exceeds the current `VARCHAR(16)`).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` — Phase 8 requirements: HEALTH-06, HEALTH-07, HEALTH-08, HEALTH-09,
  HEALTH-11, NUTR-02, NUTR-03, NUTR-05
- `.planning/ROADMAP.md` §"Phase 8: Apple Health & Nutrition Ingest" — goal, success criteria, and the
  five planning notes already called out (route order, dedicated rate-limit bucket, `build_freshness`
  signature change, metric-name spelling gap, deploy memory/secret change)
- `.planning/PROJECT.md` §Key Decisions — Apple Health ingestion = webhook receiver (not native app);
  Apple Health workouts/Hevy-sourced body-mass excluded from ingestion

### Research (2026-09-02) — read in full, not skimmed
- `.planning/research/SUMMARY.md` — executive summary, stack, critical pitfalls, phase-ordering rationale
- `.planning/research/PITFALLS.md` §Pitfalls 1–9 — every pitfall directly relevant to Phase 8 (route
  registration order, rate-limit bucket collision, unauthenticated FastAPI route, non-idempotent ingest,
  payload size vs. Cloud Run/instance limits, `export.xml` streaming — relevant context even though the
  parse itself is Phase 9, freshness envelope default, `VARCHAR(16)` source-column truncation, the latent
  `_dedupe_by_day` bug Apple Health activates as a third source even though it isn't triggered by this
  phase's D-01 decision)
- `.planning/research/ARCHITECTURE.md` — target architecture diagram, component responsibilities table,
  `health_daily_metrics` schema (day-grained, `(user_id, source, metric, local_day)` unique key,
  `source_name` column for per-datapoint origin filtering), the `health_workouts` proposal (rejected for
  Phase 8 per D-02, keep the design on file for later), and the explicit "don't add apple_health as a
  third `body_measurements` source" analysis behind D-01
- `.planning/research/FEATURES.md` — table-stakes vs. differentiator features for Apple Health ingestion;
  note its nutrition sections predate the NUTR-02 rescoping (see D-05)
- `.planning/research/STACK.md` — confirms zero new runtime dependencies; `xml.etree.ElementTree`,
  `secrets.compare_digest`, `decimal.Decimal` all stdlib

### Existing code to mirror
- `backend/app/integrations/hevy/` — the provider-isolation shape to copy for
  `integrations/health_auto_export/` (schemas.py, client/ingest, errors.py pattern)
- `backend/app/integrations/hevy/body.py:97-120` — the `pg_insert(...).on_conflict_do_update(constraint=...)`
  idempotent upsert pattern to copy for the new natural key
- `backend/app/mcp/auth.py::StaticTokenVerifier` (lines ~37-52) — the exact bytes-based
  `secrets.compare_digest` pattern for the webhook's shared-secret auth
- `backend/app/main.py` — route registration order (`app.mount("/", mcp_app)` is last, on purpose) and the
  existing `RateLimitMiddleware` wiring
- `backend/app/middleware.py` — `TokenBucket`, `RateLimitMiddleware`, `EXEMPT_PREFIXES` — the second bucket
  for the ingest path attaches here
- `backend/app/db/models/body.py` — `BodyMeasurement` model and its `source: String(16)` column (context
  for why D-01 avoids adding a third source rather than widening this column)
- `backend/app/db/models/sync_state.py` — `SyncState` model (`provider: String(32)`, `resource: String(32)`)
  that D-03's two new resource rows attach to
- `backend/app/config.py` — `Settings`, `_SECRET_FIELDS`, `secret_values()` — the new
  `health_ingest_secret` follows `hevy_api_key`/`mcp_auth_secret`'s exact pattern

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `integrations/hevy/` package shape — schemas.py / client.py / errors.py / body.py-style ingest module —
  is the direct template for `integrations/health_auto_export/`, just inbound instead of outbound.
- `hevy/body.py`'s SAVEPOINT-per-row + named-constraint `on_conflict_do_update` upsert pattern is the
  idempotency mechanism to copy verbatim for the new `health_daily_metrics` natural key.
- `mcp/auth.py::StaticTokenVerifier`'s bytes-based `secrets.compare_digest` is the exact auth check to
  reuse for the webhook's shared-secret header.
- `middleware.py::TokenBucket`/`RateLimitMiddleware` already supports per-path bucket selection via
  `app.state` — the new ingest bucket is an additive wiring change, not new middleware logic.

### Established Patterns
- Provider isolation: all Hevy-specific code lives under `integrations/hevy/`, never leaks into
  `app/db/` or `app/analytics/` — statically enforced by `test_hevy_isolation.py`. The new
  `integrations/health_auto_export/` package must get the equivalent guard.
- Secrets: every credential is a `SecretStr` in `config.py`, added to `_SECRET_FIELDS`, so the logging
  scrubber redacts it automatically. `health_ingest_secret` follows this without new plumbing.
- Freshness envelope: every analytics response carries a `FreshnessMetadata` built from
  `analytics/metadata.build_freshness`, currently defaulting to `provider=PROVIDER_HEVY` — this default
  must be removed (Pitfall 7) as part of this phase's `sync_state` work, even though the analytics
  functions that *consume* Apple Health freshness are built in later phases.
- Route registration order in `main.py` is load-bearing: FastAPI's own routes must be registered above
  `app.mount("/", mcp_app)`, which is deliberately last because it's a catch-all.

### Integration Points
- New route module registers in `main.py` above the MCP mount, alongside the existing `health.router`.
- New `integrations/health_auto_export/` package parallel to `integrations/hevy/`.
- New `db/models/health.py` for `health_daily_metrics` (only table this phase needs, per D-02).
- `sync_state` gains two new resource rows under `provider='apple_health'` (D-03) — no schema change
  needed, `SyncState` already supports arbitrary `(provider, resource)` pairs.
- `analytics/metadata.build_freshness` signature change (remove the `provider` default) is this phase's
  responsibility even though most call sites won't pass Apple Health resources until later phases.

</code_context>

<specifics>
## Specific Ideas

No UI/visual specifics — this is a backend ingest endpoint with no user-facing surface beyond the
freshness signal Claude eventually reports (later phases). The concrete asks from this discussion:

- Body-mass and workouts: go narrower than PROJECT.md's literal phrasing (D-01, D-02) — the user
  confirmed this explicitly rather than defaulting to the broadest reading of "not already Hevy-sourced."
- Freshness: split into two resources so a partial failure (nutrition logging stops, activity keeps
  flowing) is visible rather than blended (D-03).
- Robustness over strictness for unexpected metrics: never let one unrecognized metric name cost an entire
  sync window (D-04).
- Nutrition wire format is an acknowledged blind spot, not a guess dressed up as a decision (D-05) — the
  user does not have a captured payload on hand, so this goes to `gsd-phase-researcher` as an explicit flag
  rather than being planned around assumptions.

</specifics>

<deferred>
## Deferred Ideas

- **`health_workouts` coverage cross-check table** — explicitly deferred, not built in Phase 8 (D-02). If
  ever wanted, it's a future-phase addition; the design already exists in `ARCHITECTURE.md` if picked up
  later.
- **Apple Health as a third `body_measurements` source** — explicitly deferred (D-01). If ever revisited,
  it must ship together with an explicit `MappingProxyType` source-precedence map and per-pair regression
  tests (Pitfall 9's fix), which is Phase 11's territory (`_dedupe_by_day`), not this phase's.
- **HAE automation configuration specifics** (Batch Requests toggle, aggregation interval, exact
  scheduling/trigger) — this is a device-side setup task the user does themselves once the webhook exists;
  it belongs in a setup doc written during or after implementation, not a Phase 8 code decision.

None of the above expand this phase's scope — no new gray areas came up that belonged to a different
phase during discussion.

</deferred>

---

*Phase: 08-apple-health-nutrition-ingest*
*Context gathered: 2026-09-02*
