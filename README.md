# project-asterveil
Project Asterveil は、重厚で感動的な長編ストーリー、戦略性の高いコマンドバトル、豊富な育成要素、大量のエンドコンテンツ、フレンド協力機能を備えた、Steam / App Store / Google Play 向けのオリジナルRPGプロジェクトです。

## Documentation Flow (設計 → 計画 → 技術基盤)

### 1) 企画・ゲームデザイン
- [AGENTS運用ガイド](./AGENTS.md)
- [Design Proposal (JRPG)](./DESIGN_PROPOSAL_JRPG.md)

### 2) 実行計画・優先度・マイルストーン
- [MVP Execution Plan](./docs/MVP_EXECUTION_PLAN.md)
- [Delivery Backlog](./docs/DELIVERY_BACKLOG.md)
- [Milestone Roadmap (0-6 months)](./docs/MILESTONE_ROADMAP.md)
- [Release Readiness Assessment](./docs/RELEASE_READINESS_ASSESSMENT.md)
- [Release Scope Options](./docs/RELEASE_SCOPE_OPTIONS.md)
- [Production Gap Backlog](./docs/PRODUCTION_GAP_BACKLOG.md)
- [Steam Demo Play Flow](./docs/STEAM_DEMO_PLAY_FLOW.md)
- [Input Action / Presentation Contract](./docs/INPUT_ACTION_PRESENTATION_CONTRACT.md)
- [Shared Action / Screen Controller](./docs/SHARED_ACTION_SCREEN_CONTROLLER.md)
- [Steam Demo Screen Router](./docs/STEAM_DEMO_SCREEN_ROUTER.md)
- [Steam Demo ScreenFactory / Composition Root](./docs/STEAM_DEMO_COMPOSITION_ROOT.md)
- [Steam Demo Screen Runtime](./docs/STEAM_DEMO_SCREEN_RUNTIME.md)
- [Steam Demo Screen Renderer](./docs/STEAM_DEMO_SCREEN_RENDERER.md)
- [Steam Demo Screen Action Dispatcher](./docs/STEAM_DEMO_SCREEN_ACTION_DISPATCHER.md)
- [Steam Demo Desktop Client](./docs/STEAM_DEMO_DESKTOP_CLIENT.md)
- [Save Compatibility Policy](./docs/SAVE_COMPATIBILITY_POLICY.md)
- [Quest Board / Travel Screen](./docs/QUEST_BOARD_TRAVEL_SCREEN.md)
- [NPC Dialogue / Field Event Screen](./docs/NPC_DIALOGUE_FIELD_EVENT_SCREEN.md)
- [Gathering / Treasure Screen](./docs/GATHERING_TREASURE_SCREEN.md)
- [Item Use / Equipment Screen](./docs/ITEM_EQUIPMENT_SCREEN.md)
- [Equipment Upgrade / Salvage Screen](./docs/EQUIPMENT_WORKSHOP_SCREEN.md)
- [Shop / Crafting / Inn Screen](./docs/ECONOMY_FACILITY_SCREEN.md)

### 3) Vertical Slice 実装の技術基盤
- [Technical Foundation](./docs/TECHNICAL_FOUNDATION.md)
- [Content Schema](./docs/CONTENT_SCHEMA.md)
- [Implementation Guidelines](./docs/IMPLEMENTATION_GUIDELINES.md)
- [Quest Vertical Slice](./docs/QUEST_VERTICAL_SLICE.md)
- [Quest Board Vertical Slice](./docs/QUEST_BOARD_VERTICAL_SLICE.md)
- [Save Vertical Slice](./docs/SAVE_VERTICAL_SLICE.md)
- [Playable Vertical Slice](./docs/PLAYABLE_VERTICAL_SLICE.md)
- [Equipment Vertical Slice](./docs/EQUIPMENT_VERTICAL_SLICE.md)
- [Equipment Salvage Vertical Slice](./docs/EQUIPMENT_SALVAGE_VERTICAL_SLICE.md)
- [Party Menu Vertical Slice](./docs/PARTY_MENU_VERTICAL_SLICE.md)
- [Workshop Order Vertical Slice](./docs/WORKSHOP_ORDER_VERTICAL_SLICE.md)

## Steamデモ実行

### デスクトップクライアント

```bash
python -m game.app.client.run_tk_steam_demo
```

Tkinterを利用できない環境では、以下のCLI版を利用します。

### CLI

```bash
python -m game.app.cli.run_steam_demo
```

## セーブ互換確認・移行

Dry Run:

```bash
python -m game.save.cli.migrate_save path/to/save.json --dry-run
```

バックアップを作成して現在Versionへ移行:

```bash
python -m game.save.cli.migrate_save path/to/save.json
```

詳細は[Save Compatibility Policy](./docs/SAVE_COMPATIBILITY_POLICY.md)を参照してください。

個別テスト:

```bash
python -m unittest tests.test_demo_flow_slice tests.test_input_action_presentation tests.test_shared_action_screen_controller tests.test_screen_router tests.test_screen_runtime tests.test_screen_runtime_initialization tests.test_screen_renderer tests.test_screen_action_dispatcher tests.test_steam_demo_composition tests.test_steam_demo_client tests.test_save_slice tests.test_save_migration tests.test_quest_travel_screen tests.test_npc_field_event_screen tests.test_gathering_treasure_screen tests.test_item_equipment_screen tests.test_equipment_workshop_screen tests.test_economy_facility_screen -v
```

## Repository Bootstrap Structure

- `game/` : ゲーム実装コードのルート
- `data/` : マスターデータ / セーブ契約 / サンプル定義
- `tools/` : データ検証や補助スクリプト
- `tests/` : テストコードとフィクスチャ
- `prototypes/` : 実験的実装（採用時に正式格納先へ移動）
