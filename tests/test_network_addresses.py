"""Integration tests for Minecraft connection address and port allocation."""
import json, os, tempfile, threading, unittest, urllib.error, urllib.request
from http.server import ThreadingHTTPServer

TEMP = tempfile.TemporaryDirectory(prefix="nexus-network-tests-")
os.environ["NEXUS_DATA_DIR"] = TEMP.name
os.environ["NEXUS_PORT"] = "0"
os.environ["NEXUS_MINECRAFT_PORT_START"] = "28120"
os.environ["NEXUS_MINECRAFT_PORT_END"] = "28130"
import server
server.init_db()
HTTPD = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
threading.Thread(target=HTTPD.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:" + str(HTTPD.server_address[1])

def request(path, method="GET", payload=None, cookie=None, csrf=None):
    body = None if payload is None else json.dumps(payload).encode()
    headers={"Origin":BASE}
    if body is not None: headers["Content-Type"]="application/json"
    if cookie: headers["Cookie"]=cookie.split(";",1)[0]
    if csrf: headers["X-Nexus-CSRF"]=csrf
    req=urllib.request.Request(BASE+path,data=body,headers=headers,method=method)
    try:
        with urllib.request.urlopen(req,timeout=3) as r: return r.status,r.headers,json.loads(r.read().decode())
    except urllib.error.HTTPError as e: return e.code,e.headers,json.loads(e.read().decode())

class NetworkAddressTests(unittest.TestCase):
    def setUp(self):
        with server.DB_LOCK, server.connect_db() as db:
            for t in ("sessions","server_ports","servers","server_runtime","users","activities","settings"):
                db.execute("DELETE FROM "+t)
        status,headers,data=request("/api/setup","POST",{"workspace_name":"Network Test","username":"net-owner","password":"long-enough-owner-password"})
        self.assertEqual(status,200,data)
        self.cookie=headers.get("Set-Cookie"); self.csrf=data["csrf_token"]
    def test_unique_minecraft_ports_and_properties(self):
        payload={"name":"Join Test","game":"Minecraft","panel":"Nexus (local)","status":"Configured"}
        status,_,first=request("/api/servers","POST",payload,self.cookie,self.csrf)
        self.assertEqual(status,201,first)
        status,_,second=request("/api/servers","POST",{**payload,"name":"Second Test"},self.cookie,self.csrf)
        self.assertEqual(status,201,second)
        self.assertNotEqual(first["item"]["connect_port"],second["item"]["connect_port"])
        self.assertEqual(first["item"]["connect_address"],"127.0.0.1:"+str(first["item"]["connect_port"]))
        self.assertFalse(first["item"]["public_address_configured"])
        props=(server.SERVERS_DIR/first["item"]["id"]/"server.properties").read_text()
        self.assertIn("server-port="+str(first["item"]["connect_port"]),props)
        self.assertIn("server-ip=",props)
        status,_,data=request("/api/servers",cookie=self.cookie)
        self.assertEqual(status,200)
        self.assertEqual(len([x for x in data["items"] if x["connect_port"]]),2)
    def test_public_host_setting_validation_and_join_address(self):
        status,_,bad=request("/api/network/public-host","POST",{"public_host":"https://example.com"},self.cookie,self.csrf)
        self.assertEqual(status,400,bad)
        status,_,saved=request("/api/network/public-host","POST",{"public_host":"mc.example.com"},self.cookie,self.csrf)
        self.assertEqual(status,200,saved)
        status,_,created=request("/api/servers","POST",{"name":"Public Test","game":"Minecraft","panel":"Nexus (local)","status":"Configured"},self.cookie,self.csrf)
        self.assertEqual(status,201)
        self.assertTrue(created["item"]["public_address_configured"])
        self.assertTrue(created["item"]["connect_address"].startswith("mc.example.com:"))
    def test_live_status_endpoint_reports_offline_server(self):
        status,_,created=request("/api/servers","POST",{"name":"Offline Ping Test","game":"Minecraft","panel":"Nexus (local)","status":"Configured"},self.cookie,self.csrf)
        self.assertEqual(status,201,created)
        status,_,ping=request("/api/servers/"+created["item"]["id"]+"/game-status",cookie=self.cookie)
        self.assertEqual(status,200,ping)
        self.assertTrue(ping["supported"])
        self.assertFalse(ping["online"])
        self.assertEqual(ping["players"],0)

    def test_other_games_do_not_claim_minecraft_port(self):
        status,_,created=request("/api/servers","POST",{"name":"FiveM record","game":"FiveM","panel":"Nexus (local)","status":"Configured"},self.cookie,self.csrf)
        self.assertEqual(status,201)
        self.assertIsNone(created["item"]["connect_port"])
    @classmethod
    def tearDownClass(cls):
        HTTPD.shutdown(); HTTPD.server_close(); TEMP.cleanup()

if __name__=="__main__": unittest.main()
