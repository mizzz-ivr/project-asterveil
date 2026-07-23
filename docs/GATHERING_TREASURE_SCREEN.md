# 採取・探索報酬画面

## 目的

Steamデモの探索ループで利用する採取ポイントと探索報酬を、CLI固有処理から分離し、将来GUI・ゲームパッド・ポインター操作から共通利用できる型付き画面契約へ移行します。

## 対象範囲

- 現在地の採取ポイント一覧
- 採取可否、採取済み状態、再出現ルール
- 採取実行と獲得アイテム
- 現在地の探索報酬一覧
- 開封可否、開封済み状態、条件未達理由
- 宝箱・発見物の開封実行
- CLIアダプター

## 対象外

- GUIフレームワーク
- 採取アニメーション
- 宝箱開封演出
- 3Dマップ上の配置
- Steam Input API
- 他サブ画面の共通化

## 構成

```text
CLI / 将来GUI
  ↓
GatheringScreenController
TreasureScreenController
  ↓
PlayableExplorationFacade
  ↓
GatheringService / TreasureService
PlayableSliceApplication の既存状態・既存処理
```

## 探索Facade

`PlayableExplorationFacade`は採取と探索報酬だけを担当します。

NPC会話・フィールドイベント用の`PlayableInteractionFacade`へ追加しないことで、Application境界の責務肥大化を防ぎます。

Presentation層は次を行いません。

- `gathering_node_lines()`の再解析
- `treasure_node_lines()`の再解析
- `_gathering_service`や`_treasure_service`への直接アクセス
- 在庫、フラグ、採取済み・開封済み集合の直接変更

## 採取画面

### ViewModel

`GatheringNodeSummary`は次を保持します。

- `node_id`
- `location_id`
- `name`
- `node_type`
- `description`
- `can_gather`
- `reason_code`
- `is_gathered`
- `respawn_rule`
- `respawn_description`

### 実行可否

一覧作成時に既存`GatheringService.list_nodes_for_location()`を利用します。

決定時には最新一覧を再構築し、次を再確認します。

- 現在地一致
- 必須フラグ
- 採取済み状態
- 再出現後の状態

実行可能な場合だけ既存`gather_from_node()`を呼びます。

### 実行後

既存処理により次を維持します。

- 在庫へのアイテム追加
- 採取済み状態
- クエスト採取進捗
- レシピ発見

操作後は最新状態からViewModelを再構築します。

## 探索報酬画面

### ViewModel

`TreasureNodeSummary`は次を保持します。

- `reward_node_id`
- `location_id`
- `name`
- `node_type`
- `description`
- `can_open`
- `reason_code`
- `is_opened`
- `one_time`
- `required_flags`
- `required_facility_id`
- `required_facility_level`

### 実行可否

一覧作成時に既存`TreasureService.list_nodes_for_location()`を利用します。

決定時には最新一覧を再構築し、次を再確認します。

- 現在地一致
- 開封済み状態
- 必須フラグ
- 必須施設レベル

実行可能な場合だけ既存`open_treasure_node()`を呼びます。

### 実行後

既存処理により次を維持します。

- アイテム・装備・レシピ帳の獲得
- 開封済み状態
- レシピ発見
- 開封メッセージ

## Controller

両Controllerは次の入力を扱います。

- 上移動
- 下移動
- 決定
- 戻る
- ガイド表示
- ID直接指定

実行不能項目はメニュー項目を無効化します。未知IDや状態変更後に実行不能となった項目は、別項目へ置き換えず明示的に拒否します。

## CLI接続

SteamデモCLIでは次のハンドラーを変更します。

- `SteamDemoFlowId.GATHERING`
- `SteamDemoFlowId.TREASURE`

CLI側の責務は一覧表示、数値入力、キャンセルだけです。

## テスト観点

### 正常系

- 採取ポイント一覧
- 採取と在庫反映
- 採取後のViewModel更新
- 探索報酬一覧
- 開封と在庫反映
- 開封後のViewModel更新

### 異常系

- 未知採取ポイント
- 採取済みポイント
- フラグ未達ポイント
- 未知探索報酬
- 開封済み報酬
- フラグ・施設レベル未達報酬

### 境界値

- 一覧0件
- 実行可能項目0件
- 戻る
- ガイド表示
- 表示後に状態が変わった場合の再検証

### 回帰

- Gathering
- Treasure
- Inventory
- Quest Progress
- Recipe Discovery
- Save / Load
- SteamデモCLI
