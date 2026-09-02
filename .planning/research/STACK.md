# Stack Research — v2.0 (Apple Health, Strength Tracking & Coaching Programs)

**Domain:** Personal fitness/health data platform — additions to a shipped v1.0 backend
**Researched:** 2026-09-02
**Confidence:** HIGH
**Scope:** Only the five v2.0 capabilities. Everything validated in v1.0 (FastAPI, PostgreSQL,
SQLAlchemy 2.x, Alembic, Pydantic, `mcp==2.0.0`, WorkOS AuthKit, Cloud Run, Neon) stays.
Nothing below proposes replacing any of it.

> **Note for the orchestrator:** this file replaces the v1.0 milestone's STACK.md. The v1.0
> version is preserved in git at commit `c81d6cf` if it should be archived to
> `.planning/milestones/`.

---

## Critical findings — read before the tables

### 1. v2.0 requires ZERO new runtime dependencies

This is the headline, and it is not laziness — it is what the evidence supports. Every one of
the five capabilities is carried by a package already in `backend/pyproject.toml`.

| v2.0 capability | Carried by | Already installed? |
|---|---|---|
| 1. Health Auto Export webhook receiver | FastAPI 0.141.1 route + Pydantic 2.13.4 + `secrets.compare_digest` (stdlib) + `pg_insert(...).on_conflict_do_update()` | Yes |
| 1b. `export.xml` historical backfill | `xml.etree.ElementTree.iterparse` (stdlib) — **measured: 191 MB file in 2.5 s at 52 MB peak RSS** | Yes (stdlib) |
| 2. Max-weight-lifted as primary strength signal | `app/analytics/progression.py` + `records.py`; `PersonalRecordType.MAX_WEIGHT` already exists ungated | Yes |
| 3. Weekly/monthly report MCP tools | Same composition pattern as `fitness_get_training_summary` — Pydantic response models, one read-only transaction | Yes |
| 4. Manual body-measurement entry + trend analytics | FastAPI route + existing `body_measurements` table (`source='manual'` column already present) + `Decimal` maths | Yes |
| 5. Programs table + confirm-gated MCP write tool | Alembic migration + `mcp.types.ToolAnnotations` + a writable `AsyncSession` | Yes |

The only genuinely *new* third-party package worth considering is a **dev** dependency
(`pytest-postgresql`-style fixtures are already covered by `testcontainers`), and even that is
optional. Details in the tables.

The infrastructure *does* need one change — see Critical Finding 6.

---

### 2. (a) Health Auto Export supports arbitrary request headers and **no payload signature**

Verified against the official REST API automation guide (last updated **2026-08-23**) and the
live App Store listing (**version 9.1.1**, released 2026-08-31, min iOS 17.0, seller
Lybron Sobers). Confidence: **HIGH**.

**What HAE actually offers for authentication:**

- A free-form list of HTTP header key/value pairs, entered per automation ("Tap *Add Headers*",
  key on the left, value on the right). The docs give three worked examples verbatim:
  - `X-API-Key: your-api-key`
  - `Authorization: Bearer your-token`
  - `Content-Type: application/json`
- "Each header key must have a corresponding value. Empty headers will be ignored."
- **HTTP POST only.** No GET/PUT/PATCH.
- `Content-Type` is set automatically: `application/json` for JSON, `multipart/form-data` for CSV.
- A configurable **Request Timeout** (app-side; the app gives up, it does not retry).

**What HAE does NOT offer — verified absent, and this is the load-bearing finding:**

- No HMAC request signing. No shared-secret signature header. No timestamp or nonce.
- No mTLS, no OAuth, no JWT issuance.
- Nothing resembling GitHub's `X-Hub-Signature-256` or Stripe's `Stripe-Signature`.
- "Basic auth" is not a first-class option — you would type `Authorization: Basic <base64>`
  into the same free-form header field yourself. There is no reason to: bearer is simpler and
  exactly as strong against the same threat model.

**Therefore the verification scheme is fixed, and it is the one BRETT already implements
elsewhere:** a long random shared secret presented in a request header, compared in constant
time. `app/mcp/auth.py:49` is the precedent (`secrets.compare_digest` on **bytes**, never `==`,
never `str`). Nothing to install. Do **not** reach for `svix`, `standardwebhooks`, or any
signature-verification library — there is no signature to verify.

**Headers HAE adds to every request automatically** (useful, all unauthenticated and therefore
untrusted — log them, correlate on them, never make a trust decision from them):

| Header | Content | Use in BRETT |
|---|---|---|
| `session-id` | Unique per request | Correlation ID for the ingest log line; the closest thing to an idempotency key HAE offers |
| `automation-id` | Stable per automation | Distinguish "body + activity" from "sleep" automations if you split them |
| `automation-name` | User-typed name | Log only |
| `automation-aggregation` | Selected time grouping | Tells the normalizer whether points are raw or pre-aggregated |
| `automation-period` | Selected date range | Tells the normalizer the expected window |

**Placement inside the existing app matters and is non-obvious:**

- `app/main.py` mounts `mcp_app` at `"/"` as a **catch-all**, registered last so FastAPI's own
  routes win. A new `app.include_router(...)` for `/api/v1/...` must therefore be added
  **above** the `app.mount("/", mcp_app)` line, exactly as `health.router` is today.
- `RateLimitMiddleware` is app-global (30/min, 30 burst) and exempts only `/health` and
  `/.well-known/`. A HAE automation with **Batch Requests ON** sends many POSTs in quick
  succession; 30/min will 429 some of them, and HAE does not retry. Either add the ingest path
  to `EXEMPT_PREFIXES` and give it its own, more generous bucket, or raise the shared limit.
  This is a real decision for phase planning, not a footnote.
- The webhook route must **not** be reachable through the MCP SDK's `RequireAuthMiddleware`
  (it is not, because it lives on the FastAPI side of the mount) and must **not** reuse
  `MCP_AUTH_SECRET`. Give it its own `HEALTH_WEBHOOK_SECRET` in Secret Manager so the two
  rotate independently — v1.0 already proved secret rotation as an operational procedure.

---

### 3. (c) `mcp==2.0.0` has no write-tool mechanism beyond `ToolAnnotations` — and its built-in confirmation flow is unavailable to BRETT

Verified by reading the installed `mcp 2.0.0` / `mcp-types 2.0.0` source **and** the v2 SDK
docs via Context7. Confidence: **HIGH**.

**(i) `ToolAnnotations` is the entire per-tool surface.** There is no `@mcp.write_tool`, no
permission decorator, no per-tool scope. Verified from `inspect.signature(MCPServer.add_tool)`:

```
self, fn, name=None, title=None, description=None, annotations=None, icons=None,
meta=None, structured_output=None
```

No `scopes=`, no `requires_auth=`. And `AuthSettings.required_scopes` is **server-wide only**
(`list[str] | None`), so it cannot gate one tool differently from the other thirteen. The
existing comment in `app/mcp/server.py` — *"Revisit when the first write tool ships"* — resolves
to: **leave `required_scopes=None`.** Raising it to a non-`None` value would force the working
Phase 2 connector to re-consent and would gate *every* tool, including the read-only ones.
If per-tool scope checking is ever wanted, it is application code:
`mcp.server.auth.middleware.auth_context.get_access_token()` returns an `AccessToken` with a
`.scopes` list (verified present).

**(ii) The spec defaults are hostile and must be overridden explicitly.** From the SDK's own
`ToolAnnotations` docstring:

| Field | Spec default | Value for the program-switch tool | Why |
|---|---|---|---|
| `read_only_hint` | `false` | `False` | It writes. |
| `destructive_hint` | **`true`** | `False` | Switching the active program is an *additive* state change — it replaces a setting, it deletes no history. Leaving it unset advertises a destructive tool. |
| `idempotent_hint` | **`false`** | `True` | Setting the same program twice leaves the same state. |
| `open_world_hint` | **`true`** | `False` | Closed domain: one row in one table. |

BRETT's existing `READ_ONLY` constant is reused by a loop over `_TOOLS`. The write tool needs a
**second** module-level constant (e.g. `CONFIRM_GATED_WRITE`) registered by its own explicit
`mcp.add_tool(...)` call, kept out of the loop. Do not parameterise the loop — the loop's whole
value is that "every tool in it is read-only" is structurally true, and
`test_mcp_tool_schemas.py` asserts it.

**(iii) The SDK's built-in confirmation pattern does not work here.** The idiomatic v2 way to
ask the user before a mutation is `Resolve(...)` + `Elicit(...)`:

```python
async def confirm_delete(path: str) -> Confirm | Elicit[Confirm]: ...
@mcp.tool()
async def delete_folder(path: str, confirm: Annotated[ElicitationResult[Confirm], Resolve(confirm_delete)]) -> str: ...
```

Three independent blockers, each verified:

1. **Server-initiated requests are removed in protocol `2026-07-28`.** SDK docs: *"Attempting
   these operations on a modern connection will result in a `NoBackChannelError`."* On the
   legacy leg with `stateless_http=True` (BRETT's exact configuration) the error is explicit:
   `MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for
   server-initiated requests.` The replacement is `InputRequiredResult`, where the tool returns
   a result and the **client** drives the retry with `input_responses` + an echoed
   `request_state`.
2. **`request_state` is sealed with a process-local key by default.**
   `RequestStateSecurity.ephemeral()` is what `MCPServer` installs when
   `request_state_security=` is omitted — a fresh `os.urandom(32)` AES-256-GCM key held only by
   that process, TTL 600 s. Its own docstring: *"Multi-instance deployments must share a key via
   `keys=[...]`."* `scripts/deploy-cloud-run.sh` deploys with `--max=2`. A confirmation round
   trip that lands on the other instance fails with *"Invalid or expired requestState."* Fixing
   that means a new shared secret in Secret Manager, a new env var, and a key-rotation
   procedure — for one tool.
3. **Whether Claude's custom connector implements elicitation at all is UNVERIFIED.** The SDK
   troubleshooting page notes that *"a client that cannot be asked cannot provide a decline, so
   such calls will fail"* — i.e. an unsupported client produces an error, not a graceful no.

**Conclusion: PROJECT.md's two-call `confirm: bool` design is not merely a preference — it is
the only design that works.** A plain `confirm: bool = False` parameter needs no client
capability, no back-channel, no shared crypto key, and no 600-second TTL. First call returns
the warning payload; second call with `confirm=true` performs the switch.

**(iv) The annotation is a hint; the transaction is the control.** The SDK is explicit that
annotations *"should not be relied upon for security enforcement"* — which is exactly why
`app/mcp/tools/_common.py:read_only_session` opens the PostgreSQL transaction with
`postgresql_readonly=True`. The write tool needs a **sibling context manager** that does not set
that flag, and `test_mcp_readonly.py` must keep driving a write through the *read-only* session
for the other thirteen tools. Do not relax `read_only_session`; add `write_session` beside it.

---

### 4. (d) The Health Auto Export contract — what to pin, and what will silently break

All field names below are quoted from the official Help Center pages
(`/export-format/health-metrics` and `/export-format/workouts`, last updated 2026-02-06),
cross-checked against a real third-party parser (`irvinlim/apple-health-ingester`,
`pkg/healthautoexport/types.go`) that carries version-specific comments. Confidence: **HIGH**
on the field names, **MEDIUM** on the 12-hour/NNBSP quirk (documented in parser source, not in
HAE's own docs).

**There IS an explicit version selector.** The automation's *Export Version* setting offers
**Version 1 (Legacy)** and **Version 2 (Current)**. HAE's own words: *"Versioning allows
transitioning between updated versions of the export at your own pace and minimises breaking
changes to workflows."* **Pin Version 2 in the automation, record that pin in
`docs/`, and make the normalizer reject or loudly flag a Version-1-shaped payload.** The
differences are not cosmetic:

| | Version 1 (Legacy) | Version 2 (pin this) |
|---|---|---|
| Workout identity | *no `id` field at all* | `id` (UUID string) |
| Duration | absent | `duration` (Number, seconds) |
| Active energy | `activeEnergy` (scalar object) | `activeEnergyBurned` (scalar object); `activeEnergy` becomes a **time-series array** |
| `heartRateData` points | `{date, qty, units}` | `{date, Min, Avg, Max, units, source}` — **capitalised keys** |
| Route points | `lat`, `lon` | `latitude`, `longitude` (+ `course`, `*Accuracy`, `speed`) |

Version 1 having no workout `id` is the killer: an idempotent upsert needs a natural key, and
under v1 you would have to synthesise one from `(name, start, end)`.

**Top-level envelope** (stable across both versions):

```json
{"data": {"metrics": [], "workouts": [], "stateOfMind": [], "medications": [],
          "symptoms": [], "cycleTracking": [], "ecg": [], "heartRateNotifications": []}}
```

Only `metrics` and `workouts` are in v2.0 scope. Model the rest as ignored keys, not as errors —
HAE ships new arrays over time (`medications` requires iOS 26.0+, `stateOfMind` iOS 18.0+).

**Metric shape** — `{"name": snake_case, "units": str, "data": [...]}`. Most points are
`{"qty": Number, "date": Date, "source": str?}`, but several metrics are special-cased and the
extra keys are **not** under `qty`:

| Metric | Point keys |
|---|---|
| standard (`step_count`, `active_energy`, …) | `qty`, `date`, `source?` |
| `blood_pressure` | `systolic`, `diastolic`, `date` |
| `heart_rate` | `Min`, `Avg`, `Max`, `date` — **capitalised** |
| `sleep_analysis` (aggregated) | `date`, `totalSleep`, `asleep`, `core`, `deep`, `rem`, `awake`, `inBed`, `sleepStart`, `sleepEnd`, `inBedStart`, `inBedEnd`, `source` |
| `sleep_analysis` (disaggregated) | `startDate`, `endDate`, `qty`, `source`, `value` |
| `blood_glucose` | `qty`, `date`, `mealTime` |

`sleep_analysis` returns **two structurally different shapes** depending on the automation's
*Summarize Data* toggle. The reference parser handles this by attempting the disaggregated
shape, then falling back to the aggregated one. Pin *Summarize Data* in the automation and
validate the shape you pinned; treat the other as a hard error, not a silent skip.

**⚠ The date format is not ISO 8601, and Pydantic v2 rejects it.** Format string:
`yyyy-MM-dd HH:mm:ss Z`, e.g. `"2026-09-01 07:05:00 +0700"`. Measured on this project's exact
interpreter (Python 3.13, pydantic 2.13.4):

| Input | `datetime.fromisoformat` | `strptime("%Y-%m-%d %H:%M:%S %z")` | `strptime("%Y-%m-%d %I:%M:%S %p %z")` | **Pydantic `datetime` field** |
|---|---|---|---|---|
| `2026-09-01 07:05:00 +0700` | ✅ | ✅ | ❌ | **❌ FAIL** |
| `2026-09-01 7:05:00 PM +0700` | ❌ | ❌ | ✅ | **❌ FAIL** |
| `2026-09-01 7:05:00<U+202F>PM +0700` (narrow no-break space before `PM`) | ❌ | ❌ | ✅ | **❌ FAIL** |
| `2026-09-01 7:05:00 pm +0700` | ❌ | ❌ | ✅ | **❌ FAIL** |

**Consequence, and this is the single most likely silent-failure point in the whole feature:**
do **not** type HAE date fields as `datetime` in the Pydantic schema. Type them `str` and
convert with a `BeforeValidator`/`field_validator` that tries an ordered list of formats. The
12-hour variants appear when the device's *Settings → General → Date & Time → 24-Hour Time* is
**off**, and newer iOS inserts U+202F (narrow no-break space) before AM/PM — both documented in
the reference parser's `TimeFormats` list, neither documented by HAE. Python's `%p` happens to
tolerate the NNBSP (verified above), so a two-entry format list covers all four cases:

```python
_FORMATS = ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %I:%M:%S %p %z")
```

Good news: **`export.xml` uses the identical format** (verified against the user's real file:
`startDate="2022-03-21 06:38:35 +0700"`), so one parser serves both the webhook and the backfill.

**⚠ Units are user preferences, not constants.** The workout docs list `"mi"` *or* `"km"`,
`"mph"` *or* `"kmph"`, `"ft"` *or* `"m"`, `"degF"` *or* `"degC"`. Every scalar arrives as
`{"qty": …, "units": …}`. BRETT's internal units are kg/m/kcal/s/cm, converted at the boundary.
**The normalizer must read the `units` string per field and convert, and must reject an
unrecognised unit rather than assume.** A silent assumption here produces plausible-looking
wrong numbers, which is the worst failure mode for a coaching tool.

**⚠ HAE does not deduplicate and does not retry.** No retry logic is documented anywhere on the
REST API page or the FAQ; failures surface only in the in-app Activity Logs ("HTTP failures,
timeouts"). Combined with *Date Range → Since Last Sync*, a single failed POST is a permanent
gap. **Recommend configuring *Previous 7 Days* rather than *Since Last Sync*,** so every run
re-sends a week of overlap that an idempotent upsert absorbs. That makes the pipeline
self-healing without any queue, retry table, or dead-letter infrastructure. This is a
configuration decision on the phone, not code — but it is a decision the phase plan must record.

**⚠ iOS gives no schedule guarantee.** HAE's own docs: *"Apple does not allow apps to read
health data while the device is locked"* and *"iOS still decides when the automation actually
runs, based on battery, usage, and available resources."* Background tasks *"typically need to
complete within 30 seconds."* The freshness envelope (DQ-01) is therefore not optional decoration
for this source — a multi-day gap is normal operation, not an incident.
`app/analytics/metadata.py:build_freshness(..., provider=PROVIDER_HEVY)` is **already
parameterised by provider**, so adding `PROVIDER_APPLE_HEALTH = "apple_health"` to
`app/db/repositories/sync_state.py` plugs Apple Health into the existing freshness envelope with
no schema change and no new abstraction.

**What the user's actual data contains** — measured by parsing the real 191 MB `export.xml`
(HealthKit Export Version 14, 437,239 records, 2022-03-10 → 2026-08-26):

| Signal | Records | Verdict |
|---|---|---|
| `StepCount` | 48,261 | ✅ available |
| `ActiveEnergyBurned` | 45,182 | ✅ available |
| `BasalEnergyBurned` | 84,260 | ✅ available |
| `SleepAnalysis` | 2,411 | ⚠ **`HKCategoryValueSleepAnalysisInBed` only** — zero Core/Deep/REM records. iPhone-only sleep = time in bed, not sleep stages |
| `RestingHeartRate` | **0** | ❌ **ABSENT** |
| `HeartRateVariabilitySDNN` | **0** | ❌ **ABSENT** |
| `BodyFatPercentage` / `LeanBodyMass` | **0** | ❌ **ABSENT** |
| `BodyMass` | 79 | ⚠ `sourceName="Hevy"` — **already in BRETT via the Hevy API** |
| `Workout` | 224 | ⚠ 218 of them `sourceName="Hevy"` — **already in BRETT** |

Two hard consequences for phase planning:

1. **There is no Apple Watch in this dataset.** "Recovery trends" from resting HR and HRV cannot
   be built from data that does not exist. Scope the health analytics extension to
   activity (steps, active/basal energy) and time-in-bed. PROJECT.md's hedge — *"HRV where
   available"* — resolves to *not available*.
2. **Apple Health's body weight and workouts are Hevy's data round-tripping back.** Ingesting
   HAE `workouts` into the Hevy tables would duplicate 218 sessions BRETT already has, and HAE
   body weight would collide with `body_measurements` rows that already carry `source='hevy'`.
   Store Apple Health in its own namespace with its own `source` discriminator and apply an
   explicit source-precedence rule; do not merge into the Hevy tables.

---

### 5. (b) Report composition needs no library — the constraint is the transaction, not the maths

Measured, not assumed: `backend/app/analytics/*.py` imports **no third-party numeric library at
all**. The complete import census across all 11 analytics modules is `uuid`, `datetime`,
`decimal`, `dataclasses`, `enum`, `types`, `typing`, `collections.abc`, SQLAlchemy, and other
`app.*` modules. `Decimal` (not `float`) is used deliberately so identical inputs cannot produce
order-dependent results. Confidence: **HIGH**.

`fitness_get_training_summary` is the working precedent for exactly what the weekly/monthly
report tools are: four analytics calls composed into one Pydantic response model, all inside
**one** `read_only_session` — *"one consistent snapshot, so the weekly volume and the
recomposition verdict cannot describe two different databases."*

Three things the report tools must inherit from it, none of which is a library:

1. **One transaction, sequential awaits.** Do **not** reach for `asyncio.gather` to speed up the
   five-to-eight analytics calls a monthly report will make. A single SQLAlchemy `AsyncSession`
   is not concurrency-safe; gathering on one session raises or corrupts state. If the report
   ever becomes too slow, the fix is SQL, not concurrency.
2. **A response byte budget.** The summary tool documents its measurement (~9.5 KB on the wire
   at 4 weeks against a 16 KB budget) and drops the per-week × per-muscle grid for size. A
   *monthly* report composing volume + strength + measurements + trends + recommendations will
   be larger than anything shipped so far; it needs its own `MAX_*` constant in
   `_common.py` and its own measured budget, not an inherited one.
3. **A degraded payload.** `_degraded_summary()` empties *every* field rather than partially
   filling, so a failed call reads as "this call failed" and not as "no signal." Report tools
   need the same, and it matters more: a report is exactly the artefact a scheduled task will
   deliver unattended.

**No scheduler library.** APScheduler, Celery, arq, Dramatiq, and Cloud Scheduler are all
unnecessary for feature 3 — PROJECT.md's decision is that Claude's own scheduled-tasks feature
drives delivery client-side. The MCP tools are ordinary on-demand read tools. (Cloud Scheduler
*is* already in production for the 6-hourly Hevy sync; that is unrelated and unchanged.)

**No templating library.** Jinja2 would be the reflex for "report", and it is wrong here: MCP
tools return structured JSON and Claude writes the prose. Prose in the payload would fight
`docs/coaching-instructions.md` for control of tone and burn context budget on words the model
is going to rewrite anyway.

---

### 6. The one place v2.0 forces an infrastructure change: request body size on a 512 MiB instance

This is the highest-risk item in the whole milestone and it is measurable. Confidence: **HIGH**
(all numbers measured on this project's own venv and deploy script).

HAE's docs: *"Make sure your backend is configured to handle payloads of possibly several
hundred megabytes to avoid errors."*

Against that, the facts:

| Constraint | Value | Source |
|---|---|---|
| Cloud Run max HTTP/1 request size | **32 MiB** | Cloud Run quotas |
| BRETT's deployed memory | **512 MiB** | `scripts/deploy-cloud-run.sh:37` |
| BRETT's baseline RSS after `import app.main` | **101 MB** | measured |
| Peak RSS, +9 MB JSON body through `json.loads` | **176 MB** | measured |
| Peak RSS, +10 MB body through `json.loads` **+ Pydantic validate** | **~235 MB** | measured |
| `json.loads` wall time, 9 MB body | **0.03 s** | measured |

Read those together: a ~10 MB payload consumes roughly **half** the instance's memory, and
Cloud Run's default concurrency is 80 — two simultaneous ingest POSTs on one instance is an OOM,
not a slowdown. A 30 MB payload OOMs on its own. And note the timing: **CPU is not the problem**
(30 ms), so `orjson` buys nothing here. Memory is the problem.

Four mitigations, all cheap, and phase planning should take all four:

1. **Reject oversized bodies before reading them.** Neither FastAPI nor Starlette has a built-in
   JSON body cap (their `max_files`/`max_fields`/`max_part_size` apply to form parsing only). A
   ~40-line pure-ASGI middleware — the same shape as the existing `RateLimitMiddleware`, which
   is already pure-ASGI for good documented reasons — that checks `Content-Length` and then
   counts streamed bytes for chunked encoding, returning **413**, is the whole fix. No library.
2. **Raise `--memory` to `1Gi`** in `scripts/deploy-cloud-run.sh`. One flag;
   `backend/tests/test_cloud_run_deploy.py` already asserts on the flag set, so the change is
   testable. Roughly doubles cost of a service that scales to zero.
3. **Configure the automation to produce small payloads:** *Batch Requests* **ON**, only the
   handful of metrics BRETT actually uses, *Summarize Data* **ON**, hourly or daily time
   grouping, *Include Route Data* **OFF**. HAE's own performance guidance says the same, for its
   own reasons (a 30-second iOS background budget).
4. **Process synchronously inside the request.** Do **not** use FastAPI `BackgroundTasks` or any
   after-response work: Cloud Run's default CPU allocation throttles CPU to near zero the moment
   the response is sent, so background work stalls indefinitely unless the service is redeployed
   with `--no-cpu-throttling` and instance-based billing. Cloud Run's request timeout is 300 s
   in this deploy — an order of magnitude more than needed for a capped payload.

Also worth recording as a non-issue: **CVE-2026-54283** (Starlette `request.form()` limits
silently ignored for `application/x-www-form-urlencoded`, DoS) is fixed in Starlette **1.3.1**.
BRETT runs **1.6.0** — already patched, no action, and it does not apply to a JSON endpoint
anyway.

---

## Recommended Stack

### Core Technologies

Everything in this table is **already installed and validated**. It is listed because these are
the integration points phase planning needs, not because anything changes.

| Technology | Version | Purpose in v2.0 | Why (and where it plugs in) |
|------------|---------|-----------------|-----------------------------|
| **FastAPI** | 0.141.1 | Webhook receiver route; manual body-measurement entry route | Both are ordinary `APIRouter`s. **Must be `include_router`'d above `app.mount("/", mcp_app)`** in `app/main.py` — the MCP app is a catch-all mount and FastAPI's own routes only win because they are registered first |
| **Pydantic** | 2.13.4 | HAE payload schema; manual-entry request schema; report response models | Returning a `BaseModel` from an MCP tool auto-generates the output schema and populates `structured_content`. **Type HAE `date` fields as `str`, never `datetime`** — see Critical Finding 4 |
| **SQLAlchemy** | 2.0.52 | New `health_*` tables, `training_programs`, writes to `body_measurements` | `pg_insert(...).on_conflict_do_update()` is the established idempotency mechanism — four precedents already in `integrations/hevy/` and `db/repositories/sync_state.py` |
| **asyncpg** | 0.31.0 | unchanged | — |
| **Alembic** | 1.19.1 | Migrations for programs, Apple Health tables, any `body_measurements` additions | `--autogenerate` then hand-review, as in v1. Runs out-of-band, never at startup |
| **mcp** (+ `mcp-types`) | 2.0.0 | Report tools; the one confirm-gated write tool | `ToolAnnotations` is the whole write-tool surface. `add_tool()` takes no scope parameter. See Critical Finding 3 |
| **`xml.etree.ElementTree`** | stdlib (3.13) | One-time `export.xml` backfill | **Measured on the real 191 MB file: 2.5 s, 52 MB peak RSS, 437,239 records.** `iterparse(events=("end",))` + `elem.clear()`. `lxml` would be faster and is not needed |
| **`secrets` / `hmac`** | stdlib | Webhook shared-secret verification | `secrets.compare_digest` on **bytes**. Precedent: `app/mcp/auth.py:49` |
| **`decimal.Decimal`** | stdlib | Measurement trends, max-weight progression, report arithmetic | Already the analytics layer's only numeric type. Binary floats would make identical inputs produce order-dependent results |
| **`zoneinfo`** | stdlib | HAE offsets → UTC → `Asia/Jakarta` local-day grouping | HAE emits the device's local offset (`+0700`). Store UTC, group with `ZoneInfo(user.timezone)`. `tzdata` is already a declared dependency |
| **structlog** | 26.1.0 | Ingest lifecycle logging keyed on `session-id` | The existing value scrubber must be extended with `HEALTH_WEBHOOK_SECRET` via `Settings.secret_values()`, or the secret can reach a log line |
| **pydantic-settings** | 2.15.0 | `HEALTH_WEBHOOK_SECRET` as a `SecretStr` | Add the field to `_SECRET_FIELDS` in `app/config.py` — that tuple is what drives the log scrubber |

### Supporting Libraries

**None required.** The table below is the complete list of packages that were seriously
evaluated and the honest verdict on each.

| Library | Version | Purpose considered | Verdict |
|---------|---------|--------------------|---------|
| `orjson` | 3.12.0 | Faster ingest JSON parsing | **Skip.** Measured: `json.loads` on a 9 MB HAE-shaped body takes 30 ms. Memory, not CPU, is the constraint, and `orjson` does not reduce the size of the resulting Python objects |
| `lxml` | 6.x | Faster `export.xml` parsing | **Skip.** stdlib `iterparse` does the real 191 MB file in 2.5 s at 52 MB RSS. Adds a C extension to a health-data service's dependency tree for a one-time job |
| `svix` / `standardwebhooks` | — | Webhook signature verification | **Skip — inapplicable.** HAE sends no signature of any kind (Critical Finding 2). These libraries verify a header that does not exist |
| `slowapi` / `limits` | 0.1.10 | Separate rate-limit bucket for the ingest path | **Skip.** The existing `TokenBucket` in `app/middleware.py` is ~40 lines and already injectable (`clock=`). A second instance with different numbers is a constructor call, not a dependency. Also unverified against Starlette 1.x |
| `APScheduler` / `arq` / `Celery` | — | Driving weekly/monthly reports | **Skip — architecturally wrong.** PROJECT.md's decision is that Claude's scheduled-tasks feature drives delivery. There is no server-side schedule to run |
| `Jinja2` | 3.x | Rendering report prose | **Skip.** Tools return structured JSON; Claude writes the prose per `docs/coaching-instructions.md` |
| `pandas` / `numpy` | — | Trend/comparison maths | **Skip — explicitly banned.** ~50 MB, cold-start cost, and float-comparison flakiness on a 512 MiB instance that already peaks at 235 MB during ingest |
| `python-multipart` | — | HAE CSV export | **Skip.** Only needed if the automation is set to CSV (`multipart/form-data`). Pin JSON and this never appears |
| `dateutil` | 2.9 | Tolerant HAE date parsing | **Skip.** A two-entry `strptime` format tuple covers all four observed variants (verified). `dateutil.parser` is also *too* tolerant — it would silently accept malformed input the normalizer should reject |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| **pytest 9.1.1** + **pytest-asyncio 1.4.0** | unchanged | `asyncio_mode = "auto"` already configured |
| **`fastapi.testclient.TestClient`** | Webhook endpoint tests | Already the project's HTTP test seam (`test_mcp_auth.py:54`). Exercises the real ASGI stack including `RateLimitMiddleware` and the body-size middleware — which an in-memory MCP client would bypass |
| **`httpx2.ASGITransport`** | Async webhook tests if needed | Verified present in `httpx2 2.12.0`. `TestClient` is sufficient for most cases |
| **`testcontainers[postgres]` 4.15.0** | Real Postgres for ingest idempotency and new analytics | Non-negotiable for the upsert tests: `ON CONFLICT` semantics, `date_trunc`, and `AT TIME ZONE` do not exist or differ in SQLite |
| **`time-machine` 3.4.0** | Report window boundaries, measurement trends | Weekly/monthly reports are clock-dependent by construction. Note the existing caveat: `time_machine.travel()` does **not** patch `time.monotonic()` |
| **`mcp.client.Client`** | Tool discovery/schema tests, including the write tool's annotations | In-memory, no HTTP. **Caveat already recorded in v1: in-memory connections bypass auth entirely**, so the write tool's auth behaviour must be tested over HTTP |
| **Ruff 0.16.4** | Lint | `S` (bandit) rules already enabled — they will flag a non-constant-time secret comparison in the webhook handler, which is exactly what you want |
| **mypy 2.3.1** | Types | The HAE schema is where `disallow_untyped_defs` earns its keep: an untyped `dict[str, Any]` normalizer is how field-name drift becomes a runtime `KeyError` in production |
| **Recorded HAE fixtures** | Contract tests | Capture one real payload per data type from the phone (via `webhook.site` or the app's *Manual Export*) and commit them as JSON fixtures. This is the only defence against silent upstream format drift, and it costs nothing |

---

## Installation

```bash
# Runtime dependencies: NONE. backend/pyproject.toml is unchanged for v2.0.

# Dev dependencies: NONE required.

# The only stack-level change v2.0 needs is a deploy flag:
#   scripts/deploy-cloud-run.sh
- --memory=512Mi
+ --memory=1Gi
# (backend/tests/test_cloud_run_deploy.py asserts on the flag set, so update it too.)

# And one new secret, created the same way MCP_AUTH_SECRET was:
python -c "import secrets; print(secrets.token_urlsafe(48))" | \
  gcloud secrets create brett-health-webhook-secret \
    --project="$BRETT_GCP_PROJECT" --data-file=-

# Then bound in scripts/deploy-cloud-run.sh alongside the existing two:
#   --set-secrets="DATABASE_URL=...,MCP_AUTH_SECRET=...,HEALTH_WEBHOOK_SECRET=brett-health-webhook-secret:latest"
```

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| Two-call `confirm: bool` write tool | `Resolve(...)` + `Elicit(...)` → `InputRequiredResult` | Only after **all three** hold: Claude's connector is confirmed to implement elicitation; `--max` is 1 *or* a shared `RequestStateSecurity(keys=[...])` secret exists; and the 600 s TTL is acceptable. None hold today |
| Shared-secret header + `compare_digest` | Cloud Run IAM (`--no-allow-unauthenticated`) with an identity token | HAE cannot mint a Google identity token, and the service must stay `--allow-unauthenticated` for Claude's connector anyway. Not available |
| Shared-secret header | Long random URL path segment | As *additional* defence in depth only. Blueprint §32 already rules out relying on an obscure URL as the control |
| Synchronous ingest inside the request | FastAPI `BackgroundTasks` / Cloud Tasks queue | Only if a payload genuinely cannot be processed in 300 s. `BackgroundTasks` additionally requires redeploying with `--no-cpu-throttling`; Cloud Tasks adds a queue, an IAM binding and a second endpoint. Neither is justified at this data volume |
| Custom body-size ASGI middleware | Cloud Run's native 32 MiB cap | The platform cap alone is 3× the instance's usable memory. It is a backstop, not a control |
| `--memory=1Gi` | Keep 512Mi + a stricter body cap | Viable if the body cap is set aggressively (≤4 MiB) and *Batch Requests* is confirmed ON. Cheaper, but leaves no headroom for two concurrent posts |
| stdlib `iterparse` for `export.xml` | Stream the file through a Cloud Run Job instead of a local CLI | Only if the backfill must run in production. It is a genuine one-time job against a file that already sits on the user's machine — run it locally against the production DSN |
| HAE *Previous 7 Days* | HAE *Since Last Sync* | Only once HAE's retry-on-failure behaviour is empirically confirmed. Until then the 7-day overlap is what makes a dropped POST self-healing |
| Separate `health_*` tables | Merge HAE workouts into the Hevy workout tables | Never — verified that 218 of 224 Apple Health workouts and all 79 body-mass records originate from Hevy and are already in BRETT |
| `required_scopes=None` | A `brett:write` scope enforced server-wide | Only when a *second* write tool exists **and** read/write clients must be separated. Today it would force the working connector to re-consent and gate all fourteen tools identically |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `datetime` as the Pydantic field type for any HAE date | **Measured: pydantic 2.13.4 rejects `"2026-09-01 07:05:00 +0700"` outright.** The whole payload fails validation, and it will look like a transport problem | `str` field + `BeforeValidator` with `("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %I:%M:%S %p %z")` |
| `datetime.fromisoformat` as the *only* HAE date parser | Handles the 24-hour form on 3.13 but fails on all three 12-hour forms, which appear whenever the device's 24-Hour Time setting is off | The ordered `strptime` format tuple above |
| Assuming HAE units (`kg`, `km`, `degC`, …) | Units follow the user's app preferences; the docs list `mi`/`km`, `mph`/`kmph`, `ft`/`m`, `degF`/`degC` as alternatives. Guessing produces plausible wrong numbers, the worst failure mode for a coach | Read the per-field `units` string; **reject** unrecognised units |
| Pinning HAE Export Version 1 | No workout `id` at all — nothing to build an idempotent upsert key from. Also `activeEnergy` vs `activeEnergyBurned` and `lat`/`lon` vs `latitude`/`longitude` | Version 2, pinned in the automation and documented as the contract |
| `ctx.elicit()` anywhere in this codebase | Raises `NoBackChannelError` on protocol 2026-07-28; on the legacy leg with `stateless_http=True` it raises *"this transport context has no back-channel for server-initiated requests"* | A plain `confirm: bool = False` tool parameter |
| Relaxing `read_only_session` so the write tool can use it | `postgresql_readonly=True` is the *only* real enforcement of read-only — the SDK says annotations *"should not be relied upon for security enforcement"*. Relaxing it silently un-protects all thirteen read tools | A separate `write_session` context manager beside it; keep `test_mcp_readonly.py` pointed at the read-only one |
| Adding the write tool to the `_TOOLS` loop in `app/mcp/server.py` | The loop exists so "every tool in it is read-only" is structurally true, and `test_mcp_tool_schemas.py` asserts it | An explicit `mcp.add_tool(...)` call with its own annotation constant |
| Omitting `destructive_hint` / `idempotent_hint` on the write tool | Spec defaults are `destructive_hint=true`, `idempotent_hint=false` — omitting them advertises a destructive, non-idempotent tool | Set all four annotation fields explicitly, as `READ_ONLY` already does |
| `asyncio.gather` across analytics calls in a report tool | A single `AsyncSession` is not concurrency-safe; and gathering would break the one-consistent-snapshot property `fitness_get_training_summary` documents | Sequential `await`s inside one `read_only_session` |
| FastAPI `BackgroundTasks` for ingest | Cloud Run throttles CPU to near zero the moment the response is sent, under this deploy's default (request-based) billing | Process synchronously inside the 300 s request budget |
| `pandas` / `numpy` for measurement or report maths | Explicitly banned in v1 and now also a memory problem: baseline RSS is already 101 MB of a 512 MiB instance | `Decimal` + SQL aggregates, as the analytics layer already does |
| Ingesting HAE `workouts` into the Hevy workout tables | Measured: 218 of 224 Apple Health workouts have `sourceName="Hevy"` — they are BRETT's own data returning by a second path | Separate namespace + explicit source precedence |
| Building resting-HR / HRV recovery analytics | Measured: **zero** `RestingHeartRate` and **zero** `HeartRateVariabilitySDNN` records in the user's real 4.5-year export. No Apple Watch | Activity (steps, active/basal energy) and time-in-bed trends |
| Treating `sleep_analysis` as sleep *stages* | Measured: 2,411 records, **all** `HKCategoryValueSleepAnalysisInBed`. No Core/Deep/REM exists | Time-in-bed only; label it as such in the tool's field names so Claude cannot overclaim |
| Reusing `MCP_AUTH_SECRET` for the webhook | Couples two rotation schedules and widens the blast radius of either leak. v1 proved rotation as a live procedure — keep it cheap | A separate `HEALTH_WEBHOOK_SECRET`, added to `_SECRET_FIELDS` so the log scrubber covers it |
| `respx` / `pytest-httpx` | Still pinned to httpx 0.x, still cannot see `httpx2`. Carried over from v1 and still true | `pytest-httpx2`, `httpx2.MockTransport` — or, for the webhook, `TestClient` (BRETT is the *server* here, so no HTTP client mocking is needed at all) |

---

## Stack Patterns by Variant

**If HAE payloads land under ~4 MiB in practice (Batch Requests ON, few metrics, daily grouping):**
- Keep `--memory=512Mi`; add only the body-size middleware with a 4 MiB cap.
- Measured headroom: 101 MB baseline + ~100 MB peak ≈ 200 MB of 512 MiB. Comfortable for one
  request, tight for two concurrent.
- Cheapest path; revisit if 413s start appearing in HAE's Activity Logs.

**If payloads exceed ~8 MiB, or route data / second-grouping is ever wanted:**
- `--memory=1Gi` **and** a 16 MiB cap **and** `--concurrency` lowered on the service.
- Above ~25 MiB you are against Cloud Run's 32 MiB HTTP/1 ceiling regardless of memory — at
  that point the answer is to split the automation, not to scale the instance.

**If Claude's connector turns out to support elicitation *and* `--max` is set to 1:**
- `Resolve(...)` + `Elicit(...)` becomes viable and gives a nicer UX than a two-call contract.
- Still requires `RequestStateSecurity(keys=[...])` from a shared secret the moment `--max`
  goes back above 1, so the two-call design remains the safer default. Treat this as a possible
  *later* refinement, never as the Phase-1 plan.

**If a second write tool is ever wanted after the program switch:**
- *Then* introduce a `brett:write` scope and enforce it in application code via
  `get_access_token().scopes` — not via `AuthSettings.required_scopes`, which is server-wide and
  would gate the read tools too.
- Budget a connector re-consent for it.

**If Apple Health ever gains an Apple Watch as a source:**
- `RestingHeartRate` / `HeartRateVariabilitySDNN` / sleep-stage records appear with no schema
  change if the health tables are modelled as `(source, metric_name, units, value, recorded_at)`
  rather than as one column per metric. Model it that way now; it costs nothing today and is a
  migration later.

---

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| `starlette 1.6.0` | — | **> 1.3.1, so CVE-2026-54283 (form-limit bypass DoS) is already fixed.** No action; also inapplicable to a JSON endpoint |
| `pydantic 2.13.4` | HAE date format | **INCOMPATIBLE.** Verified: `"2026-09-01 07:05:00 +0700"` fails validation as a `datetime` field. Parse via validator, not via type coercion |
| `python 3.13` `datetime.fromisoformat` | HAE 24-hour dates | ✅ works (3.11+ relaxed the parser). ❌ fails on all 12-hour variants |
| `python 3.13` `strptime("%p")` | U+202F narrow no-break space before AM/PM | ✅ verified tolerant. The quirk appears on newer iOS and is documented only in third-party parser source |
| `mcp 2.0.0` + `stateless_http=True` | `ctx.elicit()` / server-initiated requests | **INCOMPATIBLE by design.** `NoBackChannelError` / *"this transport context has no back-channel"* |
| `mcp 2.0.0` `MCPServer(...)` default | Multi-instance `request_state` | `RequestStateSecurity.ephemeral()` — process-local key, 600 s TTL. Incompatible with `--max=2` unless a shared key is supplied |
| `mcp 2.0.0` `AuthSettings.required_scopes` | Per-tool gating | Not supported — server-wide `list[str] | None` only |
| `cryptography 50.0.1` | `RequestStateSecurity(keys=[...])` AES-256-GCM | Already in the tree via `pyjwt[crypto]`; no new install if that path is ever taken |
| Cloud Run HTTP/1 | Request bodies | 32 MiB hard cap. HAE warns payloads can reach "several hundred megabytes" — the automation must be configured down, the server cannot be configured up |
| Cloud Run default CPU allocation | after-response background work | Throttled to ~0. Requires `--no-cpu-throttling` + instance-based billing to change |
| `export.xml` (HealthKit Export Version 14) | `xml.etree.ElementTree.iterparse` | ✅ measured on the real 191 MB file: 2.5 s, 52 MB peak RSS, 437,239 records |
| `app/analytics/metadata.py:build_freshness` | a new provider | Already takes `provider: str = PROVIDER_HEVY`. Apple Health plugs in with a new constant and no signature change |
| `httpx2 2.12.0` | `ASGITransport`, `MockTransport` | ✅ both verified present |

---

## Sources

**Direct measurement on this repository (strongest evidence in this document — HIGH):**
- `.venv` introspection: `inspect.signature(MCPServer.add_tool)`, `ToolAnnotations.model_fields`,
  `AuthSettings.model_fields`, `AccessToken.model_fields`, `httpx2` transports — installed
  `mcp 2.0.0` / `mcp-types 2.0.0` / `pydantic 2.13.4` / `starlette 1.6.0`
- Source reads: `mcp/server/mcpserver/server.py`, `mcp/server/mcpserver/context.py`,
  `mcp/server/request_state.py`, `mcp/server/elicitation.py`, `mcp/server/session.py`,
  `mcp_types/_types.py`
- Parsed the user's real `export.xml` (191,257,897 bytes, HealthKit Export Version 14):
  437,239 records, 2022-03-10 → 2026-08-26, full type census, 2.5 s / 52 MB peak
- Memory/latency benchmarks: `import app.main` = 101 MB RSS; +9 MB JSON = 176 MB peak, 0.03 s;
  +10 MB JSON + Pydantic validate = ~235 MB peak
- Date-parsing matrix: 6 input variants × 4 parsers (`fromisoformat`, two `strptime` formats,
  Pydantic `datetime` field)
- Codebase reads: `app/main.py`, `app/mcp/server.py`, `app/mcp/tools/_common.py`,
  `app/mcp/tools/summary.py`, `app/middleware.py`, `app/config.py`, `app/db/models/body.py`,
  `app/analytics/metadata.py`, `scripts/deploy-cloud-run.sh`, `deploy/cloud-run.env.yaml`,
  `backend/pyproject.toml`

**Official documentation (HIGH):**
- https://help.healthyapps.dev/en/health-auto-export/automations/rest-api/ (updated 2026-08-23)
  — headers, POST-only, Content-Type, timeout, batching, auto-added headers, date-range options,
  export-version selector, payload-size warning
- https://help.healthyapps.dev/en/health-auto-export/export-format/ — top-level envelope,
  `yyyy-MM-dd HH:mm:ss Z`
- https://help.healthyapps.dev/en/health-auto-export/export-format/health-metrics — metric and
  special-case point schemas
- https://help.healthyapps.dev/en/health-auto-export/export-format/workouts (updated 2026-02-06)
  — full v1 vs v2 field-by-field schema, units, route shapes
- https://help.healthyapps.dev/en/health-auto-export/faq/ — device-locked and background-execution
  limits
- iTunes Lookup API, queried 2026-09-02 — HAE **9.1.1**, released 2026-08-31, min iOS 17.0
- `/websites/py_sdk_modelcontextprotocol_io_v2` (Context7) — `ToolAnnotations`, `Resolve`/`Elicit`,
  `InputRequiredResult`, stateless/legacy back-channel errors, `RequestStateSecurity` guidance
- https://docs.cloud.google.com/run/quotas — 32 MiB HTTP/1 request cap, 60 min timeout,
  concurrency limits
- https://github.com/advisories/GHSA-82w8-qh3p-5jfq — CVE-2026-54283 fixed in Starlette 1.3.1

**Third-party corroboration (MEDIUM):**
- https://github.com/irvinlim/apple-health-ingester — `pkg/healthautoexport/types.go`: real
  parsing code with version-specific field comments (`awake`/`core`/`deep`/`rem` from HAE 6.6.2+,
  `inBedStart`/`inBedEnd` before it) and the `TimeFormats` list documenting the 12-hour and
  U+202F variants. This is the only source for the NNBSP quirk
- https://github.com/Lybron/health-auto-export — official docs repo; the wiki now redirects to
  the Help Center
- Cloud Run CPU-throttling behaviour — Google Cloud blog + 2026 practitioner write-ups; the
  underlying billing-settings doc is official, the "throttled the moment the response is sent"
  framing is community

**Explicitly UNVERIFIED (flag for phase-time validation):**
- Whether HAE retries a failed POST, and whether *Since Last Sync* advances its cursor on
  failure. Nothing in the official docs addresses it. The *Previous 7 Days* recommendation exists
  precisely so this does not need answering
- Whether HAE reuses one `session-id` across the requests of a batched export, or mints one per
  request. Determines whether `session-id` can serve as a batch key
- Whether Claude's custom connector implements the `elicitation` client capability at all
- HAE's behaviour on receiving a 413 (retry, skip, surface in Activity Logs)
- Whether the phone's HAE build emits 24-hour or 12-hour timestamps — settable, and worth
  checking once against a real captured payload

---
*Stack research for: BRETT v2.0 — Apple Health ingestion, strength tracking, reports, body
measurements, training programs*
*Researched: 2026-09-02*
