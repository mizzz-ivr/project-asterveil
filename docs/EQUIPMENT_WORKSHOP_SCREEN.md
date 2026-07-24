# 装備強化・装備分解画面

## 目的

Steamデモの装備強化・装備分解をCLI固有処理から分離し、将来GUI・キーボード・ゲームパッド・ポインター操作から共通利用できる画面契約へ移行します。

## 対象範囲

- 工房ランク
- 強化対象一覧
- 現在強化段階・最大段階
- 次段階の必要素材
- 次段階のステータス補正
- 強化可否と理由
- 分解対象一覧
- 所持数・装備中個数・利用可能数
- 強化段階に応じた返却素材
- 分解可否と理由
- CLIアダプター

## 対象外

- 通常装備変更
- 装備解除
- 一括強化・一括分解
- クラフト
- GUIフレームワーク
- Steam Input API

## 構成

```text
通常CLI / SteamデモCLI / 将来GUI
  ↓
EquipmentUpgradeScreenController
EquipmentSalvageScreenController
  ↓
PlayableEquipmentWorkshopFacade
  ↓
EquipmentUpgradeService
EquipmentSalvageService
PlayableSliceApplication の既存状態・既存処理
```

## Application Facade

`PlayableEquipmentWorkshopFacade` は既存Serviceの評価結果を型付き契約へ変換します。

Presentation層は次を行いません。

- `workshop_equipment_upgrade_lines()` の文字列解析
- `workshop_equipment_salvage_lines()` の文字列解析
- 必要素材や返却素材の独自計算
- 工房ランク判定の再実装
- 装備中個数の独自判定

## 装備強化

### UpgradeOptionSummary

次を保持します。

- 装備ID・名称・説明
- 所持数
- 現在段階・最大段階・次段階
- 現在工房ランク
- 必要工房ランク
- 強化可否
- 理由コード
- 必要素材の所持数／必要数
- 次段階のステータス補正

理由コードは既存 `EquipmentUpgradeService.evaluate_upgrade()` と同じです。

- `upgradable`
- `insufficient_materials`
- `insufficient_workshop_level`
- `max_level`
- `unknown_equipment`
- `upgrade_disabled`

### 実行

決定時に一覧を再構築し、最新の素材・工房ランク・強化段階を再評価します。

強化可能な場合だけ既存 `PlayableSliceApplication.upgrade_equipment()` を実行します。

成功後は次段階の必要素材・可否を含む最新ViewModelへ更新します。

## 装備分解

### SalvageOptionSummary

次を保持します。

- 装備ID・名称・説明・タグ
- 所持数
- パーティ全体の装備中個数
- 分解に利用できる個数
- 強化段階
- 現在工房ランク
- 必要工房ランク
- 分解可否
- 理由コード
- 返却素材

利用可能数は次で算出します。

```text
所持数 - パーティ全体の装備中個数
```

理由コードは既存 `EquipmentSalvageService.evaluate_salvage()` と同じです。

- `salvageable`
- `equipped`
- `not_owned`
- `insufficient_workshop_level`
- `unknown_equipment`
- `salvage_disabled`

### 実行

決定時に所持数・装備中個数・工房ランク・強化段階を再評価します。

分解可能な場合だけ既存 `PlayableSliceApplication.salvage_equipment()` を実行します。

強化済み装備では `upgrade_bonus_returns` を強化段階分加算します。最後の1個を分解した場合、既存仕様に従い装備ID単位の強化段階も削除します。

## 画面Controller

両画面は単一リスト画面です。

- 上移動
- 下移動
- 決定
- 戻る
- ガイド表示
- ID直接指定

強化・分解できない候補は表示対象に残し、理由を提示します。選択決定は無効化されます。

## CLI接続

`game/app/cli/equipment_workshop_cli.py` が表示と数値入力を担当します。

既存共通入口を新アダプターへ委譲するため、次の両方が同じControllerを利用します。

- `python -m game.app.cli.run_game_slice`
- `python -m game.app.cli.run_steam_demo`

## テスト観点

### 正常系

- 強化候補・必要素材・補正値表示
- 素材消費と強化段階更新
- 分解候補・返却素材表示
- 装備中の1個を残した余剰在庫分解
- 強化段階に応じた追加返却
- 最後の1個分解後の強化段階削除

### 異常系

- 未知装備
- 素材不足
- 工房ランク不足
- 最大強化
- 装備中で余剰なし
- 分解対象なし

### 境界値

- 候補0件
- 実行可能候補0件
- 利用可能数0
- 現在段階0／最大段階
- 強化段階付き装備の最後の1個
- 戻る・ガイド

### 回帰

- Equipment Upgrade
- Equipment Salvage
- Equipment
- Inventory
- Workshop Progress
- Set Bonus
- Save / Load
- 通常CLI
- SteamデモCLI
