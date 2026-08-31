# Requirements: BRETT

**Defined:** 2026-08-23
**Core Value:** Claude can retrieve real, normalized workout data through the MCP server and answer training questions from actual data instead of guessing.

## v1 Requirements

Backend-first milestone: Hevy sync → PostgreSQL → analytics → read-only remote MCP server. iOS/HealthKit and nutrition auto-import are v2 (Milestone 2).

### Foundation

- [x] **FOUND-01**: Backend exposes a health endpoint reporting service and database status
- [x] **FOUND-02**: Database schema is managed via versioned Alembic migrations
- [x] **FOUND-03**: User's timezone is configurable (defaulting to Asia/Jakarta) and used for all daily/weekly calculations
- [x] **FOUND-04**: All timestamps are stored in UTC and converted to local time only at calculation/display boundaries
- [x] **FOUND-05**: Secrets (API keys, tokens, DB credentials) are never committed, are loaded from environment/secret storage, and never appear in logs

### Hevy Integration

- [ ] **HEVY-01**: System performs an initial full sync of the user's historical Hevy workouts via paginated API calls (Hevy's real pageSize cap is 10, not 50-100)
- [ ] **HEVY-02**: System performs incremental sync using Hevy's workout-events endpoint, correctly draining newest-to-oldest pages before applying changes oldest-first (naive cursor advancement silently loses events)
- [x] **HEVY-03**: Hevy sync is idempotent — running it repeatedly never creates duplicate workouts, exercises, or sets (Hevy's child objects have no stable IDs, so exercises/sets are keyed by workout + reinserted transactionally, not upserted individually)
- [x] **HEVY-04**: Deleted Hevy workouts are detected and reflected in the local database without corrupting other data
- [ ] **HEVY-05**: Hevy-specific request/response logic is isolated inside `backend/app/integrations/hevy/`
- [ ] **HEVY-06**: System syncs Hevy exercise templates, capturing each exercise's primary and secondary muscle groups
- [ ] **HEVY-07**: System syncs Hevy body measurements (weight, body fat %, waist, and other available fields) as an automatic data source, in addition to manual entry
- [ ] **HEVY-08**: A sync failure (network error, malformed response, rate limit) does not corrupt previously-synced data
- [ ] **HEVY-09**: Each data source (Hevy workouts, Hevy body measurements) exposes a `last_synced_at` timestamp

### Exercise Normalization

- [x] **NORM-01**: Every synced exercise is mapped to one or more canonical muscle groups, including a front/side/rear deltoid split that Hevy's own taxonomy does not provide
- [ ] **NORM-02**: Muscle-group mappings can be manually overridden, with the override auditable against the original source mapping
- [x] **NORM-03**: Each mapped exercise distinguishes direct (primary) vs indirect (secondary) muscle involvement, with a configurable weighting (default 1.0 direct / 0.5 indirect) applied at query time

### Analytics — Volume & Frequency

- [x] **VOL-01**: System calculates weekly training volume (hard sets, reps, and — where the exercise modality supports it — tonnage), excluding warm-up sets from all volume figures
- [x] **VOL-02**: System calculates weekly per-muscle-group volume, broken out by direct and indirect sets
- [x] **VOL-03**: System calculates training frequency per muscle group and per exercise (sessions/week)

### Analytics — Progression & Records

- [ ] **PROG-01**: System calculates an exercise's progression time series (weight, reps, sets, and an estimated 1RM only where the exercise's modality and rep range make the estimate meaningful — otherwise returns null with a reason)
- [ ] **PROG-02**: System classifies each tracked exercise's recent trend as improving, stable, declining, or unclear, based on multiple sessions rather than a single workout
- [ ] **PROG-03**: System detects plateaus using a configurable multi-week window, returning the window and threshold used alongside the result
- [ ] **PROG-04**: System detects personal records (max weight, max reps at a weight, estimated-1RM PR, volume PR, rep PR) with the date of each, excluding warm-up sets
- [ ] **CMP-01**: System can compare two time periods (e.g. last 4 weeks vs previous 4 weeks) with values normalized per week so unequal-length windows don't produce misleading deltas

### Body Composition & Recomposition

- [x] **BODY-01**: System calculates rolling body-weight averages (7/14/30-day) and weekly rate of change from synced measurements
- [ ] **BODY-02**: System classifies overall recomposition status (e.g. progressing, muscle gain, fat loss, weight stable, too fast/slow, insufficient data) from combined weight trend, training volume, and progression data, explicitly framed as decision support rather than a medical or diagnostic claim

### Data Quality & Trust

- [x] **DQ-01**: Every analytics response includes freshness metadata (when underlying data was last synced) so Claude can recognize stale data
- [x] **DQ-02**: Every analytics response includes coverage/uncertainty metadata (e.g. sessions in window, insufficient-data flags) so Claude does not treat sparse data as a confident result

### MCP Server

- [x] **MCP-01**: A remote MCP server is deployed and reachable over HTTPS, independent of any specific device's local configuration
- [ ] **MCP-02**: MCP server exposes purpose-built, read-only tools covering: recent workouts, a composed training summary, weekly volume, muscle-group volume, exercise progression, personal records, plateaus, training frequency, body-weight trend, recomposition status, and period comparison
- [ ] **MCP-03**: MCP tools return compact, structured JSON — never raw database access or unbounded result sets
- [x] **MCP-04**: MCP server authenticates requests and rejects unauthenticated ones; the authentication mechanism is verified working end-to-end from an actual Claude client (not just a local test client) before being considered done
- [ ] **MCP-05**: No MCP tool can modify, delete, or write any data — the server is read-only in v1
- [ ] **MCP-06**: No API keys, database credentials, or internal secrets are ever returned in an MCP tool response

### Deployment & Coaching

- [x] **DEPLOY-01**: Backend and MCP server are deployed to Google Cloud Run over HTTPS, with every credential supplied from Google Secret Manager and nothing committed
- [x] **DEPLOY-02**: A Claude custom connector can be added pointing at the deployed MCP endpoint and successfully discovers and calls tools
- [ ] **DEPLOY-03**: System includes automated tests covering Hevy sync (auth, pagination, incremental events, duplicate prevention, deletions, failures), analytics calculations against known workouts, and MCP tool schemas/auth/output structure
- [ ] **COACH-01**: A separate system-prompt/instructions document defines the body-recomposition coaching behavior and decision framework for Claude to follow when using the MCP tools

## v2 Requirements

Deferred to Milestone 2 (HealthKit / nutrition), plus v1.x additions to add once v1 is validated against real data.

### HealthKit & Milestone 2

- **HEALTH-01**: iOS app requests and manages fine-grained HealthKit read permissions
- **HEALTH-02**: iOS app syncs steps, active energy, and exercise minutes with 7/30-day trends
- **HEALTH-03**: iOS app syncs sleep duration/consistency, resting heart rate, and HRV where available
- **HEALTH-04**: iOS app syncs Apple Health workouts (type, duration, energy, distance)
- **HEALTH-05**: System correlates sleep and recovery indicators with training performance
- **NUTR-01**: System supports an automatic nutrition data provider (beyond manual entry)
- **RECOMP-02**: Recomposition status incorporates calories, protein, steps, and activity alongside weight and training data

### v1.x Analytics Enhancements

- **AN-V1X-01**: Volume landmark bands (MEV/MAV/MRV) per muscle, user-configurable and labeled as heuristics
- **AN-V1X-02**: Muscle balance ratios (push:pull, quad:hamstring, deltoid-head share)
- **AN-V1X-03**: RPE-derived stimulus-quality metrics with explicit RPE-coverage percentage
- **AN-V1X-04**: Exercise substitution/equivalence grouping to prevent false plateaus from variant swaps
- **AN-V1X-05**: "What to progress next" ranked candidate list
- **AN-V1X-06**: Routine adherence (planned vs actual, using Hevy's routines endpoints)
- **AN-V1X-07**: Session density / duration trend signals

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Write/mutation MCP tools (log, edit, or delete workouts/data) | Explicitly excluded per blueprint and PROJECT.md — an LLM with write access to years of training history is a correctness and security risk the project does not need to take in v1 |
| Gamification (streaks, badges, XP) | No UI to display them and no user to motivate beyond the one person who already opted in; risks incentivizing training when a deload is correct |
| Push notifications / proactive check-ins | MCP is request-response; the server cannot initiate a Claude conversation. Staleness/gap data is surfaced instead so Claude can raise it when asked |
| Social feed, friends, sharing, leaderboards | Single-user by definition; would mean exposing personal health data over a public surface, conflicting with the project's privacy constraints |
| Generic "run a query" / raw-table MCP tools | Blows the context window, pushes arithmetic onto the LLM, reopens the data-exfiltration surface the purpose-built-tool design exists to close |
| Backend-generated natural-language "insights" or coaching prose | Claude is the narrative layer; backend prose would be untestable and could contradict Claude's own reasoning in the same response |
| Composite readiness/recovery/fatigue score in v1 | No sleep, HRV, or resting HR exists until Milestone 2; a score built from training volume alone would be a repackaged number an LLM would over-trust |
| ACWR / training-monotony / training-strain metrics | Developed for team field sports; injury-risk predictive validity is actively contested in the literature; not worth the complexity for a hypertrophy/recomposition use case |
| Live Hevy fetch on every MCP request | Contradicts "PostgreSQL is the source of truth"; Hevy's pageSize cap of 10 would make every Claude turn slow and rate-limit-prone |
| Charts, images, or rendered visuals from MCP tools | MCP consumers can't render a PNG; Claude can build a table or artifact from structured data if the user wants a visual |
| Multi-user product UX (accounts, per-user auth flows beyond schema readiness) | Personal project for one user; schema must not preclude multi-user later, but no multi-user UX is built now |
| OAuth-based MCP auth as the default v1 assumption | Research found Claude's custom-connector UI does not expose a plain bearer-token field, and `static_headers` beta access is unconfirmed for a personal account — the actual mechanism (bearer via beta access, or a minimal OAuth resource-server shim) will be resolved by the Phase 2 deploy/auth spike rather than assumed upfront |

## Traceability

Every v1 requirement maps to exactly one phase. See `.planning/ROADMAP.md` for phase detail.

| Requirement | Phase | Phase Name | Status |
|-------------|-------|------------|--------|
| FOUND-01 | Phase 1 | Backend Foundation | Complete |
| FOUND-02 | Phase 1 | Backend Foundation | Complete |
| FOUND-03 | Phase 1 | Backend Foundation | Complete |
| FOUND-04 | Phase 1 | Backend Foundation | Complete |
| FOUND-05 | Phase 1 | Backend Foundation | Complete |
| MCP-01 | Phase 2 | Deploy & Connector Auth Spike | Complete |
| MCP-04 | Phase 2 | Deploy & Connector Auth Spike | Complete |
| DEPLOY-01 | Phase 2 | Deploy & Connector Auth Spike | Complete |
| DEPLOY-02 | Phase 2 | Deploy & Connector Auth Spike | Complete |
| HEVY-01 | Phase 3 | Hevy Integration & Normalization | Pending |
| HEVY-02 | Phase 3 | Hevy Integration & Normalization | Pending |
| HEVY-03 | Phase 3 | Hevy Integration & Normalization | Pending |
| HEVY-04 | Phase 3 | Hevy Integration & Normalization | Pending |
| HEVY-05 | Phase 3 | Hevy Integration & Normalization | Pending |
| HEVY-06 | Phase 3 | Hevy Integration & Normalization | Pending |
| HEVY-07 | Phase 3 | Hevy Integration & Normalization | Pending |
| HEVY-08 | Phase 3 | Hevy Integration & Normalization | Pending |
| HEVY-09 | Phase 3 | Hevy Integration & Normalization | Pending |
| NORM-01 | Phase 3 | Hevy Integration & Normalization | Pending |
| NORM-02 | Phase 3 | Hevy Integration & Normalization | Pending |
| NORM-03 | Phase 3 | Hevy Integration & Normalization | Pending |
| VOL-01 | Phase 4 | Volume & Frequency Analytics | Complete |
| VOL-02 | Phase 4 | Volume & Frequency Analytics | Complete |
| VOL-03 | Phase 4 | Volume & Frequency Analytics | Complete |
| DQ-01 | Phase 4 | Volume & Frequency Analytics | Complete |
| DQ-02 | Phase 4 | Volume & Frequency Analytics | Complete |
| PROG-01 | Phase 5 | Progression, Records & Recomposition Analytics | Pending |
| PROG-02 | Phase 5 | Progression, Records & Recomposition Analytics | Pending |
| PROG-03 | Phase 5 | Progression, Records & Recomposition Analytics | Pending |
| PROG-04 | Phase 5 | Progression, Records & Recomposition Analytics | Pending |
| CMP-01 | Phase 5 | Progression, Records & Recomposition Analytics | Pending |
| BODY-01 | Phase 5 | Progression, Records & Recomposition Analytics | Complete |
| BODY-02 | Phase 5 | Progression, Records & Recomposition Analytics | Pending |
| MCP-02 | Phase 6 | MCP Tools | Pending |
| MCP-03 | Phase 6 | MCP Tools | Pending |
| MCP-05 | Phase 6 | MCP Tools | Pending |
| MCP-06 | Phase 6 | MCP Tools | Pending |
| DEPLOY-03 | Phase 7 | Production Hardening & Coaching Layer | Pending |
| COACH-01 | Phase 7 | Production Hardening & Coaching Layer | Pending |

**Coverage:**
- v1 requirements: 39 total
- Mapped to phases: 39 ✓
- Unmapped: 0 ✓
- Duplicated across phases: 0 ✓

**Per-phase counts:**

| Phase | Requirements | Count |
|-------|--------------|-------|
| 1. Backend Foundation | FOUND-01..05 | 5 |
| 2. Deploy & Connector Auth Spike | MCP-01, MCP-04, DEPLOY-01, DEPLOY-02 | 4 |
| 3. Hevy Integration & Normalization | HEVY-01..09, NORM-01..03 | 12 |
| 4. Volume & Frequency Analytics | VOL-01..03, DQ-01, DQ-02 | 5 |
| 5. Progression, Records & Recomposition Analytics | PROG-01..04, CMP-01, BODY-01, BODY-02 | 7 |
| 6. MCP Tools | MCP-02, MCP-03, MCP-05, MCP-06 | 4 |
| 7. Production Hardening & Coaching Layer | DEPLOY-03, COACH-01 | 2 |

---
*Requirements defined: 2026-08-23*
*Last updated: 2026-08-30 after phase 4 plan 04-08 (VOL-01..03, DQ-01, DQ-02 marked complete)*
