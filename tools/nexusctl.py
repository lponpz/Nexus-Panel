#!/usr/bin/env python3
"""Nexus Panel Control Center TUI scaffold.

Safe by design: this interface does not run system-changing operations until a
verified backend/adapter is configured. Standard-library only.
"""
from __future__ import annotations

import curses
import sys
import textwrap
from datetime import datetime

ACTIONS = [
    ("Install panel", "Prepare a fresh installation on a supported host."),
    ("Update panel", "Check compatibility, create a backup, then update."),
    ("Reinstall panel", "Reinstall after an explicit backup and review."),
    ("Delete panel", "Destructive: requires typed confirmation and recovery review."),
    ("Add user", "Create a regular panel user with least-privilege access."),
    ("Add owner", "Grant owner privileges only after strong identity verification."),
    ("Backups & recovery", "Inspect backup status and recovery options."),
    ("Panel connectors", "Configure supported adapters and test capabilities."),
    ("Logs & health", "View sanitized diagnostics and operation history."),
    ("Exit", "Close the control center."),
]
PANELS = ["Nexus Panel", "Pterodactyl", "Pelican Panel", "AMP by CubeCoders", "Custom adapter"]
BLUE = 1
MUTED = 2
ACTIVE = 3
GOOD = 4
WARN = 5

def safe_add(stdscr, y, x, text, attr=0, width=None):
    h, w = stdscr.getmaxyx()
    if y < 0 or y >= h or x >= w:
        return
    available = max(0, w - x - 1)
    if width is not None:
        available = min(available, width)
    try:
        stdscr.addnstr(y, x, str(text), available, attr)
    except curses.error:
        pass

def center(stdscr, y, text, attr=0):
    _, w = stdscr.getmaxyx()
    safe_add(stdscr, y, max(1, (w - len(text)) // 2), text, attr)

def message_screen(stdscr, title, lines, warning=False):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    safe_add(stdscr, 1, 2, "NEXUS PANEL  /  CONTROL CENTER", curses.color_pair(BLUE) | curses.A_BOLD)
    safe_add(stdscr, 3, 3, title, curses.A_BOLD)
    y = 5
    for line in lines:
        for wrapped in textwrap.wrap(line, max(20, w - 8)) or [""]:
            if y < h - 3:
                safe_add(stdscr, y, 4, wrapped, curses.color_pair(WARN if warning else MUTED))
                y += 1
    safe_add(stdscr, h - 2, 2, "Press any key to return", curses.A_DIM)
    stdscr.refresh()
    stdscr.getch()

def choose_panel(stdscr, current):
    idx = PANELS.index(current) if current in PANELS else 0
    while True:
        stdscr.erase()
        safe_add(stdscr, 1, 2, "NEXUS PANEL  /  SELECT TARGET", curses.color_pair(BLUE) | curses.A_BOLD)
        safe_add(stdscr, 3, 2, "Choose the panel this action is intended for:", curses.A_BOLD)
        for i, name in enumerate(PANELS):
            attr = curses.color_pair(ACTIVE) | curses.A_BOLD if i == idx else curses.color_pair(MUTED)
            safe_add(stdscr, 5 + i, 4, ("❯ " if i == idx else "  ") + name, attr)
        safe_add(stdscr, len(PANELS) + 7, 2, "↑/↓ Navigate  •  Enter Select  •  Esc Back", curses.A_DIM)
        stdscr.refresh()
        key = stdscr.getch()
        if key in (curses.KEY_UP, ord("k")):
            idx = (idx - 1) % len(PANELS)
        elif key in (curses.KEY_DOWN, ord("j")):
            idx = (idx + 1) % len(PANELS)
        elif key in (10, 13, curses.KEY_ENTER):
            return PANELS[idx]
        elif key == 27:
            return current

def run_action(stdscr, action, panel):
    if action == "Exit":
        return False
    if action == "Panel connectors":
        message_screen(stdscr, "Panel connectors", [
            f"Selected target: {panel}",
            "The adapter registry and live API authentication are not configured yet.",
            "Next production step: validate endpoint, test scoped credentials, detect version,",
            "then discover capabilities. No credentials are requested by this prototype.",
        ])
        return True
    if action == "Backups & recovery":
        message_screen(stdscr, "Backups & recovery", [
            f"Selected target: {panel}",
            "No backup provider is connected yet.",
            "Production workflow: inspect backup destination and integrity, verify restore readiness,",
            "and require explicit approval before a production restore.",
        ])
        return True
    if action == "Logs & health":
        message_screen(stdscr, "Logs & health", [
            "Local TUI started successfully.",
            f"Target selection: {panel}",
            "No live service, database, or panel API health data is available yet.",
            "Production logs must redact tokens, passwords, session cookies and personal data.",
        ])
        return True
    destructive = action in ("Delete panel", "Reinstall panel", "Update panel")
    role_action = action in ("Add user", "Add owner")
    lines = [
        f"Action: {action}",
        f"Target: {panel}",
        "",
        "STATUS: PLANNING ONLY — no system changes were made.",
        "The production executor is intentionally not wired up yet.",
    ]
    if action == "Install panel":
        lines += ["Planned checks: OS/runtime support, disk/RAM, domain/HTTPS, database, queue,",
                  "ports, secrets setup, installer signature and recovery plan."]
    elif action == "Update panel":
        lines += ["Planned checks: current version, target version, compatibility, maintenance window,",
                  "verified backup, migration preview, health checks and rollback."]
    elif action == "Reinstall panel":
        lines += ["Planned checks: identify preserved data, verify off-host backup, preview data loss,",
                  "require typed confirmation and record an audit event."]
    elif action == "Delete panel":
        lines += ["Planned checks: ownership, dependent services, data/export preview, verified backup,",
                  "typed confirmation, separate confirmation of irreversible data deletion."]
    elif action == "Add user":
        lines += ["Planned fields: username/email, invite flow, role, tenant scope and expiry.",
                  "Passwords should be set through a secure invite/reset flow, not terminal logs."]
    elif action == "Add owner":
        lines += ["High-risk privilege grant: require existing-owner approval, MFA/identity check,",
                  "reason, audit event and optionally two-person approval. Never bypass authorization."]
    if destructive:
        lines += ["", "Production safety gate: backup + review + explicit confirmation required."]
    if role_action:
        lines += ["", "Role changes must be authorized by an existing permitted owner/admin."]
    message_screen(stdscr, action, lines, warning=destructive or action == "Add owner")
    return True

def main(stdscr):
    curses.curs_set(0)
    curses.use_default_colors()
    curses.init_pair(BLUE, curses.COLOR_CYAN, -1)
    curses.init_pair(MUTED, curses.COLOR_WHITE, -1)
    curses.init_pair(ACTIVE, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(GOOD, curses.COLOR_GREEN, -1)
    curses.init_pair(WARN, curses.COLOR_YELLOW, -1)
    selected = 0
    panel = "Nexus Panel"
    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        safe_add(stdscr, 1, 2, "✦ NEXUS PANEL  /  CONTROL CENTER", curses.color_pair(BLUE) | curses.A_BOLD)
        safe_add(stdscr, 1, max(3, w - 25), "● SAFE DEMO MODE", curses.color_pair(WARN) | curses.A_BOLD)
        safe_add(stdscr, 3, 2, f"Target: {panel}   •   {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z')}", curses.color_pair(MUTED))
        safe_add(stdscr, 5, 2, "MANAGEMENT", curses.A_BOLD)
        menu_y = 6
        for i, (name, desc) in enumerate(ACTIONS):
            if menu_y + i >= h - 5:
                break
            attr = curses.color_pair(ACTIVE) | curses.A_BOLD if i == selected else curses.color_pair(MUTED)
            safe_add(stdscr, menu_y + i, 3, f"{i + 1:>2}  {name}", attr, min(26, w // 2))
            if w > 62:
                safe_add(stdscr, menu_y + i, min(32, w - 5), desc, curses.color_pair(MUTED), w - min(34, w - 5) - 2)
        footer = "1-9: Open option  •  ↑/↓ + Enter: Select  •  P: Target  •  0/Q: Exit"
        safe_add(stdscr, h - 3, 2, "─" * max(1, w - 4), curses.color_pair(BLUE))
        safe_add(stdscr, h - 2, 2, footer, curses.A_DIM)
        safe_add(stdscr, h - 1, 2, "Prototype only: all system-changing operations are disabled.", curses.color_pair(WARN))
        stdscr.refresh()
        key = stdscr.getch()
        if key in (curses.KEY_UP, ord("k")):
            selected = (selected - 1) % len(ACTIONS)
        elif key in (curses.KEY_DOWN, ord("j")):
            selected = (selected + 1) % len(ACTIONS)
        elif key in (ord("p"), ord("P")):
            panel = choose_panel(stdscr, panel)
        elif key in (ord("q"), ord("Q"), ord("0"), 27):
            return
        elif ord("1") <= key <= ord("9"):
            selected = key - ord("1")
            if not run_action(stdscr, ACTIONS[selected][0], panel):
                return
        elif key in (10, 13, curses.KEY_ENTER):
            if not run_action(stdscr, ACTIONS[selected][0], panel):
                return

if __name__ == "__main__":
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("Nexus Panel Control Center needs an interactive terminal.")
        print("Run: python3 tools/nexusctl.py")
        raise SystemExit(2)
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
