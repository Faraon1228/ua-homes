"""Isolated local server for native auth-handshake integration tests.

Serves ../../web and a stub /api on 127.0.0.1:5050 (the web app targets this origin
automatically on loopback hosts). Only synthetic tokens are known; nothing is proxied.
Control: GET /__reset, GET /__restart/{arm[?action=&path=/__picker],next,autologout,event,events} (OS-restart harness), GET /__config?slowImageMs=N&drop=0|1 (drop=1 resets page connections: network failure, not HTTP error), POST /__upload + GET /__uploads + /__picker (mock upload page, metadata only), GET /__log (JSON list of /auth/me calls).
"""

import hashlib
import json
import os
import socket
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

WEB = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "web"))
VALID = {"synthetic-token-B"}
STATE = {"slowImageMs": 0, "log": [], "next": "none", "autoLogout": False, "events": [], "drop": False, "uploads": [], "startPath": "/seller"}
LOCK = threading.Lock()
# Test-only page probe for the OS-restart harness: reports booleans, never token values, and
# clicks the real logout button once when the harness armed it.
RESTART_PROBE = b"""<script>(async()=>{
const ev=(k,v)=>fetch('/__restart/event?kind='+k+'&v='+encodeURIComponent(v),{cache:'no-store',keepalive:true});
const has=()=>!!(localStorage.getItem('uaDim.authToken')||sessionStorage.getItem('uaDim.authToken'));
await ev('page-start',has());
setTimeout(()=>ev('page-settled',has()),7000);
for(let i=0;i<80;i++){
  const b=document.getElementById('header-logout-cta');
  if(b&&has()){await new Promise(r=>setTimeout(r,2500));if(!has())return;const b2=document.getElementById('header-logout-cta');if(!b2)return;const r=await (await fetch('/__restart/autologout',{cache:'no-store'})).json();
    if(r.click){await ev('logout-click',has());b2.click();const t=Date.now();
      while(has()&&Date.now()-t<5000)await new Promise(r=>setTimeout(r,20));
      await ev('web-cleared',!has());}
    return;}
  await new Promise(r=>setTimeout(r,250));
}})();</script>"""

# Test-only upload page for the native-picker check; uploads go to the local mock only.
PICKER_PAGE = b"""<!doctype html><meta charset=utf-8><title>picker</title>
<input id="f" type="file" accept="image/*" multiple>
<script>document.getElementById('f').addEventListener('change',async e=>{
for(const f of e.target.files){await fetch('/__upload?name='+encodeURIComponent(f.name),{method:'POST',headers:{'Content-Type':f.type},body:f});}
fetch('/__restart/event?kind=picker-change&v='+e.target.files.length);});</script>"""


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
                STATE["events"] = []
                STATE["slowImageMs"] = 0
                STATE["drop"] = False
                STATE["uploads"] = []
            return self._json(200, {"ok": True})
        if path == "/__config":
            with LOCK:
                query = parse_qs(url.query)
                STATE["slowImageMs"] = int(query.get("slowImageMs", ["0"])[0])
                STATE["drop"] = query.get("drop", ["0"])[0] == "1"
            return self._json(200, {"ok": True})
        if path.startswith("/__restart/"):
            query = parse_qs(url.query)
            with LOCK:
                if path == "/__restart/arm":
                    STATE["next"] = query.get("action", ["none"])[0]
                    start = query.get("path", ["/seller"])[0]
                    STATE["startPath"] = start if start in ("/seller", "/__picker") else "/seller"
                    return self._json(200, {"ok": True})
                if path == "/__restart/next":
                    action, STATE["next"] = STATE["next"], "none"
                    STATE["autoLogout"] = action == "logout"
                    start_path, STATE["startPath"] = STATE["startPath"], "/seller"
                    return self._json(200, {"action": action, "path": start_path})
                if path == "/__restart/autologout":
                    pending, STATE["autoLogout"] = STATE["autoLogout"], False
                    return self._json(200, {"click": pending})
                if path == "/__restart/event":
                    STATE["events"].append(
                        {"t": time.time(), "kind": query.get("kind", [""])[0], "v": query.get("v", [""])[0]}
                    )
                    return self._json(200, {"ok": True})
                if path == "/__restart/events":
                    return self._json(200, list(STATE["events"]))
            return self._json(404, {"error": "unknown"})
        if path == "/__uploads":
            with LOCK:
                return self._json(200, list(STATE["uploads"]))
        if path in ("/__picker", "/", "/app", "/seller") and STATE["drop"]:
            self.close_connection = True
            try:
                self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")
                self.connection.close()
            except OSError:
                pass
            return
        if path == "/__picker":
            html = PICKER_PAGE
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(html)
            return
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
                    b"</body>", b'<img src="/__slow.gif" width="1" height="1" alt="">' + RESTART_PROBE + b"</body>"
                )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(html)
            return
        return super().do_GET()

    def do_POST(self):
        url = urlparse(self.path)
        if url.path != "/__upload":
            return self._json(404, {"error": "unknown"})
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        query = parse_qs(url.query)
        with LOCK:
            STATE["uploads"].append(
                {
                    "name": query.get("name", [""])[0],
                    "type": self.headers.get("Content-Type", ""),
                    "size": len(body),
                    "sha256": hashlib.sha256(body).hexdigest(),
                }
            )
        return self._json(200, {"ok": True})


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 5050), Handler)
    print("ready", flush=True)
    server.serve_forever()
