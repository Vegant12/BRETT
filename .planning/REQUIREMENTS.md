# Requirements: BRETT v2.0

**Defined:** 2026-09-02
**Core Value:** Claude can retrieve real, normalized workout data through the MCP server and answer training questions ("Am I progressing?", "Which muscles are undertrained?") from actual data instead of guessing.

## v2.0 Requirements

Requirements for the v2.0 milestone. Each maps to roadmap phases. REQ-ID numbering continues from v1.0 (`.planning/milestones/v1.0-REQUIREMENTS.md`); category prefixes reused from v1.0 (HEALTH, BODY, COACH) continue their existing sequence, new capabilities get new prefixes (STR, RPT, GOAL).

### Apple Health Integration

- [ ] **HEALTH-06**: User's Apple Health activity data (steps, active energy, basal energy, distance, flights climbed) syncs into BRETT via a Health Auto Export webhook receiver — no native iOS app, no Apple Developer Program enrollment
- [ ] **HEALTH-07**: The webhook receiver authenticates inbound requests via a shared-secret bearer token (or equivalent header-based scheme), rejecting unauthenticated or mis-authenticated payloads
- [ ] **HEALTH-08**: Sync excludes Apple Health workouts and body-mass records that originate from Hevy's own HealthKit write-back, preventing double-counting of data BRETT already holds at higher fidelity
- [x] **HEALTH-09**: Sync is idempotent — reprocessing an overlapping export window does not create duplicate records
- [ ] **HEALTH-10**: A one-time historical backfill imports the user's existing `export.xml` Apple Health export, applying the same Hevy-exclusion filter as ongoing sync
- [x] **HEALTH-11**: Apple Health data freshness (`last_synced_at`) is surfaced through the same freshness/coverage envelope Hevy data already uses (DQ-01/DQ-02)

### Activity Analytics

- [ ] **HEALTH-12**: System calculates activity trends (steps, active/basal energy, distance) over configurable windows (7/14/30-day), following the existing trend-analytics pattern

*(Sleep and recovery indicators — resting heart rate, HRV, sleep quality — are explicitly cut from v2.0: the user's real Apple Health export has zero such records in 4.5 years. See Out of Scope.)*

### Nutrition

- [ ] **NUTR-02**: Nutrition data (calories, protein, carbs, fat, fiber, sugar, sodium) syncs into BRETT via the same Health Auto Export webhook receiver used for activity data — supersedes `NUTR-01`'s original "dedicated provider integration" framing; Apple Health already aggregates data from the user's existing nutrition-logging app, so no separate provider integration is needed
- [x] **NUTR-03**: Nutrition sync is idempotent, following the same dedup/idempotency guarantees as activity and body data
- [ ] **NUTR-04**: System calculates nutrition trends (daily/weekly average calories and macros) over configurable windows, consistent with existing trend-analytics patterns
- [x] **NUTR-05**: Nutrition data freshness is surfaced through the same freshness/coverage envelope (DQ-01/DQ-02)
- [ ] **NUTR-06**: A new read-only MCP tool exposes nutrition summary/trend data on demand, following the one-tool-per-analytics-slice pattern already used for volume, frequency, and body-weight trend

*(Scattered single-entry micronutrients — vitamins, minerals with 1-2 lifetime records — aren't a reliable ongoing source and are excluded; scope is calories + the six consistently-logged macros.)*

### Strength Tracking

- [ ] **STR-01**: Max-weight-lifted becomes the primary signal for exercise progression trend classification, replacing estimated-1RM as the default basis
- [ ] **STR-02**: Plateau detection uses max-weight-lifted as its primary signal, with dead-band/window thresholds re-derived against live training data rather than reused from the e1RM-tuned constants
- [ ] **STR-03**: Estimated-1RM remains available as a secondary data point on progression/records responses wherever it's already gated and valid — not removed from the system
- [ ] **STR-04**: Recomposition status's progression input reflects the max-weight-based trend rather than the e1RM-based one

### Reports

- [ ] **RPT-01**: A new MCP tool composes a weekly report — training volume, strength progression, weight/measurement changes, nutrition summary, trends, and actionable recommendations — for a given week
- [ ] **RPT-02**: A new MCP tool composes a monthly report with the same coverage, normalized appropriately for the longer window
- [ ] **RPT-03**: Report tools are verified against a real Claude scheduled-task run; if scheduled sessions cannot load MCP tools (a documented, unresolved risk), reports remain fully functional on-demand and that limitation is documented in `docs/coaching-instructions.md` rather than silently assumed to work

### Body Measurements

- [ ] **BODY-03**: User can manually record a body measurement (weight and/or any circumference/composition field) through a write path, stored with `source='manual'`
- [ ] **BODY-04**: Manual and Hevy-sourced measurements on the same day merge by field rather than one source overwriting the other's data — fixes `bodyweight.py`'s `_dedupe_by_day` all-or-nothing precedence before manual entry can trigger it
- [ ] **BODY-05**: System calculates trend/comparison analytics across circumference and composition measurements, not weight-only as today, following the existing body-weight-trend pattern

### Training Programs

- [ ] **GOAL-01**: User's active training program (Lean Bulk, Cut, or Recomp) is stored as data, not a hardcoded constant
- [ ] **GOAL-02**: Recomposition status thresholds and recommendations adapt to the active program (e.g., healthy weight-trend bands differ between a cut and a bulk)
- [ ] **GOAL-03**: A confirm-gated MCP write tool allows switching the active program by name — a first call without a valid confirmation token returns a warning plus a one-time token; only a second call echoing that exact token performs the switch (a bare `confirm: bool` is rejected as insufficient, since the model could set it `true` on the first call)
- [ ] **GOAL-04**: All MCP tools other than the program-switch tool remain read-only; the existing read-only guard test suite is extended to allow exactly this one exception, not relaxed generally

### Coaching Response Style

- [ ] **COACH-02**: `docs/coaching-instructions.md` is revised to further emphasize concise, simple answers that still cite real figures, extending the guidance already present
- [ ] **COACH-03**: `docs/coaching-instructions.md` documents the v2.0 tools (Apple Health activity data, max-weight strength progression, reports, measurement history, program switching), consistent with the existing tool-registry drift-guard test

## v2 Requirements (Deferred Beyond v2.0)

### Apple Health

- **HEALTH-01**: ~~iOS app requests and manages fine-grained HealthKit read permissions~~ — superseded; v2.0 uses a Health Auto Export webhook receiver, not a native app
- **HEALTH-03**: ~~iOS app syncs sleep duration/consistency, resting heart rate, and HRV where available~~ — superseded/deferred; no data exists in the user's real export (no Apple Watch), revisit only if the user starts wearing one
- **HEALTH-05**: ~~System correlates sleep and recovery indicators with training performance~~ — deferred, depends on HEALTH-03

### Nutrition

- **NUTR-01**: ~~Automatic/scraped nutrition provider integration (e.g. a MyFitnessPal-style API)~~ — superseded by `NUTR-02`; Apple Health via Health Auto Export achieves the same outcome without a dedicated provider integration, since the user's existing nutrition-logging app already writes to HealthKit

## Out of Scope

Explicitly excluded from v2.0. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Native iOS HealthKit app | Superseded by the Health Auto Export webhook receiver — no Apple Developer Program enrollment needed |
| Sleep / recovery trends (resting HR, HRV, sleep quality) | Zero data in the user's real Apple Health export across 4.5 years — no Apple Watch, sleep tracking stopped Nov 2024 |
| Ingesting Apple Health workouts | 218 of 221 in the user's real export are Hevy re-exports; ingesting them would double-count training data BRETT already holds at higher fidelity |
| Ingesting Hevy-sourced Apple Health body-mass records | 52 of 79 in the user's real export are Hevy re-exports; same double-counting risk as workouts |
| Manual nutrition entry; nutrition data not already in Apple Health | Only Apple-Health-sourced nutrition is in scope (NUTR-02–06); a manual-entry path or a dedicated provider integration beyond Apple Health was not requested |
| Micronutrient (vitamin/mineral) tracking | Scattered single-entry records in the user's real export, not a reliable ongoing source; scope is calories + the six consistently-logged macros |
| Write/delete MCP tools beyond the one confirm-gated program-switch tool | MCP otherwise stays read-only — a deliberate, narrowly-scoped exception, not a general opening of write access |
| BRETT-side scheduled report delivery (email, push, cron) | Reports are delivered via Claude's own scheduled-tasks feature or on-demand; no new scheduler/delivery infrastructure is built in BRETT itself |
| Multi-user product features | Schema must not preclude multi-user later, but no multi-user UX is built now |

## Traceability

Which phases cover which requirements. Populated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| HEALTH-06 | Phase 8 | Pending |
| HEALTH-07 | Phase 8 | Pending |
| HEALTH-08 | Phase 8 | Pending |
| HEALTH-09 | Phase 8 | Complete |
| HEALTH-10 | Phase 9 | Pending |
| HEALTH-11 | Phase 8 | Complete |
| HEALTH-12 | Phase 13 | Pending |
| NUTR-02 | Phase 8 | Pending |
| NUTR-03 | Phase 8 | Complete |
| NUTR-04 | Phase 13 | Pending |
| NUTR-05 | Phase 8 | Complete |
| NUTR-06 | Phase 13 | Pending |
| STR-01 | Phase 10 | Pending |
| STR-02 | Phase 10 | Pending |
| STR-03 | Phase 10 | Pending |
| STR-04 | Phase 10 | Pending |
| RPT-01 | Phase 13 | Pending |
| RPT-02 | Phase 13 | Pending |
| RPT-03 | Phase 13 | Pending |
| BODY-03 | Phase 11 | Pending |
| BODY-04 | Phase 11 | Pending |
| BODY-05 | Phase 11 | Pending |
| GOAL-01 | Phase 12 | Pending |
| GOAL-02 | Phase 12 | Pending |
| GOAL-03 | Phase 12 | Pending |
| GOAL-04 | Phase 12 | Pending |
| COACH-02 | Phase 13 | Pending |
| COACH-03 | Phase 13 | Pending |

**Coverage:**
- v2.0 requirements: 28 total
- Mapped to phases: 28 ✓
- Unmapped: 0

**By phase:**

| Phase | Requirements | Count |
|-------|--------------|-------|
| 8. Apple Health & Nutrition Ingest | HEALTH-06, HEALTH-07, HEALTH-08, HEALTH-09, HEALTH-11, NUTR-02, NUTR-03, NUTR-05 | 8 |
| 9. Historical Apple Health Backfill | HEALTH-10 | 1 |
| 10. Max-Weight Strength Signal | STR-01, STR-02, STR-03, STR-04 | 4 |
| 11. Body Measurement History | BODY-03, BODY-04, BODY-05 | 3 |
| 12. Training Programs & Confirm-Gated Write Tool | GOAL-01, GOAL-02, GOAL-03, GOAL-04 | 4 |
| 13. Health Analytics, Reports & Coaching Style | HEALTH-12, NUTR-04, NUTR-06, RPT-01, RPT-02, RPT-03, COACH-02, COACH-03 | 8 |

---
*Requirements defined: 2026-09-02*
*Last updated: 2026-09-02 after v2.0 roadmap creation (Phases 8-13, 28/28 mapped)*
