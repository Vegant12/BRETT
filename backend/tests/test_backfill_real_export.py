"""Success criterion #1, measured against the ACTUAL `export.xml` rather than a trimmed fixture.

Every other test in Phase 9 runs against `export_sample.xml` -- 21 hand-written records. That
fixture proves the tag walk, the allowlist, the Hevy exclusion and the D-07 skip paths, and it is
the right tool for all of them. The one claim it cannot support is the one the ROADMAP names
first: that streaming **438,649** elements stays inside a memory budget. A 21-record file stays
inside any budget. So this module exists, and it is the only place in the suite whose input is the
real thing.

Why this file is unlike every other test here
---------------------------------------------
Its input is **gitignored**. `export.xml` is 191 MB of one person's actual health history; it
cannot be committed, and CI will never have it. Two independent gates follow from that, and both
are deliberate rather than redundant (T-09-23):

* a `realfile` marker, so CI deselects this module **explicitly** (`-m 'not realfile'`) instead of
  relying on a skip it never had to think about; and
* a `skipif` on the file's existence, so a developer without the file gets a clean skip and never
  a red suite.

What may and may not be asserted
--------------------------------
**Counts, element names, HealthKit identifiers, units and dates only. Never a measured quantity**,
and never one interpolated into an assertion message either (T-09-22). The pinned numbers below
are structural facts about the file's *shape* -- how many records it holds, how many of them the
parser recognised, which local days it spans -- which is exactly the class of information
`backfill.py`'s logging rule already permits a log line to carry. A step total is not, and a
reader who later adds one has crossed the boundary this docstring exists to mark.

These figures describe ONE export
---------------------------------
Everything pinned here was measured against the export dated **`2026-08-26 10:09:33 +0700`**. If
the user re-exports from the Health app, every number in this module changes: the file grows, the
record total rises, the date range extends, and the row counts move. **That is a re-pin, not a
bug.** Re-derive the figures from a fresh `--dry-run` summary and update them together; do not
edit one number until the assertion goes green. Each assertion message says so on its own, because
the person reading the failure is not necessarily the person reading this docstring.
"""

import collections
import datetime as dt
import io
import logging
import time
import tracemalloc
from pathlib import Path

import pytest
import structlog

from app.config import Settings
from app.integrations.health_auto_export import backfill, normalize
from app.integrations.health_auto_export.backfill import BackfillScan, scan_export
from app.logging import configure_logging

# `parents[2]` from `backend/tests/` is the repo root -- the convention
# `test_health_auto_export_isolation.py` established and the one every path in this suite is
# built from.
REPO_ROOT = Path(__file__).resolve().parents[2]
EXPORT_XML = REPO_ROOT / "export.xml"

# The seeded user's zone, +07:00. Keyword-only and defaultless on `scan_export` for the reason
# `normalize._user_timezone` gives; passing the wrong one here would move every evening datapoint
# onto the wrong local day and still produce a plausible 8,077-row answer.
TZ = "Asia/Jakarta"

# A CEILING, not a measurement. The literal-HAEPayload pipeline this phase implements was measured
# at 310.9 MB peak RSS on this file (244.5 MB of it traced Python allocation). 800 MB leaves room
# for the interpreter, pytest and tracemalloc's own bookkeeping while still failing loudly if
# someone reintroduces an unbounded read. D-01 runs this command on the user's own laptop, so the
# constraint is "comfortably inside a laptop's headroom", not Cloud Run's 1 GiB (T-09-09).
_PEAK_MEMORY_CEILING_BYTES = 800 * 1024 * 1024

# A CEILING, not a measurement. Parse plus normalize was 4.5 s bare, ~23 s under `tracemalloc`,
# which traces every allocation the scan makes. 120 s fails only if the streaming discipline was
# replaced by something quadratic.
_WALL_CLOCK_CEILING_SECONDS = 120.0

# Appended to every assertion that pins a figure. A mismatch here almost always means a NEW export,
# not a regression, and the remedy is mechanical.
_REPIN = (
    "If the user re-exported from the Health app, every pinned figure in this module is stale "
    "together: re-derive them all from a fresh `--dry-run` summary rather than editing this one "
    "number until it passes."
)

# --- The pinned shape of the export dated 2026-08-26 10:09:33 +0700 ---
EXPECTED_SIZE_BYTES = 191_257_897
EXPECTED_RECORDS_TOTAL = 438_649
EXPECTED_RECORDS_UNRECOGNIZED = 208_175
EXPECTED_RECORDS_MALFORMED = 0
EXPECTED_BODY_MASS_SKIPPED = 79
EXPECTED_WORKOUTS_SKIPPED = 224
EXPECTED_ACTIVITY_SUMMARIES_SKIPPED = 1_443
EXPECTED_HEVY_EXCLUDED = 209
EXPECTED_DATAPOINTS_SEEN = 230_395
EXPECTED_SAMPLES_AGGREGATED = 230_186
EXPECTED_ROWS = 8_077
EXPECTED_DISTINCT_DAYS = 1_631
EXPECTED_FIRST_DAY = dt.date(2022, 3, 10)
EXPECTED_LAST_DAY = dt.date(2026, 8, 26)
EXPECTED_MULTI_POINT_DAYS = 7_403

# ~34 distinct identifiers on this export. A loose bound on purpose: the assertion that matters is
# "per TYPE, not per RECORD" -- roughly 35 versus 208,175 -- and a new Apple Health release adding
# a couple of identifiers must not turn into a failing test.
_UNRECOGNIZED_TYPE_CEILING = 60

EXPECTED_ROWS_PER_METRIC = {
    "active_energy": 1_501,
    "basal_energy_burned": 1_592,
    "carbohydrates": 53,
    "dietary_energy": 54,
    "dietary_sugar": 54,
    "fiber": 53,
    "flights_climbed": 1_211,
    "protein": 54,
    "sodium": 53,
    "step_count": 1_699,
    "total_fat": 54,
    "walking_running_distance": 1_699,
}

pytestmark = [
    pytest.mark.realfile,
    pytest.mark.skipif(
        not EXPORT_XML.exists(),
        reason=(
            "export.xml is gitignored real health data and is only present on the user's own "
            "machine. Run with -m realfile after placing it at the repo root."
        ),
    ),
]


@pytest.fixture(scope="module")
def scan() -> tuple[BackfillScan, float, int]:
    """One pass over the real file, plus its wall time and peak traced allocation.

    Module-scoped because a 191 MB parse costs ~23 s under `tracemalloc`; eleven of them would
    turn an opt-in check into a coffee break, and every test below reads the same immutable
    result.

    The scan runs with the REAL logging pipeline installed, pointed at a throwaway buffer. That is
    not cosmetic: `multi_point_days` is produced by `_MultiPointDayCounter`, a `logging.Filter` on
    the root HANDLERS, and a process that never called `configure_logging` has no root handler for
    it to attach to -- unconfigured structlog bypasses stdlib logging entirely, so the counter
    would read 0 and `test_the_real_export_multi_point_day_warnings_are_counted_not_emitted` would
    pin a number that only means "logging was not set up". `cli.py` calls `configure_logging` as
    the first thing `main()` does, so this mirrors the real run rather than staging it.

    The buffer is discarded. Everything the scan logs is counts and identifiers, but there are
    ~36 lines of it and pytest has better things to print.
    """
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    saved_logs = {module: module.log for module in (backfill, normalize)}
    saved_cache = structlog.get_config()["cache_logger_on_first_use"]
    try:
        configure_logging(Settings(_env_file=None))
        # A proxy cached by an earlier test keeps that test's configuration and would never reach
        # the handler the filter is attached to -- a suppression that silently checks nothing.
        structlog.configure(cache_logger_on_first_use=False)
        for module in saved_logs:
            module.log = structlog.get_logger()
        handler = root.handlers[0]
        assert isinstance(handler, logging.StreamHandler)
        handler.setStream(io.StringIO())

        tracemalloc.start()
        started = time.monotonic()
        result = scan_export(EXPORT_XML, tz=TZ)
        elapsed = time.monotonic() - started
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    finally:
        for module, saved in saved_logs.items():
            module.log = saved
        root.handlers, root.level = saved_handlers, saved_level
        structlog.configure(cache_logger_on_first_use=saved_cache)
        structlog.reset_defaults()
    return result, elapsed, peak


def test_the_real_export_streams_within_the_memory_ceiling(
    scan: tuple[BackfillScan, float, int],
) -> None:
    """SC#1: 438,649 elements go through the parser without the file ending up in memory.

    Read the ceiling for what it is. PITFALLS #6 claimed `ElementTree.parse()` builds a 1.5-2 GB
    DOM; the measured figure for a full DOM of this file is 316 MB, so an 800 MB ceiling would
    NOT catch that particular regression -- the research number was simply wrong. What this
    catches is unbounded accumulation of a different kind: a list of every record, a payload
    built twice, a `root.clear()` quietly dropped. The two-clear discipline itself is guarded
    structurally in `test_health_auto_export_backfill.py`, which is the right place for it,
    because that assertion does not need 191 MB to be true.
    """
    _result, elapsed, peak = scan
    assert peak < _PEAK_MEMORY_CEILING_BYTES, (
        f"the scan peaked at {peak / 1024 / 1024:.1f} MB of traced allocation, above the "
        f"{_PEAK_MEMORY_CEILING_BYTES / 1024 / 1024:.0f} MB ceiling. Something is accumulating "
        f"across the parse rather than being cleared at each end event. {_REPIN}"
    )
    assert elapsed < _WALL_CLOCK_CEILING_SECONDS, (
        f"the scan took {elapsed:.1f} s, above the {_WALL_CLOCK_CEILING_SECONDS:.0f} s ceiling "
        f"(measured ~23 s under tracemalloc, ~4.5 s without it). A miss this large means the "
        f"streaming walk became quadratic, not that the machine is slow. {_REPIN}"
    )


def test_the_real_export_file_is_the_expected_one() -> None:
    """Pin the byte size, so a re-export announces itself instead of quietly moving every count."""
    size = EXPORT_XML.stat().st_size
    assert size == EXPECTED_SIZE_BYTES, (
        f"export.xml is {size} bytes, not the {EXPECTED_SIZE_BYTES} this module was pinned "
        f"against. This is almost certainly a fresh export rather than a defect. {_REPIN}"
    )


def test_the_real_export_record_accounting_identity_holds(
    scan: tuple[BackfillScan, float, int],
) -> None:
    """Every `<Record>` is either inside a datapoint or explained by one of three counters.

    `438,649 == 230,395 + 208,175 + 79 + 0`. A record the tag walk silently drops has nowhere to
    hide: without this, the row set would still look entirely plausible and the loss would only
    surface as a gap in a trend months later.
    """
    result, _elapsed, _peak = scan
    assert result.records_total == EXPECTED_RECORDS_TOTAL, (
        f"the file holds {result.records_total} <Record> elements, not "
        f"{EXPECTED_RECORDS_TOTAL}. {_REPIN}"
    )
    explained = (
        result.normalized.datapoints_seen
        + result.records_unrecognized
        + result.body_mass_skipped
        + result.records_malformed
    )
    assert result.records_total == explained, (
        f"{result.records_total} records went in but only {explained} came out accounted for "
        f"({result.normalized.datapoints_seen} datapoints + {result.records_unrecognized} "
        f"unrecognized + {result.body_mass_skipped} body mass + {result.records_malformed} "
        f"malformed). The difference is records the walk dropped without counting."
    )
    assert result.records_unrecognized == EXPECTED_RECORDS_UNRECOGNIZED, (
        f"{result.records_unrecognized} unrecognized records, not "
        f"{EXPECTED_RECORDS_UNRECOGNIZED}. {_REPIN}"
    )


def test_the_real_export_has_no_malformed_records(scan: tuple[BackfillScan, float, int]) -> None:
    """The value audit found zero defects across all 230,395 in-scope records.

    D-07's log-and-continue path and the per-row write fallback are insurance, not expected
    traffic. A non-zero count here is new information about the file -- a truncated export, a
    HealthKit release that changed an attribute -- and not necessarily a bug in the reader.
    """
    result, _elapsed, _peak = scan
    assert result.records_malformed == EXPECTED_RECORDS_MALFORMED, (
        f"{result.records_malformed} records failed per-record validation; this export was "
        f"audited clean ({EXPECTED_RECORDS_MALFORMED} defects across "
        f"{EXPECTED_DATAPOINTS_SEEN} in-scope records). Read the "
        f"`health_backfill_record_skipped` reason tokens before assuming a parser defect. "
        f"{_REPIN}"
    )


def test_non_record_elements_are_skipped_and_counted(
    scan: tuple[BackfillScan, float, int],
) -> None:
    """SC#4: 224 workouts, 1,443 activity summaries and 79 body-mass records contribute nothing.

    218 of the 224 workouts are Hevy re-exports of sessions BRETT already holds at set-and-rep
    detail. Neither those, nor the 224 nested `WorkoutStatistics` elements that carry an
    allowlisted `type=` and no `sourceName` of their own, may produce a datapoint (D-02, T-09-06).
    Body mass is counted under its own name rather than lumped into "unrecognized" because D-01 is
    a decision, and a decision that reads as an accident on the summary invites someone to fix it.
    """
    result, _elapsed, _peak = scan
    assert result.workouts_skipped == EXPECTED_WORKOUTS_SKIPPED, (
        f"{result.workouts_skipped} <Workout> elements skipped, not "
        f"{EXPECTED_WORKOUTS_SKIPPED}. {_REPIN}"
    )
    assert result.activity_summaries_skipped == EXPECTED_ACTIVITY_SUMMARIES_SKIPPED, (
        f"{result.activity_summaries_skipped} <ActivitySummary> elements skipped, not "
        f"{EXPECTED_ACTIVITY_SUMMARIES_SKIPPED}. {_REPIN}"
    )
    assert result.body_mass_skipped == EXPECTED_BODY_MASS_SKIPPED, (
        f"{result.body_mass_skipped} body-mass records skipped, not "
        f"{EXPECTED_BODY_MASS_SKIPPED}. {_REPIN}"
    )


def test_hevy_active_energy_is_excluded_from_the_real_export(
    scan: tuple[BackfillScan, float, int],
) -> None:
    """SC#4: 209 Hevy-sourced datapoints, reproduced from the file rather than inherited.

    `normalize.py` documents "209 records across 209 training days" as a measured claim. Deriving
    the same 209 here, from the export itself and through the shared predicate, turns that claim
    into something confirmed rather than quoted -- and gives Pitfall N-3's stated warning sign,
    "a filter that never excludes anything", a detector on the one dataset where Hevy demonstrably
    did write back to HealthKit.
    """
    result, _elapsed, _peak = scan
    assert result.hevy_datapoints_excluded == EXPECTED_HEVY_EXCLUDED, (
        f"the backfill's advisory counter saw {result.hevy_datapoints_excluded} Hevy-sourced "
        f"datapoints, not {EXPECTED_HEVY_EXCLUDED}. A count of 0 means the predicate stopped "
        f"matching, which is the failure mode HEALTH-08 exists to prevent. {_REPIN}"
    )
    assert result.normalized.datapoints_dropped == EXPECTED_HEVY_EXCLUDED, (
        f"`normalize_payload` dropped {result.normalized.datapoints_dropped} datapoints while "
        f"the backfill counted {result.hevy_datapoints_excluded} Hevy-sourced ones. These two "
        f"numbers come from different code and agreeing is the point: the backfill only counts, "
        f"the normalizer enforces. {_REPIN}"
    )
    leaked = sorted(
        {
            row.source_name
            for row in result.normalized.rows
            if row.source_name.strip().casefold() == "hevy"
        }
    )
    assert not leaked, (
        f"rows survived with a Hevy source name ({leaked}); those are workout energy BRETT "
        f"already holds from the Hevy API, and keeping them double-counts every training day"
    )


def test_the_real_export_produces_the_expected_rows(
    scan: tuple[BackfillScan, float, int],
) -> None:
    """SC#2: 230,395 raw samples collapse to 8,077 rows, with the aggregation fully accounted for.

    `sum(sample_count) == datapoints_seen - datapoints_dropped` is the identity Phase 8 pins on
    the webhook path. It holding here too is what "the same code path" actually means.
    """
    result, _elapsed, _peak = scan
    rows = result.normalized.rows
    assert len(rows) == EXPECTED_ROWS, (
        f"the scan produced {len(rows)} rows, not {EXPECTED_ROWS}. {_REPIN}"
    )
    assert result.normalized.datapoints_seen == EXPECTED_DATAPOINTS_SEEN, (
        f"{result.normalized.datapoints_seen} datapoints reached the normalizer, not "
        f"{EXPECTED_DATAPOINTS_SEEN}. {_REPIN}"
    )
    aggregated = sum(row.sample_count for row in rows)
    assert aggregated == EXPECTED_SAMPLES_AGGREGATED, (
        f"the rows account for {aggregated} samples, not {EXPECTED_SAMPLES_AGGREGATED}. {_REPIN}"
    )
    assert aggregated == result.normalized.datapoints_seen - result.normalized.datapoints_dropped


def test_the_real_export_covers_the_expected_date_range(
    scan: tuple[BackfillScan, float, int],
) -> None:
    """SC#2: 2022-03-10 to 2026-08-26, 1,631 distinct local days.

    The last day is the export date, so a range that ends earlier means the tail of the file was
    not read -- the exact symptom a chunked parse would produce, and the reason
    `backfill.py` reads the whole file before returning anything.
    """
    result, _elapsed, _peak = scan
    days = {row.local_day for row in result.normalized.rows}
    assert min(days) == EXPECTED_FIRST_DAY, (
        f"the earliest local day is {min(days)}, not {EXPECTED_FIRST_DAY}. {_REPIN}"
    )
    assert max(days) == EXPECTED_LAST_DAY, (
        f"the latest local day is {max(days)}, not {EXPECTED_LAST_DAY}; the export ends at its "
        f"own ExportDate, so an earlier maximum means the tail of the file was not read. {_REPIN}"
    )
    assert len(days) == EXPECTED_DISTINCT_DAYS, (
        f"{len(days)} distinct local days, not {EXPECTED_DISTINCT_DAYS}. {_REPIN}"
    )


def test_the_real_export_rows_per_metric(scan: tuple[BackfillScan, float, int]) -> None:
    """All twelve registry metrics fill, and nutrition is genuinely sparse.

    ~54 rows per nutrition metric against ~1,600 per activity metric is a fact about the user's
    logging habits -- 631 nutrition records across roughly 54 days in 4.5 years -- and not a
    parser defect. Phase 13's nutrition trend must not be built assuming dense history.

    Asserted as one dict comparison so a failure prints the whole diff rather than stopping at
    whichever metric happens to sort first.
    """
    result, _elapsed, _peak = scan
    per_metric = dict(collections.Counter(row.metric for row in result.normalized.rows))
    assert per_metric == EXPECTED_ROWS_PER_METRIC, (
        f"the per-metric row counts moved. A metric missing entirely means its HealthKit "
        f"identifier stopped mapping; every count shifting together means a new export. {_REPIN}"
    )


def test_the_real_export_multi_point_day_warnings_are_counted_not_emitted(
    scan: tuple[BackfillScan, float, int],
) -> None:
    """Pitfall 4: 7,403 of 8,077 rows aggregate more than one sample, and none of them warns.

    For the WEBHOOK, `health_ingest_multi_point_day` means the device's daily aggregation drifted
    and re-sends have become lossy. For RAW HealthKit samples it is simply what per-event data
    looks like -- 91.7% of rows here. Left un-suppressed, 7,403 emitted lines would bury the
    Hevy-exclusion and skipped-element lines that a reader actually has to act on.
    """
    result, _elapsed, _peak = scan
    assert result.multi_point_days == EXPECTED_MULTI_POINT_DAYS, (
        f"{result.multi_point_days} multi-point days counted, not "
        f"{EXPECTED_MULTI_POINT_DAYS}. A count of 0 usually means logging was never configured "
        f"rather than that the condition vanished: the counter is a filter on the root log "
        f"handlers. {_REPIN}"
    )
    assert result.multi_point_days < len(result.normalized.rows), (
        f"{result.multi_point_days} multi-point days against "
        f"{len(result.normalized.rows)} rows -- the count cannot exceed one per row, so a "
        f"count at or above the row total means it is counting something else"
    )


def test_the_real_export_unrecognized_types_are_grouped(
    scan: tuple[BackfillScan, float, int],
) -> None:
    """One log line per unrecognized TYPE (~34), never per unrecognized RECORD (208,175).

    The same trade `health_ingest_unrecognized_metric` already makes on the webhook path, for the
    same reason. The bound is deliberately loose: a new Apple Health release adding a couple of
    identifiers is expected and must not turn into a failing test, whereas a jump to five figures
    would mean the grouping key regressed to something per-record.
    """
    result, _elapsed, _peak = scan
    assert result.records_unrecognized == EXPECTED_RECORDS_UNRECOGNIZED, (
        f"{result.records_unrecognized} unrecognized records, not "
        f"{EXPECTED_RECORDS_UNRECOGNIZED}. {_REPIN}"
    )
    assert len(result.unrecognized_types) < _UNRECOGNIZED_TYPE_CEILING, (
        f"{len(result.unrecognized_types)} distinct unrecognized identifiers (about 34 on this "
        f"export) against {result.records_unrecognized} unrecognized records. Crossing "
        f"{_UNRECOGNIZED_TYPE_CEILING} means the grouping key stopped being the type identifier"
    )
    for identifier in (
        "HKQuantityTypeIdentifierWalkingSpeed",
        "HKCategoryTypeIdentifierSleepAnalysis",
    ):
        assert identifier in result.unrecognized_types, (
            f"{identifier} is no longer reported as unrecognized. Either it entered the "
            f"allowlist -- which would be a scope change, not a fix, since v2.0 cut sleep and "
            f"recovery for lack of data -- or the grouping stopped recording identifiers. "
            f"{_REPIN}"
        )
