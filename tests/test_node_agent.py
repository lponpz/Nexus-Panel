"""Integration test for the persistent local node-agent process boundary."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from urllib.request import Request, urlopen
from unittest.mock import patch
import secrets
import runtime_manager

ROOT=Path(__file__).resolve().parents[1]

class NodeAgentIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="nexus-agent-test-")
        self.root=Path(self.temp.name)
        self.servers=self.root/"servers"; self.servers.mkdir()
        self.server_id=str(uuid.uuid4())
        self.server_dir=self.servers/self.server_id; self.server_dir.mkdir()
        (self.server_dir/"server.jar").write_bytes(b"fake server jar")
        bind=socket.socket();bind.bind(("127.0.0.1",0));self.port=bind.getsockname()[1];bind.close()
        self.token=secrets.token_urlsafe(48)
        self.bin=self.root/"bin";self.bin.mkdir()
        java=self.bin/"java"
        java.write_text("#!/usr/bin/env python3\nimport sys\nprint('agent-java-started',flush=True)\nfor line in sys.stdin:\n print('agent-input:'+line.strip(),flush=True)\n if line.strip()=='stop': break\n",encoding="utf-8")
        java.chmod(0o755)
        self.env=os.environ.copy()
        self.env.update({"NEXUS_DATA_DIR":str(self.root),"NEXUS_NODE_AGENT_PORT":str(self.port),
                         "NEXUS_NODE_AGENT_TOKEN":self.token,"NEXUS_NODE_AGENT_MODE":"1",
                         "PATH":str(self.bin)+os.pathsep+os.environ.get("PATH","")})
        self.proc=subprocess.Popen([sys.executable,str(ROOT/"node_agent.py")],cwd=str(ROOT),env=self.env,
                                   stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                                   start_new_session=True)
        self.base="http://127.0.0.1:"+str(self.port)
        deadline=time.time()+6
        while time.time()<deadline:
            try:
                req=Request(self.base+"/health",headers={"X-Nexus-Node-Token":self.token})
                with urlopen(req,timeout=0.3) as response:
                    if response.status==200: break
            except Exception:
                time.sleep(0.05)
        else:
            self.proc.terminate()
            raise RuntimeError("Node agent did not start for integration test.")
        os.environ["NEXUS_NODE_AGENT_URL"]=self.base
        os.environ["NEXUS_NODE_AGENT_TOKEN"]=self.token
        os.environ.pop("NEXUS_NODE_AGENT_MODE",None)
    def tearDown(self):
        for key in ("NEXUS_NODE_AGENT_URL","NEXUS_NODE_AGENT_TOKEN","NEXUS_NODE_AGENT_MODE"):
            if key in self.env: os.environ[key]=self.env[key]
            else: os.environ.pop(key,None)
        if self.proc.poll() is None:
            self.proc.terminate()
            try: self.proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                self.proc.kill();self.proc.wait(timeout=3)
        self.temp.cleanup()
    def test_process_control_is_proxied_to_separate_agent(self):
        result=runtime_manager.start(self.server_id,self.server_dir,"java -Xms1G -Xmx2G -jar server.jar nogui")
        self.assertTrue(result["running"])
        runtime_manager.command(self.server_id,"say persistent")
        deadline=time.time()+3
        result=runtime_manager.logs(self.server_id)
        while time.time()<deadline and not any("agent-input:say persistent" in item["text"] for item in result["logs"]):
            time.sleep(0.03);result=runtime_manager.logs(self.server_id)
        self.assertTrue(any("agent-java-started" in item["text"] for item in result["logs"]))
        self.assertTrue(any("agent-input:say persistent" in item["text"] for item in result["logs"]))
        stopped=runtime_manager.stop(self.server_id)
        self.assertFalse(stopped["running"])
        self.assertFalse(runtime_manager.snapshot(self.server_id)["running"])
    def test_agent_rejects_missing_authentication_token(self):
        req=Request(self.base+"/health")
        with self.assertRaises(Exception):
            urlopen(req,timeout=2)

if __name__=="__main__":unittest.main()
