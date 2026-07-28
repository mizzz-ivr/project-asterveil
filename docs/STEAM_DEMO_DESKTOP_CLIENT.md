# Steam Demo Desktop Client

## 1. 目的

SteamデモをCLIではなく最小デスクトップウィンドウから開始・再開・操作できるようにする。

本実装は製品版UIではなく、`PRODUCTION_GAP_BACKLOG.md` のM-1「Steamデモ向け最小クライアント導線整備」を前進させる検証用クライアントである。

## 2. 対象範囲

- タイトル画面
- New Game
- Continue
- Settings
- Exit
- 全14Routeの共通Scene描画
- Scene Entryクリック
- 上下・決定・戻る・ガイドの意味入力
- 操作ログと入力ヒントの表示切替
- 文字サイズ切替
- Gameplay内のExitによるタイトル復帰

## 3. アーキテクチャ

```text
Tkinter Window
  ↓ ViewModel / UiCommandのみ参照
SteamDemoClientController
  ↓
SteamDemoSessionComposition
  ├─ Screen Router
  ├─ Screen Runtime
  ├─ Scene Builder Registry
  └─ Scene Action Dispatcher
       ↓
各Screen Controller
       ↓
PlayableSliceApplication
```

### 責務

#### SteamDemoClientController

- タイトル、設定、ゲームプレイ、終了のPhase管理
- New Game / Continueの実行
- ゲームプレイCompositionの生成・破棄
- Scene Commandと意味入力のDispatcher委譲
- RuntimeのExit要求によるタイトル復帰
- クライアント表示用ログと通知の保持

ゲームルール、Route遷移、Controller生成、Scene変換は担当しない。

#### SteamDemoTkWindow

- Client ViewModelのWidget変換
- SceneのTitle / Status / Section / Entry描画
- UiCommand DescriptorからButtonを生成
- 表示専用EntryをLabelとして描画
- キーボードイベントをMenuInputActionへ変換
- ウィンドウ終了要求の通知

Route別Controller型、ゲームルール、セーブ形式は参照しない。

## 4. Client Phase

```text
TITLE
  ├─ New Game  → GAMEPLAY
  ├─ Continue  → GAMEPLAY
  ├─ Settings  → SETTINGS
  └─ Exit      → EXITED

SETTINGS
  └─ Back      → TITLE

GAMEPLAY
  ├─ Scene操作 → GAMEPLAY
  ├─ Cancel    → Runtime内Route Pop
  └─ Top Exit  → TITLE
```

ウィンドウの閉じる操作は現在Phaseに関係なく`EXITED`へ遷移し、保持中のCompositionを破棄する。

## 5. タイトル導線

### New Game

1. `PlayableSliceApplication.new_game()`を実行する
2. 成功後に`SteamDemoCompositionRoot.build()`を実行する
3. Gameplay Phaseへ遷移する
4. Top MenuのInteractive Sceneを表示する

Composition生成に失敗した場合はタイトルに留まり、Runtimeを保持しない。

### Continue

1. セーブファイルの存在を確認する
2. `PlayableSliceApplication.continue_game()`へ読込を委譲する
3. 読込成功後にCompositionを生成する
4. Gameplay Phaseへ遷移する

JSON破損や整合性エラー時はタイトルに留まり、通知とログを表示する。

Continueボタンの有効状態はセーブファイルの存在で判定する。内容の妥当性は既存ロード処理が検証する。

## 6. Settings

現在の設定項目はクライアント表示だけに影響する。

- 文字サイズ: 100% / 125% / 150%
- 操作ログの表示
- 入力ヒントの表示

設定はゲームセーブへ混在させず、現時点ではセッション内のみ保持する。

設定永続化はスコープ外とし、将来追加する場合もゲーム進行セーブとは別契約にする。

## 7. Scene共通描画

Tkinter側はRoute別分岐を持たない。

```text
SteamDemoInteractiveScene
  ├─ scene
  │   ├─ title / subtitle
  │   ├─ status
  │   ├─ sections
  │   └─ action_hints
  └─ commands
      ├─ section_id
      ├─ label
      ├─ enabled
      ├─ selected
      └─ SteamDemoUiCommand
```

Scene EntryとCommand Descriptorが対応する場合はButtonとして描画する。

対応するCommandがないEntryは表示専用Labelとして描画する。NPC会話本文や宿屋のパーティ状態はこの扱いになる。

Scene Sectionに存在しない明示Commandは「操作」Sectionへ描画する。宿屋の`stay`が該当する。

## 8. 入力

| 物理入力 | 意味入力 |
|---|---|
| ↑ / W | MOVE_UP |
| ↓ / S | MOVE_DOWN |
| Enter / Space | CONFIRM |
| Esc / Backspace | CANCEL |
| F1 / G | SHOW_GUIDE |

物理入力はTkinterアダプターでのみ扱い、Controllerには`MenuInputAction`を渡す。

## 9. Tkinterの扱い

Tkinterは`tk_steam_demo.py`のモジュール読込時にはimportしない。

実際にウィンドウを生成する時点で遅延importするため、ディスプレイを持たないCI環境でもClient Controllerと整形処理をテストできる。

Tkinterモジュール未導入、またはディスプレイ初期化失敗時は`TkinterUnavailableError`へ変換し、Runnerが終了コード2を返す。

## 10. 実行方法

```bash
python -m game.app.client.run_tk_steam_demo
```

セーブパスを指定する場合:

```bash
python -m game.app.client.run_tk_steam_demo \
  --save-path tmp/steam_demo_slot_01.json
```

Windows版の標準CPythonでは通常Tkinterが同梱される。

Linux環境ではPython配布方法によってTkinterパッケージが別途必要になる場合がある。

## 11. テスト

```bash
python -m unittest tests.test_steam_demo_client -v
```

全体回帰:

```bash
python -m unittest
```

主な確認項目:

- セーブなしのContinue無効化
- New Game後のTop Scene表示
- Continue失敗時のタイトル維持
- Settingsの入力検証
- Scene Entryと意味入力のDispatcher経路
- Sub RouteからのCancel
- Gameplay Exitによるタイトル復帰
- Save後の別ClientからのContinue
- Client ViewModelのJSON互換化
- TkinterウィンドウなしでのScene文字列整形

## 12. 影響範囲

変更は以下に限定する。

- `game/app/client`
- Clientテスト
- README
- 本設計文書

Application、ドメイン、マスターデータ、既存Controller、Route、Renderer、Action Dispatcher、ゲームセーブ形式は変更しない。

## 13. リスクと今後

### 現在の制約

- 本番アートやアニメーションはない
- 全Routeを汎用レイアウトで描画する
- ゲームパッド実機入力は未対応
- 設定は永続化しない
- 配布用実行ファイルは未作成

### 次工程候補

1. 最小GUIの実機回帰と操作性調整
2. ゲームパッド入力アダプター
3. 設定の独立永続化
4. PyInstaller等によるWindows配布手順
5. Route単位の専用レイアウトを必要性に応じて段階導入
