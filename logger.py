import json
import os
import yaml
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Tuple

# Configuration - should ideally be loaded from paths.yaml
# For this implementation, we'll assume the base_path logic.
# However, since we want to be robust, we'll check for the paths.yaml existence.

DEFAULT_CONFIG_PATH = "OneDrive/Vault/Memory/Configs/paths.yaml"

def _resolve_default_config_path():
    """Resolve the default config path relative to user home directory."""
    return Path(os.path.expanduser("~")) / DEFAULT_CONFIG_PATH

def get_config() -> Tuple[Dict[str, Any], Path]:
    # 1. 環境変数の優先 (E2E テストモード)
    test_config = os.environ.get("MID_TEST_CONFIG")
    if test_config:
        test_path = Path(test_config).resolve()
        try:
            with open(test_path, 'r') as f:
                config = yaml.safe_load(f)
            # Validate required keys
            if all(k in config for k in ["base_path", "configs_path", "log_path"]):
                return config, test_path.parent
        except Exception:
            pass

    # 2. 本番用・デフォルト (production config FIRST)
    try:
        default_path = _resolve_default_config_path()
        with open(default_path, 'r') as f:
            config = yaml.safe_load(f)
        # Validate required keys for isolated tree compatibility
        if all(k in config for k in ["base_path", "configs_path", "log_path"]):
            return config, default_path.parent
    except FileNotFoundError:
        pass
    except Exception as e:
        # Log error but continue to fallback
        pass

    # 3. テスト設定のフォールバック (test configs as fallback)
    import glob
    potential_configs = glob.glob("tests/*/configs/paths.yaml")
    if potential_configs:
        try:
            config_path = potential_configs[0]
            with open(config_path, 'r') as f:
                return yaml.safe_load(f), Path(config_path).parent
        except Exception:
            pass

    # 4. ハードコードされたフォールバック
    return {
        "base_path": "OneDrive/Vault",
        "configs_path": "Memory/Configs",
        "log_path": "Memory/Feedback/logs"
    }, Path.cwd()

def _find_vault_root(start: Path) -> Path:
    """Walk up from start to find the 'Vault' directory (OneDrive/Vault)."""
    for p in [start] + list(start.parents):
        if p.name == "Vault" and p.parent.name == "OneDrive":
            return p
    return start

def _resolve_base_path(base: str, config_dir: Path) -> Path:
    """Resolve base path handling Unix-style /c/Users/... paths on Windows."""
    base_path = Path(base)
    if base_path.is_absolute():
        return base_path.resolve()
    # Handle Unix-style absolute paths like /c/Users/... on Windows
    if base.startswith("/") and len(base) > 2 and base[2] == "/":
        drive_letter = base[1].upper()
        return Path(f"{drive_letter}:{base[2:]}").resolve()
    # Relative path - find vault root
    vault_root = _find_vault_root(config_dir)
    if base.startswith("OneDrive/Vault"):
        return (vault_root / base.replace("OneDrive/Vault", "").lstrip("/")).resolve()
    return (vault_root / base).resolve()

def get_log_path() -> str:
    config, config_dir = get_config()
    base = config.get("base_path", "")
    log_rel = config.get("log_path", "")

    base_path = _resolve_base_path(base, config_dir)
    log_path = base_path / log_rel
    log_path.mkdir(parents=True, exist_ok=True)
    return str(log_path)

def log_event(engine_id: str, action_type: str, correlation_id: str, 
               input_summary: str, output_summary: str, metadata: Dict[str, Any] = None):
    """
    Logs a structured event for the MID project.
    """
    log_file = f"log_{datetime.now().strftime('%Y%m%d')}.jsonl"
    full_path = os.path.join(get_log_path(), log_file)

    entry = {
        "timestamp": datetime.now().isoformat(),
        "engine_id": engine_id,
        "action_type": action_type,
        "correlation_id": correlation_id,
        "input_summary": input_summary,
        "output_summary": output_summary,
        "metadata": metadata or {}
    }
    
    with open(full_path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

# Example usage:
# log_event("Engine-1", "search_discovery", "req-123", "Query: AI Law", "Found 5 sources", {"reliability_scores": {"gov": 1.0, "news": 0.8}})