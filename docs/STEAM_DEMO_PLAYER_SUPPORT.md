# Steam Demo Player Support

## 1. 目的

SteamデモのShould項目である以下を、Client／Support層に限定して実装する。

- S-1: パッド対応・入力切替
- S-2: 初回チュートリアル・導線文言
- S-3: クラッシュ収集・ログ運用の一次対応

ゲームルール、Domain、既存Controller、Runtime、Scene、セーブ契約は変更しない。

```text
物理入力
  ├─ Keyboard
  └─ Windows XInput Gamepad
          ↓
InputBindingProfile / GamepadInputInterpreter
          ↓
MenuInputAction
          ↓
既存Client Controller / Action Dispatcher
```

## 2. 追加要素

### 2.1 Windows XInput

標準ライブラリ`ctypes`で以下のDLLを順に探索する。

1. `xinput1_4`
2. `xinput1_3`
3. `xinput9_1_0`

取得できない環境では`NullGamepadBackend`へフォールバックし、キーボード操作を継続する。

対応入力:

| 物理入力 | 意味入力 |
|---|---|
| D-pad上／左スティック上 | MOVE_UP |
| D-pad下／左スティック下 | MOVE_DOWN |
| A | CONFIRM |
| B | CANCEL |
| Y | SHOW_GUIDE |

移動操作だけ長押しリピートを許可する。決定・戻る・ガイドは押下エッジで一度だけ実行する。

既定値:

- Stick deadzone: 12000
- Repeat delay: 420ms
- Repeat interval: 130ms
- Poll interval: 50ms

切断時は押下状態を破棄し、表示とActive Deviceをキーボードへ戻す。

## 3. 入力方式の自動切替

最後に意味入力を発生させたデバイスを`InputDeviceTracker`で保持する。

- キーボード操作後: キーボードヒント
- ゲームパッド操作後: A／B／Y等のゲームパッドヒント
- ゲームパッド切断後: キーボードヒント

両方のヒントを同時表示せず、現在利用中の入力方式を優先する。

## 4. 初回ガイドとヘルプ

ゲーム進行セーブとは別の`client_settings.json`で完了状態を保持する。

初回起動時は以下の9章を表示する。

1. Project Asterveilへようこそ
2. 基本操作
3. 現在目標と推奨操作
4. 依頼の受注と報告
5. 移動と探索
6. 戦闘の進め方
7. 工房・クラフト・装備
8. セーブとContinue
9. トラブルシューティング

ガイドはタイトル画面、F1／G、ゲームパッドYから再表示できる。

Route別対応:

| Route | Guide |
|---|---|
| top_menu | welcome |
| quest_board | quest |
| travel / gathering / treasure / field_event / npc_dialogue | travel |
| battle | battle |
| shop / crafting / equipment_upgrade / equipment_salvage | workshop |
| その他 | objectives |

ガイドを開閉してもゲーム状態は変更しない。

## 5. アクセシビリティ

追加設定:

- ハイコントラスト表示
- 低モーション表示
- ゲームパッド有効／無効
- Route別ヒント表示
- ローカル診断ログ有効／無効
- 初回ガイド再表示

`reduced_motion`は、現在のTkinterクライアントにアニメーションがないため、将来の画面効果を追加する際の「無効化契約」として先に保持する。

## 6. 設定保存

保存先:

```text
Frozen Windows:
%LOCALAPPDATA%\ProjectAsterveil\support\client_settings.json

Source実行:
<repository>/tmp/steam-demo-support/client_settings.json
```

保存は一時ファイル、`fsync`、`os.replace`で原子的に行う。

設定が不正JSON、型不正、未知Versionの場合:

1. 不正ファイルを`*.invalid-<UTC>.json`へ退避
2. 既定設定を生成
3. クライアントを継続起動
4. 診断ログへ復旧理由を記録

## 7. 構造化ログ

`support/diagnostics/session-<session-id>.ndjson`へ保存する。

各行には以下を持つ。

- UTC timestamp
- Session ID
- Severity
- Category
- Event name
- Message
- Context

既定ローテーション:

- 1ファイル最大1MB
- 最大5ファイル

次のKey名は値を`[REDACTED]`へ置換する。

- token
- secret
- password
- authorization
- cookie
- api_key

Home Directoryは`~`へ置換する。外部送信は行わない。

## 8. クラッシュレポート

未処理例外またはTk callback例外時に、`support/crashes/`へJSONを作成する。

- Exception type
- Message
- Traceback
- Client phase
- Route ID
- Runtime environment
- Session ID
- 発生操作

可能な場合はクライアント内に保存先を表示し、無言終了を避ける。

## 9. サポートZIP

タイトル、Settings、またはCLIから手動生成する。

```bash
python -m game.app.client.run_tk_steam_demo \
  --export-support-bundle
```

含めるもの:

- NDJSONログ
- Crash Report
- Client設定
- Runtime環境
- SUPPORT_MANIFEST
- セーブのメタデータ

含めないもの:

- セーブファイル本体
- 認証Token
- 秘密情報
- 自動収集した個人情報

セーブメタデータは以下だけを保持する。

- ファイル名
- サイズ
- SHA-256
- save_version
- 更新日時

自動Uploadは行わない。利用者またはQA担当者が内容を確認してからIssueへ添付する。

## 10. CLI

通常起動:

```bash
python -m game.app.client.run_tk_steam_demo
```

ゲームパッドを一時無効化:

```bash
python -m game.app.client.run_tk_steam_demo --disable-gamepad
```

初回ガイドを再表示:

```bash
python -m game.app.client.run_tk_steam_demo --reset-tutorial
```

保存先を指定:

```bash
python -m game.app.client.run_tk_steam_demo \
  --support-root tmp/support
```

GUIなしSmoke Test:

```bash
python -m game.app.client.run_tk_steam_demo \
  --smoke-test \
  --support-root tmp/support-smoke
```

Smoke TestではNew Game、Top Scene、9章Guide、設定Versionを確認する。

## 11. QA Checklist v2

v1の20 Caseを維持し、Player Supportの11 Caseを追加する。

```bash
python tools/steam_demo_qa_v2.py validate --json
python tools/steam_demo_qa_v2.py materialize \
  --output tmp/checklist_v2.json
```

既存QA Toolへ渡す。

```bash
python tools/steam_demo_qa.py \
  --checklist tmp/checklist_v2.json \
  init \
  --manifest path/to/BUILD_MANIFEST.json \
  --output-dir qa/runs/<run-id> \
  --tester tester-name \
  --os-name Windows \
  --os-version "11 24H2" \
  --architecture x64 \
  --resolution 1920x1080 \
  --dpi-scale 100 \
  --input keyboard_mouse \
  --input gamepad
```

追加領域:

- XInput接続・入力表示切替
- D-pad／Stick／A／B／Y
- 長押し・切断・再接続
- 初回ガイドと再表示
- Route別ガイド
- ハイコントラスト・文字サイズ
- 設定破損復旧
- NDJSONと秘匿
- Crash Report
- Support ZIP Privacy
- GUIなしSupport ZIP

## 12. テスト

```bash
python -m unittest \
  tests.test_player_support \
  tests.test_player_support_qa \
  -v
```

CIではBackendを差し替えてヘッドレス確認する。実機XInput、DPI、ゲームパッド機種差はWindows手動QAで確認する。

## 13. 影響範囲

変更対象:

- Client adapter
- Input adapter
- Guide／Support settings
- Diagnostics
- QA v2
- Documentation／Workflow

変更しないもの:

- Domain
- Game rules
- Application serviceの進行処理
- Screen Controller
- Screen Runtime
- Scene契約
- Save Data契約

## 14. 既知の制約

- Steam Input APIは未使用
- Xbox系XInput Glyphのみ
- PlayStation／Nintendo固有表示は未対応
- 実機ゲームパッドはCIで検証できない
- 診断情報のSaaS送信は未対応
- ゲーム内キーコンフィグUIは未対応
