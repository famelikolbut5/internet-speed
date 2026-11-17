import math
import socket
from unittest.mock import patch

import pytest

from speedcheck.measurement import MeasurementError, Result, measure, validate_url


def test_summary_uses_total_bytes_over_total_time():
    result = Result(total_bytes=25_000_000, total_seconds=4.0)
    assert result.average_seconds == 0.4
    assert result.megabits_per_second == 50.0


@pytest.mark.parametrize("path", ["/data", "/unknown", "/chunked"])
def test_downloads_ten_complete_responses(server, path):
    base, state = server
    result = measure(base + path)
    assert state["paths"] == [path] * 10
    assert result.total_bytes == 131_073 * 10
    assert result.total_seconds > 0
    assert all(headers["Accept-Encoding"] == "identity" for headers in state["headers"])


def test_waits_for_each_body_before_starting_next_request(server):
    base, state = server
    result = measure(base + "/slow")
    assert state["events"] == ["start", "finish"] * 10
    assert result.total_seconds >= 0.2


def test_counts_empty_responses_without_dividing_by_zero(server):
    base, _ = server
    result = measure(base + "/empty")
    assert result.total_bytes == 0
    assert result.megabits_per_second == 0


@pytest.mark.parametrize(
    ("path", "message"),
    [("/redirect", "Redirect refused"), ("/error", "HTTP 503"), ("/truncated", "declared bytes")],
)
def test_rejects_failed_or_incomplete_download_without_retry(server, path, message):
    base, state = server
    with pytest.raises(MeasurementError, match=message):
        measure(base + path)
    assert state["paths"] == [path]


@pytest.mark.parametrize("path", ["/timeout", "/body-timeout"])
def test_enforces_timeout_before_headers_and_during_body(server, path):
    base, state = server
    with pytest.raises(MeasurementError, match="timed out"):
        measure(base + path, timeout=0.03)
    assert state["paths"] == [path]


def test_reports_connection_refusal(refused_url):
    with pytest.raises(MeasurementError, match="connect|timed out"):
        measure(refused_url, timeout=0.1)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://localhost/data",
        "data:text/plain,test",
        "example.com",
        "http://",
        "http://localhost:0",
        "http://localhost:70000",
        "http://localhost:bad",
        "http://[broken",
        "https://" + "a" * 64 + ".invalid",
        "https://user:secret@example.com/",
        "http://example.com/\nheader",
        "http://example.com/a b",
        "https://example.com/тест",
    ],
)
def test_rejects_invalid_or_unsupported_urls(url):
    with pytest.raises(ValueError):
        validate_url(url)


def test_removes_fragment_without_altering_query():
    assert validate_url("https://example.com/file?token=a%2Fb#part") == (
        "https://example.com/file?token=a%2Fb"
    )


def test_accepts_ipv6_literal_with_port():
    assert validate_url("http://[::1]:8080/file") == "http://[::1]:8080/file"


def test_socket_initialization_error_is_reported():
    with (
        patch("socket.socket", side_effect=OSError("socket unavailable")),
        pytest.raises(MeasurementError, match="initialize a network socket"),
    ):
        measure("http://127.0.0.1:1")


def test_resolution_error_is_reported_without_echoing_url(monkeypatch):
    monkeypatch.setenv("no_proxy", "*")
    with (
        patch("socket.getaddrinfo", side_effect=socket.gaierror("unknown host")),
        pytest.raises(MeasurementError, match="Request 1/10: Could not connect") as error,
    ):
        measure("https://example.invalid/file?token=test")
    assert "token" not in str(error.value)


@pytest.mark.parametrize("timeout", [0, -1, math.inf, -math.inf, math.nan])
def test_rejects_invalid_timeout_before_network_io(timeout):
    with pytest.raises(ValueError, match="Timeout"):
        measure("http://127.0.0.1:1", timeout=timeout)


def test_progress_reports_actual_bytes_and_unknown_sizes(server):
    base, _ = server
    updates = []
    measure(base + "/unknown", on_progress=lambda *event: updates.append(event))
    for number in range(1, 11):
        events = [event for event in updates if event[0] == number]
        assert events[0] == (number, 0, None)
        assert events[-1] == (number, 131_073, None)
        assert [event[1] for event in events] == sorted(event[1] for event in events)


@pytest.mark.parametrize("server", ["tls"], indirect=True)
def test_rejects_untrusted_tls_certificate(server):
    base, state = server
    with pytest.raises(MeasurementError, match="TLS certificate verification failed"):
        measure(base + "/data")
    assert state["paths"] == []


def test_rejects_incomplete_chunked_response(server):
    base, state = server
    with pytest.raises(MeasurementError, match="Invalid or incomplete"):
        measure(base + "/bad-chunks")
    assert state["paths"] == ["/bad-chunks"]


def test_accumulates_request_times_without_inter_request_gaps(server, monkeypatch):
    base, _ = server
    ticks = iter(value for index in range(10) for value in (index * 100, index * 100 + index + 1))
    monkeypatch.setattr("speedcheck.measurement.perf_counter", lambda: next(ticks))
    result = measure(base + "/data")
    assert result.total_seconds == 55
    assert result.average_seconds == 5.5


def test_reports_platform_timeout_overflow_without_network_io(server):
    base, state = server
    with pytest.raises(MeasurementError, match="supported limit"):
        measure(base + "/data", timeout=1e308)
    assert state["paths"] == []


@pytest.mark.parametrize(
    ("path", "message"),
    [("/invalid-redirect", "Redirect refused"), ("/partial", "HTTP 206")],
)
def test_rejects_unusable_response_without_another_request(server, path, message):
    base, state = server
    with pytest.raises(MeasurementError, match=message):
        measure(base + path)
    assert state["paths"] == [path]
