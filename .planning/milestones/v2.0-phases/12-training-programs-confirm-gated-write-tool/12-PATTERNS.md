# Phase 12: Training Programs & Confirm-Gated Write Tool - Pattern Map

**Mapped:** 2026-09-04
**Files analyzed:** 13 (4 new source, 1 new migration, 5 modified, 2 new test files + 3 extended test files)
**Analogs found:** 13 / 13 (every file has a same-repo analog; the write-session/atomic-token
mechanics have no exact analog but compose two existing patterns, noted below)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `backend/app/db/models/program.py` | model | CRUD (append-only) | `backend/app/db/models/sync_state.py` | role-match (closest: FK to users, string discriminator columns, `TimestampMixin`) |
| `backend/app/db/repositories/programs.py` | service/repository | CRUD + atomic token consume | `backend/app/db/repositories/sync_state.py` | role-match (never-commits convention, `_upsert` style); token-consume half has no analog, see Pattern 2 below |
| `backend/app/mcp/tools/programs.py` | controller (MCP tool) | request-response (write, two-call) | `backend/app/mcp/tools/body.py` | role-match (structure); write/token semantics are net-new, composed from PITFALLS #13 + `safe_tool` |
| `backend/migrations/versions/0006_user_program_history.py` | migration | batch (DDL + seed INSERT) | `backend/migrations/versions/0005_health_daily_metrics.py` (table/index shape); `0002_seed_default_user.py` (seed-insert-in-migration idiom) | exact (structure) / role-match (seed pattern uses a hardcoded value, this phase's seed is data-derived — see Pitfall note) |
| `backend/app/analytics/recomposition.py` (MODIFIED) | service (analytics) | transform | itself — extend existing table-driven style, no external analog needed | exact |
| `backend/app/analytics/schemas.py` (MODIFIED) | model (Pydantic contracts) | transform | itself — extend `RecompositionResult` following `PlateauResult`'s "echo the inputs" convention | exact |
| `backend/app/mcp/server.py` (MODIFIED) | route/registration | request-response | itself — add a second registration block after the `_TOOLS` loop | exact |
| `backend/app/mcp/tools/_common.py` (MODIFIED) | utility | request-response | itself — add `writable_session` beside `read_only_session` | exact |
| `backend/app/mcp/tools/schemas.py` (MODIFIED) | model (Pydantic contracts) | transform | itself — extend following `RecompositionResponse`/`WorkoutDetailResponse` conventions | exact |
| `backend/tests/test_mcp_isolation.py` (MODIFIED) | test | static/structural | itself — extend `_NOT_TOOL_MODULES`-style allowlist pattern with a new `_WRITE_ALLOWLIST` | exact |
| `backend/tests/test_mcp_tool_schemas.py` (MODIFIED) | test | request-response | itself — extend `EXPECTED_TOOLS`, rename the "fourteen" test, partition `test_every_tool_is_annotated_read_only` | exact |
| `backend/tests/test_analytics_recomposition.py` (MODIFIED) | test | unit/integration | itself — extend `test_full_label_matrix`-style table tests per program | exact |
| `backend/tests/conftest.py` (MODIFIED) | test fixture | CRUD | itself — extend `GoldenBuilder` with a `program_period(...)` builder method matching `user(...)`'s shape | exact |
| `backend/tests/test_db_program_history.py` (NEW) | test | integration | `backend/tests/test_analytics_recomposition.py`'s async/container-backed tests | role-match |
| `backend/tests/test_mcp_program_switch.py` (NEW) | test | integration | `backend/tests/test_mcp_tool_schemas.py` (Client(mcp) pattern) + a to-be-written `test_mcp_readonly.py`-style write-path test | role-match |

## Pattern Assignments

### `backend/app/db/models/program.py` (model, CRUD)

**Analog:** `backend/app/db/models/sync_state.py` (structure), `backend/app/db/models/body.py` (docstring conventions, `Numeric`/`Date` column style)

**Imports pattern** (`sync_state.py` lines 17-32):
```python
import datetime as dt
import uuid

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
```
For `program.py`, two models are needed (`ProgramPeriod`, `ProgramSwitchToken`), so also import
`Date`, `Index` (for a plain non-unique lookup index if needed) — see `body.py` lines 22-30 for the
`Date` + `Index` import shape.

**Core model pattern** (`sync_state.py` lines 35-76, adapted):
```python
class SyncState(Base, TimestampMixin):
    __tablename__ = "sync_state"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    resource: Mapped[str] = mapped_column(String(32), nullable=False)
    ...
    __table_args__ = (
        UniqueConstraint(
            "user_id", "provider", "resource", name="uq_sync_state_user_provider_resource"
        ),
    )
```
`ProgramPeriod` follows this shape with `program: Mapped[str]` (String(16), the three lowercase
values), `started_on`/`ended_on: Mapped[dt.date | None]` (use `Date`, per `body.py`'s
`measured_on` precedent — line 57 — since these are calendar dates, not instants; FOUND-04 does
not apply to a `Date` column). The partial-unique "one open period" index is NOT expressible as a
`UniqueConstraint` in the ORM `__table_args__` in a portable way — it is added in the MIGRATION
via `op.create_index(..., postgresql_where=...)` (see migration section below), not as a
SQLAlchemy `Index(..., postgresql_where=...)` on the model, to match this repo's existing
convention of keeping partial/expression indexes in the migration only when autogenerate cannot
express them (see `0005`'s own hand-written index).

`ProgramSwitchToken` also follows the `SyncState` shape: `token: Mapped[str]` (String(64),
`UniqueConstraint`), `from_period_id: Mapped[uuid.UUID]` (FK to `user_program_history.id`,
`ondelete="CASCADE"`), `to_program: Mapped[str]`, `issued_at`/`expires_at: Mapped[dt.datetime]`
(DateTime(timezone=True), FOUND-04 applies here — these ARE instants), `consumed_at:
Mapped[dt.datetime | None]`.

**Docstring convention** (`sync_state.py` lines 1-15, `body.py` lines 1-16): open with the
requirement/decision id, explain the ONE naming or modelling choice that could be gotten wrong
(here: D-07's append-only-not-mutable-column rationale, and why the partial unique index lives in
the migration not the model), in the same terse, load-bearing prose style — not generic docstring
filler.

---

### `backend/app/db/repositories/programs.py` (service/repository, CRUD + atomic token consume)

**Analog:** `backend/app/db/repositories/sync_state.py`

**Imports pattern** (`sync_state.py` lines 11-19):
```python
import datetime as dt
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.sync_state import SyncState
```
For `programs.py`, add `update`, `or_` from `sqlalchemy` (per RESEARCH.md Pattern 2's
`consume_switch_token`) and `from app.db.models.program import ProgramPeriod, ProgramSwitchToken`.
**Per Pitfall A in RESEARCH.md**, these `update`/`insert` imports are FINE here — this module is
the one place PITFALLS #14 designates for write statement construction. They must NOT leak into
`app/mcp/tools/programs.py`.

**Never-commits convention** (`sync_state.py` module docstring, lines 6-9):
```
Every function takes an `AsyncSession` and never commits. The CALLER owns the transaction --
D-08 requires the checkpoint to commit in the SAME transaction as the page of rows it
describes, and a helper that committed on its own would make that impossible.
```
Apply verbatim to `programs.py`: every function takes `session: AsyncSession` positionally,
`user_id` keyword-only with no default (ASVS V4, matches `sync_state.py`'s
`get_sync_state(session, *, user_id, provider, resource)` signature style), and none of
`get_active_period`, `get_periods_overlapping`, `issue_switch_token`, `consume_switch_token`,
`close_period_and_open_new` call `session.commit()`. The MCP tool (`app/mcp/tools/programs.py`)
is the only caller that commits, per PITFALLS #15's "commit is the LAST statement".

**Read pattern** (`get_sync_state`, `sync_state.py` lines 106-116):
```python
async def get_sync_state(
    session: AsyncSession, *, user_id: uuid.UUID, provider: str, resource: str
) -> SyncState | None:
    """The bookkeeping row, or None if this resource has never been synced."""
    return await session.scalar(
        select(SyncState).where(
            SyncState.user_id == user_id,
            SyncState.provider == provider,
            SyncState.resource == resource,
        )
    )
```
Directly analogous to `get_active_period(session, *, user_id) -> ProgramPeriod | None` (RESEARCH.md
Pattern 1) — same `session.scalar(select(...).where(tenant_predicate_first, ...))` shape.

**Atomic get-or-create / atomic update pattern** (`ensure_sync_state`, `sync_state.py` lines
119-136, and `_upsert`, lines 77-104):
```python
async def ensure_sync_state(
    session: AsyncSession, *, user_id: uuid.UUID, provider: str, resource: str
) -> SyncState:
    """Get-or-create, atomically.

    Uses `pg_insert(...).on_conflict_do_nothing(constraint=...)` followed by a SELECT, not
    SELECT-then-INSERT: the read-then-write is a race and costs two round trips even when it wins.
    """
    statement = pg_insert(SyncState).values(...)
    await session.execute(statement.on_conflict_do_nothing(constraint=_CONFLICT_CONSTRAINT))
    state = await get_sync_state(session, user_id=user_id, provider=provider, resource=resource)
    if state is None:  # pragma: no cover
        raise RuntimeError(...)
    return state
```
This is the repo's existing precedent for "avoid read-then-write races via one atomic SQL
statement" — the SAME principle RESEARCH.md's `consume_switch_token` (`UPDATE ... WHERE ...
RETURNING`) applies to token consumption. Model `consume_switch_token` and
`close_period_and_open_new` on this atomicity discipline even though the exact SQL shape
(`UPDATE...RETURNING` vs `ON CONFLICT DO NOTHING` + SELECT) differs — RESEARCH.md's Pattern 2 code
block is the concrete template to use verbatim.

**Constraint-by-name convention** (`sync_state.py` line 59 and its comment, lines 56-59):
```python
# `ON CONFLICT` is bound to the constraint BY NAME rather than by column list. If the
# constraint is ever renamed, this raises immediately instead of silently degrading into
# a duplicate-row insert.
_CONFLICT_CONSTRAINT = "uq_sync_state_user_provider_resource"
```
Apply the same by-name-not-by-columns discipline to any `ON CONFLICT`/constraint reference in
`programs.py`.

---

### `backend/app/mcp/tools/programs.py` (controller/MCP tool, request-response write)

**Analog:** `backend/app/mcp/tools/body.py` (structure — no-argument tools with `safe_tool` +
degraded factory), composed with RESEARCH.md's Pattern 4/5/6 for the write-specific mechanics
(no exact write-tool analog exists in this codebase; this is deliberately this phase's only write
tool).

**Imports pattern** (`body.py` lines 31-46):
```python
from typing import Annotated

from mcp.server.mcpserver import Context
from pydantic import Field

from app.analytics.recomposition import get_recomposition_status  # NOT needed here — analog only
from app.mcp.context import AppContext
from app.mcp.tools._common import read_only_session, resolve_user_id, safe_tool
from app.mcp.tools.schemas import ...
```
For `programs.py`: `from app.mcp.tools._common import writable_session, resolve_user_id,
safe_tool, local_today` (NOT `read_only_session` — this tool never opens one) and
`from app.db.repositories.programs import get_active_period, issue_switch_token,
consume_switch_token, close_period_and_open_new` (repository functions only — NEVER `from
sqlalchemy import insert, update, delete` here; see Pitfall A).

**Degraded-factory pattern** (`body.py` lines 53-61, 77-80):
```python
def _degraded_trend() -> BodyWeightTrendResponse:
    """BODY-01's "I could not reach the data" payload. `data_available=False` is NOT the same
    claim as "your weight has not moved"...

    Built by a factory rather than held as a module constant so each failure gets a fresh object
    and no caller can mutate the placeholder the next one receives (`safe_tool`'s contract).
    """
    return BodyWeightTrendResponse(data_available=False, trend=None)
```
Follow this shape for `_degraded_switch()`, but per RESEARCH.md Pattern 6, the write tool's
degraded status is `UNKNOWN` (never `NOT_APPLIED`) — copy RESEARCH.md's `_degraded_switch` code
block verbatim as the template; the `body.py` pattern supplies the "factory not module constant"
discipline and docstring convention, RESEARCH.md's block supplies the three-state-specific content.

**Tool function pattern** (`body.py` lines 64-74, adapted for a write tool):
```python
@safe_tool(degraded=_degraded_trend)
async def fitness_get_body_weight_trend(ctx: Context[AppContext]) -> BodyWeightTrendResponse:
    """..."""
    user_id = resolve_user_id(ctx)
    async with read_only_session(ctx) as session:
        trend = await get_body_weight_trend(session, user_id=user_id)
    return BodyWeightTrendResponse(data_available=True, trend=trend)
```
`fitness_switch_training_program` keeps the `@safe_tool(degraded=...)` decorator and the
`user_id = resolve_user_id(ctx)` opening line unchanged from this pattern. It diverges after that:
`async with writable_session(ctx) as session:` (not `read_only_session`), branches on whether
`confirmation_token` is `None`/invalid (WARN branch: call `issue_switch_token`, `session.commit()`
covering the token INSERT, return with `confirmation_token`/`expires_at` populated) vs valid
(CONFIRM branch: `consume_switch_token` → `close_period_and_open_new` → build response → **the
single `session.commit()` is the LAST statement in the function body**, per PITFALLS #15 and
RESEARCH.md Pattern 1's diagram step 6).

---

### `backend/migrations/versions/0006_user_program_history.py` (migration, batch DDL + seed)

**Analog:** `backend/migrations/versions/0005_health_daily_metrics.py` (table/FK/index shape),
`backend/migrations/versions/0002_seed_default_user.py` (seed-via-migration idiom)

**Revision header pattern** (`0005` lines 1-28):
```python
"""health daily metrics: day-grained Apple Health activity and nutrition

Generated by ``alembic revision --autogenerate`` and hand-reviewed.

One table, and only one (D-02): ...

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-02
"""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
```
`0006_user_program_history.py` follows this exactly: `revision = "0006"`, `down_revision =
"0005"` (confirmed: `0005` is the current head — `ls backend/migrations/versions/` shows
0001-0005, no 0006 yet).

**Table + FK + named-constraint pattern** (`0005` lines 32-82):
```python
op.create_table(
    "health_daily_metrics",
    sa.Column("id", sa.UUID(), nullable=False),
    sa.Column("user_id", sa.UUID(), nullable=False),
    ...
    sa.ForeignKeyConstraint(
        ["user_id"], ["users.id"],
        name=op.f("fk_health_daily_metrics_user_id_users"), ondelete="CASCADE",
    ),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_health_daily_metrics")),
    sa.UniqueConstraint(..., name=op.f("uq_health_daily_metrics_...")),
)
op.create_index(op.f("ix_health_daily_metrics_..."), "health_daily_metrics", [...], unique=False)
```
Use `op.f(...)` for every constraint/index name — matches `db/base.py`'s `NAMING_CONVENTION` and
keeps autogenerate-compatible naming even though this migration is (per RESEARCH.md) partly
hand-written. `user_program_history` and `program_switch_tokens` both follow this table shape.

**Partial unique index** (RESEARCH.md's own verified-pattern block — MEDIUM confidence, not yet
exercised in this repo, use exactly as written):
```python
op.create_index(
    "uq_user_program_history_one_open_period",
    "user_program_history",
    ["user_id"],
    unique=True,
    postgresql_where=sa.text("ended_on IS NULL"),
)
```

**Downgrade-is-exact-reverse pattern** (`0005` lines 91-98):
```python
def downgrade() -> None:
    # Exact reverse of `upgrade()`. `test_migrations_round_trip` asserts `downgrade base` leaves
    # ONLY `alembic_version`, so an index or table left behind here fails the suite.
    op.drop_index(op.f("ix_health_daily_metrics_..."), table_name="health_daily_metrics")
    op.drop_table("health_daily_metrics")
```
`0006`'s downgrade must drop both new tables and the partial index, in reverse dependency order
(drop `program_switch_tokens` before `user_program_history`, since it FKs to it).

**Seed-insert-in-migration idiom** (`0002` lines 36-47, `sa.table()` NOT the ORM model):
```python
def upgrade() -> None:
    users = sa.table(
        "users",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("timezone", sa.String),
    )
    op.bulk_insert(users, [{"id": DEFAULT_USER_ID, "timezone": DEFAULT_TIMEZONE}])
```
D-08's seed row differs from `0002`'s in one load-bearing way: `0002` seeds a FIXED, hardcoded
value; D-08 requires the seed to be DERIVED from live synced data (`MIN(w.start_time)`), which
`op.bulk_insert` with a Python literal cannot express. Use RESEARCH.md's `op.execute(sa.text("""
INSERT INTO user_program_history (...) SELECT ... FROM users u JOIN workouts w ...
GROUP BY u.id, u.timezone"""))` form instead — a raw `INSERT...SELECT`, not `op.bulk_insert`. This
is the ONE place in this phase's migration where the pattern must diverge from `0002`'s literal
idiom, and it should be commented as such (a planner/reviewer scanning past this migration should
not mistake the divergence for an oversight). Also resolve RESEARCH.md's Open Question #1 (empty
`workouts` table → zero seed rows) explicitly in the migration or its plan task.

---

### `backend/app/analytics/recomposition.py` (MODIFIED — service, transform)

**Analog:** itself. This is an in-place extension of the existing table-driven style; no external
file supplies a better analog than the module's own current shape.

**Constant-block pattern to replicate x3** (current file, lines 66-97):
```python
WEIGHT_GAIN_TOO_FAST_PERCENT_PER_WEEK = Decimal("0.25")
WEIGHT_LOSS_TOO_FAST_PERCENT_PER_WEEK = Decimal("-1.00")
WEIGHT_STABLE_BAND_PERCENT_PER_WEEK = Decimal("0.10")
```
D-04 requires these become per-program (three explicit tables, not one parametrized abstraction).
RESEARCH.md's Pattern 3 code block (`_THRESHOLDS: Mapping[TrainingProgram, "_ProgramThresholds"]
= MappingProxyType({...})`) is the concrete template — use it, adding whichever extra threshold
fields D-02's Cut ladder needs (`on_target_loss_far`/`on_target_loss_near` are already sketched
there).

**`_WeightBucket` / `_MATRIX_ROWS` / `_LABEL_MATRIX` pattern to replicate x3** (current file,
lines 153-274): the existing `zip(_SIGNAL_ORDER, statuses, strict=True)` construction (line 271)
MUST be preserved per-program — three separate `MappingProxyType` tables keyed on `(bucket,
signal)`, not one table keyed on `(program, bucket, signal)`. D-04 is explicit that a missing
branch must fail as a load-time `ImportError` PER PROGRAM.

**`classify_recomposition` signature change**: current signature (lines 277-286) is
`classify_recomposition(*, rate_percent_per_week, signal)`. Must gain a `program:
TrainingProgram` keyword-only parameter that selects which of the three `_LABEL_MATRIX_BY_PROGRAM`
tables and `_weight_bucket`-threshold-set to use — follow the existing keyword-only, no-default
style (`ProgramSwitchToken`'s `user_id` precedent throughout this codebase — ASVS V4 convention).

**`get_recomposition_status` docstring convention** (lines 289-299): "Session positional,
`user_id` keyword-only with no default... The caller owns the transaction; nothing here writes."
— preserve this framing when documenting the new `get_active_period`/`get_periods_overlapping`
reads this function gains (D-10's straddle check).

---

### `backend/app/analytics/schemas.py` (MODIFIED — model, transform)

**Analog:** itself — extend `RecompositionResult` (lines 676-697) following the "echo the inputs
that produced this result as fields" convention `PlateauResult` already establishes.

**Field-echoing convention** (`PlateauResult` docstring, lines 344-368, e.g.):
```
PROG-03's requirement text demands the window and threshold be returned ALONGSIDE the result,
so all six are fields.
```
D-10's straddle caveat (switch date + prior program name) and the active-program field should
follow this exact discipline: add them as REQUIRED fields on `RecompositionResult` (not optional-
by-omission — the module's stated convention per CONTEXT.md's "code_context" section), e.g.
`active_program: TrainingProgram` (required, always populated) and something like
`program_switch_caveat: str | None` (populated only when D-10's straddle condition is true —
follow `ExerciseTrend.rate_percent_per_week`'s "None exactly when X" documentation convention,
line 326, for whichever nullable field is chosen).

**`TrainingProgram` StrEnum placement**: per RESEARCH.md's Assumption A2 and CONTEXT.md's
"Claude's discretion" note, place it in `app/analytics/schemas.py` following `RecompositionStatus`
(lines 211-226) or `BodyMeasurementMetric`'s (lines 568-585) StrEnum conventions — a short
docstring naming the requirement id, and members as lowercase string values matching the DB
`program` column's stored strings exactly (`"lean_bulk"`, `"cut"`, `"recomp"`), mirroring
`BodyMeasurementMetric`'s "value IS the exact column name" discipline (line 571) adapted to "value
IS the exact stored string".

---

### `backend/app/mcp/server.py` (MODIFIED — route/registration)

**Analog:** itself — this is a structural addition after the existing `_TOOLS` loop, not a new
pattern.

**Existing `READ_ONLY` annotation object + loop** (current file, lines 131-146, 161-222):
```python
READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False,
)
mcp.add_tool(fitness_ping, name="fitness_ping", description="...", annotations=READ_ONLY)
_TOOLS: tuple[tuple[Callable[..., Any], str], ...] = (...)
for _fn, _description in _TOOLS:
    mcp.add_tool(_fn, name=_fn.__name__, description=_description, annotations=READ_ONLY)
```
Add a `WRITE_TOOL = ToolAnnotations(...)` object (RESEARCH.md Pattern 4's exact block:
`read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False`)
immediately after the `for _fn, _description in _TOOLS:` loop (current line 222), then a single
`mcp.add_tool(fitness_switch_training_program, name=..., description=..., annotations=WRITE_TOOL)`
call — OUTSIDE the loop and OUTSIDE the `_TOOLS` tuple, per D-04/PITFALLS #14's explicit
requirement. Import `fitness_switch_training_program` alongside the other tool imports (current
lines 41-59), following the existing `from app.mcp.tools.<module> import <fn>` grouping style.

---

### `backend/app/mcp/tools/_common.py` (MODIFIED — utility)

**Analog:** itself — `writable_session` is an explicit sibling to `read_only_session`.

**`read_only_session` to mirror-and-diverge-from** (current file, lines 123-154):
```python
@asynccontextmanager
async def read_only_session(ctx: Context[AppContext]) -> AsyncIterator[AsyncSession]:
    """..."""
    sessionmaker = ctx.request_context.lifespan_context.sessionmaker
    async with sessionmaker() as session:
        await session.connection(execution_options={"postgresql_readonly": True})
        try:
            yield session
        finally:
            await session.rollback()
```
`writable_session` (RESEARCH.md Pattern 5, use verbatim) omits the `postgresql_readonly`
execution option and the unconditional `finally: rollback()` — the caller must commit explicitly,
and per PITFALLS #15 that commit must be the LAST statement the tool body executes. Place it
directly below `read_only_session` in the file, and explicitly do NOT modify `read_only_session`
itself (CONTEXT.md's explicit instruction, restated in RESEARCH.md's Anti-Patterns section).

**`local_today` reuse** (current file, lines 198-206): D-09 requires the switch always starts
today — call the EXISTING `local_today(session, user_id=...)` from inside
`fitness_switch_training_program`, do not write new date logic.

---

### `backend/app/mcp/tools/schemas.py` (MODIFIED — model, transform)

**Analog:** itself — extend following `RecompositionResponse`/`WorkoutDetailResponse`'s
conventions.

**"Compose, never restate" + `data_available: bool` conventions** (module docstring, lines 9-17):
these two rules apply to `ProgramSwitchResponse` exactly as to every other response model in this
file. Use RESEARCH.md's Pattern 6 code block for `ProgramSwitchStatus` (StrEnum:
`APPLIED`/`NOT_APPLIED`/`UNKNOWN`) and `ProgramSwitchResponse` verbatim as the template; it already
follows this file's field-naming and nullability conventions (`data_available: bool` first,
mutually-exclusive-by-branch nullable fields documented the way `WorkoutDetailResponse.found`
(lines 279-288) pairs with its nullable `workout` field).

**`_McpModel` base class** (lines 59-74): `ProgramSwitchResponse(_McpModel)` — same
`hide_input_in_errors=True, extra="forbid", frozen=True` config as every other model in this
file, no new base class needed.

---

## Shared Patterns

### Authentication
**Source:** `backend/app/mcp/server.py` lines 89-118 (`AuthSettings`, `required_scopes=None`)
**Apply to:** No change needed — D-12 explicitly keeps `required_scopes=None` unchanged. Every
call to the new write tool is authenticated exactly like every read tool via the same
`token_verifier`; the confirmation token is a SEPARATE, additional authorization artifact, not a
second auth mechanism.

### Error Handling / Exception Guard
**Source:** `backend/app/mcp/tools/_common.py` lines 254-290 (`safe_tool`)
**Apply to:** `fitness_switch_training_program` — wrap with `@safe_tool(degraded=_degraded_switch)`
exactly like every existing tool. The degraded factory must return `ProgramSwitchStatus.UNKNOWN`
(never `NOT_APPLIED`), per RESEARCH.md Pattern 6 and PITFALLS #15 — an exception means "we do not
know if the commit landed", which is a different fact from "we know it did not."

### Session Acquisition
**Source:** `backend/app/mcp/tools/_common.py` lines 123-154 (`read_only_session`)
**Apply to:** Every OTHER tool keeps `read_only_session` unchanged. `fitness_switch_training_program`
is the ONE caller of the new `writable_session` sibling — this narrowing, not weakening, is the
core of PITFALLS #14's design.

### Response Contract (`data_available`, echo-the-inputs, no union returns)
**Source:** `backend/app/mcp/tools/schemas.py` module docstring lines 1-29
**Apply to:** `ProgramSwitchResponse` and any modified `RecompositionResponse`/
`TrainingSummaryResponse` fields touched by D-10's straddle caveat — every response model in this
phase must carry `data_available: bool`, compose (not restate) analytics results, and never use a
union return annotation.

### Repository Never-Commits / Caller-Owns-Transaction
**Source:** `backend/app/db/repositories/sync_state.py` module docstring lines 6-9
**Apply to:** Every function in the new `backend/app/db/repositories/programs.py` — no
`session.commit()` anywhere in that module; the MCP tool layer (`programs.py`'s tool module) is
the sole committer, and only as its last statement.

### Guard-Test Allowlist-by-Name, Not Relaxation
**Source:** `backend/tests/test_mcp_isolation.py` line 71 (`_NOT_TOOL_MODULES = frozenset({...})`)
and lines 68-71's comment
**Apply to:** The new `_WRITE_ALLOWLIST = frozenset({"programs.py"})` in the same file (RESEARCH.md's
exact block) — same "explicit named exception, self-asserted to be exactly one" discipline this
file already uses for `ping.py`'s raw-SQL exemption (`test_mcp_uses_no_raw_sql_text`, line 158's
`path.name != "ping.py"` check) and `_NOT_TOOL_MODULES`.

### Migration Structure (`revision`/`down_revision`, `op.f()` naming, exact-reverse downgrade)
**Source:** `backend/migrations/versions/0005_health_daily_metrics.py` in full
**Apply to:** `0006_user_program_history.py` — see the dedicated Pattern Assignment section above.

## No Analog Found

None. Every file in this phase has at least a role-match analog in the existing codebase. The
write-tool session/token mechanics (`writable_session`, `consume_switch_token`'s atomic
`UPDATE...RETURNING`) have no PRIOR IMPLEMENTATION in this repo to copy verbatim — this is
expected, since PITFALLS #13-16 exist precisely because this is the first write tool — but
RESEARCH.md's Patterns 1-6 supply fully-worked, repo-convention-consistent code blocks for exactly
this gap, verified against the installed `mcp==2.0.0` SDK source. Treat RESEARCH.md's Code
Examples section as the analog of record for these specific mechanics; every other file in this
phase should copy from the same-repo analogs listed above.

## Metadata

**Analog search scope:** `backend/app/db/models/`, `backend/app/db/repositories/`,
`backend/app/mcp/`, `backend/app/analytics/`, `backend/migrations/versions/`, `backend/tests/`
**Files read in full:** `user.py`, `sync_state.py` (model), `body.py` (model), `sync_state.py`
(repository), `workouts.py` (repository), `_common.py`, `server.py`, `body.py` (MCP tool),
`recomposition.py`, `schemas.py` (analytics), `schemas.py` (MCP tools), `test_mcp_isolation.py`,
`test_mcp_tool_schemas.py`, `0002_seed_default_user.py`, `0005_health_daily_metrics.py`,
`db/base.py`, `mcp/context.py`, plus `conftest.py`'s `GoldenBuilder` class header and
`test_analytics_recomposition.py`'s test-function inventory
**Pattern extraction date:** 2026-09-04
