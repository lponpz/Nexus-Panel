# Nexus Panel — Theme & Blueprint Studio

## Goal
Let a hosting provider customize a supported existing panel with a Nexus-inspired theme, export a reusable configuration blueprint, or download/self-host the full Nexus Panel source.

## Studio entry points
1. **Theme Studio** — accent palette, card radius, density, brand label, glow, preset preview, JSON export and reset.
2. **Panel Converter** — select Pterodactyl, Pelican, AMP or a custom adapter; select theme-only, white-label, blueprint or unified-dashboard goal; show a compatibility plan.
3. **Blueprint Export** — export theme and connector intent in a versioned JSON file. Never include secrets.
4. **Full Panel Download** — download the current repository snapshot as ZIP for inspection/self-hosting. A production release should provide versioned releases, checksums/signatures, a license file and installation/upgrade documentation.

## Current prototype behavior
- Browser-local theme preview.
- JSON theme and blueprint downloads.
- Compatibility-plan summary (demo only).
- Link to the repository ZIP.
- Responsive desktop/mobile layout.

## Not implemented yet
- No login, database, backend or live panel connection.
- No direct modification of Pterodactyl, Pelican or AMP.
- No automatic installation, migration, theme injection or production package installer.
- No live compatibility detection. User-selected panel is only used to prepare a plan.

## Safe implementation sequence
1. Define connector capability manifest: panel name/version, supported theme hooks, APIs, permissions and license constraints.
2. Add read-only connection test and compatibility report; encrypt credentials server-side and never expose them to browser code/logs.
3. Export/import versioned, schema-validated blueprints; reject secrets, unknown dangerous fields and cross-tenant references.
4. Add adapter-specific theme installation only where officially supported; require backup/export, preview/diff, explicit confirmation and rollback.
5. Package full panel using tagged releases, install/upgrade scripts, environment validation, checksums/signatures, migration backup and recovery instructions.
6. Add automated compatibility tests for supported panel versions and mobile/desktop UI regression tests.

## Security and licensing rules
- Never ask for or store a panel's root password in a theme file.
- Use least-privilege, scoped API credentials; encrypt at rest and redact logs.
- A blueprint must not contain API tokens, passwords, private keys, customer data or server secrets.
- Respect upstream licenses, trademarks, documented APIs and panel customization rules.
- Unsupported operations must be disabled with a clear reason, not falsely reported as successful.
- Theme changes must not bypass panel permissions, authentication or security checks.
- Full-panel downloads must state the applicable license and third-party components.
