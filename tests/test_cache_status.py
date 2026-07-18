"""Cache status exposes freshness and refresh policy."""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from app import cache_refresh


class CacheStatusTests(unittest.TestCase):
    def test_status_includes_age_and_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            msg_dir = root / "messages-cache"
            msg_dir.mkdir()
            db = msg_dir / "chat.db"
            db.write_bytes(b"x" * 100)
            # Make mtime slightly in the past
            past = time.time() - 120
            import os

            os.utime(db, (past, past))

            logs = root / "logs"
            logs.mkdir()
            meta = {
                "synced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(past)),
                "method": "python",
                "messages_bytes": 100,
            }
            (logs / "cache-last-sync.json").write_text(json.dumps(meta), encoding="utf-8")

            with mock.patch.object(
                cache_refresh, "messages_cache_dir", return_value=msg_dir
            ), mock.patch.object(
                cache_refresh, "contacts_cache_dir", return_value=root / "contacts"
            ), mock.patch.object(
                cache_refresh, "log_dir", return_value=logs
            ), mock.patch.object(
                cache_refresh, "_framework_python_launcher", return_value=(None, None)
            ), mock.patch(
                "app.settings.get_settings", return_value={"cache_sync_method": "python"}
            ), mock.patch(
                "app.runtime_info.runtime_status", return_value={"fda_target": None}
            ):
                status = cache_refresh.cache_status()

            self.assertTrue(status["messages_cache_exists"])
            self.assertEqual(status["messages_cache_bytes"], 100)
            self.assertEqual(status["last_sync_method"], "python")
            self.assertGreaterEqual(status["last_sync_age_seconds"], 100)
            self.assertFalse(status["refresh_policy"]["scheduled"])
            self.assertTrue(status["refresh_policy"]["on_manual_sync"])
            self.assertIn("Not on a timer", status["refresh_policy"]["summary"])


if __name__ == "__main__":
    unittest.main()
