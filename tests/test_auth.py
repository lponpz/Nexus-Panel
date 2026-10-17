"""Integration tests for Nexus owner authentication and CSRF protection.

Run with: python3 -m unittest discover -s tests -v
Only Python's standard library is required.
"""
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

TEMP = tempfile.TemporaryDirectory(prefix="nexus-auth-tests-")
os.environ["NEXUS_DATA_DIR"] = TEMP.name
os.environ["NEXUS_PORT"] = "0"

import server  # noqa: E402

server.init_db()
HTTPD = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
THREAD = threading.Thread(target=HTTPD.serve_forever, daemon=True)
THREAD.start()
BASE = "http://127.0.0.1:" + str(HTTPD.server_address[1])
ORIGIN = BASE


def request(path, method="GET", payload=None, cookie=None, csrf=None):
    body = None if payload is None else json.dumps(payload).encode()
    headers = {"Origin": ORIGIN}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if cookie:
        headers["Cookie"] = cookie.split(";", 1)[0]
    if csrf:
        headers["X-Nexus-CSRF"] = csrf
    req = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            return response.status, response.headers, json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, json.loads(exc.read().decode())


class AuthIntegrationTests(unittest.TestCase):
    def setUp(self):
        with server.DB_LOCK, server.connect_db() as db:
            for table in ("sessions", "backups", "backup_schedules", "users", "servers", "server_runtime", "connectors", "activities", "settings"):
                db.execute("DELETE FROM " + table)

    def create_owner(self):
        status, headers, data = request("/api/setup", "POST", {
            "workspace_name": "Test Workspace",
            "username": "test-owner",
            "password": "correct-horse-battery-staple"
        })
        self.assertEqual(status, 200, data)
        self.assertTrue(data["authenticated"])
        return headers.get("Set-Cookie"), data["csrf_token"]

    def test_api_is_closed_before_first_setup(self):
        status, _, data = request("/api/servers")
        self.assertEqual(status, 403)
        self.assertIn("setup", data["error"].lower())

    def test_setup_creates_owner_hash_and_authenticated_session(self):
        cookie, csrf = self.create_owner()
        with server.DB_LOCK, server.connect_db() as db:
            row = db.execute("SELECT username,password_hash FROM users").fetchone()
        self.assertEqual(row["username"], "test-owner")
        self.assertNotEqual(row["password_hash"], "correct-horse-battery-staple")
        self.assertTrue(server.password_matches("correct-horse-battery-staple", row["password_hash"]))
        status, _, data = request("/api/servers", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        status, _, data = request("/api/setup", "POST", {
            "workspace_name": "Takeover", "username": "other-owner", "password": "another-long-password"
        })
        self.assertEqual(status, 403)

    def test_mutations_require_csrf_and_logout_revokes_session(self):
        cookie, csrf = self.create_owner()
        payload = {"name": "Test Minecraft", "game": "Minecraft", "panel": "Nexus (local)", "status": "Configured"}
        status, _, data = request("/api/servers", "POST", payload, cookie=cookie)
        self.assertEqual(status, 403)
        status, _, data = request("/api/servers", "POST", payload, cookie=cookie, csrf=csrf)
        self.assertEqual(status, 201, data)
        status, _, data = request("/api/auth/logout", "POST", {}, cookie=cookie, csrf=csrf)
        self.assertEqual(status, 200, data)
        status, _, data = request("/api/servers", cookie=cookie)
        self.assertEqual(status, 401)

    def test_login_rejects_bad_password_and_accepts_owner(self):
        self.create_owner()
        status, _, _ = request("/api/auth/login", "POST", {"username": "test-owner", "password": "wrong"})
        self.assertEqual(status, 401)
        status, headers, data = request("/api/auth/login", "POST", {
            "username": "test-owner", "password": "correct-horse-battery-staple"
        })
        self.assertEqual(status, 200, data)
        self.assertTrue(headers.get("Set-Cookie", "").startswith("nexus_session="))
        self.assertTrue(data["csrf_token"])

    def test_file_download_and_server_delete(self):
        cookie, csrf = self.create_owner()
        payload = {"name": "Download Test", "game": "Minecraft", "panel": "Nexus (local)", "status": "Configured"}
        status, _, data = request("/api/servers", "POST", payload, cookie=cookie, csrf=csrf)
        self.assertEqual(status, 201, data)
        server_id = data["item"]["id"]
        folder = server.SERVERS_DIR / server_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "hello.txt").write_text("nexus download test", encoding="utf-8")
        req = urllib.request.Request(BASE + "/api/servers/" + server_id + "/file-download?path=hello.txt",
                                     headers={"Cookie": cookie.split(";", 1)[0]})
        with urllib.request.urlopen(req, timeout=3) as response:
            self.assertEqual(response.read(), b"nexus download test")
            self.assertIn("attachment", response.headers.get("Content-Disposition", ""))
        status, _, data = request("/api/servers/" + server_id, "DELETE", cookie=cookie, csrf=csrf)
        self.assertEqual(status, 200, data)
        self.assertFalse(folder.exists())

    def test_static_server_source_is_not_served(self):
        req = urllib.request.Request(BASE + "/server.py")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req, timeout=3)
        self.assertEqual(caught.exception.code, 404)

    def test_backup_and_restore_api_creates_pre_restore_safety_backup(self):
        cookie, csrf = self.create_owner()
        payload = {"name": "Backup Test", "game": "Minecraft", "panel": "Nexus (local)", "status": "Configured"}
        status, _, data = request("/api/servers", "POST", payload, cookie=cookie, csrf=csrf)
        self.assertEqual(status, 201, data)
        server_id = data["item"]["id"]
        folder = server.SERVERS_DIR / server_id
        status, _, backup_response = request("/api/servers/" + server_id + "/backup", "POST", {}, cookie=cookie, csrf=csrf)
        self.assertEqual(status, 201, backup_response)
        backup_id = backup_response["backup"]["id"]
        (folder / "new-after-backup.txt").write_text("temporary", encoding="utf-8")
        status, _, restore_response = request("/api/servers/" + server_id + "/restore", "POST", {"backup_id": backup_id}, cookie=cookie, csrf=csrf)
        self.assertEqual(status, 200, restore_response)
        self.assertFalse((folder / "new-after-backup.txt").exists())
        self.assertTrue(restore_response["pre_restore_backup_id"])
        status, _, backups_response = request("/api/servers/" + server_id + "/backups", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertEqual(len(backups_response["items"]), 2)

    def test_backup_schedule_can_be_enabled_and_disabled(self):
        cookie, csrf = self.create_owner()
        payload = {"name": "Scheduled Backup Test", "game": "Minecraft", "panel": "Nexus (local)", "status": "Configured"}
        status, _, data = request("/api/servers", "POST", payload, cookie=cookie, csrf=csrf)
        self.assertEqual(status, 201, data)
        server_id = data["item"]["id"]
        status, _, initial = request("/api/servers/" + server_id + "/backup-schedule", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertEqual(initial["schedule"]["enabled"], 0)
        status, _, enabled = request("/api/servers/" + server_id + "/backup-schedule", "POST",
                                     {"enabled": True, "interval_hours": 6}, cookie=cookie, csrf=csrf)
        self.assertEqual(status, 200, enabled)
        self.assertEqual(enabled["schedule"]["enabled"], 1)
        self.assertIsNotNone(enabled["schedule"]["next_run_at"])
        status, _, disabled = request("/api/servers/" + server_id + "/backup-schedule", "POST",
                                      {"enabled": False, "interval_hours": 24}, cookie=cookie, csrf=csrf)
        self.assertEqual(status, 200, disabled)
        self.assertEqual(disabled["schedule"]["enabled"], 0)
        self.assertIsNone(disabled["schedule"]["next_run_at"])

    def test_host_and_server_metrics_are_real_api_responses(self):
        cookie, csrf = self.create_owner()
        status, _, host = request("/api/host-metrics", cookie=cookie)
        self.assertEqual(status, 200, host)
        self.assertGreaterEqual(host["cpu_count"], 1)
        self.assertGreater(host["disk_total_gb"], 0)
        payload = {"name": "Metrics Test", "game": "Minecraft", "panel": "Nexus (local)", "status": "Configured"}
        status, _, created = request("/api/servers", "POST", payload, cookie=cookie, csrf=csrf)
        self.assertEqual(status, 201, created)
        server_id = created["item"]["id"]
        status, _, metrics = request("/api/servers/" + server_id + "/metrics", cookie=cookie)
        self.assertEqual(status, 200, metrics)
        self.assertFalse(metrics["running"])


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        HTTPD.shutdown()
        HTTPD.server_close()
        TEMP.cleanup()
