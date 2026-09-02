---
phase: 08-apple-health-nutrition-ingest
plan: 07
subsystem: api
tags: [fastapi, webhook, bearer-auth, body-size-cap, route-order, rate-limiting, roadmap-criterion-4]

# Dependency graph
requires:
  - phase: 08-apple-health-nutrition-ingest
    plan: 03
    provides: "Settings.health_ingest_secret, Settings.ingest_max_body_bytes, middleware.INGEST_PATH_PREFIX and the dedicated ingest token bucket"
  - phase: 08-apple-health-nutrition-ingest
    plan: 04
    provides: "verify_bearer's constant-time byte comparison, HAEPayload, and HAEPayloadError -- an error type defined for this plan's consumer and raised by nothing until now"
  - phase: 08-apple-health-nutrition-ingest
    plan: 06
    provides: "ingest_payload / HealthIngestResult -- the counts-only orchestration this route calls and returns"
  - phase: 01-backend-foundation
    provides: "app/api/routes/health.py's router pattern, request.app.state, and main.py's D-05 global exception handler"
provides:
  - "POST /api/v1/ingest/health-auto-export -- authenticated, size-capped, 202 with counts only"
  - "Registration above the catch-all mount, asserted structurally against the live router rather than against main.py's text"
  - "parse_payload: raw webhook bytes -> HAEPayload, inside the HAE package so no route imports its wire schemas"
  - "A FastAPI route-inventory drift guard that survives FastAPI's _IncludedRouter wrapping"
  - "ROADMAP criterion #4 as a passing test with a row-count proof"
affects: [08-08-deploy-and-device-setup, 09-historical-backfill, 13-reports-and-nutrition-trends]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Credential, then size, then parse -- ordering asserted by the ABSENCE of post-parse log events, because a status code cannot distinguish a cap that fired early from one that fired late"
    - "Structural route-order assertions against the live router list, never positional text search on a file whose comments legitimately spell the thing being searched for"
    - "A guard-on-the-guard beside every walk over framework internals: FastAPI 0.141.1 makes the obvious APIRoute filter return an empty set"
    - "Wire-model parsing stays inside the provider package; the route holds the RESULT of a parse without naming the type that produced it"

key-files:
  created:
    - backend/app/api/routes/health_ingest.py
    - backend/tests/test_health_ingest_route.py
    - backend/tests/test_health_ingest_isolation.py
  modified:
    - backend/app/main.py
    - backend/app/integrations/health_auto_export/ingest.py
    - backend/tests/test_health_ingest_auth.py
    - .planning/REQUIREMENTS.md

key-decisions:
  - "parse_payload moved INTO the HAE package: the plan's prescribed `from ...schemas import HAEPayload` is forbidden by name by test_health_auto_export_isolation.py, which names routes explicitly. HAEPayloadError existed and was raised by nothing -- it was built for this consumer"
  - "Route order asserted against app.router.routes, not against main.py's text: two pre-existing comments spell the mount call, so the plan's positional-index check reports False on a CORRECT file"
  - "The isolation seed carries two missed weigh-in days on purpose -- the gapless version was mutation-checked and proved a leak INVISIBLE rather than absent"
  - "HEALTH-06 deliberately left pending for 08-08: the receiver exists and is proven, but no data syncs from the actual phone until the deploy and the device automation exist"
  - "No try/except around ingest_payload: main.py's D-05 handler already answers identically in every environment, and the omission is documented in the handler's own docstring"

patterns-established:
  - "Mutation-check every absence assertion before trusting it: three separate mutations here each failed a different, specific test, and one of them exposed a genuinely insensitive fixture"
  - "When a plan's acceptance grep contradicts the code the same plan prescribes, satisfy the INTENT with a stronger structural check and record the contradiction"

requirements-completed: [HEALTH-07, HEALTH-08]

# Metrics
duration: 75min
completed: 2026-09-02
---

# Phase 8 Plan 07: Health Auto Export Ingest Route Summary

**The webhook terminates: credential checked before a byte of body is read, body capped before the parser sees it, counts-only 202 out — registered where FastAPI actually matches it, and paired with a row-count proof that none of it moved a single number Claude reports about training.**

## Performance

- **Duration:** ~75 min
- **Tasks:** 3 of 3, four commits (genuine RED -> GREEN on Task 1)
- **Files created:** 3 (1 source, 2 test)
- **Files modified:** 4
- **Tests added:** 18 (851 total, up from the 833 wave-4 base)

## Accomplishments

- **RESEARCH Pitfall 1 closed twice over.** The route answers 202 over real HTTP against the live `app` object, and a separate structural test asserts the ingest router's index in `app.router.routes` is below the `Mount`'s. Moving `include_router` below the mount fails **7 of 10** tests in the route file — this is not a theoretical hazard and it is no longer an unguarded one.
- **RESEARCH Pitfall 5 closed in both branches, and each proven independently.** Removing only the streaming cap fails exactly the undeclared-body test and leaves the declared-length test green, which is the evidence that `Content-Length` alone is not the control. The ordering claim is asserted by the **absence** of `health_ingest_payload_rejected` and `health_ingest_completed` in a real captured log stream, because a 413 alone cannot tell an early cap from a late one.
- **RESEARCH Pitfall 3 closed with a guard that actually works.** The obvious inventory guard — `{r.path for r in app.routes if isinstance(r, APIRoute)}` — returns the **empty set** on FastAPI 0.141.1, which wraps `include_router` in `_IncludedRouter` rather than flattening. Written that way it would have passed no matter what was registered. The walk recurses through `original_router`, and `test_the_route_walk_actually_finds_routes` fails the moment it stops understanding FastAPI's structure.
- **ROADMAP criterion #4 is a passing test, and it can fail.** The first version could not: `_dedupe_by_day` does not filter by source and orders `(measured_on, source)`, so on a day that already has a `hevy` weigh-in a stray `apple_health` row sorts first and is silently overwritten. A gapless seed therefore proves a leak invisible, not absent. Two missed weigh-in days in the seed turn the equality into a real assertion — found by mutation, not by reading.
- **HEALTH-08 asserted at the database.** Disabling `is_hevy_sourced` puts the Finding A row (666.5 kcal, `source: "Hevy"`) straight into `health_daily_metrics` and fails the test with the measurement that motivates it in the message.
- **Full suite green: 851 passed**, integration included.

## Task Commits

| Task | Gate | Commit | Message |
|------|------|--------|---------|
| 1 | RED | `4a47307` | `test(08-07)`: add failing over-HTTP test for the ingest route |
| 1 | GREEN | `e8c4076` | `feat(08-07)`: authenticating, size-capped Health Auto Export webhook route |
| 2 | — | `e5645b7` | `test(08-07)`: prove the ingest route's wire contract over real HTTP |
| 3 | — | `e6f90da` | `test(08-07)`: prove Apple Health data changes no Hevy number (criterion #4) |

## TDD Gate Compliance

**Task 1 shows a genuine RED -> GREEN pair.** The plan assigns the source to Task 1 and the tests to Tasks 2-3, which would make a conventional RED unobservable. The defining Pitfall-1 case was therefore written first, into the file Task 2 later expands, and confirmed failing with the exact symptom the pitfall predicts:

```
AssertionError: HEALTH-07: expected 202 from BRETT's own handler, got 404.
A 404 or an MCP-shaped body means `include_router` sits BELOW the catch-all mount
```

`4a47307` (test) precedes `e8c4076` (feat) in `git log`. No REFACTOR commit — the module needed no cleanup after GREEN.

**Tasks 2 and 3 have no GREEN commit, and that is stated rather than dressed up.** They add no production code; they are regression guards over behaviour Task 1 implemented. Their non-vacuity was demonstrated by three deliberate mutations instead (below), which is a stronger claim than a RED ordering because each one names the exact wrong implementation the guard rejects.

## Mutation Testing

Every mutation was applied through a `.bak` copy in the scratchpad and reverted with `git status` confirming a clean tree afterwards. No `git clean` was run at any point.

| Mutation | Result |
|----------|--------|
| `include_router(health_ingest.router)` moved below `app.mount("/", mcp_app)` | **7 of 10** route tests fail, including the structural order guard. `test_no_unauthenticated_fastapi_route_was_added` correctly still passes — the route is registered, just uselessly |
| Streaming cap removed, declared-`Content-Length` check kept | Exactly `test_an_oversized_undeclared_body_is_rejected_before_the_parse` fails; the other two oversized cases stay green |
| `is_hevy_sourced` forced to `False` | `test_no_hevy_sourced_row_lands_in_health_daily_metrics` fails, reporting 1 row |
| One `apple_health` weigh-in injected on a day the seed already covers | **PASSED — the test was insensitive.** Fixed (see Deviations) |
| One `apple_health` weigh-in injected on a GAP day, after the fix | Fails naming `'body_weight_trend'` |

## Files Created / Modified

- **`backend/app/api/routes/health_ingest.py`** (new). The module docstring records the five things a future reader needs and cannot infer: who calls this path and that nothing else does; that registration order is load-bearing; that the route inherits zero auth from the MCP sub-app; that an unset secret is a *disabled* path rather than an open one, and why the guarantee lives in the deploy-script test rather than in a boot-time raise; and why the check order is credential -> size -> parse. The handler's own docstring records the deliberate ABSENCE of a `try`/`except` around `ingest_payload`, so the omission reads as a decision.
- **`backend/app/integrations/health_auto_export/ingest.py`** — `parse_payload` added (see Deviation 1).
- **`backend/app/main.py`** — one import and one `include_router`, placed between `health.router` and the mount. No other line touched.
- **`backend/tests/test_health_ingest_route.py`** (new, 10 tests). Mount order (over HTTP and structurally), the two oversized branches plus a within-cap guard against a handler that 413s everything, the 400 envelope case, the inventory drift guard plus its own guard, the prefix check, and the 429.
- **`backend/tests/test_health_ingest_auth.py`** — the integration half the module docstring had promised since 08-04: `test_401_leaks_nothing` and `test_unset_secret_rejects_every_request`.
- **`backend/tests/test_health_ingest_isolation.py`** (new, 6 tests). Criterion #4 plus four row-count proofs plus the non-empty-snapshot guard.

## Decisions Made

- **The 401 is asserted byte-identical, not merely equal in status.** `absent.content == wrong.content` compares raw bytes, and `BAD_TOKEN` is checked against the body *and every response header*. A difference between "no credential" and "wrong credential" tells an unauthenticated prober that the endpoint exists, takes a bearer token, and that theirs was the right shape — which is most of what an attacker needs before starting.
- **`test_unset_secret_rejects_every_request` presents a CORRECT-looking credential**, among four header shapes. The dangerous implementation is the one that accepts whatever it is given when it has nothing to compare against, and a test that only sends no header would not distinguish it.
- **The 429 test uses UNAUTHENTICATED requests.** The limiter runs outside the router, so it spends a token before the handler sees anything — which is the property that bounds an anonymous flood — and it lets the test drain a bucket without writing a row.
- **`coverage` is deliberately NOT excluded from the isolation snapshot**, though `freshness` is. `sessions_in_window` and `earliest_data_at` are derived from workouts, so an Apple Health row moving either is exactly the failure criterion #4 forbids. `freshness` legitimately moves — that is the ingest working.
- **A compact seed, not `worst_case_history`.** That fixture writes ~5,200 set rows to measure a payload budget; nothing here is about size, and a smaller seed means a failure message points at a diff a person can read.
- **HEALTH-06 was NOT marked complete.** See Requirements Status.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking] The plan's prescribed import is forbidden by an existing boundary guard**

- **Found during:** Task 1, immediately after the first GREEN run
- **Issue:** The plan's `<interfaces>` block and action text both prescribe `from app.integrations.health_auto_export.schemas import HAEPayload` in the route, and `HAEPayload.model_validate_json(bytes(body))` in the handler. `test_health_auto_export_isolation.py` (plan 08-04) forbids exactly that import string in any module outside the package, and its docstring names routes explicitly: *"If an HAE Pydantic model or an HAE metric name is imported by `db/`, `analytics/` **or a route**, that change stops being a one-package problem."* The fast suite went red on the commit that introduced it. This is also a CLAUDE.md constraint (provider isolation), which takes precedence over plan text.
- **Fix:** Added `parse_payload(raw: bytes) -> HAEPayload` to `ingest.py` — the module 08-06 already documents as "the whole inbound path" — and had it raise `HAEPayloadError`. That error type was defined by plan 08-04, documented as *"Wraps a pydantic `ValidationError` WITHOUT reproducing its message"*, and **raised by nothing in the repository**: it was built for precisely this consumer and had been waiting for it. The route now imports only `ingest` and `errors`, holds the *result* of a parse without naming the type that produced it, and catches a value-free exception instead of a `ValidationError` whose `__str__` renders `input_value=...`.
- **Why not the alternatives:** Importing via the package `__init__` would be evading a guard rather than satisfying it; widening the guard to permit routes would weaken an architecture constraint to make new code pass.
- **Files modified:** `backend/app/integrations/health_auto_export/ingest.py`, `backend/app/api/routes/health_ingest.py`
- **Verification:** `test_health_auto_export_isolation.py` passes unchanged (all 5 cases); `test_valid_json_that_is_not_an_hae_envelope_is_a_400` asserts the logged reason is the class name `HAEPayloadError` and that `input_value` appears nowhere in the line
- **Committed in:** `e8c4076`

**2. [Rule 1 — Correctness of instructions] Three of Task 1's acceptance greps contradict the code the same task prescribes**

- **Found during:** Task 1 verification. Same class of internally-contradictory criteria plans 08-01, 08-03 and 08-06 each recorded.
- **Issue:**
  - (a) `python3 -c "s.index('health_ingest.router') < s.index('app.mount(\"/\", mcp_app)')"` must print `True`. It prints **False on a correct file**, and would have before this plan touched anything: `main.py:67` has spelled `app.mount("/", mcp_app)` inside the rate-limiter comment since Phase 7, so the *first* occurrence of that string precedes any possible `include_router` line. The check is unsatisfiable by construction.
  - (b) `grep "str(exc)"` must return nothing, while the action block requires the comment *"Never `str(exc)`"*.
  - (c) `grep -E "user_id.*payload|payload.*user_id"` must return nothing, while the action block prescribes the line `sessionmaker, user_id=DEFAULT_USER_ID, payload=payload` — which matches it.
- **Fix:** (a) Replaced with a *structural* assertion in `test_the_router_is_registered_before_the_catch_all_mount`, comparing indexes in `app.router.routes` — what Starlette actually resolves against. It is strictly stronger: it fails on a broken file (mutation-verified) where the text search fails on a correct one, and it cannot be "fixed" by deleting an explanatory comment. (b) Reworded to "Never the exception's rendered text", preserving the warning; grep now returns 0. (c) The intent — no payload field reaches `user_id` — is satisfied and was verified by reading: `DEFAULT_USER_ID` is a module constant and nothing in the handler indexes the payload. The grep cannot express that and is left unsatisfied deliberately rather than by contorting the call.
- **Files modified:** `backend/app/api/routes/health_ingest.py`, `backend/app/main.py`, `backend/tests/test_health_ingest_route.py`
- **Committed in:** `e8c4076`, `e5645b7`

**3. [Rule 2 — Missing critical] The plan's inventory guard, written as specified, would have asserted nothing**

- **Found during:** Task 2
- **Issue:** The plan specifies `paths = {r.path for r in app.routes if isinstance(r, APIRoute)}`. FastAPI 0.141.1 does not flatten `include_router` into `app.routes`: it appends an `_IncludedRouter` whose own `path` is `None`, with the real `APIRoute` objects on `original_router`. That set comprehension evaluates to the **empty set**, and `assert paths == {...}` would have failed immediately — or, had the expected set been "adjusted" to match as the plan invites, passed forever regardless of what was registered. The plan anticipated a different discrepancy (doc routes being `APIRoute` instances); the real one is structural.
- **Fix:** A recursive walk through `original_router`, plus `test_the_route_walk_actually_finds_routes` asserting `/health` is found — so a future FastAPI change that breaks the walk fails loudly instead of silently.
- **Verification:** confirmed empirically against the live app: `app.routes` yields 4 `Route` + 2 `_IncludedRouter` + 1 `Mount`, and the recursive walk returns exactly `{/health, /api/v1/ingest/health-auto-export}`, agreeing with `app.openapi()["paths"]`
- **Committed in:** `e5645b7`

**4. [Rule 1 — Bug] The criterion-#4 test could not fail, and the mutation check is what proved it**

- **Found during:** Task 3 mutation testing
- **Issue:** With a gapless 35-day weigh-in seed, injecting an `apple_health` `body_measurements` row changed **no** analytics answer and the criterion test passed. The cause is `_dedupe_by_day`: it does not filter by source, and it orders `(measured_on, source)`, so `'apple_health'` sorts before `'hevy'` and is overwritten on any day that already has a Hevy weigh-in. A leak is therefore invisible on a fully-covered series and wins only on a day Hevy has no row for. This is `PITFALLS.md` Pitfall 9 in miniature, and the test as first written asserted that a leak is *invisible*, not that it is *absent*.
- **Fix:** `MISSED_WEIGH_IN_DAYS = frozenset({2, 3})` — two skipped days inside the 7-day window, which needs 3 measured days of 7 and therefore still has 5. Re-running the same mutation now fails, naming `'body_weight_trend'`. Both the constant and the seed carry the full reasoning, since the gap looks like sloppiness to anyone who does not know why it is there.
- **Files modified:** `backend/tests/test_health_ingest_isolation.py`
- **Committed in:** `e6f90da`

**5. [Rule 1 — Bug] Two isolation tests leaked committed rows into each other**

- **Found during:** Task 3
- **Issue:** `test_no_hevy_sourced_row_lands_in_health_daily_metrics` and `test_the_ingest_actually_wrote_something` need no Hevy history and so do not request `committed_history` — and therefore inherit none of its purge teardown. The first left 13 committed rows behind and the second then counted them as its own first delivery's output. It **passed alone and failed in a full-file run**, which is the signature of exactly this.
- **Fix:** A module-level autouse fixture purging `health_daily_metrics` and `sync_state` for `DEFAULT_USER_ID` before *and* after every test, using the test's own session so a second connection cannot block on rows the first still holds.
- **Committed in:** `e6f90da`

**6. [Rule 1 — Bug] My own assertion, not the code: reported writes need not equal stored rows**

- **Found during:** Task 3
- **Issue:** `test_the_ingest_actually_wrote_something` asserted `stored == sum(written)` and failed 13 != 14. The code is right and the assertion was wrong: `activity_and_nutrition` and `unrecognized_and_sourceless` both carry `step_count` from `iPhone` on the same local day, so the later delivery UPSERTS. The gap is HEALTH-09 working.
- **Fix:** Equality is asserted against the FIRST delivery into an empty table — the only point at which it must hold — and the three-fixture case is bounded `after_first <= stored <= sum(written) + after_first`, which additionally catches replace semantics quietly becoming additive.
- **Committed in:** `e6f90da`

**7. [Rule 1 — Bug] The inventory guard tripped on another module's test-only route**

- **Found during:** the first full-suite run
- **Issue:** `test_secret_redaction.py` registers `/__test_boom__` on the **shared** `app` object at module import (during collection), so it is visible to the inventory guard for the whole session. The guard failed in a full run and passed in a file-scoped one.
- **Fix:** `TEST_ONLY_ROUTES` is subtracted — but only after the guard asserts each such path is **absent from `app/main.py`'s source**. A production route sneaking in under that name still fails the test rather than being waved through by the exemption.
- **Committed in:** `e6f90da`

---

**Total deviations:** 7 auto-fixed (1 Rule 3 blocking, 2 Rule 2/1 missing-or-broken guard, 4 Rule 1 bugs — three of them in my own test code, found by mutation or by a full-suite run). No Rule 4 architectural decisions arose.

**Impact on plan:** No scope creep and no interface drift. `ingest_payload`'s signature is untouched, so 08-06's contract ships exactly as promised. Deviation 1 is the only one that changes a file outside `files_modified`, and it adds a function rather than altering one. Deviations 3, 4, 5 and 7 each turned a guard that could not fail into one that does.

## Threat Model Coverage

All ten `mitigate` dispositions are implemented and test-guarded; the one `accept` remains accepted.

| Threat ID | Where it landed |
|-----------|-----------------|
| T-08-42 (unauthenticated write path) | `verify_bearer` as the first statement after `get_settings()`; `test_no_unauthenticated_fastapi_route_was_added` pins the inventory, with its own non-vacuity guard |
| T-08-43 (route below the catch-all) | `include_router` between `health.router` and the mount; asserted over HTTP AND structurally against `app.router.routes`. Mutation: 7 of 10 tests fail |
| T-08-44 (401 revealing which check failed) | One frozen `_UNAUTHORIZED_BODY`; `test_401_leaks_nothing` compares raw bytes and scans every response header for `BAD_TOKEN` |
| T-08-45 (oversized body -> OOM 503) | Declared length then streamed length, both before the parse; proven by the absence of every post-parse log event. Mutation: removing the stream branch fails exactly the undeclared case |
| T-08-46 (unauthenticated flood buffering bodies) | Credential precedes any body read; `test_an_over_limit_request_429s_from_the_ingest_bucket` drains the bucket with UNAUTHENTICATED requests, which is also the proof that the limiter spends a token before the handler runs |
| T-08-47 (`ValidationError` text in a log line) | `parse_payload` raises the value-free `HAEPayloadError`; the log carries `type(exc).__name__` and the test asserts `input_value` appears nowhere in the rendered line |
| T-08-48 (health values in the 202) | Five integer counts and a status string; `ACCEPTED_KEYS` pins the exact key set |
| T-08-49 (payload-supplied tenant) | `DEFAULT_USER_ID` from a module constant; nothing in the handler indexes the payload |
| T-08-50 (Apple Health altering training answers) | `test_health_ingest_isolation.py` — snapshot, ingest, compare, with four row-count proofs and two guards on the guards. Mutation-verified sensitive after the gap fix |
| T-08-51 (unhandled failure returning a traceback) | **Accepted**, as planned. No route-level handler; `main.py`'s D-05 handler is unchanged and the omission is documented in the handler's docstring |

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: information-disclosure | `backend/app/analytics/bodyweight.py` | Not new surface from this plan, but newly *measured* by it: `_weight_rows` applies no `source` predicate and `_dedupe_by_day` orders `(measured_on, source)`, so any future third source alphabetically before `'hevy'` silently wins on days Hevy has no row for and is silently discarded on days it does. Today D-01 keeps `apple_health` out of that table entirely, so this is latent rather than live — but it means the write-time exclusion is the ONLY thing standing between a third source and a changed body-weight trend. Phase 11 should treat this as a read-side fix, not only a write-side one. |

## Known Stubs

None. Every branch of the route is reachable and exercised: 401 (four header shapes plus the unset-secret case), 413 (declared and streamed), 400, 202, and 429.

## Requirements Status

- **HEALTH-07** — marked complete. 08-03 explicitly deferred it here with the note *"the credential and transport budget exist, but the authenticating receiver is plan 08-07"*. The receiver now exists, authenticates, and is proven over HTTP to reject a missing credential, a wrong one, and an unset server-side secret identically and without writing.
- **HEALTH-08** — marked complete. The write-time exclusion was implemented in 08-05 and unit-tested there; this plan asserts it **at the database** after a real ingest, which is the form the requirement's "preventing double-counting" claim actually needs. Mutation-verified.
- **HEALTH-09** — already complete (08-06). Additionally re-exercised here through the overlap between two fixtures.
- **HEALTH-06 — deliberately left PENDING.** It reads "*User's Apple Health activity data ... **syncs into** BRETT via a Health Auto Export webhook receiver*". The receiver is finished and proven against three real captured device payloads, but nothing syncs from the actual phone until the service is deployed with `HEALTH_INGEST_SECRET` bound and the Health Auto Export automation is pointed at the URL — both of which are plan 08-08. Marking it now would be a completion claim about a device that has never sent a request. **Action for the orchestrator: HEALTH-06 belongs to 08-08.**

## Issues Encountered

- **The worktree arrived on the WRONG base — the seventh consecutive time.** `git merge-base HEAD 4ca4e90` returned `b1d3eef` (`chore: finalize STATE.md after v1.0 milestone close`), which *equalled* `HEAD`: the worktree was created from the old milestone-close commit and was an **ancestor** of the required base, missing all of waves 1-4. Every file this plan builds on — `ingest.py`, `auth.py`, `middleware.INGEST_PATH_PREFIX`, the HAE fixtures — was absent from the filesystem. Hard-reset to `4ca4e9075835010b5a309eb41d8d933e180553d3` and confirmed `git rev-parse HEAD` matched before touching anything. Safe: fresh worktree, `git status` clean. **Seven for seven. This belongs in the worktree-creation step, not in seven separate startup checks.**
- **No `.venv` in the worktree.** `uv sync --frozen --group dev` bootstrapped from cache. `[tool.uv] default-groups = []` means `--group dev` is required — the fifth plan to note this.
- **`git clean` was never run**, per the destructive-git prohibition. The single startup `reset --hard` was the only history-affecting operation. All four mutations were applied through `.bak` copies in the scratchpad and reverted with `git status` verified clean afterwards; no `.bak` file was left behind.

## Deferred Issues

1. **`ruff format --check` reports 18 files that would be reformatted, all pre-existing.** All six files this plan created or modified are clean. `backend/tests/conftest.py` has now been recorded by **five** consecutive plans (08-01, 08-04, 08-05, 08-06, 08-07). One `uv run ruff format backend/` clears the whole backlog and it should be done centrally rather than noted a sixth time.
2. **The whole-batch ingest error path still has no test** (carried from 08-06). This plan wires the route, so a monkeypatched `sessionmaker` is now in play and the 500-with-correlation-id path is cheaply reachable. Worth adding in 08-08 or a follow-up.
3. **`test_health_ingest_route.py` and `test_health_ingest_auth.py` each carry a near-identical `_run`/`_health_row_count`/`_purge` trio.** Deliberate for now — each test module is self-contained and neither imports the other — but a third copy would be the point to lift them into `conftest.py`.
4. **Assumption A1 remains open**: that HAE's webhook spells Hevy as `"Hevy"`. Only 08-08's capture from a real training day can settle it. Everything HEALTH-08 claims rests on it.

## User Setup Required

None for this plan. Two prerequisites carried forward, both belonging to 08-08 and both now blocking a working deployment rather than merely a future one:

- **`brett-health-ingest-secret` must exist in Google Secret Manager** before the next `./scripts/deploy-cloud-run.sh`, or the deploy fails at `--set-secrets` resolution (carried from 08-03). The route now *reads* that secret, so until it is bound the deployed endpoint answers 401 to everything — correctly, and uselessly.
- **Health Auto Export's aggregation interval must be set to daily** on the device (carried from 08-06), and its REST automation pointed at `https://<service>/api/v1/ingest/health-auto-export` with the `Authorization: Bearer <secret>` header.

## Next Phase Readiness

**Ready for 08-08.** The endpoint the deploy and the device setup both target now exists and has a pinned contract:

```
POST /api/v1/ingest/health-auto-export
Authorization: Bearer <HEALTH_INGEST_SECRET>
Content-Type: application/json

202 -> {"status","rows_upserted","rows_skipped","datapoints_seen","metrics_unrecognized"}
401 -> {"error":"unauthorized"}       (absent, wrong, or unconfigured credential)
413 -> {"error":"payload_too_large"}  (before any parse)
400 -> {"error":"invalid_payload"}    (not an HAE envelope)
429 -> {"error":"rate_limited"}       (dedicated ingest bucket)
```

Three things 08-08 should carry:

- The 202 body is safe to log and safe to show the user: counts only, no value.
- Health Auto Export has no documented retry, so a 429 or a 413 is permanent loss of that window. The 1Gi memory setting from 08-03 and the daily aggregation interval are what keep both rare.
- `test_no_unauthenticated_fastapi_route_was_added` will fail on any new FastAPI route. That is intended — update `EXPECTED_FASTAPI_ROUTES` only after confirming the new route authenticates.

## Self-Check: PASSED

- All three created files verified present: `backend/app/api/routes/health_ingest.py`, `backend/tests/test_health_ingest_route.py`, `backend/tests/test_health_ingest_isolation.py`.
- All four claimed commit hashes verified in `git log`: `4a47307`, `e8c4076`, `e5645b7`, `e6f90da`.
- `must_haves` artifacts satisfied: `health_ingest.py` contains `verify_bearer`; `test_health_ingest_isolation.py` provides the criterion-#4 proof.
- All three `key_links` verified: `main.py` -> `health_ingest.router` registered above the mount (asserted structurally, mutation-proven); route -> `ingest_payload(request.app.state.sessionmaker, ...)`; route -> `DEFAULT_USER_ID` resolved server-side.
- `uv run pytest` — **851 passed**, up 18 from the wave-4 base of 833.
- `uv run mypy backend/app` — 73 source files, clean. `uv run ruff check backend/app backend/tests` — all checks passed.
- Pre-parse ordering verified directly: `request.stream()` at line 111, `parse_payload` at line 125.
- No file deletions in any commit (`git diff --diff-filter=D --name-only 4ca4e90..HEAD` empty). Working tree clean, no untracked files.
- No shared orchestrator artifacts modified: `STATE.md` and `ROADMAP.md` are untouched by every commit in this plan. `REQUIREMENTS.md` is modified deliberately and documented above.

---
*Phase: 08-apple-health-nutrition-ingest*
*Completed: 2026-09-02*
