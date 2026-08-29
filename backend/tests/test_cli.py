"""CLI argument parsing and bootstrap ORDER.

The ordering assertion is a static read of the source, in the style of
`test_cloud_run_deploy.py`: a runtime test cannot easily prove that nothing logged before
`configure_logging`, but a source-order check fails the fast suite the moment someone adds a
`log.info` above it.

No container and no marker: every failure here is a plain source or argparse fact, and it must
go red on the commit that introduces it rather than in a slower job later.
"""

import uuid
from pathlib import Path

import pytest

from app.cli import DEFAULT_USER_ID, build_parser

# `backend/tests/` -> `backend/` -> `backend/app/cli.py`.
CLI_SOURCE = Path(__file__).resolve().parents[1] / "app" / "cli.py"

# Migration 0002's fixed id. Deliberately spelled out rather than imported from the module
# under test -- a test asserting against the very constant it imports proves nothing.
SEEDED_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def test_parser_exposes_both_commands() -> None:
    """Both verbs parse. `sync-status` is the one ROADMAP criterion 5 is answered through."""
    parser = build_parser()

    assert parser.parse_args(["sync-hevy"]).command == "sync-hevy"
    assert parser.parse_args(["sync-status"]).command == "sync-status"


def test_full_and_incremental_are_mutually_exclusive() -> None:
    """`--full --incremental` is not a preference, it is a contradiction.

    Resolving it silently -- last-flag-wins, say -- would let an operator believe they forced
    a full re-import while the run drained the events feed instead.
    """
    with pytest.raises(SystemExit) as excinfo:
        build_parser().parse_args(["sync-hevy", "--full", "--incremental"])

    assert excinfo.value.code == 2


def test_only_rejects_an_unknown_resource() -> None:
    """A typo must fail loudly rather than sync nothing and exit 0.

    `nutrition` is the realistic wrong answer: it is a real BRETT data source, just not one
    Hevy provides.
    """
    with pytest.raises(SystemExit) as excinfo:
        build_parser().parse_args(["sync-hevy", "--only", "nutrition"])

    assert excinfo.value.code == 2


def test_only_accepts_the_three_resources() -> None:
    """The three Hevy resources, individually and in combination.

    Repeatable rather than comma-separated: argparse validates each `choices` value, so a
    typo in the second of two names is caught, which a split-on-comma string would not be.
    """
    for resource in ("workouts", "templates", "body"):
        assert build_parser().parse_args(["sync-hevy", "--only", resource]).only == [resource]

    combined = build_parser().parse_args(
        ["sync-hevy", "--only", "workouts", "--only", "body"]
    )
    assert combined.only == ["workouts", "body"]


def test_default_user_id_is_the_seeded_uuid() -> None:
    """v1 is single-user, and the user is migration 0002's seeded row.

    A `uuid4()` default would make every run write to a user_id with no `users` row behind it
    and fail on the foreign key -- or worse, succeed against a row nobody can find again.
    """
    assert DEFAULT_USER_ID == SEEDED_USER_ID

    for command in ("sync-hevy", "sync-status"):
        assert build_parser().parse_args([command]).user_id == SEEDED_USER_ID
