# Steam Demo QA Gate

## 1. 目的

本書は、Windows向けSteamデモ公開候補Buildについて、手動QAの実施結果と公開可否を再現可能な形で記録する運用を定義する。

対象は`docs/PRODUCTION_GAP_BACKLOG.md`のM-4「QA/デバッグ最小チェックリスト整備」である。

主な目的は以下。

- New Gameからデモ完了・Continue復帰までの進行不能を検出する
- クラッシュ、セーブ破損、主要操作不能を公開前に停止条件として扱う
- QA対象ArtifactとGit Commitを確実に関連付ける
- 実行環境、証跡、関連Defectを後から追跡できるようにする
- 担当者の主観だけで公開承認できないRelease Gateを設ける

自動テストやexe Smoke Testを置き換えるものではない。

```text
Python Unittest
  + Windows Build / exe Smoke Test
  + Manual QA Gate
  = Steamデモ公開候補の最低確認
```

## 2. 構成

```text
qa/steam_demo/checklist_v1.json
  └─ Version付きQA Case定義

qa/runs/<run-id>/
  ├─ report.json
  ├─ build_manifest.json
  ├─ SUMMARY.md
  └─ evidence/

 tools/steam_demo_qa.py
  ├─ init
  ├─ record-case
  ├─ add-defect
  ├─ validate
  ├─ finalize
  └─ validate-all
```

## 3. チェックリスト契約

`qa/steam_demo/checklist_v1.json`に以下を定義する。

- Checklist ID / Version
- Section
- Case ID
- 目的
- 前提条件
- 操作手順
- 期待結果
- Release Blockingか
- Skip可能か
- 証跡必須か
- Tags

Case IDは一度公開運用に使用した後、別の意味へ再利用しない。

手順や期待結果の意味が変わる場合は`checklist_version`を更新する。

各QA RunにはChecklistの正規化JSONから計算したSHA-256を保存する。Checklistを更新した後、古いRunを新Checklistの結果として扱うことはできない。

## 4. 現在の主要確認領域

### 4.1 配布物・起動

- Artifact ZIPを展開できる
- exe、README、Build Manifest、Master Dataが存在する
- Build ManifestとQA RunのGit SHA・Artifact名が一致する
- クリーンな状態でタイトル画面へ到達する
- 配布exeの`--smoke-test`が成功する

### 4.2 タイトル・設定・終了

- セーブなしではContinueが無効
- New Game / Settings / Exitが利用可能
- 文字サイズ100% / 125% / 150%を切り替えられる
- ログ・入力ヒント表示を切り替えられる
- Exitとウィンドウ終了でプロセスが残らない

### 4.3 Steamデモ6段階

1. 最初の依頼を受注
2. 対象ロケーションへ移動
3. 最初の戦闘に勝利
4. 依頼を報告
5. 工房とクラフト入口を確認
6. デモチェックポイントを保存

後続状態だけを満たして前段階を飛び越えていないことも確認する。

### 4.4 セーブ・復帰

- チェックポイント保存が成功する
- 終了・再起動後にContinueできる
- 現在地、クエスト、デモ完了状態が復元・再計算される
- 不正セーブではクラッシュせずタイトルへ留まる
- 不正セーブが勝手に上書きされない

### 4.5 入力・画面遷移

- サブ画面から戻れる
- 戻った後に同じ画面を再度開ける
- 上下、決定、戻る、ガイドのキーボード操作が動作する
- 無効操作後も入力を継続できる

### 4.6 表示・安定性

- 主要情報が見切れない
- 最小化・復元後も操作できる
- 主要導線を含む30分以上の連続操作でクラッシュしない
- Soft Lock、入力無反応、無限待機がない
- 発見した問題がCaseとDefectへ関連付けられる

## 5. QA Run作成

### 5.1 Artifact取得

`Windows Steam Demo Build` Workflowから、対象CommitのArtifactを取得する。

QA対象は必ず次を満たすものとする。

- Workflowが成功している
- Artifactが期限切れでない
- ZIPをエラーなく展開できる
- `BUILD_MANIFEST.json`が存在する

### 5.2 Run初期化

```bash
python tools/steam_demo_qa.py init \
  --manifest path/to/BUILD_MANIFEST.json \
  --output-dir qa/runs/qa-55a97c39-20260730T010000Z \
  --tester tester-name \
  --os-name Windows \
  --os-version "11 24H2" \
  --architecture x64 \
  --resolution 1920x1080 \
  --dpi-scale 100 \
  --input keyboard_mouse \
  --artifact-digest sha256:artifact-digest \
  --run-id qa-55a97c39-20260730T010000Z
```

複数の入力方式を記録する場合は`--input`を複数指定する。

```bash
--input keyboard_mouse --input keyboard_only
```

初期化時に以下を行う。

1. Checklist契約を検証
2. Build Manifest契約を検証
3. Build ManifestをRunディレクトリへコピー
4. Manifest SHA-256をReportへ保存
5. 全Caseを`pending`で生成
6. 初期`SUMMARY.md`を生成

初期状態のRelease Gateは`incomplete`である。

## 6. Case結果の記録

### 6.1 Status

| Status | 用途 |
|---|---|
| `pending` | 未実施 |
| `pass` | 期待結果を満たした |
| `fail` | 実施できたが期待結果を満たさなかった |
| `blocked` | 前提不成立や別不具合で実施不能 |
| `skipped` | Checklistで任意と定義されたCaseのみ |

Release Blocking Caseは`skipped`にできない。

### 6.2 Passを記録

証跡不要Caseでは、具体的な確認メモを必ず残す。

```bash
python tools/steam_demo_qa.py record-case \
  --report qa/runs/<run-id>/report.json \
  --case-id TITLE-001 \
  --status pass \
  --notes "セーブ退避後、Continueが無効でNew Game・Settings・Exitは操作可能だった。"
```

証跡必須Caseでは、Runディレクトリ内の相対PathまたはURLを指定する。

```bash
python tools/steam_demo_qa.py record-case \
  --report qa/runs/<run-id>/report.json \
  --case-id FLOW-004 \
  --status pass \
  --notes "戦闘開始から勝利まで進行し、目標が依頼報告へ更新された。" \
  --evidence "video|evidence/FLOW-004-battle.mp4|戦闘開始から勝利後目標更新まで"
```

`--evidence`の形式:

```text
type|reference|description
```

利用可能なtype:

- `screenshot`
- `log`
- `video`
- `note`
- `other`

相対PathはRunディレクトリ外を参照できない。存在しないファイルも検証時に拒否する。

### 6.3 Fail / Blockedを記録

FailまたはBlockedには、具体的なNotesと登録済みDefect IDが必要である。

先にDefectを登録する。

```bash
python tools/steam_demo_qa.py add-defect \
  --report qa/runs/<run-id>/report.json \
  --defect-id BUG-123 \
  --title "戦闘勝利後に画面が更新されない" \
  --severity critical \
  --status open \
  --issue-url https://github.com/mizzz-ivr/project-asterveil/issues/123 \
  --summary "勝利ログ後も戦闘画面に残り、操作を継続できない。" \
  --case-id FLOW-004
```

Caseへ関連付ける。

```bash
python tools/steam_demo_qa.py record-case \
  --report qa/runs/<run-id>/report.json \
  --case-id FLOW-004 \
  --status fail \
  --notes "勝利ログ後に戦闘画面から遷移せず進行不能。" \
  --defect-id BUG-123 \
  --evidence "video|evidence/FLOW-004-soft-lock.mp4|勝利後の進行不能"
```

Defectを更新する場合は`add-defect`へ`--replace`を付ける。

## 7. Defect契約

### 7.1 Severity

| Severity | 基準 |
|---|---|
| `blocker` | QA自体を続行できない、Build全体が起動しない |
| `critical` | クラッシュ、セーブ破損、主要導線の進行不能 |
| `high` | 主要機能が利用不能だが限定的な回避策がある |
| `medium` | 一部機能・表示の問題 |
| `low` | 軽微な文言・見た目・操作感 |

### 7.2 Status

- `open`
- `fixed`
- `verified`
- `deferred`
- `duplicate`

Checklistの`release_blocking_defect_severities`に含まれるSeverityは、Statusが以下になるまでRelease Gateを通さない。

- `fixed`
- `verified`
- `duplicate`

`deferred`は未解決として扱う。重大問題を「既知問題」と記載するだけで公開承認することはできない。

## 8. 検証とSummary生成

```bash
python tools/steam_demo_qa.py validate \
  --report qa/runs/<run-id>/report.json
```

処理内容:

- Checklist ID / Version / SHA-256
- Build Manifestの存在・SHA-256
- Git SHA / Artifact / Version一致
- 実行環境必須項目
- Case欠落・重複・未知ID
- Status契約
- PassのNotes / Evidence
- Fail / BlockedのDefect関連付け
- Evidence Path
- Defect Severity / Status
- 公開判断

`SUMMARY.md`は同じRunディレクトリへ再生成される。

Exit Code:

| Code | Gate |
|---:|---|
| 0 | `pass` |
| 1 | JSON・契約・Manifest・Evidenceの検証エラー |
| 2 | `incomplete` |
| 3 | `fail` |

## 9. Run完了と公開判断

### 9.1 承認

すべてのRelease Blocking CaseがPassし、重大未解決Defectがない場合のみ承認できる。

```bash
python tools/steam_demo_qa.py finalize \
  --report qa/runs/<run-id>/report.json \
  --decision approved \
  --approver release-owner \
  --notes "Windows 11 x64の公開前主要導線を確認した。"
```

条件を満たさない承認はToolが拒否し、Reportも書き換えない。

### 9.2 却下

```bash
python tools/steam_demo_qa.py finalize \
  --report qa/runs/<run-id>/report.json \
  --decision rejected \
  --approver release-owner \
  --notes "FLOW-004のcritical不具合により公開を停止する。"
```

却下Runも調査記録として保存できる。

## 10. 複数Runの検証

```bash
python tools/steam_demo_qa.py validate-all --reports-root qa/runs
```

配下の全`report.json`を検証し、各`SUMMARY.md`を更新する。

1件でも`fail`があればExit Code 3、`fail`がなく`incomplete`があればExit Code 2となる。

## 11. GitHub Actions

`.github/workflows/steam-demo-qa-report.yml`は以下の変更時に実行する。

- Checklist
- QA Tool
- QA契約テスト
- QA RunのReport / Build Manifest
- Workflow自身

実行内容:

1. QA契約テスト
2. コミット済みQA Runがある場合は全Run検証

Runがまだ存在しない段階では契約テストのみ実行する。

## 12. 不具合報告

`.github/ISSUE_TEMPLATE/steam-demo-bug.yml`を使用する。

必須情報:

- Severity
- QA Case ID
- Artifact名
- Git SHA
- Manifest SHA-256
- OS / Architecture / Resolution / DPI
- 入力方式
- セーブ状態
- 前提状態
- 再現手順
- 期待結果 / 実際の結果
- 再現頻度

Case結果の`defect_ids`とGitHub Issueを一致させる。

## 13. Release Reviewで確認するもの

公開判断PRまたはRelease Issueには以下を添付する。

- Windows Build Workflow Run
- Artifact名とDigest
- QA Runの`SUMMARY.md`
- Open Defect一覧
- Release Gate結果
- 承認者

レビュー担当者は、Case表をすべて読み直す前に以下を確認する。

1. Release Gateが`PASS`
2. Git SHAが公開対象Commitと一致
3. `fail` / `blocked` / `pending`が0
4. Openのblocker / critical / highが0
5. Completed日時とApproverが存在
6. 主要証跡へアクセス可能

## 14. 禁止事項

- 実プレイせず全CaseをPassへ変更する
- 別Buildの証跡を流用する
- Manifestを書き換えてReportへ合わせる
- Release Blocking CaseをSkipする
- 重大Defectを削除してGateを通す
- Evidence PathとしてRunディレクトリ外のローカルファイルを参照する
- 個人情報・秘密情報・セーブ原本をコミットする
- ToolのGate失敗を手動の承認文だけで上書きする

## 15. 現時点の制約

- 実機QAは本PRでは実施していない
- パッド実機回帰はS-1の対象
- GUI自動操作は未対応
- クラッシュ収集SDKはS-3の対象
- 複数OS・複数GPUの必須マトリクスは未確定
- 性能計測値はM-4の最小範囲外
- 外部QA管理SaaSとは連携していない
