# 章コンテンツパック統合・Promotion Plan

## 1. 目的

`tools/chapter_content_pack.py`で作成した章パックを、既存の`data/master/*.sample.json`へ安全に統合するための事前検証手順を定義する。

Promotion Plan生成工程ではMaster Dataを更新しない。出力するのはレビュー用のPromotion Plan、Summary、ローカライズ候補である。

正式Masterへ追加する場合は、Planとは別責務の追加専用Patch Bundleを生成し、Catalog／Master／候補ファイルを再検証したうえで明示適用する。詳細は[章コンテンツ昇格Patch Bundle](./CHAPTER_CONTENT_PROMOTION_BUNDLE.md)を参照する。

## 2. 責務境界

### Chapter Content Pack

- 章パック内部のID、参照、Quest依存、Objective順序を検証する
- Kind別Master候補を生成する
- 旧版章パックとの差分を出力する

### Chapter Content Promotion Plan

- 既存Master Catalogを読み込む
- 章パックから既存Masterへの参照を解決する
- IDを`add / unchanged / conflict`へ分類する
- 既存Questを含む依存循環を検出する
- Promotion Planとローカライズ候補を生成する
- Master Dataは変更しない

### Chapter Content Promotion Bundle

- `ready_for_review`のPlanから`add`対象だけを候補Masterへ追加する
- Before／After Hashとレビュー用Diffを生成する
- Bundle作成後のCatalog／Master変更を検出する
- 明示指定がある場合だけ正式Masterへ書き込む
- 既存Entityの更新・削除・並び替えは行わない

## 3. Master Catalog

定義ファイル:

```text
content/master_catalog_v1.json
```

各Collectionは以下を持つ。

- `path`: Project Rootからの相対Path
- `id_fields`: IDとして探索するField
- `promotable`: 章パックから追加可能か
- `optional`: ファイルが存在しない場合に空Collectionとして扱うか

`quests`、`events`、`encounters`、`locations`、`conversations`はPromotion対象である。

`npcs`、`enemies`、`items`は参照専用であり、章パックから追加しない。

## 4. 検証対象

### 4.1 外部参照

以下は同一章パック内または既存Master内に存在する必要がある。

- Quest prerequisites → Quest
- Quest encounter → Encounter
- Quest target location → Location
- Quest reporting NPC → NPC
- Objective target enemy → Enemy
- Objective / Reward item → Item
- Encounter enemy → Enemy
- Location accessible_from → Location
- Location available/default encounter → Encounter
- Event next_event → Event
- Event accept/complete quest → Quest
- Event start battle → Encounter
- Conversation npc → NPC
- Conversation Choice Effect → Quest / Encounter

### 4.2 Quest依存循環

既存Questと新規Questを1つのGraphとして検証する。

新規Questだけでは循環しなくても、既存Questとの組み合わせで循環する場合はPromotionを拒否する。

### 4.3 ID分類

| 分類 | 条件 | 扱い |
|---|---|---|
| `add` | 既存Masterに同一IDがない | Bundleレビュー対象 |
| `unchanged` | IDと内容が完全一致 | Master更新不要 |
| `conflict` | IDは同じだが内容が異なる | Promotionを拒否 |

既存IDの内容変更を章パック追加と同時に行わない。変更が必要な場合は、影響範囲とSave互換性を確認する専用PRへ分離する。

## 5. 実行方法

### 検証

```bash
python tools/chapter_content_promotion.py \
  --catalog content/master_catalog_v1.json \
  --project-root . \
  validate content/packs/ch02/pack.json
```

### Promotion Plan生成

```bash
python tools/chapter_content_promotion.py \
  --catalog content/master_catalog_v1.json \
  --project-root . \
  plan content/packs/ch02/pack.json \
  --output tmp/content-promotion/ch02
```

生成物:

```text
tmp/content-promotion/ch02/
├─ PROMOTION_PLAN.json
├─ PROMOTION_SUMMARY.md
└─ localization.ja.candidates.json
```

### Patch Bundle生成

```bash
python tools/chapter_content_promotion.py \
  --catalog content/master_catalog_v1.json \
  --project-root . \
  bundle content/packs/ch02/pack.json \
  --output tmp/content-promotion-bundle/ch02
```

PlanとBundleは別ディレクトリへ出力される。候補Master、Unified Diff、Manifestをレビューし、Dry-run後に必要な場合だけ明示適用する。

### Strict Mode

```bash
python tools/chapter_content_promotion.py \
  --catalog content/master_catalog_v1.json \
  --project-root . \
  validate content/packs/ch02/pack.json \
  --strict
```

Exit Code:

| Code | 意味 |
|---:|---|
| 0 | Promotion Reviewへ進める／Bundle検証成功 |
| 1 | JSON・Catalog・Pack・Bundle契約エラー |
| 2 | Strict ModeでWarningあり |
| 3 | 未解決参照またはID競合でBlocked |

## 6. Promotion Plan

`PROMOTION_PLAN.json`には以下を記録する。

- Pack SHA-256
- Master Catalog SHA-256
- `ready_for_review / blocked`
- Kindごとの`add / unchanged / conflict`
- 追加先Master Path
- 解決した参照一覧
- 未解決参照
- ID競合
- ローカライズ候補
- Warning
- `apply_supported: false`

`apply_supported: false`は、Promotion Planそのものを直接適用しないことを示す。正式Masterへの追加は、Planから生成したPatch Bundleを別途検証して行う。

Catalog SHA-256には各Master IDとEntity内容Hashを含める。

Plan作成後にMasterが変更された場合はCatalog SHAが変わるため、古いPlanやBundleをそのまま利用しない。

## 7. ローカライズ候補

章パック内の以下のinline文言から候補Keyを生成する。

- title
- description
- name
- line
- text
- dialogue_line

例:

```text
content.quest.ch02.first_step.title
content.location.ch02.forest.description
```

これは翻訳済みを意味しない。候補JSONをレビューし、正式なLocalization運用へ移すまでWarningとして扱う。

## 8. 正式Masterへの反映手順

1. 章パックを検証する
2. Promotion Planを生成する
3. `unresolved_references`と`conflicts`が空であることを確認する
4. Patch Bundleを生成する
5. `BUNDLE_SUMMARY.md`、Candidate、Diffをレビューする
6. `verify-bundle`を実行する
7. `apply-bundle`を`--write`なしで実行しDry-runする
8. `source_catalog_sha256`を確認値として`--write`付きで明示適用する
9. `git diff -- data/master`を確認する
10. 各Repositoryの読込テストとPlayable回帰を実行する
11. Master Data変更を専用PRとしてレビューする

PlanからMasterへ直接書き込む機能は提供しない。

## 9. テスト観点

### 正常系

- 既存Quest、Encounter、Location、NPC、Enemy、Itemを参照できる
- 新規IDが`add`になる
- 同一内容が`unchanged`になる
- PlanとSummaryを生成できる
- Patch Bundleと候補Masterを生成できる
- Dry-runではMasterが変わらない

### 異常系

- 未知のNPC、Enemy、Item
- Event／Conversation Actionの未知Quest / Encounter
- 既存IDと内容差分
- Catalog重複ID
- 必須Masterファイル欠落
- 既存Questと新規Questの依存循環
- Bundle生成後のCatalog／Master変更
- Candidate／Diff改変
- 既存Entity変更・削除・並び替え

### 非破壊性

- `validate`／`plan`／`bundle`／`verify-bundle`では`data/master`の内容が変わらない
- `apply-bundle`も`--write`なしではMasterを変更しない
- 参照専用Collectionへ追加しない
- 既存Entityを自動更新・削除しない

## 10. 未対応

- 既存Master Entityの更新・削除
- ID競合の自動解決
- 翻訳文の生成・承認・自動反映
- 画像・音声Assetの整合確認・コピー
- Save Migrationの自動生成
- Git commit／PRの自動作成
