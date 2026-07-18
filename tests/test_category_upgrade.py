"""Ensure conversation categories survive schema upgrades and chat_id rebinds."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path


class CategoryUpgradeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name) / "data"
        self.data.mkdir(parents=True)
        os.environ["THREAD_LEDGER_DATA"] = str(self.data)
        # Fresh imports so paths pick up the temp data dir.
        import importlib

        import app.categories as categories
        import app.migrations as migrations

        importlib.reload(categories)
        importlib.reload(migrations)
        self.categories = categories
        self.migrations = migrations

    def tearDown(self) -> None:
        self.tmp.cleanup()
        os.environ.pop("THREAD_LEDGER_DATA", None)

    def test_categories_survive_migrations(self) -> None:
        self.categories.set_category(101, "business", chat_guid="iMessage;-;+15550101")
        self.categories.set_category(202, "personal", chat_guid="iMessage;-;+15550202")
        self.categories.set_category(303, "ignore", chat_guid="iMessage;-;+15550303")
        before = self.categories.count_rows()
        self.assertEqual(before, 3)

        # Pretend we are on an old schema so migrations re-run transforms.
        state = {
            "schema_version": 0,
            "last_app_version": "1.0.0",
            "category_row_count": before,
        }
        (self.data / "install_state.json").write_text(
            __import__("json").dumps(state), encoding="utf-8"
        )

        result = self.migrations.run_migrations()
        self.assertEqual(result["category_row_count"], 3)
        self.assertEqual(self.categories.count_rows(), 3)
        all_rows = self.categories.get_all()
        self.assertEqual(all_rows[101]["category"], "business")
        self.assertEqual(all_rows[202]["category"], "personal")
        self.assertEqual(all_rows[303]["category"], "ignore")
        self.assertTrue(list((self.data / "backups").glob("categories-*.db")))

    def test_guid_rebind_keeps_category(self) -> None:
        self.categories.set_category(10, "business", chat_guid="guid-abc")
        resolved = self.categories.resolve_for_thread(99, chat_guid="guid-abc")
        self.assertIsNotNone(resolved)
        assert resolved is not None
        self.assertEqual(resolved["category"], "business")
        self.assertEqual(resolved["chat_id"], 99)
        self.assertNotIn(10, self.categories.get_all())

    def test_check_constraint_migration_preserves_rows(self) -> None:
        db = self.categories.categories_db_path()
        conn = sqlite3.connect(db)
        conn.execute(
            """
            CREATE TABLE thread_categories (
              chat_id INTEGER PRIMARY KEY,
              chat_guid TEXT,
              category TEXT NOT NULL CHECK (category IN ('business','personal','ignore')),
              notes TEXT,
              updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            "INSERT INTO thread_categories (chat_id, chat_guid, category) VALUES (1, 'g1', 'business')"
        )
        conn.execute(
            "INSERT INTO thread_categories (chat_id, chat_guid, category) VALUES (2, 'g2', 'personal')"
        )
        conn.commit()
        conn.close()

        # Opening the DB runs _migrate_schema.
        rows = self.categories.get_all()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["category"], "business")
        self.assertEqual(rows[2]["category"], "personal")


if __name__ == "__main__":
    unittest.main()
