# Pitfalls Research

**Domain:** Adding v2.0 capabilities to BRETT — a shipped, production-live, read-only fitness MCP backend
**Researched:** 2026-09-02
**Confidence:** HIGH for everything grounded in this repo's source (read directly); HIGH for Health Auto Export behaviour (official Help Center); MEDIUM-HIGH for Claude scheduled-task connector failures (two GitHub issues fetched directly, both closed "not planned"); MEDIUM for Claude Desktop "Always approve" irreversibility (community sources only).

> **Scope note.** This document is deliberately *not* generic fitness-app advice. Every pitfall below is
> anchored to a specific file, line, constant, constraint or deployment flag that already exists in BRETT
> today, and describes what breaks when one of the five v2.0 features is bolted onto it. Where a pitfall is
> already anticipated by an in-repo docstring or guard, that is stated — because the most dangerous
> pitfalls here are the ones where v1.0's authors *wrote down the counter-argument* and v2.0 is about to
> walk past it.

---

## Critical Pitfalls

### Pitfall 1: The webhook route is registered after the catch-all mount and silently never runs

**What goes wrong:**
`backend/app/main.py:98` ends with `app.mount("/", mcp_app)` — a catch-all mount at the root, registered
last *on purpose*, with the comment "Registered LAST because it is a catch-all: FastAPI's own routes are
matched first and therefore win." Starlette matches routes in registration order. Add
`app.include_router(webhooks.router)` **below** that line and the mount matches first: every POST to
`/webhooks/health-auto-export` is handed to the MCP sub-app, which answers with an MCP-shaped 404/406 or a
401 from `RequireAuthMiddleware`. The route exists, imports fine, has tests that pass against a
`TestClient` built from a bare router — and is dead in production.

**Why it happens:**
Every other route in the file (`app.include_router(health.router)`, line 90) sits above the mount, so the
ordering rule is invisible unless you read the comment. The natural editing instinct is to append.

**How to avoid:**
Register the webhook router **above** line 98, immediately after the health router. Add a test in the
style of `backend/tests/test_mcp_mount.py` that asserts the webhook path resolves to the FastAPI route and
not the mounted app — assert on the *response shape* (a FastAPI 422 validation error for a bad body, say),
not merely on "not 404", because the MCP app also returns 404s.

**Warning signs:**
A webhook that returns 401 with an MCP `WWW-Authenticate` header, or a 404 whose body is not FastAPI's
`{"detail":"Not Found"}`. Health Auto Export's Activity Log showing consistent non-2xx with no server log
line from your handler.

**Phase to address:** Apple Health webhook ingest phase, first plan.

---

### Pitfall 2: The webhook shares one global 30/min token bucket with `/mcp`, and Health Auto Export does not retry

**What goes wrong:**
`backend/app/middleware.py` builds **one process-wide `TokenBucket`** (`build_limiter`, capacity 30, refill
30/min) applied to every path except `/health` and `/.well-known/` (`EXEMPT_PREFIXES`, line 57). It is
registered app-level in `main.py:79`, i.e. *outside* the router, so it fires before routing. A new webhook
path inherits it automatically.

Two failure directions, both real:
- Health Auto Export with **Batch Requests ON** (which you will need — see Pitfall 4) sends many HTTP
  requests in quick succession. Those drain the same 30-token bucket Claude's MCP calls draw from. A
  mid-conversation `fitness_get_training_summary` gets a 429 during a health sync.
- Conversely, an active coaching conversation drains the bucket and the health push gets 429'd.

The second direction is the damaging one: **Health Auto Export has no documented retry mechanism.** Its own
docs describe checking "Activity Logs for HTTP status codes and per-day failures" and document no automatic
retry. A 429 is therefore not backpressure — it is silent, permanent data loss for that window, unless the
user notices and re-runs manually. Worse, if the automation is configured to **"Since Last Sync"**, a failed
delivery may leave a gap that the next run does not re-cover.

**Why it happens:**
The single global bucket was a deliberate, well-argued v1.0 decision (documented at length in
`middleware.py`'s docstring: no per-IP key because the service is `--allow-unauthenticated` and the
forwarded-address header is attacker-controlled). That reasoning is still correct *for `/mcp`*. It was
simply never asked to arbitrate between two traffic classes with opposite retry semantics.

**How to avoid:**
Give the webhook its **own bucket**, keyed by path prefix, sized for burst delivery (HAE batches) rather
than for conversational cadence. Keep the global bucket for everything else so the DoS argument in
`middleware.py`'s docstring still holds. Do **not** add the webhook to `EXEMPT_PREFIXES` — that would make
an unauthenticated-by-default write path the one unbounded surface on the service. Return `503` with
`Retry-After` rather than `429` if you want HAE to surface it as a retryable failure in its Activity Log,
and log a distinct `webhook_rejected` event so a dropped window is findable after the fact.

**Warning signs:**
`rate_limit_rejected` log lines whose `path` is the webhook path. Gaps in Apple Health data that align with
periods of heavy Claude usage. A `sync_state`-equivalent `last_synced_at` for Apple Health that stops
advancing while the iOS app reports success.

**Phase to address:** Apple Health webhook ingest phase.

---

### Pitfall 3: A FastAPI-side route inherits zero authentication on an `--allow-unauthenticated` service

**What goes wrong:**
BRETT's entire inbound auth story lives inside the mounted MCP sub-app. `AuthSettings` +
`build_token_verifier` (`backend/app/mcp/auth.py`) are consumed by `MCPServer`, and the SDK's
`RequireAuthMiddleware` wraps only `mcp_app`. The FastAPI side has exactly one route today — `/health` —
and it is **deliberately open** (`main.py:89`: "D-04: no auth dependency -- /health is open so platform
health checks reach it"). `scripts/deploy-cloud-run.sh` deploys with `--allow-unauthenticated`.

Consequently a new `POST /webhooks/...` on the FastAPI side is, by default, **a public write endpoint into
a health-data database, reachable by anyone on the internet**. Nothing in the existing test suite would
catch this: `test_mcp_auth.py` tests the MCP path, and a new webhook test written against `TestClient` with
no header would pass precisely *because* there is no auth.

**Why it happens:**
"The app is authenticated" is true of the app the developer thinks about (`/mcp`). The mental model that
auth is an app-level property is wrong here — it is a property of one mounted sub-application.

**How to avoid:**
Health Auto Export **does** support custom request headers, including `Authorization: Bearer <token>` and
`X-API-Key` (confirmed in its official REST API docs). Use one. Verify it with
`secrets.compare_digest` over **bytes**, following the exact pattern and reasoning already established in
`StaticTokenVerifier.__init__` (`auth.py:37-46` — a `str` compare raises `TypeError` on non-ASCII header
bytes, which escapes as a 500 with traceback rather than a 401). Store it in Google Secret Manager beside
`MCP_AUTH_SECRET` and add it to `Settings.secret_values()` so `configure_logging`'s scrubber redacts it.
Fail **closed** and **silent** — return a bare 401 with no body detail, matching `auth.py`'s stated
contract.

Write the negative test: `test_webhook_rejects_a_request_with_no_credential`. Then add a *static* guard in
the style of `backend/tests/test_mcp_isolation.py` asserting that every route registered on the FastAPI app
other than `/health` carries an auth dependency — so route #3 cannot be added unguarded.

**Warning signs:**
An HTTP route module under `app/api/routes/` with no `Depends(...)` in its decorator. A Cloud Run request
log showing 2xx on the webhook path from an IP outside the user's carrier ranges.

**Phase to address:** Apple Health webhook ingest phase — this is the phase's first success criterion, not a hardening afterthought.

---

### Pitfall 4: Non-idempotent ingest, when Health Auto Export re-sends overlapping windows by design

**What goes wrong:**
Health Auto Export's **Default** export period is documented as: *"Syncs data for the full previous day plus
data up to the current date and time."* Run that automation hourly and every run re-sends the whole of
yesterday plus a growing slice of today. Its docs describe **no deduplication mechanism** on the sender
side. A naive `INSERT` receiver therefore accumulates duplicate rows on every run — and because the data
feeds averages, duplicates do not error, they *bias*. A body weight re-sent 24 times gets 24 votes in a
7-day mean.

This is the one integrity property BRETT already treats as non-negotiable for Hevy ("Hevy sync must be
idempotent and must never corrupt existing data on partial/failed sync" — CLAUDE.md constraint), and the
webhook is where it is easiest to forget, because a webhook *feels* like an event rather than a sync.

**Why it happens:**
Webhooks are mentally filed as "push, therefore each delivery is new". HAE's Default period breaks that
assumption, and the `session-id` header it sends is unique *per request*, so it looks like a dedup key while
being exactly the wrong one — the same measurement arrives under a different `session-id` every run.

**How to avoid:**
Key on the **measurement's own identity**, never on delivery identity. Follow the pattern already proven in
`backend/app/integrations/hevy/body.py:97-120`: `pg_insert(...).on_conflict_do_update(constraint=...)`
against a natural-key unique constraint. For Apple Health metrics the natural key is
`(user_id, source, metric_name, measured_at)` — plus the aggregation interval, because HAE can send the same
underlying samples aggregated hourly *and* daily depending on configuration, and those are genuinely
different rows that must not collide.

Make the whole delivery **one transaction**. HAE reports per-day failures; a half-applied batch that returns
500 and is never retried is worse than a rejected one.

**Warning signs:**
Row counts growing faster than wall-clock days. A 7-day body-weight average that moves when no new weigh-in
happened. `rows_upserted` in your ingest result consistently equal to rows received (a healthy steady-state
run should be mostly no-op updates).

**Phase to address:** Apple Health webhook ingest phase. Verify with a test that POSTs the *identical* payload twice and asserts the row count and every computed average are unchanged — the direct analogue of `test_hevy_sync.py`'s duplicate test.

---

### Pitfall 5: Payload size and cold start collide with a 512 MiB / 32 MiB / 30-second budget

**What goes wrong:**
Four hard numbers, all verified, that nobody checks until the first real sync:

| Limit | Value | Source |
|---|---|---|
| Cloud Run max HTTP/1 request body | **32 MiB** | Google Cloud Run quotas |
| BRETT's instance memory | **512 MiB** | `scripts/deploy-cloud-run.sh` (`--memory=512Mi`) |
| BRETT's min instances | **0** (cold start on every idle period) | `deploy-cloud-run.sh` (`MIN_INSTANCES="${BRETT_MIN_INSTANCES:-0}"`) |
| iOS background task budget | **30 seconds** | Health Auto Export docs |

Health Auto Export's own documentation warns that backends should handle payloads of *"possibly several
hundred megabytes"* for large exports with fine-grained aggregation. That exceeds the Cloud Run request cap
by an order of magnitude, and FastAPI/Starlette buffers the request body in memory by default — so a payload
that *does* squeak under 32 MiB still risks OOM-killing a 512 MiB instance, which Cloud Run surfaces as a
generic 503 with no application log.

Separately: `MIN_INSTANCES=0` means the first webhook delivery after an idle period pays a full cold start.
Add JSON parse + N upserts and you can blow past HAE's 30-second iOS background budget, which fails the
export on the *device* side with "Health data could not be fully read."

**Why it happens:**
The `--memory=512Mi` and `--min=0` settings were correct for v1.0, where all inbound traffic was small MCP
JSON-RPC calls and all bulk work happened in an outbound-only Cloud Run Job.

**How to avoid:**
- Configure the HAE automation with **Batch Requests ON** and a **coarse aggregation interval** (hours, not
  seconds), and document that configuration in `docs/` as part of the setup — it is a deployment
  prerequisite, not a user preference.
- Enforce a request-body size cap in the webhook handler and reject oversized bodies with a clear status
  before parsing, rather than discovering the limit as an OOM.
- Keep the handler's synchronous work minimal: validate, upsert, return. Do not compute analytics inline.
- Consider `--min=1` for the service, or accept cold starts and set HAE's user-configurable request timeout
  generously. Note that `--min=1` also removes the cold-start risk against Claude's documented 10-second
  connector-discovery budget (CLAUDE.md) — one change, two problems.

**Warning signs:**
Cloud Run 503s with no corresponding application log line (the OOM signature). HAE Activity Log entries
showing timeouts. `--cpu-boost` masking the problem in testing but not under concurrent load with
`--max=2`.

**Phase to address:** Apple Health webhook ingest phase, with the deployment-flag change made and verified before the first real device sync.

---

### Pitfall 6: Parsing a 182 MB `export.xml` in-process OOMs the service

**What goes wrong:**
The backfill source file is real and already on disk: **`export.xml` is 182 MB** (`export_cda.xml` is 79 KB
and is the wrong file — it is the CDA clinical-document variant, not the HealthKit sample dump).
`xml.etree.ElementTree.parse()` builds the entire DOM in memory; for a 182 MB Apple Health export that is
routinely 1.5–2 GB of Python objects. On a 512 MiB Cloud Run instance that is an instant OOM kill.

**Why it happens:**
`ElementTree.parse()` is the obvious API and works fine on the 79 KB file you test with.

**How to avoid:**
Two rules:
1. **Stream it.** `ET.iterparse(path, events=("end",))` with an explicit `elem.clear()` and a
   `root.clear()`-equivalent after each `Record` element. Without the clear, `iterparse` still accumulates
   the tree and you have written a slower version of the same bug.
2. **Do not run it through the web service at all.** This is a one-time operation on a file the user already
   has locally. Run it as a `app/cli.py` subcommand (the pattern already exists — the Hevy sync runs as
   `uv run python -m app.cli sync-hevy` in a Cloud Run Job), executed locally against the production
   database, or as a one-off Cloud Run Job with raised memory. An HTTP upload path for a 182 MB file also
   walks straight into Pitfall 5's 32 MiB cap.

Additionally: the backfill and the ongoing webhook write into the same tables. Make the backfill use the
**same upsert path** as the webhook, so running the backfill after the webhook has been live for a week is a
no-op on the overlapping days rather than a duplicate-or-clobber event.

**Warning signs:**
A backfill command that works on a trimmed test file and dies with exit 137 (SIGKILL) on the real one.
Memory profile climbing monotonically through the parse.

**Phase to address:** Apple Health backfill phase. Success criterion should be "the real 182 MB `export.xml` parses to completion within the instance memory budget", tested against the actual file, not a fixture.

---

### Pitfall 7: The freshness envelope defaults to `provider="hevy"` and starts lying the moment a second provider writes

**What goes wrong:**
`backend/app/analytics/metadata.py:137-143`:

```python
async def build_freshness(session, *, user_id, resources, provider: str = PROVIDER_HEVY) -> FreshnessMetadata:
```

Every single analytics call site uses that default. `FRESHNESS_RESOURCES_BODY` is
`(RESOURCE_BODY_MEASUREMENTS,)`, so `fitness_get_body_weight_trend` reports the `last_synced_at` of the
**Hevy** body-measurements sync — regardless of where the weight actually came from.

Once Apple Health (or manual entry) writes body weight, this is a *silent lie in both directions*:
- Apple Health pushed a weigh-in five minutes ago, Hevy's body sync last ran six hours ago → the response
  claims six-hour-old data and Claude, obeying the coaching instructions, warns the user about staleness
  that does not exist.
- Hevy body sync is healthy but Health Auto Export stopped running two weeks ago → the response claims
  fresh data and Claude answers confidently from a stale Apple Health picture.

This directly breaks DQ-01, the requirement PROJECT.md records as *resolved at the v2.0 boundary* — and it
breaks it without any error, test failure, or code change in the analytics layer.

**Why it happens:**
`provider` was given a default because there was exactly one provider. The default is invisible at 20+ call
sites.

**How to avoid:**
Remove the default. Make `provider` (or better, a sequence of `(provider, resource)` pairs) **required** so
adding a provider is a `TypeError` at every call site rather than a silent wrong answer — the same
discipline `resolve_user_id`/`user_id`-with-no-default already applies for ASVS V4. Define the v2.0
resource tuples explicitly (`FRESHNESS_RESOURCES_BODY` must name *every* provider that writes
`body_measurements`) and follow the existing rule from `FRESHNESS_RESOURCES_MUSCLE`'s comment: an answer is
only as fresh as the **stalest** input that feeds it.

Write a `sync_state` row for the webhook provider on every successful delivery, so `last_synced_at` is real
rather than perpetually `None` (which `build_freshness` correctly reports as "never synced" — accurate, and
useless).

**Warning signs:**
A `FreshnessMetadata` response whose `resources` map has fewer keys than the number of providers writing the
tables that answer fed from. Claude flagging staleness immediately after a successful webhook delivery.

**Phase to address:** Apple Health webhook ingest phase (write the `sync_state` row) **and** the health-analytics-extension phase (fix the provider parameter). Do not defer — this pitfall is invisible until someone notices Claude giving a wrong freshness warning, which may be never.

---

### Pitfall 8: `body_measurements.source` is `VARCHAR(16)` and `'health_auto_export'` is 18 characters

**What goes wrong:**
`backend/app/db/models/body.py:50` and migration `0004_hevy_reference_tables.py:87`:
`sa.Column("source", sa.String(length=16), nullable=False)`. Candidate source names:

| Candidate | Length | Fits `VARCHAR(16)`? |
|---|---|---|
| `hevy` | 4 | yes (existing) |
| `manual` | 6 | yes (existing) |
| `apple_health` | 12 | yes |
| `healthkit` | 9 | yes |
| `health_auto_export` | **18** | **no — `StringDataRightTruncation`** |
| `apple-health-export` | 19 | no |

PostgreSQL raises rather than truncating, so this fails loudly — but it fails at *insert time in
production*, potentially inside the first real webhook delivery, and the natural "fix" under pressure is to
shorten the string in one place and miss another, leaving two spellings of the same source in one column.

**Why it happens:**
16 was generous for `'hevy'` and `'manual'`. Nobody widens a column they are not thinking about.

**How to avoid:**
Pick `'apple_health'` (12 chars, describes the *data origin* rather than the *transport*, and survives a
future switch away from the Health Auto Export app). Define it as a module constant next to
`bodyweight.MANUAL_SOURCE`, never as an inline literal. If you want transport-level detail, that belongs in
`sync_state.provider` (`VARCHAR(32)`), not in the row discriminator. If a longer name is genuinely wanted,
widen the column in the same migration that introduces the source — do not discover it at runtime.

**Warning signs:**
`asyncpg.exceptions.StringDataRightTruncationError` in the webhook path. Two source strings in
`SELECT DISTINCT source FROM body_measurements`.

**Phase to address:** Apple Health webhook ingest phase (schema migration plan).

---

### Pitfall 9: `_dedupe_by_day` resolves source conflicts at ROW grain, which deletes columns when extended beyond weight

**What goes wrong:**
This is the most subtle data-integrity pitfall in the milestone, and it is *latent today*.

`backend/app/analytics/bodyweight.py:129-155` implements D-14 — "a manual entry is a deliberate correction
of that day's number, so it wins":

```python
def _dedupe_by_day(rows):
    by_day, seen_manual = {}, set()
    for row in rows:                      # ordered by (measured_on, source)
        if row.weight_kg is None: continue
        if row.measured_on in seen_manual: continue
        by_day[row.measured_on] = row.weight_kg
        if row.source == MANUAL_SOURCE: seen_manual.add(row.measured_on)
    return by_day
```

Two things break when v2.0 extends this beyond weight-only:

**(a) Row-level precedence discards columns.** The natural key is
`UniqueConstraint("user_id", "source", "measured_on")` — the whole *row*, per source, per day. So a day can
legitimately hold a Hevy row `(weight=65.2, waist=80.0, chest=101.0)` and a manual row
`(weight=64.8, waist=NULL, chest=NULL)`. Row-level "manual wins" is correct for weight and **destroys the
waist and chest readings for that day**. The v2.0 requirement is explicitly "trend/comparison analytics
across weight *and* circumference/composition columns" — so the moment this function is generalised, the
correct rule becomes a **per-column coalesce with a stated source precedence**, not a per-row winner.
Copying `_dedupe_by_day`'s shape for `waist_cm` is the obvious move and it silently deletes data.

**(b) The precedence ladder has exactly two rungs, and third-source precedence is decided by the
alphabet.** The ordering is `ORDER BY measured_on, source`, and correctness relies on `'hevy' < 'manual'`
alphabetically with a `seen_manual` guard on top. Introduce `'apple_health'` and it sorts **first**
(`'apple_health' < 'hevy' < 'manual'`), so a day with both an Apple Health and a Hevy weigh-in resolves to
**Hevy**, because `h` comes after `a` — a precedence nobody chose, nobody wrote down, and no test asserts.
For body weight specifically that is arguably the *wrong* answer: a smart-scale reading synced through
HealthKit is usually more trustworthy than a Hevy manual log.

The v1.0 authors saw half of this coming — the docstring says "Moot today -- zero `'manual'` rows exist --
and locked now so it cannot silently become a double-count the day manual entry ships." The double-count is
guarded. The column-shadowing and the third-source ordering are not.

**Why it happens:**
The function is correct, tested, and reads as finished. Its correctness depends on two facts that are true
today and false in v2.0: that there is exactly one column, and exactly two sources.

**How to avoid:**
- Replace the implicit alphabetical ordering with an **explicit precedence map**, e.g.
  `_SOURCE_PRECEDENCE = MappingProxyType({"manual": 3, "apple_health": 2, "hevy": 1})` — the same
  `MappingProxyType` discipline `recomposition._LABEL_MATRIX` and `exercise_map.py` already use so a caller
  cannot retune a health verdict at runtime. Raise on an unknown source rather than defaulting it to zero;
  a silently-lowest-precedence source is a source that never appears.
- Resolve **per column**, not per row: for each `(day, metric)` take the value from the highest-precedence
  source that has a non-NULL value for *that metric*.
- Add the regression test that does not exist today: one day, three sources, partially overlapping columns,
  asserting every column resolves independently.

**Warning signs:**
A waist or chest series that develops holes on exactly the days a manual weight was entered. A body-weight
value that changes when Apple Health is connected, with no new weigh-in.

**Phase to address:** Historical body measurements phase — but the *fix* must land before or with the Apple Health webhook phase, since Apple Health is the third source that triggers (b).

---

### Pitfall 10: The repo already documents, with live-data evidence, why max-weight was rejected as the progression signal

**What goes wrong:**
`backend/app/analytics/progression.py:7-10`, verbatim:

> **The day's headline set is the one with the highest ESTIMATED 1RM, not the heaviest.** Epley maps 60 kg x
> 10 to 80.000 and 70 kg x 5 to 81.667: a lighter set at more reps can imply more strength. Picking the
> heaviest weight instead returns a number that is real, in the right units, and wrong — and it silently
> flattens a lifter who progressed by adding reps rather than load.

The v2.0 decision to make max-weight-lifted primary is a *user-preference* decision ("the user trains and
thinks in terms of the heaviest weight moved"), and it is legitimate. But it walks directly into a failure
mode the v1.0 author identified and wrote down. If the switch is implemented as "change the ranking key in
`best_set_per_day`", then on this user's actual data — where `progression.py:24-27` records that every
high-frequency template spans reps 5–12 with a standard deviation of 1.9–2.4 — a rep-progression block
(same load, more reps, week over week) reads as a **flat line**, and `classify_trend` returns `stable` for
training that is objectively improving.

**Why it happens:**
The requirement says "max-weight-lifted becomes the primary signal". The smallest change that satisfies that
sentence is a one-line ranking swap. The consequence is three modules away.

**How to avoid:**
Treat this as a **two-signal design**, not a substitution. Concretely:
- Keep `best_set_per_day`'s existing e1RM-ranked selection *and* add a max-weight-ranked selection, both
  derived from the same `qualifying_set_rows` fold (the module's own "one aggregate, folded once" rule).
  `SessionBest` already carries `best_weight_kg` beside `best_e1rm_kg` — the data is there.
- Make the *headline* verdict max-weight, and carry the e1RM verdict as a required sibling field, the same
  way `RecompositionResult` carries `progression_signal` beside `status` specifically so a disagreement is
  visible rather than resolved.
- Surface the disagreement explicitly: "max weight flat, estimated 1RM improving" is the sentence that
  detects rep progression, and it is only sayable if both numbers are in the payload.

The precedent is already in the codebase: `progression.py:29-35` argues at length that PROG-02 and PROG-03
"will disagree on real data, and both will be right", and solves it by making each carry its window as a
field. Do the same for the two strength signals.

**Warning signs:**
A trend verdict of `stable` for an exercise whose `total_reps` is climbing across weeks. `weeks_with_data`
jumping from a gated subset to 100% of training weeks (see Pitfall 11). A user saying "but I *am* getting
stronger" about an exercise the tool calls flat.

**Phase to address:** Strength-metric-shift phase, as an explicit design decision recorded in the phase context — with `progression.py`'s existing docstring quoted and answered, not deleted.

---

### Pitfall 11: Max weight is ungated, so removing e1RM's gates destroys the "we could not tell" honesty path

**What goes wrong:**
`estimate_1rm` (`backend/app/analytics/estimates.py:64-89`) applies two gates and returns a
`NoEstimateReason` when either fails: modality must be exactly `weight_reps` (`E1RM_EXERCISE_TYPE`), reps
must be 1–`MAX_TRUSTED_REPS` (12). The live-data consequence is recorded in the module: **4,802 of 7,719
live hard sets pass both gates**, and `progression.py:14-16` notes **376 of 2,239 exercise-sessions (16.8%)
have no e1RM-qualifying set at all**.

Max weight has no such gates by design — `records.py` says so explicitly: *"D-02's 12-rep cap gates the
ESTIMATE, never the observation. The rep PR and the max-weight PR are deliberately un-gated."*

So switching the primary signal to max weight makes **~100% of sessions qualify**. Downstream, that is not
"more data", it is the loss of a signal:
- `weeks_with_data` on `ExerciseTrend` jumps, so `MIN_TREND_WEEKS = 4` stops filtering anything and
  `TrendVerdict.UNCLEAR` all but disappears.
- `aggregate_progression` (`recomposition.py:107-150`) deliberately **excludes `unclear` from the
  denominator**. If `unclear` vanishes, the denominator inflates with low-information exercises and
  `RECOMP_PROGRESSION_NET_BAND = 0.25` is being applied to a different population than it was calibrated on.
- `scan_plateau`'s D-07a skip (`best_e1rm_kg is None` → skip, neither extends nor breaks the streak) becomes
  a dead branch. Deload weeks and high-rep accessory days now *extend* plateau streaks — reintroducing
  exactly the false positive the skip exists to prevent, in the opposite direction.
- `ProgressionPoint.no_estimate_reason` is a field in the MCP response contract that stops being populated,
  so Claude loses the "here is *why* there is no number" explanation without any schema change.

**Why it happens:**
Ungated feels strictly better — more coverage, fewer nulls. The gates were never about coverage; they were
about not putting a number on a set that cannot support one.

**How to avoid:**
Decide, per downstream consumer, what "insufficient" means under the new signal, and say it in the phase
context before writing code:
- Keep a **modality gate** for max weight. A bodyweight or duration-only exercise has no meaningful "heaviest
  weight" — `progression.py:93` already documents 48 live non-warm-up sets with a genuine `Decimal("0.000")`
  weight, which the `_NO_WEIGHT_RANK = Decimal(-1)` sentinel exists to rank below real weights. That
  sentinel logic must survive the switch or a bodyweight exercise will report a max weight of 0 kg as a real
  observation.
- Keep `no_estimate_reason` populated (rename it if the semantics widen), so the honesty channel stays open.
- Re-derive `MIN_TREND_WEEKS` and the plateau skip semantics against the new signal rather than inheriting
  numbers tuned for the gated one.

**Warning signs:**
`UNCLEAR` verdict count dropping to near zero. Plateau durations getting *longer* across the board.
`no_estimate_reason` absent from every response.

**Phase to address:** Strength-metric-shift phase.

---

### Pitfall 12: Three tuned constants are calibrated against e1RM's continuous distribution, and max weight is a step function

**What goes wrong:**
The switch changes the *statistical character* of the input, and every threshold downstream was tuned to the
old character on live data. In detail:

| Constant | Value | Where | Calibrated how |
|---|---|---|---|
| `TREND_STABLE_BAND_PERCENT_PER_WEEK` | `0.5` %/wk | `progression.py:328` | **Derived**: D-07's 2% band ÷ D-05's 4 weeks. Validated on live data: 9 improving / 9 stable / 10 declining across 28 exercises |
| `PLATEAU_IMPROVEMENT_TOLERANCE` | `0.02` (2%) | `progression.py:522` | Chosen to absorb Epley rep-scheme noise |
| `RECOMP_PROGRESSION_NET_BAND` | `0.25` | `recomposition.py:93` | Applied to the 9/9/10 live split |

Two structural problems:

**(a) D-18's derivation collapses.** `progression.py:314-328` is explicit that 0.5%/week is *not an
independent number* — it is 2%/4 weeks, and sharing one underlying figure is what makes PROG-02 and PROG-03
unable to contradict each other **by construction**. If the plateau tolerance and the trend band are
re-tuned independently for max weight, that structural guarantee is gone, and the codebase will happily
report an exercise as `improving` at a rate the plateau scanner refuses to call an improvement.

**(b) Max weight moves in discrete increments, not continuously.** Machine stacks and plate loading move in
2.5–5 kg steps. On a 100 kg lift a single 5 kg increment is a **5% jump** — 2.5× the plateau tolerance — so
*every* load increase breaks the streak. Between increases, every session is *exactly* equal, so the
tolerance band does nothing at all. The 2% band, which was a noise filter for a continuous quantity, becomes
a no-op applied to a step function. Meanwhile OLS (`_weekly_slope`) over a staircase with long flats and
occasional jumps produces a slope dominated by *when* the jump landed in the window — move the window one
week and the verdict flips.

**Why it happens:**
The constants have names that read like policy ("2% tolerance") rather than like calibration artefacts. Only
the comments record that they were fitted to a specific distribution on specific data.

**How to avoid:**
- Re-run the calibration the same way v1.0 did — against the live account, reporting the improving /
  stable / declining split — and record the new numbers and the split in the phase context. A threshold
  carried over without re-validation is a number that was right about a different quantity.
- Preserve the *derivation relationship*: whatever the new band is, derive the trend band from the plateau
  tolerance and the minimum window, and say so in a comment, so D-18's structural guarantee survives.
- Consider whether "plateau" even means the same thing under max weight. Under e1RM it meant "your ceiling
  hasn't moved". Under max weight it means "you haven't added load" — which is a longer, coarser, and
  arguably more useful signal, but it is a **different definition** and `PlateauResult`'s
  `threshold_percent` / `min_sessions` / `min_elapsed_days` echo fields must describe the new one honestly.

**Warning signs:**
Trend verdicts that flip when `weeks` changes by one. All exercises classifying as `improving` or
`declining` with almost nothing `stable` (band too tight for a step function), or the reverse.
`recomposition_status` changing for the whole account on the deploy that ships the switch.

**Phase to address:** Strength-metric-shift phase. The phase's success criterion should be a *before/after* comparison table on live data, not just green tests — green tests will stay green, because the fixtures move with the code.

---

### Pitfall 13: `confirm=true` as a plain tool parameter is not a confirmation gate

**What goes wrong:**
This is the highest-severity pitfall in the milestone, because it is the one that lets a language model
mutate state without the user's knowledge, in a system whose entire security posture to date has been
"nothing can write".

PROJECT.md's decision describes a "two-call design: first call warns, second call with `confirm=true`
switches". If `confirm` is exposed as a `bool` in the tool's `inputSchema`, **the model can set it to `true`
on the very first call.** There is no protocol-level rule that a model must make the warning call first;
`confirm` is just another argument it is free to populate, and a model that has been told "switch me to a
cut" will helpfully do exactly that in one shot. The warning step is advisory, not a gate.

Compounding it: `mcp 2.0.0`'s `Context.elicit()` exists and looks like the correct primitive — but the
SDK's own docstring (read from the installed package) says:

> "If the client is an agent, it might decide how to handle the elicitation — **either by asking the user or
> automatically generating a response.**"

So elicitation is *also* not a guaranteed human gate. And `Context.client_capabilities` documents that it is
`None` "when the client declared none (e.g. an **anonymous stateless request** without the reserved `_meta`
keys)" — BRETT builds its app with `stateless_http=True` (`server.py:221`), so a capability check will
frequently return `None` and a tool that depends on elicitation will fail on the one client the user
actually uses.

On the client side: Claude Desktop's tool-approval dialog has an "Always approve" option which community
sources report **cannot be undone** once clicked. Client-side approval is therefore a control the user can
permanently disable by accident.

**Why it happens:**
"Two-call confirm" sounds like a protocol. Implemented as a boolean parameter, it is a naming convention.

**How to avoid:**
Make the second call **impossible to construct without the first**:
- The warn call returns a **server-generated, single-use, short-TTL confirmation token** (e.g.
  `secrets.token_urlsafe(16)`), persisted server-side with the *exact target state* it authorises
  (`from_program`, `to_program`, `issued_at`, `expires_at`, `consumed_at`).
- The switch call takes `confirmation_token: str`, not `confirm: bool`. The model cannot guess it; it can
  only echo back what the server just gave it, which means the warning text was necessarily rendered into
  the conversation first.
- Bind the token to the target: if the token was issued for "switch to cut" and the second call asks for
  "switch to lean bulk", reject. Otherwise the model can reuse a token to perform a *different* switch than
  the one the user saw described.
- Consume atomically (`UPDATE ... WHERE consumed_at IS NULL RETURNING ...`) so a retried second call is a
  no-op rather than a double-switch.
- Expire in minutes, not hours. A stale token found in a scrolled-back conversation must not still work.

Do **not** rely on `ctx.elicit()` as the control. It is acceptable as an *additional* prompt where the
client supports it; it is not the gate.

**Warning signs:**
A tool schema containing a boolean named `confirm`, `force`, `yes`, or `acknowledged`. A test that switches
a program in a single tool call. Any code path where the first call has a side effect.

**Phase to address:** Training-programs / write-tool phase. This is the phase's defining success criterion: "a single tool call cannot change the active program", proven by a test that tries.

---

### Pitfall 14: Adding one write tool disarms the guards that protect the other thirteen

**What goes wrong:**
BRETT's read-only guarantee is enforced by four mechanisms, and the *smallest* way to add a write tool
breaks or bypasses each of them:

| Mechanism | Where | What the write tool does to it |
|---|---|---|
| PostgreSQL `READ ONLY` transaction | `_common.read_only_session` (`_common.py:123-154`) | Needs a writable session. Temptation: relax `read_only_session` itself, which silently un-protects all 13 read tools |
| Static ban on writes in `app/mcp/` | `test_mcp_isolation.py:129` `test_mcp_never_writes` — bans `session.commit\|flush\|add\|add_all` and `from sqlalchemy import insert\|update\|delete` across every module under `app/mcp/` | **Will fail on the commit that adds the tool.** Temptation: delete the test |
| `READ_ONLY` annotations applied by loop | `server.py:215-216` — `for _fn, _description in _TOOLS: mcp.add_tool(..., annotations=READ_ONLY)` | Adding the write tool to `_TOOLS` gives it `read_only_hint=True, destructive_hint=False`. `test_every_tool_is_annotated_read_only` **passes**, while the tool writes. The annotation is now an active lie to the client |
| No required scopes | `server.py:116` `required_scopes=None`, with the in-code note *"Revisit when the first write tool ships."* | Left as-is, the write tool is authorised by exactly the same token as a read |

**Why it happens:**
Each guard fails in a way whose cheapest fix is to weaken it globally. `test_mcp_never_writes` in particular
produces a red test with a message telling you the file must not write — and the two-second fix is to remove
the file from the walk or the assertion from the test.

**How to avoid:**
- **Narrow, never remove.** `test_mcp_never_writes` should take an explicit single-module allowlist (the
  program-switch tool module, by exact filename) and assert that the allowlist has **exactly one entry** —
  so adding a second write tool is also a red test. This mirrors how `test_mcp_uses_no_raw_sql_text` already
  exempts `ping.py` "by name".
- Add a **second** static assertion: that `read_only_session` is *not* referenced in the write module and
  that no other module references the writable-session helper. Two guards pointing at each other.
- Give the write tool its **own** `ToolAnnotations` — `read_only_hint=False`, `destructive_hint=True`,
  `idempotent_hint=False` — registered outside the `_TOOLS` loop, and update
  `test_every_tool_is_annotated_read_only` to assert *the exact partition*: 13 read-only tools by name, 1
  write tool by name. A test that says "all tools are read-only" must become a test that says "these 13 are
  read-only and this 1 is not", or it silently stops meaning anything.
- Revisit `required_scopes` as the in-code note instructs. Note the tradeoff the same comment records:
  adding a required scope "would mean re-consenting the Phase 2 connector that already works." A reasonable
  middle path is a scope required *only* by the write tool, checked in the tool body against
  `AccessToken.scopes` — but be aware `AuthKitJWTVerifier` populates scopes from the WorkOS `scope` claim,
  so this needs a corresponding AuthKit configuration change and an end-to-end re-verification, not just
  server code.
- The writable session must **not** live in `app/analytics/` — `test_analytics_isolation.py` bans writes
  there too, and for good reason. Put it in `app/db/repositories/` (which owns writes today) or a new
  `app/services/programs.py`, and have the MCP tool call it.

**Warning signs:**
A diff that deletes or weakens an assertion in `test_mcp_isolation.py`. A `git log` entry touching
`_common.read_only_session`. The write tool appearing inside the `_TOOLS` tuple.

**Phase to address:** Training-programs / write-tool phase.

---

### Pitfall 15: `safe_tool` swallows write failures and reports them as "degraded", inviting a retry that double-applies

**What goes wrong:**
`_common.safe_tool` (`_common.py:254-290`) wraps every tool: any exception is logged and replaced with a
caller-supplied `degraded()` payload. It exists for an excellent, verified reason — `mcp 2.0.0` returns
`str(exception)` to the model verbatim, and an asyncpg connection error carries the full DSN.

Applied unchanged to a write tool, it produces two distinct bugs:
1. **A failed write is indistinguishable from a failed read.** Claude receives a generic
   `data_available: false` payload and, following the coaching instructions' "call a tool before making any
   claim" discipline, may simply try again — re-consuming or re-requesting a confirmation and potentially
   applying the switch twice.
2. **Worse: an exception raised *after* `commit()`** — during response serialisation, or in a follow-up read
   — returns a *failure* payload for a write that **succeeded**. The user is told the program did not
   change; it did. If they then retry, the second switch is applied to a state they do not know about.

**Why it happens:**
`safe_tool` is applied uniformly by convention (`test_every_tool_module_guards_its_public_tools` in
`test_mcp_isolation.py:212` asserts it), so the write tool gets it automatically.

**How to avoid:**
Keep `safe_tool` — the DSN leak is real — but give the write tool a **three-state** result rather than a
boolean: `applied` / `not_applied` / `unknown`. Return `unknown` from the exception path and have the
degraded payload instruct the model to **read the current program back** rather than retry. Structure the
tool so that commit is the **last** statement and everything after it is pure serialisation of already-held
values, minimising the post-commit failure window. Consume the confirmation token **in the same transaction
as the switch**, so "token consumed" and "switch applied" cannot disagree.

**Warning signs:**
A write tool whose `degraded()` factory returns the same shape as a read tool's. A conversation transcript
where Claude calls the switch tool twice in a row.

**Phase to address:** Training-programs / write-tool phase.

---

### Pitfall 16: Storing the active program as a mutable column makes every historical answer retroactively wrong

**What goes wrong:**
`recomposition.py:68-97` hardcodes five lean-bulk constants with the comment: *"The user's stated goal is a
LEAN BULK. There is no `users.goal` column and none is being added; the goal shapes these threshold VALUES
and nothing structural."* v2.0 replaces those with program data.

The obvious model is a `users.active_program` column (or a `programs` table with an `is_active` flag). But
`get_recomposition_status` classifies against a **12-week lookback** (`RECOMP_LOOKBACK_WEEKS = 12`) and a
4-week smoothed weight rate. If the program is a single mutable value, then switching from Lean Bulk to Cut
today re-classifies the **previous twelve weeks** under cut thresholds. Asked "how did my bulk go?", Claude
answers using cut thresholds, and the answer it gave last week is now unreproducible. In a system whose
entire value proposition is *"answer from actual data instead of guessing"*, a retroactively-mutating
threshold is a silent correctness failure — and one the user is uniquely positioned to notice and lose trust
over.

**Why it happens:**
"Active program" reads as current state, not as history. The temporal dimension only becomes visible when
you notice the classifier looks 12 weeks back.

**How to avoid:**
Model it as **effective-dated history**: `program_periods(user_id, program, started_on, ended_on)`, with the
switch tool closing the current period and opening a new one. Then:
- `get_recomposition_status` resolves thresholds for the period(s) its window covers, and a window spanning
  a switch is a *reportable fact* — return the program alongside the verdict, exactly as `PlateauResult`
  returns its window and threshold alongside its verdict, for exactly the same reason
  (`progression.py:29-35`: "a verdict without its window is a contradiction waiting to be narrated").
- A window straddling a program change should say so rather than silently picking one.

This also gives the write tool something honest to report: "switched from Lean Bulk (started 2026-06-14, 11
weeks) to Cut" — which is a far better confirmation prompt than "switch program?".

**Warning signs:**
A `programs` table with a boolean `is_active` and no date columns. A recomposition response that does not
name the program it classified against. Two runs of the same question a day apart giving different verdicts
with no new data.

**Phase to address:** Training-programs / write-tool phase, in the schema plan — this is a modelling decision, and it is nearly free now and expensive after there is history.

---

### Pitfall 17: Building the report feature around a client capability that is documented-broken and closed "not planned"

**What goes wrong:**
PROJECT.md's decision: *"Weekly/monthly reports = on-demand MCP tools driven by Claude's own scheduled-tasks
feature, not a BRETT-side scheduler."* The architectural half of that (no server-side scheduler, no push
channel, reports as ordinary MCP tools) is sound and low-risk. The **delivery** half depends on a client
feature with a documented failure mode:

- **anthropics/claude-code#43397** (opened 2026-04-04, **closed as not planned**): *"Cloud scheduled tasks
  cannot access MCP connectors — tools not loaded into session."* The agent runs `ToolSearch` per connector
  and gets "No matching deferred tools found" for all of them. **100% reproducible.** Sending any user
  message into the same session immediately makes the connectors available — i.e. the failure is specific to
  autonomous start, which is the entire point of scheduling. Listed as a regression from before 2026-03-31.
- **anthropics/claude-code#45306** (opened 2026-04-08, **closed as not planned**): scheduled tasks fail
  *silently* — the agent only has WebFetch, WebSearch, RemoteTrigger and filesystem tools, and reports "the
  required integrations are not available in this environment." Affects both API-created and UI-created
  triggers.
- Related issues span Claude Desktop too (#35899, #36327), plus #40835 ("creating new tasks disables
  connectors in existing tasks").
- Separately, community reports describe OAuth token expiry crashing scheduled tasks — directly relevant
  here, because `AuthKitJWTVerifier` **fails closed** by design (`auth.py:69-73`) and a non-interactive
  session has no way to complete a refresh.

The risk is not "the reports are bad". It is that the milestone's success criterion — "reports Claude can
deliver on a schedule" — may be **unachievable for reasons entirely outside this repo**, discovered only at
the end of the phase.

**Why it happens:**
The feature is real, documented and demoed. Its interaction with third-party connectors is where it breaks,
and that is not visible from the feature's own documentation.

**How to avoid:**
- **Spike it first, in a day, before building the report tools.** Schedule a task that calls the *existing*
  `fitness_ping` and check it actually runs autonomously. This is the cheapest possible de-risk and it uses
  a tool that already ships.
- **Decouple the value from the delivery.** Design the report tools so they are fully valuable **on demand**
  ("give me my weekly report"). Then scheduling is an enhancement, and a scheduled-task failure is a missed
  convenience rather than a failed phase.
- If the spike fails, the documented community workaround for #43397 is to structure the scheduled prompt to
  **delegate to a sub-agent**, which initialises MCP tools correctly. Capture that in
  `docs/coaching-instructions.md` or a setup doc rather than in server code.
- Record explicitly in the phase context that this dependency is unverified and outside the repo's control.

**Warning signs:**
A scheduled run that completes with no output and no error. A run whose transcript contains "I don't have a
BRETT tool available in this environment". A 401 in Cloud Run logs at the scheduled time.

**Phase to address:** Report-tools phase, as a **spike plan before** the implementation plans. Consider sequencing this phase early enough that a negative result can reshape the milestone rather than sink a phase.

---

### Pitfall 18: The report tool fans out across every analytics module and blows both the context budget and the cold-start budget

**What goes wrong:**
A weekly/monthly report composing "volume, strength, measurements, trends, and recommendations into one
structured payload" is `fitness_get_training_summary` again, but wider. That tool's docstring
(`mcp/tools/schemas.py`, `TrainingSummaryResponse`) records the measurement that made it possible:

> "composing the four analytics results verbatim measures ~24 KB structured / ~57 KB wire at a 4-week
> window; this shape is ~3,963 / ~9,502."

That is a **6× reduction achieved by deliberate field selection**, and it is why the summary tool
*excludes* personal records, plateaus, the per-exercise frequency list and the per-week × per-muscle grid. A
monthly report is a wider window (higher `weeks`) over *more* modules — the naive composition is
comfortably worse than the 24 KB shape that was already rejected.

Simultaneously, on the runtime side: `get_recomposition_status` alone already calls
`get_body_weight_trend` → `get_exercise_trends` → `get_weekly_volume`, each with its own
`build_coverage`/`build_freshness` round trips. A report that adds records, plateaus, per-muscle rollups and
multi-column measurement trends multiplies the query count, on a service with `MIN_INSTANCES=0` (cold start)
and `MAX_INSTANCES=2` (SQLAlchemy pool ≤10 connections per instance).

**Why it happens:**
"One structured payload" reads as a composition problem. It is a budget problem, and the budget was already
found to be binding at a narrower scope.

**How to avoid:**
- Set the byte budget **before** writing the tool, in the phase context, and measure it the way Phase 6
  measured the summary (structured and wire, at the widest legal window). Add it to
  `test_mcp_tool_budget.py`, which already exists for this purpose.
- Add a `MAX_REPORT_WEEKS` cap next to `MAX_SUMMARY_WEEKS = 12` in `_common.py` — the monthly report's window
  is the multiplier on everything.
- Reuse the existing composition (`get_training_summary`'s selected fields) as the report's spine and add
  *narrow* extras, rather than composing full analytics results and trimming afterwards.
- Use `truncate()` (`_common.py:293`) for every list, and carry both returned flags — an unlabelled cap in a
  report is exactly the "wrong answer with no signal that anything was withheld" that function's docstring
  warns about, and a report is the response most likely to be read as complete.

**Warning signs:**
A report tool that calls three or more `app.analytics` entry points without a measured payload size. Tool
latency creeping toward the client's tool-call timeout on a cold instance.

**Phase to address:** Report-tools phase.

---

### Pitfall 19: The coaching document has ~1,800 characters of headroom, and v2.0 wants to add four topics to it

**What goes wrong:**
`backend/tests/test_coaching_doc.py` enforces `_PASTE_CEILING_CHARS = 9_000` — the practical ceiling for a
Claude Project's custom-instructions field, past which *"it silently did not all fit"* becomes the likely
failure, and *"that failure is invisible from this repo."* `docs/coaching-instructions.md` is currently
**7,216 characters**. Headroom: **1,784 characters.**

v2.0 needs that document to gain: Apple Health data sources and their freshness semantics, the max-weight vs
e1RM distinction (and how to narrate a disagreement between them), the new report tools, the program-switch
confirmation protocol (what to say on the warn call, what not to do), the new body-measurement tools, and —
simultaneously — the requirement to become **more concise**.

The same test also enforces a **bidirectional drift guard**: every `fitness_*` token in the document must
exist in the live MCP registry, and every registered tool (except the `fitness_ping` canary) must appear in
the document. So new tools *must* be documented — it is not optional — while the budget shrinks.

**Why it happens:**
The ceiling is enforced by a test nobody thinks about until it goes red, at which point the cheapest fix is
to raise the constant — which converts a loud failure into the silent truncation the constant exists to
prevent.

**How to avoid:**
Treat the coaching document as a **budgeted artefact with a rewrite plan**, not an append target. The
"concise coaching style" requirement is the lever: it is not a separate nice-to-have, it is what pays for
the new content. Draft the v2.0 document by rewriting from scratch against the new tool set rather than
editing in place. Do **not** raise `_PASTE_CEILING_CHARS`. If content genuinely will not fit, move the
overflow into the server's `_INSTRUCTIONS` string (`server.py:76-86`) — but note that file's own honest
caveat: whether Claude's custom connector actually injects `instructions` into the model's system prompt is
**UNVERIFIED**, so it is a belt, not a replacement for the braces.

**Warning signs:**
`test_coaching_doc.py` failing on length. A diff that increases `_PASTE_CEILING_CHARS`. A tool shipped
without a corresponding row in the document's mapping table (the drift guard catches this — do not silence
it).

**Phase to address:** Coaching-style phase, sequenced **after** all new tools exist so the rewrite happens once against the final registry.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Delete `test_mcp_never_writes` to land the write tool | Green suite in one line | Silently reopens write capability for all 13 read tools; the guard's whole value was that it fails on the commit that introduces a violation | **Never.** Narrow it to a one-module allowlist and assert the allowlist length |
| Add the write tool to the `_TOOLS` loop | No new registration code | Tool advertises `readOnlyHint: true, destructiveHint: false` to the client — an active lie, and `test_every_tool_is_annotated_read_only` keeps passing | **Never.** Register it separately with its own annotations |
| `confirm: bool` instead of a server-issued token | Simpler schema, one fewer table | The model can set it on the first call; the "two-call design" becomes a naming convention | **Never** — this is the milestone's only write path |
| Reuse `_dedupe_by_day`'s row-level shape for circumference columns | Symmetric with the weight path, no new concepts | Manual weight-only entries silently delete that day's Hevy circumference readings | **Never.** Per-column coalesce with explicit precedence |
| Keep `build_freshness(provider=PROVIDER_HEVY)` default | Zero call sites to change | DQ-01 lies in both directions once a second provider writes; no test catches it | Only until the first non-Hevy write lands — i.e. not past the webhook phase |
| `users.active_program` column instead of dated periods | One column, trivial write tool | Twelve weeks of history retroactively re-classified on every switch; past answers unreproducible | Acceptable **only** if recomposition drops to a window shorter than the shortest program — it does not (12 weeks) |
| Reuse the global rate-limit bucket for the webhook | No new code | HAE has no retry; a 429 is permanent data loss for that window | Acceptable only for an initial spike, never for the shipped receiver |
| Parse `export.xml` with `ElementTree.parse()` | Five lines | OOM on the real 182 MB file; only shows up against production data | Acceptable in a throwaway local exploration script only |
| Raise `_PASTE_CEILING_CHARS` above 9,000 | Coaching doc test goes green | Converts a loud failure into silent truncation of the instructions Claude actually reads | **Never** — rewrite the doc instead |
| Ship the strength switch without re-calibrating the three tuned constants | Small diff, green tests (fixtures move with the code) | Trend/plateau/recomposition verdicts change account-wide with no evidence they are right | **Never.** The constants were fitted to a distribution that no longer applies |
| Skip writing a `sync_state` row for the webhook provider | One fewer write per delivery | `last_synced_at` is permanently `None`; Claude flags Apple Health as "never synced" forever | **Never** — it is one upsert |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| **Health Auto Export → webhook** | Assuming each delivery is new data | Default period re-sends "full previous day plus data up to now" on **every** run, with no sender-side dedup. Upsert on a natural key `(user_id, source, metric, measured_at, interval)` — the `pg_insert(...).on_conflict_do_update(...)` pattern already in `integrations/hevy/body.py:97-120` |
| **Health Auto Export → webhook** | Using the `session-id` header as an idempotency key | It is unique **per request**, so the same measurement arrives under a new `session-id` every run. It is the exact opposite of an idempotency key. Key on measurement identity |
| **Health Auto Export → webhook** | Returning 4xx/5xx to signal "retry later" | No retry mechanism is documented. A non-2xx is a **dropped window**, surfaced only in the app's Activity Log. Accept-then-process, and make failures loud in your own logs and `sync_state.last_error` |
| **Health Auto Export → webhook** | Leaving the route unauthenticated because "the URL is secret" | HAE supports custom headers (`Authorization: Bearer …`, `X-API-Key: …`). Use one. CLAUDE.md already rejects obscure-URL-as-auth for `/mcp`; the same reasoning applies here, more so — this one **writes** |
| **Health Auto Export → webhook** | Accepting the default (fine-grained) aggregation | Docs warn payloads may reach "several hundred megabytes"; Cloud Run's HTTP/1 request cap is **32 MiB**. Require Batch Requests ON and a coarse interval, and document it as a setup prerequisite |
| **Apple Health timestamps** | Storing the local wall-clock time HAE sends | Repo rule: timestamps stored UTC, grouped by local day via `ZoneInfo(user.timezone)`. HAE emits ISO-8601 with offset — parse the offset, convert to UTC, and let `app.core.time.local_day` do the grouping. `body_measurements.measured_on` is a `Date` by deliberate design (`body.py` docstring) — do not "upgrade" it to a timestamp |
| **Apple Health → `body_measurements`** | Writing a new `source` string longer than 16 chars | Column is `VARCHAR(16)`. `'health_auto_export'` (18) raises `StringDataRightTruncation`. Use `'apple_health'` (12) |
| **Cloud Run** | Assuming FastAPI-side routes inherit MCP auth | `RequireAuthMiddleware` wraps only the mounted `mcp_app`. The service is `--allow-unauthenticated`. Every FastAPI route needs its own dependency |
| **Cloud Run** | Adding routes below `app.mount("/", mcp_app)` in `main.py:98` | Registration order decides matching. New routers go **above** the mount |
| **WorkOS AuthKit + scheduled tasks** | Assuming a scheduled run can refresh an expired token | `AuthKitJWTVerifier` fails **closed** by design; a non-interactive session cannot complete a consent flow. Expect scheduled runs to fail after token expiry and design the report tools to be valuable on demand |
| **MCP SDK 2.0.0** | Using `ctx.elicit()` as the confirmation gate | The SDK docstring states an agent client "might… automatically generate a response". `client_capabilities` is `None` under `stateless_http=True`. Elicitation is an enhancement, not a control |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Full-DOM parse of `export.xml` | Exit 137 / SIGKILL; memory climbing monotonically | `iterparse` + `elem.clear()`, run from the CLI not the web service | Immediately — the file is already 182 MB |
| Buffering a large webhook body on a 512 MiB instance | Cloud Run 503 with **no** application log line | Reject oversized bodies before parsing; require HAE Batch Requests | First large sync, or first backfill-shaped push |
| Report tool fanning out across 5+ analytics entry points | Tool latency climbing; timeouts on cold instances | Reuse `get_training_summary`'s selected-field spine; add `MAX_REPORT_WEEKS`; measure in `test_mcp_tool_budget.py` | At `weeks=12`+ on a cold start with `MIN_INSTANCES=0` |
| Naive composition of full analytics results into the report payload | Payload well past the ~24 KB shape Phase 6 already rejected | Set and test the byte budget before implementation | At the widest legal window — i.e. exactly when a monthly report is most wanted |
| Per-day Apple Health metrics at second/minute aggregation | Row counts in the millions; `body_measurements`-adjacent queries slowing | Coarse aggregation at the source; store daily rollups, not raw samples, for anything analytics reads | Within weeks of continuous sync |
| One global 30/min bucket arbitrating two traffic classes | `rate_limit_rejected` on the webhook path; MCP 429s during a health sync | Separate bucket per traffic class | First concurrent sync + conversation |
| SQLAlchemy pool ≤10/instance × `MAX_INSTANCES=2` | Connection-pool timeouts under a webhook batch plus an MCP conversation | Keep the webhook handler's transaction short; do not compute analytics inline | When batch deliveries overlap active coaching |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Unauthenticated webhook route on an `--allow-unauthenticated` service | Anyone on the internet can write arbitrary health data into the database — poisoning every analytic and every coaching answer | Shared secret in an HAE custom header, verified with `secrets.compare_digest` over **bytes** (per `auth.py:37-46`), fail closed and silent |
| Webhook secret in the URL path instead of a header | CLAUDE.md already rejects this for `/mcp` ("a credential in a URL is a security vulnerability"); URLs land in Cloud Run request logs in plaintext | `Authorization` or `X-API-Key` header |
| New secret not added to `Settings.secret_values()` | The logging scrubber (`configure_logging`, wired in `main.py:26`) never learns to redact it; it leaks into logs on the first exception | Add to `secret_values()` in the same commit as the setting; `test_secret_redaction.py` is the existing pattern |
| Echoing webhook validation errors back to the caller | An unauthenticated endpoint that reflects parse detail is a probing oracle — the same reasoning as `_RATE_LIMITED_BODY`'s single-key body (`middleware.py:62`) | Constant, detail-free error bodies; detail to the log, findable by correlation id |
| `confirm: bool` on the write tool | A language model can mutate the user's training program without the user ever seeing a warning | Server-issued, single-use, target-bound, short-TTL confirmation token |
| Write tool inheriting `required_scopes=None` | A read token authorises a write; no way to issue a read-only credential later | Revisit per `server.py:116`'s own note; consider a write-only scope checked in the tool body |
| Write tool registered with `READ_ONLY` annotations | The client is told the tool is non-destructive; a user's "always allow" decision for read tools may extend to it | Distinct annotations, registered outside the `_TOOLS` loop |
| Relaxing `read_only_session` to accommodate one write tool | Removes the *server-side* control protecting the other 13 tools — the control that exists precisely because annotations "should not be relied upon for security enforcement" | A separate writable-session helper, used by exactly one module, statically asserted |
| Apple Health raw samples (HR, HRV, sleep) reaching logs | Blueprint §44's deny-list explicitly covers raw health samples | Log counts and metric names only, never values; extend the structlog processor and `test_secret_redaction.py` before the first ingest |
| Manual-entry endpoint added to the FastAPI side without auth | A second unauthenticated write path, for the same reason as the webhook | Same header-auth dependency; the static "every route has an auth dependency" guard covers both |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Silent strength-metric change | Every trend verdict, plateau and recomposition status shifts overnight with no explanation; the user's trust in the numbers is the product | Return **both** signals with the primary named, and note the change in the coaching document so Claude can explain it once |
| Reporting max weight for bodyweight/duration exercises | "Your max weight on Plank is 0 kg" — a real number, in the right units, meaningless | Preserve a modality gate and the `_NO_WEIGHT_RANK` sentinel semantics; report "not applicable" with a reason |
| A confirmation prompt that does not say what changes | "Switch program? yes/no" tells the user nothing about consequences | Warn call returns the current program, its duration, the target program, and **what thresholds change** — the write tool is the one place the user meets the program model directly |
| A report that silently truncates lists | Claude reads "30 exercises" as "you train 30 exercises" and answers confidently from a partial picture | `truncate()` and carry both flags into the response model, per `_common.py:293`'s docstring |
| Freshness that describes the wrong provider | Claude either warns about staleness that doesn't exist (erodes trust in the warnings) or stays silent about staleness that does (erodes trust in the answers) | Per-provider freshness; a response is as fresh as its stalest input |
| A scheduled report that silently produces nothing | The user assumes no report means nothing to report | Verify the scheduling path with a spike; make the on-demand path the primary experience |
| Manual body-measurement entry with no unit affordance | Repo internal units are kg/cm; a user entering 180 for height-in-cm vs lbs-vs-kg confusion corrupts trend analytics | Convert at the application boundary only (existing constraint); validate ranges and reject implausible values rather than storing them |

---

## "Looks Done But Isn't" Checklist

- [ ] **Webhook receiver:** often missing *auth* — verify a request with **no** credential gets 401, in a test
- [ ] **Webhook receiver:** often missing *idempotency* — verify POSTing the identical payload twice changes no row count and no computed average
- [ ] **Webhook receiver:** often missing *route ordering* — verify the path resolves to the FastAPI route, not the catch-all mount, by asserting on FastAPI-shaped error bodies
- [ ] **Webhook receiver:** often missing a *`sync_state` row* — verify `last_synced_at` for the new provider advances after a successful delivery
- [ ] **Webhook receiver:** often missing its *own rate-limit bucket* — verify a burst of webhook requests does not 429 a concurrent `/mcp` call
- [ ] **Apple Health backfill:** often missing *streaming* — verify against the real 182 MB `export.xml`, not a fixture
- [ ] **Apple Health backfill:** often missing *convergence with the webhook path* — verify running the backfill after the webhook has been live is a no-op on overlapping days
- [ ] **Strength metric shift:** often missing *re-calibration* — verify the three tuned constants against live data and record the new improving/stable/declining split
- [ ] **Strength metric shift:** often missing the *blast-radius check* — verify what `fitness_get_recomposition_status` and `fitness_get_training_summary` return before and after; `recomposition.py` changes behaviour with **zero** lines edited in it
- [ ] **Strength metric shift:** often missing the *"we could not tell" path* — verify `UNCLEAR` verdicts and a no-value-reason field still occur
- [ ] **Body measurements:** often missing *per-column* source resolution — verify a manual weight-only row does not erase that day's Hevy circumference values
- [ ] **Body measurements:** often missing *explicit third-source precedence* — verify a day with `apple_health` + `hevy` + `manual` resolves by a stated map, not by the alphabet
- [ ] **Body measurements:** often missing the *`VARCHAR(16)` check* — verify the chosen source string inserts
- [ ] **Write tool:** often missing a *real gate* — verify a single call with every parameter the model can supply cannot change the program
- [ ] **Write tool:** often missing *token binding* — verify a token issued for "switch to Cut" cannot be used to switch to Recomp
- [ ] **Write tool:** often missing *single use* — verify replaying the second call is a no-op, not a second switch
- [ ] **Write tool:** often missing *honest annotations* — verify it advertises `readOnlyHint: false, destructiveHint: true`, and that the 13 read tools still advertise read-only
- [ ] **Write tool:** often missing *narrowed guards* — verify `test_mcp_never_writes` still fails for any module other than the one allowlisted write module
- [ ] **Write tool:** often missing *post-commit failure handling* — verify a failure after commit does not report "not applied"
- [ ] **Programs:** often missing *effective dating* — verify a 12-week recomposition question spanning a program switch names the program(s) it classified against
- [ ] **Report tools:** often missing a *measured budget* — verify structured and wire size at the widest legal window, in `test_mcp_tool_budget.py`
- [ ] **Report tools:** often missing the *delivery spike* — verify a scheduled task can actually invoke `fitness_ping` autonomously
- [ ] **Coaching doc:** often missing *budget discipline* — verify it is still under 9,000 characters **without** raising the constant, and that the bidirectional drift guard passes

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Duplicate rows from a non-idempotent webhook | **LOW** while young, **MEDIUM** later | Dedup by natural key keeping the earliest `created_at`; add the unique constraint; backfill-verify averages against a Neon PITR branch (the drill from Phase 7 is already proven) |
| Public unauthenticated webhook discovered live | **MEDIUM** | Redeploy with auth immediately; audit `body_measurements`/health tables for rows outside plausible ranges or delivered from unexpected times; rotate the (now-known) endpoint path as well as adding the secret |
| Circumference data erased by row-level dedupe | **HIGH** if it reached the DB, **LOW** if only in the read path | If dedupe was read-only (as `_dedupe_by_day` is today) no data was lost — fix the function. If a write-side "merge" was implemented, restore from a Neon PITR branch |
| Strength-metric switch shipped without re-calibration | **LOW–MEDIUM** | Constants are three literals in two files; revert or retune and redeploy. The **user-trust** cost of having given wrong verdicts is not recoverable by a redeploy — which is why this belongs in the phase's success criteria |
| Write tool with a bypassable confirm | **MEDIUM** | Ship the token gate; audit `program_periods` (if effective-dated, the history is intact and auditable — a mutable column would leave no trace, which is Pitfall 16's second argument) |
| Static write guards deleted | **LOW** to restore, **HIGH** to detect | Restore from git history and narrow rather than remove; add the allowlist-length assertion so the same shortcut fails next time |
| Program modelled as a mutable column, history already accumulated | **HIGH** | Migrate to `program_periods` with a single synthetic period covering all prior history — but the actual switch dates are unrecoverable, so historical verdicts stay approximate forever |
| Scheduled delivery proves impossible | **LOW** if spiked first, **HIGH** if discovered at phase end | With the on-demand-first design, degrade to "ask for your weekly report" and document the sub-agent workaround. Without it, the phase's headline criterion fails with no fallback |
| `export.xml` backfill OOM | **LOW** | Rewrite as `iterparse` + CLI. No data damage — the failure is before any write, provided the ingest is transactional |
| Coaching doc silently truncated in the Claude Project | **LOW** to fix, **HIGH** to detect | Invisible from this repo by design. Only prevention works: keep the ceiling, rewrite rather than append |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| 1. Route below the catch-all mount | Apple Health webhook ingest | Test asserts FastAPI-shaped (not MCP-shaped) response on the webhook path |
| 2. Shared rate-limit bucket | Apple Health webhook ingest | Burst of webhook requests does not 429 a concurrent `/mcp` call |
| 3. Unauthenticated FastAPI route | Apple Health webhook ingest | No-credential request → 401; static guard that every non-`/health` route has an auth dependency |
| 4. Non-idempotent ingest | Apple Health webhook ingest | Identical payload POSTed twice → identical row count and identical computed averages |
| 5. Payload size / cold start | Apple Health webhook ingest | Oversized body rejected before parse; deployment flags reviewed and changed before first live sync |
| 6. `export.xml` OOM | Apple Health backfill | Real 182 MB file parses within the memory budget; backfill-after-webhook is a no-op on overlapping days |
| 7. Freshness provider default | Apple Health webhook ingest (write `sync_state`) + health-analytics extension (remove the default) | `provider` has no default; `FreshnessMetadata.resources` names every writing provider |
| 8. `VARCHAR(16)` source | Apple Health webhook ingest (migration plan) | Chosen source constant inserts against real PostgreSQL |
| 9. Row-level dedupe / implicit precedence | Historical body measurements — fix must land **with or before** the webhook phase | Three-source, partially-overlapping-column test; explicit `MappingProxyType` precedence map |
| 10. Max-weight flattens rep progression | Strength-metric shift | Both signals returned; a rep-progression fixture is not classified `stable` |
| 11. Ungated max weight destroys the honesty path | Strength-metric shift | `UNCLEAR` verdicts and a no-value reason still occur; modality gate retained |
| 12. Tuned constants mis-calibrated | Strength-metric shift | Before/after verdict table on live data recorded in the phase context |
| 13. `confirm=true` bypass | Training programs / write tool | A single tool call cannot change the program; token is target-bound and single-use |
| 14. Guards disarmed | Training programs / write tool | `test_mcp_never_writes` narrowed with an allowlist-length assertion; annotation partition test (13 read / 1 write) |
| 15. `safe_tool` masks write outcome | Training programs / write tool | Three-state result; post-commit failure does not report "not applied" |
| 16. Mutable program column | Training programs / write tool (schema plan) | Recomposition response names the program(s) it classified against; a straddling window says so |
| 17. Scheduled-task connector failure | Report tools — **spike plan first** | A scheduled task autonomously invokes `fitness_ping`; on-demand path valuable independently |
| 18. Report fan-out budget | Report tools | Measured structured/wire size at the widest window, asserted in `test_mcp_tool_budget.py` |
| 19. Coaching doc ceiling | Coaching style — **sequenced last** | Under 9,000 chars without raising the constant; bidirectional drift guard green |

### Suggested phase-ordering consequences

- **Pitfall 9 forces an ordering constraint:** the source-precedence fix must land *with or before* the Apple Health webhook phase, because Apple Health is the third source that silently activates the alphabetical-precedence bug. If the roadmap puts body measurements after Apple Health, the precedence map must be pulled forward into the webhook phase.
- **Pitfall 17 argues for sequencing the report-tools spike early**, ahead of its implementation plans and possibly ahead of other phases — a negative result should reshape the milestone, not sink a phase at its end.
- **Pitfall 19 argues for sequencing the coaching-style phase last**, so the document is rewritten once against the final tool registry rather than edited N times against a moving one.
- **Pitfalls 13–16 cluster into a single write-tool phase** that is more security-shaped than feature-shaped. Its success criteria should read like a threat model, not a feature list.
- **Phases likely needing their own deeper research:** the write-tool phase (confirmation-token design, scope strategy, AuthKit implications) and the strength-metric-shift phase (re-calibration methodology against live data). The webhook phase is mostly *verification* work against facts already established here.

---

## Sources

**Repository source, read directly (HIGH confidence — this is the strongest evidence in this document):**
- `backend/app/main.py` — bootstrap order, middleware registration order, catch-all mount at line 98, open `/health`
- `backend/app/middleware.py` — single global `TokenBucket`, `EXEMPT_PREFIXES`, no-client-header policy
- `backend/app/mcp/server.py` — `required_scopes=None` with "revisit when the first write tool ships", the `READ_ONLY` annotation loop, `stateless_http=True`, `_INSTRUCTIONS`
- `backend/app/mcp/auth.py` — `StaticTokenVerifier` bytes-compare rationale, `AuthKitJWTVerifier` fail-closed design
- `backend/app/mcp/tools/_common.py` — `read_only_session`, `safe_tool`, `truncate`, response-cap constants
- `backend/app/analytics/progression.py` — the max-weight-is-wrong paragraph (lines 7–10), `TREND_STABLE_BAND_PERCENT_PER_WEEK`, `PLATEAU_IMPROVEMENT_TOLERANCE`, D-18's derivation, D-07a skip semantics, `_NO_WEIGHT_RANK`
- `backend/app/analytics/estimates.py` — `MAX_TRUSTED_REPS`, `E1RM_EXERCISE_TYPE`, `NoEstimateReason`, live-data gate statistics
- `backend/app/analytics/recomposition.py` — hardcoded lean-bulk constants, `RECOMP_PROGRESSION_NET_BAND`, `RECOMP_LOOKBACK_WEEKS`, `aggregate_progression`'s `unclear` exclusion
- `backend/app/analytics/bodyweight.py` — `_dedupe_by_day` (lines 129–155), `MANUAL_SOURCE`, D-14
- `backend/app/analytics/metadata.py` — `build_freshness(provider=PROVIDER_HEVY)` default, `FRESHNESS_RESOURCES_*`
- `backend/app/db/models/body.py` + `backend/migrations/versions/0004_hevy_reference_tables.py` — `source` `VARCHAR(16)`, `(user_id, source, measured_on)` natural key
- `backend/app/integrations/hevy/body.py` — the proven `on_conflict_do_update` upsert pattern
- `backend/tests/test_mcp_isolation.py` — `test_mcp_never_writes`, `test_mcp_uses_no_raw_sql_text`'s by-name exemption pattern
- `backend/tests/test_mcp_tool_schemas.py` — `test_every_tool_is_annotated_read_only`
- `backend/tests/test_coaching_doc.py` — `_PASTE_CEILING_CHARS = 9_000`, bidirectional drift guard
- `backend/tests/test_analytics_isolation.py` — write ban in `app/analytics/`
- `scripts/deploy-cloud-run.sh` — `--allow-unauthenticated`, `--memory=512Mi`, `--max=2`, `--timeout=300`, `MIN_INSTANCES=0`
- `docs/coaching-instructions.md` — 7,216 characters measured
- `export.xml` — 182 MB measured on disk

**Installed package introspection (HIGH confidence):**
- `mcp 2.0.0` — `Context.elicit` signature and docstring ("if the client is an agent, it might… automatically generate a response"), `Context.client_capabilities` (`None` for anonymous stateless requests), `Context.headers` ("never treat one as an identity assertion"), elicitation type surface

**Official third-party documentation (HIGH confidence):**
- [Sync Apple Health Data to REST API — HealthyApps Help Center](https://help.healthyapps.dev/en/health-auto-export/automations/rest-api/) — export periods and overlap, batch requests, custom auth headers, automatic headers including `session-id`, no documented retry, iOS 30-second background budget, "several hundred megabytes" payload warning
- [Cloud Run quotas and limits — Google Cloud](https://docs.cloud.google.com/run/quotas) — 32 MiB max HTTP/1 request size
- [health-auto-export — GitHub (Lybron)](https://github.com/Lybron/health-auto-export) — 150+ metrics, format overview

**GitHub issues, fetched directly (MEDIUM-HIGH confidence):**
- [anthropics/claude-code#43397](https://github.com/anthropics/claude-code/issues/43397) — "Cloud scheduled tasks cannot access MCP connectors — tools not loaded into session", 2026-04-04, **closed as not planned**, 100% reproducible, sub-agent workaround
- [anthropics/claude-code#45306](https://github.com/anthropics/claude-code/issues/45306) — "Scheduled task MCP connector tools unavailable in execution environment", 2026-04-08, **closed as not planned**, silent failures

**Community / secondary (MEDIUM–LOW confidence, flagged inline where used):**
- [Get started with custom connectors using remote MCP — Anthropic Help Center](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp) — tool approval guidance, "only click Allow always when you trust the server to run unsupervised"
- [How to make Claude Desktop auto-approve MCP tools](https://kahunam.com/articles/web-development/how-to-make-claude-desktop-auto-approve-mcp-tools-a-power-users-guide/) — report that "Always approve" cannot be undone (**LOW** — single community source, treat as a risk to design against rather than a verified fact)

---
*Pitfalls research for: adding five v2.0 capabilities to a shipped read-only fitness MCP backend*
*Researched: 2026-09-02*
