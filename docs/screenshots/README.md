# Screenshots

These images use **fictional demo data** from `docs/demo.html` and `docs/demo-settings.html`, not a live Messages export.

| File | Description |
|---|---|
| `app-icon.png` | MessageManager icon (green bubble + magnifying glass) |
| `conversation-view.png` | Main UI: conversation list, category chips, summary, messages |
| `settings.png` | Settings modal: updates, Apple Intelligence, defaults, categories |

To regenerate:

```bash
python3 -m http.server 8765 --bind 127.0.0.1
# open http://127.0.0.1:8765/docs/demo.html and capture screenshots
```
