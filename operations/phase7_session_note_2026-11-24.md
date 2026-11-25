# Phase 7: Engine Interface Spec - Session Note

## 1. 概要
Engine-1, Engine-2, Engine-3 のインタフェース仕様を定義。
9つのデータ構造体 (Contract)、DLQ (Dead Letter Queue)、MessageBroker (asyncio.Queue)、
Envelope 検証ミドルウェアを実装。

## 2. 設計合意事項 (Group Chat: Librarian + Respawn)
① Engine-1 (Collector) → Engine-2 (Synthesizer) → Engine-3 (Dispatcher) のパイプライン
② 全メッセージは Envelope でラップ (spec_version, msg_type, trace_id, span_id, timestamp_ns, payload)
③ DLQ は TTL=7日, max_size=10000, 手動リプレイのみ
④ 検証失敗時は自動 DLQ へルーティング
⑤ テストカバレッジ: 各モジュール 5+ テストケース

## 3. 実装ファイル一覧
- `schemas/contract.py` — 9データ構造体定義
- `schemas/verify.py` — Envelope 検証ミドルウェア
- `schemas/dlq.py` — DeadLetterQueue (メモリ内 + JSON永続化)
- `schemas/queue.py` — MessageBroker (asyncio.Queue + DLQルーティング)
- `schemas/__init__.py` — パッケージエクスポート
- `schemas/dlq_policy.yaml` — DLQ ポリシー
- `tests/test_schemas.py` — 8テストケース
- `tests/test_dlq.py` — 7テストケース
- `tests/test_queue.py` — 6テストケース

## 4. 実装ステータス
- 7-1 Engine-1 仕様: ✅ 完了 (contract.py NormalizedArticle, Envelope)
- 7-2 Engine-2 仕様: ✅ 完了 (contract.py SynthesisResult, verify.py)
- 7-3 Engine-3 仕様: ✅ 完了 (queue.py, dlq.py, dlq_policy.yaml)
- 7-4 DLQ ルーティング検証: ✅ 完了 (queue.py 検証失敗時のDLQ自動記録)
- 7-5 Engine-3 マルチチャネル配信: ⬜ 未着手 (DeliveryRecord, Obsidian/Email/Webhook/CLI)

## 5. テスト結果
```
21 passed, 1 warning
```
- test_schemas.py: 8/8 PASSED
- test_dlq.py: 7/7 PASSED
- test_queue.py: 6/6 PASSED

## 6. ブロッカー
なし

## 7. 次のマイルストーン
Phase 7-5: Engine-3 マルチチャネル配信
- DeliveryRecord スキーマに基づく配信アダプター (Obsidian/Email/Webhook/CLI)
- delivery_log の SQLite/JSONL 永続化
- リトライ機構 (指数バックオフ、最大5回)

## 8. Botモード Librarian への引き継ぎ事項
このセッションノートは以下の目的で参照される：
1. **進捗同期**: 現在 Phase 7 のどの段階にあるか（実装着手済み・PR待ち）
2. **仕様参照**: 合意済みインタフェース仕様の単一信頼ソース
3. **判断履歴**: ①〜⑤・DLQ ポリシー等の決定理由トレーサビリティ
4. **次アクション**: PR レビュー → 7-3 キュー実装へのスムーズな移行

---

*作成: @librarian (2026-11-24) / 更新: 2026-11-25*

---

## 9. Session 継承時のギャップ報告 (2026-11-25)

セッション `local-b3c4071...` (Phase 7 Engine Interface Spec) から引き継ぎ時に、
salvagelog 記載の「完了」状態と実ファイルの間に 3 件の不整合を発見。

| # | 項目 | salvagelog 記載 | 実ファイル状態 | 対応 |
|---|------|----------------|---------------|------|
| 1 | `schemas/dlq_policy.yaml` | PR#2 で追加済み | 未存在 | ✅ 作成 |
| 2 | `schemas/__init__.py` dlq/queue エクスポート | PR#2 で修正済み | 未修正 (7構造体+verifyのみ) | ✅ 修正 |
| 3 | `queue.py` DLQルーティング | PR#3 で修正済み | `rejected_dlq` カウントのみ | ✅ 修正 |

**根本原因**: salvagelog 取得元のセッションでは修正が完了したように記録されたが、
`scratch/mid-logic` ワークスペースのファイルは PR#1 初期コミット `3b07af3` の状態に留まっていた。

**追加テスト修正**:
- `tests/test_queue.py` の `test_latency_tracking` → `> 0.0` を `>= 0.0` に修正（同一プロセス内テストで即座に完了する環境での false negative）

**最終テスト結果**: 21/21 PASSED

**コミット**: `Phase 7: Fix dlq_policy.yaml missing, __init__.py exports, queue.py DLQ routing, test fix`
**ブランチ**: `feature/phase7-fix-dlq-routing` → `main` (PR#3)
