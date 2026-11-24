#!/usr/bin/env python3
"""L2 code-level rollback for MID (weight_manager.py / feedback_processor.py).

Implements the S4 L2 rollback mechanism described in
``operations/rollback_plan.md`` §4.3:

* ``backup_code()``  - snapshot the live ``.py`` modules to ``<name>_backup.py``
  in the same directory AND to a timestamped ``backups/code/<TS>/`` tree with a
  sha256 ``MANIFEST.sha256``.
* ``restore_code()`` - copy a snapshot back over the live modules, then verify
  with ``py_compile`` (and an optional import smoke test).

Legacy note (rollback_plan §2.2 / RB3): ``weight_manager_backup.py`` and
``feedback_processor_backup.py`` used to be old-generation *reference* copies
that were NOT safe rollback sources (different path scheme, dict-only schema,
no logger dependency). On the first ``backup_code()`` run such a pre-existing
file is archived to ``backups/legacy/`` so that ``<name>_backup.py`` becomes a
true L2 restore point. Nothing is deleted.

CLI::

    py -3.10 code_rollback.py backup  [--note "..."] [--targets a.py,b.py]
    py -3.10 code_rollback.py restore [--ts 20261120_120000] [--targets a.py,b.py]
    py -3.10 code_rollback.py list
    py -3.10 code_rollback.py verify
"""
from __future__ import annotations

import argparse
import hashlib
import py_compile
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

MODULE_DIR = Path(__file__).resolve().parent
BACKUP_DIR = MODULE_DIR / "backups"
CODE_SNAPSHOT_DIR = BACKUP_DIR / "code"
LEGACY_DIR = BACKUP_DIR / "legacy"
FAILED_DIR = BACKUP_DIR / "failed"

DEFAULT_TARGETS: List[str] = ["weight_manager.py", "feedback_processor.py", "logger.py"]

BACKUP_MARKER = "# L2 code rollback backup"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_our_backup(path: Path) -> bool:
    """True when ``path`` was written by this module (not a legacy copy)."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.readline().startswith(BACKUP_MARKER)
    except OSError:
        return False


def _strip_marker(text: str) -> str:
    """Remove leading L2 marker line(s) so a restore does not inject them."""
    lines = text.splitlines(keepends=True)
    while lines and lines[0].startswith(BACKUP_MARKER):
        lines.pop(0)
    return "".join(lines)


def _archive_legacy(target: Path) -> Optional[Path]:
    """Move a pre-existing non-L2 ``*_backup.py`` aside to ``backups/legacy/``."""
    backup_path = target.with_name(target.stem + "_backup.py")
    if not backup_path.exists() or _is_our_backup(backup_path):
        return None
    LEGACY_DIR.mkdir(parents=True, exist_ok=True)
    dest = LEGACY_DIR / f"{backup_path.name}.{datetime.now().strftime('%Y%m%d_%H%M%S')}.legacy"
    shutil.move(str(backup_path), str(dest))
    return dest


def _resolve_targets(targets: Optional[List[str]]) -> List[Path]:
    if not targets:
        names: List[object] = DEFAULT_TARGETS
    else:
        names = list(targets)
    resolved: List[Path] = []
    for name in names:
        p = Path(name)
        if not p.is_absolute():
            p = MODULE_DIR / p
        resolved.append(p)
    return resolved


def _write_manifest(snapshot: Path, targets: List[Path]) -> Path:
    lines = []
    for t in targets:
        src = snapshot / t.name
        lines.append(f"{_sha256(src)}  {t.name}")
    manifest = snapshot / "MANIFEST.sha256"
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #
def backup_code(targets: Optional[List[str]] = None, note: str = "") -> Dict[str, object]:
    """Snapshot the live modules and return a report dict."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    resolved = _resolve_targets(targets)
    snapshot = CODE_SNAPSHOT_DIR / ts
    snapshot.mkdir(parents=True, exist_ok=True)

    report: Dict[str, object] = {
        "status": "success",
        "timestamp": ts,
        "snapshot": str(snapshot),
        "backups": [],
        "archived_legacy": [],
        "missing": [],
    }

    for target in resolved:
        if not target.exists():
            report["missing"].append(str(target))  # type: ignore[union-attr]
            continue

        archived = _archive_legacy(target)
        if archived:
            report["archived_legacy"].append(str(archived))  # type: ignore[union-attr]

        # 1) same-dir restore point: <name>_backup.py (with L2 marker header)
        same_dir_backup = target.with_name(target.stem + "_backup.py")
        content = target.read_text(encoding="utf-8")
        same_dir_backup.write_text(
            f"{BACKUP_MARKER} created {ts} by code_rollback.py\n" + content,
            encoding="utf-8",
        )

        # 2) timestamped snapshot (plain copy, no marker)
        shutil.copy2(str(target), str(snapshot / target.name))

        report["backups"].append({  # type: ignore[union-attr]
            "module": target.name,
            "same_dir": str(same_dir_backup),
            "snapshot": str(snapshot / target.name),
            "sha256": _sha256(target),
        })

    _write_manifest(snapshot, resolved)
    (snapshot / "NOTE.txt").write_text(
        f"created: {ts}\nnote: {note or '(none)'}\ntargets: "
        + ", ".join(t.name for t in resolved) + "\n",
        encoding="utf-8",
    )
    return report


def _restore_one(target: Path, source: Path, failed_dir: Path) -> Dict[str, object]:
    entry: Dict[str, object] = {"module": target.name, "source": str(source)}
    if not source.exists():
        entry["status"] = "error"
        entry["message"] = f"backup not found: {source}"
        return entry

    target.parent.mkdir(parents=True, exist_ok=True)
    # preserve the broken live file (rollback_plan §4.3 step 1)
    failed_dir.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.copy2(str(target), str(failed_dir / target.name))

    # copy back, stripping the L2 marker header so the live file stays clean
    text = source.read_text(encoding="utf-8")
    target.write_text(_strip_marker(text), encoding="utf-8")

    # verify: py_compile
    try:
        py_compile.compile(str(target), doraise=True)
        entry["compile"] = "ok"
    except py_compile.PyCompileError as exc:
        entry["status"] = "error"
        entry["message"] = f"py_compile failed: {exc}"
        return entry

    entry["status"] = "success"
    entry["sha256"] = _sha256(target)
    return entry


def restore_code(
    targets: Optional[List[str]] = None,
    ts: Optional[str] = None,
    verify: bool = True,
) -> Dict[str, object]:
    """Restore modules from ``<name>_backup.py`` (or a timestamped snapshot)."""
    resolved = _resolve_targets(targets)
    ts_now = datetime.now().strftime("%Y%m%d_%H%M%S")
    failed_dir = FAILED_DIR / ts_now

    report: Dict[str, object] = {
        "status": "success",
        "restored_from": ts or "same-dir *_backup.py",
        "failed_dir": str(failed_dir),
        "results": [],
    }

    for target in resolved:
        if ts:
            source = CODE_SNAPSHOT_DIR / ts / target.name
        else:
            source = target.with_name(target.stem + "_backup.py")
        entry = _restore_one(target, source, failed_dir)
        report["results"].append(entry)  # type: ignore[union-attr]
        if entry.get("status") != "success":
            report["status"] = "error"

    if verify and report["status"] == "success":
        report["verify"] = verify_code(resolved)
        if not report["verify"].get("ok"):  # type: ignore[union-attr]
            report["status"] = "error"
    return report


def verify_code(targets: Optional[List[str]] = None) -> Dict[str, object]:
    """Compile-check modules and return ``{"ok": bool, "results": [...]}``."""
    resolved = _resolve_targets(targets)
    results = []
    ok = True
    for target in resolved:
        entry: Dict[str, object] = {"module": target.name}
        if not target.exists():
            entry["status"] = "missing"
            ok = False
        else:
            try:
                py_compile.compile(str(target), doraise=True)
                entry["status"] = "ok"
            except py_compile.PyCompileError as exc:
                entry["status"] = "error"
                entry["message"] = str(exc)
                ok = False
        results.append(entry)
    return {"ok": ok, "results": results}


def list_backups() -> Dict[str, object]:
    """List timestamped snapshots and same-dir restore points."""
    snapshots = []
    if CODE_SNAPSHOT_DIR.exists():
        for child in sorted(CODE_SNAPSHOT_DIR.iterdir()):
            if child.is_dir():
                manifest = child / "MANIFEST.sha256"
                snapshots.append({
                    "timestamp": child.name,
                    "path": str(child),
                    "modules": sorted(p.name for p in child.glob("*.py")),
                    "manifest": manifest.exists(),
                })
    same_dir = sorted(MODULE_DIR.glob("*_backup.py"))
    return {"snapshots": snapshots, "same_dir_backups": [p.name for p in same_dir]}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _print_report(report: Dict[str, object]) -> None:
    import json
    print(json.dumps(report, indent=2, ensure_ascii=False))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="MID L2 code rollback")
    sub = parser.add_subparsers(dest="command", required=True)

    p_backup = sub.add_parser("backup", help="snapshot live .py modules")
    p_backup.add_argument("--targets", help="comma-separated module filenames")
    p_backup.add_argument("--note", default="", help="free-form note")

    p_restore = sub.add_parser("restore", help="restore modules from a snapshot")
    p_restore.add_argument("--targets", help="comma-separated module filenames")
    p_restore.add_argument("--ts", help="timestamped snapshot id (default: same-dir *_backup.py)")
    p_restore.add_argument("--no-verify", action="store_true", help="skip py_compile verification")

    sub.add_parser("list", help="list available snapshots")
    sub.add_parser("verify", help="py_compile the live modules")

    args = parser.parse_args(argv)
    targets = args.targets.split(",") if getattr(args, "targets", None) else None

    if args.command == "backup":
        report = backup_code(targets=targets, note=args.note)
    elif args.command == "restore":
        report = restore_code(targets=targets, ts=args.ts, verify=not args.no_verify)
    elif args.command == "list":
        report = list_backups()
    elif args.command == "verify":
        report = verify_code(targets=targets)
        report = {"ok": report["ok"], "results": report["results"]}
    else:  # pragma: no cover
        parser.error("unknown command")
        return 2

    _print_report(report)
    if isinstance(report, dict) and report.get("status") == "error":
        return 1
    if isinstance(report, dict) and report.get("ok") is False:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
