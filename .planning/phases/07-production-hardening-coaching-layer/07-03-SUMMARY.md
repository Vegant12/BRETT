---
phase: 07-production-hardening-coaching-layer
plan: 03
subsystem: docs
tags: [mcp, coaching, prompt-engineering, drift-guard, pytest, claude-projects]

# Dependency graph
requires:
  - phase: 06-mcp-tools
    provides: the thirteen-tool read-only MCP registry whose names, parameters and required sets the document reproduces verbatim
  - phase: 04-volume-frequency-analytics
    provides: the DQ-01/DQ-02 freshness and coverage envelope (`freshness.resources`, `sessions_in_window`, `insufficient_data`, `earliest_data_at`) the document tells Claude to read
  - phase: 05-progression-records-recomposition-analytics
    provides: the recomposition verdict and its `recomposition_disclaimer`, which the document requires be surfaced with the verdict
provides:
  - "docs/coaching-instructions.md — the COACH-01 persona, decision framework and question-to-tool mapping, pasted once into a Claude Project's custom instructions (D-05..D-08)"
  - "A fast-suite drift guard that fails the moment the document names a tool the registry does not serve, or omits one of the twelve analytics tools"
  - "MCPServer(instructions=...) — a short tool-selection hint served via DiscoverResult.instructions, whose effect is observable during the D-09 UAT"
affects: [07-10 coaching UAT, any future phase that renames, adds or removes an MCP tool]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Prose-versus-registry drift guard: parse a committed markdown file, cross-check it against live Python objects, no integration marker"
    - "MCPServer(instructions=...) as a cheap, non-load-bearing complement to a client-side instructions document"

key-files:
  created:
    - docs/coaching-instructions.md
    - backend/tests/test_coaching_doc.py
  modified:
    - backend/app/mcp/server.py

key-decisions:
  - "The coaching document is the COACH-01 artifact and does not depend on MCPServer(instructions=...); the server hint is a belt to its braces, because whether Claude's connector injects DiscoverResult.instructions is unverified"
  - "The drift guard runs in the FAST suite with no integration marker — a tool rename must fail on the commit that introduces it, not after a user's Project starts calling a dead name"
  - "The guard's 'nothing is missing' direction excludes fitness_ping: the canary is not an analytics tool, so dropping it from the document is an editorial choice rather than drift"
  - "Required metadata field names are written as literals in the test rather than introspected from app.analytics.schemas — deriving them from the same source the document was written against would keep passing after a rename of both"

patterns-established:
  - "Committed-prose drift guard: when a document instructs a remote client, its claims about the codebase are asserted in the fast suite, following test_cloud_run_deploy.py's committed-file-versus-live-objects shape"
  - "Container-free MCP registry read: a local _mcp_state fixture plus lazy in-function app.mcp imports, so a registry assertion needs no Postgres and never runs the server bootstrap during collection"

requirements-completed: [COACH-01]

# Metrics
duration: 9min
completed: 2026-09-01
---

# Phase 7 Plan 03: Coaching Instructions Document Summary

**A 124-line Claude-Project instructions document that maps every real question to one of the thirteen live MCP tools and names the exact freshness/coverage fields that gate a verdict, plus a fast-suite guard that fails the moment a tool rename makes it lie.**

## Performance

- **Duration:** 9 min
- **Started:** 2026-09-01T08:04:54Z
- **Completed:** 2026-09-01T08:13:30Z
- **Tasks:** 3
- **Files modified:** 3 (2 created, 1 modified)

## Accomplishments

- **COACH-01 shipped as a pasteable artifact.** `docs/coaching-instructions.md` carries the blueprint §34–36 persona, the five core objectives and the seven-step decision framework in the blueprint's own order (D-05), followed by a thirteen-row question-to-tool table reproduced from the live registry rather than from schema guesses (D-06). 7,216 bytes — inside the ~8,000-character practical ceiling for a Claude Project custom-instructions paste (D-08).
- **The staleness requirement is now actionable, not aspirational.** ROADMAP criterion #4 asks Claude to flag stale or sparse data; the document names the five fields that carry that signal (`freshness.resources`, `coverage.sessions_in_window`, `coverage.insufficient_data`, `coverage.earliest_data_at`, `data_available`) and states what to *do* with each — including "when `insufficient_data` is true, give no verdict" and "`data_available: false` is a degraded response, never 'the user has no training data'".
- **The two behaviours the schemas cannot convey are written down.** `fitness_compare_periods` takes four explicit dates rather than a `weeks` count (with a worked example anchored on 2026-09-01), and `exercise_name` resolution is by title and can return multiple candidates with `matched: false` — present them, never pick one.
- **Drift is now a test failure instead of a silent remote breakage.** `backend/tests/test_coaching_doc.py` cross-checks every `fitness_*` token in the markdown against an in-memory `Client(mcp).list_tools()` read, in both directions, and pins the metadata field names and the paste ceiling.
- **The server publishes a short tool-selection hint** via `MCPServer(instructions=...)`, adding no tool, no route and no auth change — the tool surface is byte-identical, as the untouched `test_tool_registry_is_exactly_the_thirteen` and budget tests confirm.

## Task Commits

Each task was committed atomically:

1. **Task 1: Write docs/coaching-instructions.md** — `c910f94` (docs)
2. **Task 2: Pass a tool-selection hint to MCPServer(instructions=...)** — `d04cd15` (feat)
3. **Task 3: Write backend/tests/test_coaching_doc.py — the tool-name drift guard** — `c34e42e` (test)

## Files Created/Modified

- `docs/coaching-instructions.md` (created, 124 lines / 7,216 bytes) — the COACH-01 document. Eight `##` sections in blueprint order: Role, Core objectives, The data rule, Decision framework, Which tool answers which question, How to read the metadata envelope, Units/timezone/framing, Example questions.
- `backend/app/mcp/server.py` (modified, +27 lines) — a module-level `_INSTRUCTIONS` constant and one new `instructions=_INSTRUCTIONS` constructor argument. The `_TOOLS` tuple, the registration loop and both `add_tool` call sites are unchanged.
- `backend/tests/test_coaching_doc.py` (created, 170 lines) — four fast-suite tests: nothing invented, nothing missing, metadata fields named, document fits a paste.

## Decisions Made

- **The document is the artifact; the server string is not load-bearing.** 07-RESEARCH A4 records that `DiscoverResult.instructions` is genuinely delivered by `mcp` 2.0.0 under the stateless transport, but that whether Claude's *custom connector* injects it into the model's system prompt is unverified. The document therefore stands alone, and the server hint is a free observation opportunity during the D-09 UAT rather than a dependency.
- **No integration marker on the drift guard.** The failure it catches is silent and remote: a tool rename updates `EXPECTED_TOOLS` in the same commit and every existing test stays green, while the document keeps instructing Claude to call the old name inside a user's Project. That must fail on the commit that introduces it.
- **Metadata field names are literals in the test, not imports.** Importing them from `app.analytics.schemas` would assert that the constant equals itself and would keep passing through a rename of both sides. Same reasoning `test_mcp_tool_schemas.py` gives for duplicating `EXPECTED_CAPS`.
- **`fitness_ping` is excluded from the "nothing is missing" direction only.** It is the Phase 2 connectivity canary rather than an analytics tool, so a future edit dropping it from the document is editorial; an *invented* name is still caught in the other direction.

## Deviations from Plan

None — plan executed exactly as written. Two additions were made inside the plan's own latitude and are recorded here for transparency rather than as deviations:

- `read_text(encoding="utf-8")` was passed explicitly in the `document` fixture (the plan's sketch omitted it). The document contains em dashes and arrows, so relying on the platform's default encoding would make the test's character count and field matching platform-dependent. Matches `conftest.py`'s `hevy_fixture`.
- One extra comment paragraph above `_INSTRUCTIONS` records the T-07-13 mitigation explicitly — the string interpolates no `Settings` value, so no issuer URL, resource URL, secret or hostname can reach the discovery response. Comment only; no code change beyond the plan's specification.

**Total deviations:** 0
**Impact on plan:** None. All acceptance criteria met as written.

## TDD Gate Compliance

Task 3 carried `tdd="true"`, but a conventional RED gate was not available for it and its absence is by design rather than an omission: the "implementation" this test guards is `docs/coaching-instructions.md`, which the same plan creates in **Task 1**. Writing the guard first would have failed on a missing file — an import-time error, not a behavioural RED — and the plan deliberately orders the document first so the guard has a real subject.

The commit sequence is therefore `docs` → `feat` → `test` rather than `test` → `feat`.

To ensure the guard is not vacuous, each assertion was driven against a deliberately drifted copy of the document before the commit (scratch probe, not committed). All five checks fired as intended:

| Simulated drift | Result |
|---|---|
| `fitness_get_plateaus` renamed to a name the registry does not serve | caught (invented name) |
| `fitness_get_plateaus` removed from the document entirely | caught (undocumented registered tool) |
| `insufficient_data` replaced with another flag name | caught (dropped metadata field) |
| Document padded past 9,000 characters | caught (over-long paste) |
| `` `fitness_get_plateaus`_ `` written in emphasised prose | **not** a false failure (trailing-underscore strip works) |

## Issues Encountered

- The `_TOOL_TOKEN` regex `fitness_[a-z_]+` is greedy over trailing underscores, so a tool name written inside emphasised markdown prose would have been reported as an invented tool. Handled as the plan directed — strip a trailing `_` from each match rather than tightening the pattern, since a stricter regex would stop matching names in running text, which is precisely where drift hides. Explicitly probed (row 5 above).
- `uv run python` resolves without the `dev` dependency group (`default-groups = []` in `pyproject.toml`, so the Cloud Buildpacks `uv sync` does not ship pytest into the production image). Only affected the scratch verification probe; `uv run --group dev` is the correct local invocation. No repo change needed.
- `gsd-tools requirements mark-complete` ticked the COACH-01 checkbox but left its **Traceability Matrix** row reading `Pending`. The COACH-01 row was corrected by hand to `Complete`, matching the format `DQ-02` and `BODY-01` already use.

**Deferred, out of scope for this plan:** the same tool gap has left roughly ten other rows stale — every `PROG-*`, `CMP-01`, `BODY-02` and `MCP-0*` row still reads `Pending` despite those requirements being validated in Phases 5 and 6. Not touched here: they belong to other phases, and a parallel worktree agent rewriting shared planning rows it does not own is how wave merges conflict. Worth a single sweep at the next phase transition.

## Verification

| Check | Result |
|---|---|
| `uv run pytest backend/tests/test_coaching_doc.py -x -q` | 4 passed |
| `uv run pytest backend/tests/test_coaching_doc.py -x -q -m "not integration"` | 4 passed (same 4 — no integration marker) |
| `uv run pytest backend/tests -x -q -m "not integration"` | 381 passed, 274 deselected |
| `uv run pytest backend/tests -q` | **655 passed** (651 before this plan) |
| `uv run ruff check .` | All checks passed |
| `uv run mypy backend/app` | Success, 63 source files |
| Document shape | 124 lines, 7,216 bytes, exactly 8 `##` sections |
| Tool coverage | exactly 13 distinct `fitness_*` tokens, all in the registry, none invented |
| `MCPServer` surface | `instructions` confirmed an explicitly-typed `str \| None` parameter, no `**kwargs` — the argument cannot be silently swallowed |
| `grep -c "mcp.add_tool"` | 2, unchanged from before Task 2 |

## Known Stubs

None. No placeholder text, no empty data source, no deferred wiring — the document is complete prose, the guard asserts against live objects, and the server change is a single constant.

## Threat Flags

None. The plan's threat register (T-07-12..16) covers the whole surface this plan touches: the document contains no credential, DSN, connector URL or health value; `_INSTRUCTIONS` is a module-level literal that interpolates no `Settings` value; and `instructions=` adds no tool, route, write path or auth change. No new network endpoint, auth path, file access pattern or schema change at a trust boundary was introduced.

## User Setup Required

None for this plan's automated verification. Note for the phase, not a blocker here: the document only takes effect once a human pastes it into a Claude Project's custom instructions — which is step 2 of the D-09 UAT script (plan 07-10), where the end-to-end coaching behaviour and the connector's handling of `DiscoverResult.instructions` are both observed.

## Next Phase Readiness

- **COACH-01 is complete and ROADMAP Phase 7 success criterion #4 has its artifact.** The behavioural half of criterion #4 ("Claude *correctly flags* stale or sparse data when present") is still open by design and is verified by the D-09 UAT in plan 07-10, which must force the staleness case deliberately rather than wait for it.
- **Prerequisite carried forward, unchanged by this plan:** the live Cloud Run revision is still `brett-00005-gcx` from Phase 2 and serves only `fitness_ping`. The UAT cannot exercise this document until the redeploy plan lands the twelve Phase 6 tools.
- **The guard now binds future tool changes.** Any later phase that renames, adds or removes an MCP tool will fail `test_coaching_doc.py` in the fast suite until `docs/coaching-instructions.md` is updated in the same commit. That is the intent.

## Self-Check: PASSED

Every file and commit this summary claims was verified on disk and in git history.

| Claim | Result |
|---|---|
| `docs/coaching-instructions.md` | FOUND (7,216 bytes) |
| `backend/tests/test_coaching_doc.py` | FOUND (7,663 bytes) |
| `backend/app/mcp/server.py` | FOUND (modified) |
| `.planning/phases/07-production-hardening-coaching-layer/07-03-SUMMARY.md` | FOUND |
| Commit `c910f94` | FOUND |
| Commit `d04cd15` | FOUND |
| Commit `c34e42e` | FOUND |

No commit in this plan deleted a tracked file — all three are pure additions
(`create mode` on two, `27 insertions(+)` and zero deletions on the third).

---
*Phase: 07-production-hardening-coaching-layer*
*Completed: 2026-09-01*
