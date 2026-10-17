"""Local Java runtime manager integration tests using a fake Java executable."""
import os
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
import runtime_manager

class RuntimeManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="nexus-runtime-test-")
        self.root=Path(self.temp.name)
        self.bin=self.root/"bin"; self.bin.mkdir()
        self.fake_java=self.bin/"java"
        self.fake_java.write_text("#!/usr/bin/env python3\nimport sys\nprint('fake-java-started',flush=True)\nfor line in sys.stdin:\n print('stdin:'+line.strip(),flush=True)\n if line.strip()=='stop': break\n",encoding="utf-8")
        self.fake_java.chmod(0o755)
        (self.root/"server.jar").write_bytes(b"fake server jar")
        self.server_id=str(uuid.uuid4())
    def tearDown(self):
        with runtime_manager._LOCK:
            runtime_manager._PROCESSES.pop(self.server_id,None)
        self.temp.cleanup()
    def test_start_command_logs_and_graceful_stop(self):
        env_path=str(self.bin)+os.pathsep+os.environ.get("PATH","")
        with patch.dict(os.environ,{"PATH":env_path}):
            state=runtime_manager.start(self.server_id,self.root,"java -Xms1G -Xmx2G -jar server.jar nogui")
            self.assertTrue(state["running"])
            runtime_manager.command(self.server_id,"say hello")
            deadline=time.time()+3
            current=runtime_manager.logs(self.server_id)
            while time.time()<deadline and not any("stdin:say hello" in x["text"] for x in current["logs"]):
                time.sleep(0.03); current=runtime_manager.logs(self.server_id)
            self.assertTrue(any("fake-java-started" in x["text"] for x in current["logs"]))
            self.assertTrue(any("stdin:say hello" in x["text"] for x in current["logs"]))
            stopped=runtime_manager.stop(self.server_id)
            self.assertFalse(stopped["running"])
            self.assertFalse(runtime_manager.snapshot(self.server_id)["running"])
    def test_refuses_shell_operators_and_missing_jar(self):
        with self.assertRaisesRegex(ValueError,"shell operators"):
            runtime_manager._validate("java -jar server.jar; echo unsafe")
        (self.root/"server.jar").unlink()
        with self.assertRaisesRegex(ValueError,"server.jar not found"):
            runtime_manager.start(self.server_id,self.root,"java -jar server.jar nogui")

if __name__=="__main__": unittest.main()
