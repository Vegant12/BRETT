"""Hevy transport errors, split by whether retrying them can possibly help.

The split is the point. Retrying a 401 burns the entire backoff budget and turns an
immediate, obvious "your API key is wrong" into an opaque timeout sixty seconds later
(Pitfall 7). Retrying a 429 or a 5xx is exactly right.

No exception in this module ever carries the API key, a request header, or a response body.
`safe_message` is the OPT-IN channel for detail that has been checked by hand: everything
that reads an exception for storage or logging (see
``app.db.repositories.sync_state.format_sync_error``) uses only the class name unless that
attribute is present.
"""

import httpx2


class HevyError(Exception):
    """Base for every Hevy transport failure."""

    safe_message: str = ""


class HevyAuthError(HevyError):
    """401/403. Never retried. Never contains the key that was rejected.

    Constructed from a STATUS CODE and nothing else, deliberately: an ``__init__`` that
    accepted a message would let some future caller interpolate the rejected credential
    into it, and no test elsewhere would notice (T-03-16).
    """

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.safe_message = f"Hevy rejected the API key (HTTP {status_code})"
        super().__init__(self.safe_message)


class HevyRateLimited(HevyError):
    """429. Retried.

    ``retry_after`` is whatever Hevy sent, or ``None`` -- the API documents no rate limit at
    all, so this value is the only empirical evidence this project will ever get (D-10).
    """

    def __init__(self, retry_after: str | None = None) -> None:
        self.retry_after = retry_after
        self.safe_message = "Hevy rate limited the request (HTTP 429)"
        super().__init__(self.safe_message)


class HevyServerError(HevyError):
    """5xx. Retried."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.safe_message = f"Hevy returned a server error (HTTP {status_code})"
        super().__init__(self.safe_message)


class HevyClientError(HevyError):
    """A non-retryable 4xx (400 bad page size, etc.).

    Not retried: the same request will fail the same way, so a backoff sequence only delays
    the moment somebody finds out.
    """

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.safe_message = f"Hevy rejected the request (HTTP {status_code})"
        super().__init__(self.safe_message)


class HevyPageNotFound(HevyClientError):
    """404.

    Only ``/v1/body_measurements`` documents this, and there it means "you paged past the
    end", not "something broke". The caller treats it as a terminator, so it must NOT be
    retryable (Pitfall 5) -- retrying it would spend the whole backoff budget on a run that
    had already fetched everything.
    """


class HevyResponseError(HevyError):
    """A response that did not match the schema.

    Wraps a pydantic ``ValidationError`` WITHOUT reproducing its message:
    ``ValidationError.__str__`` renders ``input_value=...``, i.e. the user's workout titles
    and body-composition numbers (T-03-18, FOUND-05).
    """

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint
        self.safe_message = f"Hevy response did not match the expected schema for {endpoint}"
        super().__init__(self.safe_message)


# ``httpx2.TransportError`` is the correct base class: ``ConnectError``, ``ReadError`` (via
# ``NetworkError``), ``ConnectTimeout`` and ``ReadTimeout`` (via ``TimeoutException``) all
# descend from it, while ``HTTPStatusError`` does NOT -- so listing it here retries the
# network failures without accidentally retrying a status the mapping above already
# classified as permanent.
#
# ``retry_if_exception_type`` matches SUBCLASSES, which is why `HevyPageNotFound` inherits
# from `HevyClientError` (absent here) rather than from anything in this tuple.
RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    HevyRateLimited,
    HevyServerError,
    httpx2.TransportError,
)
