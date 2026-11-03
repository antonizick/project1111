"""A dummy engine process for the supervisor tests: serves ``GET /system_stats`` on ``--port``.

Behaviour from the environment: ``DUMMY_READY_DELAY`` (seconds before it listens),
``DUMMY_EXIT_AFTER`` (seconds after listening, then exit 3), ``DUMMY_IGNORE_TERM=1``
(ignore SIGTERM), ``DUMMY_EXIT_NOW=1`` (exit 2 before listening), ``DUMMY_MARK`` (a file to
append a line to at every start, to count restarts).
"""

import os
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = b'{"system": {"comfyui_version": "0.43.0"}, "devices": []}'
        self.send_response(200 if self.path == "/system_stats" else 404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


def main() -> None:
    port = int(sys.argv[sys.argv.index("--port") + 1])
    if mark := os.environ.get("DUMMY_MARK"):
        with open(mark, "a") as f:
            f.write(f"{os.getpid()}\n")
    if os.environ.get("DUMMY_EXIT_NOW") == "1":
        sys.exit(2)
    if os.environ.get("DUMMY_IGNORE_TERM") == "1":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(float(os.environ.get("DUMMY_READY_DELAY", "0")))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print("dummy engine listening", flush=True)
    exit_after = os.environ.get("DUMMY_EXIT_AFTER")
    if exit_after:
        time.sleep(float(exit_after))
        os._exit(3)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
