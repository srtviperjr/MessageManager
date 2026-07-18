"""FDA probe summary prefers Python.app over Terminal."""

from __future__ import annotations

import unittest
from unittest import mock

from app import fda_probe


class FdaProbeSummaryTests(unittest.TestCase):
    def test_recommends_python_over_terminal(self) -> None:
        targets = [
            {"id": "app", "ok": False},
            {"id": "python", "ok": True},
            {"id": "server", "ok": False, "informational": True},
            {"id": "terminal", "ok": True},
        ]
        with mock.patch.object(fda_probe, "probe_app", return_value=targets[0]), mock.patch.object(
            fda_probe, "probe_python", return_value=targets[1]
        ), mock.patch.object(fda_probe, "probe_server", return_value=targets[2]), mock.patch.object(
            fda_probe, "probe_terminal", return_value=targets[3]
        ):
            result = fda_probe.probe_all(include_terminal=True)

        self.assertEqual(result["summary"]["recommended"], "python")
        self.assertTrue(result["summary"]["clean_path_ready"])
        self.assertTrue(result["summary"]["python_ok"])

    def test_server_probe_is_informational(self) -> None:
        with mock.patch.object(
            fda_probe, "_try_read_messages_db", return_value=(False, "Permission denied")
        ):
            result = fda_probe.probe_server()
        self.assertTrue(result.get("informational"))
        self.assertFalse(result.get("ok"))
        self.assertIn("Expected", result.get("detail") or "")


if __name__ == "__main__":
    unittest.main()
