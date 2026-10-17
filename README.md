# Nexus Panel

**Universal game-hosting control center — working local MVP**

Nexus Panel is a Blue Neon responsive web dashboard with a Python standard-library backend and a persistent SQLite database. The app is intended to be run in a private GitHub Codespaces environment while the production architecture is developed.

## Run in GitHub Codespaces

From the repository root:

```bash
git pull
bash ./nexus
```

The launcher starts the backend on port 8000, waits for its health endpoint, and prints the forwarded Codespaces URL. If it does not open automatically, use the **Ports** tab and open port 8000. The Codespaces port should remain **Private**.

If you have not cloned the repository yet:

```bash
git clone https://github.com/lponpz/Nexus-Panel.git
cd Nexus-Panel
bash ./nexus
```

## Working now

- Python HTTP server serves the dashboard and JSON API.
- SQLite persists server records, connector endpoint records, and recent activity in `data/nexus.sqlite3`.
- Dashboard overview reads actual counts from the database instead of sample counts.
- Create and delete server records.
- Save and remove connector endpoint records.
- API health endpoint: `/api/health`.
- Dashboard data endpoint: `/api/overview`.
- Record APIs: `/api/servers` and `/api/connectors`.
- The dashboard clearly marks saved endpoints as **not tested**.

## Important current limits

This is a **working local MVP, not a production-ready public hosting panel**. It does not yet include login/authentication, multi-user authorization, encrypted credential storage, live Pterodactyl/Pelican/AMP adapters, game-process start/stop, real node telemetry, backups/restore, billing, or production deployment hardening. Do not enter API tokens or expose the Codespaces port publicly. The server and connector entries are local records only; creating one does not install a game server or control an external panel.

## Architecture and planning

- [Master roadmap](docs/ROADMAP.md)
- [Universal panel adapter architecture](docs/UNIVERSAL_ADAPTER_ARCHITECTURE.md)
- [Terminal Control Center plan](docs/TERMINAL_CONTROL_CENTER.md)
- [Codespaces dashboard instructions](docs/CODESPACES_DASHBOARD.md)

## Security direction

Before any public deployment, implement authentication and session protection, server-side authorization, CSRF protections, encrypted secrets, rate limits, SSRF protection for connector tests, audit trails, tenant isolation, and secure deployment configuration. External integrations must discover and respect each adapter's actual capabilities rather than claiming unsupported actions succeeded.
