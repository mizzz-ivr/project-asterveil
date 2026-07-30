# Steam Store Readiness

## 1. 目的

本書は、Steamデモ公開に必要なストア素材、Steamworks設定、法務確認、審査、Build、QA、公開権限を一つの台帳で管理する運用を定義する。

対象は`docs/PRODUCTION_GAP_BACKLOG.md`のM-5「ストア公開最低素材タスク分解」である。

主な目的は以下。

- 公開直前に不足素材や未完了設定が判明する事故を防ぐ
- Steam公式要件とプロジェクト独自の公開条件を区別する
- 誰が、いつまでに、何を完了させるかを明確にする
- Store Review、Coming Soon、Build Review、Demo Releaseを別々に判定する
- 完了証跡とSteamworks上の承認履歴を後から追跡できるようにする

本台帳はSteamworksへの自動入力や公開操作を行わない。

## 2. 構成

```text
release/steam/
├─ store_readiness_v1.json
│  └─ Version付き公開準備項目定義
├─ store_readiness_status.json
│  └─ 公開計画、担当、進捗、証跡、承認状態
└─ STORE_READINESS_SUMMARY.md
   └─ CLIが生成するレビュー用要約

tools/
├─ steam_store_readiness_contract.py
├─ steam_store_readiness_gate.py
└─ steam_store_readiness.py
```

チェック項目定義と実際の進捗状態を分離する。

項目の意味や公式要件を変更する場合は、定義VersionまたはLedger IDを更新する。単なる進捗更新では定義を変更しない。

## 3. 要件区分

### official_required

Steam公式ドキュメント上、対象の公開工程で必須となる項目。

例:

- Store PresenceとProduct Buildのレビュー
- 必須Capsule、Library Asset、Icon
- Gameplay Screenshot
- Content Survey
- Coming Soon公開期間
- 公開権限

### official_recommended

Steam公式が品質または表示上推奨しているが、単独では必須審査項目として扱わないもの。

例:

- 先頭TrailerをGameplay中心にする
- 成人向け表現のないScreenshotを先に配置する
- 説明内画像へAlt Textを付ける

未完了の場合はGateのWarningとする。

### conditional

プロジェクト条件に応じて必須になるもの。

例:

- 有料製品の価格設定
- Early Access説明
- 複数言語のStore文言
- macOS Icon
- ゲーム内取引の確認
- 第三者素材のライセンス確認

条件がfalseの場合は`not_applicable`とする。条件が未確定の場合はGateをIncompleteとする。

### project_required

Steam公式の単一要件ではないが、Project Asterveilの安全な公開に必要な項目。

例:

- 全素材の権利台帳
- Beta Mode内部レビュー
- Windows候補BuildとArtifact Digest
- M-4 QA Gate承認
- 公開前の最終照合

## 4. Gate

### store_review

SteamへStore Presenceをレビュー提出できる状態を判定する。

主な対象:

- Store文言
- 対応OS、機能、入力、言語、システム要件
- Capsule、Library Asset、Icon、Screenshot、Trailer
- Content Survey
- Localization
- 権利確認
- 内部プレビュー

### coming_soon

Coming Soonページを公開できる状態を判定する。

主な対象:

- Store Presence承認
- Publish App Changes権限
- 公開対象素材
- Coming Soon公開操作と証跡

### build_review

Near-final Product Buildをレビュー提出できる状態を判定する。

主な対象:

- Store Presence承認
- Windows候補Build
- Store表記とBuildの一致
- M-4 QA Gate
- Content Survey

### demo_release

Steamデモを公開できる状態を判定する。

主な対象:

- Store Presence承認
- Product Build承認
- Coming Soon最低14日
- QA承認
- 権利確認
- 公開担当者と権限
- 最終照合

Gateの承認操作は、未完了項目やFailを上書きできない。

## 5. 担当ロール

個人名を定義ファイルへ埋め込まず、状態ファイルで責任ロールへ担当者を割り当てる。

```text
release_owner       公開計画、審査、最終判断
steamworks_admin    Steamworks権限、App設定
store_owner         Store文言、対応機能表記
art_owner           Capsule、Library Asset、Screenshot、Icon
trailer_owner       Trailer制作と登録
localization_owner  Store文言と素材Localization
legal_owner         契約、権利、Content Survey
build_owner         公開候補BuildとManifest
qa_owner            M-4 QA Runと重大Defect確認
pricing_owner       価格、地域価格、取引条件
```

担当者が未割当のBlocking項目はGateを通過しない。

## 6. 期限計算

状態ファイルの`target_release_date`を基準に期限を導出する。

```bash
python tools/steam_store_readiness.py set-plan \
  --release-date 2026-12-01 \
  --non-working-date 2026-11-23
```

期限Anchorは次の2種類。

```text
release      公開予定日
coming_soon  公開予定日の14日前
```

`calendar`は暦日で計算する。

`business`は土日と`non_working_dates`を除外する。日本の祝日を自動取得しないため、プロジェクト休日は明示的に登録する。

期限超過したBlocking項目はGateをFailにする。

公開予定日が未確定の場合、期限は未確定となりGateはIncompleteになる。仮の日付を事実として登録しない。

## 7. 条件の確定

```bash
python tools/steam_store_readiness.py set-condition \
  --condition paid_product \
  --value false
```

値:

```text
true     対象
false    対象外
unknown  未確定
```

条件をfalseにした場合、対応項目を`not_applicable`へ更新する。

初期状態では、無料デモ前提で明確に対象外の項目のみ`not_applicable`としている。

`requires_app_credit`と`third_party_assets`は事実確認が必要なため未確定としている。

## 8. 担当割当

```bash
python tools/steam_store_readiness.py assign-role \
  --role art_owner \
  --assignee mizzz-ivr
```

項目単位で例外的に担当を変える場合だけ`record --owner`を使用する。

## 9. 進捗と証跡

Status:

```text
not_started
in_progress
blocked
ready_for_review
done
not_applicable
```

項目を更新する例:

```bash
python tools/steam_store_readiness.py record \
  --item-id ASSET-004 \
  --status ready_for_review \
  --notes "Gameplay Screenshot 6枚を内部レビューへ提出" \
  --evidence "file|evidence/screenshots/contact-sheet.png|6枚の一覧"
```

Steamworks上で完了した項目:

```bash
python tools/steam_store_readiness.py record \
  --item-id REVIEW-002 \
  --status done \
  --evidence "steamworks|store-review-approval-2026-11-10|Valve承認記録"
```

Evidence形式:

```text
type|value|description
```

利用可能なtype:

```text
file
url
steamworks
github
commit
artifact
```

`file`は状態ファイルのディレクトリ内だけを参照できる。絶対Pathと`../`による外部参照は拒否する。

`done`かつ証跡必須の項目は、Evidenceなしでは保存・検証できない。

依存項目が完了していない項目を`done`にできない。

## 10. Milestone

Steamworks上の提出・承認・公開日時を記録する。

```bash
python tools/steam_store_readiness.py set-milestone \
  --milestone store_review_approved_at \
  --value 2026-11-10T15:00:00+09:00
```

削除する場合:

```bash
python tools/steam_store_readiness.py set-milestone \
  --milestone store_review_approved_at \
  --value clear
```

日時にはTimezoneを必須とする。

## 11. 検証と要約

```bash
python tools/steam_store_readiness.py validate \
  --definition release/steam/store_readiness_v1.json \
  --state release/steam/store_readiness_status.json \
  --summary release/steam/STORE_READINESS_SUMMARY.md
```

検証内容:

- JSON契約
- ID重複
- 未知Role、Gate、Status、Condition、Source
- 依存循環
- 条件付き項目のN/A整合
- 担当と期限
- Done項目の証跡
- Evidence Path Traversal
- 依存項目の完了
- Milestone日時
- Gate承認Metadata

要約には、Gate結果、担当、Status、期限、公式参照元を出力する。

## 12. Gate確認

```bash
python tools/steam_store_readiness.py gate \
  --gate demo_release
```

Exit Code:

```text
0  Pass
1  JSON・契約・証跡エラー
2  Incomplete
3  Fail
```

初期状態は公開日、責任者、素材、審査、QA承認が未確定であるため、`demo_release`は必ずIncompleteになる。

## 13. Gate承認

```bash
python tools/steam_store_readiness.py approve-gate \
  --gate store_review \
  --approver release-owner \
  --notes "内部レビュー完了"
```

以下が残っている場合は承認を拒否する。

- Blocking項目の未完了
- Blocked項目
- 期限超過
- 条件未確定
- 担当未割当
- 必要Milestone未記録
- 公式要件参照元の契約違反

承認者の自由記述でGate判定を上書きしない。

## 14. 公式要件の鮮度

`verified_on`から`freshness_days`を超えた場合、GateにWarningを出す。

Steamworksの要件は変更される可能性がある。Store提出前とBuild提出前に、定義内の公式URLを再確認する。

公式要件を更新する場合:

1. Steamworks公式ドキュメントを確認する
2. `verified_on`を更新する
3. 変更された項目、画像サイズ、期間、権限を修正する
4. テストを更新する
5. 既存状態への影響をレビューする

## 15. 初期状態について

初期状態では次を確定していない。

- Steam AppID
- 正式公開予定日
- 実担当者
- 素材完成
- Content Survey回答
- Valve審査結果
- QA承認
- 公開操作

そのため、本タスク完了は「公開準備を管理・判定できる基盤が完成した」という意味であり、Steamデモが公開可能になったことを意味しない。

## 16. スコープ外

- Steamworksポータルへの自動入力
- SteamPipe Upload
- 実際の画像・Trailer制作
- 法律相談、税務判断、年齢レーティング代行
- AppID、価格、正式公開日の決定
- Store PresenceやBuildの提出・公開操作
- 実機QAの代行

権利、契約、税務、レーティングに関する最終判断は、必要に応じて専門家またはSteam Supportへ確認する。
