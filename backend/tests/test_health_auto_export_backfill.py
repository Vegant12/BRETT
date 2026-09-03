"""Coverage for the historical `export.xml` backfill: HEALTH-10, success criteria #3 and #4.

This plan (09-01) builds the TEST BED only, so what is here is fixture integrity: assertions
about `backend/tests/fixtures/hae/export_sample.xml` itself. Nothing here imports the reader
module (`backfill.py`, inside the HAE package) -- it does not exist until plan 09-02, and a
test file that cannot even be collected is a test file that proves nothing about the fixture it
was written to guard.

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

from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

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
