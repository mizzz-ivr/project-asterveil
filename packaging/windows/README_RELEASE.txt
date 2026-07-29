Project Asterveil Steam Demo - Windows x64
===========================================

起動方法
--------
ProjectAsterveilSteamDemo.exe を実行してください。

セーブデータ
------------
通常は次のユーザー書込可能領域へ保存します。

%LOCALAPPDATA%\ProjectAsterveil\steam_demo_slot_01.json

配布フォルダ内へセーブデータは作成しません。

動作確認
--------
配布物の初期化だけを確認する場合は、PowerShellから次を実行できます。

.\ProjectAsterveilSteamDemo.exe --smoke-test

終了コード0で、マスターデータ読込・Client構築・New Game・トップ画面生成が成功しています。

成果物検証
----------
BUILD_MANIFEST.json にBuild条件と配布フォルダ内ファイルのSHA-256を記録しています。

注意事項
--------
- 開発中のSteamデモ候補Buildです。
- コード署名、Steamworks SDK、SteamPipe Uploadは未対応です。
- 不具合報告時はBUILD_MANIFEST.jsonのgit_shaとversion_labelを添えてください。
