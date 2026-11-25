# TODO: S5 Prevent — os.chdir($HOME) in runner (R1 remediation)

**Scenario:** S5 — CWD 依存パスによる静かな失敗 (silent failure when run outside $HOME).

## 検証結果（2026-11-18） — 重要: 障害は再現不能だった
- EB-07 注入（cd /tmp + run weight_manager）では、`load_weights()` が空 `{"sources": {}}` になる＝静かな失敗は発生しなかった。
  原因: 現行コードは `load_config()` / `_resolve_default_config_path()` で
  `os.path.expanduser("~")`（絶対 $HOME）基準に解決するため、CWD の影響を受けない。
  `MID_TEST_CONFIG`（絶対 Windows パス `C:/Users/...`）を用いた場合も同様に独立。
- EB-08 検知: `weights_file_missing` / `config_load_error` ログは 0 件（障害自体発生せず）。
- EB-09 対応（cd $HOME + re-run）: success。
- EB-10 復旧（TC-WF-01 回帰 W1-01..W1-08）: PASS。

## 恒久防止 (Prevent)
- 再現可能性を担保するため、ランナー先頭で明示的に `os.chdir(os.path.expanduser("~"))` を入れる。
  - 参考実装（deployment_procedures §2.3 R1）:
    ```python
    import os
    os.chdir(os.path.expanduser("~"))   # CWD 依存静的失敗の予防
    ```
- 検証: `cd /tmp` のまま `py -3.10 weight_manager.py` を実行し、重みが正常ロードされることを確認。

## インシデント記録
- シナリオ S5 は「理論上の CWD 依存」がコードにより既に緩和されており、E2E 注入では未再現。
- これは R1 の「意図した障害」ではなく「既存の防御が有効」であることを示すポジティブな結果。
- 対策の完全性を保証するため、`mid_daily_run.py` 先頭に `os.chdir(expanduser("~"))` を追加し、次回 S5 ドリル時に再現確認を行うこと。

## メタデータ
- 試験日: 2026-11-18
- シナリオ: S5 (CWD 依存)
- ステータス: 完了（Prevent 文書化済み）
