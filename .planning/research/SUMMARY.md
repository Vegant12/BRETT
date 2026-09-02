# Project Research Summary

**Project:** BRETT v2.0 — Apple Health Ingestion, Strength Tracking & Coaching Programs
**Domain:** Personal fitness / body-recomposition data platform — extending a shipped, production-live FastAPI + PostgreSQL + MCP backend
**Researched:** 2026-09-02
**Confidence:** HIGH

## Executive Summary

BRETT v2.0 adds five capabilities to a working v1.0 backend: Apple Health ingestion (via Health Auto Export webhook + a one-time `export.xml` backfill), a shift to max-weight-lifted as the primary strength-progression signal, weekly/monthly report tools, manual body-measurement entry, and training-programs-as-data behind BRETT's first MCP write tool. All research was grounded not just in vendor docs but in the user's actual 191 MB Apple Health export (438,649 records, 2022-03→2026-08) and in direct reads of BRETT's committed source and test suite — this is unusually high-confidence research for a greenfield-feeling milestone.

Two findings should reshape scope before any roadmap is written. First, the user has **no Apple Watch**: zero heart-rate, HRV, VO2max, or exercise-ring samples exist across 4.5 years, and sleep data is undifferentiated `InBed`-only and stopped on 2024-11-30. "Recovery trends" (an Active requirement in PROJECT.md) has no data source and must be re-scoped to activity only (steps, active/basal energy, distance, flights) or explicitly deferred pending hardware. Second, **218 of 221 Apple Health workouts, and most Apple Health body-weight records, are Hevy data re-exported through Apple's Health app** — ingesting them as a separate signal would double-count training volume BRETT already owns at higher fidelity. Apple Health's real contribution is activity data Hevy cannot supply, not a second copy of what it can.

The recommended approach requires **zero new runtime dependencies** — every capability is carried by packages already in `pyproject.toml` plus stdlib (`xml.etree.ElementTree.iterparse`, `secrets.compare_digest`, `decimal.Decimal`). The real risk is not the stack; it is three things the research converged on independently: (1) Health Auto Export's payload can reach "several hundred megabytes" against Cloud Run's 32 MiB request cap and BRETT's 512 MiB instance — this forces a deploy change (`--memory=1Gi`) and a body-size guard, not a library; (2) the confirm-gated write tool is BRETT's first-ever mutation path in an MCP server whose entire security model has been "nothing can write" — a naive `confirm: bool` parameter is trivially bypassable by the model itself, and the fix (a server-issued, single-use, target-bound confirmation token) is the milestone's single highest-severity design decision; (3) the max-weight strength-signal switch changes three interlocking, live-data-calibrated constants (`TREND_STABLE_BAND_PERCENT_PER_WEEK`, `PLATEAU_IMPROVEMENT_TOLERANCE`, `RECOMP_PROGRESSION_NET_BAND`) whose values are tuned to e1RM's continuous distribution and will misbehave, silently and plausibly, against max weight's discrete plate-increment distribution unless re-derived and re-validated against live data.

## Key Findings

### Recommended Stack

No new third-party runtime dependencies. FastAPI, Pydantic, SQLAlchemy, `mcp==2.0.0`, and stdlib (`xml.etree.ElementTree`, `secrets`, `decimal.Decimal`, `zoneinfo`) already carry all five capabilities. The one infrastructure change required is raising Cloud Run memory from 512Mi to 1Gi (measured: baseline RSS 101 MB, +10 MB JSON body + Pydantic validation peaks near 235 MB — two concurrent ingest POSTs at default concurrency=80 is an OOM waiting to happen at 512Mi) plus a new `HEALTH_WEBHOOK_SECRET` in Secret Manager, added the same way `MCP_AUTH_SECRET` was.

**Core technologies (all already installed):**
- **FastAPI 0.141.1 + Pydantic 2.13.4** — webhook receiver and manual-entry routes. Health Auto Export dates are `"yyyy-MM-dd HH:mm:ss Z"`, NOT ISO 8601 — Pydantic's `datetime` field type rejects this outright (measured); type HAE date fields as `str` with a `BeforeValidator` trying an ordered `strptime` format list (24-hour and 12-hour, including the U+202F narrow-no-break-space variant newer iOS inserts before AM/PM).
- **`xml.etree.ElementTree.iterparse`** (stdlib) — the one-time `export.xml` backfill. Measured on the real 191 MB file: 2.5s, 52 MB peak RSS, 437,239 records. `ElementTree.parse()` (whole-DOM) would OOM a 512Mi instance immediately.
- **`mcp==2.0.0` `ToolAnnotations`** — the entire per-tool write surface; there is no scope-per-tool mechanism. Spec defaults are hostile (`destructive_hint=True`, `idempotent_hint=False`, `open_world_hint=True`) and must be overridden explicitly for the new write tool.
- **`secrets.compare_digest` on bytes** (stdlib) — the verification scheme for the webhook, since Health Auto Export offers arbitrary custom headers but no HMAC signing, no OAuth, no shared-secret mechanism of its own. Precedent already exists at `app/mcp/auth.py:49`.

**Explicitly rejected:** `orjson`/`lxml` (CPU is not the bottleneck, memory is), `svix`/`standardwebhooks` (no signature exists to verify), `APScheduler`/Celery/Cloud Tasks (Claude's own scheduled-tasks feature drives report delivery; there is no server-side schedule to run), `pandas`/`numpy` (banned in v1, and a further memory risk on a tight instance), and — critically — the MCP SDK's built-in `Elicit`/`Resolve` confirmation mechanism, which is architecturally unavailable under BRETT's `stateless_http=True` configuration (`NoBackChannelError`) and unverified on Claude's connector besides.

### Expected Features

**Must have (table stakes):**
- HAE webhook receiver with shared-secret header auth, idempotent upsert on natural keys, and a multi-shape metric parser (four distinct point shapes in one payload array)
- Metric allowlist limited to ~6 signals (`step_count`, `active_energy`, `walking_running_distance`, `flights_climbed`, `weight_body_mass`, `sleep_analysis` as `inBed` only) — not "ingest everything," which the vendor's own docs warn kills the automation
- `export.xml` backfill with an explicit `sourceName="Hevy"` exclusion filter — without it, the historical import silently double-counts sessions BRETT already owns
- Max-weight-primary progression with e1RM retained as a labelled secondary field (PROJECT.md requires retention, not removal)
- `training_programs` as real rows with an append-only active-program history, program-aware recomposition thresholds, and the confirm-gated write tool
- Manual body-measurement write path plus a fix to a latent `_dedupe_by_day` bug that manual entry activates
- One `fitness_get_weekly_report` / `fitness_get_monthly_report` composer (two windows, not two tools) over analytics that already exist

**Should have (differentiators):**
- Activity load (steps, active energy) as recomposition *context*, never a classifier input
- Dual-signal disagreement surfaced explicitly (max weight flat, e1RM improving = rep progression) rather than resolved
- Waist-vs-weight divergence as a recomposition signal — gated on the user actually logging enough waist data

**Explicit anti-features (cut, not deferred):**
- Ingesting Apple Health `workouts` into training analytics (97% Hevy duplicates)
- Sleep-stage/HRV/resting-HR "recovery score" analytics (zero records exist; no Apple Watch)
- A second MCP write tool, or a general MCP write API (PROJECT.md caps v2.0 at exactly one)
- Backend-generated coaching prose or a backend cron pushing reports (Claude writes narrative; Claude's scheduled-tasks feature drives cadence)
- Auto-deriving body fat % from circumferences, progress photos, nutrition of any kind

### Architecture Approach

Four of five capabilities fit the existing architecture without bending it: Apple Health ingestion is a new `integrations/health_auto_export/` package mirroring `integrations/hevy/`'s provider-isolation shape (just inbound instead of outbound); reports are a response-shaping layer over analytics functions that already compose (`fitness_get_training_summary` is the proof); manual measurement entry writes into a table (`body_measurements`) whose `source='manual'` column was built in v1.0 and is currently dead code. The confirm-gated write tool does **not** fit without deliberate, named changes: BRETT's read-only guarantee is enforced by a PostgreSQL `READ ONLY` transaction and three static source-scanning tests, all of which must be narrowed (never deleted) to allow exactly one write module.

**Major components:**
1. `api/routes/health_ingest.py` (NEW) — terminates the webhook; must be registered **above** the catch-all `app.mount("/", mcp_app)` in `main.py`, or every request silently 404s through the MCP sub-app
2. `integrations/health_auto_export/` (NEW) — schemas, normalizer, ingest/upsert, auth; shared by both the live webhook and the one-shot backfill CLI so the two never disagree about shape
3. `db/models/health.py` (NEW) — `health_daily_metrics` (day-grained, not sample-grained — 438k raw samples is 44% zero-value walking-gait noise) and `health_workouts` (stored but quarantined from all training analytics)
4. `db/models/program.py` (NEW) — `training_programs` + append-only `user_program_history` with a partial unique index enforcing at most one active row; a mutable single column was rejected because it retroactively re-classifies 12 weeks of past recomposition verdicts on every switch
5. `mcp/tools/programs.py` (NEW) — the **only** module in `app/mcp/` permitted to write, registered outside the shared `READ_ONLY` annotation loop with its own explicit annotation object

### Critical Pitfalls

1. **Route registration order** — a webhook router added below `app.mount("/", mcp_app)` (a catch-all, registered last on purpose) is dead code that imports fine and passes unit tests, but every real request 404s through the MCP sub-app. Register above the mount; test on FastAPI-shaped response bodies, not just "not 404."
2. **`confirm: bool` is not a confirmation gate** — the single highest-severity pitfall in the milestone. If `confirm` is a plain boolean tool parameter, the model can set it `true` on the first call; there is no protocol rule forcing a warn-then-confirm sequence, and `ctx.elicit()` is unavailable under BRETT's stateless transport besides. Fix: the warn call returns a server-issued, single-use, short-TTL, target-bound confirmation token; the switch call takes `confirmation_token: str`, not a boolean.
3. **Adding one write tool disarms the guards protecting the other thirteen** — the smallest way to add a write tool (relax `read_only_session`, delete `test_mcp_never_writes`, add the tool to the shared `READ_ONLY` annotation loop) silently un-protects every read tool or makes the annotation an active lie to the client. Narrow every guard to a named single-module allowlist; never delete.
4. **Non-idempotent ingest against a webhook with no retry** — Health Auto Export's default sync window re-sends the full previous day on every run with no sender-side dedup, and a rejected delivery is permanently lost data (no retry mechanism exists). Upsert on measurement identity `(user_id, source, metric, measured_at)`, never on the `session-id` header (unique per-request, not per-datapoint).
5. **Payload size vs. a 512 MiB instance and a 32 MiB Cloud Run request cap** — HAE warns payloads can reach "several hundred megabytes"; a 10 MB JSON body already peaks near 235 MB of RSS through parse + Pydantic validation. Requires both a deploy-time memory increase and a body-size-cap ASGI middleware that rejects oversized requests before parsing.

## Implications for Roadmap

Based on combined research, five phases plus two schedule-flexible "floaters":

### Phase 1: Apple Health Ingest Foundation
**Rationale:** Longest external lead time (the phone must be configured and data must accumulate while later phases run) and it defines the canonical metric shape every downstream phase reads. Also the phase where Pitfalls 1–5, 7, and 8 (route ordering, rate-limit collision, unauthenticated route, non-idempotent ingest, payload size, freshness-provider default, `VARCHAR(16)` truncation) must all be closed.
**Delivers:** `health_daily_metrics` + `health_workouts` schema and migration; `integrations/health_auto_export/` (schemas, normalizer, ingest, auth); the FastAPI webhook route registered correctly; `sync_state` extended for `provider='apple_health'`; a dedicated rate-limit bucket for the ingest path; the `--memory=1Gi` deploy change and new secret.
**Addresses:** Table-stakes Apple Health ingestion features from FEATURES.md.
**Avoids:** Pitfalls 1–5, 7 (partially — freshness fix completes in Phase 5), 8.

### Phase 2: Historical Backfill
**Rationale:** Deliberately separate from Phase 1 so the live webhook is proven before a 438k-element import runs; also the cheapest correctness test the normalizer will get (4.5 years of real data through the same code path).
**Delivers:** `backfill-apple-health` CLI using streaming `iterparse`, filtered to ~6 useful metric types, running through the **same** normalizer and upsert path as the webhook, with a hard `sourceName="Hevy"` exclusion filter.
**Addresses:** The one-time backfill table-stakes row from FEATURES.md.
**Avoids:** Pitfall 6 (`export.xml` OOM) and the Hevy-duplication anti-feature.

### Phase 3: Max-Weight Strength Signal (movable — may run first)
**Rationale:** No new I/O, no schema dependency — the data plumbing (`best_set_per_day` already computes `best_weight_kg`) is trivial; the risk is entirely in threshold re-derivation. Because it touches no external system, this phase could legitimately run *before* Phase 1 if Apple Health configuration stalls externally. It must land before reports (Phase 5), since it changes what the report and summary tools return.
**Delivers:** Max-weight-primary trend and plateau detection with e1RM retained as a labelled secondary field; re-derived (not merely renamed) `TREND_STABLE_BAND_PERCENT_PER_WEEK` and `PLATEAU_IMPROVEMENT_TOLERANCE` validated against live data, preserving their existing derived relationship; `recomposition.py` re-validated against the new verdict distribution.
**Addresses:** Capability #2 from FEATURES.md — max-weight as primary strength signal, with dual-signal disagreement surfaced rather than hidden.
**Avoids:** Pitfalls 10, 11, 12 (rep progression flattened, ungated max weight destroying the "we could not tell" honesty path, mis-calibrated constants).

### Phase 4: Training Programs (the write-tool phase)
**Rationale:** Must precede Phase 5 if reports are to be program-aware. Groups all write-path risk into one security-shaped phase rather than scattering it. This phase's success criteria should read like a threat model, not a feature list.
**Delivers:** `training_programs` + append-only `user_program_history` schema; program-aware `recomposition.py` thresholds (injected as parameters, keeping the classifier pure); `fitness_get_active_program` read tool; the confirm-gated `fitness_set_active_program` write tool with a server-issued single-use confirmation token; the three static MCP guards narrowed to a named single-module allowlist.
**Addresses:** Capability #5 from FEATURES.md — training programs as data, the milestone's only write path.
**Avoids:** Pitfalls 13, 14, 15, 16 (bypassable confirm, disarmed guards, `safe_tool` masking write outcomes, mutable-column history loss) — this cluster is the highest-severity set in the whole milestone.

### Phase 5: Health Analytics + Reports + Coaching Style
**Rationale:** Composes everything above (health data, settled strength verdict, programs) — sequenced last by construction. The report-tools spike (verifying Claude's scheduled-tasks feature can actually invoke an MCP tool autonomously) should run **early within this phase, before the report tools are built**, since a negative result should reshape scope rather than sink the phase at its end.
**Delivers:** `analytics/health.py` (activity trends, scoped to steps/energy/distance — explicitly not recovery); `analytics/reports.py` closed-period composition; `fitness_get_weekly_report` / `fitness_get_monthly_report`; a tightened `docs/coaching-instructions.md` rewritten once against the final tool registry.
**Addresses:** Capability #1's activity-analytics slice, Capability #3 (reports) from FEATURES.md.
**Avoids:** Pitfalls 17, 18, 19 (scheduled-task connector unreliability, report fan-out blowing the context/latency budget, coaching-doc character ceiling).

**Floaters (schedule where cheapest, no hard dependency):**
- Manual body-measurement entry + bulk CSV import (CLI-based, per architecture research) — natural fit with Phase 4's data-model thinking or Phase 1's CLI work. **Must ship the `_dedupe_by_day` fix in the same phase**, not after — Pitfall 9 notes this bug is dormant today and is activated the moment a manual row exists, and Apple Health (Phase 1) is the third source that also triggers it via alphabetical-precedence collision. If body measurements land after Phase 1, pull the precedence-map fix forward into Phase 1.
- Circumference/composition trend analytics beyond weight — independent of the health tables; data is thin (`fat_percent`/`lean_mass_kg` are 0 of 123 live rows), so per-metric coverage floors are required or most windows will honestly return `insufficient_data`.

### Phase Ordering Rationale

- Reports depend on everything else, so they sequence last — building them earlier guarantees a rewrite once the strength metric or program thresholds change underneath them.
- Max-weight and programs both terminate in `recomposition.py`'s verdict; landing both in one phase would produce a verdict change with two simultaneous causes and no clean regression baseline. They are deliberately separate phases (3 and 4).
- The Hevy-exclusion filter blocks the *backfill* (Phase 2), not the webhook (Phase 1) — going-forward deliveries can simply omit the `workouts` array from the HAE automation's data-type selection, but the historical file has no such switch.
- Pitfall 9 (the `_dedupe_by_day` bug) forces a cross-phase ordering constraint independent of the "natural" phase grouping: whichever of Phase 1 (Apple Health) or the manual-measurement floater ships first, the source-precedence fix must land with it.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 3 (max-weight strength signal):** the re-derived dead-band values have no correct answer on paper — they require live-data calibration against this user's actual plate-increment distribution, the same way the original e1RM thresholds were calibrated. Treat as its own research/validation sub-task before implementation.
- **Phase 4 (training programs / write tool):** confirmation-token design (issuance, storage, TTL, single-use consumption), scope strategy (`required_scopes` vs. tool-body scope checks against WorkOS AuthKit claims), and the per-mode vs. program-independent label-matrix decision all need to be resolved as explicit design decisions in the phase context, not defaulted.
- **Phase 5 (reports):** the scheduled-tasks reliability question is outside this repo's control (two GitHub issues closed "not planned" describe MCP tools never being injected into autonomous scheduled sessions) — spike it before committing to the phase's scope, and design the report tools to be fully valuable on-demand regardless of the spike's outcome.

Phases with standard, well-documented patterns (research-phase likely unnecessary):
- **Phase 1 (Apple Health ingest):** mostly *verification* work against facts already established in this research — the wire contract, idempotency pattern, and body-size mitigation are all specified with HIGH confidence.
- **Phase 2 (backfill):** a known streaming-XML pattern (`iterparse` + `elem.clear()`) already measured against the real file.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Verified by direct venv introspection, source reads of the installed `mcp`/`starlette` packages, and live memory/latency measurement on this project's own code — the strongest evidence class available |
| Features | HIGH for Apple Health (verified against vendor docs, vendor reference server source, two independent third-party implementations, and the user's own 438,649-record export); MEDIUM-HIGH for capabilities 2–5 (industry convention and published coaching guidelines, which genuinely disagree with each other on bulk/cut rate bands) |
| Architecture | HIGH for existing BRETT architecture and Apple Health data availability (read from committed source and the user's real export); MEDIUM for the Health Auto Export wire contract (vendor docs are thin in places and version-split) |
| Pitfalls | HIGH for everything grounded in repo source (read directly, including test-suite assertions); HIGH for Health Auto Export behavior (official docs); MEDIUM-HIGH for the Claude scheduled-task connector failure (two GitHub issues fetched directly, both closed "not planned," with independent server-log corroboration); MEDIUM for the Claude Desktop "Always approve" irreversibility claim (single community source) |

**Overall confidence:** HIGH

### Gaps to Address

- **`weight_body_mass` vs. `weight_&_body_mass` metric-name spelling is not settled by documentation** — three sources say the former, the vendor's own prose says the latter. Resolvable in five minutes with one real Manual Export from the phone before writing the normalizer; do this at the start of Phase 1.
- **Health Auto Export's retry/delivery semantics are undocumented** — assume at-least-once with overlapping windows (the *Previous 7 Days* window recommendation exists precisely so this doesn't need answering), but a single observed production run may allow a cheaper design later.
- **Whether Claude's custom connector implements the `elicitation` client capability is unverified** — irrelevant to the recommended design (two-call token confirm), but worth re-checking if elicitation is ever considered as a UX enhancement layered on top.
- **The max-weight dead-band has no empirical basis yet** — flagged above as a Phase 3 research flag; cannot be resolved on paper.
- **Whether HAE reuses one `session-id` across a batched export's requests, or mints one per request, is unknown** — determines whether it can serve as a batch-level correlation key (it must never serve as a dedup key regardless).
- **Where the manual-measurement write path lives** — CLI is recommended (lowest cost, no new auth surface) over an authenticated FastAPI route; confirm this during Phase 4/floater planning rather than defaulting silently.
- **Closed-period report anchoring (option a vs. b)** — recommend carrying the anchored-on-today recomposition verdict alongside closed-period volume/frequency/PRs rather than adding an `anchor_day` parameter to functions whose docstrings currently argue against one; decide explicitly in the Phase 5 context.

## Sources

### Primary (HIGH confidence)
- Direct venv/source introspection: `inspect.signature(MCPServer.add_tool)`, `ToolAnnotations`/`AuthSettings`/`AccessToken` model fields, installed `mcp 2.0.0`/`starlette 1.6.0` source reads
- The user's own `export.xml` (191,257,897 bytes, HealthKit Export Version 14, 438,649 records, 2022-03-10→2026-08-26) — parsed and counted directly, the primary evidence for all Apple Health data-availability claims
- BRETT repository source, read directly: `app/main.py`, `app/mcp/server.py`, `app/mcp/auth.py`, `app/mcp/tools/_common.py`, `app/analytics/{progression,recomposition,bodyweight,metadata,estimates}.py`, `app/db/models/*`, `app/integrations/hevy/*`, `app/middleware.py`, `app/config.py`, and the full `test_*_isolation.py` / `test_mcp_readonly.py` / `test_mcp_tool_schemas.py` / `test_coaching_doc.py` suites
- https://help.healthyapps.dev/en/health-auto-export/ (automations/rest-api, export-format, export-format/workouts, export-format/health-metrics — all pages dated 2026-08-23) — transport, auth, envelope, field shapes, date format
- `HealthyApps/health-auto-export-server` (vendor's own reference server source, read directly)
- https://docs.cloud.google.com/run/quotas — Cloud Run 32 MiB HTTP/1 request cap

### Secondary (MEDIUM confidence)
- `irvinlim/apple-health-ingester`, `meltforce/FreeReps`, `korosuke613/vitalbridge` — independent third-party HAE implementations corroborating field names and timestamp-format quirks
- https://github.com/anthropics/claude-code/issues/43397 and #45306 — scheduled-task MCP connector failures, both closed "not planned," with server-side protocol log corroboration
- Rate-band literature for bulk/cut/recomp (Helms, thebodybuildingdietitians.com, RippedBody-style recomp framing) — sources genuinely disagree; the disagreement itself is reported as a finding

### Tertiary (LOW confidence)
- Claude Desktop "Always approve cannot be undone" — single community source (kahunam.com), treated as a design risk rather than verified fact
- Whether the installed HAE app build emits 24-hour or 12-hour timestamps on this specific device — settable, unverified without a captured payload

---
*Research completed: 2026-09-02*
*Ready for roadmap: yes*
