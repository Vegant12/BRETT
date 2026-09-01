---
phase: 07-production-hardening-coaching-layer
plan: 06
subsystem: infra
tags: [cloud-run, gcloud, deployment, mcp, workos-authkit, oauth, rate-limiting, rfc9728, connector]

# Dependency graph
requires:
  - phase: 07-production-hardening-coaching-layer
    provides: "plan 07-01's RateLimitMiddleware and the RATE_LIMIT_* keys in deploy/cloud-run.env.yaml; plan 07-03's tool-surface work; plan 07-05's app-level middleware registration"
  - phase: 06-mcp-analytics-tools
    provides: "the twelve analytics tools registered in backend/app/mcp/server.py alongside fitness_ping"
  - phase: 02-deploy-connector-auth-spike
    provides: "scripts/deploy-cloud-run.sh, the brett Cloud Run service, WorkOS AuthKit authkit mode, both Secret Manager bindings, and 02-DEPLOY-LOG.md's evidence-record shape"
provides:
  - "Live Cloud Run revision brett-00007-xz7 serving 100% of traffic, built from commit b49f7c0"
  - "The deployed connector serves the real 13-tool set (was fitness_ping alone) - ROADMAP Phase 7 criterion #2"
  - "The rate limiter is live in production: RATE_LIMIT_PER_MINUTE=30, RATE_LIMIT_BURST=30"
  - "07-DEPLOY-RECORD.md: dated, redacted evidence for 8 anonymous rows plus a human-verified Claude round trip"
  - "A confirmed, dated statement that production holds NO training data, with the gap traced to plan 07-07"
affects: [07-07-sync-scheduling, 07-09-rotation-drill, 07-10-coaching-uat, deployment]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Concurrent burst, not a sequential loop, is the correct instrument for probing a token-bucket limiter over a network round-trip"
    - "Exemption rows are only meaningful when fired DURING a live burst with the burst process verified alive - otherwise they prove nothing"
    - "A live-service fact from a prior phase's log is re-read before use, never inherited from the plan's interfaces table"
    - "Human-verified checkpoint results are labelled as such in the record, distinct from claims inferred from source"

key-files:
  created:
    - .planning/phases/07-production-hardening-coaching-layer/07-DEPLOY-RECORD.md
  modified: []

key-decisions:
  - "The authenticated 13-tool proof is deliberately SPLIT (human checkpoint + plan 07-09's static-mode curl) rather than faked with a bearer curl that authkit mode must reject - the record says so explicitly so it does not read as an omission"
  - "Row 5's prescribed 40-request sequential loop was replaced with a concurrent burst after the sequential one produced zero 429s; the initial failure is recorded as a FAIL of the method, not rounded away"
  - "data_available: false is recorded as a FAIL against the plan's own criterion, then explained as a sequencing gap owned by plan 07-07 - the FAIL is not softened and the explanation is not used to erase it"
  - "scripts/deploy-cloud-run.sh was NOT fixed in this plan despite the --min regression it caused: changing the deploy script after the deploy would make this record describe a script that no longer exists"

patterns-established:
  - "Deploy-record redaction: credentials named only, plus an acceptance grep for DSN/Neon-host/long-Bearer patterns returning zero"
  - "Pre-deploy auth-mode gate (T-07-28): read MCP_AUTH_MODE off the live revision before deploying and abort if it reads the rollback value"
  - "An unproven must_have is carried forward as a named, dated open item against the plan that owns its prerequisite, rather than being marked complete or silently dropped"

requirements-completed: [DEPLOY-03]

# Metrics
duration: 45min
completed: 2026-09-01
---

# Phase 7 Plan 06: Cloud Run Redeploy Summary

**Cloud Run revision `brett-00007-xz7` replaces a Phase-2 revision that served one tool with one serving the real 13-tool set behind AuthKit OAuth and a live 30/min rate limiter, proven by 8 anonymous checks and a human-verified Claude round trip.**

## Performance

- **Duration:** ~45 min wall clock (including the blocking human checkpoint)
- **Started:** 2026-09-01T09:32:00Z (pre-flight suite)
- **Deployed:** 2026-09-01T09:39:33Z
- **Completed:** 2026-09-01T10:17:00Z
- **Tasks:** 3 (2 auto, 1 blocking human-verify checkpoint)
- **Files modified:** 1 created (`07-DEPLOY-RECORD.md`), 0 source files

## Accomplishments

- **ROADMAP Phase 7 criterion #2 is now true.** The deployed connector serves the real tool set. Before this plan the live revision was `brett-00006-sg2`, built during Phase 2, serving `fitness_ping` alone — exactly the gap 07-RESEARCH.md Pitfall 1 named. A real Claude client now enumerates **13** tools.
- **The rate limiter is live and proven in production**, not just in tests. A concurrent 120-request burst produced 89 × `429` with `Retry-After` and a byte-exact 24-byte `{"error":"rate_limited"}` body, while `/health` and the RFC 9728 discovery document stayed `200` at the same instant, from the same instance.
- **Exactly 31 requests admitted against a configured burst of 30**, reproduced across two independent bursts. That arithmetic simultaneously confirms the configured capacity, the refill rate, and that a single instance served the burst.
- **The auth wire contract survived the redeploy byte-identically.** The `WWW-Authenticate` challenge matches the string `02-DEPLOY-LOG.md` recorded against two earlier revisions, which is what lets Claude rediscover the resource without re-consent.
- **Three pre-deploy gates held**: 683 tests passing, ruff clean, mypy clean on 64 files — recorded before the deploy, not after.
- **T-07-28 discharged**: `MCP_AUTH_MODE` was read off the live revision *before* deploying (it read `authkit`, not the `static` rollback value) and re-read after.

## Task Commits

1. **Task 1: Pre-flight and redeploy the Cloud Run service** — `107a5bb` (chore)
2. **Task 2: Anonymous live verification matrix + 07-DEPLOY-RECORD.md** — `ae4780f` (docs)
3. **Task 3: Human-verified Claude client round trip** — `894eea9` (docs)

**Plan metadata:** this SUMMARY (docs)

## Files Created/Modified

- `.planning/phases/07-production-hardening-coaching-layer/07-DEPLOY-RECORD.md` — 535-line dated, redacted evidence record: pre-deploy gates, before/after revision table, full deployed environment read back off the serving revision, the 8-row anonymous matrix, the tool-set evidence split, the human-verified Claude round trip, 5 known limitations and 3 deviations.

No source files were changed. This plan deploys and records; it does not build.

## The one open item: `data_available: false`

**This is the only must_have this plan did not prove, and it is not a plan 07-06 defect.**

The human checkpoint asked a real Claude client to call `fitness_get_training_summary(weeks=4)`. It returned `data_available: false` with every field null or empty. Against the plan's own acceptance criterion ("A `data_available: false` is a FAIL for this checkpoint") this is recorded as a **FAIL**, unrounded, in `07-DEPLOY-RECORD.md`.

**Why it is expected rather than broken:**

1. The Secret Manager secret `brett-hevy-api-key` **does not exist** — `07-07-PLAN.md`'s own Interfaces section states the project holds `brett-database-url` and `brett-mcp-auth-secret` only. Without it, no process could have reached the Hevy API on production's behalf. The absence of production data is not merely unrecorded; it is currently *impossible* to have.
2. Phase 3's 327-workout live sync ran against **local** Postgres. `03-11-SUMMARY.md` explicitly states "production data loading (if any) is explicitly deferred to Phase 7".
3. **Plan 07-07 (wave 4) is precisely the plan that closes this** — it creates the secret, grants `brett-run@` the scoped accessor role, and runs the first production sync.

The tool behaved *correctly*: asked for a summary of an empty database, it returned the documented empty-state envelope rather than fabricating, erroring, or leaking an exception.

**Re-verification is scheduled, not hand-waved:** plan **07-07** must confirm `data_available: true` with non-empty `freshness.resources` and a populated `coverage` block after the first sync; plan **07-10**'s coaching UAT is a second hard gate that cannot pass while it is `false`.

A redeploy ships code and configuration. It cannot load data. Nothing this plan did wrong produced `false`, and nothing it could have done right would have produced `true`.

## Decisions Made

- **Split the authenticated tool proof rather than fake it.** With `MCP_AUTH_MODE=authkit`, `build_token_verifier` returns `AuthKitJWTVerifier`, so no `curl` this agent could construct can mint a WorkOS JWT. Rather than leave a silent gap, the record states *why* and splits the proof across Task 3's human checkpoint and plan 07-09's `static`-mode window. Source registration (13 `add_tool` targets) is recorded as a third, explicitly weakest line — it proves what was built, not what is served.
- **Recorded the sequential-burst failure instead of only the successful re-run.** The instrument was wrong; that is itself a finding worth carrying to the next runbook.
- **Did not fix `scripts/deploy-cloud-run.sh`.** Scope discipline — see Deferred Items.
- **Recorded re-authorization as "not reported" rather than resolving it either way.** The tester did not mention it. Silence is not evidence of absence.

## Deviations from Plan

### 1. [Rule 1 — method] Row 5's prescribed sequential burst cannot trip the limiter

- **Found during:** Task 2
- **Issue:** The plan prescribes "40 rapid POSTs … in a `for` loop". All 40 returned `401`; **zero** `429`. A sequential `curl` loop issues ~2.9 req/s, so the ~15–20 s loop let the bucket refill ~8–10 tokens against a capacity of 30 — effective supply ≈ 40 requests issued. **The prescribed burst sits exactly on the boundary rather than clearing it.**
- **Fix:** Replaced with a concurrent burst (120 requests, 30-way, 4.0 s — too fast to meaningfully refill): **89 × `429`, 31 × `401`, first 429 at request #31.** Reproduced on a second independent 200-request burst, also exactly 31 admitted.
- **Verification:** 31 admitted vs. `RATE_LIMIT_BURST=30` plus ~2 tokens refilled over 4 s. Every one of the 89 rejections carried an identical 24-byte body (`sort -u` returns one line).
- **Committed in:** `ae4780f`
- **Note:** Same class of finding as `02-DEPLOY-LOG.md` § *Row 7 required a different method than the plan prescribes*. The security property is real; the instrument was not sensitive enough. **A future runbook should specify a concurrent burst.**

### 2. [Documentation] The plan's stated starting revision was stale

- **Found during:** Task 1
- **Issue:** `07-06-PLAN.md`'s interfaces table records the live revision as `brett-00005-gcx`. It was actually **`brett-00006-sg2`** — `brett-00005-gcx` was the Stage A revision from plan 02-05, superseded by plan 02-07's AuthKit cutover.
- **Fix:** Read the real value off the live service before changing anything; documented at the top of the record.
- **Caught by:** the plan's own "re-confirmed, never assumed" instruction. The premise is unaffected (`brett-00006-sg2` also predates Phase 6 and served `fitness_ping` alone), but the "before" column names the revision that was actually serving.
- **Committed in:** `ae4780f`

### 3. [Rule 3 — blocking] The deploy silently reset `--min=1` to `--min=0`, undoing D-06f

- **Found during:** Task 1, comparing pre- and post-deploy service annotations.
- **Issue:** `scripts/deploy-cloud-run.sh` passes `--min="${BRETT_MIN_INSTANCES:-0}"` unconditionally. `BRETT_MIN_INSTANCES` was unset, so the deploy wrote `--min=0` over the service-scoped `--min=1` that plan 02-07 applied under D-06f. `02-DEPLOY-LOG.md` measured a real cold start at **7.53 s** against Claude's **10 s** discovery budget and called `--min=1` "a **hard prerequisite** for any Claude connector test" — and Task 3 *is* a Claude connector test.
- **Attempted fix:** `gcloud run services update brett --region=us-central1 --min=1` (pre-authorised by the developer on 2026-08-27). **Denied by the session's permission classifier.** The denial was respected rather than worked around.
- **Resolution:** Run by the orchestrator directly after the checkpoint, **not by this agent**. Independently verified by reading the live service back: `run.googleapis.com/minScale: "1"`, `maxScale: "2"`. The Task 3 round trip therefore ran with the cold-start guarantee in force and is not confounded by a scale-to-zero.
- **Committed in:** `894eea9` (the record of the resolution)

---

**Total deviations:** 3 (1 method correction, 1 documentation correction, 1 blocking-then-resolved config regression)
**Impact on plan:** None on scope. Deviation 1 strengthened the evidence rather than weakening it. Deviation 3 is the only one leaving residue, and it is carried as a deferred item.

## Deferred Items

1. **`scripts/deploy-cloud-run.sh` silently regresses `--min=1` on every deploy.** The script hardcodes `--min="${BRETT_MIN_INSTANCES:-0}"`, so **every** future redeploy will undo D-06f unless `BRETT_MIN_INSTANCES=1` is exported first. The durable fix is to default that variable to `1` (or read and preserve the current value). **Deliberately not fixed here** — plan 07-06's scope is the redeploy and its evidence record; editing the deploy script after the deploy would make the record describe a script that no longer exists. Flagged for a follow-up plan or a `/gsd-quick` fix. Until then, **any operator running that script must export `BRETT_MIN_INSTANCES=1` first.**
2. **Production data flow (`data_available: true`) is unproven** — owned by plan 07-07, re-gated by plan 07-10. See "The one open item" above.
3. **07-RESEARCH.md assumption A3 (consent survives redeploy) is unconfirmed** — the tester did not report whether Claude re-prompted for authorization. Circumstantially strong (both `MCP_RESOURCE_URL` and the RFC 9728 document are byte-identical to Phase 2's), but not settled. Plans 07-09 and 07-10 both re-attach a client and can settle it explicitly.

## Issues Encountered

- **The permission classifier denied a pre-authorised `gcloud run services update`.** Respected rather than worked around, matching the precedent `02-DEPLOY-LOG.md` set for its own denied secret read. Resolved out-of-band by the orchestrator.
- **5 of 200 requests in the second burst returned no status line.** Client-side connection failures under 40-way concurrency from a single laptop, not service responses. Recorded in the limitations so the tally reconciles (195 answered: 164 × `429` + 31 × `401`) rather than appearing to lose requests.
- **`status.url` reports the legacy hash hostname**, not the deterministic one. Same trap `02-DEPLOY-LOG.md` documents. Every verification row uses the deterministic host, because that is the host inside `MCP_RESOURCE_URL` and therefore the one Claude and WorkOS both match.

## Security Notes

- **T-07-27 (record leaks a credential):** discharged. The plan's three-alternative redaction grep — the Postgres DSN scheme, a Neon host prefix, and any long `Bearer` value; spelled verbatim in `07-06-PLAN.md`'s acceptance criteria, and deliberately **not** re-spelled here — returns **0** over the finished record. `MCP_AUTH_SECRET` and `DATABASE_URL` appear by name only. No `Authorization` header value and no training-data figures were recorded.
  - *Negative-space guard, same call plan 07-05 made:* this SUMMARY describes that grep rather than quoting it, because the pattern cannot distinguish a leaked DSN from a summary quoting the pattern that hunts for one. Spelling it here made the check flag this file on its own citation.
- **T-07-28 (deploy leaves the weaker rollback config):** discharged. `authkit` read before and after.
- **T-07-29 (wrong-project deploy):** discharged. `BRETT_GCP_PROJECT=brett-fitness` and the active account recorded pre-deploy.
- **T-07-30 (self-inflicted DoS):** accepted and bounded. Recovery ≈ 2 s, `/health` and discovery stayed `200` throughout, row 8 proved full refill at 90 s, and no coaching session was in progress.
- **T-07-31 (assuming the 13-tool claim):** discharged by the human checkpoint.
- **The server remains a non-oracle:** absent and malformed credentials are indistinguishable in both status and body (T-02-04), verified with `cmp` over the two saved bodies.

## Next Phase Readiness

**Ready:**
- Plan **07-07** (wave 4, sync scheduling) — its prerequisite is a live service with a working DB binding, which `brett-00007-xz7` provides. It is also the plan that closes this plan's one open item.
- Plan **07-09** (rotation drill) — the record documents both secret bindings surviving the redeploy, which is what keeps the rollback a configuration change rather than a code change. It also owes the second half of the tool-list proof.

**Blocked / gated:**
- Plan **07-10** (coaching UAT) cannot pass until 07-07 has run — it asks "Am I progressing?" against real synced data, and `data_available` is currently `false`.

**Carry forward:** export `BRETT_MIN_INSTANCES=1` before any future `scripts/deploy-cloud-run.sh` run, until Deferred Item 1 is fixed.

## Self-Check: PASSED

- `07-DEPLOY-RECORD.md` exists — 535 lines (plan requires ≥ 60), contains `Redaction rule for this file`, `human-verified` × 3, all 8 anonymous rows with explicit PASS/FAIL, and the `## Claude client round-trip (human-verified)` section.
- `07-06-SUMMARY.md` exists — 183 lines.
- Commits `107a5bb`, `ae4780f`, `894eea9` all present in `git log --all`.
- Redaction grep returns **0** on both artifacts.
- Live service re-read at record time: `latestReadyRevisionName = brett-00007-xz7`, `minScale = 1`, `maxScale = 2`.
- `.planning/STATE.md` and `.planning/ROADMAP.md` deliberately untouched — owned by the orchestrator.
- No file deletions in any commit (`git diff --diff-filter=D HEAD~1 HEAD` empty).

---
*Phase: 07-production-hardening-coaching-layer*
*Completed: 2026-09-01*
