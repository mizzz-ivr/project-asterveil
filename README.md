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

## Repository Bootstrap Structure

- `game/` : ゲーム実装コードのルート
- `data/` : マスターデータ / セーブ契約 / サンプル定義
- `tools/` : データ検証や補助スクリプト
- `tests/` : テストコードとフィクスチャ
- `prototypes/` : 実験的実装（採用時に正式格納先へ移動）
