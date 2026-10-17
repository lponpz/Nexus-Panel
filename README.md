# Nexus Panel

**Nexus Panel — independent game-hosting panel in active development**

Nexus has its own Blue Neon web UI, Python API, SQLite state, first-run owner setup, PBKDF2 password hashing, expiring HttpOnly sessions, login throttling, CSRF protection for mutations, per-server workspace, Java process adapter, browser console, and basic file manager. It is not a fork of Pterodactyl. The current runtime is a development adapter, not yet a production-grade Wings/node replacement.

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

- First-run installer creates the workspace and first owner account; passwords are stored as salted PBKDF2-HMAC-SHA256 hashes.
- Owner login with a 12-hour HttpOnly/SameSite session cookie, failed-login throttling, and CSRF tokens on API mutations.
- API routes are blocked until setup; the dashboard redirects unauthenticated visitors to the login page.
- Server record creation, editing and deletion.
- Per-server workspace folders.
- Java-only process launch/stop/restart for a server JAR named `server.jar`.
- One-click stable Paper server installer using PaperMC's current Fill API; it chooses a Java-compatible stable version, validates the artifact host and published SHA-256, checks size, and atomically installs `server.jar` without overwriting an existing JAR.
- Per-server manual and scheduled backups; one-click restore verifies backup SHA-256 and creates a pre-restore safety backup. Scheduled backups retain the latest 20 records per server.
- Browser console with output polling and game-console command input.
- Per-server file browser, text file create/edit/delete, folder create, uploads up to 50 MB, and downloads up to 200 MB.
- SQLite activity log, overview counts, and connector endpoint records.

## Current runtime limitations

- This runtime launches Java processes on the same machine as Nexus. It does not yet provide a secure isolated node daemon/container like Pterodactyl Wings.
- The host must have a compatible Java runtime installed. Upload the Java server JAR as `server.jar`; accept the Minecraft EULA by creating/editing `eula.txt` if applicable.
- File uploads are currently limited to 50 MB and downloads to 200 MB; archive extraction is not implemented.
- Metrics are host/process observations only; container-enforced resource quotas and remote node telemetry are not implemented.
- Backups are stored locally on the same host/disk; remote encrypted backup storage and isolated restore drills are not implemented.
- The Paper installer requires outbound HTTPS access to PaperMC's official Fill API and download host. Vanilla, Fabric, Forge, FiveM and Terraria auto-installers are not implemented yet.
- FiveM/Terraria-specific runtimes, automatic game installers, allocations/ports, resource telemetry, crash recovery, scheduled tasks, backups/restores, SFTP, users/roles, and live Pterodactyl/Pelican/AMP API adapters are not implemented.
- Owner authentication is implemented, but multi-user/customer accounts, per-server ownership, role permissions, password reset, MFA, and full production security review are not implemented.
- The Java process adapter still runs game servers on the same host without container isolation or enforced CPU/RAM/PID limits. Because process supervision is in the panel process, restarting/updating Nexus gracefully stops its managed game servers; a separate persistent node agent is still required for production. Do not expose this development build to the public internet; keep Codespaces ports Private.
- Authentication tests and syntax checks are wired into GitHub Actions. They must pass on the branch before considering these changes verified.

A complete hosting panel still needs a hardened node agent, isolated process execution, customer accounts and per-server authorization, resource limits, port allocation, real game installers, backups/restores, secure updates, and thorough integration/security tests. This repository is being built toward that goal in stages; do not treat this development build as production-safe.

## JTG installer audit

See [JTG audit and Nexus integration roadmap](docs/JTG_AUDIT_AND_INTEGRATION.md) for the static installer review, security findings, and staged integration plan.

## Project planning

- [Master roadmap](docs/ROADMAP.md)
- [Universal panel adapter architecture](docs/UNIVERSAL_ADAPTER_ARCHITECTURE.md)
- [Terminal Control Center plan](docs/TERMINAL_CONTROL_CENTER.md)
- [Codespaces dashboard instructions](docs/CODESPACES_DASHBOARD.md)
- [JTG installer security audit and Nexus integration roadmap](docs/JTG_AUDIT_AND_INTEGRATION.md)

## Security note

The local launcher binds to loopback by default. In GitHub Codespaces it binds to `0.0.0.0` for port forwarding and prints a warning; keep the forwarded port **Private**. This development build still has no authentication or authorization and is not safe for public internet exposure.
