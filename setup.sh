#!/usr/bin/env bash
# One-command bootstrap for the current Nexus local-node MVP.
# Usage: bash setup.sh
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

say(){ printf '\n[Nexus setup] %s\n' "$*"; }
fail(){ printf '\n[Nexus setup] ERROR: %s\n' "$*" >&2; exit 1; }

[[ "$(uname -s)" == "Linux" ]] || fail "This bootstrap currently supports Linux hosts/Codespaces only."
command -v python3 >/dev/null 2>&1 || fail "Python 3 is required. Install Python 3 and run bash setup.sh again."
python3 - <<'PY' || exit 1
import sys
if sys.version_info < (3, 9):
    print("[Nexus setup] ERROR: Python 3.9 or newer is required.")
    raise SystemExit(1)
PY

# Install Java 21 only when it is missing and a supported package manager is available.
if ! command -v java >/dev/null 2>&1; then
  say "Java runtime not found; attempting to install OpenJDK 21."
  if command -v apt-get >/dev/null 2>&1; then
    if [[ "$(id -u)" -eq 0 ]]; then
      apt-get update
      DEBIAN_FRONTEND=noninteractive apt-get install -y openjdk-21-jre-headless
    elif command -v sudo >/dev/null 2>&1; then
      sudo apt-get update
      sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y openjdk-21-jre-headless
    else
      fail "Java 21 is missing and sudo is unavailable. Install OpenJDK 21, then rerun this script."
    fi
  else
    fail "Java 21 is missing and this host has no apt-get. Install Java 21, then rerun this script."
  fi
fi

java -version 2>&1 | head -n 1 || fail "Java is installed but could not run."
mkdir -p data/servers
chmod 700 data data/servers 2>/dev/null || true
python3 -m py_compile server.py node_agent.py runtime_manager.py backup_manager.py || fail "Python syntax check failed."
say "Python syntax checks passed."
say "Initializing local database and default workspace."
python3 - <<'PY'
import server
server.init_db()
with server.DB_LOCK, server.connect_db() as db:
    db.execute("INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES('workspace_name','Nexus Workspace',?)", (server.now(),))
    db.execute("INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES('setup_complete','false',?)", (server.now(),))
PY

say "Starting Nexus Panel and its local Java-capable node runtime."
bash ./nexus
