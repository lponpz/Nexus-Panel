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
import time
import shutil
from urllib.parse import urlparse
from collections import deque
from pathlib import Path
from datetime import datetime, timezone

_LOCK = threading.RLock()
_PROCESSES = {}
_LOG_LIMIT = 500
_METRIC_SAMPLES = {}


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
    openjdk_match = re.search(r"openjdk (\d+)", output, re.IGNORECASE)
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
        if not isinstance(candidate, str) or not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", candidate):
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
    if version != "latest" and not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", str(version)):
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


def _fabric_json(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "meta.fabricmc.net":
        raise ValueError("Refusing to contact an untrusted Fabric metadata URL.")
    request = urllib.request.Request(url, headers={
        "User-Agent": "NexusPanel/0.1 (https://github.com/lponpz/Nexus-Panel)",
        "Accept": "application/json"
    })
    with urllib.request.urlopen(request, timeout=20) as response:
        if urlparse(response.geturl()).hostname != "meta.fabricmc.net":
            raise ValueError("Fabric metadata redirected to an untrusted host.")
        raw = response.read(4_000_000)
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, (dict, list)):
        raise ValueError("Fabric returned invalid metadata.")
    return payload


def _minecraft_minimum_java(version):
    parts = [int(x) for x in version.split(".")]
    if parts[0] >= 26:
        return 25
    if parts[0] >= 2:
        return 21
    if len(parts) > 1 and (parts[1] > 20 or (parts[1] == 20 and len(parts) > 2 and parts[2] >= 5)):
        return 21
    if len(parts) > 1 and parts[1] >= 18:
        return 17
    return 8


def install_fabric_server(directory, game_version="latest"):
    """Install the official Fabric executable server launcher for the newest Java-compatible stable game version."""
    root = Path(directory).resolve()
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Server directory is invalid.")
    if (root / "server.jar").exists() or (root / "fabric-server.jar").exists():
        raise ValueError("A server JAR already exists. Remove or back up existing server software before installing Fabric.")
    java_major = _java_major()
    games = _fabric_json("https://meta.fabricmc.net/v2/versions/game")
    if not isinstance(games, list):
        raise RuntimeError("Fabric returned an invalid game version catalog.")
    if game_version == "latest":
        candidates = [item for item in games if isinstance(item, dict) and item.get("stable") is True
                      and isinstance(item.get("version"), str)
                      and re.fullmatch(r"\d+(?:\.\d+){1,2}", item["version"])
                      and _minecraft_minimum_java(item["version"]) <= java_major]
        if not candidates:
            raise RuntimeError("No stable Fabric server version is compatible with Java " + str(java_major) + ".")
        game_version = candidates[0]["version"]
    else:
        if not isinstance(game_version, str) or not re.fullmatch(r"\d+(?:\.\d+){1,2}", game_version):
            raise ValueError("Choose latest or a Minecraft version such as 1.21.11.")
        game = next((item for item in games if isinstance(item, dict) and item.get("version") == game_version and item.get("stable") is True), None)
        if not game:
            raise ValueError("Fabric does not list that stable Minecraft version.")
        if _minecraft_minimum_java(game_version) > java_major:
            raise RuntimeError("Minecraft " + game_version + " requires Java " + str(_minecraft_minimum_java(game_version)) + " or newer.")
    loaders = _fabric_json("https://meta.fabricmc.net/v2/versions/loader/" + game_version)
    if not isinstance(loaders, list):
        raise RuntimeError("Fabric returned an invalid loader catalog.")
    loader = next((item.get("loader", {}).get("version") for item in loaders
                   if isinstance(item, dict) and isinstance(item.get("loader"), dict) and item["loader"].get("stable") is True), None)
    installers = _fabric_json("https://meta.fabricmc.net/v2/versions/installer")
    if not isinstance(installers, list):
        raise RuntimeError("Fabric returned an invalid installer catalog.")
    installer = next((item.get("version") for item in installers if isinstance(item, dict) and item.get("stable") is True and isinstance(item.get("version"), str)), None)
    if not loader or not installer:
        raise RuntimeError("Fabric did not list a stable loader and installer version.")
    url = "https://meta.fabricmc.net/v2/versions/loader/" + game_version + "/" + loader + "/" + installer + "/server/jar"
    request = urllib.request.Request(url, headers={"User-Agent":"NexusPanel/0.1 (https://github.com/lponpz/Nexus-Panel)"})
    with urllib.request.urlopen(request, timeout=45) as response:
        if urlparse(response.geturl()).hostname != "meta.fabricmc.net":
            raise ValueError("Fabric launcher download redirected to an untrusted host.")
        payload = response.read(100 * 1024 * 1024 + 1)
    if len(payload) < 100_000 or len(payload) > 100 * 1024 * 1024:
        raise ValueError("Fabric launcher download is empty or exceeds the 100 MB limit.")
    target = root / "fabric-server.jar"
    fd, temp_name = tempfile.mkstemp(prefix=".nexus-fabric-", suffix=".tmp", dir=str(root))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload); stream.flush(); os.fsync(stream.fileno())
        os.replace(temp_name, target)
    except Exception:
        try: os.unlink(temp_name)
        except OSError: pass
        raise
    return {"software":"fabric","version":game_version,"loader_version":loader,"installer_version":installer,
            "java_major":java_major,"filename":target.name,"size":len(payload),"sha256":hashlib.sha256(payload).hexdigest(),
            "launch_command":"java -Xms1G -Xmx2G -jar fabric-server.jar nogui"}


def _modrinth_json(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "api.modrinth.com":
        raise ValueError("Refusing to contact an untrusted Modrinth API URL.")
    request = urllib.request.Request(url, headers={
        "User-Agent": "NexusPanel/0.1 (https://github.com/lponpz/Nexus-Panel)",
        "Accept": "application/json"
    })
    with urllib.request.urlopen(request, timeout=20) as response:
        if urlparse(response.geturl()).hostname != "api.modrinth.com":
            raise ValueError("Modrinth API redirected to an untrusted host.")
        raw = response.read(4_000_000)
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, (dict, list)):
        raise ValueError("Modrinth returned invalid metadata.")
    return payload


def detect_server_software(directory):
    root = Path(directory).resolve()
    metadata = root / "nexus-server.json"
    if metadata.is_file() and not metadata.is_symlink():
        try:
            info = json.loads(metadata.read_text("utf-8"))
            software = info.get("software")
            if software in ("paper", "fabric"):
                return software
        except (OSError, ValueError, AttributeError):
            pass
    if (root / "fabric-server.jar").is_file() or (root / "fabric-server-launch.jar").is_file():
        return "fabric"
    return None


def detect_minecraft_version(directory):
    root = Path(directory).resolve()
    metadata = root / "nexus-server.json"
    if metadata.is_file() and not metadata.is_symlink():
        try:
            info = json.loads(metadata.read_text("utf-8"))
            version = info.get("game_version")
            if isinstance(version, str) and re.fullmatch(r"\d+\.\d+(?:\.\d+)?", version):
                return version
        except (OSError, ValueError, AttributeError):
            pass
    log = root / "logs" / "latest.log"
    if log.is_file() and not log.is_symlink():
        try:
            content = log.read_text("utf-8", errors="replace")[-2_000_000:]
            patterns = (
                r"Starting minecraft server version (\d+\.\d+(?:\.\d+)?)",
                r"\(MC: (\d+\.\d+(?:\.\d+)?)\)",
                r"Loading Minecraft (\d+\.\d+(?:\.\d+)?)"
            )
            for pattern in patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                if matches:
                    return matches[-1]
        except OSError:
            pass
    return None


def install_modrinth_plugin(directory, query, game_version=None):
    """Install the newest stable Paper plugin compatible with the detected Minecraft version."""
    root = Path(directory).resolve()
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Server directory is invalid.")
    query = str(query or "").strip()
    if not query or len(query) > 120 or any(ord(ch) < 32 for ch in query):
        raise ValueError("Enter a plugin name or search phrase up to 120 characters.")
    if not isinstance(game_version, str) or not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", game_version):
        raise ValueError("Nexus could not detect the Minecraft version. Install Paper and start the server once before installing plugins.")
    from urllib.parse import urlencode
    search_url = "https://api.modrinth.com/v2/search?" + urlencode({
        "query": query,
        "facets": json.dumps([["project_type:plugin"]]),
        "limit": "10"
    })
    search = _modrinth_json(search_url)
    hits = search.get("hits", []) if isinstance(search, dict) else []
    candidates = [hit for hit in hits if isinstance(hit, dict) and hit.get("project_type") == "plugin"
                  and isinstance(hit.get("slug"), str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", hit["slug"])]
    if not candidates:
        raise ValueError("No Modrinth Paper plugins matched that search.")
    project = candidates[0]
    versions_url = "https://api.modrinth.com/v2/project/" + project["slug"] + "/version?" + urlencode({
        "loaders": json.dumps(["paper"]),
        "game_versions": json.dumps([game_version])
    })
    versions = _modrinth_json(versions_url)
    if not isinstance(versions, list):
        raise ValueError("Modrinth returned an invalid plugin version list.")
    compatible = [v for v in versions if isinstance(v, dict) and v.get("version_type", "release") == "release"
                  and isinstance(v.get("files"), list) and v["files"]]
    if not compatible:
        raise ValueError("No stable version of " + str(project.get("title", project["slug"])) +
                         " supports Minecraft " + game_version + " on Fabric.")
    selected = compatible[0]
    files = [f for f in selected["files"] if isinstance(f, dict)]
    file_info = next((f for f in files if f.get("primary") is True), files[0] if files else None)
    if not file_info:
        raise ValueError("Modrinth did not provide a plugin artifact.")
    filename = file_info.get("filename", "")
    url = file_info.get("url", "")
    size = file_info.get("size")
    hashes = file_info.get("hashes", {}) if isinstance(file_info.get("hashes"), dict) else {}
    expected_sha512 = hashes.get("sha512")
    expected_sha1 = hashes.get("sha1")
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "cdn.modrinth.com":
        raise ValueError("Modrinth returned an untrusted plugin download URL.")
    if not isinstance(filename, str) or not re.fullmatch(r"[A-Za-z0-9_. -]{1,180}\.jar", filename):
        raise ValueError("Modrinth returned an invalid plugin filename.")
    if not isinstance(size, int) or size < 1 or size > 100 * 1024 * 1024:
        raise ValueError("Plugin artifact is missing its size or exceeds the 100 MB limit.")
    if not ((isinstance(expected_sha512, str) and re.fullmatch(r"[0-9a-fA-F]{128}", expected_sha512))
            or (isinstance(expected_sha1, str) and re.fullmatch(r"[0-9a-fA-F]{40}", expected_sha1))):
        raise ValueError("Modrinth did not provide a valid artifact checksum.")
    plugin_dir = root / "plugins"
    if plugin_dir.is_symlink():
        raise ValueError("Plugin directory cannot be a symbolic link.")
    plugin_dir.mkdir(parents=True, exist_ok=True)
    target = plugin_dir / filename
    if target.exists() or target.is_symlink():
        raise ValueError("Plugin file already exists: " + filename + ". Remove it before reinstalling.")
    request = urllib.request.Request(url, headers={"User-Agent": "NexusPanel/0.1 (https://github.com/lponpz/Nexus-Panel)"})
    temp_name = None
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            if urlparse(response.geturl()).hostname != "cdn.modrinth.com":
                raise ValueError("Plugin download redirected to an untrusted host.")
            payload = response.read(100 * 1024 * 1024 + 1)
        if len(payload) != size or len(payload) > 100 * 1024 * 1024:
            raise ValueError("Downloaded plugin size did not match Modrinth metadata.")
        if expected_sha512 and hashlib.sha512(payload).hexdigest().lower() != expected_sha512.lower():
            raise ValueError("Plugin SHA-512 verification failed; the download was discarded.")
        if not expected_sha512 and hashlib.sha1(payload).hexdigest().lower() != expected_sha1.lower():
            raise ValueError("Plugin SHA-1 verification failed; the download was discarded.")
        fd, temp_name = tempfile.mkstemp(prefix=".nexus-plugin-", suffix=".tmp", dir=str(plugin_dir))
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, target)
        temp_name = None
    finally:
        if temp_name:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
    return {"project": str(project.get("title", project["slug"]))[:160],
            "slug": project["slug"], "version": str(selected.get("version_number", ""))[:80],
            "game_version": game_version, "filename": filename, "size": size,
            "sha512": hashlib.sha512(payload).hexdigest(), "path": "plugins/" + filename}


def install_modrinth_mod(directory, query, game_version=None):
    """Install the newest stable Fabric mod compatible with the detected Minecraft version."""
    root = Path(directory).resolve()
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Server directory is invalid.")
    query = str(query or "").strip()
    if not query or len(query) > 120 or any(ord(ch) < 32 for ch in query):
        raise ValueError("Enter a mod name or search phrase up to 120 characters.")
    if not isinstance(game_version, str) or not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", game_version):
        raise ValueError("Nexus could not detect the Minecraft version. Install Fabric and start the server once before installing mods.")
    from urllib.parse import urlencode
    search_url = "https://api.modrinth.com/v2/search?" + urlencode({
        "query": query,
        "facets": json.dumps([["project_type:mod"]]),
        "limit": "10"
    })
    search = _modrinth_json(search_url)
    hits = search.get("hits", []) if isinstance(search, dict) else []
    candidates = [hit for hit in hits if isinstance(hit, dict) and hit.get("project_type") == "mod"
                  and isinstance(hit.get("slug"), str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", hit["slug"])]
    if not candidates:
        raise ValueError("No Modrinth Fabric mods matched that search.")
    project = candidates[0]
    versions_url = "https://api.modrinth.com/v2/project/" + project["slug"] + "/version?" + urlencode({
        "loaders": json.dumps(["fabric"]),
        "game_versions": json.dumps([game_version])
    })
    versions = _modrinth_json(versions_url)
    if not isinstance(versions, list):
        raise ValueError("Modrinth returned an invalid mod version list.")
    compatible = [v for v in versions if isinstance(v, dict) and v.get("version_type", "release") == "release"
                  and isinstance(v.get("files"), list) and v["files"]]
    if not compatible:
        raise ValueError("No stable version of " + str(project.get("title", project["slug"])) +
                         " supports Minecraft " + game_version + " on Paper.")
    selected = compatible[0]
    files = [f for f in selected["files"] if isinstance(f, dict)]
    file_info = next((f for f in files if f.get("primary") is True), files[0] if files else None)
    if not file_info:
        raise ValueError("Modrinth did not provide a mod artifact.")
    filename = file_info.get("filename", "")
    url = file_info.get("url", "")
    size = file_info.get("size")
    hashes = file_info.get("hashes", {}) if isinstance(file_info.get("hashes"), dict) else {}
    expected_sha512 = hashes.get("sha512")
    expected_sha1 = hashes.get("sha1")
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "cdn.modrinth.com":
        raise ValueError("Modrinth returned an untrusted mod download URL.")
    if not isinstance(filename, str) or not re.fullmatch(r"[A-Za-z0-9_. -]{1,180}\.jar", filename):
        raise ValueError("Modrinth returned an invalid mod filename.")
    if not isinstance(size, int) or size < 1 or size > 100 * 1024 * 1024:
        raise ValueError("Mod artifact is missing its size or exceeds the 100 MB limit.")
    if not ((isinstance(expected_sha512, str) and re.fullmatch(r"[0-9a-fA-F]{128}", expected_sha512))
            or (isinstance(expected_sha1, str) and re.fullmatch(r"[0-9a-fA-F]{40}", expected_sha1))):
        raise ValueError("Modrinth did not provide a valid artifact checksum.")
    mod_dir = root / "mods"
    if mod_dir.is_symlink():
        raise ValueError("Mod directory cannot be a symbolic link.")
    mod_dir.mkdir(parents=True, exist_ok=True)
    target = mod_dir / filename
    if target.exists() or target.is_symlink():
        raise ValueError("Mod file already exists: " + filename + ". Remove it before reinstalling.")
    request = urllib.request.Request(url, headers={"User-Agent": "NexusPanel/0.1 (https://github.com/lponpz/Nexus-Panel)"})
    temp_name = None
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            if urlparse(response.geturl()).hostname != "cdn.modrinth.com":
                raise ValueError("Mod download redirected to an untrusted host.")
            payload = response.read(100 * 1024 * 1024 + 1)
        if len(payload) != size or len(payload) > 100 * 1024 * 1024:
            raise ValueError("Downloaded mod size did not match Modrinth metadata.")
        if expected_sha512 and hashlib.sha512(payload).hexdigest().lower() != expected_sha512.lower():
            raise ValueError("Mod SHA-512 verification failed; the download was discarded.")
        if not expected_sha512 and hashlib.sha1(payload).hexdigest().lower() != expected_sha1.lower():
            raise ValueError("Mod SHA-1 verification failed; the download was discarded.")
        fd, temp_name = tempfile.mkstemp(prefix=".nexus-mod-", suffix=".tmp", dir=str(mod_dir))
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, target)
        temp_name = None
    finally:
        if temp_name:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
    return {"project": str(project.get("title", project["slug"]))[:160],
            "slug": project["slug"], "version": str(selected.get("version_number", ""))[:80],
            "game_version": game_version, "filename": filename, "size": size,
            "sha512": hashlib.sha512(payload).hexdigest(), "path": "mods/" + filename}


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


def process_metrics(server_id):
    with _LOCK:
        item = _PROCESSES.get(server_id)
        if not item:
            return {"available": False, "running": False, "pid": None, "cpu_percent": None, "memory_rss_mb": 0, "memory_vms_mb": 0}
        process = item["process"]
        running = process.poll() is None
        pid = process.pid
        started_at = item["started_at"]
    if not running:
        return {"available": False, "running": False, "pid": pid, "cpu_percent": None, "memory_rss_mb": 0, "memory_vms_mb": 0}
    status_path = Path("/proc") / str(pid) / "status"
    stat_path = Path("/proc") / str(pid) / "stat"
    if not status_path.is_file() or not stat_path.is_file():
        return {"available": False, "running": True, "pid": pid, "cpu_percent": None, "memory_rss_mb": None, "memory_vms_mb": None}
    memory = {}
    for line in status_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(("VmRSS:", "VmSize:")):
            key, value, *_ = line.split()
            memory[key.rstrip(":")] = int(value) * 1024
    stat_text = stat_path.read_text(encoding="utf-8", errors="replace")
    fields = stat_text[stat_text.rfind(")") + 1:].split()
    ticks = os.sysconf("SC_CLK_TCK")
    cpu_seconds = (int(fields[11]) + int(fields[12])) / ticks
    sampled_at = time.monotonic()
    cpu_percent = None
    with _LOCK:
        previous = _METRIC_SAMPLES.get(server_id)
        _METRIC_SAMPLES[server_id] = (sampled_at, cpu_seconds)
    if previous:
        elapsed = sampled_at - previous[0]
        if elapsed > 0:
            cpu_percent = round(max(0.0, (cpu_seconds - previous[1]) / elapsed * 100.0), 1)
            cpu_percent = min(cpu_percent, float((os.cpu_count() or 1) * 100))
    try:
        started = datetime.fromisoformat(started_at)
        uptime = max(0, int((datetime.now(timezone.utc) - started).total_seconds()))
    except (ValueError, TypeError):
        uptime = None
    return {"available": True, "running": True, "pid": pid, "cpu_percent": cpu_percent,
            "memory_rss_mb": round(memory.get("VmRSS", 0) / (1024 * 1024), 1),
            "memory_vms_mb": round(memory.get("VmSize", 0) / (1024 * 1024), 1),
            "cpu_time_seconds": round(cpu_seconds, 2), "uptime_seconds": uptime}


def host_metrics(storage_path):
    cpu_count = os.cpu_count() or 1
    load_1m = None
    try:
        load_1m = round(os.getloadavg()[0], 2)
    except (AttributeError, OSError):
        pass
    total_kb = available_kb = None
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                total_kb = int(line.split()[1])
            elif line.startswith("MemAvailable:"):
                available_kb = int(line.split()[1])
    except OSError:
        pass
    disk = shutil.disk_usage(storage_path)
    return {"available": total_kb is not None, "cpu_count": cpu_count, "load_1m": load_1m,
            "memory_total_mb": round(total_kb / 1024, 1) if total_kb is not None else None,
            "memory_available_mb": round(available_kb / 1024, 1) if available_kb is not None else None,
            "disk_total_gb": round(disk.total / (1024 ** 3), 2),
            "disk_free_gb": round(disk.free / (1024 ** 3), 2)}


def logs(server_id):
    with _LOCK:
        item = _PROCESSES.get(server_id)
        return {"running": bool(item and item["process"].poll() is None), "logs": list(item["logs"]) if item else []}


def shutdown_all():
    """Gracefully stop processes owned by this backend before an update/restart."""
    with _LOCK:
        server_ids = list(_PROCESSES.keys())
    stopped = []
    for server_id in server_ids:
        try:
            state = snapshot(server_id)
            if state.get("running"):
                stop(server_id)
                stopped.append(server_id)
        except Exception:
            # Last-resort cleanup only for processes still tracked by this process.
            with _LOCK:
                item = _PROCESSES.get(server_id)
                process = item.get("process") if item else None
            if process and process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except Exception:
                    try:
                        process.kill()
                    except OSError:
                        pass
    return stopped


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
