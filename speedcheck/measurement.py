import math
import socket
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from http.client import HTTPException
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

REQUEST_COUNT = 10
CHUNK_SIZE = 64 * 1024
ProgressCallback = Callable[[int, int, int | None], None]


class MeasurementError(Exception):
    pass


@dataclass(frozen=True)
class Result:
    total_bytes: int
    total_seconds: float

    @property
    def average_seconds(self) -> float:
        return self.total_seconds / REQUEST_COUNT

    @property
    def megabits_per_second(self) -> float:
        return self.total_bytes * 8 / self.total_seconds / 1_000_000


class _NoRedirect(HTTPRedirectHandler):
    def http_error_302(self, req, fp, code, msg, headers):
        fp.close()
        raise MeasurementError("Redirect refused. Use the final HTTP(S) URL.")

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


def validate_url(url: str) -> str:
    if not url.isascii() or any(ord(char) <= 32 or ord(char) == 127 for char in url):
        raise ValueError("Use an ASCII URL without whitespace or control characters.")
    try:
        parts = urlsplit(url)
        valid_port = parts.port is None or parts.port > 0
    except ValueError:
        raise ValueError("Invalid URL host or port.") from None
    if parts.scheme not in {"http", "https"} or not parts.hostname or not valid_port:
        raise ValueError("Use an absolute http:// or https:// URL with a valid host and port.")
    if parts.username is not None or parts.password is not None:
        raise ValueError("Credentials in URLs are not supported.")
    if ":" not in parts.hostname:
        try:
            parts.hostname.encode("idna")
        except UnicodeError:
            raise ValueError("Invalid DNS hostname.") from None
    return parts._replace(fragment="").geturl()


def measure(
    url: str,
    timeout: float = 15.0,
    on_progress: ProgressCallback | None = None,
) -> Result:
    url = validate_url(url)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Timeout must be a finite positive number.")
    try:
        with socket.socket() as probe:
            probe.settimeout(timeout)
    except OverflowError:
        raise MeasurementError("Timeout exceeds this platform's supported limit.") from None
    except OSError:
        raise MeasurementError("Could not initialize a network socket.") from None
    opener = build_opener(_NoRedirect())
    request = Request(url, headers={"Accept-Encoding": "identity", "Cache-Control": "no-cache"})
    total_bytes = 0
    total_seconds = 0.0
    for number in range(1, REQUEST_COUNT + 1):
        if on_progress is not None:
            on_progress(number, 0, None)
        started = perf_counter()
        try:
            with opener.open(request, timeout=timeout) as response:
                if response.status != 200:
                    raise MeasurementError(f"Expected HTTP 200, received HTTP {response.status}.")
                expected = response.length
                received = 0
                while chunk := response.read(CHUNK_SIZE):
                    received += len(chunk)
                    if on_progress is not None:
                        on_progress(number, received, expected)
                elapsed = perf_counter() - started
                if expected is not None and received != expected:
                    raise MeasurementError("Response ended before all declared bytes arrived.")
        except HTTPError as error:
            error.close()
            raise MeasurementError(
                f"Request {number}/{REQUEST_COUNT}: HTTP {error.code}."
            ) from None
        except MeasurementError as error:
            raise MeasurementError(f"Request {number}/{REQUEST_COUNT}: {error}") from None
        except (URLError, OSError, HTTPException) as error:
            reason = error.reason if isinstance(error, URLError) else error
            if isinstance(reason, ssl.SSLCertVerificationError):
                message = "TLS certificate verification failed."
            elif isinstance(reason, TimeoutError):
                message = "Network operation timed out."
            elif isinstance(reason, HTTPException):
                message = "Invalid or incomplete HTTP response."
            else:
                message = "Could not connect or read the response."
            raise MeasurementError(f"Request {number}/{REQUEST_COUNT}: {message}") from None
        total_bytes += received
        total_seconds += elapsed
    return Result(total_bytes, total_seconds)
