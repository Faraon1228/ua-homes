"""Isolated local server for native auth-handshake integration tests.

Serves ../../web and a stub /api on 127.0.0.1:5050 (the web app targets this origin
automatically on loopback hosts). Only synthetic tokens are known; nothing is proxied.
Control: GET /__reset, GET /__config?slowImageMs=N, GET /__log (JSON list of /auth/me calls).
"""

import json
import os
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

WEB = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "web"))
VALID = {"synthetic-token-B"}
STATE = {"slowImageMs": 0, "log": []}
LOCK = threading.Lock()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB, **kwargs)

    def log_message(self, *args):
        pass

    def _json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path
        if path == "/__reset":
            with LOCK:
                STATE["log"] = []
                STATE["slowImageMs"] = 0
            return self._json(200, {"ok": True})
        if path == "/__config":
            with LOCK:
                STATE["slowImageMs"] = int(parse_qs(url.query).get("slowImageMs", ["0"])[0])
            return self._json(200, {"ok": True})
        if path == "/__log":
            with LOCK:
                return self._json(200, list(STATE["log"]))
        if path == "/api/auth/me":
            header = self.headers.get("Authorization", "")
            token = header[7:] if header.startswith("Bearer ") else ""
            with LOCK:
                STATE["log"].append({"t": time.time(), "token": token})
            if token in VALID:
                return self._json(
                    200,
                    {"user": {"id": 1, "name": "Synthetic", "email": "synthetic@example.test", "accountType": "owner"}},
                )
            return self._json(401, {"error": "unauthorized"})
        if path.startswith("/api/"):
            return self._json(200, {"items": [], "listings": [], "total": 0})
        if path == "/__slow.gif":
            time.sleep(STATE["slowImageMs"] / 1000)
            gif = bytes.fromhex("47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b")
            self.send_response(200)
            self.send_header("Content-Type", "image/gif")
            self.send_header("Content-Length", str(len(gif)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(gif)
            return
        if path in ("/", "/app", "/seller"):
            # Test-only: a trailing slow image delays the load event (native onPageFinished)
            # without delaying the app mount.
            with open(os.path.join(WEB, "real-estate-demo.html"), "rb") as handle:
                html = handle.read().replace(
                    b"</body>", b'<img src="/__slow.gif" width="1" height="1" alt=""></body>'
                )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(html)
            return
        return super().do_GET()


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 5050), Handler)
    print("ready", flush=True)
    server.serve_forever()
