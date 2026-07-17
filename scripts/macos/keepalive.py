#!/usr/bin/env python3
"""Persistent control window for the packaged MessageManager.app launcher.

AppleScript display dialogs are unreliable from a shell-based .app (they can
fail or dismiss without user action). A Tk window stays until Quit.
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request


def request_shutdown(base_url: str) -> None:
    url = base_url.rstrip("/") + "/api/shutdown"
    req = urllib.request.Request(url, method="POST", data=b"")
    try:
        urllib.request.urlopen(req, timeout=3)
    except (urllib.error.URLError, TimeoutError, OSError):
        pass


def main() -> int:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8741"
    log_dir = sys.argv[2] if len(sys.argv) > 2 else ""

    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        print("tkinter unavailable", file=sys.stderr)
        return 2

    root = tk.Tk()
    root.title("MessageManager")
    root.geometry("460x210")
    root.minsize(400, 180)
    root.resizable(True, True)

    # Bring to front once, then leave alone so it doesn't steal focus from the browser.
    root.lift()
    root.attributes("-topmost", True)
    root.after(400, lambda: root.attributes("-topmost", False))

    frame = ttk.Frame(root, padding=16)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="MessageManager is running", font=("", 14, "bold")).pack(
        anchor="w"
    )
    ttk.Label(
        frame,
        text=(
            "Use the app in your browser.\n"
            "Keep this window open — click Quit MessageManager to stop the server."
        ),
        justify="left",
        wraplength=420,
    ).pack(anchor="w", pady=(8, 0))

    if log_dir:
        ttk.Label(
            frame,
            text=f"Logs: {log_dir}",
            justify="left",
            wraplength=420,
        ).pack(anchor="w", pady=(10, 0))

    def quit_app() -> None:
        request_shutdown(base_url)
        root.destroy()

    btn = ttk.Button(frame, text="Quit MessageManager", command=quit_app)
    btn.pack(anchor="e", pady=(16, 0))

    root.protocol("WM_DELETE_WINDOW", quit_app)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
