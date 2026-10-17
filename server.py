#!/usr/bin/env python3
"""Nexus Panel MVP: local SQLite-backed dashboard API and static web server.

This is a functional starter application, not a production-secure public hosting panel.
It intentionally does not store panel API tokens or control external game servers.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sqlite3
import subprocess
import threading
import uuid
from collections import deque
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("NEXUS_DATA_DIR", ROOT / "data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
SERVERS_DIR = DATA_DIR / "servers"
SERVERS_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "nexus.sqlite3"
PORT = int(os.environ.get("NEXUS_PORT", "8000"))
DB_LOCK = threading.RLock()
VALID_GAMES = {"Minecraft", "FiveM", "Terraria", "Other"}
VALID_STATUSES = {"Configured", "Stopped", "Maintenance"}
VALID_PANELS = {"Nexus (local)", "Pterodactyl", "Pelican Panel", "AMP by CubeCoders", "Custom adapter (SDK)"}
RUNTIME_LOCK = threading.RLock()
RUNTIMES = {}
LOG_LIMIT = 500
ALLOWED_EXECUTABLES = {"java", "java.exe"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect_db():
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    return db


def init_db():
    with DB_LOCK, connect_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS servers (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, game TEXT NOT NULL,
          panel TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Configured',
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS connectors (
          id TEXT PRIMARY KEY, panel_type TEXT NOT NULL, base_url TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'Saved - not tested', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS activities (
          id INTEGER PRIMARY KEY AUTOINCREMENT, message TEXT NOT NULL,
          detail TEXT NOT NULL, created_at TEXT NOT NULL
        );
                CREATE TABLE IF NOT EXISTS settings (
          key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        """)
        count = db.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
        if not count:
            db.execute("INSERT INTO activities(message,detail,created_at) VALUES(?,?,?)",
                       ("Nexus initialized", "Local database created successfully", now()))


def add_activity(message: str, detail: str):
    with DB_LOCK, connect_db() as db:
        db.execute("INSERT INTO activities(message,detail,created_at) VALUES(?,?,?)",
                   (message[:180], detail[:240], now()))


def valid_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return parsed.scheme in ("http", "https") and bool(parsed.hostname) and not parsed.username and not parsed.password
    except ValueError:
        return False


class Handler(SimpleHTTPRequestHandler):
    server_version = "NexusPanelMVP/0.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):
        # Keep the development console readable; do not log request bodies or secrets.
        print("[nexus] " + (fmt % args))

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def json_response(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("Invalid content length")
        if length < 2 or length > 16_384:
            raise ValueError("Request body must be valid JSON and under 16 KB")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON body")
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            if path == "/api/health":
                return self.json_response(200, {"ok": True, "app": "Nexus Panel", "mode": "local-mvp", "database": "sqlite", "timestamp": now()})
            if path == "/api/overview":
                with DB_LOCK, connect_db() as db:
                    servers = db.execute("SELECT COUNT(*) FROM servers").fetchone()[0]
                    connectors = db.execute("SELECT COUNT(*) FROM connectors").fetchone()[0]
                    activities = [dict(r) for r in db.execute("SELECT * FROM activities ORDER BY id DESC LIMIT 8")]
                return self.json_response(200, {"ok": True, "servers": servers, "connectors": connectors, "activities": activities})
            if path == "/api/setup":
                with DB_LOCK, connect_db() as db:
                    rows = {r["key"]: r["value"] for r in db.execute("SELECT key,value FROM settings")}
                return self.json_response(200, {"ok": True, "configured": rows.get("setup_complete") == "true",
                    "workspace_name": rows.get("workspace_name", "Nexus Workspace")})
            if path == "/api/servers":
                with DB_LOCK, connect_db() as db:
                    rows = [dict(r) for r in db.execute("SELECT * FROM servers ORDER BY created_at DESC")]
                return self.json_response(200, {"ok": True, "items": rows})
            if path == "/api/connectors":
                with DB_LOCK, connect_db() as db:
                    rows = [dict(r) for r in db.execute("SELECT * FROM connectors ORDER BY created_at DESC")]
                return self.json_response(200, {"ok": True, "items": rows})
            return self.json_response(404, {"ok": False, "error": "API route not found"})
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            data = self.read_json()
        except ValueError as exc:
            return self.json_response(400, {"ok": False, "error": str(exc)})

        if path == "/api/setup":
            workspace_name = str(data.get("workspace_name", "Nexus Workspace")).strip()
            if not workspace_name or len(workspace_name) > 60 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.-]*", workspace_name):
                return self.json_response(400, {"ok": False, "error": "Workspace name must be 1-60 letters, numbers, spaces, dots, underscores or hyphens."})
            with DB_LOCK, connect_db() as db:
                db.execute("INSERT OR REPLACE INTO settings(key,value,updated_at) VALUES(?,?,?)", ("workspace_name", workspace_name, now()))
                db.execute("INSERT OR REPLACE INTO settings(key,value,updated_at) VALUES(?,?,?)", ("setup_complete", "true", now()))
            add_activity("Nexus setup completed", "Workspace configured: " + workspace_name)
            return self.json_response(200, {"ok": True, "configured": True, "workspace_name": workspace_name})
        if path == "/api/servers":
            name = str(data.get("name", "")).strip()
            game = str(data.get("game", "")).strip()
            panel = str(data.get("panel", "Nexus (local)")).strip()
            status = str(data.get("status", "Configured")).strip()
            if not name or len(name) > 64 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.-]*", name):
                return self.json_response(400, {"ok": False, "error": "Name must be 1–64 letters, numbers, spaces, dots, underscores or hyphens."})
            if game not in VALID_GAMES or panel not in VALID_PANELS or status not in VALID_STATUSES:
                return self.json_response(400, {"ok": False, "error": "Choose a supported game, panel and status."})
            item = {"id": str(uuid.uuid4()), "name": name, "game": game, "panel": panel, "status": status, "created_at": now()}
            with DB_LOCK, connect_db() as db:
                db.execute("INSERT INTO servers(id,name,game,panel,status,created_at) VALUES(?,?,?,?,?,?)",
                           (item["id"], item["name"], item["game"], item["panel"], item["status"], item["created_at"]))
            add_activity("Server record created", f'{name} · {game} · {panel}')
            return self.json_response(201, {"ok": True, "item": item})

        if path == "/api/connectors":
            panel_type = str(data.get("panel_type", "")).strip()
            base_url = str(data.get("base_url", "")).strip().rstrip("/")
            if panel_type not in VALID_PANELS - {"Nexus (local)"}:
                return self.json_response(400, {"ok": False, "error": "Choose a supported connector type."})
            if len(base_url) > 500 or not valid_url(base_url):
                return self.json_response(400, {"ok": False, "error": "Enter a valid HTTP(S) base URL without embedded credentials."})
            item = {"id": str(uuid.uuid4()), "panel_type": panel_type, "base_url": base_url,
                    "status": "Saved - not tested", "created_at": now()}
            with DB_LOCK, connect_db() as db:
                db.execute("INSERT INTO connectors(id,panel_type,base_url,status,created_at) VALUES(?,?,?,?,?)",
                           (item["id"], item["panel_type"], item["base_url"], item["status"], item["created_at"]))
            add_activity("Connector record saved", f'{panel_type} · endpoint saved; not tested')
            return self.json_response(201, {"ok": True, "item": item})
        return self.json_response(404, {"ok": False, "error": "API route not found"})

    def do_PUT(self):
        path = urlparse(self.path).path.rstrip("/")
        parts = path.split("/")
        if len(parts) != 4 or parts[1] != "api" or parts[2] != "servers":
            return self.json_response(404, {"ok": False, "error": "API route not found"})
        server_id = parts[3]
        try:
            data = self.read_json()
        except ValueError as exc:
            return self.json_response(400, {"ok": False, "error": str(exc)})
        allowed = {"name", "game", "panel", "status"}
        if set(data) - allowed:
            return self.json_response(400, {"ok": False, "error": "Unsupported server fields."})
        with DB_LOCK, connect_db() as db:
            row = db.execute("SELECT * FROM servers WHERE id = ?", (server_id,)).fetchone()
            if row is None:
                return self.json_response(404, {"ok": False, "error": "Server record not found"})
            item = dict(row)
            item.update({key: str(value).strip() for key, value in data.items()})
            if not item["name"] or len(item["name"]) > 64 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.-]*", item["name"]):
                return self.json_response(400, {"ok": False, "error": "Name must be 1–64 letters, numbers, spaces, dots, underscores or hyphens."})
            if item["game"] not in VALID_GAMES or item["panel"] not in VALID_PANELS or item["status"] not in VALID_STATUSES:
                return self.json_response(400, {"ok": False, "error": "Choose a supported game, panel and status."})
            db.execute("UPDATE servers SET name=?, game=?, panel=?, status=? WHERE id=?",
                       (item["name"], item["game"], item["panel"], item["status"], server_id))
        add_activity("Server record updated", f'{item["name"]} · status: {item["status"]}')
        return self.json_response(200, {"ok": True, "item": item})

    def do_DELETE(self):
        path = urlparse(self.path).path.rstrip("/")
        parts = path.split("/")
        if len(parts) != 4 or parts[1] != "api" or parts[2] not in ("servers", "connectors"):
            return self.json_response(404, {"ok": False, "error": "API route not found"})
        kind, item_id = parts[2], parts[3]
        table = "servers" if kind == "servers" else "connectors"
        with DB_LOCK, connect_db() as db:
            row = db.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                return self.json_response(404, {"ok": False, "error": "Record not found"})
            label = row["name"] if kind == "servers" else row["panel_type"]
            db.execute(f"DELETE FROM {table} WHERE id = ?", (item_id,))
        add_activity("Record removed", f"{kind[:-1]} · {label}")
        return self.json_response(200, {"ok": True, "deleted_id": item_id})

    def translate_path(self, path):
        # Serve only files inside the repository root; the standard handler normalizes paths.
        parsed = urlparse(path)
        rel = url2pathname(parsed.path).lstrip("/")
        parts = Path(rel).parts
        # Never expose the SQLite database, dotfiles, or repository metadata as static files.
        if parts and (parts[0] == "data" or any(part.startswith(".") for part in parts)):
            return str(ROOT / "__not_found__")
        target = (ROOT / rel).resolve()
        if target != ROOT and ROOT not in target.parents:
            return str(ROOT / "__not_found__")
        return str(target)


if __name__ == "__main__":
    init_db()
    print("Nexus Panel MVP")
    print(f"Database: {DB_PATH}")
    print(f"Listening on 0.0.0.0:{PORT}")
    print("WARNING: MVP only. Keep the Codespaces port private; authentication and external panel adapters are not implemented.")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
