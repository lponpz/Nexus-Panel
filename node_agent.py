#!/usr/bin/env python3
"""Private local node agent that owns game processes independently of the web panel."""
from __future__ import annotations
import hmac
import json
import os
import signal
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

HOST = "127.0.0.1"
PORT = int(os.environ.get("NEXUS_NODE_AGENT_PORT", "7879"))
TOKEN = os.environ.get("NEXUS_NODE_AGENT_TOKEN", "")
DATA_DIR = Path(os.environ.get("NEXUS_DATA_DIR", Path(__file__).resolve().parent / "data")).resolve()
SERVERS_DIR = DATA_DIR / "servers"

class AgentHandler(BaseHTTPRequestHandler):
    server_version = "NexusNodeAgent/1.0"
    def log_message(self, fmt, *args):
        print("[node-agent] " + (fmt % args))

    def _authorized(self):
        supplied = self.headers.get("X-Nexus-Node-Token", "")
        return len(TOKEN) >= 32 and hmac.compare_digest(supplied, TOKEN)

    def _send(self, status, payload):
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _server_id(self, raw):
        try:
            value = str(uuid.UUID(str(raw)))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Invalid server ID.")
        if value != str(raw).lower():
            raise ValueError("Invalid server ID.")
        return value

    def do_GET(self):
        if not self._authorized():
            return self._send(403, {"ok": False, "error": "Node agent authentication failed."})
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            return self._send(200, {"ok": True, "agent": "Nexus Node Agent", "pid": os.getpid()})
        query = parse_qs(parsed.query)
        try:
            server_id = self._server_id(query.get("server_id", [""])[0])
            from runtime_manager import snapshot, logs, process_metrics
            if parsed.path == "/snapshot":
                return self._send(200, {"ok": True, **snapshot(server_id)})
            if parsed.path == "/logs":
                return self._send(200, {"ok": True, **logs(server_id)})
            if parsed.path == "/metrics":
                return self._send(200, {"ok": True, **process_metrics(server_id)})
            return self._send(404, {"ok": False, "error": "Node agent route not found."})
        except (ValueError, RuntimeError, OSError) as exc:
            return self._send(400, {"ok": False, "error": str(exc)})

    def do_POST(self):
        if not self._authorized():
            return self._send(403, {"ok": False, "error": "Node agent authentication failed."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self._send(400, {"ok": False, "error": "Invalid content length."})
        if length < 2 or length > 16384:
            return self._send(413, {"ok": False, "error": "Node agent request body is invalid or too large."})
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("JSON body must be an object.")
            server_id = self._server_id(data.get("server_id"))
            server_dir = (SERVERS_DIR / server_id).resolve()
            if server_dir.parent != SERVERS_DIR.resolve():
                raise ValueError("Server directory is outside the node data root.")
            from runtime_manager import start, stop, command
            if self.path == "/start":
                result = start(server_id, server_dir, data.get("command", ""))
            elif self.path == "/stop":
                result = stop(server_id)
            elif self.path == "/command":
                result = command(server_id, data.get("command", ""))
            else:
                return self._send(404, {"ok": False, "error": "Node agent route not found."})
            return self._send(200, {"ok": True, **result})
        except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
            return self._send(400, {"ok": False, "error": str(exc)})

def main():
    if len(TOKEN) < 32:
        raise SystemExit("NEXUS_NODE_AGENT_TOKEN must contain at least 32 characters.")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SERVERS_DIR.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((HOST, PORT), AgentHandler)
    httpd.daemon_threads = True
    def shutdown(signum, frame):
        print("[node-agent] Shutdown requested; stopping managed game processes.")
        threading.Thread(target=httpd.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    print("Nexus Node Agent listening on " + HOST + ":" + str(PORT))
    try:
        httpd.serve_forever()
    finally:
        try:
            from runtime_manager import shutdown_all
            shutdown_all()
        finally:
            httpd.server_close()

if __name__ == "__main__":
    main()
