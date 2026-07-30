# Steam Demo QA Runs

このディレクトリには、公開候補Buildに対して実際に手動QAを行った結果だけを保存します。

未実施のRunや、すべてを機械的に`pass`へ変更した架空のRunはコミットしません。

## ディレクトリ構成

```text
qa/runs/<run-id>/
├─ report.json
├─ build_manifest.json
├─ SUMMARY.md
└─ evidence/
   ├─ BUILD-002-title.png
   ├─ FLOW-004-battle.log
   └─ ...
```

- `report.json`: Case結果、環境、Defect、公開判断
- `build_manifest.json`: QA対象Artifactに同梱されていたBuild Manifestの原本
- `SUMMARY.md`: QA Toolが生成するレビュー用要約
- `evidence/`: スクリーンショット、短いログ、動画への参照資料

## 命名

Run IDは次の形式を推奨します。

```text
qa-<git-sha先頭8文字>-<UTC日時>
```

例:

```text
qa-55a97c39-20260730T010000Z
```

## セキュリティ

- 個人情報、秘密情報、アクセストークンを保存しない
- セーブデータ原本をコミットしない
- 長大なログは必要範囲だけを切り出す
- 外部共有できない動画は、アクセス制御されたURLを`evidence.reference`へ記録する

## 検証

```bash
python tools/steam_demo_qa.py validate \
  --report qa/runs/<run-id>/report.json
```

配下の全Runを検証:

```bash
python tools/steam_demo_qa.py validate-all --reports-root qa/runs
```

Release Gateが`pass`になるには、すべてのRelease Blocking CaseがPassし、重大な未解決Defectがなく、実施責任者による最終承認が必要です。
