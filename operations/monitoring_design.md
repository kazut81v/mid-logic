---
type: monitoring-design
status: active
date: 2026-11-16
updated: 2026-11-20
author: longcat-2.5:free
tags: [mid, operations, monitoring, observability]
related: "[[Memory/Projects/mid_phase5_logging_design]], [[Memory/Projects/mid_logic/operations/deployment_procedures]]"
---

# MID モニタリング設計（monitoring_design）

## 1. 目的と設計方針

MID の全処理（Engine-1 検索〜 Engine-3 監査、および重み管理・フィードバック処理）に対して、**監査可能性・追跡性・性能指標**を確保する。設計根拠は [[mid_phase5_logging_design]] で、本資料はその実装（`logger.py`）を前提に監視運用を具体化する。

基本方針：

1. **監査可能性**: 信頼性スコアや合成の判断根拠（なぜ）を残す。
2. **追跡性**: `correlation_id` により Engine-1 → Engine-2 → Engine-3、および重み更新・フィードバック反映を 1 リクエスト単位で結線する。
3. **粒度**: Informational / Decision / Error-Warning の 3 区分を `action_type` の語彙で表現する。
4. **性能**: ロギングによる処理時間の増分は 5% 未満（Phase 5 成功基準）。

## 2. ログ基盤の仕様（実装ベース）

### 2.1 ファイルとフォーマット

| 項目 | 値 |
|---|---|
| 出力先 | `<base_path>/<log_path>` = `OneDrive/Vault/Memory/Feedback/logs/` |
| ファイル名 | `log_YYYYMMDD.jsonl`（日次ローテーション） |
| 形式 | JSONL（1 行 1 イベント、UTF-8、`ensure_ascii=False`） |
| 書き込み | append（`open(..., 'a')`） |

### 2.2 エントリフィールド

```json
{
  "timestamp": "ISO8601",
  "engine_id": "WeightManager | FeedbackProcessor | ConfigLoader | Engine-1/2/3",
  "action_type": "後述カタログ参照",
  "correlation_id": "req-YYYYMMDD-NNN を推奨",
  "input_summary": "処理対象の要約",
  "output_summary": "結果の要約",
  "metadata": {}
}
```

> R3（既知制約）: `logger.py` には `level` フィールドが無いため、重大度判定は `action_type` と `engine_id` の組み合わせで行う（§2.3 の「区分」列）。

> 現状の `correlation_id`: `weight_manager.py` / `feedback_processor.py` の `log_event` 呼び出しは source_id または `"none"` を渡す実装になっており、エンジン間結線は未整備。Engine-1/2/3 実装時に `req-YYYYMMDD-NNN` 形式の通し ID を全イベントへ伝播させ、監視側は `"none"` を「未結線」として集計から除外する。

### 2.3 action_type カタログ（実装の `log_event` 呼出と完全対応）

| engine_id | action_type | 区分 | 意味 |
|---|---|---|---|
| WeightManager | `update_health_metrics` | Decision | 健全性メトリクスの更新成功（output_summary: `Metrics: {...}`） |
| WeightManager | `load_weights_error` | Error | 重みファイル読込失敗 |
| WeightManager | `save_weights_error` | Error | 重みファイル書込失敗 |
| WeightManager | `weights_file_missing` | Warning | 重みファイル不在（空セットで初期化） |
| WeightManager | `update_metrics_error` | Error | メトリクス更新中の例外（保存失敗等） |
| FeedbackProcessor | `process_feedback_log_success` | Decision | 行ごとのフィードバック反映成功（output_summary: `Impact score: X`） |
| FeedbackProcessor | `weight_updated` | Decision | **重み delta 適用**（output_summary: `New weight: X`） |
| FeedbackProcessor | `load_weights_error` | Error | 重み読込失敗 |
| FeedbackProcessor | `load_rules_error` | Error | ルール読込失敗 |
| FeedbackProcessor | `save_weights_error` | Error | 重み書込失敗 |
| FeedbackProcessor | `log_file_missing` | Warning | 入力 JSONL 不在 |
| FeedbackProcessor | `json_decode_error` | Warning | 不正行のスキップ（デッドレター候補） |
| FeedbackProcessor | `process_log_error` | Error | 処理全体の致命的例外 |
| ConfigLoader | `config_load_error` | Warning | `paths.yaml` 読込失敗（フォールバック使用）※feedback_processor 側は握り潰し |
| Engine-1 | `search_discovery` | Info | 検索発見（planned） |
| Engine-2 | `synthesis_output` | Decision | 合成結果（planned） |
| Engine-3 | `audit_delta_summary` | Decision | Vault 監査結果（planned） |

### 2.4 重み更新の追跡（Weight Update Tracking）

MID の重みは **2 系統** で変動する。監視は両系統を別指標で捉え、相互に突合すること。

| 系統 | イベント | 発火元 | 捕捉内容 |
|---|---|---|---|
| A: 健全性駆動 | `WeightManager.update_health_metrics` | 収集パイプライン | source 取得成功/失敗、`consecutive_failures` 増減 |
| B: フィードバック駆動 | `FeedbackProcessor.weight_updated` | 人からの feedback | delta 適用とクリップ後 `base_weight` |

**突合不変条件（reconciliation invariants）**:

1. `weight_updated` 件数 ≦ `process_feedback_log_success` 件数（同日・同一ログファイル）。
2. `feedback_rules` に定義された `feedback_type` の行は必ず `weight_updated` を伴う。success のみで `weight_updated` が無い行が散発すれば、未知 `feedback_type` かルール不整合の疑い（B4 の確認に回す）。
3. `process_feedback_log_success` の各行は `save_weights()` を呼ぶため、`save_weights_error` > 0 の場合、成功件数と整合しない書込結果が生じている（Partial Write 検知）。
4. `weight_updated` の `output_summary`（`New weight: X`）とdailyスナップショット diff が一致すること。clip 境界（0.1 / 1.5）張り付きは連続スナップショットで確認（ログはクリップ後値のみ記録）。

## 3. 監視対象 A: ソース重み（WeightManager）

### 3.1 監視ポイント

| # | 指标 | 判定基準 | 取得方法 |
|---|---|---|---|
| A1 | 重み更新成功率 | `update_health_metrics` 成功 / 総試行 ≧ 99% | 当日ログ集計 |
| A2 | `load_weights_error` / `save_weights_error` | 0 件/日 | grep |
| A3 | `consecutive_failures` 進行 | 各 source が `failure_threshold`（gov=3, tech=5）に到達前に回復 | 重みファイル direct |
| A4 | clip 境界到達 | `base_weight` が `weight_min`=0.1 または `weight_max`=1.5 に張り付いた source 数 | 重みファイル direct |
| A5 | `last_success` 鮮度 | 最終成功から `refresh_interval_min`（gov=1440, tech=60）の 2 倍を超過していない | 重みファイル direct |
| A6 | 非有限値（NaN/Inf） | 0 件（即 P1、Scenario 1） | validator |
| A7 | `weights_file_missing` | 0 件/日（確認ゼロ Otherwise 空セットで沈黙） | grep |

### 3.2 集計コマンド例

```bash
cd "$HOME"
py -3.10 - <<'EOF'
import json, glob, datetime
p = "OneDrive/Vault/Memory/Feedback/logs"
f = f"{p}/log_{datetime.date.today():%Y%m%d}.jsonl"
rows = [json.loads(l) for l in open(f, encoding="utf-8") if l.strip()]
err = [r for r in rows if "error" in r["action_type"]]
wm  = [r for r in rows if r["engine_id"] == "WeightManager"]
fb  = [r for r in rows if r["engine_id"] == "FeedbackProcessor"]
print(f"total={len(rows)} err={len(err)} weightmanager={len(wm)} feedback={len(fb)}")
for r in err[:10]:
    print("ERR:", r["timestamp"], r["engine_id"], r["action_type"], r["output_summary"])
EOF
```

### 3.3 重みファイル直接チェック

```bash
cd "$HOME"
py -3.10 - <<'EOF'
import math, yaml
w = yaml.safe_load(open("OneDrive/Vault/Memory/Configs/source_weights.yaml", encoding="utf-8"))
src = w.get("sources")
items = src.values() if isinstance(src, dict) else src
print("sources型:", type(src).__name__, "← list なら Scenario 4 の不整合")
for s in items:
    bw = s.get("base_weight")
    hm = w.get("health_metrics", {}).get(s.get("id"), {})
    flag = "" if (isinstance(bw,(int,float)) and math.isfinite(bw)) else "  ← 非有限値！"
    print(f"{s.get('id'):16} bw={bw} cf={hm.get('consecutive_failures')} ls={hm.get('last_success')}{flag}")
EOF
```

## 4. 監視対象 B: フィードバック処理（FeedbackProcessor）

### 4.1 監視ポイント

| # | 指标 | 判定基準 | 取得方法 |
|---|---|---|---|
| B1 | 日次処理行数 | 前日比 ±50% 以内の変動に収まる | 当日ログ＋JSONL 行数 |
| B2 | `process_feedback_log_success` 数 | 処理行数と整合（未達なら分岐不達＝Scenario 4 疑い） | ログ突合 |
| B3 | `load_rules_error` | 0 件/日 | grep |
| B4 | 不明 `source_id` 混入 | 0 件（unknown source は重みに入らず沈黙する） | JSONL チェック |
| B5 | delta 総量 | `inappropriate`（-0.10）/ `fix_requested`（+0.05）/ `useful`（+0.02）の内訳を週次レビュー | ログ＋重みスナップショット比較 |
| B6 | 解析失敗 | `json_decode_error` は WARNING として可視。**未知 feedback_type や rules 不整合は現状ログされない**（既知ギャップ） | 手動スモーク／トレースバック |
| B7 | **重み更新事件** | `weight_updated` 件数を日次で集計し、`process_feedback_log_success` と突合（§2.4 不変条件 1〜3） | ログ集計 |
| B8 | 保存競合 | `save_weights_error` > 0 の日は Partial Write 疑い。成功件数とファイル整合を確認 | ログ＋スナップショット |

> 重要: 現状 `save_weights()` は行ループ内で呼ばれ、分岐到達時は毎行フルファイル再書込みとなる。同時実行時に競合する可能性があるため、本監視でも「保存イベント数 vs 入力行数」の不整合を逸れなく拾うこと。

### 4.2 重み更新の内訳集計（weight_updated トラッキング用）

```bash
cd "$HOME"
py -3.10 - <<'EOF'
import json, glob, datetime, collections, re
p = "OneDrive/Vault/Memory/Feedback/logs"
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

## 5. 監視対象 C: ログ基盤ヘルス

| # | 指标 | 判定基準 |
|---|---|---|
| C1 | 日次ファイル存在 | 毎日 `log_YYYYMMDD.jsonl` が生成されている |
| C2 | 行あたりパース成功率 | JSONL 全行が `json.loads` 成功（破損行 0） |
| C3 | ファイルサイズ | 前日比 10 倍超の膨張がない（異常ループ検知） |
| C4 | 書込失败 | ディスク容量枯渇・PermissionError が無い |
| C5 | 保管場所 | `Memory/Feedback/logs/` 以外に散乱ファイルが無い |

## 6. アラートルール一覧

| 重大度 | 条件 | 即時アクション | 連絡先 |
|---|---|---|---|
| P1 | 非有限値（NaN/Inf）検出、またはログ書込不能が 30 分続く | cron 一時停止 → Scenario 1 / Scenario 3 対応 | オーナー（telegram 等） |
| P2 | `load_*_error` / `save_*_error` / `update_metrics_error` が 1 日に 1 件でも出る、`consecutive_failures` が threshold の 80%、`weight_updated` と success の不整合 | ログ確認→要因判明までdigest送信用料を見直す暂定発行 | オーナー |
| P3 | 日次処理行数の急変、clip 境界の新規張り付け、`last_success` 陳腐化、`json_decode_error` 増加 | 次回監査で確認 | 記録のみ |

通知はまず `hermes cron --failure-deliver` 経由で試行し、安定後に外部チャネルへ拡張する。

## 7. 定期監査手順

### 7.1 Daily（5 分）

```bash
hermes cron runs mid-morning-digest            # 本日用ステータス
py -3.10 <§3.2 集計スクリプト>                # エラー件数・重みイベント
py -3.10 <§4.2 重み内訳集計>                  # weight_updated 突合
```

### 7.2 Weekly（30 分）

- 前週ログの `action_type` ヒストグラム集計（情報：偏り検知）。
- `source_weights.yaml` のスナップショット diff レビュー（重みドリフト確認）。
- `last_success` が 48h 越えている source の調査。
- ログファイルのアーカイブ（30 日超は `logs/archive/` へ移動、圧縮は任意）。

### 7.3 Monthly（1 時間）

- 保持ポリシー見直し（既定 30 日）。
- `feedback_rules.yaml` の deltas が実運用の感度と合致するかの調整検討。
- 監視自体の棚卸し（既知ギャップ B6 の解消計画）。
- rollback_plan の訓練（四半期に 1 回、L0/L1 の手順確認）。

## 8. KPI / SLO

| KPI | 目標 |
|---|---|
| ログカバレッジ | 全合成サマリが生成ログの `correlation_id` を持つ（100%） |
| オーバーヘッド | ロギング追加による処理時間増分 < 5% |
| 重み更新成功率 | ≧ 99%/日 |
| エラー系 action_type | 0 件/日（P2 敷居） |
| 重みイベント突合 | `weight_updated` vs `process_feedback_log_success` 不変条件の日次合格 |
| 監視発見リードタイム | 発生から検知まで < 24h（手動監査ベース） |

## 9. 既知のギャップ（ Monitoring Debt ）

1. **B6**: 未知 `feedback_type` / rules 不整合がログに残らない → 適用除外イベントの出力と DEAD_LETTER 化。
2. レベルフィールド不在（R3）→ `action_type` 語彙の整備、将来 `logger.py` に `level` 追加。
3. 自動通知の未実装 → `hermes cron --failure-deliver` との統合、`monitor-script` 活用。
4. Validator（設定の型・有限性チェック）→ 2026-11-20 に `validate_configs.py`（設定構造・有限性・clip）/ `scripts/validate_feedback_rules.py`（CI clip gate）/ `validate_log_integrity.py`（ログ整合性）として固化済み。
5. `correlation_id` 未結線（§2.2 注記）→ Engine-1/2/3 実装時に `req-YYYYMMDD-NNN` を通す。

---
*Phase 5 運用開始時ドキュメント / 四半期ごとに KPI と照らし合わせて改訂すること。*
