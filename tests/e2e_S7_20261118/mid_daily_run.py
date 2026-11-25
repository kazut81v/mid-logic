#!/usr/bin/env python3
"""
MID daily runner (S7 DRILL - BROKEN).
Simulates cron execution failure caused by an invalid/spoofed interpreter
and a missing dependency, so the cron job reports a FAILURE status.
"""
import os
import sys

print("mid-morning-digest START", flush=True)

# Simulated interpreter/spoofing defect:
#   - The job declared an invalid interpreter ("python3.10" is not on PATH;
#     the real launcher is `py -3.10").
#   - A missing dependency module (yaml is available, so we force another).
try:
    import missing_module_for_s7_drill  # noqa: F401
except ImportError as exc:  # pragma: no cover - deliberate
    print(f"FATAL: interpreter/missing-dep check failed: {exc}", flush=True)
    sys.exit(1)

print("mid-morning-digest FINISH", flush=True)
