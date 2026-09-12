"""What Claude actually sees: the registry, the annotations, the schemas, the caps.

This file asserts the TOOL SURFACE -- the twenty-two names, their read-only annotations, their
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
        "fitness_get_weekly_report",
        "fitness_get_monthly_report",
        "fitness_get_weekly_volume",
        "fitness_get_muscle_group_volume",
        "fitness_get_training_frequency",
        "fitness_get_exercise_progression",
        "fitness_get_personal_records",
        "fitness_get_plateaus",
        "fitness_compare_periods",
        "fitness_get_body_measurement_trend",
        "fitness_get_body_weight_trend",
        "fitness_get_activity_trend",
        "fitness_get_nutrition_trend",
        "fitness_get_recomposition_status",
        "fitness_get_training_program",
        "fitness_switch_training_program",
        "fitness_log_physique_observation",
        "fitness_get_latest_physique_observation",
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


async def test_tool_registry_is_exactly_the_twenty_two(_mcp_state: None) -> None:
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


# The two deliberate exceptions, named. Everything not in here must be read-only, and this set is
# asserted to hold exactly two entries -- PITFALLS #14's requirement that the guard be WIDENED
# rather than relaxed. MCP-07/MCP-08: the second entry is a NON-destructive write, which is why the
# flags below became a per-tool mapping.
WRITE_TOOLS = frozenset({"fitness_switch_training_program", "fitness_log_physique_observation"})

# The four flags every tool's published `annotations` carries, excluding `title` (which is
# unrelated to the read-only/write claim and is `None` for every tool in this registry).
_WRITE_ANNOTATION_KEYS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")

# MCP-08. The four flags each write tool must ADVERTISE, per tool rather than uniformly.
#
# The previous shape -- one loop asserting every `readOnlyHint=false` tool carries
# `destructiveHint=True` -- was correct only while there was exactly one write tool. PHYS-06's
# append-only observation log is a write that destroys nothing, so a uniform assertion could only
# be satisfied by mislabelling it as destructive or by deleting the assertion for
# `fitness_switch_training_program`. Both are worse than a mapping.
#
# Written out as literals, like `EXPECTED_CAPS` above: importing the `ToolAnnotations` objects from
# `app.mcp.server` would make this test assert that a constant equals itself, and it would keep
# passing if someone flipped a flag on the object. These four values per tool ARE the contract.
EXPECTED_WRITE_ANNOTATIONS: dict[str, dict[str, bool]] = {
    "fitness_switch_training_program": {
        "readOnlyHint": False,
        # The switch reclassifies every future recomposition verdict.
        "destructiveHint": True,
        # The token is single-use; the second call with the same token is refused, not repeated.
        "idempotentHint": False,
        "openWorldHint": False,
    },
    "fitness_log_physique_observation": {
        "readOnlyHint": False,
        # PHYS-06: an append. Nothing is overwritten, and the correction path (PHYS-08's supersede)
        # retains the original row.
        "destructiveHint": False,
        # Two identical calls append TWO observations.
        "idempotentHint": False,
        "openWorldHint": False,
    },
}


async def test_annotations_are_an_exact_partition(_mcp_state: None) -> None:
    """MCP-05 / GOAL-04 / T-12-08 / MCP-08: twenty read-only tools and exactly two write tools.

    Written as a PARTITION rather than as "every tool except the known exception".
    Skipping an exception makes the assertion silently weaker with each new exception;
    partitioning it makes a third write tool fail here, which is where the review
    belongs. The spec DEFAULTS for `destructiveHint` and `openWorldHint` are `true`, so
    a tool registered without annotations advertises the opposite of what this project
    guarantees -- that is what `annotations is not None` below is really checking.

    These are HINTS. `test_mcp_readonly.py` drives an actual write through a tool
    session, and that is the enforcement; the token gate in `program_switch.py` and the
    per-tool refusal checks in `physique.py` are what constrain the write tools. The
    per-tool `EXPECTED_WRITE_ANNOTATIONS` mapping below is what makes the partition
    survive a second, non-destructive write tool without weakening the claim made for
    the first one.
    """
    assert len(WRITE_TOOLS) == 2, (
        "GOAL-04/MCP-08: exactly two write tools exist. A THIRD entry here is a third "
        "tool that must earn its own annotations, budget and doc entry."
    )
    assert set(EXPECTED_WRITE_ANNOTATIONS) == WRITE_TOOLS, (
        "MCP-08: every write tool needs its OWN annotation expectation. A write tool absent from "
        "EXPECTED_WRITE_ANNOTATIONS would be skipped by the per-tool loop below and would pass "
        f"this file unasserted. Missing: {sorted(WRITE_TOOLS - set(EXPECTED_WRITE_ANNOTATIONS))}"
    )

    from mcp import Client

    from app.mcp.server import mcp

    async with Client(mcp) as mcp_client:
        tools = (await mcp_client.list_tools()).tools

    by_dump = {tool.name: tool.model_dump(by_alias=True)["annotations"] for tool in tools}
    for name, tool in {tool.name: tool for tool in tools}.items():
        assert tool.annotations is not None, (
            f"MCP-05 violated: {name} carries no annotations at all, so it advertises the "
            "SPEC DEFAULTS -- destructive and open-world. Register it with "
            "`annotations=READ_ONLY` (or `WRITE_TOOL` if it genuinely writes)."
        )

    read_only_true = {name for name, ann in by_dump.items() if ann["readOnlyHint"] is True}
    read_only_false = {name for name, ann in by_dump.items() if ann["readOnlyHint"] is False}

    assert read_only_true == EXPECTED_TOOLS - WRITE_TOOLS, (
        "MCP-05 violated: the read-only-hint=True set does not match EXPECTED_TOOLS minus "
        f"WRITE_TOOLS. Got: {sorted(read_only_true)}"
    )
    assert read_only_false == WRITE_TOOLS, (
        "MCP-05 violated: the read-only-hint=False set is not exactly WRITE_TOOLS. "
        f"Got: {sorted(read_only_false)}"
    )
    for name in read_only_true:
        assert by_dump[name]["destructiveHint"] is False, (
            f"MCP-05 violated: read-only tool {name} advertises destructiveHint. The spec "
            f"default is true, so this is what an omitted flag looks like. "
            f"Got: {by_dump[name]}"
        )
    for name in read_only_false:
        four_flags = {key: by_dump[name][key] for key in _WRITE_ANNOTATION_KEYS}
        assert four_flags == EXPECTED_WRITE_ANNOTATIONS[name], (
            f"MCP-08 violated: write tool {name}'s published annotations are not its expected "
            f"per-tool set. Got: {four_flags}, expected: {EXPECTED_WRITE_ANNOTATIONS[name]}"
        )
    for name, annotations in by_dump.items():
        assert annotations["openWorldHint"] is False, (
            f"MCP-05 violated: {name} advertises openWorldHint. Every tool here reads this "
            f"project's own database and nothing else. Got: {annotations}"
        )


async def test_every_write_tool_publishes_explicit_write_annotations(_mcp_state: None) -> None:
    """T-12-07 / MCP-08: both write tools are registered OUTSIDE the shared `_TOOLS` loop.

    `fitness_switch_training_program` and `fitness_log_physique_observation` each have their own
    `mcp.add_tool` call with their own `ToolAnnotations` object. If either had been added to
    `_TOOLS` it would carry `READ_ONLY` and advertise `readOnlyHint=True` for a tool that commits
    -- the single most misleading thing this server could publish, and invisible from every other
    test in this file.
    """
    from mcp import Client

    from app.mcp.server import mcp

    async with Client(mcp) as mcp_client:
        tools = (await mcp_client.list_tools()).tools

    by_name = {tool.name: tool for tool in tools}
    for name, expected in EXPECTED_WRITE_ANNOTATIONS.items():
        annotations = by_name[name].model_dump(by_alias=True)["annotations"]
        four_flags = {key: annotations[key] for key in _WRITE_ANNOTATION_KEYS}
        assert four_flags == expected, (
            f"T-12-07/MCP-08 violated: {name}'s published annotations are wrong. "
            f"Got: {annotations}, expected: {expected}"
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

    Claude chooses between twenty-two tools on their names and descriptions alone. An empty or
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


def test_the_weekly_report_response_structurally_cannot_carry_a_physique_section() -> None:
    """ROADMAP Phase 18, criterion 1: the weekly report has NO `physique` attribute at all --
    a structural, tested absence via the declared field set, not omission by convention.

    This assertion cannot rest on the VALUE, and that is D-11's accepted consequence: a monthly
    report for a user who has never logged an observation also carries `physique=None`, so
    `None` no longer proves the period was weekly. Only the field set can.

    Mirrors the precedent `WeeklyReportResponse`'s own docstring already states for
    `narrative`.
    """
    from app.mcp.tools.reports import _degraded_weekly
    from app.mcp.tools.schemas import MonthlyReportResponse, WeeklyReportResponse

    assert "physique" not in WeeklyReportResponse.model_fields
    assert "physique" in MonthlyReportResponse.model_fields
    # The same claim against a REAL instance, not only the class declaration.
    assert not hasattr(_degraded_weekly(), "physique")
    assert "narrative" not in WeeklyReportResponse.model_fields, (
        "the narrative precedent this test mirrors must still hold"
    )
