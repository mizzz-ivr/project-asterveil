# 章コンテンツパック統合・Promotion Plan

## 1. 目的

`tools/chapter_content_pack.py`で作成した章パックを、既存の`data/master/*.sample.json`へ安全に統合するための事前検証手順を定義する。

この工程ではMaster Dataを更新しない。出力するのはレビュー用のPromotion Plan、Summary、ローカライズ候補のみである。

## 2. 責務境界

### Chapter Content Pack

- 章パック内部のID、参照、Quest依存、Objective順序を検証する
- Kind別Master候補を生成する
- 旧版章パックとの差分を出力する

### Chapter Content Promotion

- 既存Master Catalogを読み込む
- 章パックから既存Masterへの参照を解決する
- IDを`add / unchanged / conflict`へ分類する
- 既存Questを含む依存循環を検出する
- Promotion Planとローカライズ候補を生成する
- Master Dataは変更しない

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

### 4.2 Quest依存循環

既存Questと新規Questを1つのGraphとして検証する。

新規Questだけでは循環しなくても、既存Questとの組み合わせで循環する場合はPromotionを拒否する。

### 4.3 ID分類

| 分類 | 条件 | 扱い |
|---|---|---|
| `add` | 既存Masterに同一IDがない | レビュー対象 |
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
| 0 | Promotion Reviewへ進める |
| 1 | JSON・Catalog・Pack契約エラー |
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

Catalog SHA-256には各Master IDとEntity内容Hashを含める。

Plan作成後にMasterが変更された場合はCatalog SHAが変わるため、古いPlanをそのまま利用しない。

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
4. Catalog SHAが最新`main`と一致することを確認する
5. `add`だけを対象に、別PRでMaster Dataへ反映する
6. 各Repositoryの読込テストとPlayable回帰を実行する
7. Objectiveや既存IDを変更する場合はSave Migration要否を判断する

Promotion ToolからMaster Dataへ自動書込みは行わない。

## 9. テスト観点

### 正常系

- 既存Quest、Encounter、Location、NPC、Enemy、Itemを参照できる
- 新規IDが`add`になる
- 同一内容が`unchanged`になる
- PlanとSummaryを生成できる

### 異常系

- 未知のNPC、Enemy、Item
- Event Actionの未知Quest / Encounter
- 既存IDと内容差分
- Catalog重複ID
- 必須Masterファイル欠落
- 既存Questと新規Questの依存循環

### 非破壊性

- 検証前後で`data/master`の内容が変わらない
- Promotion Planに自動適用機能がない
- 参照専用Collectionへ追加しない

## 10. 未対応

- Promotion Planの自動適用
- 翻訳文の生成・承認
- 画像・音声Assetの整合確認
- Save Migrationの自動生成
- Master Entity単位の専用変更Workflow
