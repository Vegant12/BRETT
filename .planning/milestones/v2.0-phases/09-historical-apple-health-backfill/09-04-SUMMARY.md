---
phase: 09-historical-apple-health-backfill
plan: 04
subsystem: api
tags: [cli, argparse, apple-health, backfill, operator-tooling, dry-run, isolation-boundary]

# Dependency graph
requires:
  - phase: 09-historical-apple-health-backfill
    provides: "plan 09-03's run_backfill(sessionmaker, *, user_id, path, dry_run) -> BackfillSummary and format_summary(summary, *, path) -> list[str], plus plan 09-02's HAEExportFileError"
  - phase: 03-hevy-integration-normalization
    provides: "app/cli.py's parse-then-configure-then-dispatch bootstrap, _add_user_id, _safe_detail, the _run_status runner template, and the two source-order guards in test_cli.py"
provides:
  - "backend/app/cli.py — the `backfill-apple-health` subcommand: a positional export.xml path with no default and a REQUIRED mutually exclusive --dry-run / --write group"
  - "backend/app/cli.py::_run_backfill — the runner: owns the engine's lifetime, dispatches below configure_logging, prints format_summary's D-06 block to stdout, and reports failures through safe_message / _safe_detail only"
  - "Five new fast-suite guards in backend/tests/test_cli.py covering the verb, the mode gate (both directions), the positional path, the HAE import boundary and the runner's source position"
affects: [09-06, 09-07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "A destructive operator verb declares its mode as `add_mutually_exclusive_group(required=True)`, not as a default: the safe mode and the dangerous mode are both explicit, so a forgotten flag is an argparse error rather than the dangerous one"
    - "The CLI stays a thin dispatcher across an isolation boundary by importing exactly one entry point and one formatter — the summary text is built where the domain vocabulary already lives, so no line of cli.py can name a metric"
    - "A package-wide `rglob` boundary test is paired with a module-specific duplicate: the walk proves the rule holds everywhere, the duplicate fails with a message the person who broke it will understand"

key-files:
  created: []
  modified:
    - backend/app/cli.py
    - backend/tests/test_cli.py

key-decisions:
  - "The usage line in the module docstring is wrapped across two source lines with an escaped backslash rather than written as the plan spelled it. The plan's literal is 101 characters (ruff `E501`, `line-length = 100`) and omits `PYTHONPATH=backend`, without which `python -m app.cli` cannot import `app` — this project has no `[build-system]`, so `uv` never installs it"
  - "`args.dry_run` is the only mode flag the runner reads. `--write` needs no branch because the group is `required=True`, so exactly one of the two is always set; a second read would be a second place for the two to disagree"
  - "The mode gate was mutation-checked before commit: `required=True` was temporarily weakened to `required=False`, `test_backfill_requires_an_explicit_mode` was confirmed red with `DID NOT RAISE SystemExit`, and the mutation reverted — `git status` then showed `cli.py` unmodified"
  - "`requirements-completed: []`, matching 09-01, 09-02, 09-03 and 09-05. All seven Phase 9 plans carry `requirements: [HEALTH-10]`; this plan ships the operator command but no historical row has been written, so nothing an operator has run yet satisfies HEALTH-10"

patterns-established:
  - "When a plan's literal code would fail the repo's own lint, ship the intent and record the mechanical reason — a 101-character docstring line and a missing PYTHONPATH are both silent traps for the operator who copies the block"
  - "A boundary guard needs a positive assertion alongside its negatives: `registry`/`schemas` absent is satisfied trivially by deleting the feature, so `health_auto_export.backfill` present is what makes the test about the boundary rather than about emptiness"

requirements-completed: []

# Metrics
duration: 10min
completed: 2026-09-03
---

# Phase 9 Plan 04: The Backfill CLI Subcommand Summary

**`backfill-apple-health` is now a real operator verb — a positional `export.xml` path with no default, a required `--dry-run` / `--write` choice that makes a forgotten flag an argparse error rather than an unrehearsed 8,077-row write to production, and a runner that reaches 4.5 years of HealthKit history through exactly two imported names without `cli.py` ever spelling a metric.**

## Performance

- **Duration:** ~10 min
- **Tasks:** 2
- **Files modified:** 2 (0 created, 2 modified)

## Accomplishments

- **The mode is a gate, and it was proven to be one rather than asserted.** `add_mutually_exclusive_group(required=True)` makes both `backfill-apple-health export.xml` (neither flag) and `... --dry-run --write` (both) exit 2 without touching the environment, let alone the database — the parser runs before `get_settings()`. The guard was then mutation-checked: `required=True` was temporarily changed to `required=False`, `test_backfill_requires_an_explicit_mode` failed with `Failed: DID NOT RAISE SystemExit` pointing at the neither-flag case, and the mutation was reverted. `git status --short` confirmed `cli.py` byte-identical before Task 2 was committed.
- **`cli.py` crossed the HAE boundary without carrying any vocabulary across it.** The whole feature costs two import lines — `format_summary, run_backfill` from `backfill`, and `HAEError` from `errors`. `grep -c 'health_auto_export.registry\|health_auto_export.schemas' backend/app/cli.py` returns 0, so `test_health_auto_export_isolation.py`'s app-wide `rglob` walk still passes unchanged (5 passed), and every summary line an operator will read is still composed inside the package that owns the HealthKit names.
- **The T-09-17 bootstrap order survived the addition, and is now pinned twice.** `_run_backfill` is the only runner that builds an engine while carrying a *production* `DATABASE_URL`, so its position matters more than the others'. Measured on the committed source: `configure_logging(settings)` sits at byte 1083, the first `log.` at 9606, the first `make_engine` at 9737, and `async def _run_backfill` well past all three. The pre-existing aggregate guard still holds, and `test_backfill_runner_is_declared_below_the_bootstrap` now names this runner specifically.
- **The failure path adds no new way to leak.** `HAEError` is reported as `exc.safe_message or type(exc).__name__` and `ValueError` (the `_user_timezone` "unknown user" case) through the existing `_safe_detail`. `grep -c "str(exc)"` remains 0 and `safe_message` now appears 3 times, so `test_cli_never_formats_an_arbitrary_exception` passes on both halves without modification.
- **`--help` reads like an instruction rather than a reference.** `--dry-run` says "Parse, aggregate and print the full summary. Writes nothing."; `--write` says "Perform the import. Run --dry-run first and read the summary." The dangerous flag's help text is where the rehearsal instruction lives, because that is the line an operator reads immediately before typing it.
- **The whole fast suite is green and the toolchain is clean.** 558 passed / 11 skipped in the `not integration` suite (up 5 from 553), `ruff check backend` all clear, `mypy backend/app` clean across 74 source files.

## Task Commits

Each task was committed atomically:

1. **Task 1: The backfill-apple-health subcommand and its runner** — `847d043` (feat)
2. **Task 2: Parser and bootstrap guards for the new verb** — `6c40880` (test)

**Plan metadata:** see the final `docs(09-04)` commit.

## Files Created/Modified

- `backend/app/cli.py` — grew from 281 to 381 lines. Module docstring: summary line widened past "Hevy sync", a fourth usage line, and a new closing paragraph recording D-01 (the source is a 191 MB file on the operator's laptop, Cloud Run caps a request body at 32 MiB so no route could accept it, and a Job would only clear that ceiling by first uploading this person's gitignored health history to Cloud Storage to run a command once). `build_parser` gains the `backfill-apple-health` block; `main` gains one dispatch branch below `configure_logging(settings)`; `_run_backfill` is added last, after `_run_mapping_gaps`. The parser `description` was widened to match the new surface.
- `backend/tests/test_cli.py` — grew from 158 to 267 lines, additions only (`git diff --stat`: 109 insertions, 0 deletions). Three parser guards inserted before the existing source-order block, two source guards appended after it. Every pre-existing test function is present and unmodified.

## Decisions Made

- **The fourth usage line is wrapped, and carries `PYTHONPATH=backend`.** The plan's literal — `DATABASE_URL=<production-url> uv run python -m app.cli backfill-apple-health export.xml --dry-run` — is 101 characters at the docstring's indentation, one over `line-length = 100`, so `ruff check backend` would have failed the task's own verification. It also omits `PYTHONPATH=backend`, which the three lines above it all carry: `pyproject.toml` has no `[build-system]`, so `uv` treats the project as virtual and never installs `app` onto the path. A copied-and-pasted line that `ModuleNotFoundError`s is worse documentation than no line. Written as a two-line shell continuation with the backslash escaped (`\\`) so the rendered docstring shows one backslash rather than silently joining the lines.
- **`--write` is never read at runtime.** Only `args.dry_run` reaches `run_backfill`. Because the group is `required=True`, exactly one of the two is always set, so `args.write` is pure redundancy at the call site — and a redundant read is a place for the two flags to disagree after some future edit makes the group optional. `--write` earns its place entirely in the parser, as the thing an operator must type on purpose.
- **The parser `description` was widened.** `"Trigger and inspect the Hevy sync."` is the first line of `python -m app.cli --help`, and it is now false for a file that also imports 4.5 years of Apple Health history. Not requested by the plan; it is one string, in operator-facing output, that would otherwise tell a reader this command does not exist.
- **The `path` argument carries its own comment.** The plan justified the positional-with-no-default choice in prose; it is restated at the declaration because the reason (an implicit `export.xml` at the repo root makes it possible to import the wrong export without noticing — the user has both `export.xml` and `export_cda.xml` sitting there) is not recoverable from the code, and adding `default=Path("export.xml")` would look like a convenience.
- **`test_cli_does_not_import_hae_wire_vocabulary` asserts the positive as well as the two negatives.** "Does not contain `registry`" and "does not contain `schemas`" are both satisfied by deleting the subcommand entirely. The `health_auto_export.backfill` assertion is what keeps the test about the boundary rather than about absence.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] The plan's docstring usage line fails `ruff check` and would not run**

- **Found during:** Task 1(a)
- **Issue:** Two independent problems in one line. At the docstring's four-space indentation, `DATABASE_URL=<production-url> uv run python -m app.cli backfill-apple-health export.xml --dry-run` is 101 characters against `line-length = 100` with `E` selected, so `uv run ruff check backend` — listed in the task's own `<verify>` block — would have failed on the line the task just added. Separately, it omits `PYTHONPATH=backend`, which every other usage line in the file carries and which is required because `pyproject.toml` declares no `[build-system]`; `uv` therefore never installs the `app` package, and the documented invocation would exit with `ModuleNotFoundError: No module named 'app'`.
- **Fix:** Kept the command's content exactly, added `PYTHONPATH=backend`, and split it across two source lines with a shell continuation. The backslash is written `\\` in the source so the rendered docstring shows a single literal backslash — an unescaped one is a Python line continuation and would silently join the two lines back into one.
- **Files modified:** `backend/app/cli.py`
- **Verification:** `uv run ruff check backend` — All checks passed. Longest line in the file is now 97 characters.
- **Committed in:** `847d043`

### Beyond the Plan

**2. The parser `description` and the module docstring summary line were widened**

- The plan listed the usage block and one new paragraph as the docstring changes. `"""Command-line entrypoint for Hevy sync.` and `description="Trigger and inspect the Hevy sync."` both became false with this commit, and the second is the first line of `--help`. Both were updated. No test reads either string.
- **Files modified:** `backend/app/cli.py`
- **Committed in:** `847d043`

### Out of Scope — Deferred, Not Fixed

**`uv run ruff format --check backend/tests/test_cli.py` is red, on a pre-existing hunk.** The single reported difference is in `test_only_accepts_the_three_resources` (lines 97-99), which this plan did not touch. Confirmed pre-existing by running the formatter against `git show 7783b05:backend/tests/test_cli.py` — same failure, same location — and `backend/tests/test_cli.py` is already listed at line 25 of the phase's `deferred-items.md`, diagnosed by plan 09-01. Everything this plan added formats clean, and `backend/app/cli.py` passes `ruff format --check` outright. Not fixed: reformatting an untouched pre-existing hunk would put an unrelated diff in a commit whose whole point is auditable.

---

**Total deviations:** 1 auto-fixed (blocking) + 1 beyond-plan doc correction + 1 out-of-scope item carried
**Impact on plan:** None on behaviour. The blocking fix changes only how the usage line is typeset, and in the direction of being copy-pasteable; both other items are operator-facing strings. Every element the plan specified — the verb name, the positional `Path`, the `required=True` group, the dispatch position, the runner's structure and its two exception arms — shipped verbatim.

## Issues Encountered

- **The worktree started from the wrong base.** `git merge-base HEAD 7783b05` returned `b1d3eef` (`chore: finalize STATE.md after v1.0 milestone close`), i.e. HEAD was an *ancestor* of the required base and the entire Phase 9 tree was absent — `backfill.py` and every 09-0x artifact would have been missing. Corrected by the mandated `git reset --hard 7783b05` before any file was read, and verified by `git rev-parse HEAD`.
- **`uv run` built a fresh `.venv` inside the worktree** (42 packages, ~1.2 s) and warns on every invocation that the ambient `VIRTUAL_ENV` from the main checkout is being ignored. Cosmetic; the worktree `.venv` is gitignored and `git status` stayed clean throughout.

## Known Stubs

None. Every branch of the new code is reachable and covered: the parser block by three fast-suite guards, the dispatch branch by the live `--help` and no-mode invocations, and `_run_backfill`'s structure by the two source-position guards. Its two exception arms are not exercised by an automated test — that is deliberate and unchanged from the runners beside it (`_run_sync`'s `HevyError`/`RuntimeError` arms are likewise unasserted), because reaching them needs a container plus either a deliberately broken file or a deleted `users` row. The behaviour they wrap is already pinned inside the package: `HAEExportFileError` by `test_health_auto_export_backfill.py`, and the "no rendered exception" rule by the grep guard over this file.

The one thing this plan does *not* deliver, by design: no historical row has been written. `run_backfill` has still only ever run against fixtures and a container. Plans 09-06 and 09-07 are the dry run and the real write against the user's 191 MB file.

## Threat Flags

None. This plan adds no network endpoint, no auth path, no schema change and no new dependency. Its only new surface is an argv-driven local command; the file it reads and the rows it writes were already in the phase threat model. The five `mitigate` dispositions this plan owns are each pinned by an assertion:

| Threat | Where it is enforced | Where it is pinned |
|---|---|---|
| T-09-17 production `DATABASE_URL` in a log line | `get_settings()` then `configure_logging(settings)` run before any logger or engine; `_run_backfill` declared last in the file | `test_configure_logging_precedes_every_log_call` (aggregate), `test_backfill_runner_is_declared_below_the_bootstrap` (this runner) |
| T-09-18 stderr rendering an exception | `exc.safe_message or type(exc).__name__` for `HAEError`, `_safe_detail(exc)` for `ValueError` | `test_cli_never_formats_an_arbitrary_exception`; `grep -c "str(exc)"` is 0, `safe_message` appears 3 times |
| T-09-19 unrehearsed full write from a forgotten flag | `add_mutually_exclusive_group(required=True)` over `--dry-run` / `--write` | `test_backfill_requires_an_explicit_mode`, both directions — and verified red under a deliberate `required=False` mutation |
| T-09-20 importing the wrong export file | positional `path`, `type=Path`, no default; `format_summary` prints `path.name` and the covered date range before the operator trusts the run | `test_backfill_takes_the_export_path_positionally`, `test_parser_exposes_backfill_apple_health` |
| T-09-21 HAE vocabulary escaping the package | `cli.py` imports only `backfill.run_backfill` / `backfill.format_summary` (plus `errors.HAEError`) | `test_health_auto_export_isolation.py`'s app-wide `rglob` walk, plus `test_cli_does_not_import_hae_wire_vocabulary` |

## User Setup Required

None. No dependency was added; `pyproject.toml` and `uv.lock` are untouched. No new environment variable and no config file: `HEVY_API_KEY` is `SecretStr | None = None` in `config.py`, so `get_settings()` bootstraps with only `DATABASE_URL` set, and D-02's inline environment override supplies the production URL for one shell session without any credential reaching disk.

## Next Phase Readiness

**Ready for plans 09-06 and 09-07 (the real dry run, then the real write).** What they can rely on:

- The exact invocation is now typed out in `cli.py`'s own docstring and verified to parse:
  `DATABASE_URL=<production-url> PYTHONPATH=backend uv run python -m app.cli backfill-apple-health export.xml --dry-run`
- `--dry-run` exits 0 and prints the complete D-06 block; a real run is the same command with `--write`. There is no third mode and no default, so a plan step that forgets the flag fails loudly at argparse rather than at the database.
- Exit codes are settled: 0 on success (including a dry run and a real run that wrote nothing), 1 on a read or caller failure, 2 on a bad command line. `BackfillSummary.rows_skipped` and `rows_written` are still available if a later plan wants a stricter code, and nothing here forecloses that.
- The summary block's `date range:` line is what plan 09-03 flagged as the confirmation for the zero-overlap assumption (the export ends 2026-08-26, live webhook data starts 2026-09-02) — it is now reachable by a command an operator can type.

**Carried concerns:**

- **Nothing has yet run against the real 191 MB file.** SC#1's memory ceiling (310.9 MB peak, measured during research) and the parse wall-clock are still unverified through this entry point; `realfile`-marked coverage does not exist yet.
- **The `--write` run needs `DATABASE_URL` pointed at production from a shell.** That is D-02's deliberate design and the reason no credential is written to disk, but it also means the single most consequential command in the phase has no second confirmation beyond the flag itself. The dry run is the whole safety net; 09-06 running first is not optional.
- **`uv run ruff format --check backend` is still red on the same 18 pre-existing files** carried since plan 09-01. Any later Phase 9 plan whose verification block includes that whole-tree command will hit the same wall.

## Self-Check: PASSED

| Claim | Result |
|---|---|
| `backend/app/cli.py` | FOUND |
| `backend/tests/test_cli.py` | FOUND |
| `.planning/phases/09-historical-apple-health-backfill/09-04-SUMMARY.md` | FOUND |
| commit `847d043` | FOUND |
| commit `6c40880` | FOUND |

Plan `<verification>` block, re-run at completion:

| Check | Result |
|---|---|
| `... backfill-apple-health --help` exits 0 and lists `--dry-run`, `--write`, `--user-id` | PASS — exit 0, all three present |
| `... backfill-apple-health export.xml` (no mode flag) exits 2 | PASS — `error: one of the arguments --dry-run --write is required` |
| `uv run pytest -m 'not integration' -q` | PASS — 558 passed, 11 skipped, 330 deselected |
| `uv run pytest backend/tests/test_health_auto_export_isolation.py -q` | PASS — 5 passed; the HAE boundary is unmoved |
| `uv run ruff check backend` | PASS — All checks passed |
| `uv run mypy backend/app` | PASS — no issues in 74 source files |

Task 1 acceptance criteria, verified mechanically:

| Criterion | Result |
|---|---|
| contains `"backfill-apple-health"` and `add_mutually_exclusive_group(required=True)` | PASS — 6 and 1 |
| contains `from app.integrations.health_auto_export.backfill import format_summary, run_backfill` | PASS — 1 |
| `grep -c "health_auto_export.registry\|health_auto_export.schemas"` | PASS — 0 |
| `grep -c "str(exc)"` == 0 and `grep -c "safe_message"` >= 2 | PASS — 0 and 3 |
| `configure_logging(settings)` precedes the first `log.` and the first `make_engine` | PASS — 1083 < 9606, 1083 < 9737 |
| `--help` exits 0 and lists `--dry-run`, `--write`, `--user-id` | PASS |
| no mode flag exits 2 naming `--dry-run` / `--write` | PASS |
| `uv run pytest backend/tests/test_cli.py backend/tests/test_health_auto_export_isolation.py -q` | PASS — 19 passed |
| `uv run ruff check backend` and `uv run mypy backend/app` | PASS |

Task 2 acceptance criteria, verified mechanically:

| Criterion | Result |
|---|---|
| all five new test functions defined | PASS — 5 of 5 FOUND |
| every pre-existing test still present (`git diff` shows additions only) | PASS — 109 insertions, 0 deletions |
| `uv run pytest backend/tests/test_cli.py -q` | PASS — 14 passed |
| `uv run pytest -m 'not integration' -q` | PASS — 558 passed |
| `uv run ruff check backend` | PASS |

Plan `<success_criteria>`:

| Criterion | Result |
|---|---|
| A `backfill-apple-health` verb with a positional path and a required `--dry-run` / `--write` choice | PASS — and the requirement mutation-checked |
| The runner owns the engine's lifetime, dispatches below `configure_logging`, prints `format_summary`'s block to stdout | PASS — `finally: await engine.dispose()`, byte-offset guard, `for line in format_summary(...): print(line)` |
| `cli.py` imports nothing from the HAE package except `backfill` | PASS — plus `errors.HAEError`, which the plan's own `<interfaces>` block specifies; `registry`/`schemas` count 0 |
| Five new CLI guards pass, and every pre-existing CLI guard still passes | PASS — 14 in `test_cli.py`, additions only |

---
*Phase: 09-historical-apple-health-backfill*
*Completed: 2026-09-03*
