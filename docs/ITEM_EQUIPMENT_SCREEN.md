# アイテム使用・装備変更画面

## 目的

Steamデモのアイテム使用と装備変更をCLI固有処理から分離し、将来GUI・キーボード・ゲームパッド・ポインター操作から共通利用できる画面契約へ移行します。

## 対象範囲

- 使用可能消耗品一覧
- アイテム効果と所持数
- 使用対象メンバー一覧
- 対象ごとの使用可否
- パーティメンバー一覧
- 装備スロット一覧
- 現在装備
- 装備候補と利用可能数
- ステータス補正・パッシブ情報
- CLIアダプター

## 対象外

- 装備強化
- 装備分解
- 装備解除
- 戦闘中アイテム使用
- GUIフレームワーク
- Steam Input API

## 構成

```text
CLI / 将来GUI
  ↓
ItemUseScreenController
EquipmentScreenController
  ↓
PlayablePartyMenuFacade
  ↓
ItemUseService / EquipmentService
PlayableSliceApplication の既存状態・既存処理
```

## Application Facade

`PlayablePartyMenuFacade` は、アイテム使用と装備変更に必要な既存サービス・ゲーム状態を型付き契約として公開します。

Presentation層は次を行いません。

- `party_member_lines()` の解析
- `equippable_options()` のラベル解析
- アイテム・装備private定義への直接アクセス
- 在庫数と装備数の独自計算

### パーティメンバー

`PartyMemberSummary` は次を保持します。

- キャラクターID
- レベル
- 現在HP / 最大HP
- 現在SP / 最大SP
- ATK / DEF / SPD
- 生存状態
- 状態効果ID
- 現在装備

表示ステータスには既存 `EquipmentService.resolve_final_stats()` の結果を使用します。

## アイテム使用

### アイテム一覧

`UsableItemSummary` は次を保持します。

- アイテムID
- 名称
- 説明
- 所持数
- 対象範囲
- 効果種別
- 効果値
- 解除対象状態効果

既存 `usable_item_ids()` とアイテム定義を利用し、所持数が1以上の消耗品だけを返します。

### 対象可否

対象メンバーごとに次を確認します。

- HP回復: HPが満タンではない
- SP回復: SPが満タンではない
- 状態異常回復: 解除可能な対象効果を保持している
- 対象範囲が既存仕様で対応している

`ItemTargetAvailability` に `can_use` と `reason_code` を保持します。

### 実行

決定時に在庫、アイテム、対象、効果適用可否を再確認し、既存 `PlayableSliceApplication.use_item()` を実行します。

成功後は在庫とメンバー状態からViewModelを再構築します。

## アイテム使用画面Controller

`ItemUseScreenController` は次の2モードを持ちます。

- `ITEM_LIST`
- `TARGET_LIST`

戻る操作:

- 対象一覧 → アイテム一覧
- アイテム一覧 → 親画面へ戻る要求

## 装備変更

### メンバーとスロット

`EquipmentSlotSummary` はスロット種別、現在装備ID、表示名を保持します。

対応スロットは既存 `VALID_SLOTS` と同じです。

- weapon
- armor
- accessory

### 装備候補

`EquipmentOptionSummary` は次を保持します。

- 装備ID
- 名称・説明
- スロット
- 所持数
- 全パーティの装備中個数
- 利用可能数
- 現在装備か
- 装備可能か
- 強化段階
- HP / SP / ATK / DEF / SPD補正
- パッシブ説明

利用可能数は次で算出します。

```text
所持数 - 全パーティでの装備中個数
```

現在装備と同じ装備は在庫余剰がなくても `no_change` として選択できます。

### 実行

決定時に次を再確認します。

- メンバー存在
- スロット妥当性
- 装備定義存在
- スロット一致
- 所持数と他メンバー装備数

その後、既存 `PlayableSliceApplication.equip_item()` を実行します。

## 装備画面Controller

`EquipmentScreenController` は次の3モードを持ちます。

- `MEMBER_LIST`
- `SLOT_LIST`
- `EQUIPMENT_LIST`

戻る操作:

- 装備候補 → スロット一覧
- スロット一覧 → メンバー一覧
- メンバー一覧 → 親画面へ戻る要求

## 入力

両画面とも次に対応します。

- 上移動
- 下移動
- 決定
- 戻る
- ガイド表示
- ID直接指定

無効項目で決定しても、別項目へ置き換えて実行しません。

## CLI接続

CLI固有の表示と数値入力は `game/app/cli/item_equipment_cli.py` に分離します。

- `SteamDemoFlowId.USE_ITEM`
- `SteamDemoFlowId.EQUIPMENT`

Steamデモ本体は上記アダプターをハンドラーとして登録するだけです。

## テスト観点

### 正常系

- アイテム一覧
- 対象一覧
- HP / SP回復
- 状態異常回復
- 在庫減算
- メンバー・スロット一覧
- 装備候補
- 装備変更
- 現在装備・最終ステータス更新

### 異常系

- 未知アイテム
- 在庫なし
- 未知対象
- HP / SP満タン
- 解除対象効果なし
- 未知メンバー
- 不正スロット
- 未知装備
- 在庫不足
- スロット不一致

### 境界値

- アイテム0件
- 使用可能対象0件
- パーティ0人
- 装備候補0件
- 利用可能数0
- 現在装備の再選択
- 各階層からの戻る

### 回帰

- ItemUse
- Equipment
- Inventory
- Party Status
- Set Bonus
- Save / Load
- SteamデモCLI
