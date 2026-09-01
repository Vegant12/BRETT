"""What Claude actually sees: the registry, the annotations, the schemas, the caps.

This file asserts the TOOL SURFACE -- the thirteen names, their read-only annotations, their
published input and output schemas, and the `maximum` on every window argument. It does not
assert what any tool returns; `test_mcp_tools.py` owns that, and `test_mcp_readonly.py` owns the
runtime read-only enforcement that the annotations here only *claim*.

**Container-free, and deliberately not marked `integration`, except for the three tests that call
a tool.** `tools/list` issues no query, so the `_mcp_state` fixture below builds a session factory
over an engine that is never connected to -- the same trick `test_mcp_mount.py`'s `mcp_server`
fixture uses, and for the same reason: a schema regression must fail the FAST suite on the commit
that introduces it. Entering `Client(mcp)` runs `mcp_lifespan`, which reads
`app.state.sessionmaker`, so *something* has to populate it; a real Postgres container is not that
something.

**`from app.mcp.server import mcp` is repeated inside every test and never written at module
scope.** `conftest` seeds the MCP environment at module import, and `app.mcp.server` freezes the
token verifier and the Host allowlist at ITS import. A module-scope import here would run that
bootstrap during pytest's collection phase, before the seeding has necessarily happened.

The highest-risk assertion in the file is `test_decorated_tools_still_publish_schemas`. Every
Phase 6 tool is wrapped in `_common.safe_tool`, and a decorator that forgot `functools.wraps`
would publish `outputSchema: null` and an `inputSchema` derived from `(*args, **kwargs)` -- with
no error anywhere. The tools would still work over the wire; Claude would simply have no argument
names and no output shape to reason about.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# The complete tool surface as of Phase 6 (MCP-02). A frozenset rather than a list: the registry
# is a SET of names, and asserting an order would make an `add_tool` reshuffle look like a
# regression.
EXPECTED_TOOLS = frozenset(
    {
        "fitness_ping",
        "fitness_get_recent_workouts",
        "fitness_get_workout",
        "fitness_get_training_summary",
        "fitness_get_weekly_volume",
        "fitness_get_muscle_group_volume",
        "fitness_get_training_frequency",
        "fitness_get_exercise_progression",
        "fitness_get_personal_records",
        "fitness_get_plateaus",
        "fitness_compare_periods",
        "fitness_get_body_weight_trend",
        "fitness_get_recomposition_status",
    }
)

# The `maximum` each window/limit parameter must ADVERTISE, per D-04/D-08/D-10. Duplicated from
# `_common`'s cap constants on purpose: importing `MAX_WEEKS` here would make the test assert that
# the constant equals itself, and it would keep passing if someone changed the constant. These
# numbers are the contract, so they are written out as literals.
EXPECTED_CAPS = {
    ("fitness_get_weekly_volume", "weeks"): 52,
    ("fitness_get_muscle_group_volume", "weeks"): 52,
    ("fitness_get_training_frequency", "weeks"): 52,
    ("fitness_get_exercise_progression", "weeks"): 52,
    ("fitness_get_personal_records", "weeks"): 52,
    ("fitness_get_plateaus", "lookback_weeks"): 52,
    # 12, not 52. This response carries a per-week row AND a 19-row muscle rollup, so its size
    # grows with the window where the single-purpose tools' does not (D-08, T-06-05).
    ("fitness_get_training_summary", "weeks"): 12,
    ("fitness_get_recent_workouts", "limit"): 25,
}


@pytest.fixture
def _mcp_state() -> Iterator[None]:
    """Populate `app.state.sessionmaker` without a container.

    `Client(mcp)` enters `mcp_lifespan`, which reads `app.state.sessionmaker`. Outside a
    `TestClient` the FastAPI lifespan has never run, so that attribute does not exist and every
    test here would die on `AttributeError` before reaching an assertion. SQLAlchemy defers
    connection until first use and `tools/list` issues no query, so this engine is created and
    never dialled.
    """
    from app.config import get_settings
    from app.main import app

    engine = create_async_engine(get_settings().async_database_url)
    preexisting = getattr(app.state, "sessionmaker", None)
    app.state.sessionmaker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        yield
    finally:
        if preexisting is not None:
            app.state.sessionmaker = preexisting
        engine.sync_engine.dispose()


# Every assertion below reads `tool.model_dump(by_alias=True)`, never the snake_case Python
# attributes. `by_alias` is not cosmetic: the wire names are `inputSchema`, `outputSchema` and
# `readOnlyHint`, and asserting on the attributes would test the SDK's internal model rather than
# the payload Claude actually parses.


async def test_tool_registry_is_exactly_the_thirteen(_mcp_state: None) -> None:
    """MCP-02: the whole tool surface, named.

    An exact set rather than a count. A count of 13 stays green through a rename, and a renamed
    tool is a tool every saved Claude conversation now calls by a name that no longer exists.
    """
    from mcp import Client

    from app.mcp.server import mcp

    async with Client(mcp) as mcp_client:
        names = {tool.name for tool in (await mcp_client.list_tools()).tools}

    assert names == EXPECTED_TOOLS, (
        "MCP-02: the registered tool set is not the expected one. "
        f"Registered but unexpected: {sorted(names - EXPECTED_TOOLS)}. "
        f"Expected but missing: {sorted(EXPECTED_TOOLS - names)}. "
        "A name on both lists is a RENAME -- update EXPECTED_TOOLS and remember that every "
        "existing Claude conversation still calls the old name."
    )


async def test_every_tool_is_annotated_read_only(_mcp_state: None) -> None:
    """MCP-05 / T-06-03: no tool advertises itself as destructive or open-world.

    The spec DEFAULTS for `destructiveHint` and `openWorldHint` are `true`, so a tool registered
    without annotations advertises the opposite of what this project guarantees. `server.py`
    applies one shared `READ_ONLY` object in a loop, which makes this true today; this test is
    what keeps it true after someone adds a fourteenth tool with a hand-written `add_tool` call.

    These are HINTS. The SDK's docs say annotations "should not be relied upon for security
    enforcement" -- `test_mcp_readonly.py` drives an actual write through a tool session, and that
    is the enforcement. This test only asserts that the claim is being made.
    """
    from mcp import Client

    from app.mcp.server import mcp

    async with Client(mcp) as mcp_client:
        tools = (await mcp_client.list_tools()).tools

    for tool in tools:
        assert tool.annotations is not None, (
            f"MCP-05 violated: {tool.name} carries no annotations at all, so it advertises the "
            "SPEC DEFAULTS -- destructive and open-world. Register it with "
            "`annotations=READ_ONLY`."
        )
        annotations = tool.model_dump(by_alias=True)["annotations"]
        assert annotations["readOnlyHint"] is True, (
            f"MCP-05 violated: {tool.name} does not advertise readOnlyHint. Got: {annotations}"
        )
        assert annotations["destructiveHint"] is False, (
            f"MCP-05 violated: {tool.name} advertises destructiveHint. The spec default is true, "
            f"so this is what an omitted flag looks like. Got: {annotations}"
        )
        assert annotations["openWorldHint"] is False, (
            f"MCP-05 violated: {tool.name} advertises openWorldHint. Every tool here reads this "
            f"project's own database and nothing else. Got: {annotations}"
        )


async def test_decorated_tools_still_publish_schemas(_mcp_state: None) -> None:
    """RESEARCH assumption A1: `@safe_tool` erases nothing. The highest-risk claim in the phase.

    A decorator without `functools.wraps` publishes an `inputSchema` derived from the WRAPPER's
    `(*args, **kwargs)` signature and `outputSchema: null` -- silently. Nothing raises, nothing
    logs, and the tool still "works" over the wire; Claude simply receives no argument names and
    no output shape, and every call it composes is a guess.

    If this ever fails, the fix is NOT to loosen the assertion. Drop `safe_tool` and inline the
    `try`/`except` in all twelve tools -- the exception guard (MCP-06) is not negotiable and the
    schema is not either.
    """
    from mcp import Client

    from app.mcp.server import mcp

    async with Client(mcp) as mcp_client:
        tools = (await mcp_client.list_tools()).tools

    for tool in tools:
        published = tool.model_dump(by_alias=True)
        output_schema = published["outputSchema"]
        assert isinstance(output_schema, dict) and output_schema, (
            f"A1 violated: {tool.name} publishes no outputSchema. This is what a decorator "
            "without `functools.wraps` looks like -- see `_common.safe_tool`."
        )
        properties = published["inputSchema"].get("properties", {})
        for leaked in ("args", "kwargs", "ctx"):
            assert leaked not in properties, (
                f"A1 violated: {tool.name} publishes {leaked!r} as a model-facing argument. "
                f"`args`/`kwargs` mean the wrapper's signature leaked; `ctx` means the parameter "
                f"is not annotated `Context[AppContext]`. Got: {sorted(properties)}"
            )


async def test_no_tool_publishes_a_user_id_argument(_mcp_state: None) -> None:
    """ASVS V4 / T-06-02: whose data this is is never the model's to choose.

    `_common.resolve_user_id` resolves the tenant SERVER-side. Threading `user_id` out to Claude
    as an argument would turn an access-control convention into an IDOR, and the value would be
    one a model can hallucinate.
    """
    from mcp import Client

    from app.mcp.server import mcp

    async with Client(mcp) as mcp_client:
        tools = (await mcp_client.list_tools()).tools

    for tool in tools:
        properties = tool.model_dump(by_alias=True)["inputSchema"].get("properties", {})
        assert "user_id" not in properties, (
            f"T-06-02 violated: {tool.name} publishes `user_id` as a tool argument. That is an "
            "IDOR by construction -- the model would be choosing the tenant. Resolve it through "
            "`_common.resolve_user_id` instead."
        )


async def test_no_tool_publishes_an_exercise_template_id_argument(_mcp_state: None) -> None:
    """D-01: Claude asks by NAME. A Hevy template id is never a parameter.

    The ids are opaque -- 8-char hex for Hevy's built-ins, full UUIDs for user-custom templates --
    and carry nothing a model could reason about. An id argument is therefore a value Claude can
    only echo back from an earlier response or invent, and the invented case answers a progression
    question about an exercise that does not exist.
    """
    from mcp import Client

    from app.mcp.server import mcp

    async with Client(mcp) as mcp_client:
        tools = (await mcp_client.list_tools()).tools

    for tool in tools:
        properties = tool.model_dump(by_alias=True)["inputSchema"].get("properties", {})
        assert "exercise_template_external_id" not in properties, (
            f"D-01 violated: {tool.name} takes an opaque Hevy template id as an argument. Take "
            "the exercise NAME and resolve it with `_common.find_templates_by_title`."
        )


async def test_window_caps_are_published(_mcp_state: None) -> None:
    """D-04 / D-08 / D-10 / T-06-05: every bound is ADVERTISED, not just enforced.

    A cap checked only in the tool body is a cap Claude discovers by being rejected. Publishing
    `{"minimum": 1, "maximum": 52}` in `inputSchema` prevents the bad call instead of reporting
    it, and the SDK enforces the published bound before the body runs (see the test below).
    """
    from mcp import Client

    from app.mcp.server import mcp

    async with Client(mcp) as mcp_client:
        tools = (await mcp_client.list_tools()).tools

    by_name = {tool.name: tool for tool in tools}
    for (tool_name, parameter), expected_max in EXPECTED_CAPS.items():
        properties = by_name[tool_name].model_dump(by_alias=True)["inputSchema"]["properties"]
        assert parameter in properties, (
            f"{tool_name} no longer publishes a `{parameter}` argument at all. "
            f"Got: {sorted(properties)}"
        )
        schema = properties[parameter]
        assert schema.get("maximum") == expected_max, (
            f"T-06-05 violated: {tool_name}.{parameter} advertises maximum "
            f"{schema.get('maximum')!r}, expected {expected_max}. The published bound is the "
            "control -- an unbounded window is an unbounded response."
        )
        assert schema.get("minimum") == 1, (
            f"{tool_name}.{parameter} advertises minimum {schema.get('minimum')!r}, expected 1. "
            "A zero or negative window divides a per-week rate by zero or by a negative number."
        )


@pytest.mark.integration
async def test_a_request_above_the_cap_is_rejected_before_the_body_runs(
    client: TestClient,
) -> None:
    """T-06-05: the published `maximum` is enforced by the SDK, not by the tool.

    Argument validation happens in `FuncMetadata.call_fn_with_arg_validation`, which runs BEFORE
    `fn` is invoked. That means this rejection cannot be intercepted in the tool body and cannot
    be turned into the `data_available=False` shape every other failure in this phase takes -- it
    surfaces as `is_error=True` with no structured content.

    That is the accepted trade for advertising `"maximum": 52`. A model that reads the schema
    never sends `weeks=999`; a model that does not gets a protocol-level rejection rather than a
    52-week answer to a 999-week question. What matters is that no database work happens.
    """
    from mcp import Client

    from app.mcp.server import mcp

    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool("fitness_get_weekly_volume", {"weeks": 999})

    assert result.is_error is True, (
        "T-06-05: `weeks=999` was accepted. The `Field(le=MAX_WEEKS)` bound is missing or the "
        "cap was raised without updating EXPECTED_CAPS."
    )
    assert result.structured_content is None, (
        "A validation rejection must carry no structured content -- the tool body never ran, so "
        f"there is nothing to report. Got: {result.structured_content!r}"
    )


@pytest.mark.integration
async def test_a_malformed_argument_type_is_rejected_before_the_body_runs(
    client: TestClient,
) -> None:
    """DEPLOY-03 / ASVS V5: type validation happens in the SDK, not in the tool.

    `FuncMetadata.call_fn_with_arg_validation` runs before `fn` is invoked, so a string where an
    int is published cannot be intercepted in the tool body and cannot be turned into the
    `data_available=False` shape. It surfaces as `is_error=True` with no structured content, and
    -- the point of the test -- no database work happens at all.

    Tool arguments are MODEL-generated and therefore structurally untrusted. `weeks` is what
    `window_from_weeks` turns into a date range, and a coerced `"four"` would be a window nobody
    asked for rather than a rejected call.
    """
    from mcp import Client

    from app.mcp.server import mcp

    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool("fitness_get_weekly_volume", {"weeks": "four"})

    assert result.is_error is True, (
        "DEPLOY-03 violated: fitness_get_weekly_volume accepted weeks='four'. The published "
        "integer schema is the only thing standing between a model's typo and a query. "
        f"Got: is_error={result.is_error}"
    )
    assert result.structured_content is None, (
        "A validation rejection must carry no structured content -- the tool body never ran, so "
        f"there is nothing to report. Got: {result.structured_content!r}"
    )


@pytest.mark.integration
async def test_a_missing_required_argument_is_rejected_before_the_body_runs(
    client: TestClient,
) -> None:
    """DEPLOY-03 / ASVS V5: a required parameter with no default must stay required.

    `fitness_get_exercise_progression.exercise_name` is the one tool argument in the registry
    that carries no default, and that is deliberate: D-01 says Claude asks by NAME, so there is
    no sensible exercise to fall back to. The regression this guards is not a crash -- it is a
    default quietly appearing. A tool that accepted `{}` would answer a progression question
    about whichever exercise the default named, confidently and in the right shape, and the only
    symptom would be a coaching answer about the wrong lift.

    Rejected by `FuncMetadata.call_fn_with_arg_validation` before `fn` runs, so like the two
    cases above it surfaces as `is_error=True` with no structured content and touches no data.
    """
    from mcp import Client

    from app.mcp.server import mcp

    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool("fitness_get_exercise_progression", {})

    assert result.is_error is True, (
        "DEPLOY-03 violated: fitness_get_exercise_progression accepted a call with no arguments. "
        "`exercise_name` has no default, and it must not acquire one -- a defaulted exercise is "
        f"a confident answer about the wrong lift. Got: is_error={result.is_error}"
    )
    assert result.structured_content is None, (
        "A validation rejection must carry no structured content -- the tool body never ran, so "
        f"there is nothing to report. Got: {result.structured_content!r}"
    )


async def test_every_tool_has_a_description(_mcp_state: None) -> None:
    """The description is the tool's entire pitch to the model.

    Claude chooses between thirteen tools on their names and descriptions alone. An empty or
    one-word description is not a cosmetic problem: it is a tool that gets called for the wrong
    question, or never called at all, and the symptom is "Claude ignored my data" rather than
    anything that looks like a bug.
    """
    from mcp import Client

    from app.mcp.server import mcp

    async with Client(mcp) as mcp_client:
        tools = (await mcp_client.list_tools()).tools

    for tool in tools:
        assert isinstance(tool.description, str) and len(tool.description) >= 20, (
            f"{tool.name} publishes the description {tool.description!r}. It is what Claude reads "
            "to decide whether this is the tool for the question being asked."
        )


async def test_ping_is_still_registered_first_class(_mcp_state: None) -> None:
    """D-08: the Phase 2 canary survived the Phase 6 registration.

    `fitness_ping` is the one tool that does a bare `SELECT 1` through the lifespan-wired session
    factory, so it is the cheapest available proof that the MCP layer can reach the database at
    all. When twelve analytics tools all return `data_available=False`, this is the tool that
    distinguishes "the database is unreachable" from "twelve tools have the same bug".

    Both output fields are asserted required because `status` alone would let a refactor drop
    `database` -- the field that carries the entire answer.
    """
    from mcp import Client

    from app.mcp.server import mcp

    assert "fitness_ping" in EXPECTED_TOOLS

    async with Client(mcp) as mcp_client:
        tools = (await mcp_client.list_tools()).tools

    ping = next(tool for tool in tools if tool.name == "fitness_ping")
    output_schema = ping.model_dump(by_alias=True)["outputSchema"]

    assert set(output_schema["required"]) == {"status", "database"}
    assert set(output_schema["properties"]) == {"status", "database"}
