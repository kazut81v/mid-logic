---
type: rollback-plan
status: active
date: 2026-11-16
updated: 2026-11-20
author: longcat-2.5:free
tags: [mid, operations, rollback, disaster-recovery]
related: "[[Memory/Projects/mid_logic/operations/deployment_procedures.md]], [[Memory/Projects/mid_logic/operations/fault_response_flow.md]], [[Memory/Projects/mid_logic/operations/monitoring_design.md]]"
---

# MID 退回し計画（rollback_plan）

## 1. 目的と適用範囲

本ドキュメントは、MID（Morning Intelligence Digest）プロジェクトにおいて、デプロイ・設定変更・コード修正のいずれかが失敗した場合に、**最後に既知の正常状態（Last Known Good）へ確実に復帰する手順**を定める。

対象は Phase 5（Operational Readiness）以降の全運用変更とする。

| 対象 | 配置先 |
|---|---|
| `weight_manager.py` | `Memory/Projects/mid_logic/` |
| `feedback_processor.py` | `Memory/Projects/mid_logic/` |
| `logger.py` | `Memory/Projects/mid_logic/` |
| `source_weights.yaml` | `Memory/Configs/` |
| `feedback_rules.yaml` | `Memory/Configs/` |
| `paths.yaml` | `Memory/Configs/` |
| Hermes cron ジョブ | `mid-morning-digest` |

関連資料：デプロイ手順は [[deployment_procedures]] 、障害対応は [[fault_response_flow]] 、定期試験は [[e2e_test_plan]] を参照。

## 2. 退回しの基本原則

### 2.1 退回しの判断基準

以下のいずれかに該当した場合、**その場での修正を試みず退回しを優先する**。

- 設定ファイル（YAML）が破損し `yaml.safe_load` が失敗する
- 重み値に非有限値（NaN / Inf）が混入した
- ログ出力先が Vault 外に散乱し、監査証跡が分断された
- フィードバック反映が二重適用され、重みが意図せず変動した
- デプロイ後 30 分以内に P1/P2 アラートが継続している

> 原則：**「直す」より「戻す」を先に行い、原因調査は復旧後**とする。原因不明のまま再デプロイすると、同一障害の再発と証跡の消失を招く。

### 2.2 旧世代バックアップの取り扱い（重要）

`mid_logic/` 配下の `weight_manager_backup.py` / `feedback_processor_backup.py` は**旧世代の参照版**であり、以下が現行と異なる：

| 項目 | 旧世代（`*_backup.py`） | 現行 |
|---|---|---|
| パス体系 | `Memory/Configs` を直接指定 | `paths.yaml` 経由の相対解決 |
| スキーマ前提 | `sources` を dict 前提 | list 形式は `load_weights()` で dict へ正規化（Scenario 4 対策済み） |
| 依存 | `logger` 未使用 | `logger.log_event` に依存 |

**現行環境への巻き戻しには使用しないこと。** 巻き戻しは必ず Phase 0 で取得した `backups/<TS>/` スナップショットを使用する。

> **2026-11-20 更新**: `code_rollback.py` が導入され、L2 コード巻き戻しが自動化された。
> 初回 `backup_code()` 実行時、旧世代 `*_backup.py` は `backups/legacy/` へ退避される
> （削除されない）。これ以降 `mid_logic/<name>_backup.py` は **L2 の正しい復元点**
> として扱える（`# L2 code rollback backup` マーカー付き）。

### 2.3 退回しの単位

退回しは **3 層** で実施し、影響範囲に応じて最小単位から選択する。

| 層 | 対象 | 復旧時間目標 |
|---|---|---|
| L0 | cron ジョブの一時停止（処理停止） | 1 分 |
| L1 | 設定ファイル（YAML）の巻き戻し | 5 分 |
| L2 | コード（`.py`）＋設定の完全巻き戻し | 15 分 |

> L2 は `code_rollback.py`（§4.3）で自動化済み。手順書の `cp` 手順は同等の
> マニュアル手順として残す。

## 3. 事前準備（退回しの前提）

退回しは「バックアップが存在すること」を前提とする。バックアップは**デプロイ・変更のたびに**取得を必須とする。

### 3.1 バックアップ取得手順

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

**コードスナップショット（L2 復元点）** — 上記 `cp` に加えて `code_rollback.py` でも
同名の復元点を作成する（`*_backup.py` ＋ `backups/code/<TS>/`）:

```bash
cd "$HOME"
py -3.10 OneDrive/Vault/Memory/Projects/mid_logic/code_rollback.py backup \
  --note "Phase 0 snapshot $TS"
```

### 3.2 バックアップの健全性確認

退回し前に、バックアップが実際に使用可能か確認する。

```bash
cd "$HOME/OneDrive/Vault/Memory"
BK="Projects/mid_logic/backups/<TS>"   # 退回し対象の TS に置換

# 1) チェックサム検証（破損・欠落の検出）
cd "$BK" && sha256sum -c MANIFEST.sha256 && cd "$HOME/OneDrive/Vault/Memory"

# 2) YAML の構文・型チェック
py -3.10 - <<'EOF'
import math, yaml, sys
bk = "Projects/mid_logic/backups/<TS>/configs"
w = yaml.safe_load(open(f"{bk}/source_weights.yaml", encoding="utf-8"))
r = yaml.safe_load(open(f"{bk}/feedback_rules.yaml", encoding="utf-8"))
assert isinstance(w.get("sources"), (dict, list)), "sources missing"
for s in (w["sources"].values() if isinstance(w["sources"], dict) else w["sources"]):
    bw = s.get("base_weight")
    assert isinstance(bw, (int, float)) and math.isfinite(bw), f"invalid base_weight: {s}"
assert r["weight_min"] < r["weight_max"], "clip range invalid"
print("backup validation passed")
EOF
```

**Gate**: チェックサム不一致・YAML パース失敗・非有限値が 1 件でも検出された場合、そのバックアップは使用不可。1 つ前の TS へ退避を試みる。

### 3.3 バックアップ保持ポリシー

| 項目 | 設定 |
|---|---|
| 保持期間 | 直近 30 日 |
| 世代数 | 最低 5 世代 |
| 保管場所 | `Memory/Projects/mid_logic/backups/<TS>/` |
| 削除 | 30 日超過分は `backups/archive/` へ移動（削除は手動・要レビュー） |

> 注意: `backups/` 配下は OneDrive 同期対象であるため、削除は同期反映後も残る。誤削除を避けるため、削除前に Vault の変更履歴へ記録すること。

## 4. 退回し手順

### 4.1 L0: cron ジョブの一時停止

**目的**: 障害が進行中の場合、これ以上の重み破損・ログ散乱を防ぐ。最初に必ず実施する。

```bash
hermes cron pause mid-morning-digest
hermes cron list          # status が paused であること
hermes cron status        # 次回実行が None であること
```

**判断**: 処理が走っていない時間帯（09:00 の実行後 30 分以外）であれば、L0 は数秒で完了する。実行中の場合は `hermes cron` の停止完了を待ってから次へ進む。

### 4.2 L1: 設定ファイルの巻き戻し

**適用場面**: 重みの異常変動、clip 境界への張り付き、ルール誤編集。

```bash
cd "$HOME/OneDrive/Vault/Memory"
BK="Projects/mid_logic/backups/<TS>"

# 1) 現行ファイルを退避（上書きしない）
TS_NOW=$(date +%Y%m%d_%H%M%S)
mkdir -p "Projects/mid_logic/backups/failed_$TS_NOW"
cp Configs/source_weights.yaml Configs/feedback_rules.yaml Configs/paths.yaml \
   "Projects/mid_logic/backups/failed_$TS_NOW/"

# 2) バックアップから復元
cp "$BK/configs/source_weights.yaml" "$BK/configs/feedback_rules.yaml" "$BK/configs/paths.yaml" Configs/

# 3) 検証
py -3.10 - <<'EOF'
import math, yaml
w = yaml.safe_load(open("Configs/source_weights.yaml", encoding="utf-8"))
r = yaml.safe_load(open("Configs/feedback_rules.yaml", encoding="utf-8"))
items = w["sources"].values() if isinstance(w["sources"], dict) else w["sources"]
for s in items:
    bw = s.get("base_weight")
    assert isinstance(bw, (int, float)) and math.isfinite(bw), f"invalid: {s}"
    print(f"{s.get('id'):16} bw={bw}")
print("weight_min/max:", r["weight_min"], r["weight_max"])
EOF
```

**Gate**: 上記が全 source で `bw` を出力し、例外が発生しないこと。

### 4.3 L2: コード＋設定の完全巻き戻し

**適用場面**: コード変更に起因する障害（`logger` 依存の破損、`paths.yaml` 解決失敗、`ModuleNotFoundError`）。

**自動手順（推奨）** — `code_rollback.py` が退避・復元・構文検証を一括で行う:

```bash
cd "$HOME"
PROJ="OneDrive/Vault/Memory/Projects/mid_logic"

# 1) 復元（壊れた live ファイルは backups/failed_<TS>/ へ自動退避される）
py -3.10 "$PROJ/code_rollback.py" restore

# 2) 設定（YAML）は L1 と同様にバックアップから復元
cd "$HOME/OneDrive/Vault/Memory"
BK="Projects/mid_logic/backups/<TS>"
cp "$BK"/configs/*.yaml Configs/

# 3) 構文・スモーク検証
py -3.10 "$PROJ/code_rollback.py" verify
py -3.10 "$PROJ/weight_manager.py"
py -3.10 "$PROJ/test_logger.py"
```

`restore` は同ディレクトリの `<name>_backup.py` から復元する。タイムスタンプ
スナップショットから戻す場合は `--ts` を指定する:

```bash
py -3.10 "$PROJ/code_rollback.py" list                      # 利用可能なスナップショット
py -3.10 "$PROJ/code_rollback.py" restore --ts 20261120_200045
```

**手動手順（`code_rollback.py` が使えない場合のフォールバック）**:

```bash
cd "$HOME/OneDrive/Vault/Memory"
BK="Projects/mid_logic/backups/<TS>"

# 1) 現行コードを退避
TS_NOW=$(date +%Y%m%d_%H%M%S)
mkdir -p "Projects/mid_logic/backups/failed_$TS_NOW"
cp Projects/mid_logic/weight_manager.py Projects/mid_logic/feedback_processor.py \
   Projects/mid_logic/logger.py "Projects/mid_logic/backups/failed_$TS_NOW/"

# 2) コード・設定を復元
cp "$BK"/weight_manager.py "$BK"/feedback_processor.py "$BK"/logger.py Projects/mid_logic/
cp "$BK"/configs/*.yaml Configs/

# 3) 構文検証
py -3.10 -m py_compile Projects/mid_logic/weight_manager.py \
                        Projects/mid_logic/feedback_processor.py \
                        Projects/mid_logic/logger.py
```

**Gate**: `code_rollback.py verify`（または `py_compile`）が全ファイルで成功し、スモークテストで重みが表示されること。

### 4.4 cron ジョブの再開

```bash
hermes cron resume mid-morning-digest
hermes cron list          # status が active、next_run_at が翌朝であること
```

再開後は [[deployment_procedures]] §4 の受け入れチェックリストを実施し、全項目を満たすまで本番稼働とみなさない。

## 5. 退回し後の検証

### 5.1 必須検証項目

| # | 項目 | 確認方法 | 合格基準 |
|---|---|---|---|
| V1 | 重みの有限性 | §4.2 の検証スクリプト | 全 source が有限値 |
| V2 | ログ出力先 | `ls OneDrive/Vault/Memory/Feedback/logs/` | Vault 内に生成 |
| V3 | エラー系 action_type | 当日ログの grep | 0 件 |
| V4 | cron 状態 | `hermes cron list` | active / next_run が翌朝 |
| V5 | スモークテスト | §4.3（`code_rollback.py verify` + `weight_manager.py` + `test_logger.py`） | 成功 |

### 5.2 ログ整合性の確認

退回しで設定を巻き戻した場合、ログ上の重み値とファイル上の重み値に一時的な不整合が生じる。これは**退回しの正常な副作用**であり、再開後の初回実行で再同期される。

```bash
cd "$HOME"
py -3.10 - <<'EOF'
import json, glob, datetime
f = f"OneDrive/Vault/Memory/Feedback/logs/log_{datetime.date.today():%Y%m%d}.jsonl"
rows = [json.loads(l) for l in open(f, encoding="utf-8") if l.strip()]
err = [r for r in rows if "error" in r["action_type"]]
print(f"total={len(rows)} err={len(err)}")
for r in err[:10]:
    print("ERR:", r["timestamp"], r["engine_id"], r["action_type"])
EOF
```

**自動チェック**: `validate_log_integrity.py` が上記に加えて JSONL 破損行・
時刻順・`weight_updated` vs `process_feedback_log_success` 不変条件を検証する:

```bash
cd "$HOME"
py -3.10 OneDrive/Vault/Memory/Projects/mid_logic/validate_log_integrity.py
```

## 6. シナリオ別退回し判断

| シナリオ | 症状 | 退回し層 | 備考 |
|---|---|---|---|
| Scenario 1 | 非有限値（NaN/Inf）検出 | L1 | 重みファイルのみ差し替え。原因は手動編集の有無を確認 |
| Scenario 3 | ログ書込不能（容量/権限） | L0 → L1 | まず処理停止。Vault 外散乱ファイルを削除 |
| Scenario 4 | `sources` list/dict 不整合 | L1 → L2 | `load_weights()` が list を dict へ正規化するコード修正済み（2026-11-20）。まず L1 で設定を巻き戻す |
| Scenario 5 | コード変更後の `ModuleNotFoundError` | L2 | `py -3.10` 環境の確認を兼ねる |
| Scenario 6 | 二重適用による重み変動 | L1 | フィードバックログの重複実行を確認 |

> 各シナリオの詳細な初動対応は [[fault_response_flow]] を参照。

## 7. ロールバックの訓練

退回し手順は「文書として存在するだけ」では機能しない。以下を実施する。

| 頻度 | 内容 | 実施者 |
|---|---|---|
| 四半期 1 回 | L0/L1 の手順確認（実働は設定の差し替えのみ） | オーナー |
| 年 1 回 | L2 の完全巻き戻し訓練（テスト用バックアップを使用） | オーナー |

訓練後は、実施日・結果・課題を `Memory/Sessions/` に記録し、本ドキュメントの `updated` を更新する。

## 8. 既知の制約

| # | 内容 | 深刻度 | 対処 |
|---|---|---|---|
| RB1 | `backups/` が未作成の状態で障害が発生した場合、退回し元が存在しない | High | デプロイ時のバックアップ取得を必須化（§3.1） |
| RB2 | `sources` の list/dict 不整合（Scenario 4） | ~~Critical~~ Medium | 2026-11-20: `load_weights()` が list を dict へ正規化、`validate_configs.py` が CI gate で list を検出。本番は dict を維持 |
| RB3 | 旧世代 `*_backup.py` が紛らわしい配置されている | ~~Medium~~ 解消済 | 2026-11-20: `code_rollback.py` が初動時に `backups/legacy/` へ退避し、`*_backup.py` は L2 復元点として再利用（§2.2） |
| RB4 | バックアップの自動取得が未実装（手動 cp のみ） | ~~Medium~~ 解消済 | 2026-11-20: `code_rollback.py backup` で `*_backup.py` ＋ `backups/code/<TS>/` を自動取得（§3.1, §4.3） |

## 9. 付録A: コマンド早見表

| 目的 | コマンド |
|---|---|
| cron 停止 | `hermes cron pause mid-morning-digest` |
| cron 再開 | `hermes cron resume mid-morning-digest` |
| バックアップ取得 | `cd "$HOME/OneDrive/Vault/Memory"` → §3.1、または `py -3.10 "$PROJ/code_rollback.py" backup` |
| L2 コード復元 | `py -3.10 "$PROJ/code_rollback.py" restore`（`$PROJ` = `OneDrive/Vault/Memory/Projects/mid_logic`） |
| L2 構文検証 | `py -3.10 "$PROJ/code_rollback.py" verify` |
| チェックサム検証 | `cd "$BK" && sha256sum -c MANIFEST.sha256` |
| 重み検証 | §4.2 の `py -3.10` スニペット、または `py -3.10 "$PROJ/validate_configs.py"` |
| clip 範囲検証 | `py -3.10 "$PROJ/scripts/validate_feedback_rules.py"` |
| ログ整合性検証 | `py -3.10 "$PROJ/validate_log_integrity.py"` |
| スモークテスト | `cd "$HOME" && py -3.10 OneDrive/Vault/Memory/Projects/mid_logic/weight_manager.py` |

---
*Phase 5 運用開始時ドキュメント / 四半期ごとの訓練結果を反映し、updated と変更履歴を更新すること。*
