#!/usr/bin/env python3
"""Synthetic, offline checkpoint regression tests."""

from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import checkpoint as cp


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.now = cp.timestamp("2026-10-04T12:00:00Z")
        self.base = "2026-09-01T00:00:00Z"

    def args(self, command, *extra, provider="gmail", account="demo@example.test", scope="all-received"):
        return cp.parser().parse_args([
            command, "--provider", provider, "--account", account, "--scope", scope,
            "--state-dir", self.temporary.name, *extra,
        ])

    def begin(self, **kwargs):
        return cp.execute(self.args("begin", "--since", self.base, **kwargs), self.now)

    def complete(self, run, **kwargs):
        return cp.execute(self.args(
            "finish", "--run-id", run["run_id"], "--status", "complete",
            "--coverage-complete", "--report-ready", **kwargs,
        ), self.now + timedelta(hours=3))

    def state(self, **kwargs):
        return cp.execute(self.args("show", **kwargs))["state"]

    def test_first_run_has_no_false_checkpoint(self):
        self.assertIsNone(self.state())
        with self.assertRaises(ValueError):
            cp.execute(self.args("begin"), self.now)
        run = self.begin()
        self.assertEqual(run["window_start"], self.base)
        self.assertIsNone(self.state()["covered_through"])

    def test_commit_uses_start_cutoff_not_finish_time(self):
        run = self.begin()
        self.complete(run)
        self.assertEqual(self.state()["covered_through"], cp.iso(self.now))
        self.assertNotEqual(self.state()["covered_through"], cp.iso(self.now + timedelta(hours=3)))

    def test_empty_completed_interval_is_valid(self):
        run = self.begin()
        self.complete(run)
        self.assertEqual(self.state()["reported_keys"], [])
        self.assertEqual(self.state()["covered_through"], run["window_end"])

    def test_resume_overlaps_and_respects_baseline(self):
        self.base = cp.iso(self.now - timedelta(hours=2))
        run = self.begin()
        self.complete(run)
        next_run = cp.execute(self.args("begin"), self.now + timedelta(days=2))
        self.assertEqual(next_run["window_start"], self.base)

    def test_two_days_later_covers_whole_new_interval(self):
        self.complete(self.begin())
        later = self.now + timedelta(days=2)
        run = cp.execute(self.args("begin"), later)
        self.assertEqual(run["new_since"], cp.iso(self.now))
        self.assertEqual(run["window_end"], cp.iso(later))
        self.assertEqual(run["window_start"], cp.iso(self.now - timedelta(days=1)))
        result = cp.execute(self.args("finish", "--run-id", run["run_id"], "--status", "complete",
                                      "--coverage-complete", "--report-ready"), later + timedelta(minutes=20))
        self.assertEqual(result["covered_through"], cp.iso(later))

    def test_partial_preserves_boundary_and_restarts(self):
        self.complete(self.begin())
        before = self.state()["covered_through"]
        run = cp.execute(self.args("begin"), self.now + timedelta(days=1))
        cp.execute(self.args("finish", "--run-id", run["run_id"], "--status", "partial",
                             "--reason", "Unreadable result page"))
        self.assertEqual(self.state()["covered_through"], before)
        retry = cp.execute(self.args("begin"), self.now + timedelta(days=2))
        self.assertEqual(retry["window_start"], cp.iso(self.now - timedelta(days=1)))

    def test_partial_first_run_remembers_original_baseline(self):
        run = self.begin()
        cp.execute(self.args("finish", "--run-id", run["run_id"], "--status", "partial",
                             "--reason", "UI blocked"))
        self.assertIsNone(self.state()["covered_through"])
        retry = cp.execute(self.args("begin"), self.now + timedelta(days=1))
        self.assertEqual(retry["window_start"], self.base)

    def test_scope_provider_and_account_are_isolated(self):
        self.complete(self.begin())
        for kwargs in ({"scope": "topic-only"}, {"provider": "outlook"},
                       {"provider": "feishu"}, {"account": "other@example.test"}):
            self.assertIsNone(self.state(**kwargs))
            with self.assertRaises(ValueError):
                cp.execute(self.args("begin", **kwargs), self.now)

    def test_feishu_completion_and_incremental_resume(self):
        run = self.begin(provider="feishu")
        self.complete(run, provider="feishu")
        self.assertEqual(self.state(provider="feishu")["provider"], "feishu")
        self.assertIsNone(self.state(provider="gmail"))
        self.assertIsNone(self.state(provider="outlook"))
        self.assertIsNone(self.state(provider="feishu", account="shared@example.test"))
        later = self.now + timedelta(days=2)
        next_run = cp.execute(self.args("begin", provider="feishu"), later)
        self.assertEqual(next_run["new_since"], run["window_end"])
        self.assertEqual(next_run["window_end"], cp.iso(later))

    def test_active_run_stale_token_and_missing_assertion_rejected(self):
        run = self.begin()
        with self.assertRaises(ValueError):
            self.begin()
        for token, flags in (("wrong-token", ["--coverage-complete", "--report-ready"]),
                             (run["run_id"], ["--report-ready"])):
            with self.assertRaises(ValueError):
                cp.execute(self.args("finish", "--run-id", token, "--status", "complete", *flags))
        self.assertIsNone(self.state()["covered_through"])
        self.complete(run)
        with self.assertRaises(ValueError):
            self.complete(run)

    def test_feishu_personal_completion_does_not_advance_shared_mailbox(self):
        personal = self.begin(provider="feishu")
        shared = self.begin(provider="feishu", account="shared@example.test")
        self.complete(personal, provider="feishu")
        cp.execute(self.args("finish", "--run-id", shared["run_id"], "--status", "partial",
                             "--reason", "Shared mailbox read access unavailable",
                             provider="feishu", account="shared@example.test"))
        self.assertEqual(self.state(provider="feishu")["covered_through"], personal["window_end"])
        self.assertIsNone(self.state(provider="feishu", account="shared@example.test")["covered_through"])

    def test_invalid_dates_and_changed_baseline_do_not_write(self):
        for date in ("2026-10-03T12:00:00", "2030-01-01T00:00:00Z"):
            with self.assertRaises(ValueError):
                cp.execute(self.args("begin", "--since", date), self.now)
            self.assertIsNone(self.state())
        self.complete(self.begin())
        with self.assertRaises(ValueError):
            cp.execute(self.args("begin", "--since", "2026-10-01T00:00:00Z"), self.now)

    def test_timezone_offsets_and_dst_are_absolute(self):
        self.assertEqual(cp.timestamp("2026-10-24T13:00:00+01:00"),
                         cp.timestamp("2026-10-24T12:00:00Z"))
        self.assertEqual(cp.timestamp("2026-10-26T13:00:00+00:00"),
                         cp.timestamp("2026-10-26T13:00:00Z"))

    def test_dedupe_stores_only_hashes_not_identity(self):
        run = self.begin()
        cp.execute(self.args("finish", "--run-id", run["run_id"], "--status", "complete",
                             "--coverage-complete", "--report-ready",
                             "--reported-id", "synthetic-message-id", "--reported-id", "synthetic-message-id"))
        self.assertEqual(self.state()["reported_keys"], [cp.digest("synthetic-message-id")])
        raw = Path(run["state_path"]).read_text()
        self.assertNotIn("demo@example.test", raw)
        self.assertNotIn("synthetic-message-id", raw)
        self.assertEqual(Path(run["state_path"]).stat().st_mode & 0o777, 0o600)

    def test_failed_atomic_replace_preserves_previous_file(self):
        run = self.begin()
        path = Path(run["state_path"])
        before = path.read_bytes()
        with patch.object(cp.os, "replace", side_effect=OSError("synthetic failure")):
            with self.assertRaises(OSError):
                self.complete(run)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(path.parent.glob(".checkpoint-*")), [])

    def test_corrupt_state_is_not_silently_reset(self):
        args = self.args("show")
        path = cp.state_path(args)
        path.write_text("not-json")
        with self.assertRaises(json.JSONDecodeError):
            self.begin()
        self.assertEqual(path.read_text(), "not-json")


if __name__ == "__main__":
    unittest.main()
