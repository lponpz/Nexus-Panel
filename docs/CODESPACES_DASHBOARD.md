# Dashboard port in Codespaces

Run the one-command launcher from the repository root:

```bash
bash ./nexus
```

It starts the static frontend dashboard on port 8000 (or `NEXUS_PORT` if set), prints the Codespaces forwarded URL, and opens the terminal Control Center. The dashboard server runs in the background.

In Codespaces, the configured port 8000 is labeled **Nexus Panel Dashboard** and requests the browser to open when forwarded. If it does not open automatically, open the **Ports** tab in VS Code/Codespaces and click the forwarded port URL. Outside Codespaces, visit `http://localhost:8000`.

This serves the current static frontend only. Authentication, database, backend APIs, panel installation and actual server operations are not implemented yet. Do not expose a production service publicly using this development server.
