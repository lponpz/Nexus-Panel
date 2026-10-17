"""Tests for automatic compatible Modrinth plugin selection and verification."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import runtime_manager

class FakeResponse:
    def __init__(self, payload, url):
        self.payload = payload
        self.url = url
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, size=-1): return self.payload if size < 0 else self.payload[:size]
    def geturl(self): return self.url

class ModrinthInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nexus-modrinth-test-")
        self.root = Path(self.temp.name)
        self.artifact = b"fake-paper-plugin-jar-payload"
        self.sha512 = hashlib.sha512(self.artifact).hexdigest()
        self.bad_hash = False
        self.version_list = [
            {"version_number":"2.0-beta","version_type":"beta","files":[self.file_info()]},
            {"version_number":"1.9.2","version_type":"release","files":[self.file_info()]}
        ]
    def tearDown(self):
        self.temp.cleanup()
    def file_info(self):
        return {"filename":"ExamplePlugin-1.9.2.jar","url":"https://cdn.modrinth.com/data/abc/versions/123/ExamplePlugin.jar",
                "size":len(self.artifact),"primary":True,"hashes":{"sha512":("0"*128 if self.bad_hash else self.sha512)}}
    def fake_urlopen(self, request, timeout=0):
        url = request.full_url if hasattr(request,"full_url") else str(request)
        if url.startswith("https://api.modrinth.com/v2/search?"):
            body = json.dumps({"hits":[{"project_type":"plugin","slug":"ExamplePlugin","title":"Example Plugin"}]}).encode()
            return FakeResponse(body,"https://api.modrinth.com/v2/search")
        if url.startswith("https://api.modrinth.com/v2/project/ExamplePlugin/version?"):
            body = json.dumps(self.version_list).encode()
            return FakeResponse(body,"https://api.modrinth.com/v2/project/ExamplePlugin/version")
        if url.startswith("https://cdn.modrinth.com/"):
            return FakeResponse(self.artifact,url)
        raise AssertionError("Unexpected URL: "+url)
    def test_installs_latest_stable_compatible_plugin_and_verifies_hash(self):
        with patch.object(runtime_manager.urllib.request,"urlopen",side_effect=self.fake_urlopen):
            result = runtime_manager.install_modrinth_plugin(self.root,"Example Plugin","1.21.11")
        self.assertEqual(result["version"],"1.9.2")
        self.assertEqual(result["game_version"],"1.21.11")
        self.assertEqual((self.root/"plugins"/"ExamplePlugin-1.9.2.jar").read_bytes(),self.artifact)
        self.assertEqual(result["sha512"],self.sha512)
    def test_checksum_mismatch_discards_plugin(self):
        self.bad_hash = True
        self.version_list = [{"version_number":"1.9.2","version_type":"release","files":[self.file_info()]}]
        with patch.object(runtime_manager.urllib.request,"urlopen",side_effect=self.fake_urlopen):
            with self.assertRaisesRegex(ValueError,"SHA-512 verification failed"):
                runtime_manager.install_modrinth_plugin(self.root,"Example Plugin","1.21.11")
        self.assertFalse((self.root/"plugins"/"ExamplePlugin-1.9.2.jar").exists())
        self.assertEqual(list((self.root/"plugins").iterdir()),[])
    def fake_mod_urlopen(self, request, timeout=0):
        url = request.full_url if hasattr(request,"full_url") else str(request)
        if url.startswith("https://api.modrinth.com/v2/search?"):
            body = json.dumps({"hits":[{"project_type":"mod","slug":"ExampleMod","title":"Example Mod"}]}).encode()
            return FakeResponse(body,"https://api.modrinth.com/v2/search")
        if url.startswith("https://api.modrinth.com/v2/project/ExampleMod/version?"):
            body = json.dumps([{"version_number":"1.9.2","version_type":"release","files":[self.file_info()]}]).encode()
            return FakeResponse(body,"https://api.modrinth.com/v2/project/ExampleMod/version")
        if url.startswith("https://cdn.modrinth.com/"):
            return FakeResponse(self.artifact,url)
        raise AssertionError("Unexpected URL: "+url)
    def test_installs_compatible_fabric_mod(self):
        with patch.object(runtime_manager.urllib.request,"urlopen",side_effect=self.fake_mod_urlopen):
            result=runtime_manager.install_modrinth_mod(self.root,"Example Mod","1.21.11")
        self.assertEqual(result["version"],"1.9.2")
        self.assertEqual((self.root/"mods"/"ExamplePlugin-1.9.2.jar").read_bytes(),self.artifact)
    def test_refuses_unknown_game_version_before_network(self):
        with patch.object(runtime_manager.urllib.request,"urlopen") as urlopen:
            with self.assertRaisesRegex(ValueError,"could not detect"):
                runtime_manager.install_modrinth_plugin(self.root,"Example Plugin",None)
            urlopen.assert_not_called()
    def test_refuses_overwrite_existing_plugin(self):
        target=self.root/"plugins"/"ExamplePlugin-1.9.2.jar"
        target.parent.mkdir(); target.write_bytes(b"existing")
        with patch.object(runtime_manager.urllib.request,"urlopen",side_effect=self.fake_urlopen):
            with self.assertRaisesRegex(ValueError,"already exists"):
                runtime_manager.install_modrinth_plugin(self.root,"Example Plugin","1.21.11")
        self.assertEqual(target.read_bytes(),b"existing")

if __name__=="__main__": unittest.main()
