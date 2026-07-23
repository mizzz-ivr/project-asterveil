# NPC会話・フィールドイベント画面

## 目的

Steamデモで利用頻度の高いNPC会話とフィールドイベントを、CLI固有の選択処理から分離し、将来GUI・ゲームパッド・ポインター操作から共通利用できる画面契約へ移行します。

## 対象範囲

- 現在地のNPC一覧
- NPC会話開始
- 会話行と選択肢
- 選択肢によるフラグ・クエスト・会話効果
- 現在地のフィールドイベント一覧
- イベント実行可否
- イベント詳細と選択肢
- イベント結果と完了状態
- CLIアダプター

## 対象外

- GUIフレームワーク
- 立ち絵、アニメーション、音声
- マップ描画
- Steam Input API
- 他サブ画面の共通化

## 構成

```text
CLI / 将来GUI
  ↓
NpcDialogueScreenController
FieldEventScreenController
  ↓
PlayableInteractionFacade
  ↓
DialogueService / FieldEventService
PlayableSliceApplication の既存状態・既存処理
```

## Application Facade

`PlayableInteractionFacade` は、NPC会話とフィールドイベントに必要な既存サービス・ゲーム状態を型付き契約として公開します。

Presentation層は次を行いません。

- `talk_npc_options_lines()` の再解析
- `field_event_lines()` の再解析
- `field_event_choice_lines()` の再解析
- `_dialogue_service` や `_field_event_service` への直接アクセス

既存private serviceへの接続はApplication層のFacade内に限定します。

## NPC会話状態

### NPC一覧

`NpcSummary` は次を保持します。

- `npc_id`
- `npc_name`
- `location_id`

現在地に存在するNPCだけを返します。

### 会話開始

`start_dialogue(npc_id)` は、現在のフラグ・クエスト状態・現在地から優先度の高い会話エントリを解決します。

戻り値 `DialogueState` は次を保持します。

- NPC情報
- 会話エントリID
- 現在ステップID
- 話者
- 表示行
- 現在選択可能な選択肢
- 完了状態
- 適用済みログ

### 選択肢

`select_dialogue_choice()` は既存の `DialogueService.apply_choice()` を利用し、次を既存仕様どおり適用します。

- `set_flags`
- クエスト受注
- クエスト報告
- レシピ解放
- 戦闘開始
- 会話終了
- 工房進行

選択肢適用後は次ステップを型付き状態として返します。

### 完了

次の条件で会話を完了します。

- `end_dialogue` 効果
- 次ステップがない
- 次ステップに選択肢がない
- fallback会話または単一行会話

完了時は既存の会話後処理を維持します。

## NPC画面Controller

`NpcDialogueScreenController` は次の2モードを持ちます。

- `NPC_LIST`
- `DIALOGUE`

対応入力:

- 上下移動
- 決定
- 戻る
- ガイド表示
- NPC ID直接指定
- 選択肢ID直接指定

未知NPC・現在地外NPC・未知選択肢は別の項目へ置き換えず拒否します。

## フィールドイベント状態

### 一覧

`FieldEventSummary` は次を保持します。

- イベントID
- 名称
- 説明
- repeatable
- 完了状態
- 実行可否
- 理由コード

### 詳細

`field_event_detail(event_id)` は、現在地と最新状態で再検証し、実行可能なイベントだけ選択肢を返します。

### 実行

`execute_field_event_choice()` は、実行直前に既存 `FieldEventService.resolve_choice()` で次を検証します。

- イベント存在
- 現在地一致
- 完了済み非repeatableではない
- 必須・除外フラグ
- 選択肢存在

検証後は既存 `resolve_field_event_choice()` を呼び、アイテム、フラグ、戦闘、状態異常、宝箱解放、ミニボス等のoutcomeを適用します。

## フィールドイベント画面Controller

`FieldEventScreenController` は次の2モードを持ちます。

- `EVENT_LIST`
- `CHOICE_LIST`

イベント一覧では実行不能項目を無効化します。完了済み非repeatableイベントや条件未達イベントを決定しても実行しません。

## CLI接続

SteamデモCLIでは次のハンドラーを共通Controllerへ変更します。

- `SteamDemoFlowId.NPC_DIALOGUE`
- `SteamDemoFlowId.FIELD_EVENT`

CLI側の責務は表示、数値入力、キャンセル入力だけです。会話・イベントの状態判定はControllerとFacadeが担当します。

## テスト観点

### 正常系

- 現在地NPC一覧
- 会話開始
- 選択肢によるフラグ設定
- 選択肢によるクエスト受注
- 次ステップ表示
- イベント一覧
- イベント詳細
- イベント選択肢実行
- 完了状態更新

### 異常系

- 未知NPC
- 現在地外NPC
- 未知会話選択肢
- 未知イベント
- 未知イベント選択肢
- 完了済み非repeatableイベント
- 条件未達イベント

### 境界値

- NPCが0件
- イベントが0件
- 選択肢が0件
- 会話終了後の決定
- 一覧・詳細からの戻る

### 回帰

- Quest
- Battle
- Save / Load
- Workshop
- Field Event
- SteamデモCLI
