# JTG Panel installer audit and Nexus integration plan

Audit date: 2026-10-17

Scope: a static review of the public JTG Panel README and `install.sh` on the repository's `main` branch, plus a comparison with the current Nexus Panel repository. This is **not** a complete source-code, dependency, or runtime penetration test of JTG Panel. No installer was executed and no software was installed.

Reviewed sources:
- https://github.com/JishnuTheGamer/Jtg
- https://raw.githubusercontent.com/JishnuTheGamer/Jtg/refs/heads/main/install.sh
- https://github.com/lponpz/Nexus-Panel

## Findings

| Severity | Finding | Evidence / impact | Decision |
|---|---|---|---|
| Critical | Docker socket permissions are loosened to mode `666` | The installer attempts `chmod 666 /var/run/docker.sock` (including a sudo fallback). Docker socket access is effectively host-root control; any local account/process that can access it can create privileged containers or mount host files. | Never copy this permission change into Nexus. Use a narrowly scoped, authenticated node service and keep Docker access out of the web app. |
| High | Non-interactive install can select known owner credentials | The installer contains a non-TTY fallback of username `owner` and password `owner12345`. If this path is used and the account is reachable, predictable credentials can expose the panel. | Nexus setup must fail closed if an administrator credential is not explicitly created; never ship default credentials. |
| High | Panel/runtime trust boundary is unclear | The documented recommended mode runs the panel on the host and game servers in Docker; the installer also changes Docker socket permissions. A compromised web panel may therefore gain control over the host's Docker daemon. | Separate panel and node agent. Authenticate and authorize every node request; restrict agent API network access; use least privilege. |
| High | Remote web access is shown over plain HTTP | The installer prints an `http://<host-ip>:6767` URL. No HTTPS requirement is visible in the reviewed install path. Passwords/session tokens sent over untrusted networks could be intercepted. | Require HTTPS for public deployments; allow HTTP only for local development or behind a trusted TLS reverse proxy. |
| Medium | Downloaded JRE fallback is extracted without visible checksum/signature verification in the reviewed path | The script fetches an Adoptium archive using curl and extracts it. The reviewed section does not verify a published digest/signature before extraction. | Prefer OS packages or pinned, verified artifacts. Verify SHA-256 against a trusted release manifest before extraction. |
| Medium | Installer mutates host packages/services and may use sudo | It installs system dependencies, enables Docker, changes socket permissions and starts services. A one-line remote script makes these changes difficult to inspect before execution. | Nexus setup should print planned changes, require explicit confirmation for privileged operations, log results, and support dry-run. |
| Medium | Health check verifies HTTP response, not full security/readiness | The installer considers a responding health endpoint sufficient for success. That does not prove admin login, node isolation, server creation, file safety, or backup restore works. | Use explicit readiness checks and automated integration tests for each claimed capability. |
| Low / accuracy | Status output can infer SFTP availability from the panel being online | In the reviewed status function, SFTP status is set online when either panel is online; that is not a real SFTP protocol health check. | Nexus should probe each service independently and show Unknown when not tested. |

## Useful JTG ideas for Nexus (adapt, don't copy blindly)

1. **Guided installer menu:** Install / update / create admin / restart / exit, with clear progress and actionable error logs.
2. **Runtime selection:** distinguish local development from isolated container runtime, and explain trade-offs before selection.
3. **Service lifecycle controls:** show panel, node agent, Docker and SFTP as separate health states.
4. **Health checks:** poll the actual application endpoint and show recent logs when startup fails.
5. **Update workflow:** backups, version display, migration check, update, health test, and rollback rather than a blind overwrite.
6. **System compatibility checks:** OS/architecture, available disk/RAM, Docker availability, Java version, and required ports.
7. **Readable CLI UX:** consistent progress states, log files, and clear post-install URLs.

These are design patterns, not proof that every feature in JTG is complete or secure. Nexus must implement and test each feature independently.

## Nexus security changes in this branch

- The Python backend now binds to loopback by default (`127.0.0.1`) instead of exposing its API on all interfaces.
- The `nexus` launcher keeps ordinary local installs on loopback. It opts into `0.0.0.0` only when it detects a Codespaces environment so port forwarding can work; it prints a warning. **Keep that Codespaces port Private.**
- An operator can override the listener with `NEXUS_HOST`. Do not use a remote bind on a public host until authentication, authorization, CSRF protection, TLS, and hardened node isolation are implemented.

This is a reduction of accidental exposure, not a claim that Nexus is production secure. The current app still has no user login/authorization and the local Java runtime is not a container isolation boundary.

## Integration roadmap

### Phase 1 — Installer and diagnostics
- Preflight: supported OS/architecture, Python, Java/Docker availability, disk space, free ports, and permissions.
- Interactive and non-interactive setup modes; non-interactive mode must require explicit admin creation and never invent credentials.
- Structured logs, real health checks per component, and actionable failure output.
- Safe update command with backup + migration check + health verification + rollback.

### Phase 2 — Accounts and control-plane security (blocker before public exposure)
- Administrator bootstrap that stores password hashes (Argon2id or scrypt), not plaintext.
- Session rotation, secure cookie flags, CSRF protection, login throttling, audit log, and role-based authorization on every API route.
- HTTPS / reverse-proxy trust configuration and secure default headers.
- Private listener by default; no public unauthenticated API.

### Phase 3 — Node agent and server isolation
- Panel communicates with a separate node agent over authenticated TLS with rotated per-node credentials.
- Agent owns Docker operations; the web process never receives the raw Docker socket.
- One container per game server with CPU/memory/PID/disk limits, controlled mounts, non-root execution where possible, network/port allocations, and explicit image allowlists.
- Per-server file root and path validation, safe upload/download, and atomic writes.

### Phase 4 — Hosting features
- Server templates/installer definitions, startup variables, allocations, console streaming, file transfer, resource telemetry, scheduled tasks, backups/restores, crash recovery, and per-user quotas.
- Add adapters for Pterodactyl/Pelican/AMP only after defining each adapter's auth, API capability map, error handling and secret storage. A saved URL is not a working connector.

### Phase 5 — Verification and release
- Unit tests for validation and path handling; API authorization tests; integration tests for create/start/stop/restart/delete; backup-and-restore test; container isolation checks; dependency and secret scans.
- Pin release artifacts and dependencies, verify checksums/signatures, and publish a versioned upgrade/rollback guide.
- Do not label the panel production-ready until all critical tests pass.

## Current release gate

**Do not expose the current Nexus build to the public internet.** Before a public beta, the minimum release gate is authenticated accounts + authorization on every API + HTTPS + CSRF/session protections + isolated node execution + resource/port limits + tested backup/restore and automated security tests.
