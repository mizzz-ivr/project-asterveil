from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from game.app.application.playable_slice import PlayableSliceApplication
from game.save.application.migration import (
    LEGACY_V0_TIMESTAMP,
    SaveMigrationService,
    SaveMigrationStep,
)
from game.save.cli.migrate_save import main as migrate_cli_main
from game.save.infrastructure.repository import JsonFileSaveRepository


class SaveMigrationTests(unittest.TestCase):
    def _v0_payload(self) -> dict:
        return {
            "save_version": 0,
            "player_profile": {
                "difficulty": "standard",
                "play_time_sec": 88,
            },
            "party_state": {
                "members": [
                    {
                        "character_id": "char.main.rion",
                        "level": 8,
                        "current_hp": 111,
                        "current_sp": 76,
                        "alive": True,
                    }
                ]
            },
            "quest_state": {
                "quest.ch01.missing_port_record": {
                    "status": "active",
                    "objective_progress": [1, 0],
                }
            },
            "world_flags": {"flag.game.new_game_started": True},
        }

    def _v1_payload(self) -> dict:
        return SaveMigrationService().migrate(self._v0_payload()).payload

    def test_v1_is_loaded_without_migration(self) -> None:
        payload = self._v1_payload()

        result = SaveMigrationService().migrate(payload)

        self.assertFalse(result.migrated)
        self.assertEqual(1, result.original_version)
        self.assertEqual(1, result.current_version)
        self.assertEqual(tuple(), result.applied_steps)
        self.assertEqual(payload, result.payload)

    def test_v0_is_migrated_deterministically_without_mutating_input(self) -> None:
        payload = self._v0_payload()
        original = copy.deepcopy(payload)

        first = SaveMigrationService().migrate(payload)
        second = SaveMigrationService().migrate(payload)

        self.assertEqual(original, payload)
        self.assertTrue(first.migrated)
        self.assertEqual(("save_v0_to_v1",), first.applied_steps)
        self.assertEqual(first.payload, second.payload)
        self.assertEqual(1, first.payload["save_version"])
        self.assertEqual(
            LEGACY_V0_TIMESTAMP,
            first.payload["player_profile"]["last_saved_at"],
        )
        member = first.payload["party_state"]["members"][0]
        self.assertEqual(111, member["max_hp"])
        self.assertEqual(76, member["max_sp"])
        self.assertEqual(0, member["current_exp"])
        self.assertEqual({}, member["equipped"])
        quest = first.payload["quest_state"]["quest.ch01.missing_port_record"]
        self.assertEqual([], quest["objective_item_progress"])
        self.assertFalse(quest["reward_claimed"])
        self.assertFalse(quest["repeat_ready"])
        self.assertEqual({}, first.payload["progression"])
        self.assertEqual({}, first.payload["inventory_state"])
        self.assertEqual({}, first.payload["meta"])

    def test_future_version_is_rejected(self) -> None:
        payload = self._v1_payload()
        payload["save_version"] = 2

        with self.assertRaisesRegex(ValueError, "future_save_version_not_supported"):
            SaveMigrationService().migrate(payload)

    def test_missing_migration_step_is_rejected(self) -> None:
        step = SaveMigrationStep(
            from_version=0,
            to_version=1,
            name="test_v0_to_v1",
            migrate=lambda payload: {**payload, "save_version": 1},
        )
        service = SaveMigrationService(current_version=2, steps={0: step})

        with self.assertRaisesRegex(ValueError, "save_migration_step_missing"):
            service.migrate(self._v0_payload())

    def test_repository_load_migrates_in_memory_without_rewriting_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            save_path = Path(directory) / "slot.json"
            original_text = json.dumps(self._v0_payload(), ensure_ascii=False, indent=2)
            save_path.write_text(original_text, encoding="utf-8")
            repository = JsonFileSaveRepository(save_path)

            result = repository.load_with_report()

            self.assertTrue(result.migrated)
            self.assertEqual(original_text, save_path.read_text(encoding="utf-8"))
            self.assertEqual(1, repository.load().save_version)

    def test_explicit_file_migration_creates_backup_and_updates_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            save_path = Path(directory) / "slot.json"
            original_text = json.dumps(self._v0_payload(), ensure_ascii=False, indent=2)
            save_path.write_text(original_text, encoding="utf-8")
            repository = JsonFileSaveRepository(save_path)

            result = repository.migrate_file()

            self.assertTrue(result.file_updated)
            self.assertIsNotNone(result.backup_path)
            assert result.backup_path is not None
            self.assertEqual(original_text, result.backup_path.read_text(encoding="utf-8"))
            migrated_raw = json.loads(save_path.read_text(encoding="utf-8"))
            self.assertEqual(1, migrated_raw["save_version"])
            self.assertEqual(1, repository.load().save_version)

            second = repository.migrate_file()
            self.assertFalse(second.file_updated)
            self.assertIsNone(second.backup_path)

    def test_existing_backup_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            save_path = Path(directory) / "slot.json"
            backup_path = Path(directory) / "existing.bak"
            original_text = json.dumps(self._v0_payload(), ensure_ascii=False, indent=2)
            save_path.write_text(original_text, encoding="utf-8")
            backup_path.write_text("keep", encoding="utf-8")
            repository = JsonFileSaveRepository(save_path)

            with self.assertRaises(FileExistsError):
                repository.migrate_file(backup_path=backup_path)

            self.assertEqual(original_text, save_path.read_text(encoding="utf-8"))
            self.assertEqual("keep", backup_path.read_text(encoding="utf-8"))

    def test_write_failure_restores_pre_migration_file_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            save_path = Path(directory) / "slot.json"
            backup_path = Path(directory) / "slot.backup.json"
            original_text = json.dumps(self._v0_payload(), ensure_ascii=False, indent=2)
            save_path.write_text(original_text, encoding="utf-8")
            repository = JsonFileSaveRepository(save_path)

            with patch.object(
                repository,
                "_atomic_write_payload",
                side_effect=OSError("simulated write failure"),
            ):
                with self.assertRaisesRegex(OSError, "simulated write failure"):
                    repository.migrate_file(backup_path=backup_path)

            self.assertEqual(original_text, save_path.read_text(encoding="utf-8"))
            self.assertFalse(backup_path.exists())

    def test_atomic_save_replaces_existing_file_without_temp_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            save_path = Path(directory) / "slot.json"
            save_path.write_text("old", encoding="utf-8")
            repository = JsonFileSaveRepository(save_path)
            save_data = SaveMigrationService().migrate(self._v0_payload()).save_data

            repository.save(save_data)

            self.assertEqual(1, json.loads(save_path.read_text(encoding="utf-8"))["save_version"])
            self.assertEqual([], list(Path(directory).glob(".slot.json.*.tmp")))

    def test_playable_continue_loads_v0_payload_through_repository_migration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            save_path = Path(directory) / "playable.json"
            app = PlayableSliceApplication(Path("data/master"), save_path)
            app.new_game()
            app.perform_action("save")

            payload = json.loads(save_path.read_text(encoding="utf-8"))
            payload["save_version"] = 0
            payload["player_profile"].pop("last_saved_at", None)
            payload.pop("progression", None)
            payload.pop("inventory_state", None)
            payload.pop("meta", None)
            for member in payload["party_state"]["members"]:
                for key in (
                    "current_exp",
                    "next_level_exp",
                    "max_hp",
                    "max_sp",
                    "atk",
                    "defense",
                    "spd",
                    "equipped",
                    "unlocked_skill_ids",
                    "active_effects",
                ):
                    member.pop(key, None)
            for quest in payload["quest_state"].values():
                quest.pop("objective_item_progress", None)
                quest.pop("reward_claimed", None)
                quest.pop("repeat_ready", None)
            save_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            resumed = PlayableSliceApplication(Path("data/master"), save_path)
            succeeded, message = resumed.continue_game()

            self.assertTrue(succeeded, message)
            self.assertIsNotNone(resumed.quest_session)
            self.assertEqual(0, json.loads(save_path.read_text(encoding="utf-8"))["save_version"])

    def test_cli_dry_run_does_not_rewrite_and_explicit_run_migrates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            save_path = Path(directory) / "slot.json"
            original_text = json.dumps(self._v0_payload(), ensure_ascii=False, indent=2)
            save_path.write_text(original_text, encoding="utf-8")

            output = io.StringIO()
            with redirect_stdout(output):
                dry_run_code = migrate_cli_main([str(save_path), "--dry-run"])
            self.assertEqual(0, dry_run_code)
            self.assertEqual(original_text, save_path.read_text(encoding="utf-8"))
            self.assertTrue(json.loads(output.getvalue())["migrated"])

            output = io.StringIO()
            with redirect_stdout(output):
                migrate_code = migrate_cli_main([str(save_path)])
            self.assertEqual(0, migrate_code)
            result = json.loads(output.getvalue())
            self.assertTrue(result["file_updated"])
            self.assertEqual(1, json.loads(save_path.read_text(encoding="utf-8"))["save_version"])


if __name__ == "__main__":
    unittest.main()
