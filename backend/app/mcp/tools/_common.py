"""The one module every Phase 6 tool imports (MCP-02, MCP-03, MCP-05, MCP-06).

Five things live here because each of them is cross-cutting, and a rule written twelve times
is twelve chances to forget one:

**Session acquisition PostgreSQL itself refuses to let write** (MCP-05). ``read_only_session``
opens the transaction READ ONLY at the server, which is the half of "read-only in v1" that a
``ToolAnnotations`` hint cannot provide.

**``weeks`` -> inclusive local date range, Monday-anchored** (D-03, D-04). ``week_window`` and
``window_from_weeks``. The anchor is not cosmetic: the volume tools re-snap the range themselves,
so a non-Monday start silently returns one week more than the caller asked for.

**The user's local today, never the server's UTC date** (D-13, FOUND-03). ``local_timezone`` is
the ONE timezone read in the MCP layer, and ``local_today`` the only sanctioned "what day is it".

**Exercise-name resolution without string interpolation** (D-01, D-02). ``find_templates_by_title``
compares a bound parameter and returns every match, because ``exercise_templates.title`` carries
no uniqueness constraint at all.

**The exception guard** (D-10, MCP-06). ``safe_tool`` exists because ``mcp 2.0.0`` returns
``str(exception)`` to the model verbatim, and an asyncpg connection error carries the DSN.

**The one writable session** (GOAL-03, PITFALLS #14, MCP-07). ``writable_session`` is
``read_only_session``'s sibling, not its replacement; ``program_switch.py`` and ``physique.py``
are the only two tool modules that open it, and ``test_mcp_isolation._WRITE_ALLOWLIST`` asserts
that set EXACTLY -- a third entry fails the suite.

Plus the per-tool response caps, in one block, so a budget can be re-tuned in one place.
"""

import datetime as dt
import functools
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager

import structlog
from mcp.server.mcpserver import Context
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import DEFAULT_USER_ID
from app.core.time import local_day, utc_now
from app.db.models.exercise import ExerciseTemplate
from app.db.models.user import User
from app.db.repositories.sync_state import PROVIDER_HEVY
from app.mcp.context import AppContext

log = structlog.get_logger()

# --------------------------------------------------------------------------
# Response caps (MCP-03, D-02, D-04, D-06, D-08, D-10, D-11/D-12)
#
# Every number below is a CONTEXT budget, not a database limit. The failure these prevent is not
# a slow query -- it is Claude receiving so many rows that the answer it was asked for no longer
# fits beside them. One constant per tool, named for the tool, so re-tuning one budget cannot
# quietly move another.
# --------------------------------------------------------------------------

# D-04: one year of week buckets. 53 rows is where a "how has my last year gone" answer stops
# being summarisable; 52 is also exactly what a user means by "the last year".
MAX_WEEKS = 52

# D-08 + the 16 KB summary budget. The training summary carries per-muscle and per-week detail
# for every week in its window, so its row count multiplies out far faster than MAX_WEEKS does.
MAX_SUMMARY_WEEKS = 12

# D-10: a recent-workouts list is a browsing aid, not an export. Twenty-five sessions is roughly
# six weeks of training at four sessions a week -- past that, the coach should be asking for
# aggregates instead.
MAX_RECENT_WORKOUTS = 25

# D-02: bound the DISAMBIGUATION payload too. A name that matches many templates is exactly the
# case where the response is a list of candidates, so the "we found too much" path needs its own
# cap or it becomes the unbounded one.
MAX_CANDIDATES = 20

# D-11/D-12: one workout's sets, expanded. A long full-body session is ~60 sets; 120 leaves
# headroom for an outlier without letting a single tool call dominate the context window.
MAX_WORKOUT_SETS = 120

# MCP-03: frequency across every exercise trained in a window. Thirty distinct exercises already
# describes a full training split.
MAX_FREQUENCY_EXERCISES = 30

# MCP-03: plateau detection reports one row per stalled exercise. Thirty stalled exercises is
# already a training-programme problem, not a data problem.
MAX_PLATEAU_EXERCISES = 30

# MCP-03: one progression series is one point per session. Sixty points is over a year of
# training a given lift weekly -- enough to see a trend, bounded enough to send.
MAX_PROGRESSION_POINTS = 60

# MCP-03: a two-period comparison returns paired rows. Twenty-five pairs is fifty numbers, which
# is the practical ceiling on what a coaching answer can reference individually.
MAX_COMPARISON_ITEMS = 25

# D-06: each comparison period is capped at a year, so the widest legal comparison spans two
# years of history and still terminates.
MAX_COMPARISON_PERIOD_DAYS = 365

# D-02's "narrow extras, not the full lists". `fitness_get_personal_records` and
# `fitness_get_plateaus` still return everything; a REPORT carries the handful worth naming
# in a summary paragraph. Five, because a coaching answer that cites more than about five
# individual lifts has stopped summarizing. Both lists travel with `was_truncated` and
# `total_available` from `truncate()` -- an unlabelled cap is a wrong answer delivered with
# full confidence.
MAX_REPORT_PR_HIGHLIGHTS = 5
MAX_REPORT_PLATEAU_HIGHLIGHTS = 5

# Deliberately no window-count cap beside the two constants above. Both report tools take NO
# parameters -- the period is fixed by which tool was called (D-04) -- so there is no
# caller-supplied window to cap. "The other window tools all have one" is exactly the reasoning
# that would add a parameter the analytics layer has no place to receive.


# Type parameters are declared PEP 695 style (`def f[T](...)`) rather than with module-level
# `TypeVar`/`ParamSpec` objects. The binding is identical -- both scope the variable to the
# function -- but Ruff's UP047 rejects the older form at this project's `target-version = py313`,
# and a `noqa` here would be a suppression standing in for a two-character change.


def resolve_user_id(ctx: Context[AppContext]) -> uuid.UUID:
    """Whose data this call reads. Resolved SERVER-side, never from a tool argument.

    ``user_id`` must never appear in any tool's ``inputSchema``. A model-supplied identity is an
    IDOR by construction (ASVS V4): the model would be choosing the tenant, and "which user"
    would become a value Claude could hallucinate. Plan 06-09 asserts the absence.

    v1 has exactly one user, so the subject -> user mapping is deliberately deferred rather than
    designed now. What is NOT deferred is the seam: when a second user exists, the JWT subject is
    read here, in one function, instead of being retrofitted into twelve tool bodies.

    ``ctx`` is accepted and unused ON PURPOSE. It already carries the authenticated request, so
    the seam is handed the value it will need on the day it starts needing it -- adding the
    parameter later would touch every call site.
    """
    return DEFAULT_USER_ID


@asynccontextmanager
async def read_only_session(ctx: Context[AppContext]) -> AsyncIterator[AsyncSession]:
    """A session whose transaction PostgreSQL will not let anything write (MCP-05, T-06-03).

    The execution option makes asyncpg issue ``START TRANSACTION ... READ ONLY``, so an INSERT,
    UPDATE or DELETE raises ``asyncpg.exceptions.ReadOnlySQLTransactionError`` from the SERVER.
    That is the half of "MCP is read-only in v1" that ``ToolAnnotations(read_only_hint=True)``
    cannot supply: the SDK documents annotations as hints that "should not be relied upon for
    security enforcement", which is to say they constrain nothing.

    Three non-obvious facts, all verified rather than assumed:

    * The option must be applied BEFORE the first query. It takes effect at transaction START,
      and a session that has already emitted a statement has already begun a writable one.
    * It works at the DEFAULT isolation level. Do NOT add SERIALIZABLE despite SQLAlchemy's
      PostgreSQL docs pairing the two -- serializing a read-only analytics query buys nothing
      and costs retries.
    * The flag does not leak back into the pooled connection: the next checkout starts writable,
      so the CLI and the sync service are unaffected.

    The rollback in ``finally`` is unconditional. There is nothing to commit by construction, and
    an explicit rollback returns the connection to the pool in a known state on the error path
    too.
    """
    sessionmaker = ctx.request_context.lifespan_context.sessionmaker
    async with sessionmaker() as session:
        # Must precede the first query: the execution option applies at transaction START.
        await session.connection(execution_options={"postgresql_readonly": True})
        try:
            yield session
        finally:
            await session.rollback()


@asynccontextmanager
async def writable_session(ctx: Context[AppContext]) -> AsyncIterator[AsyncSession]:
    """The ONE session in `app/mcp/` PostgreSQL will let write (GOAL-03, PITFALLS #14).

    Three deliberate differences from `read_only_session`, each of which is the point:

    * no read-only execution option set on the connection -- the server would otherwise refuse
      the INSERT and UPDATE the confirm branch exists to perform;
    * no unconditional `rollback()` in `finally` -- the caller commits explicitly, and every
      path that does NOT commit relies on the session closing to roll back, which is the
      correct outcome for a refused token;
    * the commit is the caller's LAST statement (PITFALLS #15). Nothing may run after it,
      because an exception after a successful commit is reported by `safe_tool` as `unknown`
      -- and `unknown` on an applied switch invites a retry that double-applies.

    Used by exactly TWO modules -- `program_switch.py` (GOAL-03's confirm-gated switch) and
    `physique.py` (PHYS-06's append-only observation log).
    `test_mcp_isolation._WRITE_ALLOWLIST` asserts that membership exactly, with `len == 2`, so a
    THIRD write tool cannot arrive quietly. The allowlist was WIDENED for the second one, never
    loosened into a prefix or substring check. The commit-is-last rule now has two callers:
    `program_switch.py`'s double-apply and `physique.py`'s duplicate-append are the same failure.
    """
    sessionmaker = ctx.request_context.lifespan_context.sessionmaker
    async with sessionmaker() as session:
        yield session


def week_window(*, today: dt.date, weeks: int) -> tuple[dt.date, dt.date]:
    """Turn ``weeks=N`` into an inclusive local date range anchored on a Monday (D-03, D-04).

    Monday-anchored, and that is load-bearing rather than tidy. ``get_weekly_volume`` and
    ``get_muscle_group_volume`` call ``snap_local_week_range`` themselves, which widens a range
    OUTWARD to whole weeks. Hand them a Wednesday start and the snap reaches back to the previous
    Monday, so a ``weeks=52`` request returns **53** week rows -- blowing the D-04 row cap for a
    reason that reads like an off-by-one in the test rather than a missing anchor here.

    It is also what a person means. "The last 12 weeks" is twelve calendar weeks ending with the
    one currently in progress, not 84 days measured backwards from a Thursday.

    The guard runs first and its message names the failure while carrying no value: Pitfall 3
    established that this string can reach Claude as tool output, not just the log.
    """
    if weeks < 1 or weeks > MAX_WEEKS:
        raise ValueError("weeks outside the permitted range")
    this_monday = today - dt.timedelta(days=today.weekday())
    start_day = this_monday - dt.timedelta(weeks=weeks - 1)
    return start_day, today


async def local_timezone(session: AsyncSession, *, user_id: uuid.UUID) -> str:
    """The user's IANA timezone, read from ``users.timezone`` (FOUND-03).

    Never a module constant, never an environment variable, never a caller default. A hardcoded
    default would let a wrong-timezone bug pass every test, because every test would be reading
    the same wrong answer the code writes.

    This is the ONE timezone read in the MCP layer. ``fitness_get_recent_workouts`` and
    ``fitness_get_workout`` call it directly for the ``tz`` string their repository needs; every
    other tool reaches it through ``local_today``/``window_from_weeks``. The analytics layer has
    its own equivalent read in ``rollup.resolve_window`` -- deliberately, since analytics must not
    depend on the MCP package.
    """
    tz = await session.scalar(select(User.timezone).where(User.id == user_id))
    if tz is None:
        raise ValueError("unknown user")
    return tz


async def local_today(session: AsyncSession, *, user_id: uuid.UUID) -> dt.date:
    """What day it is where the user trains (D-13).

    Never ``dt.date.today()`` and never the server's UTC date. At UTC+7 every instant between
    17:00Z and 24:00Z belongs to the NEXT local day -- which is every morning workout. A
    UTC-derived end day therefore drops the whole of today's training for seven hours out of
    every twenty-four, and does it silently, as a slightly-low number rather than an error.
    """
    return local_day(utc_now(), await local_timezone(session, user_id=user_id))


async def window_from_weeks(
    session: AsyncSession, *, user_id: uuid.UUID, weeks: int
) -> tuple[dt.date, dt.date]:
    """``weeks`` -> the inclusive local date range analytics wants (D-03).

    The composition every window-taking tool performs, written once. Tools accept ``weeks: int``
    rather than a date pair because a model choosing two dates chooses two chances to be wrong
    about what "the last month" means.
    """
    return week_window(today=await local_today(session, user_id=user_id), weeks=weeks)


async def find_templates_by_title(
    session: AsyncSession, *, user_id: uuid.UUID, name: str
) -> list[tuple[str, str]]:
    """Every exercise template whose title matches ``name``, case-insensitively (D-01, D-02).

    Returns ``(title, external_id)`` pairs -- zero, one, or many.

    Many is REAL, not theoretical. ``exercise_templates.title`` carries no uniqueness constraint
    and no index, and Hevy ships both built-in templates (8-char hex ids) and user-custom ones
    (full UUIDs), so the same name can legitimately exist twice. A helper that returned "the"
    template would pick one arbitrarily and answer a progression question from half the data.

    ``func.lower(column) == bound_parameter``, never a Python-side f-string (Ruff S608, ASVS V5):
    the name is a model-chosen string crossing a trust boundary. ``user_id`` sits in the WHERE
    list, not merely in the caller's intentions (ASVS V4, T-06-02).

    The ordering is explicit because an unordered ``LIMIT`` is a flaky test waiting for the
    planner to change its mind, and the limit is ``MAX_CANDIDATES`` because the disambiguation
    payload needs a bound as much as any other response does.
    """
    stmt = (
        select(ExerciseTemplate.title, ExerciseTemplate.external_id)
        .where(
            ExerciseTemplate.user_id == user_id,
            ExerciseTemplate.provider == PROVIDER_HEVY,
            func.lower(ExerciseTemplate.title) == name.strip().lower(),
        )
        .order_by(ExerciseTemplate.title, ExerciseTemplate.external_id)
        .limit(MAX_CANDIDATES)
    )
    return [(title, external_id) for title, external_id in (await session.execute(stmt)).all()]


def safe_tool[**P, R](
    *, degraded: Callable[[], R]
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Guarantee that no exception raised inside a tool body reaches Claude (MCP-06, T-06-01).

    This is not defensive style. It closes a VERIFIED leak: ``mcp 2.0.0``'s ``Tool.run`` wraps any
    escaping exception as ``ToolError(f"Error executing tool {name}: {e}")``, and
    ``MCPServer._handle_call_tool`` returns
    ``CallToolResult(content=[TextContent(text=str(e))], is_error=True)`` -- verbatim, to the
    model. An asyncpg connection error's message carries the full DSN: user, password, host, port
    and database. Structlog's three-layer redaction (FOUND-05) does not touch that channel,
    because a tool result is not a log record.

    So the detail goes to ``log.exception`` -- which DOES run the redaction chain -- and the model
    gets a coarse degraded payload built by the caller's own factory. ``degraded`` is a callable
    rather than a value so the placeholder is constructed fresh per failure and cannot be mutated
    across calls.

    ``functools.wraps`` is load-bearing, not hygiene: the SDK builds the tool's schema from
    ``fn.__doc__``, the return annotation and ``inspect.signature`` (which follows
    ``__wrapped__``). Without it, every decorated tool publishes an empty description and a
    ``**kwargs`` signature. Plan 06-09's ``test_decorated_tools_still_publish_schemas`` is what
    proves it stays true.
    """

    def decorate(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return await fn(*args, **kwargs)
            except Exception:  # noqa: BLE001 - see the docstring; nothing may escape
                log.exception("mcp_tool_failed", tool=fn.__name__)
                return degraded()

        return wrapper

    return decorate


def truncate[T](items: Sequence[T], limit: int) -> tuple[list[T], bool, int]:
    """Cap a list and return the two facts that make the cap honest.

    Returns ``(capped, truncated, total_available)``. Every truncated list MUST be returned
    alongside both, and the tool's response model must carry both as fields.

    Without them, Claude reads "30 exercises" as "you train 30 exercises" -- a wrong answer with
    no signal that anything was withheld, delivered with full confidence. That is precisely the
    failure mode D-02 exists to prevent for ambiguous exercise names, and an unlabelled cap
    reintroduces it everywhere else.
    """
    return list(items[:limit]), len(items) > limit, len(items)
