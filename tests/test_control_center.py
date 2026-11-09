"""Tests for the local Nexus Builder & Control Center."""
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import nexus_control


class NexusControlTests(unittest.TestCase):
    def test_build_zip_excludes_local_state_and_environment_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("source")
            (root / ".env").write_text("SECRET=never-package")
            (root / "data").mkdir()
            (root / "data" / "db.sqlite3").write_text("private")
            (root / ".git").mkdir()
            (root / ".git" / "config").write_text("git metadata")
            with patch.object(nexus_control, "ROOT", root), patch.object(nexus_control, "OUT", root / "dist"):
                archive = nexus_control.build_zip()
                with zipfile.ZipFile(archive) as z:
                    names = set(z.namelist())
                self.assertIn("README.md", names)
                self.assertFalse(any(name.startswith("data/") for name in names))
                self.assertFalse(any(name.startswith(".git/") for name in names))
                self.assertNotIn(".env", names)

    def test_update_refuses_non_git_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(nexus_control, "ROOT", Path(tmp)):
                with self.assertRaisesRegex(RuntimeError, "not a Git checkout"):
                    nexus_control.update_repo()

    def test_delete_requires_exact_confirmation_and_makes_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            (root / "README.md").write_text("keep in backup")
            with patch.object(nexus_control, "ROOT", root):
                with self.assertRaisesRegex(RuntimeError, "Confirmation text"):
                    nexus_control.safe_delete("no")
                backup = Path(nexus_control.safe_delete("BACKUP AND DELETE NEXUS SOURCE"))
                self.assertTrue(backup.is_file())
                with zipfile.ZipFile(backup) as z:
                    self.assertIn("README.md", z.namelist())
                self.assertFalse(root.exists())


if __name__ == "__main__":
    unittest.main()
