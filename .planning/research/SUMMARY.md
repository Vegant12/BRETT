# Project Research Summary

**Project:** BRETT v2.1 — Longitudinal Physique Analysis
**Domain:** Extending an already-shipped, heavily-guarded personal fitness backend (FastAPI + PostgreSQL + SQLAlchemy + remote MCP server) with a second write path: Claude-produced, per-muscle-group physique ratings and bounded free-text notes, derived from photos BRETT never receives or stores.
**Researched:** 2026-09-05
**Confidence:** MEDIUM-HIGH overall (HIGH on everything traceable to this repo's own code/tests and to live SDK verification; MEDIUM on the rating-scale design and the LLM self-consistency/anchoring claims, which are reasoned from adjacent literature rather than a measurement of this exact task)

## Executive Summary

This is not a greenfield feature — it is a narrow, well-precedented extension of a system that already has a strict, test-enforced architecture (one write path, a read-only MCP guard, deterministic byte-identical narrative generation). All four researchers converged, independently, on the same load-bearing shape: store physique data as one narrow child row per `(observation, muscle_group)` — mirroring `health_daily_metrics`, not the wide-row `body_measurements` shape — because coverage is inherently partial (a photo set may not show every muscle) and the 19-value `CanonicalMuscleGroup` taxonomy already lives in code, not in a database enum. No new runtime dependency is needed anywhere in the stack. The volume cross-reference ("is the underdeveloped area also the undertrained one?") is not a bonus feature layered on top — Stack, Features, Architecture, and Pitfalls research all treat it as load-bearing: it is simultaneously the feature's genuine differentiator over every reviewed competitor app, the mechanism that keeps the anchoring-ratchet risk from running unchecked for a year, and the honesty check against manufacturing a causal story from two independently-noisy signals.

The recommended approach: run a self-consistency/anchoring spike first (same discipline as Phase 2's auth spike and Phase 13's RPT-03 spike) to measure how much a rating actually moves across repeated, blind, and anchored calls on the same photos — this number should set the diff analytics' thresholds and the minimum-elapsed-time floor, not a guess. Ship a pre-deploy migration-safety fix before this milestone's own migration (0007) lands, since the deploy pipeline currently has zero migration step and has already let production drift behind deployed code three times. Build the write tool and a read tool together in the same phase, not write-then-read-later, because an append-only design with no correction path leaves `safe_tool`'s "unknown" (possible-but-unconfirmed) result state with nowhere to recover to without a read tool. Widen the read-only/write-annotation guards deliberately (exact-membership assertions grown by one, never loosened to a pattern match) rather than casually.

The primary risk this research surfaces and does not resolve is a genuine tension between the milestone gate's decision (single-call, append-only, no correction/delete tool) and a real gap that decision leaves open: duplicate observations and hallucinated ratings (a rating written when no photo was actually attached) have no correction path at all under this design. This is presented below as an open decision for requirements, with evidence on both sides — it should not be silently assumed either way going into roadmap phase-sequencing. A second, quieter risk is a numeric-provenance loophole: once Claude-authored free text is a field on the report result, any number inside that text trivially satisfies the existing "every number in the narrative is already in the structured data" test, defeating the property it exists to enforce, unless notes are excluded from `build_narrative`'s own output by design. Finally, the rating scale itself is original to this project — there is no published, validated instrument for photographic regional muscle-development scoring — and 2 of the 19 canonical muscle groups (abductors, adductors) are not assessable from any standard photo at all; both are stated limitations to carry forward, not gaps to paper over.

## Key Findings

### Recommended Stack

Zero new runtime dependencies. The existing `SQLAlchemy 2.0.52` + PostgreSQL (Neon) + `Pydantic 2.13.4` + `mcp==2.0.0` stack, already pinned in `pyproject.toml`, is sufficient for storage, MCP schema generation, and deterministic diff analytics. The only new artifacts are one Alembic migration (`0007`), one or two new SQLAlchemy models, new `StrEnum`/Pydantic types in `app/analytics/schemas.py`, and a new `app/analytics/physique.py` module.

**Core technologies (all reused, none new):**
- SQLAlchemy 2.0 (`Mapped[]`) — two new tables (`physique_observations`, `physique_observation_ratings`), same ORM pattern as every other table
- PostgreSQL (Neon) — storage plus a named `CHECK` constraint for defense-in-depth on the two closed vocabularies (muscle group, rating); no JSONB, no native `ENUM` type anywhere
- Pydantic 2.13.4 `StrEnum` — rating enum and MCP tool I/O schemas, identical pattern to `TrainingProgram`/`RecompositionStatus`
- `mcp==2.0.0` — verified live in this project's own venv: a `list[MuscleRating]` shape (a list of small `{muscle_group, rating}` objects) is the recommended tool I/O shape, not a `dict[MuscleGroup, Rating]` (uncommon `propertyNames`/`$ref` schema, implicated in an open, unresolved SDK client-quoting issue, #1373) and not a positional tuple list (model-unfriendly to produce)

**Two concrete, verified constraints worth carrying into implementation:** (1) never use a native Postgres `ENUM` type for the rating or muscle-group column — `DROP TABLE` does not drop the underlying `pg_type`, which would break this project's own `test_migrations_round_trip` (confirmed via still-open `sqlalchemy/alembic` issues #754/#886) — use `String` + app-layer `StrEnum` + a named `CHECK` constraint instead, exactly like `source`/`metric`/`program` today; (2) the rating scale should be a `StrEnum`-backed `String` column, never a `SmallInteger`, because the diff (`improved`/`unchanged`/`regressed`) is a three-way ordinal comparison via a Python-side rank lookup, never arithmetic — no averaging ever happens on it, so the project's no-float/`Decimal` discipline is never implicated.

### Expected Features

**Must have (table stakes) — all fully specified by research:**
- Structured per-muscle rating on the existing 19-value `CanonicalMuscleGroup` taxonomy — no new taxonomy
- A defined, fixed-anchor 5-level ordinal rating scale (Minimal / Emerging / Developed / Well-Developed / Standout), with `Not Assessable` as a first-class state, not a forced numeric guess
- Three bounded free-text fields (leanness, conditioning, symmetry notes — ~300 chars proposed, a tuning decision not a design one)
- Minimal confounder/context metadata per observation (`photo_angles_present`, `pose_state`, `conditions_note`) — without this, a comparison cannot distinguish real change from a lighting/pump/pose difference
- Single-call, append-only, non-destructive MCP write tool with prior-observation context returned at analysis time (the milestone's stated load-bearing drift mitigation)
- Deterministic diff (`analytics/physique.py`): improved/unchanged/regressed per muscle, `None`-safe for `Not Assessable`
- Cross-reference against `fitness_get_muscle_group_volume`
- Subjective-output disclaimer traveling verbatim on every physique-touching response, mirroring `RecompositionResult.disclaimer`
- Monthly-report-only integration, requiring `_report_body_fields` to be deliberately split (it is currently one shared projection)
- Narrowed read-only guard, updated per the Phase 12 `program_switch.py` precedent

**Should have (differentiators, evidence-grounded):** cross-referencing visible development against real per-muscle training volume (no reviewed consumer app — PeakBFF, GainFrame, LocalOne — has structured training-volume data to correlate against); anchored/relative rating methodology via prior-observation context (directly mitigates the single-rater, no-calibration-loop weakness the granularity literature flags); zero photo storage/retention as a genuine privacy differentiator, not merely a constraint; deterministic, reproducible diff logic instead of a recomputed opaque "score."

**Explicitly anti-featured (do not build):** precise numeric body-fat-percent estimation from a photo (even validated CV methods carry 2–4% error against DEXA; an LLM eyeballing one uncontrolled photo is the worst-case setup in the literature); a composite whole-body physique score/tier system (hides exactly the information the feature exists to preserve, and reads as population-relative gamification); aesthetic or comparative-to-others judgments (implicated in body-checking/body-dysmorphia research — the scale is structurally defined as relative-to-self only, never population-relative); weekly or more-frequent physique check-ins (sub-2-week intervals fall below the real-change noise floor per multiple independent progress-photo guides, and higher check-in frequency correlates with worse body-image outcomes in at-risk individuals); separate numeric axes per muscle (mass/symmetry/conditioning/separation × 19 groups) mirroring IFBB judging literally — IFBB's reliability comes from averaging 5-9 independent judges, a mechanism a single monthly rater cannot reproduce; gamification (streaks, badges, a score that goes up); any photo storage or retention, ever.

**Honest limitation, stated plainly, not buried:** no published, validated instrument exists for photographic regional muscle-development rating. BRETT's 5-level scale is *originated for this project*, synthesized from psychometric ordinal-scale-granularity literature and bodybuilding judging dimension lists — it is not adopted from an existing standard. Separately, 2 of the 19 canonical muscle groups (`abductors`, `adductors`) are not assessable from any standard photo at any angle — they blend visually into the quad/glute outline and are almost universally covered by clothing even when uncovered elsewhere. Several more groups (`upper_back`, `lower_back`, `rear_delts`, `triceps`, `hamstrings`, `glutes`) are only "partially assessable," requiring specific angles a routine 3-photo (front/side/back relaxed) protocol may or may not capture. `Not Assessable` must be a first-class, expected, honestly-common answer — not an edge case.

### Architecture Approach

The system already enforces "exactly one write module" via `test_mcp_isolation.py`'s `_WRITE_ALLOWLIST` (currently `frozenset({"program_switch.py"})`, asserted `len == 1` in three separate tests from three angles) and a separate uniform write-tool-annotation assumption in `test_mcp_tool_schemas.py`. This milestone widens both to exactly two named modules, deliberately, never by loosening an assertion's shape (`==` to `in`, `frozenset` to `set`, a length check to a range).

**Major components:**
1. `app/mcp/tools/physique.py` (new) — a `READ_ONLY` tool (`fitness_get_latest_physique_observation`) plus a second write path (`fitness_log_physique_observation`, `APPEND_ONLY_WRITE_TOOL` annotation, `destructive_hint=False` / `idempotent_hint=False`), using `writable_session` (never `read_only_session`), calling into the repository layer only
2. `app/db/repositories/physique.py` (new, mirrors `programs.py`) — the ONLY module allowed to construct `INSERT`s into the two new tables
3. `app/analytics/physique.py` (new) — `get_physique_diff()` and `get_physique_training_correlation()` (the volume cross-reference), both read-only, both provable against `test_analytics_isolation.py`'s existing static guards with zero new exemptions
4. `app/db/models/physique.py` + migration `0007` — two tables: `physique_observations` (header row, bounded free-text notes) and `physique_ratings` (narrow, one row per `(observation_id, muscle_group)`, `user_id` deliberately denormalized onto the child row for query efficiency)
5. `app/mcp/tools/reports.py` (modified) — `ReportResult.physique: PhysiqueSection | None`, populated only when `period is MONTHLY`, via a one-line branch inside `compose_report()` (mirrors the already-shipped `narrative` field's None-only-when-weekly pattern exactly)

**Two concrete, specific test-breakage points that must not be lost in planning:**
- `backend/tests/test_mcp_isolation.py:79` — `_WRITE_ALLOWLIST` — requires four coordinated assertion changes across this file (the frozenset itself, the `len == 1 -> == 2` bump at lines ~166-171, the renamed `test_the_write_allowlist_holds_exactly_one_module` -> `..._two_modules`, and the renamed `test_only_one_module_opens_a_writable_session` -> `..._the_allowlisted_modules...`), plus corresponding updates in `backend/tests/test_mcp_tool_schemas.py`
- `backend/tests/test_mcp_tool_schemas.py`'s `test_annotations_are_an_exact_partition` currently hard-codes a **uniform** `destructiveHint=True`/`idempotentHint=False` loop over every write tool. This breaks the moment the physique write tool ships with its truthfully different `destructive_hint=False` — the loop must become a per-tool `EXPECTED_WRITE_ANNOTATIONS` mapping, not merely extended

**The numeric-provenance loophole (architecture-level, requirement-relevant):** `test_analytics_reports.py`'s check that "every number in the narrative is already in `report.model_dump_json()`" is trivially defeated once Claude-authored free text becomes a field on `ReportResult` — any number inside a note (e.g., "waist down maybe an inch") is a substring of the JSON dump by construction, so the check passes green while providing no actual guarantee. Architecture's recommendation, treated here as a requirement-level constraint rather than an implementation detail: notes travel to Claude as structured JSON fields on the tool/report response (so Claude can read and relay them conversationally), but are **never** echoed into `build_narrative`'s own deterministic markdown output. The disclaimer field remains the one exception allowed to travel verbatim, specifically because it is a fixed backend-authored constant — free text has no equivalent property.

### Critical Pitfalls

1. **The vision model does not agree with itself, and there is no ground truth to check it against** (arXiv:2510.27106 on LLM-judge self-inconsistency) — mitigate by running a self-consistency spike before the schema/write-tool contract locks, and by persisting provenance (which model, when) with every observation so a model-version discontinuity is a queryable fact.
2. **The anchoring mitigation is also a ratchet** — feeding the prior observation as context solves absolute-rating drift but introduces assimilative anchoring bias (sequential-judgment literature on repeated ratings, including a radiologist-mammogram analogue); twelve one-step nudges in the same direction are indistinguishable, month to month, from twelve real improvements. Mitigate with a periodic blind re-anchor (no prior context passed every N months) and by making the volume cross-reference an active coherence check, not just narrative color.
3. **A rating sitting beside a measurement in one report reads as equally authoritative to both** — needs a required, non-optional disclaimer field (never `| None = None`) mirroring `RecompositionResult.disclaimer`, plus a distinct verb register ("rated as" vs. "measured") — a caveat sentence alone is documented not to reliably change how much weight readers give AI-labeled content.
4. **The determinism contract breaks in new ways specific to rated, textual content** — free text is the banned-token scan's actual first real test (advisory language is far more likely in a Claude-authored body note than in backend-composed prose), and any bare number in a note defeats numeric provenance. Enforce both checks at write time, not just in the narrative test suite, sharing the same token/number-pattern source as the existing tests.
5. **`_report_body_fields` is one shared projection, and physique is deliberately not shared** — the natural, minimal-diff way to add a field (inside the shared projection) is exactly the change that leaks physique into the weekly report, silently, with no existing test to catch it. Needs a positive-exclusion test, not just an absence of inclusion.

## Where the four researchers independently converged (stronger evidence than any single file)

At least three of the four research files arrived at the same conclusions from different angles, without reference to each other's specific reasoning:

- **A spike before the schema locks.** Pitfalls names this explicitly as the milestone's central, retirable-with-evidence risk (same shape as Phase 2's auth spike and Phase 13's RPT-03 spike). Architecture independently treats the taxonomy step-size, diff thresholds, and re-anchor cadence as unknowns a spike should produce, not a guess baked into the migration. Features independently notes the granularity literature's caveats do not transfer cleanly to an uncalibrated, single-rater system, arguing for the conservative (5-level, not 7 or 10) end of the range pending real evidence.
- **The narrow-child-table shape over the wide-row shape.** Stack derives it from `health_daily_metrics`'s own documented rationale (partial, evolving coverage) versus `body_measurements`'s wide-row rationale (atomic, all-or-nothing external payload). Architecture derives the identical conclusion independently from the same two files, plus the observation that every other muscle-group-shaped result in this codebase (`MuscleGroupVolume`, `roll_up_muscles`'s output) is already a list of narrow rows. Features' Section 2 visibility table supplies the empirical reason coverage really is partial: a given photo set may rate 12 of 19 groups, not all 19, because most angles don't reveal every muscle.
- **The volume cross-reference is load-bearing, not a bonus.** Features frames it as the genuine differentiator over every reviewed competitor app. Architecture frames it as data composition analogous to `RecompositionResult`'s existing two-signal pairing, deserving its own composed function rather than being left to Claude to eyeball. Pitfalls frames it, from two more directions, as (a) the coherence check that can actually catch the anchoring ratchet before a year of narrative drifts unmoored from reality, and (b) a distinct risk in its own right (Pitfall 12) — two independently-noisy signals agreeing is not proof of causation, and the narrative must never imply "underdeveloped because undertrained." All four treat this one feature as structurally required, not deferrable.

## An open tension the research does not resolve — flag for requirements, do not pre-decide

The milestone gate already decided: the physique write tool is **single-call, append-only, with no correction/delete tool** (a deliberate, low-friction design for a low-stakes, frequent action). Pitfalls research (Pitfalls 8 and 9) argues this leaves two real gaps with no accepted mitigation yet:

- **Duplicate observations have no correction path.** Nothing stops a model from calling the write tool twice for one real event (ambiguous response, conversation retry, `safe_tool` firing after a successful commit) and, under an append-only design, there is no canonical "current state" to read back and reconcile against — every row is permanent history, and a duplicate actively corrupts the diff analytics and the anchoring chain, not just the current-moment answer.
- **Hallucinated ratings have no correction path either.** Because BRETT never receives the image, it has no way to verify a photo was actually attached to the conversation that produced a write call. A model can call the write tool with a plausible rating in a conversation where no photo was ever sent — through misunderstanding, memory of an earlier photo, or outright fabrication — and there is no field, signature, or metadata BRETT can check against.

Pitfalls proposes partial mitigations that stop short of a correction tool: a required structured attestation field (`photo_count`/`photo_description`) at write time, an explicit coaching-instructions constraint restricting the tool to photo-attached turns, a duplicate-window flag for implausibly-close repeat calls, and — as a recovery-cost note, not a proposal to build now — that if this ever needs fixing post-ship, the honest fix under "append-only" is a `superseded_by`/`voided` marker rather than deletion, preserving the audit trail while letting analytics exclude the row. This summary does **not** resolve whether such a marker (or any correction mechanism) should be in v2.1's scope — that is a requirements-stage decision that needs the milestone gate's original single-call/append-only/no-correction reasoning weighed explicitly against this gap, with both sides on the table.

## Implications for Roadmap

Architecture and Pitfalls research each proposed a build order from different angles (Architecture from real code dependencies; Pitfalls from risk-retirement discipline). They reconcile into one coherent order:

### Phase 0: Pre-deploy migration safety (must come first — a real dependency, not a priority call)
**Rationale:** This milestone ships its own new migration (`0007`) into a deploy pipeline (`scripts/deploy-cloud-run.sh`) that today has zero migration step of any kind. Production has already drifted behind deployed code three times this milestone-cycle (Phase 8's `0004` vs `0005`, a Phase 9 operator `DATABASE_URL` mistake, Phase 13's `0005` vs `0006` `UndefinedTableError`). Shipping a fourth migration through the same unguarded script risks reproducing the exact same failure, this time on the milestone's own new table.
**Delivers:** A pre-deploy hook running `alembic upgrade head` (or an enforced `alembic current` vs `alembic heads` pre-flight that aborts on mismatch), proven via one real deploy before phase 3 below ships its own migration.
**Avoids:** The recurring deploy-drift pattern named explicitly in PROJECT.md's carried-forward debt.

### Phase 1: Self-consistency / anchoring spike
**Rationale:** The milestone's central, highest-uncertainty question (how much does a rating move across repeated/blind/anchored calls on the same photos) is currently unmeasured. The rating scale's step size, the diff analytics' improved/regressed thresholds, and the minimum-elapsed-time floor for a meaningful two-point diff are all downstream of this number. Building the schema first and hoping the spike's findings fit risks a second migration.
**Delivers:** A recorded spike result (same shape as `13-SPIKE-RESULT.md`) measuring rating movement, informing the concrete constants used in Phase 3.
**Addresses:** Features' rating-scale design section directly; retires Pitfalls 1 and informs Pitfall 2's re-anchor cadence and Pitfall 6's elapsed-time floor.

### Phase 2: Data model, migration, repository layer
**Rationale:** Foundational — nothing downstream can be built against real rows without it. Depends on Phase 1's spike only insofar as constants (step size, floors) are best set with evidence, not the schema shape itself, which research already resolved with high confidence.
**Delivers:** `physique_observations` + `physique_ratings` tables (narrow child-table shape, `String` + `StrEnum` + named `CHECK` constraints, no native `ENUM`), migration `0007`, `db/repositories/physique.py` (insert/read functions, the sole INSERT constructor).
**Implements:** Stack's Q1/Q3/Q4 recommendations; Architecture Section 7.

### Phase 3: Analytics layer + write/read MCP tools, together
**Rationale:** Pitfalls 8 and 9 argue explicitly that the write tool must not ship without a read tool in the same phase — an append-only design with no correction path leaves `safe_tool`'s "unknown" result state with nowhere to recover to without something to read back against. This also widens the write/annotation guards as its own reviewable step (mirroring how Phase 12 treated the original guard narrowing as a first-class change).
**Delivers:** `analytics/physique.py` (diff + volume cross-reference, both read-only, zero new exemptions from existing static guards), `mcp/tools/physique.py` (write tool + prior-observation read tool), widened `_WRITE_ALLOWLIST` and the per-tool annotation mapping in `test_mcp_tool_schemas.py`, `docs/coaching-instructions.md` updated with the read-before-write steering text and the photo-must-be-attached constraint.
**Avoids:** Pitfalls 3, 4 (write-time half), 7, 8, 9, 10.
**Open decision to surface during this phase's requirements pass:** the duplicate/hallucination correction-path tension above.

### Phase 4: Monthly report integration
**Rationale:** Depends on Phase 3's analytics functions existing to call; building Phase 3 first gives real, testable observation data to compose the report against rather than only hand-built fixtures, though it does not strictly gate this phase.
**Delivers:** `ReportResult.physique` (Optional, populated only when `period is MONTHLY`), `MonthlyReportResponse.physique` mirroring the existing `narrative` field pattern exactly, a new `build_narrative` "## Physique" section under the existing determinism/banned-token/numeric-provenance constraints (free text excluded from this output — see the numeric-provenance loophole above), and a positive-exclusion test proving the weekly report has no physique field.
**Avoids:** Pitfalls 4 (test-fixture half), 5, 11, 12.

### Phase 5: Production deploy of migration 0007
**Rationale:** The first real-world proof that Phase 0's fix actually prevents the failure mode it was built for.
**Delivers:** Closes the loop PROJECT.md names explicitly as carried-forward debt.

### Research Flags

Needs research or a dedicated spike during phase planning:
- **Phase 1 (spike):** by definition — this is the retirable-with-evidence risk itself; no amount of upfront research substitutes for measuring the actual model's behavior on the actual task.
- **Phase 3:** the exact resolution of the duplicate/hallucination tension (attestation field shape, whether any correction marker belongs in scope) needs a requirements-stage decision informed by, but not pre-empted by, this research.

Phases with standard, well-documented patterns (research-phase can be light or skipped):
- **Phase 2:** the schema shape, MCP tool I/O shape, and Alembic mechanics are all resolved with HIGH confidence, verified against this project's own live venv and existing precedents (`health_daily_metrics`, `TrainingProgram`).
- **Phase 4:** the wire-layer and analytics-layer pattern for a monthly-only section is a direct, already-shipped precedent (`narrative`'s own `Optional`-when-weekly shape) — low risk of needing new research.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Every claim verified either by reading this codebase's own precedents directly, by executing the actual installed `mcp==2.0.0` + `pydantic==2.13.4` in this project's venv, or against current official Alembic/GitHub issue sources, dated and quoted |
| Features | MEDIUM-HIGH | HIGH for everything structurally decided at the milestone gate; MEDIUM for the rating-scale design itself (no published, validated instrument exists — this is a reasoned synthesis, not a citation of an existing standard) and for muscle-visibility classification (anatomical/posing-guide reasoning, not a controlled study of real photos) |
| Architecture | HIGH | Every claim grounded in code actually read, with file names and line numbers cited throughout, not in the milestone's prose description of itself |
| Pitfalls | MEDIUM | HIGH on everything traceable to this repo's own code and tests; MEDIUM on the VLM/LLM self-consistency and anchoring claims, sourced to adjacent academic literature (LLM-judge self-inconsistency, sequential-judgment psychology, a radiologist-mammogram analogue) rather than to a controlled measurement of this exact model on this exact task — which is precisely what Pitfall 1's recommended spike exists to produce |

**Overall confidence:** MEDIUM-HIGH. The mechanical/architectural half of this milestone (schema, MCP guards, migration mechanics, report wiring) is HIGH confidence and directly precedented. The domain-specific half (does a 5-level scale actually work, how much does anchoring actually drift, what should the elapsed-time floor actually be) is honestly MEDIUM until the Phase 1 spike produces real numbers — which is exactly why that spike is sequenced first, not why the milestone should proceed without it.

### Gaps to Address

- **The duplicate/hallucination correction-path tension** (see "An open tension" above) — needs an explicit requirements-stage decision, not a default assumption in either direction.
- **Rating scale calibration** (step size, minimum-elapsed-time floor, re-anchor cadence) — currently `[ASSUMED]` placeholders pending the Phase 1 spike's real measurement; treat as one-constant changes if the spike's findings differ from the proposed defaults (5 levels, ~300-char notes, weeks-scale elapsed-time floor).
- **Free-text logging/privacy scope** — the existing `app/logging.py` redaction layers are built entirely for credential-shaped secrets and have no concept of "this text describes the user's body." Needs an explicit scoping decision (what logs at what level) as a phase deliverable, not an assumption that "no image stored" already covers this.
- **Model-identity/provenance on each observation** — worth deciding whether to persist which model version produced a rating (if reliably obtainable) so a future model-version discontinuity is a queryable fact rather than an invisible one.

## Sources

### Primary (HIGH confidence)
- This repository, read directly across all four research files: `backend/app/db/models/{health,body,program}.py`, `backend/app/db/base.py`, `backend/app/analytics/{schemas,recomposition,body_measurements,reports}.py`, `backend/app/normalization/muscles.py`, `backend/app/mcp/tools/{program_switch,body,programs,_common,server,reports,schemas}.py`, `backend/app/logging.py`, `backend/tests/test_mcp_isolation.py`, `backend/tests/test_mcp_tool_schemas.py`, `backend/tests/test_mcp_readonly.py`, `backend/tests/test_analytics_isolation.py`, `backend/tests/test_analytics_reports.py`, `backend/tests/test_migrations.py`, `backend/tests/test_cloud_run_deploy.py`, `backend/migrations/versions/0006_user_program_history.py`, `scripts/deploy-cloud-run.sh`, `docs/coaching-instructions.md`, `.planning/PROJECT.md`, `.planning/research/PITFALLS.md` (v2.0 predecessor, Pitfalls #13-16)
- Live execution against the installed `mcp==2.0.0` + `pydantic==2.13.4` in this project's own `.venv` — `MCPServer.tool()`, `list_tools()`, `call_tool()` exercised directly for dict/tuple/list-of-model schema shapes, including deliberately invalid inputs
- https://alembic.sqlalchemy.org/en/latest/autogenerate.html; https://github.com/sqlalchemy/alembic/issues/754 and #886 — Postgres `ENUM`/`DROP TABLE` interaction, both issues still open

### Secondary (MEDIUM confidence)
- https://github.com/modelcontextprotocol/python-sdk/issues/1373 — `$ref`-based enum schema client-quoting fragility, unresolved as of this research
- "Rating Roulette: Self-Inconsistency in LLM-as-a-Judge Frameworks," arXiv:2510.27106 (Oct 2025) — intra-rater reliability in subjective LLM scoring
- Yu & Zhang, PMC5995378 (sequential judgment bias); PMC5858736 (sequential context effects in mammogram interpretation) — anchoring/assimilation risk in repeated ratings
- PMC12887897 — AI-generated content labels do not reliably reduce persuasive weight, motivating structural rather than textual disclaimer separation
- ResearchGate/ScienceDirect/arXiv ordinal-scale-granularity literature — 4-7 category reliability sweet spot, extrapolated (not validated) to this single-rater, no-calibration-loop case
- Progress-photo protocol guides (SET FOR SET, Five Starr Physique, Gymnoteplus, MacroFactor) — confounder list (pump, glycogen, hydration, lighting, pose, clothing) and the sub-2-week noise-floor finding corroborating the milestone's monthly-only decision
- PubMed (Bolonchuk et al.); Nature npj Digital Medicine (x2) — visual/CV body-fat estimation error bounds, grounding the numeric-body-fat anti-feature

### Tertiary (LOW/MEDIUM confidence, vendor or single-source)
- GainFrame, PeakBFF, LocalOne Gym Pics product/blog content — competitor feature landscape, vendor marketing copy not independently verified
- WorkOS MCP-auth-providers blog — IdP comparison, treated as a shortlist not a verdict (not directly load-bearing for this milestone, carried from prior stack research context)

---
*Research completed: 2026-09-05*
*Ready for roadmap: yes*
