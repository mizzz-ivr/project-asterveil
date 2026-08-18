from __future__ import annotations

import json
import unittest
from pathlib import Path

from game.app.infrastructure.dialogue_event_repository import DialogueEventMasterDataRepository
from game.battle.infrastructure.master_data_repository import MasterDataRepository
from game.location.infrastructure.field_event_repository import FieldEventMasterDataRepository
from game.quest.infrastructure.master_data_repository import QuestMasterDataRepository
from tools.chapter_content_pack import validate_pack
from tools.content_promotion import evaluate_promotion, load_catalog


MASTER_ROOT = Path("data/master")
PACK_PATH = Path("content/packs/ch02/pack.json")
CATALOG_PATH = Path("content/master_catalog_v1.json")
CHAPTER2_CONVERSATION_IDS = {
    "dialogue.ch02.fog_keeper.first_trace_offer",
    "dialogue.ch02.fog_keeper.first_trace_progress",
    "dialogue.ch02.fog_keeper.first_trace_ready",
    "dialogue.ch02.fog_keeper.marsh_patrol_offer",
    "dialogue.ch02.fog_keeper.marsh_patrol_progress",
    "dialogue.ch02.fog_keeper.marsh_patrol_ready",
    "dialogue.ch02.fog_keeper.mist_trace_offer",
    "dialogue.ch02.fog_keeper.mist_trace_progress",
    "dialogue.ch02.fog_keeper.echo_patrol_offer",
    "dialogue.ch02.fog_keeper.echo_patrol_progress",
    "dialogue.ch02.fog_keeper.echo_patrol_ready",
    "dialogue.ch02.fog_keeper.boss_offer",
    "dialogue.ch02.fog_keeper.boss_progress",
    "dialogue.ch02.fog_keeper.boss_ready",
    "dialogue.ch02.fog_keeper.chapter_clear",
}


class Chapter2PlayableContentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))

    def test_pack_is_playable_scale_and_matches_promoted_master(self) -> None:
        result = validate_pack(self.pack)

        self.assertEqual(result.counts["locations"], 3)
        self.assertEqual(result.counts["encounters"], 4)
        self.assertEqual(result.counts["quests"], 5)
        self.assertEqual(result.counts["events"], 2)
        self.assertEqual(result.counts["conversations"], 15)
        self.assertEqual(
            {row["entry_id"] for row in self.pack["content"]["conversations"]},
            CHAPTER2_CONVERSATION_IDS,
        )

        evaluation = evaluate_promotion(
            self.pack,
            load_catalog(CATALOG_PATH, Path(".")),
        )
        self.assertFalse(evaluation.blocked)
        self.assertEqual(evaluation.plan["status"], "ready_for_review")
        self.assertEqual(evaluation.plan["unresolved_references"], [])
        self.assertEqual(evaluation.plan["conflicts"], [])

        expected_unchanged = {
            "locations": 3,
            "encounters": 4,
            "quests": 5,
            "events": 2,
        }
        for kind, count in expected_unchanged.items():
            classification = evaluation.plan["classifications"][kind]
            self.assertEqual(classification["add"], [])
            self.assertEqual(classification["conflict"], [])
            self.assertEqual(len(classification["unchanged"]), count)

        conversation_classification = evaluation.plan["classifications"]["conversations"]
        self.assertEqual(conversation_classification["conflict"], [])
        added = set(conversation_classification["add"])
        unchanged = set(conversation_classification["unchanged"])
        self.assertFalse(added & unchanged)
        self.assertEqual(added | unchanged, CHAPTER2_CONVERSATION_IDS)

    def test_chapter2_encounters_load_with_expected_rosters(self) -> None:
        repository = MasterDataRepository(MASTER_ROOT)
        expected_counts = {
            "encounter.ch02.mist_wolf": 1,
            "encounter.ch02.lantern_moth_swarm": 2,
            "encounter.ch02.echo_patrol": 2,
            "encounter.ch02.fog_behemoth_boss": 1,
        }

        for encounter_id, expected_count in expected_counts.items():
            units, runtime_map = repository.build_enemy_party(encounter_id)
            self.assertEqual(len(units), expected_count)
            self.assertEqual(len(runtime_map), expected_count)
            self.assertTrue(
                all(enemy_id.startswith("enemy.ch02.") for enemy_id in runtime_map.values())
            )

    def test_main_quest_chain_unlocks_bastion_then_chapter_clear(self) -> None:
        quests = QuestMasterDataRepository(MASTER_ROOT).load_quests()

        first_trace = quests["quest.ch02.first_trace"]
        echo_patrol = quests["quest.ch02.echo_patrol"]
        boss = quests["quest.ch02.fog_behemoth_subjugation"]

        self.assertIn(
            "quest.ch01.tide_serpent_subjugation",
            first_trace.availability.required_quest_ids,
        )
        self.assertIn("flag.ch02.access_granted", first_trace.availability.required_flags)
        self.assertIn("quest.ch02.first_trace", echo_patrol.availability.required_quest_ids)
        self.assertIn(
            "flag.field_event.ch02.mist_trace_collected",
            echo_patrol.availability.required_flags,
        )
        self.assertEqual(
            echo_patrol.reward.completion_flag,
            "flag.ch02.echoing_bastion_unlocked",
        )
        self.assertIn("quest.ch02.echo_patrol", boss.availability.required_quest_ids)
        self.assertIn(
            "flag.ch02.echoing_bastion_unlocked",
            boss.availability.required_flags,
        )
        self.assertEqual(boss.reward.completion_flag, "flag.ch02.chapter_clear")

    def test_mist_harbor_npc_and_automatic_location_events_are_registered(self) -> None:
        repository = DialogueEventMasterDataRepository(MASTER_ROOT)
        npcs = repository.load_npc_dialogues()
        events = repository.load_location_events()

        fog_keeper = npcs["npc.ch02.fog_keeper"]
        self.assertEqual(fog_keeper.npc_name, "霧守セラ")
        self.assertEqual(fog_keeper.location_id, "location.ch02.mist_harbor")
        self.assertGreaterEqual(len(fog_keeper.fallback_lines), 3)

        route_unlock = events["event.location.ch02.route_unlock"]
        self.assertEqual(route_unlock.location_id, "location.town.astel")
        self.assertEqual(
            route_unlock.condition.required_quest_status[
                "quest.ch01.tide_serpent_subjugation"
            ],
            "completed",
        )
        self.assertTrue(
            any(
                action.action_type == "set_flag"
                and action.params.get("flag_id") == "flag.ch02.access_granted"
                for action in route_unlock.actions
            )
        )

        marsh_intro = events["event.location.ch02.fogbound_marsh.first_entry"]
        self.assertTrue(
            any(
                action.action_type == "start_battle"
                and action.params.get("encounter_id") == "encounter.ch02.mist_wolf"
                for action in marsh_intro.actions
            )
        )

    def test_field_exploration_connects_collection_and_optional_battle(self) -> None:
        events = FieldEventMasterDataRepository(MASTER_ROOT).load_events()

        trace = events["event.field.ch02.fogbound_marsh.mist_trace"]
        self.assertIn("flag.ch02.first_trace_complete", trace.required_flags)
        inspect_choice = next(
            choice for choice in trace.choices if choice.choice_id == "choice.inspect_trace"
        )
        self.assertTrue(
            any(
                outcome.outcome_type == "grant_items"
                and outcome.params.get("item_id") == "item.material.memory_shard"
                and outcome.params.get("amount") == "2"
                for outcome in inspect_choice.outcomes
            )
        )
        self.assertTrue(
            any(
                outcome.outcome_type == "set_flag"
                and outcome.params.get("flag_id")
                == "flag.field_event.ch02.mist_trace_collected"
                for outcome in inspect_choice.outcomes
            )
        )

        lantern = events["event.field.ch02.fogbound_marsh.lantern_lure"]
        follow_choice = next(
            choice for choice in lantern.choices if choice.choice_id == "choice.follow_lights"
        )
        self.assertTrue(
            any(
                outcome.outcome_type == "start_battle"
                and outcome.params.get("encounter_id")
                == "encounter.ch02.lantern_moth_swarm"
                for outcome in follow_choice.outcomes
            )
        )


if __name__ == "__main__":
    unittest.main()
