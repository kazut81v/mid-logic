# MID E2E Test Report: EC-06 through EC-10 (Scenario 6)

**Date:** 2026-11-20 (KST)
**Execution Session:** EC-06 through EC-10
**Test Isolation Directory:** `tests/e2e_20261120_195103/`
**Python:** 3.10.6 (py -3.10)
**Environment:** MID_TEST_MODE=1, MID_TEST_CONFIG=tests/e2e_20261120_195103/configs/paths.yaml

---

## Summary

| Scenario | Phase | Task | Status |
|----------|-------|------|--------|
| EC-06 | Inject | Create JSONL with one invalid line + valid lines | ✅ DONE |
| EC-07 | Detect | Run process_feedback_log, check json_decode_error log, count mismatch | ✅ DONE |
| EC-08 | Respond | Fix/remove bad line, re-run, verify line count = success count | ✅ DONE |
| EC-09 | Recover | Run TC-WF-02 regression (W2-01 through W2-06) | ✅ DONE |
| EC-10 | Prevent | Implement dead_letter output handling in feedback_processor.py | ✅ DONE |

---

## Detailed Results

### EC-06: Inject (bad JSONL)
- **File:** `tests/e2e_20261120_195103/bad_feedback.jsonl`
- **Contents:** 3 lines (2 valid + 1 invalid JSON line)
  ```
  {"source_id": "gov_official", "feedback_type": "inappropriate", "impact_score": 1}
  {invalid json line
  {"source_id": "gov_official", "feedback_type": "inappropriate", "impact_score": 1}
  ```
- **Verification:** File has 3 lines, line 2 is invalid JSON ✓

### EC-07: Detect
- **Command:** `process_feedback_log('tests/e2e_20261120_195103/bad_feedback.jsonl')`
- **Result:** "Feedback processed successfully."
- **Log entries detected:**
  - `json_decode_error` (×1): "Skipping malformed line" — "Expecting property name enclosed in double quotes: line 1 column 2 (char 1)"
  - `weight_updated` (×2): New weight: 0.1 (clipped at min 0.1)
  - `process_feedback_log_success` (×2): For each valid line
- **Detection:** `json_decode_error=1`, `success=2` (only valid lines processed), line count (3) > success count (2) ✓

### EC-08: Respond (fix + re-run)
- **Fix:** Removed invalid line from bad_feedback.jsonl
- **Result:** 2 valid lines processed, `weight_updated=2`, `success=2`
- **Verification:** line count (2) = success count (2), no decode errors ✓

### EC-09: Recover (TC-WF-02 regression)
- **Steps executed:**
  - W2-01: feedback_rules.yaml verified (inappropriate: {delta: -0.10}, weight_min: 0.1, weight_max: 1.5) ✓
  - W2-02: test_feedback.jsonl created with 3 inappropriate lines ✓
  - W2-03: process_feedback_log executed successfully ✓
  - W2-04: gov_official base_weight updated (delta -0.30 applied, clipped at min 0.1) ✓
  - W2-05: monitoring aggregation — weight_updated=success=7, no duplicate correlation_ids ✓
  - W2-06: save_weights_error=0 ✓
- **All TC-WF-02 steps PASS** ✓

### EC-10: Prevent (dead_letter implementation)
- **Implementation:** Added dead_letter output handling in `feedback_processor.py`
- **New functions:**
  - `get_dead_letter_path(ts=None)`: Returns dead_letter file path with timestamp
  - `write_dead_letter(failed_entry)`: Writes failed line to dead_letter file with metadata
- **Modified:** `process_feedback_log()` — json.JSONDecodeError handler now writes failed lines to dead_letter file
- **Dead_letter file created:** `logs/dead_letter_20261120_195539.jsonl`
- **Dead_letter content:**
  ```json
  {
    "timestamp": "2026-11-20T19:55:39.888698",
    "engine_id": "FeedbackProcessor",
    "action_type": "dead_letter",
    "correlation_id": "21808061c6934cd1912a503fb0704e98",
    "raw_line": "{invalid json line does not parse}",
    "error": "Expecting property name enclosed in double quotes: line 1 column 2 (char 1)",
    "source_id": "",
    "feedback_type": "",
    "impact_score": 0
  }
  ```
- **Verification:** Dead_letter file created with the failed line, json_decode_error and dead_letter_written events logged ✓

---

## Test Isolation Directory Structure

```
tests/e2e_20261120_195103/
├── configs/
│   ├── feedback_rules.yaml
│   ├── paths.yaml
│   ├── source_weights.yaml
│   └── source_weights.yaml.baseline
├── bad_feedback.jsonl
├── invalid_feedback.jsonl
├── logs/
│   ├── dead_letter_20261120_195539.jsonl
│   └── log_20261120.jsonl
└── test_feedback.jsonl
```

---

## Notes

1. **Log accumulation:** The log file (log_20261120.jsonl) is cumulative across all test runs. The counts in this report reflect the total, not just the latest run.

2. **Base weight:** The test isolation configs have gov_official base_weight=0.14. After applying 3 inappropriate feedbacks (delta -0.10 each), the weight is clipped at weight_min=0.1, resulting in base_weight=0.1.

3. **Dead_letter implementation:** The dead_letter file is created in the logs directory (resolved from base_path/log_path in the test configs/paths.yaml). Each failed line is written with its raw content, the JSON parse error, and metadata. The `dead_letter_written` event is logged for each failed line.

4. **Code changes:** feedback_processor.py was modified with:
   - LOG_DIR resolution (line 84-86)
   - get_dead_letter_path() function (line 89-93)
   - write_dead_letter() function (line 96-118)
   - Dead_letter writing in process_feedback_log() json.JSONDecodeError handler (line 167-176)

---

## Status: COMPLETE
