#!/usr/bin/env python3
"""Log-file integrity checker for MID (TODO_FILE_INTEGRITY / monitoring_design §5).

Verifies the daily JSONL log is well-formed and internally consistent:

* C1 - the daily ``log_YYYYMMDD.jsonl`` file exists
* C2 - every line parses as JSON and carries the required event fields
* C3 - timestamps are ISO-8601 and non-decreasing within the file
* C4 - no ``log_*.jsonl`` has scattered outside ``<base_path>/<log_path>``
* C5 - file size did not explode (>10x the previous day)
* Inv - ``weight_updated`` <= ``process_feedback_log_success``
  (monitoring_design §2.4 reconciliation invariant 1)

Exit code 0 = pass, 1 = integrity failure, 2 = environment error.

CLI::

    py -3.10 validate_log_integrity.py [--log-dir DIR] [--date YYYY-MM-DD] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

REQUIRED_FIELDS = ("timestamp", "engine_id", "action_type", "correlation_id",
                   "input_summary", "output_summary")
SIZE_EXPLOSION_FACTOR = 10.0


def _default_log_dir() -> Path:
    env = os.environ.get("MID_TEST_CONFIG")
    if env:
        config_dir = Path(env).resolve().parent
    else:
        config_dir = Path(os.path.expanduser("~")) / "OneDrive" / "Vault" / "Memory" / "Configs"
    paths_file = config_dir / "paths.yaml"
    try:
        import yaml
        with open(paths_file, "r", encoding="utf-8") as fh:
            paths = yaml.safe_load(fh) or {}
    except Exception:
        paths = {}
    base = paths.get("base_path", "OneDrive/Vault")
    log_rel = paths.get("log_path", "Memory/Feedback/logs")
    base_path = Path(base)
    if not base_path.is_absolute():
        base_path = Path(os.path.expanduser("~")) / base_path
    return (base_path / log_rel).resolve()


def _parse_ts(value) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def validate_log_integrity(log_dir: Path, target_date: date) -> Dict[str, object]:
    errors: List[str] = []
    warnings: List[str] = []
    stats: Dict[str, object] = {}

    log_dir = Path(log_dir)
    if not log_dir.is_dir():
        return {
            "ok": False,
            "log_dir": str(log_dir),
            "date": target_date.isoformat(),
            "errors": [f"log directory not found: {log_dir}"],
            "warnings": warnings,
            "stats": stats,
        }

    filename = f"log_{target_date:%Y%m%d}.jsonl"
    log_file = log_dir / filename
    if not log_file.exists():
        errors.append(f"C1 daily log file missing: {log_file}")

    rows: List[dict] = []
    parse_failures: List[int] = []
    field_failures: List[str] = []
    bad_timestamps: List[int] = []
    last_ts: Optional[datetime] = None
    out_of_order: List[int] = []

    if log_file.exists():
        with open(log_file, "r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError as exc:
                    parse_failures.append(lineno)
                    errors.append(f"C2 line {lineno}: invalid JSON: {exc}")
                    continue
                if not isinstance(entry, dict):
                    parse_failures.append(lineno)
                    errors.append(f"C2 line {lineno}: entry is not an object")
                    continue
                rows.append(entry)
                missing = [f for f in REQUIRED_FIELDS if f not in entry]
                if missing:
                    field_failures.append(str(lineno))
                    errors.append(f"C2 line {lineno}: missing fields {missing}")
                ts = _parse_ts(entry.get("timestamp"))
                if ts is None:
                    bad_timestamps.append(lineno)
                    errors.append(f"C3 line {lineno}: invalid timestamp {entry.get('timestamp')!r}")
                elif last_ts is not None and ts < last_ts:
                    out_of_order.append(lineno)
                    errors.append(f"C3 line {lineno}: timestamp out of order ({ts} < {last_ts})")
                else:
                    last_ts = ts

        # C5 size explosion vs previous day
        prev_file = log_dir / f"log_{target_date - timedelta(days=1):%Y%m%d}.jsonl"
        if prev_file.exists():
            prev_size = prev_file.stat().st_size
            cur_size = log_file.stat().st_size
            if prev_size > 0 and cur_size > prev_size * SIZE_EXPLOSION_FACTOR:
                errors.append(
                    f"C5 size explosion: {cur_size} bytes vs previous {prev_size} "
                    f"({cur_size / prev_size:.1f}x)"
                )
            stats["prev_day_size"] = prev_size
            stats["size_ratio"] = round(cur_size / prev_size, 3) if prev_size else None

        # C4 stray log files outside the log directory
        base_path = log_dir.parent
        # walk up to the Vault root (the dir containing Memory/)
        for candidate in [log_dir] + list(log_dir.parents):
            if (candidate / "Memory").is_dir():
                base_path = candidate
                break
        strays: List[str] = []
        for stray in base_path.rglob("log_*.jsonl"):
            try:
                if log_dir.resolve() not in stray.resolve().parents and stray.resolve() != log_dir.resolve():
                    strays.append(str(stray))
            except OSError:
                continue
        if strays:
            warnings.append(f"C4 stray log file(s) outside {log_dir}: {strays[:10]}")

    # Invariants (monitoring_design §2.4)
    weight_updated = [r for r in rows if r.get("action_type") == "weight_updated"]
    success = [r for r in rows if r.get("action_type") == "process_feedback_log_success"]
    error_rows = [r for r in rows if "error" in str(r.get("action_type", ""))]
    if len(weight_updated) > len(success):
        errors.append(
            f"Invariant 1 violated: weight_updated ({len(weight_updated)}) > "
            f"process_feedback_log_success ({len(success)})"
        )

    stats.update({
        "total_rows": len(rows),
        "parse_failures": len(parse_failures),
        "field_failures": len(field_failures),
        "bad_timestamps": len(bad_timestamps),
        "out_of_order": len(out_of_order),
        "weight_updated": len(weight_updated),
        "process_feedback_log_success": len(success),
        "error_action_types": len(error_rows),
        "stray_files": len([s for s in warnings if s.startswith("C4")]),
    })

    return {
        "ok": not errors,
        "log_dir": str(log_dir),
        "date": target_date.isoformat(),
        "errors": errors,
        "warnings": warnings,
        "stats": stats,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate MID daily log integrity")
    parser.add_argument("--log-dir", help="directory containing log_YYYYMMDD.jsonl")
    parser.add_argument("--date", help="target date YYYY-MM-DD (default: today)")
    parser.add_argument("--json", action="store_true", help="emit JSON report")
    args = parser.parse_args(argv)

    log_dir = Path(args.log_dir).resolve() if args.log_dir else _default_log_dir()
    if args.date:
        try:
            target = date.fromisoformat(args.date)
        except ValueError:
            print(f"FATAL: invalid --date {args.date!r} (expected YYYY-MM-DD)", file=sys.stderr)
            return 2
    else:
        target = date.today()

    report = validate_log_integrity(log_dir, target)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"log_dir: {report['log_dir']}")
        print(f"date   : {report['date']}")
        print(f"stats  : {json.dumps(report['stats'], ensure_ascii=False)}")
        if report["ok"]:
            print("PASS: log integrity checks passed")
        else:
            print(f"FAIL: {len(report['errors'])} error(s):")
            for err in report["errors"]:
                print(f"  - {err}")
        for warn in report["warnings"]:
            print(f"WARN: {warn}")

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
