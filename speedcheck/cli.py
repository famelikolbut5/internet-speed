import argparse
import math
from collections.abc import Sequence
from contextlib import nullcontext
from time import perf_counter

from rich.console import Console
from rich.live import Live
from rich.progress_bar import ProgressBar
from rich.table import Table

from speedcheck.measurement import REQUEST_COUNT, MeasurementError, measure, validate_url


def _url(value: str) -> str:
    try:
        return validate_url(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from None


def _timeout(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("Timeout must be a number.") from None
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("Timeout must be finite and greater than zero.")
    return seconds


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure 10 sequential HTTP downloads.")
    parser.add_argument("url", type=_url, help="direct HTTP(S) URL to download")
    parser.add_argument(
        "--timeout",
        type=_timeout,
        default=15.0,
        metavar="SECONDS",
        help="socket operation timeout, not a total deadline (default: 15)",
    )
    parser.add_argument("--no-progress", action="store_true", help="disable the progress display")
    args = parser.parse_args(argv)
    output = Console(highlight=False)
    errors = Console(stderr=True, highlight=False)
    enabled = output.is_terminal and errors.is_interactive and not args.no_progress
    live = Live(console=errors, auto_refresh=False, transient=True)
    last_refresh = 0.0

    def update(number: int, received: int, expected: int | None) -> None:
        nonlocal last_refresh
        now = perf_counter()
        if now - last_refresh >= 0.2:
            size = f"{received / 1_000_000:.2f} MB"
            if expected:
                size = f"{received / expected:.0%}  {size} / {expected / 1_000_000:.2f} MB"
            line = Table.grid(padding=(0, 2))
            line.add_row(
                f"[cyan]Request {number}/{REQUEST_COUNT}",
                ProgressBar(total=expected, completed=received, width=24),
                size,
            )
            live.update(line, refresh=True)
            last_refresh = perf_counter()

    try:
        with live if enabled else nullcontext():
            result = measure(args.url, args.timeout, update if enabled else None)
    except MeasurementError as error:
        errors.print(f"Error: {error}", style="red", markup=False)
        return 1
    except KeyboardInterrupt:
        errors.print("Cancelled.", style="yellow")
        return 130
    table = Table.grid(padding=(0, 3))
    table.add_column()
    table.add_column(justify="right")
    table.add_row("Completed requests", f"{REQUEST_COUNT}/{REQUEST_COUNT}")
    table.add_row("Download speed", f"{result.megabits_per_second:.2f} Mbit/s", style="bold cyan")
    table.add_row("Average request time", f"{result.average_seconds:.3f} s")
    table.add_row("Downloaded data", f"{result.total_bytes / 1_000_000:.2f} MB")
    table.add_row("Downloaded bytes", str(result.total_bytes))
    output.print(table)
    return 0
