---
phase: 08-apple-health-nutrition-ingest
plan: 03
subsystem: infra
tags: [rate-limiting, token-bucket, secret-manager, cloud-run, pydantic-settings, structlog, asgi-middleware]

# Dependency graph
requires:
  - phase: 07-production-hardening-coaching-layer
    provides: "TokenBucket + RateLimitMiddleware with per-request bucket resolution off app.state, and the whole-module grep guard that forbids reading client-supplied headers"
  - phase: 02-deploy-connector-auth-spike
    provides: "scripts/deploy-cloud-run.sh, deploy/cloud-run.env.yaml, and the env-file/secret-binding drift guards in test_cloud_run_deploy.py"
  - phase: 01-backend-foundation
    provides: "the three-layer FOUND-05 secret defense: SecretStr fields, _SECRET_FIELDS, and the structlog value scrubber built from Settings.secret_values()"
provides:
  - "Settings.health_ingest_secret (SecretStr | None), redacted by the existing log scrubber with no call-site discipline"
  - "Settings.ingest_rate_limit_per_minute / ingest_rate_limit_burst / ingest_max_body_bytes as readable, non-secret operational tuning"
  - "middleware.INGEST_PATH_PREFIX and build_ingest_limiter(), plus path-prefix bucket selection in RateLimitMiddleware._bucket"
  - "app.state.ingest_rate_limit_bucket, published beside its sibling in main.py"
  - "--memory=1Gi and the HEALTH_INGEST_SECRET Secret Manager binding in the deploy script"
  - "A structural guard against comments inside the backslash-continued gcloud invocation"
affects: [08-07-ingest-route, 08-08-deploy-and-secret-provisioning, health-auto-export-webhook, future-write-endpoints]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Second bucket, not second limiter: RateLimitMiddleware already resolves a bucket per request, so a new throttling domain is additive wiring rather than new dispatch logic"
    - "Path-prefix bucket selection with a fail-safe cascade — ingest bucket, then shared bucket, then constructor fallback; an unresolvable bucket is never an unlimited one"
    - "Deploy-script rationale lives above the invocation, never between continued lines"

key-files:
  created: []
  modified:
    - backend/app/config.py
    - backend/app/middleware.py
    - backend/app/main.py
    - scripts/deploy-cloud-run.sh
    - deploy/cloud-run.env.yaml
    - backend/tests/test_config.py
    - backend/tests/test_secret_redaction.py
    - backend/tests/test_rate_limit.py
    - backend/tests/test_cloud_run_deploy.py

key-decisions:
  - "The ingest path gets a dedicated token bucket, never an EXEMPT_PREFIXES entry — Health Auto Export's lack of retry argues for separation, not for leaving an internet-reachable write path unbounded on an --allow-unauthenticated service"
  - "health_ingest_secret is optional at boot: an unset credential means a DISABLED ingest path (fail-closed at request time), and production is guaranteed by the deploy-script binding assertion rather than by a boot-time raise that would break every developer and test environment"
  - "The ingest bucket ships with the same 30/30 numbers as the shared bucket — the point is separation, not a different limit"
  - "Deploy-script comments must sit above `exec gcloud run deploy`; a comment between continued lines truncates the command while `bash -n` still passes"
  - "HEALTH-07 is NOT marked complete by this plan — the credential and transport budget exist, but the authenticating receiver is plan 08-07"

patterns-established:
  - "Fail-safe bucket resolution: every unresolvable path in RateLimitMiddleware._bucket falls back to a real bucket, so the limiter's failure mode is 'throttled by the wrong bucket', never 'unthrottled'"
  - "Operational tuning numbers stay out of _SECRET_FIELDS deliberately, asserted by test — a plain number in the value scrubber redacts itself out of every unrelated log line"
  - "Structural (not textual) assertions on the deploy script where a text grep would pass on a broken file"

requirements-completed: []

# Metrics
duration: 20min
completed: 2026-09-02
---

# Phase 8 Plan 03: Ingest Endpoint Prerequisites Summary

**A dedicated `/api/v1/ingest/` token bucket that cannot drain the `/mcp` bucket, a `SecretStr` webhook credential the log scrubber already knows about, a 10 MiB pre-parse body budget, and a Cloud Run deploy at 1Gi with the credential bound from Secret Manager — all landed before the route that consumes them exists.**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-09-02T07:17:00Z
- **Completed:** 2026-09-02T07:37:00Z
- **Tasks:** 3 (all TDD, RED then GREEN)
- **Files modified:** 9

## Accomplishments

- **RESEARCH Pitfall 2 closed structurally.** `/api/v1/ingest/` draws from `app.state.ingest_rate_limit_bucket`, and `test_draining_the_ingest_bucket_leaves_the_shared_bucket_full` proves a burst of Health Auto Export deliveries leaves the bucket Claude's connector shares at full capacity. The prefix is deliberately absent from `EXEMPT_PREFIXES`, and a test fails if anyone adds it.
- **RESEARCH Pitfall 5 closed on the deploy side.** `--memory=1Gi` replaces the measured-too-small half-gigabyte request, asserted in both directions so neither a dropped flag nor a reinstated small one can pass review.
- **T-08-14 closed with no new mechanism.** `health_ingest_secret` joins `_SECRET_FIELDS`, which is the entire wiring: `Settings.secret_values()` feeds the structlog value scrubber, so the credential is redacted everywhere without any call-site discipline. A distinctive-value test goes red the moment the field leaves that tuple.
- **T-08-15 closed.** The credential is bound only through `--set-secrets` from Secret Manager; the existing credential-shaped-key guard keeps it out of `deploy/cloud-run.env.yaml`, and the partition test now *requires* the binding to exist.
- **A latent deploy-script hazard found and guarded** (see Deviations) — the plan's literal instruction would have shipped a script that deploys with no environment, no secrets and no memory setting, while `bash -n` reported it valid.
- **Full suite green: 700 passed** (687 at v1.0 close + the 13 added here), including the Postgres-backed integration half.

## Task Commits

Each task was committed atomically, RED gate then GREEN gate:

1. **Task 1: health_ingest_secret and the ingest tuning fields** — `0fb74e1` (test), `7dccdce` (feat)
2. **Task 2: dedicated ingest token bucket, selected by path prefix** — `830f449` (test), `d6ce766` (feat)
3. **Task 3: 1Gi memory and the HEALTH_INGEST_SECRET binding** — `6920d22` (test), `25cbb08` (feat)

No REFACTOR commits were needed — each GREEN implementation was the shape the plan specified.

## Files Created/Modified

- `backend/app/config.py` — `health_ingest_secret: SecretStr | None`, added to `_SECRET_FIELDS`; `ingest_rate_limit_per_minute`/`ingest_rate_limit_burst` (30/30) and `ingest_max_body_bytes` (10 MiB) as plain ints kept deliberately out of that tuple
- `backend/app/middleware.py` — `INGEST_PATH_PREFIX`, `build_ingest_limiter()`, and a `_bucket` that selects the ingest bucket by path prefix with a fail-safe fallback cascade
- `backend/app/main.py` — publishes `app.state.ingest_rate_limit_bucket` beside its sibling; the load-bearing `add_middleware` PREPEND ordering is untouched
- `scripts/deploy-cloud-run.sh` — `--memory=1Gi`, the third `--set-secrets` binding, and the rationale for both placed above the invocation
- `deploy/cloud-run.env.yaml` — the three quoted `INGEST_*` tuning keys; no credential
- `backend/tests/test_config.py` — 4 cases: masking + scrubber membership, optional-at-boot, the three defaults and their non-secret status, env overridability
- `backend/tests/test_secret_redaction.py` — the fourth per-secret case; `HEALTH_INGEST_SECRET` is now seeded for the whole module so the broader `secret_values()` scans see it too
- `backend/tests/test_rate_limit.py` — 6 ingest cases in the fast half, all against an injected clock
- `backend/tests/test_cloud_run_deploy.py` — the memory assertion, the extended required-binding tuple, `_deploy_script_text()`, and the new comment-placement guard

## Decisions Made

- **Separate bucket over exemption.** The pressure to exempt is real and documented (Health Auto Export has no retry, so a 429 is permanent data loss), but the ingest path is an internet-reachable *write* path on an `--allow-unauthenticated` service. Exempting it would make it the one unbounded surface in the process. Both halves are now asserted by test.
- **Same 30/30 numbers as the shared bucket.** The value delivered is separation, not a different limit; the factory test uses four deliberately distinct numbers so a factory reading the wrong settings pair cannot hide behind the identical shipped values.
- **`app/logging.py` DENY_KEYS was deliberately left alone.** Layer 2 (the key-name deny-list) exists to catch secrets Layer 3 has never heard of. Because `health_ingest_secret` *is* in `_SECRET_FIELDS`, Layer 3 already covers every configured value of it by content, so a `DENY_KEYS` entry would add no coverage — and `logging.py` is outside this plan's `files_modified`, which matters while sibling agents run concurrently.
- **HEALTH-07 was not marked complete and `REQUIREMENTS.md` was not touched.** HEALTH-07 reads "*the webhook receiver authenticates inbound requests … rejecting unauthenticated or mis-authenticated payloads*". This plan provisions the credential, the throttling domain and the body budget; the receiver that does the authenticating is plan 08-07. Marking it now would be a false completion claim. (It also avoids a three-way write to a shared file mid-wave.) **Action for the orchestrator: leave HEALTH-07 pending until 08-07 lands.**

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] The plan's comment placement would have silently broken the deploy script**

- **Found during:** Task 3 (deploy script edits)
- **Issue:** The plan instructed: *"Add a comment immediately above `--memory=1Gi`"*, inside the backslash-continued `exec gcloud run deploy` invocation. Backslash continuation is removed during tokenization, so the comment is joined onto the previous line, swallows the rest of that logical line, and the unescaped newline **ends the command**. The deploy would still run — but as `gcloud run deploy … --cpu-boost` with every flag below the comment dropped: no `--env-vars-file`, no `--set-secrets`, no `--memory`, no `--timeout`. Those lines would then be executed as separate shell commands and fail *after* a revision had already been deployed. Verified empirically in a scratch script: `bash -n` exits **0** and the truncated command runs, with `--three: command not found` following it. The plan's own verification step (`bash -n scripts/deploy-cloud-run.sh`) therefore could not have caught this.
- **Fix:** Moved the memory rationale, the secret-binding note and an explicit warning about this hazard into the comment block *above* `exec gcloud run deploy`. The flag list itself is now comment-free.
- **Files modified:** `scripts/deploy-cloud-run.sh`
- **Verification:** `bash -n` exits 0; all 15 cases in `test_cloud_run_deploy.py` pass; the flag list visually matches the intended invocation.
- **Committed in:** `25cbb08` (Task 3 commit)

**2. [Rule 2 - Missing Critical] Added a structural guard for that failure mode**

- **Found during:** Task 3, immediately after deviation 1
- **Issue:** Nothing in the repo could catch a recurrence. `bash -n` passes on the broken shape, and `test_deploy_script_carries_every_required_flag` greps the file as **text** — so every flag it looks for is still "present" in a script that no longer passes any of them. A prose warning alone would sit exactly where the next person is about to add another comment.
- **Fix:** Added `test_deploy_script_has_no_comment_inside_the_gcloud_call`, which walks from `exec gcloud run deploy` to the first line not ending in a backslash and fails on any comment line inside that block.
- **Files modified:** `backend/tests/test_cloud_run_deploy.py`
- **Verification:** Proved non-vacuous — the same detection logic run against a synthetic hazardous variant of the real script reports the injected comment, and reports nothing against the committed script.
- **Committed in:** `25cbb08` (Task 3 commit)

**3. [Rule 1 - Bug] Reworded the deploy-script comment so the plan's own acceptance greps hold**

- **Found during:** Task 3 verification
- **Issue:** The plan's action text and its acceptance criteria contradicted each other: the prescribed comment contains the strings `1Gi` and `512Mi`, but the criteria require `grep -c "\-\-memory=1Gi"` to return exactly **1** and `grep -c "512Mi"` to return **0**. Written literally, the comment made both criteria fail.
- **Fix:** Reworded the comment to *describe* the old and new values rather than spell them — the same device `backend/app/middleware.py` already uses for its grep-guarded names. `--memory=1Gi` now appears exactly once (as the flag) and `512Mi` not at all.
- **Files modified:** `scripts/deploy-cloud-run.sh`
- **Verification:** `grep -c "\-\-memory=1Gi"` → 1; `grep -c "512Mi"` → 0; `test_service_has_enough_memory_for_json_ingest` passes on both of its assertions.
- **Committed in:** `25cbb08` (Task 3 commit)

---

**Total deviations:** 3 auto-fixed (2 bug, 1 missing critical)
**Impact on plan:** No scope creep. Deviation 1 prevented shipping a deploy script that would have deployed a revision with no environment and no secrets; deviations 2 and 3 make that fix durable and reconcile the plan's internal contradiction. Every other instruction was executed exactly as written.

## Issues Encountered

- **The plan's env-file verification command needs a group flag.** `uv run python -c "import yaml…"` fails with `ModuleNotFoundError: No module named 'yaml'` because `pyproject.toml` sets `default-groups = []` and `pyyaml` lives in the dev group. `uv run --group dev python -c …` works and prints `10485760 30 30`. This is a property of the verification command, not of any committed file — no code change was made.
- **Worktree base correction.** The worktree branch was created from `b1d3eef` (v1.0 close) rather than the phase-8 planning HEAD. Hard-reset to `d688789` per the startup check, on a clean tree, before any work began.

## Known Stubs / Deliberately Unconsumed Surface

This plan builds prerequisites *ahead of* the route that uses them, exactly as its objective states. Two pieces therefore have no consumer yet — neither is an unfinished implementation:

| Item | Status | Resolved by |
|------|--------|-------------|
| `Settings.ingest_max_body_bytes` | Configured and tested; nothing reads it yet. The 413-before-parse enforcement point does not exist. | Plan 08-07 |
| `Settings.health_ingest_secret` | Configured, redacted and bound in the deploy; no comparison site exists yet, so nothing can currently fail closed on it. | Plan 08-07 |

`app.state.ingest_rate_limit_bucket` is **not** in this table — it is live and already selected by `RateLimitMiddleware` for any request under `/api/v1/ingest/`, whether or not a route answers it.

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: availability | `scripts/deploy-cloud-run.sh` | New surface not in the plan's register: a `#` comment between backslash-continued lines silently truncates `gcloud run deploy`, producing a deployed revision with no `--env-vars-file` and no `--set-secrets` while `bash -n` reports the file valid. Now mitigated by `test_deploy_script_has_no_comment_inside_the_gcloud_call`. Worth carrying into any future edit of a multi-line shell invocation in this repo. |

Threat register dispositions from the plan are otherwise all satisfied: T-08-11, T-08-12, T-08-13 (config half), T-08-14, T-08-15 and T-08-16 each have a passing assertion; T-08-17 was accepted and remains true — nothing added here reads a client-supplied header, and all three whole-module grep guards on `middleware.py` are clean.

## User Setup Required

**Deferred to plan 08-08, not actionable here.** The plan's `user_setup` block names a Google Secret Manager secret that must exist before `--set-secrets` can resolve at deploy time:

```
gcloud secrets create brett-health-ingest-secret
```

No live cloud action was taken by this agent (per the parallel-execution brief, this wave's `user_setup` belongs to 08-08). The deploy script now *references* `brett-health-ingest-secret:latest`; **until that secret exists in the project, `./scripts/deploy-cloud-run.sh` will fail at deploy time.** This is a hard ordering constraint between this plan and the next deploy, and is the single most important thing to carry forward from 08-03.

## Next Phase Readiness

Ready for plan 08-07 (the ingest route):

- Read the credential as `settings.health_ingest_secret` and compare in constant time; return a bare 401 when it is `None` so an unconfigured deployment is a disabled path
- Enforce `settings.ingest_max_body_bytes` **before** the JSON parse and answer 413
- The route must live under `/api/v1/ingest/` or it will silently draw from the shared `/mcp` bucket

Blockers/concerns:

- `brett-health-ingest-secret` must exist in Secret Manager before the next deploy (see User Setup Required)
- HEALTH-07 remains correctly pending in `REQUIREMENTS.md`

## Self-Check: PASSED

All nine modified files exist on disk and all six task commits are present in `git log`. Verified below.

---
*Phase: 08-apple-health-nutrition-ingest*
*Completed: 2026-09-02*
