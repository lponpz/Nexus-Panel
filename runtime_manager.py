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
    if not isinstance(data, (dict, list)):
        raise ValueError("Paper metadata response was invalid.")
    return data


def _java_major():
    try:
        result = subprocess.run(["java", "-version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError("Java runtime was not found. Install a compatible Java runtime and retry.")
    if result.returncode != 0:
        raise RuntimeError("Java runtime could not start. Install a compatible Java runtime and retry.")
    output = result.stdout or ""
    version_match = re.search(r'version "([^"]+)"', output)
    if version_match:
        version_text = version_match.group(1)
        pieces = version_text.split(".")
        try:
            return int(pieces[1] if pieces[0] == "1" and len(pieces) > 1 else pieces[0])
        except ValueError:
            pass
    openjdk_match = re.search(r"openjdk (\\d+)", output, re.IGNORECASE)
    if openjdk_match:
        return int(openjdk_match.group(1))
    raise RuntimeError("Could not determine the installed Java version.")


def _paper_versions():
    catalog = _paper_json("https://fill.papermc.io/v3/projects/paper/versions")
    entries = catalog.get("versions", []) if isinstance(catalog, dict) else []
    result = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        item = entry.get("version", {})
        if not isinstance(item, dict):
            continue
        candidate = item.get("id")
        if not isinstance(candidate, str) or not re.fullmatch(r"\\d+\\.\\d+(?:\\.\\d+)?", candidate):
            continue
        java_info = item.get("java", {})
        java_version = java_info.get("version", {}) if isinstance(java_info, dict) else {}
        minimum_java = java_version.get("minimum", 21) if isinstance(java_version, dict) else 21
        try:
            minimum_java = int(minimum_java)
        except (ValueError, TypeError):
            minimum_java = 21
        support_info = item.get("support", {})
        support_status = support_info.get("status", "") if isinstance(support_info, dict) else ""
        result.append({"id": candidate, "minimum_java": minimum_java, "support": str(support_status).upper()})
    return result


def install_paper(directory, version="latest"):
    """Install the newest compatible stable Paper build, verifying SHA-256 before atomic replacement."""
    root = Path(directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise ValueError("Server folder cannot be a symbolic link.")
    jar = root / "server.jar"
    if jar.exists():
        raise ValueError("server.jar already exists. Move or delete it before installing Paper.")
    if version != "latest" and not re.fullmatch(r"\\d+\\.\\d+(?:\\.\\d+)?", str(version)):
        raise ValueError("Choose 'latest' or a Minecraft version such as 1.21.11.")
    java_major = _java_major()
    versions = _paper_versions()
    if version == "latest":
        compatible = [v for v in versions if v["minimum_java"] <= java_major]
        supported = [v for v in compatible if v["support"] in ("SUPPORTED", "SUPPORTING", "")]
        choices = supported or compatible
        if not choices:
            required = min((v["minimum_java"] for v in versions), default=21)
            raise RuntimeError("No listed Paper release supports Java " + str(java_major) + ". Install Java " + str(required) + " or newer.")
        version_info = choices[0]
        version = version_info["id"]
    else:
        version_info = next((v for v in versions if v["id"] == version), None)
        if version_info is None:
            raise ValueError("Paper did not list Minecraft version " + version + ". Check the version and try again.")
        if version_info["minimum_java"] > java_major:
            raise RuntimeError("Paper " + version + " requires Java " + str(version_info["minimum_java"]) + " or newer; this host has Java " + str(java_major) + ".")

    builds_url = "https://fill.papermc.io/v3/projects/paper/versions/" + version + "/builds?channel=STABLE"
    builds = _paper_json(builds_url)
    if isinstance(builds, dict):
        builds = builds.get("builds", [])
    if not isinstance(builds, list):
        raise RuntimeError("Paper returned an invalid stable-build list.")
    stable_builds = [item for item in builds if isinstance(item, dict) and str(item.get("channel", "")).upper() == "STABLE"]
    if not stable_builds:
        raise RuntimeError("No stable Paper build is available for Minecraft " + version + ".")
    metadata = stable_builds[0]
    download = metadata.get("downloads", {}).get("server:default", {})
    url = download.get("url", "")
    checksum = download.get("checksums", {}).get("sha256", "")
    name = download.get("name", "")
    size = download.get("size")
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "fill-data.papermc.io":
        raise ValueError("Paper returned an untrusted download URL.")
    if not isinstance(name, str) or not name.endswith(".jar") or "/" in name or "\\\\" in name:
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
                "build": metadata.get("id"), "java_major": java_major, "file": "server.jar",
                "size": received, "sha256": digest.hexdigest()}
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


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
