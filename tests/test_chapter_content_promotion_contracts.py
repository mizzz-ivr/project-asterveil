from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.content_promotion import PromotionError, evaluate_promotion, load_catalog


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


class ChapterContentPromotionMasterContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.catalog_path = self.root / "content" / "master_catalog_v1.json"
        collections = {
            "quests": ("data/master/quests.sample.json", ["quest_id", "id"], True),
            "events": ("data/master/events.sample.json", ["event_id", "id"], True),
            "encounters": (
                "data/master/encounters.sample.json",
                ["encounter_id", "id"],
                True,
            ),
            "locations": (
                "data/master/locations.sample.json",
                ["location_id", "id"],
                True,
            ),
            "conversations": (
                "data/master/dialogues.sample.json",
                ["conversation_id", "entry_id", "id"],
                True,
            ),
            "npcs": ("data/master/npcs.sample.json", ["npc_id", "id"], False),
            "enemies": ("data/master/enemies.sample.json", ["enemy_id", "id"], False),
            "items": ("data/master/items.sample.json", ["item_id", "id"], False),
        }
        master_values = {
            "quests": [
                {
                    "quest_id": "quest.ch01.prologue",
                    "id": "quest.ch01.prologue",
                    "availability": {"required_quest_ids": []},
                }
            ],
            "events": [{"id": "event.ch01.prologue"}],
            "encounters": [
                {
                    "encounter_id": "encounter.ch01.slime",
                    "enemies": [{"enemy_id": "enemy.ch01.slime", "count": 1}],
                }
            ],
            "locations": [{"location_id": "location.ch01.town"}],
            "conversations": [
                {"entry_id": "conversation.ch01.greeting", "npc_id": "npc.ch01.guide"}
            ],
            "npcs": [
                {
                    "npc_id": "npc.ch01.guide",
                    "npc_name": "案内人",
                    "location_id": "location.ch01.town",
                    "fallback_lines": ["気をつけて。"],
                }
            ],
            "enemies": [{"id": "enemy.ch01.slime"}],
            "items": [{"item_id": "item.ch01.herb"}],
        }
        definition = {}
        for kind, (relative, id_fields, promotable) in collections.items():
            write_json(self.root / relative, master_values[kind])
            definition[kind] = {
                "path": relative,
                "id_fields": id_fields,
                "promotable": promotable,
            }
        write_json(
            self.catalog_path,
            {"schema_version": 1, "collections": definition},
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _pack(self) -> dict:
        return {
            "schema_version": 1,
            "chapter_id": "ch02",
            "title": "第二章",
            "estimated_play_minutes": 0,
            "content": {
                "quests": [],
                "events": [],
                "encounters": [],
                "locations": [],
                "conversations": [],
            },
        }

    def _evaluate(self, pack: dict):
        return evaluate_promotion(
            pack,
            load_catalog(self.catalog_path, self.root),
        )

    def _conversation(self) -> dict:
        return {
            "entry_id": "conversation.ch02.guide",
            "npc_id": "npc.ch01.guide",
            "priority": 100,
            "condition": {},
            "lines": ["霧の森へ向かってください。"],
        }

    def _quest(self) -> dict:
        return {
            "quest_id": "quest.ch02.report_check",
            "id": "quest.ch02.report_check",
            "title": "報告先確認",
            "description": "報告NPCの明示指定を確認する。",
            "availability": {
                "required_quest_ids": [],
                "required_flags": [],
                "min_level": 1,
            },
            "objectives": [
                {
                    "id": "obj.ch02.report_check.talk",
                    "type": "talk",
                }
            ],
            "reward": {"exp": 10, "gold": 0, "items": []},
        }

    def test_event_candidate_must_match_master_repository_contract(self) -> None:
        pack = self._pack()
        pack["content"]["events"] = [
            {
                "event_id": "event.ch02.invalid",
                "next_event_ids": [],
            }
        ]
        with self.assertRaisesRegex(
            PromotionError,
            "master_contract_invalid:events",
        ):
            self._evaluate(pack)

    def test_required_event_action_reference_must_be_present(self) -> None:
        pack = self._pack()
        pack["content"]["events"] = [
            {
                "id": "event.ch02.battle",
                "title": "戦闘開始",
                "next_event_ids": [],
                "steps": [
                    {
                        "id": "step.start",
                        "action": {
                            "type": "start_battle",
                            "params": {},
                        },
                    }
                ],
            }
        ]
        with self.assertRaisesRegex(
            PromotionError,
            "required_action_param_missing.*start_battle.*encounter_id",
        ):
            self._evaluate(pack)

    def test_set_flag_requires_flag_id(self) -> None:
        pack = self._pack()
        pack["content"]["events"] = [
            {
                "id": "event.ch02.flag",
                "title": "Flag設定",
                "next_event_ids": [],
                "steps": [
                    {
                        "id": "step.flag",
                        "action": {"type": "set_flag", "params": {}},
                    }
                ],
            }
        ]
        with self.assertRaisesRegex(
            PromotionError,
            "required_action_param_missing.*set_flag.*flag_id",
        ):
            self._evaluate(pack)

    def test_unknown_event_action_is_rejected(self) -> None:
        pack = self._pack()
        pack["content"]["events"] = [
            {
                "id": "event.ch02.typo",
                "title": "未知Action",
                "next_event_ids": [],
                "steps": [
                    {
                        "id": "step.typo",
                        "action": {"type": "typo_action", "params": {}},
                    }
                ],
            }
        ]
        with self.assertRaisesRegex(PromotionError, "unsupported_action_type"):
            self._evaluate(pack)

    def test_valid_event_candidate_can_be_review_ready(self) -> None:
        pack = self._pack()
        pack["content"]["events"] = [
            {
                "id": "event.ch02.battle",
                "title": "戦闘開始",
                "next_event_ids": [],
                "steps": [
                    {
                        "id": "step.start",
                        "action": {
                            "type": "start_battle",
                            "params": {
                                "encounter_id": "encounter.ch01.slime",
                            },
                        },
                    }
                ],
            }
        ]
        evaluation = self._evaluate(pack)
        self.assertFalse(evaluation.blocked)
        self.assertEqual(
            ["event.ch02.battle"],
            evaluation.plan["classifications"]["events"]["add"],
        )

    def test_mismatched_id_aliases_are_rejected(self) -> None:
        pack = self._pack()
        pack["content"]["events"] = [
            {
                "event_id": "event.ch02.claimed",
                "id": "event.ch02.loaded",
                "title": "不一致ID",
                "next_event_ids": [],
                "steps": [],
            }
        ]
        with self.assertRaisesRegex(PromotionError, "entity_id_alias_mismatch"):
            self._evaluate(pack)

    def test_quest_requires_explicit_reporting_npc(self) -> None:
        pack = self._pack()
        pack["content"]["quests"] = [self._quest()]
        with self.assertRaisesRegex(PromotionError, "reporting_npc_id_required"):
            self._evaluate(pack)

    def test_entry_id_conversation_matches_pack_and_master_contracts(self) -> None:
        pack = self._pack()
        pack["content"]["conversations"] = [self._conversation()]
        evaluation = self._evaluate(pack)
        self.assertFalse(evaluation.blocked)
        self.assertEqual(
            ["conversation.ch02.guide"],
            evaluation.plan["classifications"]["conversations"]["add"],
        )

    def test_unknown_conversation_npc_is_recorded_as_unresolved(self) -> None:
        pack = self._pack()
        conversation = self._conversation()
        conversation["npc_id"] = "npc.ch99.unknown"
        pack["content"]["conversations"] = [conversation]
        evaluation = self._evaluate(pack)
        self.assertTrue(evaluation.blocked)
        self.assertTrue(
            any(
                item["source_kind"] == "conversations"
                and item["target_kind"] == "npcs"
                and item["target_id"] == "npc.ch99.unknown"
                for item in evaluation.plan["unresolved_references"]
            )
        )

    def test_conversation_priority_must_be_convertible_to_integer(self) -> None:
        pack = self._pack()
        conversation = self._conversation()
        conversation["priority"] = "high"
        pack["content"]["conversations"] = [conversation]
        with self.assertRaisesRegex(PromotionError, "priority_must_be_integer"):
            self._evaluate(pack)

    def test_dialogue_effect_requires_quest_id(self) -> None:
        pack = self._pack()
        conversation = self._conversation()
        conversation["steps"] = [
            {
                "step_id": "step.choice",
                "speaker": "案内人",
                "lines": ["依頼を受けますか？"],
                "choices": [
                    {
                        "choice_id": "choice.accept",
                        "text": "受ける",
                        "next_step_id": "",
                        "effects": [
                            {"action_type": "accept_quest", "params": {}}
                        ],
                    }
                ],
            }
        ]
        pack["content"]["conversations"] = [conversation]
        with self.assertRaisesRegex(
            PromotionError,
            "required_action_param_missing.*accept_quest.*quest_id",
        ):
            self._evaluate(pack)

    def test_dialogue_effect_unknown_quest_is_unresolved(self) -> None:
        pack = self._pack()
        conversation = self._conversation()
        conversation["steps"] = [
            {
                "step_id": "step.choice",
                "speaker": "案内人",
                "lines": ["依頼を受けますか？"],
                "choices": [
                    {
                        "choice_id": "choice.accept",
                        "text": "受ける",
                        "next_step_id": "",
                        "effects": [
                            {
                                "action_type": "accept_quest",
                                "params": {"quest_id": "quest.ch99.unknown"},
                            }
                        ],
                    }
                ],
            }
        ]
        pack["content"]["conversations"] = [conversation]
        evaluation = self._evaluate(pack)
        self.assertTrue(evaluation.blocked)
        self.assertTrue(
            any(
                item["target_id"] == "quest.ch99.unknown"
                and item["source_kind"] == "conversations"
                for item in evaluation.plan["unresolved_references"]
            )
        )


if __name__ == "__main__":
    unittest.main()
