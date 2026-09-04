"""D-08: ``fitness_ping`` really reaches the database, and really degrades.

Two non-obvious choices, both deliberate.

**The in-memory ``mcp.Client`` bypasses ``RequireAuthMiddleware`` entirely, and
that is exactly what is wanted here.** Auth is proven over HTTP in
``test_mcp_auth.py``, where a 401 is unambiguous. Driving the tool through the
authenticated transport instead would fuse the two concerns: a tool that raised
and a credential that was rejected would both surface as "the call did not
return what I expected", and the first thing anyone would suspect is the token.
Splitting them means a failure here can only be the tool.

**The unreachable database is a REAL connection to closed port 1, never a
mock**, for the same reason ``test_health.py`` gives: a patched exception proves
the ``except`` branch runs, not that an actual driver error is what lands in it.
Connection failures are precisely where the DSN, the credentials, and the driver
internals live, so the leak assertion is only worth anything if the failure that
produced the payload was genuine (T-02-09).

The degrade path here is *not* the one ``/health`` takes. There is no status
code in an MCP tool result to carry the bad news, so the tool must still report
``is_error: false`` and express the failure in the payload as
``database="error"``. A tool that raised instead would reach the model as a
protocol-level error with an SDK-generated message -- which is exactly the
uncontrolled string this project refuses to let near a driver exception.

**From Phase 6 on, this module covers SIXTEEN tools, not one** (MCP-02, MCP-06).
MCP-02's claim is behavioural -- "Claude can call tools covering eleven analytics
areas" -- so a schema test cannot discharge it. Every registered tool therefore
gets at least one case here that asserts a real structured answer against seeded
data, and the dead-database leak test is parametrized over all sixteen rather
than proving one tool's ``except`` branch and assuming the other fifteen.

**``committed_history`` is the fixture to use here, NEVER ``golden_workout``.**
``golden_workout`` flushes and rolls back, which is correct for the analytics
suites: those call an analytics function with the SAME ``AsyncSession``, so it
reads the uncommitted rows inside the open transaction. A tool driven through
``Client(mcp)`` does not get that session. It opens its own from
``ctx.request_context.lifespan_context.sessionmaker`` -- a different transaction
on a different connection, which cannot see uncommitted rows at all. A test that
seeded through ``golden_workout`` here would get an empty, entirely valid,
entirely meaningless response.
"""

import datetime as dt
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.time import utc_now
from app.db.models.program import ProgramPeriod
from app.db.repositories.programs import get_active_period
from app.db.repositories.sync_state import PROVIDER_HEVY, SYNC_RESOURCES, complete_sync
from app.normalization.muscles import CanonicalMuscleGroup, MuscleRole
from tests.conftest import DEFAULT_USER_ID, GoldenBuilder, GoldenExercise, GoldenSet

# Mirrors `test_health.py:19`. Port 1 is reserved and never listening, so the
# connection fails immediately rather than hanging on a routable-but-silent host.
DEAD_DB_URL = "postgresql+asyncpg://nobody:nopass@127.0.0.1:1/nodb"

# Every string that must not appear in ANY tool result. The first four are `DEAD_DB_URL`'s own
# components -- user, password, host and database -- because an asyncpg connection error carries
# the whole DSN. The rest are how a driver, an ORM or the interpreter names ITSELF, which is what
# an escaped exception message would carry even if the DSN had been stripped out of it.
LEAK_MARKERS = (
    "nobody",
    "nopass",
    "127.0.0.1",
    "nodb",
    "asyncpg",
    "Traceback",
    "psycopg",
    "ConnectionRefused",
    "sqlalchemy",
)

# The minimal VALID call for every registered tool: `{}` for the eight that take none, a sentinel
# name for the two that resolve by title, a sentinel id for the detail tool, and four dates for
# the comparison tool.
#
# The comparison dates are deliberately VALID and in forward order. `fitness_compare_periods`
# checks its range BEFORE opening a session (T-06-05), so a reversed or over-long pair would
# return `data_available=False` without ever touching the database -- and the leak test below
# would then be asserting that a tool which never ran leaked nothing, which is true and worthless.
# Fixed literals rather than clock-relative dates because nothing here depends on "now"; only the
# ordering and the span do.
#
# Exported rather than private: `test_secret_redaction.py` drives the same sixteen calls against
# a HEALTHY database, and two copies of "the minimal call for every tool" is one copy that stops
# covering a tool the day a signature changes.
MINIMAL_TOOL_ARGUMENTS: dict[str, dict[str, object]] = {
    "fitness_ping": {},
    "fitness_get_recent_workouts": {},
    "fitness_get_workout": {"workout_id": "whatever"},
    "fitness_get_training_summary": {},
    "fitness_get_weekly_volume": {},
    "fitness_get_muscle_group_volume": {},
    "fitness_get_training_frequency": {},
    "fitness_get_exercise_progression": {"exercise_name": "Bench Press (Barbell)"},
    "fitness_get_personal_records": {"exercise_name": "Bench Press (Barbell)"},
    "fitness_get_plateaus": {},
    "fitness_compare_periods": {
        "period_a_start": "2026-01-01",
        "period_a_end": "2026-01-14",
        "period_b_start": "2026-01-15",
        "period_b_end": "2026-01-28",
    },
    "fitness_get_body_measurement_trend": {"metric": "waist_cm"},
    "fitness_get_body_weight_trend": {},
    "fitness_get_recomposition_status": {},
    "fitness_get_training_program": {},
    # `lean_bulk` is the seeded active program, so the minimal call is a REFUSAL that writes
    # nothing -- `test_secret_redaction.py` drives this same table against a HEALTHY
    # container and requires every call to succeed, and a minimal call that minted a token
    # would leave a row behind in a test whose subject is not this tool.
    "fitness_switch_training_program": {"program": "lean_bulk"},
}

# --------------------------------------------------------------------------
# The reference history every behavioural test seeds.
#
# Shapes and counts are named constants rather than inlined literals so a test can assert
# against the SAME number the fixture wrote. A hand-copied `36` in an assertion is a number
# that silently stops matching the fixture the day the fixture changes.
# --------------------------------------------------------------------------

# 02:00Z is 09:00 in Asia/Jakarta -- well inside the local day, so these fixtures exercise the
# date arithmetic and never the local-midnight boundary (which has its own dedicated tests).
# Mirrors `conftest._worst_case_anchor` deliberately: the reason is the same and so is the risk.
_REFERENCE_HOUR = 2

# Days back from the anchor, OLDEST FIRST so the bench weight can climb with the index and the
# progression/records/plateau tools all have a real series to read. The widest offset is 17, and
# a `weeks=4` window reaches back at least 21 days from today under every weekday the run can
# start on -- so every one of these six sessions is inside a 4-week window, always.
_REFERENCE_WORKOUT_DAY_OFFSETS = (17, 14, 10, 7, 4, 1)

# Per workout: bench (1 warm-up + 2 working), squat (2 working), pull-ups (2 working).
_REFERENCE_WARMUP_SETS_PER_WORKOUT = 1
_REFERENCE_WORKING_SETS_PER_WORKOUT = 6

REFERENCE_WORKOUTS = len(_REFERENCE_WORKOUT_DAY_OFFSETS)
# What every volume figure MUST report: warm-ups excluded.
REFERENCE_HARD_SETS = REFERENCE_WORKOUTS * _REFERENCE_WORKING_SETS_PER_WORKOUT
# What a tool that forgot the warm-up exclusion would report instead. Asserting against BOTH is
# what makes the first number mean "warm-ups were excluded" rather than "some number came back".
REFERENCE_SETS_INCLUDING_WARMUPS = REFERENCE_WORKOUTS * (
    _REFERENCE_WORKING_SETS_PER_WORKOUT + _REFERENCE_WARMUP_SETS_PER_WORKOUT
)

# ~30 daily weigh-ins ending on the anchor day, so the body tools return real numbers instead of
# three nulls. Thirty covers the 30-day rolling average, which is the widest window BODY-01 has.
REFERENCE_BODY_MEASUREMENT_DAYS = 30

# The 19-member canonical taxonomy. Named here because three separate tests assert against it and
# a hand-typed `19` in each is three places to forget when the taxonomy grows.
CANONICAL_MUSCLE_GROUP_COUNT = 19

# Nothing in the reference history maps to calves, so it is the group that proves an UNTRAINED
# muscle comes back as a zero row rather than as an absence -- the most diagnostically
# interesting row for "which muscles are undertrained?".
UNTRAINED_MUSCLE_GROUP = CanonicalMuscleGroup.CALVES.value

BENCH_TITLE = "Bench Press (Barbell)"
SQUAT_TITLE = "Squat (Barbell)"
PULL_TITLE = "Pull Up"
# TWO templates share this title on purpose. It is not a contrived case: `exercise_templates.title`
# carries no uniqueness constraint, and Hevy ships both built-in templates (8-char hex ids) and
# user-custom ones (full UUIDs) that can legitimately spell an exercise the same way.
AMBIGUOUS_TITLE = "Lateral Raise"


def _reference_anchor() -> dt.datetime:
    """The most recent seeded workout instant: today at 02:00Z, or yesterday's if it has not come.

    Anchored on ``utc_now()`` and never on a hard-coded date. A fixed anchor silently ages out of
    every ``weeks=N`` window that ends today, at which point every assertion below measures an
    empty response and passes for entirely the wrong reason.

    The step back to yesterday matters for a run that starts between 00:00Z and 02:00Z: without it
    the newest "historical" workout would be in the future.
    """
    now = utc_now()
    day = now.date() if now.hour >= _REFERENCE_HOUR else now.date() - dt.timedelta(days=1)
    return dt.datetime.combine(day, dt.time(hour=_REFERENCE_HOUR), tzinfo=dt.UTC)


async def _seed_reference_history(builder: GoldenBuilder, session: AsyncSession) -> dt.datetime:
    """Commit the training history every behavioural test in this module reads. Returns the anchor.

    A module-level ``async def`` rather than a pytest fixture ON PURPOSE: a test that needs this
    history says so by calling it, and a test that must run against an EMPTY database (the leak
    suite) cannot acquire it by accident through fixture ordering.

    ``committed_history`` requires the caller to commit -- making the builder commit per statement
    would break ``GoldenBuilder``'s contract for every Phase 4/5 test that shares it -- so the
    commit happens here, once, at the end.
    """
    anchor = _reference_anchor()

    await builder.template(
        external_id="MCP-BENCH",
        exercise_type="weight_reps",
        title=BENCH_TITLE,
        muscles=(
            (CanonicalMuscleGroup.CHEST, MuscleRole.DIRECT),
            (CanonicalMuscleGroup.TRICEPS, MuscleRole.INDIRECT),
        ),
    )
    await builder.template(
        external_id="MCP-SQUAT",
        exercise_type="weight_reps",
        title=SQUAT_TITLE,
        muscles=((CanonicalMuscleGroup.QUADS, MuscleRole.DIRECT),),
    )
    await builder.template(
        external_id="MCP-PULL",
        # `reps_only` on purpose: it is the modality that produces a NULL tonnage product, so the
        # response models' `Decimal | None` tonnage fields are exercised rather than assumed.
        exercise_type="reps_only",
        title=PULL_TITLE,
        muscles=((CanonicalMuscleGroup.LATS, MuscleRole.DIRECT),),
    )
    # The D-02 multi-match case. Both are real templates with real mappings; what makes them
    # ambiguous is only that they spell the exercise identically.
    for ambiguous_id in ("MCP-LAT1", "MCP-LAT2"):
        await builder.template(
            external_id=ambiguous_id,
            exercise_type="weight_reps",
            title=AMBIGUOUS_TITLE,
            muscles=((CanonicalMuscleGroup.SIDE_DELTS, MuscleRole.DIRECT),),
        )

    for index, days_back in enumerate(_REFERENCE_WORKOUT_DAY_OFFSETS):
        # Climbing bench weight across sessions, so progression, records and plateau detection all
        # have something to say rather than a flat series they would each call "unclear".
        bench_kg = Decimal("60.000") + Decimal(index) * Decimal("2.5")
        squat_kg = Decimal("100.000") + Decimal(index) * Decimal("5")
        await builder.workout(
            start_time=anchor - dt.timedelta(days=days_back),
            title=f"MCP Reference Session {index}",
            exercises=(
                GoldenExercise(
                    template_external_id="MCP-BENCH",
                    title=BENCH_TITLE,
                    sets=(
                        # The warm-up every volume figure must EXCLUDE. Deliberately light, so a
                        # tonnage that accidentally included it would still look plausible -- which
                        # is why the assertions count sets rather than eyeball kilograms.
                        GoldenSet(set_type="warmup", weight_kg=Decimal("20.000"), reps=10),
                        GoldenSet(weight_kg=bench_kg, reps=8),
                        GoldenSet(weight_kg=bench_kg, reps=8),
                    ),
                ),
                GoldenExercise(
                    template_external_id="MCP-SQUAT",
                    title=SQUAT_TITLE,
                    sets=(
                        GoldenSet(weight_kg=squat_kg, reps=5),
                        GoldenSet(weight_kg=squat_kg, reps=5),
                    ),
                ),
                GoldenExercise(
                    template_external_id="MCP-PULL",
                    title=PULL_TITLE,
                    sets=(GoldenSet(reps=8), GoldenSet(reps=8)),
                ),
            ),
        )

    anchor_day = anchor.date()
    for offset in range(REFERENCE_BODY_MEASUREMENT_DAYS):
        await builder.body_measurement(
            measured_on=anchor_day - dt.timedelta(days=offset),
            # `Decimal`, never `float`: these average into rolling 7/14/30-day figures and binary
            # floating point would make two arithmetically identical averages compare unequal.
            weight_kg=Decimal("80.000") + Decimal(offset) / Decimal(20),
        )

    # So `build_freshness` returns three real timestamps rather than three `None`s. Written through
    # the repository's own upsert, never by hand: one implementation of the ON CONFLICT rule.
    for resource in sorted(SYNC_RESOURCES):
        await complete_sync(
            session,
            user_id=DEFAULT_USER_ID,
            provider=PROVIDER_HEVY,
            resource=resource,
            last_synced_at=anchor,
        )

    await session.commit()
    return anchor


# ---------------------------------------------------------------------------
# D-08: the ping canary, unchanged from Phase 2.
# ---------------------------------------------------------------------------


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


@pytest.mark.integration
async def test_ping_degrades_cleanly(client: TestClient) -> None:
    """Unreachable database -> ``database="error"``, and still not an error result.

    The swap happens BEFORE ``async with Client(mcp)`` because ``mcp_lifespan``
    reads ``app.state.sessionmaker`` once, when the client context is entered,
    and hands the result to every tool call as ``AppContext``. Swapping after
    entry would leave the tool holding the healthy factory and the test would
    pass while proving nothing.

    ``app.state.sessionmaker`` is the attribute swapped, not
    ``app.state.engine`` -- the tool reads the factory, and ``/health`` reads the
    engine. The session-scoped engine is restored, never disposed: disposing a
    shared engine poisons every later test in the session.
    """
    from mcp import Client

    from app.mcp.server import mcp

    app = client.app
    original = app.state.sessionmaker
    dead = create_async_engine(DEAD_DB_URL, connect_args={"timeout": 1}, pool_pre_ping=False)
    app.state.sessionmaker = async_sessionmaker(dead, expire_on_commit=False, autoflush=False)
    try:
        async with Client(mcp) as mcp_client:
            result = await mcp_client.call_tool("fitness_ping", {})

        assert result.is_error is False, (
            "D-08: a database failure must degrade in the payload, not surface as "
            "a protocol-level tool error carrying an SDK-generated message."
        )
        assert result.structured_content == {"status": "ok", "database": "error"}
    finally:
        app.state.sessionmaker = original
        dead.sync_engine.dispose()


@pytest.mark.integration
async def test_every_tool_degradation_leaks_nothing(client: TestClient) -> None:
    """T-02-09/T-06-01: not one byte of connection detail reaches ANY tool result.

    MCP tool output is model-facing and, through the transcript, user-facing. ``mcp 2.0.0`` wraps
    any escaping exception as ``ToolError(f"Error executing tool {name}: {e}")`` and returns that
    string to the model VERBATIM -- and an asyncpg connection error's message carries the full
    DSN: user, password, host, port and database. Structlog's three-layer redaction (FOUND-05)
    never sees it, because a tool result is not a log record. ``@safe_tool`` is the only thing
    standing in that path.

    Every registered tool is exercised, not just ``fitness_ping``. The guard is applied
    per-function, so proving one ``except`` branch runs proves nothing about the other fifteen;
    the equality assertion below makes "all sixteen" structural, so a seventeenth tool registered
    without an entry in ``MINIMAL_TOOL_ARGUMENTS`` fails here rather than being silently skipped.

    One swap for all sixteen, and failures are COLLECTED rather than asserted in the loop: a bare
    ``assert`` on the first tool would hide every tool after it, and the interesting fact is which
    tools leak, not that one does.

    The swap happens BEFORE ``async with Client(mcp)`` because ``mcp_lifespan`` reads
    ``app.state.sessionmaker`` once, when the client context is entered, and hands the result to
    every tool call as ``AppContext``. Swapping after entry would leave every tool holding the
    healthy factory and the test would pass while proving nothing. The session-scoped engine is
    restored in ``finally``, never disposed: disposing a shared engine poisons every later test.
    """
    from mcp import Client

    from app.mcp.server import mcp

    app = client.app
    original = app.state.sessionmaker
    dead = create_async_engine(DEAD_DB_URL, connect_args={"timeout": 1}, pool_pre_ping=False)
    app.state.sessionmaker = async_sessionmaker(dead, expire_on_commit=False, autoflush=False)
    failures: list[str] = []
    try:
        async with Client(mcp) as mcp_client:
            registered = {tool.name for tool in (await mcp_client.list_tools()).tools}
            assert registered == set(MINIMAL_TOOL_ARGUMENTS), (
                "MINIMAL_TOOL_ARGUMENTS must name exactly the registered tool set, or this test "
                "silently stops covering whichever tool was added or renamed. Missing: "
                f"{sorted(registered - set(MINIMAL_TOOL_ARGUMENTS))}; stale: "
                f"{sorted(set(MINIMAL_TOOL_ARGUMENTS) - registered)}"
            )

            for name, arguments in MINIMAL_TOOL_ARGUMENTS.items():
                result = await mcp_client.call_tool(name, arguments)
                rendered = f"{result.structured_content}{result.content}"

                failures.extend(
                    f"MCP-06/Pitfall 3 violated: {leak!r} leaked out of {name}"
                    for leak in LEAK_MARKERS
                    if leak in rendered
                )
                if result.is_error is not False:
                    failures.append(
                        f"{name} returned is_error=True: @safe_tool degrades, it does not error, "
                        "and an error result is where the SDK puts an uncontrolled string"
                    )
                payload = result.structured_content
                if payload is None:
                    failures.append(f"{name} returned no structured content to degrade into")
                elif name == "fitness_ping":
                    # D-08's canary predates `data_available` and keeps its own degrade contract:
                    # it reports connectivity as a value, so `database="error"` IS its "I could
                    # not reach the data" flag. Every other tool carries `data_available`.
                    if payload != {"status": "ok", "database": "error"}:
                        failures.append(f"fitness_ping degraded to {payload!r}, not database=error")
                elif payload["data_available"] is not False:
                    failures.append(
                        f"{name} degraded with data_available={payload['data_available']!r}: an "
                        "outage reported as a real empty result is a wrong answer with no signal"
                    )
    finally:
        app.state.sessionmaker = original
        dead.sync_engine.dispose()

    assert not failures, "\n".join(failures)


async def test_a_raising_tool_would_leak_without_the_guard() -> None:
    """This test asserts the leak EXISTS, on purpose. It is why ``@safe_tool`` is mandatory.

    ``_common.safe_tool``'s docstring claims that ``mcp 2.0.0`` hands an escaping exception's
    ``str()`` back to the model verbatim. Every other test in this module asserts the guard's
    EFFECT; none of them would notice if the SDK quietly started sanitizing tool errors itself, at
    which point the guard's justification would be folklore rather than a verified fact.

    So the channel is documented rather than assumed: a throwaway tool on a SEPARATE ``MCPServer``
    -- never the app's ``mcp``, which would register a raising tool into the real server for the
    rest of the session -- raises with a DSN in its message, and the DSN is asserted to come back.

    If this test ever starts FAILING, the SDK has changed its error handling. That is a signal to
    re-verify the guard's justification against the new behaviour, not a signal to relax it.
    """
    from mcp import Client
    from mcp.server import MCPServer

    async def leaky_probe() -> str:
        """Raises on purpose. Never registered on the application's MCP server."""
        raise ValueError("postgresql://user:SECRET@host:5432/db unreachable")

    probe = MCPServer(name="leak-probe", version="0.0.0")
    probe.add_tool(leaky_probe, name="leaky_probe", description="Raises on purpose.")

    async with Client(probe) as probe_client:
        result = await probe_client.call_tool("leaky_probe", {})

    rendered = f"{result.structured_content}{result.content}"
    assert "SECRET@host" in rendered, (
        "the SDK no longer returns an unguarded exception's message to the model. @safe_tool's "
        "stated justification must be re-verified against the new behaviour before anyone "
        "concludes the guard is unnecessary."
    )


@pytest.mark.integration
async def test_ping_output_schema_requires_both_fields(client: TestClient) -> None:
    """Both fields are advertised as required, so neither can go missing silently.

    ``status`` alone would let a future refactor drop ``database`` and still
    satisfy the schema -- and the dropped field is the entire point of the tool.
    Asserted against the serialized (``by_alias``) form because that is the
    payload the model actually receives.
    """
    from mcp import Client

    from app.mcp.server import mcp

    async with Client(mcp) as mcp_client:
        tools = (await mcp_client.list_tools()).tools

    # Indexed BY NAME, never positionally. With sixteen tools registered, positional indexing
    # asserts against whichever tool the SDK happens to list first -- a green test about the
    # wrong tool, and nothing in the failure message would say so.
    ping = {tool.name: tool for tool in tools}["fitness_ping"]
    output_schema = ping.model_dump(by_alias=True)["outputSchema"]

    assert set(output_schema["required"]) == {"status", "database"}
    assert set(output_schema["properties"]) == {"status", "database"}


# ---------------------------------------------------------------------------
# D-09/D-11/D-12: the workout list and the drill-in it feeds.
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_recent_workouts_returns_summaries_with_ids(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """D-09: a real list, newest first, every row carrying the id the detail tool takes."""
    from mcp import Client

    from app.mcp.server import mcp

    await _seed_reference_history(committed_history, session)

    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool("fitness_get_recent_workouts", {"limit": 3})

    assert result.is_error is False
    payload = result.structured_content
    assert payload is not None
    assert payload["data_available"] is True
    workouts = payload["workouts"]
    assert len(workouts) == 3, "the limit is a cap on a real list, not a suggestion"
    assert all(row["workout_id"] for row in workouts), (
        "D-12/T-06-08: every row must carry the Hevy external id, because that id is the only "
        "thing fitness_get_workout accepts"
    )
    days = [row["local_day"] for row in workouts]
    assert days == sorted(days, reverse=True), "newest first, or 'recent' means nothing"


@pytest.mark.integration
async def test_get_workout_fetches_the_id_the_list_echoed(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """The list -> detail navigation path, end to end.

    D-12 exists to make exactly this unambiguous: the id the list echoes is the id the detail tool
    takes. Asserting it here is what stops a future change from echoing the internal `workouts.id`
    surrogate in one tool and expecting the external id in the other.
    """
    from mcp import Client

    from app.mcp.server import mcp

    await _seed_reference_history(committed_history, session)

    async with Client(mcp) as mcp_client:
        listed = await mcp_client.call_tool("fitness_get_recent_workouts", {"limit": 1})
        assert listed.structured_content is not None
        workout_id = listed.structured_content["workouts"][0]["workout_id"]
        detail = await mcp_client.call_tool("fitness_get_workout", {"workout_id": workout_id})

    assert detail.is_error is False
    payload = detail.structured_content
    assert payload is not None
    assert payload["found"] is True
    assert payload["requested_workout_id"] == workout_id
    assert payload["workout"]["workout_id"] == workout_id
    assert payload["workout"]["exercises"], "a seeded session must expand to its exercises"


@pytest.mark.integration
async def test_get_workout_reports_not_found_without_erroring(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """An unknown id is an ANSWER, not an error -- and not a claim about the database.

    `found=False` with `data_available=True` says "the tool reached the data and there is no
    workout with that id". The degraded payload says `data_available=False`, which is the entirely
    different claim "the tool could not reach the data at all". Collapsing them is how "you have no
    workout on record" gets said about an outage.
    """
    from mcp import Client

    from app.mcp.server import mcp

    await _seed_reference_history(committed_history, session)

    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool(
            "fitness_get_workout", {"workout_id": "no-such-workout"}
        )

    assert result.is_error is False, "an unknown id must never reach Claude through the SDK's "
    payload = result.structured_content
    assert payload is not None
    assert payload["data_available"] is True
    assert payload["found"] is False
    assert payload["workout"] is None


# ---------------------------------------------------------------------------
# VOL-01/VOL-02/VOL-03: volume and frequency.
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_weekly_volume_excludes_warmups(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """VOL-01: `hard_sets` is the hand-counted WORKING-set total, never the raw set count."""
    from mcp import Client

    from app.mcp.server import mcp

    await _seed_reference_history(committed_history, session)

    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool("fitness_get_weekly_volume", {"weeks": 4})

    assert result.is_error is False
    payload = result.structured_content
    assert payload is not None
    assert payload["data_available"] is True
    weeks = payload["volume"]["weeks"]
    assert weeks, "a 4-week window over seeded history must return week rows"
    total_hard_sets = sum(week["hard_sets"] for week in weeks)
    assert total_hard_sets == REFERENCE_HARD_SETS, (
        "hard sets are an EXCLUSION of warm-ups. Getting "
        f"{REFERENCE_SETS_INCLUDING_WARMUPS} here would mean the warm-up set of every "
        "seeded session was counted as training volume."
    )
    assert total_hard_sets != REFERENCE_SETS_INCLUDING_WARMUPS


@pytest.mark.integration
async def test_muscle_group_volume_returns_all_nineteen_groups(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """VOL-02: an untrained muscle is a ZERO ROW, never an absence.

    The zero row is the most diagnostically interesting row for PROJECT.md's "which muscles are
    undertrained?" question, which is exactly why omitting it would be the worst possible
    optimisation: an absent group reads as "no data" when the fact is "no training".
    """
    from mcp import Client

    from app.mcp.server import mcp

    await _seed_reference_history(committed_history, session)

    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool("fitness_get_muscle_group_volume", {"weeks": 4})

    assert result.is_error is False
    payload = result.structured_content
    assert payload is not None
    assert payload["data_available"] is True
    muscles = payload["muscles"]
    assert len(muscles) == CANONICAL_MUSCLE_GROUP_COUNT
    by_group = {row["muscle_group"]: row for row in muscles}
    assert by_group["chest"]["direct_sets"] > 0, "the seeded bench press is direct chest work"
    untrained = by_group[UNTRAINED_MUSCLE_GROUP]
    assert untrained["direct_sets"] == 0
    assert untrained["insufficient_data"] is True, (
        "zero sessions IS insufficient -- an untrained muscle reading as a CONFIDENT zero is the "
        "opposite of what the absence of a mapping means"
    )


@pytest.mark.integration
async def test_training_frequency_reports_per_muscle_and_per_exercise(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """VOL-03: sessions per week overall, per muscle group AND per exercise, all populated."""
    from mcp import Client

    from app.mcp.server import mcp

    await _seed_reference_history(committed_history, session)

    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool("fitness_get_training_frequency", {"weeks": 4})

    assert result.is_error is False
    payload = result.structured_content
    assert payload is not None
    assert payload["data_available"] is True
    assert payload["sessions_per_week"] is not None
    assert payload["muscle_groups"], "the seeded templates map to real canonical groups"
    assert payload["exercises"], "three distinct exercises were trained in the window"


# ---------------------------------------------------------------------------
# D-01/D-02: name resolution, in both failure modes, on both name-taking tools.
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_exercise_name_is_case_insensitive(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """D-01: Claude asks by NAME, and the name is what the user says out loud -- any casing."""
    from mcp import Client

    from app.mcp.server import mcp

    await _seed_reference_history(committed_history, session)

    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool(
            "fitness_get_exercise_progression", {"exercise_name": BENCH_TITLE.lower()}
        )

    assert result.is_error is False
    payload = result.structured_content
    assert payload is not None
    assert payload["matched"] is True, (
        "D-01: a lower-cased name must resolve. `find_templates_by_title` compares "
        "`func.lower(column)` against a bound parameter precisely so it does."
    )
    assert payload["progression"] is not None
    assert payload["progression"]["points"], "six seeded bench sessions must produce points"


@pytest.mark.integration
async def test_unknown_exercise_name_returns_no_candidates(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """D-02, zero-match half: "no such exercise" is a successful result carrying an empty list."""
    from mcp import Client

    from app.mcp.server import mcp

    await _seed_reference_history(committed_history, session)

    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool(
            "fitness_get_exercise_progression", {"exercise_name": "Nonexistent Lift"}
        )

    assert result.is_error is False, (
        "raising here would put the model's own requested name into the SDK's error text, which "
        "is the uncontrolled string channel MCP-06 exists to close"
    )
    payload = result.structured_content
    assert payload is not None
    assert payload["data_available"] is True
    assert payload["matched"] is False
    assert payload["candidates"] == []
    assert payload["progression"] is None


@pytest.mark.integration
async def test_ambiguous_exercise_name_returns_every_candidate(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """D-02, multi-match half: two templates, two candidates, no analytics. T-06-12."""
    from mcp import Client

    from app.mcp.server import mcp

    await _seed_reference_history(committed_history, session)

    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool(
            "fitness_get_exercise_progression", {"exercise_name": AMBIGUOUS_TITLE}
        )

    assert result.is_error is False
    payload = result.structured_content
    assert payload is not None
    assert payload["data_available"] is True
    assert payload["matched"] is False
    candidates = payload["candidates"]
    assert len(candidates) == 2, (
        "no silent auto-pick, ever. Answering a progression question from one of two same-named "
        "templates is half the data reported as the whole of it -- a wrong-exercise answer with no "
        "signal, which is worse than an extra round trip."
    )
    assert {row["exercise_template_external_id"] for row in candidates} == {
        "MCP-LAT1",
        "MCP-LAT2",
    }
    assert payload["progression"] is None


@pytest.mark.integration
async def test_personal_records_resolves_by_name_too(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """PROG-04 with the SAME D-02 contract. Two tools take a name; both must disambiguate."""
    from mcp import Client

    from app.mcp.server import mcp

    await _seed_reference_history(committed_history, session)

    async with Client(mcp) as mcp_client:
        matched = await mcp_client.call_tool(
            "fitness_get_personal_records", {"exercise_name": SQUAT_TITLE}
        )
        ambiguous = await mcp_client.call_tool(
            "fitness_get_personal_records", {"exercise_name": AMBIGUOUS_TITLE}
        )

    assert matched.is_error is False
    matched_payload = matched.structured_content
    assert matched_payload is not None
    assert matched_payload["matched"] is True
    assert matched_payload["records"] is not None
    assert matched_payload["records"]["records"], "a climbing squat series must set records"

    assert ambiguous.is_error is False
    ambiguous_payload = ambiguous.structured_content
    assert ambiguous_payload is not None
    assert ambiguous_payload["data_available"] is True
    assert ambiguous_payload["matched"] is False
    assert len(ambiguous_payload["candidates"]) == 2, (
        "D-02 is a contract of the name-resolution helper, not a feature of one tool. A records "
        "tool that auto-picked would report a max weight from half the history."
    )
    assert ambiguous_payload["records"] is None


# ---------------------------------------------------------------------------
# PROG-03 / CMP-01 / BODY-01 / BODY-02.
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_plateaus_reports_its_window_and_threshold(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """PROG-03 requires the window AND the threshold to travel WITH the result.

    A plateau verdict with no window is unfalsifiable: "you are stuck" means something different
    over 4 weeks than over 52, and a reader cannot tell which was measured.
    """
    from mcp import Client

    from app.mcp.server import mcp

    await _seed_reference_history(committed_history, session)

    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool(
            "fitness_get_plateaus", {"lookback_weeks": 12, "plateaued_only": False}
        )

    assert result.is_error is False
    payload = result.structured_content
    assert payload is not None
    assert payload["data_available"] is True
    assert payload["lookback_weeks"] == 12
    assert payload["lookback_start"] is not None
    assert payload["lookback_end"] is not None
    exercises = payload["exercises"]
    assert exercises, "plateaued_only=False must report every analysable exercise, not none"
    for row in exercises:
        assert row["threshold_percent"] is not None
        assert row["min_sessions"] is not None
        assert row["min_elapsed_days"] is not None
        assert "last_max_weight_kg" in row, (
            "PlateauResult gained a new field but fitness_get_plateaus is not forwarding it -- "
            "Task 1's PlateauResult.last_max_weight_kg must reach the MCP response unchanged"
        )


@pytest.mark.integration
async def test_compare_periods_normalizes_per_week(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """CMP-01: every figure carries its per-week form, so unequal windows cannot mislead."""
    from mcp import Client

    from app.mcp.server import mcp

    anchor_day = (await _seed_reference_history(committed_history, session)).date()
    # Two ADJACENT two-week periods, A the older baseline. `compare_periods` reads every delta as
    # "B minus A", so passing the newer range as A silently inverts every sign.
    period_a_start = anchor_day - dt.timedelta(days=27)
    period_a_end = anchor_day - dt.timedelta(days=14)
    period_b_start = anchor_day - dt.timedelta(days=13)

    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool(
            "fitness_compare_periods",
            {
                "period_a_start": period_a_start.isoformat(),
                "period_a_end": period_a_end.isoformat(),
                "period_b_start": period_b_start.isoformat(),
                "period_b_end": anchor_day.isoformat(),
            },
        )

    assert result.is_error is False
    payload = result.structured_content
    assert payload is not None
    assert payload["data_available"] is True
    assert payload["period_a"] is not None
    assert payload["period_b"] is not None
    assert payload["totals"], "the four metric rows are unconditional"
    for row in payload["totals"]:
        assert "period_a_per_week" in row
        assert "period_b_per_week" in row


@pytest.mark.integration
async def test_compare_periods_rejects_a_reversed_period_without_erroring(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """T-06-05: a reversed period is refused as a payload, never as an exception.

    A reversed range produces a negative window length and therefore a per-week normalisation
    divided by a negative number -- every delta silently inverted. Raising instead would echo the
    model's four dates back through the SDK's error-text channel for no benefit: they are its own
    arguments.
    """
    from mcp import Client

    from app.mcp.server import mcp

    anchor_day = (await _seed_reference_history(committed_history, session)).date()

    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool(
            "fitness_compare_periods",
            {
                # END BEFORE START. The only thing wrong with this call.
                "period_a_start": anchor_day.isoformat(),
                "period_a_end": (anchor_day - dt.timedelta(days=14)).isoformat(),
                "period_b_start": (anchor_day - dt.timedelta(days=13)).isoformat(),
                "period_b_end": anchor_day.isoformat(),
            },
        )

    assert result.is_error is False
    payload = result.structured_content
    assert payload is not None
    assert payload["data_available"] is False


@pytest.mark.integration
async def test_body_weight_trend_returns_rolling_averages(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """BODY-01: real rolling averages against the seeded weigh-ins, anchored on the LOCAL day."""
    from mcp import Client

    from app.mcp.server import mcp

    await _seed_reference_history(committed_history, session)

    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool("fitness_get_body_weight_trend", {})

    assert result.is_error is False
    payload = result.structured_content
    assert payload is not None
    assert payload["data_available"] is True
    trend = payload["trend"]
    assert trend["anchor_day"] is not None, "the anchor is the user's LOCAL day, never UTC"
    assert any(
        trend[field] is not None for field in ("average_7d_kg", "average_14d_kg", "average_30d_kg")
    ), f"{REFERENCE_BODY_MEASUREMENT_DAYS} daily weigh-ins must produce at least one average"


@pytest.mark.integration
async def test_body_measurement_trend_compares_latest_against_earliest(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """BODY-05 end to end: a real two-point comparison arrives as structured content."""
    from mcp import Client

    from app.mcp.server import mcp

    await _seed_reference_history(committed_history, session)
    today = utc_now().date()
    await committed_history.body_measurement(
        measured_on=today - dt.timedelta(days=60),
        weight_kg=None,
        waist_cm=Decimal("85.00"),
    )
    await committed_history.body_measurement(
        measured_on=today, weight_kg=None, waist_cm=Decimal("81.50")
    )
    await session.commit()

    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool(
            "fitness_get_body_measurement_trend", {"metric": "waist_cm"}
        )

    assert result.is_error is False
    payload = result.structured_content
    assert payload is not None
    assert payload["data_available"] is True
    trend = payload["trend"]
    assert trend["metric"] == "waist_cm"
    assert trend["window_days"] == 90
    assert trend["stale_after_days"] == 30
    assert trend["coverage"]["insufficient_data"] is False
    assert Decimal(str(trend["delta_value"])) == Decimal("-3.50")


@pytest.mark.integration
async def test_body_measurement_trend_rejects_an_unknown_metric(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """D-09: an unrecognized metric is refused by the tool's own inputSchema.

    Not a 500, and emphatically not an empty result presented as an answer -- "we have no
    readings for `elbow_cm`" would be a confident report about a metric that does not exist. The
    `StrEnum` annotation is what makes the SDK's schema validation the thing that refuses it,
    before any code in this repo runs.
    """
    from mcp import Client

    from app.mcp.server import mcp

    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool(
            "fitness_get_body_measurement_trend", {"metric": "elbow_cm"}
        )

    assert result.is_error is True
    rendered = f"{result.structured_content}{result.content}"
    for leak in LEAK_MARKERS:
        assert leak not in rendered, f"MCP-06: {leak!r} leaked out of a rejected call"


@pytest.mark.integration
async def test_recomposition_status_carries_its_disclaimer(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """BODY-02/T-06-09: the disclaimer is a REQUIRED FIELD, and it must be non-empty in practice.

    `analytics/schemas.py` calls it "a REQUIRED FIELD, not documentation" precisely so a Phase 6
    serialization change cannot drop it. Asserting the KEY exists would not catch an empty string;
    this asserts the string.
    """
    from mcp import Client

    from app.mcp.server import mcp

    await _seed_reference_history(committed_history, session)

    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool("fitness_get_recomposition_status", {})

    assert result.is_error is False
    payload = result.structured_content
    assert payload is not None
    assert payload["data_available"] is True
    recomposition = payload["recomposition"]
    assert recomposition is not None
    assert recomposition["status"] is not None
    disclaimer = recomposition["disclaimer"]
    assert isinstance(disclaimer, str) and disclaimer.strip(), (
        "the verdict is decision support, and the field that says so travels with it or the "
        "framing is lost"
    )


@pytest.mark.integration
async def test_program_status_is_reported_with_its_start_date_and_what_it_replaced(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """ROADMAP success criterion #1, over the real transport.

    Close the seeded lean_bulk period and open a `cut` period, commit, then call
    `fitness_get_training_program`: `program == "cut"`, `started_on` is the switch day,
    `previous_program == "lean_bulk"`, and `previous_period_ended_on` is that same day.
    """
    from mcp import Client

    from app.mcp.server import mcp

    active = await get_active_period(session, user_id=DEFAULT_USER_ID)
    assert active is not None
    switch_day = utc_now().date()
    # The partial unique index permits only one open period per user, so the seeded period
    # must be closed in the SAME transaction that opens the new one -- see
    # `conftest.GoldenBuilder.program_period`'s own docstring for the invariant.
    await session.execute(
        update(ProgramPeriod).where(ProgramPeriod.id == active.id).values(ended_on=switch_day)
    )
    await committed_history.program_period(program="cut", started_on=switch_day, ended_on=None)
    await session.commit()

    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool("fitness_get_training_program", {})

    assert result.is_error is False
    payload = result.structured_content
    assert payload is not None
    assert payload["data_available"] is True
    assert payload["program"] == "cut"
    assert payload["started_on"] == switch_day.isoformat()
    assert payload["previous_program"] == "lean_bulk"
    assert payload["previous_period_ended_on"] == switch_day.isoformat()


# ---------------------------------------------------------------------------
# D-08/MCP-02: the composed summary -- the "one call" criterion.
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_training_summary_composes_four_analytics(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """MCP-02's "one call" criterion, asserted as one call. T-06-20.

    PROJECT.md's Core Value names two questions -- "Am I progressing?" and "Which muscles are
    undertrained?" -- and this is the tool that must answer both without a four-tool chain. Each of
    the six elements below is one of them losing its answer if it goes missing.
    """
    from mcp import Client

    from app.mcp.server import mcp

    await _seed_reference_history(committed_history, session)

    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool("fitness_get_training_summary", {"weeks": 4})

    assert result.is_error is False
    payload = result.structured_content
    assert payload is not None
    assert payload["data_available"] is True

    assert payload["volume_by_week"], "no weekly volume: 'am I progressing?' loses its trend"
    assert len(payload["muscles"]) == CANONICAL_MUSCLE_GROUP_COUNT, (
        "fewer than 19 rows: 'which muscles are undertrained?' loses the zero rows that ARE the "
        "answer"
    )
    assert payload["recomposition_status"] is not None
    assert payload["recomposition_disclaimer"], (
        "T-06-09: the disclaimer is dropped exactly here if it is dropped anywhere -- this is the "
        "one response that flattens the recomposition verdict instead of embedding it whole"
    )
    assert payload["progression_verdict"] is not None
    assert payload["sessions_per_week"] is not None
