from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from game.app.application.playable_party_menu_facade import PlayablePartyMenuFacade
from game.app.application.playable_slice import PlayableSliceApplication
from game.app.cli import item_equipment_cli
from game.app.presentation.input_actions import MenuInputAction
from game.app.presentation.item_equipment_screen import (
    EquipmentScreenController,
    EquipmentScreenMode,
    ItemUseScreenController,
    ItemUseScreenMode,
)
from game.quest.domain.entities import BattleResult


MEMBER_ID = "char.main.rion"
POTION_ID = "item.consumable.mini_potion"
BRONZE_BLADE_ID = "equip.weapon.bronze_blade"
IRON_BLADE_ID = "equip.weapon.iron_blade"
LEATHER_JACKET_ID = "equip.armor.leather_jacket"


class ItemEquipmentScreenTestBase(unittest.TestCase):
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


class PartyMenuFacadeTests(ItemEquipmentScreenTestBase):
    def test_lists_typed_items_members_slots_and_equipment_options(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            facade = PlayablePartyMenuFacade(app)

            potion = next(item for item in facade.list_usable_items() if item.item_id == POTION_ID)
            member = facade.list_party_members()[0]
            slots = facade.list_equipment_slots(MEMBER_ID)
            bronze = next(
                option
                for option in facade.list_equipment_options(MEMBER_ID, "weapon")
                if option.equipment_id == BRONZE_BLADE_ID
            )

            self.assertEqual("ミニポーション", potion.name)
            self.assertEqual(3, potion.amount)
            self.assertEqual("recover_hp", potion.effect_type)
            self.assertEqual(MEMBER_ID, member.character_id)
            self.assertEqual(("weapon", "armor", "accessory"), tuple(slot.slot_type for slot in slots))
            self.assertEqual(1, bronze.owned)
            self.assertEqual(1, bronze.equipped_count)
            self.assertEqual(0, bronze.available)
            self.assertTrue(bronze.is_current)
            self.assertTrue(bronze.can_equip)
            self.assertEqual(4, bronze.atk_bonus)

    def test_use_item_rechecks_target_and_updates_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            app.party_members[0].current_hp = 60
            facade = PlayablePartyMenuFacade(app)

            targets = facade.list_item_targets(POTION_ID)
            result = facade.use_item(POTION_ID, MEMBER_ID)

            self.assertTrue(targets[0].can_use)
            self.assertTrue(result.success)
            self.assertEqual(100, app.party_members[0].current_hp)
            self.assertEqual(2, app.inventory_state["items"][POTION_ID])

    def test_full_hp_unknown_item_and_unknown_target_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            facade = PlayablePartyMenuFacade(app)

            target = facade.list_item_targets(POTION_ID)[0]
            full_hp = facade.use_item(POTION_ID, MEMBER_ID)
            unknown_item = facade.use_item("item.unknown", MEMBER_ID)
            unknown_target = facade.use_item(POTION_ID, "char.unknown")

            self.assertFalse(target.can_use)
            self.assertEqual("hp_full", target.reason_code)
            self.assertFalse(full_hp.success)
            self.assertEqual("hp_full", full_hp.code)
            self.assertEqual("item_not_available", unknown_item.code)
            self.assertEqual("target_not_available", unknown_target.code)
            self.assertEqual(3, app.inventory_state["items"][POTION_ID])

    def test_item_target_check_matches_existing_item_use_contract_with_hp_bonus(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            app.inventory_state["items"][LEATHER_JACKET_ID] = 1
            app.equip_item(MEMBER_ID, "armor", LEATHER_JACKET_ID)
            facade = PlayablePartyMenuFacade(app)

            member = facade.list_party_members()[0]
            target = facade.list_item_targets(POTION_ID)[0]
            result = facade.use_item(POTION_ID, MEMBER_ID)

            self.assertEqual(120, member.current_hp)
            self.assertEqual(132, member.max_hp)
            self.assertEqual(app.party_members[0].current_hp, app.party_members[0].max_hp)
            self.assertFalse(target.can_use)
            self.assertEqual("hp_full", target.reason_code)
            self.assertFalse(result.success)
            self.assertEqual("hp_full", result.code)
            self.assertEqual(3, app.inventory_state["items"][POTION_ID])

    def test_equipment_rechecks_stock_and_updates_member(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            app.inventory_state["items"][IRON_BLADE_ID] = 1
            facade = PlayablePartyMenuFacade(app)

            result = facade.equip_item(MEMBER_ID, "weapon", IRON_BLADE_ID)
            current = next(
                option
                for option in facade.list_equipment_options(MEMBER_ID, "weapon")
                if option.equipment_id == IRON_BLADE_ID
            )
            unavailable = next(
                option
                for option in facade.list_equipment_options(MEMBER_ID, "weapon")
                if option.equipment_id == "equip.weapon.memory_edge"
            )

            self.assertTrue(result.success)
            self.assertEqual(IRON_BLADE_ID, app.party_members[0].equipped["weapon"])
            self.assertTrue(current.is_current)
            self.assertTrue(current.can_equip)
            self.assertFalse(unavailable.can_equip)
            self.assertEqual(0, unavailable.available)


class ItemUseScreenControllerTests(ItemEquipmentScreenTestBase):
    def test_item_and_target_selection_executes_and_returns_to_item_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            app.party_members[0].current_hp = 60
            controller = ItemUseScreenController(PlayablePartyMenuFacade(app))

            initial = controller.current_view()
            target_view = controller.activate_item(POTION_ID)
            executed = controller.activate_target(MEMBER_ID)

            self.assertEqual(ItemUseScreenMode.ITEM_LIST, initial.mode)
            self.assertEqual(ItemUseScreenMode.TARGET_LIST, target_view.view.mode)
            self.assertEqual(ItemUseScreenMode.ITEM_LIST, executed.view.mode)
            self.assertIn(f"item_used:{POTION_ID}:target={MEMBER_ID}", executed.logs)

    def test_disabled_target_unknown_item_back_and_guide_are_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            controller = ItemUseScreenController(PlayablePartyMenuFacade(app))

            unknown = controller.activate_item("item.unknown")
            controller.activate_item(POTION_ID)
            disabled = controller.activate_target(MEMBER_ID)
            guide = controller.handle_input(MenuInputAction.SHOW_GUIDE)
            back = controller.handle_input(MenuInputAction.CANCEL)

            self.assertEqual("item_not_available", unknown.rejection_reason)
            self.assertEqual("hp_full", disabled.rejection_reason)
            self.assertTrue(guide.logs[0].startswith("item_target_guide:"))
            self.assertEqual(ItemUseScreenMode.ITEM_LIST, back.view.mode)


class EquipmentScreenControllerTests(ItemEquipmentScreenTestBase):
    def test_member_slot_and_equipment_selection_updates_view(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            controller = EquipmentScreenController(PlayablePartyMenuFacade(app))

            initial = controller.current_view()
            slots = controller.activate_member(MEMBER_ID)
            options = controller.activate_slot("weapon")
            equipped = controller.activate_equipment(BRONZE_BLADE_ID)

            self.assertEqual(EquipmentScreenMode.MEMBER_LIST, initial.mode)
            self.assertEqual(EquipmentScreenMode.SLOT_LIST, slots.view.mode)
            self.assertEqual(EquipmentScreenMode.EQUIPMENT_LIST, options.view.mode)
            self.assertIsNone(equipped.rejection_reason)
            self.assertEqual(BRONZE_BLADE_ID, app.party_members[0].equipped["weapon"])
            self.assertTrue(
                next(
                    option
                    for option in equipped.view.equipment_options
                    if option.equipment_id == BRONZE_BLADE_ID
                ).is_current
            )

    def test_invalid_member_slot_equipment_back_and_guide_are_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            controller = EquipmentScreenController(PlayablePartyMenuFacade(app))

            invalid_member = controller.activate_member("char.unknown")
            controller.activate_member(MEMBER_ID)
            invalid_slot = controller.activate_slot("invalid")
            controller.activate_slot("weapon")
            invalid_equipment = controller.activate_equipment("equip.weapon.unknown")
            guide = controller.handle_input(MenuInputAction.SHOW_GUIDE)
            back = controller.handle_input(MenuInputAction.CANCEL)

            self.assertEqual("member_not_available", invalid_member.rejection_reason)
            self.assertEqual("invalid_slot", invalid_slot.rejection_reason)
            self.assertEqual("equipment_not_available", invalid_equipment.rejection_reason)
            self.assertTrue(guide.logs[0].startswith("equipment_option_guide:"))
            self.assertEqual(EquipmentScreenMode.SLOT_LIST, back.view.mode)


class ItemEquipmentCliAdapterTests(ItemEquipmentScreenTestBase):
    def test_item_use_cli_uses_new_controller(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            app.party_members[0].current_hp = 60

            with patch.object(
                item_equipment_cli.base_cli,
                "_choose",
                side_effect=[POTION_ID, MEMBER_ID],
            ):
                logs = item_equipment_cli.run_item_use_screen(app)

            self.assertIn(f"item_used:{POTION_ID}:target={MEMBER_ID}", logs)
            self.assertEqual(2, app.inventory_state["items"][POTION_ID])

    def test_equipment_cli_uses_new_controller(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")

            with patch.object(
                item_equipment_cli.base_cli,
                "_choose",
                side_effect=[MEMBER_ID, "weapon", BRONZE_BLADE_ID],
            ):
                logs = item_equipment_cli.run_equipment_screen(app)

            self.assertTrue(any(line.startswith("equip_succeeded:") for line in logs))
            self.assertEqual(BRONZE_BLADE_ID, app.party_members[0].equipped["weapon"])


if __name__ == "__main__":
    unittest.main()
