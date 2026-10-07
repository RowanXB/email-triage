#!/usr/bin/env python3
"""Private account index and live checkpoint overview; no mailbox connections."""

import argparse
import html
import json
import sys
from zoneinfo import ZoneInfo

import checkpoint as cp


PROVIDERS = ("outlook", "gmail", "feishu")


def read_index(path):
    if not path.exists():
        return {"version": 1, "accounts": []}
    index = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(index, dict) or index.get("version") != 1:
        raise ValueError("Unsupported account index; existing file unchanged")
    if not isinstance(index.get("accounts"), list):
        raise ValueError("Invalid account index")
    seen = set()
    for item in index["accounts"]:
        if (not isinstance(item, dict) or item.get("provider") not in PROVIDERS
                or not isinstance(item.get("account"), str) or not item["account"].strip()
                or not isinstance(item.get("label", ""), str)
                or not isinstance(item.get("scopes"), list)
                or any(not isinstance(s, str) or not s.strip() for s in item["scopes"])):
            raise ValueError("Invalid account index entry")
        key = (item["provider"], item["account"].strip().casefold())
        if key in seen:
            raise ValueError("Duplicate account identity in index")
        seen.add(key)
    return index


def register(args):
    account = args.account.strip().casefold()
    scopes = [s.strip() for s in args.scope]
    if not account or any(not s for s in scopes):
        raise ValueError("Account and supplied scopes must not be empty")
    path = cp.state_root(args) / "accounts.json"
    with cp.locked(path):
        index = read_index(path)
        item = next((entry for entry in index["accounts"]
                     if entry["provider"] == args.provider
                     and entry["account"].strip().casefold() == account), None)
        if item is None:
            item = {"provider": args.provider, "account": account, "label": "", "scopes": []}
            index["accounts"].append(item)
        if args.label is not None:
            item["label"] = args.label.strip()
        item["scopes"] = sorted(set(item["scopes"]) | set(scopes))
        cp.save(path, index)
    return {"index_path": str(path), "account": item}


def overview(args):
    root = cp.state_root(args)
    rows = []
    for item in read_index(root / "accounts.json")["accounts"]:
        for scope in item["scopes"] or [None]:
            row = {"provider": item["provider"], "account": item["account"],
                   "label": item.get("label", ""), "scope": scope,
                   "initial_since": None, "covered_through": None,
                   "last_attempt": None, "status": "not_checked"}
            rows.append(row)
            if scope is None:
                continue
            path = cp.state_path(argparse.Namespace(
                provider=item["provider"], account=item["account"], scope=scope,
                state_dir=str(root)))
            if not path.exists():
                continue
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
                if (state["version"] != 1 or state["provider"] != item["provider"]
                        or state["scope"] != scope):
                    raise ValueError("Checkpoint schema or scope mismatch")
                cp.timestamp(state["initial_since"])
                if state["covered_through"] is not None:
                    cp.timestamp(state["covered_through"])
                attempt = state["last_attempt"]
                if attempt is not None:
                    if attempt["status"] not in ("in_progress", "partial", "complete"):
                        raise ValueError("Unknown attempt status")
                    cp.timestamp(attempt["window_end"])
                row.update(initial_since=state["initial_since"],
                           covered_through=state["covered_through"], last_attempt=attempt,
                           status=attempt["status"] if attempt else "not_checked")
            except (ValueError, OSError, KeyError, TypeError, AttributeError):
                row.update(status="error", error=f"Cannot read valid checkpoint: {path.name}")
    return {"accounts": sorted(rows, key=lambda r: (r["provider"], r["account"], r["scope"] or ""))}


def markdown(result, timezone_name):
    zone = ZoneInfo(timezone_name)

    def cell(value):
        return html.escape(str(value or "-"), quote=False).replace("\\", "\\\\").replace(
            "|", "\\|").replace("\r", " ").replace("\n", " ").replace("`", "&#96;")

    def date(value):
        return cp.timestamp(value).astimezone(zone).isoformat() if value else "Never"

    lines = [f"Known accounts only; not proof of current access. Time zone: {cell(timezone_name)}.",
             "", "| Provider | Account | Label | Scope | Coverage starts | Fully checked through | Latest attempt | Note |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for row in result["accounts"]:
        note = row.get("error") or (row["last_attempt"] or {}).get("reason", "")
        values = [row["provider"], row["account"], row["label"], row["scope"],
                  date(row["initial_since"]), date(row["covered_through"]), row["status"], note]
        lines.append("| " + " | ".join(cell(v) for v in values) + " |")
    if not result["accounts"]:
        lines.extend(["", "No registered accounts."])
    return "\n".join(lines)


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    add = commands.add_parser("register", help="Add/update a known account without changing checkpoints")
    add.add_argument("--provider", choices=PROVIDERS, required=True)
    add.add_argument("--account", required=True)
    add.add_argument("--label")
    add.add_argument("--scope", action="append", default=[])
    add.add_argument("--state-dir")
    listing = commands.add_parser("list", help="Read registered accounts and their current checkpoints")
    listing.add_argument("--state-dir")
    listing.add_argument("--format", choices=("json", "markdown"), default="json")
    listing.add_argument("--timezone", default="UTC", help="IANA zone for Markdown output")
    return root


def main():
    args = parser().parse_args()
    try:
        result = register(args) if args.command == "register" else overview(args)
        output = (markdown(result, args.timezone)
                  if args.command == "list" and args.format == "markdown"
                  else json.dumps(result, indent=2, ensure_ascii=True))
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1
    print(output)
    return int(any(row["status"] == "error" for row in result.get("accounts", [])))


if __name__ == "__main__":
    sys.exit(main())
