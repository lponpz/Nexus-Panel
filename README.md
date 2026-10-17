# Nexus Panel

**Nexus Panel — independent game-hosting panel in active development**

Nexus has its own Blue Neon web UI, Python API, SQLite state, installer, per-server workspace, Java process adapter, browser console, and basic file manager. It is not a fork of Pterodactyl. The current runtime is a development adapter, not yet a production-grade Wings/node replacement.

## One-command setup (Linux / GitHub Codespaces)

From the repository root, run:

```bash
bash setup.sh
```

The bootstrap checks Python, compiles the Python modules, creates the local data directories and SQLite database, attempts to install OpenJDK 21 when Java is missing on an apt-based Linux host, and starts the panel. If Java installation requires unavailable privileges or the package is unavailable, it stops with an explicit message. On later runs, use `bash ./nexus`.

Open the installer/dashboard URL printed by the launcher. If it does not open automatically, open the matching port in the Codespaces **Ports** tab. Keep that port **Private**.

**Node scope:** this one-command bootstrap prepares the local development runtime on the machine where it runs. It cannot provision remote VPS nodes that you have not given access to; a secure remote node agent and authenticated pairing still need to be built before claiming multi-node hosting.

Open the installer/dashboard URL printed by the launcher. If it does not open automatically, open the matching port in the Codespaces **Ports** tab. Keep that port **Private**.

## Currently implemented

- First-run installer and persistent workspace settings.
- Server record creation, editing and deletion.
- Per-server workspace folders.
- Java-only process launch/stop for a server JAR named `server.jar`.
- Browser console with output polling and game-console command input.
- Per-server file browser, text file create/edit/delete, folder create, and uploads up to 50 MB.
- SQLite activity log, overview counts, and connector endpoint records.

## Current runtime limitations

- This runtime launches Java processes on the same machine as Nexus. It does not yet provide a secure isolated node daemon/container like Pterodactyl Wings.
- The host must have a compatible Java runtime installed. Upload the Java server JAR as `server.jar`; accept the Minecraft EULA by creating/editing `eula.txt` if applicable.
- File uploads are currently limited to 50 MB; no archive extraction or download flow yet.
- FiveM/Terraria-specific runtimes, automatic game installers, allocations/ports, resource telemetry, crash recovery, scheduled tasks, backups/restores, SFTP, users/roles, and live Pterodactyl/Pelican/AMP API adapters are not implemented.
- The current app has **no login or authorization**. Never expose this development server publicly or enter secrets into it.

A complete hosting panel needs a hardened node agent, isolated process execution, authenticated owner/customer accounts, permissions, resource limits, port allocation, backups, and thorough tests. This repository is being built toward that goal in stages; do not treat this development build as production-safe.

## Project planning

- [Master roadmap](docs/ROADMAP.md)
- [Universal panel adapter architecture](docs/UNIVERSAL_ADAPTER_ARCHITECTURE.md)
- [Terminal Control Center plan](docs/TERMINAL_CONTROL_CENTER.md)
- [Codespaces dashboard instructions](docs/CODESPACES_DASHBOARD.md)
- [JTG installer security audit and Nexus integration roadmap](docs/JTG_AUDIT_AND_INTEGRATION.md)

## Security note

The local launcher binds to loopback by default. In GitHub Codespaces it binds to `0.0.0.0` for port forwarding and prints a warning; keep the forwarded port **Private**. This development build still has no authentication or authorization and is not safe for public internet exposure.
