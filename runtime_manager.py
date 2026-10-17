"""Local per-server process manager for Nexus Panel.

This development adapter launches Java game servers only. Run Nexus on a trusted,
private host; this module is not a security boundary for a public multi-user panel.
"""
from __future__ import annotations
import shlex
import subprocess
import threading
from collections import deque
from pathlib import Path
from datetime import datetime, timezone

_LOCK = threading.RLock()
_PROCESSES = {}
_LOG_LIMIT = 500


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
