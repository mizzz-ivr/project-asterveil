# ショップ・クラフト・宿屋画面

## 目的

Steamデモのショップ・クラフト・宿屋をCLI固有処理から分離し、通常CLI・SteamデモCLI・将来GUIから共通利用できる画面契約へ移行します。

## 対象範囲

- ショップ情報と施設レベル
- 所持金、販売品、価格、所持数
- 商品購入可否
- 可視レシピ一覧
- レシピの解放・発見・工房ランク状態
- 必要素材と出力
- クラフト可否
- 宿屋情報、料金、回復方針
- パーティの回復対象状態
- 宿泊可否
- CLIアダプター

## 対象外

- 購入数量選択
- クラフト回数選択
- アイテム売却
- 複数ショップ・宿屋の選択画面
- GUIフレームワーク
- Steam Input API

現行Vertical Sliceの仕様を維持し、購入数量とクラフト回数は1固定です。

## 構成

```text
通常CLI / SteamデモCLI / 将来GUI
  ↓
ShopScreenController
CraftingScreenController
InnScreenController
  ↓
PlayableEconomyFacilityFacade
  ↓
ShopService / CraftingService / InnService
PlayableSliceApplication の既存状態・既存処理
```

## Application Facade

`PlayableEconomyFacilityFacade` は、経済・施設画面に必要な状態を型付き契約として公開します。

Presentation層は次を行いません。

- `shop_catalog_lines()` の解析
- `crafting_recipe_lines()` の解析
- `inn_info_lines()` の解析
- ショップ在庫解放条件の再実装
- レシピ解放・工房ランク・発見条件の独自判定
- 宿泊後の回復・状態解除の独自実装

## ショップ

### ShopSummary

次を保持します。

- ショップID・名称・説明
- 雑貨店施設レベル
- 所持金
- 現在販売可能な商品

施設進行で未解放の商品は一覧へ含めません。

### ShopItemSummary

次を保持します。

- 商品ID・名称・説明
- 価格
- 在庫種別
- 現在所持数
- 購入可否
- 理由コード

主な理由コード:

- `purchasable`
- `insufficient_gold`
- `invalid_price`

直接指定された商品は実行直前に次を再確認します。

- ショップ存在
- 商品が販売定義に存在
- 施設進行による在庫解放
- 所持金

成功時は既存 `buy_item()` を数量1で実行します。

## クラフト

### CraftRecipeSummary

次を保持します。

- レシピID・名称・説明
- カテゴリ・Tier
- 必要工房ランク・現在工房ランク
- レシピ自体の発見済み状態
- 必須レシピ帳などの発見条件充足状態
- 解放状態
- クラフト可否
- 理由コード
- ミニボス素材の必要有無
- 必要素材
- 出力

`is_discovered` と `discovery_requirement_met` は別の状態です。

- `is_discovered`: レシピIDが発見済みか
- `discovery_requirement_met`: 必須レシピ帳などの条件を満たしているか

これらを混同しないことで、基礎レシピと上位レシピの表示状態を正しく扱います。

### 理由コード

主な理由コード:

- `craftable`
- `missing_material`
- `required_workshop_rank_missing`
- `required_recipe_discovery_missing`
- `required_flag_missing`
- `required_quest_missing`
- `required_location_missing`
- `recipe_locked`

実行直前に最新の素材、レシピ解放、施設ランク、工房ランク、発見条件を再評価します。

成功時は既存 `craft_recipe()` を回数1で実行し、既存のクエストクラフト進捗も維持します。

## 宿屋

### InnSummary

次を保持します。

- 宿屋ID・名称・説明・定義上の所在地
- 宿泊料金
- 所持金
- 戦闘不能メンバーを復活させるか
- 宿泊可否
- 理由コード
- パーティメンバーのHP/SP、生存状態、休息解除対象効果

現行Application仕様では現在地による宿泊制限を行っていないため、本画面でも新たな所在地制約は追加しません。

### 宿泊時の既存副作用

成功時は既存 `stay_at_inn()` を実行し、次を維持します。

- 所持金の減算
- 戦闘不能メンバーの復活
- 装備補正後の最大HP/SPまで回復
- `clear_on_rest=true` の状態効果解除
- `on_rest` 採取ポイントの再出現
- `on_rest` の繰り返しクエスト更新

## 画面Controller

### ShopScreenController

単一の商品一覧画面です。

### CraftingScreenController

可視レシピの単一一覧画面です。未解放・素材不足レシピも状態確認用に表示し、決定は無効化します。

### InnScreenController

宿屋情報と「宿泊する」操作を表示します。宿泊不能時は操作を無効化します。

3画面とも次に対応します。

- 上下移動
- 決定
- 戻る
- ガイド表示
- ID直接指定

無効項目の決定や未知ID指定で、別項目へ置き換えて実行しません。

## CLI接続

`game/app/cli/economy_facility_cli.py` が表示と数値入力を担当します。

`run_game_slice.py` の既存共通入口を新アダプターへ委譲するため、次の両方が同じControllerを利用します。

- 通常Playable Vertical Slice CLI
- SteamデモCLI

## テスト観点

### ショップ

- 商品一覧・価格・所持数
- 正常購入と所持金・在庫更新
- 所持金不足
- 施設レベル未解放商品
- 未知商品

### クラフト

- 発見状態と発見条件の分離
- 解放・工房ランク・素材状態
- 正常クラフトと素材消費・成果物付与
- 素材不足
- 未解放レシピ
- 未知レシピ

### 宿屋

- 料金・所持金・回復対象表示
- 正常宿泊
- HP/SP回復
- 戦闘不能復活
- 休息解除効果
- 採取ポイント再出現
- 所持金不足
- 空パーティ
- 未知宿屋

### 回帰

- Shop
- Crafting
- Inventory
- Facility Progression
- Workshop Progress
- Inn
- Gathering Respawn
- Repeatable Quest
- Save / Load
- 通常CLI
- SteamデモCLI
