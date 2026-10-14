"""Bounded retries for transient provider HTTP responses."""
import math
import time
from collections.abc import Callable

import httpx


RETRYABLE_STATUS_CODES = {500, 502, 503, 504}
MAX_ATTEMPTS = 3
MAX_BACKOFF_SECONDS = 2.0


def post_with_retries(send: Callable[[], httpx.Response]) -> httpx.Response:
    """Retry explicit transient HTTP responses and connection failures only.

    Read/write timeouts are not retried: a provider may have processed a POST
    before the client timed out, and retrying could duplicate work or charges.
    """
    response = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = send()
        except httpx.ConnectError:
            if attempt == MAX_ATTEMPTS - 1:
                raise
            delay = min(0.5 * (2 ** attempt), MAX_BACKOFF_SECONDS)
            time.sleep(delay)
            continue

        if response.status_code not in RETRYABLE_STATUS_CODES | {429} or attempt == MAX_ATTEMPTS - 1:
            return response

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            try:
                delay = float(retry_after) if retry_after else None
            except ValueError:
                delay = None
            # Retry throttling only when the provider gives a short reset hint.
            # Quota exhaustion (429 without a short Retry-After) cannot be fixed by rapid retries.
            if delay is None or not math.isfinite(delay) or delay < 0 or delay > MAX_BACKOFF_SECONDS:
                return response
        else:
            delay = min(0.5 * (2 ** attempt), MAX_BACKOFF_SECONDS)
        time.sleep(delay)

    # The loop returns or raises on every pass; this is a defensive invariant.
    raise RuntimeError("Provider retry loop ended without a response")
