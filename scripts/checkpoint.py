#!/usr/bin/env python3
"""Local coverage transactions. This helper never connects to a mailbox."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import uuid


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def iso(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def state_root(args):
    return Path(args.state_dir).expanduser() if args.state_dir else (
        Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
        / "email-triage"
    )


def state_path(args):
    account, scope = args.account.strip().casefold(), args.scope.strip()
    if not account or not scope:
        raise ValueError("Account and scope must not be empty")
    identity = json.dumps([args.provider, account, scope], separators=(",", ":"))
    return state_root(args) / (digest(identity) + ".json")


@contextmanager
def locked(path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path.with_suffix(".lock"), os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def save(path, state):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".checkpoint-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, ensure_ascii=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def execute(args, now=None):
    now = now or datetime.now(timezone.utc)
    path = state_path(args)
    with locked(path):
        state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        if state is not None and state.get("version") != 1:
            raise ValueError("Unsupported checkpoint version; existing state unchanged")
        if args.command == "show":
            return {"state_path": str(path), "state": state}

        if args.command == "begin":
            if not math.isfinite(args.overlap_hours) or args.overlap_hours < 0:
                raise ValueError("Overlap hours must be finite and nonnegative")
            if state is None:
                if not args.since:
                    raise ValueError("First run requires --since with an explicit baseline")
                baseline = timestamp(args.since)
                state = {
                    "version": 1, "provider": args.provider, "scope": args.scope.strip(),
                    "initial_since": iso(baseline), "covered_through": None,
                    "last_attempt": None, "reported_keys": [],
                }
            else:
                baseline = timestamp(state["initial_since"])
                if args.since and timestamp(args.since) != baseline:
                    raise ValueError("Cannot replace baseline; use a separate backfill scope")
            if (state["last_attempt"] or {}).get("status") == "in_progress":
                raise ValueError("An active run exists; inspect show before resolving it")
            covered = timestamp(state["covered_through"]) if state["covered_through"] else None
            if baseline >= now or (covered and covered > now):
                raise ValueError("Baseline/checkpoint is in the future or the interval is empty")
            start = max(baseline, covered - timedelta(hours=args.overlap_hours)) if covered else baseline
            attempt = {
                "run_id": str(uuid.uuid4()), "status": "in_progress",
                "new_since": iso(covered or baseline),
                "window_start": iso(start), "window_end": iso(now),
            }
            state["last_attempt"] = attempt
            save(path, state)
            return {
                **attempt, "covered_through": state["covered_through"],
                "reported_keys": state["reported_keys"], "state_path": str(path),
            }

        if state is None:
            raise ValueError("No run exists for this provider/account/scope")
        attempt = state["last_attempt"] or {}
        if attempt.get("status") != "in_progress" or attempt.get("run_id") != args.run_id:
            raise ValueError("Stale or mismatched run ID; checkpoint unchanged")
        if args.status == "complete" and not (args.coverage_complete and args.report_ready):
            raise ValueError("Completion requires --coverage-complete and --report-ready")
        if args.reported_id and not args.report_ready:
            raise ValueError("Reported IDs require --report-ready")
        if args.status == "partial" and not (args.reason or "").strip():
            raise ValueError("Partial attempts require a short non-sensitive --reason")

        if args.status == "complete":
            # Commit the frozen mailbox interval, never the finish command's clock.
            state["covered_through"] = attempt["window_end"]
        attempt["status"] = args.status
        if args.status == "partial":
            attempt["reason"] = args.reason.strip()[:240]
        keys = dict.fromkeys(state["reported_keys"])
        for value in args.reported_id:
            key = digest(value)
            keys.pop(key, None)
            keys[key] = None
        state["reported_keys"] = list(keys)[-2000:]
        save(path, state)
        return {
            "status": args.status, "covered_through": state["covered_through"],
            "new_since": attempt["new_since"],
            "window_start": attempt["window_start"], "window_end": attempt["window_end"],
            "reported_key_count": len(state["reported_keys"]), "state_path": str(path),
        }


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("show", "begin", "finish"):
        command = commands.add_parser(name)
        command.add_argument("--provider", choices=("outlook", "gmail", "feishu"), required=True)
        command.add_argument("--account", required=True)
        command.add_argument("--scope", required=True)
        command.add_argument("--state-dir")
        if name == "begin":
            command.add_argument("--since")
            command.add_argument("--overlap-hours", type=float, default=24)
        if name == "finish":
            command.add_argument("--run-id", required=True)
            command.add_argument("--status", choices=("complete", "partial"), required=True)
            command.add_argument("--coverage-complete", action="store_true")
            command.add_argument("--report-ready", action="store_true")
            command.add_argument("--reason")
            command.add_argument("--reported-id", action="append", default=[])
    return root


def main():
    try:
        result = execute(parser().parse_args())
    except (ValueError, OSError, KeyError, TypeError, OverflowError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
