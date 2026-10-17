"""Unit tests for safe Paper download resolution and checksum verification."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import runtime_manager


class FakeResponse:
    def __init__(self, payload, url):
        self.payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.url = url
        self.offset = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def geturl(self):
        return self.url

    def read(self, size=-1):
        if size is None or size < 0:
            size = len(self.payload) - self.offset
        chunk = self.payload[self.offset:self.offset + size]
        self.offset += len(chunk)
        return chunk


class PaperInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nexus-paper-test-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def responses(self, payload, checksum=None, size=None):
        checksum = checksum or hashlib.sha256(payload).hexdigest()
        size = len(payload) if size is None else size
        return [
            FakeResponse({"versions": [
                {"version": {"id": "26.3", "java": {"version": {"minimum": 25}}, "support": {"status": "SUPPORTED"}}},
                {"version": {"id": "1.21.11", "java": {"version": {"minimum": 21}}, "support": {"status": "SUPPORTED"}}}
            ]}, "https://fill.papermc.io/v3/projects/paper/versions"),
            FakeResponse([{
                "id": 123,
                "channel": "STABLE",
                "downloads": {"server:default": {
                    "name": "paper-1.21.11-123.jar",
                    "url": "https://fill-data.papermc.io/v1/objects/test/paper-1.21.11-123.jar",
                    "checksums": {"sha256": checksum},
                    "size": size
                }}
            }], "https://fill.papermc.io/v3/projects/paper/versions/1.21.11/builds?channel=STABLE"),
            FakeResponse(payload, "https://fill-data.papermc.io/v1/objects/test/paper-1.21.11-123.jar")
        ]

    def test_installs_latest_stable_paper_and_verifies_hash(self):
        payload = b"paper-jar-test-content"
        with patch("runtime_manager._java_major", return_value=21), patch("runtime_manager.urllib.request.urlopen", side_effect=self.responses(payload)):
            result = runtime_manager.install_paper(self.root, "latest")
        self.assertEqual(result["version"], "1.21.11")
        self.assertTrue(result["installed"])
        self.assertEqual((self.root / "server.jar").read_bytes(), payload)
        self.assertEqual(result["sha256"], hashlib.sha256(payload).hexdigest())

    def test_checksum_mismatch_discards_download(self):
        payload = b"unexpected content"
        wrong_hash = "0" * 64
        with patch("runtime_manager._java_major", return_value=21), patch("runtime_manager.urllib.request.urlopen", side_effect=self.responses(payload, checksum=wrong_hash)):
            with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                runtime_manager.install_paper(self.root, "latest")
        self.assertFalse((self.root / "server.jar").exists())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_refuses_to_overwrite_existing_server_jar(self):
        (self.root / "server.jar").write_bytes(b"keep me")
        with self.assertRaisesRegex(ValueError, "already exists"):
            runtime_manager.install_paper(self.root, "latest")
        self.assertEqual((self.root / "server.jar").read_bytes(), b"keep me")

    def test_rejects_invalid_version_before_network_access(self):
        with patch("runtime_manager.urllib.request.urlopen") as fetch:
            with self.assertRaisesRegex(ValueError, "Minecraft version"):
                runtime_manager.install_paper(self.root, "../../evil")
        fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
