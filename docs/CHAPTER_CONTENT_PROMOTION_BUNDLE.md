# 章コンテンツ昇格Patch Bundle

## 1. 目的

`Promotion Plan`で`ready_for_review`となった章コンテンツを、レビュー可能な候補MasterとDiffへ変換し、安全条件を満たす場合だけ正式Masterへ追加する。

本機能は追加専用である。既存Entityの更新・削除・並び替え、ID競合解決、Save Migrationは扱わない。

## 2. 責務境界

### Promotion Plan

- 章パックと既存Masterの契約・参照を検証する
- `add / unchanged / conflict`を分類する
- 未解決参照と競合を記録する
- Masterを書き換えない

### Promotion Patch Bundle

- `add`対象だけを候補Masterへ追加する
- Before／After Hashと対象Pathを固定する
- レビュー用Unified Diffを生成する
- 適用前に現在のCatalogとBundleを再検証する
- 明示指定がある場合だけ書き込む
- 書込み途中で失敗した場合は元データへ戻す

## 3. Bundle生成条件

次の条件をすべて満たす必要がある。

- Promotion Statusが`ready_for_review`
- `unresolved_references`が空
- `conflicts`が空
- Promotion対象Collectionである
- `add`対象が1件以上ある
- 追加IDが既存Masterに存在しない

`unchanged`は候補Masterへ重複追加しない。`conflict`はBundle生成を拒否する。

## 4. Bundle生成

```bash
python tools/chapter_content_promotion.py \
  --catalog content/master_catalog_v1.json \
  --project-root . \
  bundle content/packs/ch02/pack.json \
  --output tmp/content-promotion-bundle/ch02
```

出力例:

```text
tmp/content-promotion-bundle/ch02/
├─ plan/
│  ├─ PROMOTION_PLAN.json
│  ├─ PROMOTION_SUMMARY.md
│  └─ localization.ja.candidates.json
└─ bundle/
   ├─ BUNDLE_MANIFEST.json
   ├─ BUNDLE_SUMMARY.md
   ├─ candidate/
   │  └─ data/master/
   │     ├─ quests.sample.json
   │     └─ locations.sample.json
   └─ diff/
      ├─ quests.patch
      └─ locations.patch
```

出力先の`bundle`ディレクトリが空でない場合は生成しない。古い候補ファイルが混在することを防ぐためである。

## 5. Manifest契約

`BUNDLE_MANIFEST.json`には以下を記録する。

- `schema_version`
- `bundle_type`
- `chapter_id`
- `pack_sha256`
- `source_catalog_sha256`
- `expected_catalog_sha256`
- `mode: add_only`
- 対象Collection
- 正式Masterの相対Path
- Candidate／Diffの相対Path
- MasterのBefore SHA-256
- CandidateのAfter SHA-256
- Diff SHA-256
- 既存件数・候補件数
- 追加ID一覧
- 書込み時に必要なCatalog確認値

`source_catalog_sha256`はBundle生成時点のCatalogである。`expected_catalog_sha256`は候補を追加した後に期待するCatalogである。

## 6. Candidate契約

Candidate JSONは正式Masterの配列を基準に、次の構造を必須とする。

1. 既存Entityを同じ順序・同じ内容で保持する
2. 新規Entityを末尾へ追加する
3. Manifestの`added_ids`順と末尾EntityのID順を一致させる
4. ID重複を作らない
5. 既存IDを追加対象へ含めない

ManifestのAfter SHAを書き換えただけでは、既存Entityの変更・削除・並び替えを通過できない。

## 7. Bundle検証

```bash
python tools/chapter_content_promotion.py \
  --catalog content/master_catalog_v1.json \
  --project-root . \
  verify-bundle tmp/content-promotion-bundle/ch02/bundle
```

次を検証する。

- Bundle Schema／Type
- 現在のCatalog SHA
- 対象CollectionとMaster Path
- MasterのBefore SHA
- Candidate／Diff SHA
- Candidateの追加専用構造
- 既存Entity保持
- ID重複
- 追加ID一覧
- 適用後に期待するCatalog SHA

いずれかが一致しない場合、Bundleを作り直す。

## 8. Dry-run

Manifestの`source_catalog_sha256`を確認値として指定する。

```bash
python tools/chapter_content_promotion.py \
  --catalog content/master_catalog_v1.json \
  --project-root . \
  apply-bundle tmp/content-promotion-bundle/ch02/bundle \
  --confirm-catalog-sha <source_catalog_sha256>
```

`--write`がない場合は検証だけを行い、`data/master`を変更しない。

Dry-run結果:

```json
{
  "status": "verified",
  "written": false,
  "source_catalog_sha256": "...",
  "expected_catalog_sha256": "...",
  "file_count": 2,
  "added_entity_count": 3
}
```

## 9. 明示適用

CandidateとDiffをレビューし、Dry-runが成功した後だけ実行する。

```bash
python tools/chapter_content_promotion.py \
  --catalog content/master_catalog_v1.json \
  --project-root . \
  apply-bundle tmp/content-promotion-bundle/ch02/bundle \
  --confirm-catalog-sha <source_catalog_sha256> \
  --write
```

書込み条件:

- `--write`が指定されている
- `--confirm-catalog-sha`がManifestと一致する
- 現在のCatalogがBundle作成時点と一致する
- 全MasterのBefore SHAが一致する
- Candidate／Diffが改変されていない
- 全Candidateが追加専用契約を満たす

全対象ファイルを検証してから一時ファイルへ書き出し、同一ディレクトリ内で置換する。

適用後にCatalogを再読込し、`expected_catalog_sha256`と一致することを確認する。

## 10. 失敗時の挙動

### 書込み前の失敗

Masterを変更しない。

例:

- Catalogが更新されている
- MasterのBefore SHAが変わっている
- Candidate／Diffが改変されている
- 既存Entityが変更されている
- 確認Catalog SHAが一致しない

### 書込み途中の失敗

Bundle検証時に保持した元Bytesを使って、全対象Masterを復元する。

ロールバック自体が失敗した場合は、`promotion_bundle_apply_and_rollback_failed`として停止する。この場合はGit差分とManifestのBefore SHAを使って手動復旧する。

## 11. 推奨レビュー手順

1. Promotion Planの`status`を確認する
2. `unresolved_references`と`conflicts`が空であることを確認する
3. `BUNDLE_SUMMARY.md`を確認する
4. CollectionごとのDiffを確認する
5. Candidateで既存Entityが保持されていることを確認する
6. Dry-runを実行する
7. `git status`がCleanであることを確認する
8. `--write`付きで適用する
9. `git diff -- data/master`を確認する
10. Repository読込テストとPlayable回帰を実行する
11. Master変更だけを明確にしたPRを作成する

## 12. テスト観点

### 正常系

- 複数Collectionの候補とDiffを生成できる
- Dry-runでMasterが変わらない
- 新規Entityだけを末尾追加できる
- 適用後Catalog SHAが期待値と一致する

### 異常系

- Blocked Plan
- 追加対象なし
- Catalog更新
- Master更新
- Candidate改変
- Diff改変
- 既存Entity変更・削除・並び替え
- ID Alias不一致・重複
- Catalog確認値不一致
- 書込み途中の失敗

### 既存機能への影響

- `validate`と`plan`の既存挙動を維持する
- `--write`なしではMasterを変更しない
- Runtime、Domain、Save契約を変更しない

## 13. スコープ外

- 既存Entityの更新・削除
- ID競合の自動解決
- Localization候補の自動反映
- 画像・音声Assetのコピー
- Save Migration
- Git commit／PRの自動作成
- 複数Repositoryへの分散適用
