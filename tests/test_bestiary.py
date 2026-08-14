from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from game.app.application.bestiary_playable_slice import (
    BestiaryPlayableSliceApplication,
)
from game.app.application.bestiary_service import (
    BestiaryRecord,
    BestiaryService,
    BestiaryUnlockStage,
)
from game.app.infrastructure.bestiary_repository import BestiaryMasterDataRepository
from game.quest.domain.entities import BattleResult


MASTER_ROOT = Path("data/master")


class BestiaryServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = BestiaryMasterDataRepository(MASTER_ROOT).load()
        self.service = BestiaryService(self.catalog)

    def test_master_covers_all_battle_enemies(self) -> None:
        self.assertEqual(
            set(self.catalog.profiles),
            set(self.catalog.definitions),
        )
        self.assertEqual(len(self.catalog.definitions), 7)
        self.assertEqual(self.catalog.definitions["enemy.ch01.tide_serpent"].category, "boss")

    def test_unknown_entry_does_not_reveal_confidential_information(self) -> None:
        view = self.service.entry_view({}, "enemy.ch01.tide_serpent")

        self.assertEqual(view.stage, BestiaryUnlockStage.UNKNOWN)
        self.assertIsNone(view.display_name)
        self.assertEqual(view.habitat_names, tuple())
        self.assertIsNone(view.level)
        self.assertIsNone(view.stats)
        self.assertEqual(view.weakness_elements, tuple())
        self.assertIsNone(view.description)

    def test_mixed_encounter_counts_multiple_enemies_and_loss(self) -> None:
        state = {}
        changed = self.service.record_battle(
            state,
            encounter_id="encounter.ch01.harbor_miasma_patrol",
            battle_result=BattleResult(
                encounter_id="encounter.ch01.harbor_miasma_patrol",
                player_won=False,
                defeated_enemy_ids=("enemy.ch01.brine_slime",),
            ),
        )

        self.assertEqual(
            changed,
            ("enemy.ch01.port_wraith", "enemy.ch01.brine_slime"),
        )
        self.assertEqual(
            state["enemy.ch01.port_wraith"],
            BestiaryRecord(encounter_count=1, battle_loss_count=1),
        )
        self.assertEqual(
            state["enemy.ch01.brine_slime"],
            BestiaryRecord(encounter_count=2, kill_count=1, battle_loss_count=1),
        )
        self.assertEqual(
            self.service.entry_view(state, "enemy.ch01.port_wraith").stage,
            BestiaryUnlockStage.ENCOUNTERED,
        )
        slime_view = self.service.entry_view(state, "enemy.ch01.brine_slime")
        self.assertEqual(slime_view.stage, BestiaryUnlockStage.DEFEATED)
        self.assertEqual(slime_view.weakness_elements, ("fire",))

    def test_mastered_stage_is_unlocked_at_configured_kill_count(self) -> None:
        state = {}
        for _ in range(5):
            self.service.record_battle(
                state,
                encounter_id="encounter.ch01.port_wraith_single",
                battle_result=BattleResult(
                    encounter_id="encounter.ch01.port_wraith_single",
                    player_won=True,
                    defeated_enemy_ids=("enemy.ch01.port_wraith",),
                ),
            )

        view = self.service.entry_view(state, "enemy.ch01.port_wraith")
        self.assertEqual(view.stage, BestiaryUnlockStage.MASTERED)
        self.assertEqual(view.kill_count, 5)
        self.assertIsNotNone(view.description)

    def test_progress_summary_separates_normal_and_boss(self) -> None:
        state = {}
        self.service.record_battle(
            state,
            encounter_id="encounter.ch01.port_wraith_single",
            battle_result=BattleResult(
                encounter_id="encounter.ch01.port_wraith_single",
                player_won=True,
                defeated_enemy_ids=("enemy.ch01.port_wraith",),
            ),
        )

        overall = self.service.progress_summary(state)
        normal = self.service.progress_summary(state, category="normal")
        boss = self.service.progress_summary(state, category="boss")

        self.assertEqual((overall.encountered_count, overall.total_count), (1, 7))
        self.assertEqual((normal.encountered_count, normal.total_count), (1, 5))
        self.assertEqual((boss.encountered_count, boss.total_count), (0, 2))
        self.assertEqual(overall.encounter_rate_percent, 14)

    def test_invalid_battle_result_is_rejected_before_state_mutation(self) -> None:
        state = {}
        with self.assertRaisesRegex(ValueError, "defeated_enemy_not_in_encounter"):
            self.service.record_battle(
                state,
                encounter_id="encounter.ch01.port_wraith_single",
                battle_result=BattleResult(
                    encounter_id="encounter.ch01.port_wraith_single",
                    player_won=True,
                    defeated_enemy_ids=("enemy.ch01.tide_serpent",),
                ),
            )
        self.assertEqual(state, {})

    def test_restore_ignores_unknown_enemy_and_rejects_invalid_known_record(self) -> None:
        restored = self.service.restore_state(
            {
                "version": 1,
                "records": {
                    "enemy.removed": {
                        "encounter_count": 99,
                        "battle_win_count": 99,
                        "kill_count": 99,
                        "battle_loss_count": 0,
                    },
                    "enemy.ch01.port_wraith": {
                        "encounter_count": 1,
                        "battle_win_count": 1,
                        "kill_count": 1,
                        "battle_loss_count": 0,
                    },
                },
            }
        )
        self.assertEqual(set(restored), {"enemy.ch01.port_wraith"})

        with self.assertRaisesRegex(ValueError, "field_must_be_non_negative"):
            self.service.restore_state(
                {
                    "version": 1,
                    "records": {
                        "enemy.ch01.port_wraith": {
                            "encounter_count": -1,
                        }
                    },
                }
            )


class BestiaryPlayableSliceIntegrationTest(unittest.TestCase):
    @staticmethod
    def _battle_executor(encounter_id: str, *_args: object) -> BattleResult:
        defeated_by_encounter = {
            "encounter.ch01.harbor_miasma_patrol": (
                "enemy.ch01.port_wraith",
                "enemy.ch01.brine_slime",
                "enemy.ch01.brine_slime",
            ),
            "encounter.ch01.port_wraith_single": ("enemy.ch01.port_wraith",),
        }
        return BattleResult(
            encounter_id=encounter_id,
            player_won=True,
            defeated_enemy_ids=defeated_by_encounter.get(encounter_id, tuple()),
        )

    def test_action_is_available_and_state_is_saved_and_restored(self) -> None:
        with tempfile.TemporaryDirectory(prefix="asterveil-bestiary-") as temporary:
            save_path = Path(temporary) / "slot.json"
            app = BestiaryPlayableSliceApplication(
                master_root=MASTER_ROOT,
                save_file_path=save_path,
                battle_executor=self._battle_executor,
            )
            app.new_game()

            self.assertIn("bestiary", [action.key for action in app.available_actions()])
            app._battle_executor("encounter.ch01.harbor_miasma_patrol")
            lines = app.perform_action("bestiary")
            self.assertTrue(any(line.startswith("bestiary_progress:overall") for line in lines))
            self.assertTrue(any("enemy.ch01.brine_slime" in line for line in lines))
            app.save_game()

            raw = json.loads(save_path.read_text(encoding="utf-8"))
            saved_records = raw["meta"]["bestiary_state"]["records"]
            self.assertEqual(saved_records["enemy.ch01.brine_slime"]["encounter_count"], 2)
            self.assertEqual(saved_records["enemy.ch01.brine_slime"]["kill_count"], 2)

            restored = BestiaryPlayableSliceApplication(
                master_root=MASTER_ROOT,
                save_file_path=save_path,
                battle_executor=self._battle_executor,
            )
            success, _ = restored.continue_game()
            self.assertTrue(success)
            detail = restored.bestiary_detail_lines("enemy.ch01.brine_slime")
            self.assertTrue(any("stage=defeated" in line for line in detail))
            self.assertTrue(any("elements=fire" in line for line in detail))

    def test_old_save_without_bestiary_meta_loads_with_empty_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="asterveil-bestiary-old-save-") as temporary:
            save_path = Path(temporary) / "slot.json"
            app = BestiaryPlayableSliceApplication(
                master_root=MASTER_ROOT,
                save_file_path=save_path,
                battle_executor=self._battle_executor,
            )
            app.new_game()
            app.save_game()

            raw = json.loads(save_path.read_text(encoding="utf-8"))
            raw["meta"].pop("bestiary_state")
            save_path.write_text(
                json.dumps(raw, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            restored = BestiaryPlayableSliceApplication(
                master_root=MASTER_ROOT,
                save_file_path=save_path,
                battle_executor=self._battle_executor,
            )
            success, _ = restored.continue_game()

            self.assertTrue(success)
            self.assertEqual(restored.bestiary_state, {})
            unknown_lines = restored.bestiary_detail_lines("enemy.ch01.tide_serpent")
            self.assertEqual(
                unknown_lines,
                ["bestiary_entry:slot=detail:stage=unknown:name=？？？"],
            )


if __name__ == "__main__":
    unittest.main()
