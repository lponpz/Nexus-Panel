# Nexus Panel — Master Roadmap

A planned feature is not complete until implemented, tested, and documented. The current branch has a persistent local node agent, a real local Java runtime, owner authentication, per-server console/files, Paper/Fabric installers, and CI checks. It is still not a production multi-node hosting panel. It is still not a production multi-node hosting panel.

## Phase 1 — Foundation (partially implemented)
- [x] Blue Neon responsive dashboard shell and mobile navigation.
- [x] SQLite-backed server/connector records and activity feed.
- [x] First-run owner bootstrap, password hashing, expiring sessions, login throttling and CSRF-protected mutations.
- [x] Per-server local Java process start/stop/restart, console commands/logs, file CRUD, upload and download.
- [x] Minecraft Player Manager: live online player list, kick/ban/unban, operator and whitelist actions, gamemode changes, and live online inventory inspection.
- [x] One-click stable Paper installer with published SHA-256 verification and explicit EULA confirmation.
- [x] Official Fabric server launcher selection based on installed Java compatibility, plus compatible Modrinth Fabric mod installation with SHA-512/SHA-1 verification.
- [x] Modrinth Paper plugin installer: auto-select latest stable compatible version and verify the artifact checksum before atomic install.
- [x] Automated authentication/Paper installer tests and GitHub Actions checks.
- [ ] Production web framework and hardened deployment architecture.
- [x] Customer accounts, per-server authorization, customer portal, and owner-only administrative APIs.
- [x] Local loopback-only node agent with token authentication; game processes survive web panel restarts.
- [ ] Remote node pairing, container isolation, enforced CPU/RAM/disk/PID limits, and production deployment hardening.
- [ ] First live external panel adapter with encrypted credentials and contract tests.

## Universal multi-panel platform
- Unified server dashboard across supported panels.
- Pterodactyl, Pelican, AMP and permitted custom adapters.
- Connection test, version detection, capability negotiation, health checks and connector lifecycle.
- Compatibility matrix; unsupported operations disabled with explanation.
- Connector marketplace with supported versions, permission disclosure, verified publishers/signatures, setup wizard, updates and safe disable.
- Migration importer for supported source panels, with capacity validation, transfer integrity, cutover and recovery plan.

## Dashboard, themes and branding
- Premium rounded Blue Neon design system.
- Responsive desktop/tablet/mobile; accessible keyboard/touch behavior.
- Per-user themes, palettes, gradients/glow, layout, wallpaper, presets, live preview, import/export, reset, contrast and reduced-motion support.
- Personal dashboard studio with custom widgets, saved views and quick actions.
- White-label brands: logo, favicon, colors, login/loading screens, domains, emails/invoices, store/support links and multiple brand profiles.
- Localization and language packs, locale/timezone, dates, numbers and currency display.

## Selected Nexus features (user-approved scope)
- [x] Automatic Backup Scheduler (local storage, configurable interval, 20-backup retention).
- [ ] Mod Compatibility Checker.
- [x] Hosting Plan Builder (owner CRUD for enabled/disabled plans, currency/interval and resource limits; automated billing integration remains pending).
- [ ] Nexus Plugin Marketplace.
- [ ] Expiry Grace Dashboard.
- [ ] Free Server Queue.
- [ ] Server Templates.
- [x] Live Performance Dashboard (local host/process metrics; container quotas remain pending).
- [ ] Role Permission Builder.
- [x] One-Click Restore (checksum-verified backup, pre-restore safety snapshot).

These remain planned until the relevant storage, scheduler, node, permission, and recovery backends are implemented and tested.

## Admin Control Center
- Searchable global settings registry.
- Egg import/export/edit/duplicate/bulk operations, JSON validation, diff/history, dependencies and safe deletion warnings.
- Custom Egg Builder.
- Feature flags, staged rollouts and emergency kill switch.
- Configuration history, diff and rollback preview; no plaintext secrets.
- Approval queue for mass deletion, production restore, risky migration, permission changes and large billing changes.
- Audit/compliance center, filters, exports and retention.
- System jobs dashboard, maintenance planner, incident commander, recovery mode and sanitized diagnostics.
- Platform health center for API, database, queue workers, storage, agents, integrations and delayed jobs.

## Game, Egg and resource management
- Game catalog with game-specific dashboards and validated installers.
- Minecraft: Vanilla, Paper, Purpur, Spigot, Fabric, Forge and NeoForge, plus compatible plugins/mods/modpacks.
- FiveM: FXServer/artifacts, ESX, QBCore, Qbox and compatible resources/scripts/maps.
- Terraria: Vanilla/tModLoader and matching mods.
- Resource metadata: game, platform, loader/framework, version, dependencies and source.
- Automatically select the best compatible stable version; manual override/pinning; batch preview; source verification; integrity checks; backup/rollback where supported.
- Installed item manager, game configuration studio, update center, templates/cloning with secrets excluded, compatibility tests.
- Server creation wizard with validation, capacity checks, install progress, logs and retry.

## Store, billing and business
- Hosting store, plans, comparison, upgrades, renewals, coupons, invoices and notifications.
- Custom plan calculator: base price + RAM + CPU allocation + storage with admin-controlled rates, limits and increments.
- Resource upgrade center with capacity validation before applying changes.
- PKR, INR and USD pricing/display options; per-currency prices; optional exchange-rate conversion and explicit repricing rules.
- Reseller/business center, tenant separation, wholesale pricing, quotas, commissions, invoices and custom branding.
- Loyalty/referrals/rewards with eligibility and abuse controls.
- Refund/dispute workflow, transaction reconciliation, evidence/deadlines, idempotent payment webhooks and duplicate-payment protection.
- Capacity/pricing simulator, sales/subscription analytics, estimated margins and forecasts only when sufficient data exists.
- Provision only after payment verification and capacity validation.
- CPU allocation must be explained as a limit, not guaranteed physical cores.

## Discord Bot Center
- OAuth-based linking, bot configuration, commands, roles/channels, runtime/Egg selection, deployment, logs, monitoring and automation.
- Server, ticket, billing and maintenance notifications.
- Encrypt/mask tokens; never log secrets; no bypassing Discord authorization.

## Automation and AI
- Workflow builder with triggers, conditions, actions, schedules, retries, cooldowns, loop prevention, dry-run, logs and kill switch.
- Crash notification/log collection/safe restart suggestions; scheduled backup verification.
- AI diagnostics for crash logs, plugin conflicts, FiveM errors, bottlenecks and config suggestions.
- Confidence/risk indicators; read-only by default; approval before destructive actions.
- Resource optimization recommendations; no paid upgrades or billing changes without approval.
- In-panel, Discord and email notifications with preferences, retries, delivery history and deduplication.

## Infrastructure, backups and recovery
- Backup vault with schedules, retention, local/remote storage, checksums, encryption, isolated restore tests and recovery readiness.
- Pre-update backups, production restore approval and immutable backups where storage supports them.
- Node registry, locations, supported games, health, capacity, smart placement, reservations, heartbeat, maintenance drain and migration.
- Placement checks for CPU/RAM/disk, game/image, network allocation, region, restrictions and node health.
- Storage/file queues, integrity, scoped access, orphan review and live/backup separation.
- Disaster recovery drills in isolated environments.
- Status page, incidents, planned maintenance, notifications and optional read-only mode.
- Panel maintenance does not automatically stop game servers.
- Network health, allocation/port checks, latency measurements and firewall integration where available.

## Developer ecosystem
- Scoped API keys, expiry/revocation, rate limits, audit, docs, versioning and test sandbox.
- Signed webhooks with timestamps/replay protection, retries and delivery history.
- Extension SDK with permission manifests, sandboxing where supported, signatures, compatibility/versioning, staged publishing, tests and rollback.
- Marketplace for extensions/connectors, free/paid/subscription options where supported, reviews, moderation, entitlement checks and refunds.
- Automated adapter/game/API regression tests.
- Release management, changelogs, compatibility matrix, staged rollout, feature flags and rollback.

## Security, support and customer experience
- Tenant isolation across provider/reseller/customer boundaries; encrypted tenant-scoped credentials and cross-tenant authorization tests.
- Least-privilege roles, 2FA where supported, session management, suspicious activity detection, malware-scanning integrations and abuse appeals.
- Customer support tickets, knowledge base and Discord notifications.
- Customer account center: profile, security, sessions, servers, billing, activity and ownership transfer.
- Global search and reports for customers, servers, Eggs, resources, orders and nodes; filters, scheduled reports, CSV and sensitive-field redaction.
- Referral abuse checks, deletion preview/export and audited admin access.

## Delivery rules
- A planned feature is not implemented until built, tested and documented.
- Never claim universal support without verifying the target API, version, permissions and license terms.
- Unknown capabilities must not be displayed as working.
- Never commit credentials or emit them in logs.
- Destructive and billing actions need server-side authorization, idempotency and audit trails.