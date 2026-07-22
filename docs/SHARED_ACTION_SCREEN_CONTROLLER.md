# Steamデモ 共有アクション／画面状態シェル

## 1. 目的

Steamデモのトップレベル操作をCLI固有処理から分離し、将来のGUI、キーボード、ゲームパッド、マウス、タッチ入力から同じ操作契約を利用できるようにする。

PR #73で入力アクションとメニューViewModelを追加したが、CLIではアクションIDごとに `_run_*_flow` を直接呼び分けていた。本変更では、ゲーム操作の分類と画面状態更新をプレゼンテーション層へ集約し、CLIは入出力アダプターとして扱う。

## 2. 責務分離

### `game/app/presentation/action_controller.py`

- トップレベルのアクションIDを受け取る
- 即時実行、サブ画面要求、終了要求、拒否へ分類する
- `PlayableSliceApplication` と `SteamDemoApplication` の公開操作だけを呼ぶ
- CLIの `input()`、`print()`、`_run_*_flow` は呼ばない

### `game/app/presentation/screen_controller.py`

- 意味入力を `MenuNavigationService` へ渡す
- 選択位置を画面セッション中だけ保持する
- 決定されたアクションを `SteamDemoActionController` へ渡す
- 操作後に `SteamDemoMenuPresenter` からViewModelを再構築する
- ゲーム進行やセーブ状態を重複保持しない

### `game/app/cli/run_steam_demo.py`

- 標準入力と標準出力を担当する
- `FLOW_REQUIRED` を既存 `_run_*_flow` へ変換する
- 既存の数値選択UIを維持する
- ゲーム操作の分類ロジックを持たない

## 3. アクション実行結果

`ActionDispatchResult` は次の分類を返す。

| Kind | 用途 |
|---|---|
| `EXECUTED` | 追加選択なしで処理が完了した |
| `FLOW_REQUIRED` | アイテム選択、移動先選択などのサブ画面が必要 |
| `EXIT_REQUESTED` | 現在のゲーム画面を終了する要求 |
| `REJECTED` | 未知、利用不可、ゲーム未開始などで実行できない |

結果には、対象アクションID、ログ、サブ画面ID、拒否理由を必要に応じて含める。

## 4. サブ画面ID

現時点では以下を定義する。

- `use_item`
- `equip`
- `shop`
- `upgrade_equipment`
- `salvage_equipment`
- `craft`
- `inn`
- `quest_board`
- `move`
- `talk_npc`
- `gather`
- `open_treasure`
- `field_events`

これらはCLI関数名ではなく、画面ルーターが利用する安定した識別子とする。

## 5. 即時実行アクション

以下のように追加選択を必要としない操作は共有コントローラー内で実行する。

- 現在のデモガイド表示
- 工房ガイド確認
- ステータス、所持品、現在地、クエスト一覧などの参照
- 討伐、報告など利用可能な直接操作
- セーブ
- ロード

`save` はSteamデモのチェックポイント管理を維持するため、`SteamDemoApplication.save_checkpoint()` を使用する。

## 6. 画面状態シェル

`SteamDemoScreenController` は次の入力経路を提供する。

### 意味入力

```python
interaction = screen.handle_input(MenuInputAction.MOVE_DOWN)
interaction = screen.handle_input(MenuInputAction.CONFIRM)
```

キーボードやゲームパッドの物理入力は、既存 `InputBindingProfile` で意味入力へ変換してから渡す。

### ポインター／タッチ入力

```python
interaction = screen.activate_action("quest_board")
```

GUIのボタン、リスト項目、タッチ操作は、表示中メニューに存在する有効なアクションだけを起動できる。

### 戻り値

- 更新後の `SteamDemoMenuViewModel`
- `ActionDispatchResult`
- 戻る要求の有無

描画層は戻り値だけを参照し、ゲームオブジェクトを直接更新しない。

## 7. CLIとの接続

CLIは `FLOW_REQUIRED` の `flow_id` を既存の選択フローへ変換する。

```text
共有コントローラー
  └─ FLOW_REQUIRED: quest_board
       └─ CLIアダプター
            └─ _run_quest_board_flow(app)
```

将来GUIを追加する場合は、同じ `quest_board` をGUIのクエストボード画面へルーティングする。

## 8. エラー処理

- 空アクションIDは `REJECTED / empty_action_id`
- 表示中または利用可能な操作にないアクションは `REJECTED / action_not_available`
- ゲーム未開始などApplication層の拒否は `REJECTED / application_rejected`
- ポインター入力で表示中メニューにない操作は `REJECTED / menu_item_not_available`
- 未知アクションでプロセスを終了させない

## 9. テスト観点

- 即時実行アクション
- サブ画面要求
- 終了要求
- 未知・空アクション
- ゲーム未開始
- 意味入力による選択移動と決定
- ガイド表示
- 戻る要求
- ポインター形式の直接起動
- CLIサブフローアダプター
- 既存Steamデモの回帰

## 10. 実行方法

```bash
python -m unittest tests.test_shared_action_screen_controller -v
```

```bash
python -m unittest
```

```bash
python -m game.app.cli.run_steam_demo
```

## 11. スコープ外

- GUIフレームワークの採用
- サブ画面の描画実装
- ゲームパッド実機イベント
- Steam Input API
- キーコンフィグ保存
- 既存ゲームロジックの再設計

## 12. 次の拡張

1. クエストボード、移動、所持品などのサブ画面ViewModelを追加する
2. CLIの各 `_run_*_flow` を画面コントローラーへ段階的に置き換える
3. 2DゲームクライアントのGUIシェルから `SteamDemoScreenController` を利用する
4. フォーカス復元、モーダル、画面スタックを追加する
5. 実機ゲームパッドとポインター入力アダプターを追加する
