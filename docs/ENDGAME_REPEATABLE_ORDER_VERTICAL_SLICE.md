# ENDGAME_REPEATABLE_ORDER_VERTICAL_SLICE

## 今回の実装
- `flag.workshop.special_chain.rank3.completed` を解放条件にした準エンドゲーム用 repeatable 高難度依頼を追加。
- objective は `defeat_miniboss` / `craft_equipment` / `upgrade_equipment` / `activate_set_bonus` を最小構成で接続。
- 工房NPC会話導線で、未解放・解放・進行・完了・再受注可能をログで確認できるようにした。
- Save/Load に `endgame_repeatable_order_state` を追加し、解放状態・受注状態・進捗・再受注状態を保持。

## 接続先
- Workshop Special Chain: 完了フラグを解放条件として使用。
- Field Miniboss: 再討伐 objective 判定に使用。
- Advanced Crafting / Equipment Upgrade / Equipment Set Bonus: 各 objective 判定に使用。
- Playable Slice: `talk_to_npc` と `travel_to(拠点帰還)` に統合。

## 実行方法
- `python -m unittest tests.test_endgame_repeatable_order_slice`
- `python -m unittest`

## 今回のスコープ外
- ランダム依頼生成
- 周回ランクの段階拡張
- 週替わり/日替わり更新

## 次の拡張ポイント
- 依頼ランク段階（tier）追加
- 報酬テーブルによる周回バランス調整
- 工房UIログを明示的なコマンドメニューへ昇格
