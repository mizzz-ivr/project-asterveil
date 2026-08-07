# モンスター図鑑・戦闘記録仕様

## 目的

既存の戦闘・探索ループへ収集目標を追加し、敵との遭遇・討伐履歴に応じて攻略情報を段階的に解放する。

## 設計方針

- 戦闘ルールと `BattleResult` 契約は変更しない。
- 図鑑は既存 Battle Executor の結果を記録するだけとする。
- 戦闘用 `enemies.sample.json` と図鑑表示用 `enemy_bestiary.sample.json` の責務を分ける。
- レベル、能力値、弱点は戦闘用Masterを正本とし、図鑑Masterへ複製しない。
- Save Versionは1のまま維持し、`meta.bestiary_state`として後方互換に追加する。
- 未遭遇の敵名、ID、生息地、能力値、弱点、説明を画面表示へ出さない。
- 既存 `PlayableSliceApplication` 本体へ図鑑責務を追加せず、継承拡張へ閉じ込める。

## 情報解放段階

| 段階 | 条件 | 表示内容 |
| --- | --- | --- |
| `unknown` | 未遭遇 | `？？？` のみ |
| `encountered` | 遭遇数が1以上 | 名前、生息地、戦闘記録 |
| `defeated` | 討伐数が1以上 | 上記 + レベル、能力値、弱点 |
| `mastered` | 討伐数が `mastery_kill_count` 以上 | 上記 + 詳細説明 |

`mastery_kill_count` は敵ごとに図鑑Masterで定義する。

## 戦闘記録

敵種ごとに以下を保存する。

- `encounter_count`: 実際にEncounterへ出現した個体数の累計
- `battle_win_count`: その敵種を含む戦闘に勝利した回数
- `kill_count`: `BattleResult.defeated_enemy_ids`に含まれた討伐数
- `battle_loss_count`: その敵種を含む戦闘に敗北した回数

同一Encounterに同じ敵が複数体いる場合、`encounter_count`は個体数分を加算する。勝敗数は戦闘単位で1回だけ加算する。

## Master Data

### `enemy_bestiary.sample.json`

図鑑表示固有情報のみを管理する。

- `enemy_id`
- `display_name`
- `category`: `normal` / `boss`
- `habitat_location_ids`
- `description`
- `mastery_kill_count`

起動時に以下を検証する。

- 戦闘用Enemyと図鑑EnemyのID集合が一致すること
- Enemy ID、Location ID、Encounter参照が解決できること
- Encounterの出現数が正の整数であること
- Categoryが許可値であること
- 熟練討伐数が正の整数であること

## Save契約

```json
{
  "meta": {
    "bestiary_state": {
      "version": 1,
      "records": {
        "enemy.ch01.port_wraith": {
          "encounter_count": 2,
          "battle_win_count": 1,
          "kill_count": 2,
          "battle_loss_count": 0
        }
      }
    }
  }
}
```

### 復元ルール

- `bestiary_state`が存在しない旧Saveは空の図鑑として読み込む。
- 図鑑State Versionが未知の場合は拒否する。
- 負数、非整数、不整合な既知Enemy記録は拒否する。
- Master更新で存在しなくなった未知Enemy IDは無視し、ゲーム進行を止めない。
- Save本体の原子的書込みは既存 `JsonFileSaveRepository` に委譲する。

## Playable / Steamデモ導線

`available_actions()`へ `bestiary / モンスター図鑑` を追加する。

既存のMenu PresenterとAction Controllerは `available_actions()` / `perform_action()` を利用しているため、新しいRouteを追加せず既存Steamデモのトップメニューから実行できる。

現段階では既存ログ表示を利用し、達成率・一覧・解放済み詳細を表示する。専用画像画面、3Dモデル、図鑑内カーソルUIは本Issueの対象外とする。

## テスト観点

### 正常系

- 初遭遇で `encountered` へ進む。
- 初討伐で `defeated` へ進む。
- 規定討伐数で `mastered` へ進む。
- 混成Encounterと同一敵複数体を正しく集計する。
- 通常敵 / Boss / 全体の達成率を集計する。
- Save / Continueで戦闘記録を復元する。

### 異常系

- Encounterと異なる `BattleResult.encounter_id` を拒否する。
- Encounterに存在しない討伐Enemyを拒否する。
- 出現数を超える討伐数を拒否する。
- 負数や不正VersionのSaveを拒否する。
- Master参照切れ・重複IDを拒否する。

### 回帰

- 既存のBattleResult、Battle Domainを変更しない。
- 既存Save Versionを変更しない。
- 既存GUI / Action DispatcherへRoute固有分岐を追加しない。
- `python -m unittest`を全件実行する。
- SteamデモSmoke TestでNew GameとトップScene生成を確認する。

## 将来拡張候補

以下は別Issueで扱う。

- 専用図鑑画面と画像 / 3Dモデル
- ドロップ履歴
- 図鑑達成報酬
- Steam実績
- 戦闘中の解析情報表示
- 地域別・章別フィルター
