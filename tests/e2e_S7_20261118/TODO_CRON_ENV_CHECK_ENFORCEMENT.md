# Scenario S7 (cron 実行失敗 / 滞留) — 再発防止ノート

- 対象作業ドリル: EB-12 → EB-16 (S7: cron 実行失敗 / 滞留)
- 日付: 2026-11-18
- 作業ディレクトリ: `tests/e2e_S7_20261118/`

## 実施内容 (EB-12 .. EB-16)

1. **EB-12 (Inject - インタプリタ偽装 / 依存欠落):**
   - 壊れた `mid_daily_run.py` を hermes scripts 配下に配置し、`import missing_module_for_s7_drill`（存在しないモジュール）で強制失敗させた。
   - 壊れたジョブの `hermes cron` は `interpreter` を誤指定（yaml を持たない hermes venv Python を指す形）とし、依存モジュール `yaml` も欠落していた。
2. **EB-13 (Detect - cron 状態確認):**
   - `hermes cron runs mid-morning-digest` を確認 → `Last run: error`、`FATAL: No module named 'missing_module_for_s7_drill'` を検知。
   - 直後の `hermes cron list` / `hermes cron runs` でも失敗状態を確認。
3. **EB-14 (Respond - 手動実行確認):**
   - 失敗理由（インタプリタ不在 / 依存欠落）を特定。
   - `py -3.10 --version` と `import yaml` を検証（Python310 系に `yaml` があることを確認）。
   - `hermes cron run mid-morning-digest` で即時再実行（手動実行）で経過確認。
4. **EB-15 (Recover - RW-01 回帰):**
   - 壊れたジョブと誤インタプリタを撤去し、実行可能な `mid_daily_run.py` を hermes scripts 配下に設置。
   - 再登録の `hermes cron create` は絶対パスで `--workdir` / `--interpreter` を指定。
   - `hermes cron list` / `hermes cron runs` で最終 `ok` を確認。
   - S7 隔離ディレクトリで RW-01 回帰（TC-WF-01/02/03）を実行し、全系通過。
5. **EB-16 (Prevent - env check ノート):**
   - 下記の「環境チェック」をランナースクリプト先頭に必須化。

## 再発防止（EB-16）

`tests/e2e_S7_20261118/mid_daily_run.py` では、スクリプト先頭で次を必須チェックする:

- **インタプリタ:** 実行環境の Python バージョンが 3.8 以上であること（`sys.version_info >= (3, 8)`）。
- **依存:** `yaml` モジュールが import できていること。
- **CWD:** `$HOME` へ `os.chdir()` ガードし、相対パス解決に依存しない。
- **権限 / ディスク:** 書き込み先ディレクトリの存在・書き込み権限を事前確認。

失敗時は **即座に非ゼロ終了（`sys.exit(1)` / `raise SystemExit(1)`）** し、cron で `error` 状態として記録されるようにする（静かに成功扱いにしない）。

### 環境チェック コード例（要実装）

```python
import os
import sys

def _env_ok():
    if sys.version_info < (3, 8):
        print("FATAL: Python >= 3.8 required", file=sys.stderr)
        return False
    try:
        import yaml  # noqa: F401
    except ImportError:
        print("FATAL: yaml module is missing", file=sys.stderr)
        return False
    home = os.path.expanduser("~")
    os.chdir(home)  # CWD 依存を断つ
    if not os.access(home, os.W):
        print("FATAL: home dir is not writable", file=sys.stderr)
        return False
    return True

if not _env_ok():
    sys.exit(1)
```

## 検証

- S7 隔離ディレクトリ (`tests/e2e_S7_20261118/`) に `configs/`（`paths.yaml`, `source_weights.yaml`, `feedback_rules.yaml`, `source_weights.yaml.baseline`）および `logs/` を保持。
- 稼働中の `mid-morning-digest` ジョブは `Python310/python.exe` を使用し、`Last run: ok` を確認済み（2026-11-18T17:36:21 +09:00）。
