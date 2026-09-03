# Health Auto Export — Device Setup

First written: 2026-09-02
Scope: the iPhone-side configuration that BRETT's Apple Health and nutrition ingest depends on.
Owner artifacts: `backend/app/api/routes/health_ingest.py` (the receiver),
`backend/app/integrations/health_auto_export/registry.py` (the metric allowlist),
`backend/app/integrations/health_auto_export/normalize.py` (aggregation and the Hevy exclusion),
`scripts/deploy-cloud-run.sh` (the `HEALTH_INGEST_SECRET` binding).

**Redaction rule for this file:** no credential value is ever recorded. The ingest credential is
referred to by its Secret Manager name — `brett-health-ingest-secret` — and by nothing else. If you
need the value, read it from Secret Manager; do not copy it into this document, a screenshot, or a
commit.

---

## 1. Why this document exists

Every other piece of Phase 8 is in version control and covered by tests. The Health Auto Export
automation on the iPhone is not. BRETT can neither read it nor enforce it: the service only ever
sees the POST bodies that arrive, and a body that arrives is indistinguishable from a correctly
configured phone.

One of those settings is a **correctness prerequisite, not a preference**. The Aggregate Data toggle
decides whether re-sending an overlapping export window is a no-op or silent data loss. Get it wrong
and BRETT does not error — it stores a plausible-looking number that is quietly smaller than the
truth, which is this project's stated primary risk. Writing the setting down is the only control
available, so it is written down here rather than remembered.

---

## 2. Endpoint and credential

| | |
|---|---|
| URL | `https://brett-792870654598.us-central1.run.app/api/v1/ingest/health-auto-export` |
| Method | `POST` |
| Content type | `application/json` (Health Auto Export's REST API default) |
| Header name | `Authorization` |
| Header value | `Bearer ` followed by the value of the `brett-health-ingest-secret` Secret Manager secret |

Include the word `Bearer` and the single space after it. The app sends the header value verbatim;
BRETT compares the token bytes with `secrets.compare_digest` and a missing scheme is simply a
mismatch.

Read the value with:

```bash
gcloud secrets versions access latest \
  --secret=brett-health-ingest-secret --project=brett-fitness
```

**Never put the token in the URL query string.** A credential in a URI lands in Cloud Run's request
logs, in any proxy in front of them, and in the browser history of anyone who pastes it — and the
MCP authorization spec prohibits access tokens in the query string for exactly that reason. It is
the same rule, for the same reason, as the Claude connector's bearer token. The `Authorization`
header is the only supported place for it.

---

## 3. Required settings

Configure in the Health Auto Export iOS app under **Automations → REST API**.

| Setting | Required value | Why |
|---|---|---|
| Automation type | **REST API** | The only mode that POSTs JSON to a URL. Export-to-file and iCloud modes do not reach BRETT |
| Aggregate Data | **On** | **Correctness prerequisite, not a dropdown.** Despite the name "Aggregation interval" that earlier documentation drafts used, on this app version (verified against 9.1.1) the control is a single boolean toggle called **Aggregate Data**, not an interval picker — turning it on is what collapses each metric to one point per local day. BRETT stores one row per metric per source per local day and uses REPLACE semantics (`SET value = excluded.value`) when a day is re-sent, so with Aggregate Data on, a batch boundary can only ever fall *between* days and a re-send is a genuine no-op. With it off, HAE sends raw per-sample datapoints — a real device attempt with it off produced a **~115 MB** payload from two days of data and was rejected outright at `413` before it reached the day-splitting risk described below. At any finer-than-daily granularity a single day can also be split across two POSTs, and the second POST would silently overwrite the first instead of adding to it. Confirmed live 2026-09-03: with Aggregate Data on, a real export produced exactly one datapoint per metric per day and zero `health_ingest_multi_point_day` events |
| Batch Requests | **Off** | With Aggregate Data on the payload is small enough that batching buys nothing, and turning it on reintroduces the split-day risk above. The vendor documents Batch Requests as "splits one export across multiple POSTs" and guarantees nothing about where the boundary falls |
| Data type | **Health Metrics** | Workouts are deliberately not ingested (D-02, see §5) |
| Export period / window | **A rolling window of several days (e.g. 7)** | Overlap is safe and desirable. Re-sending a day BRETT already holds is a no-op (HEALTH-09), and a window wider than the schedule lets a missed or failed run self-heal on the next one |
| Schedule | **Hourly, or on-arrival** | The ingest path has its own rate-limit bucket (30 requests/minute, burst 30) sized for this and kept separate from the bucket Claude's connector uses, so phone exports can never throttle a coaching turn |

Two limits worth knowing, because Health Auto Export has **no documented retry** and a rejected
delivery is permanent loss of that window:

- Bodies above **10 MiB** are rejected with `413` before they are parsed. With Aggregate Data on, a
  7-day window stays roughly three orders of magnitude below this; a real device attempt with
  Aggregate Data **off** measured ~115 MB for just two days and was rejected immediately.
- Above 30 requests/minute the endpoint answers `429`. An hourly schedule uses 1.

---

## 4. Metrics to select

Twelve metrics, and only these twelve, are stored. Select them under the app's data-selection
screen; the "HAE / Apple Health UI label" column is what the app actually calls them.

| HAE wire name | HAE / Apple Health UI label | Unit |
|---|---|---|
| `step_count` | Steps | count |
| `active_energy` | Active Energy | kcal |
| `basal_energy_burned` | Resting Energy / Basal Energy Burned | kcal |
| `walking_running_distance` | Walking + Running Distance | km |
| `flights_climbed` | Flights Climbed | count |
| `dietary_energy` | Dietary Energy | kcal |
| `protein` | Protein | g |
| `carbohydrates` | Carbohydrates | g |
| `total_fat` | Total Fat | g |
| `fiber` | Fiber | g |
| `dietary_sugar` | Dietary Sugar | g |
| `sodium` | Sodium | mg |

BRETT **silently ignores anything else** (D-04). An unlisted metric costs only itself: it produces
one `health_ingest_unrecognized_metric` log line and every other metric in the same payload is
ingested normally. Selecting extra metrics is therefore harmless — it just wastes payload.

Units are a per-metric preference *inside the phone app* and are converted on-device at export time,
so changing one silently changes the wire units on the next export. BRETT converts kJ→kcal, mi→km
and g→mg at the boundary and **rejects a datapoint whose unit it does not recognise** rather than
storing an unconverted number. The units above are the defaults and the ones to prefer.

---

## 5. Metrics to NOT select

| Do not select | Why |
|---|---|
| **Body Mass / Weight** | D-01. BRETT takes body weight from Hevy only. 52 of the 79 Apple Health body-mass records in this user's export are Hevy re-exports of rows BRETT already has, and the Apple Health series stops in May 2025 — it adds a duplicate source with no recency value and an arbitration problem |
| **Workouts** | D-02. 218 of the 221 Apple Health workouts in this user's export are Hevy re-exports, and BRETT already holds those at set-and-rep detail from the Hevy API. An Apple Health workout would be a strictly poorer copy of a record that already exists |

Selecting them anyway is **harmless** — neither is in the allowlist, so both are dropped at the
registry gate before anything is written. It only wastes payload. The reason to leave them
unselected is that the payload is then an honest description of what BRETT ingests.

One related exclusion happens on BRETT's side and cannot be configured on the phone: Hevy writes
its own `ActiveEnergyBurned` records back into Apple Health, and on training days that single lump
record is 70–88% of the day's entire active-energy total. `active_energy` *is* in the allowlist, so
BRETT excludes those datapoints by their `source` at write time (HEALTH-08). Nothing to do here —
but it is why §7's alarm list includes a "did the filter fire?" check.

---

## 6. How to check it is working

```bash
# 1. The service is up.
curl -s -o /dev/null -w '%{http_code}\n' https://brett-792870654598.us-central1.run.app/health

# 2. No credential -> 401 with {"error":"unauthorized"} and nothing else:
curl -si -X POST https://brett-792870654598.us-central1.run.app/api/v1/ingest/health-auto-export \
  -H 'content-type: application/json' -d '{}' | head -20

# 3. Recent ingest activity (no health values are ever logged):
gcloud logging read \
  'resource.type=cloud_run_revision AND jsonPayload.event=~"^health_ingest_"' \
  --project=brett-fitness --limit=50 --freshness=1d
```

A successful delivery answers `202` with counts only — `rows_upserted`, `rows_skipped`,
`datapoints_seen`, `metrics_unrecognized` — and no measured value. That body is safe to read out of
the phone app, screenshot, or paste into a chat.

The rejection bodies carry one key each and never say *which* check failed. A missing credential and
a wrong credential produce byte-identical responses on purpose: a difference between them tells an
unauthenticated prober that the endpoint exists, takes a bearer token, and that theirs was the right
shape.

| Status | Body | Meaning |
|---|---|---|
| `202` | `{"status":"accepted", …counts}` | Delivered and stored |
| `401` | `{"error":"unauthorized"}` | Header absent, wrong, or the server has no secret configured |
| `413` | `{"error":"payload_too_large"}` | Body above 10 MiB, rejected before parsing |
| `400` | `{"error":"invalid_payload"}` | Valid JSON, but not a Health Auto Export envelope |
| `429` | `{"error":"rate_limited"}` | Above 30 requests/minute |

---

## 7. The one alarm to watch for

```
health_ingest_multi_point_day   metric= source_name= local_day= points=
```

**Under a correct configuration this event never fires.** It fires when a single delivery carries
more than one datapoint for one `(metric, source_name, local_day)` key — which is exactly what
Aggregate Data being on makes impossible. Confirmed live 2026-09-03: two real exports with
Aggregate Data on produced zero occurrences of this event.

If it appears, the device's Aggregate Data toggle has drifted off (or Batch Requests was turned
on). The consequence is not cosmetic: re-sends are no longer lossless, and a day split across two
POSTs loses whichever half arrived first. BRETT's within-payload aggregation still adds up the
datapoints it receives *in one delivery*, so a single POST is always internally correct — the loss
happens between deliveries, which is the half no code can fix.

Remedy:

1. Turn **Aggregate Data** back on in the app (§3).
2. Re-run the export for the affected days. Because re-sending is a no-op under a correct
   configuration and a full replace under any configuration, the corrected export restores the day.

This event exists for one reason: to convert a silent data-loss mode into a visible one. A daily
step total that quietly falls after a re-sync is otherwise indistinguishable from a day you walked
less.

Related events, all safe to read — none of them carries a measured value. The four
`health_backfill_*` events come from the one-time historical import, not from the phone:

| Event | Fields | Read it as |
|---|---|---|
| `health_ingest_completed` | `rows_upserted` `rows_skipped` `datapoints_seen` … | A delivery landed |
| `health_ingest_hevy_source_excluded` | `metric=` `points=` | The HEALTH-08 filter matched Hevy's write-back. **Its absence is not by itself evidence of a problem** — as of 2026-09-03, Hevy is not writing `active_energy` (or anything) to HealthKit for this user at all, so this event does not fire on any day, training or not. If Hevy resumes HealthKit write-back in the future, check the Health app directly (Browse → a metric → a day → sources) to see whether Hevy appears as a source before assuming the filter itself is broken |
| `health_ingest_unrecognized_metric` | `metric=` | An unlisted metric was dropped (see §8) |
| `health_ingest_datapoint_dropped` | `metric=` `unit=` `reason=` | One datapoint failed conversion — most often a unit changed in the app's per-metric settings |
| `health_ingest_unauthorized` | — | A request was rejected. Expected: this endpoint is on the public internet |
| `health_ingest_payload_too_large` | `declared_bytes=`/`read_bytes=` `cap=` | Over 10 MiB. Narrow the export window |
| `health_backfill_parsed` | `records_total` `datapoints` `unrecognized_records` `body_mass_skipped` `malformed` `workouts_skipped` `activity_summaries_skipped` | The file was read end to end |
| `health_backfill_progress` | `rows_written` `rows_total` | The write is alive; one line per 500 rows |
| `health_backfill_row_skipped` | `metric` `local_day` `source_name` `reason` | One row failed; the rest of the run continued |
| `health_backfill_completed` | `rows_written` `rows_skipped` `datapoints_seen` `datapoints_dropped` `records_total` `kinds` | The backfill finished |

### After the historical backfill: a falling `sample_count` is expected, once

Phase 9's one-time backfill imports `export.xml` and writes `sample_count` as the number of **raw
HealthKit samples** aggregated into that metric-day. Raw samples are per-event, not per-day:
measured on the real export, **7,403 of 8,077 backfilled rows (91.7%)** aggregate more than one
sample. The webhook writes `sample_count = 1`, because Aggregate Data makes the phone send one
datapoint per metric per day (confirmed live 2026-09-03, §9).

`health_daily_metrics.sample_count` is documented in the schema as "the cheapest diagnostic for
Pitfall N-2" — a `sample_count` that **falls** on a re-sync is a batch-split data loss. On a day
the backfill covered and the webhook later re-delivers, `sample_count` legitimately drops from N
to 1. That is a **false positive**, and it is expected exactly once per overlapping day.

How to tell the two apart:

| | The backfill false positive | A real batch-split loss |
|---|---|---|
| Which day it lands on | On or before the backfill's `ExportDate` | A recent day, inside the live webhook window |
| What happens to the day alongside it | The value is replaced by a correct daily total | The day's total gets smaller |
| How often | Once per overlapping day, then never again | Every affected re-sync |

Why this is accepted rather than fixed: `sample_count` is diagnostic-only and feeds no analytics,
and the alternative — making the backfill write `sample_count = 1` — would be the backfill lying
about what it actually aggregated, which is worse than a documented false positive. It is recorded
here so it does not cost a future debugging session.

In practice the overlap is expected to be **zero days**: the export ends 2026-08-26 and the live
webhook feed starts 2026-09-02, so no day is covered by both paths. Confirm that empirically from
the backfill's own `--dry-run` summary date range before the real run rather than assuming it.

---

## 8. What BRETT does with an unexpected metric

One `health_ingest_unrecognized_metric` log line, and nothing else. The metric is dropped; **the
rest of the payload is ingested normally** (D-04).

This is deliberate and worth understanding before anyone "hardens" it. Health Auto Export has no
documented retry, so a delivery BRETT rejects is gone. Rejecting a whole batch over one unrecognised
metric name would lose the entire window's activity *and* nutrition because of a metric nobody asked
for — a strictly worse outcome than dropping the one thing that was not on the list.

The same reasoning applies one level down: a malformed or unit-unrecognisable *datapoint* is dropped
individually, not the metric it belongs to and not the payload it arrived in. The blast radius of
one bad element is that element.

---

## 10. The one-time historical backfill (HEALTH-10)

*This section sits ahead of §9 on purpose. §9 is an append-only log that only ever grows at the
bottom; everything above it is procedure, and this is procedure.*

This runs **once**, maybe twice, ever. It imports the Apple Health history that predates the
webhook — the file you exported by hand from the Health app — through the same normalizer and the
same upsert the live webhook uses, so a day covered by both paths holds one value per metric rather
than two.

It is a **local** command run against the production database, not a deployed job. The source is a
191 MB file on your own machine; Cloud Run caps a request body at 32 MiB, so no route could accept
it, and a Cloud Run Job would only clear that ceiling by first uploading your entire gitignored
health history to Cloud Storage to run a command exactly once (D-01). The file never leaves the
laptop; only the rows do.

### Before you run it

1. **Confirm the file is where you think it is, and is the export you mean.** There are two exports
   at the repo root (`export.xml` and `export_cda.xml`), and the path is a positional argument with
   no default for exactly this reason:

   ```bash
   ls -l export.xml
   # 20000 bytes, not 400: HealthKit writes a ~7 KB inline DTD ahead of the ExportDate
   # element, so a small window finds nothing and looks like a malformed file.
   head -c 20000 export.xml | grep -o 'ExportDate value="[^"]*"'
   ```

2. **Confirm the production database is not behind the deployed code.** This has been the failure
   mode **twice** (see `docs/runbook-sync-schedule.md`, "Schema drift is not detected before it
   breaks a run"), and this command writes to `health_daily_metrics`, which migration `0005`
   created:

   ```bash
   cd backend    # alembic.ini lives here; from the repo root alembic exits with
                 # "No 'script_location' key found in configuration"
   DATABASE_URL='<production-database-url>' uv run alembic current
   DATABASE_URL='<production-database-url>' uv run alembic heads
   # These must match. If they do not:
   DATABASE_URL='<production-database-url>' uv run alembic upgrade head
   ```

   The inline `DATABASE_URL` is what makes `cd backend` safe here: settings read `.env` relative to
   the working directory, so nothing under `backend/` would otherwise be configured — and an
   environment override beats `.env` regardless. Return to the repo root before Step 1; the
   backfill command below is written from there.

   `/health` probes `SELECT 1`, which succeeds against any schema, so a database behind head looks
   perfectly healthy until a query touches a table that does not exist.

3. **Note what is already in the table**, so that afterwards you can tell what the backfill added
   rather than inferring it:

   ```sql
   SELECT source, count(*), min(local_day), max(local_day)
   FROM health_daily_metrics
   GROUP BY source;
   ```

### Step 1 — dry run (always)

```bash
# The production URL is an INLINE override for this one shell session (D-02). Do not create a
# .env.production and do not export it into your shell profile: a production credential should
# not outlive the command that needed it. The leading space keeps the line out of shell history
# in zsh/bash when HIST_IGNORE_SPACE / HISTCONTROL=ignorespace is set.
 DATABASE_URL='<production-database-url>' PYTHONPATH=backend \
   uv run python -m app.cli backfill-apple-health export.xml --dry-run
```

Nothing is written. The command parses and aggregates the whole file, reads `users.timezone`, and
prints the summary block below.

Check the printed summary against these figures. They were measured against the export dated
`2026-08-26 10:09:33 +0700` (191,257,897 bytes). A **different** export legitimately produces
different numbers — re-derive them from the new summary rather than assuming something is broken.

| Line | Expected |
|---|---|
| records | 438,649 total = 230,395 in-scope + 208,175 unrecognized + 79 body-mass + 0 malformed |
| datapoints | 230,395 seen, 209 dropped (209 Hevy-sourced) |
| skipped elements | Workout=224 ActivitySummary=1,443 |
| multi-point days | 7,403 |
| date range | 2022-03-10 .. 2026-08-26 |
| rows | 8,077 would write, 0 skipped |
| freshness | not advanced (dry run) |

Rows per metric: `step_count` 1,699 · `walking_running_distance` 1,699 · `basal_energy_burned`
1,592 · `active_energy` 1,501 · `flights_climbed` 1,211 · `dietary_energy` 54 · `protein` 54 ·
`total_fat` 54 · `dietary_sugar` 54 · `carbohydrates` 53 · `fiber` 53 · `sodium` 53.

Two lines deserve to be read rather than skimmed:

- **The four numbers on the `records:` line must add up to the total.** That identity is how you
  know no record was silently dropped by the tag walk. A record that vanishes there leaves a
  plausible-looking summary and a hole that only surfaces as a gap in a trend months later.
- **Read the `date range:` line.** If its end date is on or after the first day the webhook
  delivered, the backfill and the live feed overlap, and the overlapping days will be **replaced**
  — not duplicated, not summed — by whichever ran last. That is by design; you just want to know it
  happened, because it is also when §7's `sample_count` false positive appears.

The same figures are asserted mechanically by `backend/tests/test_backfill_real_export.py`
(`uv run pytest -m realfile`), so a doc that has drifted from the file cannot stay quietly wrong.

### Step 2 — the real run

```bash
 DATABASE_URL='<production-database-url>' PYTHONPATH=backend \
   uv run python -m app.cli backfill-apple-health export.xml --write
```

`--dry-run` and `--write` are mutually exclusive and **one of them is required**. A forgotten flag
is an argparse error (exit 2) before the environment is even read — never a silent full write.

Expected shape of the run: the parse is a few seconds. The write is the slow part, and its speed is
round-trip latency to the database, not CPU. A `health_backfill_progress` line appears roughly
every 500 rows — about 16 lines for a full 8,077-row run. Silence for minutes with no progress line
means the connection, not the parser.

### Afterwards

```sql
-- 1. What landed, and over what span.
SELECT source, count(*) AS rows, min(local_day), max(local_day)
FROM health_daily_metrics
GROUP BY source;

-- 2. Success criterion #3: no metric-day may hold two rows for the SAME source_name.
SELECT metric, source_name, local_day, count(*)
FROM health_daily_metrics
GROUP BY 1, 2, 3
HAVING count(*) > 1;
-- Expect ZERO rows. Two rows for the same metric-day with DIFFERENT source_name values is
-- correct and expected (two phones, two nutrition apps); two with the SAME one is the bug.

-- 3. Success criterion #4: no Hevy-sourced row may exist.
SELECT count(*) FROM health_daily_metrics WHERE lower(source_name) = 'hevy';
-- Expect 0.

-- 4. Freshness bookkeeping advanced for both resources.
SELECT resource, status, last_synced_at
FROM sync_state
WHERE provider = 'apple_health';
```

Expect `sample_count` to fall from N to 1 on any day the webhook later re-delivers. That is the
documented false positive in §7, not data loss.

### If something goes wrong

- **One bad row** is skipped and logged as `health_backfill_row_skipped` (metric, day, source name
  and the exception's class name — never a value); the run continues. Re-running the command is
  safe and is a no-op on rows that already landed correctly.
- **A malformed XML element** is counted as `malformed` on the `records:` line and skipped; the run
  continues to the end of the file (D-07). Aborting mid-parse on one bad element would throw away
  4.5 years of otherwise-good history.
- **An unreadable or non-HealthKit file** exits 1 with `Apple Health backfill failed: Apple Health
  export file could not be read as a HealthKit export` and writes nothing. The message deliberately
  names no path and echoes nothing read out of the file.
- **The whole command is idempotent by construction**: replace semantics on the natural key
  `(user_id, source, metric, source_name, local_day)`. Running it twice produces the same table.

### Credential hygiene

Every `DATABASE_URL` in this section is the placeholder `<production-database-url>`. Never paste a
real connection string into this file, into a commit message, or into a chat transcript. `gitleaks`
runs in pre-commit and will refuse the commit, but the rule is the point, not the hook — a
transcript is not covered by a pre-commit hook.

---

## 9. Verification record

### 2026-09-02 — deployment and endpoint contract

Service `brett`, project `brett-fitness`, region `us-central1`, gcloud SDK 578.0.0, deploying
account `hovegant12@gmail.com`. Requests issued against the deterministic host
`https://brett-792870654598.us-central1.run.app`.

This section records what the endpoint **actually does**, observed from the outside, not what it is
supposed to do.

| Before | After |
|---|---|
| revision `brett-00009-fsm` | revision **`brett-00010-kln`**, 100% of traffic |
| `--memory=512Mi` | **`1Gi`** (RESEARCH Pitfall 5: ~235 MB peak decoding a 10 MB body) |
| no `HEALTH_INGEST_SECRET`, no `INGEST_*` | `HEALTH_INGEST_SECRET` bound from Secret Manager, plus `INGEST_MAX_BODY_BYTES`, `INGEST_RATE_LIMIT_PER_MINUTE`, `INGEST_RATE_LIMIT_BURST` |

`brett-health-ingest-secret` was created the same way `brett-mcp-auth-secret` was — automatic
replication, `roles/secretmanager.secretAccessor` granted on the **secret** (not per version) to
`serviceAccount:brett-run@brett-fitness.iam.gserviceaccount.com`, verified by reading the live
policy of both. The value was piped to `gcloud --data-file=-` from `secrets.token_urlsafe(48)` and
never written to disk. `access latest | wc -c` returns `64`, which confirms no trailing newline —
a newline in the stored value would make every correctly-copied token fail `compare_digest` with a
401 and no diagnostic.

| # | Check | Expected | Observed | Result |
|---|---|---|---|---|
| 1 | `GET /health` | `200` | `200`, body exactly `{"status":"ok","database":"connected"}` | **PASS** |
| 2 | `POST /api/v1/ingest/health-auto-export`, no `Authorization` | `401`, bare body | `401`, `content-type: application/json`, `content-length: 24`, body exactly `{"error":"unauthorized"}` | **PASS** |
| 3 | Same POST with a deliberately wrong bearer token | byte-identical to row 2 | `cmp` of the two bodies reports **identical**; the response header set is identical too, modulo the per-request `x-request-id`, `x-cloud-trace-context` and `date`. The presented token appears **0 times** across the response body and every response header | **PASS** |
| 4 | `GET /.well-known/oauth-protected-resource/mcp` | `200` | `200`, advertising `resource` `…/mcp` and the AuthKit authorization server — the MCP connector is unaffected by the new route (RESEARCH Pitfall 1) | **PASS** |
| 5 | Cloud Run logs for rows 2 and 3 | `health_ingest_unauthorized`, no credential | Both requests logged `health_ingest_unauthorized` with `correlation_id` matching the `x-request-id` returned to the caller. The presented token appears **0 times** in the log export | **PASS** |
| 6 | Secret value in the repository | absent | `git grep` and a full working-tree `grep` both find it nowhere; `git status --porcelain` empty | **PASS** |

Row 5 matters more than it looks. A `401` on its own could have come from the Cloud Run edge, from
the MCP sub-app's `RequireAuthMiddleware`, or from BRETT's own handler — three very different
things, one of which would mean the route is not reachable at all. The matching correlation ID
proves the rejection came from `health_ingest.py`.

The wrong-token request in row 3 is deliberately **not** reproduced verbatim in this document: a
long token-shaped string after the word `Bearer` is exactly the pattern this file is checked for.
To repeat it, substitute any long string of your own into the `-H 'authorization: Bearer …'` header
of the row 2 command.

### 2026-09-03 — first real device export

Two configuration problems surfaced before the first successful delivery, both instructive for the
next reader:

1. **`413 Payload too large`** on the first attempt (~115 MB). The automation had **Aggregate
   Data off** (`"exportAggregation": "Default"` in the app's own diagnostics export) — see §3's
   correction above. Fixed by turning Aggregate Data on.
2. **Export "accepted" but every row skipped** (`reason: "ProgrammingError"`, `rows_upserted: 0`)
   on the second attempt. Not a device problem: the live production database was one migration
   behind the deployed code (`alembic current` == `0004`; the deployed revision needed `0005` for
   `health_daily_metrics`, the table plan 08-01 created). `scripts/deploy-cloud-run.sh` has no
   migration step — fixed with `alembic upgrade head` against production, with the user's
   confirmation before running it. See `.planning/STATE.md`'s blockers section for the follow-up
   this deserves before Phase 9 deploys its own migration.

The third export succeeded:

| # | Check | Expected | Observed | Result |
|---|---|---|---|---|
| 1 | `health_ingest_completed` | `rows_upserted > 0` | `datapoints_seen: 23, rows_upserted: 23, rows_skipped: 0` | **PASS** |
| 2 | All 12 registry metrics present | across the exported days | All 12 present for the full day (2026-09-02); 11 of 12 for the partial day (2026-09-03) — `sodium` had not been logged in the nutrition app yet that day, not a bug | **PASS** |
| 3 | `sodium` units | `mg` | `mg` | **PASS** |
| 4 | `health_ingest_multi_point_day` | absent | Not present in the delivery's logs | **PASS** |
| 5 | Repeat export changes nothing | same row count, same `sum(sample_count)` | 23 rows / 23 total samples, unchanged before and after the repeat | **PASS** |
| 6 | `device_capture.json` fixture | scrubbed, real shape and source vocabulary | Created; see its file and `backend/tests/conftest.py`'s `hae_fixture` docstring — reconstructed from confirmed-live metric names, units and source strings, not a literal captured request body (the app has no feature to export one) | **PASS** |

**Assumption A1 (does the exclusion filter match Hevy's real webhook spelling): MOOT, not
confirmed or refuted.** No `health_ingest_hevy_source_excluded` event fired, despite a Hevy
workout ("Upper 1") on the exported day. The user checked the native Health app directly
(Browse → Active Energy → Sep 2 → sources): **Hevy is not a source at all** for that day. Read
together with §5's note that Hevy's Apple Health body-mass write-back "stops in May 2025", the
most likely explanation is that Hevy stopped writing to HealthKit generally around then — there
is currently nothing live for the exclusion filter to catch. The filter (`_HEVY_SOURCE_ALIASES`
in `normalize.py`) is unchanged and stays in place: Phase 9's `export.xml` historical backfill
covers the period when Hevy demonstrably did write to HealthKit (52/79 body-mass records, 218/221
workouts — see §5), so the predicate is still load-bearing there. If Hevy ever resumes writing to
HealthKit, treat the first live delivery on a training day as the real test of this filter, not
this checkpoint.

### 2026-09-03 — historical backfill dry run

The §10 procedure, rehearsed end to end before the real write. **This run used the LOCAL
`docker compose` database, not production.** A dry run writes nothing, but it does read
`users.timezone`, and there is no reason to point a rehearsal at production when the local
database holds the same seeded user. D-02's inline production override belongs to the real run
only, so no `DATABASE_URL` appears anywhere below — the command read the repo's gitignored `.env`,
which points at `localhost`.

Pre-flight, in order:

```bash
docker compose up -d
cd backend && uv run alembic upgrade head    # 0004 -> 0005 (health daily metrics)
uv run alembic current                        # 0005 (head)
uv run alembic heads                          # 0005 (head)  -- they match
```

The file, confirmed to be the one the pinned figures describe:

```
ls -l export.xml                 ->  191257897 bytes, mtime Aug 26 10:09
ExportDate value="2026-08-26 10:09:33 +0700"
```

The command:

```bash
PYTHONPATH=backend uv run python -m app.cli backfill-apple-health export.xml --dry-run
```

Exit code **0**. Wall clock **4.41 s** for the whole command, of which ~2.6 s was the streaming
parse (`hevy_cli_started` 06:00:22.011Z → `health_backfill_parsed` 06:00:24.634Z). Run twice; the
two summary blocks are byte-identical.

The summary block, as printed:

```
Apple Health backfill — DRY RUN (nothing written)
file: export.xml
records: 438649 total = 230395 in-scope + 208175 unrecognized + 79 body-mass + 0 malformed
datapoints: 230395 seen, 209 dropped (209 Hevy-sourced)
skipped elements: Workout=224 ActivitySummary=1443
multi-point days: 7403 (normal for raw HealthKit samples; warning suppressed)
date range: 2022-03-10 .. 2026-08-26
rows by metric:
  active_energy                  1501
  basal_energy_burned            1592
  carbohydrates                    53
  dietary_energy                   54
  dietary_sugar                    54
  fiber                            53
  flights_climbed                1211
  protein                          54
  sodium                           53
  step_count                     1699
  total_fat                        54
  walking_running_distance       1699
unrecognized types (34):
  HKQuantityTypeIdentifierWalkingSpeed                       57364
  HKQuantityTypeIdentifierWalkingStepLength                  57363
  HKQuantityTypeIdentifierWalkingDoubleSupportPercentage     50031
  HKQuantityTypeIdentifierWalkingAsymmetryPercentage         30218
  HKQuantityTypeIdentifierHeadphoneAudioExposure             10077
  HKCategoryTypeIdentifierSleepAnalysis                       2411
  HKQuantityTypeIdentifierAppleWalkingSteadiness               219
  HKQuantityTypeIdentifierDietaryFatSaturated                   63
  HKQuantityTypeIdentifierDietaryPotassium                      63
  HKQuantityTypeIdentifierDietaryIron                           58
  HKQuantityTypeIdentifierDietaryCalcium                        56
  HKQuantityTypeIdentifierDietaryMagnesium                      54
  HKQuantityTypeIdentifierDietaryVitaminC                       53
  HKQuantityTypeIdentifierDietaryCholesterol                    50
  HKQuantityTypeIdentifierDietaryPhosphorus                     49
  HKQuantityTypeIdentifierHeight                                 8
  HKQuantityTypeIdentifierWaistCircumference                     8
  HKCategoryTypeIdentifierHeadphoneAudioExposureEvent            2
  HKQuantityTypeIdentifierDietaryCopper                          2
  HKQuantityTypeIdentifierDietaryFatPolyunsaturated              2
  HKQuantityTypeIdentifierDietaryFolate                          2
  HKQuantityTypeIdentifierDietaryManganese                       2
  HKQuantityTypeIdentifierDietaryNiacin                          2
  HKQuantityTypeIdentifierDietaryPantothenicAcid                 2
  HKQuantityTypeIdentifierDietaryRiboflavin                      2
  HKQuantityTypeIdentifierDietarySelenium                        2
  HKQuantityTypeIdentifierDietaryVitaminB6                       2
  HKQuantityTypeIdentifierDietaryVitaminE                        2
  HKQuantityTypeIdentifierDietaryVitaminK                        2
  HKQuantityTypeIdentifierDietaryZinc                            2
  HKDataTypeSleepDurationGoal                                    1
  HKQuantityTypeIdentifierDietaryBiotin                          1
  HKQuantityTypeIdentifierDietaryFatMonounsaturated              1
  HKQuantityTypeIdentifierDietaryThiamin                         1
rows: 8077 would write, 0 skipped
freshness: not advanced (dry run)
```

Nothing else from the run is reproduced here. The block above carries counts, metric names,
HealthKit identifiers and dates and no measured quantity — which is a property of
`format_summary`, asserted by `test_summary_prints_no_measured_quantity`, not a judgement call
made while pasting it.

**All eleven expected figures matched**, and so did all twelve per-metric row counts: 438,649
records total; the four addends 230,395 / 208,175 / 79 / 0 summing to it exactly; 230,395
datapoints seen; 209 dropped and all 209 Hevy-sourced; Workout=224; ActivitySummary=1,443; 7,403
multi-point days; 8,077 rows would-write; 0 rows skipped; date range 2022-03-10 .. 2026-08-26;
freshness not advanced. No figure was edited to match — nothing needed to be.

**The overlap answer (RESEARCH Assumption A2): zero days overlap.** The dry run's `date range:`
ends **2026-08-26**. The first `local_day` the live webhook delivered is **2026-09-02** (the
entry above this one). 2026-08-26 < 2026-09-02, so no day is covered by both paths, the §7
`sample_count` false positive will not fire on this run, and success criterion #3 ("no metric-day
holds two rows for the same `source_name`") is satisfied **vacuously** on production data. That is
worth stating plainly rather than reading as a pass: the criterion is genuinely proven by
`test_backfill_idempotency.py`'s container test, not by this run. Re-confirm the production side
empirically with §10's pre-flight step 3 before the real write — this rehearsal read the local
database, which holds no webhook rows at all.

**The dry run wrote zero rows.** `SELECT count(*) FROM health_daily_metrics` on the local database
read **0 before and 0 after** both invocations, and `sync_state` still holds **no** row for
`provider = 'apple_health'` — freshness was not advanced either.

Two defects in §10 were found by following it and are fixed in the committed version: the alembic
pre-flight had no `cd backend` (alembic exits `No 'script_location' key found in configuration`
from the repo root), and the `ExportDate` probe read `head -c 400` when a real HealthKit export
puts a ~7 KB inline DTD ahead of that element — it begins at byte 7426 in this file. Both would
have read as a broken export rather than a mistyped command.

### 2026-09-03 — historical backfill, production run

Command shape (the placeholder never held a real value in any pasted output):

```bash
DATABASE_URL='<production-database-url>' uv run alembic current
DATABASE_URL='<production-database-url>' uv run alembic heads

 DATABASE_URL='<production-database-url>' PYTHONPATH=backend \
   uv run python -m app.cli backfill-apple-health export.xml --dry-run

 time DATABASE_URL='<production-database-url>' PYTHONPATH=backend \
   uv run python -m app.cli backfill-apple-health export.xml --write
```

Pre-flight: `alembic current` and `alembic heads` both printed **0005** — matched, no migration gap
this time.

**Operational note, worth carrying forward.** The first pass at this run's post-write verification
queries came back showing the stale before-state (`count: 23`, range `2026-09-02 .. 2026-09-03`)
immediately after a `--write` that had logged `rows_written=8077` with no errors. The cause was not
the write — it was an incorrect `DATABASE_URL` used for the *verification* queries: not the actual
Neon connection string bound to the deployed service (held in Google Secret Manager as
`brett-database-url`, per `scripts/deploy-cloud-run.sh`). This is the same family of risk as the
migration-gap incidents already logged in `.planning/STATE.md` — the operator's shell pointed
somewhere other than intended — but on the read side rather than the write side, and on the third
occasion this class of mistake has cost time in this phase. Retrieving the confirmed value with
`gcloud secrets versions access latest --secret="brett-database-url"` and re-running the full
sequence against it (pre-flight, dry run, write) resolved it. The write is idempotent by natural
key, so repeating it was safe and cost nothing.

Before state (query 1, against the confirmed production URL, prior to the write that landed):

```
apple_health | 23 | 2026-09-02 | 2026-09-03
```

The real run's printed summary, as printed (wall clock: `hevy_cli_started` 11:19:12.863Z →
`hevy_cli_stopped` 11:20:11.922Z, ≈59 s):

```
Apple Health backfill — WROTE TO THE DATABASE
file: export.xml
records: 438649 total = 230395 in-scope + 208175 unrecognized + 79 body-mass + 0 malformed
datapoints: 230395 seen, 209 dropped (209 Hevy-sourced)
skipped elements: Workout=224 ActivitySummary=1443
multi-point days: 7403 (normal for raw HealthKit samples; warning suppressed)
date range: 2022-03-10 .. 2026-08-26
rows by metric:
  active_energy                  1501
  basal_energy_burned            1592
  carbohydrates                    53
  dietary_energy                   54
  dietary_sugar                    54
  fiber                            53
  flights_climbed                1211
  protein                          54
  sodium                           53
  step_count                     1699
  total_fat                        54
  walking_running_distance       1699
rows: 8077 written, 0 skipped
freshness: activity, nutrition advanced
```

(The 34-line `unrecognized types` breakdown is identical to the dry-run entry above and is not
repeated here — same file, same figures, both invocations of `format_summary` byte-identical on
that section.)

After state (query 1, re-run against the same confirmed URL):

```
apple_health | 8100 | 2022-03-10 | 2026-09-03
```

The four verification queries, mapped onto the four ROADMAP success criteria:

1. **`rows: 8077 written, 0 skipped`, date range `2022-03-10 .. 2026-08-26`** — the printed summary
   matches every pinned figure from the §9 dry-run entry exactly, over the real 191 MB file —
   **success criterion #1**.
2. **Before/after state**: count moved from 23 to **8,100** (23 + 8,077), and the date range
   widened from `2026-09-02 .. 2026-09-03` (webhook only) to `2022-03-10 .. 2026-09-03` — 4.5 years
   of history is queryable in production alongside the live webhook feed — **success criterion #2**.
3. **Duplicate metric-day check** (`GROUP BY metric, source_name, local_day HAVING count(*) > 1`):
   **zero rows** — **success criterion #3**. As RESEARCH Assumption A2 anticipated, the export ends
   2026-08-26 and the webhook feed begins 2026-09-02, so this held vacuously rather than by
   overlap; the day-overlap case itself is proven by `test_backfill_idempotency.py`'s container
   test, and this query confirms nothing violated it live.
4. **Hevy-sourced row check** (`WHERE lower(source_name) = 'hevy'`): **`0`** — **success criterion
   #4**.

`sync_state` freshness: `activity` and `nutrition` both report `idle` with the identical
`last_synced_at: 2026-09-03 11:20:08.304243+00` — one `utc_now()` for the whole run, confirming
`complete_sync` advanced both resources together in the same transaction as the rows (T-09-34).

**Assumption A2 (backfill/webhook day overlap): confirmed zero overlapping days**, empirically, on
production data — the export's last day (2026-08-26) precedes the webhook's first day
(2026-09-02).

**Assumption A3 (device name unchanged): confirmed.** Query 3 [duplicate check] returning zero rows
is the observable form of the backfill and webhook writing the same `source_name` for the same
device. `test_source_name_matches_device_capture` pins this so a future device rename fails the
fast suite instead of silently producing two rows per metric-day.

No day existed to exercise the §7 `sample_count` divergence (raw sample count from the backfill vs.
always-1 from the webhook) live, since no day is shared. It remains an open, documented, accepted
divergence — not something this run closed — and will surface the first time a backfilled day and
a webhook day for the same metric genuinely coincide.
