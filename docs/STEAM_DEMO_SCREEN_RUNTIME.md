# Steamデモ画面Runtime

## 目的

SteamデモのRouter、ScreenFactory、画面Controllerを一つのセッション実行契約として束ね、CLIと将来GUIが同じ手順で画面遷移を実行できるようにします。

## 背景

PR #93でトップメニューとサブ画面のRoute遷移を`SteamDemoScreenRouter`へ移し、PR #95でRouteごとのController生成を`SteamDemoScreenFactory`へ集約しました。

一方、画面を開く処理は描画側で次のように組み合わせる必要がありました。

```text
RouterでRouteをPush
  ↓
ScreenFactoryでControllerを生成
  ↓
画面処理を実行
  ↓
Routerへ完了またはキャンセルを通知
```

この手順をCLIとGUIが個別実装すると、RouteとControllerの状態がずれる可能性があります。

代表例:

- RouteはPushされたがController生成に失敗する
- 画面完了後もController参照が残る
- トップ画面なのにサブ画面Controllerが残る
- Routerの現在RouteとControllerのRouteが異なる

## 構成

```text
SteamDemoCompositionRoot
  ↓
SteamDemoSessionComposition
  ├─ SteamDemoScreenController
  ├─ SteamDemoScreenRouter
  ├─ SteamDemoScreenFactory
  └─ SteamDemoScreenRuntime
       ├─ Router状態
       ├─ Active Route Screen
       └─ 現在Frame
```

## Runtimeの責務

`SteamDemoScreenRuntime`は次を担当します。

- トップ画面入力のRouterへの委譲
- Route Push後のController生成
- Active Route Screenの保持
- サブ画面意味入力の実行
- 完了・キャンセル後のController破棄
- Reset時のController破棄
- Factory失敗時のRoute Rollback
- 現在RouteとViewModelを含むFrame生成
- RouterとActive Controllerの不整合検知

## Runtimeが担当しないこと

- 画面描画
- `input()`やOSイベント取得
- ゲームルール
- マスターデータ読み込み
- Controller固有の直接選択API
- 非同期処理
- Route状態のセーブ

## 主要契約

### SteamDemoRuntimeFrame

現在画面を描画するためのスナップショットです。

保持内容:

- `route_state`
- `route_id`
- `view`
- `is_top_menu`
- `has_active_screen`

`view`は現在Controllerが返すViewModelです。

`to_dict()`はRoute状態だけを文字列・真偽値・list・dictへ変換します。ViewModel自体は画面ごとに型が異なるため、共通JSONへ変換しません。

### SteamDemoRuntimeResult

入力や画面遷移の結果です。

保持内容:

- 更新後Frame
- Route遷移結果
- ログ
- 拒否理由
- 終了要求

描画側は1回の操作結果から、遷移と更新後ViewModelを同時に取得できます。

## 入力処理

### トップ画面

```python
result = runtime.handle_input(MenuInputAction.CONFIRM)
```

またはポインター操作などでAction IDを直接指定します。

```python
result = runtime.activate_top_action("quest_board")
```

Actionがサブ画面を要求した場合、Runtimeは次を一つの操作として実行します。

```text
Router Push
  ↓
ScreenFactory.create(route_id)
  ↓
Active Route Screenへ設定
  ↓
サブ画面Frameを返す
```

### サブ画面

```python
result = runtime.handle_input(MenuInputAction.MOVE_DOWN)
```

RuntimeはActive Controllerの`handle_input()`を呼び出します。

- 通常操作: Routeを維持
- Controller拒否: Routeを維持して`REJECTED`
- Cancel要求: RouteをPopしてControllerを破棄
- 想定内`ValueError`: Routeを維持して拒否結果を返す

Controller固有のID直接指定は、引き続き各Controllerの`activate_*()`を使用します。

## 完了・キャンセル

### 完了

```python
result = runtime.complete_current_route(logs=("quest_completed",))
```

次を実行します。

1. RouterをPop
2. Active Controllerを破棄
3. トップ画面ViewModelを再構築

### キャンセル

```python
result = runtime.cancel_current_route()
```

Controller側から`cancel_requested=True`が返された場合も同じ処理を行います。

### Reset

```python
result = runtime.reset_to_top()
```

Route履歴をトップへ戻し、Active Controllerを破棄します。

## Factory失敗時の原子的Rollback

Route Push後にFactory生成が失敗した場合、RuntimeはサブRouteを残しません。

```text
Route Push
  ↓
Factory.create()失敗
  ↓
Router.cancel_current_route()
  ↓
Active Controllerを空にする
  ↓
REJECTED結果をトップ画面Frameとともに返す
```

ログ形式:

```text
screen_open_rejected:<route_id>:<reason>
```

拒否理由:

```text
screen_creation_failed
```

## 不変条件

Runtimeは操作前後に次を確認します。

### トップ画面

```text
Router.current_route == TOP_MENU
Active Route Screen == None
```

### サブ画面

```text
Router.current_route != TOP_MENU
Active Route Screen != None
Active Route Screen.route_id == Router.current_route
```

外部コードがRouterだけを直接操作して不整合を作った場合、Runtimeは`RuntimeError`で検知します。

## Composition Root

`SteamDemoCompositionRoot.build()`はRuntimeを含むセッション構成を返します。

```python
composition = SteamDemoCompositionRoot.build(playable, demo)
runtime = composition.runtime
```

New GameまたはContinue後にCompositionを再生成するため、次は前セッションから持ち越しません。

- Route履歴
- Active Controller
- 選択位置
- 会話Step
- イベント詳細状態

Application状態は同じ`PlayableSliceApplication`を参照するため維持されます。

## CLI接続

SteamデモCLIは次の順で実行します。

```text
runtime.activate_top_action(action_id)
  ↓
RuntimeがRouteとControllerを準備
  ↓
runtime.active_screenをCLI Handlerへ渡す
  ↓
CLI Handlerが描画・入力・Controller操作を実行
  ↓
runtime.complete_current_route(logs)
```

Handler未登録時は`cancel_current_route()`、Handler内の想定内拒否時は`complete_current_route()`を通して必ずトップへ戻ります。

## 将来GUIでの利用

GUI側は次だけを実装します。

- OS入力を`MenuInputAction`へ変換
- `RuntimeFrame.view`を描画
- Controller固有の直接ActionをUIイベントへ接続
- 完了タイミングでRuntimeへ通知

Route Push、Controller生成、Controller破棄、RollbackをGUI側で重複実装する必要はありません。

## テスト観点

### 正常系

- 初期トップFrame
- Top Actionからサブ画面を開く
- Factory生成Controllerの保持
- サブ画面意味入力
- 完了後のトップ復帰
- キャンセル後のトップ復帰
- Reset
- Exit要求

### 異常系

- Factory生成失敗
- Factoryが異なるRouteを返す
- サブ画面なしで完了・キャンセル
- Routerだけを外部操作した不整合
- Controller入力の想定内拒否
- CLI Handler未登録
- CLI Handlerの想定内拒否

### 境界値

- Active Controller 0件
- Active Controller 1件
- トップRoute
- 1階層のサブRoute
- ログなしキャンセル
- 即時Action

### 回帰

- Screen Router
- ScreenFactory / Composition Root
- 全サブ画面Controller
- SteamデモCLI
- 通常CLI
- Save / Load
