---
phase: 09-historical-apple-health-backfill
plan: 06
subsystem: docs
tags: [runbook, apple-health, backfill, dry-run, operator, verification-record, healthkit]

# Dependency graph
requires:
  - phase: 09-historical-apple-health-backfill
    provides: "plan 09-04's `backfill-apple-health` CLI verb (positional path, required --dry-run/--write group) and plan 09-03's `format_summary` D-06 block"
  - phase: 09-historical-apple-health-backfill
    provides: "plan 09-05's eleven `realfile` tests and the pinned ground truth for the 2026-08-26 export"
  - phase: 08-apple-health-nutrition-ingest
    provides: "docs/health-auto-export-setup.md §1-§9, including §7's sample_count discriminator and §9's two dated verification entries"
provides:
  - "docs/health-auto-export-setup.md §10 — the operator runbook for the one-time backfill: pre-flight, dry run with the expected figures, the real run, four verification SQL blocks, failure modes and credential hygiene"
  - "docs/health-auto-export-setup.md §9's third dated entry — the executed dry run against the real 191 MB export, its full printed summary, and the empirical answer to RESEARCH Assumption A2"
  - "The empirically settled overlap answer: zero days overlap between the backfill (ends 2026-08-26) and the live webhook feed (begins 2026-09-02)"
affects: [09-07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "A runbook step is not written, it is executed — every command in §10's pre-flight was run before the section was committed, and two of them did not work as the plan spelled them"
    - "The verification record pastes the summary block verbatim and nothing else from the run, because `format_summary` is asserted to emit no measured quantity — safety by construction rather than by the operator's judgement at paste time"
    - "A vacuously-satisfied success criterion is recorded as vacuous, naming the test that actually proves it, so a later reader does not mistake 'zero rows returned' for evidence"

key-files:
  created: []
  modified:
    - docs/health-auto-export-setup.md

key-decisions:
  - "§10 is placed physically BEFORE §9 despite the numbering. §9 is an append-only log that only grows at the bottom; §10 is procedure and belongs with the procedure. An italic note at the top of §10 says so, so the ordering reads as deliberate rather than as a botched insert"
  - "The rehearsal ran against the LOCAL docker compose database, not production (T-09-28). No `DATABASE_URL` appears anywhere in the new §9 entry — the command read the repo's gitignored `.env`, which points at localhost"
  - "The dry run was executed twice and the two summary blocks compared byte-for-byte. One run proves the command works; two identical runs prove the summary is deterministic, which is what makes it usable as a diff target before and after 09-07's write"
  - "`requirements-completed: []`, matching 09-01 through 09-05. HEALTH-10 is satisfied by a historical row existing in production, and this plan deliberately wrote none — 09-07 is the plan that completes it"

patterns-established:
  - "Rehearsing a runbook is the test of the runbook, not just of the command: both defects found here were in prose that had never been executed, and both would have read to an operator as a broken export file rather than as a mistyped instruction"

requirements-completed: []

# Metrics
duration: 25min
completed: 2026-09-03
---

# Phase 9 Plan 06: The Backfill Runbook and Its Rehearsal Summary

**`docs/health-auto-export-setup.md` §10 is now the operator runbook for the one-time backfill — pre-flight, both invocations, the eleven measured figures, four verification queries and the failure modes — and it has been executed rather than merely written: the dry run ran against the real 191,257,897-byte `export.xml` in 4.41 s, exited 0, matched all eleven pinned figures and all twelve per-metric row counts, wrote zero rows, and settled Assumption A2 with observed dates (export ends 2026-08-26, webhook feed begins 2026-09-02 — zero days overlap).**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-09-03T05:45Z (approx.)
- **Completed:** 2026-09-03T06:05Z
- **Tasks:** 2 (plus two auto-fix commits)
- **Files modified:** 1 (0 created, 1 modified)

## Accomplishments

- **§10 exists and every command in it has been run.** Pre-flight (file identity, `alembic current` vs `heads`, the current-contents query), Step 1 (dry run), Step 2 (the real run, documented not executed), Afterwards (four SQL blocks covering SC#3, SC#4 and freshness), If something goes wrong, and a Credential hygiene paragraph. `grep -cE "postgres(ql)?://[^<]"` over the whole file returns **0** — every `DATABASE_URL` is the literal `<production-database-url>` placeholder.
- **The dry run is a measured event, not a formality.** Exit code 0, wall clock **4.41 s** for the whole command (~2.6 s of it the streaming parse, from `hevy_cli_started` 06:00:22.011Z to `health_backfill_parsed` 06:00:24.634Z). Run **twice**; the two 57-line summary blocks are byte-identical, which is what makes the block usable as a before/after diff target for plan 09-07.
- **All eleven figures matched, and so did all twelve per-metric row counts.** 438,649 records total; the four addends 230,395 + 208,175 + 79 + 0 summing to it exactly; 230,395 datapoints seen; 209 dropped and all 209 Hevy-sourced; Workout=224; ActivitySummary=1,443; 7,403 multi-point days; 8,077 rows would-write; 0 skipped; date range 2022-03-10 .. 2026-08-26; freshness not advanced. Nothing was edited to match — nothing needed to be. `multi-point days: 7403` in particular confirms plan 09-05's logging-pipeline finding holds through the CLI entry point, where `configure_logging` runs first by construction.
- **Assumption A2 is answered with dates rather than assumed.** The dry run's `date range:` ends 2026-08-26; the first `local_day` the webhook delivered is 2026-09-02 (§9's preceding entry). Zero days overlap. Recorded explicitly as making SC#3 **vacuous** on production data — the criterion is proven by `test_backfill_idempotency.py`'s container test, not by this run — so a later reader cannot mistake an empty result set for evidence.
- **The dry run demonstrably wrote nothing.** `SELECT count(*) FROM health_daily_metrics` on the local database read **0 before and 0 after** both invocations, and `sync_state` still holds **no** row for `provider = 'apple_health'`, so freshness was not advanced either. An observed zero delta on two dimensions, not an assertion inherited from a unit test.
- **The full suite is green through the change.** `uv run pytest -q` → **899 passed**; `-m 'not integration'` → 569 passed, 330 deselected; `-m realfile backend/tests/test_backfill_real_export.py` → **11 passed in 26.65 s**, so the eleven figures quoted in §10 are asserted mechanically as well as transcribed.

## Task Commits

1. **Task 1: The §10 backfill runbook** — `d28568e` (docs)
2. *(auto-fix)* **The alembic pre-flight had no working directory** — `6f8e7d4` (docs)
3. *(auto-fix)* **The `ExportDate` probe window was too small for a real export** — `c8dbc77` (docs)
4. **Task 2: The executed dry run, recorded as §9's third dated entry** — `e78622b` (docs)

**Plan metadata:** see the final `docs(09-06)` commit.

## Files Created/Modified

- `docs/health-auto-export-setup.md` — grew from 342 to 642 lines. `git diff --numstat e0edce4 HEAD` reports **300 insertions, 0 deletions**: additions only against the wave-4 baseline. (The one deletion inside the range, in `c8dbc77`, rewrote a line this plan had itself added one commit earlier, so it nets out.) Two blocks were added: `## 10. The one-time historical backfill (HEALTH-10)` inserted between §8 and §9, and `### 2026-09-03 — historical backfill dry run` appended to §9. Every pre-existing heading `## 1.` through `## 9.` and both existing dated subsections are intact and unrenumbered.

## Decisions Made

- **§10 sits physically before §9.** The plan required it (§9 must stay last, because the next task appends to it), and the acceptance criterion checks the byte offsets: `## 10.` at 16170, `## 9.` at 24014. Left as a numbering discontinuity rather than a renumber, with a one-line italic note at the top of §10 explaining that §9 is an append-only log and §10 is procedure. Without the note the ordering reads as a mistake, which invites the next editor to "fix" it.
- **The rehearsal used the local database.** T-09-28 asks for exactly this, and it means the entire new §9 entry contains no connection string of any kind — not even a placeholder, because there was nothing to place. The production override belongs to plan 09-07, which is the only place in the phase it should appear.
- **Two runs, not one.** The plan asked for one execution. A second costs 4.4 s and converts "the command works" into "the summary is deterministic", which is the property plan 09-07 will rely on when it diffs the `--write` block against this one.
- **`sync_state` was checked as well as `health_daily_metrics`.** The plan's zero-write check is a row count. `format_summary`'s last line is `freshness: not advanced (dry run)`, and a summary line claiming something about the database is worth confirming against the database rather than against the code that printed it. Zero `apple_health` rows, so the claim holds.
- **The two runbook defects are recorded in §9, not only in this summary.** They were found by following §10, and the person most likely to hit them is the next person following §10 — the operator doc is where that belongs. This summary is the audit trail; the doc is the artifact.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] The §10 alembic pre-flight block does not run from the repo root**

- **Found during:** Task 2, step 1 (bringing the local database to head — i.e. the first time anyone executed the block Task 1 had just written)
- **Issue:** The plan specified the pre-flight as three bare `uv run alembic …` commands. `alembic.ini` lives in `backend/`, not at the repo root, so from the root every one of them exits with `FAILED: No 'script_location' key found in configuration`. Reproduced directly in this worktree. The already-committed sibling runbook (`docs/runbook-sync-schedule.md`) uses `cd backend` for exactly this reason, so §10 was the outlier.
- **Fix:** Added `cd backend` to the block with an inline comment naming the error it prevents, plus two sentences explaining why `cd backend` is safe here specifically (settings read `.env` relative to cwd, so nothing under `backend/` would be configured — but the inline `DATABASE_URL` override beats `.env` regardless) and an instruction to return to the repo root before Step 1, since the backfill command is written from there.
- **Files modified:** `docs/health-auto-export-setup.md`
- **Verification:** `uv run --directory backend alembic upgrade head` → `0004 -> 0005`; `alembic current` and `alembic heads` both `0005 (head)`.
- **Committed in:** `6f8e7d4`

**2. [Rule 1 - Bug] The `ExportDate` probe reads too small a window to find `ExportDate`**

- **Found during:** Task 2, step 2 (confirming the file is the one the pinned figures describe)
- **Issue:** The plan specified `head -c 400 export.xml | grep -o 'ExportDate value="[^"]*"'`. It returns **nothing** on a real HealthKit export. Apple writes a ~7 KB inline DTD immediately after the XML declaration; `<ExportDate value="…"/>` begins at byte **7426** in this file. The 400-byte window lands inside the `<!ELEMENT>`/`<!ATTLIST>` declarations, where the string `ExportDate value="` does not occur. An operator running the documented command would see empty output on a perfectly good file — and the step's whole purpose is to answer "is this the export I mean", so a false negative there is worse than no check.
- **Fix:** Widened to `head -c 20000`, with a comment naming the DTD as the reason so the number does not look arbitrary. Verified against the real file: returns `ExportDate value="2026-08-26 10:09:33 +0700"`. Still instant — it reads 20 KB of a 191 MB file.
- **Files modified:** `docs/health-auto-export-setup.md`
- **Verification:** `head -c 20000 export.xml | grep -o 'ExportDate value="[^"]*"'` → the expected line.
- **Committed in:** `c8dbc77`

**3. [Rule 3 - Blocking] The worktree had no `export.xml`, no `.env` and no virtualenv**

- **Found during:** setup, before Task 1
- **Issue:** `export.xml` and `.env` are both gitignored, so a fresh git worktree has neither — and this plan's entire second task is running a command against the real file with a database URL. `uv sync` had also never run here.
- **Fix:** Read-only symlinks at the worktree root pointing at the real files in the main checkout (plus `backend/.env → ../.env`, because pydantic-settings resolves `env_file=".env"` relative to cwd and alembic runs from `backend/`), and `uv sync --group dev --frozen`. `git check-ignore -v` confirms all three are covered by `.gitignore:1` and `.gitignore:16`; `git status --short` stayed clean at every commit.
- **Files modified:** none (untracked, gitignored setup only)
- **Verification:** `ls -lL export.xml` → 191,257,897 bytes; `git status --short` empty before each `git add`.
- **Committed in:** n/a — no repository change

**4. [Rule 3 - Blocking] `docker compose up -d` collided with the already-running local database**

- **Found during:** Task 2, step 1
- **Issue:** The worktree's compose project tried to create its own `db` container and failed with `Bind for 0.0.0.0:5432 failed: port is already allocated` — the main checkout's `brett-db-1` (up 4 days, healthy) already holds :5432. That container **is** the local database the plan names, so a second one was never wanted.
- **Fix:** `docker compose down` in the worktree to remove the stray container and network, then used the running `brett-db-1` directly. Ran `alembic upgrade head` against it (`0004 → 0005`), which is a purely additive migration the local database needed anyway.
- **Files modified:** none
- **Verification:** `docker ps --filter name=brett-db-1` → `Up 4 days (healthy) 0.0.0.0:5432->5432/tcp`; `alembic current` → `0005 (head)`.
- **Committed in:** n/a — no repository change

### Beyond the Plan

**5. The dry run was executed twice and the summaries compared byte-for-byte**

- The plan asked for one execution. The second cost 4.41 s and proves determinism, which is the property plan 09-07 needs when it compares the `--write` summary against this one. Recorded in §9 as "Run twice; the two summary blocks are byte-identical."
- **Files modified:** `docs/health-auto-export-setup.md`
- **Committed in:** `e78622b`

**6. `sync_state` was checked alongside the row count**

- The plan's zero-write confirmation is a `SELECT count(*)` on `health_daily_metrics`. The summary's final line also makes a claim about freshness, so `sync_state` was queried too: **zero** rows for `provider = 'apple_health'`. Both dimensions are recorded in §9.
- **Files modified:** `docs/health-auto-export-setup.md`
- **Committed in:** `e78622b`

### Out of Scope — Deferred, Not Fixed

**`uv run ruff format --check backend` remains red on the same 18 pre-existing files** carried since plan 09-01 (`deferred-items.md`). This plan touched no Python at all, so the relevant `pre-commit run --files docs/health-auto-export-setup.md` correctly skips both ruff hooks and passes gitleaks, large-files, end-of-file and trailing-whitespace.

---

**Total deviations:** 2 auto-fixed doc bugs + 2 blocking environment fixes + 2 beyond-plan verifications + 1 out-of-scope item carried
**Impact on plan:** Both auto-fixed bugs are in the artifact this plan owns and were found by the mechanism the plan designed — rehearsing the runbook is what tests the runbook. Neither changes what §10 instructs, only whether the instruction executes. Everything the plan specified shipped: the section, its placement, both invocations verbatim, all eleven figures, the four SQL blocks, the failure modes, the credential-hygiene paragraph, and the dated record with the summary block, the wall clock, the figure-by-figure comparison, the A2 answer and the zero-write confirmation.

## Issues Encountered

- **The stdout/stderr split is not what a reader might expect.** structlog writes the run's log lines to **stdout**, not stderr, so `> file` captures the log stream and the summary block together and `2> file` captures only `uv`'s virtualenv warning. Harmless here — the summary block is the last 57 lines either way — but a future operator piping the run through `grep` should know the log lines are in the same stream.
- **`uv` warns on every invocation in a worktree** that the ambient `VIRTUAL_ENV` from the main checkout is being ignored. Cosmetic, and the same warning plan 09-04 recorded.

## Known Stubs

None. Every command in §10 either was executed during this plan (the pre-flight, Step 1) or is the same command with one flag changed and is deliberately deferred to plan 09-07 (Step 2, `--write`). The four SQL blocks in "Afterwards" are written against a table that will only have backfill rows in it after 09-07 — they were not run here because there is nothing yet for them to return, which is stated in the §9 record rather than implied.

The one thing this plan does **not** deliver, by design: **no historical row has been written.** HEALTH-10 is not complete. Plan 09-07 is the real write.

## Threat Flags

None. This plan adds no network endpoint, no auth path, no schema change, no new dependency and no new file read. Its only new surface is committed prose. The five `mitigate` dispositions it owns:

| Threat | Where it is enforced | Where it is pinned |
|---|---|---|
| T-09-26 production DSN in the runbook or the record | Every occurrence is the literal `<production-database-url>`; the rehearsal used the local database so the new §9 entry contains no URL at all | `grep -cE "postgres(ql)?://[^<]" docs/health-auto-export-setup.md` == **0**; `gitleaks` passed in pre-commit; the rule is also stated in prose in §10's Credential hygiene paragraph so it survives a copy-paste into a transcript |
| T-09-27 the summary block pasted into the doc | The block is `format_summary`'s output verbatim and nothing else from the run was copied | `test_summary_prints_no_measured_quantity` asserts the block carries counts, metric names, HealthKit identifiers, units and dates only — safe by construction, not by judgement |
| T-09-28 rehearsing against production | The run used `brett-db-1` on localhost via the repo's `.env`; the production override is deferred to 09-07 | The §9 entry says so explicitly and shows a command with no `DATABASE_URL`; `sync_state` and `health_daily_metrics` were both read from the local database |
| T-09-29 expected figures edited to match a wrong result | Nothing was edited; all eleven matched on the first run | `uv run pytest -m realfile` → 11 passed, asserting the same figures mechanically, so loosening the doc would not loosen the test |
| T-09-30 production schema behind the deployed code at write time | The `alembic current` / `alembic heads` comparison is step 2 of §10's pre-flight, promoted from a STATE.md blocker that has already occurred twice | The block was executed against the local database this run (`0004 → 0005`, then `current` == `heads` == `0005`), so the instruction is known to work before 09-07 runs it against production |

## User Setup Required

None for the repository. To reproduce the rehearsal locally you need `export.xml` at the repo root (gitignored, the user's own Health app export) and `docker compose up -d`. Without the export the eleven `realfile` tests skip cleanly and §10 is still readable.

## Next Phase Readiness

**Ready for plan 09-07 (the real `--write` run against production).** What it can rely on:

- **The procedure is written down and has been executed.** §10's pre-flight and Step 1 are proven; Step 2 differs from Step 1 by one flag.
- **The expected `--write` summary is knowable in advance.** The dry-run block is deterministic across runs, so 09-07's output should differ in exactly four places: the headline (`WROTE TO THE DATABASE`), the `rows:` verb (`written`), the `freshness:` line, and nothing else. A fifth difference is a finding.
- **The overlap question is closed on the file side.** The export ends 2026-08-26. What 09-07 still owes is the production-side half: §10's pre-flight step 3 (`SELECT source, count(*), min/max(local_day) … GROUP BY source`) against production, to confirm the webhook's `min(local_day)` really is 2026-09-02 there and not earlier.
- **The local database is at `0005`**, so an integration run needs no migration step.

**Carried concerns:**

- **SC#3 will be satisfied vacuously on production data.** Zero overlapping days means the "two rows for the same `source_name`" query returns zero rows for a reason that has nothing to do with the upsert being correct. The container test is the real proof. Worth saying out loud in 09-07's record too, so the phase's verification does not rest on an empty result set.
- **Assumption A3 (the phone is not renamed) is untested and untestable from here.** A rename between now and the real write desynchronizes backfill and webhook `source_name`. With zero overlapping days it cannot bite on this run, but it is the reason the overlap answer must be re-checked against production immediately before the write rather than trusted from this record.
- **The `--write` run has no second confirmation beyond the flag.** That is D-02's deliberate design. This dry run is the safety net, and it has now been used.
- **`uv run ruff format --check backend` is still red on 18 untouched files** (`deferred-items.md`), unchanged by this plan.

## Self-Check: PASSED

| Claim | Result |
|---|---|
| `docs/health-auto-export-setup.md` | FOUND |
| `.planning/phases/09-historical-apple-health-backfill/09-06-SUMMARY.md` | FOUND |
| commit `d28568e` | FOUND |
| commit `6f8e7d4` | FOUND |
| commit `c8dbc77` | FOUND |
| commit `e78622b` | FOUND |

Plan `<verification>` block, re-run at completion:

| Check | Result |
|---|---|
| `uv run pytest -m realfile backend/tests/test_backfill_real_export.py -q` | PASS — 11 passed in 26.65s |
| `uv run pytest -q` (full suite) | PASS — 899 passed in 45.90s |
| `uv run pre-commit run --files docs/health-auto-export-setup.md` | PASS — gitleaks, large-files, end-of-file, trailing-whitespace; ruff hooks correctly skipped |
| `grep -cE "postgres(ql)?://[^<]" docs/health-auto-export-setup.md` | PASS — **0** |
| The dry run against the real `export.xml` exited 0 and matched all eleven figures | PASS — exit 0 in 4.41 s, all eleven matched, plus all twelve per-metric counts |

Task 1 acceptance criteria, verified mechanically:

| Criterion | Result |
|---|---|
| heading `## 10. The one-time historical backfill (HEALTH-10)` present | PASS |
| `## 9.` is still the LAST top-level section (offset `## 9.` > offset `## 10.`) | PASS — 24014 > 16170 |
| both invocations present verbatim (`--dry-run`, `--write`) | PASS |
| `alembic current` and `alembic heads` in the pre-flight | PASS |
| figures `438,649` `230,395` `208,175` `209` `224` `1,443` `7,403` `8,077` `2022-03-10` `2026-08-26` | PASS — all ten present |
| four verification SQL blocks incl. `HAVING count(*) > 1` and `lower(source_name) = 'hevy'` | PASS |
| `grep -cE "postgres(ql)?://[^<]"` == 0 | PASS — 0 |
| `## 1.` through `## 9.` all still present and unrenumbered | PASS — 9 of 9 FOUND |
| `uv run pre-commit run --files docs/health-auto-export-setup.md` exits 0 | PASS |

Task 2 acceptance criteria, verified mechanically:

| Criterion | Result |
|---|---|
| the command was executed against the real file and exited 0 | PASS — exit code 0, twice |
| §9 contains a dated subsection ending `— historical backfill dry run` | PASS |
| it contains `records:` `datapoints:` `date range:` `rows by metric:` `freshness:` | PASS — all five |
| it contains the observed size and `ExportDate` | PASS — `191257897`, `ExportDate value="2026-08-26 10:09:33 +0700"` |
| it states whether all eleven figures matched and answers A2 with two compared dates | PASS — "All eleven expected figures matched"; 2026-08-26 vs 2026-09-02, zero overlap |
| it confirms zero rows written to the local database | PASS — 0 before / 0 after, and zero `apple_health` rows in `sync_state` |
| `grep -cE "postgres(ql)?://[^<]"` == 0 | PASS — 0 |
| `uv run pytest -m realfile backend/tests/test_backfill_real_export.py -q` exits 0 | PASS — 11 passed |
| `uv run pre-commit run --files docs/health-auto-export-setup.md` exits 0 | PASS |

Plan `<success_criteria>`:

| Criterion | Result |
|---|---|
| §10 documents pre-flight, dry run, real run, verification SQL and failure modes | PASS |
| the command has actually been run against the real 191 MB export with `--dry-run` and exited 0 | PASS — twice, 4.41 s, exit 0 |
| the printed summary matched the eleven measured figures, or every divergence is explained | PASS — zero divergences |
| Assumption A2 answered with observed dates rather than assumed | PASS — 2026-08-26 vs 2026-09-02, zero days overlap, and recorded as making SC#3 vacuous |
| no real connection string exists anywhere in the repository | PASS — `grep -cE "postgres(ql)?://[^<]"` == 0 on the file; gitleaks passed; the rehearsal used the local database so no URL was written at all |

---
*Phase: 09-historical-apple-health-backfill*
*Completed: 2026-09-03*
