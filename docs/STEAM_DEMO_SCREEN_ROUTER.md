# Steamデモ画面ルーター

## 目的

Steamデモのトップメニューと各サブ画面の遷移を、CLI固有の条件分岐から分離します。

将来GUI、キーボード、ゲームパッド、ポインター操作へ移行しても、同じRoute状態と遷移結果を利用できる構造にします。

## 背景

主要サブ画面は個別Controllerへ分離済みですが、Steamデモ実行時には次の責務が`run_steam_demo.py`へ残っていました。

- `ActionDispatchResult`からサブ画面を選ぶ
- Flow IDとCLI関数を対応付ける
- サブ画面完了後にトップメニューへ戻る
- 未対応Flowを処理する
- トップメニューのControllerとは別にPresenterとActionControllerを直接利用する

この状態では、GUI導入時に同じ遷移判定を再実装する可能性があります。

## 構成

```text
物理入力 / ポインター
  ↓
MenuInputAction / action_id
  ↓
SteamDemoScreenController
  ↓
ActionDispatchResult
  ↓
SteamDemoScreenRouter
  ├─ STAY
  ├─ PUSHED
  ├─ POPPED
  ├─ RESET
  ├─ EXIT_REQUESTED
  └─ REJECTED
       ↓
CLI Route Handler または将来GUI画面
```

## Route ID

`SteamDemoRouteId`は描画実装に依存しない画面識別子です。

- `steam_demo.top_menu`
- `steam_demo.use_item`
- `steam_demo.equipment`
- `steam_demo.shop`
- `steam_demo.equipment_upgrade`
- `steam_demo.equipment_salvage`
- `steam_demo.crafting`
- `steam_demo.inn`
- `steam_demo.quest_board`
- `steam_demo.travel`
- `steam_demo.npc_dialogue`
- `steam_demo.gathering`
- `steam_demo.treasure`
- `steam_demo.field_event`

ApplicationのAction IDや`SteamDemoFlowId`とは別の契約とし、画面名の変更や描画実装の差し替えをApplicationへ波及させません。

## Route状態

`SteamDemoRouteState`はRoute履歴だけを保持します。

```python
SteamDemoRouteState(
    route_stack=(
        SteamDemoRouteId.TOP_MENU,
        SteamDemoRouteId.QUEST_BOARD,
    )
)
```

### 不変条件

- Routeスタックの先頭は必ず`TOP_MENU`
- 現在Routeはスタック末尾
- 戻れるのはスタックが2件以上の場合だけ
- RouterはApplication状態を保持しない
- Routerは画面Controllerや描画オブジェクトをRoute状態へ格納しない
- `to_dict()`は文字列、真偽値、listだけを返す

## 遷移種別

### STAY

現在Routeを変更しません。

対象:

- ステータス表示
- ガイド表示
- セーブ
- メニュー選択移動

### PUSHED

トップメニューからサブ画面を開きます。

`ActionDispatchKind.FLOW_REQUIRED`と`SteamDemoFlowId`を、登録済みRouteへ変換します。

### POPPED

現在のサブ画面を閉じ、直前Routeへ戻ります。

対象:

- サブ画面操作完了
- サブ画面キャンセル
- 戻る操作
- CLI Route Handlerの正常終了
- CLI Route Handlerの想定内Application拒否

### RESET

Route履歴を破棄し、トップメニューだけの状態へ戻します。

ゲームセッション再開始やタイトル復帰後の初期化に利用できます。

### EXIT_REQUESTED

終了要求を描画アダプターへ返します。Route履歴は変更しません。

### REJECTED

不正な遷移を拒否します。Route履歴は変更しません。

例:

- ルート画面で戻る
- ルート画面で完了通知
- 未登録Flow
- サブ画面表示中のトップメニュー操作
- `FLOW_REQUIRED`なのにFlow IDがない

## サブ画面内部状態との責務境界

Routerはサブ画面内部の状態を管理しません。

次の状態は既存の各Controllerが引き続き管理します。

- メニュー選択位置
- NPC会話の現在Step
- NPC会話の選択肢
- フィールドイベントの一覧／詳細モード
- 装備対象メンバーとスロット
- アイテム対象メンバー
- ショップ、クラフト、宿屋の最新ViewModel

Routerが管理するのは「トップメニューか、どのサブ画面か」だけです。

## CLI接続

`run_steam_demo.py`は次の順で処理します。

1. `SteamDemoScreenController.activate_action()`をRouter経由で呼ぶ
2. `FLOW_REQUIRED`ならRouterがRouteをPushする
3. `_CLI_ROUTE_HANDLERS`からRoute Handlerを取得する
4. CLI Handlerが表示と入力を処理する
5. HandlerのログをRouterへ完了通知する
6. RouterがRouteをPopしてトップメニューへ戻る

```text
SteamDemoRouteId
  ↓
_CLI_ROUTE_HANDLERS
  ↓
既存サブ画面CLIアダプター
  ↓
complete_current_route()
```

CLI Handlerが未登録の場合も`cancel_current_route()`でトップへ戻します。

想定内の`ValueError`が発生した場合は`route_handler_rejected`ログを返し、RouteをPopします。

## 失敗時の挙動

### 未登録Route

- 遷移しない
- `route_not_registered`を返す
- Route履歴を変更しない

### CLI Handler未登録

- 一度開いたRouteをキャンセル扱いで閉じる
- `route_not_supported:<route_id>`を返す
- トップメニューへ戻る

### サブ画面中のトップAction

- `top_action_not_allowed_from_subroute`で拒否
- 現在のサブ画面を維持する

### 二重完了

トップメニューへ戻った後に再度完了通知された場合、`cannot_complete_root`で拒否します。

## 対象外

- GUIフレームワーク
- 画面生成Factory
- モーダル、ダイアログ、オーバーレイ
- 画面アニメーション
- サブ画面内部の多段Route化
- Route履歴のセーブデータ保存
- Steam Input API

## テスト観点

### 正常系

- トップActionから対応RouteをPushできる
- サブ画面完了後にトップへPopする
- サブ画面キャンセル後にトップへPopする
- 即時ActionはRouteを変更しない
- ExitはRouteを変更せず終了要求を返す
- CLI Route Handlerのログを維持する

### 異常系

- 未登録Flow
- Handler未登録
- Flow ID欠落
- サブ画面中のトップ操作
- ルート画面での戻る、キャンセル、完了
- Applicationの想定内拒否

### 境界値

- Routeスタック1件
- Routeスタック2件
- 全FlowのRoute登録
- Reset後の履歴
- JSONシリアライズ

### 回帰

- Steamデモトップメニュー
- 既存ActionController
- 既存ScreenController
- 全サブ画面Controller
- 通常CLI
- SteamデモCLI
