---
phase: 07-production-hardening-coaching-layer
plan: 08
subsystem: infra
tags: [neon, postgres, point-in-time-recovery, branching, psql, backup, runbook, sqlalchemy-metadata]

# Dependency graph
requires:
  - phase: 07-production-hardening-coaching-layer
    provides: "plan 07-07's production Hevy sync — the 327 workouts / 7,984 sets / 463 templates / 125 measurements that made this drill a comparison of real data rather than of an empty schema"
  - phase: 02-deploy-connector-auth-spike
    provides: "the Neon project `brett` and the brett-database-url secret whose DSN this plan deliberately never had to read"
  - phase: 03-hevy-integration-normalization
    provides: "the sync_state table, whose updated_at is what made a quiet --parent interval measurable rather than guessed"
provides:
  - "scripts/verify-restore.sql — a read-only nine-table count + whole-row md5 digest comparison, one UNION ALL arm per mapped table"
  - "backend/tests/test_verify_restore_sql.py — a fast-suite guard that reads the table inventory from Base.metadata, so a table added in a later phase cannot silently escape the restore proof"
  - "docs/runbook-backup-restore.md — the D-01/D-02 procedure, both drill and real-recovery variants, and the first recorded drill with 8 verified rows"
  - "A measured restore coverage claim: Neon free_v3, history_retention_seconds 21600 = exactly 6 hours"
  - "Evidence for ROADMAP Phase 7 success criterion #3 (first half): a branch from a past timestamp compared byte-for-byte against production across all nine tables"
affects: [07-09-verification, disaster-recovery, deployment-runbooks, future-migrations]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "A restore proof digests the WHOLE row (md5 of the row cast to text), not an identifier — a digest over ids alone passes just as happily over rows whose contents had rotted"
    - "Digest aggregates order on the uuid primary key, which is unique, NOT NULL and collation-free, so two byte-identical databases cannot disagree about the ordering"
    - "A comparison script pins session TimeZone/DateStyle, because row-to-text rendering of timestamptz is session-dependent and would otherwise report a false mismatch between a branch and its own parent"
    - "The table inventory for a drift guard is read from SQLAlchemy metadata at test time, never from a hand-kept tuple"

key-files:
  created:
    - scripts/verify-restore.sql
    - backend/tests/test_verify_restore_sql.py
    - docs/runbook-backup-restore.md
  modified: []

key-decisions:
  - "Aggregated md5(<row>::text) rather than the plan's md5(<identifier>) — the plan's own stated rationale ('an identical count over corrupted rows passes') argues for whole-row content, and an id-only digest would have had exactly the weakness the digest exists to remove"
  - "Ordered every aggregate on the uuid primary key rather than on external_id/measured_on — uuid comparison has no collation dependency and is unique-and-NOT-NULL on every one of the nine tables, whereas a text key's ordering can differ between databases"
  - "Chose --parent 2026-09-01T11:45:00Z from measured data (17 min after the newest sync_state write settled, all three rows idle) rather than from the plan's suggested '30-90 minutes ago', which would have landed within seconds of the last commit"
  - "Validated the SQL against a throwaway Postgres 17 container BEFORE the drill, including a positive control that a title-only change moves the digest while leaving count(*) unchanged — a syntax error discovered mid-drill would have burned a branch slot and the quiet interval"
  - "Used --no-secrets on branches create: it prints connection credentials by default and its output routinely lands in a transcript"
  - "Recorded the honest coverage as 'exactly 6 hours' with the framing 'recover from a bad sync you noticed today', never 'backed up'"

patterns-established:
  - "A drill is not finished until the artifact it created is deleted and the temp files are gone — both are numbered rows in the verification table, not afterthoughts"
  - "Non-destructiveness is measured, not argued: the digest query was re-run on production after the drill and compared against the pre-drill reading"
  - "A runbook records the assumptions the plan got wrong, by name, so the next operator does not rediscover them"

requirements-completed: [DEPLOY-03]

# Metrics
duration: 15m
completed: 2026-09-01
---

# Phase 7 Plan 8: Backup & Restore Verification Summary

**A Neon branch created from a timestamp 13 minutes in the past, proven byte-identical to production across all nine tables by whole-row md5 digest, confirmed to be a live Postgres 18.6 answering ad-hoc SQL, then deleted — plus a fast-suite guard that makes the next drill impossible to pass while silently skipping a table.**

## Performance

- **Duration:** 15m
- **Started:** 2026-09-01T11:48:32Z
- **Completed:** 2026-09-01T12:03:37Z
- **Tasks:** 3 of 3
- **Files modified:** 3 (3 created, 0 modified)

## Accomplishments

- **The drill passed on substance, not on a technicality.** `restore-drill-20260901T1159` was created from parent timestamp `2026-09-01T11:45:00Z` with its own compute endpoint, and `diff` of the digest query's output against production produced **no output at all** — all nine counts and all nine whole-row md5 digests matched. The branch answered `SELECT count(*) FROM workouts` → `327` and `version()` → `PostgreSQL 18.6`, which is what "restores into a fresh instance" actually means.
- **The digest was proven to detect content corruption before it was trusted.** Against a throwaway Postgres 17, a `title`-only change to one `workouts` row left `count(*)` at `1` and moved the digest from `a19b2503…` to `00d80b59…`. Two consecutive runs over unchanged data were byte-identical. This is the positive control that separates a real proof from a ritual.
- **Non-destructiveness was measured rather than asserted.** After the branch was deleted, `verify-restore.sql` was re-run on production: every count and every digest identical to the pre-drill reading. `branches create --parent` is non-destructive by construction, but "by construction" is an argument.
- **The coverage claim is a number read from the API, not a recollection.** `history_retention_seconds: 21600` — exactly 6 hours — on `subscription_type: free_v3`, confirming 07-RESEARCH.md assumption A2 by measurement. The runbook frames it as "recover from a bad sync you noticed today", explicitly not as "backed up".
- **The single manual-snapshot slot is confirmed unspent** (`snapshots list` → none), preserving it for a pre-migration moment per Open Question 3.
- **The drift guard reads its table list from `Base.metadata`**, so the nine-table coverage cannot rot. Phase 7 plan 07-07 already proved this failure class is real in this repo: eight tables existed in code and had never reached production while every health signal read green.
- **Two wrong assumptions the plan carried were caught and written down** rather than worked around silently — see Deviations.

## Task Commits

1. **Task 1: verify-restore.sql + its coverage guard** (TDD) — `9e35d4b` (test, RED: 4 failing), `88743da` (feat, GREEN: 4 passing). No refactor commit — the query needed none.
2. **Task 2: Neon API access** — no commit. Checkpoint, satisfied by the orchestrator; establishes no repository file by design.
3. **Task 3: run the drill, write the runbook** — `8fbdb8d` (docs)

**Plan metadata:** `<this commit>` (docs: complete plan)

## Files Created/Modified

- `scripts/verify-restore.sql` — 77 lines. Nine `UNION ALL` arms, one per mapped table, each `count(*)` plus `md5(string_agg(md5(x::text), ',' ORDER BY x.id))`. Pins session `TimeZone`/`DateStyle`. Header explains why each choice is load-bearing.
- `backend/tests/test_verify_restore_sql.py` — 190 lines, 4 tests, fast suite, no integration marker. Guards coverage (from `Base.metadata`), read-only-ness (over comment-stripped text), ordered aggregates (by paren-matched `string_agg` argument extraction), and absence of any credential-shaped string.
- `docs/runbook-backup-restore.md` — 268 lines. Measured coverage, six preconditions, Procedure A (drill) and Procedure B (real recovery), the 8-row verification record, the full side-by-side digest table, and eight known limitations.

## Decisions Made

- **The digest aggregates the whole row, not an identifier.** The plan's template digested `id::text` / `external_id`. But the plan's own justification for having a digest at all is that "an identical count over corrupted rows passes" — and a digest over identifiers alone passes over exactly those same corrupted rows. `md5(x::text)` covers every column, which is what the stated intent requires.
- **Every aggregate orders on the uuid primary key.** Ordering on a text column (`external_id`, `resource`) makes the result depend on the database's collation and is only unique because v1 has one user. The uuid PK is unique, `NOT NULL` and collation-free on all nine tables.
- **The `--parent` timestamp came from a query, not from the cron schedule.** Production's newest write of any kind was `sync_state.updated_at` at `11:27:41.241142Z` with all three rows `idle`; `11:45:00Z` sits 17 minutes after that and 13 minutes before the drill. The plan's suggested "30-90 minutes ago" would have been `~11:28Z` — within a second or two of that commit, and the digests would have differed for a reason that took explaining.
- **The SQL was validated against a real Postgres before the drill, not during it.** A throwaway container, the schema generated from SQLAlchemy metadata, and both a stability check and a corruption-detection check. A syntax error found mid-drill would have wasted a branch slot and the quiet interval.
- **`--no-secrets` on `branches create`.** That command prints connection credentials by default (`--secrets` defaults to `true`), and its output goes straight into the transcript.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] The plan's production branch name is wrong: it is `production`, not `main`**
- **Found during:** Task 3 (step 4, and confirmed in Task 2's recon)
- **Issue:** The plan's `<interfaces>` block and its step-4 command both name `main` (`$NEON connection-string main …`). The project's only branch is named `production` (id `br-floral-tooth-aydx74h7`). Every command written against `main` fails with a branch-not-found error.
- **Fix:** Used `production` throughout, and recorded the correction as a named entry in the runbook's Known limitations so the next operator does not repeat it.
- **Files modified:** `docs/runbook-backup-restore.md`
- **Verification:** `neonctl branches list` shows `[default] production` and nothing else; every command in the drill ran clean
- **Committed in:** `8fbdb8d`

**2. [Rule 3 - Blocking] `neonctl connection-string` refuses to run without `--database-name`, and the obvious guess is the wrong database**
- **Found during:** Task 3 (step 4, first attempt)
- **Issue:** The plan's step-4 commands have no `--database-name`. The branch carries two databases and neonctl exits with `ERROR: Multiple databases found for the branch … brett, neondb`. Worse than the error: the intuitive choice, `brett`, contains **zero** of the nine application tables — they all live in `neondb`. A drill pointed at `brett` would have compared two empty schemas, diffed them successfully, and been recorded as a **PASS**.
- **Why this is a genuine hazard and not a footnote:** it is a silent false negative on the one procedure whose entire purpose is detecting data loss — the precise failure mode T-07-44 exists to prevent, arriving through the connection string rather than through the query.
- **Fix:** Probed both databases for the nine tables before comparing anything (`brett` → 0, `neondb` → 9), passed `--database-name neondb` on every subsequent call, and gave the trap its own titled section in the runbook plus a Known-limitations entry.
- **Files modified:** `docs/runbook-backup-restore.md`
- **Verification:** Production returned 9 rows with real counts (327 workouts, 7,984 sets); an empty result would have been the symptom of the wrong database
- **Committed in:** `8fbdb8d`

**3. [Rule 2 - Missing Critical] The digest as specified would not have detected content corruption**
- **Found during:** Task 1
- **Issue:** The plan's arms digest a single identifier column per table (`id::text`, `external_id`, `measured_on::text`). Such a digest changes only when a row is added, removed or re-keyed — it is blind to a change in `weight_kg`, `reps`, `title`, `last_synced_at` or any other column. The plan's header comment simultaneously claims the digest exists because "an identical count over corrupted rows passes", which an id-only digest does not fix.
- **Fix:** Aggregate `md5(x::text)` — the whole row, every column — ordered by the primary key. Added two supporting guarantees the plan did not specify: `SET TimeZone`/`SET DateStyle` at the top of the file, because `<row>::text` renders `timestamptz` according to session GUCs and two psql sessions with differing settings would otherwise report a false mismatch.
- **Files modified:** `scripts/verify-restore.sql`
- **Verification:** Positive control on a throwaway Postgres 17 — a `title`-only `UPDATE` left `count(*)` at 1 and changed the `workouts` digest; two runs over unchanged data were byte-identical
- **Committed in:** `88743da`

**4. [Rule 2 - Missing Critical] `branches create` prints connection credentials by default**
- **Found during:** Task 3 (step 3, from reading `branches create --help`)
- **Issue:** The plan's step-3 command has no `--no-secrets`, and neonctl's `--secrets` flag defaults to `true` — "Include connection credentials in command output". The plan's own threat model (T-07-41) forbids exactly this, but its command would have printed a full-access DSN into the transcript.
- **Fix:** Passed `--no-secrets`. Both DSNs were obtained separately via `connection-string` into shell variables, and their presence was confirmed by printing `${#VAR}` — a character count, never a value.
- **Files modified:** `docs/runbook-backup-restore.md` (the corrected command is what the procedure now documents)
- **Verification:** The create output contains only branch name, id, state, timestamp and an endpoint id — no credential
- **Committed in:** `8fbdb8d`

---

**Total deviations:** 4 auto-fixed (1 bug, 1 blocking, 2 missing-critical)
**Impact on plan:** Two were required to complete the plan at all — the drill could not connect with the plan's branch name, and could not connect at all without `--database-name`. The other two would each have produced a plan that *appeared* to succeed while failing at its actual purpose: a digest blind to corruption, and a credential in the transcript. No scope creep; all three files are exactly the three the plan names, and nothing outside `scripts/`, `backend/tests/` and `docs/` was touched.

## Issues Encountered

- **Neon's API session came from `neonctl`'s cached browser OAuth (`~/.config/neon`), not from `NEON_API_KEY`.** Functionally equivalent for every command this plan runs, but it means the plan's precondition ("`NEON_API_KEY` exported") describes only one of two working paths. The runbook documents both rather than pretending the key was used. `git grep -c NEON_API_KEY -- ':!*.md' ':!.planning'` returns zero matches either way.
- **The `exercise_muscle_overrides` digest is NULL on both sides** because the table has zero rows and `string_agg` over no rows returns NULL. This is correct and identical on both branches, so it diffs clean — but it is worth knowing that an empty table contributes a blank digest cell rather than a hash of nothing.
- **No `refactor` commit exists for the TDD task.** The GREEN implementation needed no cleanup; per the TDD flow, a refactor commit is made only if changes are actually made.

## User Setup Required

None. Task 2 was a `checkpoint:human-action` for Neon API access, satisfied before execution began; it establishes no repository file by design and required no further human input.

## Next Phase Readiness

- **ROADMAP Phase 7 success criterion #3, first half is now evidenced** — "a database backup restores into a fresh instance with no data loss" was demonstrated against the real project, with the digest table as the artifact. Plan 07-09's verification can cite `docs/runbook-backup-restore.md` rather than re-deriving it.
- **The 6-hour window is now a written, measured constraint** rather than an assumption, and it is the single most consequential limitation in the deployment. Any future work that considers longer-horizon recovery starts from a number.
- **The next drill is protected against the most likely way it could go wrong.** A schema migration that adds a table now fails `backend/tests/test_verify_restore_sql.py` in the fast suite on the commit that introduces it, rather than producing a clean-looking drill that skipped the new data.
- **One standing caution:** this record ages silently. The fast suite catches the SQL drifting from the models, but nothing catches the *drill* going stale. The runbook says to re-run it after any migration; nothing enforces that.
- **Branch budget is clean:** the project is back to exactly one branch of ten, and the manual-snapshot slot remains unspent.

## Threat Flags

None. This plan added no network endpoint, no auth path, no file-access pattern and no schema change. The one new trust-boundary interaction — a temporary branch holding a copy of real health data — is the subject of T-07-40 and was disposed of within the plan: created at `11:58:32Z`, deleted before the plan ended, absence verified by `branches list`.

## Self-Check: PASSED

All three claimed files exist on disk:

- `scripts/verify-restore.sql` — FOUND (77 lines)
- `backend/tests/test_verify_restore_sql.py` — FOUND (190 lines)
- `docs/runbook-backup-restore.md` — FOUND (268 lines)

All three task commits exist in git: `9e35d4b`, `88743da`, `8fbdb8d`. `git diff --diff-filter=D c44e850..HEAD` reports **no deletions** — nothing from a prior wave was removed.

Credential check: `grep -Ec "postgresql://|ep-[a-z0-9-]+\.|NEON_API_KEY="` returns **0** for `docs/runbook-backup-restore.md`, and the same patterns are asserted absent from `scripts/verify-restore.sql` by a test that runs in the fast suite. No DSN was ever echoed, written to a file, or passed anywhere except as a quoted shell variable. `gcloud secrets versions access` was never invoked.

Plan-level `<verification>` re-run at completion:

| # | Check | Result |
|---|---|---|
| 1 | `uv run pytest backend/tests/test_verify_restore_sql.py -x -q` | PASS — 4 passed |
| 2 | `uv run pytest backend/tests -x -q -m "not integration"` | PASS — 401 passed, 286 deselected |
| 3 | `diff /tmp/prod.txt /tmp/drill.txt` | PASS — identical, no explained difference needed |
| 4 | `neonctl branches list` shows no `restore-drill-*` | PASS — one branch, `[default] production` |
| 5 | Runbook exists, redacted, 8 verified rows, measured window | PASS — 268 lines, 8/8 rows with non-empty Observed and explicit verdict, `21600` seconds recorded |

`STATE.md` and `ROADMAP.md` are untouched in this worktree, as required in parallel mode.

---
*Phase: 07-production-hardening-coaching-layer*
*Completed: 2026-09-01*
