"""Coverage for the historical `export.xml` backfill: HEALTH-10, success criteria #3 and #4.

Two layers, in this order:

1. **Fixture integrity** (plan 09-01) -- assertions about
   `backend/tests/fixtures/hae/export_sample.xml` itself. A fixture that the behavioural
   assertions below depend on gets its shape pinned, so an editor silently normalising it fails
   loudly rather than quietly changing what a later test asserts.
2. **The reader** (plan 09-02) -- the twelve-entry HealthKit identifier mapping and the
   streaming `scan_export` walk over that fixture. Still pure and container-free: `backfill.py`
   touches no database, so every case here runs in the FAST suite and fails on the commit that
   breaks it rather than after a deploy.

What deliberately lives ELSEWHERE:

* **Idempotency, and the backfill-then-webhook-same-day case that proves criterion #3** --
  `test_backfill_idempotency.py`, marked `integration`, against a real Postgres container.
  Whether a second write of the same key is an update or an insert is a property of the upsert,
  not of the parse.
* **The real 191 MB `export.xml`** -- `test_backfill_real_export.py`, behind the `realfile`
  marker. That file is gitignored health data, CI will never have it, and criterion #1 (parse
  within a memory ceiling) can only be measured against the real thing.

Non-ASCII source names are written as ESCAPES (`\\u2019`), never as literals. `V's iPhone` and
`Vegant's iPhone` carry U+2019 RIGHT SINGLE QUOTATION MARK, which is invisible in a diff and
which one careless editor normalising to an ASCII apostrophe would silently turn into a
different assertion. The XML fixture is the one place the literal is allowed to live, because
it is data, read with an explicit `encoding="utf-8"`.
"""

import datetime as dt
import inspect
import io
import json
import logging
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import pytest
import structlog

from app.config import Settings
from app.integrations.health_auto_export import backfill, normalize
from app.integrations.health_auto_export.backfill import (
    _HK_BODY_MASS,
    HK_TO_WIRE,
    BackfillScan,
    scan_export,
)
from app.integrations.health_auto_export.errors import HAEExportFileError
from app.integrations.health_auto_export.normalize import (
    UNKNOWN_SOURCE_NAME,
    normalize_payload,
)
from app.integrations.health_auto_export.registry import METRIC_REGISTRY
from app.integrations.health_auto_export.schemas import HAEPayload
from app.logging import configure_logging
from tests.conftest import hae_fixture, hae_xml_fixture

# The live-verified webhook source vocabulary (`fixtures/hae/device_capture.json`, captured
# against the deployed service on 2026-09-03). These strings sit INSIDE the natural key
# `(user_id, source, metric, source_name, local_day)`, so the backfill reproducing them
# byte-for-byte is what makes success criterion #3 achievable at all.
DEVICE_CURRENT = "V\u2019s iPhone"  # device_capture.json, live-verified 2026-09-03
DEVICE_PREVIOUS = "Vegant\u2019s iPhone"  # the pre-rename name, still 86% of the real export
NUTRITION_SOURCE = "Foodvisor"
HEVY_SOURCE = "Hevy"

FIXTURE_NAME = "export_sample"

# Shape counts, from RESEARCH's enumeration of what the streaming parser must handle.
EXPECTED_RECORDS = 21
EXPECTED_WORKOUTS = 1
EXPECTED_WORKOUT_STATISTICS = 1
EXPECTED_ACTIVITY_SUMMARIES = 1

# The real file's fingerprint is high-precision floats (RESEARCH measured up to 9 decimal
# places). Synthetic values are round on purpose, so anything past this is a leak.
MAX_SYNTHETIC_DECIMAL_PLACES = 4

# One identifier per `METRIC_REGISTRY` entry. Written as its own number rather than as
# `len(METRIC_REGISTRY)` so that deleting a registry entry AND its identifier together -- which
# keeps the totality assertion green -- still fails here.
EXPECTED_MAPPED_METRICS = 12

# Every mapped identifier is a QUANTITY type. Category types carry a string `value=` and workout
# types do not appear on a `Record` at all.
HK_QUANTITY_PREFIX = "HKQuantityTypeIdentifier"

# `users.timezone` today, and the offset every timestamp in the fixture carries. Never a default
# inside `scan_export`: at UTC+7 a wrong zone moves every evening datapoint onto the wrong day.
TZ = "Asia/Jakarta"  # +07:00

# What the fixture's 21 Records decompose into. Each of these is a separate counter on
# `BackfillScan` precisely because D-04 wants them reported separately.
EXPECTED_DATAPOINTS = 16
EXPECTED_UNRECOGNIZED_RECORDS = 2
EXPECTED_MALFORMED_RECORDS = 2
EXPECTED_BODY_MASS_SKIPPED = 1
EXPECTED_HEVY_EXCLUDED = 1
EXPECTED_MULTI_POINT_DAYS = 1

# The one legitimate, non-Hevy `ActiveEnergyBurned` record in the fixture. The `<Workout>`'s
# nested `<WorkoutStatistics sum="228">` carries the SAME `type=` string; if it were ever
# ingested this total would read 528.
LEGITIMATE_ACTIVE_ENERGY = Decimal("300")

BUSY_DAY = dt.date(2026, 9, 2)


def _fixture_path() -> Path:
    return hae_xml_fixture(FIXTURE_NAME)


def _fixture_text() -> str:
    """The raw bytes as text. `encoding="utf-8"` is load-bearing, not decoration: the source
    names carry U+2019, and a locale default would either mangle them or raise."""
    return _fixture_path().read_text(encoding="utf-8")


def _fixture_root() -> ET.Element:
    """Parse the fixture with the stdlib parser, `noqa`'d exactly as plan 09-02's reader will be.

    `S314` ("use `defusedxml`") is a documented, accepted risk here, not an oversight -- RESEARCH
    Pitfall 6 works the decision through and rejects `defusedxml` on the project's own dependency
    standard (last release 2021-03-08, staler than the `python-jose` CLAUDE.md already refuses),
    for zero real protection: the input is a locally-exported, user-owned file, expat does not
    resolve external entities by default, and `test_fixture_parses_and_declares_no_entities`
    pins the document as declaring none.
    """
    return ET.parse(_fixture_path()).getroot()  # noqa: S314 -- see RESEARCH Pitfall 6


def _record_source_names() -> set[str]:
    return {
        source
        for source in (record.get("sourceName") for record in _fixture_root().findall("Record"))
        if source is not None
    }


def test_fixture_parses_and_declares_no_entities() -> None:
    """The fixture-side half of the T-09-03 disposition.

    Phase 9 accepts the XXE risk rather than adding `defusedxml`, and the stated reason is that
    the input is a locally-exported file whose DTD declares only `ELEMENT`/`ATTLIST` -- **zero**
    `ENTITY` declarations. The parser in plan 09-02 is trusted against exactly that shape, so
    the fixture it is tested against has to have exactly that shape too. A fixture that quietly
    grew an entity declaration would make the trust argument false while every other test in
    this file still passed.
    """
    text = _fixture_text()
    assert "<!DOCTYPE HealthData [" in text, "the real export carries an internal-subset DOCTYPE"
    assert "<!ENTITY" not in text, "the real export declares zero entities; the fixture must too"

    # Parsing last: a DOCTYPE the stdlib parser rejects would fail here rather than in 09-02.
    assert _fixture_root().tag == "HealthData"


def test_fixture_carries_every_element_shape_the_parser_must_handle() -> None:
    """Four element shapes, three of which must never produce a row (SC#4).

    `Workout`, `WorkoutStatistics` and `ActivitySummary` are the D-04 counters; `Record` is the
    only shape that maps to a `health_daily_metrics` row. If a later edit trims one of these out
    of the fixture, the test that proves it is never ingested would start passing vacuously.
    """
    root = _fixture_root()
    assert len(root.findall("Record")) == EXPECTED_RECORDS
    assert len(root.findall("Workout")) == EXPECTED_WORKOUTS
    assert len(root.findall("Workout/WorkoutStatistics")) == EXPECTED_WORKOUT_STATISTICS
    assert len(root.findall("ActivitySummary")) == EXPECTED_ACTIVITY_SUMMARIES


def test_fixture_source_names_are_u2019_not_ascii() -> None:
    """Both device names carry U+2019, and no `sourceName` carries an ASCII apostrophe.

    An editor (or a well-meaning "smart quotes off" setting) normalising U+2019 to `'` would
    silently turn the success-criterion-#3 pin into a different assertion: the backfill would
    then write a `source_name` the webhook never sends, the natural key would differ, and an
    overlapping day would hold two rows instead of one. Nothing else in the suite would notice.
    """
    sources = _record_source_names()
    assert DEVICE_CURRENT in sources
    assert DEVICE_PREVIOUS in sources
    assert sources == {DEVICE_CURRENT, DEVICE_PREVIOUS, NUTRITION_SOURCE, HEVY_SOURCE}
    assert not [source for source in sources if "'" in source]


def test_fixture_source_names_match_the_live_webhook_capture() -> None:
    """RESEARCH Pitfall 2, turned from a coincidence into a guarantee.

    `source_name` sits INSIDE the natural key `(user_id, source, metric, source_name,
    local_day)`. The backfill and the live webhook producing the same string byte-for-byte is
    the only reason an overlapping metric-day ends up as ONE row rather than two -- and today
    that is a coincidence of the user not having renamed their phone (RESEARCH assumption A3).
    This assertion is what detects the rename. Nothing else would: the upsert would simply
    insert, silently and invisibly.

    A SUBSET, not equality: the fixture deliberately also carries `DEVICE_PREVIOUS` (the
    pre-rename name, still 86% of the real export) and `Hevy` (the exclusion case), neither of
    which the current webhook sends.
    """
    capture: dict[str, Any] = hae_fixture("device_capture")
    webhook_sources = {
        point["source"]
        for metric in capture["data"]["metrics"]
        for point in metric["data"]
        if "source" in point
    }
    assert webhook_sources == {DEVICE_CURRENT, NUTRITION_SOURCE}, (
        "device_capture.json changed; re-check the backfill's source_name pass-through"
    )
    assert webhook_sources <= _record_source_names()


def test_fixture_workout_statistics_carries_active_energy_but_no_source() -> None:
    """RESEARCH Pitfall 3: the back door into `active_energy`.

    `<WorkoutStatistics>` carries `type="HKQuantityTypeIdentifierActiveEnergyBurned"` -- an
    allowlisted metric -- but is not a `Record`. It uses `sum=` rather than `value=`, and it has
    no `sourceName` of its own, so `is_hevy_sourced(None)` returns `False` by design (that
    `None` branch exists for the gait-metric case) and would NOT filter it. A parser keyed on
    `type=` rather than on `elem.tag == "Record"` would therefore ingest Hevy's own workout
    energy -- the exact double-count HEALTH-08 exists to prevent -- while the D-04 skip counter
    still cheerfully reported the parent workout as skipped.
    """
    statistics = _fixture_root().findall("Workout/WorkoutStatistics")
    assert len(statistics) == EXPECTED_WORKOUT_STATISTICS
    element = statistics[0]
    assert element.get("type") == "HKQuantityTypeIdentifierActiveEnergyBurned"
    assert element.get("sum") is not None
    assert element.get("value") is None
    assert element.get("sourceName") is None


def test_fixture_holds_no_high_precision_value() -> None:
    """T-09-01: no committed quantity may be traceable to the user's real export.

    RESEARCH measured values with up to 9 decimal places in the real `export.xml`. Synthetic
    values here are round on purpose (1000, 500, 4.5), so a long fractional part is a
    fingerprint of a copy-paste from the real file rather than a formatting choice. The check
    walks EVERY element, not just `Record`, because `ActivitySummary` and `WorkoutStatistics`
    carry quantities too.
    """
    offenders = []
    for element in _fixture_root().iter():
        for attribute in ("value", "sum", "activeEnergyBurned", "totalEnergyBurned"):
            raw = element.get(attribute)
            if raw is None:
                continue
            _, _, fraction = raw.partition(".")
            if len(fraction) > MAX_SYNTHETIC_DECIMAL_PLACES:
                offenders.append((element.tag, attribute, raw))
    assert not offenders, f"high-precision values look copied from the real export: {offenders}"


# ---------------------------------------------------------------------------
# T-09-08: the HealthKit identifier -> wire metric mapping
# ---------------------------------------------------------------------------


def test_mapping_is_total() -> None:
    """Both directions, because each has its own silent failure mode.

    A `METRIC_REGISTRY` entry with no identifier pointing at it is a metric that can never be
    backfilled -- the column simply stays empty for the historical period and nothing raises.
    An identifier pointing at a name the registry does not hold is worse: `normalize_payload`'s
    D-04 branch drops the whole metric with one log line and no test failure, so the records ARE
    parsed, ARE counted as seen, and produce no rows.

    `backfill.py` asserts the same thing at IMPORT time. This test is the one that names which
    direction broke.
    """
    assert set(HK_TO_WIRE.values()) == set(METRIC_REGISTRY)
    assert len(HK_TO_WIRE) == EXPECTED_MAPPED_METRICS


def test_naming_traps() -> None:
    """The five pairs a hand-written mapping gets wrong, asserted one per line.

    HAE's `dietary_` prefix is inconsistent and `registry.py`'s own comment says a real
    third-party fixture in the wild gets `protein` wrong. One assertion per trap so the failure
    message names the trap rather than dumping a twelve-entry dict diff.
    """
    assert HK_TO_WIRE["HKQuantityTypeIdentifierDietaryFatTotal"] == "total_fat"
    assert HK_TO_WIRE["HKQuantityTypeIdentifierDietarySugar"] == "dietary_sugar"
    assert HK_TO_WIRE["HKQuantityTypeIdentifierDietaryProtein"] == "protein"
    assert HK_TO_WIRE["HKQuantityTypeIdentifierDietaryEnergyConsumed"] == "dietary_energy"
    distance = HK_TO_WIRE["HKQuantityTypeIdentifierDistanceWalkingRunning"]
    assert distance == "walking_running_distance"


def test_every_identifier_is_a_healthkit_quantity_type() -> None:
    """A category or workout identifier in this table would mean an unparseable element shape.

    `HKCategoryTypeIdentifier*` records carry `value="HKCategoryValueSleepAnalysisAsleep"` rather
    than a number, and workout identifiers appear on `<Workout workoutActivityType=...>`, which is
    not a `Record` at all. Either would reach the `Record` branch's `Decimal(raw_value)` and be
    counted as malformed on every single row -- a plausible-looking counter that is entirely a
    mapping bug.
    """
    offenders = [key for key in HK_TO_WIRE if not key.startswith(HK_QUANTITY_PREFIX)]
    assert not offenders, f"not HKQuantityTypeIdentifier*: {offenders}"


def test_body_mass_is_not_mapped() -> None:
    """SC#4's FIRST line of defence is the allowlist, before the Hevy predicate ever runs.

    52 of the 79 `BodyMass` records in the real export are Hevy's own write-back, but the other
    27 are not -- and D-01 keeps ALL of them out, because `body_measurements` already holds this
    data from Hevy at higher fidelity and there is no third source to arbitrate a disagreement.
    Relying on `is_hevy_sourced` here would let the 27 through.
    """
    assert _HK_BODY_MASS not in HK_TO_WIRE
    assert "weight_body_mass" not in METRIC_REGISTRY


def test_export_file_error_carries_no_detail() -> None:
    """T-09-07. Constructed from NOTHING, exactly like `HAEPayloadError`.

    The two things a caller would naturally want to interpolate are the path and the parse
    error's own message. The path is an operator argument the operator already knows; the parse
    message renders a byte offset into a document that is this person's entire health history.
    An `__init__` that accepted either would let a future edit put it in a log line, and no test
    elsewhere would notice -- so the signature itself is the guard.
    """
    exc = HAEExportFileError()
    assert exc.safe_message == "Apple Health export file could not be read as a HealthKit export"
    assert str(exc) == exc.safe_message

    parameters = list(inspect.signature(HAEExportFileError.__init__).parameters)
    assert parameters == ["self"], (
        f"HAEExportFileError.__init__ grew a parameter ({parameters}); a caller can now "
        f"interpolate a path or a parse offset into a health-data exception"
    )


# ---------------------------------------------------------------------------
# The streaming scan. Everything below runs `scan_export` over the fixture above.
# ---------------------------------------------------------------------------


def _scan() -> BackfillScan:
    return scan_export(hae_xml_fixture(FIXTURE_NAME), tz=TZ)


def _rows_for(scan: BackfillScan, metric: str) -> list[Any]:
    return [row for row in scan.normalized.rows if row.metric == metric]


def run_capturing_logs[T](
    monkeypatch: pytest.MonkeyPatch, action: Callable[[], T]
) -> tuple[T, list[dict[str, Any]]]:
    """Run `action` with the REAL logging pipeline rendered into a buffer.

    A near-copy of `test_health_auto_export_normalize.py`'s helper, and deliberately not an
    import of it: this one patches BOTH `backfill.log` and `normalize.log`, because a backfill
    run emits through both modules and the Pitfall 4 assertion is precisely that one module's
    event does not reach the stream while the other module's do.

    Not `structlog.testing.capture_logs`: that replaces the configured processor chain for its
    duration, which would leave a no-values-in-logs assertion green over a pipeline that never
    ran. It would also bypass stdlib logging entirely, and the stdlib handler is where
    `_MultiPointDayCounter` attaches -- so the suppression under test would not even run.

    `configure_logging` turns structlog's first-use cache ON. A proxy already cached by an
    earlier test keeps that test's configuration and would write somewhere else entirely,
    leaving this buffer empty -- a capture that silently checks nothing. So the cache is
    disabled and each module is handed a fresh proxy for the duration.
    """
    monkeypatch.setenv("ENVIRONMENT", "production")  # JSONRenderer; development is console
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    saved_logs = {module: module.log for module in (backfill, normalize)}
    try:
        configure_logging(Settings(_env_file=None))
        structlog.configure(cache_logger_on_first_use=False)
        for module in saved_logs:
            monkeypatch.setattr(module, "log", structlog.get_logger())
        buffer = io.StringIO()
        handler = root.handlers[0]
        assert isinstance(handler, logging.StreamHandler)
        handler.setStream(buffer)
        result = action()
        rendered = buffer.getvalue()
    finally:
        for module, saved in saved_logs.items():
            module.log = saved
        root.handlers, root.level = saved_handlers, saved_level
        structlog.reset_defaults()
    return result, [json.loads(line) for line in rendered.splitlines() if line.strip()]


def _events(entries: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [entry for entry in entries if entry.get("event") == name]


def test_non_record_elements_never_ingested() -> None:
    """SC#4, and RESEARCH Pitfall 3 specifically.

    The fixture's `<Workout sourceName="Hevy">` nests
    `<WorkoutStatistics type="HKQuantityTypeIdentifierActiveEnergyBurned" sum="228"/>`. A parser
    keyed on `type=` rather than on `elem.tag == "Record"` would add those 228 kcal to
    `active_energy` -- and the D-04 counter would still cheerfully report "1 workout skipped",
    so the summary would look correct while the number was wrong. `WorkoutStatistics` also
    carries no `sourceName`, so `is_hevy_sourced(None)` returns `False` by design and would not
    catch it on the way through either.

    Two independent assertions, because either alone can pass while the other fails: the total
    must be exactly the one legitimate record, AND no row may carry the `unknown` source-name
    sentinel that a `sourceName`-less element would produce.
    """
    scan = _scan()

    assert scan.workouts_skipped == EXPECTED_WORKOUTS
    assert scan.activity_summaries_skipped == EXPECTED_ACTIVITY_SUMMARIES
    assert scan.body_mass_skipped == EXPECTED_BODY_MASS_SKIPPED

    total_active_energy = sum((row.value for row in _rows_for(scan, "active_energy")), Decimal(0))
    assert total_active_energy == LEGITIMATE_ACTIVE_ENERGY, (
        f"expected exactly the one non-Hevy ActiveEnergyBurned record "
        f"({LEGITIMATE_ACTIVE_ENERGY}); {total_active_energy} means a WorkoutStatistics, an "
        f"ActivitySummary or the Hevy record reached a row"
    )
    assert not [row for row in scan.normalized.rows if row.source_name == UNKNOWN_SOURCE_NAME]


def test_hevy_active_energy_excluded() -> None:
    """HEALTH-08 / SC#4. The exclusion is `normalize.is_hevy_sourced`, unchanged.

    `backfill.py` only COUNTS the Hevy datapoints -- it still appends them to the payload, so
    `normalize_payload` is the single place the drop happens and the backfill and the webhook
    cannot drift apart on which datapoints are Hevy's. That is why the assertion below checks
    both sides: an advisory counter of 1 AND a real drop inside the normalizer.

    All 209 Hevy `ActiveEnergyBurned` records in the real export are pre-2025, from the period
    when Hevy demonstrably did write to HealthKit -- which is exactly the period this backfill
    imports. Phase 8 closed the question as MOOT for live sync; it is emphatically not moot here.
    """
    scan = _scan()

    assert scan.hevy_datapoints_excluded == EXPECTED_HEVY_EXCLUDED
    assert scan.normalized.datapoints_dropped >= EXPECTED_HEVY_EXCLUDED
    assert not [row for row in _rows_for(scan, "active_energy") if row.source_name == HEVY_SOURCE]


def test_unrecognized_types_are_counted_by_type_not_by_record() -> None:
    """D-04 granularity. 208,175 records in the real file land here; ~35 distinct types do.

    One log line and one counter entry per distinct identifier, never per record. This mirrors
    `health_ingest_unrecognized_metric`, which fires once per metric for the same reason.

    Body mass is asserted ABSENT from this table: it has its own counter because D-01 is a
    decision, and a decision that reads as an accident on the summary invites someone to "fix"
    it by adding the identifier back.
    """
    scan = _scan()

    assert set(scan.unrecognized_types) == {
        "HKQuantityTypeIdentifierWalkingSpeed",
        "HKQuantityTypeIdentifierWaistCircumference",
    }
    assert scan.records_unrecognized == EXPECTED_UNRECOGNIZED_RECORDS
    assert _HK_BODY_MASS not in scan.unrecognized_types


def test_malformed_record_does_not_abort(monkeypatch: pytest.MonkeyPatch) -> None:
    """D-07, and the reason this validation is not duplicated work.

    `HAEPayload.model_validate` validates ATOMICALLY. A single `value="not-a-number"` anywhere
    in a 191 MB export would raise `ValidationError` for all 230,395 datapoints at once, so
    validating per record on the way in is what keeps one bad element from costing the run.

    T-09-07: `reason` is a fixed token. The offending attribute value is a raw string out of a
    health-data file, and neither it nor the `value=` attribute text it came from may reach a
    log sink.
    """
    scan, entries = run_capturing_logs(monkeypatch, _scan)

    assert scan.records_malformed == EXPECTED_MALFORMED_RECORDS
    assert [row for row in scan.normalized.rows if row.local_day == BUSY_DAY], (
        "the scan aborted at the first malformed record instead of running to the end of file"
    )

    skipped = _events(entries, "health_backfill_record_skipped")
    assert len(skipped) == EXPECTED_MALFORMED_RECORDS
    assert {event["reason"] for event in skipped} == {"unparsable_value", "missing_start_date"}

    serialized = json.dumps(entries)
    assert "not-a-number" not in serialized, (
        "T-09-07 violated: the offending attribute value was rendered into a log line"
    )
    assert "value=" not in serialized


def test_record_accounting_identity_holds() -> None:
    """Every `<Record>` is inside a datapoint or explained by one of three counters.

    Without this, a record that the tag walk silently drops -- an early `continue`, a branch that
    forgets to count -- disappears with no symptom at all: the row set is still plausible, the
    summary is still internally consistent, and the missing days only surface as a gap in a trend
    months later.
    """
    scan = _scan()

    assert scan.records_total == EXPECTED_RECORDS
    assert scan.records_total == (
        scan.normalized.datapoints_seen
        + scan.records_unrecognized
        + scan.body_mass_skipped
        + scan.records_malformed
    )
    assert scan.normalized.datapoints_seen == EXPECTED_DATAPOINTS


def test_two_source_names_on_one_day_stay_two_rows() -> None:
    """`source_name` is INSIDE the natural key, so the same metric-day from two phones is two rows.

    This is the same property success criterion #3 depends on, seen from the other side: because
    the key includes `source_name`, a backfill that reproduced the webhook's string INEXACTLY
    would insert a second row rather than update the first -- silently, and invisibly.
    """
    scan = _scan()
    same_day = {
        row.source_name: row for row in _rows_for(scan, "step_count") if row.local_day == BUSY_DAY
    }

    assert set(same_day) == {DEVICE_CURRENT, DEVICE_PREVIOUS}
    assert same_day[DEVICE_CURRENT].sample_count == 2
    assert same_day[DEVICE_CURRENT].value == Decimal("1500")
    assert same_day[DEVICE_PREVIOUS].sample_count == 1


def test_source_name_matches_device_capture() -> None:
    """SC#3's pin at the ROW level, not just at the fixture level (RESEARCH Pitfall 2).

    The fixture-integrity test above proves `device_capture.json`'s sources appear in the XML.
    This one proves they survive the whole scan into `NormalizedRow.source_name` -- `.strip()`
    only, no ASCII-folding, no normalisation. That is what makes an overlapping metric-day ONE
    row instead of two when the backfill and the live webhook both cover it.

    A SUBSET, not equality: the rows also carry `Vegant's iPhone`, the pre-rename name that is
    still 86% of the real export and which the current webhook never sends.
    """
    scan = _scan()
    capture: dict[str, Any] = hae_fixture("device_capture")
    webhook_sources = {
        point["source"]
        for metric in capture["data"]["metrics"]
        for point in metric["data"]
        if "source" in point
    }

    assert webhook_sources <= {row.source_name for row in scan.normalized.rows}


def test_multi_point_day_warning_is_suppressed_and_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RESEARCH Pitfall 4, both halves: suppressed HERE, still warning for the WEBHOOK.

    `health_ingest_multi_point_day` fires 7,403 times on the real file -- 91.7% of rows -- because
    raw HealthKit samples are per-event. For the webhook the same warning means the device's daily
    aggregation has drifted and replace semantics has become lossy, which is a real incident. The
    backfill therefore suppresses and counts it, and `normalize.py` is not touched.

    The second half is the one that would rot: a filter left attached to the root handler would
    silently eat the webhook's warning for the rest of the process, and nothing else in the suite
    would notice.
    """
    scan, entries = run_capturing_logs(monkeypatch, _scan)

    assert scan.multi_point_days == EXPECTED_MULTI_POINT_DAYS
    assert not _events(entries, "health_ingest_multi_point_day"), (
        "Pitfall 4: the multi-point-day warning escaped the backfill's suppression"
    )
    # A sanity check on the capture itself: an empty buffer would make the assertion above
    # vacuously true. Other backfill events must still be present.
    assert _events(entries, "health_backfill_parsed")

    _, after = run_capturing_logs(
        monkeypatch, lambda: normalize_payload(_two_point_payload(), tz=TZ)
    )
    assert _events(after, "health_ingest_multi_point_day"), (
        "the suppression filter outlived the backfill: the WEBHOOK path must still warn"
    )


def _two_point_payload() -> HAEPayload:
    """Two datapoints for one `(metric, source_name, local_day)` key -- the warning's trigger."""
    point = {"qty": 1, "date": "2026-09-02 08:00:00 +0700", "source": DEVICE_CURRENT}
    return HAEPayload.model_validate(
        {"data": {"metrics": [{"name": "step_count", "units": "count", "data": [point, point]}]}}
    )


def test_unreadable_file_raises_a_detail_free_error(tmp_path: Path) -> None:
    """T-09-07. Two structural failures, one detail-free exception.

    `str(exc)` must contain neither the path -- which would put the location of this person's
    entire health history into whatever the caller logs -- nor the word `line`, which is how
    `ET.ParseError` renders a byte offset into that same document.
    """
    missing = tmp_path / "does-not-exist.xml"
    not_healthkit = tmp_path / "other.xml"
    not_healthkit.write_text("<NotHealthData/>", encoding="utf-8")

    for path in (missing, not_healthkit):
        with pytest.raises(HAEExportFileError) as raised:
            scan_export(path, tz=TZ)
        message = str(raised.value)
        assert str(path) not in message
        assert path.name not in message
        assert "line" not in message.lower()
