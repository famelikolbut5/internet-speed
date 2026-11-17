import socket
import ssl
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from time import sleep

import pytest


@pytest.fixture(autouse=True)
def bypass_proxy_for_local_server(monkeypatch):
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")


@pytest.fixture
def server(request):
    state = {"paths": [], "events": [], "headers": []}
    lock = Lock()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format, *args):
            pass

        def do_GET(self):
            with lock:
                state["paths"].append(self.path)
                state["headers"].append(dict(self.headers))
            with suppress(BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                self.respond()

        def respond(self):
            path = self.path
            if path in {"/redirect", "/invalid-redirect"}:
                self.send_response(302)
                self.send_header("Location", "/data" if path == "/redirect" else "http://[")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if path == "/error":
                self.send_error(503)
                return
            if path == "/rate-limited" and len(state["paths"]) == 9:
                self.send_error(429)
                return
            if path == "/partial":
                self.send_response(206)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if path == "/timeout":
                sleep(0.15)
            payload = b"x" * 131_073
            if path == "/empty":
                payload = b""
            self.send_response(200)
            if path in {"/chunked", "/bad-chunks"}:
                self.send_header("Transfer-Encoding", "chunked")
            elif path != "/unknown":
                self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            if path == "/truncated":
                self.wfile.write(payload[:10])
                return
            if path == "/bad-chunks":
                self.wfile.write(b"10\r\nshort")
                return
            if path == "/body-timeout":
                self.wfile.write(payload[:10])
                self.wfile.flush()
                sleep(0.15)
                self.wfile.write(payload[10:])
                return
            if path == "/chunked":
                self.wfile.write(f"{len(payload):x}\r\n".encode() + payload + b"\r\n0\r\n\r\n")
                return
            if path == "/slow":
                with lock:
                    state["events"].append("start")
                sleep(0.02)
                with lock:
                    state["events"].append("finish")
            self.wfile.write(payload)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    scheme = "http"
    if getattr(request, "param", None) == "tls":
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        fixtures = Path(__file__).parent / "fixtures"
        context.load_cert_chain(fixtures / "localhost-cert.pem", fixtures / "localhost-key.pem")
        httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
        scheme = "https"
    thread = Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"{scheme}://127.0.0.1:{httpd.server_port}", state
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


@pytest.fixture
def refused_url():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        yield f"http://127.0.0.1:{sock.getsockname()[1]}"
