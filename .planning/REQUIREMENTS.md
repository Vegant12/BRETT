# Requirements: BRETT — Milestone v2.1 Longitudinal Physique Analysis

**Defined:** 2026-09-05
**Core Value:** Claude can retrieve real, normalized workout data through the MCP server and answer training questions from actual data instead of guessing.

**Milestone goal:** Give BRETT a longitudinal record of physique observations — produced by Claude from progress photos BRETT never stores — so the monthly report reads across training, nutrition, measurements and visible physique in one view.

**Numbering:** continues from the v1.0/v2.0 requirement sets. `PHYS-*` is new to this milestone; `RPT-*`, `MCP-*` and `DEPLOY-*` continue their existing sequences.

---

## v2.1 Requirements

### Rating Model & Observation Capture

- [ ] **PHYS-01**: Claude rates each assessable muscle group on a fixed 5-level ordinal scale (Minimal, Emerging, Developed, Well-Developed, Standout), with the level definitions stored as a single verbatim-travelling constant so the anchors cannot drift in wording between sessions — the same pattern `recomposition.py`'s `INTERPRETATION_DISCLAIMER` already uses. Level 5 is defined relative to this same person's own physique only, so population comparison is structurally forbidden at the definition level rather than by convention
- [ ] **PHYS-02**: `Not Assessable` is a first-class per-muscle value carrying a short reason, never a forced numeric guess — mirroring `body_measurements.py`'s treatment of "we have nothing" as its own explicit signal. `abductors` and `adductors` are expected to be permanently not-assessable from standard photos
- [ ] **PHYS-03**: A physique observation is stored as a header row plus one narrow child row per `(observation, muscle_group)`, keyed on the existing 19-value `CanonicalMuscleGroup` enum with no new taxonomy. Ratings persist as a `String`-backed `StrEnum` guarded by a named `CHECK` constraint — never a native PostgreSQL `ENUM` type, which would orphan a `pg_type` on `DROP TABLE` and break the existing `test_migrations_round_trip`
- [ ] **PHYS-04**: Each observation carries three separately-capped qualitative free-text note fields — leanness, conditioning and symmetry — which are strictly qualitative and contain no numeric body-fat estimate
- [ ] **PHYS-05**: Each observation records confounder metadata as fields independent of the ratings themselves: which photo angles were present, pose state as a bounded enum (relaxed vs lightly flexed), and a short free-text conditions note. "The rating changed" and "the conditions were comparable" stay two separately inspectable facts, never one blended verdict
- [x] **PHYS-06**: A single-call, append-only, non-destructive MCP write tool records one physique observation, annotated `destructive_hint=False`. It does not use the two-call confirmation-token ceremony, which exists to gate an irreversible change that this write does not make
- [x] **PHYS-07**: A read tool returns the most recent prior observation — ratings, notes and confounder metadata — and is documented in both the tool description and `docs/coaching-instructions.md` as the required precursor to recording a new one. This is the anchoring mitigation, and it is honestly labelled as soft steering: nothing in MCP can force call ordering
- [x] **PHYS-08**: An observation can be marked superseded, with a reason, by a later correction. The row is retained in the ledger and excluded from diffs — never hard-deleted. This is the correction path for a duplicate observation or one recorded without a photo actually present

### Physique Progress Analytics

- [x] **PHYS-09**: `analytics/physique.py` computes a deterministic per-muscle-group ordinal diff between two observations — improved, unchanged, regressed, or not-comparable when either side is `Not Assessable` — with no model call, no image, and no arithmetic beyond ordinal comparison, satisfying the project's rule that analytics stays deterministic and testable
- [x] **PHYS-10**: A composed analytics function cross-references physique ratings against per-muscle training volume from `get_muscle_group_volume`, answering "is the underdeveloped area also the undertrained one?". BRETT performs the join; Claude is never asked to correlate two separate tool responses
- [x] **PHYS-11**: Every physique-touching response carries a required disclaimer field, travelling verbatim, stating that ratings are subjective model output rather than measurement — the same required-field posture `RecompositionResult.disclaimer` already holds. Model-generated ratings are never presented indistinguishably from measured figures such as kilograms lifted or grams of protein

### Rating Calibration

- [x] **PHYS-12**: Before the observation schema is finalized, a spike measures actual rating movement across repeated, blind and anchored calls on the same photo set. Its results set the diff thresholds and any elapsed-time floor, rather than those being guessed. The spike explicitly tests whether the anchoring mitigation in PHYS-07 causes a self-reinforcing ratchet — a slow drift no adjacent-pair diff can detect because every individual month-to-month comparison still looks reasonable

### Monthly Report Integration

- [ ] **RPT-04**: The monthly report carries a physique section — latest observation, per-muscle diff versus the prior observation, and the volume cross-reference — expressed as an Optional field on `ReportResult` populated by a period conditional in `compose_report`, mirroring the already-shipped `MonthlyReportResponse.narrative` precedent. The weekly report does not carry it, which requires splitting the currently-shared `_report_body_fields` projection deliberately
- [ ] **RPT-05**: `build_narrative` renders the physique section under its existing determinism contract — byte-identical across runs, no recommendation language, no number absent from the structured data. Claude-authored free-text notes travel to Claude as structured JSON fields but are never echoed into the narrative output, because a note's own presence in `model_dump_json()` would make any number inside it trivially "provable" and defeat the numeric-provenance check

### MCP Write-Guard Amendments

- [x] **MCP-07**: `_WRITE_ALLOWLIST` in `backend/tests/test_mcp_isolation.py` is widened to exactly two named modules, with the exact-membership property preserved rather than loosened — a second write tool still cannot pass by being skipped. Four assertions across two test files change deliberately
- [x] **MCP-08**: `test_annotations_are_an_exact_partition` in `backend/tests/test_mcp_tool_schemas.py` is restructured from a uniform `destructiveHint=True` assertion over all write tools into a per-tool annotation mapping, so a non-destructive write tool is expressible without weakening the assertion for the destructive one

### Deploy Safety

- [x] **DEPLOY-04**: `scripts/deploy-cloud-run.sh` gains a migration step, or an enforced `alembic current` versus `alembic heads` pre-flight that fails the deploy on drift, plus a documented single source of truth for the production `DATABASE_URL`. Production ran a schema behind deployed code three separate times during v2.0, each caught only during live verification
- [ ] **DEPLOY-05**: This milestone's new migration reaches production through the fixed pipeline, proving DEPLOY-04 works rather than asserting it

---

## Future Requirements

Deferred from v2.1 scope. Tracked, not roadmapped.

### Physique

- **PHYS-F01**: Minimum-elapsed-interval floor that refuses or flags a change claim when two observations are too close together. Deferred by user decision at the scoping gate; the monthly-only report cadence and PHYS-08's supersede mechanism partially cover the gap, since a spurious close-interval "regressed" can be superseded rather than living in the diff history permanently
- **PHYS-F02**: `fitness_get_physique_history` — an ad-hoc read tool for questions between monthly reports ("what was my chest rated in March?"). Research classed this as add-after-validation; the monthly report plus PHYS-07's prior-observation read may already cover it
- **PHYS-F03**: Model-identity provenance recorded per observation, so a drift discontinuity can be attributed to a model version change rather than to the physique. Cheap now, impossible to backfill — revisit if PHYS-12's spike shows meaningful cross-version movement
- **PHYS-F04**: Widening the free-text note caps if the chosen limit proves too tight in real use — a tuning decision, not a design one

### Carried operational debt

- **NUTR-F01**: D-06 production nutrition/activity coverage re-query, blocked throughout v2.0 by the sandbox command classifier on `gcloud secrets versions access`. `MEASURED_DAY_FLOORS` remains a documented UNMEASURED fallback until a human operator re-queries
- **HEVY-F01**: Verify Hevy's real rate limits. Carried unresolved from v1.0 — the retry policy is still unverified against an actual limit rather than confirmed unnecessary

---

## Out of Scope

Explicitly excluded. Each carries a specific reasoning chain that would be lost if compressed.

| Feature | Reason |
|---------|--------|
| Numeric body-fat-percentage estimation from a photo | Validated computer-vision methods carry 2–4% documented error against DEXA; trained human visual estimation carries ~3–5% error with ~2.7% inter-rater disagreement. An LLM on one uncontrolled phone photo, with no criterion measurement to ever check itself against, is the worst case in that literature. It also contradicts `recomposition.py`'s established refusal to treat body fat as an input. A real figure already exists as measured data in `fitness_get_body_measurement_trend`'s `fat_percent` column |
| Any photo storage or retention, temporary or otherwise | Decided at the milestone gate. Storing photos would make BRETT a store of the most privacy-sensitive data category it could hold, on a Cloud Run service deployed `--allow-unauthenticated`, with no object storage, retention policy or image-handling code anywhere in the system. A visual side-by-side is the user's own photo library, not BRETT's job |
| A composite whole-body physique score or tier | A single blended number hides exactly the per-muscle information this feature exists to preserve, and tier language is inherently a population-relative aesthetic judgment |
| Aesthetic or comparative-to-others judgments, including proportion-ideal scoring | Repeated visual self-scrutiny against an external standard is the mechanism implicated in body-checking research and is out of place in a tool whose own instructions state it is decision support, not a clinician. PHYS-01's level 5 definition forbids this structurally |
| Weekly or more frequent physique check-ins | Sub-2-week intervals fall below the real-change noise floor, so frequent re-rating encodes confounder noise as apparent regression — dishonest data, and increased checking frequency is linked to worsening body-image outcomes |
| Per-muscle multi-axis scoring (mass/symmetry/conditioning/separation × 19 groups) | IFBB's multi-axis precision is reliable only because 5–9 independent judges' rankings are averaged, a mechanism a single-rater monthly system cannot reproduce. 76 numbers a month from one uncalibrated rater is manufactured precision, not more signal |
| Gamification — streaks, badges, a score that goes up | Not requested, and creates exactly the compulsive-check-in incentive the body-checking research warns against |
| A hard-delete tool for physique observations | Rejected in favour of PHYS-08's supersede-with-reason. A hard delete is genuinely destructive, would need the two-call token ceremony, and would widen the write guard to three modules |
| A photo upload endpoint, object storage client, or any image library | Follows from the no-photo-storage decision. BRETT never receives an image byte, so none of this surface exists to build |
| Server-side vision API call from the backend | Claude does the vision work in-conversation. A model call inside `app/analytics/` would break the project's rule that analytics is deterministic and testable |
| Native iOS app for photo capture | Unchanged from v2.0's scope decision — no Apple Developer Program enrollment, and this milestone needs no capture app at all |
| Multi-user physique features | Consistent with every prior milestone: schema must not preclude multi-user later, but no multi-user UX is built |

---

## Traceability

Which phases cover which requirements. Populated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| PHYS-01 | Phase 16 | Planned |
| PHYS-02 | Phase 16 | Planned |
| PHYS-03 | Phase 16 | Planned |
| PHYS-04 | Phase 16 | Planned |
| PHYS-05 | Phase 16 | Planned |
| PHYS-06 | Phase 17 | Complete |
| PHYS-07 | Phase 17 | Complete |
| PHYS-08 | Phase 17 | Complete |
| PHYS-09 | Phase 17 | Complete |
| PHYS-10 | Phase 17 | Complete |
| PHYS-11 | Phase 17 | Complete |
| PHYS-12 | Phase 15 | Planned |
| RPT-04 | Phase 18 | Planned |
| RPT-05 | Phase 18 | Planned |
| MCP-07 | Phase 17 | Complete |
| MCP-08 | Phase 17 | Complete |
| DEPLOY-04 | Phase 14 | Complete |
| DEPLOY-05 | Phase 19 | Planned |
