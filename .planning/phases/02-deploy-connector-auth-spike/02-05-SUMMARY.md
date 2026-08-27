---
phase: 02-deploy-connector-auth-spike
plan: 05
subsystem: infra
tags: [cloud-run, gcloud, neon, secret-manager, alembic, mcp, checkpoint]
status: BLOCKED — partial, stopped at Task 1 checkpoint:human-action

# Dependency graph
requires:
  - phase: 02-deploy-connector-auth-spike (plan 08)
    provides: Procfile, .gcloudignore, deploy/cloud-run.env.yaml, scripts/deploy-cloud-run.sh, backend/tests/test_cloud_run_deploy.py — all validated present and green (12 passed) before this plan paused
provides: []   # nothing shipped yet — see "Status" below
affects: [02-06 WorkOS resource indicator, 02-07 connector round-trip + --min=1 flip]

# Tech tracking
tech-stack:
  added: []
  patterns: []

key-files:
  created:
    - .planning/phases/02-deploy-connector-auth-spike/02-05-SUMMARY.md
  modified: []

key-decisions:
  - "Stopped at Task 1's blocking gate without creating a GCP project: `gcloud projects create` + `gcloud billing projects link` bind a real billing account to a new project, which is spending the developer's money and is not an agent's decision to make"

patterns-established: []

requirements-completed: []   # DEPLOY-01, MCP-01, MCP-04 all remain OPEN. Nothing is deployed.

# Metrics
duration: 8min (precondition gathering only)
completed: null
---

# Phase 2 Plan 05: Cloud Run Deploy — PARTIAL (blocked at Task 1)

**Every automatable precondition for the Cloud Run deploy is verified green — clean tree, 12/12 deploy-artifact tests, gcloud 578.0.0 authenticated against an open billing account — but the plan is stopped at its first task, a blocking `checkpoint:human-action` requiring the developer to authorise spend and hand back a Neon connection string. No GCP resource was created and no money was spent.**

## Status

| Task | Type | State |
|---|---|---|
| 1. Authorise GCP project + billing, create Neon DB | `checkpoint:human-action` | **BLOCKED — awaiting developer** |
| 2. Bootstrap project, store secrets, pin hostname, migrate Neon | `auto` | Not started (gated by 1) |
| 3. Deploy, reconcile URLs, run Auth Verification Matrix | `auto` | Not started (gated by 2) |
| 4. D-01 Claude Code CLI proof | `checkpoint:human-verify` | Not started (gated by 3) |

**0 of 4 tasks complete. No task commit exists.** This summary is the only artifact.

## Performance

- **Duration:** ~8 min (precondition gathering only)
- **Started:** 2026-08-27T05:39:28Z
- **Paused at checkpoint:** 2026-08-27T05:47Z
- **Tasks:** 0 of 4
- **Files modified:** 1 (this summary)

## Precondition Evidence Gathered (Task 1 `<action>` steps 1-6)

All six of Task 1's pre-pause requirements were completed, so the developer is deciding rather than discovering.

### 1. Working tree clean, plan 02-08's artifacts committed

`git status --short` → empty, both before and after materialising the worktree venv.

### 2. Deploy artifacts still validate

`uv run pytest backend/tests/test_cloud_run_deploy.py -q` → **12 passed** in 0.41s.

The worktree had no `.venv`; `uv sync --frozen --group dev` was run once to materialise it (the `--group dev` is required since plan 02-08 set `[tool.uv] default-groups = []`, so a bare `uv sync` no longer installs pytest). Same `VIRTUAL_ENV=` prefix workaround plans 02-01/02-03/02-08 reported.

### 3. gcloud environment — all five probes match the plan's `<interfaces>` table exactly

| Probe | Observed | Matches plan |
|---|---|---|
| `gcloud version \| head -1` | `Google Cloud SDK 578.0.0` | yes |
| `gcloud auth list --format='value(account)'` | `hovegant12@gmail.com` | yes |
| `gcloud config get-value project` | `idx-yfinance-mcp-1785725283` | yes — **an unrelated project** |
| `gcloud billing accounts list` | `01E8E3-6C54F5-D6B9B6` "My Billing Account 1" **OPEN=True**; `01438D-49BD0E-61F138` OPEN=False | yes |
| `gcloud projects list \| wc -l` | `7` | yes |

**On the active project:** it is `idx-yfinance-mcp-1785725283`, which has nothing to do with BRETT. This is exactly why `scripts/deploy-cloud-run.sh` opens with `PROJECT_ID="${BRETT_GCP_PROJECT:?set BRETT_GCP_PROJECT}"` — it fails closed rather than inheriting this value (T-02-16). Every `gcloud` call in Task 2 and Task 3 passes `--project` explicitly for the same reason.

### 4. Proposed project ID — and why the availability probe cannot actually answer the question

**Proposal: `brett-fitness`** (13 chars, matches `^[a-z][a-z0-9-]{5,29}$`). Alternate if taken: **`brett-fitness-eceh`**.

The plan's prescribed probe is inconclusive by Google's design. Calibrated three ways:

```
gcloud projects describe brett-fitness       → PERMISSION_DENIED
gcloud projects describe brett-fitness-eceh  → PERMISSION_DENIED   (random 4-char suffix, near-certainly nonexistent)
gcloud projects describe habit-tracker-app-441414 → habit-tracker-app-441414   (control: a project this account owns)
```

A random, almost-certainly-free ID returns the **identical** error to the proposed one. Google deliberately conflates "does not exist" with "exists but you cannot see it" to prevent project-ID enumeration. So `describe` is a positive-only oracle: success proves *you already own it*, failure proves nothing at all. Availability is only discoverable by attempting `gcloud projects create` — which is precisely the gated action. See Deviations #1.

### 5. Exact bootstrap sequence Task 2 will run

Substituted with the proposed values, for concrete authorisation:

```bash
PROJECT_ID="brett-fitness"
REGION="us-central1"
BILLING_ACCOUNT="01E8E3-6C54F5-D6B9B6"

gcloud projects create "$PROJECT_ID" --name="BRETT"                       # <-- creates a resource
gcloud billing projects link "$PROJECT_ID" --billing-account="$BILLING_ACCOUNT"   # <-- starts the meter
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com \
  compute.googleapis.com --project="$PROJECT_ID"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/run.builder"
gcloud iam service-accounts create brett-run --project="$PROJECT_ID" \
  --display-name="BRETT Cloud Run runtime"
# two secrets written with printf (never echo — Pitfall CR-6), per-secret accessor grants
```

`compute.googleapis.com` is enabled not for VMs but because it is what materialises the Compute Engine default service account; its absence is a named cause of first-deploy failure in a Run-only project. `roles/run.builder` is required because, since July 2024, that account no longer inherits the legacy Cloud Build role in new projects.

### 6. Deterministic URL that will result

```
https://brett-<PROJECT_NUMBER>.us-central1.run.app/mcp
```

Knowable before the first deploy, which is what removes the abandoned Render path's deploy→discover→redeploy round trip. Cloud Run also assigns a legacy hash URL and serves both, so Task 3 step 3 still reads `gcloud run services describe` and appends any second hostname to `MCP_ALLOWED_HOSTS`.

## Bonus checks (cheap, and they retire open assumptions early)

- **A-CR-1, flag-acceptance half: RESOLVED POSITIVELY.** `gcloud run deploy --help` lists `--set-build-env-vars` (2 occurrences) on SDK 578.0.0, so the deploy script will not be rejected outright. The remaining half — whether non-`GOOGLE_`-prefixed keys are actually *forwarded* to the buildpack — is only observable from the first build log's package count (41 = `default-groups = []` took effect, 73 = it did not), exactly as plan 02-08's handoff specifies.
- **`--min` vs `--min-instances`:** both exist on SDK 578.0.0. The script uses `--min`, per research Q4.3. No change needed.
- **Task 4 readiness:** `claude` CLI is **2.1.246** (the plan verified against 2.1.237). `claude mcp add --help` still lists both `-t, --transport` and `-H, --header`, so the D-01 command shape in the plan is intact despite the version drift.
- **gitleaks baseline:** `uv run pre-commit run gitleaks --all-files` → **Passed**.

## Deviations from Plan

Both are defects in the plan's own acceptance-criteria text, found while gathering Task 1's preconditions. Neither is a code change; both are recorded so the criteria are not silently marked pass or silently failed by a later verifier. No repo file was modified for either.

**1. [Rule 1 - Bug] Task 1's project-ID availability criterion is unsatisfiable as written**

- **Found during:** Task 1, precondition step 4
- **Issue:** The plan says *"a `NOT_FOUND` or `PERMISSION_DENIED` means it is taken or unavailable to this account"*, and the acceptance criterion reads *"Claude's availability probe did not report it as already taken."* But `gcloud projects describe` returns `PERMISSION_DENIED` for **every** ID the caller does not own, whether or not it exists — verified above against a random suffix. Under the plan's stated reading, every candidate ID including a freshly-invented one is "taken", so the criterion can never pass and carries no signal.
- **Fix:** Not fixed in code — surfaced to the developer at the checkpoint instead, with the three-way calibration above so the ambiguity is explicit. The criterion's *intent* ("do not collide with an existing project") is only testable by running `gcloud projects create`, which is the gated action itself. If creation fails with `ALREADY_EXISTS`, Task 2 falls back to `brett-fitness-eceh`.
- **Verification:** Three `describe` calls, one owned control returning success, two non-owned returning identical errors.
- **Committed in:** this summary (no code commit)

**2. [Rule 1 - Bug] Task 1's repo-wide DSN grep criterion already fails at baseline, before any credential is handled**

- **Found during:** Task 1, precondition step 1
- **Issue:** The criterion is `grep -rilE 'postgres(ql)?://[^ ]*:[^ ]*@' --exclude-dir=.git . | wc -l` returns `0`. It matches **19 tracked files** on the pristine tree — every one a documentation placeholder (`.env.example` documents the `USER:PASSWORD@HOST` shape; `01-01-PLAN.md` and `test_secret_redaction.py` use throwaway `u:pw@h`-style literals as redaction fixtures). The regex matches DSN *shape*, and this repo legitimately documents DSN shape in nineteen places. The criterion would report a violation no matter what Task 2 does. Same class of collision as plan 02-08's Deviation #2 and plan 02-03's two.
- **Fix:** Not fixed in code. The baseline set is captured verbatim below so the criterion can be evaluated by its intent — *the pasted Neon DSN never lands in a file* — as: **the match set after Task 2 is unchanged from this baseline, and gitleaks still passes.** That is a real test; the literal `wc -l == 0` is not.
- **Baseline match set (19 paths, measured before this summary existed):** `.env.example`, `01-01-PLAN.md`, `01-01-SUMMARY.md`, `01-02-PLAN.md`, `01-03-PLAN.md`, `01-05-PLAN.md`, `01-RESEARCH.md`, `02-01-PLAN.md`, `02-08-PLAN.md`, `02-08-SUMMARY.md`, `02-PATTERNS.md`, `02-RESEARCH.md`, `README.md`, `backend/app/config.py`, `backend/tests/conftest.py`, `backend/tests/test_config.py`, `backend/tests/test_db_models.py`, `backend/tests/test_mcp_auth.py`, `backend/tests/test_secret_redaction.py`
- **Note for the verifier:** this summary quotes the regex on the line above, so **`02-05-SUMMARY.md` itself joins the set once committed, making the expected count 20, not 19.** That is self-reference, not a leak — the only DSN-shaped text in this file is the regex literal itself. Verified: `grep -cE` on this file returns `1`, on line 155 only.
- **Verification:** `git grep -lIE` over tracked files; `pre-commit run gitleaks --all-files` → Passed.
- **Committed in:** this summary (no code commit)

**3. [Rule 3 - Blocking, pre-empted] The `000000000000` placeholder occurs three times, not two — and Task 2's criterion demands zero**

- **Found during:** Task 1 self-check (verifying `deploy/cloud-run.env.yaml` was untouched)
- **Issue:** Plan 02-08's handoff table and this plan's Task 2 `<read_first>` both describe the placeholder as appearing in *"two keys"*. It actually appears on **three lines**: `MCP_ALLOWED_HOSTS` (26), `MCP_RESOURCE_URL` (31), and **an explanatory comment on line 23** (`# 000000000000 is a PLACEHOLDER for the GCP project number...`). Task 2's acceptance criterion is `grep -c '000000000000' deploy/cloud-run.env.yaml` returns `0`. Substituting only the two keys leaves the comment behind, the count returns `1`, and Task 2 fails its own criterion while the configuration is in fact correct.
- **Fix:** Not applicable yet — Task 2 has not run. Recorded here so whoever resumes substitutes the two **values** *and* rewrites the line-23 comment (it is stale the moment the real number lands: it says "Plan 02-05 replaces it", which will have happened). The companion criterion `grep -c "brett-$PROJECT_NUMBER"` returns `2` correctly targets only the two keys, so the two criteria together are satisfiable once the comment is rewritten to stop naming the literal.
- **Verification:** `grep -n '000000000000' deploy/cloud-run.env.yaml` → lines 23, 26, 31.
- **Committed in:** this summary (no code commit — the file is deliberately untouched)

---

**Total deviations:** 3 documented (3 plan-text/handoff bugs, 0 code changes)
**Impact on plan:** None on the deliverables — none affects what Task 2/3/4 actually build. All three would otherwise have produced a false red at verification time, #3 inside Task 2's own acceptance gate.

## Issues Encountered

- **Worktree base was stale.** The worktree branch was created from `1e97f3b` but the orchestrator specified base `3b9b383` ("docs(phase-02): update tracking after wave 4"), so wave 4's commits — including every artifact this plan consumes — were absent. Corrected with the branch-check protocol's `git reset --hard 3b9b383` on a clean tree. Without this, `deploy/cloud-run.env.yaml`, `scripts/deploy-cloud-run.sh`, `Procfile` and `test_cloud_run_deploy.py` would all have been missing and Task 1's second precondition would have errored rather than reporting 12 passed.
- **Fresh worktree had no `.venv`.** Resolved with one `uv sync --frozen --group dev`. Note the `--group dev`: plan 02-08's `default-groups = []` means a bare `uv sync` gives a production-shaped env with no pytest.

## Security Notes

**Nothing was provisioned and no credential was handled.** No GCP project created, no billing account linked, no API enabled, no service account created, no secret written, no deploy run, and no Neon connection string received or requested-in-file. The `checkpoint:human-action` gate held exactly as designed.

The threat register's `mitigate` items for this plan are all downstream of Task 2 and remain **unimplemented**: T-02-10 (log redaction), T-02-12 (least-privilege runtime SA), T-02-01 (host allowlist, live), T-02-06 (deployed 401), T-02-04 (401 body not an oracle), T-02-09 (tool response), T-02-17 (trailing-newline secret), T-02-11 (upload set), T-02-16 (right project). Only the pre-existing static half of T-02-11/T-02-16 — the committed `.gcloudignore` and the fail-closed `BRETT_GCP_PROJECT` — is in place, inherited from plan 02-08.

**No threat flags.** This plan has introduced no new surface, because it has introduced nothing.

## User Setup Required

**Yes — this is the blocker.** Four items, detailed in the checkpoint returned to the orchestrator:

1. Approve the project ID (`brett-fitness`, or name another)
2. Explicitly authorise charging billing account `01E8E3-6C54F5-D6B9B6`
3. Explicit yes/no on plan 02-07's `--min=1` warm-instance flip (D-06f) — a "no" is a valid answer that 02-07 must route around, and discovering it there instead of here would stall the connector test
4. Create the Neon project (US region) and hand back the **DIRECT / unpooled** connection string — into the conversation only, never into a file

## Next Phase Readiness

**Not ready.** Plans 02-06 and 02-07 both depend on outputs this plan has not produced:

- **02-06** needs the canonical hostname for the WorkOS Resource Indicator — unknown until the GCP project number exists.
- **02-07** needs the connector URL and the cold-start latency figure — unknown until Task 3 deploys.

`deploy/cloud-run.env.yaml` still carries plan 02-08's `000000000000` placeholder in both `MCP_ALLOWED_HOSTS` and `MCP_RESOURCE_URL`. That is unchanged and correct: the real project number does not exist yet.

**Carried forward, unresolved:**
- **A-CR-1** — half resolved (flag is accepted); the forwarding half needs the first build log.
- **A-CR-3** — whether Cloud Run forwards the original public `Host` header unmodified. Still unknown; diagnosable in one request (matrix row 7) once deployed.
- **Research addendum validity** — dated *valid until 2026-09-10*. Today is 2026-08-27, so still inside the window, but Cloud Buildpacks' Python/uv support is actively changing. If this checkpoint sits unanswered past 2026-09-10, re-verify the Procfile analysis before Task 3.

## Known Stubs

| Stub | File | Line | Reason / resolver |
|---|---|---|---|
| `000000000000` GCP project number | `deploy/cloud-run.env.yaml` | **23 (comment)**, 26 (`MCP_ALLOWED_HOSTS`), 31 (`MCP_RESOURCE_URL`) | Inherited from plan 02-08, **still unresolved** because this plan stopped before creating the GCP project. Resolved by this plan's Task 2 once the checkpoint is answered — note all **three** occurrences must go, not two (Deviation #3). |
| `MCP_ISSUER_URL: "https://example.authkit.app"`, `MCP_JWKS_URI: ""` | `deploy/cloud-run.env.yaml` | 37-38 | Intentional; `MCP_AUTH_MODE` is `static` for the D-01 CLI proof. Resolved by plans 02-06/02-07. |

## Self-Check: PASSED

- File claimed created verified present: `.planning/phases/02-deploy-connector-auth-spike/02-05-SUMMARY.md`.
- No task commits claimed, because none exist — consistent with 0 of 4 tasks complete.
- No GCP resource claimed created; `gcloud projects list | wc -l` remains `7`, unchanged from the pre-execution probe.
- `deploy/cloud-run.env.yaml` verified still containing `000000000000` (untouched), consistent with Task 2 not having run.
- `02-DEPLOY-LOG.md` deliberately **not** created — it is Task 2's artifact and Task 2 did not run. A verifier should expect its absence.

**Not modified, by design (worktree mode):** `.planning/STATE.md` and `.planning/ROADMAP.md` — the orchestrator owns those writes.

---
*Phase: 02-deploy-connector-auth-spike*
*Status: BLOCKED at Task 1 checkpoint:human-action — 0 of 4 tasks complete*
