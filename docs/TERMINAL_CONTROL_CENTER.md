# Nexus Panel Control Center (terminal TUI)

## Run
From the repository root on Linux/macOS or a Linux server with Python 3:
```bash
python3 tools/nexusctl.py
```
This uses Python's standard library (curses) and does not require pip packages. Some minimal Linux installs may need their OS-provided Python curses package.

## Menu
- Install panel
- Update panel
- Reinstall panel
- Delete panel
- Add user
- Add owner
- Backups & recovery
- Panel connectors
- Logs & health
- Exit

Use Up/Down (or j/k), Enter, P to change the target panel, Esc/Q to exit.

## Safety status
This is the first TUI scaffold. Every action is planning-only; it does not run installers, update/delete services, change users, grant owner access, or call a panel API. The UI intentionally reports this instead of pretending operations succeeded.

## Next implementation phases
1. Define the deployment target (Nexus itself vs. a connected external panel), supported OS versions, installation method and database.
2. Add authenticated local control daemon with strict permissions; do not run the whole UI as root.
3. Add adapter/installer registry, signed manifests, version and OS compatibility checks, dry-run plans and idempotent jobs.
4. Implement install/update with verified downloads, checksums/signatures, staged changes, backup and rollback.
5. Implement reinstall/delete with data-impact preview, off-host backup verification, typed confirmation and audit log.
6. Implement regular-user creation via supported auth backend. Owner grants require an existing authorized owner, MFA/identity check, reason and audit event; never provide an authorization bypass.
7. Add tests and an explicit opt-in production mode only after each action is implemented and reviewed.

## Security
Never pipe unverified internet content directly into a root shell. Never put API tokens/passwords in blueprints or logs. Keep secrets in a protected credential store. Destructive operations must be tenant-scoped, least-privilege, auditable, and recoverable where possible.
