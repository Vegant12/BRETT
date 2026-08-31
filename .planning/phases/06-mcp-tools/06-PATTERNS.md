# Phase 6: MCP Tools - Pattern Map

**Mapped:** 2026-08-31
**Files analyzed:** 18 (12 new source, 2 modified source, 4 new test files, 2 modified test files)
**Analogs found:** 17 / 18

Every new file in this phase has an in-repo analog. The one file with no direct analog
(`backend/app/mcp/tools/_common.py`) is a *composition* of four existing patterns, each of which
has an exact source cited below. **This phase is mostly a list of imports** — RESEARCH.md's
own conclusion, and the codebase confirms it.

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `backend/app/mcp/server.py` (MODIFY) | config / tool registry | request-response | itself, lines 66-71 | exact (self) |
| `backend/app/mcp/tools/_common.py` (NEW) | utility / cross-cutting | request-response | composite: `analytics/rollup.py:134-152`, `tools/ping.py:34-44`, `db/repositories/sync_state.py:88-98` | partial (composed) |
| `backend/app/mcp/tools/schemas.py` (NEW) | model / schema | transform | `app/analytics/schemas.py:40-54, 87-103` | exact |
| `backend/app/mcp/tools/workouts.py` (NEW) | controller (tool adapter) | request-response | `app/mcp/tools/ping.py` | role-match |
| `backend/app/mcp/tools/volume.py` (NEW) | controller (tool adapter) | request-response | `app/mcp/tools/ping.py` | role-match |
| `backend/app/mcp/tools/progression.py` (NEW) | controller (tool adapter) | request-response | `app/mcp/tools/ping.py` | role-match |
| `backend/app/mcp/tools/records.py` (NEW) | controller (tool adapter) | request-response | `app/mcp/tools/ping.py` | role-match |
| `backend/app/mcp/tools/comparison.py` (NEW) | controller (tool adapter) | request-response | `app/mcp/tools/ping.py` | role-match |
| `backend/app/mcp/tools/body.py` (NEW) | controller (tool adapter) | request-response | `app/mcp/tools/ping.py` | role-match |
| `backend/app/mcp/tools/summary.py` (NEW) | controller (tool adapter, composing) | request-response | `app/analytics/recomposition.py:289-300` (composes other analytics) + `ping.py` | role-match |
| `backend/app/db/repositories/workouts.py` (NEW) | repository | CRUD (read-only) | `app/db/repositories/sync_state.py` + `app/analytics/rollup.py:193+` | exact |
| `backend/tests/test_mcp_tools.py` (MODIFY) | test (integration) | request-response | itself, lines 37-143 | exact (self) |
| `backend/tests/test_mcp_tool_schemas.py` (NEW) | test (unit, fast) | transform | `backend/tests/test_mcp_tools.py:124-143` | role-match |
| `backend/tests/test_mcp_tool_budget.py` (NEW) | test (unit + integration) | transform | `backend/tests/test_mcp_tools.py:37-53` | role-match |
| `backend/tests/test_mcp_isolation.py` (NEW) | test (static source walk) | batch | `backend/tests/test_analytics_isolation.py` | exact |
| `backend/tests/test_mcp_readonly.py` (NEW) | test (integration) | request-response | `backend/tests/test_mcp_tools.py:56-90` | role-match |
| `backend/tests/test_mcp_window.py` (NEW) | test (unit, fast) | transform | `backend/tests/test_time.py` + `test_analytics_rollup.py` | role-match |
| `backend/tests/conftest.py` (MODIFY — `worst_case_history`) | test fixture | batch | `conftest.py:306-545` (`GoldenBuilder` / `golden_workout`) | exact (self) |

---

## Pattern Assignments

### `backend/app/mcp/tools/{volume,progression,records,comparison,body,summary,workouts}.py` (controller, request-response)

**Analog:** `backend/app/mcp/tools/ping.py` — the ONLY existing tool. Every rule below is
already stated or demonstrated there.

**Module docstring pattern** (`ping.py:1-12`) — this repo writes long "why" docstrings, and the
MCP `ctx` annotation rule is recorded in one:

```python
"""Database connectivity tool (D-08, MCP-01).

Throwaway in scope, permanent in shape: Phase 6 replaces this tool but not the
path it proves. ...

``ctx`` MUST be annotated ``Context[AppContext]``. With no annotation the SDK
exposes it to the model as a required string argument (``"properties": {"ctx":
{"type": "string"}}``) and every call fails schema validation.
"""
```

Copy this convention: each new tool module opens with a docstring naming its requirement IDs
(`MCP-02, MCP-03, MCP-05, MCP-06`) and its decision IDs (`D-01`..`D-13`), in the same
`(REQ-ID, D-NN)` parenthetical style.

**Imports pattern** (`ping.py:14-21`):

```python
import structlog
from mcp.server.mcpserver import Context
from pydantic import BaseModel
from sqlalchemy import text

from app.mcp.context import AppContext

log = structlog.get_logger()
```

Note for new tools: **drop `from sqlalchemy import text`.** `test_analytics_isolation.py:44`
bans `text(` in `app/analytics/`, and `test_mcp_isolation.py` will extend the same guard to
`app/mcp/`. `ping.py` is the one sanctioned `text()` site (a literal `SELECT 1`); a new tool
that imports it will trip the new guard.

**Tool function signature + return-a-BaseModel pattern** (`ping.py:24-32`):

```python
class PingResult(BaseModel):
    """Returning a BaseModel auto-populates outputSchema and structuredContent."""

    status: str
    database: str


async def fitness_ping(ctx: Context[AppContext]) -> PingResult:
    """Round-trip the database through the lifespan-wired session factory."""
```

**Session-acquisition pattern** (`ping.py:35-37`) — the exact three lines
`read_only_session()` in `_common.py` must wrap:

```python
sessionmaker = ctx.request_context.lifespan_context.sessionmaker
async with sessionmaker() as session:
    await session.execute(text("SELECT 1"))
```

**Error handling pattern — copy verbatim into every tool** (`ping.py:38-44`). This is the
MCP-06 control and RESEARCH.md's Pattern 8 is a hoisted version of exactly this:

```python
    except Exception:  # noqa: BLE001 - any failure to reach the DB must degrade, not error
        # Mirrors health.py: the detail goes to the log (which runs through the
        # redaction pipeline); the caller gets only the coarse state. Connection
        # errors carry the DSN, host, and driver internals (T-02-09, FOUND-05).
        log.exception("mcp_ping_db_check_failed")
        database = "error"
    return PingResult(status="ok", database=database)
```

Three properties of this excerpt that the planner must preserve in `@safe_tool`:
1. `except Exception:` with the `# noqa: BLE001` and a comment justifying it — Ruff's `BLE`
   rule is on, so the noqa is required, and this repo always explains a noqa inline.
2. `log.exception(<snake_case_event_name>)` with **no** exception interpolated into any string.
3. The function still returns a **valid, schema-conforming payload** — never re-raises.

**Analytics call signature to adapt to** (`app/analytics/volume.py:137-143`) — session
positional, everything else keyword-only, `user_id` with no default (ASVS V4):

```python
async def get_weekly_volume(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    start_day: dt.date,
    end_day: dt.date,
) -> WeeklyVolumeResult:
```

Verified signatures every tool composes (read from source, not from RESEARCH.md):

| Analytics function | Source | Keyword params after `session` |
|---|---|---|
| `get_weekly_volume` | `analytics/volume.py:137` | `user_id, start_day, end_day` |
| `get_muscle_group_volume` | `analytics/volume.py:204` | `user_id, start_day, end_day, weights=None` |
| `get_training_frequency` | `analytics/frequency.py:106` | `user_id, start_day, end_day, weights=None` |
| `get_exercise_progression` | `analytics/progression.py:226` | `user_id, exercise_template_external_id, start_day, end_day` |
| `get_plateaus` | `analytics/progression.py:642` | `user_id, lookback_weeks=DEFAULT_PLATEAU_LOOKBACK_WEEKS, template_external_ids=None` |
| `get_personal_records` | `analytics/records.py:107` | `user_id, exercise_template_external_id, start_day, end_day` |
| `compare_periods` | `analytics/comparison.py:392` | `user_id, period_a_start, period_a_end, period_b_start, period_b_end, include_muscle_groups=False, weights=None` |
| `get_body_weight_trend` | `analytics/bodyweight.py:178` | `user_id` only |
| `get_recomposition_status` | `analytics/recomposition.py:289` | `user_id` only |

---

### `backend/app/mcp/tools/_common.py` (utility, cross-cutting)

**No single analog.** Composed from four sources, each cited below.

**(a) `window_from_weeks` — copy from `app/analytics/rollup.py:134-152` (`resolve_window`).**
This is the exact timezone-read + `ValueError("unknown user")` shape RESEARCH.md sketches:

```python
async def resolve_window(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    start_day: dt.date,
    end_day: dt.date,
    snap_to_weeks: bool,
) -> AnalyticsWindow:
    """Read the user's timezone (FOUND-03) and build the window.

    The timezone comes from ``users.timezone`` and is never a module constant, an environment
    variable or a caller default: a hardcoded default would let a wrong-timezone bug pass every
    test, and at UTC+7 every instant between 17:00Z and 24:00Z belongs to the NEXT local day --
    which is every morning workout.
    """
    tz = await session.scalar(select(User.timezone).where(User.id == user_id))
    if tz is None:
        raise ValueError("unknown user")
    return build_window(start_day=start_day, end_day=end_day, tz=tz, snap_to_weeks=snap_to_weeks)
```

Copy the `session.scalar(select(User.timezone).where(User.id == user_id))` line and the
`if tz is None: raise ValueError("unknown user")` guard verbatim. The date helpers to call are
in `app/core/time.py`: `utc_now()` (line 21), `local_day(ts, tz)` (line 62),
`local_week_start(ts, tz)` (line 67), `snap_local_week_range(start, end)` (line 108).
`local_week_start` is what Pitfall 6's Monday-anchored `start_day` should be built from.

**Do not add a helper to `app/core/time.py`** — 05-PATTERNS.md lists it under "verify, do not
touch", and every function there is pure/synchronous with `tz` as a parameter;
`window_from_weeks` needs an `AsyncSession`.

**(b) Validation-guard style — `app/analytics/rollup.py:98-113` (`build_window`):**

```python
    if end_day < start_day:
        raise ValueError("end_day precedes start_day")
    if (end_day - start_day).days + 1 > MAX_ANALYTICS_WINDOW_DAYS:
        raise ValueError("requested analytics window exceeds the maximum span")
```

Note the documented rule at `rollup.py:105-109`: *"Every message names the failure and carries
no date value and no user id, because it will be logged."* That rule is doubly binding in
`app/mcp/` — Pitfall 3 proves the message can reach Claude, not just the log.

**(c) Bounded-constant + one-place-per-rule style — `app/analytics/rollup.py:61-75`:**

```python
WARMUP_SET_TYPE = "warmup"
...
# ONE constant, checked in ONE place (`_hard_set_predicates`), so flipping this decision later is
# a one-line change. Do NOT scatter a modality list through the query or the fold: 24 live sets
# are affected and the flip must not require finding every site.
COUNT_DURATION_ONLY_SETS = True

# ASVS V5 / MCP-03: reject an implausible range before any row is materialised, so a Phase 6 tool
# cannot ask for two centuries of week buckets. ~5 years, which comfortably covers the 17 months
# of real history and any "all time" question a coach would ask.
MAX_ANALYTICS_WINDOW_DAYS = 1830
```

`MAX_WEEKS = 52`, `MAX_RECENT_WORKOUTS`, `MAX_CANDIDATES` and `HEVY_PROVIDER` in `_common.py`
follow this shape: one constant, one comment naming the requirement ID and the concrete
consequence of the number.

**(d) Query style for `find_templates_by_title` — `app/db/repositories/sync_state.py:88-98`:**

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

Note: session positional, everything else keyword-only, `user_id` first in the WHERE list,
comma-separated predicates (never `and_()` at the top level), bound parameters only.
The provider constant already exists as `sync_state.py:21 PROVIDER_HEVY = "hevy"` — **import
it rather than declaring a second `HEVY_PROVIDER`** (RESEARCH.md's sketch declares a duplicate;
the repo already has this constant and `app/mcp/` may import `app/db/`).

**(e) `resolve_user_id` — the `DEFAULT_USER_ID` constant currently lives at
`backend/app/cli.py:45`:**

```python
DEFAULT_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
```

Third copies exist at `backend/migrations/versions/0002_seed_default_user.py:28` (deliberate —
migrations must not import app code) and `backend/tests/conftest.py:62` (deliberate — a test
asserting against a value it imports proves nothing). Promote the **application-side** copy to
a shared module and import it in both `cli.py` and `_common.py`. `app/config.py` is the
placement analog: it already holds module-level constants beside `Settings`
(`config.py:22 _SSL_REQUIRING_MODES`, `config.py:24 _SECRET_FIELDS`).

---

### `backend/app/mcp/tools/schemas.py` (model, transform)

**Analog:** `backend/app/analytics/schemas.py`

**Base-model pattern** (`analytics/schemas.py:40-54`) — `_McpModel` must mirror this exactly:

```python
class _AnalyticsModel(BaseModel):
    """Shared config for every analytics return type.

    ``hide_input_in_errors`` for the same reason ``hevy/schemas.py`` sets it: a ValidationError
    would otherwise render ``input_value=...`` -- weekly tonnage, workout counts, body-composition
    adjacent numbers -- into a message that could reach a log line (FOUND-05).

    Extra fields are FORBIDDEN here, not ignored -- the opposite of the wire models: these are
    internal domain types, not a mirror of somebody else's format. An unexpected field here is a
    bug in this repo, and it should fail loudly rather than be dropped. ``frozen=True`` because
    this is a read path -- a result object that a caller can mutate is a result object two
    callers will disagree about.
    """

    model_config = ConfigDict(hide_input_in_errors=True, extra="forbid", frozen=True)
```

**Result-model shape pattern** (`analytics/schemas.py:87-103`) — flat fields, `Decimal | None`
never `float`, one-line docstring stating the invariant:

```python
class WeeklyVolumeWeek(_AnalyticsModel):
    """One whole local Monday-start week of VOL-01 totals. Warm-up sets excluded from all of it."""

    week_start: dt.date
    sessions: int
    hard_sets: int
    total_reps: int | None
    tonnage_sets: int
    tonnage_kg: Decimal | None


class WeeklyVolumeResult(_AnalyticsModel):
    """VOL-01. ``weeks`` is ascending and GAP-FREE: a week with no training is a zero row."""

    weeks: list[WeeklyVolumeWeek]
    coverage: CoverageMetadata
    freshness: FreshnessMetadata
```

Every MCP response model carrying window-scoped data should end with the same
`coverage: CoverageMetadata` / `freshness: FreshnessMetadata` pair — built by
`app/analytics/metadata.py:164 build_coverage(session, *, user_id, utc_start, utc_end)` and
`app/analytics/metadata.py:137 build_freshness(session, *, user_id, resources, provider=PROVIDER_HEVY)`.

**MCP-06 field-selection rule to copy** (`analytics/metadata.py:155-159`) — the existing,
already-enforced deny-list for anything read off `sync_state`:

```python
        # ONLY the last-synced timestamp is read off the row. MCP-06: the row's stored error
        # text, its run status and its two resume cursors are internal bookkeeping that must
        # never reach anything Claude can read, and `format_sync_error` exists precisely to
        # bound that leak at the point it is written.
        # Forbidden here: last_error, status, cursor_page, cursor_timestamp -- operator CLI only.
```

**No `float`, ever** — `test_analytics_isolation.py:60` bans it statically in `app/analytics/`
and `test_mcp_isolation.py` should carry the same `_FLOAT_USE` regex into `app/mcp/`:

```python
_FLOAT_USE = re.compile(r"(?<![\w.])float\s*\(|:\s*float\b|->\s*float\b|\[\s*float\s*[],]")
```

---

### `backend/app/db/repositories/workouts.py` (repository, read-only CRUD)

**Analog:** `backend/app/db/repositories/sync_state.py` (placement + signature convention) and
`backend/app/analytics/rollup.py` (aggregate-query + hard-set-rule convention).

**Package contract** (`app/db/repositories/__init__.py`, the whole file):

```python
"""Query helpers that own no session and no engine -- callers pass both in."""
```

**Module docstring pattern** (`sync_state.py:1-9`):

```python
"""Read and advance per-resource sync bookkeeping (HEVY-09, D-08).

Provider-neutral on purpose: these helpers take `provider` and `resource` as arguments and
import nothing from `app.integrations`, so HEVY-05's boundary holds in both directions.

Every function takes an `AsyncSession` and never commits. The CALLER owns the transaction --
D-08 requires the checkpoint to commit in the SAME transaction as the page of rows it
describes, and a helper that committed on its own would make that impossible.
"""
```

**Imports pattern** (`sync_state.py:11-19`):

```python
import datetime as dt
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.sync_state import SyncState
```

For `workouts.py`: keep the first block, **drop `pg_insert`** — `test_mcp_isolation.py`'s
`_WRITE_IMPORT` guard bans write constructs, and a read-only repository has no use for one.

**Hard-set rule — import, do not re-derive** (`app/analytics/rollup.py:178-190`):

```python
def _hard_set_predicates() -> list[Any]:
    """Which sets count as hard sets. VOL-01 plus U-02, in one place.

    Returns predicates rather than a single expression so the caller composes them into the
    same WHERE list as the user and window filters -- keeping every predicate visible in one
    statement instead of buried in a nested boolean.
    """
    predicates: list[Any] = [WorkoutSet.set_type != WARMUP_SET_TYPE]
    if not COUNT_DURATION_ONLY_SETS:
        predicates.append(not_(and_(WorkoutSet.weight_kg.is_(None), WorkoutSet.reps.is_(None))))
    return predicates
```

**Boundary caveat the planner must resolve:** `_hard_set_predicates` is module-private in
`app/analytics/rollup.py`. `app/db/repositories/workouts.py` importing `app.analytics` would
invert the dependency arrow that `test_analytics_isolation.py:109-122` is built to protect
(it bans `app.analytics` → `app.mcp`, not `app/db` → `app.analytics`, but the spirit is a
one-way arrow). Two acceptable options: (1) promote `_hard_set_predicates` to public
`hard_set_predicates` in `rollup.py` and import it, or (2) put the query in
`app/mcp/tools/workouts.py` and import from `app.analytics.rollup` there. Option (1) matches
the existing "ONE constant, checked in ONE place" comment at `rollup.py:61-64` and is
recommended; RESEARCH.md A5 already flags the placement as LOW-risk either way.

**Columns available** (verified from `app/db/models/workout.py`):

| Model | Line | Fields the projection needs |
|---|---|---|
| `Workout` | 36 | `id`, `user_id`, `provider`, `external_id` (`String(64)`, line 56), `title` (line 59), `start_time`/`end_time` (`DateTime(timezone=True)`, lines 67-68) |
| `WorkoutExercise` | 93 | `workout_id`, `exercise_index`, `title`, `exercise_template_external_id`, `supersets_id` |
| `WorkoutSet` | 135 | `workout_exercise_id`, `set_index`, `set_type`, `weight_kg` (`Numeric(7,3)`), `reps`, `distance_meters`, `duration_seconds`, `rpe`, `custom_metric` |

D-12: key on `Workout.external_id` (line 56), never `Workout.id` (line 41).

---

### `backend/app/mcp/server.py` (config / tool registry, MODIFY)

**Analog:** itself.

**Existing registration to extend** (`server.py:66-71`):

```python
# D-08: one tool, and it does a real DB round-trip.
mcp.add_tool(
    fitness_ping,
    name="fitness_ping",
    description="Database connectivity check.",
)
```

**Import block to extend** (`server.py:30-37`):

```python
from mcp.server import MCPServer
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings

from app.config import get_settings
from app.mcp.auth import build_token_verifier
from app.mcp.context import mcp_lifespan
from app.mcp.tools.ping import fitness_ping
```

**Load-bearing ordering constraint — do not move the new `add_tool` calls below line 74**
(`server.py:73-83`). `streamable_http_app()` must remain the last statement:

```python
# MUST run at import time. See the module docstring.
mcp_app = mcp.streamable_http_app(
    streamable_http_path="/mcp",
    stateless_http=True,
    transport_security=TransportSecuritySettings(
        allowed_hosts=settings.mcp_allowed_hosts,
        allowed_origins=[],
    ),
)
```

Also note `server.py:60-62` — the scope decision was explicitly deferred to this phase:

```python
        # Scope design belongs with the real tool set in Phase 6. An empty
        # scope list is the least likely thing to break a first handshake.
        required_scopes=None,
```

CONTEXT.md puts auth out of scope for Phase 6, so `required_scopes=None` stays; the planner
should note the comment is now stale rather than act on it.

---

### `backend/tests/test_mcp_isolation.py` (test, static source walk)

**Analog:** `backend/tests/test_analytics_isolation.py` — copy this file's structure wholesale.

**Header pattern** (`test_analytics_isolation.py:1-22`) — states the boundary, the direction of
the arrow, and *why anchored regexes*:

```python
"""The `app/analytics/` boundary, asserted statically over committed source.

No container, no network, and deliberately no integration marker -- a boundary violation must
fail the FAST suite on the commit that introduces it, not after a deploy.
...
Every check is an ANCHORED REGEX or a CamelCase class identifier, never a bare substring.
`app/analytics/__init__.py` states these very rules in prose, so a substring check would fail on
the sentence documenting the boundary -- the trap already recorded at
`test_hevy_isolation.py:88-93`.
"""
```

**Path + regex block** (`test_analytics_isolation.py:24-51`) — the read-only guards
RESEARCH.md's sketch reuses are already written here, verbatim:

```python
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ANALYTICS = REPO_ROOT / "backend" / "app" / "analytics"

_RAW_SQL_TEXT = re.compile(r"(?<![\w.])(?:(?:sa|sqlalchemy)\.)?text\s*\(")

# Read-only in v1 (MCP-05 inherits this). `session_ids.add(...)` on a Python set is fine and
# deliberately not matched -- only session-bound mutations are.
_SESSION_WRITE = re.compile(r"\bsession\.(?:commit|flush|add|add_all)\s*\(")
_WRITE_IMPORT = re.compile(
    r"^\s*from\s+sqlalchemy\s+import\s+.*\b(?:insert|update|delete)\b", re.MULTILINE
)
```

Note `REPO_ROOT = parents[2]` — RESEARCH.md's sketch uses `parents[2]` then appends
`backend/app/mcp`, which matches. Use `parents[2] / "backend" / "app" / "mcp"`.

**The guard-on-the-guards test — MUST be copied** (`test_analytics_isolation.py:79-90`):

```python
def test_the_walk_actually_finds_files() -> None:
    """A guard on the guards: an empty walk would make every test below vacuously true.

    If `ANALYTICS` were ever wrong -- a moved package, a renamed directory -- `rglob` returns
    nothing and five boundary tests pass while checking nothing at all.
    """
    modules = _analytics_modules()

    assert len(modules) >= 6, f"the walk found only {len(modules)} modules under {ANALYTICS}"
```

The Phase 6 floor: `app/mcp/` will hold `__init__`, `auth`, `context`, `server`,
`tools/__init__`, `tools/_common`, `tools/schemas`, `tools/ping` + 7 tool modules = **>= 15**.

**Module-walk helper** (`test_analytics_isolation.py:70-76`):

```python
def _analytics_modules() -> list[Path]:
    """Every committed module under `app/analytics/`.

    `rglob` rather than a hand-maintained list: a new analytics submodule must be covered by
    these boundaries the moment it exists, without anyone remembering to add it here.
    """
    return sorted(ANALYTICS.rglob("*.py"))
```

**Assertion-message style** (`test_analytics_isolation.py:171-180`) — every assertion carries
the requirement ID, the offending path relative to the repo root, and the *reason*:

```python
    for path in _analytics_modules():
        source = path.read_text(encoding="utf-8")
        assert not _SESSION_WRITE.search(source), (
            f"MCP-05 violated: {path.relative_to(REPO_ROOT)} mutates the session. Analytics "
            f"reads; the caller owns the transaction"
        )
```

**Carry-over caveat:** `ping.py:17` imports `text` and `ping.py:37` calls `text("SELECT 1")`.
If `_RAW_SQL_TEXT` is applied to `app/mcp/`, `ping.py` must be explicitly exempted (the
`test_epley_is_computed_only_in_estimates` pattern at `test_analytics_isolation.py:205-224`
shows the established one-module-exemption idiom: `if path.name != "estimates.py"`).

---

### `backend/tests/test_mcp_tools.py` (test, integration, MODIFY/EXTEND)

**Analog:** itself. All four existing tests are the template for the new per-tool tests.

**In-memory client + lazy import pattern** (`test_mcp_tools.py:37-53`) — note the import is
*inside* the test function (Pitfall 8) and the `client: TestClient` fixture is taken even
though no HTTP request is made (Pitfall 7):

```python
@pytest.mark.integration
async def test_ping_hits_database(client: TestClient) -> None:
    """Live container -> a real ``SELECT 1`` and a structured result.

    ``structured_content`` rather than the text block: returning a
    ``BaseModel`` is what populates it, and asserting on it proves the
    output-schema path Phase 6's analytics tools all depend on.
    """
    from mcp import Client

    from app.mcp.server import mcp

    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool("fitness_ping", {})

    assert result.is_error is False
    assert result.structured_content == {"status": "ok", "database": "connected"}
```

**The MCP-06 leak test to parametrize over all 12 tools** (`test_mcp_tools.py:93-121`) — the
dead-DB URL and the leak-token list are already written:

```python
DEAD_DB_URL = "postgresql+asyncpg://nobody:nopass@127.0.0.1:1/nodb"
...
    app = client.app
    original = app.state.sessionmaker
    dead = create_async_engine(DEAD_DB_URL, connect_args={"timeout": 1}, pool_pre_ping=False)
    app.state.sessionmaker = async_sessionmaker(dead, expire_on_commit=False, autoflush=False)
    try:
        async with Client(mcp) as mcp_client:
            result = await mcp_client.call_tool("fitness_ping", {})

        rendered = f"{result.structured_content}{result.content}"
        for leak in ("nobody", "nopass", "127.0.0.1", "nodb", "asyncpg", "Traceback"):
            assert leak not in rendered, (
                f"FOUND-05/T-02-09 violated: {leak!r} leaked into the tool result"
            )
    finally:
        app.state.sessionmaker = original
        dead.sync_engine.dispose()
```

Copy the swap-before-`Client(mcp)` ordering and the `finally` restore exactly — the docstring
at `test_mcp_tools.py:59-70` explains why swapping after entry proves nothing, and why the
engine is restored rather than disposed.

**Output-schema assertion pattern** (`test_mcp_tools.py:124-143`) — the template for
`test_mcp_tool_schemas.py::test_decorated_tools_still_publish_schemas` (RESEARCH.md A1):

```python
    async with Client(mcp) as mcp_client:
        tools = (await mcp_client.list_tools()).tools

    output_schema = tools[0].model_dump(by_alias=True)["outputSchema"]

    assert set(output_schema["required"]) == {"status", "database"}
    assert set(output_schema["properties"]) == {"status", "database"}
```

`tools[0]` works today because there is one tool. With 13 registered, index by name:
`{t.name: t for t in tools}`. The existing test must be updated in the same commit that
registers tool #2, or it starts asserting against an arbitrary tool.

---

### `backend/tests/conftest.py` — `worst_case_history` fixture (MODIFY)

**Analog:** `GoldenBuilder` (`conftest.py:306`) + `golden_workout` (`conftest.py:532-545`).

**Fixture contract to copy** (`conftest.py:532-545`):

```python
@pytest_asyncio.fixture
async def golden_workout(session: AsyncSession) -> AsyncIterator[GoldenBuilder]:
    """A builder whose every write is rolled back, pass or fail.

    Rollback rather than a compensating DELETE for two reasons, both verified in
    this suite: it survives an assertion failure mid-test, and
    ``test_migrations.py`` asserts ``count(*) == 1`` on ``users`` from a SEPARATE
    connection, which cannot see uncommitted rows at all.
    """
    try:
        yield GoldenBuilder(session)
    finally:
        await session.rollback()
```

**Builder API available** (verified signatures):

| Method | Line | Signature |
|---|---|---|
| `user` | 322 | `*, user_id: uuid.UUID, timezone: str = "Asia/Jakarta"` |
| `template` | 338 | `*, external_id, exercise_type="weight_reps", title=None, muscles=(), user_id=DEFAULT_USER_ID` |
| `body_measurement` | 388 | — |
| `override` | 427 | — |
| `workout` | 453 | `*, start_time: dt.datetime, exercises: Sequence[GoldenExercise], user_id=DEFAULT_USER_ID, title="Fixture Workout", external_id=None, duration_minutes=60` |

Data classes: `GoldenSet` (`conftest.py:275`, fields `set_type="normal"`, `weight_kg`, `reps`,
`distance_meters`, `duration_seconds`, `rpe`) and `GoldenExercise` (`conftest.py:297`, fields
`template_external_id`, `sets`, `supersets_id`, `title`).

**Load-bearing constraint** (`conftest.py:469-470`): `builder.workout()` rejects a naive
`start_time` — every fixture timestamp must be timezone-aware UTC.

**Flush-not-commit contract** (`conftest.py:306-317` docstring): the builder writes with
explicit Core statements and **flushes**; the tool under test must receive the SAME
`AsyncSession`. This is a direct conflict with `read_only_session()`, which opens its own
session from `ctx.request_context.lifespan_context.sessionmaker`. **The planner must resolve
this:** an MCP tool driven through `Client(mcp)` opens a different session and will not see
flushed-but-uncommitted rows. Options: commit the `worst_case_history` fixture and clean up via
the `restore_schema` fixture (`conftest.py:225`), or build the budget fixtures at the model
layer (RESEARCH.md's own note that `test_mcp_tool_budget.py` can be "fast, no container: build
models directly").

---

## Shared Patterns

### Read-only session (MCP-05)
**Source:** `backend/app/mcp/tools/ping.py:35-37` (the session-open shape) +
`backend/app/mcp/context.py:27-31` (what `AppContext` carries)
**Apply to:** every tool module, via `_common.read_only_session(ctx)`

```python
@dataclass(slots=True)
class AppContext:
    """What every MCP tool is handed. Borrowed, never owned."""

    sessionmaker: async_sessionmaker[AsyncSession]
```

```python
sessionmaker = ctx.request_context.lifespan_context.sessionmaker
async with sessionmaker() as session:
    ...
```

`context.py:1-13` documents that the sessionmaker is **borrowed** — a tool must never call
`make_engine()` or build its own factory.

### Error containment (MCP-06)
**Source:** `backend/app/mcp/tools/ping.py:38-44`
**Apply to:** every tool body (`@safe_tool` in `_common.py`)
See the full excerpt under the tool-module section above. Reinforced by
`app/db/repositories/sync_state.py:44-56`, which is this repo's other worked example of
"never `str(exc)`":

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

### Structured logging
**Source:** `backend/app/mcp/tools/ping.py:14,21,42`
**Apply to:** every module in `app/mcp/tools/`

```python
import structlog
log = structlog.get_logger()
...
log.exception("mcp_ping_db_check_failed")
```

Event names are `snake_case` verbs/nouns with no interpolation. `app/logging.py` wires the
three-layer redaction chain; `test_secret_redaction.py:158` proves rendered tracebacks are
covered. Nothing new is needed — but note this channel does **not** cover the SDK's tool-error
path (RESEARCH.md Pitfall 3).

### `user_id` handling (ASVS V4)
**Source:** `backend/app/analytics/records.py:107-118` (and every other analytics function)

```python
async def get_personal_records(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    ...
):
    """...

    Session positional, everything else keyword-only; ``user_id`` has no default (ASVS V4). The
    caller owns the transaction; nothing here writes. ...
    """
```

Apply to `_common.find_templates_by_title` and everything in
`app/db/repositories/workouts.py`. `user_id` never appears in a tool's `inputSchema`.

### Docstring convention (project-wide, non-negotiable)
**Source:** every file read for this map — `analytics/volume.py:1-40`,
`analytics/schemas.py:1-27`, `mcp/server.py:1-28`, `db/repositories/sync_state.py:1-9`,
`tests/test_mcp_tools.py:1-26`.

This codebase's docstrings state **the counter-intuitive rule and the measured consequence of
breaking it**, not what the function does. Example (`analytics/volume.py:10-17`):

```
**Tonnage is gated on OPERAND PRESENCE and reported as ``None`` rather than ``0``.** The product
``weight x reps`` is NULL whenever either operand is, and SQL ``SUM`` skips those rows without a
warning -- 543 of 7,719 live non-warmup sets produce a NULL product. ...
```

New Phase 6 modules must carry the same density. A one-line "Returns the weekly volume."
docstring is a deviation from the established convention, and it is also what the SDK publishes
to Claude when `description=` is omitted from `add_tool`.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| — | — | — | None. Every file has at least a partial in-repo analog. |

Two files are *composed* rather than copied and deserve extra planner attention:

| File | Why it is not a straight copy |
|---|---|
| `backend/app/mcp/tools/_common.py` | Composes four separate analogs (window resolution, error containment, bounded constants, repository query style). No single file does all four. The `@safe_tool` decorator itself has no analog anywhere in the repo — RESEARCH.md A1 flags it as unverified in decorated form and requires a schema-preservation test before committing to it. |
| `backend/app/db/repositories/workouts.py` | `sync_state.py` is the only existing repository and it is a *write* path (`pg_insert`, `on_conflict_do_update`). The read-only projection query shape actually lives in `app/analytics/rollup.py:193+ weekly_set_rows`, which is in a different package. Take the module/signature conventions from `sync_state.py` and the query shape from `rollup.py`. |

---

## Metadata

**Analog search scope:** `backend/app/mcp/`, `backend/app/analytics/`, `backend/app/db/`,
`backend/app/core/`, `backend/app/config.py`, `backend/app/cli.py`, `backend/tests/`
**Files scanned:** 96 Python files under `backend/`; 14 read in full or in substantial part
**Pattern extraction date:** 2026-08-31
**Skills directory:** none present (`.claude/skills/`, `.agents/skills/` do not exist)
</content>
</invoke>
