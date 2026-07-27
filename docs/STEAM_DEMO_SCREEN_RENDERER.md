# Steamデモ Screen Renderer

## 目的

SteamデモのRuntime Frameおよび各画面ViewModelを、CLI・DOM・Canvasなどの描画方式から独立したScene Modelへ変換します。

既存のControllerやRuntimeは画面状態を返しますが、最終的な表示構造はCLI内の`print()`処理へ分散していました。本契約では、ViewModelから描画用構造への変換を1か所へ集約します。

## 全体構成

```text
Application / Domain
  ↓
Screen Controller
  ↓
ViewModel
  ↓
Screen Runtime Frame
  ↓
SteamDemoSceneBuilderRegistry
  ↓
SteamDemoSceneModel
  ├─ SteamDemoConsoleRenderer
  ├─ 将来DOM Renderer
  └─ 将来Canvas Renderer
```

## 責務分離

### Controller

- 画面内部状態
- 意味入力
- 選択状態
- Application操作
- 更新後ViewModel

### Runtime

- RouteとActive Controllerの同期
- Controller生成と破棄
- 画面開始失敗時のRollback
- Runtime Frame／Result

### Scene Builder Registry

- RouteとViewModel型の対応
- ViewModelからScene Modelへの変換
- 選択状態・有効状態・推奨状態の保持
- Registry不足・余分なRouteの検知

### Renderer

- Scene Modelを描画先へ出力
- CLIでは文字列行へ変換
- 将来GUIではDOM／Canvas要素へ変換

Rendererはゲームルール、Controller生成、Route遷移、入力処理を行いません。

## Scene Model

### SteamDemoSceneModel

画面全体を表します。

- `route_id`
- `title`
- `subtitle`
- `status`
- `sections`
- `action_hints`
- `is_completed`

### SceneSection

画面内の意味的なグループです。

例:

- アクション
- クエスト一覧
- 移動先
- 会話
- 選択肢
- 商品
- レシピ
- パーティ状態

### SceneEntry

一覧や選択対象の1項目です。

- `entry_id`
- `label`
- `description`
- `fields`
- `is_enabled`
- `is_selected`
- `is_recommended`

### SceneField

項目の補助情報です。

例:

- 所持数
- 価格
- HP／SP
- 進行状態
- 必要素材
- 利用可能数
- 実行不可理由

### SceneActionHint

意味入力と物理入力表示を結びます。

トップ画面では既存`InputBindingProfile`からキーボード・ゲームパッドの表示ラベルを引き継ぎます。

## JSON互換

`SteamDemoSceneModel.to_dict()`は次の値だけを返します。

- `str`
- `int`
- `bool`
- `None`
- `list`
- `dict`

Enum、Controller、Application、Renderer固有オブジェクトは含みません。

```python
scene = registry.build_frame(runtime.current_frame())
payload = scene.to_dict()
```

これにより、将来GUIの状態ストア、デバッグ表示、スナップショットテストへ利用できます。

## RouteとViewModel型

Registryはトップ画面を含む全14Routeを登録します。

```text
steam_demo.top_menu
  → SteamDemoMenuViewModel

steam_demo.quest_board
  → QuestBoardScreenViewModel

steam_demo.npc_dialogue
  → NpcDialogueScreenViewModel

steam_demo.shop
  → ShopScreenViewModel
```

RouteとViewModel型が一致しない場合は、描画前に`TypeError`で拒否します。

```text
scene_view_type_mismatch:<route>:expected=<type>:actual=<type>
```

Builderが異なるRouteのSceneを返した場合も拒否します。

```text
scene_builder_route_mismatch:expected=<route>:actual=<route>
```

## Registry検証

Registry初期化時に、次を確認します。

- 登録漏れがない
- 未定義Routeが追加されていない
- トップ画面を含む全Routeが存在する

不正な場合は次の形式で拒否します。

```text
invalid_scene_builder_registry:missing=...:extra=...
```

## 画面モード

同じRouteで複数モードを持つ画面も、Scene Model上ではSectionを切り替えて表現します。

### アイテム使用

```text
ITEM_LIST
  → 使用可能アイテムSection

TARGET_LIST
  → 使用対象Section
```

### 装備変更

```text
MEMBER_LIST
  → メンバーSection

SLOT_LIST
  → 装備スロットSection

EQUIPMENT_LIST
  → 装備候補Section
```

### NPC会話

```text
NPC_LIST
  → 会話相手Section

DIALOGUE
  → 会話Section + 選択肢Section
```

### フィールドイベント

```text
EVENT_LIST
  → イベントSection

CHOICE_LIST
  → 選択肢Section
```

## Console Renderer

`SteamDemoConsoleRenderer`はScene Modelだけを参照します。

```python
renderer = SteamDemoConsoleRenderer(registry)
renderer.render_frame(runtime.current_frame())
```

出力は機械的に確認しやすい安定した行形式です。

```text
- screen:<route_id>:<title>:completed=<bool>
- screen_status:<route_id>:<key>=<value>
- screen_section:<route_id>:<section_id>:<title>:count=<n>
- screen_entry:<route_id>:<section_id>:<entry_id>:<label>:enabled=<bool>:selected=<bool>:recommended=<bool>
- screen_entry_field:<route_id>:<entry_id>:<key>=<value>
- screen_hint:<route_id>:<action_id>:keyboard=<label>:gamepad=<label>
```

CLI固有の数値選択やキャンセル入力は既存アダプターへ残します。

## Composition Root

`SteamDemoSessionComposition`は次を提供します。

- Top Screen Controller
- Screen Router
- ScreenFactory
- Screen Runtime
- Scene Builder Registry

```python
composition = SteamDemoCompositionRoot.build(playable, demo)
scene = composition.scene_registry.build_frame(
    composition.runtime.current_frame()
)
```

Registryは状態を持たないため、ControllerライフサイクルやRoute履歴には影響しません。

## CLI移行

次の表示処理を共通Rendererへ移行します。

- Steamデモトップ画面
- クエストボード
- 移動
- NPC会話
- フィールドイベント
- 採取
- 宝箱
- アイテム使用
- 装備変更
- ショップ
- 装備強化
- 装備分解
- クラフト
- 宿屋

既存の`_print_*`関数名は互換ラッパーとして維持します。

## テスト観点

### 正常系

- トップFrameからScene生成
- 全13サブRouteのScene生成
- 選択状態
- 有効／無効状態
- 推奨状態
- 入力ヒント
- JSONシリアライズ
- Console出力

### 異常系

- RouteとViewModel型の不一致
- Registry登録不足
- 余分なRoute
- Builderが異なるRouteを返す
- モードに必要な詳細データがない

### 境界値

- Entry 0件
- Section内Entry 0件
- 選択可能項目0件
- 説明なし
- 補助情報なし
- 完了済み画面

### 回帰

- Screen Runtime
- ScreenFactory
- Composition Root
- 全サブ画面Controller
- 通常CLI
- SteamデモCLI
- Save / Load

## スコープ外

- DOM Renderer
- Canvas Renderer
- GUIフレームワーク
- CSSテーマ
- アニメーション
- 画像・音声アセット
- モーダル／オーバーレイRenderer
- Steam Input API
