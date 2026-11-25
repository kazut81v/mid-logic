# TODO: Clip Range Validator for CI Gate (Phase 6)

## Context
Scenario S8 (EA-11 to EA-15) tested the feedback rule validation flow:
- EA-11: Injected corruption by swapping weight_min (1.5) and weight_max (0.1) in feedback_rules.yaml
- EA-12: Detected violation via validator script (assert weight_min < weight_max)
- EA-13: Restored baseline rules (L1 rollback)
- EA-14: Ran TC-WF-02 regression (W2-01 to W2-06) - all passed
- EA-15: This TODO documents the prevention step

## Required CI Gate Enhancement
Add a clip range validator to the CI pipeline that enforces:
1. `weight_min < weight_max` in feedback_rules.yaml
2. `weight_min >= 0.0` and `weight_max <= 1.5` (valid probability range)
3. All `source_weight_delta` values are within reasonable bounds (e.g., -1.0 to 1.0)

## Implementation Location
- Add validator script to `scripts/validate_feedback_rules.py` (or similar)
- Integrate into CI workflow (GitHub Actions / pre-commit hook)
- Run on every PR that modifies `configs/feedback_rules.yaml`

## Acceptance Criteria
- CI fails fast if weight_min >= weight_max
- CI fails if weight_min < 0 or weight_max > 1.5
- Clear error message indicating which constraint violated
- Documented in Phase 6 implementation plan

## Related Files
- Test configs: `configs/feedback_rules.yaml`
- Validator used in test: `validate_feedback_rules.py`
- Baseline: `configs/feedback_rules.yaml.baseline`

## Status
- [ ] Create standalone validator script for CI
- [ ] Add CI workflow step
- [ ] Add pre-commit hook
- [ ] Update Phase 6 documentation