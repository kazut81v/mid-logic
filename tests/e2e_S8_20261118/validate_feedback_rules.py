#!/usr/bin/env python3
"""Validator for feedback_rules.yaml - checks weight_min < weight_max"""
import yaml
import sys

def validate_feedback_rules(filepath):
    with open(filepath, 'r') as f:
        data = yaml.safe_load(f)
    
    weight_min = data.get('weight_min')
    weight_max = data.get('weight_max')
    
    if weight_min is None or weight_max is None:
        print("ERROR: weight_min or weight_max not found in config")
        return False
    
    print(f"weight_min: {weight_min}")
    print(f"weight_max: {weight_max}")
    
    if weight_min < weight_max:
        print("PASS: weight_min < weight_max")
        return True
    else:
        print(f"FAIL: weight_min ({weight_min}) >= weight_max ({weight_max})")
        return False

if __name__ == "__main__":
    filepath = "configs/feedback_rules.yaml"
    success = validate_feedback_rules(filepath)
    sys.exit(0 if success else 1)