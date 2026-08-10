from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from game.app.application.bestiary_service import (
    BestiaryEntryView,
    BestiaryProgressSummary,
    BestiaryService,
    BestiaryState,
    BestiaryUnlockStage,
)
from game.app.application.playable_slice import ActionItem, PlayableSliceApplication
from game.app.infrastructure.bestiary_repository import BestiaryMasterDataRepository
from game.quest.domain.entities import BattleResult
from game.save.domain.entities import SaveData


class _BestiarySaveRepositoryDecorator:
    """既存の原子的Save処理を維持したまま図鑑状態だけmetaへ追加する。"""

    def __init__(
        self,
        delegate: object,
        *,
        service: BestiaryService,
        state_provider: Callable[[], BestiaryState],
    ) -> None:
        self._delegate = delegate
        self._service = service
        self._state_provider = state_provider

    def save(self, save_data: SaveData) -> None:
        save_data.meta = dict(save_data.meta)
        save_data.meta["bestiary_state"] = self._service.serialize_state(
            self._state_provider()
        )
        getattr(self._delegate, "save")(save_data)

    def load(self) -> SaveData:
        return getattr(self._delegate, "load")()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)


class BestiaryPlayableSliceApplication(PlayableSliceApplication):
    """既存Playable Sliceへ図鑑記録・表示・永続化だけを追加する拡張。"""

    def __init__(
        self,
        master_root: Path,
        save_file_path: Path,
        battle_executor: Callable[..., BattleResult] | None = None,
    ) -> None:
        super().__init__(
            master_root=master_root,
            save_file_path=save_file_path,
            battle_executor=battle_executor,
        )
        catalog = BestiaryMasterDataRepository(master_root).load()
        self._bestiary_service = BestiaryService(catalog)
        self.bestiary_state: BestiaryState = {}

        base_battle_executor = self._battle_executor

        def tracked_battle_executor(
            encounter_id: str,
            *args: object,
            **kwargs: object,
        ) -> BattleResult:
            battle_result = base_battle_executor(encounter_id, *args, **kwargs)
            self._bestiary_service.record_battle(
                self.bestiary_state,
                encounter_id=encounter_id,
                battle_result=battle_result,
            )
            return battle_result

        self._battle_executor = tracked_battle_executor
        self._save_repo = _BestiarySaveRepositoryDecorator(
            self._save_repo,
            service=self._bestiary_service,
            state_provider=lambda: self.bestiary_state,
        )

    def new_game(self) -> list[str]:
        self.bestiary_state = {}
        return super().new_game()

    def continue_game(self) -> tuple[bool, str]:
        try:
            save_data = self._save_repo.load()
            restored_state = self._bestiary_service.restore_state(
                save_data.meta.get("bestiary_state")
            )
        except FileNotFoundError:
            return False, "セーブデータが見つかりません。先に New Game を開始してください。"
        except json.JSONDecodeError:
            return False, "セーブデータのJSONが破損しています。"
        except ValueError as exc:
            return False, f"セーブデータの整合性エラー: {exc}"

        success, message = super().continue_game()
        if success:
            self.bestiary_state = restored_state
        return success, message

    def available_actions(self) -> list[ActionItem]:
        actions = super().available_actions()
        if not actions or any(action.key == "bestiary" for action in actions):
            return actions

        insert_index = next(
            (
                index
                for index, action in enumerate(actions)
                if action.key in {"save", "exit"}
            ),
            len(actions),
        )
        actions.insert(insert_index, ActionItem("bestiary", "モンスター図鑑"))
        return actions

    def perform_action(self, action_key: str) -> list[str]:
        if action_key == "bestiary":
            if self.quest_session is None:
                raise ValueError("ゲームが開始されていません。")
            return self.bestiary_lines()
        return super().perform_action(action_key)

    def bestiary_progress(self) -> tuple[BestiaryProgressSummary, ...]:
        return (
            self._bestiary_service.progress_summary(self.bestiary_state),
            self._bestiary_service.progress_summary(
                self.bestiary_state,
                category="normal",
            ),
            self._bestiary_service.progress_summary(
                self.bestiary_state,
                category="boss",
            ),
        )

    def bestiary_lines(self) -> list[str]:
        lines = [self._format_progress(summary) for summary in self.bestiary_progress()]
        for slot_index, entry in enumerate(
            self._bestiary_service.list_entries(self.bestiary_state),
            start=1,
        ):
            lines.extend(self._format_entry(entry, slot_index=slot_index))
        return lines

    def bestiary_detail_lines(self, enemy_id: str) -> list[str]:
        entry = self._bestiary_service.entry_view(self.bestiary_state, enemy_id)
        return self._format_entry(entry, slot_index=None)

    @staticmethod
    def _format_progress(summary: BestiaryProgressSummary) -> str:
        return (
            f"bestiary_progress:{summary.category}:"
            f"encountered={summary.encountered_count}/{summary.total_count}:"
            f"defeated={summary.defeated_count}/{summary.total_count}:"
            f"mastered={summary.mastered_count}/{summary.total_count}:"
            f"encounter_rate={summary.encounter_rate_percent}%:"
            f"mastery_rate={summary.mastery_rate_percent}%"
        )

    @staticmethod
    def _format_entry(
        entry: BestiaryEntryView,
        *,
        slot_index: int | None,
    ) -> list[str]:
        slot = f"{slot_index:03d}" if slot_index is not None else "detail"
        if entry.stage == BestiaryUnlockStage.UNKNOWN:
            return [f"bestiary_entry:slot={slot}:stage=unknown:name=？？？"]

        lines = [
            (
                f"bestiary_entry:slot={slot}:enemy_id={entry.enemy_id}:"
                f"stage={entry.stage.value}:name={entry.display_name}:"
                f"encounters={entry.encounter_count}:wins={entry.battle_win_count}:"
                f"kills={entry.kill_count}:losses={entry.battle_loss_count}"
            ),
            f"bestiary_habitat:{entry.enemy_id}:{' / '.join(entry.habitat_names)}",
        ]
        if entry.stage in {BestiaryUnlockStage.DEFEATED, BestiaryUnlockStage.MASTERED}:
            stats = entry.stats or {}
            stat_text = ",".join(
                f"{key}={value}" for key, value in sorted(stats.items())
            )
            element_text = ",".join(entry.weakness_elements) or "none"
            weapon_text = ",".join(entry.weakness_weapon_types) or "none"
            lines.extend(
                [
                    f"bestiary_level:{entry.enemy_id}:{entry.level}",
                    f"bestiary_stats:{entry.enemy_id}:{stat_text}",
                    (
                        f"bestiary_weakness:{entry.enemy_id}:"
                        f"elements={element_text}:weapon_types={weapon_text}"
                    ),
                ]
            )
        if entry.stage == BestiaryUnlockStage.MASTERED and entry.description:
            lines.append(f"bestiary_description:{entry.enemy_id}:{entry.description}")
        return lines
