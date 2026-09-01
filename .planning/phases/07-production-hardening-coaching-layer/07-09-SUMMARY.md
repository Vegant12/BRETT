---
phase: 07-production-hardening-coaching-layer
plan: 09
subsystem: infra
tags: [secret-manager, gcloud, cloud-run, workos, authkit, mcp-auth, secret-rotation, runbook]

# Dependency graph
requires:
  - phase: 07-production-hardening-coaching-layer
    provides: "plan 07-06's deployed revision and its 07-DEPLOY-RECORD.md, which deliberately deferred the authenticated curl-side 13-tool proof to this plan because authkit mode admits no curl-able credential"
  - phase: 07-production-hardening-coaching-layer
    provides: "plan 07-08's runbook structure (Preconditions / Procedure / Verification record / Known limitations), reused here verbatim as the sibling-runbook shape"
  - phase: 02-deploy-connector-auth-spike
    provides: "the brett-mcp-auth-secret Secret Manager secret, the MCP_AUTH_MODE lever in deploy/cloud-run.env.yaml, and scripts/deploy-cloud-run.sh's --set-secrets=:latest binding"
provides:
  - "A real, executed rotation of MCP_AUTH_SECRET: version 2 enabled and serving, version 1 disabled and recoverable, nothing destroyed"
  - "docs/runbook-secret-rotation.md — the D-03/D-04 procedure plus its first recorded execution, 14 verification rows, all PASS"
  - "The authenticated curl-side half of the 13-tool proof that 07-DEPLOY-RECORD.md split off — tools/list over an authenticated request against the serving revision"
  - "The first live exercise of the documented WorkOS-outage rollback path (authkit -> static -> authkit), proving it is a config flip and not a code change"
  - "Evidence for ROADMAP Phase 7 success criterion #3, second half: a secret rotated without breaking the live connector, confirmed by a human Claude round trip after both deploys"
  - "Two corrected operator commands (lowercase gcloud state rendering; application/json rather than text/event-stream on /mcp)"
affects: [disaster-recovery, deployment-runbooks, 07-10-coaching-uat, future-secret-rotations, mcp-auth-mode-changes]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "A secret rotation on Cloud Run is a DEPLOY procedure, not a `gcloud secrets` procedure — `--set-secrets=name:latest` resolves at instance start, so adding a version changes nothing until a revision serves traffic"
    - "The flip-back to the stronger auth mode is a verified step with two independent checks (live service read-back AND `git diff --quiet`), never a trailing note — the file can be right while the service is stale, and vice versa"
    - "Disable, never destroy: a disabled secret version is re-enablable for the retention period and is the only rollback if the new value turns out wrong"
    - "The old-401 and new-200 assertions are both required, and the 200 additionally asserts the exact 13-tool name set, so a 200 from a stale revision cannot pass"
    - "A human-verified checkpoint row is labelled as such in the artifact, and unobserved facts are recorded as 'not reported' rather than as 'did not happen'"

key-files:
  created:
    - docs/runbook-secret-rotation.md
  modified:
    - deploy/cloud-run.env.yaml

key-decisions:
  - "Recorded the two prescribed-command corrections in the runbook rather than silently fixing them, because each would waste the next operator's time mid-procedure while a production auth window is open"
  - "Recorded re-authorization as 'not reported by the tester' rather than 'not required' — the checkpoint did not ask for confirmation of an absence, and the distinction is a real diagnostic signal for the next rotation"
  - "Used status.url for operator curls while MCP_RESOURCE_URL keeps naming the deterministic host; both are in MCP_ALLOWED_HOSTS, and the resource_metadata= challenge correctly advertises the deterministic host regardless of arrival host"
  - "Disabled version 1 only after the flip-back was verified green, so the rollback credential survived the entire risk window"

patterns-established:
  - "A rotation drill doubles as a rollback drill: the same MCP_AUTH_MODE lever documented for a WorkOS outage is the one the rotation must flip, so exercising one exercises the other"
  - "Deferred proofs are named in the deferring artifact and closed by name in the closing artifact — 07-DEPLOY-RECORD.md assigned the curl half to this plan, and the runbook has a 'What row 7 actually closes' section pointing back"
  - "A runbook records the assumptions its source plan got wrong, by name, so the next operator does not rediscover them"

requirements-completed: [DEPLOY-03]

# Metrics
duration: 48m
completed: 2026-09-01
---

# Phase 7 Plan 9: MCP_AUTH_SECRET Rotation Summary

**`MCP_AUTH_SECRET` rotated for real against production — version 2 minted and serving, the old token proven dead with a `401` and the new one proven live with a `200` listing all thirteen tools, the service flipped `authkit` → `static` → `authkit` across two deploys and verified back off the live revision, version 1 disabled but recoverable, and a human Claude round trip confirming the connector never noticed.**

## Performance

- **Duration:** ~48m (including the human checkpoint wait)
- **Started:** 2026-09-01T12:10:00Z (approximate — pre-flight preceded the 12:17:26Z version add)
- **Completed:** 2026-09-01T12:58:00Z
- **Tasks:** 3 of 3
- **Files modified:** 2 (1 created, 1 modified — and the modified one nets to zero by design)

## Accomplishments

- **The rotation is real, not simulated.** `brett-mcp-auth-secret` version `2` was minted with `secrets.token_urlsafe(48)`, piped in via `--data-file=-`, and confirmed 64 bytes with no trailing newline. It is enabled and serving. Version `1` is `disabled`. Nothing is `destroyed`.
- **Old-401 / new-200 both hold, and the 200 carries the full tool set.** Against revision `brett-00008-rlg` in `static` mode: the old token returned `401` in 0.376 s, the new token returned `200` in 0.419 s listing exactly **13** tools whose sorted names matched the expected set item for item. Row A alone would have proven nothing; row B alone would have proven nothing; together they are the rotation.
- **The service ends where it started, verified twice over.** `MCP_AUTH_MODE` reads `authkit` off the *live* revision `brett-00009-fsm` (not off the file), and `git diff --quiet deploy/cloud-run.env.yaml` exits 0 against both the last commit and the pre-plan commit — byte-identical, not merely committed. These are two independent checks because the file can be right while the service is stale.
- **The static window is a bounded interval, written down as one.** The runbook carries a revision/mode/secret timeline table: window opens at `brett-00008-rlg`, closes at `brett-00009-fsm`, exactly two production deploys apart. After the flip-back, the new static token returned `401` with a body byte-identical (`cmp`) to the anonymous request's — the static path is verifiably out of the request path again.
- **The deferred 13-tool proof from 07-06 is closed.** `07-DEPLOY-RECORD.md` recorded the tool set from source registration and from a real Claude client but explicitly **not** from a `curl`, because in `authkit` mode no credential available to an agent can produce a `200` from `tools/list`. It called that a split, not an omission, and assigned the `curl` half to this rotation drill. Row 7 is that half — a third, independent line of evidence that the *serving* revision exposes 13 tools, obtained over an authenticated request rather than inferred from `add_tool` call sites.
- **The WorkOS-outage rollback path was exercised for the first time.** `deploy/cloud-run.env.yaml` has claimed since Phase 2 that rollback is "one value plus a redeploy, never a code change." That claim had never been executed. It is now, in both directions, with the fast suite gating each deploy.
- **The connector survived, confirmed by a human.** `fitness_ping` returned `status: ok` and `fitness_get_weekly_volume` for the last 2 weeks returned real data with `data_available: true`, taken after both deploys and after version 1 was disabled.
- **The architectural claim was stated plainly rather than dressed as risk.** In `authkit` mode `MCP_AUTH_SECRET` is not in the request path at all — Claude presents a WorkOS JWT. Rotating it is invisible to the connector. ROADMAP criterion #3's second half is satisfied by the architecture, and row 14 is the empirical check on that reasoning rather than the reason it is true.

## Task Commits

1. **Task 1: pre-flight, mint version 2, flip to `static`, deploy** — `1d37b6f` (chore)
2. **Task 2: old-401 / new-200 with the 13-tool list, flip back to `authkit`, disable version 1** — `0b4d9ea` (chore, the flip-back) and `f97c888` (docs, rows 6–13 and the disable)
3. **Task 3: human-verified connector round trip + the runbook** — `55e49ce` (docs)

**Plan metadata:** `<this commit>` (docs: complete plan)

Net file change across all four commits: `docs/runbook-secret-rotation.md` created (369 lines). `deploy/cloud-run.env.yaml` was modified twice and nets to zero, which is itself acceptance criterion 11.

## Files Created/Modified

- `docs/runbook-secret-rotation.md` — 369 lines. Redaction header; why rotation is a deploy procedure; why the mode flip is unavoidable; why rotation is invisible to the connector in `authkit` mode; five preconditions; a nine-step procedure with two named STOP conditions; the revision/mode/secret timeline; the 14-row verification record; "What row 7 actually closes"; the two corrected commands; the two-hostname note; four known limitations.
- `deploy/cloud-run.env.yaml` — `MCP_AUTH_MODE` flipped `authkit` → `static` → `authkit`. Ends byte-identical to its pre-plan state.

## Decisions Made

- **The two prescribed-command corrections are recorded, not silently fixed.** Both are in a titled runbook section. Each would cost the next operator time in the middle of a procedure that holds a production auth window open, and one of them (`grep -c ENABLED` → `0`) reads exactly like a *failed rotation* on a perfectly healthy secret — the worst possible false alarm at the worst possible moment.
- **Re-authorization is recorded as "not reported by the tester", not as "not required".** The checkpoint asked whether both calls succeeded and whether re-authorization was needed; the tester reported the successes and did not mention a prompt. The procedure never asked them to affirm its *absence*, so the record says what is known. The runbook explains why the distinction matters: an unprompted round trip is weak positive evidence that consent survived, not proof, and a consent prompt on a future rotation would be a signal that something other than `MCP_AUTH_SECRET` moved — issuer and `MCP_RESOURCE_URL` being the first two things to check.
- **Version 1 was disabled only after the flip-back verified green.** Ordering, not ceremony: disabling earlier would have destroyed the rollback credential while the risk window was still open.
- **`BASE` came from `status.url`, never retyped.** That returns the legacy hash host while `MCP_RESOURCE_URL` names the deterministic one. Both are in `MCP_ALLOWED_HOSTS`, and the `resource_metadata=` challenge still advertises the deterministic host regardless of arrival host — which is exactly what a connector needs, and worth a runbook note so it does not read as a bug next time.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] The plan's automated verify command `grep -c ENABLED` returns `0` against a healthy secret**
- **Found during:** Task 1 (the task's own `<verify><automated>` line)
- **Issue:** gcloud SDK 578.0.0 renders the secret-version `state` column **lowercase** — `enabled`, `disabled` — under both `--format='value(state)'` and `--format='table(name,state)'`. The plan's verification one-liner greps for uppercase `ENABLED`, matches nothing, and returns `0`. Read literally, that is a rotation that failed to produce an enabled version — the precise opposite of the truth, delivered at the moment an operator most needs a reliable signal.
- **Fix:** Used case-insensitive `grep -ci enabled`. Recorded the gotcha as a block quote inside the runbook's Step 2 so the next operator hits the warning before the command.
- **Files modified:** `docs/runbook-secret-rotation.md`
- **Verification:** Against a version list showing two enabled versions, `grep -c ENABLED` → `0` and `grep -ci enabled` → `2`
- **Committed in:** `f97c888`

**2. [Rule 1 - Bug] `/mcp` answers `application/json`, so the plan's SSE-stripping `sed` filter emits nothing**
- **Found during:** Task 2 (row B, the 13-tool count)
- **Issue:** The plan asserts the response is `text/event-stream` and pipes the body through `sed -n 's/^data: //p'` before parsing. Against this deployment the `content-type` on row 7 was `application/json` and the body was plain JSON-RPC, so the filter emitted nothing and the JSON parse failed on empty input. Left unfixed, the 13-tool assertion — the load-bearing half of the rotation proof and the half 07-06 deferred to this plan — simply could not be evaluated.
- **Fix:** Replaced the `sed` stage with a parser that tolerates both framings: it strips `data: ` prefixes only if the payload actually starts with `data:`, and parses directly otherwise. The tolerant version is what the runbook documents, since the framing may differ by SDK version or transport settings.
- **Files modified:** `docs/runbook-secret-rotation.md`
- **Verification:** The tolerant parser returned `13` and the exact expected sorted name list from the live `200` response
- **Committed in:** `f97c888`

---

**Total deviations:** 2 auto-fixed (2 bugs, both in commands the plan prescribed rather than in project code)
**Impact on plan:** Neither changed the plan's intent or scope; both were required to evaluate its own acceptance criteria. No project code was touched by this plan at all — `backend/` is untouched, and the only net repository change is one new document. No scope creep.

## Issues Encountered

- **The plan's central premise was correct and load-bearing.** 07-RESEARCH.md Pitfall 2's finding — that D-04's verification is unobservable in `authkit` mode because `StaticTokenVerifier` is never constructed — is exactly what happened. Without the mode flip, the new token would have returned `401` identically to the old one, and a "successful rotation" could have been recorded on the strength of two indistinguishable failures.
- **The IAM assumption held.** 07-RESEARCH.md A1 assumed `roles/secretmanager.secretAccessor` was bound at the *secret* level rather than per version. Pre-flight confirmed one binding at `version: 1` of the policy with no version-scoped condition, so both flip deploys started cleanly. Had it been per-version, the first deploy would have produced a revision that could not start.
- **The static window touched production twice.** Two real deploys, and an interval in which a single long-lived bearer was the whole of authentication. This is T-07-53, dispositioned `accept` in the plan's threat register, and it is bounded and documented rather than waved away. No coaching session was in progress.

## User Setup Required

None. Task 3 was a `checkpoint:human-verify` requiring a Claude client round trip, which the operator performed and reported; it establishes no repository file and no configuration beyond what already existed.

## Next Phase Readiness

- **ROADMAP Phase 7 success criterion #3 is now complete in both halves.** Plan 07-08 evidenced "a database backup restores into a fresh instance with no data loss"; this plan evidences "a secret can be rotated without breaking the live connector," with `docs/runbook-secret-rotation.md` as the artifact and a human-verified row 14 as the connector half.
- **The 13-tool set now has three independent lines of evidence** — source registration, a real Claude client (07-06), and an authenticated `curl` against the serving revision (row 7 here). The split 07-DEPLOY-RECORD.md opened is closed; nothing in Phase 7 is still waiting on it.
- **The next rotation is a procedure, not an investigation.** Nine steps, two STOP conditions, two corrected commands, and a known-limitations section that names the things nothing else will catch.
- **One standing caution, stated in the runbook rather than here:** nothing alerts on a service left in `static` mode. `test_auth_mode_is_a_valid_literal` checks that the value is *legal*, not that it is `authkit`. Rows 10 and 11 are the only guard, and they are operator discipline rather than automation. If a future phase wants to close that gap, this is where it starts.
- **Plan 07-10's coaching UAT can proceed against a service known to be on `authkit`** and a connector confirmed working as of `2026-09-01T12:5x`, with the deploy state recorded revision by revision.

## Threat Flags

None. This plan added no network endpoint, no auth path, no file-access pattern and no schema change. It exercised existing surface and produced one document. The trust-boundary interactions it did touch are all in the plan's own register and were dispositioned within it: T-07-47 (service left in `static`) closed by the verified flip-back, T-07-48 (token values) by never echoing, writing or recording either, T-07-49 (destroying the rollback) by `disable` rather than `destroy`, T-07-51 (a rotation that proves nothing) by requiring both the `401` and the `200`-with-13-tools, and T-07-54 (this document) by the redaction rule and its grep.

## Known Stubs

None. This plan produced no code and no placeholder values.

## Self-Check: PASSED

Claimed files exist on disk:

- `docs/runbook-secret-rotation.md` — FOUND (369 lines)
- `deploy/cloud-run.env.yaml` — FOUND, and `git diff --quiet` exits 0 against its pre-plan state

All four task commits exist in git: `1d37b6f`, `0b4d9ea`, `f97c888`, `55e49ce`. `git diff --diff-filter=D --name-only 6713652..HEAD` reports **no deletions** — nothing from a prior wave was removed. `git diff --stat 6713652..HEAD` shows exactly one file, `docs/runbook-secret-rotation.md`, +369.

Credential check: the plan's acceptance grep over `docs/runbook-secret-rotation.md` — a DSN scheme prefix, or a long credential-shaped value following a bearer scheme — returns **0** matches. (The literal pattern is spelled out in the plan's Task 3 acceptance criteria and is deliberately *not* reproduced here, so that a repo-wide credential sweep does not flag this summary on its own quoted regex.) Neither token value was echoed, written to a file, or recorded anywhere; both were `unset` at the end of Task 2. The only quantitative fact recorded about a token is its 64-byte length, which is a property of `secrets.token_urlsafe(48)` and not of the value.

Plan-level `<verification>` re-run at completion:

| # | Check | Result |
|---|---|---|
| 1 | `gcloud secrets versions list brett-mcp-auth-secret --format='table(name,state)'` | PASS — `2 enabled`, `1 disabled`, none destroyed |
| 2 | live `MCP_AUTH_MODE` off `gcloud run services describe` | PASS — `"value": "authkit"` |
| 3 | `git diff --quiet deploy/cloud-run.env.yaml` | PASS — exit 0 |
| 4 | `uv run pytest backend/tests -q -m "not integration"` | PASS — 401 passed, 286 deselected in 1.27s |
| 5 | Runbook exists, redacted, 14 rows incl. 13-tool count and human-verified round trip | PASS — 369 lines, 14/14 rows with non-empty Observed and explicit `**PASS**`, credential grep `0` |

Task 3 acceptance criteria re-checked individually after the row-14 edit: file exists and is ≥110 lines (369); contains `Redaction rule for this file:`; 14 rows each with a non-empty Observed cell and an explicit verdict; row 7 records `**13** tools`; row 10 records `authkit` read back off the live service; row 11 records an empty `git diff`; row 13 records version 1 `disabled` with `grep -ci destroyed` → `0`; row 14 records the human-verified round trip and the re-authorization status; the "Why the mode has to be flipped" section cites `MCP_AUTH_MODE: "authkit"` and `build_token_verifier`; the "Does rotation break the live connector?" section states the invisibility plainly; the credential grep returns `0`.

`STATE.md` and `ROADMAP.md` are untouched in this worktree, as required in parallel mode.

---
*Phase: 07-production-hardening-coaching-layer*
*Completed: 2026-09-01*
