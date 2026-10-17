# One-command launch

From the repository root in GitHub Codespaces:

    git pull
    bash ./nexus

The launcher starts the Python backend, initializes SQLite, checks the health endpoint and prints two URLs: **Installer GUI** and **Dashboard**. Open the Installer GUI URL first. If the browser does not open automatically, open the **Ports** tab and open the actual port printed in the terminal.

The launcher checks whether port 8000 is occupied; if so, it tries the next available port. For a first-time clone:

    git clone https://github.com/lponpz/Nexus-Panel.git && cd Nexus-Panel && bash ./nexus

The browser installer saves a workspace name. The dashboard supports local server records and connector endpoint records. It does not yet control external hosting panels or install remote game servers. Keep the forwarded port Private; this MVP has no login.
