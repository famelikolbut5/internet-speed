import subprocess
import sys
from io import StringIO
from time import perf_counter

import pytest
from rich.console import Console

from speedcheck import cli


def test_cli_runs_as_a_module_and_prints_plain_summary(server):
    base, _ = server
    completed = subprocess.run(
        [sys.executable, "-m", "speedcheck", base + "/data", "--timeout", "5"],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert completed.returncode == 0
    assert "10/10" in completed.stdout
    assert "Mbit/s" in completed.stdout
    assert "1310730" in completed.stdout
    assert "\x1b[" not in completed.stdout
    assert completed.stderr == ""


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "invalid"])
def test_invalid_timeout_is_a_usage_error(value, capsys):
    with pytest.raises(SystemExit) as error:
        cli.main(["https://example.com", "--timeout", value])
    assert error.value.code == 2
    assert "Timeout" in capsys.readouterr().err


def test_non_http_url_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as error:
        cli.main(["file:///example"])
    assert error.value.code == 2
    assert "http://" in capsys.readouterr().err


def test_failure_has_no_success_summary_or_traceback(server, capsys):
    base, _ = server
    assert cli.main([base + "/error"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "HTTP 503" in captured.err
    assert "Traceback" not in captured.err


def test_ninth_request_rate_limit_stops_without_summary(server, capsys):
    base, state = server
    assert cli.main([base + "/rate-limited"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Request 9/10: HTTP 429" in captured.err
    assert state["paths"] == ["/rate-limited"] * 9


def test_keyboard_interrupt_returns_130(monkeypatch, capsys):
    def interrupt(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "measure", interrupt)
    assert cli.main(["https://example.com"]) == 130
    assert "Cancelled" in capsys.readouterr().err


@pytest.mark.parametrize(("disabled", "redirected"), [(False, False), (True, False), (False, True)])
def test_progress_respects_terminal_and_option(server, monkeypatch, disabled, redirected):
    base, _ = server
    output, errors = StringIO(), StringIO()
    frames = []

    class RecordingLive(cli.Live):
        def update(self, *args, **kwargs):
            frames.append(perf_counter())
            return super().update(*args, **kwargs)

    monkeypatch.setattr(cli, "Live", RecordingLive)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("TTY_INTERACTIVE", raising=False)
    monkeypatch.setattr(
        cli,
        "Console",
        lambda **kwargs: Console(
            file=errors if kwargs.get("stderr") else output,
            force_terminal=bool(kwargs.get("stderr")) or not redirected,
            width=100,
            color_system=None,
            legacy_windows=False,
        ),
    )
    args = [base + "/slow"] + (["--no-progress"] if disabled else [])
    assert cli.main(args) == 0
    expected_progress = not disabled and not redirected
    assert ("Request" in errors.getvalue()) == expected_progress
    assert "10/10" in output.getvalue()
    if expected_progress:
        assert len(frames) >= 2
        assert all(right - left >= 0.2 for left, right in zip(frames, frames[1:], strict=False))
