# Steamデモ ScreenFactory / Composition Root

## 目的

Steamデモの各Routeで必要となるFacade・Controllerの生成をCLIや将来GUIから分離し、具象依存の組み立て場所を1か所へ集約します。

## 背景

主要サブ画面は個別Controllerへ分離され、PR #93でトップ画面とサブ画面のRoute遷移も共通化されました。

一方、各Controllerの生成は次の場所へ分散していました。

- `run_steam_demo.py`
- `item_equipment_cli.py`
- `equipment_workshop_cli.py`
- `economy_facility_cli.py`

この状態でGUIを追加すると、CLIとGUIがそれぞれ次を直接生成することになります。

- Application向けFacade
- Presentation Controller
- Top Screen Controller
- Screen Router

依存構成が複数の描画実装へ分散すると、Route追加時の登録漏れやController型の不整合が発生しやすくなります。

## 構成

```text
PlayableSliceApplication
SteamDemoApplication
  ↓
SteamDemoCompositionRoot
  ├─ SteamDemoScreenController
  ├─ SteamDemoScreenRouter
  └─ SteamDemoScreenFactory
       ↓ Route開始ごとに生成
     SteamDemoRouteScreen
       ├─ route_id
       └─ controller
```

## Composition Root

`SteamDemoCompositionRoot`はSteamデモ1セッション分の具象依存を組み立てる入口です。

```python
composition = SteamDemoCompositionRoot.build(playable, demo)
```

戻り値の`SteamDemoSessionComposition`は次を保持します。

- `top_screen`
- `router`
- `screen_factory`

ゲーム開始またはロード後にComposition Rootを再実行することで、前セッションの選択状態やController内部状態を持ち越しません。

## ScreenFactory

`SteamDemoScreenFactory`は`SteamDemoRouteId`に対応するControllerを生成します。

```python
route_screen = factory.create(SteamDemoRouteId.QUEST_BOARD)
```

`SteamDemoRouteScreen`は次だけを保持します。

- Route ID
- 生成されたController

Factoryは描画、入力、ゲームルールの実行を行いません。

## 対応Route

Factoryはトップメニューを除く13Routeを登録します。

- アイテム使用
- 装備変更
- ショップ
- 装備強化
- 装備分解
- クラフト
- 宿屋
- クエストボード
- 移動
- NPC会話
- 採取
- 宝箱
- フィールドイベント

トップメニューは`SteamDemoScreenController`が担当するため、Factoryからの生成を拒否します。

## RouteとController型

RouteとControllerの対応はFactory内のRegistryで一元管理します。

生成後には期待型を確認し、誤ったControllerが返された場合は実行前に`TypeError`で拒否します。

```text
steam_demo.quest_board
  → QuestBoardScreenController

steam_demo.npc_dialogue
  → NpcDialogueScreenController

steam_demo.shop
  → ShopScreenController
```

Registryに不足・余分なRouteがある場合もFactory初期化時に拒否します。

## Controllerライフサイクル

サブ画面ControllerはRouteを開くたびに新規生成します。

```text
1回目のNPC会話Route
  → NpcDialogueScreenController A

トップへ戻る

2回目のNPC会話Route
  → NpcDialogueScreenController B
```

これにより、前回の次の状態を意図せず持ち越しません。

- 選択位置
- 選択中アイテム
- 選択中メンバー・スロット
- 会話ステップ
- フィールドイベント詳細

ControllerとFacadeは新規生成しますが、参照する`PlayableSliceApplication`は同一です。そのため、購入・装備・クエスト進行などの最新ゲーム状態は次回画面生成時に反映されます。

## Routerとの責務分離

### Router

- 現在Route
- Route履歴
- Push / Pop / Reset
- Action結果からRouteへの変換

### ScreenFactory

- Routeに対応するController生成
- RouteとController型の整合確認
- Controllerライフサイクル

### 各Controller

- サブ画面内部状態
- ViewModel構築
- 意味入力
- Application操作

RouterはControllerを保持しません。FactoryもRoute履歴を保持しません。

## CLI接続

SteamデモCLIは次の順で処理します。

```text
Top Action
  ↓
RouterがRouteをPush
  ↓
ScreenFactory.create(route_id)
  ↓
CLI Route HandlerへControllerを注入
  ↓
Handler完了
  ↓
RouterがRouteをPop
```

CLI Route Handlerは`PlayableSliceApplication`からControllerを生成しません。

## 通常CLI互換

既存の通常CLI入口は維持します。

```python
run_item_use_screen(app)
run_equipment_screen(app)
run_shop_screen(app)
run_equipment_upgrade_screen(app)
run_equipment_salvage_screen(app)
run_crafting_screen(app)
run_inn_screen(app)
```

各関数は内部でController注入版へ委譲します。

```python
run_item_use_controller(controller)
run_equipment_controller(controller)
run_shop_controller(controller)
```

SteamデモはController注入版を使用し、通常CLIは従来どおりApplicationを渡せます。

## エラー処理

次の状態はゲーム処理開始前に拒否します。

- トップRouteをサブ画面として生成
- Route Builderの登録不足
- 未知・余分なRoute Builder
- RouteとController型の不一致
- CLI RouteとController型の不一致

Route Handlerで`TypeError`または想定内`ValueError`が発生した場合、CLIは拒否ログを返し、Routerをトップメニューへ戻します。

## テスト観点

### 正常系

- 全13Routeの生成
- RouteとController型の対応
- Composition RootからTop Screen・Router・Factory生成
- Factory生成ControllerをCLI Handlerへ注入
- 最新Application状態の反映

### 異常系

- トップRouteの生成拒否
- 空Registry
- 登録不足・余分なRoute
- Controller型不一致
- CLI Handlerの型不一致

### ライフサイクル

- 同じRouteを2回開くと別Controller
- セッション再構築時に別Top Screen・Router・Factory
- Controller再生成後もゲーム状態は共有

### 回帰

- 通常CLIの既存関数
- SteamデモRouter
- 全サブ画面Controller
- Save / Load
- 画面操作後のApplication状態

## 対象外

- 汎用DIコンテナ
- Controller Singleton
- Route／Controller状態のセーブ
- GUIフレームワーク
- モーダル／オーバーレイFactory
- Steam Input API
