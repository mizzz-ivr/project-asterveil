# Steam Demo Screen Action Dispatcher

## 1. 目的

SteamデモのScene上で選択されたEntryを、CLI・将来GUIから共通Commandとして実行できるようにする。

描画側が次のController固有知識を持たないことを目標とする。

- `activate_item`
- `activate_target`
- `activate_member`
- `activate_slot`
- `activate_equipment`
- `activate_recipe`
- `activate_quest`
- `activate_destination`
- `activate_npc`
- `activate_choice`
- `activate_node`
- `activate_stay`

## 2. 背景

画面基盤は以下の順で分離されている。

```text
Screen Controller
  ↓
Screen Router
  ↓
ScreenFactory / Composition Root
  ↓
Screen Runtime
  ↓
Scene Builder Registry / Renderer
```

Renderer導入後も、Entry確定時のController呼び分けはCLIに残っていた。

```text
Scene Entryを選択
  ↓
CLIが現在Routeと画面Modeを判定
  ↓
Controller固有のactivate_*を直接呼ぶ
```

この構造をGUIへ移植すると、GUI側にも全Controller型と画面Modeの知識が必要になる。

## 3. 推奨構成

```text
CLI / 将来GUI
  ↓
SteamDemoUiCommand
  ↓
SteamDemoSceneActionDispatcher
  ├─ 期待Route検証
  ├─ 現在SceneのCommand検証
  ├─ Route別Action Adapter
  └─ Controller固有Action呼び出し
  ↓
SteamDemoScreenRuntime.apply_subscreen_interaction
  ↓
SteamDemoRuntimeResult
```

## 4. Command契約

### 4.1 Entry確定

```python
SteamDemoUiCommand.activate_entry(
    SteamDemoRouteId.QUEST_BOARD,
    "quest.chapter01.main",
)
```

Commandは次を保持する。

- Command種別
- 操作元が期待するRoute ID
- Entry ID

### 4.2 意味入力

```python
SteamDemoUiCommand.input(
    SteamDemoRouteId.EQUIPMENT,
    MenuInputAction.CANCEL,
)
```

対応する意味入力は既存契約を利用する。

- `MOVE_UP`
- `MOVE_DOWN`
- `CONFIRM`
- `CANCEL`
- `SHOW_GUIDE`

物理キー、ゲームパッドボタン、ポインター入力はDispatcherの責務外とする。

## 5. Interactive Scene

`SteamDemoInteractiveScene`は、既存Scene Modelと現在実行可能なCommand一覧をまとめる。

```text
SteamDemoInteractiveScene
  ├─ scene
  └─ commands
       ├─ command
       ├─ section_id
       ├─ label
       ├─ is_enabled
       ├─ is_selected
       └─ is_recommended
```

描画側は`commands`だけを操作対象として扱う。

### 5.1 NPC会話

会話本文の`line.*` Entryは表示専用であり、Command一覧へ含めない。

```text
NPC一覧    → 操作可能
会話本文   → 表示専用
会話選択肢 → 操作可能
```

### 5.2 宿屋

宿屋SceneのパーティEntryは状態表示専用である。

Dispatcherは次の明示Actionを公開する。

```text
entry_id = stay
section_id = actions
```

これにより、パーティメンバーを選択する操作と宿泊操作を混同しない。

## 6. Route別Action Adapter

Dispatcherはトップ画面を除く全13RouteのAdapterを登録する。

| Route | Controller操作 |
|---|---|
| アイテム使用 | Modeに応じてアイテム／対象を選択 |
| 装備変更 | Modeに応じてメンバー／スロット／装備を選択 |
| ショップ | 商品を購入 |
| 装備強化 | 装備を強化 |
| 装備分解 | 装備を分解 |
| クラフト | レシピを実行 |
| 宿屋 | 宿泊 |
| クエストボード | クエストを受注 |
| 移動 | 移動先を選択 |
| NPC会話 | Modeに応じてNPC／選択肢を選択 |
| 採取 | 採取ポイントを選択 |
| 宝箱 | 報酬ポイントを選択 |
| フィールドイベント | Modeに応じてイベント／選択肢を選択 |

Adapter Registryの登録漏れ・余分なRouteは初期化時に拒否する。

## 7. 検証順序

Entry確定時は以下の順で検証する。

```text
1. Commandの期待Routeと現在Routeを比較
2. 現在Runtime FrameからSceneを再構築
3. Interactive SceneからEntryを検索
4. Entryが操作対象か確認
5. Entryが有効か確認
6. Active ControllerのRoute・型を確認
7. Controller固有Actionを実行
8. Controller InteractionをRuntimeへ反映
```

Controllerも実行直前に対象存在・有効状態を再検証する。

```text
Scene検証
  +
Controller再検証
```

これにより、表示後に所持金・在庫・進行状態が変化しても、不正な操作を実行しない。

## 8. 古いScene操作

Commandには`expected_route_id`を含める。

現在Routeと一致しない場合は、次の理由で拒否する。

```text
stale_scene_route
```

例:

```text
画面Aを表示
  ↓
別操作で画面Bへ遷移
  ↓
遅れて画面Aのクリックイベントが到着
  ↓
Route不一致として拒否
```

拒否しても現在RouteとActive Controllerは変更しない。

## 9. Runtime境界

Runtimeへ以下を追加する。

### 9.1 Controller Interaction反映

```python
runtime.apply_subscreen_interaction(interaction)
```

Runtimeは次を共通処理する。

- logs検証
- cancel要求
- rejection reason
- 更新後ViewModel
- Route維持／Pop
- Active Controller破棄

### 9.2 事前検証拒否

```python
runtime.reject_current_action(reason_code, logs=...)
```

Dispatcherは独自にRuntime Resultを組み立てず、Runtimeの共通拒否契約を利用する。

## 10. CLI接続

通常CLIの公開関数は維持する。

```text
run_item_use_screen(app)
run_equipment_screen(app)
run_shop_screen(app)
...
```

Controller実行関数はDispatcherを任意注入できる。

```python
run_item_use_controller(controller, dispatcher=None)
```

- Dispatcherなし: 従来どおりControllerを直接実行
- Dispatcherあり: Scene Commandとして実行

SteamデモではComposition RootのDispatcherを注入する。

```text
Composition Root
  ↓
action_dispatcher
  ↓
SteamデモCLI Route Handler
```

表示と物理入力取得は引き続きCLIが担当する。

## 11. Composition Root

`SteamDemoSessionComposition`は次を提供する。

```text
Top Screen Controller
Screen Router
ScreenFactory
Screen Runtime
Scene Builder Registry
Scene Action Dispatcher
```

DispatcherはRuntimeとScene Registryを共有するが、Controllerを保持しない。

## 12. テスト観点

### 正常系

- トップEntryからサブRouteを開ける
- 全Route Adapterが登録される
- 単階層画面のEntryを実行できる
- 複数階層画面で現在Modeに対応したActionを実行できる
- 意味入力をRuntimeへ渡せる
- Cancelでトップへ戻りControllerを破棄する

### 異常系

- 古いRouteのCommand
- 未知Entry
- 無効Entry
- Active Controller欠落
- Controller型不一致
- Adapter欠落
- Controller Action例外
- 不正Interaction

### 境界値

- Command 0件
- Entry 1件
- 選択可能Entry 0件
- 会話完了後の選択肢0件
- 宿泊不可
- トップ画面の即時Action

### 回帰

- Screen Router
- ScreenFactory
- Screen Runtime
- Scene Renderer
- 全サブ画面Controller
- 通常CLI
- SteamデモCLI
- Save / Load

## 13. スコープ外

- DOM／Canvas GUI
- CSSテーマ
- アニメーション
- ポインター座標管理
- フォーカス管理
- モーダル／オーバーレイ
- 非同期Command
- Steam Input API
