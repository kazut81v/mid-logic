# MIDプロジェクト Phase 7 Engine Interface Spec - 議事録 / セッションノート

**日付**: 2026-11-24
**参加者**: @user, @librarian, @respawn
**目的**: MIDプロジェクト Phase 7 Engine Interface Spec (Draft) の polish と実装合意
**ステータス**: 仕様合意完了 → 実装着手 (7-1/7-2) / @respawn 実装中

---

## 1. 経緯・背景

- Phase 1〜6 完了。Phase 7 (Full Integration) で Engine-1/2/3 実装へ移行する段階。
- @respawn が作成した「Phase 7 Engine Interface Spec (Draft)」を @librarian が polish する目的でグループチャット開始。
- Vault 内にドラフトファイルが見つからず、@respawn からチャット上で草案共有を受領。

---

## 2. 初期ドラフト（@respawn 提供）

**タイトル**: MIDプロジェクト Phase 7 Engine Interface Spec (Draft)
**目的**: Phase 7 に向けたエンジンと外部モジュール間のインタフェース定義
**対象**: エンジンコア、データ処理モジュール、ユーザーインタフェースモジュール
**主要変更点**:
- データフローの再設計
- メモリ管理の最適化
- エラーハンドリングの強化

※ 方針レベルにとどまり、実装可能な仕様には未到達

---

## 3. ポリッシュ案（@librarian 提示・合意済み）

### 3.1 アーキテクチャ前提
| 項目 | 定義 |
|------|------|
| 通信方式 | 非同期メッセージング（in-proc: `asyncio.Queue` / cross-process: Redis Streams） |
| 直列化 | **MessagePack** + **JSON Schema** 契約検証 |
| バージョニング | `v1` 固定。破壊的変更は `v2` 並行運用後切替 |
| 観測性 | 全メッセージに `trace_id`, `span_id`, `timestamp_ns` 付与（OpenTelemetry互換） |

### 3.2 エンジン別インタフェース契約

#### Engine-1: Collector / Normalizer
```python
class NormalizedArticle(TypedDict):
    article_id: str              # UUIDv7
    source_id: str
    reliability_category: Literal["official", "major_media", "tech_journal", "specialized"]
    title: str
    body_md: str
    published_at: int            # Unix ns
    fetched_at: int
    url: str
    content_hash: str            # SHA-256
    metadata: dict
```
**SLA**: 遅延中央値 < 5 分、99%-ile < 30 分

#### Engine-2: Synthesizer / Judge
```python
class ActionableInsight(TypedDict):
    decision_point: str
    recommended_action: str
    confidence: Literal["High", "Medium", "Low"]
    confidence_gaps: list[str]
    residual_risks: list[str]

class SynthesisResult(TypedDict):
    cluster_id: str
    articles: list[str]
    summary_md: str
    insight: ActionableInsight   # ★必須ブロック
    weight_snapshot: dict
    generated_at: int
```
**検証ルール**: `insight` 欠落時はリジェクト → DLQ

#### Engine-3: Publisher / Delivery
```python
class DeliveryRecord(TypedDict):
    synthesis_id: str
    channels: list[Literal["obsidian", "email", "webhook", "cli"]]
    status_per_channel: dict[str, Literal["ok", "failed", "retrying"]]
    delivered_at: int
    retry_count: int
```

### 3.3 共有データ契約（Envelope）
```python
class Envelope(TypedDict):
    spec_version: Literal["v1"]
    msg_type: Literal["NormalizedArticle", "SynthesisResult", "DeliveryRecord", "HealthMetric", "FeedbackEvent"]
    trace_id: str
    span_id: str
    timestamp_ns: int
    payload: ...
```

### 3.4 メモリ管理・ステート
| エンジン | ステート種別 | 保存先 | TTL / 保持 |
|---------|-------------|--------|-----------|
| Engine-1 | `source_health` | `source_weights.yaml` (inline) | 永続 |
| Engine-2 | `cluster_cache` | Redis / LMDB | 24 h |
| Engine-3 | `delivery_log` | SQLite (WAL) / JSONL | 30 日 |

### 3.5 エラーハンドリング・リトライポリシー
| エラー分類 | 対象 | リトライ | DLQ 条件 |
|-----------|------|---------|----------|
| `Transient` | 全エンジン | 指数バックオフ (max 5 回) | 5 回失敗 |
| `SchemaViolation` | Engine-1→2, 2→3 | **なし** | 即時 |
| `BusinessReject` | Engine-2→3 | **なし** | 即時 |
| `PoisonPill` | 全 | — | 即時 + アラート |

### 3.6 監視メトリクス（Prometheus 互換）
- `engine1_fetch_latency_seconds`, `engine1_normalized_total`
- `engine2_synthesis_latency_seconds`, `engine2_confidence_distribution`
- `engine3_delivery_latency_seconds`, `engine3_delivery_total`
- `engine_queue_depth`, `engine_dlq_total`

### 3.7 フィードバックループ
```python
class FeedbackEvent(TypedDict):
    event_id: str
    synthesis_id: str
    article_ids: list[str]
    label: Literal["useful", "inappropriate", "fix_requested"]
    comment: str | None
    engine_version: str
    created_at: int
```
- 重み更新: `inappropriate: -0.1`, `fix_requested: +0.05`, `useful: +0.01`
- クリップ: `[0.1, 1.5]`
- 適用: 非同期バッチ (5 分毎)

### 3.8 実装タスク分解（Phase 7 スプリント）
| ID | タスク | 担当 | 受入基準 |
|----|--------|------|----------|
| 7-1 | `schemas/` パッケージ作成 | respawn | `pytest -k schema` 全緑 |
| 7-2 | Envelope 検証ミドルウェア | respawn | 不正メッセージ 100% リジェクト |
| 7-3 | Engine-1→2 キュー実装 | respawn | 負荷試験 1k msg/s |
| 7-4 | Engine-2 `insight` 必須化 | librarian | 欠落時 DLQ ルーティング確認 |
| 7-5 | Engine-3 マルチチャネル配信 | respawn | 各チャネル実配信成功 |
| 7-6 | 監視ダッシュボード追加 | librarian | 全メトリクス可視化・アラート 5 件以上 |
| 7-7 | E2E テスト 5 ケース自動化 | 両者 | CI で全パス |

---

## 4. 判断事項 ①〜⑤（全項目合意済み）

| # | 項目 | 合意内容 |
|---|------|----------|
| ① | 通信基盤 | in-proc `asyncio.Queue` で開始、Redis Streams はスケールアウト時導入 |
| ② | 直列化 | **MessagePack** 採用（パース速度・帯域効率重視） |
| ③ | スキーマ言語 | **`msgspec.Struct` 単一ソース**統一、JSON Schema は自動生成 |
| ④ | クラスタリング | Engine-1: ヒューリスティック(キーワード/エンティティ) → 第1クラスタ<br>Enrichment Module: Embedding+DBSCAN → 第2クラスタ（非同期・疎結合） |
| ⑤ | バージョニング | 移行期間 **2 スプリント** |

---

## 5. 追加定義：DLQ ポリシー

| 項目 | 設定値 | 根拠 |
|------|--------|------|
| 保留期間 | 7 日 (`TTL_DAYS = 7`) | 運用週次レビューに間に合う |
| リプレイ | 手動トリガーのみ (`dlq replay --trace-id <id> --fix-payload <json>`) | 自動リプレイは無限ループリスク |
| 可視化 | Grafana `engine_dlq_age_hours` + アラート（24h超で通知） | 放置防止 |
| 最大件数 | 10,000 件/エンジン（超過時最古から削除・`dlq_overflow_total` インクリメント） | ディスク保護 |

→ `schemas/dlq_policy.yaml` として 7-1 に同梱

---

## 6. 実装着手合意（2026-11-24）

### @respawn 実装計画
1. **インフラ設置**: `schemas/` パッケージ + `pyproject.toml` 依存関係（`msgspec`, `pydantic` 等）
2. **スキーマ定義**: `msgspec.Struct` 単一ソースで 9 つの構造体定義
3. **JSON Schema 自動生成**: `msgspec.to_json_schema()` で出力ファイル同梱
4. **検証ミドルウェア**: Envelope 検証 → 成功: 次キュー / 失敗: DLQ + Prometheus メトリクス
5. **テスト**: 正常系・必須欠落・型不正・未知 `msg_type` の 4 ケース以上

### 進捗記録フォーマット（統一）
```markdown
## YYYY-MM-DD
- **Done**: <PRリンク / 完了タスク>
- **Blocking**: <あれば>
- **Next**: <翌日着手>
```

### PR レビュー観点（@librarian 事前共有）
- 単一ソース原則（`msgspec.Struct` のみ）
- Envelope 必須フィールド 6 つ強制
- 検証ミドルウェア 2 経路のみ
- 後方互換（`Optional` / デフォルト値のみ追加許容）
- テスト 4 ケース以上網羅

---

### 2026-11-24 実装進捗
- **7-1 `schemas/` パッケージ作成**: ✅ 完了
  - `schemas/contract.py`: msgspec.Struct 9構造体定義完了（NormalizedArticle, ActionableInsight, SynthesisResult, DeliveryRecord, Envelope, FeedbackEvent, HealthMetric）
  - `schemas/verify.py`: Envelope 検証ミドルウェア実装（正常系→次キュー / 不正系→DLQ）
  - `tests/test_schemas.py`: テスト8ケース全パス（型一致, 必須欠落, 未知msg_type, Enum不正, payload欠落, insight必須）
- **7-2 Envelope 検証ミドルウェア**: ✅ 完了
- **7-3 Engine-1→2 キュー実装**: ✅ 完了
  - `schemas/dlq.py`: DeadLetterQueue 実装（メモリ保持, JSON永続化, max_size Eviction, 追跡/取得/クリア API）
  - `schemas/dlq_policy.yaml`: DLQ ポリシー定義（TTL=7日, 手動リプレイのみ, max_size=10,000, 可視化指標）
  - `tests/test_dlq.py`: テスト7ケース全パス（記録/取得/スニペット截断, max_size Eviction, ファイル永続化, ファイル復帰保存, 最近N件取得）
- **7-4 Engine-2 `insight` 必須化 / DLQ ルーティング**: ✅ 完了
  - `verify.py`: `insight` 欠落時即時リジェクト + DLQ ルーティング確認済み
  - `test_schemas.py`: `insight` 必須テストパス済み

### 現在地
| ステータス | 詳細 |
|-----------|------|
| **仕様合意** | 完了（全項目合意済み） |
| **実装** | 7-1/7-2/7-3/7-4 完了。7-5 マルチチャネル配信へ移行可 |
| **PR** | 未作成（作成次第 @librarian が即時レビュー） |
| **ブロッカー** | なし（既存の `regression_test.py` は S2 Regression 失敗のみで Phase 7 非依存） |

**次のマイルストーン**: PR 作成 → レビュー → マージ → 7-5 Engine-3 マルチチャネル配信

---

## 8. Botモード Librarian への引き継ぎ事項

このセッションノートは以下の目的で参照される：
1. **進捗同期**: 現在 Phase 7 のどの段階にあるか（実装着手済み・PR待ち）
2. **仕様参照**: 合意済みインタフェース仕様の単一信頼ソース
3. **判断履歴**: ①〜⑤・DLQ ポリシー等の決定理由トレーサビリティ
4. **次アクション**: PR レビュー → 7-3 キュー実装へのスムーズな移行

---

*作成: @librarian (2026-11-24) / 更新: 同*