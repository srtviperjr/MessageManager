# MessageManager 1.0

Local macOS app that reads your Messages database, lets you tag conversations (business, personal, ignore, or custom categories), and generates summaries on demand.

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

- Browse recent conversations from your local Messages DB (read-only copy)
- Resolve phone numbers / emails to names from macOS Contacts
- Filter by business / personal / uncategorized / ignore / custom categories
- Search by name, phone/email, or preview text
- Persist categories in `data/categories.db` (local only)
- Summarize a conversation with a local extractive summarizer
- Optional **Apple Intelligence** summaries on Apple Silicon (Settings)
- Built-in update checks against GitHub Releases
- Automatic data migrations when upgrading versions

## Apple Intelligence summaries (Apple Silicon)

Summaries stay on-device via a Shortcuts bridge.

1. On an **Apple Silicon** Mac (M1 or later), open **Shortcuts**
2. Create a shortcut named exactly **`MessageManager Summarize`**
3. Add these actions:
   - **Receive** Text input from nowhere (or Shortcut Input)
   - **Summarize** (Apple Intelligence / Writing Tools) on that text
   - **Stop and Output** the summary
4. In **Settings**, turn on **Apple Intelligence**
5. Open a conversation and click **Summarize**

On Intel Macs the toggle can still be enabled for later use, but AI summaries will explain that Apple Silicon is required and extractive mode remains available when the toggle is off.

Settings are stored under Application Support when using the packaged app (`~/Library/Application Support/MessageManager/`), or `data/` in development.

## Install with the macOS package (recommended)

### 1. Build the installer

```bash
cd ~/Documents/imessage-categorizer
chmod +x scripts/create-macos-app.sh scripts/create-macos-installer.sh scripts/macos/launch.sh scripts/macos/pkg/postinstall
./scripts/create-macos-installer.sh
```

Creates:

- `dist/MessageManager.app`
- `dist/MessageManager.pkg` (filename is unversioned; version lives inside the package metadata)

### 2. Install on a Mac

1. Double-click `MessageManager.pkg`
2. Complete the installer (app is always installed to **/Applications/MessageManager.app**)
3. If Python 3.9+ is missing, the installer downloads and installs Python 3.12 from python.org, then installs app dependencies
4. When prompted, grant **Full Disk Access** to **MessageManager**
5. Launch MessageManager from Applications

### Gatekeeper (“untrusted developer”) prompts

macOS blocks unsigned downloads by default. **There is no supported way to skip this for public GitHub downloads without Apple notarization.**

| Distribution | What users see |
|---|---|
| Unsigned `.pkg` from GitHub (current default) | First open needs right-click → **Open** (or System Settings → Privacy & Security → Open Anyway) |
| Signed + notarized `.pkg` | Normal double-click install |

To ship a notarized installer you need an [Apple Developer Program](https://developer.apple.com/programs/) membership (~$99/year), then:

```bash
# One-time: create Developer ID Application + Developer ID Installer certs in Xcode/developer.apple.com
# One-time: store notary credentials
xcrun notarytool store-credentials notary-profile \
  --apple-id "you@example.com" --team-id "TEAMID" --password "app-specific-password"

export CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)"
export INSTALLER_IDENTITY="Developer ID Installer: Your Name (TEAMID)"
export NOTARY_PROFILE="notary-profile"
./scripts/create-macos-installer.sh
```

**Full Disk Access** is separate from Gatekeeper — macOS always requires that permission for reading Messages, even with a notarized app.

### 3. Updates

On every launch, MessageManager checks GitHub Releases and prompts if a newer version is available. You can also use **Settings → Updates**. Choosing install downloads `MessageManager.pkg` and opens it; finish the installer, then quit and reopen so migrations can apply.

To publish a release:

```bash
gh release create v1.0.6 dist/MessageManager.pkg --title "MessageManager 1.0.6" --notes "Release 1.0.6"
```

### Dev / direct `.app` copy

```bash
./scripts/create-macos-app.sh
```

Then copy `dist/MessageManager.app` to Applications. The other Mac needs:

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
