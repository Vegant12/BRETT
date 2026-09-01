# Runbook — Backup & Restore (Neon)

First executed: 2026-09-01
Mechanism: Neon point-in-time recovery via branch-from-timestamp (D-01). There is deliberately
no `pg_dump`/`pg_restore` path in this repo.
Owner artifacts: `scripts/verify-restore.sql`, guarded by
`backend/tests/test_verify_restore_sql.py`.

**Redaction rule for this file:** no credential value is ever recorded. Connection strings are
referred to as `$PROD_DSN` / `$DRILL_DSN` and never written out; the Neon API key is named only,
never assigned; no compute endpoint hostname appears below. The md5 digests recorded here are
hashes of row content, not the content itself, and are one-way.

## What is actually covered

Measured, not assumed — `neonctl projects get lively-bread-92140092` reports:

| Property | Measured value |
|---|---|
| Project | `brett`, id `lively-bread-92140092`, region `aws-us-east-2`, Postgres 18 |
| Plan | **Free** (`owner.subscription_type: free_v3`) |
| `history_retention_seconds` | **21600 — exactly 6 hours** |
| `owner.branches_limit` | 10 |
| Production branch | `production`, id `br-floral-tooth-aydx74h7` — the **default** branch and a root branch |

**The honest coverage claim is six hours.** That is "recover from a bad sync, a bad migration or
a bad `DELETE` that you noticed today". It is **not** "the data is backed up". There is no
copy of this database from last week, and there is no way to obtain one after the fact — a
`--parent` timestamp older than the window is rejected outright, not silently rounded up.

This bounds what any incident response can achieve. If a corruption is introduced and not
noticed within six hours, the corrupted state is the only state that exists.

Confirmed by measurement on 2026-09-01: `neonctl snapshots list --branch production` returns
**no snapshots**. The Free plan's single manual-snapshot slot is therefore **unspent, and
deliberately so** (07-RESEARCH.md Open Question 3) — it is reserved for a "before a risky
migration" moment, which is precisely the situation the 6-hour window handles worst. A drill
does not need it and must not consume it.

### The database-name trap — read this before running anything below

The production branch carries **two** databases: `neondb`, which holds all nine application
tables, and `brett`, which holds **none** (it is an unused leftover from project creation).

`neonctl connection-string` refuses to guess and exits with
`ERROR: Multiple databases found for the branch, please provide one with the --database-name
option: brett, neondb`. Every command below therefore passes `--database-name neondb`
explicitly.

This matters more than an ergonomics note. Pointing the comparison at `brett` on both sides
would compare two empty schemas, `diff` them successfully, and record a **PASS** — a perfect
false negative on the one procedure whose entire purpose is detecting data loss.

## Preconditions

1. Authenticated Neon CLI access to the project, by **either** path:
   - a cached browser OAuth session under `~/.config/neon` (what this drill actually used), or
   - a personal API key exported as the `NEON_API_KEY` environment variable.

   The key, if used, is exported in the shell and lands in no file — never `.env`, never
   `deploy/`, never anything committed. `backend/tests/` and the repo at large are checked:
   `git grep -c NEON_API_KEY -- ':!*.md' ':!.planning'` returns zero matches.
2. `npx` available — the Neon CLI is deliberately **not** installed globally. Every command
   below is written as `npx --yes neonctl@latest …`.
3. `psql` available (verified at v18.6 against the server; the client was v18.6 locally).
4. Fewer than 10 branches on the project. Check first: `neonctl branches list`.
5. The manual-snapshot slot is deliberately **UNSPENT**. Keep it for a pre-migration moment,
   not for a drill.
6. The `--parent` timestamp is inside the 6-hour window **and** in a quiet interval. The sync
   job (`docs/runbook-sync-schedule.md`) fires on `0 */6 * * *` `Asia/Jakarta` — 17:00, 23:00,
   05:00 and 11:00 UTC. A timestamp that straddles a sync produces a legitimate digest
   difference, which is not a failure but must be explained rather than recorded as a FAIL.

## Procedure A — the drill (non-destructive, safe to repeat)

Set up once per session:

```bash
NEON="npx --yes neonctl@latest"
PROJECT_ID="lively-bread-92140092"
```

**1. Confirm the plan tier and the history window.** Never inherit last drill's numbers; the
coverage claim must be measured each time.

```bash
$NEON projects get "$PROJECT_ID" --output json    # read history_retention_seconds, subscription_type
$NEON branches list --project-id "$PROJECT_ID"    # confirm the count is well under 10
```

**2. Pick a `--parent` timestamp inside the window and outside a sync.** Read the last write
directly rather than guessing at the cron schedule:

```bash
PROD_DSN="$($NEON connection-string production --project-id "$PROJECT_ID" --database-name neondb)"
psql "$PROD_DSN" -c "SELECT resource, status, updated_at FROM sync_state ORDER BY resource;"
```

Every row `idle` means no sync is in flight. Choose a timestamp comfortably **after** the
newest `updated_at` and comfortably **before** now. Record the timestamp and the reasoning.

**3. Create the drill branch (non-destructive).**

```bash
DRILL_BRANCH="restore-drill-$(date -u +%Y%m%dT%H%M)"
$NEON branches create --project-id "$PROJECT_ID" \
      --name "$DRILL_BRANCH" --parent "<RFC3339 timestamp>" --no-secrets
```

`--no-secrets` matters: `branches create` prints connection credentials by default, and this
command's output routinely ends up in a transcript or a scrollback buffer.

**4. Get both connection strings into shell variables — never into a file, never echoed.**

```bash
PROD_DSN="$($NEON connection-string production    --project-id "$PROJECT_ID" --database-name neondb)"
DRILL_DSN="$($NEON connection-string "$DRILL_BRANCH" --project-id "$PROJECT_ID" --database-name neondb)"
```

Do **not** run `gcloud secrets versions access latest --secret=brett-database-url`. `neonctl
connection-string` supplies both DSNs, so the Secret Manager value never has to be printed at
all. To confirm the variables are populated without revealing them, print `${#PROD_DSN}` — a
length, not a value — and assert the two differ.

**5. Compare.**

```bash
psql "$PROD_DSN"  -f scripts/verify-restore.sql > /tmp/prod.txt
psql "$DRILL_DSN" -f scripts/verify-restore.sql > /tmp/drill.txt
diff /tmp/prod.txt /tmp/drill.txt && echo "IDENTICAL"
```

Copy the table of counts and digests into a new verification record. Digests are md5 hashes,
one-way and safe to commit. The DSNs are not, and never appear.

**6. Prove the branch is a working database, not just a row dump** — this is what "restores
into a fresh instance" means:

```bash
psql "$DRILL_DSN" -c "SELECT count(*) FROM workouts;"
psql "$DRILL_DSN" -c "SELECT version();"
```

**7. Delete the drill branch. The drill is not finished until this runs.**

```bash
$NEON branches delete "$DRILL_BRANCH" --project-id "$PROJECT_ID"
$NEON branches list --project-id "$PROJECT_ID"     # confirm it is gone
rm -f /tmp/prod.txt /tmp/drill.txt
```

A branch left behind is a second, unmonitored copy of real health data with its own connection
string, and it permanently consumes one of ten branch slots. The two comparison files hold row
counts over real health data and have no reason to survive the session.

## Procedure B — a real recovery

**Do not run this in a drill.** It is here so that, during an actual incident, nobody has to
work out the command under pressure.

```bash
$NEON branches restore production "^self@<RFC3339 timestamp>" --project-id "$PROJECT_ID"
```

What it does, and why it is reserved for an incident:

- It is an **in-place, complete overwrite** of the target branch — Neon's own wording is "a
  complete overwrite, not a merge". Any data written to `production` after the chosen timestamp
  is gone from `production`.
- It is not quite destructive: the pre-restore state is preserved as a new branch named
  `{branch}_old_{timestamp}`. That backup branch **consumes a branch slot**, so the ten-branch
  limit is a live concern during an incident, not a theoretical one. Delete it once the
  recovery is confirmed good.
- **No redeploy is required afterwards.** `DATABASE_URL` (in Secret Manager as
  `brett-database-url`) addresses the branch by name, so an in-place restore is transparent to
  Cloud Run and to the Cloud Run sync job. Neither needs to be touched.
- Restoring is only possible **from a root branch**. `production` is the default branch and a
  root branch, so this is satisfied by default — but a restore of a child branch is not.

Before running it in anger, consider spending the manual snapshot slot on the current
(damaged) state first. Once the overwrite happens, the 6-hour window is the only way back, and
the clock on it started when the damage did.

## Verification record — 2026-09-01

The drill branch was `restore-drill-20260901T1159` (id `br-long-poetry-ay59576q`), created at
`2026-09-01T11:58:32Z` from parent timestamp **`2026-09-01T11:45:00Z`**.

Why that timestamp: production's newest write of any kind was `sync_state.updated_at` at
`2026-09-01T11:27:41.241142Z`, and all three `sync_state` rows read `idle`. `11:45:00Z` sits 17
minutes after that write settled and 13 minutes before the drill began, inside the 6-hour
window, and roughly five hours before the next scheduled sync at `17:00Z`. It is therefore a
genuinely quiet interval, and the expected result was an exact match rather than an explained
difference.

| Row | Check | Expected | Observed | Pass/Fail |
|---|---|---|---|---|
| 1 | plan tier and history window (`projects get`) | a measured number, not "backed up" | `subscription_type: free_v3` (Free); `history_retention_seconds: 21600` = exactly 6 h; `branches_limit: 10`; branch count before the drill: **1** | **PASS** |
| 2 | branch created from `2026-09-01T11:45:00Z` | new branch, own DSN, production untouched | Branch `restore-drill-20260901T1159` reached state `ready` with its **own compute endpoint**. `$PROD_DSN` and `$DRILL_DSN` were asserted to differ (140 chars each, values never printed). After the drill, `verify-restore.sql` was re-run on production: all 9 counts and all 9 digests **identical to the pre-drill reading** — the branch operation wrote nothing to production | **PASS** |
| 3 | `verify-restore.sql` on production | 9 rows | 9 rows returned; counts `users 1`, `workouts 327`, `workout_exercises 2239`, `workout_sets 7984`, `exercise_templates 463`, `exercise_muscles 1147`, `exercise_muscle_overrides 0`, `body_measurements 125`, `sync_state 3` | **PASS** |
| 4 | `verify-restore.sql` on the drill branch | 9 rows | 9 rows returned, same nine table names, same nine counts (full digests in the table below) | **PASS** |
| 5 | `diff` of the two outputs | identical | `diff /tmp/prod.txt /tmp/drill.txt` produced **no output** and the script printed `IDENTICAL`. All nine counts **and** all nine whole-row md5 digests matched | **PASS** |
| 6 | drill branch answers `SELECT count(*) FROM workouts` and `version()` | a working database | `count` → `327`. `version()` → `PostgreSQL 18.6 (c5250a2) on aarch64-unknown-linux-gnu, compiled by gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0, 64-bit`. A live server answering ad-hoc SQL, not an export | **PASS** |
| 7 | drill branch deleted, branch list clean | gone | `branches delete` returned the branch in state `ready`; the follow-up `branches list` shows exactly one row, `[default] production  br-floral-tooth-aydx74h7`. No `restore-drill-*` branch remains | **PASS** |
| 8 | `/tmp/prod.txt` and `/tmp/drill.txt` removed | gone | `ls` reports `No such file or directory` for both | **PASS** |

### Digest comparison

Both branches, side by side. `n` is `count(*)`; `digest` is
`md5(string_agg(md5(<whole row>::text), ',' ORDER BY <pk>))`.

| Table | production `n` | production `digest` | drill `n` | drill `digest` | Match |
|---|---|---|---|---|---|
| `body_measurements` | 125 | `ff2203e11e5394d3b5237ba4ceca891f` | 125 | `ff2203e11e5394d3b5237ba4ceca891f` | ✅ |
| `exercise_muscle_overrides` | 0 | *(null — no rows)* | 0 | *(null — no rows)* | ✅ |
| `exercise_muscles` | 1147 | `2f0a274deb9730c73c64e342ed45d743` | 1147 | `2f0a274deb9730c73c64e342ed45d743` | ✅ |
| `exercise_templates` | 463 | `3d33dea48c67e4a4e60a61deffcfcfc0` | 463 | `3d33dea48c67e4a4e60a61deffcfcfc0` | ✅ |
| `sync_state` | 3 | `a67b71fb546f8adda19e98afb0fb0d06` | 3 | `a67b71fb546f8adda19e98afb0fb0d06` | ✅ |
| `users` | 1 | `bf3c2db954948f6223eab87a9ef07a9d` | 1 | `bf3c2db954948f6223eab87a9ef07a9d` | ✅ |
| `workout_exercises` | 2239 | `963f3ea25b06b31a8364adf5cc3e69e9` | 2239 | `963f3ea25b06b31a8364adf5cc3e69e9` | ✅ |
| `workout_sets` | 7984 | `8fedc45f31876ef08e357f3b27b5fc49` | 7984 | `8fedc45f31876ef08e357f3b27b5fc49` | ✅ |
| `workouts` | 327 | `b057d5cf1a207fcbad73fa5dce6d4801` | 327 | `b057d5cf1a207fcbad73fa5dce6d4801` | ✅ |

The counts corroborate independent records: 327 workouts, 463 templates and 125 body
measurements are exactly what plan 07-07's first production sync reported, and 7,984
`workout_sets` matches the figure recorded in `backend/app/db/models/exercise.py`. An
`exercise_muscle_overrides` count of 0 is correct — no manual override has ever been entered.

### Why the digest is not a ritual

A row count alone would have passed this drill even if every row's contents had been replaced.
The digest was checked against that specific failure on a throwaway Postgres 17 before the drill
ran: with one `workouts` row present, a `title`-only change left `count(*)` at `1` and moved the
digest from `a19b2503…` to `00d80b59…`. Two consecutive runs over unchanged data produced
byte-identical output.

That property depends on two things `backend/tests/test_verify_restore_sql.py` enforces on every
commit: an explicit `ORDER BY` inside each `string_agg` (without one Postgres defines no order,
and the same database can digest differently twice), and an arm for every table on
`Base.metadata` (a table nobody compares is a silent gap in the proof).

## Known limitations

- **The 6-hour history window bounds everything.** A `--parent` timestamp older than the window
  is rejected; there is no fallback and no older copy. Damage not noticed within six hours is
  permanent. This is the single most important line in this document.
- **There is no `pg_dump` path, by decision (D-01).** The upside is that nothing has to be
  scheduled, monitored or stored; the downside is that the coverage is exactly Neon's retention
  window and not one second more. If long-horizon recovery ever becomes a requirement, that is a
  new mechanism, not a tuning of this one.
- **Restoring is only possible from a ROOT branch.** `production` qualifies. A child branch does
  not, which matters if the topology ever grows.
- **This drill was run once, by hand, on 2026-09-01. It is not in CI (D-02) and will not tell
  you it has gone stale.** Re-run it after any schema migration — a migration is precisely the
  event that adds a table, and a table absent from `scripts/verify-restore.sql` is a table the
  next drill silently does not compare. The fast-suite guard catches the SQL drifting from the
  models, but nothing catches this *record* ageing.
- **The production branch is named `production`, not `main`.** Plan 07-08 and several Neon docs
  examples assume `main`; commands written against that assumption fail with a branch-not-found
  error. Prefer `neonctl branches list` over memory.
- **Both databases on the branch answer connections; only `neondb` has data.** See the trap
  above. A drill pointed at `brett` compares nothing and reports success.
- **The Free plan's 10-branch limit is a real constraint during an incident**, because a real
  restore *creates* a branch (`{branch}_old_{timestamp}`) rather than discarding the old state.
  Keep the branch list clean between incidents.
- **Nothing here is monitored.** No alert fires if the retention window changes, if branches
  accumulate, or if this procedure stops working. Its only trigger is somebody deciding to run
  it.
