#!/usr/bin/env python3
"""Nexus Panel development backend with owner authentication; node isolation is not production-ready."""
from __future__ import annotations
import json, os, re, sqlite3, threading, uuid, time
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from urllib.request import url2pathname

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("NEXUS_DATA_DIR", ROOT / "data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
SERVERS_DIR = DATA_DIR / "servers"
SERVERS_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "nexus.sqlite3"
PORT = int(os.environ.get("NEXUS_PORT", "8000"))
# Bind to loopback by default. Remote binding is only enabled explicitly by the launcher
# for Codespaces, where the user must keep the forwarded port private.
HOST = os.environ.get("NEXUS_HOST", "127.0.0.1")
DB_LOCK = threading.RLock()
LOGIN_FAILURES = {}
VALID_GAMES = {"Minecraft", "FiveM", "Terraria", "Other"}
VALID_STATUSES = {"Configured", "Stopped", "Maintenance"}
VALID_PANELS = {"Nexus (local)", "Pterodactyl", "Pelican Panel", "AMP by CubeCoders", "Custom adapter (SDK)"}

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def connect_db():
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    with DB_LOCK, connect_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS servers (id TEXT PRIMARY KEY, name TEXT NOT NULL, game TEXT NOT NULL, panel TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Configured', created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS server_runtime (server_id TEXT PRIMARY KEY, launch_command TEXT NOT NULL DEFAULT 'java -Xms1G -Xmx2G -jar server.jar nogui', updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS connectors (id TEXT PRIMARY KEY, panel_type TEXT NOT NULL, base_url TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Saved - not tested', created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS activities (id INTEGER PRIMARY KEY AUTOINCREMENT, message TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'owner', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, csrf_token TEXT NOT NULL,
            expires_at TEXT NOT NULL, created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """)
        if not db.execute("SELECT COUNT(*) FROM activities").fetchone()[0]:
            db.execute("INSERT INTO activities(message,detail,created_at) VALUES(?,?,?)", ("Nexus initialized", "Local database created", now()))

def add_activity(message, detail):
    with DB_LOCK, connect_db() as db:
        db.execute("INSERT INTO activities(message,detail,created_at) VALUES(?,?,?)", (str(message)[:180], str(detail)[:240], now()))

def server_exists(server_id):
    with DB_LOCK, connect_db() as db:
        return db.execute("SELECT 1 FROM servers WHERE id=?", (server_id,)).fetchone() is not None


def password_hash(password, salt=None):
    import hashlib, secrets
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310000)
    return salt.hex() + ":" + digest.hex()


def password_matches(password, encoded):
    import hashlib, hmac
    try:
        salt_hex, digest_hex = encoded.split(":", 1)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), 310000)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _token_digest(token):
    import hashlib
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def current_session(handler):
    import secrets
    cookie = handler.headers.get("Cookie", "")
    token = ""
    for item in cookie.split(";"):
        key, sep, value = item.strip().partition("=")
        if sep and key == "nexus_session":
            token = value
            break
    if not token:
        return None
    with DB_LOCK, connect_db() as db:
        row = db.execute(
            "SELECT sessions.user_id,sessions.csrf_token,sessions.expires_at,users.username,users.role "
            "FROM sessions JOIN users ON users.id=sessions.user_id WHERE sessions.token_hash=?",
            (_token_digest(token),)
        ).fetchone()
        if not row or row["expires_at"] <= now():
            if row:
                db.execute("DELETE FROM sessions WHERE token_hash=?", (_token_digest(token),))
            return None
        return dict(row)


def issue_session(handler, user_id):
    import secrets
    import hashlib
    token = secrets.token_urlsafe(48)
    csrf = secrets.token_urlsafe(32)
    created = datetime.now(timezone.utc)
    expires = (created.replace(microsecond=0) + __import__("datetime").timedelta(hours=12)).isoformat()
    with DB_LOCK, connect_db() as db:
        db.execute("INSERT INTO sessions(token_hash,user_id,csrf_token,expires_at,created_at) VALUES(?,?,?,?,?)",
                   (_token_digest(token), user_id, csrf, expires, now()))
    secure = "; Secure" if os.environ.get("NEXUS_COOKIE_SECURE") == "1" else ""
    handler.send_header("Set-Cookie", "nexus_session=" + token + "; Path=/; HttpOnly; SameSite=Strict; Max-Age=43200" + secure)
    return csrf


def clear_session_cookie(handler):
    secure = "; Secure" if os.environ.get("NEXUS_COOKIE_SECURE") == "1" else ""
    handler.send_header("Set-Cookie", "nexus_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0" + secure)


def configured():
    with DB_LOCK, connect_db() as db:
        row = db.execute("SELECT value FROM settings WHERE key='setup_complete'").fetchone()
        return bool(row and row["value"] == "true")


def has_owner():
    with DB_LOCK, connect_db() as db:
        return db.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None


def valid_origin(handler):
    origin = handler.headers.get("Origin")
    if origin:
        from urllib.parse import urlparse as _urlparse
        return _urlparse(origin).netloc == handler.headers.get("Host", "")
    fetch_site = handler.headers.get("Sec-Fetch-Site", "")
    return fetch_site not in ("cross-site", "same-site")


def valid_url(value):
    from urllib.parse import urlparse as parse
    try:
        p = parse(value)
        return p.scheme in ("http", "https") and bool(p.hostname) and not p.username and not p.password
    except ValueError:
        return False

class Handler(SimpleHTTPRequestHandler):
    server_version = "NexusPanelDev/0.2"
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)
    def log_message(self, fmt, *args):
        print("[nexus] " + (fmt % args))
    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()
    def json_response(self, code, payload, extra_headers=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra_headers or []):
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)
    def auth_error(self, code, message):
        return self.json_response(code, {"ok": False, "error": message})
    def api_authenticated(self):
        path = urlparse(self.path).path
        public = {"/api/health", "/api/setup", "/api/auth/login", "/api/auth/session"}
        if path in public:
            return True
        if not configured():
            if path in public:
                return True
            self.auth_error(403, "Complete the first-run owner setup before using the API.")
            return False
        session = current_session(self)
        if not session:
            self.auth_error(401, "Login required. Open login.html and sign in.")
            return False
        if self.command in ("POST", "PUT", "PATCH", "DELETE"):
            if not valid_origin(self):
                self.auth_error(403, "Request origin rejected.")
                return False
            supplied = self.headers.get("X-Nexus-CSRF", "")
            import hmac
            if not supplied or not hmac.compare_digest(supplied, session["csrf_token"]):
                self.auth_error(403, "Security token missing or expired. Reload the page and try again.")
                return False
        return True
    def read_json(self, limit=16384):
        if urlparse(self.path).path.endswith("/files"):
            limit = 1100000
        try: length = int(self.headers.get("Content-Length", "0"))
        except ValueError: raise ValueError("Invalid content length")
        if length < 2 or length > limit: raise ValueError("Request body must be valid JSON and under the size limit")
        try: data = json.loads(self.rfile.read(length))
        except json.JSONDecodeError: raise ValueError("Invalid JSON body")
        if not isinstance(data, dict): raise ValueError("JSON body must be an object")
        return data
    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html", "/studio.html") and configured():
            if not has_owner():
                self.send_response(302); self.send_header("Location", "/installer.html"); self.end_headers(); return
            if not current_session(self):
                self.send_response(302); self.send_header("Location", "/login.html"); self.end_headers(); return
        if path == "/api/auth/session":
            session = current_session(self)
            if not session:
                return self.json_response(200, {"ok": True, "authenticated": False})
            return self.json_response(200, {"ok": True, "authenticated": True, "username": session["username"], "role": session["role"], "csrf_token": session["csrf_token"]})
        if path.startswith("/api/") and not self.api_authenticated():
            return
        if path == "/api/health":
            return self.json_response(200, {"ok": True, "app": "Nexus Panel", "mode": "local-dev", "database": "sqlite", "timestamp": now()})
        if path == "/api/setup":
            with DB_LOCK, connect_db() as db: rows = {r["key"]: r["value"] for r in db.execute("SELECT key,value FROM settings")}
            return self.json_response(200, {"ok": True, "configured": rows.get("setup_complete") == "true", "workspace_name": rows.get("workspace_name", "Nexus Workspace")})
        if path == "/api/overview":
            with DB_LOCK, connect_db() as db:
                servers = db.execute("SELECT COUNT(*) FROM servers").fetchone()[0]
                connectors = db.execute("SELECT COUNT(*) FROM connectors").fetchone()[0]
                activities = [dict(r) for r in db.execute("SELECT * FROM activities ORDER BY id DESC LIMIT 8")]
            return self.json_response(200, {"ok": True, "servers": servers, "connectors": connectors, "activities": activities})
        if path == "/api/servers":
            with DB_LOCK, connect_db() as db: rows = [dict(r) for r in db.execute("SELECT * FROM servers ORDER BY created_at DESC")]
            return self.json_response(200, {"ok": True, "items": rows})
        if path == "/api/connectors":
            with DB_LOCK, connect_db() as db: rows = [dict(r) for r in db.execute("SELECT * FROM connectors ORDER BY created_at DESC")]
            return self.json_response(200, {"ok": True, "items": rows})
        if path.startswith("/api/servers/"):
            parts = path.strip("/").split("/")
            if len(parts) < 3 or not server_exists(parts[2]): return self.json_response(404, {"ok": False, "error": "Server not found"})
            sid = parts[2]
            from runtime_manager import snapshot, logs, list_files, server_path
            if len(parts) == 3:
                with DB_LOCK, connect_db() as db: cfg = db.execute("SELECT launch_command FROM server_runtime WHERE server_id=?", (sid,)).fetchone()
                return self.json_response(200, {"ok": True, "runtime": snapshot(sid), "launch_command": cfg["launch_command"] if cfg else "java -Xms1G -Xmx2G -jar server.jar nogui"})
            if len(parts) == 4 and parts[3] == "console": return self.json_response(200, {"ok": True, **logs(sid)})
            if len(parts) == 4 and parts[3] == "files":
                try: return self.json_response(200, {"ok": True, **list_files(SERVERS_DIR / sid, parse_qs(urlparse(self.path).query).get("path", [""])[0])})
                except (ValueError, OSError) as exc: return self.json_response(400, {"ok": False, "error": str(exc)})
            if len(parts) == 4 and parts[3] == "file-download":
                try:
                    target = server_path(SERVERS_DIR / sid, parse_qs(urlparse(self.path).query).get("path", [""])[0])
                    if not target.is_file() or target.is_symlink(): return self.json_response(400, {"ok": False, "error": "File not found"})
                    if target.stat().st_size > 200 * 1024 * 1024: return self.json_response(413, {"ok": False, "error": "File is larger than the 200 MB download limit"})
                    from urllib.parse import quote
                    payload = target.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Length", str(len(payload)))
                    self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(target.name, safe=""))
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                except (ValueError, OSError) as exc: return self.json_response(400, {"ok": False, "error": "Cannot download file: " + str(exc)})
            if len(parts) == 4 and parts[3] == "file-content":
                try:
                    target = server_path(SERVERS_DIR / sid, parse_qs(urlparse(self.path).query).get("path", [""])[0])
                    if not target.is_file() or target.is_symlink(): return self.json_response(400, {"ok": False, "error": "Text file not found"})
                    if target.stat().st_size > 1000000: return self.json_response(400, {"ok": False, "error": "File is larger than 1 MB"})
                    return self.json_response(200, {"ok": True, "content": target.read_text(encoding="utf-8")})
                except (ValueError, OSError, UnicodeDecodeError) as exc: return self.json_response(400, {"ok": False, "error": "Cannot read text file: " + str(exc)})
        if path.startswith("/api/"): return self.json_response(404, {"ok": False, "error": "API route not found"})
        return super().do_GET()
    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/auth/logout":
            if not self.api_authenticated():
                return
            cookie = self.headers.get("Cookie", "")
            token = next((v.strip().split("=",1)[1] for v in cookie.split(";") if v.strip().startswith("nexus_session=")), "")
            if token:
                with DB_LOCK, connect_db() as db:
                    db.execute("DELETE FROM sessions WHERE token_hash=?", (_token_digest(token),))
            secure = "; Secure" if os.environ.get("NEXUS_COOKIE_SECURE") == "1" else ""
            return self.json_response(200, {"ok": True, "authenticated": False}, [("Set-Cookie", "nexus_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0" + secure)])
        if path == "/api/auth/login":
            if not valid_origin(self):
                return self.auth_error(403, "Request origin rejected.")
            try:
                data = self.read_json()
            except ValueError as exc:
                return self.auth_error(400, str(exc))
            username = str(data.get("username", "")).strip()
            password = data.get("password", "")
            if not isinstance(password, str) or len(username) > 80 or len(password) > 1024:
                return self.auth_error(400, "Invalid username or password.")
            remote_ip = self.client_address[0]
            monotonic_now = time.monotonic()
            with DB_LOCK:
                attempts, window_start = LOGIN_FAILURES.get(remote_ip, (0, monotonic_now))
                if monotonic_now - window_start >= 900:
                    attempts, window_start = 0, monotonic_now
                if attempts >= 5:
                    return self.auth_error(429, "Too many sign-in attempts. Wait 15 minutes and try again.")
            with DB_LOCK, connect_db() as db:
                user = db.execute("SELECT id,password_hash FROM users WHERE username=?", (username,)).fetchone()
            if not user or not password_matches(password, user["password_hash"]):
                with DB_LOCK:
                    attempts, window_start = LOGIN_FAILURES.get(remote_ip, (0, monotonic_now))
                    if monotonic_now - window_start >= 900:
                        attempts, window_start = 0, monotonic_now
                    LOGIN_FAILURES[remote_ip] = (attempts + 1, window_start)
                return self.auth_error(401, "Incorrect username or password.")
            with DB_LOCK:
                LOGIN_FAILURES.pop(remote_ip, None)
            headers = []
            # Issue the cookie on the same response that reports a successful login.
            import secrets
            token = secrets.token_urlsafe(48); csrf = secrets.token_urlsafe(32)
            created = datetime.now(timezone.utc)
            expires = (created.replace(microsecond=0) + __import__("datetime").timedelta(hours=12)).isoformat()
            with DB_LOCK, connect_db() as db:
                db.execute("INSERT INTO sessions(token_hash,user_id,csrf_token,expires_at,created_at) VALUES(?,?,?,?,?)",
                           (_token_digest(token), user["id"], csrf, expires, now()))
            secure = "; Secure" if os.environ.get("NEXUS_COOKIE_SECURE") == "1" else ""
            headers.append(("Set-Cookie", "nexus_session=" + token + "; Path=/; HttpOnly; SameSite=Strict; Max-Age=43200" + secure))
            add_activity("Owner login", username)
            return self.json_response(200, {"ok": True, "authenticated": True, "csrf_token": csrf}, headers)
        if path.startswith("/api/") and not self.api_authenticated():
            return
        if path.startswith("/api/servers/") and path.endswith("/file-upload"):
            parts = path.strip("/").split("/")
            if len(parts) != 4 or not server_exists(parts[2]): return self.json_response(404, {"ok": False, "error": "Server not found"})
            query = parse_qs(urlparse(self.path).query)
            name, folder = query.get("name", [""])[0], query.get("path", [""])[0]
            if not name or name in (".", "..") or "/" in name or chr(92) in name or any(ord(c) < 32 for c in name):
                return self.json_response(400, {"ok": False, "error": "Invalid file name"})
            try: length = int(self.headers.get("Content-Length", "0"))
            except ValueError: return self.json_response(400, {"ok": False, "error": "Invalid content length"})
            if length < 1 or length > 50 * 1024 * 1024: return self.json_response(413, {"ok": False, "error": "File must be between 1 byte and 50 MB"})
            from runtime_manager import server_path
            try:
                target = server_path(SERVERS_DIR / parts[2], (folder + "/" if folder else "") + name)
                target.parent.mkdir(parents=True, exist_ok=True)
                payload = self.rfile.read(length)
                if len(payload) != length: return self.json_response(400, {"ok": False, "error": "Upload was incomplete"})
                target.write_bytes(payload)
                add_activity("Server file uploaded", parts[2] + " / " + name)
                return self.json_response(201, {"ok": True, "name": name, "size": length})
            except (ValueError, OSError) as exc: return self.json_response(400, {"ok": False, "error": str(exc)})
        try: data = self.read_json()
        except ValueError as exc: return self.json_response(400, {"ok": False, "error": str(exc)})
        if path == "/api/setup":
            if not valid_origin(self):
                return self.auth_error(403, "Request origin rejected.")
            if has_owner():
                return self.auth_error(403, "Initial setup is already complete. Sign in instead.")
            name = str(data.get("workspace_name", "Nexus Workspace")).strip()
            username = str(data.get("username", "")).strip()
            password = data.get("password", "")
            if not name or len(name) > 60 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.-]*", name):
                return self.auth_error(400, "Workspace name must be 1-60 valid characters.")
            if not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username):
                return self.auth_error(400, "Owner username must be 3-32 letters, numbers, dots, underscores or hyphens.")
            if not isinstance(password, str) or len(password) < 12 or len(password) > 1024:
                return self.auth_error(400, "Owner password must be at least 12 characters.")
            owner_id = str(uuid.uuid4())
            with DB_LOCK, connect_db() as db:
                db.execute("INSERT INTO users(id,username,password_hash,role,created_at) VALUES(?,?,?,?,?)",
                           (owner_id, username, password_hash(password), "owner", now()))
                db.execute("INSERT OR REPLACE INTO settings(key,value,updated_at) VALUES(?,?,?)", ("workspace_name", name, now()))
                db.execute("INSERT OR REPLACE INTO settings(key,value,updated_at) VALUES(?,?,?)", ("setup_complete", "true", now()))
            import secrets
            token = secrets.token_urlsafe(48)
            csrf = secrets.token_urlsafe(32)
            created = datetime.now(timezone.utc)
            expires = (created.replace(microsecond=0) + __import__("datetime").timedelta(hours=12)).isoformat()
            with DB_LOCK, connect_db() as db:
                db.execute("INSERT INTO sessions(token_hash,user_id,csrf_token,expires_at,created_at) VALUES(?,?,?,?,?)",
                           (_token_digest(token), owner_id, csrf, expires, now()))
            secure = "; Secure" if os.environ.get("NEXUS_COOKIE_SECURE") == "1" else ""
            headers = [("Set-Cookie", "nexus_session=" + token + "; Path=/; HttpOnly; SameSite=Strict; Max-Age=43200" + secure)]
            add_activity("Nexus owner account created", username)
            return self.json_response(200, {"ok": True, "configured": True, "workspace_name": name, "authenticated": True, "csrf_token": csrf}, headers)
        if path == "/api/servers":
            name, game, panel = str(data.get("name", "")).strip(), str(data.get("game", "")).strip(), str(data.get("panel", "Nexus (local)")).strip()
            status = str(data.get("status", "Configured")).strip()
            if not name or len(name) > 64 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.-]*", name): return self.json_response(400, {"ok": False, "error": "Server name is invalid."})
            if game not in VALID_GAMES or panel not in VALID_PANELS or status not in VALID_STATUSES: return self.json_response(400, {"ok": False, "error": "Choose a supported game, panel and status."})
            item = {"id": str(uuid.uuid4()), "name": name, "game": game, "panel": panel, "status": status, "created_at": now()}
            with DB_LOCK, connect_db() as db:
                db.execute("INSERT INTO servers(id,name,game,panel,status,created_at) VALUES(?,?,?,?,?,?)", (item["id"], name, game, panel, status, item["created_at"]))
                db.execute("INSERT OR IGNORE INTO server_runtime(server_id,launch_command,updated_at) VALUES(?,?,?)", (item["id"], "java -Xms1G -Xmx2G -jar server.jar nogui", now()))
            (SERVERS_DIR / item["id"]).mkdir(parents=True, exist_ok=True)
            add_activity("Server record created", name + " · " + game + " · " + panel)
            return self.json_response(201, {"ok": True, "item": item})
        if path.startswith("/api/servers/"):
            parts = path.strip("/").split("/")
            if len(parts) != 4 or not server_exists(parts[2]): return self.json_response(404, {"ok": False, "error": "Server not found"})
            sid, action = parts[2], parts[3]
            from runtime_manager import start, stop, command, change_file, snapshot, install_paper, _validate
            try:
                if action == "install":
                    with DB_LOCK, connect_db() as db:
                        game_row = db.execute("SELECT game FROM servers WHERE id=?", (sid,)).fetchone()
                    if not game_row or game_row["game"] != "Minecraft":
                        raise ValueError("The Paper installer is available only for Minecraft servers.")
                    if snapshot(sid).get("running"):
                        raise RuntimeError("Stop the server before installing or replacing server software.")
                    result = install_paper(SERVERS_DIR / sid, str(data.get("version", "latest")))
                    add_activity("Paper server software installed", sid + " · " + result["version"])
                    return self.json_response(200, {"ok": True, "install": result})
                if action == "start":
                    with DB_LOCK, connect_db() as db: cfg = db.execute("SELECT launch_command FROM server_runtime WHERE server_id=?", (sid,)).fetchone()
                    launch = str(data.get("launch_command") or (cfg["launch_command"] if cfg else "java -Xms1G -Xmx2G -jar server.jar nogui"))
                    state = start(sid, SERVERS_DIR / sid, launch)
                    with DB_LOCK, connect_db() as db: db.execute("INSERT OR REPLACE INTO server_runtime(server_id,launch_command,updated_at) VALUES(?,?,?)", (sid, launch, now()))
                    add_activity("Game process started", sid)
                    return self.json_response(200, {"ok": True, "runtime": state})
                if action == "stop":
                    state = stop(sid); add_activity("Game process stopped", sid)
                    return self.json_response(200, {"ok": True, "runtime": state})
                if action == "restart":
                    with DB_LOCK, connect_db() as db: cfg = db.execute("SELECT launch_command FROM server_runtime WHERE server_id=?", (sid,)).fetchone()
                    launch = str(data.get("launch_command") or (cfg["launch_command"] if cfg else "java -Xms1G -Xmx2G -jar server.jar nogui"))
                    if snapshot(sid).get("running"):
                        stop(sid)
                    state = start(sid, SERVERS_DIR / sid, launch)
                    with DB_LOCK, connect_db() as db: db.execute("INSERT OR REPLACE INTO server_runtime(server_id,launch_command,updated_at) VALUES(?,?,?)", (sid, launch, now()))
                    add_activity("Game process restarted", sid)
                    return self.json_response(200, {"ok": True, "runtime": state})
                if action == "command": return self.json_response(200, command(sid, data.get("command", "")))
                if action == "configure":
                    launch = str(data.get("launch_command", "")).strip(); _validate(launch)
                    with DB_LOCK, connect_db() as db: db.execute("INSERT OR REPLACE INTO server_runtime(server_id,launch_command,updated_at) VALUES(?,?,?)", (sid, launch, now()))
                    return self.json_response(200, {"ok": True, "launch_command": launch})
                if action == "files":
                    result = change_file(SERVERS_DIR / sid, data.get("operation"), str(data.get("path", "")), data.get("content", ""))
                    return self.json_response(200, {"ok": True, **result})
            except (ValueError, RuntimeError, OSError) as exc: return self.json_response(400, {"ok": False, "error": str(exc)})
            return self.json_response(404, {"ok": False, "error": "Server action not found"})
        if path == "/api/connectors":
            panel_type, base_url = str(data.get("panel_type", "")).strip(), str(data.get("base_url", "")).strip().rstrip("/")
            if panel_type not in VALID_PANELS - {"Nexus (local)"}: return self.json_response(400, {"ok": False, "error": "Choose a supported connector type."})
            if len(base_url) > 500 or not valid_url(base_url): return self.json_response(400, {"ok": False, "error": "Enter a valid HTTP(S) URL."})
            item = {"id": str(uuid.uuid4()), "panel_type": panel_type, "base_url": base_url, "status": "Saved - not tested", "created_at": now()}
            with DB_LOCK, connect_db() as db: db.execute("INSERT INTO connectors(id,panel_type,base_url,status,created_at) VALUES(?,?,?,?,?)", (item["id"], panel_type, base_url, item["status"], item["created_at"]))
            add_activity("Connector record saved", panel_type)
            return self.json_response(201, {"ok": True, "item": item})
        return self.json_response(404, {"ok": False, "error": "API route not found"})
    def do_PUT(self):
        if not self.api_authenticated():
            return
        path = urlparse(self.path).path.rstrip("/")
        parts = path.split("/")
        if len(parts) != 4 or parts[1:3] != ["api", "servers"]: return self.json_response(404, {"ok": False, "error": "API route not found"})
        try: data = self.read_json()
        except ValueError as exc: return self.json_response(400, {"ok": False, "error": str(exc)})
        sid = parts[3]
        with DB_LOCK, connect_db() as db:
            row = db.execute("SELECT * FROM servers WHERE id=?", (sid,)).fetchone()
            if row is None: return self.json_response(404, {"ok": False, "error": "Server not found"})
            item = dict(row); item.update({k: str(v).strip() for k,v in data.items()})
            if not item["name"] or len(item["name"]) > 64 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.-]*", item["name"]): return self.json_response(400, {"ok": False, "error": "Server name is invalid."})
            if item["game"] not in VALID_GAMES or item["panel"] not in VALID_PANELS or item["status"] not in VALID_STATUSES: return self.json_response(400, {"ok": False, "error": "Unsupported server settings."})
            db.execute("UPDATE servers SET name=?,game=?,panel=?,status=? WHERE id=?", (item["name"], item["game"], item["panel"], item["status"], sid))
        add_activity("Server record updated", item["name"])
        return self.json_response(200, {"ok": True, "item": item})
    def do_DELETE(self):
        if not self.api_authenticated():
            return
        parts = urlparse(self.path).path.rstrip("/").split("/")
        if len(parts) != 4 or parts[1] != "api" or parts[2] not in ("servers", "connectors"): return self.json_response(404, {"ok": False, "error": "API route not found"})
        kind, item_id = parts[2], parts[3]; table = "servers" if kind == "servers" else "connectors"
        with DB_LOCK, connect_db() as db:
            row = db.execute("SELECT * FROM " + table + " WHERE id=?", (item_id,)).fetchone()
            if row is None: return self.json_response(404, {"ok": False, "error": "Record not found"})
            label = row["name"] if kind == "servers" else row["panel_type"]
        if kind == "servers":
            from runtime_manager import snapshot, stop
            import shutil
            if snapshot(item_id).get("running"):
                try:
                    stop(item_id)
                except RuntimeError as exc:
                    return self.auth_error(409, "Cannot delete a running server safely: " + str(exc))
            with DB_LOCK, connect_db() as db:
                db.execute("DELETE FROM server_runtime WHERE server_id=?", (item_id,))
                db.execute("DELETE FROM servers WHERE id=?", (item_id,))
            server_dir = (SERVERS_DIR / item_id).resolve()
            if server_dir.parent == SERVERS_DIR.resolve() and server_dir.exists():
                shutil.rmtree(server_dir)
        else:
            with DB_LOCK, connect_db() as db:
                db.execute("DELETE FROM connectors WHERE id=?", (item_id,))
        add_activity("Record removed", label)
        return self.json_response(200, {"ok": True, "deleted_id": item_id})
    def translate_path(self, path):
        rel = url2pathname(urlparse(path).path).lstrip("/")
        parts = Path(rel).parts
        if parts and (parts[0] == "data" or any(p.startswith(".") for p in parts)): return str(ROOT / "__not_found__")
        target = (ROOT / rel).resolve()
        if target != ROOT and ROOT not in target.parents: return str(ROOT / "__not_found__")
        return str(target)

if __name__ == "__main__":
    init_db()
    print("Nexus Panel local development backend")
    print("Database:", DB_PATH)
    print("Listening on " + HOST + ":" + str(PORT))
    if HOST not in ("127.0.0.1", "::1", "localhost"):
        print("WARNING: remote binding enabled; this MVP has no login/authorization. Keep the forwarded port PRIVATE.")
    else:
        print("Local-only binding enabled. No login/authorization is implemented in this development build.")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
