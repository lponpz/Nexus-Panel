"""Integration tests for hosting plan and invoice workflows."""
import json, os, tempfile, threading, unittest, urllib.error, urllib.request
from http.server import ThreadingHTTPServer

TEMP = tempfile.TemporaryDirectory(prefix="nexus-billing-tests-")
os.environ["NEXUS_DATA_DIR"] = TEMP.name
os.environ["NEXUS_PORT"] = "0"
import server
server.init_db()
HTTPD = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
threading.Thread(target=HTTPD.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:" + str(HTTPD.server_address[1])
ORIGIN = BASE

def request(path, method="GET", payload=None, cookie=None, csrf=None):
    body = None if payload is None else json.dumps(payload).encode()
    headers = {"Origin": ORIGIN}
    if body is not None: headers["Content-Type"] = "application/json"
    if cookie: headers["Cookie"] = cookie.split(";",1)[0]
    if csrf: headers["X-Nexus-CSRF"] = csrf
    req = urllib.request.Request(BASE+path,data=body,headers=headers,method=method)
    try:
        with urllib.request.urlopen(req,timeout=3) as r: return r.status,r.headers,json.loads(r.read().decode())
    except urllib.error.HTTPError as e: return e.code,e.headers,json.loads(e.read().decode())

class BillingTests(unittest.TestCase):
    def setUp(self):
        with server.DB_LOCK, server.connect_db() as db:
            for t in ("sessions","billing_invoices","billing_plans","users","servers","server_runtime","connectors","activities","settings"):
                db.execute("DELETE FROM "+t)
        status, headers, data = request("/api/setup","POST",{"workspace_name":"Billing Test","username":"bill-owner","password":"long-enough-owner-password"})
        self.assertEqual(status,200,data)
        self.cookie=headers.get("Set-Cookie"); self.csrf=data["csrf_token"]
    def create_plan(self):
        payload={"name":"Starter","description":"Small server","currency":"PKR","price_minor":50000,"billing_interval":"month","ram_mb":2048,"cpu_percent":100,"disk_mb":10240,"server_limit":1}
        status,_,data=request("/api/billing/plans","POST",payload,self.cookie,self.csrf)
        self.assertEqual(status,201,data)
        return data["item"]
    def test_plan_create_list_disable(self):
        plan=self.create_plan()
        status,_,data=request("/api/billing/plans",cookie=self.cookie)
        self.assertEqual(status,200); self.assertEqual(data["items"][0]["id"],plan["id"])
        status,_,data=request("/api/billing-plans/"+plan["id"],"DELETE",{},self.cookie,self.csrf)
        self.assertEqual(status,200,data)
        status,_,data=request("/api/billing/plans",cookie=self.cookie)
        self.assertEqual(data["items"][0]["enabled"],0)
    def test_invoice_snapshot_and_manual_payment_idempotency(self):
        plan=self.create_plan()
        status,_,data=request("/api/billing/invoices","POST",{"plan_id":plan["id"],"customer_name":"Test Customer","customer_email":"customer@example.com"},self.cookie,self.csrf)
        self.assertEqual(status,201,data)
        invoice=data["item"]; self.assertEqual(invoice["amount_minor"],50000); self.assertEqual(invoice["status"],"pending")
        status,_,paid=request("/api/billing/invoices/"+invoice["id"]+"/record-payment","POST",{"payment_reference":"receipt-123","notes":"Verified offline"},self.cookie,self.csrf)
        self.assertEqual(status,200,paid); self.assertTrue(paid["manual_record_only"]); self.assertEqual(paid["item"]["status"],"paid")
        status,_,duplicate=request("/api/billing/invoices/"+invoice["id"]+"/record-payment","POST",{"payment_reference":"receipt-123"},self.cookie,self.csrf)
        self.assertEqual(status,409)
    def test_invoice_requires_valid_customer_and_enabled_plan(self):
        plan=self.create_plan()
        status,_,data=request("/api/billing/invoices","POST",{"plan_id":plan["id"],"customer_name":"Customer","customer_email":"not-an-email"},self.cookie,self.csrf)
        self.assertEqual(status,400)
        status,_,data=request("/api/billing/invoices","POST",{"plan_id":"missing","customer_name":"Customer","customer_email":"a@example.com"},self.cookie,self.csrf)
        self.assertEqual(status,404)

if __name__ == "__main__":
    try: unittest.main()
    finally: HTTPD.shutdown(); HTTPD.server_close(); TEMP.cleanup()
