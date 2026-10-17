"""Backup/restore integrity tests; no external dependencies."""
import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path

import backup_manager


class BackupManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nexus-backup-test-")
        self.root = Path(self.temp.name)
        self.server = self.root / "servers" / "server-1"
        self.server.mkdir(parents=True)
        self.backups = self.root / "backups" / "server-1"
        (self.server / "config").mkdir()
        (self.server / "config" / "server.properties").write_text("motd=original\n", encoding="utf-8")
        (self.server / "world.dat").write_bytes(b"world-data")

    def tearDown(self):
        self.temp.cleanup()

    def test_backup_restore_round_trip_and_preserves_original_backup(self):
        created = backup_manager.create_backup(self.server, self.backups, "backup-one")
        self.assertEqual(created["files"], 2)
        (self.server / "config" / "server.properties").write_text("motd=changed\n", encoding="utf-8")
        (self.server / "new.txt").write_text("remove me", encoding="utf-8")
        restored = backup_manager.restore_backup(self.server, created["filename"], created["sha256"], self.backups)
        self.assertTrue(restored["restored"])
        self.assertEqual((self.server / "config" / "server.properties").read_text(encoding="utf-8"), "motd=original\n")
        self.assertFalse((self.server / "new.txt").exists())
        self.assertEqual((self.server / "world.dat").read_bytes(), b"world-data")

    def test_restore_refuses_checksum_mismatch_without_changing_server(self):
        created = backup_manager.create_backup(self.server, self.backups, "backup-two")
        (self.server / "world.dat").write_bytes(b"current")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            backup_manager.restore_backup(self.server, created["filename"], "0" * 64, self.backups)
        self.assertEqual((self.server / "world.dat").read_bytes(), b"current")

    def test_restore_rejects_path_traversal_archive(self):
        self.backups.mkdir(parents=True, exist_ok=True)
        bad = self.backups / "malicious.zip"
        with zipfile.ZipFile(bad, "w") as archive:
            archive.writestr("../escaped.txt", "unsafe")
        checksum = hashlib.sha256(bad.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "unsafe path"):
            backup_manager.restore_backup(self.server, bad.name, checksum, self.backups)
        self.assertFalse((self.root / "escaped.txt").exists())
        self.assertEqual((self.server / "world.dat").read_bytes(), b"world-data")


if __name__ == "__main__":
    unittest.main()
