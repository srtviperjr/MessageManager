"""Quick health access must not copy or COUNT the Messages database."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import imessage


class AccessStatusQuickTests(unittest.TestCase):
    def test_quick_reads_cache_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            db = cache / "chat.db"
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE chat (ROWID INTEGER PRIMARY KEY)")
            conn.execute("INSERT INTO chat DEFAULT VALUES")
            conn.commit()
            conn.close()

            missing = cache / "missing-live.db"
            with mock.patch.object(imessage, "_messages_cache_dir", return_value=cache), mock.patch.object(
                imessage, "CHAT_DB", missing
            ), mock.patch.object(imessage, "connect_messages") as connect_mock:
                status = imessage.access_status(quick=True)

            connect_mock.assert_not_called()
            self.assertTrue(status["readable"])
            self.assertTrue(status["using_cache"])
            self.assertIsNone(status["available_threads"])

    def test_full_status_still_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            db = cache / "chat.db"
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE chat (ROWID INTEGER PRIMARY KEY)")
            conn.executemany("INSERT INTO chat DEFAULT VALUES", [()] * 3)
            conn.commit()
            conn.close()

            def fake_connect():
                c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
                c.row_factory = sqlite3.Row
                return c, db

            with mock.patch.object(imessage, "_messages_cache_dir", return_value=cache), mock.patch.object(
                imessage, "connect_messages", side_effect=fake_connect
            ), mock.patch.object(imessage, "cleanup_temp_db"):
                status = imessage.access_status(quick=False)

            self.assertTrue(status["readable"])
            self.assertEqual(status["available_threads"], 3)


if __name__ == "__main__":
    unittest.main()
