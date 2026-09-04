"""BRETT's only MCP write path: a two-call, server-issued-token confirmation (GOAL-03,
ROADMAP success criteria #3 and #4; PITFALLS #13, #14, #15).

`fitness_switch_training_program` is the ONE tool under `app/mcp/` allowed to commit.
`test_mcp_isolation._WRITE_ALLOWLIST` names this module, and only this module, and asserts
that allowlist holds exactly one entry -- a second write tool either fails the write-import
ban (no allowlist at all) or fails that length assertion.

PITFALLS #13's whole point is that a plain boolean confirmation flag is a naming convention
rather than a gate -- a model can set it `true` on the very first call, and `ctx.elicit()` is
not a guaranteed human gate either. The only thing a model cannot manufacture is a value the
server minted and stored. So there is no boolean confirmation argument anywhere in this
module's tool signature: the gate is `confirmation_token`, a server-issued, single-use,
short-lived, target-bound nonce.

This module must NOT import the read-only session helper from `_common` -- it has no
read-only path, by design, and importing that helper here would be a standing invitation to
reach for the wrong one.

Per 12-RESEARCH.md Pitfall A, this module must also NOT import `insert`, `update` or `delete`
from `sqlalchemy` (or `sqlalchemy` itself) -- `test_mcp_isolation._WRITE_IMPORT` bans that
across the WHOLE `app/mcp/` package with NO allowlist. Every write statement lives in
`app/db/repositories/programs.py`; this module only calls into it.
"""

from typing import Annotated

from mcp.server.mcpserver import Context
from pydantic import Field

from app.analytics.schemas import TrainingProgram
from app.db.repositories.programs import (
    close_period_and_open_new,
    consume_switch_token,
    get_active_period,
    issue_switch_token,
)
from app.mcp.context import AppContext
from app.mcp.tools._common import local_today, resolve_user_id, safe_tool, writable_session
from app.mcp.tools.schemas import ProgramSwitchResponse, ProgramSwitchStatus

# The single reason text shared by every refusal path (missing token, wrong-program token,
# expired token, already-consumed token, and the period having moved between issue and
# confirm). T-12-25: distinguishing the four causes would tell a caller which guess was
# closest -- an oracle. A model told this should start over with a token-free call.
_REFUSAL_REASON = (
    "The switch was not applied. The confirmation token was missing, did not match this "
    "program, had expired, had already been used, or the active program changed since it was "
    "issued. Call fitness_switch_training_program again with just `program` (no token) to get "
    "a fresh confirmation token."
)


def _degraded_switch() -> ProgramSwitchResponse:
    """`safe_tool`'s exception payload. `UNKNOWN`, never `NOT_APPLIED` (PITFALLS #15).

    An exception here means the server does not know whether the commit landed -- which is a
    different fact from knowing it did not. `NOT_APPLIED` would invite an immediate retry,
    and a retry after a successful-but-unreported commit is a SECOND switch. So the reason
    text instructs the model to read the current program back instead.
    """
    return ProgramSwitchResponse(
        data_available=False,
        switch_status=ProgramSwitchStatus.UNKNOWN,
        reason=(
            "Could not confirm whether the switch was applied. Call "
            "fitness_get_training_program to read the current program before doing anything "
            "else -- do not retry this call."
        ),
        requested_program=None,
        active_program=None,
        previous_program=None,
        previous_period_started_on=None,
        switched_on=None,
        confirmation_token=None,
        expires_at=None,
    )


@safe_tool(degraded=_degraded_switch)
async def fitness_switch_training_program(
    ctx: Context[AppContext],
    program: Annotated[
        TrainingProgram,
        Field(
            description=(
                "The program to switch TO: 'lean_bulk', 'cut' or 'recomp'. Required on both "
                "calls -- the confirmation token is bound to this exact value."
            )
        ),
    ],
    confirmation_token: Annotated[
        str | None,
        Field(
            description=(
                "Omit on the first call. The first call writes NOTHING and returns a "
                "one-time token; relay its warning to the user, and only if they confirm, "
                "call again echoing that exact token. Tokens expire in 5 minutes, work once, "
                "and only for the program they were issued for."
            )
        ),
    ] = None,
) -> ProgramSwitchResponse:
    """Switch the active training program. TWO CALLS ARE REQUIRED.

    Call once with just `program` to receive a warning and a one-time confirmation token;
    nothing changes. Show the user the warning, and only after they agree, call a second time
    with the same `program` and the exact token. Never invent, guess or reuse a token.
    """
    user_id = resolve_user_id(ctx)
    async with writable_session(ctx) as session:
        active = await get_active_period(session, user_id=user_id)
        if active is None:
            # No program history exists yet for this user. Nothing to switch FROM, so nothing
            # is written -- the session closing rolls back the read-only work above.
            return ProgramSwitchResponse(
                data_available=True,
                switch_status=ProgramSwitchStatus.NOT_APPLIED,
                reason="No training program history exists yet. There is nothing to switch.",
                requested_program=program,
                active_program=None,
                previous_program=None,
                previous_period_started_on=None,
                switched_on=None,
                confirmation_token=None,
                expires_at=None,
            )

        if confirmation_token is None:
            active_program = TrainingProgram(active.program)
            if active_program is program:
                # A no-op switch must not mint a credential -- issuing a token here would be
                # a write-shaped side effect for a call that changes nothing. Nothing is
                # written; the session closing rolls back.
                return ProgramSwitchResponse(
                    data_available=True,
                    switch_status=ProgramSwitchStatus.NOT_APPLIED,
                    reason=f"'{program.value}' is already the active program. Nothing to switch.",
                    requested_program=program,
                    active_program=active_program,
                    previous_program=None,
                    previous_period_started_on=None,
                    switched_on=None,
                    confirmation_token=None,
                    expires_at=None,
                )

            nonce, expires_at = await issue_switch_token(
                session,
                user_id=user_id,
                from_period_id=active.id,
                to_program=program,
            )
            response = ProgramSwitchResponse(
                data_available=True,
                switch_status=ProgramSwitchStatus.NOT_APPLIED,
                reason=(
                    f"Nothing has changed yet. Switching from '{active_program.value}' to "
                    f"'{program.value}' will change how future recomposition verdicts are "
                    "classified. Confirm with the user, then call this tool again with the "
                    "same `program` and this exact `confirmation_token` to apply it."
                ),
                requested_program=program,
                active_program=active_program,
                previous_program=None,
                previous_period_started_on=None,
                switched_on=None,
                confirmation_token=nonce,
                expires_at=expires_at,
            )
            # The commit is the LAST statement in this branch (PITFALLS #15): nothing may run
            # after it, because an exception past a successful commit degrades to `unknown` on
            # a token issue that actually landed.
            await session.commit()
            return response

        from_period_id = await consume_switch_token(
            session, user_id=user_id, nonce=confirmation_token, to_program=program
        )
        if from_period_id is None:
            # Missing, wrong-program, expired or already-consumed -- all indistinguishable on
            # purpose (T-12-25). Nothing was written; the session closing rolls back the
            # attempted consume.
            return ProgramSwitchResponse(
                data_available=True,
                switch_status=ProgramSwitchStatus.NOT_APPLIED,
                reason=_REFUSAL_REASON,
                requested_program=program,
                active_program=None,
                previous_program=None,
                previous_period_started_on=None,
                switched_on=None,
                confirmation_token=None,
                expires_at=None,
            )

        # D-09: the new period always starts on the user's local today, never a caller-supplied
        # or backdated date.
        today = await local_today(session, user_id=user_id)
        new_period = await close_period_and_open_new(
            session,
            user_id=user_id,
            from_period_id=from_period_id,
            to_program=program,
            today=today,
        )
        if new_period is None:
            # The period the nonce was issued against is no longer open -- something else
            # switched the program between issue and confirm. Do not commit.
            return ProgramSwitchResponse(
                data_available=True,
                switch_status=ProgramSwitchStatus.NOT_APPLIED,
                reason=_REFUSAL_REASON,
                requested_program=program,
                active_program=None,
                previous_program=None,
                previous_period_started_on=None,
                switched_on=None,
                confirmation_token=None,
                expires_at=None,
            )

        response = ProgramSwitchResponse(
            data_available=True,
            switch_status=ProgramSwitchStatus.APPLIED,
            reason=None,
            requested_program=program,
            active_program=program,
            previous_program=TrainingProgram(active.program),
            previous_period_started_on=active.started_on,
            switched_on=today,
            confirmation_token=None,
            expires_at=None,
        )
        # Again the LAST statement inside the `async with` (PITFALLS #15): anything after it
        # can raise, and an exception after a successful commit is reported as `unknown` on a
        # switch that actually applied.
        await session.commit()
        return response
