# Phase 9: Historical Apple Health Backfill - Pattern Map

**Mapped:** 2026-09-03
**Files analyzed:** 11 (5 new, 6 modified)
**Analogs found:** 10 / 11 (1 partial)

Every excerpt below is quoted from committed source at the stated line numbers. Planner: cite the
analog path + line range in each plan action, not "follow the existing pattern."

## File Classification

| New/Modified File | New? | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|------|-----------|----------------|---------------|
| `backend/app/integrations/health_auto_export/backfill.py` | NEW | integration service (parse + aggregate + batch write) | file-I/O → batch → CRUD upsert | `backend/app/integrations/health_auto_export/ingest.py` | exact (same package, same table, same constraint, same result shape) |
| `backend/app/cli.py` | MODIFIED | CLI entrypoint / thin dispatch | request-response (operator command) | `backend/app/cli.py::_run_mapping_gaps` + `::_run_status` (same file, lines 205-277) | exact |
| `pyproject.toml` | MODIFIED | config | n/a | `[tool.pytest.ini_options] markers` (same file) | exact |
| `backend/app/integrations/health_auto_export/normalize.py` | MODIFIED (docstring only) | normalizer | pure transform | itself (lines 21-28, stale claim) | exact |
| `backend/tests/conftest.py` | MODIFIED | test fixture loader | file-I/O | `conftest.py::hae_fixture` (lines 140-174) | exact |
| `backend/tests/fixtures/hae/export_sample.xml` | NEW | test fixture (data) | file-I/O | `backend/tests/fixtures/hae/device_capture.json` | role-match (XML vs JSON; provenance discipline identical) |
| `backend/tests/test_health_auto_export_backfill.py` | NEW | test (unit, fast suite) | pure transform | `backend/tests/test_health_auto_export_normalize.py` | exact |
| `backend/tests/test_backfill_idempotency.py` | NEW | test (integration, container) | CRUD | `backend/tests/test_health_ingest_idempotency.py` | exact |
| `backend/tests/test_backfill_real_export.py` | NEW | test (opt-in, gitignored input) | file-I/O | `backend/tests/test_cloud_run_deploy.py` (`.exists()` gating, lines 382-427) | **partial** — see [No Analog Found](#no-analog-found) |
| `backend/tests/test_cli.py` | MODIFIED | test (unit, source-order + argparse) | n/a | itself (lines 28-43, 104-113) | exact |
| `docs/health-auto-export-setup.md` | MODIFIED | operator doc | n/a | itself (§7 "The one alarm to watch for", lines 169+) | exact |

**Deliberately NOT modified** (research is explicit — reuse verbatim):
`registry.py`, `schemas.py`, `ingest.py`, `errors.py`, `db/models/health.py`,
`db/repositories/sync_state.py`, `core/time.py`. No migration.

---

## Pattern Assignments

### `backend/app/integrations/health_auto_export/backfill.py` (integration service, file-I/O → batch upsert)

**Analog:** `backend/app/integrations/health_auto_export/ingest.py`

This is the closest analog in the repo on every axis: same package, same target table, same named
constraint, same replace semantics, same counts-only result dataclass, same logging rule, same
"caller owns the transaction" discipline, same freshness bookkeeping.

**Module docstring pattern** (`ingest.py:1-52`) — this codebase writes docstrings as decision
records with requirement IDs, named pitfalls, and the reason a rejected alternative was rejected.
Match this density; it is the house style, not decoration:

```python
"""Normalized rows -> PostgreSQL, idempotently (HEALTH-09, NUTR-03, HEALTH-11, NUTR-05).

The conflict clause is the whole design
---------------------------------------
* An **additive** clause ... is correct when a single day arrives split across two batched
  POSTs, and **double-counts** every re-sent window.
* A **replace** clause is the mirror: a re-send is a correct no-op, and a day split across two
  batches silently **loses** the first of them.

The logging rule
----------------
A metric **name**, a **local_day**, a **source_name**, a **count** and an exception **class
name** are loggable. A stored quantity is not, ever (T-08-39, FOUND-05).
"""
```

**Imports pattern** (`ingest.py:54-84`) — stdlib, then third-party, then `app.*` by full path.
Never a barrel import; `__init__.py` re-exports nothing on purpose (`health_auto_export/__init__.py:9-11`):

```python
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

import structlog
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.time import utc_now
from app.db.models.health import HealthDailyMetric
from app.db.models.user import User
from app.db.repositories.sync_state import (
    PROVIDER_APPLE_HEALTH,
    RESOURCE_ACTIVITY,
    RESOURCE_NUTRITION,
    complete_sync,
    ensure_sync_state,
    record_sync_error,
)
from app.integrations.health_auto_export.normalize import (
    SOURCE_APPLE_HEALTH,
    NormalizedRow,
    normalize_payload,
)
from app.integrations.health_auto_export.schemas import HAEPayload

log = structlog.get_logger()
```

New import this phase adds (and the only `noqa` it needs — Pitfall 6, RESEARCH lines 624-651):

```python
from xml.etree import ElementTree as ET  # noqa: S314 (see the threat-model comment)
```

**Constant-table pattern for `HK_TO_WIRE`** — copy `registry.py:42-59`'s `MappingProxyType` +
naming-trap comment shape, and `ingest.py:92-102`'s "TOTAL, a missing key is a `KeyError`"
rationale. `registry.py:28-41`:

```python
# The ONLY place a metric name appears. `MappingProxyType` for the reason `exercise_map.py`'s
# tables use it: a caller must not be able to retune ingestion at runtime (T-08-23).
#
# ### The naming trap ###
# HAE's `dietary_` prefix is INCONSISTENT and guessing it wrong is SILENT, not an error --
#     carries the prefix : dietary_energy, dietary_sugar
#     does NOT carry it  : protein, carbohydrates, total_fat, fiber, sodium
METRIC_REGISTRY: Mapping[str, MetricSpec] = MappingProxyType({...})
```

and `ingest.py:92-102`:

```python
# Table-driven and TOTAL: a kind with no entry here is a `KeyError`, which is exactly the
# failure a `.get(kind, RESOURCE_ACTIVITY)` would hide behind a plausible default.
_KIND_TO_RESOURCE: Mapping[str, str] = MappingProxyType(
    {
        "activity": RESOURCE_ACTIVITY,
        "nutrition": RESOURCE_NUTRITION,
    }
)
```

**Counts-only result dataclass** (`ingest.py:105-113`) — copy verbatim and extend with this
phase's D-04/D-06 counters (workouts skipped, body-mass skipped, hevy excluded, date range):

```python
@dataclass(frozen=True, slots=True)
class HealthIngestResult:
    """Counts only. Never a value -- this object is what the route logs and returns."""

    rows_upserted: int
    rows_skipped: int
    datapoints_seen: int
    datapoints_dropped: int
    metrics_unrecognized: int
```

Also see `normalize.py:136-150` for the accounting-identity docstring convention that a new
result type should carry:

```python
@dataclass(frozen=True, slots=True)
class NormalizeResult:
    """Counts only, never a value -- this object is what callers log.

    The three counters satisfy an accounting identity that a test pins:
    ``sum(row.sample_count for row in rows) == datapoints_seen - datapoints_dropped``.
    """
```

**Core upsert pattern — copy the conflict clause exactly** (`ingest.py:116-173`). RESEARCH
line 382-383: `_upsert_many` must set **exactly** these four columns on conflict or the two paths
diverge:

```python
async def upsert_health_metric(
    session: AsyncSession, *, user_id: uuid.UUID, row: NormalizedRow
) -> None:
    """Write one day-grained row, keyed on ``(user_id, source, metric, source_name, local_day)``.

    ``user_id`` is keyword-only with no default (ASVS V4) ... resolved server-side ... NEVER
    read from the payload.
    """
    statement = pg_insert(HealthDailyMetric).values(
        id=uuid.uuid4(),
        user_id=user_id,
        source=SOURCE_APPLE_HEALTH,
        metric=row.metric,
        source_name=row.source_name,
        local_day=row.local_day,
        value=row.value,
        units=row.units,
        sample_count=row.sample_count,
    )
    statement = statement.on_conflict_do_update(
        constraint=_CONFLICT_CONSTRAINT,
        set_={
            "value": statement.excluded.value,
            "units": statement.excluded.units,
            "sample_count": statement.excluded.sample_count,
            "updated_at": func.now(),
        },
    )
    await session.execute(statement)
```

Constraint name, bound BY NAME (`ingest.py:87-90`) — reuse this exact constant, do not re-declare
the string:

```python
# Bound BY NAME rather than by column list, mirroring `app.db.repositories.sync_state`: if the
# constraint is ever renamed this raises immediately instead of silently degrading into a
# duplicate-row insert (T-08-35).
_CONFLICT_CONSTRAINT = "uq_health_daily_metrics_user_source_metric_source_name_day"
```

Its definition lives at `backend/app/db/models/health.py:103-127`.

**SAVEPOINT-per-row skip-and-continue** (`ingest.py:245-268`) — this is the fallback arm of
RESEARCH Pattern 3's chunked writer. Copy the loop, the `SQLAlchemyError` catch, and the
class-name-only log verbatim:

```python
rows_upserted = 0
rows_skipped = 0
try:
    for row in normalized.rows:
        try:
            # SAVEPOINT per row: without it one bad row aborts the whole transaction and
            # every later statement fails with "current transaction is aborted"
            # (T-08-40).
            async with session.begin_nested():
                await upsert_health_metric(session, user_id=user_id, row=row)
        except SQLAlchemyError as exc:
            rows_skipped += 1
            # Class name only: `str(DataError)` renders the bound parameters, which here
            # are this person's calorie counts (T-08-39).
            log.warning(
                "health_ingest_row_skipped",
                metric=row.metric,
                local_day=row.local_day.isoformat(),
                source_name=row.source_name,
                reason=type(exc).__name__,
            )
        else:
            rows_upserted += 1
```

Second, older copy of the same shape at `backend/app/integrations/hevy/body.py:161-182` — the two
agree, which is why this is the established mechanism rather than one module's choice.

**Freshness bookkeeping, same transaction** (`ingest.py:270-288`) — reuse verbatim; RESEARCH
Open Question 4 says advance only on a real run that wrote ≥1 row of that kind, never on `--dry-run`:

```python
# ONE instant for every resource this delivery advances, so a mixed payload cannot
# report activity and nutrition as fractionally different ages.
now = utc_now()
for kind in sorted(normalized.kinds_present):
    resource = _KIND_TO_RESOURCE[kind]
    await ensure_sync_state(
        session, user_id=user_id, provider=PROVIDER_APPLE_HEALTH, resource=resource
    )
    await complete_sync(
        session,
        user_id=user_id,
        provider=PROVIDER_APPLE_HEALTH,
        resource=resource,
        last_synced_at=now,
    )
await session.commit()
```

`complete_sync`'s aware-datetime guard is at `backend/app/db/repositories/sync_state.py:188-192`;
do not hand it a naive value.

**Timezone read** (`ingest.py:176-194`) — `tz` comes from `users.timezone`, never a constant.
Reuse this helper rather than writing a third copy:

```python
async def _user_timezone(session: AsyncSession, *, user_id: uuid.UUID) -> str:
    """The user's IANA timezone, read from ``users.timezone`` (FOUND-03).
    ...
    Never a module constant, never an environment variable, never a caller default. A missing
    row raises rather than falling back to a default zone.
    """
    tz = await session.scalar(select(User.timezone).where(User.id == user_id))
    if tz is None:
        raise ValueError("unknown user")
    return tz
```

**Handoff into Phase 8 unchanged** — the seam is already documented in the analog.
`normalize.py:190-195` anticipates this phase by name:

```python
# `Decimal(str(...))`, never a direct binary-to-Decimal construction, which would
# import the binary representation error into stored health data. `point.qty` is
# already a Decimal from the wire model; this is the belt to that model's braces,
# because Phase 9's XML path will feed this same function from a raw string.
value = to_canonical(Decimal(str(point.qty)), metric.units, spec, metric=metric.name)
```

and `schemas.py:106-109`:

```python
# THIS PARSER IS SHARED WITH PHASE 9. `export.xml`, `records.csv` and the webhook JSON all use
# this format ... Do not write a second one; two parsers produce two shapes and the historical
# trend silently disagrees with the ongoing one.
```

Wire model to construct: `HAEPayload` (`schemas.py:90-98`) via `HAEPayload.model_validate({"data":
{"metrics": [...]}})`. Hevy exclusion predicate to rely on unchanged (`normalize.py:104-116`):

```python
_HEVY_SOURCE_ALIASES: frozenset[str] = frozenset({"hevy"})


def is_hevy_sourced(source: str | None) -> bool:
    """True when this datapoint came from Hevy's HealthKit write-back (HEALTH-08).

    Matches the APP name, never the device name ... A missing source is not Hevy: it is the
    gait-metric case, and treating it as Hevy would silently delete the phone's own samples.
    """
    if source is None:
        return False
    return source.strip().casefold() in _HEVY_SOURCE_ALIASES
```

**Progress / heartbeat logging pattern (D-05)** — closest analog is the per-page commit line in
`backend/app/integrations/hevy/workouts.py:283-289`. Counts only, one event name, structured kwargs:

```python
log.info(
    "hevy_workout_page_committed",
    page=page,
    page_count=payload.page_count,
    upserted=result.upserted,
    skipped=len(result.skipped),
)
```

RESEARCH lines 1016 corrects CONTEXT D-05: the heartbeat belongs on the **write** loop
(~24k round trips unbatched, ~17 chunked statements), not on the parse (3.5 s). Note the split:
`log.info` is the *record of what the process did*; the D-06 summary is `print()` (see the CLI
section below).

**Completion log** (`ingest.py:309-317`) — the shape the backfill's own completion event should copy:

```python
log.info(
    "health_ingest_completed",
    rows_upserted=rows_upserted,
    rows_skipped=rows_skipped,
    datapoints_seen=normalized.datapoints_seen,
    datapoints_dropped=normalized.datapoints_dropped,
    metrics_unrecognized=normalized.metrics_unrecognized,
    kinds=sorted(normalized.kinds_present),
)
```

**Errors** — if this module needs a new exception (e.g. unreadable/not-HealthData XML), subclass
`HAEError` in `backend/app/integrations/health_auto_export/errors.py` and follow
`HAEPayloadError`'s constructed-from-nothing discipline (`errors.py:21-34`):

```python
class HAEPayloadError(HAEError):
    """... Constructed from NOTHING, deliberately: an ``__init__`` that accepted
    a message would let a future caller interpolate the payload into it and no test elsewhere
    would notice.
    """

    def __init__(self) -> None:
        self.safe_message = "Health Auto Export payload did not match the expected envelope"
        super().__init__(self.safe_message)
```

**Boundary constraint on this file's public surface (Pitfall 1):** expose ONE high-level entry
point that `cli.py` imports. Mirror how `backend/app/api/routes/health_ingest.py` imports only
`ingest.parse_payload` / `ingest.ingest_payload` and never names `HAEPayload`. The enforcing test
is `backend/tests/test_health_auto_export_isolation.py:62-99`.

---

### `backend/app/cli.py` (CLI entrypoint, request-response) — MODIFIED

**Analog:** the same file's existing subcommands. `_run_status` (lines 205-228) for the
`print()`-based operator output; `_run_mapping_gaps` (lines 231-277) for the read-only,
no-`HEVY_API_KEY`, engine-lifetime-owning shape.

**Module docstring** (`cli.py:1-21`) — extend the usage block at the top; the bootstrap-order
paragraph below it is load-bearing and enforced by a test:

```python
"""Command-line entrypoint for Hevy sync.

    PYTHONPATH=backend uv run python -m app.cli sync-hevy
    PYTHONPATH=backend uv run python -m app.cli sync-status
    PYTHONPATH=backend uv run python -m app.cli mapping-gaps

Bootstrap order is load-bearing and is the same order `app/main.py` uses: configuration is
read first ... then logging is configured ... and only then is anything that can emit a
log line constructed.
"""
```

**Subcommand registration** (`cli.py:97-108`) — copy `mapping-gaps`' shape; `_add_user_id`
(lines 52-59) is the shared `--user-id` declaration:

```python
    status = subcommands.add_parser(
        "sync-status", help="Print last_synced_at for every Hevy resource."
    )
    _add_user_id(status)

    gaps = subcommands.add_parser(
        "mapping-gaps",
        help="List exercise templates with no canonical muscle mapping (D-03).",
    )
    _add_user_id(gaps)

    return parser
```

For the `--dry-run` flag, the flag-declaration style to follow is `cli.py:78-88` (note: `sync-hevy`
uses `add_mutually_exclusive_group()` when two flags contradict — `--dry-run` does not need one,
but the comment discipline about *why* a flag shape was chosen does apply).

**Dispatch** (`cli.py:111-125`) — add one branch. Nothing may move above `configure_logging`:

```python
def main(argv: Sequence[str] | None = None) -> int:
    """Parse, configure, dispatch. Returns the process exit code.

    Nothing above the `configure_logging` call may construct a logger or an engine, and the
    parser deliberately runs first: an invalid command line should exit 2 without ever
    touching the environment.
    """
    args = build_parser().parse_args(argv)
    settings = get_settings()  # fail-fast BEFORE anything else
    configure_logging(settings)  # then logging, so the scrubber has the secret values
    if args.command == "sync-status":
        return asyncio.run(_run_status(settings, args))
    if args.command == "mapping-gaps":
        return asyncio.run(_run_mapping_gaps(settings, args))
    return asyncio.run(_run_sync(settings, args))
```

**Runner shape + engine lifetime + `print()` operator output** (`cli.py:205-228`). This is the
exact template for `_run_backfill`, including the docstring's explanation of why `print` and not a
log line, and why the command does not need `HEVY_API_KEY`:

```python
async def _run_status(settings: Settings, args: argparse.Namespace) -> int:
    """HEVY-09 as operator output: one line per resource, on stdout.

    `print`, not a log line: this is the answer to a question somebody asked, not a record of
    what the process did, and it has to stay readable when the renderer is JSON.

    Calls `resource_status` directly rather than through `HevySyncService`, because the
    service needs a `HevyClient` and `build_hevy_client` refuses to build one without
    `HEVY_API_KEY`. Reading a local timestamp must not require the credential.
    """
    log = structlog.get_logger()
    engine = db_session.make_engine(settings)
    sessionmaker = db_session.make_sessionmaker(engine)
    log.info("hevy_cli_started", command="sync-status")
    try:
        entries = await resource_status(sessionmaker, user_id=args.user_id)
    finally:
        await engine.dispose()
        log.info("hevy_cli_stopped", command="sync-status")

    for entry in entries:
        when = entry.last_synced_at.isoformat() if entry.last_synced_at is not None else "never"
        print(f"{entry.resource}: {when} ({entry.status})")
    return 0
```

The D-06 summary block follows `_run_mapping_gaps`' multi-line-then-total shape (`cli.py:261-277`):

```python
        print(f"{external_id}  {titles.get(external_id, '?')}  [{flag}]")
    gaps = len(external_ids) - deliberate
    print(f"{len(external_ids)} unmapped ({deliberate} deliberate, {gaps} gaps)")

    # Exit 0 even with gaps. This is an inspection command ... exiting non-zero would turn a
    # curation backlog into a broken pipeline the moment this is ever wired into CI.
    return 0
```

**Error printing — `str(exc)` is banned by a test** (`cli.py:137-146`, enforced by
`test_cli.py:142-158`). If the backfill needs to report a failure to stderr, route through this:

```python
def _safe_detail(exc: BaseException) -> str:
    """The message an exception was CONSTRUCTED with, or its class name.

    Reading `args[0]` rather than rendering the exception keeps the call that would reproduce a
    pydantic ValidationError's `input_value=` -- and with it this person's workout titles -- out
    of this file entirely (T-03-45).
    """
    first = exc.args[0] if exc.args else None
    return first if isinstance(first, str) and first else type(exc).__name__
```

and the failure branch shape (`cli.py:185-196`):

```python
    except HevyError as exc:
        log.error("hevy_cli_failed", reason=type(exc).__name__)
        print(f"Hevy sync failed: {exc.safe_message or type(exc).__name__}", file=sys.stderr)
        return 1
```

**RESEARCH Open Question 3 — settled, no action needed.** `backend/app/config.py:65` declares
`hevy_api_key: SecretStr | None = None`, so `get_settings()` bootstraps with only `DATABASE_URL`.
D-02's one-liner invocation stands.

**Hard constraint on this file:** `cli.py` is inside `_app_modules_outside_hae()`
(`test_health_auto_export_isolation.py:37-43` uses `rglob`), so it MUST NOT contain the strings
`from app.integrations.health_auto_export.registry` or `...health_auto_export.schemas`. Import only
`backfill`.

---

### `backend/app/integrations/health_auto_export/normalize.py` — MODIFIED (docstring only)

**Analog:** itself. RESEARCH Pitfall 2 (lines 537-567) proves the documented "Pitfall N-3" claim is
stale, and that the staleness inverts the conclusion about success criterion #3.

**Text to correct** (`normalize.py:21-28`):

```python
Pitfall N-3 -- match the APP name, never the device name
--------------------------------------------------------
Two source vocabularies exist. The webhook sends ``"iPhone"``; ``export.xml`` says
``"Vegant’s iPhone"``. The device name is unstable -- this device was renamed mid-history
(366,339 records under one name, 70,900 under the other) -- and it carries U+2019 RIGHT SINGLE
QUOTATION MARK rather than an ASCII apostrophe, so any hardcoded device comparison fails
silently and forever.
```

Ground truth (`backend/tests/fixtures/hae/device_capture.json`, live-verified 2026-09-03): the
webhook sends `V’s iPhone` — byte-identical, U+2019 included, to `export.xml`'s current-phone
`sourceName`. Correct the claim; keep the "match the APP name, never the device name" rule, which
is still right. **No code change.** `_HEVY_SOURCE_ALIASES` needs no widening (269/269 caught).

Also worth noting in the same pass: `normalize.py:30-37` ("Assumption A1, STILL OPEN") is now
closed by the same fixture.

---

### `backend/tests/conftest.py` — MODIFIED (add an XML fixture loader)

**Analog:** `conftest.py::hae_fixture` (lines 140-174). Copy the signature shape, the
`encoding="utf-8"` argument, and — critically — the provenance paragraph, which is this repo's
convention for any fixture derived from the user's real health data:

```python
HAE_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "hae"


def hae_fixture(name: str) -> dict[str, Any]:
    """Load a canned Health Auto Export webhook payload.

    Provenance matters here and is recorded on purpose. These files are transcribed from FIVE
    REAL captured device payloads ... They are NOT derived from
    `jare0014/obsidian-health-connect`'s sample, which is hand-written and WRONG.

    `encoding="utf-8"` is load-bearing, not decoration: the real source names include
    `カロミル` and `Vegant’s iPhone`, the latter carrying U+2019 RIGHT SINGLE QUOTATION MARK
    rather than an ASCII apostrophe (Pitfall N-3). Reading under a locale default would either
    mangle them or raise, and a mangled source name is exactly the failure that makes the
    HEALTH-08 exclusion predicate stop matching.
    """
    payload: dict[str, Any] = json.loads(
        (HAE_FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8")
    )
    return payload
```

New loader returns a `Path` (or raw text), not a parsed dict — the module under test owns the parse.

---

### `backend/tests/fixtures/hae/export_sample.xml` (test fixture, file-I/O) — NEW

**Analog:** `backend/tests/fixtures/hae/device_capture.json` — role-match (same directory, same
purpose, different serialization). The binding rule is the one recorded in `hae_fixture`'s
docstring above: **synthetic quantities only.** `export.xml` is gitignored real health data; no
measured value from it may be committed. `device_capture.json`'s own header records exactly this
compromise ("Its `qty` values are synthetic ... What IS real ... the metric-name and units
vocabulary, and this device's CURRENT source vocabulary").

Required contents (RESEARCH lines 910-915): the `<!DOCTYPE HealthData [...]>` internal subset; a
`<Workout>` containing a nested `<WorkoutStatistics type="HKQuantityTypeIdentifierActiveEnergyBurned"
sum="..." unit="kcal"/>` (Pitfall 3); a `sourceName="Hevy"` `ActiveEnergyBurned` `Record`; a
`BodyMass` `Record`; both U+2019 device names; an `<ActivitySummary>`; and one unrecognized type.

Source strings to copy byte-for-byte from `device_capture.json` (`V’s iPhone`, `Foodvisor`) — this
is what the SC#3 pinning test compares against.

---

### `backend/tests/test_health_auto_export_backfill.py` (test, unit / fast suite) — NEW

**Analog:** `backend/tests/test_health_auto_export_normalize.py`

**Docstring pattern** (lines 1-20) — states requirement IDs, then explicitly says what lives
elsewhere. Copy that structure; this phase's "elsewhere" is the idempotency and real-file files:

```python
"""Unit coverage for the HAE normalizer: HEALTH-06, HEALTH-08, NUTR-02, D-01, D-02, D-04.

Pure and container-free on purpose. `normalize.py` touches no database, so every case here runs
in the FAST suite and fails on the commit that breaks it rather than after a deploy.

What deliberately lives ELSEWHERE:

* **Idempotency and the `ON CONFLICT` clause** -- plan 08-06, against a real Postgres container.
...

Non-ASCII source names are written as ESCAPES (`\\u2019`), never as literals: `Vegant's iPhone`
carries U+2019 RIGHT SINGLE QUOTATION MARK, which is invisible in a diff and which one careless
editor normalising to an ASCII apostrophe would silently turn into a different test.
"""
```

**Constants pattern** (lines 45-54) — the escape rule is non-negotiable here:

```python
TZ = "Asia/Jakarta"  # +07:00

MORNING = "2025-08-15 08:00:00 +0900"  # 06:00 in Jakarta -> 2025-08-15
DAY = dt.date(2025, 8, 15)

# The device name from the user's real export, spelled with U+2019. It must NOT match the Hevy
# predicate: HEALTH-08 is about the APP that wrote the sample, not the phone it was written on.
DEVICE_NAME = "Vegant’s iPhone"
```

**Builder-helper pattern** (lines 63-80) — small composable builders instead of large fixture files.
The XML analog is a `_record(...)` / `_workout(...)` string builder:

```python
def _point(*, qty: Any = 100, date: Any = MORNING, source: Any = "iPhone") -> dict[str, Any]:
    """One wire datapoint. Pass `_OMITTED` to leave a KEY OUT, which is not the same as null --
    real payloads omit `source` entirely for gait metrics."""
    raw = {"qty": qty, "date": date, "source": source}
    return {key: value for key, value in raw.items() if value is not _OMITTED}


def _metric(name: str, *, units: str = "count", points: list[dict[str, Any]]) -> dict[str, Any]:
    return {"name": name, "units": units, "data": points}
```

**Log-capture pattern** — this file already does structlog capture via `configure_logging` +
`io`/`json`/`logging` (imports at lines 24-31, `Callable` capture helper). Reuse it for the D-07
"logged and skipped" assertion and for the Pitfall 4 warning-suppression assertion. The richer
version, with a typed helper, is `test_health_ingest_idempotency.py:163-205`
(`_run_capturing_logs`, `_events`, `_scan`).

Tests to write are enumerated in RESEARCH lines 886-894 (mapping totality, the 5 naming traps,
non-`Record` elements never ingested, Hevy exclusion, `device_capture.json` source-name equality,
dry-run writes nothing, malformed record does not abort).

---

### `backend/tests/test_backfill_idempotency.py` (test, integration / CRUD) — NEW

**Analog:** `backend/tests/test_health_ingest_idempotency.py` — exact match. Same table, same
constraint, same container, same cleanup hazard.

**Docstring + cleanup discipline** (lines 1-15):

```python
"""HEALTH-09 and NUTR-03 against a real Postgres container.

The day-grained upsert is the whole design, and it only means anything against a database that
actually enforces `uq_health_daily_metrics_user_source_metric_source_name_day`. SQLite would
accept a duplicate key and every assertion below would pass while production silently grew two
rows per day.

Cleanup is a per-test `finally` rather than a fixture teardown, deliberately: these rows share a
session-scoped container with every other integration test, and a health row that outlived its
test would make the NEXT test's "one row, not two" assertion depend on execution order.

Non-ASCII source names are written as ESCAPES (`\\u30ab`), never as literals.
"""
```

**Row-snapshot comparison type** (lines 57-59) — compare rows as data, never as ORM identity:

```python
# One stored row, as data rather than as ORM identity:
# (metric, source_name, local_day, value, units, sample_count).
Snapshot = tuple[str, str, dt.date, Decimal, str, int]
```

**Marker + engine fixture pattern** (lines 222-223 and throughout):

```python
@pytest.mark.integration
async def test_identical_payload_twice_changes_nothing(engine: AsyncEngine) -> None:
```

Helper set to copy: `_maker` (line 90), `_read_all_rows` (line 107), `_read_one` (line 125),
`_cleanup` (line 145). The SC#3 test this phase adds is the backfill-then-webhook-same-day case;
the closest existing shape is `test_an_overlapping_window_replaces_rather_than_accumulates`
(line 296) and `test_two_sources_on_one_day_stay_two_rows_across_a_resend` (line 471).

---

### `backend/tests/test_backfill_real_export.py` (test, opt-in file-I/O) — NEW

**Analog:** partial only. See [No Analog Found](#no-analog-found).

Closest existing shapes to borrow from:
- `backend/tests/test_cloud_run_deploy.py:382-427` — the only place the suite branches on a
  repo-file's existence (`PROCFILE.exists()`), though it *asserts* presence rather than skipping.
- `pyproject.toml [tool.pytest.ini_options] markers` — where the new `realfile` marker registers.
- `test_cli.py`'s `REPO_ROOT`-relative path construction (`test_health_auto_export_isolation.py:25-27`):

```python
REPO_ROOT = Path(__file__).resolve().parents[2]
APP = REPO_ROOT / "backend" / "app"
```

---

### `pyproject.toml` — MODIFIED

**Analog:** the existing marker registration, same file:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["backend/tests"]
pythonpath = ["backend"]
markers = [
    "integration: test requires a live Postgres container (deselect with -m 'not integration')",
]
```

Add `realfile` in the same one-line "name: description (how to deselect)" form.

**Do not add a dependency.** RESEARCH lines 186-198: stdlib-only, `[project].dependencies` and
`uv.lock` are untouched. If a `noqa` is unacceptable, the ruff per-file-ignore block is the
alternative lever — but note its current scope is tests and migrations only:

```toml
[tool.ruff.lint.per-file-ignores]
"backend/tests/*" = ["S101", "S105", "S106"]
"backend/migrations/versions/*" = ["E501"]
```

RESEARCH (Pitfall 6) recommends the scoped inline `# noqa: S314` with a threat-model comment over
either a per-file-ignore or a five-year-stale `defusedxml`.

---

### `backend/tests/test_cli.py` — MODIFIED

**Analog:** itself. Two guard tests already cover this file and must keep passing after the new
subcommand lands — the planner should treat them as acceptance criteria, not just tests:

`test_configure_logging_precedes_every_log_call` (lines 116-139):

```python
    source = CLI_SOURCE.read_text(encoding="utf-8")
    boundary = source.index("configure_logging(settings)")

    assert "log." not in source[:boundary], (...)
    assert "make_engine" not in source[:boundary], (...)
```

`test_cli_never_formats_an_arbitrary_exception` (lines 142-158):

```python
    assert "str(exc)" not in source, (...)
    assert "safe_message" in source, (...)
```

New parser tests follow lines 28-43 / 104-113:

```python
def test_parser_exposes_mapping_gaps() -> None:
    """The curation report is a first-class verb, not an ad-hoc SQL query in a summary."""
    assert build_parser().parse_args(["mapping-gaps"]).command == "mapping-gaps"

    other_user = uuid.UUID("00000000-0000-0000-0000-0000000000ff")
    parsed = build_parser().parse_args(["mapping-gaps", "--user-id", str(other_user)])
    assert parsed.user_id == other_user
    assert build_parser().parse_args(["mapping-gaps"]).user_id == SEEDED_USER_ID
```

---

### `docs/health-auto-export-setup.md` — MODIFIED

**Analog:** itself. RESEARCH Open Question 2 wants a note that `sample_count` falling from N to 1
on a backfilled day is now a **false positive** for the batch-split detector. That detector is
documented in §7 (line 169, "The one alarm to watch for"):

```markdown
## 7. The one alarm to watch for

```
health_ingest_multi_point_day   metric= source_name= local_day= points=
```

**Under a correct configuration this event never fires.** It fires when a single delivery carries
```

Section-style to copy for a dated entry: §9 "Verification record" (line 225) already holds
`### 2026-09-02 — deployment and endpoint contract` and `### 2026-09-03 — first real device export`.
Add the backfill run as a third dated subsection.

---

## Shared Patterns

### 1. Provider isolation — enforced by test, not convention
**Source:** `backend/tests/test_health_auto_export_isolation.py:37-99`
**Apply to:** `backfill.py` (must contain all HealthKit vocabulary), `cli.py` (must contain none)

```python
def _app_modules_outside_hae() -> list[Path]:
    """Every committed module under `app/` that is not part of the HAE package.

    `rglob` rather than a hand-maintained list: a new subpackage must be covered by this
    boundary the moment it exists, without anyone remembering to add it here.
    """
    return [path for path in sorted(APP.rglob("*.py")) if HAE_PKG not in path.parents]
```

```python
        for forbidden in (
            "from app.integrations.health_auto_export.schemas",
            "import app.integrations.health_auto_export.schemas",
        ):
            assert forbidden not in source, (...)
```

Also asserted INSIDE the package (lines 102-133): no HTTP client import
(`httpx2|httpx|requests|aiohttp|urllib.request`) and no `mcp` / `app.mcp` import. `backfill.py`
reads a local file — it must not grow a fetch path.

### 2. The logging rule — counts, names, dates, units. Never a quantity.
**Source:** `ingest.py:44-52`, `normalize.py:64-69`, `errors.py:1-12`
**Apply to:** `backfill.py`, `cli.py`'s summary block, every new test's log assertions

```python
A metric **name**, a **local_day**, a **source_name**, a **count** and an exception **class
name** are loggable. A stored quantity is not, ever (T-08-39, FOUND-05). ``str(DataError)``
renders the bound parameters, which here are this person's calorie counts, so every skip path
logs ``type(exc).__name__`` and nothing else.
```

RESEARCH extends this verbatim to **stdout**: D-06's summary is counts, metric names, units and
dates only. `test_health_ingest_idempotency.py:949-950`
(`test_no_stored_value_reaches_the_log_stream`) is the existing enforcement shape to copy for a
backfill equivalent.

### 3. `user_id` keyword-only, no default, never from the input (ASVS V4)
**Source:** `ingest.py:116-128`
**Apply to:** every write function in `backfill.py`

```python
async def upsert_health_metric(
    session: AsyncSession, *, user_id: uuid.UUID, row: NormalizedRow
) -> None:
    """...
    ``user_id`` is keyword-only with no default (ASVS V4): the schema is multi-user-ready, so an
    unscoped write is a cross-tenant defect a single-user suite cannot see. It is resolved
    server-side by the route and is NEVER read from the payload -- Health Auto Export cannot
    supply one and must not be able to (T-08-38).
    """
```

`export.xml` cannot supply a `user_id` and must not be able to. The CLI resolves it from
`--user-id` / `DEFAULT_USER_ID` (`cli.py:52-59`).

### 4. Caller owns the transaction; bookkeeping commits with its rows
**Source:** `ingest.py:30-35`, `sync_state.py:5-9`
**Apply to:** `backfill.py`'s write pass

```python
Nothing here commits except :func:`ingest_payload` itself. The two D-03 freshness timestamps are
written into the SAME transaction as the rows they describe and commit with them, so a crash can
never leave a ``sync_state`` row claiming work that rolled back.
```

```python
Every function takes an `AsyncSession` and never commits. The CALLER owns the transaction --
D-08 requires the checkpoint to commit in the SAME transaction as the page of rows it
describes, and a helper that committed on its own would make that impossible.
```

### 5. `ON CONFLICT` bound to the constraint BY NAME
**Source:** `ingest.py:87-90`, `sync_state.py:56-59`
**Apply to:** `backfill.py`'s `_upsert_many` and any per-row fallback

```python
# `ON CONFLICT` is bound to the constraint BY NAME rather than by column list. If the
# constraint is ever renamed, this raises immediately instead of silently degrading into
# a duplicate-row insert.
_CONFLICT_CONSTRAINT = "uq_sync_state_user_provider_resource"
```

### 6. Non-ASCII in tests written as escapes, never literals
**Source:** `test_health_auto_export_normalize.py:18-20`, `test_health_ingest_idempotency.py:11-14`
**Apply to:** every new test file and the XML fixture's inline comments

```python
Non-ASCII source names are written as ESCAPES (`\\u2019`), never as literals: `Vegant's iPhone`
carries U+2019 RIGHT SINGLE QUOTATION MARK, which is invisible in a diff and which one careless
editor normalising to an ASCII apostrophe would silently turn into a different test.
```

The XML fixture is the one place a literal U+2019 must appear (it is data, read with
`encoding="utf-8"`) — flag it in the fixture's own comment so a future editor does not normalize it.

### 7. `print()` = operator answer; `log.*` = record of what the process did
**Source:** `cli.py:206-213`
**Apply to:** D-05 heartbeat (log) vs. D-06 summary (print)

```python
    `print`, not a log line: this is the answer to a question somebody asked, not a record of
    what the process did, and it has to stay readable when the renderer is JSON.
```

### 8. Docstrings as decision records
**Source:** every module read for this map — `ingest.py:1-52`, `normalize.py:1-70`,
`health.py:1-37`, `registry.py:28-41`, `schemas.py:1-16`
**Apply to:** `backfill.py`, all new test files

The convention: requirement IDs in the first line; a named section per decision; the rejected
alternative stated with its concrete failure mode; measured numbers where they exist. Deviating
from this makes the new module the odd one out in a codebase where every peer explains itself.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `backend/tests/test_backfill_real_export.py` | test (opt-in) | file-I/O | **No test in the suite skips on a missing local file.** `grep` for `skipif` / `pytest.skip` across `backend/tests/*.py` returns nothing; the only file-existence branching is `test_cloud_run_deploy.py:382-427`, which *asserts* presence of committed repo files. `export.xml` is gitignored, so CI will not have it — this test needs a genuinely new `pytest.mark.skipif(not EXPORT_XML.exists(), ...)` + `realfile` marker pattern. Use RESEARCH §Validation Architecture (lines 870-921) rather than a codebase analog. |

Two sub-patterns within `backfill.py` also have **no direct in-repo analog** and should be taken
from RESEARCH rather than from a peer module:

1. **Streaming XML parse with the two-clear discipline** — RESEARCH Pattern 1 (lines 290-319).
   Nothing in `backend/app/` parses XML today. The `elem.clear()` + `root.clear()` pair is
   load-bearing (16.2 MB vs 53.5 MB peak, measured).
2. **Chunked multi-row upsert with per-chunk fallback** — RESEARCH Pattern 3 (lines 344-386).
   `grep` for `chunk`/`batch` across `backend/app/` finds only the HTTP body accumulation in
   `api/routes/health_ingest.py:111-112`. Every existing writer is per-row. The *fallback arm*
   of the hybrid, however, IS `ingest.py:245-268` verbatim — so this is half-new, half-copied.

---

## Metadata

**Analog search scope:** `backend/app/**`, `backend/tests/**`, `backend/migrations/**`, `docs/**`,
`pyproject.toml`
**Files scanned:** 133 Python modules + 9 fixtures + 6 docs
**Files read in full for extraction:** `cli.py`, `ingest.py`, `normalize.py`, `registry.py`,
`schemas.py`, `errors.py`, `health_auto_export/__init__.py`, `db/models/health.py`,
`db/repositories/sync_state.py`, `test_health_auto_export_isolation.py`, `test_cli.py`,
`conftest.py` (lines 100-299), `hevy/body.py` (write loop), `hevy/workouts.py` (progress logging),
`pyproject.toml`
**Pattern extraction date:** 2026-09-03
