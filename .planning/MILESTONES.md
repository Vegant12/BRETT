# Milestones

## v2.1 Longitudinal Physique Analysis (Shipped: 2026-09-15)

**Phases completed:** 6 phases, 17 plans, 46 tasks
**Timeline:** 2026-09-05 → 2026-09-15 (10 days)
**Git range:** `1cd5e05` (Phase 14 context) → `534a8da` (evolve PROJECT.md after Phase 19) — 108 files changed, +27,728/-222 lines, ~58.1k LOC in `backend/`; 1195 tests passing (up from 925 at v2.0 close); MCP registry grew 20 → 22 tools

**Delivered:** BRETT can now log and retrieve Claude-authored physique observations from progress photos it never stores, diff them deterministically against training volume, and surface both in the monthly report — and this milestone's own migration (`0007`) proved, in production, that the deploy-migration gap which bit three times in v2.0 is actually fixed.

**Key accomplishments:**

- Closed the carried-forward deploy-migration gap first: extracted an `alembic current` vs `alembic heads` predicate (`app.db.migration_preflight`), wired a fetch-apply-verify pre-flight into `scripts/deploy-cloud-run.sh`, and rehearsed it against a real drifted Postgres container before trusting it with this milestone's own schema change.
- Ran a pre-registered calibration spike (5 blind ratings + a 5-step anchored chain on one unchanged photo set) before locking the observation schema, finding BLIND-STABLE ratings and no self-reinforcing anchoring ratchet, and derived the diff-threshold and elapsed-time-floor constants from that measured evidence rather than a guess.
- Built the physique data model and repository — a header row plus one child row per muscle group on the existing 19-value canonical taxonomy, `Not Assessable` as a first-class value, and a non-destructive supersede-with-reason correction path, with 19-row completeness enforced before any insert.
- Shipped `fitness_log_physique_observation` (single-call, append-only, non-destructive) alongside its required companion read tool, deterministic ordinal diff and volume-cross-reference analytics, and widened the MCP write-guard suite from a uniform destructive-hint claim to an exact per-tool mapping — all backed by container-level tests proving every refusal family writes nothing.
- Integrated physique into the monthly report only (the weekly report structurally cannot carry it): a deterministic, provenance-checked `## Physique` section with zero Claude-authored free text reaching the narrative.
- Proved the deploy fix in production: migration `0007` reached Cloud Run through the unmodified Phase 14 pipeline (revision `brett-00012-n6r`), and a live OAuth-authenticated MCP call against that revision returned a schema-valid response — real evidence, not a fixture assertion.

**Known Gaps / Deferred:**

- No formal `/gsd-audit-milestone` run before close — third milestone running without one (see STATE.md Deferred Items).
- REQUIREMENTS.md traceability drift reconciled at close for the third consecutive milestone (PHYS-01–05 and PHYS-12 were stale despite Phase 16's own verification confirming them satisfied) — a 3-for-3 pattern worth a structural fix rather than another manual reconciliation.
- Hevy rate-limit verification and D-06's nutrition-coverage re-query remain open, carried again from v1.0/v2.0.

---

## v2.0 Apple Health, Strength Tracking & Coaching Programs (Shipped: 2026-09-05)

**Phases completed:** 6 phases, 34 plans, 81 tasks
**Timeline:** 2026-09-02 → 2026-09-05 (4 days)
**Git range:** `b1d3eef` (v1.0 tag) → `2eb6fd6` (evolve PROJECT.md after Phase 13) — 220 commits; `backend/` +19,056/-204 across 77 files (~52.3k LOC total); 925 test functions; MCP registry grew 13 → 20 tools

**Delivered:** BRETT stopped being Hevy-only. Apple Health activity and nutrition now flow in continuously from the user's phone with 4.5 years of history behind them; the training program is real, switchable, effective-dated data that shifts recomposition thresholds; and a single tool call returns a complete weekly or monthly report — proven from a real Claude scheduled task rather than assumed.

**Key accomplishments:**

- **Apple Health & nutrition ingest (Phase 8):** A Health Auto Export webhook receiver landing 12 metrics — steps, active/basal energy, distance, flights, calories and six macros — authenticated by a `SecretStr` credential checked before a byte of body is read, capped at 10 MiB pre-parse, and given its own rate-limit bucket that cannot drain `/mcp`'s. `source_name` sits inside the 5-column natural key so Hevy's HealthKit write-back stays a separately-excludable row instead of being silently summed into the iPhone's total. Verified live from the user's phone, with a repeat run proving idempotency (23 rows unchanged).
- **Historical backfill (Phase 9):** 8,077 rows spanning 2022-03-10 → 2026-08-26 imported once from the real 191 MB `export.xml`, streamed with `iterparse` inside an 800 MB ceiling and pushed through Phase 8's *unchanged* normalizer and upsert — one code path, so historical and ongoing trends cannot drift. A required `--dry-run`/`--write` choice made a forgotten flag an argparse error rather than an unrehearsed production write.
- **Max-weight strength signal (Phase 10):** `PlateauResult.last_max_weight_kg` added as a labelled display-only field so Claude can cite the literal last weight lifted, with estimated-1RM still driving every verdict unchanged. Notable mostly for what it *didn't* become — the phase was rescoped mid-flight from "max weight replaces e1RM as classifier" down to one field, after investigation showed `ExerciseTrend` is never exposed through any MCP tool at all.
- **Body measurement history (Phase 11):** One generic function covering all 16 non-weight measurement columns via a closed `BodyMeasurementMetric` enum, using a latest-vs-earliest 90-day comparison rather than copying the body-weight rolling average — because at 15/123 measured days for waist and 0/123 for body fat, the rolling-average design would have returned `insufficient_data` almost universally. Staleness and insufficient data are reported as two independently-gated facts.
- **Training programs & the one write tool (Phase 12):** Append-only `user_program_history` with PostgreSQL enforcing "at most one open period" via a partial unique index, three per-program threshold tables replacing five hardcoded Lean Bulk constants (76 label-matrix cells), and BRETT's only MCP write path — a two-call, server-issued-token confirmation a model cannot short-circuit by setting `confirm: true`. The read-only guard was *narrowed* to exactly one named module, never relaxed, with the test suite asserting a second write tool cannot pass by being skipped.
- **Reports & coaching style (Phase 13):** `fitness_get_weekly_report` and `fitness_get_monthly_report` compose nine already-tested analytics functions with no new arithmetic, alongside activity/nutrition trend tools and a cross-exercise PR scan that costs one query instead of a per-exercise loop. RPT-03's central risk — that Claude scheduled sessions never receive tool schemas — was retired the right way: spiked *first* with `fitness_ping` before the report tools existed, then re-proven against the real report tool at the end. Both PASSed.

**Known deferred items at close:** 8 (see below and STATE.md Blockers/Concerns)

**Known gaps at close:**

- No formal `/gsd-audit-milestone` was run before this close (skipped by explicit user choice at the pre-flight gate — the same choice made at v1.0). Substituted with direct code verification of the three requirements whose traceability rows read `Pending`: HEALTH-10 (`integrations/health_auto_export/backfill.py` + `backfill-apple-health` CLI verb), BODY-05 (`analytics/body_measurements.py` + the registered `fitness_get_body_measurement_trend` tool), and GOAL-02 (`_THRESHOLDS` keyed on `TrainingProgram` in `analytics/recomposition.py`). All three confirmed implemented before archiving.
- **REQUIREMENTS.md traceability drift, second milestone running.** Three requirements were marked `Pending` despite being complete and production-verified; reconciled to 26/26 as part of this close. This is the identical failure mode logged at v1.0 close and it recurred, which suggests the per-phase workflow does not reliably update the traceability table. Worth a structural fix rather than a third manual reconciliation.
- **`gsd-tools.cjs audit-open` is still broken** (`ReferenceError: output is not defined` — a bare `output()` at gsd-tools.cjs:784/786 that should be `core.output()`). Reported as a deferred item at v1.0 close, never fixed upstream, so the automated pre-close artifact audit could not run for a second consecutive milestone. Global `~/.claude/get-shit-done/` install bug, not a BRETT issue.
- **The deploy migration gap bit three times this milestone.** `scripts/deploy-cloud-run.sh` has no migration step, and production was found behind deployed code in Phase 8 (`0004` vs `0005`), during the Phase 9 operator run (wrong `DATABASE_URL` showing a stale before-state), and again in the Phase 13 spike (`0005` vs `0006`, surfacing as `UndefinedTableError: relation "user_program_history" does not exist`). Each was fixed live. The structural fix — a pre-deploy migration step or an enforced `alembic current` vs `alembic heads` pre-flight — is **still not done** and should be the first thing v2.1 addresses.
- **D-06's production nutrition-coverage re-query never happened** — blocked by the sandbox command classifier on `gcloud secrets versions access`. `MEASURED_DAY_FLOORS` (3/7, 5/14, 10/30) was reused unchanged for nutrition trend floors as a documented fallback. This does **not** close with Phase 13 and still needs a human-operator re-query.
- **`sample_count` semantics diverge** between the backfill (raw sample count, >1 for 91.7% of rows) and the webhook (always 1), making a falling `sample_count` on a backfilled day a false positive for the Pitfall N-2 batch-split detector. Documented in `docs/health-auto-export-setup.md` §7; no overlapping day existed to exercise it (zero overlap confirmed).
- **Hevy's real rate limits remain undocumented** (carried unresolved from v1.0) — the retry policy is still unverified against an actual limit rather than confirmed unnecessary.
- **`Gymverse` (2 records) and `Zing` (1 record) active-energy rows were deliberately ingested** — a decision, not an oversight. HEALTH-08 names Hevy specifically and its rationale ("BRETT already holds this data at higher fidelity") is false of these two, whose workouts BRETT does not hold at all.

---

## v1.0 MVP (Shipped: 2026-09-02)

**Phases completed:** 7 phases, 65 plans, 151 tasks
**Timeline:** 2026-08-23 → 2026-09-01 (10 days)
**Git range:** `b6a78a2` (initialize project) → `750ff56` (evolve PROJECT.md after Phase 7) — 345 files changed, +111,596/-21 lines, ~33.9k LOC in `backend/`

**Delivered:** The full Hevy → PostgreSQL → analytics → MCP → Claude loop is live in production. A real Claude Project, pointed at the deployed Cloud Run MCP server, answers "Am I progressing?" and "Which muscles are undertrained?" from real synced training data — the project's Core Value, observed working end-to-end for the first time.

**Key accomplishments:**

- **Foundation (Phase 1):** FastAPI + PostgreSQL + Alembic scaffold with UTC-storage enforcement, Asia/Jakarta-configurable timezone bucketing, and a three-layer structlog pipeline that provably strips secrets from every log channel.
- **Deploy & auth spike (Phase 2):** Resolved the project's single highest-uncertainty question first — a real Claude Desktop client authenticates to the Cloud Run-hosted MCP server via WorkOS AuthKit (OAuth 2.1), overturning the original "bearer token, not OAuth" assumption with evidence rather than argument.
- **Hevy integration (Phase 3):** Idempotent full + incremental sync (correct oldest-first event application, no duplicate/corrupted data on failure), a 19-value canonical muscle taxonomy with front/side/rear deltoid split, and an auditable manual-override layer — all isolated inside `backend/app/integrations/hevy/` and validated against the real Hevy API (463 exercise templates curated, unmapped count driven 77 → 44).
- **Analytics layer (Phases 4-5):** Deterministic, SQL-first volume/frequency, progression trend classification, plateau detection, personal records, period comparison, body-weight trend, and a recomposition verdict — every response carrying a freshness/coverage uncertainty envelope (DQ-01/DQ-02) so sparse data is never reported as confident.
- **MCP tool surface (Phase 6):** Thirteen purpose-built, read-only, byte-budgeted MCP tools composing the analytics layer directly (no HTTP round-trip), with zero secret leakage proven by a full-registry redaction test and a live check that the DB session structurally cannot write.
- **Production hardening (Phase 7):** Live token-bucket rate limiting (proven against a real 429 flood), a real Neon PITR backup/restore drill (byte-identical across all 9 tables), a real `MCP_AUTH_SECRET` rotation with zero connector disruption, 6-hourly production Hevy sync (327 workouts/463 templates/125 body measurements), 687 green tests, and the coaching-instructions document that turned the data layer into an actual working coach.

**Known gaps at close:**

- No formal `/gsd-audit-milestone` was run before this close (skipped by explicit user choice — see pre-flight gate). Substituted with a targeted spot-check of 8 requirements whose REQUIREMENTS.md checkboxes/traceability rows were stale (HEVY-01/02/05/06/07/08/09, NORM-02) — all 8 confirmed implemented directly against code before archiving.
- `gsd-tools.cjs audit-open` (and `--json`) is broken in this GSD install (`ReferenceError: output is not defined` — a bare `output()` call at gsd-tools.cjs:784/786 that should be `core.output()`). The pre-close automated artifact audit could not run as a result. This is a tooling bug in the global `~/.claude/get-shit-done/` install, not a BRETT project issue.
- REQUIREMENTS.md's traceability table and checkboxes had drifted out of sync with actual progress since 2026-08-30 (only updated through Phase 4); reconciled to reflect all 39/39 v1 requirements complete as part of this milestone close.
- Three PROJECT.md "Active" items remain genuinely open scope questions rather than incomplete v1 work: body-measurement manual entry, nutrition manual entry, and freshness surfacing — each flagged in PROJECT.md as likely already satisfied or redundant, pending a scope decision at the v1.1 boundary.

---
