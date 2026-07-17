# MessageManager

Local web app that reads your macOS Messages database, lets you tag threads as **business** or **personal**, and generates an **extractive summary** on demand.

## Requirements

- macOS with a Messages database at `~/Library/Messages/chat.db`
- Python 3.9+
- **Full Disk Access** for the app that runs the server (Terminal, iTerm, Cursor, or MessageManager.app)

### Grant Full Disk Access

1. Open **System Settings → Privacy & Security → Full Disk Access**
2. Enable access for the app that launches the server:
   - **MessageManager** if you use the `.app`
   - **Cursor** if you start it from Cursor’s terminal
   - **Terminal** / **iTerm** if you start it from there
3. Fully quit and reopen that app, then launch again

Without this, macOS blocks reads of `chat.db`.

## Setup (development)

```bash
cd ~/Documents/imessage-categorizer
python3 -m pip install --user -r requirements.txt
python3 run.py
```

Open [http://127.0.0.1:8741](http://127.0.0.1:8741).

## Features

- Browse recent message threads from your local Messages DB (read-only copy)
- Resolve phone numbers / emails to names from macOS Contacts
- Filter by business / personal / uncategorized
- Search by name, phone/email, or preview text
- Persist categories in `data/categories.db` (local only)
- Summarize a thread with a local extractive summarizer
- Optional **Apple Intelligence** summaries on Apple Silicon (toggle in the sidebar)

## Apple Intelligence summaries (Apple Silicon)

Summaries stay on-device via a Shortcuts bridge.

1. On an **Apple Silicon** Mac (M1 or later), open **Shortcuts**
2. Create a shortcut named exactly **`MessageManager Summarize`**
3. Add these actions:
   - **Receive** Text input from nowhere (or Shortcut Input)
   - **Summarize** (Apple Intelligence / Writing Tools) on that text
   - **Stop and Output** the summary
4. In the app sidebar, turn on **Apple Intelligence**
5. Open a thread and click **Summarize**

On Intel Macs the toggle can still be enabled for later use, but AI summaries will explain that Apple Silicon is required and extractive mode remains available when the toggle is off.

Settings are stored in `data/settings.json`.

## Install on another Mac (clickable app icon)

### 1. Build the `.app` on this Mac

```bash
cd ~/Documents/imessage-categorizer
chmod +x scripts/create-macos-app.sh scripts/macos/launch.sh
./scripts/create-macos-app.sh
```

That creates / refreshes:

`dist/MessageManager.app`

Rebuild this after app changes before copying it to another Mac.

### 2. Copy it to the other Mac

AirDrop, USB, or shared folder — copy **`MessageManager.app`** into that Mac’s **Applications** folder (or Desktop).

The other Mac needs:

- macOS 13+
- **Python 3.9+ from [python.org](https://www.python.org/downloads/macos/)** (recommended — the built-in `/usr/bin/python3` stub often cannot create a virtual environment)
- Messages + Contacts data for that user account

If launch says it cannot create a virtual environment: install Python from python.org, then reopen MessageManager.

### Logs

When launched as **MessageManager.app**, logs are here:

- `~/Library/Application Support/MessageManager/logs/app.log` — API / summary errors
- `~/Library/Application Support/MessageManager/logs/server.log` — uvicorn server output
- `~/Library/Application Support/MessageManager/logs/launch.log` — app launcher output

In the UI, use the **Logs** button in the status bar to see these paths.

When running with `python3 run.py` from the project folder, logs go under `logs/` in the project (or next to `THREAD_LEDGER_DATA` for the packaged app).

### 3. First launch on the other Mac

1. If macOS blocks it: **right-click → Open** (Gatekeeper)
2. A browser window opens to the app; a small **MessageManager** control window stays open while it runs (use **Quit MessageManager** there, or **Quit** in the browser footer)
3. Grant **Full Disk Access** to **MessageManager**:
   - System Settings → Privacy & Security → Full Disk Access → enable MessageManager
   - Quit the app and open it again
4. Optional Apple Intelligence: create the **MessageManager Summarize** Shortcut (Apple Silicon only), then enable the toggle in the sidebar

Logs and the Python virtualenv live in:

`~/Library/Application Support/MessageManager/`

### Optional: custom Dock icon

In Finder: right-click **MessageManager.app** → **Get Info** → drag any `.icns`/`.png` onto the small icon in the top-left of that window.

## Privacy

- Everything stays on your machine
- The server binds to `127.0.0.1` only
- Categories are stored under `data/` in the project (dev) or under Application Support when launched from the `.app`
- Message content is read from a temporary copy of `chat.db` and never uploaded
