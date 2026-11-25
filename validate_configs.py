#!/usr/bin/env python3
"""Configuration validator for MID - CI gate (TODO_VALIDATE_CONFIGS, S1/S4).

Checks ``source_weights.yaml``, ``feedback_rules.yaml`` and ``paths.yaml``
before deploy / on every PR that touches the configs:

1. **Finite weight validation** - every ``sources.*.base_weight`` is finite and
   within ``[weight_min, weight_max]`` from ``feedback_rules.yaml``.
2. **Structure validation** - ``sources`` is a dict (not a list); each source
   has ``id``, ``base_weight``, ``failure_threshold``, ``reliability_category``;
   ``health_metrics`` has integer ``consecutive_failures`` and an ISO
   ``last_success``.
3. **Feedback rules validation** - ``weight_min < weight_max``, deltas numeric
   (delegated to ``scripts/validate_feedback_rules.py``).
4. **Paths validation** - ``paths.yaml`` resolves to existing directories and
   ``configs_path`` / ``log_path`` are valid relative to ``base_path``.

Exit code 0 = pass, 1 = validation failure, 2 = environment error.

CLI::

    py -3.10 validate_configs.py [--config-dir DIR] [--json]

``--config-dir`` defaults to ``$HOME/OneDrive/Vault/Memory/Configs`` (or the
parent of ``$MID_TEST_CONFIG`` when set, for isolated test runs).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:  # pragma: no cover
    print("FATAL: PyYAML is required (run with `py -3.10`)", file=sys.stderr)
    raise SystemExit(2)

MODULE_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = MODULE_DIR / "scripts"

REQUIRED_SOURCE_FIELDS = ("id", "base_weight", "failure_threshold", "reliability_category")


# --------------------------------------------------------------------------- #
# path resolution
# --------------------------------------------------------------------------- #
def _find_vault_root(start: Path) -> Path:
    for p in [start] + list(start.parents):
        if p.name == "Vault" and p.parent.name == "OneDrive":
            return p
    return start


def _resolve_base(base: str, config_dir: Path) -> Path:
    p = Path(base)
    if p.is_absolute():
        return p.resolve()
    # Unix-style absolute path on Windows, e.g. /c/Users/...
    if base.startswith("/") and len(base) > 2 and base[2] == "/":
        return Path(f"{base[1].upper()}:{base[2:]}").resolve()
    vault_root = _find_vault_root(config_dir)
    if base.startswith("OneDrive/Vault"):
        return (vault_root / base.replace("OneDrive/Vault", "").lstrip("/")).resolve()
    return (vault_root / base).resolve()


def _default_config_dir() -> Path:
    env = os.environ.get("MID_TEST_CONFIG")
    if env:
        return Path(env).resolve().parent
    return Path(os.path.expanduser("~")) / "OneDrive" / "Vault" / "Memory" / "Configs"


def _load_yaml(path: Path) -> Tuple[Optional[object], Optional[str]]:
    if not path.exists():
        return None, f"file not found: {path}"
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh), None
    except Exception as exc:
        return None, f"YAML parse error in {path}: {exc}"


# --------------------------------------------------------------------------- #
# individual checks
# --------------------------------------------------------------------------- #
def check_paths(config_dir: Path, errors: List[Dict[str, str]]) -> Dict[str, Path]:
    """Validate paths.yaml and return the resolved directories."""
    resolved = {"base": config_dir, "configs": config_dir, "logs": config_dir}
    data, err = _load_yaml(config_dir / "paths.yaml")
    if err:
        errors.append({"check": "paths", "ref": "paths.yaml", "message": err})
        return resolved
    if not isinstance(data, dict):
        errors.append({"check": "paths", "ref": "paths.yaml",
                       "message": f"top level must be a mapping, got {type(data).__name__}"})
        return resolved

    for key in ("base_path", "configs_path", "log_path"):
        if not data.get(key):
            errors.append({"check": "paths", "ref": f"paths.yaml:{key}",
                           "message": f"missing required key '{key}'"})

    base = _resolve_base(str(data.get("base_path", "")), config_dir)
    resolved["base"] = base
    if not base.is_dir():
        errors.append({"check": "paths", "ref": f"paths.yaml:base_path -> {base}",
                       "message": "base_path does not resolve to an existing directory"})

    for key, label in (("configs_path", "configs"), ("log_path", "logs")):
        rel = data.get(key)
        if not rel:
            continue
        target = (base / str(rel)).resolve()
        resolved[label] = target
        if not target.is_dir():
            errors.append({"check": "paths", "ref": f"paths.yaml:{key} -> {target}",
                           "message": f"{key} does not resolve to an existing directory"})
    return resolved


def check_feedback_rules(rules_path: Path, errors: List[Dict[str, str]]) -> Dict[str, float]:
    """Delegate to scripts/validate_feedback_rules.py and return clip bounds."""
    bounds = {"weight_min": float("-inf"), "weight_max": float("inf")}
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        from validate_feedback_rules import validate_feedback_rules as _validate
    except Exception as exc:  # pragma: no cover
        errors.append({"check": "feedback_rules", "ref": str(rules_path),
                       "message": f"could not import clip validator: {exc}"})
        return bounds

    ok, rule_errors, _warnings = _validate(str(rules_path))
    for msg in rule_errors:
        errors.append({"check": "feedback_rules", "ref": str(rules_path), "message": msg})
    if ok:
        data, _ = _load_yaml(rules_path)
        if isinstance(data, dict):
            bounds["weight_min"] = float(data.get("weight_min", bounds["weight_min"]))
            bounds["weight_max"] = float(data.get("weight_max", bounds["weight_max"]))
    return bounds


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_iso_date(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _check_health_metrics(where: str, metrics: Dict[str, object], errors: List[Dict[str, str]]) -> None:
    cf = metrics.get("consecutive_failures")
    if not _is_int(cf):
        errors.append({"check": "structure", "ref": f"{where}.health_metrics.consecutive_failures",
                       "message": f"must be an integer, got {cf!r}"})
    ls = metrics.get("last_success")
    if not _is_iso_date(ls):
        errors.append({"check": "structure", "ref": f"{where}.health_metrics.last_success",
                       "message": f"must be an ISO date string, got {ls!r}"})


def check_source_weights(
    weights_path: Path,
    bounds: Dict[str, float],
    errors: List[Dict[str, str]],
) -> None:
    data, err = _load_yaml(weights_path)
    if err:
        errors.append({"check": "weights", "ref": str(weights_path), "message": err})
        return
    if not isinstance(data, dict):
        errors.append({"check": "weights", "ref": str(weights_path),
                       "message": f"top level must be a mapping, got {type(data).__name__}"})
        return

    sources = data.get("sources")
    if sources is None:
        errors.append({"check": "structure", "ref": "source_weights.yaml:sources",
                       "message": "'sources' is missing"})
        return
    if not isinstance(sources, dict):
        errors.append({
            "check": "structure",
            "ref": "source_weights.yaml:sources",
            "message": (f"'sources' must be a dict keyed by source id, got "
                        f"{type(sources).__name__} (Scenario 4 list/dict mismatch)"),
        })
        return

    wmin, wmax = bounds["weight_min"], bounds["weight_max"]

    for source_id, source in sources.items():
        where = f"sources.{source_id}"
        if not isinstance(source, dict):
            errors.append({"check": "structure", "ref": where,
                           "message": f"source entry must be a mapping, got {type(source).__name__}"})
            continue
        for field in REQUIRED_SOURCE_FIELDS:
            if field not in source:
                errors.append({"check": "structure", "ref": f"{where}.{field}",
                               "message": f"missing required field '{field}'"})

        bw = source.get("base_weight")
        if bw is None:
            pass  # already reported as a missing required field
        elif not isinstance(bw, (int, float)) or isinstance(bw, bool):
            errors.append({"check": "weights", "ref": f"{where}.base_weight",
                           "message": f"must be numeric, got {bw!r}"})
        elif not math.isfinite(bw):
            errors.append({"check": "weights", "ref": f"{where}.base_weight",
                           "message": f"must be finite, got {bw!r} (NaN/Inf injection)"})
        elif not (wmin <= bw <= wmax):
            errors.append({
                "check": "weights",
                "ref": f"{where}.base_weight",
                "message": f"{bw} outside clip range [{wmin}, {wmax}]",
            })

        if "health_metrics" in source:
            hm = source.get("health_metrics")
            if isinstance(hm, dict):
                _check_health_metrics(where, hm, errors)
            else:
                errors.append({"check": "structure", "ref": f"{where}.health_metrics",
                               "message": f"must be a mapping, got {type(hm).__name__}"})

    # top-level health_metrics block (present in the production file)
    top_hm = data.get("health_metrics")
    if isinstance(top_hm, dict):
        for source_id, hm in top_hm.items():
            if isinstance(hm, dict):
                _check_health_metrics(f"health_metrics.{source_id}", hm, errors)


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def validate_config_dir(config_dir: Path) -> Dict[str, object]:
    errors: List[Dict[str, str]] = []
    warnings: List[str] = []

    resolved = check_paths(config_dir, errors)

    weights_path = resolved.get("configs", config_dir) / "source_weights.yaml"
    rules_path = resolved.get("configs", config_dir) / "feedback_rules.yaml"

    bounds = check_feedback_rules(rules_path, errors)
    check_source_weights(weights_path, bounds, errors)

    return {
        "ok": not errors,
        "config_dir": str(config_dir),
        "base_path": str(resolved.get("base", "")),
        "configs_path": str(resolved.get("configs", "")),
        "log_path": str(resolved.get("logs", "")),
        "errors": errors,
        "warnings": warnings,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate MID configs (CI gate)")
    parser.add_argument("--config-dir", help="directory holding paths.yaml / source_weights.yaml / feedback_rules.yaml")
    parser.add_argument("--json", action="store_true", help="emit JSON report")
    args = parser.parse_args(argv)

    config_dir = Path(args.config_dir).resolve() if args.config_dir else _default_config_dir()
    report = validate_config_dir(config_dir)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"config_dir: {report['config_dir']}")
        print(f"base_path : {report['base_path']}")
        print(f"configs   : {report['configs_path']}")
        print(f"log_path  : {report['log_path']}")
        if report["ok"]:
            print("PASS: all config checks passed")
        else:
            print(f"FAIL: {len(report['errors'])} error(s):")
            for err in report["errors"]:
                print(f"  - [{err['check']}] {err['ref']}: {err['message']}")
        for warn in report["warnings"]:
            print(f"WARN: {warn}")

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
