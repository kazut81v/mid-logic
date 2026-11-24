---
type: e2e-test-plan
status: active
date: 2026-11-16
updated: 2026-11-20
author: longcat-2.5:free
tags: [mid, operations, e2e-testing, phase5]
related: "[[Memory/Projects/mid_logic/operations/fault_response_flow.md]], [[Memory/Projects/mid_logic/operations/monitoring_design.md]], [[Memory/Projects/mid_logic/operations/rollback_plan.md]], [[Memory/Projects/mid_logic/operations/deployment_procedures.md]]"
---

# MID E2E Test Plan (Phase 5 Operational Readiness)

## 1. 目的と適用範囲

MID（Morning Intelligence Digest）の **Phase 5 運用開始前** および **定期回帰試験** におけるエンドツーエンド検証を定義する。対象は以下の 3 系統のデータフローと、既知障害シナリオ（Scenario 1–8）の再現・検知・復旧の確認である。

- **Weight 更新系統**: `WeightManager.update_health_metrics` → `source_weights.yaml` → ログ
- **Feedback 反映系統**: `FeedbackProcessor.process_feedback_log` → 重み delta → `source_weights.yaml` → ログ
- **ログ基盤系統**: `logger.log_event` → JSONL 出力 → 監視集計

成功基準: **全データフローがリグレッションなしで完了し、監視不変条件（monitoring_design §2.4）を満たすこと。**

---

## 2. テスト環境セットアップ（依存モック）

### 2.1 物理・論理環境

| 項目 | 本番相当値 | テスト用値 / モック |
|---|---|---|
| OS / Shell | Windows 10 / git-bash | 同一（ローカル実行） |
| Python インタプリタ | `py -3.10` | `py -3.10`（実在確認） |
| 作業ディレクトリ | `$HOME` | `$HOME`（`os.chdir` 強制） |
| Vault ルート | `OneDrive/Vault` | `OneDrive/Vault`（実在） |
| 設定ディレクトリ | `Memory/Configs` | **専用テスト隔離コピー** |
| ログディレクトリ | `Memory/Feedback/logs` | **専用テスト隔離コピー** |
| OneDrive 状態 | 常時同期 | **「常にこのデバイスに保持する」を ON** |

### 2.2 隔離テストフィクスチャの準備（各試験前に実行）

```bash
cd "$HOME"

# 1. バックアップ用タイムスタンプ
TS=$(date +%Y%m%d_%H%M%S)
TEST_ROOT="OneDrive/Vault/Memory/Projects/mid_logic/tests/e2e_${TS}"
mkdir -p "${TEST_ROOT}/configs" "${TEST_ROOT}/logs"

# 2. 本番設定のスナップショットをテスト用にコピー（差し替え可能にする）
cp "OneDrive/Vault/Memory/Configs/paths.yaml" "${TEST_ROOT}/configs/"
cp "OneDrive/Vault/Memory/Configs/source_weights.yaml" "${TEST_ROOT}/configs/"
cp "OneDrive/Vault/Memory/Configs/feedback_rules.yaml" "${TEST_ROOT}/configs/"

# 3. テスト用 paths.yaml を生成（テスト隔離パスを指すように書き換え）
cat > "${TEST_ROOT}/configs/paths.yaml" <<EOF
base_path: "${HOME}/${TEST_ROOT}"
configs_path: "configs"
log_path: "logs"
EOF

# 4. 環境変数でテストモードを通知（コード側で検知可能にする）
export MID_TEST_MODE=1
export MID_TEST_CONFIG="${HOME}/${TEST_ROOT}/configs/paths.yaml"
```

> **注意**: 本番 `source_weights.yaml` と `feedback_rules.yaml` は **読み取り専用** として扱い、テスト内部ではテスト隔離コピーのみを書き換える。試験終了後に `MID_TEST_MODE` を unset し、元のパス構成へ戻すこと。

### 2.3 モック対象外（実実行）コンポーネント

- `yaml` / `json` / `datetime` / `os` / `pathlib`：標準ライブラリ・実ファイル I/O を使用
- `logger.py`：実装のまま使用（ログ出力先がテスト隔離ディレクトリになるのみ）
- `weight_manager.py` / `feedback_processor.py`：実装のまま使用（`paths.yaml` 経由でテスト隔離パスを参照）

### 2.4 モック・スタブが必要な外部依存（現状なし・将来拡張用）

| 依存 | 現状 | モック戦略（将来） |
|---|---|---|
| Engine-1/2/3 | 未実装 | `unittest.mock.patch` で `search_discovery` 等をスタブ化 |
| 外部 API（検索・LLM） | 未使用 | `responses` / `httpx_mock` で HTTP をインターセプト |
| Telegram 通知 | 未実装 | `hermes cron --failure-deliver` のローカル配信で代替 |

---

## 3. コアワークフロー試験

### 3.1 TC-WF-01: Weight 更新フロー（健全性駆動）

| ステップ | アクション | 期待結果 | 検証コマンド |
|---|---|---|---|
| 1 | テスト用 `source_weights.yaml` に `gov_official`（`base_weight: 1.0`, `consecutive_failures: 0`）を用意 | ファイル存在・dict 形式 | `py -3.10 -c "import yaml; print(yaml.safe_load(open('${TEST_ROOT}/configs/source_weights.yaml'))['sources'].keys())"` |
| 2 | `WeightManager.update_health_metrics('gov_official', True)` 実行 | `last_success` 更新、`consecutive_failures=0`、`save_weights` 呼出 | ログに `update_health_metrics` + `Decision` |
| 3 | 同 source で `False` を 2 回実行 | `consecutive_failures=2`、`last_success` 変わらず | 重みファイル直接確認 |
| 4 | `failure_threshold`（gov=3）到達直前で `True` 実行 | `consecutive_failures=0` にリセット | 重みファイル直接確認 |
| 5 | ログ突合：`update_health_metrics` 件数 == 成功件数 | 不整合なし | `monitoring_design §3.2` 集計スクリプト |

**合格基準**: 重みファイルの `health_metrics` が操作通りに更新され、ログに `update_health_metrics`（Decision）が正しく記録され、エラー系 action_type が 0 件。

---

### 3.2 TC-WF-02: Feedback 反映フロー（フィードバック駆動）

| ステップ | アクション | 期待結果 | 検証コマンド |
|---|---|---|---|
| 1 | テスト用 `feedback_rules.yaml` に `inappropriate: {source_weight_delta: -0.10}`, `weight_min: 0.1, weight_max: 1.5` を用意 | ルール読込成功 | `py -3.10 -c "import yaml; print(yaml.safe_load(open('${TEST_ROOT}/configs/feedback_rules.yaml')))"` |
| 2 | テスト用 JSONL ログを作成（`source_id: gov_official, feedback_type: inappropriate, impact_score: 1` × 3 行） | 3 行の有効 JSONL | `wc -l <test_feedback.jsonl` |
| 3 | `FeedbackProcessor.process_feedback_log(test_feedback.jsonl)` 実行 | 3 回 `weight_updated` 発火、最終 `base_weight = max(0.1, 1.0 - 0.30) = 0.7` | ログ `weight_updated` 件数 = 3、`New weight: 0.7` |
| 4 | 同一 `correlation_id` で `weight_updated` が重複していないか確認 | 重複なし（Scenario 2 対策） | `monitoring_design §4.2` 集計スクリプト |
| 5 | `save_weights_error` が 0 件 | 部分書込みなし | grep |

**合格基準**: delta 適用がルール通り、`weight_min/max` でクリップ、ログ不変条件（§2.4 の 1–3）を全満足。

---

### 3.3 TC-WF-03: ログ基盤整合性フロー

| ステップ | アクション | 期待結果 | 検証コマンド |
|---|---|---|---|
| 1 | `logger.log_event` を複数 engine_id で 10 件発行 | `log_YYYYMMDD.jsonl` に 10 行追記 | `wc -l < "${TEST_ROOT}/logs/log_$(date +%Y%m%d).jsonl"` |
| 2 | 全行が `json.loads` 成功 | パースエラー 0 | `py -3.10 -c "import json; [json.loads(l) for l in open('${TEST_ROOT}/logs/log_$(date +%Y%m%d).jsonl')]"` |
| 3 | `correlation_id` が `"none"` 以外の行で Engine-1→2→3 の結線が取れる（将来） | 現状は `"none"` のみ→除外確認 | `grep -c '"correlation_id": "none"'` |
| 4 | ログファイルが `Memory/Feedback/logs/` 以外に生成されていない | 散乱なし（Scenario 3 対策） | `find "$HOME" -name "log_*.jsonl" -not -path "*/Feedback/logs/*"` |

**合格基準**: JSONL 形式完全準拠、日次ローテーション正常、ファイル散乱なし、書込失敗 0 件。

---

## 4. エッジケース試験（Scenario 1–8 再現・検知・復旧）

各 Scenario は **「障害注入 → 検知確認 → 初動対応実行 → 復旧確認 → 再発防止確認」** の 5 フェーズで試験する。

### 共通試験手順テンプレート

```bash
# Phase A: 障害注入
<障害固有の注入コマンド>

# Phase B: 検知確認（monitoring_design の集計スクリプト実行）
py -3.10 <monitoring_design §3.2 または §4.2 のスクリプト>
# → 期待するアラート条件（P1/P2/P3）が検知されること

# Phase C: 初動対応（fault_response_flow §4 の手順実行）
<Scenario 固有の初動手順>

# Phase D: 復旧確認
# → 正常フロー（TC-WF-01/02/03）を再実行し、全合格すること

# Phase E: 再発防止確認
# → 同一障害を再注入しても検知・阻止される、または自動復旧することを確認
```

---

### Scenario 1: 非有限値（NaN / Inf）の混入 —— **P1**

| フェーズ | 実施内容 |
|---|---|
| **注入** | `source_weights.yaml` の `gov_official.base_weight` を `NaN` または `Infinity` に手動書き換え（YAML: `.nan` / `.inf`） |
| **検知** | `monitoring_design §3.3` validator スクリプト実行 → `math.isfinite()` 失敗を検出、P1 アラート |
| **初動** | 1. `hermes cron pause mid-morning-digest` 2. バックアップから `source_weights.yaml` 復元 3. 全 source 有限性再確認 |
| **復旧** | TC-WF-01/02/03 全合格 |
| **再発防止** | `validate_configs.py`（Phase 6 実装予定）で delta 許容範囲を固定化し、CI で gate |

---

### Scenario 2: フィードバック二重適用による重み変動 —— **P2**

| フェーズ | 実施内容 |
|---|---|
| **注入** | `feedback_processor.py` の `save_weights(weights)` をループ内からループ外へ**移動せず**に、同一セッションで `process_feedback_log` を 2 回連続実行（意図的な二重適用） |
| **検知** | `weight_updated` 件数 > `process_feedback_log_success` 件数、`correlation_id` 同一で `weight_updated` 重複 |
| **初動** | 1. 直近 JSONL 確認・変動量特定 2. 余剰分を手動戻し（最後の手段） 3. 必要なら L1 |
| **復旧** | 重みを正常値に戻し、TC-WF-02 合格 |
| **再発防止** | Phase 6 で `save_weights()` をループ外へ移動するリファクタ完了を確認（コードレビュー） |

---

### Scenario 3: ログ出力先の散乱 / 書込失敗 —— **P1（30分継続）/ P2（単発）**

| フェーズ | 実施内容 |
|---|---|
| **注入** | 1. `logger.get_log_path()` が返すパスを一時的に `$TMPDIR` 等に変更（`paths.yaml` の `base_path` 書き換え） 2. OneDrive「オンデマンド」模擬：ログディレクトリを一時的に `mv` して欠落させる |
| **検知** | `find "$HOME" -name "log_*.jsonl" -not -path "*/Feedback/logs/*"` で散乱検出、または書込失敗ログ（`save_weights_error` 等） |
| **初動** | 1. OneDrive 設定を「常にこのデバイスに保持する」へ 2. 散乱ファイルを `logs/` へ移動 3. Vault 外ログは削除 |
| **復旧** | `paths.yaml` を正規パスに戻し、TC-WF-03 合格 |
| **再発防止** | cron に `--workdir "$HOME"` 必須化（deployment_procedures §2.3 R1）を CI で検証 |

---

### Scenario 4: `sources` の list/dict 不整合 —— **P2（Release Blocker）**

| フェーズ | 実施内容 |
|---|---|
| **注入** | `source_weights.yaml` の `sources` を list 形式（`- id: gov_official`）に書き換え |
| **検知** | `update_health_metrics('gov_official', True)` → `{'status': 'error', 'message': 'Source ID not found'}` 返却、`type(sources).__name__ == 'list'` |
| **初動** | 1. YAML を dict 形式に是正（`id` をキー化） 2. `update_health_metrics` で `success` 確認 3. 旧 list 版を `backups/failed_<TS>/` へ退避 |
| **復旧** | TC-WF-01 合格、`sources` 型が `dict` |
| **再発防止** | 設定編集を `feedback_processor` 経由に限定、直接編集には validator 必須化（Phase 6） |

---

### Scenario 5: CWD 依存パスによる静かな失敗 —— **P2**

| フェーズ | 実施内容 |
|---|---|
| **注入** | `cd /tmp` 等、$HOME 以外から `weight_manager.py` または cron ジョブを実行 |
| **検知** | `load_weights()` が空の `{"sources": {}}` を返す、スモークテストで `gov base_weight` が出ない、`config_load_error` または `weights_file_missing` ログ |
| **初動** | 1. `cd "$HOME"` して再実行 2. cron の `--workdir "$HOME"` 確認 3. 空重みで走った処理結果を破棄・再実行 |
| **復旧** | 正規 CWD で TC-WF-01 合格 |
| **再発防止** | `mid_daily_run.py` 先頭で `os.chdir(os.path.expanduser("~"))` 実施、またはパス解決を絶対パス化 |

---

### Scenario 6: フィードバック解析失敗の未検知 —— **P3（昇格余地）**

| フェーズ | 実施内容 |
|---|---|
| **注入** | JSONL に不正行（`{invalid json`）を混入、`process_feedback_log` 実行 |
| **検知** | `json_decode_error` ログ発生、処理行数と `process_feedback_log_success` 数の不整合（B2） |
| **初動** | 1. エラー行番号特定・修正 or 削除 2. 修正後 JSONL で再実行 3. 行数と成功数一致確認 |
| **復旧** | TC-WF-02 合格、DEAD_LETTER ファイル（`logs/dead_letter_<TS>.jsonl`）に失敗行が退避されること（Phase 6 実装後） |
| **再発防止** | DEAD_LETTER 出力導入（Phase 6）、解析失敗行を自動隔離 |

---

### Scenario 7: cron 実行失敗 / 滞留 —— **P2**

| フェーズ | 実施内容 |
|---|---|
| **注入** | 1. インタプリタ不在模擬：`py -3.10` を PATH から外す / 2. 依存欠落：`yaml` モジュールを一時的に `import` 不可にする / 3. タイムアウト：長時間 sleep するスクリプトを cron 登録 |
| **検知** | `hermes cron runs mid-morning-digest` で `error` 状態、`--failure-deliver` 通知 |
| **初動** | 1. 失敗理由確認 2. `py -3.10 --version` と `import yaml` 検証 3. `hermes cron run mid-morning-digest` で即時再実行 4. 継続なら L2（rollback_plan §4.3） |
| **復旧** | 環境修復後、手動実行で TC-WF-01/02/03 全合格 |
| **再発防止** | ランナースクリプト先頭で環境チェック（インタプリタ・依存・ディスク・権限）を実施、失敗時即 nonzero exit |

---

### Scenario 8: `feedback_rules.yaml` の clip range 破損 —— **P1**

| フェーズ | 実施内容 |
|---|---|
| **注入** | `feedback_rules.yaml` の `weight_min: 1.5, weight_max: 0.1`（min ≥ max）に書き換え |
| **検知** | validator の `assert r["weight_min"] < r["weight_max"]` 失敗、重みが一方的に境界値へ張り付き続ける |
| **初動** | L1：設定巻き戻し（rollback_plan §4.2）、直接編集禁止を Vault 変更履歴に記録 |
| **復旧** | 正常ルールで TC-WF-02 合格、clip 境界到達なし |
| **再発防止** | 設定直接編集禁止の徹底、validator で clip 範囲妥当性を CI gate 化 |

---

## 5. 回帰試験スイート（Regression Suite）

| ID | 試験名 | 実行頻度 | 所要時間 | 自動化 |
|---|---|---|---|---|
| RS-01 | 全コアワークフロー（TC-WF-01/02/03） | 毎回デプロイ前・週次 | 5 分 | ✅ スクリプト化済 |
| RS-02 | Scenario 4（list/dict 不整合）再現・是正 | 月 1 回（fault_response_flow §7） | 10 分 | ✅ |
| RS-03 | Scenario 3（ログ散乱）初動 | 四半期 1 回 | 15 分 | △ 手順書ベース |
| RS-04 | Scenario 1（非有限値）全工程 | 年 1 回 | 30 分 | △ 手順書ベース |
| RS-05 | 全 Scenario 1–8 連続注入・復旧 | リリース前・四半期 1 回 | 60 分 | △ 部分自動化 |

> **自動化方針**: RS-01 は CI パイプラインに組み込み、PR マージ必須 gate とする。RS-02/03/04 は `pytest` + `tmp_path` フィクスチャで自動化を Phase 6 で推進。

---

## 6. 検証基準（Verification Criteria）

### 6.1 データフロー完全性

| 基準 | 判定方法 | 閾値 |
|---|---|---|
| Weight 更新成功率 | `update_health_metrics` 成功 / 総試行 | ≧ 99% / 日 |
| Feedback 反映成功率 | `process_feedback_log_success` / 入力行数 | 100%（不整合 0） |
| ログパース成功率 | JSONL 全行 `json.loads` 成功 | 100%（破損行 0） |
| 重みイベント突合 | `weight_updated` vs `process_feedback_log_success` 不変条件 1–3 | 全日合格 |
| 非有限値検出 | validator で `math.isfinite()` 全 source パス | 0 件（即 P1） |

### 6.2 リグレッション不在基準

- **全既存テストケース（test_cases.yaml TC-01–05）が合格**し、実行時間が前回比 ±20% 以内
- **新規エラー系 action_type（`*_error`）が 0 件/日**
- **`consecutive_failures` が閾値の 80% を超える source が 0 件**
- **`last_success` が `refresh_interval_min` の 2 倍を超える source が 0 件**

### 6.3 運用ドキュメント整合性

- `fault_response_flow.md` の全 Scenario が本試験計画でカバーされている
- `monitoring_design.md` の集計スクリプトが試験実行時にエラーなく動作する
- `rollback_plan.md` の L0/L1/L2 手順が Scenario 試験で実演可能である
- `deployment_procedures.md` の R1（CWD 固定）が cron 実行で遵守されている

---

## 7. 試験実行手順（Runbook）

### 7.1 事前準備（各試験ラン共通）

```bash
cd "$HOME"

# 1. 環境クリーンアップ
unset MID_TEST_MODE
unset MID_TEST_CONFIG

# 2. テスト隔離環境構築（§2.2 実行）
TS=$(date +%Y%m%d_%H%M%S)
TEST_ROOT="OneDrive/Vault/Memory/Projects/mid_logic/tests/e2e_${TS}"
# ... （§2.2 のスクリプト実行）

# 3. ベースライン取得（試験前の正常状態スナップショット）
cp "${TEST_ROOT}/configs/source_weights.yaml" "${TEST_ROOT}/configs/source_weights.yaml.baseline"
py -3.10 -c "
import yaml, json, datetime
w = yaml.safe_load(open('${TEST_ROOT}/configs/source_weights.yaml'))
print('BASELINE:', json.dumps({k: v.get('base_weight') for k,v in w.get('sources',{}).items()}))
"
```

### 7.2 コアワークフロー実行

```bash
# TC-WF-01
py -3.10 -c "
from weight_manager import update_health_metrics
print(update_health_metrics('gov_official', True))
print(update_health_metrics('gov_official', False))
print(update_health_metrics('gov_official', False))
print(update_health_metrics('gov_official', True))
"

# TC-WF-02
cat > "${TEST_ROOT}/test_feedback.jsonl" <<'EOF'
{"source_id": "gov_official", "feedback_type": "inappropriate", "impact_score": 1}
{"source_id": "gov_official", "feedback_type": "inappropriate", "impact_score": 1}
{"source_id": "gov_official", "feedback_type": "inappropriate", "impact_score": 1}
EOF
py -3.10 -c "
from feedback_processor import process_feedback_log
print(process_feedback_log('${TEST_ROOT}/test_feedback.jsonl'))
"

# TC-WF-03
py -3.10 -c "
from logger import log_event
for i in range(10):
    log_event('TestEngine', 'test_action', f'req-{i}', f'input {i}', f'output {i}')
"
```

### 7.3 監視集計による検証

```bash
# monitoring_design §3.2 実行
cd "$HOME"
py -3.10 - <<'EOF'
import json, glob, datetime
p = f"${TEST_ROOT}/logs"
f = f"{p}/log_{datetime.date.today():%Y%m%d}.jsonl"
rows = [json.loads(l) for l in open(f, encoding="utf-8") if l.strip()]
err = [r for r in rows if "error" in r["action_type"]]
wm  = [r for r in rows if r["engine_id"] == "WeightManager"]
fb  = [r for r in rows if r["engine_id"] == "FeedbackProcessor"]
print(f"total={len(rows)} err={len(err)} weightmanager={len(wm)} feedback={len(fb)}")
for r in err[:10]:
    print("ERR:", r["timestamp"], r["engine_id"], r["action_type"], r["output_summary"])
EOF

# monitoring_design §4.2 実行
py -3.10 - <<'EOF'
import json, datetime, collections, re
p = f"${TEST_ROOT}/logs"
f = f"{p}/log_{datetime.date.today():%Y%m%d}.jsonl"
rows = [json.loads(l) for l in open(f, encoding="utf-8") if l.strip()]
upd = [r for r in rows if r["action_type"] == "weight_updated"]
suc = [r for r in rows if r["action_type"] == "process_feedback_log_success"]
per_type = collections.Counter(re.sub(r"Applied ", "", r["input_summary"]) for r in upd)
print(f"weight_updated={len(upd)} success={len(suc)} ratio={len(upd)}/{len(suc)}")
for k, v in per_type.items():
    print(f"  {k}: {v}")
EOF
```

### 7.4 事後処理

```bash
# 1. ベースラインとの差分確認
diff -u "${TEST_ROOT}/configs/source_weights.yaml.baseline" "${TEST_ROOT}/configs/source_weights.yaml" || true

# 2. テスト隔離環境のアーカイブ（任意）
tar -czf "${TEST_ROOT}.tar.gz" "${TEST_ROOT}" && rm -rf "${TEST_ROOT}"

# 3. 環境変数クリア
unset MID_TEST_MODE
unset MID_TEST_CONFIG
```

---

## 8. 合格判定・レポート

### 8.1 合格判定マトリクス

| カテゴリ | 必須項目 | 合格条件 |
|---|---|---|
| コアワークフロー | TC-WF-01, 02, 03 | 全ステップ PASS、エラー系 action_type 0 件 |
| 障害シナリオ | Scenario 1–8 | 各 Phase A–E 完了、復旧後コアワークフロー合格 |
| 回帰試験 | RS-01 | 全既存 TC 合格、実行時間 ±20% |
| 監視不変条件 | §2.4 の 1–4 | 日次集計で全条件満たす |
| ドキュメント整合 | §6.3 | 全項目チェック済み |

### 8.2 試験結果レポートテンプレート

```markdown
# E2E Test Report: YYYY-MM-DD

## 概要
- 実行者: 
- 環境: Windows 10 / py-3.10 / MID_TEST_MODE=1
- 試験ID: e2e_YYYYMMDD_HHMMSS

## 結果サマリ
| カテゴリ | 試験数 | 合格 | 不合格 | スキップ |
|---|---|---|---|---|
| Core Workflows | 3 |  |  |  |
| Scenario Injection | 8 |  |  |  |
| Regression Suite | 1 |  |  |  |

## 詳細結果
### TC-WF-01 Weight Update
- [ ] Step 1-5 All PASS
- エラー系 action_type: 0 件

### TC-WF-02 Feedback Processing
- [ ] Step 1-5 All PASS
- weight_updated / success 突合: OK

### TC-WF-03 Log Integrity
- [ ] Step 1-4 All PASS
- 散乱ファイル: 0 件

### Scenario 1–8
| Scenario | Phase A | Phase B | Phase C | Phase D | Phase E | 備考 |
|---|---|---|---|---|---|---|
| S1 NaN/Inf |  |  |  |  |  |  |
| S2 Double Apply |  |  |  |  |  |  |
| ... |  |  |  |  |  |  |

## インシデント・逸脱記録
- なし / あり（詳細）

## 判定
- [ ] **全項目合格 → リリース可 / 運用継続可**
- [ ] 条件付き合格（詳細）
- [ ] **不合格 → リリース停止 / 即時調査**

## 次回アクション
- 
```

---

## 9. 障害注入テストとしてのドリル活用（fault_response_flow §7 連携）

| ドリル頻度 | 対象 Scenario | 本試験計画での位置づけ |
|---|---|---|
| 月 1 回 | Scenario 4 | RS-02 として自動化済み |
| 四半期 1 回 | Scenario 3 | RS-03 として手順書ベース実施 |
| 年 1 回 | Scenario 1 | RS-04 として全工程（P1 想定）実施 |

> ドリル実施時は本計画の **Phase A–E** をそのまま実行し、結果を **§8.2 レポートテンプレート** で記録する。ドリル所要時間・気づき・手順改善点を `fault_response_flow.md` の「更新履歴」および `monitoring_design.md` の「既知のギャップ」に反映すること。

---

## 10. 既知の制約・今後の拡張

| # | 制約 | 影響 | 対応計画 |
|---|---|---|---|
| C1 | Engine-1/2/3 未実装 | `correlation_id` 結線検証不可 | Phase 6 で実装時、§3.3 に結線試験を追加 |
| C2 | ~~`validate_configs.py` 未製品化~~ | 2026-11-20 に固化済み（`validate_configs.py` / `scripts/validate_feedback_rules.py` / `validate_log_integrity.py`） |
| C3 | 自動通知未実装 | P1 検知から初動までタイムラグ | Phase 6 で telegram 連携（monitoring_design §9-3） |
| C4 | DEAD_LETTER 未実装 | Scenario 6 の自動隔離不可 | Phase 6 で導入（monitoring_design §9-1） |
| C5 | テスト隔離フィクスチャの手動準備 | 試験実行の手間・ミスリスク | `pytest` フィクスチャ化・CI 組込（Phase 6） |

---

## 11. 変更履歴

| 日付 | 版数 | 変更内容 | 作成者 |
|---|---|---|---|
| 2026-11-16 | 1.0 | 初版作成（Phase 5 運用開始時） | longcat-2.5:free |
| 2026-11-20 | 1.1 | C2 解消: `validate_configs.py` / `scripts/validate_feedback_rules.py` / `validate_log_integrity.py` を導入 | respawn |

---

*本計画は Phase 5 運用開始時のベースラインとする。インシデント発生時・四半期見直し時に `updated` と変更履歴を更新すること。*