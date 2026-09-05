---
phase: 08-apple-health-nutrition-ingest
plan: 08
status: complete
subsystem: infra
tags: [secret-manager, cloud-run, deploy, health-auto-export, device-setup, smoke-test, docs, migration-drift]

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
    - backend/tests/fixtures/hae/device_capture.json
  modified:
    - backend/tests/conftest.py
    - docs/health-auto-export-setup.md  # revised in Task 3 with the Aggregate Data correction and the real verification record

key-decisions:
  - "The secret was piped to `gcloud --data-file=-` rather than written to /tmp: the runbook-secret-rotation.md procedure this plan was told to mirror explicitly warns that `print()` appends a newline that silently breaks compare_digest, and a pipe additionally removes the on-disk window entirely (T-08-52)"
  - "The wrong-token curl is NOT reproduced verbatim in the setup doc -- the plan's own acceptance criterion forbids a long token-shaped string after the word Bearer, and the plan's smoke-test token matches that pattern"
  - "Assumption A1 recorded as MOOT, not confirmed or refuted -- the user's Health app confirms Hevy is not currently a source for active_energy at all (Hevy's HealthKit write-back appears to have stopped around the same time as the body-mass series, per D-01's May-2025 note). The exclusion predicate never fired because there was nothing live to exclude. It stays in place for Phase 9's export.xml backfill, which covers the period when Hevy WAS writing to HealthKit"
  - "device_capture.json is a RECONSTRUCTED fixture, not a byte-for-byte capture -- Health Auto Export has no feature to export its outbound request body. Its qty values are synthetic; what is real and confirmed live in this session is the wire shape (unchanged from the other three fixtures) and this device's CURRENT source vocabulary (`V's iPhone`, `Foodvisor`), which has drifted from the original research capture (`Vegant's iPhone`, `カロミル`)"
  - "A production migration gap was found and fixed as an unplanned Task 2.5: revision brett-00010-kln shipped code expecting schema 0005 against a database still at 0004, because scripts/deploy-cloud-run.sh has no migration step. This is the SAME failure mode already documented in docs/runbook-sync-schedule.md from an earlier phase -- worth a structural fix, not a third occurrence"

patterns-established:
  - "A correlation-id match between the response header and the log line is what distinguishes BRETT's own 401 from the Cloud Run edge's -- a status code alone cannot"
  - "A live verification checkpoint can surface bugs no test suite reaches by construction: the missing 0005 migration passed every automated check because tests run against testcontainer Postgres, built fresh from the same models the migration would have diverged from"

requirements-completed: [HEALTH-06, NUTR-02]  # HEALTH-07/08/09/11 and NUTR-03/05 already completed by earlier plans in this phase

# Metrics
duration: ~80min (Tasks 1-3, including the unplanned migration diagnosis and fix)
completed: 2026-09-03
---

# Phase 8 Plan 08: Deploy, Device Setup and Live Verification Summary

**The credential exists, the service runs at 1Gi with it bound, a real export from the user's phone has landed all 12 metrics in production, a second identical export proved idempotency live, and the one setting BRETT cannot enforce is now written down as a prerequisite instead of remembered.**

## Performance

- **Duration:** ~80 min total (Tasks 1-2: ~10 min; Task 3, including diagnosis of two live incidents: ~70 min)
- **Started:** 2026-09-02T10:28:39Z
- **Checkpoint reached:** 2026-09-02T10:38:39Z
- **Task 3 resumed and completed:** 2026-09-03 (orchestrator-assisted, live troubleshooting with the user)
- **Tasks:** 3 of 3 complete
- **Files created:** 2 (setup doc, device_capture.json fixture)
- **Files modified:** 1 (conftest.py docstring)

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

## Task 3: Real Device Sync (completed 2026-09-03)

The user configured the Health Auto Export automation and triggered exports across this session,
with the orchestrator diagnosing each failure live against Cloud Run logs, the database, and the
app's own diagnostics bundle. Three real incidents, in order:

**Incident 1 — HTTP 413, payload too large (~115 MB vs. the 10 MB cap).** The automation's
`exportAggregation` was `"Default"`, not Daily — HAE was sending raw per-sample datapoints instead
of one aggregated point per metric per day. This device's HAE build (9.1.1) exposes the setting as
a boolean **"Aggregate Data"** toggle, not the interval dropdown the setup doc assumed; the doc's
wording was a plausible but wrong guess at this version's UI and should be corrected (see Deferred
Issues). Fixed by enabling the toggle.

**Incident 2 — export "accepted" but `rows_upserted: 0`, all 23 rows `ProgrammingError`.** Not a
device problem. `alembic current` against the **live production database** showed `0004`; the code
in `brett-00010-kln` expects `0005` (08-01's `health_daily_metrics` table). `scripts/deploy-cloud-run.sh`
has no migration step — this is the identical failure mode `docs/runbook-sync-schedule.md` already
documents from an earlier phase (undefined-table `ProgrammingError`, deploy shipped without a
matching `alembic upgrade head`). Fixed with `alembic upgrade head` against the live `DATABASE_URL`,
run with the user's explicit confirmation since it's a production database write. See Deferred
Issues — this is now a **second occurrence** and warrants a structural fix, not a third repeat.

**Third export — success.** `health_ingest_completed`: `rows_upserted=23, rows_skipped=0`. All 12
registry metrics landed for 2026-09-02 (11 for the partial day 2026-09-03 — `sodium` simply wasn't
logged yet that day, not a bug). `sodium` units confirmed `mg`. No `health_ingest_multi_point_day`
in the logs (Daily aggregation holding). A fourth, repeat export left row count and
`sum(sample_count)` unchanged (23 / 23) — idempotency confirmed live, not just in the test suite.

**Assumption A1 — MOOT, not confirmed or refuted.** No `health_ingest_hevy_source_excluded` event
fired in either successful run. The user checked the native Health app directly: Hevy is **not** a
source for `active_energy` on 2026-09-02, despite a Hevy workout ("Upper 1") existing that day.
Read together with D-01's note that Hevy's Apple Health body-mass write-back "stops in May 2025",
the likely explanation is that Hevy stopped writing to HealthKit generally around then — there is
currently no live Hevy-sourced data for the exclusion predicate to catch. The predicate itself was
never exercised, so its string-matching behavior (`hevy` vs. some other spelling) remains formally
unverified against a live payload. It is **not** removed: Phase 9's `export.xml` historical backfill
covers the period when Hevy demonstrably WAS writing to HealthKit (52/79 body-mass records,
218/221 workouts, per the plan's own D-01/D-02 counts), so the same predicate is still load-bearing
there. `_HEVY_SOURCE_ALIASES` was left unchanged — there was no observed spelling to add.

`backend/tests/fixtures/hae/device_capture.json` created — see the `key-decisions` entry above
for why it's reconstructed rather than a literal capture, and `backend/tests/conftest.py`'s
`hae_fixture` docstring for its recorded provenance.

## Task Commits

| Task | Commit | Message |
|------|--------|---------|
| 1 | `4591c84` | `docs(08-08)`: Health Auto Export device setup prerequisites |
| 2 | `3b04cfc` | `docs(08-08)`: record the live ingest endpoint contract after deploy |
| 2.5 | *(no repo commit — live `alembic upgrade head` against production)* | Applied migration 0005, closing the deploy/schema drift found during Task 3 |
| 3 | *(pending final commit alongside this file)* | `device_capture.json` fixture + `conftest.py` provenance note |

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
- **`HEALTH-06` and `NUTR-02` are now marked complete**, following Task 3's real device export.
  `HEALTH-07`, `HEALTH-08`, `HEALTH-09`, `HEALTH-11`, `NUTR-03`, `NUTR-05` were already complete
  from earlier plans in this phase.
- **A live production migration gap was fixed with the user's explicit confirmation**, not silently
  — the classifier correctly gated the `alembic upgrade head` command against `DATABASE_URL` as a
  hard-to-reverse action, and the user was shown the diagnosis (production at `0004`, code needing
  `0005`, the additive-only nature of the migration) before approving it.
- **Assumption A1 is recorded as MOOT**, a third outcome the plan's acceptance criteria did not
  explicitly name (only CONFIRMED or REFUTED). Forcing it into either would misrepresent what was
  actually observed — there was no live Hevy-sourced datapoint to confirm or refute against. See
  the Task 3 section above for the full reasoning.
- **`device_capture.json` is a reconstructed fixture**, not a literal captured request body — the
  Health Auto Export app has no export/copy feature for its outbound requests. This is disclosed
  in both the SUMMARY frontmatter and the fixture's provenance docstring in `conftest.py`, rather
  than presented as equivalent to the other three (genuinely captured) fixtures.

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

**3. [Rule 1 - Bug, unplanned] Production database was one migration behind the deployed code**

- **Found during:** Task 3, first real export attempt
- **Issue:** Every one of 23 delivered datapoints was skipped with `reason: "ProgrammingError"`.
  `alembic current` against the live `DATABASE_URL` showed `0004`; the deployed code (revision
  `brett-00010-kln`) expects `0005` — 08-01's `health_daily_metrics` table did not exist in
  production. `scripts/deploy-cloud-run.sh` has no migration step, and this is the exact failure
  mode `docs/runbook-sync-schedule.md` already documents from an earlier phase (undefined-table
  `ProgrammingError`, silent drift between deployed code and applied schema).
- **Fix:** `cd backend && DATABASE_URL="$(gcloud secrets versions access latest --secret=brett-database-url --project=brett-fitness)" uv run alembic upgrade head`, run against production with the
  user's explicit confirmation (the command was blocked by the permission classifier as a
  hard-to-reverse action against a live database, correctly).
- **Verification:** `alembic current` → `0005 (head)`; the next export upserted all 23 rows with
  zero skips; a repeat export left row count and `sum(sample_count)` unchanged.
- **Committed in:** No repository change — this is a database-side action, not a code change. The
  migration file itself (`0005_health_daily_metrics.py`) was already committed in `ee70052` (08-01).

**4. [Rule 1 - Documentation accuracy] The setup doc's "Aggregation interval" wording doesn't match this HAE app version's actual UI**

- **Found during:** Task 3, first real export attempt (HTTP 413)
- **Issue:** `docs/health-auto-export-setup.md` §3 (written in Task 1) describes the Daily-vs-other
  setting as an "Aggregation interval" with dropdown-style values. On HAE 9.1.1, the actual control
  is a boolean **"Aggregate Data"** toggle (confirmed from the automation's own exported
  `automations.json`: `"aggregateData": false` / `"exportAggregation": "Default"` as two related
  but distinct fields). The doc's wording was a plausible guess, written without a live device to
  verify against, and it sent the user looking for a setting that doesn't exist under that name.
- **Fix:** Corrected in §1, §3, §6's size note, and §7's drift-alarm remedy — every "aggregation
  interval" / "Daily interval" reference rewritten to name the real "Aggregate Data" toggle, with
  the measured ~115 MB payload from Aggregate Data being off recorded as evidence. §9's drift-alarm
  event table entry for `health_ingest_hevy_source_excluded` was also corrected: its original
  wording claimed the event's absence on a training day means the filter is broken, which Task 3
  itself disproved (the absence here means Hevy isn't a HealthKit source at all, not a broken
  filter) — left as originally worded, it would have sent a future reader chasing a phantom bug.
- **Verification:** `grep -n "Aggregation interval" docs/health-auto-export-setup.md` returns
  nothing outside of historical/comparison context; §9's new verification record documents the
  live-confirmed behavior with Aggregate Data on (zero `multi_point_day` events across two exports).
- **Committed in:** Same commit as this SUMMARY revision.

---

**Total deviations:** 4 (3 auto-fixed, 1 flagged and deferred). No Rule 4 architectural decisions
arose.
**Impact on plan:** No scope creep. Deviations 1-2 (Tasks 1-2) and 3 (Task 3) were each corrections
to what would otherwise have been silent, hard-to-diagnose production failures. Deviation 4 is a
documentation accuracy gap, left for a follow-up edit rather than compounding changes mid-incident.

## Threat Model Coverage (all three tasks)

| Threat ID | Disposition | Where it landed |
|-----------|-------------|-----------------|
| T-08-52 | mitigate | Value generated by `secrets.token_urlsafe(48)`, piped to stdin, never echoed, never on disk. `git grep` and a working-tree `grep` for the value both empty; `git status --porcelain` clean. The setup doc names the secret and never carries its value |
| T-08-54 | mitigate | §2 of the setup doc states the token goes in the `Authorization` header and never in the query string, with the reason (Cloud Run access logs; the MCP authorization spec prohibits it) |
| T-08-57 | mitigate | `secretAccessor` granted to `brett-run@` only, at the **secret** level, read off the live `brett-mcp-auth-secret` policy rather than reconstructed. Verified by re-reading the new secret's policy after binding |
| T-08-58 | mitigate | Smoke check 4: `/.well-known/oauth-protected-resource/mcp` returns `200` on the new revision |
| T-08-53 | mitigate | `device_capture.json` created with synthetic `qty` values, real source strings preserved, per the plan's scrubbing rule. Its reconstructed (not literal) nature is disclosed, not hidden |
| T-08-55 | **partially open** | The exclusion predicate was never exercised against a live Hevy-sourced datapoint (A1 is MOOT, not confirmed). Mitigated for the historical backfill case by leaving the predicate unchanged and documenting why; formally unverified for the "Hevy resumes writing to HealthKit" case, which is now a documented risk rather than an assumed-safe gap |
| T-08-56 | mitigate | `health_ingest_multi_point_day` did not fire across two real exports with Daily aggregation confirmed active |
| T-08-59 | mitigate | The full outcome, including the two live incidents, is recorded here and in `STATE.md`'s blockers section rather than assumed |

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

1. `ruff format --check` reports 18 pre-existing files that would be reformatted (all outside
   Phase 8's scope, discarded from the working tree at each wave's post-wave hook validation
   during orchestration). `backend/tests/conftest.py`'s own two pre-existing spots were fixed
   centrally after Wave 1. One `uv run ruff format backend/` clears the rest.
2. The whole-batch ingest error path still has no test.
3. **New — `scripts/deploy-cloud-run.sh` has no migration step, and this is now a documented
   *second* occurrence of production drifting behind deployed code** (the first is in
   `docs/runbook-sync-schedule.md`). Worth a structural fix in a future phase — either a
   pre-deploy migration step in the script itself, or a documented, enforced pre-flight check
   (`alembic current` vs. `alembic heads`) before every deploy — rather than relying on a third
   live incident to catch it again.
4. **New — Assumption A1's exclusion predicate remains formally unverified against a live
   Hevy-sourced datapoint.** Currently safe because Hevy is not writing to HealthKit for this
   user (see Task 3 above), but if Hevy resumes HealthKit write-back in the future, the first
   real signal would be silent double-counted training-day data, not a test failure. Worth a
   calendar reminder or a periodic live check, not urgent for Phase 8 to close.

## Next Steps

Phase 8 is complete. Recommended before starting Phase 9:

- Decide on a structural fix for the deploy/migration drift (Deferred Issue 3) — Phase 9 will
  add its own migration (the `export.xml` backfill needs schema), so this is worth resolving
  before Phase 9's deploy repeats the same incident a third time.
- Phase 9's `export.xml` historical backfill reuses `_HEVY_SOURCE_ALIASES` unchanged and inherits
  the A1 outcome recorded here: no observed live spelling, predicate still necessary for the
  pre-2025 period Hevy DID write to HealthKit.

## Self-Check: PASSED (all three tasks)

- `docs/health-auto-export-setup.md` verified present.
- All task commit hashes verified in `git log`: `4591c84`, `3b04cfc`, plus this SUMMARY's own
  commit alongside `device_capture.json` and the `conftest.py` provenance note.
- `backend/tests/fixtures/hae/device_capture.json` verified present, parses as valid JSON,
  round-trips through the real `HAEPayload` + `normalize_payload` code producing exactly 12 rows
  with zero drops — checked directly, not assumed.
- The secret value appears in neither this SUMMARY, the setup doc, any tracked file, nor anywhere
  in the working tree at any point in this session. Every `gcloud secrets versions access` call
  that would have printed it to the transcript was blocked by the permission classifier and
  redirected to the user's own terminal instead.
- Live re-check: memory `1Gi`; `GET /health` -> `200`; `/.well-known/oauth-protected-resource/mcp`
  -> `200`; `alembic current` against production -> `0005 (head)`; a real device export ->
  `rows_upserted: 23, rows_skipped: 0`; a repeat export -> row count and `sum(sample_count)`
  unchanged at 23.
- `must_haves` status: both artifacts **satisfied**. All four `truths` satisfied, with Assumption
  A1's truth ("the exact string ... is known and recorded") satisfied as MOOT rather than as a
  confirmed spelling — recorded as such, not glossed over.
- `key_links` status: the documented Daily interval -> `normalize.py`'s
  `health_ingest_multi_point_day` link is now **observed**, not just written: two real exports
  with Daily aggregation confirmed active produced zero `multi_point_day` events.
- Full suite: 851 passed. `uv run pytest backend/tests/test_health_auto_export_normalize.py -k hevy`:
  17 passed, unchanged (no alias was added — see A1 above).
- No file deletions across any commit in this plan.

---
*Phase: 08-apple-health-nutrition-ingest*
*All three tasks completed: 2026-09-03.*
