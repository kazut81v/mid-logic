#!/usr/bin/env python3
"""Clip-range / feedback-rule validator - CI gate (TODO_CI_CLIP_VALIDATOR, S8).

Enforces, on every change to ``feedback_rules.yaml``:

1. ``weight_min < weight_max``
2. ``weight_min >= 0.0`` and ``weight_max <= 1.5`` (valid probability range)
3. every ``feedback_rules.*.source_weight_delta`` is numeric, finite and within
   ``[-1.0, 1.0]``

Exit code 0 = pass, 1 = validation failure (fail fast), 2 = environment error.

CLI::

    py -3.10 scripts/validate_feedback_rules.py [--rules PATH] [--json]

This module is also imported by the project-wide ``validate_configs.py``.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

try:
    import yaml
except ImportError:  # pragma: no cover - environment error
    print("FATAL: PyYAML is required (run with `py -3.10`)", file=sys.stderr)
    raise SystemExit(2)

DELTA_MIN = -1.0
DELTA_MAX = 1.0
ABS_WEIGHT_MIN = 0.0
ABS_WEIGHT_MAX = 1.5


def validate_feedback_rules(filepath: str) -> Tuple[bool, List[str], List[str]]:
    """Validate a ``feedback_rules.yaml`` file.

    Returns ``(ok, errors, warnings)``. ``errors`` are constraint violations
    (CI fails); ``warnings`` are non-fatal observations.
    """
    errors: List[str] = []
    warnings: List[str] = []
    path = Path(filepath)

    if not path.exists():
        return False, [f"file not found: {path}"], warnings

    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except Exception as exc:
        return False, [f"{path}: YAML parse error: {exc}"], warnings

    if not isinstance(data, dict):
        return False, [f"{path}: top level must be a mapping, got {type(data).__name__}"], warnings

    # --- clip range -------------------------------------------------------- #
    weight_min = data.get("weight_min")
    weight_max = data.get("weight_max")

    if weight_min is None:
        errors.append("weight_min: missing")
    elif not isinstance(weight_min, (int, float)) or isinstance(weight_min, bool):
        errors.append(f"weight_min: must be numeric, got {weight_min!r}")
    elif not math.isfinite(weight_min):
        errors.append(f"weight_min: must be finite, got {weight_min!r}")

    if weight_max is None:
        errors.append("weight_max: missing")
    elif not isinstance(weight_max, (int, float)) or isinstance(weight_max, bool):
        errors.append(f"weight_max: must be numeric, got {weight_max!r}")
    elif not math.isfinite(weight_max):
        errors.append(f"weight_max: must be finite, got {weight_max!r}")

    if not errors:
        if weight_min < ABS_WEIGHT_MIN:
            errors.append(
                f"weight_min: {weight_min} < {ABS_WEIGHT_MIN} (valid probability range)"
            )
        if weight_max > ABS_WEIGHT_MAX:
            errors.append(
                f"weight_max: {weight_max} > {ABS_WEIGHT_MAX} (valid probability range)"
            )
        if weight_min >= weight_max:
            errors.append(
                f"clip range violated: weight_min ({weight_min}) >= weight_max ({weight_max})"
            )

    # --- feedback rule deltas --------------------------------------------- #
    rules = data.get("feedback_rules")
    if rules is None:
        errors.append("feedback_rules: missing")
    elif not isinstance(rules, dict):
        errors.append(f"feedback_rules: must be a mapping, got {type(rules).__name__}")
    else:
        for feedback_type, rule in rules.items():
            label = f"feedback_rules.{feedback_type}"
            if not isinstance(rule, dict):
                errors.append(f"{label}: must be a mapping, got {type(rule).__name__}")
                continue
            delta = rule.get("source_weight_delta")
            if delta is None:
                errors.append(f"{label}.source_weight_delta: missing")
                continue
            if not isinstance(delta, (int, float)) or isinstance(delta, bool):
                errors.append(f"{label}.source_weight_delta: must be numeric, got {delta!r}")
                continue
            if not math.isfinite(delta):
                errors.append(f"{label}.source_weight_delta: must be finite, got {delta!r}")
                continue
            if delta < DELTA_MIN or delta > DELTA_MAX:
                errors.append(
                    f"{label}.source_weight_delta: {delta} outside [{DELTA_MIN}, {DELTA_MAX}]"
                )

    return (not errors), errors, warnings


def _default_rules_path() -> str:
    env = os.environ.get("MID_TEST_CONFIG")
    if env:
        return str(Path(env).resolve().parent / "feedback_rules.yaml")
    return str(Path(os.path.expanduser("~")) / "OneDrive" / "Vault" / "Memory" / "Configs" / "feedback_rules.yaml")


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate feedback_rules.yaml clip range")
    parser.add_argument(
        "--rules",
        default=_default_rules_path(),
        help="path to feedback_rules.yaml",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON report")
    args = parser.parse_args(argv)

    ok, errors, warnings = validate_feedback_rules(args.rules)

    if args.json:
        print(json.dumps({"ok": ok, "errors": errors, "warnings": warnings}, indent=2))
    else:
        print(f"file: {args.rules}")
        if ok:
            print("PASS: feedback_rules.yaml clip range and deltas are valid")
        else:
            print(f"FAIL: {len(errors)} violation(s):")
            for err in errors:
                print(f"  - {err}")
        for warn in warnings:
            print(f"WARN: {warn}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
