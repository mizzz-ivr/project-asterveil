from __future__ import annotations

import unittest
from pathlib import Path

from game.app.infrastructure.bestiary_repository import BestiaryMasterDataRepository
from game.battle.infrastructure.master_data_repository import MasterDataRepository
from game.location.application.travel_service import TravelService
from game.location.domain.entities import LocationState
from game.location.infrastructure.master_data_repository import LocationMasterDataRepository


MASTER_ROOT = Path("data/master")
CHAPTER2_ENEMY_IDS = {
    "enemy.ch02.mist_wolf",
    "enemy.ch02.lantern_moth",
    "enemy.ch02.echo_knight",
    "enemy.ch02.fog_behemoth",
}
CHAPTER2_LOCATION_IDS = {
    "location.ch02.mist_harbor",
    "location.ch02.fogbound_marsh",
    "location.ch02.echoing_bastion",
}


class Chapter2EnemyFoundationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.battle_repository = MasterDataRepository(MASTER_ROOT)
        self.location_repository = LocationMasterDataRepository(MASTER_ROOT)
        self.skills = self.battle_repository.load_skills()
        self.ai_profiles = self.battle_repository.load_enemy_ai_profiles()
        self.ai_bindings = self.battle_repository.load_enemy_ai_bindings()
        self.locations = self.location_repository.load_locations()
        self.bestiary = BestiaryMasterDataRepository(MASTER_ROOT).load()

    def test_chapter2_enemy_skill_and_ai_references_resolve(self) -> None:
        for enemy_id in CHAPTER2_ENEMY_IDS:
            enemy = self.battle_repository.load_enemy(enemy_id)
            self.assertTrue(enemy.skill_ids, enemy_id)
            self.assertTrue(set(enemy.skill_ids).issubset(self.skills), enemy_id)

            profile_id = self.ai_bindings.get(enemy_id)
            self.assertIsNotNone(profile_id, enemy_id)
            self.assertIn(profile_id, self.ai_profiles, enemy_id)
            for rule in self.ai_profiles[profile_id].action_rules:
                if rule.action_type == "skill":
                    self.assertIsNotNone(rule.skill_id, rule.rule_id)
                    self.assertIn(rule.skill_id, self.skills, rule.rule_id)

    def test_bestiary_covers_all_chapter2_enemies(self) -> None:
        self.assertTrue(CHAPTER2_ENEMY_IDS.issubset(self.bestiary.definitions))
        self.assertTrue(CHAPTER2_ENEMY_IDS.issubset(self.bestiary.profiles))
        self.assertEqual(
            set(self.bestiary.definitions),
            set(self.bestiary.profiles),
        )
        self.assertEqual(
            "boss",
            self.bestiary.definitions["enemy.ch02.fog_behemoth"].category,
        )

    def test_chapter2_bestiary_habitats_resolve_to_seed_locations(self) -> None:
        self.assertTrue(CHAPTER2_LOCATION_IDS.issubset(self.locations))
        for enemy_id in CHAPTER2_ENEMY_IDS:
            definition = self.bestiary.definitions[enemy_id]
            self.assertTrue(definition.habitat_location_ids, enemy_id)
            for location_id in definition.habitat_location_ids:
                self.assertIn(location_id, self.locations, enemy_id)

    def test_chapter2_locations_stay_locked_until_progress_flags_are_set(self) -> None:
        service = TravelService(self.locations, "location.town.astel")
        state = LocationState(
            current_location_id="location.town.astel",
            unlocked_location_ids={"location.town.astel"},
        )

        service.evaluate_unlocks(state, set())
        self.assertTrue(CHAPTER2_LOCATION_IDS.isdisjoint(state.unlocked_location_ids))

        service.evaluate_unlocks(state, {"flag.ch02.access_granted"})
        self.assertIn("location.ch02.mist_harbor", state.unlocked_location_ids)
        self.assertIn("location.ch02.fogbound_marsh", state.unlocked_location_ids)
        self.assertNotIn("location.ch02.echoing_bastion", state.unlocked_location_ids)

        service.evaluate_unlocks(
            state,
            {
                "flag.ch02.access_granted",
                "flag.ch02.echoing_bastion_unlocked",
            },
        )
        self.assertIn("location.ch02.echoing_bastion", state.unlocked_location_ids)


if __name__ == "__main__":
    unittest.main()
