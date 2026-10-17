#!/usr/bin/env python3
"""Nexus Panel development backend with owner authentication; node isolation is not production-ready."""
from __future__ import annotations
import json, os, re, sqlite3, threading, uuid, time, zipfile, signal, socket, ipaddress
from datetime import datetime, timezone, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from urllib.request import url2pathname

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("NEXUS_DATA_DIR", ROOT / "data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
SERVERS_DIR = DATA_DIR / "servers"
SERVERS_DIR.mkdir(parents=True, exist_ok=True)
BACKUPS_DIR = DATA_DIR / "backups"
BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
try:
    os.chmod(DATA_DIR, 0o700)
    os.chmod(BACKUPS_DIR, 0o700)
except OSError:
    pass
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
        CREATE TABLE IF NOT EXISTS server_ports (
            server_id TEXT PRIMARY KEY, port INTEGER NOT NULL UNIQUE,
            created_at TEXT NOT NULL, FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE
        );
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
        CREATE TABLE IF NOT EXISTS backups (
            id TEXT PRIMARY KEY, server_id TEXT NOT NULL, filename TEXT NOT NULL,
            size INTEGER NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS backup_schedules (
            server_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0,
            interval_hours INTEGER NOT NULL DEFAULT 24, next_run_at TEXT,
            last_run_at TEXT, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS billing_plans (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
            currency TEXT NOT NULL DEFAULT 'PKR', price_minor INTEGER NOT NULL,
            billing_interval TEXT NOT NULL DEFAULT 'month',
            ram_mb INTEGER NOT NULL, cpu_percent INTEGER NOT NULL, disk_mb INTEGER NOT NULL,
            server_limit INTEGER NOT NULL DEFAULT 1, enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS billing_invoices (
            id TEXT PRIMARY KEY, invoice_number TEXT NOT NULL UNIQUE, plan_id TEXT,
            plan_name TEXT NOT NULL, customer_name TEXT NOT NULL, customer_email TEXT NOT NULL,
            currency TEXT NOT NULL, amount_minor INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            payment_reference TEXT, notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
            due_at TEXT NOT NULL, paid_at TEXT,
            FOREIGN KEY(plan_id) REFERENCES billing_plans(id) ON DELETE SET NULL
        );
        """)
        if not db.execute("SELECT COUNT(*) FROM activities").fetchone()[0]:
            db.execute("INSERT INTO activities(message,detail,created_at) VALUES(?,?,?)", ("Nexus initialized", "Local database created", now()))

def add_activity(message, detail):
    with DB_LOCK, connect_db() as db:
        db.execute("INSERT INTO activities(message,detail,created_at) VALUES(?,?,?)", (str(message)[:180], str(detail)[:240], now()))

def public_host():
    configured = os.environ.get("NEXUS_PUBLIC_HOST", "").strip()
    if not configured:
        with DB_LOCK, connect_db() as db:
            row = db.execute("SELECT value FROM settings WHERE key='public_host'").fetchone()
        configured = row["value"].strip() if row else ""
    return configured

def valid_public_host(value):
    value = str(value or "").strip()
    if not value or len(value) > 253 or any(ch in value for ch in ("/", "?", "#", "@", " ")):
        return False
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return bool(re.fullmatch(r"(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(?:\.(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?))*", value))

def connection_address(port):
    host = public_host()
    if not host:
        return "127.0.0.1:" + str(port), False
    try:
        if ipaddress.ip_address(host).version == 6:
            host = "[" + host + "]"
    except ValueError:
        pass
    return host + ":" + str(port), True

def allocate_minecraft_port(db):
    start = int(os.environ.get("NEXUS_MINECRAFT_PORT_START", "25565"))
    end = int(os.environ.get("NEXUS_MINECRAFT_PORT_END", str(start + 99)))
    if start < 1024 or end < start or end > 65535 or end - start > 2000:
        raise ValueError("Minecraft port range is invalid. Configure NEXUS_MINECRAFT_PORT_START/END between 1024 and 65535.")
    allocated = {row["port"] for row in db.execute("SELECT port FROM server_ports")}
    for port in range(start, end + 1):
        if port in allocated:
            continue
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            probe.bind(("0.0.0.0", port))
            return port
        except OSError:
            continue
        finally:
            probe.close()
    raise RuntimeError("No free Minecraft ports remain in the configured allocation range.")

def configure_minecraft_properties(server_id, port):
    root = SERVERS_DIR / server_id
    root.mkdir(parents=True, exist_ok=True)
    path = root / "server.properties"
    existing = path.read_text("utf-8", errors="replace").splitlines() if path.exists() and not path.is_symlink() else []
    output = []
    seen_port = seen_ip = False
    for line in existing:
        if line.startswith("server-port="):
            output.append("server-port=" + str(port)); seen_port = True
        elif line.startswith("server-ip="):
            output.append("server-ip="); seen_ip = True
        else:
            output.append(line)
    if not seen_port: output.append("server-port=" + str(port))
    if not seen_ip: output.append("server-ip=")
    temp = path.with_suffix(".properties.tmp")
    temp.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    os.replace(temp, path)

def _write_varint(value):
    value = int(value) & 0xFFFFFFFF
    out = bytearray()
    while True:
        part = value & 0x7F
        value >>= 7
        if value:
            part |= 0x80
        out.append(part)
        if not value:
            return bytes(out)

def _read_varint(sock):
    value = 0
    for index in range(5):
        raw = sock.recv(1)
        if not raw:
            raise ConnectionError("Minecraft server closed the status connection.")
        byte = raw[0]
        value |= (byte & 0x7F) << (7 * index)
        if not byte & 0x80:
            return value
    raise ValueError("Invalid Minecraft status packet length.")

def _recv_exact(sock, count):
    chunks = bytearray()
    while len(chunks) < count:
        part = sock.recv(count - len(chunks))
        if not part:
            raise ConnectionError("Minecraft server closed the status packet.")
        chunks.extend(part)
    return bytes(chunks)

def minecraft_status(port, timeout=1.5):
    """Query a local Java Edition server using the vanilla Server List Ping protocol."""
    import json as _json
    import time as _time
    started = _time.monotonic()
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout) as sock:
            sock.settimeout(timeout)
            host = b"localhost"
            handshake = (b"\x00" + _write_varint(767) + _write_varint(len(host)) + host
                         + int(port).to_bytes(2, "big") + b"\x01")
            packet = _write_varint(len(handshake)) + handshake
            sock.sendall(packet + b"\x01\x00")
            packet_length = _read_varint(sock)
            if packet_length < 1 or packet_length > 1_048_576:
                raise ValueError("Invalid Minecraft status response size.")
            packet_id = _read_varint(sock)
            if packet_id != 0:
                raise ValueError("Unexpected Minecraft status response packet.")
            json_length = _read_varint(sock)
            if json_length < 2 or json_length > 1_048_576 or json_length > packet_length:
                raise ValueError("Invalid Minecraft status JSON size.")
            payload = _json.loads(_recv_exact(sock, json_length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Invalid Minecraft status JSON.")
            players = payload.get("players") if isinstance(payload.get("players"), dict) else {}
            version = payload.get("version") if isinstance(payload.get("version"), dict) else {}
            description = payload.get("description", "")
            if isinstance(description, dict):
                description = description.get("text", "")
            elif isinstance(description, list):
                description = " ".join(str(x.get("text", "")) if isinstance(x, dict) else str(x) for x in description)
            return {"online": True, "players": int(players.get("online", 0)), "max_players": int(players.get("max", 0)),
                    "version": str(version.get("name", "Unknown"))[:80], "motd": str(description)[:200],
                    "latency_ms": round((_time.monotonic() - started) * 1000)}
    except (OSError, ValueError, UnicodeError, ConnectionError, TimeoutError, _json.JSONDecodeError):
        return {"online": False, "players": 0, "max_players": 0, "version": None, "motd": None, "latency_ms": None}

def server_connection_info(item):
    result = dict(item)
    with DB_LOCK, connect_db() as db:
        row = db.execute("SELECT port FROM server_ports WHERE server_id=?", (item["id"],)).fetchone()
    if item.get("game") == "Minecraft" and row:
        result["connect_port"] = row["port"]
        result["connect_address"], result["public_address_configured"] = connection_address(row["port"])
        result["connection_type"] = "Java Edition"
    else:
        result["connect_port"] = None
        result["connect_address"] = None
        result["public_address_configured"] = False
        result["connection_type"] = None
    return result

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
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
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
        if path in ("/", "/index.html", "/studio.html"):
            if not configured() or not has_owner():
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
        if path == "/api/billing/plans":
            with DB_LOCK, connect_db() as db:
                rows = [dict(row) for row in db.execute("SELECT * FROM billing_plans ORDER BY created_at DESC")]
            return self.json_response(200, {"ok": True, "items": rows})
        if path == "/api/billing/invoices":
            with DB_LOCK, connect_db() as db:
                rows = [dict(row) for row in db.execute("SELECT * FROM billing_invoices ORDER BY created_at DESC LIMIT 500")]
            return self.json_response(200, {"ok": True, "items": rows})
        if path == "/api/network/public-host":
            host = public_host()
            return self.json_response(200, {"ok": True, "public_host": host, "configured": bool(host),
                                            "environment_override": bool(os.environ.get("NEXUS_PUBLIC_HOST", "").strip()),
                                            "port_start": int(os.environ.get("NEXUS_MINECRAFT_PORT_START", "25565")),
                                            "port_end": int(os.environ.get("NEXUS_MINECRAFT_PORT_END", str(int(os.environ.get("NEXUS_MINECRAFT_PORT_START", "25565")) + 99)))})
        if path == "/api/host-metrics":
            from runtime_manager import host_metrics
            return self.json_response(200, {"ok": True, **host_metrics(DATA_DIR)})
        if path == "/api/overview":
            with DB_LOCK, connect_db() as db:
                servers = db.execute("SELECT COUNT(*) FROM servers").fetchone()[0]
                connectors = db.execute("SELECT COUNT(*) FROM connectors").fetchone()[0]
                activities = [dict(r) for r in db.execute("SELECT * FROM activities ORDER BY id DESC LIMIT 8")]
            return self.json_response(200, {"ok": True, "servers": servers, "connectors": connectors, "activities": activities})
        if path == "/api/servers":
            with DB_LOCK, connect_db() as db: rows = [dict(r) for r in db.execute("SELECT * FROM servers ORDER BY created_at DESC")]
            return self.json_response(200, {"ok": True, "items": [server_connection_info(row) for row in rows]})
        if path == "/api/connectors":
            with DB_LOCK, connect_db() as db: rows = [dict(r) for r in db.execute("SELECT * FROM connectors ORDER BY created_at DESC")]
            return self.json_response(200, {"ok": True, "items": rows})
        if path.startswith("/api/servers/"):
            parts = path.strip("/").split("/")
            if len(parts) < 3 or not server_exists(parts[2]): return self.json_response(404, {"ok": False, "error": "Server not found"})
            sid = parts[2]
            from runtime_manager import snapshot, logs, list_files, server_path, process_metrics
            if len(parts) == 3:
                with DB_LOCK, connect_db() as db:
                    cfg = db.execute("SELECT launch_command FROM server_runtime WHERE server_id=?", (sid,)).fetchone()
                    item = db.execute("SELECT * FROM servers WHERE id=?", (sid,)).fetchone()
                return self.json_response(200, {"ok": True, "runtime": snapshot(sid), "launch_command": cfg["launch_command"] if cfg else "java -Xms1G -Xmx2G -jar server.jar nogui", "server": server_connection_info(dict(item))})
            if len(parts) == 4 and parts[3] == "game-status":
                with DB_LOCK, connect_db() as db:
                    game = db.execute("SELECT game FROM servers WHERE id=?", (sid,)).fetchone()
                    port_row = db.execute("SELECT port FROM server_ports WHERE server_id=?", (sid,)).fetchone()
                if not game or game["game"] != "Minecraft" or not port_row:
                    return self.json_response(200, {"ok": True, "supported": False, "online": False, "players": 0, "max_players": 0})
                return self.json_response(200, {"ok": True, "supported": True, **minecraft_status(port_row["port"])})
            if len(parts) == 4 and parts[3] == "metrics": return self.json_response(200, {"ok": True, **process_metrics(sid)})
            if len(parts) == 4 and parts[3] == "console": return self.json_response(200, {"ok": True, **logs(sid)})
            if len(parts) == 4 and parts[3] == "backups":
                with DB_LOCK, connect_db() as db:
                    rows = [dict(row) for row in db.execute("SELECT id,server_id,filename,size,sha256,created_at FROM backups WHERE server_id=? ORDER BY created_at DESC", (sid,))]
                return self.json_response(200, {"ok": True, "items": rows})
            if len(parts) == 4 and parts[3] == "backup-schedule":
                with DB_LOCK, connect_db() as db:
                    row = db.execute("SELECT server_id,enabled,interval_hours,next_run_at,last_run_at,updated_at FROM backup_schedules WHERE server_id=?", (sid,)).fetchone()
                schedule = dict(row) if row else {"server_id": sid, "enabled": 0, "interval_hours": 24, "next_run_at": None, "last_run_at": None}
                return self.json_response(200, {"ok": True, "schedule": schedule})
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
        if path == "/api/network/public-host":
            if os.environ.get("NEXUS_PUBLIC_HOST", "").strip():
                return self.json_response(409, {"ok": False, "error": "NEXUS_PUBLIC_HOST is set by the environment. Change it there and restart Nexus."})
            host = str(data.get("public_host", "")).strip().lower()
            if host and not valid_public_host(host):
                return self.json_response(400, {"ok": False, "error": "Enter a public IPv4 address or DNS hostname (not a URL)."})
            with DB_LOCK, connect_db() as db:
                db.execute("INSERT OR REPLACE INTO settings(key,value,updated_at) VALUES('public_host',?,?)", (host, now()))
            add_activity("Public game address updated", host or "Cleared; local-only display")
            return self.json_response(200, {"ok": True, "public_host": host, "configured": bool(host)})
        if path == "/api/billing/plans":
            name = str(data.get("name", "")).strip()
            description = str(data.get("description", "")).strip()[:500]
            currency = str(data.get("currency", "PKR")).upper()
            interval = str(data.get("billing_interval", "month"))
            try:
                price = data.get("price_minor")
                ram = data.get("ram_mb")
                cpu = data.get("cpu_percent")
                disk = data.get("disk_mb")
                limit = data.get("server_limit", 1)
                values = (price, ram, cpu, disk, limit)
                if any(isinstance(v, bool) or not isinstance(v, int) for v in values):
                    raise ValueError("Price and resource limits must be whole numbers.")
                if not name or len(name) > 80 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.-]*", name):
                    raise ValueError("Plan name must be 1–80 valid characters.")
                if currency not in ("PKR", "USD", "INR") or interval not in ("month", "year"):
                    raise ValueError("Choose PKR, USD or INR and a monthly or yearly interval.")
                if not (0 <= price <= 100000000 and 256 <= ram <= 1048576 and 10 <= cpu <= 6400 and 512 <= disk <= 1048576 and 1 <= limit <= 100):
                    raise ValueError("Plan price or resource limits are outside supported bounds.")
                plan = {"id": str(uuid.uuid4()), "name": name, "description": description,
                        "currency": currency, "price_minor": price, "billing_interval": interval,
                        "ram_mb": ram, "cpu_percent": cpu, "disk_mb": disk, "server_limit": limit,
                        "enabled": 1, "created_at": now(), "updated_at": now()}
                with DB_LOCK, connect_db() as db:
                    db.execute("INSERT INTO billing_plans(id,name,description,currency,price_minor,billing_interval,ram_mb,cpu_percent,disk_mb,server_limit,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                               tuple(plan[k] for k in ("id","name","description","currency","price_minor","billing_interval","ram_mb","cpu_percent","disk_mb","server_limit","enabled","created_at","updated_at")))
                add_activity("Billing plan created", name)
                return self.json_response(201, {"ok": True, "item": plan})
            except (ValueError, TypeError) as exc:
                return self.json_response(400, {"ok": False, "error": str(exc)})
        if path == "/api/billing/invoices":
            plan_id = str(data.get("plan_id", ""))
            customer_name = str(data.get("customer_name", "")).strip()
            customer_email = str(data.get("customer_email", "")).strip().lower()
            if not customer_name or len(customer_name) > 120 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", customer_email):
                return self.json_response(400, {"ok": False, "error": "Enter a customer name and valid email address."})
            with DB_LOCK, connect_db() as db:
                plan = db.execute("SELECT * FROM billing_plans WHERE id=? AND enabled=1", (plan_id,)).fetchone()
                if not plan:
                    return self.json_response(404, {"ok": False, "error": "Enabled billing plan not found."})
                count = db.execute("SELECT COUNT(*) FROM billing_invoices").fetchone()[0]
                invoice_number = "NEX-" + datetime.now(timezone.utc).strftime("%Y%m") + "-" + str(count + 1).zfill(5)
                invoice_id = str(uuid.uuid4())
                created = datetime.now(timezone.utc)
                due = (created + timedelta(days=7)).isoformat(timespec="seconds")
                db.execute("INSERT INTO billing_invoices(id,invoice_number,plan_id,plan_name,customer_name,customer_email,currency,amount_minor,status,payment_reference,notes,created_at,due_at,paid_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (invoice_id, invoice_number, plan["id"], plan["name"], customer_name, customer_email,
                            plan["currency"], plan["price_minor"], "pending", None, "", now(), due, None))
                row = db.execute("SELECT * FROM billing_invoices WHERE id=?", (invoice_id,)).fetchone()
            add_activity("Billing invoice created", invoice_number + " · " + customer_email)
            return self.json_response(201, {"ok": True, "item": dict(row)})
        if path.startswith("/api/billing/invoices/") and path.endswith("/record-payment"):
            parts = path.strip("/").split("/")
            if len(parts) != 5:
                return self.json_response(404, {"ok": False, "error": "Invoice action not found"})
            invoice_id = parts[3]
            reference = str(data.get("payment_reference", "")).strip()
            notes = str(data.get("notes", "")).strip()[:500]
            if not reference or len(reference) > 120:
                return self.json_response(400, {"ok": False, "error": "Enter a payment reference before recording payment."})
            with DB_LOCK, connect_db() as db:
                invoice = db.execute("SELECT * FROM billing_invoices WHERE id=?", (invoice_id,)).fetchone()
                if not invoice:
                    return self.json_response(404, {"ok": False, "error": "Invoice not found."})
                if invoice["status"] == "paid":
                    return self.json_response(409, {"ok": False, "error": "This invoice is already recorded as paid."})
                db.execute("UPDATE billing_invoices SET status='paid',payment_reference=?,notes=?,paid_at=? WHERE id=?",
                           (reference, notes, now(), invoice_id))
                row = db.execute("SELECT * FROM billing_invoices WHERE id=?", (invoice_id,)).fetchone()
            add_activity("Manual payment recorded", row["invoice_number"] + " · reference " + reference)
            return self.json_response(200, {"ok": True, "item": dict(row), "manual_record_only": True})
        if path == "/api/servers":
            name, game, panel = str(data.get("name", "")).strip(), str(data.get("game", "")).strip(), str(data.get("panel", "Nexus (local)")).strip()
            status = str(data.get("status", "Configured")).strip()
            if not name or len(name) > 64 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.-]*", name): return self.json_response(400, {"ok": False, "error": "Server name is invalid."})
            if game not in VALID_GAMES or panel not in VALID_PANELS or status not in VALID_STATUSES: return self.json_response(400, {"ok": False, "error": "Choose a supported game, panel and status."})
            item = {"id": str(uuid.uuid4()), "name": name, "game": game, "panel": panel, "status": status, "created_at": now()}
            port = None
            try:
                with DB_LOCK, connect_db() as db:
                    db.execute("INSERT INTO servers(id,name,game,panel,status,created_at) VALUES(?,?,?,?,?,?)", (item["id"], name, game, panel, status, item["created_at"]))
                    db.execute("INSERT OR IGNORE INTO server_runtime(server_id,launch_command,updated_at) VALUES(?,?,?)", (item["id"], "java -Xms1G -Xmx2G -jar server.jar nogui", now()))
                    if game == "Minecraft" and panel == "Nexus (local)":
                        port = allocate_minecraft_port(db)
                        db.execute("INSERT INTO server_ports(server_id,port,created_at) VALUES(?,?,?)", (item["id"], port, now()))
                        item["connect_port"] = port
                (SERVERS_DIR / item["id"]).mkdir(parents=True, exist_ok=True)
                if port is not None:
                    configure_minecraft_properties(item["id"], port)
            except (OSError, RuntimeError, ValueError, sqlite3.IntegrityError) as exc:
                with DB_LOCK, connect_db() as db:
                    db.execute("DELETE FROM server_ports WHERE server_id=?", (item["id"],))
                    db.execute("DELETE FROM server_runtime WHERE server_id=?", (item["id"],))
                    db.execute("DELETE FROM servers WHERE id=?", (item["id"],))
                return self.json_response(400, {"ok": False, "error": str(exc)})
            item = server_connection_info(item)
            add_activity("Game server record created", name + " · " + game + " · " + (item.get("connect_address") or panel))
            return self.json_response(201, {"ok": True, "item": item})
        if path.startswith("/api/servers/"):
            parts = path.strip("/").split("/")
            if len(parts) != 4 or not server_exists(parts[2]): return self.json_response(404, {"ok": False, "error": "Server not found"})
            sid, action = parts[2], parts[3]
            from runtime_manager import start, stop, command, change_file, snapshot, install_paper, _validate
            from backup_manager import create_backup, restore_backup
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
                if action == "backup-schedule":
                    enabled_value = data.get("enabled", False)
                    interval_value = data.get("interval_hours", 24)
                    if not isinstance(enabled_value, bool):
                        raise ValueError("Schedule enabled must be true or false.")
                    if isinstance(interval_value, bool) or not isinstance(interval_value, int) or interval_value < 1 or interval_value > 168:
                        raise ValueError("Backup interval must be between 1 and 168 hours.")
                    next_run = (datetime.now(timezone.utc) + timedelta(hours=interval_value)).isoformat(timespec="seconds") if enabled_value else None
                    with DB_LOCK, connect_db() as db:
                        db.execute("INSERT OR REPLACE INTO backup_schedules(server_id,enabled,interval_hours,next_run_at,last_run_at,updated_at) VALUES(?,?,?,?,COALESCE((SELECT last_run_at FROM backup_schedules WHERE server_id=?),NULL),?)",
                                   (sid, 1 if enabled_value else 0, interval_value, next_run, sid, now()))
                        row = db.execute("SELECT server_id,enabled,interval_hours,next_run_at,last_run_at,updated_at FROM backup_schedules WHERE server_id=?", (sid,)).fetchone()
                    add_activity("Backup schedule updated", sid + " · " + ("enabled" if enabled_value else "disabled"))
                    return self.json_response(200, {"ok": True, "schedule": dict(row)})
                if action == "backup":
                    backup_id = str(uuid.uuid4())
                    paused = False
                    try:
                        if snapshot(sid).get("running"):
                            command(sid, "save-off")
                            paused = True
                            command(sid, "save-all flush")
                            time.sleep(2)
                        result = create_backup(SERVERS_DIR / sid, BACKUPS_DIR / sid, backup_id)
                    finally:
                        if paused:
                            try:
                                command(sid, "save-on")
                            except Exception:
                                add_activity("Backup save-on recovery failed", sid + " · check server console")
                    with DB_LOCK, connect_db() as db:
                        db.execute("INSERT INTO backups(id,server_id,filename,size,sha256,created_at) VALUES(?,?,?,?,?,?)",
                                   (backup_id, sid, result["filename"], result["size"], result["sha256"], now()))
                    add_activity("Server backup created", sid + " · " + result["filename"])
                    return self.json_response(201, {"ok": True, "backup": {**result, "created_at": now()}})
                if action == "restore":
                    if snapshot(sid).get("running"):
                        raise RuntimeError("Stop the server before restoring a backup.")
                    backup_id = str(data.get("backup_id", ""))
                    with DB_LOCK, connect_db() as db:
                        selected = db.execute("SELECT * FROM backups WHERE id=? AND server_id=?", (backup_id, sid)).fetchone()
                    if not selected:
                        return self.json_response(404, {"ok": False, "error": "Backup not found for this server."})
                    # Preserve the current state before replacing any files.
                    pre_id = str(uuid.uuid4())
                    pre = create_backup(SERVERS_DIR / sid, BACKUPS_DIR / sid, pre_id)
                    with DB_LOCK, connect_db() as db:
                        db.execute("INSERT INTO backups(id,server_id,filename,size,sha256,created_at) VALUES(?,?,?,?,?,?)",
                                   (pre_id, sid, pre["filename"], pre["size"], pre["sha256"], now()))
                    restored = restore_backup(SERVERS_DIR / sid, selected["filename"], selected["sha256"], BACKUPS_DIR / sid)
                    add_activity("Server backup restored", sid + " · " + selected["filename"])
                    return self.json_response(200, {"ok": True, "restore": restored, "pre_restore_backup_id": pre_id})
                if action == "start":
                    with DB_LOCK, connect_db() as db:
                        cfg = db.execute("SELECT launch_command FROM server_runtime WHERE server_id=?", (sid,)).fetchone()
                        game_row = db.execute("SELECT game FROM servers WHERE id=?", (sid,)).fetchone()
                        port_row = db.execute("SELECT port FROM server_ports WHERE server_id=?", (sid,)).fetchone()
                    if game_row and game_row["game"] == "Minecraft" and port_row:
                        configure_minecraft_properties(sid, port_row["port"])
                    launch = str(data.get("launch_command") or (cfg["launch_command"] if cfg else "java -Xms1G -Xmx2G -jar server.jar nogui"))
                    state = start(sid, SERVERS_DIR / sid, launch)
                    with DB_LOCK, connect_db() as db: db.execute("INSERT OR REPLACE INTO server_runtime(server_id,launch_command,updated_at) VALUES(?,?,?)", (sid, launch, now()))
                    add_activity("Game process started", sid)
                    return self.json_response(200, {"ok": True, "runtime": state})
                if action == "stop":
                    state = stop(sid); add_activity("Game process stopped", sid)
                    return self.json_response(200, {"ok": True, "runtime": state})
                if action == "restart":
                    with DB_LOCK, connect_db() as db:
                        cfg = db.execute("SELECT launch_command FROM server_runtime WHERE server_id=?", (sid,)).fetchone()
                        game_row = db.execute("SELECT game FROM servers WHERE id=?", (sid,)).fetchone()
                        port_row = db.execute("SELECT port FROM server_ports WHERE server_id=?", (sid,)).fetchone()
                    if game_row and game_row["game"] == "Minecraft" and port_row:
                        configure_minecraft_properties(sid, port_row["port"])
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
            except (ValueError, RuntimeError, OSError, zipfile.BadZipFile) as exc: return self.json_response(400, {"ok": False, "error": str(exc)})
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
        if len(parts) == 4 and parts[1:3] == ["api", "billing-plans"]:
            plan_id = parts[3]
            with DB_LOCK, connect_db() as db:
                row = db.execute("SELECT name FROM billing_plans WHERE id=?", (plan_id,)).fetchone()
                if row is None:
                    return self.json_response(404, {"ok": False, "error": "Billing plan not found"})
                db.execute("UPDATE billing_plans SET enabled=0,updated_at=? WHERE id=?", (now(), plan_id))
            add_activity("Billing plan disabled", row["name"])
            return self.json_response(200, {"ok": True, "disabled_id": plan_id})
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
                db.execute("DELETE FROM backups WHERE server_id=?", (item_id,))
                db.execute("DELETE FROM backup_schedules WHERE server_id=?", (item_id,))
                db.execute("DELETE FROM server_ports WHERE server_id=?", (item_id,))
                db.execute("DELETE FROM server_runtime WHERE server_id=?", (item_id,))
                db.execute("DELETE FROM servers WHERE id=?", (item_id,))
            server_dir = (SERVERS_DIR / item_id).resolve()
            if server_dir.parent == SERVERS_DIR.resolve() and server_dir.exists():
                shutil.rmtree(server_dir)
            backup_dir = (BACKUPS_DIR / item_id).resolve()
            if backup_dir.parent == BACKUPS_DIR.resolve() and backup_dir.exists():
                shutil.rmtree(backup_dir)
        else:
            with DB_LOCK, connect_db() as db:
                db.execute("DELETE FROM connectors WHERE id=?", (item_id,))
        add_activity("Record removed", label)
        return self.json_response(200, {"ok": True, "deleted_id": item_id})
    def translate_path(self, path):
        rel = url2pathname(urlparse(path).path).lstrip("/")
        # Only serve the explicit browser UI allowlist. Never expose Python source,
        # tests, docs, local data, Git metadata, or arbitrary repository files.
        public_files = {"index.html", "login.html", "installer.html", "studio.html", "styles.css", "app.js", "runtime-ui.js"}
        if rel not in public_files:
            return str(ROOT / "__not_found__")
        target = (ROOT / rel).resolve()
        if target != ROOT and ROOT not in target.parents:
            return str(ROOT / "__not_found__")
        return str(target)

def _run_scheduled_backup(server_id, interval_hours):
    from backup_manager import create_backup
    from runtime_manager import snapshot, command
    paused = False
    try:
        if not server_exists(server_id):
            with DB_LOCK, connect_db() as db:
                db.execute("UPDATE backup_schedules SET enabled=0,next_run_at=NULL,updated_at=? WHERE server_id=?", (now(), server_id))
            return
        next_run = (datetime.now(timezone.utc) + timedelta(hours=interval_hours)).isoformat(timespec="seconds")
        with DB_LOCK, connect_db() as db:
            db.execute("UPDATE backup_schedules SET next_run_at=?,updated_at=? WHERE server_id=?", (next_run, now(), server_id))
        if snapshot(server_id).get("running"):
            command(server_id, "save-off")
            paused = True
            command(server_id, "save-all flush")
            time.sleep(2)
        backup_id = str(uuid.uuid4())
        result = create_backup(SERVERS_DIR / server_id, BACKUPS_DIR / server_id, backup_id)
        created = now()
        with DB_LOCK, connect_db() as db:
            db.execute("INSERT INTO backups(id,server_id,filename,size,sha256,created_at) VALUES(?,?,?,?,?,?)",
                       (backup_id, server_id, result["filename"], result["size"], result["sha256"], created))
            db.execute("UPDATE backup_schedules SET last_run_at=?,updated_at=? WHERE server_id=?", (created, created, server_id))
            stale = [dict(row) for row in db.execute("SELECT id,filename FROM backups WHERE server_id=? ORDER BY created_at DESC LIMIT -1 OFFSET 20", (server_id,))]
            for item in stale:
                db.execute("DELETE FROM backups WHERE id=?", (item["id"],))
        for item in stale:
            path = (BACKUPS_DIR / server_id / item["filename"]).resolve()
            if path.parent == (BACKUPS_DIR / server_id).resolve() and path.exists():
                path.unlink()
        add_activity("Scheduled backup completed", server_id + " · " + result["filename"])
    except Exception as exc:
        retry_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(timespec="seconds")
        with DB_LOCK, connect_db() as db:
            db.execute("UPDATE backup_schedules SET next_run_at=?,updated_at=? WHERE server_id=?", (retry_at, now(), server_id))
        add_activity("Scheduled backup failed", server_id + " · " + str(exc)[:180])
    finally:
        if paused:
            try:
                command(server_id, "save-on")
            except Exception:
                add_activity("Backup save-on recovery failed", server_id + " · check server console")


def _backup_scheduler_loop():
    while True:
        time.sleep(30)
        try:
            with DB_LOCK, connect_db() as db:
                due = [dict(row) for row in db.execute(
                    "SELECT server_id,interval_hours FROM backup_schedules WHERE enabled=1 AND next_run_at IS NOT NULL AND next_run_at<=?",
                    (now(),)
                )]
            for item in due:
                _run_scheduled_backup(item["server_id"], item["interval_hours"])
        except Exception as exc:
            print("[nexus] Backup scheduler error: " + str(exc))


if __name__ == "__main__":
    init_db()
    threading.Thread(target=_backup_scheduler_loop, daemon=True, name="nexus-backup-scheduler").start()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print("Nexus Panel development backend")
    print("Database:", DB_PATH)
    print("Listening on " + HOST + ":" + str(PORT))
    if HOST not in ("127.0.0.1", "::1", "localhost"):
        print("WARNING: remote binding enabled; owner login exists but node isolation and production hardening are incomplete. Keep the forwarded port PRIVATE.")
    else:
        print("Local-only binding enabled. Node isolation and production hardening are still required before public deployment.")

    def _handle_shutdown(signum, frame):
        print("[nexus] Shutdown requested; stopping managed game processes safely...")
        threading.Thread(target=httpd.shutdown, daemon=True, name="nexus-http-shutdown").start()

    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)
    try:
        httpd.serve_forever()
    finally:
        try:
            from runtime_manager import shutdown_all
            stopped = shutdown_all()
            print("[nexus] Stopped " + str(len(stopped)) + " managed game process(es).")
        finally:
            httpd.server_close()
