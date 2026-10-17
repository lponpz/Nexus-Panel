# Nexus Panel

**Nexus Panel — working local web-app foundation**

Nexus is a Blue Neon responsive game-hosting dashboard with a Python standard-library HTTP API and persistent SQLite database. This repository now includes a browser-based first-run installer.

## Start in GitHub Codespaces

From the repository root, run:

```bash
git pull
bash ./nexus
```

The launcher checks whether the app is already running, detects an occupied port and tries the next available port, starts the backend, waits for `/api/health`, and prints the installer and dashboard URLs. In Codespaces, open the printed **Installer GUI** URL. If the URL does not open automatically, use the **Ports** tab and open the port shown in the terminal.

First-time clone:

```bash
git clone https://github.com/lponpz/Nexus-Panel.git && cd Nexus-Panel && bash ./nexus
```

## Working features

- Browser-based installer wizard to save the workspace name.
- Python HTTP server and JSON API.
- SQLite database for settings, server records, connector endpoint records and activity.
- Dashboard overview based on actual local database counts.
- Create and delete local server records.
- Save and remove connector endpoint records.
- Health endpoint: `/api/health`.
- Setup endpoint: `/api/setup`.
- Dashboard endpoints: `/api/overview`, `/api/servers`, `/api/connectors`.

## Important: this is not yet a complete production hosting panel

The intended product is a complete Nexus Panel, but this current version is an early working foundation. The installer configures the local workspace; it does **not** install game servers on remote hosts. Login and owner accounts, authorization, live Pterodactyl/Pelican/AMP adapters, game process controls, node telemetry, backups/restore, billing and production deployment hardening are not implemented yet.

Keep the Codespaces port **Private**. Do not enter API tokens or expose this development server publicly until authentication, authorization, CSRF protection, secret encryption, rate limits, SSRF defenses and tenant isolation are implemented and tested.

## Project planning

- [Master roadmap](docs/ROADMAP.md)
- [Universal panel adapter architecture](docs/UNIVERSAL_ADAPTER_ARCHITECTURE.md)
- [Terminal Control Center plan](docs/TERMINAL_CONTROL_CENTER.md)
- [Codespaces dashboard instructions](docs/CODESPACES_DASHBOARD.md)
