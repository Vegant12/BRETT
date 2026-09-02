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

One of those settings is a **correctness prerequisite, not a preference**. The aggregation interval
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
| Aggregation interval | **Daily** | **Correctness prerequisite.** BRETT stores one row per metric per source per local day and uses REPLACE semantics (`SET value = excluded.value`) when a day is re-sent. With a Daily interval each metric emits exactly one datapoint per day, so a batch boundary can only ever fall *between* days and a re-send is a genuine no-op. At any finer interval a single day can be split across two POSTs, and the second POST silently overwrites the first instead of adding to it. It also shrinks the payload by roughly two orders of magnitude — a real captured export carried 189 datapoints for one metric-day |
| Batch Requests | **Off** | With a Daily interval the payload is small enough that batching buys nothing, and turning it on reintroduces the split-day risk above. The vendor documents Batch Requests as "splits one export across multiple POSTs" and guarantees nothing about where the boundary falls |
| Data type | **Health Metrics** | Workouts are deliberately not ingested (D-02, see §5) |
| Export period / window | **A rolling window of several days (e.g. 7)** | Overlap is safe and desirable. Re-sending a day BRETT already holds is a no-op (HEALTH-09), and a window wider than the schedule lets a missed or failed run self-heal on the next one |
| Schedule | **Hourly, or on-arrival** | The ingest path has its own rate-limit bucket (30 requests/minute, burst 30) sized for this and kept separate from the bucket Claude's connector uses, so phone exports can never throttle a coaching turn |

Two limits worth knowing, because Health Auto Export has **no documented retry** and a rejected
delivery is permanent loss of that window:

- Bodies above **10 MiB** are rejected with `413` before they are parsed. A Daily interval keeps a
  7-day window three orders of magnitude below this.
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
more than one datapoint for one `(metric, source_name, local_day)` key — which is exactly what a
Daily aggregation interval makes impossible.

If it appears, the device's aggregation interval has drifted off Daily (or Batch Requests was turned
on). The consequence is not cosmetic: re-sends are no longer lossless, and a day split across two
POSTs loses whichever half arrived first. BRETT's within-payload aggregation still adds up the
datapoints it receives *in one delivery*, so a single POST is always internally correct — the loss
happens between deliveries, which is the half no code can fix.

Remedy:

1. Set the aggregation interval back to **Daily** in the app (§3).
2. Re-run the export for the affected days. Because re-sending is a no-op under a correct
   configuration and a full replace under any configuration, the corrected export restores the day.

This event exists for one reason: to convert a silent data-loss mode into a visible one. A daily
step total that quietly falls after a re-sync is otherwise indistinguishable from a day you walked
less.

Two related events, both safe to read — none of them carries a measured value:

| Event | Fields | Read it as |
|---|---|---|
| `health_ingest_completed` | `rows_upserted` `rows_skipped` `datapoints_seen` … | A delivery landed |
| `health_ingest_hevy_source_excluded` | `metric=` `points=` | The HEALTH-08 filter matched Hevy's write-back. Expected on any training day in the window; its **absence** on a training day means the filter is not matching and Hevy's active energy is being double-counted |
| `health_ingest_unrecognized_metric` | `metric=` | An unlisted metric was dropped (see §8) |
| `health_ingest_datapoint_dropped` | `metric=` `unit=` `reason=` | One datapoint failed conversion — most often a unit changed in the app's per-metric settings |
| `health_ingest_unauthorized` | — | A request was rejected. Expected: this endpoint is on the public internet |
| `health_ingest_payload_too_large` | `declared_bytes=`/`read_bytes=` `cap=` | Over 10 MiB. Narrow the export window |

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

## 9. Verification record

_Populated by plan 08-08 Task 2 (deployment smoke tests) and Task 3 (first real device export)._
