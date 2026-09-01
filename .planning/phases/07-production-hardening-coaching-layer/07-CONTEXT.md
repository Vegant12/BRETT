# Phase 7: Production Hardening & Coaching Layer - Context

**Gathered:** 2026-09-01
**Status:** Ready for planning

<domain>
## Phase Boundary

The deployment is production-grade and Claude actually coaches — the end-to-end Hevy → Postgres
→ analytics → MCP → Claude path works against real data. Delivers: an automated test suite
including the mock-Hevy-to-MCP end-to-end integration test (DEPLOY-03), rate limiting on the MCP
endpoint applied ahead of handler work, a proven backup/restore path and a proven secret-rotation
procedure, and the coaching system-prompt/instructions document (COACH-01) verified live against
real synced data.

**Explicitly NOT this phase:** New analytics, new MCP tools, changing the auth mechanism itself
(WorkOS AuthKit OAuth 2.1 was decided and verified in Phase 2 — this phase finalizes/hardens
around it, it does not re-litigate it).

</domain>

<decisions>
## Implementation Decisions

### Backup & Restore
- **D-01:** Rely on **Neon Postgres's built-in point-in-time recovery (PITR) and branching** as
  the backup/restore mechanism. No independent `pg_dump`/`pg_restore` script is built this
  phase — Neon-native is sufficient for this project's scale and self-paced, single-user,
  cost-conscious posture. (User explicitly chose Neon-only over "also build a scripted
  pg_dump/pg_restore path" and over "both".)
- **D-02:** ROADMAP success criterion #3 ("a database backup restores into a fresh instance with
  no data loss") is proven via a **one-time manual verification during phase execution**, not an
  automated/CI test: create a Neon branch from a recent point in time, compare row
  counts/checksums against production, and document the exact steps and result in a runbook doc.
  This mirrors how Phase 2's connector-auth verification matrix worked (manual checklist, not
  CI) — Neon branching needs real Neon API/CLI access against the live project, which isn't
  something to script into the automated test suite this phase also has to build.

### Secret Rotation
- **D-03:** Only **`MCP_AUTH_SECRET`** (the static bearer token compared in `StaticTokenVerifier`)
  gets a documented/tested rotation procedure this phase. `DATABASE_URL` and `HEVY_API_KEY` were
  explicitly considered and **not** selected — `HEVY_API_KEY` isn't in the live connector's
  request path at all (sync-job only), and `DATABASE_URL` rotation wasn't chosen as in-scope
  despite being offered as an option.
- **D-04:** Rotation procedure, matching how secrets are actually wired
  (`--set-secrets=...:latest` in `scripts/deploy-cloud-run.sh`, which only takes effect on
  redeploy): add a new version to the existing `brett-mcp-auth-secret` Secret Manager secret,
  run the deploy script (picks up `:latest`), then verify against the **live** `/mcp` endpoint —
  one request with the **old** token (expect 401) and one with the **new** token (expect
  success). No new code — this exercises `StaticTokenVerifier` exactly as already built. No
  dual-secret/grace-period mechanism (was offered, not chosen) — a rotation is a hard cutover,
  which is acceptable because the static path is CLI/rollback-only, not the primary live
  connector auth.

### Coaching Instructions Document (COACH-01)
- **D-05:** Follow blueprint §34-36 closely: the "Personal Body Recomposition Coach" persona,
  the 5 core objectives, the 7-step decision framework, and the example-question list, all
  reproduced/adapted from the blueprint (CLAUDE.md names the blueprint authoritative for phase
  content).
- **D-06:** Additionally include an **explicit mapping from question types to actual MCP tool
  names** — e.g. "for progression questions, call `fitness_get_exercise_progression`; for 'am I
  progressing overall', call `fitness_get_training_summary`" — using the real 12 tool names built
  in Phase 6, not generic guidance. Makes the document immediately actionable instead of relying
  on Claude to infer tool choice from schemas alone.
- **D-07:** File location: **`docs/coaching-instructions.md`**, alongside the existing
  `docs/hevy-api-observations.md`.
- **D-08:** Loading mechanism the document is written for: pasted into a **Claude.ai/Desktop
  Project's custom instructions**, once, in a Project that also has the BRETT MCP connector
  attached — so every conversation in that Project automatically has both the coach persona and
  live data access, rather than being re-pasted per conversation.
- **D-09:** ROADMAP success criterion #4 is proven via a **manual UAT checkpoint during phase
  execution**: set up (or reuse) a Claude Project with the connector attached and the document
  loaded as custom instructions, ask both example questions from the criterion ("Am I
  progressing?", "Which muscles are undertrained?") plus one question expected to surface
  stale/sparse data, and record the transcript/result in a verification doc. This is
  human-in-the-loop by nature — it is not something a subagent can script, same category as the
  Phase 2 connector-auth checkpoint.

### Claude's Discretion
- Exact runbook doc name/location for the backup-restore verification steps (D-02) and the
  secret-rotation steps (D-04) — no existing convention to match beyond "documented, like Phase
  2's verification matrix"
- Exact wording/structure of the coaching document beyond the blueprint outline (D-05) and the
  tool-name mapping (D-06) — e.g. how much narrative vs. bulleted framework
- Where the UAT transcript/result gets recorded (D-09) — e.g. a `07-COACH-VERIFICATION.md` or
  similar, Claude's discretion on naming, consistent with other phase verification artifacts

### Areas Explicitly Not Discussed (left to research/planning discretion)
Two gray areas were surfaced but the user did not select them for discussion — they remain real
work items for this phase (both are in ROADMAP's success criteria and REQUIREMENTS' DEPLOY-03)
but carry no user-specified constraints beyond what's already decided elsewhere in this project:
- **Rate limiting** — mechanism, keying (IP vs. authenticated identity), limit numbers, and 429
  response shape are all open. CLAUDE.md's "Alternatives Considered" table recommends an
  in-process token-bucket keyed on client IP as sufficient at this project's scale, reaching for
  `slowapi`/`limits` only if the API opens to the iOS app later — a reasonable default absent
  further user input, but not a locked decision.
- **Test coverage gap** — how deep the new mock-Hevy-to-MCP end-to-end integration test (ROADMAP
  criterion #1, blueprint §43) needs to go, and whether any other coverage gaps count against
  DEPLOY-03, beyond the 47 test files that already cover Hevy sync, analytics, and MCP tools
  individually. `backend/tests/test_hevy_end_to_end.py` currently stops at Postgres — it does not
  exercise analytics or MCP.

### Production Hevy Sync Scheduling
- **D-10 (added post-research 2026-09-01):** Fold production Hevy sync scheduling into this
  phase. `README.md` states "production scheduling is Phase 7," but no requirement, success
  criterion, or the decisions above covered it — without it, "the deployment... works against
  real data" decays daily since nothing keeps synced data fresh once the phase ships. Surfaced
  as Open Question 1 in `07-RESEARCH.md`; user chose to fold it in rather than defer or drop.
  Mechanism (Cloud Run Job + Cloud Scheduler vs. other) and cadence are Claude's discretion at
  planning time — no user constraint given beyond "in scope."

### Folded Todos
None — `.planning/todos/pending/` is empty (per STATE.md "Pending Todos: None yet").

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` §"Phase 7: Production Hardening & Coaching Layer" — goal, 4 success
  criteria, requirements (DEPLOY-03, COACH-01), depends on Phase 6
- `.planning/REQUIREMENTS.md` — DEPLOY-03 (automated test suite: Hevy sync, analytics, MCP tool
  schemas/auth/output structure) and COACH-01 (coaching system-prompt/instructions document)
- `.planning/PROJECT.md` §"Active" — DEPLOY-03/COACH-01 as the two remaining Active requirements
  for v1; §"Core Value" — the two questions this phase's coaching document and UAT (D-09) verify
  directly

### Backup, restore & secret rotation
- `scripts/deploy-cloud-run.sh` — the exact `--set-secrets=DATABASE_URL=...,MCP_AUTH_SECRET=...`
  wiring D-04's rotation procedure exercises; secrets only take effect on redeploy, not live
- `deploy/cloud-run.env.yaml` — non-secret env vars; confirms secrets are bound only via
  `--set-secrets`, never written here (T-02-10 in the file's own comments)
- `backend/app/mcp/auth.py` — `StaticTokenVerifier` (constant-time comparison against
  `MCP_AUTH_SECRET`) and `AuthKitJWTVerifier`; D-04's rotation test targets `StaticTokenVerifier`
  specifically
- `.planning/phases/02-deploy-connector-auth-spike/02-CONTEXT.md` — D-06d (Google Secret Manager
  for all secrets, no value ever written to a file in the repo) and D-06e (checked-in,
  test-asserted deploy script) — the constraints D-04's rotation procedure must respect
- No existing canonical doc for Neon PITR/branching mechanics — this is new ground; the runbook
  written this phase becomes the canonical reference for future rotations/restores

### Coaching instructions document
- `BRETT blueprint.md` §34 "Claude Fitness Coach Instructions" — persona ("Personal Body
  Recomposition Coach"), 5 core objectives (build muscle, reduce unnecessary body fat, improve
  strength, maintain sustainable habits, avoid unnecessary program changes)
- `BRETT blueprint.md` §35 "Claude Decision Framework" — the 7-step framework (retrieve data →
  establish time period → compare recent vs. previous → identify trends → identify bottlenecks →
  smallest useful intervention → define what to track next); explicitly "do not immediately
  change the training program"
- `BRETT blueprint.md` §36 "Example Claude Questions" — the full example-question list, including
  the two named in ROADMAP success criterion #4 ("Am I actually progressing?", "Which muscles are
  undertrained?")
- `.planning/phases/06-mcp-tools/06-CONTEXT.md` — the full 12-tool surface and their parameter
  conventions (D-01 through D-14) that D-06's tool-name mapping must reference accurately: recent
  workouts, single workout detail, training summary, weekly volume, muscle-group volume, exercise
  progression, personal records, plateaus, training frequency, body-weight trend, recomposition
  status, period comparison
- `docs/hevy-api-observations.md` — the sibling doc D-07's file placement matches, for tone/format
  precedent (a living reference doc, not a formal spec)

### Test coverage (background — not discussed, but the gap is real)
- `backend/tests/test_hevy_end_to_end.py` — the existing mock-Hevy → Postgres composition test;
  explicitly does NOT exercise analytics or MCP (confirmed by scout: no `mcp`/`MCP` references in
  the file)
- `BRETT blueprint.md` §42 "Testing" and §43 "Integration Test" — the full testing scope
  (Hevy auth/pagination/incremental/duplicates/deletions/failures/rate-limiting; analytics;
  the mock-Hevy → sync → Postgres → analytics → MCP → expected-result integration test)
- `BRETT blueprint.md` §44 "Observability" — log sync started/completed/counts/duration/errors;
  never log API keys, tokens, or full health samples — relevant if rate-limiting or rotation work
  touches logging

### Rate limiting (background — not discussed, but real work for this phase)
- `CLAUDE.md` §"Alternatives Considered" — "Custom rate-limit middleware" row: recommends a
  ~20-line in-process token bucket keyed on client IP over `slowapi`, reserving `slowapi`/`limits`
  for if the API opens to the iOS app later
- `BRETT blueprint.md` §32 "Authentication" — rate limiting listed as a minimum private-development
  requirement alongside HTTPS, strong bearer token, environment secrets
- `.planning/phases/02-deploy-connector-auth-spike/02-CONTEXT.md` §Deferred — rate limiting was
  explicitly deferred here to Phase 7, confirming this phase is where it lands
- `.planning/phases/06-mcp-tools/06-CONTEXT.md` §Deferred — same deferral, restated

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `backend/app/mcp/auth.py` — `build_token_verifier`, `StaticTokenVerifier`,
  `AuthKitJWTVerifier` — both auth mechanisms are complete and proven; nothing here is rebuilt,
  only exercised (rotation) or wrapped (rate limiting, if it lands ahead of the verifier in the
  request path)
- `scripts/deploy-cloud-run.sh` + `backend/tests/test_cloud_run_deploy.py` — the existing
  test-asserted deploy script; the pattern (a script the test parses and cross-checks flags
  against) is the precedent for any new rotation/backup runbook tooling
- 47 existing test files across `backend/tests/` — Hevy sync, analytics, and MCP tool coverage
  already substantial; DEPLOY-03's real gap is the missing end-to-end composition test, not a
  from-scratch test suite

### Established Patterns
- Manual verification checklists for infrastructure claims that need a real external service
  (Phase 2's Auth Verification Matrix) — D-02 (backup) and D-09 (coaching UAT) both follow this
  precedent rather than inventing a new verification style
- Secrets bound only via `--set-secrets` at deploy time, never written to `cloud-run.env.yaml` or
  committed (D-06d from Phase 2) — D-04's rotation procedure must not violate this
- `structlog` + secret redaction already wired (FOUND-05) — any new logging (rate-limit rejections,
  rotation events) routes through the existing `log = structlog.get_logger()` pattern

### Integration Points
- Rate limiting (not discussed, Claude's discretion at research/plan time) would sit as
  middleware/dependency ahead of `verify_token` in the MCP request path, per ROADMAP criterion #2
  ("rate limiting applied ahead of handler work")
- The end-to-end integration test (not discussed) most naturally extends
  `backend/tests/test_hevy_end_to_end.py`'s pattern (mocked Hevy via respx/httpx2, real Postgres
  testcontainer) through `app/analytics/*` and into an `app/mcp/tools/*` call, rather than being
  a wholly new test file — Claude's discretion at research/plan time

</code_context>

<specifics>
## Specific Ideas

- The coaching document should read as directly actionable — not just prose adapted from the
  blueprint, but explicit enough that Claude can look up "which tool do I call for this kind of
  question" (D-06).
- Verification of both the backup/restore claim and the coaching document's real-world behavior
  should happen against the live, real system (Neon branch from live data; Claude Project against
  the deployed connector) — not simulated or mocked. Both D-02 and D-09 were chosen specifically
  because they're the kind of claim that's only actually proven by doing the real thing once and
  writing down what happened.

</specifics>

<deferred>
## Deferred Ideas

- Independent `pg_dump`/`pg_restore` backup path — considered and explicitly not chosen (D-01);
  Neon-native only for now. Revisit only if there's ever a reason to distrust Neon-internal
  recovery or to plan a migration off Neon.
- `DATABASE_URL` and `HEVY_API_KEY` rotation procedures — considered and not selected into this
  phase's scope (D-03). Not lost, just not built now; `HEVY_API_KEY` in particular has no urgency
  since it's off the live connector's request path entirely.
- Dual-secret/grace-period rotation mechanism for `MCP_AUTH_SECRET` — considered and not chosen
  (D-04); a hard-cutover rotation was judged acceptable given the static path is CLI/rollback-only.
- Per-conversation (non-Project) loading of the coaching document — considered and not chosen
  (D-08); Project-level custom instructions was preferred.

### Reviewed Todos (not folded)
None — no pending todos existed to review (`.planning/todos/pending/` is empty).

</deferred>

---

*Phase: 07-production-hardening-coaching-layer*
*Context gathered: 2026-09-01*
