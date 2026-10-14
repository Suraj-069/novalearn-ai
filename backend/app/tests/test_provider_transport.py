"""Transient provider responses use short bounded retries without retrying uncertain POSTs."""
import httpx
import pytest

from app.services.providers import transport


def test_transient_status_retries_with_bounded_exponential_backoff(monkeypatch):
    replies = iter([
        httpx.Response(503),
        httpx.Response(502),
        httpx.Response(200),
    ])
    calls = []
    delays = []

    def send():
        calls.append(1)
        return next(replies)

    monkeypatch.setattr(transport.time, "sleep", delays.append)
    response = transport.post_with_retries(send)

    assert response.status_code == 200
    assert len(calls) == transport.MAX_ATTEMPTS == 3
    assert delays == [0.5, 1.0]


def test_short_retry_after_is_honored_for_rate_limit(monkeypatch):
    replies = iter([httpx.Response(429, headers={"Retry-After": "1"}), httpx.Response(200)])
    delays = []
    monkeypatch.setattr(transport.time, "sleep", delays.append)

    response = transport.post_with_retries(lambda: next(replies))

    assert response.status_code == 200 and delays == [1.0]


@pytest.mark.parametrize("headers", [
    {}, {"Retry-After": "60"}, {"Retry-After": "invalid"},
    {"Retry-After": "-1"}, {"Retry-After": "nan"},
])
def test_rate_limit_without_short_retry_hint_fails_immediately(headers, monkeypatch):
    calls = []
    delays = []
    monkeypatch.setattr(transport.time, "sleep", delays.append)

    response = transport.post_with_retries(lambda: (calls.append(1), httpx.Response(429, headers=headers))[1])

    assert response.status_code == 429
    assert len(calls) == 1 and delays == []


def test_permanent_http_error_is_not_retried(monkeypatch):
    calls = []
    delays = []
    monkeypatch.setattr(transport.time, "sleep", delays.append)

    response = transport.post_with_retries(lambda: (calls.append(1), httpx.Response(401))[1])

    assert response.status_code == 401
    assert len(calls) == 1 and delays == []


def test_read_timeout_is_not_retried_to_avoid_duplicate_provider_work(monkeypatch):
    calls = []
    delays = []
    monkeypatch.setattr(transport.time, "sleep", delays.append)

    def send():
        calls.append(1)
        raise httpx.ReadTimeout("request timed out")

    with pytest.raises(httpx.ReadTimeout):
        transport.post_with_retries(send)

    assert len(calls) == 1 and delays == []


def test_connection_failure_is_retried_then_succeeds(monkeypatch):
    calls = []
    delays = []
    monkeypatch.setattr(transport.time, "sleep", delays.append)

    def send():
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200)

    response = transport.post_with_retries(send)

    assert response.status_code == 200
    assert len(calls) == 2 and delays == [0.5]
