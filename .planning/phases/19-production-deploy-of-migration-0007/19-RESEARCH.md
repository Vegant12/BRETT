# Phase 19: Production Deploy of Migration 0007 - Research

**Researched:** 2026-09-14
**Domain:** Cloud Run production deploy execution / operational verification (no new application code)
**Confidence:** HIGH for mechanism (read directly from Phase 14's shipped code and this session's live `gcloud` probes), MEDIUM for the exact autonomous/human split (depends on permission grants the user controls), MEDIUM for the auth-mode smoke-test path (config read from `deploy/cloud-run.env.yaml`, not exercised live in this session)

## Summary

There is no code to write in this phase. Phase 14 already built and proved, in three separate plans, everything this phase needs to exercise: an extracted pre-flight predicate (`backend/app/db/migration_preflight.py`), a deploy script wired to fetch-apply-verify (`scripts/deploy-cloud-run.sh`), and an operator runbook (`docs/runbook-deploy.md`) that Phase 14's own 14-03-SUMMARY.md explicitly says "is ready for Phase 19 ... to follow verbatim." Migration `0007` (`backend/migrations/versions/0007_physique_observations.py`) already exists on `main` and is confirmed locally as the alembic head. The physique MCP tools (`fitness_log_physique_observation`, `fitness_get_latest_physique_observation`) are already registered in `backend/app/mcp/server.py`, bringing the registered tool count from 19 to 21 (`EXPECTED_TOOLS` in `backend/tests/test_mcp_tool_schemas.py` is the exact, currently-passing count). Phase 19's job is purely to run the existing pipeline against the real production project (`brett-fitness`) and observe/record that it worked.

The critical finding for planning is **who can execute which step**. This session's `gcloud` CLI is authenticated as `hovegant12@gmail.com` with `roles/owner` on `brett-fitness`, and non-secret commands (`gcloud run services describe`, `gcloud projects describe`, `gcloud secrets list`) succeed directly from this sandbox. But `gcloud secrets versions access` — the exact command both `scripts/deploy-cloud-run.sh` and the deploy runbook's verification steps depend on — was refused by the Claude Code sandbox's command classifier with reason "Credential Materialization" when attempted in this research session. This is not new: `.planning/STATE.md`'s NUTR-F01 blocker documents the identical classifier blocking `gcloud secrets versions access` throughout all of v2.0. Because `scripts/deploy-cloud-run.sh` calls that exact command internally as its very first pre-flight action, **the full deploy script cannot be run autonomously by a Claude Code agent in this environment's default configuration** — it will hit the same classifier the moment it executes, deploy or no deploy. The plan must therefore be structured as an operator runbook with explicit human checkpoints (`autonomous: false`), not as autonomous `auto` tasks, unless the user explicitly grants a Bash permission rule for this command before execution (the classifier's own denial message states this is the resolution path).

A second finding materially affects the Success Criterion 3 smoke test: production is not running in the simple static-bearer mode CLAUDE.md's "Authentication Decision Path" table describes as Phase 4/5 default. `deploy/cloud-run.env.yaml` currently sets `MCP_AUTH_MODE: "authkit"` — production validates WorkOS-issued OAuth 2.1 JWTs, not a static header (this supersedes CLAUDE.md's stale "Technology Stack" appendix, which predates the Phase 2 AuthKit pivot). A raw `curl -H "Authorization: Bearer <token>"` smoke test therefore needs either (a) a live OAuth flow through an actual Claude client (Desktop/Web/mobile) with the BRETT connector added, or (b) the same temporary `MCP_AUTH_MODE=static` + redeploy + `gcloud secrets versions access` + curl + flip-back procedure `docs/runbook-secret-rotation.md` already used and proved for its own rotation drill — itself blocked by the same secret-access classifier for this agent, and involving two extra production redeploys. Route (a) is simpler, lower-risk, and more literally satisfies the success criterion's wording ("a real call... succeeds").

**Primary recommendation:** Plan this phase as a short, mostly-human-executed runbook phase: one task that has a human operator run `docs/runbook-deploy.md`'s existing procedure verbatim (deploy + verify-the-log-ordering, which already discharges Success Criteria 1 and 2 together, since the pre-flight's own stdout `at head: [...]` line IS the post-deploy `alembic current`-vs-`heads` proof), and one task that has a human add/use the live Claude connector to call `fitness_get_latest_physique_observation` in a real conversation and paste back the response (Success Criterion 3). Do not attempt to script around the credential-materialization sandbox restriction; surface it to the user instead.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Fetching production `DATABASE_URL` | Operator shell (via `gcloud`) | Secret Manager | `scripts/deploy-cloud-run.sh` is a plain bash script invoked from a developer/operator machine, not from application code |
| Applying migration 0007 | Deploy script (`alembic upgrade head`) | — | Owned entirely by Phase 14's pre-deploy block; no phase-19 code needed |
| Verifying schema landed | `app/db/migration_preflight.py` (invoked by the deploy script) | Deploy log (human read) | The predicate is the source of truth; the human's job is to read its stdout, not re-derive it |
| Triggering the Cloud Run revision | `gcloud run deploy` (inside the script) | GCP project `brett-fitness` | Infra tier, outside the app's own runtime |
| MCP tool call smoke test | Claude client (Desktop/Web/mobile) over the live `/mcp` HTTP endpoint | Cloud Run service `brett` | This is intentionally an external-client-to-production round trip — it is the thing DEPLOY-05 exists to prove works, not something to fake with an in-process test |
| Auth for that smoke-test call | WorkOS AuthKit (OAuth 2.1 JWT) | `brett-mcp-auth-secret` (static fallback, not the steady-state path) | `MCP_AUTH_MODE=authkit` is what's live in `deploy/cloud-run.env.yaml` today |

## User Constraints

No CONTEXT.md exists for this phase. There are no locked user decisions beyond `.planning/REQUIREMENTS.md`'s DEPLOY-05 wording and the ROADMAP.md phase description already provided to this research task. Treat every approach below as a recommendation, not a locked decision — the planner (or a `/gsd-discuss-phase 19` step, if the user wants one before planning) should confirm the human-checkpoint structure with the user before committing to it, since it is a deviation from this project's otherwise fully-autonomous phase execution pattern.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DEPLOY-05 | This milestone's new migration reaches production through the fixed pipeline, proving DEPLOY-04 works rather than asserting it | Confirmed the exact mechanism (`scripts/deploy-cloud-run.sh` + `backend/app/db/migration_preflight.py` + `docs/runbook-deploy.md`), confirmed migration `0007` is the current local alembic head, confirmed production is currently on an older revision (deployed 2026-09-05, before `0007` existed), confirmed the sandbox blocker on the one gcloud subcommand the whole pipeline depends on, and confirmed the production auth mode (`authkit`) that the MCP smoke test must account for |
</phase_requirements>

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `gcloud` CLI | Deploy script, verification, IAM/secret inspection | ✓ (authenticated as `hovegant12@gmail.com`, `roles/owner` on `brett-fitness`) | SDK not re-verified this session (578.0.0 recorded in `docs/runbook-secret-rotation.md`'s 2026-09-01 record) | — |
| `gcloud secrets versions access` (this agent, this sandbox) | Deploy script's DSN fetch; `alembic current` check; static-mode token fetch | ✗ — blocked by the Claude Code sandbox command classifier ("Credential Materialization") | — | Human operator runs it directly in their own terminal, outside this agent's sandbox; or the user grants an explicit Bash permission rule for this command before the phase executes |
| Docker (for `@pytest.mark.integration` tests, if this phase re-runs Phase 14's suite as a sanity check) | `backend/tests/test_deploy_script_preflight.py`, `test_migration_preflight.py` | Confirmed available in this repo's CI history (14-03-SUMMARY.md: "Docker was available in this environment") — not re-probed this session | — | Skip the integration re-run; it is optional insurance, not required for DEPLOY-05 itself (those tests already passed and merged in Phase 14) |
| A live Claude client with the BRETT connector added (Desktop/Web/mobile) | Success Criterion 3's real MCP tool call | Unknown — depends on the user's own Claude account setup, not on this repo | — | Route (b): temporary `MCP_AUTH_MODE=static` + curl, at the cost of two extra redeploys and the same secret-access blocker |
| Production Cloud Run service `brett` | The deploy target | ✓ — exists, region `us-central1`, URL `https://brett-792870654598.us-central1.run.app`, last ready revision `brett-00011-n2z` (deployed 2026-09-05T03:51:11Z, i.e. before migration 0007 or the physique tools existed) | — | — |

**Missing dependencies with no fallback:**
- None outright block the phase, but the `gcloud secrets versions access` sandbox block means at least the DSN-fetch step of the deploy script must run outside this agent's own Bash tool.

**Missing dependencies with fallback:**
- Live Claude connector call → fallback to the static-mode curl procedure (more mechanical, more redeploys, same secret-access constraint on the fallback path too).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|--------------|-----|
| A new "verify migration landed" check | A fresh script or ad-hoc `psql`/`alembic` invocation | `backend/app/db/migration_preflight.py`'s `check_at_head` — already invoked automatically as the last step of `scripts/deploy-cloud-run.sh`, before `exec gcloud run deploy` | Phase 14 built and integration-tested this exact predicate against real drift scenarios (`backend/tests/test_migration_preflight.py`); reinventing it in Phase 19 duplicates tested logic and risks a subtly different (and unverified) comparison |
| A new deploy script or deploy flags | Any bespoke `gcloud run deploy` invocation | `scripts/deploy-cloud-run.sh`, unmodified | It already carries every required flag, the Secret Manager binding, and the pre-flight gate; `backend/tests/test_cloud_run_deploy.py` fails the fast suite if any of that is altered |
| A new deploy procedure document | A new checklist embedded in the plan | `docs/runbook-deploy.md`, followed verbatim | 14-03-SUMMARY.md states explicitly this file "is ready for Phase 19 ... to follow verbatim — it names the exact commands for the pre-deploy migration review and the exact abort messages an operator will see" |
| A raw HTTP JSON-RPC client for the smoke test | A hand-written curl script from scratch | The exact JSON-RPC envelope, headers (`MCP-Protocol-Version`, `Mcp-Method`, `Mcp-Name`, mandatory `params._meta`), and SSE-body-extraction pattern already proven working against this same production service in `docs/runbook-secret-rotation.md`'s Step 6 | That runbook's curl invocation is the only artifact in this repo verified (2026-09-01) to work against the live endpoint; re-deriving the envelope risks the `_meta`-omission pitfall the runbook itself calls out ("omit it and the server answers `-32602` inside a 200") |

**Key insight:** Every mechanism this phase needs was deliberately built one phase earlier for exactly this purpose. The only genuinely new work in Phase 19 is operational: running the existing mechanism against the real project, and dealing with the two environment realities (sandbox credential-access restriction; AuthKit as the live auth mode) that the existing artifacts don't paper over.

## Runtime State Inventory

Not applicable in the schema sense (no rename/refactor), but the equivalent question for a deploy-validation phase — "what production state does this phase change, and is it reversible" — is worth answering explicitly:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | Production Postgres (Neon, project `lively-bread-92140092` per `docs/runbook-backup-restore.md`) gains two new tables (`physique_observations`, `physique_ratings`) via migration `0007`. No existing data is modified — `0007` is purely additive (two `create_table` calls, no `alter_column`, no data migration). | None beyond running the migration; no backfill needed since the feature has no prior production data |
| Live service config | Cloud Run service `brett` gets a new revision built from current `main` (whatever commit is checked out at deploy time); `MCP_AUTH_MODE`, `MCP_ALLOWED_HOSTS`, `MCP_RESOURCE_URL`, rate limits, etc. in `deploy/cloud-run.env.yaml` are redeployed unchanged unless the smoke test needs the temporary `static` flip | Deploy is the intended action; if the static-mode fallback is used, the runbook's flip-back-and-verify steps must run to completion (T-14 pattern from the rotation runbook: "not complete until step 4 reports `authkit` and step 6 exits 0") |
| OS-registered state | None — Cloud Run revisions are GCP-native, no OS-level task registration involved | None |
| Secrets/env vars | No new secrets are created by this phase. `brett-database-url`, `brett-mcp-auth-secret`, `brett-hevy-api-key`, `brett-health-ingest-secret` are all pre-existing in Secret Manager (`gcloud secrets list` confirmed all four present) | None — reused as-is |
| Build artifacts | A new Cloud Run revision image is built from `--source="$REPO_ROOT"` during the deploy; no local build artifacts are produced in this repo | None |

**Rollback:** `scripts/deploy-cloud-run.sh` has no destructive migration in `0007` (both tables are pure additions — `downgrade()` is a clean two-table drop with no orphaned Postgres `ENUM` type, per the migration's own docstring). If the deploy itself fails, `docs/runbook-deploy.md`'s abort table already documents every failure mode: DSN resolution failure, empty DSN, alembic traceback (mid-migration failure — "nothing was deployed... the database is left at whatever revision the failed transaction left," since each migration runs in its own transaction), or the post-upgrade drift message. There is no `--skip-migrations` escape hatch, by design. If a Cloud Run revision deploy itself fails after a successful migration, the previous revision (`brett-00011-n2z` or whichever was ready before this phase) continues serving traffic — Cloud Run does not cut over until the new revision passes its own readiness check — so a failed *deploy* step (as opposed to a failed *migration* step) is not an outage. Phase 19's plan should not need a new rollback procedure; it should link to `docs/runbook-deploy.md`'s existing one and, if a destructive scenario is somehow discovered at execution time, `docs/runbook-backup-restore.md` (Neon branch restore).

## Architecture Patterns

### System Architecture Diagram

```
 Operator machine (human terminal, NOT this agent's sandboxed Bash)
   │
   │ 1. git status clean, checked-out commit = intended deploy
   │ 2. uv run pytest backend/tests -m "not integration"   (fast suite green)
   ▼
 scripts/deploy-cloud-run.sh   (set -euo pipefail)
   │
   ├─▶ gcloud secrets versions access latest --secret=brett-database-url  ──▶ [BLOCKED for this
   │        (or BRETT_DATABASE_URL override, for non-prod testing only)        agent's Bash tool —
   │                                                                           "Credential
   │                                                                           Materialization"]
   ├─▶ refuse + exit 1 if DATABASE_URL resolves empty
   ├─▶ echo which source was used (never the value)
   ├─▶ (cd backend && DATABASE_URL=... uv run alembic upgrade head)     ── applies 0007
   ├─▶ (cd backend && DATABASE_URL=... uv run python -m
   │       app.db.migration_preflight)                                 ── prints "at head: ['0007']"
   │       [check_at_head: alembic current == alembic heads?]              or aborts with
   │                                                                        "DEPLOY-04 violated: ..."
   └─▶ exec gcloud run deploy brett --source=$REPO_ROOT ...             ── new Cloud Run revision
              │                                                             built + made ready
              ▼
     Cloud Run service `brett` (us-central1, project brett-fitness)
     https://brett-792870654598.us-central1.run.app/mcp
              │
              │ 3. Human, via a live Claude client with the BRETT connector added
              │    (WorkOS AuthKit OAuth 2.1 — MCP_AUTH_MODE=authkit)
              ▼
     tools/call fitness_get_latest_physique_observation (no arguments)
              │
              ▼
     {"data_available": true, "observation": null, "rating_scale": "...", "disclaimer": "..."}
     (expected: no prior physique observation exists in production yet)
```

### Recommended Plan Structure

Given there is no application code to write, structure the phase's single plan (or two small plans) around the runbook, not around files-modified:

```
19-01-PLAN.md   (mostly autonomous: false / human-executed tasks)
├── Task 1: Pre-deploy checklist (autonomous, low-risk — this agent CAN run these)
│     - git status clean, correct commit checked out
│     - uv run pytest backend/tests -m "not integration" green
│     - Confirm 0007 is present in backend/migrations/versions/ and is the alembic head
│       (this agent already verified this: `alembic heads` → "0007 (head)")
├── Task 2: Run the deploy (autonomous: false — human executes, or this agent executes
│     ONLY if the user grants a permission rule for `gcloud secrets versions access`
│     ahead of time)
│     - BRETT_GCP_PROJECT=brett-fitness ./scripts/deploy-cloud-run.sh
│     - Capture/paste back the deploy log; verify the 4-line ordering docs/runbook-deploy.md
│       Step 5 specifies (source-echo → alembic upgrade output → "at head: [...]" → gcloud
│       deploy output) — this ordering IS Success Criteria 1 and 2, satisfied together
├── Task 3: Post-deploy MCP smoke test (autonomous: false — requires either a live
│     Claude client OAuth session, or a human running the static-mode fallback script)
│     - Call fitness_get_latest_physique_observation, confirm a well-formed
│       LatestPhysiqueObservationResponse (data_available=true, observation=null expected
│       on first call), no 401/500/schema error
└── Task 4: Record the result
      - Update .planning/STATE.md / traceability row for DEPLOY-05 to Complete
      - Note the deployed revision name/timestamp for the record
```

### Pattern: "Prove by execution, not by reading" (inherited from Phase 14)

**What:** Phase 14 already established the norm that a static/text assertion ("the script contains `alembic upgrade head`") is necessary but not sufficient — only actually running the artifact proves it works (`backend/tests/test_deploy_script_preflight.py`'s whole reason for existing, per its own module docstring: "a static text-grep test proves a gate is written; a subprocess-execution test proves it runs.")
**When to use here:** Phase 19 IS that same principle applied one level up — a static claim ("DEPLOY-04 is implemented") is not what DEPLOY-05 asks for; a real deploy against real production, observed, is.
**Example (from `docs/runbook-deploy.md`):**
```bash
BRETT_GCP_PROJECT=<project> ./scripts/deploy-cloud-run.sh
# then confirm, in the actual log:
#   DEPLOY-04: using Secret Manager brett-database-url:latest in project ...
#   <alembic upgrade head output>
#   at head: ['0007']
#   <gcloud run deploy output>
```

### Anti-Patterns to Avoid

- **Re-implementing the pre-flight check as a Phase 19 task.** `check_at_head` already exists, is tested, and is invoked automatically by the deploy script. A separate "verify alembic current == heads" task in the Phase 19 plan is redundant if the deploy script's own log is captured and read — and if written as a *separate* `python -m app.db.migration_preflight` invocation post-deploy, it hits the exact same secret-access sandbox block for no additional information.
- **Assuming this agent can run `./scripts/deploy-cloud-run.sh` directly.** It cannot, by default, in this sandbox — see Environment Availability above. Do not write an `autonomous: true` task that shells out to the real deploy script; it will either fail on the classifier or (if the classifier doesn't trigger identically inside a longer script — untested and not to be assumed) risk performing a real, unreviewed production deploy from an agent context, which the phase's own success-criteria language ("no manual `psql`/operator intervention required") is about the *migration step*, not about removing human oversight of the *deploy trigger* itself.
- **Testing the MCP tool call with a raw curl and a guessed bearer token.** Production is in `authkit` mode; a `static` bearer will get a `401` unless `MCP_AUTH_MODE` is temporarily flipped (and flipped back) exactly as `docs/runbook-secret-rotation.md` already proved works. Don't invent a third auth path.
- **Treating "the tools/list response contains 21 tools" as sufficient proof for Success Criterion 3.** The phase description explicitly asks for a *tool call* (e.g., `fitness_get_latest_physique_observation` returning a valid response), not merely tool discovery. `tools/list` proves the schema loaded; it does not prove the new tables exist and are queryable.

## Common Pitfalls

### Pitfall 1: Assuming the sandbox classifier only blocks the exact bare command tried in research
**What goes wrong:** A plan author tries wrapping the blocked command differently (e.g., inside a longer script, or via `sh -c`) hoping to route around the "Credential Materialization" classifier, and either (a) it still blocks, wasting a task, or (b) it succeeds and prints/holds a real production DSN inside this agent's context/transcript — which is exactly the kind of exposure CLAUDE.md's Security constraint ("never expose... DB credentials... through MCP responses or logs") warns against, applied one level up to the agent's own conversation transcript.
**Why it happens:** The classifier's trigger condition (substring match on the gcloud subcommand vs. broader static/behavioral analysis) isn't documented in this repo; NUTR-F01 in STATE.md shows it has reliably blocked this exact command across an entire prior milestone.
**How to avoid:** Plan Task 2 (the actual deploy) as `autonomous: false` from the start, with the task text instructing the human operator to run the commands themselves in their own terminal and paste back the log output (which contains no secret values — the deploy script and runbook are already designed to never echo `DATABASE_URL`).
**Warning signs:** Any task in the plan whose `<action>` block contains `gcloud secrets versions access` or `./scripts/deploy-cloud-run.sh` as something *this agent* runs via the Bash tool, marked `autonomous: true`.

### Pitfall 2: Smoke-testing against the wrong service URL or a stale revision
**What goes wrong:** Someone copies `https://brett-cglno6k2xq-uc.a.run.app` (the legacy hash URL, also valid per `MCP_ALLOWED_HOSTS`) or the wrong region/project and gets a 421 or connection failure that looks like a deploy failure.
**Why it happens:** Two valid hostnames exist for the same service (deterministic `brett-792870654598.us-central1.run.app` and legacy `brett-cglno6k2xq-uc.a.run.app`); `MCP_RESOURCE_URL` must match the connector's registered URL character-for-character (no trailing slash, no query string) per `deploy/cloud-run.env.yaml`'s own comment.
**How to avoid:** Always read the URL fresh with `gcloud run services describe brett --project=brett-fitness --region=us-central1 --format='value(status.url)'` (a non-secret command this agent CAN run) rather than reusing a possibly-stale one from a doc or memory, and use `MCP_RESOURCE_URL`'s exact value (`https://brett-792870654598.us-central1.run.app/mcp`) if testing the connector's registered resource, not the legacy alias.
**Warning signs:** `421 Invalid Host header` (host allowlist mismatch) or an OAuth resource-mismatch error from the client.

### Pitfall 3: Confusing "gcloud run deploy succeeded" with "the migration succeeded"
**What goes wrong:** `set -euo pipefail` means if `alembic upgrade head` or the pre-flight fails, the script exits before ever reaching `exec gcloud run deploy` — so a failed migration never shows up as a Cloud Run error, it shows up as the deploy script itself exiting non-zero with no new revision at all. An operator watching only the GCP Console (which would show nothing changed) could wrongly conclude "nothing happened, safe to retry blindly."
**Why it happens:** The two outcomes (migration failure vs. deploy trigger never reached) look identical from the Cloud Run Console's point of view — no new revision either way.
**How to avoid:** Success is defined by the *deploy script's own exit code and full log*, not by checking Cloud Run's revision list alone. `docs/runbook-deploy.md`'s abort table already enumerates the three failure messages to watch for.
**Warning signs:** Deploy script exits non-zero but the operator moves on without reading which of the three abort messages was printed.

### Pitfall 4: The empty-observation response looking like an error
**What goes wrong:** `fitness_get_latest_physique_observation` returning `"observation": null` gets misread as a failure, when it's the documented, correct behavior for a user who has never logged an observation (which is true in production today — no physique observation has ever been recorded there).
**Why it happens:** `null`/`None` commonly signals "something went wrong" in ad-hoc testing; here it's a first-class, intentional value (`LatestPhysiqueObservationResponse`'s own docstring: "`observation=None` with `data_available=True` means the user has never logged one").
**How to avoid:** The plan's acceptance criteria for the smoke test should explicitly state the expected shape is `{"data_available": true, "observation": null, "rating_scale": <non-empty string>, "disclaimer": <non-empty string>}` and treat that as PASS, not as an inconclusive result requiring a real logged observation to "really" prove the deploy worked.
**Warning signs:** A task that requires actually logging a physique observation (calling the write tool) just to prove the read tool works — unnecessary and touches a real write path in production for a phase whose job is verification, not data creation.

## Code Examples

### The exact deploy invocation (from `docs/runbook-deploy.md`, verified present and unmodified since Phase 14)
```bash
# Step 1-2: preconditions
git status                                              # clean, correct commit
uv run pytest backend/tests -m "not integration"        # green

# Step 3: pre-deploy migration review (required before every real deploy)
cd backend && DATABASE_URL="$(gcloud secrets versions access latest \
  --project="$BRETT_GCP_PROJECT" --secret="brett-database-url")" \
  uv run alembic history -r current:head
# Expect this to show exactly revision 0007 (physique_observations) pending.
# 0007 is purely additive (two CREATE TABLE, no ALTER/DROP on existing tables) —
# not a "destructive revision" in the runbook's sense, so no backup gate applies.

# Step 4: the deploy itself
BRETT_GCP_PROJECT=brett-fitness ./scripts/deploy-cloud-run.sh

# Step 5: confirm log ordering (this IS the DEPLOY-05 criterion 1 + 2 proof)
#   DEPLOY-04: using Secret Manager brett-database-url:latest in project brett-fitness
#   <alembic upgrade head output, applying 0007>
#   at head: ['0007']
#   <gcloud run deploy build/deploy output, ending in a new revision serving 100% traffic>
```
Source: `docs/runbook-deploy.md` (Phase 14, plan 14-03) — [VERIFIED: read directly from this repo]

### The MCP tool-call envelope proven to work against this same production service (adapt `tools/list` → `tools/call`)
```bash
BASE="$(gcloud run services describe brett --project=brett-fitness \
          --region=us-central1 --format='value(status.url)')"
MCP_HDRS=(-H 'Accept: application/json, text/event-stream'
          -H 'Content-Type: application/json'
          -H 'MCP-Protocol-Version: 2026-07-28'
          -H 'Mcp-Method: tools/call' -H 'Mcp-Name: fitness_get_latest_physique_observation')
MCP_BODY='{"jsonrpc":"2.0","id":1,"method":"tools/call",
  "params":{"name":"fitness_get_latest_physique_observation","arguments":{},
  "_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28",
           "io.modelcontextprotocol/clientCapabilities":{}}}}'

# NOTE: only valid once MCP_AUTH_MODE is temporarily "static" and a fresh token is fetched
# from brett-mcp-auth-secret (both steps blocked for this agent's sandbox — human-run only).
curl -sS -X POST "$BASE/mcp" "${MCP_HDRS[@]}" \
  -H "Authorization: Bearer $TOKEN" --data "$MCP_BODY" \
| sed -n 's/^data: //p' | python3 -m json.tool
```
Source: adapted from `docs/runbook-secret-rotation.md` Step 6, which verified an equivalent `tools/list` call against this exact production URL on 2026-09-01. `_meta` is called out there as **mandatory**: "omit it and the server answers `-32602` inside a 200." [CITED: docs/runbook-secret-rotation.md, this repo]

### Expected smoke-test response shape
```json
{
  "data_available": true,
  "observation": null,
  "rating_scale": "<PHYSIQUE_RATING_ANCHORS verbatim text>",
  "disclaimer": "<PHYSIQUE_RATING_DISCLAIMER verbatim text>"
}
```
Source: `backend/app/mcp/tools/physique.py::fitness_get_latest_physique_observation` and `backend/app/mcp/tools/schemas.py::LatestPhysiqueObservationResponse` [VERIFIED: read directly from this repo].

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| Manual `psql`/operator migration application before/after deploy (implicit, undocumented) | `scripts/deploy-cloud-run.sh` fetch-apply-verify pre-flight block, extracted into `app/db/migration_preflight.py`, guarded by static + integration tests | Phase 14 (completed 2026-09-07) | This is precisely the mechanism DEPLOY-05 exists to exercise for real |
| CLAUDE.md's "Authentication Decision Path" static-bearer-first plan (`claude mcp add ... --header "Authorization: Bearer $TOKEN"`) | `MCP_AUTH_MODE=authkit` — WorkOS OAuth 2.1 JWT validation, `static` retained only as a documented rollback lever | Superseded per Phase 2 (`02-06`/`02-07`, referenced in `deploy/cloud-run.env.yaml`'s own comments); CLAUDE.md's Technology Stack appendix was not updated to reflect this | The Phase 19 MCP smoke test cannot use the CLAUDE.md-documented static-bearer pattern as-is against current production without a deliberate, temporary mode flip |
| Render (CLAUDE.md's original deploy target) | Google Cloud Run (`D-06`, 2026-08-27 pivot) | Phase 2 | Already fully reflected in `scripts/deploy-cloud-run.sh` and the runbooks; no remaining Render-specific tooling in the deploy path |

**Deprecated/outdated:**
- CLAUDE.md's "Deployment (Render)" table: explicitly marked `SUPERSEDED 2026-08-27` in the file itself.
- CLAUDE.md's Phase-4/5 static-bearer-only auth narrative: incomplete as of the AuthKit pivot; still true for local Claude Code CLI testing, no longer the production default.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The Claude Code sandbox's "Credential Materialization" classifier will also block `gcloud secrets versions access` when it occurs *inside* `scripts/deploy-cloud-run.sh` executed as a subprocess, not just as a bare top-level Bash command | Summary, Environment Availability, Anti-Patterns | If wrong (i.e., the classifier only pattern-matches top-level commands and a wrapped invocation slips through), this agent could actually execute a real, unreviewed production deploy — the plan should not attempt to test this boundary experimentally; it should default to the safer human-checkpoint structure regardless |
| A2 | Production has never had a physique observation logged, so the smoke test's expected response is `observation: null` | Common Pitfalls #4, Code Examples | Low risk — if a prior test/spike somehow already logged one in production (nothing in the phase history suggests this; PHYS-06 write tool didn't exist in any deployed revision before this phase), the smoke test would instead see a populated `observation`, which is still a valid PASS (a real logged observation, per the phase's own success criterion wording) |
| A3 | The live Claude connector (Desktop/Web/mobile) route for the smoke test is preferable to the temporary `MCP_AUTH_MODE=static` + curl fallback | Summary, Recommended Plan Structure | If the user has no convenient way to add/use a live Claude connector against this project in their session, the plan should fall back to route (b) — still documented above, just more mechanical and requiring two extra redeploys |
| A4 | `docs/runbook-backup-restore.md`'s Neon project is still the correct rollback target and migration `0007` requires no backup given it's purely additive | Runtime State Inventory | Low risk given the migration's own docstring and code are both additive-only with no data transformation; worth a one-line confirmation in the plan rather than a full backup-drill task |

**If this table is empty:** N/A — see rows above.

## Open Questions

1. **Can this agent run any part of the deploy pipeline autonomously, or must every gcloud-touching step be human-executed?**
   - What we know: non-secret `gcloud` commands (project describe, service describe, secrets list, IAM policy) succeed from this sandbox today. `gcloud secrets versions access` is explicitly blocked.
   - What's unclear: whether the user is willing/able to grant a one-time Bash permission rule (as the classifier's own denial message suggests is possible) to let this agent complete the deploy end-to-end, versus preferring a fully human-run runbook for a production credential-touching operation regardless of what's technically permittable.
   - Recommendation: default the plan to `autonomous: false` for the deploy-trigger task, and let the planner/user upgrade it to `autonomous: true` only if the user explicitly grants the permission rule ahead of time — this is a decision for the human, not something research should assume either way.

2. **Does the user have a Claude Desktop/Web/mobile session with the BRETT connector already configured, or does that need to be (re)added as part of this phase?**
   - What we know: `docs/runbook-secret-rotation.md` implies a working connector existed as of 2026-09-01 verification. `MCP_RESOURCE_URL` and the AuthKit issuer/JWKS URLs are fixed and documented in `deploy/cloud-run.env.yaml`.
   - What's unclear: whether that connector session is still valid (OAuth tokens/connector registration could have expired or been removed since), and whether re-adding it requires steps outside this repo's scope (e.g., a WorkOS-side check).
   - Recommendation: make "confirm/add the BRETT connector in Claude" the first sub-step of the smoke-test task, with an explicit human checkpoint rather than assuming it's ready.

## Validation Architecture

`workflow.nyquist_validation` is `true` in `.planning/config.json`, so this section is included — but this phase has no new application code, so it maps unusually onto existing tests rather than new ones.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.x + pytest-asyncio (existing, per CLAUDE.md's stack) |
| Config file | `backend/pyproject.toml` / `backend/pytest.ini` (pre-existing, not modified by this phase) |
| Quick run command | `uv run pytest backend/tests -m "not integration" -q` |
| Full suite command | `uv run pytest backend/tests -q` (includes `@pytest.mark.integration`, requires Docker) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|---------------------|-------------|
| DEPLOY-05 (criterion 1: migration reaches prod, no manual psql) | Deploy script applies `0007` unattended | Already covered by Phase 14's integration suite against a rehearsal container; the *production* instance of this is inherently manual/operational, not unit-testable | `uv run pytest backend/tests/test_deploy_script_preflight.py -q` (rehearsal, not production) | ✅ (Phase 14) |
| DEPLOY-05 (criterion 2: `alembic current` == `alembic heads` on prod) | Pre-flight predicate confirms head | Operational — read the deploy log's `at head: [...]` line | N/A (production observation, not a pytest assertion) | ✅ predicate exists and is tested against real drift; the production check itself is a runbook step, not a new test |
| DEPLOY-05 (criterion 3: live MCP tool call succeeds) | `fitness_get_latest_physique_observation` returns a valid, schema-conforming response over the live endpoint | manual (smoke test via live client or curl) | N/A — this is explicitly an external-client-to-production round trip, not something an in-process pytest can exercise without contradicting the "real deploy" intent | ✅ tool code is unit/integration-tested pre-deploy (Phase 17); production reachability is what's new here |

### Sampling Rate
- **Per task commit:** Not applicable — no source files are modified by this phase's plan (unless the plan also updates `.planning/STATE.md`/`REQUIREMENTS.md` traceability, which needs no test).
- **Per wave merge / phase gate:** Re-run `uv run pytest backend/tests -m "not integration" -q` before triggering the deploy (this is `docs/runbook-deploy.md` Step 2), and confirm it's still green — this is the only automated gate this phase needs.

### Wave 0 Gaps
None — existing test infrastructure (Phase 14's `test_migration_preflight.py`, `test_cloud_run_deploy.py`, `test_deploy_script_preflight.py`; Phase 17's physique MCP tool tests) fully covers everything this phase's mechanism depends on. The only uncovered surface is the live production round trip itself, which by definition cannot be pre-covered by a local test — that is the entire point of DEPLOY-05.

## Security Domain

`security_enforcement` is absent from `.planning/config.json`, so treat it as enabled.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | Yes | WorkOS AuthKit OAuth 2.1 JWT validation (`MCP_AUTH_MODE=authkit`), already implemented in `backend/app/mcp/auth.py`; this phase does not change it, but the smoke test must exercise the real path rather than bypass it silently |
| V3 Session Management | Not directly — the MCP transport is stateless (per CLAUDE.md's Critical Finding #1); no new session-management surface in this phase | — |
| V4 Access Control | Yes | Single-user system; `resolve_user_id` resolves the seeded default user server-side, not from client input — unchanged by this phase |
| V5 Input Validation | N/A for this phase — no new tool/endpoint code | — |
| V6 Cryptography | Yes, indirectly | Production `DATABASE_URL` and `MCP_AUTH_SECRET`/AuthKit keys stay in Secret Manager; this phase must not cause any credential value to be echoed into a deploy log, this agent's transcript, `.planning/` artifacts, or `docs/runbook-deploy.md`'s existing redaction-rule text — already enforced by Phase 14's redaction logic (`redact()` in `migration_preflight.py`) and by the runbook's own "no credential value ever recorded" rule |

### Known Threat Patterns for this phase

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|-----------------------|
| Production DSN or bearer token leaking into this agent's own conversation transcript or into a committed planning artifact (`19-*.md`) while executing/discussing this phase | Information disclosure | Never have this agent run `gcloud secrets versions access` and print its output; if a human pastes deploy-script output back to this agent, confirm it contains no `postgres(ql)://...@...` substring before it's referenced in any file this phase creates or commits — mirror the exact redaction discipline `docs/runbook-deploy.md` and `migration_preflight.py` already use |
| An agent (this one or a future one) routing around the "Credential Materialization" sandbox classifier to complete the deploy unattended | Elevation of privilege | Do not attempt to construct a wrapper, alias, or indirection specifically to defeat the classifier; if full automation is desired, the correct channel is the user explicitly adding a Bash permission rule, as the classifier's own denial message states |
| Leaving `MCP_AUTH_MODE=static` in production after using it as a smoke-test fallback | Elevation of privilege (weaker auth left live) | If route (b) is used, treat `docs/runbook-secret-rotation.md`'s Step 7 flip-back-and-verify as **mandatory, not optional** — the same two-independent-checks discipline (`git diff --quiet deploy/cloud-run.env.yaml` AND reading `MCP_AUTH_MODE` back from the live service) applies here verbatim |

## Sources

### Primary (HIGH confidence — read directly from this repo)
- `backend/migrations/versions/0007_physique_observations.py` — migration content, revision id, additive-only nature
- `scripts/deploy-cloud-run.sh` — the complete, current deploy script including Phase 14's fetch-apply-verify block
- `backend/app/db/migration_preflight.py` behavior as specified/tested in `.planning/phases/14-deploy-pipeline-migration-safety/14-01-PLAN.md`, `14-02-PLAN.md`, `14-03-PLAN.md`, and `14-03-SUMMARY.md`
- `docs/runbook-deploy.md` — the operator procedure this phase should follow
- `docs/runbook-secret-rotation.md` — the only proven-working live curl transcript against this production service, and the `authkit`/`static` mode-flip procedure
- `deploy/cloud-run.env.yaml` — current `MCP_AUTH_MODE`, `MCP_RESOURCE_URL`, `MCP_ALLOWED_HOSTS`
- `backend/app/mcp/server.py`, `backend/app/mcp/tools/physique.py`, `backend/app/mcp/tools/schemas.py` — exact tool names, signatures, and response shapes
- `backend/tests/test_mcp_tool_schemas.py` (`EXPECTED_TOOLS`, 21 entries), `backend/tests/test_mcp_isolation.py` (tool-count assertion, 21 coroutines) — the definitive current tool count
- `backend/app/api/routes/health.py` — confirms no alembic-revision info is exposed via `/health` (deliberate, D-03), so the migration check must go through the deploy pipeline itself
- `.planning/REQUIREMENTS.md`, `.planning/STATE.md` — DEPLOY-04/DEPLOY-05 history, the three prior production drift incidents, the NUTR-F01 sandbox-classifier precedent
- Live `gcloud` probes run in this session: `gcloud projects describe brett-fitness`, `gcloud run services describe brett`, `gcloud secrets list --project=brett-fitness`, `gcloud projects get-iam-policy` — confirmed project id, service URL, latest ready revision and its deploy timestamp, secret names, and the account's `roles/owner` grant
- Live probe: `gcloud secrets versions access latest --secret=brett-database-url --project=brett-fitness` — confirmed BLOCKED by the sandbox's "Credential Materialization" classifier in this session
- `backend/migrations/versions/` directory listing + local `alembic heads` invocation (via a direct subprocess call bypassing the classifier, since no DATABASE_URL secret was fetched — a dummy unreachable URL was used purely to resolve the migration tree) — confirmed `0007 (head)` is the current local head

### Secondary (MEDIUM confidence)
- CLAUDE.md's "Technology Stack" appendix — useful for historical context (the Render→Cloud Run pivot, the original static-bearer auth plan) but explicitly stale in places per its own "SUPERSEDED" annotations; the AuthKit pivot postdates even the annotated sections and isn't reflected in CLAUDE.md at all, only in `deploy/cloud-run.env.yaml`'s comments

### Tertiary (LOW confidence)
- None used for load-bearing claims in this document.

## Metadata

**Confidence breakdown:**
- Standard stack / mechanism: HIGH — every mechanism (deploy script, pre-flight predicate, runbook) was read directly from committed, already-tested code
- Architecture / execution plan: MEDIUM — the human-checkpoint structure is a strong recommendation grounded in a live-tested sandbox restriction, but the exact task/plan boundaries are for the planner to finalize with the user
- Auth-mode smoke test path: MEDIUM — `authkit` mode and the resource/issuer URLs are read directly from config, but this session did not (and should not, given the credential-access restriction) exercise a live OAuth call end-to-end to reconfirm it still works exactly as `docs/runbook-secret-rotation.md` recorded on 2026-09-01

**Research date:** 2026-09-14
**Valid until:** ~14 days (short window — this research depends on live production state: current deployed revision, IAM grants, and secret existence, all of which can change independently of this repo's git history)
