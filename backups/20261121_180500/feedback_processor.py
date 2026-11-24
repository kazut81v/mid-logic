import json
import os
import uuid
from datetime import datetime
import yaml
from pathlib import Path
from logger import log_event


# Configuration (Paths will be resolved by load_config)
DEFAULT_CONFIG_PATH = "OneDrive/Vault/Memory/Configs/paths.yaml"

def _resolve_default_config_path():
    """Resolve the default config path relative to user home directory."""
    return Path(os.path.expanduser("~")) / DEFAULT_CONFIG_PATH

def load_config():
    # 1. 環境変数の優先 (explicit test config)
    test_config = os.environ.get("MID_TEST_CONFIG")
    if test_config:
        try:
            with open(test_config, 'r') as f:
                return yaml.safe_load(f)
        except Exception:
            pass
    
    # 2. 本番用・デフォルト (production config FIRST)
    try:
        default_path = _resolve_default_config_path()
        with open(default_path, 'r') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        pass
    except Exception as e:
        log_event("FeedbackProcessor", "config_load_error", uuid.uuid4().hex, "Failed to load config", str(e))
    
    # 3. テスト設定のフォールバック (test configs as fallback)
    import glob
    potential_configs = glob.glob("tests/*/configs/paths.yaml")
    if potential_configs:
        try:
            config_path = potential_configs[0]
            with open(config_path, 'r') as f:
                return yaml.safe_load(f)
        except Exception:
            pass
    
    # 4. ハードコードされたフォールバック
    return {
        "base_path": "OneDrive/Vault",
        "configs_path": "Memory/Configs",
        "log_path": "Memory/Feedback/logs"
    }

# Load configuration globally
config = load_config()
BASE_PATH = config.get("base_path", "OneDrive/Vault")
raw_base = BASE_PATH
# Handle Unix-style absolute paths like /c/Users/... on Windows
if raw_base.startswith("/") and len(raw_base) > 2 and raw_base[2] == "/":
    # Convert /c/Users/... to C:/Users/...
    drive_letter = raw_base[1].upper()
    base_path_obj = Path(f"{drive_letter}:{raw_base[2:]}")
elif not raw_base.startswith("/"):
    base_path_obj = Path(raw_base)
    # Fix: Check if path contains "OneDrive" (parts are split, so check for "OneDrive" in parts)
    if "OneDrive" in base_path_obj.parts:
        # Resolve relative to user home directory, preserving full path structure
        base_path_obj = Path(os.path.expanduser("~")) / base_path_obj
    else:
        # Fallback for relative paths in current dir
        base_path_obj = Path(__file__).parent / base_path_obj
else:
    base_path_obj = Path(raw_base)

# Resolve CONFIG_DIR
configs_rel = config.get("configs_path", "Memory/Configs")
CONFIG_DIR = (base_path_obj / configs_rel).resolve()

# Define resource paths based on loaded config
WEIGHTS_FILE = CONFIG_DIR / "source_weights.yaml"
RULES_FILE = CONFIG_DIR / "feedback_rules.yaml"

# Resolve log directory path for dead_letter output
LOG_REL = config.get("log_path", "Memory/Feedback/logs")
LOG_DIR = (base_path_obj / LOG_REL).resolve()


def get_dead_letter_path(ts=None):
    """Get the dead_letter file path with timestamp for failed line isolation."""
    if ts is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return LOG_DIR / f"dead_letter_{ts}.jsonl"


def write_dead_letter(failed_entry):
    """
    Write a failed line to the dead_letter file.
    Returns the dead_letter file path.
    """
    dl_path = get_dead_letter_path()
    dl_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now().isoformat(),
        "engine_id": "FeedbackProcessor",
        "action_type": "dead_letter",
        "correlation_id": uuid.uuid4().hex,
        "raw_line": failed_entry.get("raw_line", ""),
        "error": failed_entry.get("error", ""),
        "source_id": failed_entry.get("source_id", ""),
        "feedback_type": failed_entry.get("feedback_type", ""),
        "impact_score": failed_entry.get("impact_score", 0)
    }
    with open(dl_path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    log_event("FeedbackProcessor", "dead_letter_written", uuid.uuid4().hex,
              "Failed line written to dead_letter", f"File: {dl_path}")
    return dl_path

def load_weights():
    try:
        with open(WEIGHTS_FILE, 'r') as f:
            data = yaml.safe_load(f)
            if data and 'sources' in data:
                if isinstance(data['sources'], list):
                    data['sources'] = {s.get('id'): s for s in data['sources'] if 'id' in s}
            return data
    except Exception as e:
        log_event("FeedbackProcessor", "load_weights_error", uuid.uuid4().hex, "Attempting to load weights", str(e))
        return {"sources": {}}

def save_weights(weights):
    try:
        with open(WEIGHTS_FILE, 'w') as f:
            yaml.dump(weights, f, default_flow_style=False)
    except Exception as e:
        log_event("FeedbackProcessor", "save_weights_error", uuid.uuid4().hex, "Attempting to save weights", str(e))

def load_rules():
    try:
        with open(RULES_FILE, 'r') as f:
            return yaml.safe_load(f)
    except Exception as e:
        log_event("FeedbackProcessor", "load_rules_error", uuid.uuid4().hex, "Attempting to load rules", str(e))
        return {}

def process_feedback_log(log_file):
    """
    Processes a single JSONL feedback log and updates source weights.
    """
    try:
        rules = load_rules()
        print(f"DEBUG: Loaded rules: {rules}")
        weights = load_weights()
        
        if not os.path.exists(log_file):
            log_event("FeedbackProcessor", "log_file_missing", uuid.uuid4().hex, "Input log file not found", log_file)
            return "Log file missing."
            
        with open(log_file, 'r') as f:
            for line in f:
                if not line.strip(): continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError as e:
                    log_event("FeedbackProcessor", "json_decode_error", uuid.uuid4().hex, "Skipping malformed line", str(e))
                    # Write failed line to dead_letter file for isolation
                    failed_entry = {
                        "raw_line": line.rstrip("\n"),
                        "error": str(e),
                        "source_id": "",
                        "feedback_type": "",
                        "impact_score": 0
                    }
                    dl_path = write_dead_letter(failed_entry)
                    continue
                    
                source_id = entry.get("source_id")
                feedback_type = entry.get("feedback_type")
                impact_score = entry.get("impact_score", 0)
                
                if source_id in weights['sources']:
                    source = weights['sources'][source_id]
                    
                    # Apply rule-based delta if exists
                    if feedback_type in rules.get("feedback_rules", {}):
                        delta = rules["feedback_rules"][feedback_type].get("source_weight_delta", 0)
                        # Apply delta and clip
                        new_weight = source.get("base_weight", 1.0) + delta
                        source["base_weight"] = max(rules.get("weight_min", 0.1), min(rules.get("weight_max", 1.5), new_weight))
                        log_event("FeedbackProcessor", "weight_updated", f"{source_id}-{uuid.uuid4().hex}", f"Applied {feedback_type}", f"New weight: {source['base_weight']}")
                    
                    save_weights(weights)
                    log_event("FeedbackProcessor", "process_feedback_log_success", f"{source_id}-{uuid.uuid4().hex}", 
                               f"Feedback type: {feedback_type}", 
                               f"Impact score: {impact_score}")
        return "Feedback processed successfully."
    except Exception as e:
        log_event("FeedbackProcessor", "process_log_error", uuid.uuid4().hex, "Critical error in processing", str(e))
        return f"Error: {str(e)}"

# --------------------------------------------------------------------------- #
# L2 code rollback (S4) - implementation lives in code_rollback.py
# --------------------------------------------------------------------------- #
def backup_code(targets=None, note=""):
    """L2 rollback: snapshot live modules to ``*_backup.py`` + ``backups/code/<TS>/``.

    See ``code_rollback.py`` and ``operations/rollback_plan.md`` §4.3.
    """
    from code_rollback import backup_code as _backup_code
    return _backup_code(targets=targets, note=note)


def restore_code(targets=None, ts=None, verify=True):
    """L2 rollback: restore modules from ``*_backup.py`` (or a timestamped snapshot)."""
    from code_rollback import restore_code as _restore_code
    return _restore_code(targets=targets, ts=ts, verify=verify)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(f"Processing log: {sys.argv[1]}")
        print(process_feedback_log(sys.argv[1]))
    else:
        print("Feedback Processor Ready.")
