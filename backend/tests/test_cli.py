"""CLI argument parsing and bootstrap ORDER.

The ordering assertion is a static read of the source, in the style of
`test_cloud_run_deploy.py`: a runtime test cannot easily prove that nothing logged before
`configure_logging`, but a source-order check fails the fast suite the moment someone adds a
`log.info` above it.

No container and no marker: every failure here is a plain source or argparse fact, and it must
go red on the commit that introduces it rather than in a slower job later.
"""

import inspect
import uuid
from pathlib import Path

import pytest

from app.cli import DEFAULT_USER_ID, _run_mapping_gaps, build_parser

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


def test_parser_exposes_mapping_gaps() -> None:
    """The curation report is a first-class verb, not an ad-hoc SQL query in a summary."""
    assert build_parser().parse_args(["mapping-gaps"]).command == "mapping-gaps"

    other_user = uuid.UUID("00000000-0000-0000-0000-0000000000ff")
    parsed = build_parser().parse_args(["mapping-gaps", "--user-id", str(other_user)])
    assert parsed.user_id == other_user
    assert build_parser().parse_args(["mapping-gaps"]).user_id == SEEDED_USER_ID


def test_mapping_gaps_is_not_a_gate() -> None:
    """D-03: an unmapped exercise is a supported state, not a build failure.

    Asserted against the source rather than by calling it, because reproducing "there are
    gaps" at runtime needs a container and a seeded database, and the property worth
    protecting is simply that no branch of this function can ever hand back a non-zero code.
    """
    returns = [
        line.strip()
        for line in inspect.getsource(_run_mapping_gaps).splitlines()
        if line.strip().startswith("return")
    ]

    assert returns == ["return 0"], (
        "D-03 violated: `_run_mapping_gaps` can exit non-zero, which turns a curation "
        f"backlog into a broken pipeline the moment it is wired into CI. Found: {returns}"
    )


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


def test_parser_exposes_backfill_apple_health() -> None:
    """HEALTH-10 is a first-class verb, not a script somebody pastes into a REPL.

    The path is read back as a `Path` rather than a string because `run_backfill` and
    `format_summary` both take one, and an `str` reaching them would only fail deep inside the
    parse -- after the operator has already been told the command started.
    """
    parsed = build_parser().parse_args(["backfill-apple-health", "export.xml", "--dry-run"])

    assert parsed.command == "backfill-apple-health"
    assert parsed.path == Path("export.xml")
    assert parsed.dry_run is True
    assert parsed.write is False
    assert parsed.user_id == SEEDED_USER_ID

    other_user = uuid.UUID("00000000-0000-0000-0000-0000000000ff")
    overridden = build_parser().parse_args(
        ["backfill-apple-health", "export.xml", "--write", "--user-id", str(other_user)]
    )
    assert overridden.user_id == other_user
    assert overridden.write is True
    assert overridden.dry_run is False


def test_backfill_requires_an_explicit_mode() -> None:
    """The mode is a GATE, not a default: neither flag and both flags are equally an error.

    This command writes 4.5 years of history to a production database and has no practical
    rollback, so a forgotten flag must exit 2 rather than fall through to a silent full write.
    Both directions matter for the same reason `--full --incremental` does: `--dry-run --write`
    is a contradiction, and resolving it silently would let an operator believe they rehearsed
    a run that actually wrote.

    This is the argparse half of D-03. The runtime half -- that `dry_run=True` really touches
    no row and no `sync_state` timestamp -- is `test_dry_run_writes_nothing` in
    `test_backfill_idempotency.py`.
    """
    for argv in (
        ["backfill-apple-health", "export.xml"],
        ["backfill-apple-health", "export.xml", "--dry-run", "--write"],
    ):
        with pytest.raises(SystemExit) as excinfo:
            build_parser().parse_args(argv)

        assert excinfo.value.code == 2, argv


def test_backfill_takes_the_export_path_positionally() -> None:
    """No default path. An implicit `export.xml` at the repo root is how the wrong file is read.

    The operator has two exports sitting side by side (`export.xml` and `export_cda.xml`) and
    the summary's `file:` line is only a confirmation if the name was typed on purpose. A
    defaulted path would also let a run started in the wrong directory look like a run over an
    empty file rather than like the mistake it is.
    """
    with pytest.raises(SystemExit) as excinfo:
        build_parser().parse_args(["backfill-apple-health", "--dry-run"])

    assert excinfo.value.code == 2


def test_configure_logging_precedes_every_log_call() -> None:
    """T-03-44, asserted against the SOURCE because the runtime cannot show it.

    Anything emitted before `configure_logging` bypasses all three FOUND-05 redaction layers,
    and the very first thing this command has to record is a Hevy request. A runtime test
    would have to prove the absence of an event on a stream that does not exist yet; a
    source-order read fails the moment somebody adds a `log.info` above the bootstrap.

    `make_engine` is included for the same reason: an engine built above that line brings
    SQLAlchemy's own loggers with it.
    """
    source = CLI_SOURCE.read_text(encoding="utf-8")
    boundary = source.index("configure_logging(settings)")

    assert "log." not in source[:boundary], (
        "T-03-44 violated: backend/app/cli.py reaches for a logger above "
        "`configure_logging(settings)`, so that line is written with every redaction layer "
        "switched off"
    )
    assert "make_engine" not in source[:boundary], (
        "T-03-44 violated: backend/app/cli.py builds an engine above "
        "`configure_logging(settings)`; SQLAlchemy's loggers would then be live before the "
        "value scrubber has the secrets"
    )


def test_cli_never_formats_an_arbitrary_exception() -> None:
    """T-03-45. stderr is outside the redaction pipeline, so what reaches it is curated.

    `str(exc)` on an arbitrary exception is the leak: a pydantic `ValidationError` renders
    `input_value=`, i.e. this person's workout titles and body-composition numbers, straight
    onto the operator's terminal and into whatever captured it.
    """
    source = CLI_SOURCE.read_text(encoding="utf-8")

    assert "str(exc)" not in source, (
        "T-03-45 violated: backend/app/cli.py renders an exception directly. Print "
        "`exc.safe_message` or `type(exc).__name__` instead"
    )
    assert "safe_message" in source, (
        "T-03-45 violated: backend/app/cli.py no longer uses the curated `safe_message` "
        "channel, so a Hevy failure now reaches the operator as a bare class name at best"
    )


def test_cli_does_not_import_hae_wire_vocabulary() -> None:
    """`cli.py` reaches the backfill through ONE door: `backfill.run_backfill`/`format_summary`.

    This duplicates one half of `test_health_auto_export_isolation.py` on purpose. That file's
    `rglob` walk proves the boundary holds across the whole app and reports whichever module
    broke it; this one fails with a message naming the CLI specifically, so the person who
    reached for `METRIC_REGISTRY` to build a summary line by hand sees why they must not.

    The positive half is the load-bearing one: dropping the `backfill` import entirely would
    satisfy the two negatives while removing the subcommand.
    """
    source = CLI_SOURCE.read_text(encoding="utf-8")

    for forbidden in (
        "health_auto_export.registry",
        "health_auto_export.schemas",
    ):
        assert forbidden not in source, (
            f"HEALTH-06 violated: backend/app/cli.py names `{forbidden}`. The metric names and "
            f"the wire schemas are Health Auto Export's identifiers; the summary block is "
            f"built by `backfill.format_summary`, where that vocabulary already lives"
        )

    assert "health_auto_export.backfill" in source, (
        "backend/app/cli.py no longer imports the backfill entry point, so HEALTH-10 has no "
        "operator command behind it"
    )


def test_backfill_runner_is_declared_below_the_bootstrap() -> None:
    """The new runner's position, pinned specifically rather than only in aggregate.

    `test_configure_logging_precedes_every_log_call` already proves that nothing in this file
    logs or builds an engine above `configure_logging(settings)`. This one names
    `_run_backfill` because it does BOTH -- `structlog.get_logger()` and `make_engine` on its
    first two lines -- so moving it above `main`, which reads as a harmless tidy-up, would
    write the production `DATABASE_URL` into a log line with every redaction layer off
    (T-09-17).
    """
    source = CLI_SOURCE.read_text(encoding="utf-8")

    assert source.index("async def _run_backfill") > source.index("configure_logging(settings)"), (
        "T-09-17 violated: `_run_backfill` is declared above `configure_logging(settings)`. It "
        "builds an engine and a logger, so at that position SQLAlchemy's loggers are live "
        "before the value scrubber has the production DATABASE_URL"
    )
