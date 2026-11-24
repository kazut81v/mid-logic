import os
import sys
import json
import yaml
import datetime

TEST_ROOT = "C:/Users/kazut.DESKTOP-28CC918/OneDrive/Vault/Memory/Projects/mid_logic/tests/e2e_S2_20261118_185504"

from weight_manager import update_health_metrics
from feedback_processor import process_feedback_log
from logger import log_event

CONF = os.path.join(TEST_ROOT, "configs", "paths.yaml")
os.environ["MID_TEST_CONFIG"] = CONF

print("=== S2 Regression: W2-01 to W2-06 ===")

# W2-01: Verify weight restored to 0.7
wm_path = os.path.join(TEST_ROOT, "configs", "source_weights.yaml")
wm = yaml.safe_load(open(wm_path, encoding="utf-8"))
gw = wm["sources"]["gov_official"]["base_weight"]
print(f"W2-01 gov base_weight: {gw} (expected 0.7)")
w2_01_pass = abs(gw - 0.7) < 1e-6

# W2-02: Health metrics update (failure then success)
r1 = update_health_metrics("gov_official", False)
r2 = update_health_metrics("gov_official", False)
r3 = update_health_metrics("gov_official", True)
wm = yaml.safe_load(open(wm_path, encoding="utf-8"))
final_cf = wm["sources"]["gov_official"]["health_metrics"]["consecutive_failures"]
print(f"W2-02 gov consecutive_failures: {final_cf} (expected 0)")
w2_02_pass = (r1["status"] == "success" and r2["status"] == "success" and r3["status"] == "success" and final_cf == 0)

# W2-03: Feedback processing - inappropriate (should decrease weight)
fb = os.path.join(TEST_ROOT, "test_feedback.jsonl")
# Backup original
with open(fb, "r") as f:
    orig_fb = f.read()
# Write test feedback
with open(fb, "w", encoding="utf-8") as f:
    for _ in range(3):
        f.write('{"source_id":"gov_official","feedback_type":"inappropriate","impact_score":1}\n')
r = process_feedback_log(fb)
print(f"W2-03 feedback result: {r}")
wm = yaml.safe_load(open(wm_path, encoding="utf-8"))
fbw = wm["sources"]["gov_official"]["base_weight"]
print(f"W2-03 gov base_weight after inappropriate x3: {fbw} (expected 0.4)")
# Starting from 0.7, 3 x -0.1 = 0.4
w2_03_pass = abs(fbw - 0.4) < 1e-6

# W2-04: Feedback processing - useful (should increase weight)
with open(fb, "w", encoding="utf-8") as f:
    for _ in range(2):
        f.write('{"source_id":"gov_official","feedback_type":"useful","impact_score":1}\n')
r = process_feedback_log(fb)
print(f"W2-04 feedback result: {r}")
wm = yaml.safe_load(open(wm_path, encoding="utf-8"))
fbw = wm["sources"]["gov_official"]["base_weight"]
print(f"W2-04 gov base_weight after useful x2: {fbw} (expected 0.44)")
# Starting from 0.4, 2 x +0.02 = 0.44
w2_04_pass = abs(fbw - 0.44) < 1e-6

# W2-05: Log infrastructure - write and verify
today = datetime.date.today().strftime("%Y%m%d")
logf = os.path.join(TEST_ROOT, "logs", f"log_{today}.jsonl")
for i in range(5):
    log_event("TestEngine", "test_action", f"req-{i}", "in", "out")
lines = [l for l in open(logf, encoding="utf-8") if l.strip()]
rows = [json.loads(l) for l in lines if l.strip()]
print(f"W2-05 daily log lines: {len(lines)}")
print(f"W2-05 valid JSON: {all(isinstance(r, dict) for r in rows)}")
new_engine = [r for r in rows if r.get("engine_id") == "TestEngine"]
print(f"W2-05 TestEngine events: {len(new_engine)} | correlation_id present: {all(r.get('correlation_id') for r in new_engine)}")
w2_05_pass = (len(lines) >= 5 and all(isinstance(r, dict) for r in rows) and len(new_engine) == 5 and all(r.get("correlation_id") for r in new_engine))

# W2-06: No scattered logs created
scattered_before = set()
for root, dirs, files in os.walk("C:/Users/kazut.DESKTOP-28CC918"):
    if "Feedback/logs" in root.split(os.sep) or "e2e_S2_20261118_185504/logs" in root.split(os.sep):
        continue
    for fn in files:
        if fn.startswith("log_") and fn.endswith(".jsonl"):
            scattered_before.add(os.path.abspath(os.path.join(root, fn)))

# Trigger some logging
log_event("TestEngine", "test_action", "scatter-check", "in", "out")

scattered_after = set()
for root, dirs, files in os.walk("C:/Users/kazut.DESKTOP-28CC918"):
    if "Feedback/logs" in root.split(os.sep) or "e2e_S2_20261118_185504/logs" in root.split(os.sep):
        continue
    for fn in files:
        if fn.startswith("log_") and fn.endswith(".jsonl"):
            scattered_after.add(os.path.abspath(os.path.join(root, fn)))
new_scatter = len(scattered_after - scattered_before)
print(f"W2-06 new scattered files created this run: {new_scatter}")
w2_06_pass = (new_scatter == 0)

# Restore original feedback file
with open(fb, "w") as f:
    f.write(orig_fb)

# Final verdict
all_pass = w2_01_pass and w2_02_pass and w2_03_pass and w2_04_pass and w2_05_pass and w2_06_pass
print(f"\nW2-01: {'PASS' if w2_01_pass else 'FAIL'}")
print(f"W2-02: {'PASS' if w2_02_pass else 'FAIL'}")
print(f"W2-03: {'PASS' if w2_03_pass else 'FAIL'}")
print(f"W2-04: {'PASS' if w2_04_pass else 'FAIL'}")
print(f"W2-05: {'PASS' if w2_05_pass else 'FAIL'}")
print(f"W2-06: {'PASS' if w2_06_pass else 'FAIL'}")
print(f"\nS2 Regression result: {'PASS' if all_pass else 'FAIL'}")
sys.exit(0 if all_pass else 1)
