# Steam Demo Play Flow

## 1. 目的

既存の Playable Vertical Slice を、初見プレイヤーが New Game から一区切りまで迷わず進める Steam デモ向け体験へ接続する。

今回の実装は本格GUIやSteamworks連携ではなく、以下を検証するための製品化準備である。

- プレイヤーが次に行うべき操作を理解できるか
- Battle / Quest / Location / Workshop / Save が一つの体験としてつながるか
- Save / Load 後も適切な目標を提示できるか
- 将来のGUIクライアントでも同じ進行判定を再利用できるか

## 2. デモフロー

`data/master/demo_flows.sample.json` に、以下の6段階を定義する。

1. `accept_first_quest`: 最初の依頼を受注する
2. `travel_to_tidal_flats`: 対象ロケーションへ移動する
3. `win_first_battle`: 最初の戦闘に勝利する
4. `report_first_quest`: 完了した依頼を報告する
5. `inspect_workshop`: 工房とクラフトの入口を確認する
6. `save_demo_checkpoint`: デモチェックポイントを保存する

進行判定は定義順に行い、未完了の最初のステップを現在目標として表示する。
後続条件だけを満たしても、前段階を飛び越えて完了扱いにはしない。

## 3. 責務分離

### DemoFlowMasterDataRepository

配置:

- `game/app/infrastructure/demo_flow_repository.py`

責務:

- JSON定義の読み込み
- 必須項目、ID重複、条件形式、クエスト状態値の検証
- `DemoFlowDefinition` への変換

ゲーム状態の参照や進行更新は行わない。

### DemoFlowService

配置:

- `game/app/application/demo_flow_service.py`

責務:

- 受け取った `DemoFlowContext` を基に現在ステップを導出する
- 完了済みステップ、現在ステップ、全体完了を返す
- 表示層向けのガイダンス行を生成する

Battle / Quest / Crafting の実行ロジックは持たない。

### SteamDemoApplication

配置:

- `game/app/application/demo_flow_service.py`

責務:

- `PlayableSliceApplication` の既存状態から `DemoFlowContext` を構築する
- デモ用工房確認とチェックポイント保存を既存アプリへ接続する
- デモ進行サービスと既存ゲームループの境界を保つ

`PlayableSliceApplication` 本体へデモ専用ロジックを追加せず、外側から合成する。

### Steam Demo CLI

配置:

- `game/app/cli/run_steam_demo.py`

責務:

- New Game / Continue / Exit の入口を提供する
- 現在目標と推奨アクションを表示する
- 既存CLIの操作フローを再利用する
- 工房確認とチェックポイント保存のみデモ用処理へ振り分ける

## 4. Save / Load 方針

デモの進行状態を独立した保存データとして重複保持しない。

以下の既存状態から進行を再計算する。

- クエスト状態
- world flags
- 現在地
- 工房ランク

デモ固有操作として、以下の2フラグだけを既存 `world_flags` に保存する。

- `flag.demo.steam.workshop_checked`
- `flag.demo.steam.checkpoint_saved`

そのため、`save_data_v1` の構造変更やセーブバージョン更新は不要である。
チェックポイント保存では、保存処理を呼び出す前にフラグを反映し、同じ保存データへ確実に含める。

## 5. 実行方法

```bash
python -m game.app.cli.run_steam_demo
```

セーブ先を変更する場合:

```bash
python -m game.app.cli.run_steam_demo --save-path tmp/steam_demo_slot_01.json
```

フローIDを明示する場合:

```bash
python -m game.app.cli.run_steam_demo --flow-id demo.steam.ch01.core_loop
```

## 6. テスト

今回追加したテスト:

```bash
python -m unittest tests.test_demo_flow_slice -v
```

リポジトリ全体の回帰確認:

```bash
python -m unittest
```

主な確認観点:

- デフォルトフローの読み込み
- ID重複や未対応条件の検知
- 6段階の順次進行
- 後続条件による前段階の飛び越し防止
- 工房確認の順序外操作
- チェックポイントフラグの保存前反映
- New Game と最初のクエスト受注による実アプリ上の遷移
- 既存 Battle / Quest / Save / Playable / Workshop の回帰

## 7. 既知の制約

SteamデモCLIは差分を小さくするため、既存 `run_game_slice.py` のCLI補助関数を再利用している。
これはプレゼンテーション層内に限定した一時的な共有であり、ゲームドメインやアプリケーションサービスは依存していない。

GUIクライアント実装へ進む前に、入力アクションと表示用データの共通インターフェースを抽出する。

## 8. スコープ外

- 本格的なGUIタイトル画面
- Steamworks SDK連携
- コントローラ対応
- ローカライズ
- ストア提出用ビルド
- デモ専用の大規模シナリオ追加
- 既存ゲームシステムの大規模リファクタリング

## 9. 次の拡張

1. キーボード・コントローラを共通化する入力アクション層
2. アプリケーションサービスを利用する製品向けGUIシェル
3. デモの操作フローQAと進行不能チェックリスト
4. パッケージング、ログ、クラッシュ時案内の整備
