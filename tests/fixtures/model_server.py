"""A loopback HTTP server for downloader tests: Range requests, interruptions, redirects.

Files are registered by path. Each request is recorded (path, Range, Authorization, Host) so a
test can assert what was sent. Behaviours per path:

- ``cut_after``: close the connection after N body bytes, once (an interrupted transfer);
- ``ignore_range``: answer 200 with the whole body even when a Range is asked;
- ``status``: answer with this code (``fail_times`` times, then serve the body; -1 = always);
- ``redirect``: a 302 to another absolute URL.
"""

from __future__ import annotations

import json
import struct
import threading
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


@dataclass
class Route:
    body: bytes = b""
    cut_after: int | None = None
    ignore_range: bool = False
    status: int | None = None
    #: How many requests get ``status`` before the body is served; -1 = every request.
    fail_times: int = -1
    redirect: str | None = None


@dataclass
class Request:
    path: str
    range: str | None
    authorization: str | None
    host: str


@dataclass
class ModelServer:
    port: int = 0
    routes: dict[str, Route] = field(default_factory=dict)
    requests: list[Request] = field(default_factory=list)

    def url(self, path: str, host: str = "127.0.0.1") -> str:
        return f"http://{host}:{self.port}{path}"

    def add(self, path: str, body: bytes = b"", **kw: Any) -> str:
        self.routes[path] = Route(body=body, **kw)
        return self.url(path)


def serve() -> Iterator[ModelServer]:
    state = ModelServer()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: object) -> None:
            pass

        def do_GET(self) -> None:
            state.requests.append(
                Request(
                    self.path,
                    self.headers.get("Range"),
                    self.headers.get("Authorization"),
                    self.headers.get("Host", ""),
                )
            )
            route = state.routes.get(self.path)
            if route is None:
                self._reply(404, b"")
                return
            if route.redirect:
                self.send_response(302)
                self.send_header("Location", route.redirect)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if route.status is not None and route.fail_times != 0:
                route.fail_times -= 1 if route.fail_times > 0 else 0
                self._reply(route.status, b"")
                return
            body = route.body
            start = 0
            rng = self.headers.get("Range")
            if rng and not route.ignore_range:
                start = int(rng.removeprefix("bytes=").split("-")[0])
                if start >= len(body):
                    self._reply(416, b"")
                    return
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{len(body) - 1}/{len(body)}")
            else:
                self.send_response(200)
            chunk = body[start:]
            self.send_header("Content-Length", str(len(chunk)))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            if route.cut_after is not None:
                cut, route.cut_after = route.cut_after, None
                self.wfile.write(chunk[:cut])
                self.wfile.flush()
                self.close_connection = True
                self.connection.shutdown(2)
                return
            self.wfile.write(chunk)

        def _reply(self, code: int, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    class Quiet(ThreadingHTTPServer):
        def handle_error(self, request: object, client_address: object) -> None:
            pass  # clients hanging up mid-body is what several tests do on purpose

    httpd = Quiet(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    state.port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, args=(0.02,), daemon=True)
    thread.start()
    try:
        yield state
    finally:
        httpd.shutdown()
        httpd.server_close()


def safetensors_bytes(
    tensors: Mapping[str, int], metadata: Mapping[str, str] | None = None
) -> bytes:
    """A valid safetensors file with ``name → number of float16 values`` (zero-filled)."""
    header: dict[str, Any] = {}
    offset = 0
    for name, n in tensors.items():
        header[name] = {"dtype": "F16", "shape": [n], "data_offsets": [offset, offset + 2 * n]}
        offset += 2 * n
    if metadata:
        header["__metadata__"] = dict(metadata)
    raw = json.dumps(header).encode()
    raw += b" " * (-len(raw) % 8)
    return struct.pack("<Q", len(raw)) + raw + b"\0" * offset
