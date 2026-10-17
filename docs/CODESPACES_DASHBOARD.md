# Dashboard port in Codespaces

Run from the repository root:

    git pull
    bash ./nexus

The launcher starts the SQLite-backed Python application on port 8000 (or NEXUS_PORT if set), checks the health endpoint, and prints the Codespaces URL. If the browser does not open automatically, open the Ports tab and click the forwarded URL. Outside Codespaces, use http://localhost:8000.

The app has a working local database and APIs for creating/removing server records and saving/removing connector endpoint records. The dashboard shows actual saved counts and local activity events.

**Keep the forwarded port Private.** This MVP does not yet implement login/authentication, live Pterodactyl/Pelican/AMP adapters, game process controls, backups, or billing. Saved connector endpoints are not tested and do not imply a real connection. Do not enter API tokens or expose this development server publicly.
