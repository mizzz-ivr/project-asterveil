import tempfile
import unittest
from pathlib import Path

from tools.chapter_content_pack import (
    ContentPackError,
    create_template,
    diff_packs,
    generate,
    validate_pack,
)


def build_pack() -> dict[str, object]:
    return {
        "schema_version": 1,
        "chapter_id": "ch02",
        "title": "霧都の残響",
        "estimated_play_minutes": 45,
        "content": {
            "locations": [
                {"location_id": "location.ch02.mist_harbor", "name": "霧港"}
            ],
            "encounters": [
                {
                    "encounter_id": "encounter.ch02.mist_wolf",
                    "enemies": [{"enemy_id": "enemy.ch02.mist_wolf", "count": 1}],
                }
            ],
            "quests": [
                {
                    "quest_id": "quest.ch02.first_trace",
                    "title": "最初の痕跡",
                    "availability": {
                        "required_quest_ids": [],
                        "required_flags": [],
                        "min_level": 1,
                    },
                    "encounter_id": "encounter.ch02.mist_wolf",
                    "target_location_id": "location.ch02.mist_harbor",
                    "objectives": [
                        {"id": "obj.ch02.first_trace.kill", "type": "kill_enemy"}
                    ],
                    "reward": {"exp": 100, "gold": 50, "items": []},
                }
            ],
            "events": [
                {"event_id": "event.ch02.opening", "next_event_ids": []}
            ],
            "conversations": [],
        },
    }


class ChapterContentPackTest(unittest.TestCase):
    def test_valid_pack(self) -> None:
        self.assertEqual(validate_pack(build_pack()).counts["quests"], 1)

    def test_duplicate_id_is_rejected(self) -> None:
        pack = build_pack()
        quests = pack["content"]["quests"]
        quests.append(dict(quests[0]))
        with self.assertRaises(ContentPackError):
            validate_pack(pack)

    def test_missing_reference_is_rejected(self) -> None:
        pack = build_pack()
        pack["content"]["quests"][0]["encounter_id"] = "encounter.ch02.none"
        with self.assertRaises(ContentPackError):
            validate_pack(pack)

    def test_dependency_cycle_is_rejected(self) -> None:
        pack = build_pack()
        second = dict(pack["content"]["quests"][0])
        second["quest_id"] = "quest.ch02.second"
        second["availability"] = {"required_quest_ids": ["quest.ch02.first_trace"]}
        pack["content"]["quests"][0]["availability"] = {
            "required_quest_ids": ["quest.ch02.second"]
        }
        pack["content"]["quests"].append(second)
        with self.assertRaises(ContentPackError):
            validate_pack(pack)

    def test_multistage_objective_sequence(self) -> None:
        pack = build_pack()
        quest = pack["content"]["quests"][0]
        quest["objectives"] = [
            {"id": "obj.ch02.a", "next_objective_id": "obj.ch02.b"},
            {"id": "obj.ch02.b"},
        ]
        quest["objective_sequence"] = ["obj.ch02.a", "obj.ch02.b"]
        validate_pack(pack)

    def test_generate_outputs_manifest_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            generate(build_pack(), Path(directory))
            self.assertTrue((Path(directory) / "CONTENT_PACK_MANIFEST.json").exists())
            self.assertTrue((Path(directory) / "SUMMARY.md").exists())

    def test_removed_persistent_id_is_compatibility_risk(self) -> None:
        old = build_pack()
        new = build_pack()
        new["content"]["events"] = []
        self.assertTrue(diff_packs(old, new)["compatibility_risks"])

    def test_template_creation(self) -> None:
        self.assertEqual(create_template("ch03", "第三章")["chapter_id"], "ch03")


if __name__ == "__main__":
    unittest.main()
