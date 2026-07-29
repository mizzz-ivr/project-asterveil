# Windows Steam Demo Build

## 1. 目的

Steam提出候補となるWindows x64向けSteamデモを、ローカルWindowsとGitHub Actionsで同じ手順から生成・検証する。

対象は`docs/PRODUCTION_GAP_BACKLOG.md`のM-3「配布/ビルド手順の最小確立（Steam向け）」である。

## 2. 成果物

Build後に以下を生成する。

```text
build/windows-release/
├─ project-asterveil-steam-demo-windows-x64/
│  ├─ ProjectAsterveilSteamDemo.exe
│  ├─ README_RELEASE.txt
│  ├─ BUILD_MANIFEST.json
│  └─ _internal/
│     └─ data/master/...
└─ project-asterveil-steam-demo-windows-x64.zip
```

Steam Depotへ投入する単位は、ZIP展開後の`project-asterveil-steam-demo-windows-x64`ディレクトリ配下とする。

## 3. 採用方式

### onedir

PyInstallerのonedir構成を採用する。

理由:

- 起動時の一時展開が不要
- Steamの差分配信で変更ファイルだけを扱いやすい
- DLL・マスターデータ・README・マニフェストを確認しやすい
- 不具合調査時に配布構成を比較しやすい

### Build依存の分離

ゲームRuntimeは外部Packageへ依存しない。

PyInstallerは`requirements-build.txt`だけに固定し、通常実行・Unit Testの依存へ混在させない。

## 4. ローカルBuild

### 前提

- Windows x64
- Python 3.11
- PowerShell

### Build依存の導入

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements-build.txt
```

### Build・検証

```powershell
python tools/build_windows_release.py `
  --output-root build/windows-release `
  --git-sha local `
  --version-label development
```

このコマンドで以下を連続実行する。

1. PyInstaller onedir Build
2. 配布フォルダ作成
3. exeの`--smoke-test`
4. `BUILD_MANIFEST.json`生成
5. 必須ファイルとSHA-256検証
6. ZIP生成
7. ZIP破損・必須ファイル検証

Smoke Testを一時的に省略する場合:

```powershell
python tools/build_windows_release.py --skip-smoke-test
```

提出候補Buildでは省略しない。

## 5. Smoke Test

配布exeはGUIを生成しない検証入口を持つ。

```powershell
.\ProjectAsterveilSteamDemo.exe --smoke-test
```

確認内容:

- 同梱`data/master`の解決
- Demo Flow Masterの読込
- `PlayableSliceApplication`構築
- Client Controller構築
- New Game開始
- Steam Demo Top Scene生成
- 一時セーブのみ使用

終了コード:

| Code | 意味 |
|---:|---|
| 0 | 成功 |
| 1 | 初期化・データ・導線検証失敗 |
| 2 | 通常GUI起動時のTkinter利用不可 |

Smoke TestはTkinter Windowを生成せず、ユーザーの通常セーブを変更しない。

## 6. ResourceとSave Path

### マスターデータ

ソース実行時:

```text
<repository>/data/master
```

PyInstaller実行時:

```text
<_MEIPASS>/data/master
```

### セーブデータ

Frozen Windows Buildでは次を既定値とする。

```text
%LOCALAPPDATA%\ProjectAsterveil\steam_demo_slot_01.json
```

配布フォルダ内へ書き込まないため、Steam Client配下やProgram Files配下でも書込権限に依存しない。

## 7. BUILD_MANIFEST.json

以下を記録する。

- Manifest Schema Version
- Build Script Version
- Application / Artifact名
- Git SHA
- Version Label
- Build日時UTC
- OS / Architecture
- Python Version
- PyInstaller Version
- 配布物全ファイルの相対Path
- File Size
- SHA-256

`BUILD_MANIFEST.json`自身は自己参照を避けるためHash対象外とする。

不具合報告時は、最低限`git_sha`と`version_label`を添付する。

## 8. GitHub Actions

Workflow:

```text
.github/workflows/windows-steam-demo-build.yml
```

実行条件:

- `main`への関連変更Push
- 関連Pathを変更するPull Request
- 手動`workflow_dispatch`

Job内容:

1. Windows Runner Checkout
2. Python 3.11固定
3. Build依存導入
4. Release Helper Test
5. Windows配布Build
6. exe Smoke Test
7. Manifest / ZIP検証
8. GitHub Actions Artifact Upload

Artifact保持期間は14日とする。

## 9. 成果物受入確認

### 自動確認

- Unit Test成功
- Windows Build成功
- exe Smoke Test成功
- 必須ファイル存在
- Manifest Hash一致
- ZIP破損なし

### 手動確認

自動検証後、Windows実機で以下を確認する。

- exeをダブルクリックしてタイトル画面が表示される
- New Gameが開始できる
- Settingsへ遷移できる
- セーブ後にContinueできる
- Exitで安全に終了できる
- `%LOCALAPPDATA%`へセーブされる
- 日本語表示が崩れない
- Windows Defender等の警告内容を記録する

GUI表示とOS警告はGitHub Actionsのヘッドレス検証だけでは保証しない。

## 10. 担当境界

### 開発担当

- Build Scriptとspec維持
- Build依存Version更新
- Smoke Test維持
- Manifest Schema維持
- CI失敗の一次解析

### QA担当

- Artifact取得
- Windows実機確認
- 主要導線確認
- Build Manifest記録
- 不具合と再現手順の報告

### リリース担当

- 提出対象Git SHAの確定
- コード署名確認
- Steam Depot投入
- Steamworks設定
- 公開可否判断

## 11. Version更新時のルール

PyInstaller、Python、GitHub ActionsのMajor Versionを変更する場合は、同一PRで以下を行う。

- Windows Build成功
- Smoke Test成功
- Artifact内容差分確認
- ManifestのVersion記録確認
- 実機起動確認結果の記載

理由のない最新版追従や、未固定Version指定は禁止する。

## 12. スコープ外

- コード署名
- Steamworks SDK
- SteamPipe Upload
- Installer / MSI
- 自動GitHub Release作成
- macOS / Linux Build
- 本番アイコン・スプラッシュ
- Bit-for-bit完全再現Build
