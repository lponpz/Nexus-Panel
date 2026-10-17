# Universal Panel Adapter Architecture

## Purpose
Nexus Panel provides a consistent interface over multiple hosting panels. Each connector must explicitly report its capabilities. A connected panel is not automatically assumed to support every operation.

## Components
1. **Connector registry** — connector ID, type, tenant owner, endpoint, version range, health and lifecycle state.
2. **Adapter contract** — normalized, typed operations for common panel tasks.
3. **Capability negotiation** — supported, unsupported or unknown per operation. Unknown must never be treated as supported.
4. **Credential vault** — encrypted, tenant-scoped credentials; rotation and revocation; secrets excluded from logs.
5. **Policy gate** — role, tenant, server scope, permission and risk checks on every action.
6. **Job queue** — installs, backups, migrations and other long tasks with bounded retries and idempotency.
7. **Audit trail** — actor, tenant, connector, operation, result, timestamp and correlation ID.
8. **Contract tests** — authentication, permissions, API versions, pagination, rate limits, errors and capability accuracy.

## Capability examples
- Server list and status
- Start, stop and restart
- Console access
- File read/write
- Plugin and mod management
- Backup create/restore
- Node and resource reporting
- Migration export/import
- Billing and audit APIs, where exposed

## Planned adapter targets
- Pterodactyl
- Pelican Panel
- AMP by CubeCoders
- Custom adapter SDK for APIs that permit integration

Support and operation coverage must be verified against documented APIs, configured permissions, product versions and license terms. Unsupported controls should be disabled with a clear explanation.

## Connector lifecycle
Draft → configure endpoint → validate URL → test authentication → inspect permissions → discover capabilities → enable → periodic health checks → update/re-authenticate or safely disable.

## Security requirements
- Enforce HTTPS in production except explicitly configured local development.
- Prevent SSRF: block loopback, link-local and private targets unless a self-hosted deployment explicitly permits them; validate DNS and redirects.
- Store credential references in normal application logic, not raw tokens.
- Encrypt credentials at rest using a managed key system.
- Scope every query and mutation to the authenticated tenant.
- Rate-limit requests and use bounded retries.
- Require confirmation and audit logging for destructive operations; consider two-person approval for high-impact actions.
- Test integrations against disposable environments, not customer production servers.
- A successful connection does not imply all features are supported.

## Example contract sketch
```ts
type Capability =
  | "server.list" | "server.status" | "server.start" | "server.stop"
  | "server.restart" | "console.read" | "files.read" | "files.write"
  | "backup.create" | "backup.restore" | "resources.read" | "nodes.read";

interface PanelAdapter {
  readonly id: string;
  readonly displayName: string;
  testConnection(context: ConnectorContext): Promise<ConnectionTest>;
  getCapabilities(context: ConnectorContext): Promise<Set<Capability>>;
  listServers(context: ConnectorContext, page?: PageRequest): Promise<Page<NormalizedServer>>;
  getServerStatus(context: ConnectorContext, serverId: string): Promise<NormalizedStatus>;
  execute(context: ConnectorContext, action: SupportedAction): Promise<ActionResult>;
}
```

This is a design sketch only; it is not wired to a production backend.