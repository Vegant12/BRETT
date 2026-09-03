"""Health Auto Export ingest errors.

No exception in this module ever carries a quantity, a payload fragment, or the presented
credential. ``safe_message`` is the OPT-IN channel for detail that has been checked by hand:
everything that reads an exception for storage or logging (see
``app.db.repositories.sync_state.format_sync_error``) uses only the class name unless that
attribute is present.

Deliberately no HTTP client import of any kind. This integration is INBOUND -- HAE calls
BRETT, never the reverse -- and ``test_health_auto_export_isolation.py`` asserts that no module
in this package imports one.
"""


class HAEError(Exception):
    """Base for every Health Auto Export ingest failure."""

    safe_message: str = ""


class HAEPayloadError(HAEError):
    """The webhook body did not match the expected envelope.

    Wraps a pydantic ``ValidationError`` WITHOUT reproducing its message:
    ``ValidationError.__str__`` renders ``input_value=...``, i.e. this person's calorie counts
    and macro grams, into a string that would reach a log line and ``sync_state.last_error``
    (T-08-21, FOUND-05). Constructed from NOTHING, deliberately: an ``__init__`` that accepted
    a message would let a future caller interpolate the payload into it and no test elsewhere
    would notice.
    """

    def __init__(self) -> None:
        self.safe_message = "Health Auto Export payload did not match the expected envelope"
        super().__init__(self.safe_message)


class HAEDateFormatError(HAEError):
    """A datapoint timestamp matched none of the known formats.

    Carries NO value. A timestamp is not health data, but it is user-controlled input reaching
    a log sink, and there is nothing a caller can do with it that the format list does not
    already say.
    """

    def __init__(self) -> None:
        self.safe_message = "Health Auto Export timestamp matched no known format"
        super().__init__(self.safe_message)


class UnknownUnitError(HAEError):
    """A metric arrived in a unit the registry does not accept.

    Carries the METRIC NAME and the UNIT STRING and never the measured value: a metric name and
    a unit are structural facts, a measured value is personal health data (T-08-22, Shared
    Pattern 3). The unit is truncated because it is attacker-controlled and lands in a log line.
    """

    _MAX_UNIT_LEN = 32

    def __init__(self, *, metric: str, unit: str) -> None:
        self.metric = metric
        self.unit = unit[: self._MAX_UNIT_LEN]
        self.safe_message = f"unsupported unit {self.unit!r} for metric {metric!r}"
        super().__init__(self.safe_message)


class HAEExportFileError(HAEError):
    """The Apple Health export file could not be read as a HealthKit export.

    Covers an unreadable path, a file whose root element is not ``HealthData``, and a parse
    failure that is structural rather than per-record. Carries NO detail from the file and no
    path: the path is an operator argument the operator already knows, and the parse error's own
    message renders a byte offset into a document that is this person's entire health history
    (T-09-07). Constructed from NOTHING, exactly like :class:`HAEPayloadError` -- an ``__init__``
    that accepted a message would let a future caller interpolate the path, or the offending
    line, straight into a log line.
    """

    def __init__(self) -> None:
        self.safe_message = "Apple Health export file could not be read as a HealthKit export"
        super().__init__(self.safe_message)
