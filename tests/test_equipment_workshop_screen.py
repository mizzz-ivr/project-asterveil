from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from game.app.application.playable_equipment_workshop_facade import (
    PlayableEquipmentWorkshopFacade,
)
from game.app.application.playable_slice import PlayableSliceApplication
from game.app.cli import equipment_workshop_cli
from game.app.presentation.equipment_workshop_screen import (
    EquipmentSalvageScreenController,
    EquipmentUpgradeScreenController,
)
from game.app.presentation.input_actions import MenuInputAction
from game.quest.domain.entities import BattleResult


MEMBER_ID = "char.main.rion"
BRONZE_BLADE_ID = "equip.weapon.bronze_blade"
TIDEBREAKER_ID = "equip.armor.tidebreaker_harness"
IRON_FRAGMENT_ID = "item.material.iron_fragment"
DEEPSEA_THREAD_ID = "item.material.relic.deepsea_thread"
GUARDIAN_CORE_ID = "item.material.miniboss.guardian_core"


class EquipmentWorkshopScreenTestBase(unittest.TestCase):
    def build_app(self, save_path: Path) -> PlayableSliceApplication:
        def battle_executor(encounter_id: str, *_args, **_kwargs) -> BattleResult:
            return BattleResult(
                encounter_id=encounter_id,
                player_won=True,
                defeated_enemy_ids=("enemy.ch01.port_wraith",),
            )

        app = PlayableSliceApplication(
            master_root=Path("data/master"),
            save_file_path=save_path,
            battle_executor=battle_executor,
        )
        app.new_game()
        return app

    def prepare_upgrade_level_one(self, app: PlayableSliceApplication) -> None:
        app.workshop_progress_state.level = 2
        app.inventory_state["items"][TIDEBREAKER_ID] = 1
        app.inventory_state["items"][DEEPSEA_THREAD_ID] = 1
        app.inventory_state["items"][IRON_FRAGMENT_ID] = 2


class EquipmentWorkshopFacadeTests(EquipmentWorkshopScreenTestBase):
    def test_upgrade_option_exposes_materials_rank_and_bonus(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            self.prepare_upgrade_level_one(app)
            facade = PlayableEquipmentWorkshopFacade(app)

            option = facade.list_upgrade_options()[0]

            self.assertEqual(TIDEBREAKER_ID, option.equipment_id)
            self.assertEqual("タイドブレイカーハーネス", option.name)
            self.assertEqual(0, option.current_level)
            self.assertEqual(2, option.max_level)
            self.assertEqual(1, option.next_level)
            self.assertEqual(2, option.required_workshop_level)
            self.assertTrue(option.can_upgrade)
            self.assertEqual("upgradable", option.reason_code)
            self.assertEqual(
                (("def", 2), ("hp", 8)),
                option.stat_bonus,
            )
            materials = {material.item_id: material for material in option.required_materials}
            self.assertEqual(1, materials[DEEPSEA_THREAD_ID].required)
            self.assertEqual(1, materials[DEEPSEA_THREAD_ID].owned)
            self.assertEqual(2, materials[IRON_FRAGMENT_ID].required)
            self.assertTrue(all(material.is_sufficient for material in materials.values()))

    def test_upgrade_executes_and_rechecks_materials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            self.prepare_upgrade_level_one(app)
            facade = PlayableEquipmentWorkshopFacade(app)

            result = facade.upgrade_equipment(TIDEBREAKER_ID)

            self.assertTrue(result.success)
            self.assertEqual(1, app.equipment_upgrade_levels[TIDEBREAKER_ID])
            self.assertNotIn(DEEPSEA_THREAD_ID, app.inventory_state["items"])
            self.assertNotIn(IRON_FRAGMENT_ID, app.inventory_state["items"])
            refreshed = facade.list_upgrade_options()[0]
            self.assertEqual(1, refreshed.current_level)
            self.assertEqual(2, refreshed.next_level)
            self.assertFalse(refreshed.can_upgrade)
            self.assertEqual("insufficient_workshop_level", refreshed.reason_code)

    def test_upgrade_rejects_unknown_material_shortage_rank_and_max_level(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            app.inventory_state["items"][TIDEBREAKER_ID] = 1
            facade = PlayableEquipmentWorkshopFacade(app)

            low_rank = facade.list_upgrade_options()[0]
            unknown = facade.upgrade_equipment("equip.unknown")

            self.assertFalse(low_rank.can_upgrade)
            self.assertEqual("insufficient_workshop_level", low_rank.reason_code)
            self.assertEqual("equipment_not_available", unknown.code)

            app.workshop_progress_state.level = 2
            shortage = facade.list_upgrade_options()[0]
            self.assertEqual("insufficient_materials", shortage.reason_code)

            app.equipment_upgrade_levels[TIDEBREAKER_ID] = 2
            maximum = facade.list_upgrade_options()[0]
            rejected = facade.upgrade_equipment(TIDEBREAKER_ID)
            self.assertEqual("max_level", maximum.reason_code)
            self.assertEqual("max_level", rejected.code)

    def test_salvage_option_distinguishes_equipped_and_available_stock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            facade = PlayableEquipmentWorkshopFacade(app)

            equipped_only = facade.list_salvage_options()[0]
            self.assertEqual(BRONZE_BLADE_ID, equipped_only.equipment_id)
            self.assertEqual(1, equipped_only.owned)
            self.assertEqual(1, equipped_only.equipped_count)
            self.assertEqual(0, equipped_only.available)
            self.assertFalse(equipped_only.can_salvage)
            self.assertEqual("equipped", equipped_only.reason_code)

            app.inventory_state["items"][BRONZE_BLADE_ID] = 2
            available = facade.list_salvage_options()[0]
            self.assertEqual(1, available.available)
            self.assertTrue(available.can_salvage)
            self.assertEqual("salvageable", available.reason_code)
            self.assertEqual(IRON_FRAGMENT_ID, available.returns[0].item_id)
            self.assertEqual(1, available.returns[0].quantity)

    def test_salvage_executes_and_preserves_equipped_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            app.inventory_state["items"][BRONZE_BLADE_ID] = 2
            facade = PlayableEquipmentWorkshopFacade(app)

            result = facade.salvage_equipment(BRONZE_BLADE_ID)

            self.assertTrue(result.success)
            self.assertEqual(1, app.inventory_state["items"][BRONZE_BLADE_ID])
            self.assertEqual(1, app.inventory_state["items"][IRON_FRAGMENT_ID])
            self.assertEqual(BRONZE_BLADE_ID, app.party_members[0].equipped["weapon"])
            refreshed = facade.list_salvage_options()[0]
            self.assertFalse(refreshed.can_salvage)
            self.assertEqual("equipped", refreshed.reason_code)

    def test_upgraded_salvage_returns_bonus_and_clears_upgrade_level(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            app.workshop_progress_state.level = 3
            app.inventory_state["items"][TIDEBREAKER_ID] = 1
            app.equipment_upgrade_levels[TIDEBREAKER_ID] = 2
            facade = PlayableEquipmentWorkshopFacade(app)

            option = next(
                entry
                for entry in facade.list_salvage_options()
                if entry.equipment_id == TIDEBREAKER_ID
            )
            result = facade.salvage_equipment(TIDEBREAKER_ID)

            returns = {entry.item_id: entry.quantity for entry in option.returns}
            self.assertEqual(1, returns[DEEPSEA_THREAD_ID])
            self.assertEqual(2, returns[IRON_FRAGMENT_ID])
            self.assertTrue(result.success)
            self.assertNotIn(TIDEBREAKER_ID, app.inventory_state["items"])
            self.assertNotIn(TIDEBREAKER_ID, app.equipment_upgrade_levels)
            self.assertEqual(1, app.inventory_state["items"][DEEPSEA_THREAD_ID])
            self.assertEqual(2, app.inventory_state["items"][IRON_FRAGMENT_ID])


class EquipmentWorkshopControllerTests(EquipmentWorkshopScreenTestBase):
    def test_upgrade_controller_executes_direct_id_and_supports_guide_cancel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            self.prepare_upgrade_level_one(app)
            controller = EquipmentUpgradeScreenController(
                PlayableEquipmentWorkshopFacade(app)
            )

            guide = controller.handle_input(MenuInputAction.SHOW_GUIDE)
            executed = controller.activate_equipment(TIDEBREAKER_ID)
            cancel = controller.handle_input(MenuInputAction.CANCEL)

            self.assertTrue(guide.logs[0].startswith("equipment_upgrade_guide:"))
            self.assertIsNone(executed.rejection_reason)
            self.assertEqual(1, app.equipment_upgrade_levels[TIDEBREAKER_ID])
            self.assertTrue(cancel.cancel_requested)

    def test_salvage_controller_rejects_disabled_and_executes_available(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            controller = EquipmentSalvageScreenController(
                PlayableEquipmentWorkshopFacade(app)
            )

            rejected = controller.activate_equipment(BRONZE_BLADE_ID)
            app.inventory_state["items"][BRONZE_BLADE_ID] = 2
            executed = controller.activate_equipment(BRONZE_BLADE_ID)
            guide = controller.handle_input(MenuInputAction.SHOW_GUIDE)

            self.assertEqual("equipped", rejected.rejection_reason)
            self.assertIsNone(executed.rejection_reason)
            self.assertTrue(guide.logs[0].startswith("equipment_salvage_guide:"))


class EquipmentWorkshopCliAdapterTests(EquipmentWorkshopScreenTestBase):
    def test_upgrade_cli_uses_new_controller(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            self.prepare_upgrade_level_one(app)

            with patch.object(
                equipment_workshop_cli.base_cli,
                "_choose",
                return_value=TIDEBREAKER_ID,
            ):
                logs = equipment_workshop_cli.run_equipment_upgrade_screen(app)

            self.assertTrue(
                any(line.startswith("equipment_upgrade_success:") for line in logs)
            )
            self.assertEqual(1, app.equipment_upgrade_levels[TIDEBREAKER_ID])

    def test_salvage_cli_uses_new_controller(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            app.inventory_state["items"][BRONZE_BLADE_ID] = 2

            with patch.object(
                equipment_workshop_cli.base_cli,
                "_choose",
                return_value=BRONZE_BLADE_ID,
            ):
                logs = equipment_workshop_cli.run_equipment_salvage_screen(app)

            self.assertTrue(
                any(line.startswith("equipment_salvage_success:") for line in logs)
            )
            self.assertEqual(1, app.inventory_state["items"][BRONZE_BLADE_ID])


if __name__ == "__main__":
    unittest.main()
