#!/usr/bin/env bash
set -Eeuo pipefail
if [[ ! -f nexus_control.py ]]; then
  git clone -b feature/nexus-auth-foundation https://github.com/lponpz/Nexus-Panel.git nexus-panel
  cd nexus-panel
fi
python3 nexus_control.py
