"""The training-program READ tool (GOAL-01, ROADMAP success criterion #1; MCP-05, MCP-06).

This module holds READ tools only. It stays under the full `test_mcp_isolation._SESSION_WRITE`
ban like every other tool module -- it must therefore never appear in
`test_mcp_isolation._WRITE_ALLOWLIST`. The write side lives in the sibling module
`app/mcp/tools/program_switch.py`, kept separate on purpose: putting both tools in one file would
exempt this read tool from the write guard for no reason, and the allowlist would then have to
name a module that also contains a read tool instead of staying at exactly one write-only entry.
"""

from mcp.server.mcpserver import Context

from app.analytics.schemas import TrainingProgram
from app.db.repositories.programs import get_recent_periods
from app.mcp.context import AppContext
from app.mcp.tools._common import read_only_session, resolve_user_id, safe_tool
from app.mcp.tools.schemas import TrainingProgramResponse


def _degraded_program() -> TrainingProgramResponse:
    """GOAL-01's "I could not reach the data" payload, built by a factory for the same reason
    `body.py`'s are: each failure gets a fresh object, so no caller can mutate the
    placeholder the next one receives (`safe_tool`'s contract).

    Every field is None, and `data_available=False` is what distinguishes that from "you
    have never set a program" -- which is `data_available=True` with `program=None`.
    """
    return TrainingProgramResponse(
        data_available=False,
        program=None,
        started_on=None,
        previous_program=None,
        previous_period_started_on=None,
        previous_period_ended_on=None,
    )


@safe_tool(degraded=_degraded_program)
async def fitness_get_training_program(ctx: Context[AppContext]) -> TrainingProgramResponse:
    """Which training program is active, when it started, and which program it replaced.

    Takes no arguments, for the same reason the body-weight and recomposition tools do not:
    "what am I on" is always a question about now.
    """
    user_id = resolve_user_id(ctx)
    async with read_only_session(ctx) as session:
        periods = await get_recent_periods(session, user_id=user_id, limit=2)
    # `get_recent_periods` is newest-first, so [0] is the open period and [1] -- when it
    # exists -- is the one it replaced. Slicing rather than indexing so a user with no
    # history at all returns the honest all-None answer instead of raising.
    current = periods[0] if periods else None
    previous = periods[1] if len(periods) > 1 else None
    return TrainingProgramResponse(
        data_available=True,
        program=TrainingProgram(current.program) if current is not None else None,
        started_on=current.started_on if current is not None else None,
        previous_program=(TrainingProgram(previous.program) if previous is not None else None),
        previous_period_started_on=previous.started_on if previous is not None else None,
        previous_period_ended_on=previous.ended_on if previous is not None else None,
    )
