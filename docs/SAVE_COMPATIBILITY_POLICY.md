# セーブ互換運用ポリシー

## 1. 目的

本書は、Project AsterveilのセーブデータVersionを更新する際に、既存プレイヤーの進行データを破損・消失させないための互換方針と移行手順を定義する。

対象は`game/save`のJSONセーブ契約であり、`docs/PRODUCTION_GAP_BACKLOG.md`のM-2「セーブ互換運用ルールと移行テスト」に対応する。

## 2. 現在の契約

- 現在Version: `save_version = 1`
- Version定義: `game.save.domain.entities.SAVE_VERSION`
- 現行Data Model: `SaveData`
- 永続化実装: `JsonFileSaveRepository`
- 移行実装: `SaveMigrationService`

セーブpayloadはトップレベルに整数の`save_version`を必須で持つ。

## 3. 互換性の基本方針

### 3.1 同一Version

現在Versionと一致するpayloadは、Migration Stepを適用せず`SaveData.from_dict()`で検証する。

### 3.2 過去Version

過去Versionは、登録済みMigration Stepを1段ずつ適用して現在Versionへ上げる。

```text
v0
  ↓ save_v0_to_v1
v1
```

1つのStepは必ず`N → N+1`だけを担当する。

### 3.3 将来Version

現在の実行バイナリより新しいVersionは読み込まない。

```text
future_save_version_not_supported
```

古いクライアントから新しいセーブを開き、未知フィールドを欠落させて上書きする事故を防ぐためである。

### 3.4 Migration経路がないVersion

現在Versionより古くても、連続したMigration Stepが存在しない場合は読み込まない。

```text
save_migration_step_missing
```

推測や部分補完によるサイレント破損を避ける。

## 4. v0 → v1 Migration

v0は`save_version: 0`を明示的に持つ旧形式とする。Versionフィールド自体がないpayloadは、Version不明として拒否する。

v1移行時は以下を決定的な既定値で補完する。

### Player Profile

- `last_saved_at`: `1970-01-01T00:00:00+00:00`

現在時刻は使用しない。Migrationを複数回検証しても同じ結果にするためである。

### Party Member

- `current_exp`: `0`
- `next_level_exp`: `100`
- `max_hp`: `current_hp`
- `max_sp`: `current_sp`
- `atk`: `1`
- `defense`: `1`
- `spd`: `1`
- `equipped`: `{}`
- `unlocked_skill_ids`: `[]`
- `active_effects`: `[]`

### Quest

- `objective_item_progress`: `[]`
- `reward_claimed`: `false`
- `repeat_ready`: `false`

### Top Level

- `progression`: `{}`
- `inventory_state`: `{}`
- `meta`: `{}`

Migration後は必ず`SaveData.from_dict()`を実行し、現行契約として完全に読み込めることを確認する。

## 5. 読み込み時の挙動

通常のゲーム開始・Continueでは、旧セーブをメモリ上でのみ移行する。

```text
JSON読込
  ↓
SaveMigrationService.migrate
  ↓
SaveData検証
  ↓
ゲーム状態へ復元
```

この経路では元ファイルを書き換えない。

理由:

- Continueだけでユーザーファイルを暗黙更新しない
- 移行後のゲーム起動中に別障害が起きても原本を保持する
- 明示移行と通常読込の責務を分ける

次回通常セーブ時には現行Versionで保存される。

## 6. 明示的なファイル移行

### Dry Run

```bash
python -m game.save.cli.migrate_save path/to/save.json --dry-run
```

確認項目:

- 元Version
- 現在Version
- Migrationの要否
- 適用予定Step
- 現行`SaveData`として検証可能か

Dry Runはファイルを変更しない。

### Migration実行

```bash
python -m game.save.cli.migrate_save path/to/save.json
```

バックアップ先を指定する場合:

```bash
python -m game.save.cli.migrate_save path/to/save.json \
  --backup-path path/to/save.before-migration.json
```

既定バックアップ名:

```text
<save-file>.pre-v<current>.from-v<original>.bak
```

例:

```text
slot_01.json.pre-v1.from-v0.bak
```

## 7. ファイル更新の安全性

明示移行は以下の順序で行う。

1. 元JSONを読み込む
2. メモリ上で全Migrationを適用する
3. `SaveData.from_dict()`で完全検証する
4. 更新前JSONを排他的にバックアップする
5. 移行済みJSONを同一ディレクトリの一時ファイルへ書き込む
6. Flushと`fsync`を行う
7. `os.replace()`で元ファイルへ原子的に置換する

既存バックアップは上書きしない。

書換え失敗時は、今回新規作成したバックアップを削除し、元ファイルを変更前の状態に保つ。

## 8. Version更新時の実装ルール

`SAVE_VERSION`を上げるPRでは、同一PRまたは先行PRで以下を必須とする。

1. `SaveMigrationStep`を追加する
2. Step名を`save_vN_to_vN+1`形式にする
3. 入力payloadを変更しない
4. 実行時刻・乱数・外部APIに依存しない
5. Migration後に現行`SaveData`で検証する
6. 旧Version Fixtureを追加する
7. Continue統合テストを追加する
8. Dry Runと明示移行を確認する
9. 互換ポリシーを更新する
10. リリースノートへセーブVersion変更を記載する

## 9. 禁止事項

- Version不明payloadを推測して読み込む
- 将来Versionを現在Versionへダウングレードする
- Migration中にゲームルールを再実行する
- Migrationで現在時刻や乱数を設定する
- 通常`load()`で自動的に元ファイルを書き換える
- バックアップを上書きする
- 検証前に元ファイルを更新する
- 複数Versionを1つのStepで飛び越える

## 10. テスト観点

### 正常系

- v1をStepなしで読み込める
- v0をv1へ移行できる
- Continueがv0セーブから成功する
- 明示移行後のファイルを再読込できる
- 現行Versionのファイルでは書換え・バックアップを行わない

### 異常系

- 将来Versionを拒否する
- 未登録Migration経路を拒否する
- Versionフィールド欠落を拒否する
- 不正JSONを拒否する
- 現行契約に不足する必須フィールドを拒否する
- 既存バックアップを上書きしない
- 原子的更新失敗時に元ファイルを維持する

### 境界値

- Version `0`
- Version `SAVE_VERSION`
- Version `SAVE_VERSION + 1`
- 空Party
- 空Quest
- optionalフィールドがすべてないv0

## 11. 影響範囲

本対応はセーブJSONの読込・移行・保存運用に限定する。

以下は変更しない。

- QuestやBattleなどのゲームルール
- Playable Sliceの状態意味
- 現在のv1出力形式
- マスターデータ
- Steamデモ画面契約
- GUI／CLIの操作仕様

## 12. 次の課題

M-2完了後は、M-3「配布／ビルド手順の最小確立」を進める。

候補:

- Windows向け成果物生成
- バージョン情報の埋め込み
- ビルド成果物のSmoke Test
- GitHub Actions Artifact
- Steam提出候補チェックリスト
