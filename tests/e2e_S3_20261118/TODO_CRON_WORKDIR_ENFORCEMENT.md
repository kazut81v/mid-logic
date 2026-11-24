# TODO: S3 Prevent — cron workdir enforcement (R1)

## 再発防止 (Prevent)
- 検知 (EB-03): `find "$HOME" -name "log_*.jsonl" -not -path "*/Feedback/logs/*" -not -path "${TEST_ROOT}/logs/*"` で散乱を検出。
- 対応 (EB-04): `paths.yaml` の `base_path` を正規のテスト隔離パスへ復帰し、散乱ログは `logs/` へ移動（削除しない）。
- 恒久防止: cron ランナーには `--workdir "$HOME"` を必須化する（deployment_procedures §2.3 R1）。CI ゲートを追加。
  - 検証: `hermes cron list` / `hermes cron status` で `mid-morning-digest` の workdir が `$HOME` であることを確認。
  - 自動化: PR マージ必須 gate（RS-01 / CI）で `--workdir "$HOME"` 遵守をチェック。

## 検証結果（2026-11-18）
- EB-01: base_path を Windows TEMP (AppData/Local/Temp) へ変更 -> 散乱ログ生成
- EB-02: log_event 発行 -> `AppData/Local/Temp/logs/log_20261118.jsonl` に書出
- EB-03: 散乱検出 -> 6 件（うち S3 由来 1 件）
- EB-04: paths.yaml 正規パス復帰 + 散乱ログを test logs/ へ移動
- EB-05: TC-WF-03 回帰 -> 31 行全有効JSON、散乱 0（S3 由来）、PASS
- 注記: ロードパスは `MID_TEST_CONFIG`（絶対Windowsパス `C:/Users/...` 必須）で解決。相対PATH が CWD(=project root)相対だと二重プレフィックスで参照失敗する。

## メタデータ
- 試験日: 2026-11-18
- シナリオ: S3 (ログ散乱)
- ステータス: 完了（Prevent 文書化済み）
