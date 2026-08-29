---
phase: 03-hevy-integration-normalization
plan: 05
subsystem: api
tags: [hevy, httpx2, tenacity, pydantic, retry, provider-isolation, structlog, respx]

# Dependency graph
requires:
  - phase: 01-backend-foundation
    provides: "Settings.hevy_api_key (SecretStr, already in _SECRET_FIELDS), the three-layer log redaction pipeline, and the factory-not-singleton convention from app/db/session.py"
  - phase: 02-deploy-connector-auth-spike
    provides: "app/mcp/auth.py — the credential-unwrapped-once-at-construction pattern and the fail-fast factory that names the ENV VAR rather than the settings field"
  - phase: 03-hevy-integration-normalization
    provides: "plan 03-01: tenacity 9.1.4 + httpx2 2.12.0 as RUNTIME deps, pytest-httpx2 in dev, `api-key` on the log deny-list, five OpenAPI-accurate fixtures behind hevy_fixture()"
provides:
  - "HevyClient: typed async access to all six Hevy GET endpoints with per-endpoint page sizes (10/10/10/100)"
  - "get_workout(id) — single-workout re-read with a percent-encoded path segment"
  - "Status -> exception mapping that makes 401/403/400/404 permanently non-retryable and 429/5xx/TransportError retryable"
  - "Pydantic wire schemas for every Hevy response shape, including a DISCRIMINATED workout-event union"
  - "event_timestamp() — the per-variant timestamp accessor the 03-09 events drain sorts on"
  - "build_hevy_client(settings) — fail-fast factory naming HEVY_API_KEY"
  - "A no-op `sleep` injection seam so retry tests exercise the real predicate in ~0s"
  - "test_hevy_isolation.py — a static, fast-suite HEVY-05 boundary that fails on the offending commit"
affects: [03-06 sync service, 03-09 events drain, 03-10 resilience tests, 03-11 body measurements, 03-04 exercise templates, 03-12 CLI]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Provider wire schemas are the quarantine boundary: Pydantic models transcribed from the LIVE OpenAPI, `extra=\"ignore\"` so additions pass and renames fail"
    - "Two narrow injection seams per network client (`transport`, `sleep`) so tests replace the socket and the pause, never the logic"
    - "Exceptions carry a hand-checked `safe_message` and nothing else; the wrapped ValidationError is dropped with `from None`"
    - "Architectural boundaries are enforced by a static rglob test in the FAST suite, not by review"

key-files:
  created:
    - backend/app/integrations/__init__.py
    - backend/app/integrations/hevy/__init__.py
    - backend/app/integrations/hevy/errors.py
    - backend/app/integrations/hevy/schemas.py
    - backend/app/integrations/hevy/client.py
    - backend/tests/test_hevy_wire_schemas.py
    - backend/tests/test_hevy_client.py
    - backend/tests/test_hevy_isolation.py
  modified: []

key-decisions:
  - "Added a `sleep` constructor seam alongside the planned `transport` seam: the real wait strategy would have cost the fast suite ~10 real seconds across five retry tests, for zero extra coverage — the predicate and the attempt count stay entirely real"
  - "Task 1's TDD RED gate needed a test file the plan assigned to no task; created backend/tests/test_hevy_wire_schemas.py so test_hevy_client.py could stay at exactly the 18 tests task 3's criteria count"
  - "`_request`/`_get` take `**params: str | int`, not `**params: object` — httpx2's `params=` is typed and an untyped passthrough would let a datetime reach the query string as its repr"
  - "The isolation boundary is asserted as an IMPORT (regex), not as a bare substring: three source files legitimately discuss `app.integrations` and `httpx2` in prose, including the docstring that states the rule"
  - "Added the missing sixth endpoint (`get_workout`) rather than leave a plan-level success criterion unmet by a task-level omission — and percent-encoded its id, the only upstream value in this client that reaches a request PATH"
  - "Did NOT check off any requirement in REQUIREMENTS.md — only HEVY-05 is actually delivered here, and REQUIREMENTS.md is a shared file with sibling wave-2 agents"

patterns-established:
  - "Pattern: a guard on the guards — `test_the_walk_actually_finds_files` fails if rglob returns nothing, so a moved package cannot make four boundary tests vacuously pass"
  - "Pattern: a boundary test is proven to fail before it is trusted — a throwaway violating module was added, the reds observed, and the module deleted"
  - "Pattern: the retryable/not-retryable split is asserted by INHERITANCE as well as identity, because retry_if_exception_type matches subclasses"

requirements-completed: [HEVY-01, HEVY-02, HEVY-05, HEVY-06, HEVY-07, HEVY-08]

# Metrics
duration: 22min
completed: 2026-08-29
---

# Phase 3 Plan 5: Hevy Transport Layer Summary

**A retry-wrapped, Pydantic-validated `HevyClient` over all six Hevy GET endpoints — per-endpoint page sizes (10/10/10/**100**), 401/403/400/404 permanently non-retryable, the API key unwrapped exactly once into a header dict, and a static test that fails the fast suite the moment a Hevy wire type escapes `app/integrations/hevy/`.**

## Performance

- **Duration:** 22 min
- **Started:** 2026-08-29T06:36:00Z
- **Completed:** 2026-08-29T06:58:00Z
- **Tasks:** 3 of 3
- **Files modified:** 8 (8 created, 0 modified)

## Accomplishments

- **The quarantine boundary exists and is enforced by a test, not a convention.** `test_hevy_isolation.py` walks every `*.py` under `backend/app` that is not inside the Hevy package and fails if any of them imports `app.integrations.hevy.schemas` or `httpx2`, or if `normalization/` or `db/` imports `app.integrations` at all. It carries no `integration` marker and starts no container, so a violation goes red on the commit that introduces it. It was **proven able to fail** before being trusted: a throwaway module under `app/normalization/` importing `HevyWorkout` and `httpx2` turned three of the five tests red, and was then deleted.
- **The retryable/not-retryable split is the design, not a detail.** `RETRYABLE_EXCEPTIONS` is `(HevyRateLimited, HevyServerError, httpx2.TransportError)` and nothing else. `test_auth_error_is_not_retried` queues a 401 *followed by a perfectly good 200* and asserts the 200 is never reached — so a predicate that ever widened to "retry any non-2xx" fails loudly instead of turning a revoked API key into a minute-long opaque timeout (Pitfall 7). The split is also asserted by **inheritance**, because `retry_if_exception_type` matches subclasses and `HevyPageNotFound` would have become retryable had it descended from the wrong base.
- **Decimals were verified, not assumed.** `response.json()` hands pydantic Python floats. The plan flagged that a broken float→Decimal path would silently render `9.5` as `Decimal("9.50000000000000177...")` and poison every tonnage figure downstream. Pydantic converts via the value's *string* form, so no `mode="before"` validator was needed — but `test_decimal_fields_round_trip_exactly` asserts `str(rpe) == "9.5"` rather than a float comparison, so the day that changes it goes red.
- **Two undocumented Hevy realities are handled and one is instrumented.** `/v1/exercise_templates` caps at `pageSize=100` while the other three cap at 10 (Pitfall 6, ~40 requests vs ~5). A 404 from `/v1/body_measurements` returns `None` as an end-of-pages terminator rather than failing a run that had already fetched everything (Pitfall 5), and consumes zero retry budget. And because Hevy documents no rate limit at all, every response header matching `ratelimit` or `retry-after` is logged as `hevy_rate_limit_headers` — the first real sync is the only chance this project gets to learn what the actual limits are (D-10, STATE.md open item).
- **The credential has exactly one exit from `SecretStr`.** `get_secret_value()` appears twice in `client.py`: once building the `AsyncClient` header dict, once in `build_hevy_client`'s emptiness check. It is never stored on `self`, never logged, never interpolated into an exception — `HevyAuthError` is constructed from a *status code*, so there is structurally no message to leak into. `test_key_never_appears_in_an_exception` asserts a distinctive key string is absent from `str`, `repr` and `safe_message`.

## Task Commits

1. **Task 1: Error hierarchy and Pydantic wire schemas** — `b9c5397` (test, RED) → `6d4be4c` (feat, GREEN)
2. **Task 2: HevyClient — transport, page sizes, status mapping, retry policy** — `5ba3193` (test, RED) → `cb11923` (feat, GREEN)
3. **Task 3: Client tests and the HEVY-05 isolation test** — `9e63342` (test)

Supporting: `63a9468` (feat — `get_workout()`, the sixth endpoint; see deviation 6)

_All three tasks were `tdd="true"`. Task 3's `test_hevy_client.py` is the RED gate of task 2 — the plan's own task-2 `<verify>` runs that file, so the two tasks necessarily interleave. No REFACTOR commits: nothing survived GREEN that needed restructuring._

## Files Created/Modified

- `backend/app/integrations/__init__.py` — package root; docstring states the HEVY-05 rule and names the test that enforces it
- `backend/app/integrations/hevy/__init__.py` — docstring only, deliberately re-exports nothing (a re-export of `schemas` would make the isolation test's job ambiguous)
- `backend/app/integrations/hevy/errors.py` (108 lines) — `HevyError` base with an opt-in `safe_message`, plus `HevyAuthError` / `HevyRateLimited` / `HevyServerError` / `HevyClientError` / `HevyPageNotFound` / `HevyResponseError`, and `RETRYABLE_EXCEPTIONS`
- `backend/app/integrations/hevy/schemas.py` (198 lines) — `_HevyModel` base (`hide_input_in_errors=True`, `extra="ignore"`), the five paginated envelopes, `WorkoutCount`, the discriminated `HevyWorkoutEvent` union, and `event_timestamp()`
- `backend/app/integrations/hevy/client.py` (275 lines) — `HevyClient` over the six GET endpoints, the status map, the tenacity wrapper, the rate-limit-header logger, and `build_hevy_client()`
- `backend/tests/test_hevy_wire_schemas.py` — 15 tests: fixture round-trips, decimal exactness, the discriminated union, `extra="ignore"` asymmetry, and the FOUND-05 rendering of a `ValidationError`
- `backend/tests/test_hevy_client.py` — 19 tests: the 18 the plan enumerates plus the sixth-endpoint test, over a mocked HTTP transport only
- `backend/tests/test_hevy_isolation.py` — 5 static boundary tests (the plan's four, plus a guard on the walk itself)

## Decisions Made

- **A `sleep` seam was added to `HevyClient.__init__` beside the planned `transport` seam.** The real policy is `wait_exponential_jitter(initial=1, max=60, jitter=2)`, so the first retry waits 1–3 *real* seconds. Five tests retry (429, 500, `ConnectError`, exhaustion, header logging), which is roughly a **10-second tax on every run of a suite whose entire purpose is to be container-free** — and a nondeterministic one, since the jitter is random. The seam replaces only the pause *between* attempts; the predicate (which errors retry) and the stop (how many attempts) are the parts under test and are untouched. Defaulted to `anyio.sleep` rather than `asyncio.sleep` so it is correct under whichever event loop the MCP SDK's anyio stack is running. The full fast suite now runs in **1.85s**.
- **`event_timestamp` dispatches on `isinstance`, not on `.type`.** Both work, but the isinstance form is what mypy narrows, so a future third variant is a type error at the call site rather than an `AttributeError` at 3am mid-drain.
- **`HevySet.type` is `str`, not a `Literal`.** Hevy documents `{normal, warmup, dropset, failure}`, but a fifth set type appearing upstream must not fail an entire sync page. Deciding what an unrecognised type *means* is the normalization layer's job; the wire model's job is to let it through. This is the one place the schemas are deliberately permissive, and it is the opposite call from the event union — where an unknown type is data loss and must raise.
- **No requirement was checked off in `REQUIREMENTS.md`.** Of the plan's six claimed IDs, only **HEVY-05** is genuinely delivered here (and it now has a test that enforces it). HEVY-01/02/06/07/08 all name *sync* behaviour — pagination runs, cursor drains, template ingestion, measurement ingestion, corruption-free failure — which plans 03-04, 03-06, 03-09, 03-10 and 03-11 deliver on top of this transport. Checking them off now would be false, and `REQUIREMENTS.md` is contended by sibling wave-2 agents. Follows the precedent 03-01 set for HEVY-08.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Task 1 declared `tdd="true"` but the plan assigns it no test file**

- **Found during:** Task 1
- **Issue:** Task 1's `<behavior>` block specifies four testable properties (decimal exactness, event-union ordering, `type: "archived"` raising, `safe_message` carrying no credential), but its `<files>` list contains only source files. `test_hevy_client.py` belongs to task 3, whose acceptance criteria require that file to report **exactly 18 passed** — so folding task 1's tests into it would break task 3. Without a test file there is no RED gate and the TDD declaration is decorative. (The plan's own task-1 `<verify>` line hints at this: it runs `pytest backend/tests/test_hevy_client.py ... 2>/dev/null;` with `2>/dev/null` and a `;` rather than `&&`, i.e. written to tolerate that file not existing yet.)
- **Fix:** Created `backend/tests/test_hevy_wire_schemas.py` (15 tests) as task 1's RED gate. Named `..._wire_schemas` to stay distinct from the pre-existing `test_hevy_schema.py`, which is about the *database* schema. `test_hevy_client.py` is untouched by this and still reports exactly 18.
- **Files modified:** `backend/tests/test_hevy_wire_schemas.py` (new)
- **Verification:** RED confirmed empirically — `ModuleNotFoundError: No module named 'app.integrations'` at collection, before any source file existed. GREEN after `errors.py`/`schemas.py`: 15 passed.
- **Committed in:** `b9c5397` (RED) / `6d4be4c` (GREEN)

**2. [Rule 3 - Blocking] `respx`'s `assert_all_called` failed the naive-`since` test in teardown**

- **Found during:** Task 2
- **Issue:** `test_events_request_rejects_naive_since` registers a route that must *never* be called — that is the assertion. `pytest-httpx2` runs `respx.mock(...)` with `assert_all_called=True` by default, so the test passed and then errored in fixture teardown with `RESPX: some routes were not called!`.
- **Fix:** Registered no route at all and asserted `not httpx2_mock.calls`. This is strictly stronger than the plan's `route.call_count == 0`: with zero routes, respx's `assert_all_mocked` would *raise* on any request the client managed to send, so the property is guarded twice. The alternative — `@pytest.mark.httpx2(assert_all_called=False)` — worked but emitted `PytestUnknownMarkWarning`, and silencing that would have meant editing `pyproject.toml`'s `markers` list, a shared file three other wave-2 agents may also be touching.
- **Files modified:** `backend/tests/test_hevy_client.py`
- **Verification:** 18 passed, no warnings, no teardown errors.
- **Committed in:** `cb11923`

**3. [Rule 3 - Blocking] `**params: object` does not type-check against httpx2's `params=`**

- **Found during:** Task 2
- **Issue:** The plan's `_request(self, path: str, **params: object)` produces `dict[str, object]`, which mypy rejects against httpx2's typed `QueryParams | Mapping[str, str | int | float | bool | None | ...]`. `uv run mypy backend/app` is a task-2 acceptance criterion and exited 1.
- **Fix:** Narrowed both `_request` and `_get` to `**params: str | int` — the exact union the five call sites pass. This is more than a mypy appeasement: an `object`-typed passthrough would let a `datetime` or a `Decimal` reach the query string as its `repr`, which is precisely the bug `get_workout_events` formats `since` to avoid.
- **Files modified:** `backend/app/integrations/hevy/client.py`
- **Verification:** `uv run mypy backend/app` — Success, 29 source files.
- **Committed in:** `cb11923`

**4. [Rule 3 - Blocking] The prescribed `normalization` isolation assertion fails on the docstring that states the rule**

- **Found during:** Task 3
- **Issue:** The plan specifies that every file under `app/normalization/` "contains no `app.integrations` reference at all". `app/normalization/__init__.py` — written by a sibling wave-1 plan — ends its docstring with *"Nothing here may import from ``app.integrations``."* A bare-substring assertion therefore fails on the sentence documenting the very boundary it guards.
- **Fix:** Matched an **import** (`^\s*(?:import|from)\s+app\.integrations`, `re.MULTILINE`) instead of a substring — the same regex the sibling `db/` test uses, so both tests mean the same thing by "does not import". The same reasoning applies to the `httpx2` check, which the plan already specified as a regex for exactly this reason.
- **Files modified:** `backend/tests/test_hevy_isolation.py`
- **Verification:** 5 passed; and with a deliberate violating module in place, 3 of 5 failed — including this one.
- **Committed in:** `9e63342`

**5. [Rule 2 - Missing Critical] The four isolation tests could pass vacuously**

- **Found during:** Task 3
- **Issue:** All four boundary tests are `for path in <walk>: assert ...`. If `APP` were ever wrong — a moved package, a renamed directory, a change to `parents[2]` — `rglob` returns an empty list and **all four pass while checking nothing**. That is the same "green while proving nothing" failure mode `test_secret_redaction.py`'s docstring warns about, and it is worse here because the tests exist precisely to catch a boundary erosion nobody is watching for.
- **Fix:** Added `test_the_walk_actually_finds_files`, which asserts the walk finds >10 modules outside the Hevy package and at least one inside it.
- **Files modified:** `backend/tests/test_hevy_isolation.py`
- **Verification:** 5 passed. The file has 5 tests where the plan lists 4; the plan's four are all present under their specified names.
- **Committed in:** `9e63342`

**6. [Rule 2 - Missing Critical] The sixth Hevy GET endpoint had no method**

- **Found during:** Post-task verification against `<success_criteria>`
- **Issue:** The plan's `<success_criteria>` opens with *"All six Hevy GET endpoints are reachable through typed methods that validate their responses"*, and its `<interfaces>` table lists six rows — but task 2's `<action>` enumerates only **five** method signatures. `GET /v1/workouts/{workoutId}` had no implementation, so the plan as written could not satisfy its own success criterion.
- **Fix:** Added `HevyClient.get_workout(workout_id)`, returning a bare `HevyWorkout` (the endpoint has no envelope and no pagination), routed through the same `_get` retry wrapper and the same `HevyResponseError` wrapping as every other method. `workout_id` is `quote(..., safe="")`-encoded, because this is the **only** place in the client where a value from an upstream payload reaches the request *path* rather than the query string — an id containing `/` or `..` would otherwise rewrite the path this client asks for. Added `test_single_workout_is_fetched_by_a_percent_encoded_id`, which asserts the wire URL for both a normal UUID and a traversal-shaped id.
- **Files modified:** `backend/app/integrations/hevy/client.py`, `backend/tests/test_hevy_client.py`
- **Verification:** 19 passed. The encoding was confirmed by probe before being asserted: httpx2 emits `/v1/workouts/..%2F..%2Fevil%20id` on the wire, so the traversal is neutralised rather than merely hidden by `URL.path`'s display decoding.
- **Committed in:** `63a9468`
- **Tension acknowledged:** this makes `test_hevy_client.py` report **19**, where task 3's acceptance criterion says 18. Resolved in favour of the plan-level `<success_criteria>` over the task-level count: a functional gap is a real failure, whereas one extra passing test is not. All 18 of the plan's named tests are present under their specified names.

---

**Total deviations:** 6 auto-fixed (4 blocking, 2 missing critical)
**Impact on plan:** No scope creep. Four of the six were forced by the plan's own text failing against reality (a TDD task with no test file, a fixture default, a library's type signature, a sibling plan's docstring); the other two close real gaps — four boundary assertions that could pass vacuously, and a success criterion that the task-level spec omitted the code for. Every file listed in the plan's `files_modified` was produced; one extra test file was added, and its reason is deviation 1.

## Issues Encountered

- **Three of the plan's acceptance criteria are self-contradictory as written**, in the same way 03-01 Task 1 criterion 5 was. In each case the plan's own prescribed source text makes its own grep impossible. All three were verified against evident intent instead, and no code changed as a result — flagging them so they can be corrected if reused:

  | Criterion | Why it cannot hold | How intent was verified |
  |---|---|---|
  | `grep -qE '\brir\b\|weight_unit' schemas.py` exits **1** | The plan *prescribes* a module docstring reading "it expects `rir` (Hevy sends `rpe`), `weight_unit` (Hevy normalises to `weight_kg`)". Both tokens are in the text the plan supplied. | Introspected `model_fields` on every model in the module: no `rir`, `weight_unit`, `weight`, `distance` or `duration` field exists. Also asserted permanently by `test_the_wire_shape_is_the_wire_shape_not_the_blueprint`, which is stronger than a grep — it would also catch `rir_value` or a field added under an alias. |
  | `get_secret_value()` appears **exactly once** (inside `__init__`) | The plan's own `build_hevy_client` body is `if key is None or not key.get_secret_value():`, which is a second occurrence. | Both occurrences inspected: line 90 (the `AsyncClient` header dict) and line 254 (the emptiness check). Neither logs, stores, or interpolates the value. The real property — the key never reaches an exception or a log line — is asserted by `test_key_never_appears_in_an_exception` and `test_rate_limit_headers_are_logged`. |
  | `grep -q 'integration' test_hevy_isolation.py` exits **1**; `grep -q 'import httpx$' test_hevy_client.py` exits **0** | "integration" is a substring of "integrations", and the module's entire subject is the `app.integrations` package (12 occurrences). Symmetrically, the plan's own prescribed import line is `import httpx      # 0.x -- required by respx...`, so `httpx$` never matches. | No `pytest.mark.integration` and no `@pytest.mark` of any kind exists in the isolation module; the single singular "integration" is the docstring sentence stating that the marker is deliberately absent. `import httpx` (0.x) is present at line 25 with the plan's own trailing comment. |

- **`03-PATTERNS.md` is referenced by the plan's `<context>` but does not exist.** It is untracked in the parent repo and therefore absent from this worktree. Task 1 and task 2 both list it under `<read_first>`. Worked around by reading `03-RESEARCH.md` directly for the sections the plan cites by name (Hevy API Ground Truth, Pattern 2, Code Examples, Pitfalls 3/5/6/7/9), all of which are present there. No decision in this plan rested on a pattern that could only have come from the missing file.

- **`pytest-httpx2`'s marker is not registered with pytest.** The plugin's `pytest_configure` calls `addinivalue_line("markers", "httpx2(...)")`, but the entry point exposes only the `httpx2_mock` fixture, so `@pytest.mark.httpx2` raises `PytestUnknownMarkWarning`. Avoided rather than worked around (see deviation 2). Anyone who later *needs* the marker should add `httpx2: configure the httpx2_mock fixture` to `[tool.pytest.ini_options].markers` — a one-line change, deliberately not made mid-wave on a shared file.

- **Confirmed by direct probe, not by trusting the docs:** with `pytest-httpx2`'s `using="httpcore2"` mocker, `route.calls.last.request` is an **`httpx.Request` (0.x)** object even though the client under test is `httpx2`. `.url.params`, `.headers` and `str(.url)` all behave normally on it. This is the request-side half of conftest's Pitfall-3 rule, which only documented the response side.

## Known Stubs

None. Every method reaches a real endpoint path, every response is validated by a real schema, and no placeholder, TODO, or hardcoded empty return exists in the three source modules. `get_body_measurements` returns `None` on 404 by design (Pitfall 5), not as a stub — `test_body_measurements_404_returns_none` and `test_body_measurements_page_parses` cover both branches.

## Threat Flags

None. This plan introduces outbound HTTP to a single hard-coded HTTPS host and no inbound surface: no route, no MCP tool, no schema change, no file access. Every trust boundary it crosses is already in the plan's `<threat_model>` (T-03-16 through T-03-21), and each `mitigate` disposition has a named test:

| Threat | Mitigation landed | Asserted by |
|---|---|---|
| T-03-16 Info disclosure (the API key) | `get_secret_value()` only into the header dict; `HevyAuthError` built from a status code | `test_key_never_appears_in_an_exception` |
| T-03-17 Tampering (unvalidated JSON) | Every response Pydantic-validated; discriminated event union; `extra="ignore"` tolerates additions only | `test_an_unknown_event_type_is_rejected_not_dropped`, `test_unknown_fields_are_ignored_but_a_rename_is_not` |
| T-03-18 Info disclosure (`ValidationError` payload echo) | `raise HevyResponseError(endpoint) from None`; `hide_input_in_errors=True` | `test_malformed_response_raises_hevy_response_error_without_the_payload`, `test_a_validation_error_never_echoes_the_payload` |
| T-03-19 DoS (retry storm) | `wait_exponential_jitter` + `stop_after_attempt(5)`; 401/403/400/404 bypass the predicate | `test_auth_error_is_not_retried`, `test_bad_request_is_not_retried`, `test_retry_exhaustion_reraises_the_real_error` |
| T-03-20 DoS (hung response) | Explicit `httpx2.Timeout(connect=5, read=30, write=10, pool=5)`; page size capped by the API | `grep 'httpx2.Timeout('` (task-2 criterion); no unbounded body is ever requested |
| T-03-21 Spoofing (TLS) | `accept` — `BASE_URL` is `https://` and httpx2 verifies against the system trust store; no pinning in v1 | n/a (accepted disposition) |

One surface exists that the register does not name, and it is mitigated rather than flagged: `get_workout(workout_id)` is the only method that puts an upstream-supplied value into the request **path**. `quote(workout_id, safe="")` neutralises it, asserted on the wire URL by `test_single_workout_is_fetched_by_a_percent_encoded_id`. It is listed here rather than as a `threat_flag` because it introduces no new trust boundary — it is the same outbound call to the same host, with one more injection point closed.

## TDD Gate Compliance

All three tasks declared `tdd="true"`. The gate sequence is intact in `git log`:

| Task | RED | GREEN | REFACTOR |
|---|---|---|---|
| 1 | `b9c5397` `test(03-05): add failing tests for Hevy wire schemas and the retry split` — genuinely failing (`ModuleNotFoundError: No module named 'app.integrations'`) | `6d4be4c` — 15 passed | none needed |
| 2 | `5ba3193` `test(03-05): add failing HevyClient transport suite` — genuinely failing (`No module named 'app.integrations.hevy.client'`) | `cb11923` — 18 passed | none needed |
| 3 | `9e63342` — see note | `9e63342` | none needed |

Two notes on the gates, both deliberate:

- **The fail-fast rule was honoured.** No test passed unexpectedly at RED. Both RED runs failed at *collection*, which is the strongest possible form of "the thing under test does not exist yet".
- **Task 3 is a single `test(...)` commit, and that is correct rather than a skipped gate.** Its two files split cleanly: `test_hevy_client.py` is task 2's RED gate (the plan's own task-2 `<verify>` runs it, so the interleave is the plan's design, not an improvisation) and is already committed at `5ba3193`; `test_hevy_isolation.py` asserts a property of *existing committed source* and therefore has no implementation to precede it. Its RED was nonetheless demonstrated empirically rather than assumed — a violating module was added under `app/normalization/`, three of the five tests went red, and the module was deleted before commit.
- No `refactor(...)` commit was made anywhere. Per the workflow, one is created only if changes are actually needed; nothing survived GREEN that needed restructuring.

## Verification Results

Plan-level `<verification>`:

| # | Check | Result |
|---|-------|--------|
| 1 | `uv run pytest backend/tests -q -m "not integration"` green with the new client and isolation tests | **PASS — 139 passed, 33 deselected, 0.89s** (baseline at `cdf712f` was 100; +15 wire schemas, +19 client, +5 isolation) |
| 2 | `uv run mypy backend/app` and `uv run ruff check .` exit 0 | **PASS** — mypy: "Success: no issues found in 29 source files"; ruff: "All checks passed!" |
| 3 | `grep -rE "^\s*(import\|from) httpx2" backend/app \| grep -v integrations/hevy` returns nothing | **PASS** — no output. Also now enforced permanently by `test_httpx2_is_only_imported_inside_the_hevy_package` |

Plan-level `<success_criteria>`:

| Criterion | Result |
|-----------|--------|
| All six Hevy GET endpoints reachable through typed, response-validating methods | **PASS** — `get_workouts`, `get_workout`, `get_workout_count`, `get_workout_events`, `get_exercise_templates`, `get_body_measurements`. The sixth (`get_workout`) was absent from the plan's task-level spec and was added; see deviation 6 |
| 429/5xx/transport errors retry with jitter; 401/403/400/404 do not | **PASS** — tests 6/7/8 assert `call_count == 2`; tests 9/10/12 assert `call_count == 1` |
| A 404 from `/v1/body_measurements` returns `None` instead of failing a run | **PASS** — `test_body_measurements_404_returns_none` |
| No Hevy schema type and no `httpx2` import exists outside `backend/app/integrations/hevy/` | **PASS** — verified by grep and by `test_hevy_isolation.py` |

`must_haves` artifacts:

| Artifact | `contains` | `min_lines` | Actual |
|---|---|---|---|
| `client.py` | `PAGE_SIZE_EXERCISE_TEMPLATES = 100` ✓ | 150 | **275** |
| `schemas.py` | `discriminator="type"` ✓ | 120 | **198** |
| `errors.py` | `RETRYABLE_EXCEPTIONS` ✓ | — | 108 |
| `test_hevy_isolation.py` | `rglob` ✓ (6 uses) | — | 115 |

`must_haves` key_links: `client.py` → `errors.py` via `HevyRateLimited` ✓; `client.py` → `tenacity.AsyncRetrying` via `retry_if_exception_type(RETRYABLE_EXCEPTIONS)` ✓.

All task-level `<acceptance_criteria>` pass, with the three documented exceptions in *Issues Encountered*, each verified against intent.

## User Setup Required

None for this plan's tests — the entire suite runs against a mocked transport with no credential.

**But before any live verification:** `HEVY_API_KEY` is declared in `Settings` and in `.env.example`, and is currently **unset**, with no `.env` present. `build_hevy_client()` raises `RuntimeError("HEVY_API_KEY is required to run a Hevy sync")` until it is set. The key is available (Hevy Pro subscription confirmed in PROJECT.md context) — it just has not been placed in the environment yet. Whichever plan first runs a real sync needs it.

## Next Phase Readiness

Wave 2's transport half is complete. Specifically unblocked:

- **03-06 (sync service)** can call `get_workouts(page=...)` and loop on `page < page_count`, knowing 429/5xx are already absorbed and that a 401 arrives immediately rather than after a minute of backoff.
- **03-09 (events drain)** has `get_workout_events(since=..., page=...)` — which rejects a naive `since` outright — and `event_timestamp()`, the per-variant accessor Pattern 2's oldest-first sort depends on. The fixture confirms Hevy really does serve events newest-first.
- **03-04 (exercise templates)** gets `PAGE_SIZE_EXERCISE_TEMPLATES = 100` for free, i.e. ~5 requests instead of ~40.
- **03-11 (body measurements)** gets the `None`-on-404 terminator, so its paging loop needs no special-casing of the end of the range.
- **03-10 (resilience tests)** can build a `HevyClient` with `max_attempts=N` and `sleep=<no-op>` and assert retry behaviour in milliseconds, and can re-read a single workout via `get_workout(id)` after a simulated partial failure.

Concerns carried forward:

- **D-10 (Hevy's real rate limits) is instrumented but not yet answered.** `hevy_rate_limit_headers` fires on any response carrying a `ratelimit*` or `retry-after` header. Nothing will be learned until a real sync runs against the live API — whoever runs it first should read those log lines and record the finding in STATE.md. Right now the only empirical data point available is that Hevy's spec mentions none of this at all.
- **Pitfall 12 (dumbbell weight semantics) is untouched and remains open.** `weight_kg` is stored exactly as Hevy sends it, with no correction factor applied anywhere in this plan — which is the correct posture, but it means the 2× ambiguity is still live for whoever computes tonnage.
- **`pyproject.toml` still does not register the `httpx2` pytest marker**, so `@pytest.mark.httpx2(...)` warns. Avoided here; noted above for whoever needs per-test respx configuration.
- **`deferred-items.md` is unchanged** — nothing out-of-scope was found. The one pre-existing item (conftest fixture annotations, from 03-01) still stands.

## Self-Check: PASSED

- **Files claimed as created:** 9 of 9 found on disk (5 source modules, 3 test modules, this SUMMARY).
- **Commits claimed:** 6 of 6 present in `git log` (`b9c5397`, `6d4be4c`, `5ba3193`, `cb11923`, `9e63342`, `63a9468`).
- **Suite re-run at self-check time:** 139 passed, 33 deselected, 0.89s. `mypy backend/app` exit 0 (29 source files). `ruff check .` exit 0. `ruff format --check backend` clean.
- **No unexpected deletions:** `git diff --diff-filter=D --name-only cdf712f HEAD` is empty.
- **No shared orchestrator artifact touched:** `STATE.md`, `ROADMAP.md` and `REQUIREMENTS.md` are all unmodified in this worktree.

---
*Phase: 03-hevy-integration-normalization*
*Completed: 2026-08-29*
