from __future__ import annotations

import unittest
from pathlib import Path

from game.app.application.bestiary_service import BestiaryService
from game.app.infrastructure.bestiary_repository import BestiaryMasterDataRepository
from game.quest.domain.entities import BattleResult


MASTER_ROOT = Path("data/master")


class BestiaryContractTest(unittest.TestCase):
    def setUp(self) -> None:
        catalog = BestiaryMasterDataRepository(MASTER_ROOT).load()
        self.service = BestiaryService(catalog)

    def test_encounter_id_mismatch_is_rejected_without_mutation(self) -> None:
        state = {}

        with self.assertRaisesRegex(ValueError, "battle_result_encounter_mismatch"):
            self.service.record_battle(
                state,
                encounter_id="encounter.ch01.port_wraith_single",
                battle_result=BattleResult(
                    encounter_id="encounter.ch01.tide_serpent_boss",
                    player_won=True,
                    defeated_enemy_ids=("enemy.ch01.port_wraith",),
                ),
            )

        self.assertEqual(state, {})

    def test_defeated_count_exceeding_roster_is_rejected_without_mutation(self) -> None:
        state = {}

        with self.assertRaisesRegex(ValueError, "defeated_enemy_count_exceeds_roster"):
            self.service.record_battle(
                state,
                encounter_id="encounter.ch01.port_wraith_single",
                battle_result=BattleResult(
                    encounter_id="encounter.ch01.port_wraith_single",
                    player_won=True,
                    defeated_enemy_ids=(
                        "enemy.ch01.port_wraith",
                        "enemy.ch01.port_wraith",
                    ),
                ),
            )

        self.assertEqual(state, {})

    def test_unknown_bestiary_state_version_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported_version"):
            self.service.restore_state(
                {
                    "version": 999,
                    "records": {},
                }
            )

    def test_battle_count_exceeding_encounters_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "battle_count_exceeds_encounters"):
            self.service.restore_state(
                {
                    "version": 1,
                    "records": {
                        "enemy.ch01.port_wraith": {
                            "encounter_count": 1,
                            "battle_win_count": 1,
                            "kill_count": 0,
                            "battle_loss_count": 1,
                        }
                    },
                }
            )


if __name__ == "__main__":
    unittest.main()
