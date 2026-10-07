#!/usr/bin/env python3
"""Offline account inventory tests; all identities and state are synthetic."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import accounts
import checkpoint as cp


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "state"
        self.index = self.root / "accounts.json"

    def register(self, *extra, provider="outlook", account="demo@example.test"):
        return accounts.register(accounts.parser().parse_args([
            "register", "--state-dir", str(self.root), "--provider", provider,
            "--account", account, *extra]))

    def listing(self):
        return accounts.overview(accounts.parser().parse_args([
            "list", "--state-dir", str(self.root)]))

    def checkpoint(self, command, *extra, scope="received"):
        return cp.execute(cp.parser().parse_args([
            command, "--state-dir", str(self.root), "--provider", "outlook",
            "--account", "demo@example.test", "--scope", scope, *extra]),
            cp.timestamp("2026-10-06T14:52:40Z"))

    def begin(self, scope="received"):
        return self.checkpoint("begin", "--since", "2026-10-02T23:00:00Z", scope=scope)

    def complete(self, run):
        self.checkpoint("finish", "--run-id", run["run_id"], "--status", "complete",
                        "--coverage-complete", "--report-ready")

    def test_empty_listing_is_read_only(self):
        self.assertEqual(self.listing(), {"accounts": []})
        self.assertFalse(self.root.exists())

    def test_example_inventory_is_portable_and_unchecked(self):
        example = Path(__file__).resolve().parents[1] / "assets" / "accounts.example.json"
        index = accounts.read_index(example)
        self.assertEqual(set(index), {"version", "accounts"})
        self.assertEqual({item["provider"] for item in index["accounts"]}, set(accounts.PROVIDERS))
        for item in index["accounts"]:
            self.assertEqual(set(item), {"provider", "account", "label", "scopes"})
            self.assertTrue(item["account"].endswith("@example.com"))
            self.assertEqual(item["scopes"], [])
            self.register("--label", item["label"], provider=item["provider"], account=item["account"])
        rows = self.listing()["accounts"]
        self.assertEqual(len(rows), len(index["accounts"]))
        self.assertTrue(all(row["status"] == "not_checked" and row["covered_through"] is None
                            and row["initial_since"] is None for row in rows))
        self.assertEqual(list(self.root.glob("*.json")), [self.index])

    def test_register_normalizes_and_merges_without_dates(self):
        self.register("--scope", "received", "--label", "School", account=" Demo@Example.test ")
        self.register("--scope", "topic", "--scope", "received")
        data = accounts.read_index(self.index)
        self.assertEqual(data["accounts"], [{"provider": "outlook", "account": "demo@example.test",
                                           "label": "School", "scopes": ["received", "topic"]}])
        self.assertEqual(self.index.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)
        self.assertEqual(list(self.root.glob("*.json")), [self.index])

    def test_unchecked_accounts_and_providers_stay_separate(self):
        self.register()
        self.register(provider="gmail")
        self.register(provider="feishu", account="shared@example.test")
        rows = self.listing()["accounts"]
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r["covered_through"] is None and r["status"] == "not_checked" for r in rows))

    def test_existing_checkpoints_join_without_migration(self):
        run = self.begin()
        self.complete(run)
        path = Path(run["state_path"])
        before = path.read_bytes()
        self.register("--scope", "received")
        row = self.listing()["accounts"][0]
        self.assertEqual(row["covered_through"], run["window_end"])
        self.assertEqual(row["status"], "complete")
        self.assertEqual(path.read_bytes(), before)

    def test_listing_refreshes_live_and_keeps_partial_boundary(self):
        self.register("--scope", "received")
        index_before = self.index.read_bytes()
        run = self.begin()
        self.assertEqual(self.listing()["accounts"][0]["status"], "in_progress")
        self.complete(run)
        second = self.checkpoint("begin")
        self.checkpoint("finish", "--run-id", second["run_id"], "--status", "partial",
                        "--reason", "Access unavailable")
        row = self.listing()["accounts"][0]
        self.assertEqual(row["covered_through"], run["window_end"])
        self.assertEqual(row["status"], "partial")
        self.assertEqual(row["last_attempt"]["reason"], "Access unavailable")
        self.assertEqual(self.index.read_bytes(), index_before)

    def test_partial_first_attempt_does_not_claim_coverage(self):
        self.register("--scope", "received")
        run = self.begin()
        self.checkpoint("finish", "--run-id", run["run_id"], "--status", "partial",
                        "--reason", "Reading incomplete")
        row = self.listing()["accounts"][0]
        self.assertIsNone(row["covered_through"])
        self.assertEqual(row["status"], "partial")

    def test_scopes_are_never_collapsed_to_latest_date(self):
        self.register("--scope", "received", "--scope", "topic")
        self.complete(self.begin())
        rows = self.listing()["accounts"]
        self.assertEqual(rows[0]["scope"], "received")
        self.assertIsNotNone(rows[0]["covered_through"])
        self.assertEqual(rows[1]["scope"], "topic")
        self.assertIsNone(rows[1]["covered_through"])

    def test_corrupt_index_is_not_overwritten(self):
        self.register()
        for raw in ("not-json", '{"version": 2}', '{"version": 1, "accounts": [null]}'):
            self.index.write_text(raw)
            with self.assertRaises(ValueError):
                self.register()
            self.assertEqual(self.index.read_text(), raw)

    def test_bad_checkpoint_is_an_error_not_unchecked(self):
        self.register("--scope", "received")
        run = self.begin()
        Path(run["state_path"]).write_text("not-json")
        row = self.listing()["accounts"][0]
        self.assertEqual(row["status"], "error")
        self.assertIsNone(row["covered_through"])

    def test_failed_save_preserves_index(self):
        self.register()
        before = self.index.read_bytes()
        with patch.object(cp.os, "replace", side_effect=OSError("synthetic failure")):
            with self.assertRaises(OSError):
                self.register("--label", "Changed")
        self.assertEqual(self.index.read_bytes(), before)

    def test_markdown_timezone_escaping_and_no_files(self):
        self.register("--scope", "received", "--label", "Work | <b>\nOther")
        self.complete(self.begin())
        result = self.listing()
        rendered = accounts.markdown(result, "Europe/London")
        self.assertIn("2026-10-06T15:52:40+01:00", rendered)
        self.assertIn("Work \\| &lt;b&gt; Other", rendered)
        self.assertIn("received", rendered)
        self.assertEqual(list(self.root.glob("*.md")), [])
        result["accounts"][0]["covered_through"] = "2026-11-06T14:52:40Z"
        self.assertIn("2026-11-06T14:52:40+00:00", accounts.markdown(result, "Europe/London"))

    def test_blank_account_or_scope_is_rejected(self):
        for extra, identity in (([], " "), (["--scope", " "], "demo@example.test")):
            with self.assertRaises(ValueError):
                self.register(*extra, account=identity)
        self.assertFalse(self.root.exists())


if __name__ == "__main__":
    unittest.main()
