---
type: e2e-execution-roadmap
status: active
date: 2026-11-16
updated: 2026-11-16
author: hermes-agent
tags: [mid, operations, e2e-testing, phase5, roadmap]
related: "[[Memory/Projects/mid_logic/operations/e2e_test_plan.md]], [[Memory/Projects/mid_logic/operations/fault_response_flow.md]], [[Memory/Projects/mid_logic/operations/monitoring_design.md]], [[Memory/Projects/mid_logic/operations/rollback_plan.md]], [[Memory/Projects/mid_logic/operations/deployment_procedures.md]]"
---

# MID E2E Execution Roadmap (Phase 5 Operational Readiness)

**Purpose**: Convert the comprehensive E2E Test Plan into atomic, sequential tasks executable in single interactions.
**Approach**: Each task = one terminal session / one verification cycle. Tasks are ordered by dependency.

---

## Phase 0: Pre-Execution Checklist (Pre-requisites)

| ID | Task | Verification | Est. Time |
|----|------|--------------|-----------|
| P0-01 | Verify `py -3.10` exists and `yaml` module importable | `py -3.10 -c "import yaml; print('OK')"` | 1 min |
| P0-02 | Verify Vault root `OneDrive/Vault` exists and OneDrive "Always keep on this device" is ON | `ls "OneDrive/Vault" && echo "OK"` | 1 min |
| P0-03 | Verify source configs exist: `paths.yaml`, `source_weights.yaml`, `feedback_rules.yaml` | `ls OneDrive/Vault/Memory/Configs/` | 1 min |
| P0-04 | Verify `weight_manager.py`, `feedback_processor.py`, `logger.py` import without error | `py -3.10 -c "from weight_manager import *; from feedback_processor import *; from logger import *; print('OK')"` | 1 min |

> **Gate**: All P0 tasks must PASS before Phase 1.

---

## Phase 1: Setup & Prerequisites (Environment, Mocking, Isolation)

### 1.1 Test Isolation Environment Creation

| ID | Task | Command / Action | Verification | Est. Time |
|----|------|------------------|--------------|-----------|
| S1-01 | Create timestamped test root directory | `TS=$(date +%Y%m%d_%H%M%S); TEST_ROOT="OneDrive/Vault/Memory/Projects/mid_logic/tests/e2e_${TS}"; mkdir -p "${TEST_ROOT}/configs" "${TEST_ROOT}/logs"` | `ls "${TEST_ROOT}/configs" "${TEST_ROOT}/logs"` | 1 min |
| S1-02 | Copy production configs to test isolation | `cp "OneDrive/Vault/Memory/Configs/paths.yaml" "${TEST_ROOT}/configs/"` + `source_weights.yaml` + `feedback_rules.yaml` | `ls "${TEST_ROOT}/configs/"` | 1 min |
| S1-03 | Generate test `paths.yaml` pointing to isolation dirs | `cat > "${TEST_ROOT}/configs/paths.yaml" <<EOF\nbase_path: "${HOME}/${TEST_ROOT}"\nconfigs_path: "configs"\nlog_path: "logs"\nEOF` | `cat "${TEST_ROOT}/configs/paths.yaml"` | 1 min |
| S1-04 | Export test mode environment variables | `export MID_TEST_MODE=1; export MID_TEST_CONFIG="${HOME}/${TEST_ROOT}/configs/paths.yaml"` | `echo $MID_TEST_MODE $MID_TEST_CONFIG` | 1 min |
| S1-05 | Capture baseline `source_weights.yaml` snapshot | `cp "${TEST_ROOT}/configs/source_weights.yaml" "${TEST_ROOT}/configs/source_weights.yaml.baseline"` | `diff "${TEST_ROOT}/configs/source_weights.yaml" "${TEST_ROOT}/configs/source_weights.yaml.baseline" && echo "identical"` | 1 min |

> **Gate**: Test isolation ready. All paths resolve to `${TEST_ROOT}`.

---

## Phase 2: Core Workflows — Atomic Task Breakdown

### 2.1 TC-WF-01: Weight Update Flow (Health-Driven)

| ID | Task | Action | Expected Verification | Est. Time |
|----|------|--------|----------------------|-----------|
| W1-01 | Verify test `source_weights.yaml` has `gov_official` with `base_weight: 1.0`, `consecutive_failures: 0` | `py -3.10 -c "import yaml; d=yaml.safe_load(open('${TEST_ROOT}/configs/source_weights.yaml')); print(d['sources']['gov_official'])"` | Dict shows correct initial state | 1 min |
| W1-02 | Execute `update_health_metrics('gov_official', True)` once | `py -3.10 -c "from weight_manager import update_health_metrics; print(update_health_metrics('gov_official', True))"` | Returns success, `last_success` updated, `consecutive_failures=0` | 1 min |
| W1-03 | Verify weight file updated correctly after success | `py -3.10 -c "import yaml; d=yaml.safe_load(open('${TEST_ROOT}/configs/source_weights.yaml')); print(d['sources']['gov_official'])"` | `consecutive_failures: 0`, `last_success` recent | 1 min |
| W1-04 | Execute `update_health_metrics('gov_official', False)` twice | `py -3.10 -c "from weight_manager import update_health_metrics; print(update_health_metrics('gov_official', False)); print(update_health_metrics('gov_official', False))"` | Both return success, failures increment | 1 min |
| W1-05 | Verify `consecutive_failures=2` after two failures | `py -3.10 -c "import yaml; d=yaml.safe_load(open('${TEST_ROOT}/configs/source_weights.yaml')); print(d['sources']['gov_official']['consecutive_failures'])"` | Output: `2` | 1 min |
| W1-06 | Execute `update_health_metrics('gov_official', True)` to reset failures | `py -3.10 -c "from weight_manager import update_health_metrics; print(update_health_metrics('gov_official', True))"` | Returns success, failures reset to 0 | 1 min |
| W1-07 | Verify `consecutive_failures=0` after reset | `py -3.10 -c "import yaml; d=yaml.safe_load(open('${TEST_ROOT}/configs/source_weights.yaml')); print(d['sources']['gov_official']['consecutive_failures'])"` | Output: `0` | 1 min |
| W1-08 | Run monitoring aggregation to verify log integrity (zero error action_types) | `py -3.10 - <<'EOF'\nimport json, glob, datetime\np = f"${TEST_ROOT}/logs"\nf = f"{p}/log_{datetime.date.today():%Y%m%d}.jsonl"\nrows = [json.loads(l) for l in open(f, encoding="utf-8") if l.strip()]\nerr = [r for r in rows if "error" in r["action_type"]]\nwm  = [r for r in rows if r["engine_id"] == "WeightManager"]\nprint(f"total={len(rows)} err={len(err)} weightmanager={len(wm)}")\nfor r in err[:5]: print("ERR:", r["action_type"], r["output_summary"])\nEOF` | `err=0`, `weightmanager>=4` (4 calls logged) | 2 min |

> **TC-WF-01 PASS Gate**: All W1-01 through W1-08 PASS.

---

### 2.2 TC-WF-02: Feedback Processing Flow (Feedback-Driven)

| ID | Task | Action | Expected Verification | Est. Time |
|----|------|--------|----------------------|-----------|
| W2-01 | Verify test `feedback_rules.yaml` has `inappropriate: {source_weight_delta: -0.10}`, `weight_min: 0.1`, `weight_max: 1.5` | `py -3.10 -c "import yaml; print(yaml.safe_load(open('${TEST_ROOT}/configs/feedback_rules.yaml')))"` | Rules present and correct | 1 min |
| W2-02 | Create test feedback JSONL (3 inappropriate lines for gov_official) | `cat > "${TEST_ROOT}/test_feedback.jsonl" <<'EOF'\n{"source_id": "gov_official", "feedback_type": "inappropriate", "impact_score": 1}\n{"source_id": "gov_official", "feedback_type": "inappropriate", "impact_score": 1}\n{"source_id": "gov_official", "feedback_type": "inappropriate", "impact_score": 1}\nEOF` | `wc -l "${TEST_ROOT}/test_feedback.jsonl"` → `3` | 1 min |
| W2-03 | Execute `process_feedback_log` on test file | `py -3.10 -c "from feedback_processor import process_feedback_log; print(process_feedback_log('${TEST_ROOT}/test_feedback.jsonl'))"` | Returns success, 3 weight_updated events | 1 min |
| W2-04 | Verify final `base_weight = 0.7` (1.0 - 0.30, clipped at min 0.1) | `py -3.10 -c "import yaml; d=yaml.safe_load(open('${TEST_ROOT}/configs/source_weights.yaml')); print(d['sources']['gov_official']['base_weight'])"` | Output: `0.7` | 1 min |
| W2-05 | Run monitoring aggregation: verify `weight_updated` count = `process_feedback_log_success` count, no duplicates by correlation_id | `py -3.10 - <<'EOF'\nimport json, datetime, collections, re\np = f"${TEST_ROOT}/logs"\nf = f"{p}/log_{datetime.date.today():%Y%m%d}.jsonl"\nrows = [json.loads(l) for l in open(f, encoding="utf-8") if l.strip()]\nupd = [r for r in rows if r["action_type"] == "weight_updated"]\nsuc = [r for r in rows if r["action_type"] == "process_feedback_log_success"]\nper_type = collections.Counter(re.sub(r"Applied ", "", r["input_summary"]) for r in upd)\nprint(f"weight_updated={len(upd)} success={len(suc)} ratio={len(upd)}/{len(suc)}")\nfor k, v in per_type.items(): print(f"  {k}: {v}")\nEOF` | `weight_updated=3`, `success=1`, ratio 3/1, no duplicate correlation_ids | 2 min |
| W2-06 | Verify zero `save_weights_error` in logs | `py -3.10 -c "import json, datetime; p=f'${TEST_ROOT}/logs'; f=f'{p}/log_{datetime.date.today():%Y%m%d}.jsonl'; rows=[json.loads(l) for l in open(f) if l.strip()]; err=[r for r in rows if r.get('action_type')=='save_weights_error']; print(f'save_weights_error={len(err)}')"` | Output: `save_weights_error=0` | 1 min |

> **TC-WF-02 PASS Gate**: All W2-01 through W2-06 PASS.

---

### 2.3 TC-WF-03: Log Infrastructure Integrity Flow

| ID | Task | Action | Expected Verification | Est. Time |
|----|------|--------|----------------------|-----------|
| W3-01 | Emit 10 log events via `logger.log_event` with varied engine_ids | `py -3.10 -c "from logger import log_event; [log_event('TestEngine', 'test_action', f'req-{i}', f'input {i}', f'output {i}') for i in range(10)]"` | No exceptions raised | 1 min |
| W3-02 | Verify daily log file has 10 new lines (plus previous workflow logs) | `wc -l "${TEST_ROOT}/logs/log_$(date +%Y%m%d).jsonl"` | Line count increased by 10 | 1 min |
| W3-03 | Verify all lines parse as valid JSON | `py -3.10 -c "import json; [json.loads(l) for l in open('${TEST_ROOT}/logs/log_$(date +%Y%m%d).jsonl') if l.strip()]; print('All valid JSON')"` | No JSONDecodeError | 1 min |
| W3-04 | Verify no log files outside `logs/` directory (scatter check) | `find "$HOME" -name "log_*.jsonl" -not -path "*/Feedback/logs/*" -not -path "${TEST_ROOT}/logs/*" 2>/dev/null | wc -l` | Output: `0` | 1 min |
| W3-05 | Verify all 10 new events have `correlation_id: "none"` (current implementation) | `py -3.10 -c "import json; rows=[json.loads(l) for l in open('${TEST_ROOT}/logs/log_$(date +%Y%m%d).jsonl') if l.strip()]; new=[r for r in rows if r.get('engine_id')=='TestEngine']; print(f'TestEngine events: {len(new)}'); print(f'none correlation_id: {sum(1 for r in new if r.get(\"correlation_id\")==\"none\")}')` | All 10 have `correlation_id: "none"` | 1 min |

> **TC-WF-03 PASS Gate**: All W3-01 through W3-05 PASS.

---

### 2.4 Core Workflows Regression Verification (RS-01)

| ID | Task | Action | Expected Verification | Est. Time |
|----|------|--------|----------------------|-----------|
| RW-01 | Run full TC-WF-01, 02, 03 sequence again (regression) | Execute W1-01→W1-08, W2-01→W2-06, W3-01→W3-05 in order | All pass, no new error action_types | 10 min |
| RW-02 | Compare final `source_weights.yaml` against baseline | `diff -u "${TEST_ROOT}/configs/source_weights.yaml.baseline" "${TEST_ROOT}/configs/source_weights.yaml"` | Expected deltas only (gov_official weight=0.7, failures=0) | 1 min |

> **Phase 2 Complete Gate**: RW-01 and RW-02 PASS.

---

## Phase 3: Edge Case Testing — Scenario Groups (Logical Batches)

> Each Scenario follows 5-phase template: **Inject → Detect → Respond → Recover → Prevent**.
> Grouped by shared infrastructure / failure mode for efficient execution.

---

### 3.1 Group A: Configuration Corruption Scenarios (Scenarios 1, 4, 8)
*Shared: YAML file corruption, validator detection, config restore*

| ID | Scenario | Phase | Task | Action | Verification |
|----|----------|-------|------|--------|--------------|
| EA-01 | **S1: NaN/Inf Injection (P1)** | Inject | Corrupt `gov_official.base_weight` to `.nan` in test `source_weights.yaml` | `py -3.10 -c "import yaml; d=yaml.safe_load(open('${TEST_ROOT}/configs/source_weights.yaml')); d['sources']['gov_official']['base_weight'] = float('nan'); yaml.dump(d, open('${TEST_ROOT}/configs/source_weights.yaml','w'))"` | File contains `.nan` |
| EA-02 | S1 | Detect | Run validator (`math.isfinite` check) | `py -3.10 -c "import yaml, math; d=yaml.safe_load(open('${TEST_ROOT}/configs/source_weights.yaml')); print(all(math.isfinite(v['base_weight']) for v in d['sources'].values()))"` | Returns `False` |
| EA-03 | S1 | Respond | Pause cron, restore from baseline, re-verify all sources finite | `cp "${TEST_ROOT}/configs/source_weights.yaml.baseline" "${TEST_ROOT}/configs/source_weights.yaml"; py -3.10 -c "import yaml, math; d=yaml.safe_load(open('${TEST_ROOT}/configs/source_weights.yaml')); print(all(math.isfinite(v['base_weight']) for v in d['sources'].values()))"` | Returns `True` |
| EA-04 | S1 | Recover | Run TC-WF-01/02/03 regression (RW-01) | Execute RW-01 | All PASS |
| EA-05 | S1 | Prevent | Document: `validate_configs.py` needed for CI gate (Phase 6) | Create TODO note | Note recorded |
| EA-06 | **S4: sources list/dict Mismatch (P2)** | Inject | Rewrite `sources` as list format in test `source_weights.yaml` | `py -3.10 -c "import yaml; d=yaml.safe_load(open('${TEST_ROOT}/configs/source_weights.yaml')); d['sources'] = [{'id': 'gov_official', **d['sources']['gov_official']}]; yaml.dump(d, open('${TEST_ROOT}/configs/source_weights.yaml','w'))"` | `type(sources) == list` |
| EA-07 | S4 | Detect | Call `update_health_metrics` → expect error return | `py -3.10 -c "from weight_manager import update_health_metrics; print(update_health_metrics('gov_official', True))"` | Returns error dict with 'Source ID not found' |
| EA-08 | S4 | Respond | Fix YAML to dict format, verify success | `cp "${TEST_ROOT}/configs/source_weights.yaml.baseline" "${TEST_ROOT}/configs/source_weights.yaml"; py -3.10 -c "from weight_manager import update_health_metrics; print(update_health_metrics('gov_official', True))"` | Returns success |
| EA-09 | S4 | Recover | Run TC-WF-01 regression | Execute W1-01→W1-08 | All PASS |
| EA-10 | S4 | Prevent | Document: restrict direct config edits, add validator (Phase 6) | Create TODO note | Note recorded |
| EA-11 | **S8: Clip Range Corruption (P1)** | Inject | Swap `weight_min: 1.5, weight_max: 0.1` in test `feedback_rules.yaml` | `py -3.10 -c "import yaml; d=yaml.safe_load(open('${TEST_ROOT}/configs/feedback_rules.yaml')); d['weight_min'], d['weight_max'] = 1.5, 0.1; yaml.dump(d, open('${TEST_ROOT}/configs/feedback_rules.yaml','w'))"` | min ≥ max |
| EA-12 | S8 | Detect | Run validator `assert weight_min < weight_max` | `py -3.10 -c "import yaml; d=yaml.safe_load(open('${TEST_ROOT}/configs/feedback_rules.yaml')); print(d['weight_min'] < d['weight_max'])"` | Returns `False` |
| EA-13 | S8 | Respond | Restore baseline rules (L1 rollback) | `cp "${TEST_ROOT}/configs/feedback_rules.yaml.baseline" "${TEST_ROOT}/configs/feedback_rules.yaml"` (create baseline first if needed) | Rules restored |
| EA-14 | S8 | Recover | Run TC-WF-02 regression | Execute W2-01→W2-06 | All PASS |
| EA-15 | S8 | Prevent | Document: validator for clip range in CI (Phase 6) | Create TODO note | Note recorded |

---

### 3.2 Group B: Runtime Environment Scenarios (Scenarios 3, 5, 7)
*Shared: CWD, path resolution, cron execution environment*

| ID | Scenario | Phase | Task | Action | Verification |
|----|----------|-------|------|--------|--------------|
| EB-01 | **S3: Log Scatter / Write Failure (P1/P2)** | Inject | Temporarily change `paths.yaml` `base_path` to `$TMPDIR` | `cat > "${TEST_ROOT}/configs/paths.yaml" <<EOF\nbase_path: "${TEMP}"\nconfigs_path: "configs"\nlog_path: "logs"\nEOF` | Paths point to temp |
| EB-02 | S3 | Inject | Emit log event, verify scatter outside test logs | `py -3.10 -c "from logger import log_event; log_event('TestEngine', 'test_action', 'req-1', 'in', 'out')" && find "$HOME" -name "log_*.jsonl" -not -path "${TEST_ROOT}/logs/*" -not -path "*/Feedback/logs/*" 2>/dev/null` | Scattered log found in temp |
| EB-03 | S3 | Detect | Run scatter detection command | `find "$HOME" -name "log_*.jsonl" -not -path "*/Feedback/logs/*" 2>/dev/null | grep -v "${TEST_ROOT}" | wc -l` | Count > 0 |
| EB-04 | S3 | Respond | Fix `paths.yaml` to correct test path, move scattered logs, set OneDrive "Always keep" | `cat > "${TEST_ROOT}/configs/paths.yaml" <<EOF\nbase_path: "${HOME}/${TEST_ROOT}"\nconfigs_path: "configs"\nlog_path: "logs"\nEOF` | Paths corrected |
| EB-05 | S3 | Recover | Run TC-WF-03 regression | Execute W3-01→W3-05 | All PASS, zero scatter |
| EB-06 | S3 | Prevent | Document: cron `--workdir "$HOME"` enforcement (CI) | Create TODO note | Note recorded |
| EB-07 | **S5: CWD Dependency Silent Failure (P2)** | Inject | `cd /tmp` and run `weight_manager.update_health_metrics` | `cd /tmp && py -3.10 -c "from weight_manager import update_health_metrics; print(update_health_metrics('gov_official', True))"` | Returns empty weights or error |
| EB-08 | S5 | Detect | Check for `weights_file_missing` or `config_load_error` in logs | `py -3.10 -c "import json, datetime; p=f'${TEST_ROOT}/logs'; f=f'{p}/log_{datetime.date.today():%Y%m%d}.jsonl'; rows=[json.loads(l) for l in open(f) if l.strip()]; err=[r for r in rows if 'error' in r.get('action_type','')]; print([r['action_type'] for r in err])"` | Error action_types present |
| EB-09 | S5 | Respond | `cd "$HOME"` and re-run, verify success | `cd "$HOME" && py -3.10 -c "from weight_manager import update_health_metrics; print(update_health_metrics('gov_official', True))"` | Returns success |
| EB-10 | S5 | Recover | Run TC-WF-01 regression | Execute W1-01→W1-08 | All PASS |
| EB-11 | S5 | Prevent | Document: `os.chdir(os.path.expanduser("~"))` in runner (Phase 6) | Create TODO note | Note recorded |
| EB-12 | **S7: Cron Execution Failure (P2)** | Inject | Simulate missing interpreter: rename `py` temporarily or use invalid command | `py -3.10 -c "import sys; print(sys.executable)"` (verify current), then test with `hermes cron runs mid-morning-digest` (check status) | Cron shows error or simulated failure |
| EB-13 | S7 | Detect | Run `hermes cron runs mid-morning-digest` check status | `hermes cron runs mid-morning-digest` | Shows `error` state |
| EB-14 | S7 | Respond | Verify interpreter, dependencies, re-run manually | `py -3.10 --version && py -3.10 -c "import yaml"` then `hermes cron run mid-morning-digest` | Manual run succeeds |
| EB-15 | S7 | Recover | Run full core workflow regression | Execute RW-01 | All PASS |
| EB-16 | S7 | Prevent | Document: env check at script start (interpreter, deps, disk, perms) | Create TODO note | Note recorded |

---

### 3.3 Group C: Data Processing Scenarios (Scenarios 2, 6)
*Shared: Feedback processing, JSONL parsing, duplicate detection*

| ID | Scenario | Phase | Task | Action | Verification |
|----|----------|-------|------|--------|--------------|
| EC-01 | **S2: Feedback Double Apply (P2)** | Inject | Run `process_feedback_log` twice on same test file (simulate missing `save_weights` move) | `py -3.10 -c "from feedback_processor import process_feedback_log; print(process_feedback_log('${TEST_ROOT}/test_feedback.jsonl'))" && py -3.10 -c "from feedback_processor import process_feedback_log; print(process_feedback_log('${TEST_ROOT}/test_feedback.jsonl'))"` | Second run applies delta again |
| EC-02 | S2 | Detect | Check `weight_updated` count > `success` count, duplicate correlation_ids | `py -3.10 - <<'EOF'\nimport json, datetime, collections, re\np = f"${TEST_ROOT}/logs"\nf = f"{p}/log_{datetime.date.today():%Y%m%d}.jsonl"\nrows = [json.loads(l) for l in open(f, encoding="utf-8") if l.strip()]\nupd = [r for r in rows if r["action_type"] == "weight_updated"]\nsuc = [r for r in rows if r["action_type"] == "process_feedback_log_success"]\nprint(f"weight_updated={len(upd)} success={len(suc)}")\n# Check correlation_id duplicates\nids = [r.get("correlation_id") for r in upd if r.get("correlation_id") != "none"]\nprint(f"correlation_ids: {ids}")\nprint(f"duplicates: {len(ids) != len(set(ids))}")\nEOF` | `weight_updated=6`, `success=2`, duplicate correlation_ids present | 2 min |
| EC-03 | S2 | Respond | Manually restore correct weight (0.7), document fix | `py -3.10 -c "import yaml; d=yaml.safe_load(open('${TEST_ROOT}/configs/source_weights.yaml')); d['sources']['gov_official']['base_weight'] = 0.7; yaml.dump(d, open('${TEST_ROOT}/configs/source_weights.yaml','w'))"` | Weight restored to 0.7 |
| EC-04 | S2 | Recover | Run TC-WF-02 regression | Execute W2-01→W2-06 | All PASS |
| EC-05 | S2 | Prevent | Document: `save_weights()` move out of loop (Phase 6 refactor) | Create TODO note | Note recorded |
| EC-06 | **S6: Feedback Parse Failure Undetected (P3)** | Inject | Create JSONL with one invalid line + valid lines | `cat > "${TEST_ROOT}/bad_feedback.jsonl" <<'EOF'\n{"source_id": "gov_official", "feedback_type": "inappropriate", "impact_score": 1}\n{invalid json line\n{"source_id": "gov_official", "feedback_type": "inappropriate", "impact_score": 1}\nEOF` | File has 3 lines, line 2 invalid | 1 min |
| EC-07 | S6 | Detect | Run `process_feedback_log`, check `json_decode_error` log, count mismatch | `py -3.10 -c "from feedback_processor import process_feedback_log; print(process_feedback_log('${TEST_ROOT}/bad_feedback.jsonl'))" && py -3.10 -c "import json, datetime; p=f'${TEST_ROOT}/logs'; f=f'{p}/log_{datetime.date.today():%Y%m%d}.jsonl'; rows=[json.loads(l) for l in open(f) if l.strip()]; err=[r for r in rows if r.get('action_type')=='json_decode_error']; suc=[r for r in rows if r.get('action_type')=='process_feedback_log_success']; print(f'json_decode_error={len(err)} success={len(suc)}')"` | `json_decode_error>=1`, `success=1` (only valid lines) | 2 min |
| EC-08 | S6 | Respond | Fix/remove bad line, re-run, verify line count = success count | `cat > "${TEST_ROOT}/bad_feedback.jsonl" <<'EOF'\n{"source_id": "gov_official", "feedback_type": "inappropriate", "impact_score": 1}\n{"source_id": "gov_official", "feedback_type": "inappropriate", "impact_score": 1}\nEOF` then re-run | `success=2`, no decode errors | 1 min |
| EC-09 | S6 | Recover | Run TC-WF-02 regression | Execute W2-01→W2-06 | All PASS |
| EC-10 | S6 | Prevent | Document: DEAD_LETTER output for failed lines (Phase 6) | Create TODO note | Note recorded |

---

## Phase 4: Verification & Completion

### 4.1 Final Regression Suite (RS-01 Full)

| ID | Task | Action | Verification | Est. Time |
|----|------|--------|--------------|-----------|
| V-01 | Execute complete TC-WF-01, 02, 03 sequence one final time | Run all W1, W2, W3 tasks in order | All PASS, zero error action_types | 10 min |
| V-02 | Run monitoring design aggregation scripts (§3.2 and §4.2) | Execute both aggregation scripts from test plan §7.3 | All invariants satisfied (§2.4) | 3 min |
| V-03 | Verify fault_response_flow.md coverage | Check all 8 Scenarios have Phase A-E executed | Coverage matrix complete | 2 min |
| V-04 | Verify rollback_plan.md L0/L1/L2 exercised | Confirm Scenarios 1,4,8 (L1), 3,5,7 (L0/L2) tested | Rollback procedures validated | 2 min |
| V-05 | Verify deployment_procedures.md R1 (CWD fixed) | Confirm cron workdir enforcement tested in S5/S7 | R1 validated | 1 min |

### 4.2 Test Report Generation

| ID | Task | Action | Output | Est. Time |
|----|------|--------|--------|-----------|
| V-06 | Generate E2E Test Report per §8.2 template | Fill markdown template with results | `E2E_Test_Report_YYYY-MM-DD.md` in test root | 5 min |
| V-07 | Archive test isolation environment | `tar -czf "${TEST_ROOT}.tar.gz" "${TEST_ROOT}" && rm -rf "${TEST_ROOT}"` | Archive created, test dir cleaned | 2 min |
| V-08 | Clear test environment variables | `unset MID_TEST_MODE; unset MID_TEST_CONFIG` | Env vars unset | 1 min |

### 4.3 Go/No-Go Decision

| ID | Task | Criteria | Decision |
|----|------|----------|----------|
| V-09 | Final gate evaluation | All Phase 2 PASS, all Phase 3 Scenarios A-E complete, Phase 4 V-01 through V-05 PASS | **PASS → Release / Operate** / **CONDITIONAL** / **FAIL → Block** |

---

## Execution Order Summary (Linearized)

```
P0-01 → P0-02 → P0-03 → P0-04
  ↓
S1-01 → S1-02 → S1-03 → S1-04 → S1-05
  ↓
W1-01 → W1-02 → W1-03 → W1-04 → W1-05 → W1-06 → W1-07 → W1-08
  ↓
W2-01 → W2-02 → W2-03 → W2-04 → W2-05 → W2-06
  ↓
W3-01 → W3-02 → W3-03 → W3-04 → W3-05
  ↓
RW-01 → RW-02
  ↓
EA-01 → EA-02 → EA-03 → EA-04 → EA-05
EA-06 → EA-07 → EA-08 → EA-09 → EA-10
EA-11 → EA-12 → EA-13 → EA-14 → EA-15
  ↓
EB-01 → EB-02 → EB-03 → EB-04 → EB-05 → EB-06
EB-07 → EB-08 → EB-09 → EB-10 → EB-11
EB-12 → EB-13 → EB-14 → EB-15 → EB-16
  ↓
EC-01 → EC-02 → EC-03 → EC-04 → EC-05
EC-06 → EC-07 → EC-08 → EC-09 → EC-10
  ↓
V-01 → V-02 → V-03 → V-04 → V-05 → V-06 → V-07 → V-08 → V-09
```

---

## Task Sizing Guidelines

- **Each task** = single terminal command or short script (≤ 2 min execution)
- **Each verification** = single command with clear PASS/FAIL output
- **No task** depends on unverified prior output
- **Gates** (TC-WF-01/02/03 PASS, Phase 2 complete, Phase 3 groups complete) are mandatory checkpoints

---

## Next Action Recommendation

### **START HERE: P0-01** — Verify Python 3.10 and PyYAML availability

```bash
py -3.10 -c "import yaml; print('PyYAML OK')"
```

**Why**: This is the absolute prerequisite. If this fails, the entire test environment is invalid and must be fixed before any other task. Takes < 30 seconds.

**Expected**: `PyYAML OK` printed. If error → install Python 3.10 / PyYAML first.

---

## Progress Tracking

Use this checklist during execution:

```
[ ] P0-01  [ ] P0-02  [ ] P0-03  [ ] P0-04
[ ] S1-01  [ ] S1-02  [ ] S1-03  [ ] S1-04  [ ] S1-05
[ ] W1-01  [ ] W1-02  [ ] W1-03  [ ] W1-04  [ ] W1-05  [ ] W1-06  [ ] W1-07  [ ] W1-08
[ ] W2-01  [ ] W2-02  [ ] W2-03  [ ] W2-04  [ ] W2-05  [ ] W2-06
[ ] W3-01  [ ] W3-02  [ ] W3-03  [ ] W3-04  [ ] W3-05
[ ] RW-01  [ ] RW-02
[ ] EA-01  [ ] EA-02  [ ] EA-03  [ ] EA-04  [ ] EA-05
[ ] EA-06  [ ] EA-07  [ ] EA-08  [ ] EA-09  [ ] EA-10
[ ] EA-11  [ ] EA-12  [ ] EA-13  [ ] EA-14  [ ] EA-15
[ ] EB-01  [ ] EB-02  [ ] EB-03  [ ] EB-04  [ ] EB-05  [ ] EB-06
[ ] EB-07  [ ] EB-08  [ ] EB-09  [ ] EB-10  [ ] EB-11
[ ] EB-12  [ ] EB-13  [ ] EB-14  [ ] EB-15  [ ] EB-16
[ ] EC-01  [ ] EC-02  [ ] EC-03  [ ] EC-04  [ ] EC-05
[ ] EC-06  [ ] EC-07  [ ] EC-08  [ ] EC-09  [ ] EC-10
[ ] V-01   [ ] V-02   [ ] V-03   [ ] V-04   [ ] V-05   [ ] V-06   [ ] V-07   [ ] V-08   [ ] V-09
```

---

**Total Estimated Time**: ~60-75 minutes for full execution (single pass, no retries).
**Recommended Session Breakdown**: 3-4 sessions of 20-25 minutes each (Phase 0-1, Phase 2, Phase 3, Phase 4).