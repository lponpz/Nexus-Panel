"""Tests for official Fabric server launcher selection and download handling."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import runtime_manager

class FakeResponse:
    def __init__(self,payload,url): self.payload,self.url=payload,url
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def read(self,size=-1): return self.payload if size<0 else self.payload[:size]
    def geturl(self): return self.url

class FabricInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="nexus-fabric-test-")
        self.root=Path(self.temp.name)
        self.jar=b"F"*100_000
        self.redirect_to="https://meta.fabricmc.net/v2/versions/loader/1.21.11/0.18.4/1.0.3/server/jar"
    def tearDown(self): self.temp.cleanup()
    def fake_urlopen(self,request,timeout=0):
        url=request.full_url if hasattr(request,"full_url") else str(request)
        if url=="https://meta.fabricmc.net/v2/versions/game":
            return FakeResponse(json.dumps([
                {"version":"26.1","stable":True},{"version":"1.21.11","stable":True},{"version":"1.21.10","stable":False}
            ]).encode(),url)
        if url=="https://meta.fabricmc.net/v2/versions/loader/1.21.11":
            return FakeResponse(json.dumps([
                {"loader":{"version":"0.18.4","stable":True}},{"loader":{"version":"0.19-beta","stable":False}}
            ]).encode(),url)
        if url=="https://meta.fabricmc.net/v2/versions/installer":
            return FakeResponse(json.dumps([
                {"version":"1.0.3","stable":True},{"version":"1.1-beta","stable":False}
            ]).encode(),url)
        if url==self.redirect_to:
            return FakeResponse(self.jar,self.redirect_to)
        raise AssertionError("Unexpected URL: "+url)
    def test_selects_latest_game_version_compatible_with_java_and_installs_launcher(self):
        with patch.object(runtime_manager,"_java_major",return_value=21),patch.object(runtime_manager.urllib.request,"urlopen",side_effect=self.fake_urlopen):
            result=runtime_manager.install_fabric_server(self.root,"latest")
        self.assertEqual(result["version"],"1.21.11")
        self.assertEqual(result["loader_version"],"0.18.4")
        self.assertEqual(result["filename"],"fabric-server.jar")
        self.assertEqual((self.root/"fabric-server.jar").read_bytes(),self.jar)
        self.assertEqual(result["launch_command"],"java -Xms1G -Xmx2G -jar fabric-server.jar nogui")
    def test_refuses_to_overwrite_existing_server_jar(self):
        (self.root/"server.jar").write_bytes(b"existing")
        with patch.object(runtime_manager.urllib.request,"urlopen") as urlopen:
            with self.assertRaisesRegex(ValueError,"already exists"):
                runtime_manager.install_fabric_server(self.root,"latest")
            urlopen.assert_not_called()
    def test_rejects_untrusted_download_redirect(self):
        def fake(request,timeout=0):
            response=self.fake_urlopen(request,timeout)
            if (request.full_url if hasattr(request,"full_url") else str(request))==self.redirect_to:
                return FakeResponse(self.jar,"https://attacker.example/file.jar")
            return response
        with patch.object(runtime_manager,"_java_major",return_value=21),patch.object(runtime_manager.urllib.request,"urlopen",side_effect=fake):
            with self.assertRaisesRegex(ValueError,"untrusted host"):
                runtime_manager.install_fabric_server(self.root,"latest")
        self.assertFalse((self.root/"fabric-server.jar").exists())

if __name__=="__main__": unittest.main()
