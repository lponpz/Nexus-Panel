# One-command launch

From the repository root in GitHub Codespaces, run:

    git pull
    bash ./nexus

The launcher starts the Python backend, initializes SQLite, checks /api/health, and prints the dashboard URL. Open port 8000 from the Codespaces Ports tab if the browser does not open automatically.

To clone for the first time:

    git clone https://github.com/lponpz/Nexus-Panel.git && cd Nexus-Panel && bash ./nexus

This is a working local MVP: server records and connector endpoint records can be created and deleted and are stored in SQLite. It is not yet a production panel; no login/authentication or external panel-control adapter is implemented. Keep the Codespaces port private and do not enter API tokens.
