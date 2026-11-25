import os
import sys
import json
import yaml
import datetime

TEST_ROOT = "C:/Users/kazut.DESKTOP-28CC918/OneDrive/Vault/Memory/Projects/mid_logic/tests/e2e_S7_20261118"

from weight_manager import update_health_metrics  # noqa: E402
from feedback_processor import process_feedback_log  # noqa: E402
from logger import log_event  # noqa: E402


CONF = os.path.join(TEST_ROOT, "configs", "paths.yaml")
os.environ["MID_TEST_CONFIG"] = CONF

print("=== RW-01 regression: full core workflow (TC-WF-01/02/03) ===")

# TC-WF-01: weight update
r2 = update_health_metrics("gov_official", False)
r3 = update_health_metrics("gov_official", False)
r4 = update_health_metrics("gov_official", True)
print("TC-WF-01 gov success:", r4["status"])
wm_path = os.path.join(TEST_ROOT, "configs", "source_weights.yaml")
wm = yaml.safe_load(open(wm_path, encoding="utf-8"))
gw = wm["sources"]["gov_official"]["base_weight"]
final_cf = wm["sources"]["gov_official"]["health_metrics"]["consecutive_failures"]
print("TC-WF-01 gov base_weight: %.12f | final consecutive_failures: %d" % (gw, final_cf))

# TC-WF-02: feedback processing
fb = os.path.join(TEST_ROOT, "test_feedback.jsonl")
with open(fb, "w", encoding="utf-8") as f:
    for _ in range(3):
        f.write('{"source_id":"gov_official","feedback_type":"inappropriate","impact_score":1}\n')
r = process_feedback_log(fb)
print("TC-WF-02:", r)
w = yaml.safe_load(open(os.path.join(TEST_ROOT, "configs", "source_weights.yaml")))
gw = w["sources"]["gov_official"]["base_weight"]
fbw = w["sources"]["gov_official"]["base_weight"]
delta_expected = -0.30
print("TC-WF-02 gov base_weight: %.12f (initial %.12f -> expect %.12f)" % (fbw, gw, gw + delta_expected))
print("TC-WF-02 gov base_weight == initial-0.30:", abs(fbw - (gw + delta_expected)) < 1e-6)

# TC-WF-03: log infrastructure
today = datetime.date.today().strftime("%Y%m%d")
logf = os.path.join(TEST_ROOT, "logs", "log_%s.jsonl" % today)
for i in range(10):
    log_event("TestEngine", "test_action", "req-%d" % i, "in", "out")
lines = [l for l in open(logf, encoding="utf-8") if l.strip()]
rows = [json.loads(l) for l in lines if l.strip()]
print("TC-WF-03 daily log lines:", len(lines))
print("TC-WF-03 valid JSON:", all(isinstance(r, dict) for r in rows))
new_engine = [r for r in rows if r.get("engine_id") == "TestEngine"]
print("TC-WF-03 TestEngine events:", len(new_engine), "| correlation_id present:", all(r.get("correlation_id") for r in new_engine))

# Pre-run snapshot of scattered logs (whole drive, excluding fixture dirs)
scattered_before = set()
for root, dirs, files in os.walk("C:/Users/kazut.DESKTOP-28CC918"):
    if "Feedback/logs" in root.split(os.sep) or "e2e_S7_20261118/logs" in root.split(os.sep):
        continue
    for fn in files:
        if fn.startswith("log_") and fn.endswith(".jsonl"):
            scattered_before.add(os.path.abspath(os.path.join(root, fn)))
print("TC-WF-03 scatter (before run):", len(scattered_before))

# Post-run snapshot
scattered_after = set()
for root, dirs, files in os.walk("C:/Users/kazut.DESKTOP-28CC918"):
    if "Feedback/logs" in root.split(os.sep) or "e2e_S7_20261118/logs" in root.split(os.sep):
        continue
    for fn in files:
        if fn.startswith("log_") and fn.endswith(".jsonl"):
            scattered_after.add(os.path.abspath(os.path.join(root, fn)))
new_scatter = len(scattered_after - scattered_before)
print("TC-WF-03 new scattered files created this run:", new_scatter)

# Verdict
ok = (
    r2["status"] == "success" and r3["status"] == "success" and r4["status"] == "success"
    and final_cf == 0
    and fbw == max(0.1, gw + delta_expected)
    and len(lines) >= 10 and all(isinstance(r, dict) for r in rows)
    and {"req-%d"%i for i in range(10)} <= {r.get("correlation_id") for r in new_engine}
    and new_scatter == 0
)
print("RW-01 regression result:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
