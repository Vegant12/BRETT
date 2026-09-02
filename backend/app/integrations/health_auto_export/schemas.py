"""Pydantic mirrors of Health Auto Export's LIVE wire format (HEALTH-06, NUTR-02).

This module is the quarantine boundary. If HAE renames a field, validation fails HERE rather
than a `None` propagating into the database and surfacing three phases later as a wrong calorie
figure.

Transcribed from five real captured device payloads and the vendor's own reference server, NOT
from the vendor's published TypeScript interface, which is wrong in two places that matter:
`units` is declared per-datapoint (no real payload has it there; the vendor's own `mapMetric`
reads the metric-level field) and `source` is declared required (it is absent entirely for gait
metrics in every real payload).

Every model sets `hide_input_in_errors=True`. A `ValidationError` from this module would
otherwise render `input_value=...` -- this person's calorie counts and macro grams -- into a
message that could reach a log line and `sync_state.last_error` (T-08-21, FOUND-05).
"""

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.integrations.health_auto_export.errors import HAEDateFormatError


class _HAEModel(BaseModel):
    """Shared config for every wire model.

    ``extra="ignore"`` on purpose, and asymmetrically so: HAE ADDING a field must not break an
    ingest -- the app ships whenever it likes and the user can toggle new data types on from
    the phone -- while a field this module NAMES going missing must be visible here. It is also
    what structurally implements D-02: the ``workouts`` array that sits beside ``metrics``
    inside ``data`` is ignored, so Apple Health workouts cannot enter BRETT even by accident.
    """

    model_config = ConfigDict(hide_input_in_errors=True, extra="ignore")


class HAEDataPoint(_HAEModel):
    """One datapoint. EVERY field is optional, and that is a deliberate deviation.

    Health Auto Export has no documented retry, so a rejected batch is permanent data loss for
    the whole window (D-04). Pydantic validates a payload atomically, so one required field
    would let a single odd datapoint -- e.g. a heart-rate metric the user toggled on, whose
    datapoints carry Min/Max/Avg and no ``qty`` at all -- destroy an entire day of steps AND
    nutrition. Optional fields push the decision down to ``normalize.py``, which drops ONE
    datapoint and logs it (T-08-24).

    ``qty`` is ``Decimal``, never ``float``: HAE prorates ``count``-unit metrics across
    aggregation buckets, so ``flights_climbed`` really does arrive as 0.20163697817574894 and a
    float would make the same inputs produce order-dependent sums (RESEARCH Finding C).

    ``date`` is the RAW wire string, parsed by ``parse_hae_datetime`` in ``normalize.py``.
    Parsing here would make one malformed timestamp a whole-payload failure, which is the same
    trap again.

    ``source`` is ``str | None``: it is ABSENT ENTIRELY for gait metrics in every real captured
    payload, despite the vendor's own TypeScript interface declaring it required.
    """

    qty: Decimal | None = None
    date: str | None = None
    source: str | None = None


class HAEMetric(_HAEModel):
    """One metric. ``units`` lives HERE, at the metric level, and nowhere else.

    The vendor's ``BaseMetric`` interface declares ``units`` on each datapoint; no real payload
    contains it there, and the vendor's own ``mapMetric`` reads ``metric.units``. Defaulting to
    ``""`` rather than requiring it keeps a units-less metric from failing the whole payload --
    ``to_canonical`` rejects ``""`` per datapoint, loudly.

    ``name`` is a free-form ``str``, not a ``Literal`` over the registry: an unlisted metric
    must PARSE and then be dropped by name (D-04), because failing validation on it would cost
    the recognised metrics sitting beside it in the same payload.
    """

    name: str
    units: str = ""
    data: list[HAEDataPoint] = Field(default_factory=list)


class HAEData(_HAEModel):
    """The ``data`` envelope. Its ``workouts`` sibling is deliberately unmodelled (D-02)."""

    metrics: list[HAEMetric] = Field(default_factory=list)


class HAEPayload(_HAEModel):
    """The webhook body. ``data`` is the ONLY required field in this module.

    Its absence is a broken envelope -- a misconfigured exporter or something that is not HAE
    at all -- not an odd datapoint, so it is the one failure that should reject the request
    rather than be salvaged.
    """

    data: HAEData


# Real payloads: "2025-08-15 00:00:00 +0900" -- NOT ISO 8601, which is why pydantic's native
# `datetime` field type is not used. The 12-hour variant appears in 12-hour locales, and newer
# iOS inserts U+202F NARROW NO-BREAK SPACE before AM/PM rather than a plain space. A
# third-party receiver additionally reports seeing a true ISO form.
#
# THIS PARSER IS SHARED WITH PHASE 9. `export.xml`, `records.csv` and the webhook JSON all use
# this format -- verified against the user's own records.csv ("2026-08-21 12:35:53 +0700"). Do
# not write a second one; two parsers produce two shapes and the historical trend silently
# disagrees with the ongoing one.
_HAE_DATE_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d %H:%M:%S %z",
    "%Y-%m-%d %I:%M:%S %p %z",
)
# Written as an ESCAPE, never as a literal: a bare U+202F in source is invisible in every
# diff and every review, and one careless editor normalising it to a plain space silently
# disables this whole branch.
_NARROW_NO_BREAK_SPACE = "\u202f"


def parse_hae_datetime(value: str) -> dt.datetime:
    """Parse an HAE timestamp into a TIMEZONE-AWARE datetime. FOUND-04.

    Raises ``HAEDateFormatError``, which carries no input, rather than returning None: a naive
    or unparsed timestamp silently mis-buckets a whole local day (``core.time._require_aware``
    exists for exactly this reason).

    ``raise ... from None`` throughout: chaining would attach the original ``ValueError``,
    whose message renders the input string straight into the traceback.
    """
    candidate = value.strip().replace(_NARROW_NO_BREAK_SPACE, " ")
    for fmt in _HAE_DATE_FORMATS:
        try:
            # Every format in `_HAE_DATE_FORMATS` ends in `%z`, and an offset-less result is
            # rejected below -- ruff cannot see that through the loop variable.
            parsed = dt.datetime.strptime(candidate, fmt)  # noqa: DTZ007
        except ValueError:
            continue
        if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
            raise HAEDateFormatError
        return parsed
    try:
        parsed = dt.datetime.fromisoformat(candidate)
    except ValueError:
        raise HAEDateFormatError from None
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise HAEDateFormatError
    return parsed
