"""Command-line entrypoint for Hevy sync.

    PYTHONPATH=backend uv run python -m app.cli sync-hevy
    PYTHONPATH=backend uv run python -m app.cli sync-status
    PYTHONPATH=backend uv run python -m app.cli mapping-gaps

Bootstrap order is load-bearing and is the same order `app/main.py` uses: configuration is
read first so a misconfigured process dies immediately, then logging is configured -- the
value scrubber needs `settings.secret_values()` -- and only then is anything that can emit a
log line constructed. A sync command that logged before `configure_logging` would write an
unredacted line, and the very first thing it has to log is a Hevy request (FOUND-05).

That invariant is enforced by a source-order test rather than a comment, which is why the
definitions below run `build_parser` then `main` and only then the two coroutines: everything
that touches a logger or an engine has to sit BELOW `configure_logging(settings)` in this
file, and Python resolves the forward references at call time.

This is a VERIFICATION and operations trigger, not the production schedule. Phase 7 decides
how sync actually runs in production (Cloud Run job, scheduler, or otherwise); this phase only
needs a way to invoke `HevySyncService`.
"""

import argparse
import asyncio
import sys
import uuid
from collections.abc import Sequence

import structlog
from sqlalchemy import select

from app.config import DEFAULT_USER_ID, Settings, get_settings
from app.db import session as db_session
from app.db.models.exercise import ExerciseTemplate
from app.integrations.hevy.client import build_hevy_client
from app.integrations.hevy.errors import HevyError
from app.integrations.hevy.sync import HevySyncService, SyncMode, resource_status
from app.logging import configure_logging
from app.normalization.exercise_map import DELIBERATELY_UNMAPPED
from app.normalization.resolver import unmapped_template_ids

# `DEFAULT_USER_ID` is migration 0002's fixed id, not uuid4(), and now lives in `app.config`
# because the MCP layer needs the same identity. v1 is single-user; `--user-id` exists so the CLI
# does not have to change when a second user does. A uuid4 default would write rows against
# a user_id with no `users` row behind it.

# The three Hevy resources, in the order `sync_all` walks them. Named for the operator
# ("body") rather than for the table ("body_measurements"), because this is a keystroke.
RESOURCE_CHOICES = ("workouts", "templates", "body")


def _add_user_id(parser: argparse.ArgumentParser) -> None:
    """Both subcommands take the same `--user-id`, so it is declared in one place."""
    parser.add_argument(
        "--user-id",
        type=uuid.UUID,
        default=DEFAULT_USER_ID,
        help="Which user's data to act on. Defaults to the single seeded v1 user.",
    )


def build_parser() -> argparse.ArgumentParser:
    """The whole command surface. Pure: it parses, and reads no settings and no database.

    Kept side-effect free so the parser tests run in the fast suite without a container, an
    environment variable or a Hevy key.
    """
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="Trigger and inspect the Hevy sync.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    sync = subcommands.add_parser("sync-hevy", help="Sync Hevy data into PostgreSQL.")
    # Mutually exclusive rather than last-flag-wins: `--full --incremental` is a
    # contradiction, and resolving it silently would let an operator believe they forced a
    # full re-import while the run drained the events feed instead.
    selected_mode = sync.add_mutually_exclusive_group()
    selected_mode.add_argument(
        "--full",
        action="store_true",
        help="Force the full /v1/workouts import instead of the events feed.",
    )
    selected_mode.add_argument(
        "--incremental",
        action="store_true",
        help="Force the /v1/workouts/events drain. Refuses if no full sync has completed.",
    )
    sync.add_argument(
        "--only",
        action="append",
        choices=RESOURCE_CHOICES,
        help="Act on only the named resource. Repeatable. Default: all three.",
    )
    _add_user_id(sync)

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


def _requested_mode(args: argparse.Namespace) -> SyncMode:
    """`--full` / `--incremental` / neither, in the service's own vocabulary."""
    if args.full:
        return "full"
    if args.incremental:
        return "incremental"
    return "auto"


def _safe_detail(exc: BaseException) -> str:
    """The message an exception was CONSTRUCTED with, or its class name.

    Used only for the `RuntimeError` this codebase raises itself. Reading `args[0]` rather
    than rendering the exception keeps the call that would reproduce a pydantic
    ValidationError's `input_value=` -- and with it this person's workout titles -- out of
    this file entirely (T-03-45).
    """
    first = exc.args[0] if exc.args else None
    return first if isinstance(first, str) and first else type(exc).__name__


async def _sync_selected(
    service: HevySyncService, *, resources: Sequence[str], mode: SyncMode
) -> None:
    """`--only`, implemented by calling the individual service methods.

    Deliberately NOT a filter parameter threaded into `sync_all`: keeping `sync_all` free of
    branching is what makes the default path readable, and this is its only subset caller.
    The order matches `sync_all`'s -- templates, then workouts, then body.
    """
    if "templates" in resources:
        await service.sync_templates()
    if "workouts" in resources:
        if await service.resolve_mode(mode) == "full":
            await service.sync_workouts_full()
        else:
            await service.sync_workouts_incremental()
    if "body" in resources:
        await service.sync_body()


async def _run_sync(settings: Settings, args: argparse.Namespace) -> int:
    """Own the engine's lifetime, run the service, and fail without naming a credential."""
    log = structlog.get_logger()
    mode = _requested_mode(args)
    resources: tuple[str, ...] = tuple(args.only or ())

    engine = db_session.make_engine(settings)
    sessionmaker = db_session.make_sessionmaker(engine)
    log.info("hevy_cli_started", command="sync-hevy", mode=mode, only=resources or "all")
    try:
        async with build_hevy_client(settings) as client:
            service = HevySyncService(client, sessionmaker, user_id=args.user_id)
            if resources:
                await _sync_selected(service, resources=resources, mode=mode)
            else:
                await service.sync_all(mode=mode)
    except HevyError as exc:
        # `safe_message` is the curated, opt-in channel every Hevy error populates by hand;
        # the fallback is the class name. Neither is ever derived from the API key.
        log.error("hevy_cli_failed", reason=type(exc).__name__)
        print(f"Hevy sync failed: {exc.safe_message or type(exc).__name__}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        # `build_hevy_client`'s own refusal: it names the ENV VAR the operator has to set and
        # never its value, which is precisely the detail worth printing.
        log.error("hevy_cli_failed", reason=type(exc).__name__)
        print(f"Hevy sync failed: {_safe_detail(exc)}", file=sys.stderr)
        return 1
    finally:
        # Every exit path closes both pools: `async with` releases the HTTP client, this
        # releases the database connections (T-03-47).
        await engine.dispose()
        log.info("hevy_cli_stopped", command="sync-hevy")
    return 0


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


async def _run_mapping_gaps(settings: Settings, args: argparse.Namespace) -> int:
    """NORM-01/D-03 as operator output: which templates resolve to no canonical muscle.

    Splits "unmapped" into the two states that look identical in the database but mean
    opposite things: `deliberate` (an id listed in `DELIBERATELY_UNMAPPED` -- cardio,
    conditioning, `neck`; the intended end state) and `GAP` (nobody has curated it yet).
    Without the split, a curation backlog and a finished taxonomy produce the same output.

    Local-only, like `sync-status`: it reads the database and never needs `HEVY_API_KEY`.
    """
    log = structlog.get_logger()
    engine = db_session.make_engine(settings)
    sessionmaker = db_session.make_sessionmaker(engine)
    log.info("hevy_cli_started", command="mapping-gaps")
    try:
        async with sessionmaker() as session:
            external_ids = await unmapped_template_ids(session, user_id=args.user_id)
            rows = (
                await session.execute(
                    select(ExerciseTemplate.external_id, ExerciseTemplate.title).where(
                        ExerciseTemplate.user_id == args.user_id,
                        ExerciseTemplate.external_id.in_(external_ids),
                    )
                )
            ).all()
            titles: dict[str, str] = {row[0]: row[1] for row in rows}
    finally:
        await engine.dispose()
        log.info("hevy_cli_stopped", command="mapping-gaps")

    deliberate = 0
    for external_id in external_ids:
        if external_id in DELIBERATELY_UNMAPPED:
            deliberate += 1
            flag = "deliberate"
        else:
            flag = "GAP"
        # `?` rather than a blank: a template row that vanished between the two reads is a
        # different problem from one that was never given a title.
        print(f"{external_id}  {titles.get(external_id, '?')}  [{flag}]")
    gaps = len(external_ids) - deliberate
    print(f"{len(external_ids)} unmapped ({deliberate} deliberate, {gaps} gaps)")

    # Exit 0 even with gaps. This is an inspection command, and D-03 makes an unmapped
    # exercise a supported state -- exiting non-zero would turn a curation backlog into a
    # broken pipeline the moment this is ever wired into CI.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
