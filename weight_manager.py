from pathlib import Path
import yaml
import os
from datetime import datetime
from typing import Any, Dict, Tuple
from logger import log_event

# Configuration
DEFAULT_CONFIG_PATH = "OneDrive/Vault/Memory/Configs/paths.yaml"

def _resolve_default_config_path():
    """Resolve the default config path relative to user home directory."""
    return Path(os.path.expanduser("~")) / DEFAULT_CONFIG_PATH

def load_config() -> Tuple[Dict[str, Any], Path]:
    # Check for environment variable first (explicit test config)
    test_config = os.environ.get("MID_TEST_CONFIG")
    if test_config:
        test_path = Path(test_config).resolve()
        try:
            with open(test_path, 'r') as f:
                return yaml.safe_load(f), test_path.parent
        except Exception:
            pass
    
    # Check main config file first (production/default)
    try:
        default_path = _resolve_default_config_path()
        with open(default_path, 'r') as f:
            return yaml.safe_load(f), default_path.parent
    except FileNotFoundError:
        pass
    except Exception as e:
        log_event("ConfigLoader", "config_load_error", "none", "Failed to load config", str(e))
        # Fall through to fallback
    
    # Check for test configuration in the local directory (fallback for test runs)
    import glob
    current_dir = Path(__file__).parent
    test_patterns = glob.glob(str(current_dir / "tests" / "*" / "configs" / "paths.yaml"))
    if test_patterns:
        try:
            with open(test_patterns[0], 'r') as f:
                return yaml.safe_load(f), Path(test_patterns[0]).parent
        except Exception:
            pass
    
    # Fallback for local development or missing config
    return {
        "base_path": "OneDrive/Vault",
        "configs_path": "Memory/Configs",
        "log_path": "Memory/Feedback/logs"
    }, Path.cwd()

config, config_dir = load_config()

# Path normalization
raw_base = config.get("base_path", "OneDrive/Vault")
if raw_base.startswith("/c/"):
    base_path_str = raw_base.replace("/c/", "C:/")
elif raw_base.startswith("/") or raw_base.startswith("C:"):
    base_path_str = str(Path(raw_base).resolve())
elif "OneDrive" in raw_base:
    base_path_str = str((Path(os.path.expanduser("~")).resolve() / raw_base).resolve())
else:
    base_path_str = str((config_dir / raw_base).resolve())

BASE_PATH = base_path_str
CONFIG_DIR = os.path.normpath(os.path.join(BASE_PATH, config.get("configs_path", "Memory/Configs")))
WEIGHTS_FILE = os.path.join(CONFIG_DIR, "source_weights.yaml")
RULES_FILE = os.path.join(CONFIG_DIR, "feedback_rules.yaml")

def _normalize_sources(weights):
    """Enforce the dict schema for ``sources`` (Scenario 4 / S4 TODO).

    A list-form ``sources`` is converted to a dict keyed by ``id`` so the rest
    of the module (which is dict-oriented) can operate on it. The conversion is
    logged; ``save_weights()`` persists the normalized form.
    """
    if not isinstance(weights, dict):
        return {"sources": {}}
    sources = weights.get("sources")
    if isinstance(sources, list):
        log_event("WeightManager", "sources_list_detected", "none",
                  "Converting sources list -> dict keyed by id",
                  f"count={len(sources)}")
        converted = {}
        for s in sources:
            if isinstance(s, dict) and s.get("id") is not None:
                converted[s["id"]] = s
        weights["sources"] = converted
    elif sources is None:
        weights["sources"] = {}
    return weights


def load_weights():
    try:
        if not os.path.exists(WEIGHTS_FILE):
            log_event("WeightManager", "weights_file_missing", "none", "Weights file not found, initializing empty", WEIGHTS_FILE)
            return {"sources": {}}
        with open(WEIGHTS_FILE, 'r') as f:
            w = yaml.safe_load(f)
            w = _normalize_sources(w)
            print(f"DEBUG: load_weights() returned: {w}")
            return w
    except Exception as e:
        log_event("WeightManager", "load_weights_error", "none", "Attempting to load weights", str(e))
        return {"sources": {}}

def load_rules():
    try:
        with open(RULES_FILE, 'r') as f:
            return yaml.safe_load(f)
    except Exception as e:
        log_event("WeightManager", "load_rules_error", "none", "Attempting to load rules", str(e))
        return {}

def save_weights(weights):
    try:
        with open(WEIGHTS_FILE, 'w') as f:
            yaml.dump(weights, f, default_flow_style=False)
    except Exception as e:
        log_event("WeightManager", "save_weights_error", "none", "Attempting to save weights", str(e))

def update_health_metrics(source_id, success, failure_count=1):
    weights = load_weights()
    sources = weights.get('sources', [])
    source = None
    
    if isinstance(sources, dict):
        source = sources.get(source_id)
    elif isinstance(sources, list):
        source = next((s for s in sources if s.get('id') == source_id), None)
    
    if source:
        # Ensure metrics dict exists for this source
        if 'health_metrics' not in source:
            source['health_metrics'] = {'last_success': '2026-01-01', 'consecutive_failures': 0}
        
        # Trace for debugging
        old_metrics = source['health_metrics'].copy()
        
        try:
            if success:
                source['health_metrics']['last_success'] = datetime.now().isoformat()
                source['health_metrics']['consecutive_failures'] = 0
                if source.get('base_weight') == float('nan') or (source.get('base_weight') != source.get('base_weight')):
                    source['base_weight'] = 1.0
            else:
                source['health_metrics']['consecutive_failures'] = source['health_metrics'].get('consecutive_failures', 0) + failure_count
            
            # Force a reload to ensure we are saving what we think we are saving
            current_weights = load_weights()
            if isinstance(current_weights.get('sources'), dict):
                current_weights['sources'][source_id] = source
            elif isinstance(current_weights.get('sources'), list):
                for idx, s in enumerate(current_weights['sources']):
                    if s.get('id') == source_id:
                        current_weights['sources'][idx] = source
                        break
            
            save_weights(current_weights)
            log_event("WeightManager", "update_health_metrics", source_id, 
                       f"Success: {success}", 
                       f"Source: {source_id}, Old: {old_metrics}, New: {source['health_metrics']}")
            return {"status": "success", "source_id": source_id, "metrics": source['health_metrics']}
        except Exception as e:
            log_event("WeightManager", "update_metrics_error", source_id, "Failed to update metrics", str(e))
            return {"status": "error", "message": str(e)}
    return {"status": "error", "message": "Source ID not found"}

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
    print("Loaded weights:", load_weights())
