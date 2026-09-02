---
phase: 08-apple-health-nutrition-ingest
plan: 08
status: IN-PROGRESS -- BLOCKED AT TASK 3 (checkpoint:human-verify, gate=blocking)
subsystem: infra
tags: [secret-manager, cloud-run, deploy, health-auto-export, device-setup, smoke-test, docs]

# Dependency graph
requires:
  - phase: 08-apple-health-nutrition-ingest
    plan: 03
    provides: "--memory=1Gi and the HEALTH_INGEST_SECRET binding in scripts/deploy-cloud-run.sh, plus the INGEST_* tuning keys in deploy/cloud-run.env.yaml -- all shipped but never deployed until now"
  - phase: 08-apple-health-nutrition-ingest
    plan: 05
    provides: "_HEVY_SOURCE_ALIASES and health_ingest_multi_point_day -- the alias set Task 3 may extend and the drift alarm the setup doc names"
  - phase: 08-apple-health-nutrition-ingest
    plan: 07
    provides: "POST /api/v1/ingest/health-auto-export -- the route these smoke tests exercise against the live deployment for the first time"
  - phase: 02-deploy-connector-auth-spike
    provides: "brett-mcp-auth-secret's shape (automatic replication, secret-level secretAccessor to brett-run@) and scripts/deploy-cloud-run.sh"
provides:
  - "docs/health-auto-export-setup.md -- the device-side configuration BRETT depends on for correctness, with Daily aggregation stated as a prerequisite and health_ingest_multi_point_day named as its drift alarm"
  - "brett-health-ingest-secret in Google Secret Manager, readable by brett-run@ at the secret level"
  - "Cloud Run revision brett-00010-kln: 1Gi, HEALTH_INGEST_SECRET bound, INGEST_* tuning live"
  - "An observed (not asserted) record of the live endpoint's rejection contract"
affects: [09-historical-backfill, 13-reports-and-nutrition-trends]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Secret creation by stdin pipe, never a temp file: the value has no on-disk window to shred and cannot acquire a trailing newline"
    - "Byte-length assertion as the only quantitative fact recorded about a credential (a property of the generator, not of the value)"
    - "A doc's own verification section records OBSERVED output, so the document states what the endpoint does rather than what it should do"

key-files:
  created:
    - docs/health-auto-export-setup.md
  modified: []

key-decisions:
  - "The secret was piped to `gcloud --data-file=-` rather than written to /tmp: the runbook-secret-rotation.md procedure this plan was told to mirror explicitly warns that `print()` appends a newline that silently breaks compare_digest, and a pipe additionally removes the on-disk window entirely (T-08-52)"
  - "The wrong-token curl is NOT reproduced verbatim in the setup doc -- the plan's own acceptance criterion forbids a long token-shaped string after the word Bearer, and the plan's smoke-test token matches that pattern"
  - "No requirement marked complete: HEALTH-06 and NUTR-02 both claim data that SYNCS from the phone, which is Task 3"

patterns-established:
  - "A correlation-id match between the response header and the log line is what distinguishes BRETT's own 401 from the Cloud Run edge's -- a status code alone cannot"

requirements-completed: []  # HEALTH-06, NUTR-02 remain PENDING until Task 3 lands a real device export

# Metrics
duration: 10min (Tasks 1-2 only)
completed: null
---

# Phase 8 Plan 08: Deploy, Device Setup and Live Verification Summary

> ## THIS PLAN IS NOT COMPLETE
>
> **Tasks 1 and 2 of 3 are done and committed. Task 3 is a `checkpoint:human-verify` with
> `gate="blocking"` and is OUTSTANDING.** It requires the user to configure the Health Auto Export
> app on their iPhone and trigger a real export; no agent can perform it. Until it lands:
>
> - **ROADMAP success criterion #1 is NOT met** ("verified against the live deployment, not a fixture")
> - **RESEARCH Assumption A1 is still OPEN** — the highest-risk open item in the phase
> - **HEALTH-06 and NUTR-02 remain PENDING** in `REQUIREMENTS.md`
> - `backend/tests/fixtures/hae/device_capture.json` does not exist
>
> This file exists to record Tasks 1-2 across the checkpoint boundary. It must be revised, not
> merely appended to, when Task 3 completes.

**The credential exists, the service runs at 1Gi with it bound, the endpoint rejects a missing and a wrong bearer token with byte-identical bare 401s from BRETT's own handler — and the one setting BRETT cannot enforce is now written down as a prerequisite instead of remembered.**

## Performance

- **Duration:** ~10 min (Tasks 1-2)
- **Started:** 2026-09-02T10:28:39Z
- **Paused at checkpoint:** 2026-09-02T10:38:39Z
- **Tasks:** 2 of 3 complete
- **Files created:** 1

## Accomplishments

- **The phase's only unversioned state is now documented.** `docs/health-auto-export-setup.md`
  states the Daily aggregation interval as a **correctness prerequisite** with the reason spelled
  out — replace-semantics upsert is lossless only when each metric emits one datapoint per day —
  and names `health_ingest_multi_point_day` as the alarm that fires when it drifts. RESEARCH
  Pitfall N-2's remaining half (the between-deliveries half, which no code can fix) is now a
  written requirement rather than an assumption.
- **The 08-03 deploy prerequisites actually shipped.** The service had been running at **512Mi with
  no `HEALTH_INGEST_SECRET` and no `INGEST_*` variables at all** since revision `brett-00009-fsm`.
  Revision `brett-00010-kln` is the first to carry them. Until this deploy, the ingest route that
  08-07 landed answered 401 to everything because the server-side secret was `None` — correctly,
  and uselessly.
- **The 401 contract is now an observation, not a claim.** `cmp` reports the no-credential and
  wrong-credential bodies **byte-identical**, the response header sets differ only in per-request
  IDs, and the presented token appears zero times across body, headers and the Cloud Run log
  export. 08-07 proved this against a `TestClient`; this proves it against the internet.
- **The 401 was proven to come from BRETT, not from the edge.** Both smoke requests logged
  `health_ingest_unauthorized` with a `correlation_id` equal to the `x-request-id` returned to the
  caller. A `401` alone could equally have come from the Cloud Run edge or from the MCP sub-app's
  `RequireAuthMiddleware` — one of which would mean the route is unreachable. The ID match rules
  both out.
- **RESEARCH Pitfall 1 confirmed unregressed in production.**
  `GET /.well-known/oauth-protected-resource/mcp` returns `200` and still advertises the AuthKit
  authorization server. The new FastAPI route did not shadow the catch-all mount.
- **The credential never touched disk.** No temp file was created, so none had to be shredded.
  `git grep` and a full working-tree `grep` for the value both find nothing.

## Task Commits

| Task | Commit | Message |
|------|--------|---------|
| 1 | `4591c84` | `docs(08-08)`: Health Auto Export device setup prerequisites |
| 2 | `3b04cfc` | `docs(08-08)`: record the live ingest endpoint contract after deploy |
| 3 | — | **NOT STARTED — blocking checkpoint** |

## Files Created

- **`docs/health-auto-export-setup.md`** (270 lines). Nine sections. The load-bearing ones are §3
  (the required-settings table, where Aggregation interval = Daily carries its full argument in the
  Why column), §5 (the D-01 body-mass and D-02 workout exclusions with the measured duplicate counts
  — 52 of 79 and 218 of 221 — so a future reader cannot mistake them for taste), §7 (the drift
  alarm, its consequence, and its remedy), and §9 (the observed verification record). The document
  carries no credential value, only the Secret Manager secret name and the command that reads it.

## Infrastructure Changed

**These are live cloud-side changes, not repository changes.**

| Resource | Before | After |
|---|---|---|
| Secret `brett-health-ingest-secret` | did not exist | version 1 `enabled`, automatic replication, no labels |
| Its IAM | — | `roles/secretmanager.secretAccessor` -> `serviceAccount:brett-run@brett-fitness.iam.gserviceaccount.com`, bound on the **secret** (not per version), one binding |
| Cloud Run `brett` revision | `brett-00009-fsm` | **`brett-00010-kln`**, 100% traffic |
| Memory | `512Mi` | `1Gi` |
| Env (secret-bound) | `DATABASE_URL`, `MCP_AUTH_SECRET` | + **`HEALTH_INGEST_SECRET`** |
| Env (plain) | 9 keys | + `INGEST_MAX_BODY_BYTES`, `INGEST_RATE_LIMIT_PER_MINUTE`, `INGEST_RATE_LIMIT_BURST` |

The secret's shape was **read from the live `brett-mcp-auth-secret`** (`gcloud secrets describe` and
`get-iam-policy` on both) rather than copied from any document, exactly as the plan instructed. The
Phase 2 planning directory no longer exists on disk — the v1.0 milestone archived it — so
`docs/runbook-secret-rotation.md` served as the written procedure and the live resource served as
ground truth. They agreed.

## Verification Results

Every acceptance criterion from Tasks 1 and 2, run and recorded:

| Criterion | Result |
|---|---|
| `docs/health-auto-export-setup.md` exists | PASS |
| All 12 `METRIC_REGISTRY` keys appear verbatim | PASS (asserted against the live registry import, not a hand-copied list) |
| `grep -c "Daily"` >= 1 | 6 |
| `grep "health_ingest_multi_point_day"` | 1 match |
| `grep "api/v1/ingest/health-auto-export"` | 3 matches |
| `grep -i "body mass\|weight"` | matches |
| `grep -i "workout"` | matches |
| `grep -Ei "bearer [a-z0-9_-]{20,}"` returns nothing | PASS (see Deviation 2 — this criterion is what forced a rewording) |
| `gcloud secrets describe brett-health-ingest-secret` exits 0 | PASS |
| Deployed memory | `1Gi` |
| Deployed env includes `HEALTH_INGEST_SECRET` | PASS |
| `GET /health` | `200`, `{"status":"ok","database":"connected"}` |
| No-credential POST body | exactly `{"error":"unauthorized"}` |
| Wrong-credential response byte-identical, token not echoed | PASS (`cmp` identical; token count 0 in body + all headers + logs) |
| `/.well-known/oauth-protected-resource/mcp` | `200` |
| `git status --porcelain` clean; no temp file with the secret | PASS (no temp file was ever created) |
| Plan's composite Task 2 verify one-liner | `live smoke test passed` |
| Fast suite | 530 passed, 321 deselected |
| `test_cloud_run_deploy.py` (run before deploying) | 15 passed |

Two extra checks not required by the plan but run anyway:

- **Byte length of the stored secret is 64.** `secrets.token_urlsafe(48)` produces 64 characters;
  anything else would mean a trailing newline had been stored. This is the one quantitative fact
  it is safe to record about a credential, and it is the check that would have caught Deviation 1.
- **`health_ingest_unauthorized` correlation IDs matched the returned `x-request-id`.** See
  Accomplishments.

## Decisions Made

- **The secret was piped, not written to a temp file.** The plan prescribed
  `uv run python -c "import secrets; print(...)" > /tmp/brett-ingest-secret.txt` followed by
  `--data-file=/tmp/...` and a shred. `docs/runbook-secret-rotation.md` Step 3 — the Phase 2
  procedure the plan told me to mirror — prescribes the opposite and explains why. See Deviation 1.
- **No requirement was marked complete.** `HEALTH-06` reads "*syncs into BRETT via a Health Auto
  Export webhook receiver*" and `NUTR-02` "*syncs into BRETT via the same … receiver*". Both are
  claims about data arriving from the phone, which is Task 3. `HEALTH-07` and `HEALTH-08` were
  already marked complete by 08-07 and are unaffected.
- **`STATE.md` was not advanced and `ROADMAP.md` was not updated to "complete".** Both are derived
  from plan completion, and this plan is not complete. A blocker entry was added to `STATE.md`
  instead.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] The plan's secret-generation command would have stored a trailing newline**

- **Found during:** Task 2, step A
- **Issue:** The plan prescribes
  `uv run python -c "import secrets; print(secrets.token_urlsafe(48))" > /tmp/brett-ingest-secret.txt`
  and then `--data-file=/tmp/brett-ingest-secret.txt`. `print()` appends `\n`, and
  `gcloud secrets create --data-file=` stores the file's bytes verbatim — so the stored credential
  would have been 65 bytes ending in a newline. Cloud Run would inject that newline into
  `HEALTH_INGEST_SECRET`, and `verify_bearer`'s `secrets.compare_digest` would then reject the
  token the user copies **correctly** from `gcloud secrets versions access`. The symptom is a
  permanent 401 from a phone that is configured perfectly, with no diagnostic anywhere: the log
  line says only `health_ingest_unauthorized`, by design. This is not hypothetical — it is
  documented as a known failure mode in `docs/runbook-secret-rotation.md` Step 3, which is the
  Phase 2 procedure the plan's own action text instructs me to "mirror exactly ... rather than
  trusting the values above".
- **Fix:** Used the runbook's form —
  `python3 -c 'import secrets,sys; sys.stdout.write(secrets.token_urlsafe(48))' | gcloud secrets create … --data-file=-`.
  This also removes the on-disk window entirely, which strengthens T-08-52: there is no temp file
  to shred, no shred to forget, and no window in which the value exists outside process memory and
  Secret Manager. The plan's acceptance criterion "`/tmp/brett-ingest-secret.txt` no longer exists"
  is satisfied more strongly than intended — it never existed.
- **Verification:**
  `gcloud secrets versions access latest --secret=brett-health-ingest-secret | wc -c` returns `64`.
  The live endpoint's 401 behaviour is unaffected either way, so this check is the **only** thing
  that could have caught the bug before the user spent an evening debugging their phone.
- **Committed in:** No repository change (this is a cloud-side action). Recorded in
  `docs/health-auto-export-setup.md` §9 in `3b04cfc`.

**2. [Rule 1 - Correctness of instructions] Task 2's action text would have violated Task 1's acceptance criterion**

- **Found during:** Task 2, step C
- **Issue:** Task 1 requires `grep -Ei "bearer [a-z0-9_-]{20,}" docs/health-auto-export-setup.md`
  to return nothing — the guard against committing a credential. Task 2 then instructs me to
  "record the observed outputs of checks 2, 3 and 4 in `docs/health-auto-export-setup.md`'s
  verification section", and check 3's command is
  `-H 'authorization: Bearer wrong-ingest-token-7b2e-must-not-be-echoed'`. That literal is 42
  characters of lowercase alphanumerics and hyphens after the word `Bearer` — it matches the
  forbidden pattern exactly. Pasting the command verbatim, as instructed, would have failed the
  plan's own guard. (The same class of internally-contradictory criteria that 08-01, 08-03, 08-05,
  08-06 and 08-07 each recorded.)
- **Fix:** The verification record describes row 3 as "the same POST with a deliberately wrong
  bearer token", records the *result* (byte-identical to row 2, token echoed 0 times), and adds an
  explicit note telling the next reader why the literal is absent and how to reproduce the check.
  The command was run exactly as the plan specified — only its transcription into the document was
  changed.
- **Verification:** `grep -Ei "bearer [a-z0-9_-]{20,}"` returns nothing; the plan's composite
  Task 2 verify one-liner (which contains the literal token) passes.
- **Committed in:** `3b04cfc`

---

**Total deviations:** 2 auto-fixed (2 x Rule 1). No Rule 4 architectural decisions arose.
**Impact on plan:** No scope creep. Deviation 1 prevented shipping a credential that would have
been rejected on every correctly-configured request; deviation 2 reconciles two of the plan's own
criteria against each other. Every other instruction was executed exactly as written, including the
full smoke-test command set.

## Threat Model Coverage (Tasks 1-2)

| Threat ID | Disposition | Where it landed |
|-----------|-------------|-----------------|
| T-08-52 | mitigate | Value generated by `secrets.token_urlsafe(48)`, piped to stdin, never echoed, never on disk. `git grep` and a working-tree `grep` for the value both empty; `git status --porcelain` clean. The setup doc names the secret and never carries its value |
| T-08-54 | mitigate | §2 of the setup doc states the token goes in the `Authorization` header and never in the query string, with the reason (Cloud Run access logs; the MCP authorization spec prohibits it) |
| T-08-57 | mitigate | `secretAccessor` granted to `brett-run@` only, at the **secret** level, read off the live `brett-mcp-auth-secret` policy rather than reconstructed. Verified by re-reading the new secret's policy after binding |
| T-08-58 | mitigate | Smoke check 4: `/.well-known/oauth-protected-resource/mcp` returns `200` on the new revision |
| T-08-53 | **outstanding** | Task 3 — no fixture has been captured yet |
| T-08-55 | **outstanding** | Task 3 — Assumption A1 is still open |
| T-08-56 | **outstanding** | Documented (§3, §7) but not yet observed against a real export |
| T-08-59 | **outstanding** | Task 3 is the checkpoint |

## Issues Encountered

- **The Phase 2 planning directory does not exist.** The plan's `<read_first>` names
  `.planning/phases/02-deploy-connector-auth-spike/` for the `brett-mcp-auth-secret` creation
  procedure; the v1.0 milestone close archived every phase directory except 08. Substituted
  `docs/runbook-secret-rotation.md` (which records the procedure and its gotchas) plus a direct
  read of the live secret's `describe` and `get-iam-policy` output. The live resource is stronger
  evidence than a summary would have been, and the two agreed.
- **The service had never been deployed with 08-03's changes.** `brett-00009-fsm` predates the
  whole of Phase 8's execution. This was expected but is worth recording: every prior Phase 8 plan's
  "the deploy script now binds X" claim was true of the script and false of the running service
  until `3b04cfc`.

## Deferred Issues

Carried forward unchanged from 08-07, none of them this plan's to close:

1. `ruff format --check` reports 18 pre-existing files that would be reformatted;
   `backend/tests/conftest.py` has now been recorded by six consecutive plans. One
   `uv run ruff format backend/` clears it centrally.
2. The whole-batch ingest error path still has no test.

## User Setup Required

**This is the blocking checkpoint.** See Task 3 in `08-08-PLAN.md` for the full procedure. In short:
the user must create a REST API automation in the Health Auto Export iOS app pointing at
`https://brett-792870654598.us-central1.run.app/api/v1/ingest/health-auto-export`, with the
`Authorization: Bearer …` header, the 12 metrics from §4 of the setup doc, **Aggregation interval =
Daily**, and an export window that includes at least one recent training day.

The `Bearer` value is deliberately not in the setup doc. It must be read from Secret Manager and
handed to the user directly:

```bash
gcloud secrets versions access latest \
  --secret=brett-health-ingest-secret --project=brett-fitness
```

## Next Steps

**Task 3, and nothing else.** It closes, in one real export:

- ROADMAP criterion #1 (all five activity metrics plus calories and the six macros, live)
- ROADMAP criterion #3, live (a second identical export changes nothing)
- ROADMAP criterion #5 (two Apple Health freshness timestamps, Hevy's three unchanged)
- **RESEARCH Assumption A1** — CONFIRMED if `health_ingest_hevy_source_excluded` fires on a
  training day, REFUTED (and remediated with one added alias) if it does not. Phase 9's `export.xml`
  backfill reuses `_HEVY_SOURCE_ALIASES` and inherits whatever this answers.
- `HEALTH-06` and `NUTR-02`

## Self-Check: PASSED (for Tasks 1-2 only)

- `docs/health-auto-export-setup.md` verified present, 269 lines.
- Both claimed commit hashes verified in `git log`: `4591c84`, `3b04cfc`.
- `backend/tests/fixtures/hae/device_capture.json` verified **absent**, as it must be — Task 3
  has not run. A summary claiming otherwise would be the failure this check exists to catch.
- The secret value appears in neither the SUMMARY, the setup doc, any tracked file, nor anywhere in
  the working tree. `git status --porcelain` empty.
- Live re-check after writing this file: memory `1Gi`; `GET /health` -> `200`;
  unauthenticated ingest POST -> `401`; `/.well-known/oauth-protected-resource/mcp` -> `200`
  (three consecutive attempts; one earlier probe returned a transient curl `000` with no HTTP
  response, not a service error).
- `must_haves` status: `docs/health-auto-export-setup.md` **satisfied** (contains "Daily", all 12
  registry keys, the drift alarm). `backend/tests/fixtures/hae/device_capture.json`
  **NOT satisfied** — Task 3.
- `key_links` status: the documented Daily interval -> `normalize.py`'s
  `health_ingest_multi_point_day` link is **written** but not yet **observed** against a real
  export. Task 3 observes it.
- No file deletions in either commit (`git diff --diff-filter=D --name-only 8876b20..HEAD` empty).
  No untracked files. No `git clean` was run at any point.

---
*Phase: 08-apple-health-nutrition-ingest*
*Tasks 1-2 completed: 2026-09-02. Task 3 outstanding.*
