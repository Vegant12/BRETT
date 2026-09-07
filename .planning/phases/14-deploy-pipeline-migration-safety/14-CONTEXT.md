# Phase 14: Deploy Pipeline Migration Safety - Context

**Gathered:** 2026-09-07
**Status:** Ready for planning

<domain>
## Phase Boundary

Fix `scripts/deploy-cloud-run.sh` (and only that pipeline) so a deploy against a database with
pending migrations can no longer silently ship code against a stale schema. This phase closes
the v2.0 operational debt (DEPLOY-04) that bit production three separate times (Phase 8: `0004`
vs `0005`; Phase 9 operator run: wrong `DATABASE_URL`; Phase 13 spike: `0005` vs `0006`,
`UndefinedTableError` on `user_program_history`). It does not touch physique feature work
(Phases 15-19) and does not change the sync job (`scripts/deploy-sync-job.sh`) beyond anything
this fix incidentally shares.

</domain>

<decisions>
## Implementation Decisions

All four decisions below were made by Claude on the user's explicit instruction ("go with your
recommendation or decision for all") rather than through individual back-and-forth — each is
still a locked decision for downstream agents, not an open question.

### Migration mechanism
- **D-01:** The script auto-applies migrations — it runs `alembic upgrade head` as an explicit
  pre-deploy step, not merely an abort-on-drift detector. Rationale: the recurring failure mode
  across all three v2.0 incidents was a human *forgetting* to migrate, not a lack of detection.
  An abort-only pre-flight still requires a human to remember a follow-up step; auto-applying
  removes that step entirely. This also matches the project's own original tech-stack guidance
  ("run `alembic upgrade head` in a pre-deploy command, not at app startup — startup migrations
  race across restarts").
- **D-02:** After running the upgrade, the script verifies success by asserting `alembic
  current` now matches `alembic heads` — a hard-fail check, not just trusting the upgrade
  command's exit code — so a partial or silently-incomplete apply still aborts before
  `gcloud run deploy` runs.

### Where the check lives
- **D-03:** The pre-flight/migration step is added directly inside `scripts/deploy-cloud-run.sh`,
  before the existing `exec gcloud run deploy` invocation — not a separate wrapper script a
  developer could forget to invoke. `deploy-cloud-run.sh` already documents itself as "the
  single reproducible description of how BRETT deploys" and is the file
  `backend/tests/test_cloud_run_deploy.py` already treats as canonical and tests against. A
  forgettable separate script would reproduce the exact "forgot a step" failure mode this phase
  exists to close.
- Preserve the existing `set -euo pipefail` behavior and the file's established comment
  conventions (rationale comments live ABOVE the command they explain — see the existing
  warning about comments breaking the backslash-continued `gcloud` invocation; the new
  alembic step must not repeat that mistake).

### Drift rehearsal method
- **D-04:** Prove the fix against a real drift scenario via an automated integration test, not a
  one-off manual runbook. Reuse the existing testcontainers + `alembic` fixture pattern already
  proven in `backend/tests/test_migrations.py` (`test_migrations_round_trip`,
  `test_no_pending_model_drift`): stand up a real Postgres container, downgrade it to a revision
  behind head, then exercise the same pre-flight logic the deploy script uses (extracted into a
  testable function/predicate rather than only inline shell, so it can be called directly from a
  test) and assert it detects the drift and would abort. This satisfies ROADMAP's "rehearsed
  against a real drift scenario ... not asserted only against fixtures" while staying a
  permanent regression test rather than a one-time manual exercise that proves nothing on the
  next change.
- The static assertion mirroring `_REQUIRED_FLAGS` (ROADMAP success criterion 3) stays in
  `backend/tests/test_cloud_run_deploy.py`; the drift-rehearsal integration test is a new,
  separate test (fast-suite static check vs. integration-marked container test — don't collapse
  the two into one test).

### DATABASE_URL sourcing
- **D-05:** The script fetches the production `DATABASE_URL` itself, via
  `gcloud secrets versions access latest --secret="brett-database-url"` (already the documented
  single source of truth per STATE.md), rather than trusting a pre-set shell environment
  variable. This directly closes the Phase 9 incident's actual cause — an operator's shell was
  pointed at the wrong `DATABASE_URL`, showing a stale before-state. Enforcing the fetch in code
  removes that failure mode instead of merely documenting the correct command for a human to
  remember to run.
- **D-06:** Keep an overridable escape hatch for local/non-prod testing, consistent with the
  script's existing convention for other values (`BRETT_GCP_PROJECT`, `BRETT_MIN_INSTANCES`,
  etc. are all `${VAR:-default}` or `${VAR:?required}` patterns) — e.g. `BRETT_DATABASE_URL` to
  override the fetched value when deliberately testing against a non-production database. The
  production path (no override set) must always resolve through the `gcloud secrets` fetch.

### Claude's Discretion
- Exact wording of abort/failure messages (should follow the existing style in
  `test_cloud_run_deploy.py`'s assertions: cite the requirement id, state what's wrong and why
  it's dangerous).
- Exact function/module boundary for the extracted pre-flight predicate (e.g., a small Python
  helper the test imports directly vs. a shell function the test shells out to) — planner's
  call, informed by which is easier to unit-test without a live `gcloud` binary.
- Whether the new integration test lives in `test_cloud_run_deploy.py` or a new sibling test
  file — planner's call based on how large the addition gets.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Deploy pipeline (this phase's primary surface)
- `scripts/deploy-cloud-run.sh` — the script this phase modifies; read in full before planning,
  including its existing comments (they document load-bearing gotchas, e.g. the
  comment-inside-backslash-continuation hazard)
- `backend/tests/test_cloud_run_deploy.py` — the canonical test file; the `_REQUIRED_FLAGS`
  guard pattern (lines ~54-64) is the pattern ROADMAP.md says to mirror for the new migration
  step assertion
- `scripts/deploy-sync-job.sh` — sibling script showing the project's established Cloud Run
  Job / secret-binding conventions (not modified by this phase, but shows the house style)

### Migrations
- `backend/alembic.ini`, `backend/migrations/env.py` — Alembic configuration
- `backend/migrations/versions/0006_user_program_history.py` — current head; this phase does not
  add a new migration (that's Phase 16's `0007`), only the safety mechanism around applying them
- `backend/tests/test_migrations.py` — existing testcontainers + `alembic` fixture pattern
  (`test_migrations_round_trip`, `test_no_pending_model_drift`) to reuse for the drift-rehearsal
  integration test

### Project context
- `.planning/PROJECT.md` — Key Decisions table entries for D-06 (Cloud Run migration) and the
  carried-forward deploy-migration debt description
- `.planning/REQUIREMENTS.md` — DEPLOY-04 (this phase) and DEPLOY-05 (Phase 19, proves this
  phase's fix works in production)
- `.planning/STATE.md` — Blockers/Concerns section documents the three prior incidents and the
  documented single source of truth for the production `DATABASE_URL`

No ADRs or external specs beyond the above — this is an internal operational-safety fix with no
new library or protocol surface.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `backend/tests/test_migrations.py`'s `alembic` and `engine` fixtures (from
  `backend/tests/conftest.py`) — real testcontainers Postgres already wired for upgrade/downgrade
  cycles; the drift-rehearsal test should reuse these rather than building new container
  plumbing.
- `test_cloud_run_deploy.py`'s existing helper style (`_deploy_script_text()`,
  `_secret_bindings()`, regex-based parsing of the script as text) — the new migration-step
  assertion should read as text like the others, never execute the script (running it would
  deploy).

### Established Patterns
- `scripts/deploy-cloud-run.sh` uses `${VAR:?required}` for must-be-set values and `${VAR:-default}`
  for overridable ones — the new `DATABASE_URL`-fetch override should follow this same shape.
- Every script-level gotcha in this file is documented as a comment ABOVE the command block it
  affects, never inside a backslash-continued invocation — a hard constraint, not a style
  preference (a comment inside the `exec gcloud run deploy \` continuation silently truncates
  the command, and `test_deploy_script_has_no_comment_inside_the_gcloud_call` already guards
  against a recurrence of that specific failure).
- `backend/app/cli.py` has no migration-related subcommand today — this phase does not need to
  add one; the migration step lives in the shell script, invoking `alembic` via its CLI directly
  (e.g. `(cd backend && uv run alembic upgrade head)`), consistent with how the script already
  shells out to `gcloud`.

### Integration Points
- The new pre-flight logic sits between the existing env/var setup at the top of
  `deploy-cloud-run.sh` and the existing `exec gcloud run deploy` block at the bottom — it must
  run and succeed before that `exec` line, and `set -euo pipefail` (already present) is what
  makes any failure inside it abort the whole script.

</code_context>

<specifics>
## Specific Ideas

No further specific implementation ideas beyond the four locked decisions above — the user
delegated the remaining implementation-shape choices to Claude's judgment.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope. No todos matched this phase
(`gsd-tools todo match-phase 14` returned zero matches).

</deferred>

---

*Phase: 14-deploy-pipeline-migration-safety*
*Context gathered: 2026-09-07*
