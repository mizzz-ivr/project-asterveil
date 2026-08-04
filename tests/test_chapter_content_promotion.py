from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.chapter_content_promotion import (
    PromotionError,
    evaluate_promotion,
    load_catalog,
    main,
    write_outputs,
)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class ChapterContentPromotionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.catalog_path = self.root / "content" / "master_catalog_v1.json"
        self._write_master(
            {
                "quests": [
                    {
                        "quest_id": "quest.ch01.prologue",
                        "availability": {"required_quest_ids": []},
                        "objectives": [{"id": "obj.ch01.prologue", "type": "talk"}],
                        "reward": {"exp": 10, "gold": 0, "items": []},
                    }
                ],
                "events": [{"id": "event.ch01.prologue", "steps": []}],
                "encounters": [
                    {
                        "encounter_id": "encounter.ch01.slime",
                        "enemies": [{"enemy_id": "enemy.ch01.slime", "count": 1}],
                    }
                ],
                "locations": [
                    {
                        "location_id": "location.ch01.town",
                        "name": "始まりの町",
                        "accessible_from": [],
                    }
                ],
                "conversations": [
                    {"entry_id": "conversation.ch01.greeting", "npc_id": "npc.ch01.guide"}
                ],
                "npcs": [{"npc_id": "npc.ch01.guide"}],
                "enemies": [{"id": "enemy.ch01.slime"}],
                "items": [{"item_id": "item.ch01.herb"}],
            }
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_master(self, values: dict[str, list[dict]]) -> None:
        mapping = {
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
        collections = {}
        for kind, (relative, id_fields, promotable) in mapping.items():
            write_json(self.root / relative, values.get(kind, []))
            collections[kind] = {
                "path": relative,
                "id_fields": id_fields,
                "promotable": promotable,
            }
        write_json(
            self.catalog_path,
            {"schema_version": 1, "collections": collections},
        )

    def _pack(self) -> dict:
        return {
            "schema_version": 1,
            "chapter_id": "ch02",
            "title": "第二章",
            "estimated_play_minutes": 30,
            "content": {
                "locations": [
                    {
                        "location_id": "location.ch02.forest",
                        "name": "霧の森",
                        "description": "町の北に広がる森。",
                        "accessible_from": ["location.ch01.town"],
                        "available_encounter_ids": ["encounter.ch01.slime"],
                        "default_encounter_id": "encounter.ch01.slime",
                    }
                ],
                "encounters": [],
                "quests": [
                    {
                        "quest_id": "quest.ch02.first_step",
                        "title": "森への一歩",
                        "description": "案内人から話を聞く。",
                        "reporting_npc_id": "npc.ch01.guide",
                        "availability": {
                            "required_quest_ids": ["quest.ch01.prologue"],
                            "required_flags": [],
                            "min_level": 1,
                        },
                        "encounter_id": "encounter.ch01.slime",
                        "target_location_id": "location.ch02.forest",
                        "objectives": [
                            {
                                "id": "obj.ch02.first_step.kill",
                                "type": "kill_enemy",
                                "target_enemy_id": "enemy.ch01.slime",
                                "required_count": 1,
                            }
                        ],
                        "reward": {
                            "exp": 100,
                            "gold": 50,
                            "items": [{"item_id": "item.ch01.herb", "amount": 1}],
                        },
                    }
                ],
                "events": [],
                "conversations": [],
            },
        }

    def test_external_master_references_are_resolved(self) -> None:
        evaluation = evaluate_promotion(
            self._pack(),
            load_catalog(self.catalog_path, self.root),
        )
        self.assertFalse(evaluation.blocked)
        self.assertEqual("ready_for_review", evaluation.plan["status"])
        self.assertEqual(
            ["quest.ch02.first_step"],
            evaluation.plan["classifications"]["quests"]["add"],
        )
        targets = {
            (item["target_kind"], item["target_id"])
            for item in evaluation.plan["references"]
        }
        self.assertIn(("quests", "quest.ch01.prologue"), targets)
        self.assertIn(("encounters", "encounter.ch01.slime"), targets)
        self.assertIn(("npcs", "npc.ch01.guide"), targets)

    def test_unresolved_reference_blocks_promotion(self) -> None:
        pack = self._pack()
        pack["content"]["quests"][0]["reporting_npc_id"] = "npc.ch99.unknown"
        evaluation = evaluate_promotion(
            pack,
            load_catalog(self.catalog_path, self.root),
        )
        self.assertTrue(evaluation.blocked)
        self.assertEqual("npc.ch99.unknown", evaluation.plan["unresolved_references"][0]["target_id"])

    def test_existing_id_with_different_content_is_conflict(self) -> None:
        path = self.root / "data/master/quests.sample.json"
        master_quests = json.loads(path.read_text())
        existing = dict(self._pack()["content"]["quests"][0])
        existing["title"] = "既存Master側の旧タイトル"
        master_quests.append(existing)
        write_json(path, master_quests)

        evaluation = evaluate_promotion(
            self._pack(),
            load_catalog(self.catalog_path, self.root),
        )
        self.assertTrue(evaluation.blocked)
        self.assertIn(
            "quest.ch02.first_step",
            evaluation.plan["classifications"]["quests"]["conflict"],
        )

    def test_identical_existing_entity_is_unchanged(self) -> None:
        existing = json.loads(
            (self.root / "data/master/locations.sample.json").read_text()
        )[0]
        existing["location_id"] = "location.ch02.forest"
        write_json(self.root / "data/master/locations.sample.json", [existing])
        pack = self._pack()
        pack["content"]["locations"] = [existing]
        evaluation = evaluate_promotion(
            pack,
            load_catalog(self.catalog_path, self.root),
        )
        self.assertIn(
            "location.ch02.forest",
            evaluation.plan["classifications"]["locations"]["unchanged"],
        )

    def test_combined_master_and_pack_quest_cycle_is_rejected(self) -> None:
        path = self.root / "data/master/quests.sample.json"
        master_quests = json.loads(path.read_text())
        master_quests[0]["availability"]["required_quest_ids"] = [
            "quest.ch02.first_step"
        ]
        write_json(path, master_quests)
        with self.assertRaisesRegex(PromotionError, "quest_dependency_cycle"):
            evaluate_promotion(
                self._pack(),
                load_catalog(self.catalog_path, self.root),
            )

    def test_event_action_reference_is_validated(self) -> None:
        pack = self._pack()
        pack["content"]["events"] = [
            {
                "event_id": "event.ch02.start",
                "next_event_ids": [],
                "steps": [
                    {
                        "id": "step_1",
                        "action": {
                            "type": "start_battle",
                            "params": {"encounter_id": "encounter.ch99.missing"},
                        },
                    }
                ],
            }
        ]
        evaluation = evaluate_promotion(
            pack,
            load_catalog(self.catalog_path, self.root),
        )
        self.assertTrue(evaluation.blocked)
        self.assertTrue(
            any(
                item["field"] == "steps[0].action.params.encounter_id"
                for item in evaluation.plan["unresolved_references"]
            )
        )

    def test_localization_candidates_are_generated_from_inline_text(self) -> None:
        evaluation = evaluate_promotion(
            self._pack(),
            load_catalog(self.catalog_path, self.root),
        )
        candidates = {
            item["key"]: item["ja"]
            for item in evaluation.plan["localization_candidates"]
        }
        self.assertIn("霧の森", candidates.values())
        self.assertIn("森への一歩", candidates.values())
        self.assertTrue(evaluation.warnings)

    def test_plan_outputs_do_not_modify_master(self) -> None:
        path = self.root / "data/master/quests.sample.json"
        before = path.read_bytes()
        evaluation = evaluate_promotion(
            self._pack(),
            load_catalog(self.catalog_path, self.root),
        )
        output = self.root / "tmp" / "promotion"
        write_outputs(evaluation, output)
        self.assertTrue((output / "PROMOTION_PLAN.json").exists())
        self.assertTrue((output / "PROMOTION_SUMMARY.md").exists())
        self.assertTrue((output / "localization.ja.candidates.json").exists())
        self.assertEqual(before, path.read_bytes())

    def test_strict_cli_returns_two_for_localization_warnings(self) -> None:
        pack_path = self.root / "content/packs/ch02/pack.json"
        write_json(pack_path, self._pack())
        exit_code = main(
            [
                "--catalog",
                str(self.catalog_path),
                "--project-root",
                str(self.root),
                "validate",
                str(pack_path),
                "--strict",
            ]
        )
        self.assertEqual(2, exit_code)


if __name__ == "__main__":
    unittest.main()
