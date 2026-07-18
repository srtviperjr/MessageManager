# MessageManager — Requirements

Version covered: **1.0.10**

This document describes product requirements for MessageManager as implemented today, plus constraints for future work.

## 1. Purpose

MessageManager is a **local-only macOS application** that helps users:

1. Browse recent iMessage / SMS conversations from the on-device Messages database  
2. Categorize conversations (business, personal, ignore, or custom)  
3. Generate on-device summaries of a conversation for a chosen day range  

It is **not** a messaging client: it does not send, edit, delete, or sync messages.

## 2. Stakeholders & environment

| Item | Requirement |
|---|---|
| Platform | macOS **13.0+** |
| Hardware | Intel or Apple Silicon; Apple Intelligence summaries require **Apple Silicon (M1+)** |
| Identity | Single local macOS user account with Messages history |
| Network | Optional — needed for GitHub update checks and (first install) Python bootstrap |

## 3. Functional requirements

### 3.1 Conversations

| ID | Requirement | Status |
|---|---|---|
| F-C1 | Read Messages data from a **read-only copy** of `~/Library/Messages/chat.db` (never write to Apple’s DB) | Done |
| F-C2 | List conversations with display name, last activity, and preview text | Done |
| F-C3 | Load by **count** (default 50; max = available) or by **activity window** (months/years) | Done |
| F-C4 | Stream load progress in the status bar | Done |
| F-C5 | Search loaded conversations by name, handle, or preview | Done |
| F-C6 | On select, load recent messages (default 10; load +100 or all) | Done |
| F-C7 | Collapse load controls after conversations are loaded | Done |

### 3.2 Contacts

| ID | Requirement | Status |
|---|---|---|
| F-N1 | Resolve phone numbers / emails to Contacts names when available | Done |
| F-N2 | Fall back to the raw handle when Contacts are unavailable or timed out | Done |
| F-N3 | Refresh Contacts via the same Full Disk Access path used for Messages (launcher cache) | Done (1.0.8) |

### 3.3 Categories

| ID | Requirement | Status |
|---|---|---|
| F-G1 | Built-in categories: Business, Personal, Uncategorized, Ignore | Done |
| F-G2 | Persist category assignments locally | Done (`categories.db`) |
| F-G3 | Filter / summary chips for category counts in the main pane | Done |
| F-G4 | Change category from conversation header / flyout even when already set | Done |
| F-G5 | User-defined custom categories | Done |
| F-G6 | Enable/disable categories; hide selected categories from the default All view | Done |
| F-G7 | **Category durability (critical):** assignments must survive every app upgrade | Done (1.0.10) |
| F-G7a | Store categories outside the `.app` bundle (`Application Support/.../data/categories.db`) | Done |
| F-G7b | Installer/postinstall must never delete or overwrite `categories.db` / `data/backups` | Done |
| F-G7c | Before schema migrations, snapshot `categories.db` under `data/backups/` | Done |
| F-G7d | After each migration, verify row count did not drop; restore from backup on loss | Done |
| F-G7e | Schema transforms must copy/transform rows — never wipe the table | Done |
| F-G7f | Resolve categories by `chat_guid` when Messages reassigns `chat_id` | Done |

### 3.4 Summaries

| ID | Requirement | Status |
|---|---|---|
| F-S1 | Local **extractive** summarizer describing overall discussion | Done |
| F-S2 | Configurable summary day range | Done |
| F-S3 | Optional **Apple Intelligence** via user Shortcut on Apple Silicon | Done |
| F-S4 | When AI is enabled, do not silently fall back to extractive on failure | Done |
| F-S5 | Copy summary to clipboard | Done |
| F-S6 | Show method used (extractive vs Apple Intelligence) | Done |

### 3.5 Settings & operations

| ID | Requirement | Status |
|---|---|---|
| F-O1 | Settings for auto-load, load mode, defaults for messages/summary days, categories, AI | Done |
| F-O2 | In-app Logs viewer | Done |
| F-O3 | Quit stops the local server | Done |
| F-O4 | Detect Apple Silicon vs Intel in the status bar | Done |
| F-O5 | Full Disk Access guidance only when Messages are unreadable (no repeated nag if OK) | Done |

### 3.6 Packaging & updates

| ID | Requirement | Status |
|---|---|---|
| F-P1 | Clickable `.app` with Dock icon | Done |
| F-P2 | Installer `.pkg` named `MessageManager.pkg` (version in metadata, not filename) | Done |
| F-P3 | Install to `/Applications/MessageManager.app` | Done |
| F-P4 | Bootstrap Python 3.9+ / deps when missing | Done |
| F-P5 | Check GitHub Releases on launch; prompt to download/install update | Done |
| F-P6 | Run data migrations on upgrade | Done |

## 4. Non-functional requirements

| ID | Requirement |
|---|---|
| N-1 | Server binds to `127.0.0.1` only |
| N-2 | Message content stays on-device; no cloud upload of conversations |
| N-3 | Outbound HTTPS limited to GitHub Releases (updates) and optional python.org (install bootstrap) |
| N-4 | Packaged app must obtain Full Disk Access as the **app bundle** executable |
| N-5 | Rebuild `dist/MessageManager.app` after product file changes (see project rule) |

## 5. System & dependency requirements

### End-user (packaged)

- macOS 13+
- Messages database present for the logged-in user
- **Full Disk Access** for **MessageManager**
- Python 3.9+ (installer prefers/installs python.org **3.12** when needed)
- Network for update checks (optional but recommended)

### Developer

- Same macOS / FDA expectations for the process that launches Python (Terminal, Cursor, etc.)
- Python packages in `requirements.txt`: FastAPI, Uvicorn, Pydantic, certifi

### Apple Intelligence (optional)

- Apple Silicon Mac
- User-created Shortcut (default name: `MessageManager Summarize`) using Summarize / Writing Tools
- `shortcuts` CLI available

## 6. Data locations

| Data | Packaged path |
|---|---|
| Categories / settings / migrations | `~/Library/Application Support/MessageManager/data/` |
| Messages DB cache | `…/MessageManager/messages-cache/` |
| Contacts DB cache | `…/MessageManager/contacts-cache/` |
| Logs | `…/MessageManager/logs/` |
| Venv | `…/MessageManager/venv/` |

Dev defaults use project `data/` and `logs/` unless `THREAD_LEDGER_DATA` is set.

## 7. Permissions model

1. User grants **Full Disk Access** to MessageManager.app.  
2. Native launcher (Mach-O) copies Messages + AddressBook into Application Support.  
3. Python / Uvicorn reads those caches (and local category/settings DBs).  
4. UI prompts for FDA only when Messages remain unreadable.

## 8. Out of scope (non-goals)

- Sending or deleting messages  
- iCloud / multi-device management  
- Windows / Linux  
- Cloud accounts, sync, or multi-user sharing  
- Continuous background monitoring of new messages  
- Bundled proprietary LLM weights (AI is via Apple’s on-device tools only)

## 9. Acceptance checks (smoke)

1. Install `MessageManager.pkg` → app appears in **/Applications**.  
2. Grant FDA → relaunch → conversations load; Contacts names resolve when present.  
3. Categorize a conversation; restart app → category persists.  
4. Summarize (extractive); Copy works.  
5. Settings → Check for updates against public GitHub Releases.  
6. Logs button shows launch/server/app logs.
