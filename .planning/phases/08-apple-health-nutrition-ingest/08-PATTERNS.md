# Phase 8: Apple Health & Nutrition Ingest - Pattern Map

**Mapped:** 2026-09-02
**Files analyzed:** 32 (13 new source/data files, 8 new test files, 11 modified files)
**Analogs found:** 30 / 32

> Every excerpt below is verbatim from committed source, with the file path and line numbers it
> was read from on 2026-09-02. Planner: cite the analog path + line range in each plan's action
> section rather than restating the pattern in prose.

---

## File Classification

### New files

| New file | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `backend/app/api/routes/health_ingest.py` | route | request-response (inbound webhook) | `backend/app/api/routes/health.py` | role-match (only other FastAPI route; that one is a GET probe, this is an authenticated POST) |
| `backend/app/integrations/health_auto_export/__init__.py` | package marker / boundary doc | — | `backend/app/integrations/hevy/__init__.py` | exact |
| `backend/app/integrations/health_auto_export/auth.py` | middleware/guard (function-level) | request-response | `backend/app/mcp/auth.py::StaticTokenVerifier` (lines 34-51) | exact |
| `backend/app/integrations/health_auto_export/errors.py` | utility (error taxonomy) | — | `backend/app/integrations/hevy/errors.py` | role-match (Hevy's split is retryable-vs-not for an OUTBOUND client; HAE's is drop-datapoint-vs-drop-metric for an INBOUND payload) |
| `backend/app/integrations/health_auto_export/registry.py` | config (immutable data table) | transform | `backend/app/normalization/exercise_map.py` (lines 46-56) + `backend/app/analytics/recomposition.py:264-274` | exact |
| `backend/app/integrations/health_auto_export/schemas.py` | model (wire quarantine) | transform | `backend/app/integrations/hevy/schemas.py` (lines 24-32, 160-195) | exact |
| `backend/app/integrations/health_auto_export/normalize.py` | service (pure transform) | transform / batch | `backend/app/integrations/hevy/events.py::drain_events` (85-126) for collect-then-apply; `hevy/body.py:54-74` for the wire→column table | role-match |
| `backend/app/integrations/health_auto_export/ingest.py` | service (persistence orchestration) | batch upsert + bookkeeping | `backend/app/integrations/hevy/body.py` (85-232) | exact |
| `backend/app/db/models/health.py` | model (SQLAlchemy) | CRUD | `backend/app/db/models/body.py` (36-92) | exact |
| `backend/migrations/versions/0005_*.py` | migration | — | `backend/migrations/versions/0004_hevy_reference_tables.py` (162-226 = `body_measurements`) | exact |
| `backend/tests/fixtures/hae/*.json` | test fixture data | — | `backend/tests/fixtures/hevy/*.json` + `conftest.py::hevy_fixture` (122-136) | exact |
| `backend/tests/test_health_auto_export_schema.py` | test (unit, wire) | — | `backend/tests/test_hevy_wire_schemas.py` (1-56) | exact |
| `backend/tests/test_health_auto_export_normalize.py` | test (unit, pure) | — | `backend/tests/test_analytics_recomposition.py` / `test_hevy_wire_schemas.py` | role-match |
| `backend/tests/test_health_auto_export_isolation.py` | test (static guard) | — | `backend/tests/test_hevy_isolation.py` (17-116) | exact |
| `backend/tests/test_health_ingest_auth.py` | test (unit + integration) | — | `backend/tests/test_mcp_auth.py` (1-110) | exact |
| `backend/tests/test_health_ingest_route.py` | test (integration, HTTP) | — | `backend/tests/test_rate_limit.py` (305-341) + `test_secret_redaction.py` route-ordering block | role-match |
| `backend/tests/test_health_ingest_idempotency.py` | test (integration, DB) | — | `backend/tests/test_hevy_body.py::test_resync_upserts_on_the_date` (267-285) | exact |
| `backend/tests/test_health_ingest_isolation.py` | test (integration, DB) | — | `backend/tests/test_hevy_body.py` (1-40 header + per-test `finally` cleanup) | role-match |
| `docs/health-auto-export-setup.md` | doc (device prerequisite) | — | `docs/runbook-sync-schedule.md`, `docs/hevy-api-observations.md` | role-match |

### Modified files

| Modified file | Role | What changes | Analog for the change |
|---|---|---|---|
| `backend/app/main.py` | config/bootstrap | register `health_ingest.router` **above** `app.mount("/", mcp_app)`; publish second bucket on `app.state` | `main.py:78-98` (its own existing block) |
| `backend/app/middleware.py` | middleware | second `TokenBucket` selected by path prefix inside `_bucket()` | `middleware.py:110-118` (its own `_bucket`) |
| `backend/app/config.py` | config | `health_ingest_secret: SecretStr \| None`, added to `_SECRET_FIELDS`; ingest rate-limit tuning ints kept OUT | `config.py:25`, `config.py:64-66`, `config.py:95-106` |
| `backend/app/analytics/metadata.py` | service | drop `provider: str = PROVIDER_HEVY` default; `resources` becomes `(provider, resource)` pairs; add `FRESHNESS_RESOURCES_*` for Apple Health | `metadata.py:61-72`, `metadata.py:137-161` |
| 8 `build_freshness` call sites | service/tool | pass explicit pairs | see "Shared Patterns → Freshness signature change" |
| `backend/app/db/repositories/sync_state.py` | repository | add `PROVIDER_APPLE_HEALTH`, `RESOURCE_ACTIVITY`, `RESOURCE_NUTRITION`; decide whether `SYNC_RESOURCES` stays Hevy-only | `sync_state.py:21-34` |
| `backend/app/db/models/__init__.py` | registry | import + `__all__` entry for `HealthDailyMetric` | `db/models/__init__.py:11-27` |
| `backend/tests/conftest.py` | test fixture | `hae_fixture()` loader; `health_daily_metrics` in `_MCP_PURGE_TABLES` | `conftest.py:122-136`, `583-633` |
| `scripts/deploy-cloud-run.sh` | config | `--memory=1Gi`; append `HEALTH_INGEST_SECRET=brett-health-ingest-secret:latest` | `deploy-cloud-run.sh:37`, `:40` |
| `backend/tests/test_cloud_run_deploy.py` | test | required-binding list gains `HEALTH_INGEST_SECRET`; memory assertion | `test_cloud_run_deploy.py:257-272` |
| `backend/tests/test_rate_limit.py` / `test_secret_redaction.py` / `test_config.py` / `test_analytics_metadata.py` / `test_sync_state.py` | test | extend existing cases | their own existing bodies |

### Role/data-flow notes the planner should carry into plan boundaries

- `registry.py`, `schemas.py`, `errors.py` and `auth.py` are **pure, dependency-free, no-DB** —
  they can all land in one early wave and be fully covered by the fast (`-m "not integration"`) suite.
- `normalize.py` is pure but depends on `registry` + `schemas` + `core.time.local_day`.
- `ingest.py` and `db/models/health.py` + the migration are the only DB-touching pieces.
- `main.py` / `middleware.py` / `config.py` / `deploy-cloud-run.sh` are cross-cutting wiring and
  each has an existing drift-guard test that will fail if the change is half-done.

---

## Pattern Assignments

### `backend/app/integrations/health_auto_export/auth.py` (guard, request-response)

**Analog:** `backend/app/mcp/auth.py` — CONTEXT.md D-05 "Claude's Discretion" says copy this exactly.

**The whole pattern** (`backend/app/mcp/auth.py:34-51`) — note the comment is as load-bearing as
the code; it is the only place the bytes-vs-str reasoning is written down:

```python
class StaticTokenVerifier:
    """Constant-time comparison against ``MCP_AUTH_SECRET`` (D-01)."""

    def __init__(self, secret: str) -> None:
        # Compared as BYTES, never as `str`. `secrets.compare_digest` raises
        # `TypeError` on a `str` holding non-ASCII characters, and the ASGI
        # server latin-1 decodes header bytes -- so a single arbitrary byte in
        # the Authorization header would escape as an unhandled exception.
        # Starlette's AuthenticationMiddleware catches only AuthenticationError,
        # so that surfaces as a 500 with a traceback rather than a silent 401,
        # breaking this module's fail-closed contract (T-02-04). The bytes
        # overload has no such restriction and is still constant-time.
        self._secret = secret.encode("utf-8")

    async def verify_token(self, token: str) -> AccessToken | None:
        if secrets.compare_digest(token.encode("utf-8"), self._secret):
            return AccessToken(token=token, client_id="brett-cli", scopes=[])
        return None
```

**Fail-fast factory pattern** (`backend/app/mcp/auth.py:138-141`) — the ingest secret must refuse to
start rather than default to open:

```python
    secret = settings.mcp_auth_secret
    if secret is None or not secret.get_secret_value():
        raise RuntimeError("MCP_AUTH_SECRET is required to start the MCP server")
    return StaticTokenVerifier(secret.get_secret_value())
```

**Deviations for this file:** MCP's verifier returns an SDK `AccessToken`; the HAE one returns
`bool` (RESEARCH "Code Examples → The auth check"). Do NOT import `mcp.server.auth.provider` here —
that would put an MCP dependency inside an integrations package.

---

### `backend/app/integrations/health_auto_export/registry.py` (config, transform)

**Analogs:** `backend/app/normalization/exercise_map.py:46-56` and
`backend/app/analytics/recomposition.py:264-274`.

**Immutable-table pattern** (`exercise_map.py:46-56`) — module constants for the values, a typed
`Mapping` annotation, `MappingProxyType` for the container, and a comment stating why:

```python
_F = CanonicalMuscleGroup.FRONT_DELTS
_S = CanonicalMuscleGroup.SIDE_DELTS
_R = CanonicalMuscleGroup.REAR_DELTS

# NORM-01. Keys are normalize_title() output.
# Values are the deltoid head(s) Hevy's flat 'shoulders' expands to for that movement; the
# role (direct/indirect) is inherited from whether Hevy listed it as primary or secondary.
DELTOID_SPLIT_BY_TITLE: Mapping[str, tuple[CanonicalMuscleGroup, ...]] = MappingProxyType(
```

**The "why immutable" comment to mirror** (`recomposition.py:264-265`):

```python
# MappingProxyType for the reason `exercise_map.py`'s tables use it: a caller must not be able to
# retune a health verdict at runtime.
```

**Explicit-identity-mapping discipline** (`hevy/body.py:51-53`) — the reason every metric name is
listed even when the mapping is an identity; this is exactly the D-04 silent-drop guard:

```python
# wire field name -> local column name. The seven entries whose key differs from their value
# are the unsuffixed fields Hevy sends; the rest are identity mappings, listed explicitly so
# that a field added upstream is a visible omission here rather than a silent drop.
```

**Table-driven-total-function discipline** (`recomposition.py:277-286`) — the model for
"a missing entry is a `KeyError`, not a silent `else`":

```python
def classify_recomposition(
    *, rate_percent_per_week: Decimal | None, signal: ProgressionSignal
) -> RecompositionStatus:
    """Cross the weight-rate ladder with the progression signal. Pure, total, and table-driven.

    A ``KeyError`` here would mean the matrix lost a combination, which is exactly the failure a
    nested-if implementation hides behind a final ``else``. Every one of the 24 pairs is asserted
    by the tests.
    """
    return _LABEL_MATRIX[(_weight_bucket(rate_percent_per_week), signal)]
```

**Drift-guard analog for the registry's key set:** `backend/tests/test_rate_limit.py:222-226`
asserts an exact tuple with a message explaining both failure directions — use this shape for
`set(METRIC_REGISTRY) == EXPECTED_METRICS`:

```python
    assert EXEMPT_PREFIXES == ("/health", "/.well-known/"), (
        f"T-07-04 violated: the exemption list changed. Removing an entry makes the limiter "
        f"able to fail the Cloud Run health probe or Claude's connector discovery; adding one "
        f"opens an unthrottled path. Got: {EXEMPT_PREFIXES!r}"
    )
```

---

### `backend/app/integrations/health_auto_export/schemas.py` (model, wire quarantine)

**Analog:** `backend/app/integrations/hevy/schemas.py`.

**Module docstring establishes the quarantine claim** (`hevy/schemas.py:1-15`, abridged):

```python
"""Pydantic mirrors of Hevy's LIVE wire format (HEVY-05).

This module is the quarantine boundary. If Hevy renames a field, validation fails HERE with a
clear error, instead of a `None` propagating into the database and surfacing three phases
later as a wrong tonnage figure.
...
Every model sets `hide_input_in_errors=True`. A ValidationError from this module would
otherwise render `input_value=...` -- workout titles and body-composition numbers -- into a
message that could reach a log line (FOUND-05).
"""
```

**Shared base-model config** (`hevy/schemas.py:24-32`) — copy this class verbatim, renamed:

```python
class _HevyModel(BaseModel):
    """Shared config for every wire model.

    ``extra="ignore"`` on purpose, and asymmetrically so: Hevy ADDING a field must not break
    a sync -- they ship whenever they like -- while Hevy RENAMING or REMOVING one must break
    it loudly, here, rather than letting a silent `None` reach the database.
    """

    model_config = ConfigDict(hide_input_in_errors=True, extra="ignore")
```

**Decimal-on-the-wire pattern** (`hevy/schemas.py:35-55`) — directly answers RESEARCH Finding C
(fractional `count` metrics) and names the escape hatch if the round trip ever breaks:

```python
class HevySet(_HevyModel):
    """One set. No `id` and no `rir`: sets are identified by `index` alone.

    Numerics are `Decimal`, never `float`. `response.json()` hands pydantic a Python float
    and pydantic converts float->Decimal via the value's STRING form, so `9.5` becomes
    `Decimal("9.5")` rather than `Decimal("9.500000000000000177635683940025...")`. Verified by
    `test_decimal_fields_round_trip_exactly`; if that test ever goes red, the fix is a
    `@field_validator(..., mode="before")` returning `Decimal(str(v))`.
    """
    ...
    weight_kg: Decimal | None = None
```

**Wire-name-fidelity rule** (`hevy/schemas.py:165-166, 178-179`) — the reason `source` stays
`source` here and only becomes `source_name` in `db/models/health.py`:

```python
    # `date`, not `measured_on`, and no `id` field: this mirrors the WIRE. The rename to
    # `measured_on` and to `*_cm` happens in the persistence layer, not here.
```

```python
    # No `_cm` suffix on these six: Hevy does not send one. Adding it here would be a
    # rename, and a rename is exactly what this module exists to make impossible.
```

**Deviations for this file (from RESEARCH §D-05.4 and the anti-patterns list):**
`source: str | None = None` (absent for gait metrics in every real payload);
`units` read at the **metric** level only, never per datapoint; the `date` field needs a
`BeforeValidator`/`strptime` list, not Pydantic's native `datetime` parsing.

---

### `backend/app/integrations/health_auto_export/errors.py` (utility)

**Analog:** `backend/app/integrations/hevy/errors.py`.

**The `safe_message` opt-in channel** (`hevy/errors.py:1-34`) — this is what makes
`format_sync_error` safe, and the HAE errors must join it:

```python
"""Hevy transport errors, split by whether retrying them can possibly help.
...
No exception in this module ever carries the API key, a request header, or a response body.
`safe_message` is the OPT-IN channel for detail that has been checked by hand: everything
that reads an exception for storage or logging (see
``app.db.repositories.sync_state.format_sync_error``) uses only the class name unless that
attribute is present.
"""


class HevyError(Exception):
    """Base for every Hevy transport failure."""

    safe_message: str = ""


class HevyAuthError(HevyError):
    """401/403. Never retried. Never contains the key that was rejected.

    Constructed from a STATUS CODE and nothing else, deliberately: an ``__init__`` that
    accepted a message would let some future caller interpolate the rejected credential
    into it, and no test elsewhere would notice (T-03-16).
    """

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.safe_message = f"Hevy rejected the API key (HTTP {status_code})"
        super().__init__(self.safe_message)
```

**Payload-free wrapping of a `ValidationError`** (`hevy/errors.py:82-93`) — the shape for an
HAE parse failure:

```python
class HevyResponseError(HevyError):
    """A response that did not match the schema.

    Wraps a pydantic ``ValidationError`` WITHOUT reproducing its message:
    ``ValidationError.__str__`` renders ``input_value=...``, i.e. the user's workout titles
    and body-composition numbers (T-03-18, FOUND-05).
    """

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint
        self.safe_message = f"Hevy response did not match the expected schema for {endpoint}"
        super().__init__(self.safe_message)
```

**Deviation:** `UnknownUnitError` must carry the **unit string only** (a unit is not health data);
it must never carry the `qty`. Do NOT copy `RETRYABLE_EXCEPTIONS` or the `import httpx2` line —
`test_health_auto_export_isolation.py` will assert no HTTP client is imported anywhere in this
package (RESEARCH Pitfall N-5).

---

### `backend/app/integrations/health_auto_export/normalize.py` (service, transform)

**Analog for "collect everything before applying anything":**
`backend/app/integrations/hevy/events.py:85-126`. This is the closest existing expression of
RESEARCH Pattern 3 (aggregate the whole payload, then upsert once).

```python
async def drain_events(client: HevyClient, *, since: dt.datetime) -> DrainResult:
    """Read every page of the events feed against ONE `since`, oldest-first. HEVY-02.

    Touches no database and applies nothing: separating the read from the write is what makes
    Rule 2 ("collect every page before applying anything") a property of the type rather than
    a discipline the caller has to remember.
    """
```

**Result-type pattern** (`hevy/events.py:60-82`) — frozen slotted dataclasses, counts only:

```python
@dataclass(frozen=True, slots=True)
class DrainResult:
    """Everything the feed had to say, already ordered for application."""

    events: tuple[HevyWorkoutEvent, ...]  # OLDEST-FIRST
    pages_fetched: int
    cursor: dt.datetime


@dataclass(frozen=True, slots=True)
class EventSyncResult:
    """Counts only, never a payload -- this value is what callers log.

    `skipped_reason` is not an error. It is the answer to "why did an incremental sync do
    nothing?", which is otherwise indistinguishable from "nothing changed upstream".
    """

    pages_fetched: int
    events_applied: int
    ...
```

**Local-day resolution — the only sanctioned source** (`backend/app/core/time.py:62-64`, with the
FOUND-04 guard at `:31-40` and the module docstring's warning at `:12-15`):

```python
def local_day(ts: dt.datetime, tz: str) -> dt.date:
    """The user's local calendar day that this instant falls on. FOUND-03."""
    return to_local(ts, tz).date()
```

```python
def _require_aware(ts: dt.datetime) -> dt.datetime:
    """Fail loudly on naive datetimes.

    FOUND-04 is enforced by a guard, not a convention. Silently assuming UTC
    for a naive input is how a local-time value ends up mis-bucketed with no
    error anywhere in the stack.
    """
    if ts.tzinfo is None or ts.tzinfo.utcoffset(ts) is None:
        raise ValueError("naive datetime rejected: all timestamps must be timezone-aware UTC")
    return ts
```

`tz` is always a parameter, never a module constant — `core/time.py:9-13` is explicit that a
module-level default "would let a wrong-timezone bug pass every test". Read it from `users.timezone`.

**Structured-log-on-skip pattern** (`hevy/events.py:157-162`) — the shape for D-04's
`health_ingest_unrecognized_metric` and RESEARCH's `health_ingest_multi_point_day`: a stable event
name, a categorical field, `reason=type(exc).__name__`, and **never** a value:

```python
        except SQLAlchemyError as exc:
            # Class name only, never the exception's message: a DataError renders the bound
            # parameters, which here are this person's workout titles and weights (T-03-43).
            log.warning(
                "hevy_event_skipped", event_type=event.type, reason=type(exc).__name__
            )
```

**Hevy source constant to reuse, not re-spell** (`hevy/body.py:49`) — RESEARCH Pitfall N-3 says the
exclusion predicate must reference a named constant beside this one, never an inline literal:

```python
SOURCE_HEVY = "hevy"
```

---

### `backend/app/integrations/health_auto_export/ingest.py` (service, batch upsert)

**Analog:** `backend/app/integrations/hevy/body.py` — cited by name in CONTEXT.md and RESEARCH.

**The idempotent upsert** (`backend/app/integrations/hevy/body.py:96-119`) — copy the
constraint-by-name binding and the replace-semantics comment verbatim:

```python
    metrics = {column: getattr(measurement, wire) for wire, column in _WIRE_TO_COLUMN.items()}
    stmt = pg_insert(BodyMeasurement).values(
        id=uuid.uuid4(),
        user_id=user_id,
        source=SOURCE_HEVY,
        # No external_id: this endpoint has no id to store. The column exists for a future
        # provider that does have one.
        external_id=None,
        measured_on=measurement.date,
        **metrics,
    )
    # EVERY metric is written on conflict, including the ones that are now None. Hevy's own
    # PUT documents "all fields are overwritten; omitted fields are set to null", so the local
    # upsert mirrors row-replacement semantics: a metric the user deleted upstream must
    # disappear locally rather than linger as a stale value in a weight trend (T-03-35).
    #
    # Bound to the constraint BY NAME rather than by column list, mirroring
    # `app.db.repositories.sync_state`: if the constraint is ever renamed this raises
    # immediately instead of silently degrading into a duplicate-row insert.
    stmt = stmt.on_conflict_do_update(
        constraint="uq_body_measurements_user_source_measured_on",
        set_={column: getattr(stmt.excluded, column) for column in _WIRE_TO_COLUMN.values()},
    )
    await session.execute(stmt)
```

**Caller-owns-the-transaction contract** (`hevy/body.py:91-95`):

```python
    """Write one dated row, keyed on `(user_id, source, measured_on)`.

    Does not commit: the caller owns the transaction, so the page of rows and the D-08
    resume checkpoint land together or not at all.
    """
```

**SAVEPOINT-per-row loop + bookkeeping in the same transaction** (`hevy/body.py:165-196`):

```python
            async with sessionmaker() as session:
                for measurement in payload.body_measurements:
                    try:
                        # SAVEPOINT per row: without it one bad value aborts the whole
                        # transaction and every later statement fails with
                        # "current transaction is aborted" (Pitfall 11).
                        async with session.begin_nested():
                            await upsert_body_measurement(
                                session, user_id=user_id, measurement=measurement
                            )
                    except SQLAlchemyError as exc:
                        # Class name only: str(DataError) renders the bound parameters, which
                        # here are this person's body-composition numbers (T-03-34).
                        log.warning(
                            "hevy_body_measurement_skipped",
                            measured_on=measurement.date.isoformat(),
                            reason=type(exc).__name__,
                        )
                    else:
                        rows_upserted += 1

                # D-08: the checkpoint commits in the SAME transaction as the rows it
                # describes, so a crash can never leave a cursor claiming work that rolled
                # back.
                await advance_cursor_page(...)
                await session.commit()
```

**Counts-only result** (`hevy/body.py:77-83`) — this is what the 202 body is built from:

```python
@dataclass(frozen=True, slots=True)
class BodyMeasurementSyncResult:
    """Counts only. Never a measurement -- this value is what callers log (T-03-33)."""

    pages_fetched: int
    rows_upserted: int
```

**Sync-state bookkeeping helpers to call** — import from `app.db.repositories.sync_state`, never
re-implement (`hevy/body.py:35-43`):

```python
from app.db.repositories.sync_state import (
    PROVIDER_HEVY,
    RESOURCE_BODY_MEASUREMENTS,
    advance_cursor_page,
    complete_sync,
    ensure_sync_state,
    mark_running,
    record_sync_error,
)
```

`complete_sync` already enforces the tz-aware guard (`db/repositories/sync_state.py:172-174`), so
pass `utc_now()` from `app.core.time`. D-03's two resources call `complete_sync` **independently**,
each only when that payload contained ≥1 accepted metric of that kind (RESEARCH Open Question 2).

**Deviations for this file:** no pagination, no client, no `cursor_page`. The
`advance_cursor_page` call has no analogue here — a webhook has no resume point.

---

### `backend/app/db/models/health.py` (model, CRUD)

**Analog:** `backend/app/db/models/body.py:36-92`.

**Model shape** (`db/models/body.py:36-63`) — `Base, TimestampMixin`, PGUUID pk with
`default=uuid.uuid4`, FK with `ondelete="CASCADE"`, `String(n)` discriminators, `Numeric` never
`Float`:

```python
class BodyMeasurement(Base, TimestampMixin):
    """Every metric Hevy records for one calendar date, in one row."""

    __tablename__ = "body_measurements"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # 'hevy' | 'manual' (D-06)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    ...
    # A calendar DATE, never a timestamp -- see the module docstring.
    measured_on: Mapped[dt.date] = mapped_column(Date, nullable=False)

    # Numeric, never Float: Phase 4 averages these into 7/14/30-day trends and a
    # binary float would make the same inputs produce order-dependent results.
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
```

**Named unique constraint + covering index** (`db/models/body.py:84-92`) — the name is what
`on_conflict_do_update(constraint=...)` binds to:

```python
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "source",
            "measured_on",
            name="uq_body_measurements_user_source_measured_on",
        ),
        Index("ix_body_measurements_user_id_measured_on", "user_id", "measured_on"),
    )
```

**Deviations forced by RESEARCH Pitfall N-1 and Finding C:**
`source_name` is **in** the natural key and **NOT NULL** with an explicit `'unknown'` sentinel;
values are `Numeric(14, 4)`, never `Integer`. Note the auto-generated `uq_` naming convention in
`db/base.py:18-24` yields `uq_%(table_name)s_%(column_0_name)s`, so the five-column constraint
**must** be given an explicit `name=` — as `body.py` does — or the generated name collides.

**Register the model** (`db/models/__init__.py:1-9` states the rule; `:11-27` is the list):

```python
"""Model registry.

Importing this package is what attaches every table to ``Base.metadata``.
``migrations/env.py`` imports it for exactly that reason: without the import,
``alembic revision --autogenerate`` sees empty metadata and emits an empty
migration with no error.

Every new model must be imported here.
"""
```

---

### `backend/migrations/versions/0005_*.py` (migration)

**Analog:** `backend/migrations/versions/0004_hevy_reference_tables.py` — the `body_measurements`
block at lines 162-226 is the direct template.

**Header + revision wiring** (`0004:1-24`):

```python
"""hevy reference tables: exercise templates, muscle map, overrides, body measurements, sync state

Generated by ``alembic revision --autogenerate`` and hand-reviewed.
...
Revision ID: 0004
Revises: 0003
Create Date: 2026-08-29

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
```

**Table body, `op.f()`-wrapped names, TIMESTAMPTZ audit columns, explicit constraint name**
(`0004:162-226`, abridged to the load-bearing lines):

```python
    op.create_table(
        "body_measurements",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        # D-06: 'hevy' | 'manual'.
        sa.Column("source", sa.String(length=16), nullable=False),
        ...
        # NUMERIC, never DOUBLE PRECISION: Phase 4 averages these into 7/14/30-day trends.
        sa.Column("weight_kg", sa.Numeric(precision=6, scale=2), nullable=True),
        ...
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        ...
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_body_measurements_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_body_measurements")),
        # HEVY-07: the whole ROW is keyed by date, not one row per metric.
        sa.UniqueConstraint(
            "user_id",
            "source",
            "measured_on",
            name=op.f("uq_body_measurements_user_source_measured_on"),
        ),
    )
    op.create_index(
        op.f("ix_body_measurements_user_id_measured_on"),
        "body_measurements",
        ["user_id", "measured_on"],
        unique=False,
    )
```

**Exact-reverse downgrade** (`0004:272-278`) — `test_migrations_round_trip` asserts it:

```python
def downgrade() -> None:
    # Exact reverse of `upgrade()`. `test_migrations_round_trip` asserts `downgrade base`
    # leaves ONLY `alembic_version`, so a table or index left behind here fails the suite
    # rather than rotting silently.
    op.drop_table("sync_state")
    op.drop_index(op.f("ix_body_measurements_user_id_measured_on"), table_name="body_measurements")
    op.drop_table("body_measurements")
```

---

### `backend/app/api/routes/health_ingest.py` (route, request-response)

**Analog:** `backend/app/api/routes/health.py` (the only existing route module) — role-match only;
that route is an unauthenticated GET, this is an authenticated POST with a body cap.

**Router construction + degrade-don't-500 error handling** (`api/routes/health.py:14-42`):

```python
router = APIRouter(tags=["health"])
log = structlog.get_logger()


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    """Report service status plus a live database connectivity check.

    D-03: the body is minimal -- ``{status, database}`` and nothing else. ...
    """
    database = "connected"
    status_code = 200
    try:
        async with request.app.state.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - any failure to reach the DB must degrade, not 500
        # The detail goes to the log (which runs through the redaction pipeline);
        # the client gets only the coarse state. Connection errors carry the DSN,
        # host, and driver internals (D-05, FOUND-05).
        log.exception("health_db_check_failed")
        database, status_code = "error", 503
    return JSONResponse(
        status_code=status_code,
        content={"status": "ok" if status_code == 200 else "degraded", "database": database},
    )
```

Note this route reads `request.app.state.engine`; the ingest route reads
`request.app.state.sessionmaker` (published in `main.py:52`).

**Minimal-body-with-an-asserted-key-set precedent** (`middleware.py:60-62`) — the 401 and 429 bodies
this project ships are one key, and a test pins the key set:

```python
# The exact key set of the 429 body. One key, asserted by test: this endpoint can
# be made to emit this body by anyone on the internet, so it must never grow a
# field that echoes the presented credential or an exception detail (T-07-02).
_RATE_LIMITED_BODY = b'{"error":"rate_limited"}'
```

**`user_id` resolved server-side, never from the payload** — `config.py:27-33` is the constant and
the reason it is not configurable:

```python
# The single v1 user, fixed by migration 0002. A plain module constant and deliberately NOT a
# `Settings` field: this is a migration-fixed identity, not configuration, and making it
# env-overridable creates a way to point production at a `user_id` with no `users` row behind it.
DEFAULT_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
```

**No analog in-repo for:** the 413 body-size guard before parse. Follow RESEARCH's architecture
diagram (check `content-length`/stream the body with a cap **before** `await request.json()`),
and give it its own test per the RESEARCH test map.

---

### `backend/app/main.py` (modified — bootstrap)

**The block to edit** (`backend/app/main.py:78-98`). The route must be added between
`app.include_router(health.router)` and `app.mount("/", mcp_app)`:

```python
app.state.rate_limit_bucket = build_limiter(settings)
app.add_middleware(RateLimitMiddleware, bucket=app.state.rate_limit_bucket)

# Pure-ASGI middleware, never Starlette's response-materialising middleware base
# ...
app.add_middleware(CorrelationIdMiddleware)

# D-04: no auth dependency -- /health is open so platform health checks reach it.
app.include_router(health.router)

# MCP-01: mounted at "/" and NOT at "/mcp". ...
# Registered LAST because it is a
# catch-all: FastAPI's own routes are matched first and therefore win.
app.mount("/", mcp_app)
```

The middleware-ordering comment at `main.py:71-77` explains the `add_middleware` PREPEND semantics —
if a second bucket is published on `app.state`, follow the same "one live object, one owner"
convention:

```python
# Order is load-bearing and is the reason this line sits ABOVE the correlation-id
# line rather than below it: `add_middleware` PREPENDS, so the last one added runs
# FIRST. ...
# The bucket is also published on app.state so there is exactly one live bucket
# object with one owner; the middleware reads it per request.
```

**Existing proof that route order is load-bearing** — `backend/tests/test_secret_redaction.py:62-78`
had to re-append the mount after adding a route at test time. Reference it in the plan as the
evidence, and mirror its reasoning in `test_health_ingest_route.py`'s "route resolves to FastAPI,
not the MCP mount" case.

---

### `backend/app/middleware.py` (modified — second bucket)

**The extension point** (`backend/app/middleware.py:110-118`) — this method already resolves a
bucket per request from `scope`; adding a path-prefix branch here is additive:

```python
    def _bucket(self, scope: Scope) -> TokenBucket:
        # `app/main.py` also publishes the bucket at `app.state.rate_limit_bucket`
        # so there is exactly one live bucket object and a test can replace it
        # without rebuilding the middleware stack. Falls back to the constructor
        # argument if `scope["app"]` is absent, so the middleware still works
        # mounted under a bare Starlette router.
        state = getattr(scope.get("app"), "state", None)
        bucket = getattr(state, "rate_limit_bucket", None)
        return bucket if isinstance(bucket, TokenBucket) else self._default_bucket
```

**The dispatch that calls it** (`middleware.py:120-133`) — note `EXEMPT_PREFIXES` is checked
**before** the bucket; the ingest path must NOT be added there (RESEARCH anti-patterns):

```python
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if path.startswith(EXEMPT_PREFIXES):
            await self.app(scope, receive, send)
            return

        wait = self._bucket(scope).take()
```

**Factory pattern for the second bucket** (`middleware.py:153-162`):

```python
def build_limiter(settings: Settings) -> TokenBucket:
    """Build the process-wide bucket from configuration.

    There is no development bypass. A limiter that is off in development is a
    limiter nobody has ever seen fire.
    """
    return TokenBucket(
        capacity=settings.rate_limit_burst,
        refill_per_second=settings.rate_limit_per_minute / 60.0,
    )
```

**Hard constraint on this file:** `backend/tests/test_rate_limit.py:193-209` greps the **whole
module text, comments and docstrings included** for `"x-forwarded-for"`, `'scope["headers"]'` and
`"basehttpmiddleware"`. Any new code or comment here must spell around those three strings, exactly
as the current docstring does (`middleware.py:9-12, 23-36`).

---

### `backend/app/config.py` (modified — new secret)

**The three edits, each with its in-file precedent.**

`config.py:25` — add `"health_ingest_secret"`:

```python
_SECRET_FIELDS = ("database_url", "hevy_api_key", "mcp_auth_secret")
```

`config.py:62-66` — declare the field beside its siblings, `SecretStr | None = None`:

```python
    # SecretStr, never a pydantic DSN type: a DSN-typed field's validation
    # failure echoes the raw input -- password included -- into the
    # ValidationError message.
    database_url: SecretStr
    hevy_api_key: SecretStr | None = None
    mcp_auth_secret: SecretStr | None = None
```

`config.py:95-106` — new **non-secret** tuning ints (the ingest bucket's capacity/refill) go here,
and the comment explaining why they stay OUT of `_SECRET_FIELDS` is the one to mirror:

```python
    # Rate limiting (ROADMAP Phase 7 criterion #2). NOT secrets: these are
    # operational tuning numbers that must stay readable in logs, so they are
    # deliberately kept OUT of `_SECRET_FIELDS`.
    ...
    rate_limit_per_minute: int = 30
    rate_limit_burst: int = 30
```

`config.py:151-158` — nothing to change; adding the field name to `_SECRET_FIELDS` is the entire
wiring, which is why RESEARCH says "a `test_secret_redaction.py` case comes free":

```python
    def secret_values(self) -> list[str]:
        """Every literal secret string the log scrubber must never emit.

        Consumed by ``app.logging.make_value_scrubber``. Sorted longest-first so
        a scrubber replacing sequentially removes the full DB URL before it
        removes the bare password substring inside it.
        """
```

---

### `backend/app/analytics/metadata.py` (modified — `build_freshness` signature)

**The function as it stands** (`backend/app/analytics/metadata.py:137-161`) — the
`provider: str = PROVIDER_HEVY` default on line 142 is what Pitfall 7 says must go:

```python
async def build_freshness(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    resources: Sequence[str],
    provider: str = PROVIDER_HEVY,
) -> FreshnessMetadata:
    """DQ-01. One `last_synced_at` per requested resource, and NOTHING else from the row.

    A resource that has never synced reports `None` rather than being omitted: "never synced"
    is the answer to "when was this last synced", and a missing key is indistinguishable from
    "the resource does not exist".

    Iterated in sorted order so the map is deterministic and diffable between runs.
    """
    out: dict[str, dt.datetime | None] = {}
    for resource in sorted(resources):
        state = await get_sync_state(session, user_id=user_id, provider=provider, resource=resource)
        # ONLY the last-synced timestamp is read off the row. MCP-06: the row's stored error
        # text, its run status and its two resume cursors are internal bookkeeping that must
        # never reach anything Claude can read, and `format_sync_error` exists precisely to
        # bound that leak at the point it is written.
        # Forbidden here: last_error, status, cursor_page, cursor_timestamp -- operator CLI only.
        out[resource] = state.last_synced_at if state is not None else None
    return FreshnessMetadata(resources=out)
```

**Named resource-bundle constants to extend** (`metadata.py:58-72`) — add the Apple Health bundles
in the same style, with the same "why these resources" comment:

```python
# Which bookkeeping rows actually feed a given answer (DQ-01). A per-muscle number is only as
# fresh as the STALER of the two: the muscle map comes from exercise_templates, so a stale
# template sync silently changes every per-muscle figure with no error anywhere in the stack.
FRESHNESS_RESOURCES_WORKOUTS: tuple[str, ...] = (RESOURCE_WORKOUTS,)
FRESHNESS_RESOURCES_MUSCLE: tuple[str, ...] = (RESOURCE_WORKOUTS, RESOURCE_EXERCISE_TEMPLATES)
FRESHNESS_RESOURCES_BODY: tuple[str, ...] = (RESOURCE_BODY_MEASUREMENTS,)
```

**Response-model constraint that bounds the change** (`analytics/schemas.py:57-71`) —
`FreshnessMetadata.resources` is `dict[str, ...]`, so a `(provider, resource)` key must be
flattened to a string before it reaches this model, or the model changes too and
`test_freshness_model_cannot_carry_sync_state_internals` (`test_analytics_metadata.py:144-158`)
must be updated deliberately:

```python
class FreshnessMetadata(_AnalyticsModel):
    """DQ-01. Per-resource ``last_synced_at``, keyed by the ``RESOURCE_*`` constants.
    ...
    Carries ``last_synced_at`` ONLY. Never ``sync_state.last_error``, ``status``, ``cursor_page``
    or ``cursor_timestamp`` -- MCP-06 and CLAUDE.md forbid internal tokens or error text in
    anything Claude can read, and ``format_sync_error`` exists precisely to bound that leak.
    """

    resources: dict[str, dt.datetime | None]
```

**Complete call-site inventory** (all must be updated in the same wave as the signature change):

| File | Lines |
|---|---|
| `backend/app/analytics/volume.py` | 71-74, 198-199, 283-284 |
| `backend/app/analytics/frequency.py` | 37-39, 172-173 |
| `backend/app/analytics/progression.py` | 62-64, 298-299, 497-498, 776-777 |
| `backend/app/analytics/bodyweight.py` | 49-50, 291-292 |
| `backend/app/analytics/records.py` | 44-46, 279-280 |
| `backend/app/analytics/comparison.py` | 45-47, 504-505 |
| `backend/app/analytics/recomposition.py` | 55, 337-338 |
| `backend/app/mcp/tools/workouts.py` | 36, 103-104, 188-189 |
| `backend/tests/test_analytics_metadata.py` | 30-36, 113-114, 137-138, 194-195, 629-636 |

---

### `backend/app/db/repositories/sync_state.py` (modified — new constants)

**The constant block to extend** (`backend/app/db/repositories/sync_state.py:21-34`):

```python
PROVIDER_HEVY = "hevy"

RESOURCE_WORKOUTS = "workouts"
RESOURCE_EXERCISE_TEMPLATES = "exercise_templates"
RESOURCE_BODY_MEASUREMENTS = "body_measurements"

# HEVY-09: three independent data sources, three independent last_synced_at values.
SYNC_RESOURCES: frozenset[str] = frozenset(
    {RESOURCE_WORKOUTS, RESOURCE_EXERCISE_TEMPLATES, RESOURCE_BODY_MEASUREMENTS}
)
```

**Provider-neutrality contract that makes this safe** (`sync_state.py:1-9`) — no schema change is
needed and no `app.integrations` import may appear here:

```python
"""Read and advance per-resource sync bookkeeping (HEVY-09, D-08).

Provider-neutral on purpose: these helpers take `provider` and `resource` as arguments and
import nothing from `app.integrations`, so HEVY-05's boundary holds in both directions.

Every function takes an `AsyncSession` and never commits. The CALLER owns the transaction --
D-08 requires the checkpoint to commit in the SAME transaction as the page of rows it
describes, and a helper that committed on its own would make that impossible.
"""
```

**Trap:** `SYNC_RESOURCES` is consumed by `conftest.py:837` (`worst_case_history` seeds a
`complete_sync` per entry, with `provider=PROVIDER_HEVY` hardcoded). Widening the frozenset to
include `activity`/`nutrition` would silently seed Apple Health rows under `provider='hevy'`.
Recommendation: leave `SYNC_RESOURCES` Hevy-only and add a separate
`APPLE_HEALTH_RESOURCES` frozenset.

---

### `scripts/deploy-cloud-run.sh` (modified — memory + secret)

**Lines to change** (`scripts/deploy-cloud-run.sh:37, 40`):

```bash
  --memory=512Mi \
  --timeout=300 \
  --env-vars-file="$REPO_ROOT/deploy/cloud-run.env.yaml" \
  --set-secrets="DATABASE_URL=brett-database-url:latest,MCP_AUTH_SECRET=brett-mcp-auth-secret:latest" \
```

**The guard that will fail until the test is updated too**
(`backend/tests/test_cloud_run_deploy.py:257-272`):

```python
def test_env_file_and_secret_bindings_partition_the_environment(env_file: dict[str, str]) -> None:
    """Cloud Run rejects a deploy that binds one name twice, and boots without a missing one."""
    bindings = _secret_bindings()

    overlap = sorted(set(env_file) & set(bindings))
    assert not overlap, (...)

    for required in ("DATABASE_URL", "MCP_AUTH_SECRET"):
        assert required in bindings, (
            f"T-02-10 violated: {required} is not bound by --set-secrets. It is a credential, "
            f"so Secret Manager is its only legitimate source -- it must never move into "
            f"deploy/cloud-run.env.yaml"
        )
```

**Also note** `test_no_credential_shaped_key_is_present` (`test_cloud_run_deploy.py:172-187`) fails
on any env-file key containing `SECRET`/`KEY`/`TOKEN`/`PASSWORD` — so `HEALTH_INGEST_SECRET` must
go **only** into `--set-secrets`, never into `deploy/cloud-run.env.yaml`. The ingest rate-limit
tuning ints, being non-secret, go into the env file and are covered by
`test_every_env_var_maps_to_a_settings_field` (`:128-139`).

---

### Test files

#### `backend/tests/test_health_auto_export_isolation.py`

**Analog:** `backend/tests/test_hevy_isolation.py` — copy the whole structure, re-scoped.

**Walk setup + the guard-on-the-guards** (`test_hevy_isolation.py:17-48`):

```python
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APP = REPO_ROOT / "backend" / "app"
HEVY_PKG = APP / "integrations" / "hevy"

# Matched at the START of a line (modulo indentation) so a mention inside a docstring or a
# comment -- of which there are several, deliberately -- is not read as an import.
_HTTPX2_IMPORT = re.compile(r"^\s*(?:import httpx2|from httpx2)", re.MULTILINE)
_INTEGRATIONS_IMPORT = re.compile(r"^\s*(?:import|from)\s+app\.integrations", re.MULTILINE)


def _app_modules_outside_hevy() -> list[Path]:
    """Every committed module under `app/` that is not part of the Hevy package.

    `rglob` rather than a hand-maintained list: a new subpackage must be covered by this
    boundary the moment it exists, without anyone remembering to add it here.
    """
    return [path for path in sorted(APP.rglob("*.py")) if HEVY_PKG not in path.parents]


def test_the_walk_actually_finds_files() -> None:
    """A guard on the guards: an empty walk would make every test below vacuously true.
    ...
    """
    outside = _app_modules_outside_hevy()

    assert len(outside) > 10, f"the walk found only {len(outside)} modules under {APP}"
    assert list(HEVY_PKG.rglob("*.py")), f"no Hevy package found at {HEVY_PKG}"
```

**The wire-schema leak assertion to mirror** (`test_hevy_isolation.py:51-68`):

```python
def test_hevy_schemas_are_not_imported_outside_the_package() -> None:
    """A Hevy wire type in `db/` or `analytics/` makes a Hevy rename a whole-app rename.
    ...
    """
    for path in _app_modules_outside_hevy():
        source = path.read_text(encoding="utf-8")
        for forbidden in (
            "from app.integrations.hevy.schemas",
            "import app.integrations.hevy.schemas",
        ):
            assert forbidden not in source, (
                f"HEVY-05 violated: {path.relative_to(REPO_ROOT)} imports Hevy's wire "
                f"schemas. Translate them inside app/integrations/hevy/ and pass domain "
                f"types outward -- otherwise a Hevy field rename reaches this file too"
            )
```

**Deviation (RESEARCH Pitfall N-5):** the `httpx2` test inverts. For HAE the assertion is that
**no HTTP client is imported anywhere INSIDE** `integrations/health_auto_export/` (it is inbound
only), rather than that none appears outside it. Reuse the `_HTTPX2_IMPORT` regex, flip the walk.
The one-directional boundary note (`test_hevy_isolation.py:11-14`) applies unchanged — the HAE
package may import `app.db.models`, but nothing may import HAE's `schemas`.

#### `backend/tests/test_health_ingest_auth.py`

**Analog:** `backend/tests/test_mcp_auth.py`.

**The split-the-concern docstring** (`test_mcp_auth.py:1-14`) — the same split applies here
(verifier function in the fast suite, wire contract over HTTP with the `integration` marker):

```python
"""Unit tests for the MCP bearer-token verifier (MCP-04).

These test the verifier **directly**, not over HTTP, and that is deliberate. ...
Splitting the concern:

* **here** -- the verifier's decision function: what it accepts, what it denies,
  and that it denies in constant time.
* **over HTTP** (plan 02-04's mount tests) -- the wire contract: that a missing
  or wrong credential yields ``401`` ...
"""
```

**Distinctive-bad-token convention** (`test_mcp_auth.py:105-110` / `test_rate_limit.py:253-256`) —
reuse it so the "the 401 must not echo the credential" assertion cannot pass vacuously:

```python
# Distinctive on purpose: `test_401_leaks_nothing` asserts this exact string is
# absent from the rejection body, so an SDK that starts echoing the presented
# credential back to the caller fails loudly instead of shipping.
BAD_TOKEN = "wrong-token-9f3a-must-not-be-echoed"
```

**Env-not-kwargs settings builder** (`test_mcp_auth.py:113-123`):

```python
def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    """Build ``Settings`` from the environment, exactly as the app does at boot.

    ``_env_file=None`` mirrors ``test_config.py``: a developer's real ``.env``
    must never decide the outcome of a test.
    """
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)
```

#### `backend/tests/test_health_ingest_idempotency.py`

**Analog:** `backend/tests/test_hevy_body.py` — see `test_resync_upserts_on_the_date:267`,
`test_metric_cleared_upstream_is_cleared_locally:286`,
`test_last_synced_at_for_body_measurements_is_independent:363`, and
`test_no_metric_value_reaches_the_log_stream:459`. All four have a direct Phase 8 counterpart.

**Module header stating the container requirement and the cleanup rule** (`test_hevy_body.py:1-16`):

```python
"""HEVY-07 against a real Postgres container.

The date-keyed upsert is the whole design, and it only means anything against a database that
actually enforces `uq_body_measurements_user_source_measured_on`. Only the HTTP transport is
mocked.
...
Cleanup is a per-test `finally` rather than a fixture teardown, deliberately: these rows share
a session-scoped container with every other integration test, and a body-measurement row that
outlived its test would make the NEXT test's "two rows, not four" assertion depend on
execution order.
"""
```

#### `backend/tests/fixtures/hae/*.json` + `conftest.py` loader

**Analog:** `backend/tests/conftest.py:122-136`:

```python
HEVY_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "hevy"


def hevy_fixture(name: str) -> dict[str, Any]:
    """Load a canned Hevy response.

    These files are transcribed from Hevy's LIVE OpenAPI document, not from
    `BRETT blueprint.md` -- the blueprint is wrong about `rir`, `weight_unit`, and
    about exercises/sets having ids. Regenerating them by hand from the blueprint
    would reintroduce exactly the schema drift this phase exists to eliminate.
    """
    payload: dict[str, Any] = json.loads(
        (HEVY_FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8")
    )
    return payload
```

Write the equivalent `HAE_FIXTURE_DIR` / `hae_fixture()` with a docstring recording provenance
(RESEARCH: the five `bunya-gap/health-management-free` device payloads are real output; the
`jare0014` sample is hand-written and **wrong**).

**Purge-table registration** (`conftest.py:583-592`) — add `"health_daily_metrics"` in FK-child-first
order and a matching scoped `delete()` in `_mcp_purge_statements` (`:611-632`):

```python
_MCP_PURGE_TABLES: tuple[str, ...] = (
    "workout_sets",
    "workout_exercises",
    "workouts",
    "exercise_muscle_overrides",
    "exercise_muscles",
    "exercise_templates",
    "body_measurements",
    "sync_state",
)
```

---

## Shared Patterns

Apply these to every file this phase touches. Each already has an enforcing test.

### 1. Secret handling — three layers, no call-site discipline

**Source:** `backend/app/config.py:1-13` (the contract), `:25` (`_SECRET_FIELDS`),
`backend/app/logging.py:1-30` + `:41-71` (layers 2 and 3).
**Apply to:** `config.py`, `health_ingest.py`, `auth.py`, `errors.py`, `ingest.py`.

```python
"""Typed, fail-fast application settings.

Layer 1 of the three-layer FOUND-05 secret defense:

1. **this module** — every secret is a ``SecretStr``, so ``repr`` and
   ``model_dump_json`` render ``**********`` and validation errors never echo
   the raw input.
2. ``app/logging.py`` — key-name censor + value scrubber built from
   :meth:`Settings.secret_values`.
3. the FastAPI error handler — sanitized responses.

Nothing here may ``print`` or log a settings value.
"""
```

`authorization` is already on the layer-2 deny-list (`logging.py:52`), so a log line keyed
`authorization=` is redacted for free. Adding `health_ingest_secret` to `_SECRET_FIELDS` is the
entire layer-3 wiring.

### 2. Error text that never carries a payload

**Source:** `backend/app/db/repositories/sync_state.py:44-56`.
**Apply to:** `errors.py`, `ingest.py`, `normalize.py`, and anything that writes `last_error`.

```python
def format_sync_error(exc: BaseException) -> str:
    """Render an exception for storage WITHOUT leaking a payload.

    Only exceptions that opt in -- by exposing a `safe_message` attribute the raiser curated
    -- contribute any detail. Everything else stores its class name alone. This matters
    concretely: `pydantic.ValidationError.__str__` renders `input_value=...`, so a naive
    `str(exc)` would write a user's workout titles and body-composition numbers into a
    column and, from there, into any log line that reads it back (T-03-13).
    """
    detail = getattr(exc, "safe_message", None)
    if isinstance(detail, str) and detail:
        return f"{type(exc).__name__}: {detail}"[:_MAX_ERROR_LEN]
    return type(exc).__name__[:_MAX_ERROR_LEN]
```

A HAE `ValidationError` renders `input_value=` — i.e. this person's calorie counts. Never
`str(exc)`; always `type(exc).__name__` plus an opt-in `safe_message`.

### 3. Never log a value, only a category and a count

**Source:** `backend/app/integrations/hevy/body.py:129-133` and `:178-182`.
**Apply to:** every `log.*` call added this phase.

```python
    """Walk `/v1/body_measurements` from the D-08 resume point to the end.

    Never logs a metric VALUE. `measured_on` is fine -- a calendar date is not a body
    composition figure -- but a weight, a lean mass or a body-fat percentage is personal
    health data and must not reach the log sink (T-03-33, blueprint §44).
    """
```

By the same rule: a metric **name**, a **local_day**, a **source_name** and a **count** are all
loggable. A `qty` is not. This is exactly what makes `health_ingest_unrecognized_metric` (D-04) and
`health_ingest_multi_point_day` (Pitfall N-2) safe to emit.

### 4. `Decimal`, never `float`, and never `Decimal(float)`

**Source:** `backend/app/db/models/body.py:59-61`, `backend/app/integrations/hevy/schemas.py:38-42`,
`backend/tests/test_hevy_wire_schemas.py:7-13`.
**Apply to:** `schemas.py`, `normalize.py`, `registry.py`, `db/models/health.py`, the migration.

```python
    # Numeric, never Float: Phase 4 averages these into 7/14/30-day trends and a
    # binary float would make the same inputs produce order-dependent results.
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
```

There is an existing repo-wide guard named `test_analytics_declares_no_float` (referenced in
RESEARCH Finding C) that this phase's analytics-adjacent code inherits.

### 5. Constraint bound BY NAME, always

**Source:** `backend/app/db/repositories/sync_state.py:38-41`; same rule restated at
`backend/app/integrations/hevy/body.py:112-114`.
**Apply to:** `ingest.py`, `db/models/health.py`, the migration.

```python
# `ON CONFLICT` is bound to the constraint BY NAME rather than by column list. If the
# constraint is ever renamed, this raises immediately instead of silently degrading into
# a duplicate-row insert.
_CONFLICT_CONSTRAINT = "uq_sync_state_user_provider_resource"
```

### 6. Keyword-only `user_id` with no default (ASVS V4)

**Source:** `backend/app/analytics/metadata.py:108-111` and `:226-228`.
**Apply to:** every new function that reads or writes a user-scoped row.

```python
    `user_id` is keyword-only with no default: ASVS V4 -- the schema is multi-user-ready, so an
    unscoped count is a cross-tenant disclosure a single-user suite cannot see.
```

### 7. Fail-fast at boot, not at first request

**Source:** `backend/app/mcp/auth.py:117-141`, `backend/app/config.py:36-42`,
`backend/app/main.py:1-7`.
**Apply to:** `config.py`, `health_ingest.py`, `main.py`.

```python
    """Select the verifier for the configured auth mode.

    Fails fast at import time rather than at first request: a server that starts
    without a working verifier is a server that is unauthenticated in production
    until someone notices. ...
    """
```

Consequence for planning: if `HEALTH_INGEST_SECRET` is unset, decide explicitly between
"refuse to start" and "register the route but reject everything with 401". The precedent in
this repo is refuse-to-start; a silently unauthenticated write path on an
`--allow-unauthenticated` Cloud Run service is the failure this rule exists to prevent.

### 8. Assertion messages name the requirement, the failure, and the value

**Source:** every test in `backend/tests/` — canonical example
`backend/tests/test_rate_limit.py:76-86`:

```python
    assert allowed == [None, None], (
        f"DEPLOY-03 violated: a bucket with capacity=2 refused one of its first two takes on a "
        f"frozen clock. Every rejection here is a 429 in the middle of a coaching turn, which "
        f"is worse than an unthrottled minute for a single-user connector. Got: {allowed}"
    )
```

**Apply to:** all eight new test files. Requirement ID (`HEALTH-06`…, `NUTR-02`…) + what breaks in
production + the observed value. **Exception:** an assertion about a payload must not interpolate a
`qty` into its message.

### 9. Package boundary docstring

**Source:** `backend/app/integrations/hevy/__init__.py:1-10`.
**Apply to:** `integrations/health_auto_export/__init__.py`.

```python
"""Hevy API integration (HEVY-05).

Everything that knows Hevy's wire format lives here and nowhere else. Hevy's own API preamble
says: "we make no guarantees that we won't completely change the structure or abandon the
project entirely so use it at your own risk." That is the whole justification for this
boundary -- when Hevy changes, exactly one package changes.

Import submodules by full path (``from app.integrations.hevy.client import HevyClient``).
This file deliberately re-exports nothing.
"""
```

---

## No Analog Found

| File / concern | Role | Data Flow | Reason |
|---|---|---|---|
| Body-size rejection (413 **before** JSON parse) in `health_ingest.py` | route guard | request-response | No existing route reads a request body at all. `health.py` is a GET; `/mcp` body limits are owned by the MCP SDK's `max_request_body_size`. Follow RESEARCH's architecture diagram and the ASVS V5 row in the Security Domain section; the closest structural hint is `middleware.py`'s pure-ASGI `__call__` (`:120-150`), which shows how to answer without invoking the router. |
| HAE date parsing (`"%Y-%m-%d %H:%M:%S %z"` + 12-hour variant + U+202F) | utility | transform | Every existing datetime in the repo arrives ISO-8601 from Hevy and is parsed by Pydantic natively (`hevy/schemas.py:80-83`). No `strptime` call exists anywhere in `backend/app/`. Use RESEARCH Pattern 4 verbatim; the only in-repo pattern to carry over is that the parser lives inside the integrations package and raises a `safe_message`-bearing error. |
| `docs/health-auto-export-setup.md` (device prerequisite doc) | doc | — | Partial analog: `docs/runbook-sync-schedule.md` and `docs/hevy-api-observations.md` are the nearest in tone/placement, but no existing doc describes a **device-side setting BRETT depends on for correctness** (Pitfall N-2's daily aggregation interval). Treat the required value as a stated prerequisite, not a tip. |

---

## Metadata

**Analog search scope:** `backend/app/` (all 60 modules), `backend/tests/` (all 47 modules),
`backend/migrations/versions/`, `scripts/`, `deploy/`, `docs/`.
**Files scanned:** 118 committed files; 24 read in full for excerpt extraction.
**Project skills consulted:** none — `.claude/skills/`, `.agents/skills/`, `.cursor/skills/` and
`.github/skills/` are all absent (confirmed 2026-09-02).
**Pattern extraction date:** 2026-09-02
