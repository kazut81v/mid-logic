---
type: deployment-runbook
status: active
date: 2026-11-16
updated: 2026-11-20
author: longcat-2.5:free
tags: [mid, operations, deployment, runbook]
related: "[[Memory/Projects/mid_phase5_logging_design]], [[Memory/Projects/mid_logic/operations/monitoring_design]]"
---

# MID デプロイ手順書（deployment_procedures）

## 1. 目的と適用範囲

本文書は、MID（Morning Intelligence Digest）プロジェクトの稼働環境への導入〜本番稼働までの手順を定める。対象は Phase 5（Operational Readiness）以降の運用開始時、およびその後全ての再デプロイとする。

対象コンポーネント：

| コンポーネント | 配置先 | 役割 |
|---|---|---|
| `weight_manager.py` | `Memory/Projects/mid_logic/` | ソース重み（`source_weights.yaml`）の読み書き・健全性メトリクス更新 |
| `feedback_processor.py` | `Memory/Projects/mid_logic/` | JSONL フィードバックログの解析と重みへの反映 |
| `logger.py` | `Memory/Projects/mid_logic/` | 構造化 JSONL ログ出力（`Memory/Feedback/logs/`） |
| 設定群 | `Memory/Configs/` | `paths.yaml` / `source_weights.yaml` / `feedback_rules.yaml` |

不在要件は fault_response_flow、退回し手順は rollback_plan、定期試験は e2e_test_plan を参照すること（別ドキュメント化予定）。

## 2. 前提条件

### 2.1 実行インタプリタ（重要）

2026-11-16 時点の実測に基づく必須環境：

- **使用するインタプリタ**: `py -3.10`（Python 3.10.6、PyYAML 6.0.3 導入済み）
- **避けるべきもの**: 既定の `python`（3.14.9）には PyYAML が無く、インポート時に `ModuleNotFoundError` となる。全コマンドで `py -3.10` を使用すること。

```bash
py -3.10 --version                                  # Python 3.10.6
py -3.10 -c "import yaml; print(yaml.__version__)"   # 6.0.3
```

新規マシンへ移設する場合は、Python 3.10 系を用意のうえ `py -3.10 -m pip install pyyaml` で同等環境を構築する。

### 2.2 Vault / OneDrive

- Vault ルート: `C:\Users\kazut.DESKTOP-28CC918\OneDrive\Vault`
- OneDrive の「オンandemand」設定の場合、Vault ルートを「常にこのデバイスに保持する」に設定しておくこと（未設定だとファイル缺落＝Scenario 3 障害と区別が付かない）。
- 複数端末での同時編集は禁止する（同期競合により YAML が破損する）。
- **バージョン管理**: Vault は git 管理下にない（2026-11-16 実測）。変更履歴は Phase 0 のスナップショットバックアップで代用する。Obsidian Git 等の導入は任意。

### 2.3 作業ディレクトリ（CWD）規約

`mid_logic/*.py` は `paths.yaml` を**相対パス**（`OneDrive/Vault/Memory/Configs/paths.yaml`）で解決するため、**カレントディレクトリがユーザー Home（`C:\Users\kazut.DESKTOP-28CC918`）のときのみ正しく動作する**。Home 以外から実行すると設定読込が静かに失敗し、空の重みセットが返る（実測で確認済み）。

- 手动実行: 必ず `cd "$HOME"` してから実行。
- cron 登録: `--workdir "$HOME"` を指定する（後述）。

### 2.4 外部連携

- Gmail 送信は **未実装**。E2E 検証ではシミュレーション（擬似信箱への出力）までを対象とする。
- ニュース取得系の実装状況に応じて、Phase 6 で実 API 連携を追加する。

## 3. デプロイ手順

### Phase 0: 事前バックアップ

```bash
cd "$HOME/OneDrive/Vault/Memory"
TS=$(date +%Y%m%d_%H%M%S)
BK="Projects/mid_logic/backups/$TS"
mkdir -p "$BK/configs"
cp Configs/paths.yaml Configs/source_weights.yaml Configs/feedback_rules.yaml "$BK/configs/"
cp Projects/mid_logic/weight_manager.py Projects/mid_logic/feedback_processor.py \
   Projects/mid_logic/logger.py "$BK/"
sha256sum "$BK"/configs/* "$BK"/*.py > "$BK/MANIFEST.sha256"
ls -la "$BK" "$BK/configs"
```

> 注意: 既存の `*_backup.py` は**旧世代の参照版**であり、パス体系（`Memory/Configs` 直接指定）もスキーマ前提（dict）も現行と異なる。现行環境への巻き戻しには使わないこと（rollback_plan §2.2）。

### Phase 1: 環境検証（Pre-flight）

```bash
py -3.10 --version
py -3.10 -c "import yaml; print(yaml.__version__)"
test -d "$HOME/OneDrive/Vault/Memory/Configs" && echo "vault OK"
```

すべて成功すること。失敗時はここで停止し、環境構築に戻る。

### Phase 2: 設定ファイルの検証

```bash
cd "$HOME"
py -3.10 - <<'EOF'
import math, yaml
base = "OneDrive/Vault/Memory/Configs"
cfg = yaml.safe_load(open(f"{base}/paths.yaml", encoding="utf-8"))
assert cfg["base_path"] == "OneDrive/Vault", "base_path mismatch"
w = yaml.safe_load(open(f"{base}/source_weights.yaml", encoding="utf-8"))
r = yaml.safe_load(open(f"{base}/feedback_rules.yaml", encoding="utf-8"))

# 1) sources の型（既知の不整合チェック）
src = w.get("sources")
if isinstance(src, list):
    print("WARN: sources が list 形式。weight_manager/feedback_processor は dict 前提のため更新が無効化される（fault_response_flow Scenario 4）")
elif isinstance(src, dict):
    print("OK: sources は dict 形式")

# 2) 重み・ルールの有限性
for s in (src.values() if isinstance(src, dict) else src):
    bw = s.get("base_weight")
    assert isinstance(bw, (int, float)) and math.isfinite(bw), f"invalid base_weight: {s}"
for ft, rule in r.get("feedback_rules", {}).items():
    d = rule.get("source_weight_delta")
    assert isinstance(d, (int, float)) and math.isfinite(d), f"invalid delta: {ft}"
assert r["weight_min"] < r["weight_max"], "clip range invalid"
print("config validation passed")
EOF
```

**Gate**: 上記 WARN（sources が list）が出た場合、本番投入前に是正を完了させること（§6 R2）。

> **2026-11-20**: 同チェックは `validate_configs.py`（プロジェクト直下）として自動化済み。
> CI / デプロイ前 gate では次を実行する:
> ```bash
> cd "$HOME"
> py -3.10 OneDrive/Vault/Memory/Projects/mid_logic/validate_configs.py
> ```

### Phase 3: コード配置の確認

今回は新規配置ではなく既存モジュールの継続利用だが、変更を加えた場合の確認手順：

1. 編集後ファイルを Phase 0 と同じ要領でスナップショット。
2. `py -3.10 -m py_compile <各 .py>` で構文検証。
3. Vault は git 管理下にないため、差分はスナップショットの `MANIFEST.sha256` で追跡する。

### Phase 4: スモークテスト

```bash
cd "$HOME"
py -3.10 OneDrive/Vault/Memory/Projects/mid_logic/weight_manager.py     # 重みが表示されること
py -3.10 OneDrive/Vault/Memory/Projects/mid_logic/test_logger.py        # "Log entry successful." + ログファイル一覧
py -3.10 -c "
import sys; sys.path.insert(0, 'OneDrive/Vault/Memory/Projects/mid_logic')
from feedback_processor import process_feedback_log, load_weights
print(process_feedback_log('OneDrive/Vault/Memory/Feedback/test_feedback_tc05.jsonl'))
print('gov base_weight:', load_weights()['sources'][0]['base_weight'])
"
```

期待される現在の出力（**既知の不整合のため重みは変わらない**）：

```
Feedback processed successfully.
gov base_weight: 1.0
```

`update_health_metrics('gov_official', True)` が `{'status': 'error', ...}` を返す場合は Scenario 4 の不整合が残存しており、**本番 Gate 未達**。是正后再试验すること。

### Phase 5: スケジュール登録（Hermes cron）

ランナースクリプトは **profile の scripts 配下**を基准点とする。この環境では次パス：

```
C:\Users\kazut.DESKTOP-28CC918\AppData\Local\hermes\profiles\respawn\scripts\
```

参考: 既存ジョブ `obsidian-memory-daily-report`（`0 9 * * *` / script モード / `--deliver local`）が同基淮で動作済み。MID ランナー（`mid_daily_run.py`）を同上記ディレクトリに配置し、以下で登録する。

```bash
hermes cron create "0 9 * * *" \
  --name mid-morning-digest \
  --workdir "$HOME" \
  --script mid_daily_run.py \
  --deliver local \
  --failure-deliver local \
  --timezone "Asia/Tokyo" \
  --catch-up off \
  --grace-minutes 30
```

- `--workdir "$HOME"`: §2.3 の CWD 規約を満たすため必須。
- `--catch-up off`：マシン休止中の滞留実行を増殖させない。
- `--failure-deliver local`：失敗通知を抑制しつつ `hermes cron list` で状態は追える。运用慣らし後、`telegram` 等へ昇格する。
- エージェントモード（LLM パイプライン本体）で動かす場合は script モードに代えてプロンプトを渡す運用とする。
- 登録後：

```bash
hermes cron list
hermes cron status
hermes cron doctor
```

### Phase 6: 初回本番実行と受け入れ

1. `hermes cron run mid-morning-digest` で即時 1 回実行（可能なら時間を待たずに確認）。
2. 当日ログ `Memory/Feedback/logs/log_YYYYMMDD.jsonl` に以下が記録されることを確認：
   - `engine_id: WeightManager` の重み更新（`update_health_metrics`）、`engine_id: FeedbackProcessor` の処理成功（`process_feedback_log_success`）。
   - 同一 `correlation_id` で Engine-1 → Engine-2 → Engine-3 が連鎖（engines 実装後に有効。現時点では `none`/source_id のみ）。
3. エラーイベント（`load_*_error` / `save_*_error`）が 0 件であること。
4. `hermes cron runs mid-morning-digest` で実行履歴 status=ok。

## 4. デプロイ後の受け入れチェックリスト

- [ ] Phase 1〜4 の全コマンドが期待どおり終了した
- [ ] `sources` が dict 形式である（Scenario 4 是正済み）
- [ ] 初回本番ログに error 系 action_type が無い
- [ ] 当日分ログが Vault 内 `Memory/Feedback/logs/` に生成されている
- [ ] cron が pause 状態でなく `next_run_at` が翌朝である
- [ ] バックアップ `backups/<TS>/MANIFEST.sha256` が残っている

## 5. 設定変更管理

- `source_weights.yaml` / `feedback_rules.yaml` の編集は、変更前に必ず Phase 0 と同じ快照を取り、frontmatter の `updated` と変更履歴を更新する。
- 重みの一括変更は手作業で行わず、`feedback_processor` 経由の反映を原則とする。
- どうしても直接編集する場合、PyYAML 有効値（`0.1`〜`1.5`、有限値）のみ許可する（fault_response_flow Scenario 1）。

## 6. 既知の制約・リスク

| # | 内容 | 深刻度 | 対処 |
|---|---|---|---|
| R1 | CWD 依存パス。`$HOME` 以外から実行すると設定読込が静かに失敗する | High | `--workdir "$HOME"`／`cd "$HOME"` を徹底 |
| R2 | `sources` の list/dict 不整合で重み更新が無効化（実測確認済み） | Critical | 本番前に dict 化＋validator 導入 |
| R3 | `logger.py` に level フィールドが無く、重大度は `action_type` の語彙で表現する | Medium | 監視設計側でマッピング（[[monitoring_design]] §2.2） |
| R4 | Gmail 連携未実装。E2E はシミュレーション止まり | Medium | Phase 6 で実装予定 |
| R5 | Vault が git 管理下にないため変更履歴がスナップショット依存 | Medium | 四半期毎にバックアップの棚卸し |

## 7. 付録A: コマンド早見表

| 目的 | コマンド |
|---|---|
| 環境確認 | `py -3.10 -c "import yaml; print(yaml.__version__)"` |
| 重み読込確認 | `cd "$HOME" && py -3.10 OneDrive/Vault/Memory/Projects/mid_logic/weight_manager.py` |
| ログ作成確認 | `cd "$HOME" && py -3.10 OneDrive/Vault/Memory/Projects/mid_logic/test_logger.py` |
| cron 登録 | `hermes cron create "0 9 * * *" --name mid-morning-digest --workdir "$HOME" --script mid_daily_run.py` |
| cron 一時停止 | `hermes cron pause mid-morning-digest` |
| 即時実行 | `hermes cron run mid-morning-digest` |
| 実績確認 | `hermes cron runs mid-morning-digest` |

---
*Phase 5 運用開始時ドキュメント / 見直し時は updated と変更履歴を更新すること。*
