# Steamデモ クエストボード／移動画面契約

## 1. 目的

Steamデモで最初に利用するクエストボードと移動画面を、CLI固有の選択処理から分離し、将来のGUI・キーボード・ゲームパッド・ポインター操作から共通利用できる状態にする。

PR #77でトップレベル操作は共有コントローラーへ分離されたが、`quest_board` と `move` は追加選択が必要なため、CLI固有の `_run_*_flow` に残っていた。本変更では、この2画面に限定してViewModelとサブ画面コントローラーを追加する。

## 2. 責務分離

### `QuestBoardScreenPresenter`

- `PlayableSliceApplication.quest_board_lines()` の構造化出力を読み取る
- クエストID、タイトル、状態、進捗、受注可否をViewModelへ変換する
- 状態値を画面表示用の日本語ラベルへ変換する
- 不正な構造化出力を黙って無視せず `ValueError` として検知する

### `QuestBoardScreenController`

- 選択位置を保持する
- 上下、決定、戻る、ガイド表示を処理する
- 受注可能なクエストだけを `accept_quest()` へ渡す
- ロック済み、進行中、未知クエストを拒否結果として返す
- 操作後にPresenterからViewModelを再構築する

### `TravelScreenPresenter`

- `PlayableSliceApplication.travel_options_lines()` の構造化出力を読み取る
- 現在地と移動可能な行き先をViewModelへ変換する
- ロケーションID、名称、種別を描画方式に依存しない形式で提供する
- 不正な移動候補出力を検知する

### `TravelScreenController`

- 選択位置を保持する
- 上下、決定、戻る、ガイド表示を処理する
- 現在表示されている移動先だけを `travel_to()` へ渡す
- 未知または現在移動不能なIDを拒否する
- 移動後の現在地と行き先を再構築する

### CLIアダプター

- 一覧を端末へ表示する
- 数値選択を受け取る
- 選択結果をサブ画面コントローラーへ渡す
- クエスト／移動のルール判定を持たない

## 3. 構造化出力契約

既存のPlayable SliceはCLI表示と自動テストで利用する構造化ログを公開している。本変更では、ゲーム内部のprivate serviceへPresentation層から直接依存せず、この公開契約をRead Modelの入力として利用する。

### クエストボード

```text
quest_board:max_active=<number>
quest_board_entry:<quest_id>:<title>:status=<status>:can_accept=<bool>:progress=<dict>
```

### 移動

```text
current_location:<location_id>:<name>
travel_option:<location_id>:<name>:type=<location_type>
```

契約に一致しない対象行は、画面の誤表示や誤操作を防ぐため例外として検知する。未知の補助ログは無視できるが、`quest_board_entry:` または `travel_option:` で始まる不正形式は無視しない。

## 4. クエスト状態表示

| 状態 | 表示 |
|---|---|
| `locked` | 未解放 |
| `available` | 受注可能 |
| `in_progress` | 進行中 |
| `ready_to_complete` | 報告可能 |
| `completed` | 完了 |
| `repost_waiting` | 再掲待ち |
| `reacceptable` | 再受注可能 |

`can_accept=True` の項目だけが決定可能である。表示一覧からロック済み項目を消さず、状態は確認できるが誤受注はしない。

## 5. 画面遷移

```text
SteamDemoActionController
  ├─ FLOW_REQUIRED: quest_board
  │    └─ QuestBoardScreenController
  │         └─ accept_quest
  └─ FLOW_REQUIRED: move
       └─ TravelScreenController
            └─ travel_to
```

操作後はメインメニューへ戻り、Steamデモの進行ViewModelが再構築される。

## 6. テスト観点

- 受注可能・未解放・進行中の状態表示
- 進捗表示
- 正常な受注
- 重複受注の拒否
- ロック済み／未知クエストの拒否
- 現在地と移動先の表示
- 正常な移動
- 移動後の行き先再構築
- 未知移動先の拒否
- 戻る／ガイド表示
- 不正な構造化出力の検知
- CLIアダプター経由の受注と移動
- 既存機能の全体回帰

## 7. 実行方法

```bash
python -m unittest tests.test_quest_travel_screen -v
```

```bash
python -m unittest
```

```bash
python -m game.app.cli.run_steam_demo
```

## 8. スコープ外

- クエスト詳細画面
- マップ描画
- NPC会話、ショップ、クラフト等のサブ画面移行
- GUIフレームワーク導入
- アニメーション、サウンド、画面演出
- ゲームパッド実機／Steam Input API接続

## 9. 次の拡張

1. NPC会話とフィールドイベントを同じ画面契約へ移す
2. クエスト詳細用ViewModelを追加する
3. 移動画面へ目的地の説明と推奨目標を追加する
4. GUIルーターから `QuestBoardScreenController` と `TravelScreenController` を呼び出す
