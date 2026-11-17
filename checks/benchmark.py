import json
import multiprocessing
import os
import platform
import tracemalloc
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer
from statistics import median
from time import perf_counter, process_time, sleep
from unittest.mock import patch

from rich.console import Console

from speedcheck.cli import main
from speedcheck.measurement import measure


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        path, _, query = self.path.partition("?")
        try:
            size = int(path.removeprefix("/"))
        except ValueError:
            self.send_error(404)
            return
        if not 0 <= size <= 64 * 1024**2:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(size))
        self.end_headers()
        chunk = b"x" * 65_536
        for offset in range(0, size, len(chunk)):
            if query == "slow":
                sleep(0.002)
            self.wfile.write(chunk[: size - offset])


def serve(pipe):
    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        pipe.send(server.server_port)
        pipe.close()
        server.serve_forever()


def run(base: str) -> dict:
    memory = []
    measure(f"{base}/65536")
    for size in (8 * 1024**2, 64 * 1024**2):
        tracemalloc.start()
        result = measure(f"{base}/{size}")
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        expected_bytes = size * 10
        if result.total_bytes != expected_bytes:
            raise RuntimeError(f"Downloaded {result.total_bytes} bytes, expected {expected_bytes}.")
        memory.append(
            {
                "response_bytes": size,
                "downloaded_bytes": result.total_bytes,
                "peak_python_bytes": peak,
            }
        )
    timings: dict[str, list[dict[str, float]]] = {"plain": [], "progress": []}
    with open(os.devnull, "w", encoding="utf-8") as sink:

        def console(**kwargs):
            return Console(
                file=sink,
                force_terminal=True,
                force_interactive=True,
                legacy_windows=False,
                width=100,
            )

        with patch("speedcheck.cli.Console", side_effect=console), redirect_stdout(sink):
            for index in range(7):
                for mode in ("plain", "progress") if index % 2 == 0 else ("progress", "plain"):
                    args = [f"{base}/1048576?slow"] + (["--no-progress"] if mode == "plain" else [])
                    cpu = process_time()
                    started = perf_counter()
                    exit_code = main(args)
                    if exit_code != 0:
                        raise RuntimeError(
                            f"Benchmark run ({mode}) failed with exit code {exit_code}."
                        )
                    timings[mode].append(
                        {
                            "wall_seconds": perf_counter() - started,
                            "cpu_seconds": process_time() - cpu,
                        }
                    )
    summary = {
        mode: {
            key: median(sample[key] for sample in samples)
            for key in ("wall_seconds", "cpu_seconds")
        }
        for mode, samples in timings.items()
    }
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "memory": memory,
        "samples": timings,
        "median": summary,
        "progress_wall_difference_percent": (
            summary["progress"]["wall_seconds"] / summary["plain"]["wall_seconds"] - 1
        )
        * 100,
        "render_target": "os.devnull; real Rich rendering, terminal painting excluded",
    }


if __name__ == "__main__":
    parent, child = multiprocessing.Pipe(duplex=False)
    process = multiprocessing.Process(target=serve, args=(child,), daemon=True)
    process.start()
    child.close()
    try:
        if not parent.poll(10):
            raise TimeoutError("Local benchmark server did not start.")
        with patch.dict(os.environ, {"no_proxy": "127.0.0.1,localhost", "TERM": "xterm-256color"}):
            print(json.dumps(run(f"http://127.0.0.1:{parent.recv()}"), indent=2))
    finally:
        parent.close()
        process.terminate()
        process.join(timeout=5)
