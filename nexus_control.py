#!/usr/bin/env python3
"""Nexus Builder & Control Center — local-only source package manager."""
from __future__ import annotations
import argparse, http.server, json, os, shutil, subprocess, tempfile, threading, time, zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = int(os.environ.get("NEXUS_CONTROL_PORT", "8765"))
OUT = ROOT / "dist"
PAGE = ROOT / "nexus-control.html"
EXCLUDES = {".git", ".venv", "venv", "__pycache__", "data", "dist", "node_modules", ".pytest_cache"}

def build_zip():
    OUT.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = OUT / f"nexus-panel-{stamp}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in ROOT.rglob("*"):
            rel = p.relative_to(ROOT)
            if any(part in EXCLUDES for part in rel.parts) or p.name in {".env", ".env.local"}:
                continue
            if p.is_file() and not p.is_symlink():
                z.write(p, rel.as_posix())
    return target

def update_repo():
    if not (ROOT / ".git").is_dir():
        raise RuntimeError("This folder is not a Git checkout; update is unavailable.")
    status = subprocess.run(["git","status","--porcelain"], cwd=ROOT, text=True, capture_output=True)
    if status.returncode or status.stdout.strip():
        raise RuntimeError("Update stopped: working tree has local changes. Commit or back them up first.")
    branch = subprocess.run(["git","branch","--show-current"], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip()
    subprocess.run(["git","fetch","origin",branch], cwd=ROOT, check=True, timeout=120)
    subprocess.run(["git","pull","--ff-only","origin",branch], cwd=ROOT, check=True, timeout=120)
    return "Updated branch " + branch

def safe_delete(confirmation):
    if confirmation != "BACKUP AND DELETE NEXUS SOURCE":
        raise RuntimeError("Confirmation text did not match.")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = ROOT.parent / (ROOT.name + "-backup-" + stamp + ".zip")
    with zipfile.ZipFile(backup, "w", zipfile.ZIP_DEFLATED) as z:
        for p in ROOT.rglob("*"):
            rel = p.relative_to(ROOT)
            if ".git" in rel.parts or p.is_symlink():
                continue
            if p.is_file():
                z.write(p, rel.as_posix())
    # Remove source only after a complete backup has been written.
    for p in sorted(ROOT.rglob("*"), reverse=True):
        if p.is_file() or p.is_symlink():
            p.unlink(missing_ok=True)
        elif p.is_dir():
            try: p.rmdir()
            except OSError: pass
    return str(backup)

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): print("[Nexus Control] " + (fmt % args))
    def send_json(self, code, data):
        body=json.dumps(data).encode()
        self.send_response(code); self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(body))); self.send_header("Cache-Control","no-store")
        self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        path=urlparse(self.path).path
        if path in ("/","/index.html"):
            try: body=PAGE.read_bytes()
            except OSError: body=b"Nexus Control UI missing."
            self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8")
            self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path.startswith("/download/"):
            name=Path(path).name
            file=(OUT/name).resolve()
            if file.parent != OUT.resolve() or not file.is_file(): return self.send_error(404)
            body=file.read_bytes(); self.send_response(200); self.send_header("Content-Type","application/zip")
            self.send_header("Content-Disposition",f'attachment; filename="{name}"')
            self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
        self.send_error(404)
    def do_POST(self):
        try:
            size=int(self.headers.get("Content-Length","0"))
            if size>4096: return self.send_json(413,{"ok":False,"error":"Request too large"})
            data=json.loads(self.rfile.read(size) or b"{}")
            path=urlparse(self.path).path
            if path=="/api/build":
                f=build_zip(); return self.send_json(200,{"ok":True,"file":f.name,"download":"/download/"+f.name})
            if path=="/api/update":
                msg=update_repo(); return self.send_json(200,{"ok":True,"message":msg})
            if path=="/api/delete":
                msg=safe_delete(data.get("confirm","")); return self.send_json(200,{"ok":True,"backup":msg})
            if path=="/api/status":
                return self.send_json(200,{"ok":True,"branch":subprocess.run(["git","branch","--show-current"],cwd=ROOT,text=True,capture_output=True).stdout.strip() if (ROOT/".git").exists() else "source archive","panel_url":f"http://127.0.0.1:{os.environ.get('NEXUS_PORT','8000')}/"})
            return self.send_json(404,{"ok":False,"error":"Unknown action"})
        except Exception as e: return self.send_json(400,{"ok":False,"error":str(e)})
    def do_OPTIONS(self):
        self.send_response(204); self.end_headers()

def menu():
    while True:
        print("\n=== NEXUS BUILDER & CONTROL CENTER ===")
        print("[1] Build / Download ZIP\n[2] Update source\n[3] Delete source (backup first)\n[4] Open panel URL\n[5] Open GUI URL\n[6] Exit")
        choice=input("Select option: ").strip().lower()
        try:
            if choice in ("1","a"):
                f=build_zip(); print("Built:",f)
            elif choice=="2": print(update_repo())
            elif choice=="3":
                print("This removes the source checkout only, after making a backup.")
                if input("Type BACKUP AND DELETE NEXUS SOURCE: ").strip()=="BACKUP AND DELETE NEXUS SOURCE":
                    print("Backup created:",safe_delete("BACKUP AND DELETE NEXUS SOURCE")); return
                print("Cancelled.")
            elif choice=="4": print(f"Panel: http://127.0.0.1:{os.environ.get('NEXUS_PORT','8000')}/")
            elif choice=="5": print(f"Control GUI: http://{HOST}:{PORT}/")
            elif choice in ("6","q","quit"): return
            else: print("Unknown option.")
        except Exception as e: print("ERROR:",e)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--gui-only",action="store_true")
    args=parser.parse_args()
    httpd=http.server.ThreadingHTTPServer((HOST,PORT),Handler)
    threading.Thread(target=httpd.serve_forever,daemon=True).start()
    print(f"Nexus Control GUI: http://{HOST}:{PORT}/ (local machine only)")
    if not args.gui_only: menu()
    else:
        try:
            while True: time.sleep(3600)
        except KeyboardInterrupt: pass
    httpd.shutdown()

if __name__=="__main__": main()
