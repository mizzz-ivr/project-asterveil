# 章コンテンツパック量産パイプライン

## 目的
章・クエスト・イベントを既存Masterへ直接追記せず、レビュー可能な独立パックとして作成・検証する。

## 基本フロー
1. `init`で章パックを作成する
2. Quest / Event / Encounter / Location / Conversationを記述する
3. `validate`で契約を検証する
4. `generate`でMaster候補とSummaryを生成する
5. 旧版がある場合は`diff`で互換性リスクを確認する
6. レビュー後に正式Masterへ手動反映する

## コマンド
```bash
python tools/chapter_content_pack.py init \
  --chapter-id ch03 \
  --title "第三章" \
  --output content/packs/ch03/pack.json

python tools/chapter_content_pack.py validate \
  content/packs/ch03/pack.json

python tools/chapter_content_pack.py generate \
  content/packs/ch03/pack.json \
  --output tmp/generated-content/ch03

python tools/chapter_content_pack.py diff \
  old.json new.json \
  --output tmp/ch03-diff.json
```

## 検証内容
- `chNN`形式の章ID
- 永続IDの文字種と章Namespace
- 全Kind横断のID重複
- QuestからEncounter / Locationへの参照
- Quest前提条件の循環
- Objective ID重複
- `objective_sequence`と`next_objective_id`の整合
- Event遷移先の存在
- 高すぎるEXP報酬の警告
- 旧版から削除された永続IDの互換性リスク

## 生成物
- `quests.generated.json`
- `events.generated.json`
- `encounters.generated.json`
- `locations.generated.json`
- `conversations.generated.json`
- `CONTENT_PACK_MANIFEST.json`
- `SUMMARY.md`

## レビュー観点
- 既存IDをリネームしていないか
- Quest前提経路が意図した順序になっているか
- Objective順序変更が既存セーブへ影響しないか
- EXP / Gold / Item報酬が章内で突出していないか
- 想定プレイ時間とQuest数が不自然でないか
- 参照先を同じ章パックへ含めるべきか、既存Master参照として扱うべきか

## 運用上の注意
- 生成物を直接編集しない。
- 既存IDをリネームしない。
- 生成物は自動で正式Masterへマージしない。
- Objective順序変更は既存進行へ影響するため、Save Migration要否を別途判断する。
- サンプル`ch02`はパイプライン説明用であり、完成シナリオではない。
