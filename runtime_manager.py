"""Local per-server process manager for Nexus Panel.

This development adapter launches Java game servers only. Run Nexus on a trusted,
private host; this module is not a security boundary for a public multi-user panel.
"""
from __future__ import annotations
import shlex
import subprocess
import threading
import hashlib
import json
import os
import re
import tempfile
import urllib.request
from urllib.parse import urlparse
from collections import deque
from pathlib import Path
from datetime import datetime, timezone

_LOCK = threading.RLock()
_PROCESSES = {}
_LOG_LIMIT = 500


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _paper_json(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "fill.papermc.io":
        raise ValueError("Refusing to contact an untrusted Paper metadata URL.")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "NexusPanel/0.1 (https://github.com/lponpz/Nexus-Panel)", "Accept": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if urlparse(response.geturl()).hostname != "fill.papermc.io":
            raise ValueError("Paper metadata redirected to an untrusted host.")
        payload = response.read(2_000_000)
    data = json.loads(payload.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Paper metadata response was invalid.")
    return data


def install_paper(directory, version="latest"):
    """Download the latest stable Paper build and verify its SHA-256 before atomic install."""
    root = Path(directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise ValueError("Server folder cannot be a symbolic link.")
    jar = root / "server.jar"
    if jar.exists():
        raise ValueError("server.jar already exists. Move or delete it before installing Paper.")
    if version != "latest" and not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", str(version)):
        raise ValueError("Choose 'latest' or a Minecraft version such as 1.21.11.")
    if version == "latest":
        catalog = _paper_json("https://fill.papermc.io/v3/projects/paper/versions")
        versions = catalog.get("versions", [])
        ids = []
        for entry in versions:
            if isinstance(entry, dict):
                item = entry.get("version", {})
                candidate = item.get("id") if isinstance(item, dict) else None
                if isinstance(candidate, str) and re.fullmatch(r"\d+\.\d+(?:\.\d+)?", candidate):
                    ids.append(candidate)
        if not ids:
            raise RuntimeError("Paper did not return any supported Minecraft versions.")
        version = ids[0]
    metadata = _paper_json("https://fill.papermc.io/v3/projects/paper/versions/" + version + "/builds/latest")
    if str(metadata.get("channel", "")).upper() != "STABLE":
        raise RuntimeError("Paper API did not return a stable build; refusing unstable builds.")
    download = metadata.get("downloads", {}).get("server:default", {})
    url = download.get("url", "")
    checksum = download.get("checksums", {}).get("sha256", "")
    name = download.get("name", "")
    size = download.get("size")
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "fill-data.papermc.io":
        raise ValueError("Paper returned an untrusted download URL.")
    if not isinstance(name, str) or not name.endswith(".jar") or "/" in name or "\\" in name:
        raise ValueError("Paper returned an invalid artifact name.")
    if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", checksum):
        raise ValueError("Paper did not provide a valid SHA-256 checksum.")
    if not isinstance(size, int) or size < 1 or size > 100 * 1024 * 1024:
        raise ValueError("Paper artifact size is missing or exceeds the 100 MB limit.")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "NexusPanel/0.1 (https://github.com/lponpz/Nexus-Panel)"}
    )
    temporary_path = None
    digest = hashlib.sha256()
    received = 0
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            final_host = urlparse(response.geturl()).hostname
            if final_host != "fill-data.papermc.io":
                raise ValueError("Paper download redirected to an untrusted host.")
            with tempfile.NamedTemporaryFile(prefix=".nexus-paper-", suffix=".tmp", dir=str(root), delete=False) as tmp:
                temporary_path = Path(tmp.name)
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > size or received > 100 * 1024 * 1024:
                        raise RuntimeError("Paper download exceeded the expected artifact size.")
                    digest.update(chunk)
                    tmp.write(chunk)
        if received != size:
            raise RuntimeError("Paper download size did not match its published metadata.")
        if digest.hexdigest().lower() != checksum.lower():
            raise RuntimeError("Paper SHA-256 verification failed; the downloaded file was discarded.")
        os.replace(str(temporary_path), str(jar))
        temporary_path = None
        return {"installed": True, "game": "Minecraft", "software": "Paper", "version": version,
                "build": metadata.get("id"), "file": "server.jar", "size": received, "sha256": digest.hexdigest()}
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def _validate(command):
    if not isinstance(command, str) or not command.strip() or len(command) > 500:
        raise ValueError("Enter a launch command under 500 characters.")
    if any(ch in command for ch in (";", "|", "&", ">", "<", chr(96), "$", "\n", "\r")):
        raise ValueError("Launch command cannot contain shell operators.")
    try:
        args = shlex.split(command)
    except ValueError:
        raise ValueError("Launch command quoting is invalid.")
    if not args or Path(args[0]).name not in ("java", "java.exe"):
        raise ValueError("Only Java server processes can be launched by this adapter.")
    if any(arg.startswith(("/", "~")) for arg in args[1:]):
        raise ValueError("Use paths relative to the server folder.")
    return args


def _reader(server_id, process):
    for line in iter(process.stdout.readline, ""):
        with _LOCK:
            item = _PROCESSES.get(server_id)
            if item:
                item["logs"].append({"time": _now(), "stream": "output", "text": line.rstrip()[:4000]})
    with _LOCK:
        item = _PROCESSES.get(server_id)
        if item:
            item["logs"].append({"time": _now(), "stream": "system", "text": "Process exited with code " + str(process.poll())})


def start(server_id, directory, command):
    args = _validate(command)
    root = Path(directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if not (root / "server.jar").is_file():
        raise ValueError("server.jar not found. Upload a Java server JAR in the Files tab first.")
    with _LOCK:
        old = _PROCESSES.get(server_id)
        if old and old["process"].poll() is None:
            raise RuntimeError("Server is already running.")
        try:
            process = subprocess.Popen(args, cwd=str(root), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, bufsize=1, shell=False)
        except FileNotFoundError:
            raise RuntimeError("Java was not found on this host.")
        _PROCESSES[server_id] = {"process": process, "logs": deque(maxlen=_LOG_LIMIT), "started_at": _now()}
        threading.Thread(target=_reader, args=(server_id, process), daemon=True).start()
        return snapshot(server_id)


def snapshot(server_id):
    with _LOCK:
        item = _PROCESSES.get(server_id)
        if not item:
            return {"running": False, "pid": None}
        return {"running": item["process"].poll() is None, "pid": item["process"].pid, "started_at": item["started_at"]}


def logs(server_id):
    with _LOCK:
        item = _PROCESSES.get(server_id)
        return {"running": bool(item and item["process"].poll() is None), "logs": list(item["logs"]) if item else []}


def command(server_id, text):
    text = str(text).strip()
    if not text or len(text) > 1000 or any(ord(ch) < 32 and ch != "\t" for ch in text):
        raise ValueError("Console command must be 1–1000 characters.")
    with _LOCK:
        item = _PROCESSES.get(server_id)
        if not item or item["process"].poll() is not None:
            raise RuntimeError("Start the server before sending console commands.")
        try:
            item["process"].stdin.write(text + "\n")
            item["process"].stdin.flush()
        except (BrokenPipeError, OSError):
            raise RuntimeError("Console input is no longer available.")
        item["logs"].append({"time": _now(), "stream": "input", "text": "> " + text})
    return {"ok": True}


def stop(server_id):
    with _LOCK:
        item = _PROCESSES.get(server_id)
        if not item or item["process"].poll() is not None:
            raise RuntimeError("No running process is managed by this Nexus process.")
        process = item["process"]
        try:
            process.stdin.write("stop\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    return {"running": False, "pid": process.pid}


def server_path(directory, relative=""):
    root = Path(directory).resolve()
    if "\\" in relative or relative.startswith("/"):
        raise ValueError("Use a relative path inside the server folder.")
    target = (root / relative).resolve()
    if target != root and root not in target.parents:
        raise ValueError("Path must stay inside this server folder.")
    return target


def list_files(directory, relative=""):
    folder = server_path(directory, relative)
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for item in sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if item.is_symlink():
            continue
        rows.append({"name": item.name, "directory": item.is_dir(), "size": item.stat().st_size if item.is_file() else None})
    return {"path": relative, "items": rows}


def change_file(directory, operation, relative, content=""):
    target = server_path(directory, relative)
    if operation == "mkdir":
        target.mkdir(parents=False, exist_ok=False)
    elif operation == "write":
        if not isinstance(content, str) or len(content.encode("utf-8")) > 1_000_000:
            raise ValueError("Text file content must be under 1 MB.")
        if target.is_symlink():
            raise ValueError("Symbolic links are not editable.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    elif operation == "delete":
        if target == Path(directory).resolve():
            raise ValueError("Cannot delete the server root.")
        if target.is_symlink():
            raise ValueError("Symbolic links cannot be deleted from this view.")
        if target.is_dir():
            import shutil
            shutil.rmtree(target)
        elif target.is_file():
            target.unlink()
        else:
            raise ValueError("File not found.")
    else:
        raise ValueError("Unsupported file operation.")
    return {"path": relative}
