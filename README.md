# Nexus Panel

**Universal game-hosting control center — Phase 1 prototype**

Nexus Panel is being designed as a premium, Blue Neon, responsive dashboard that can unify supported game hosting panels through a capability-aware adapter architecture.

## Start here
- Open `index.html` in a modern browser to preview the responsive dashboard.
- See [Universal Panel Adapter Architecture](docs/UNIVERSAL_ADAPTER_ARCHITECTURE.md).
- See the [Master Roadmap](docs/ROADMAP.md) for all agreed future feature groups.

## Phase 1 prototype includes
- Responsive dashboard layout and mobile navigation.
- Demo overview cards, connector list, activity feed, server table and quick actions.
- UI-only connector setup dialog and local demo search.
- Architecture and security design notes.

## Important
This is a frontend prototype. Dashboard figures are sample data. It does not yet authenticate users, contact panel APIs, control servers, store credentials, process billing, or perform backups. Do not enter real API tokens into the demo UI.

## Planned production direction
A typed frontend, secure backend API, tenant-aware authorization, connector registry, encrypted credential vault, job queue, audit trail and adapter contract tests. The actual production stack will be finalized before backend implementation.

## Security principles
Least privilege, tenant isolation, encrypted secrets, secret redaction, SSRF protection, server-side authorization, audit trails, idempotent operations, and approval gates for high-impact actions.

## Terminal Control Center (early scaffold)

Run the keyboard-driven terminal menu on Linux/macOS with Python 3:

```bash
python3 tools/nexusctl.py
```

Menu options include Install, Update, Reinstall, Delete, Add User, Add Owner, Backups & Recovery, Panel Connectors, and Logs & Health. **At this stage these actions are planning-only:** the TUI does not make system changes or connect to panel APIs. See [Terminal Control Center safety and implementation plan](docs/TERMINAL_CONTROL_CENTER.md).
## One-command terminal menu

Clone the repository and immediately open the terminal Control Center:

```bash
git clone https://github.com/lponpz/Nexus-Panel.git && cd Nexus-Panel && bash ./nexus
```

Use number keys **1–9** to open menu actions and **0** to exit. This currently launches the prototype TUI; production installation and destructive operations are not yet implemented. See [one-command launch notes](docs/ONE_COMMAND_LAUNCH.md).
## Codespaces dashboard port

The `bash ./nexus` launcher starts the static dashboard on port 8000 and then opens the terminal Control Center. Codespaces is configured to forward port 8000 and open the dashboard in a browser. If it does not open automatically, use the **Ports** tab and click the forwarded URL. Details: [Codespaces dashboard instructions](docs/CODESPACES_DASHBOARD.md).
