# WORKSHOP SPECIAL CHAIN VERTICAL SLICE

## 概要
- 工房ランク3到達後に解放される特別依頼チェーンを最小実装。
- ミニボス討伐 → 上位装備作成 → 装備強化 → 報告 の4段階を1本の導線として提供。

## 実装ポイント
- `data/master/workshop_special_chains.sample.json` に静的なチェーン定義を追加。
- `WorkshopSpecialChainService` で段階進行・完了判定・最終報酬付与を管理。
- `PlayableSliceApplication` の工房NPC会話導線に統合し、進行ログを表示。
- Save/Load で `meta.workshop_special_chain_state` を保存・復元。

## CLI確認
- `python -m unittest tests.test_workshop_special_chain_slice -v`

## スコープ外
- 複数チェーン同時進行UI
- 章またぎ高難度エンドゲーム設計
