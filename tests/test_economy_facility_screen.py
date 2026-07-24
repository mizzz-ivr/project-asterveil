from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from game.app.application.playable_economy_facility_facade import (
    PlayableEconomyFacilityFacade,
)
from game.app.application.playable_slice import PlayableSliceApplication
from game.app.cli import economy_facility_cli
from game.app.presentation.economy_facility_screen import (
    CraftingScreenController,
    InnScreenController,
    ShopScreenController,
)
from game.app.presentation.input_actions import MenuInputAction
from game.quest.domain.entities import BattleResult
from game.save.domain.entities import PartyActiveEffectState


POTION_ID = "item.consumable.mini_potion"
LOCKED_SHOP_ITEM_ID = "equip.weapon.prayer_staff"
MEMORY_TONIC_RECIPE_ID = "recipe.craft.memory_tonic"
MEMORY_SHARD_ID = "item.material.memory_shard"
MEMORY_TONIC_ID = "item.consumable.memory_tonic"
REST_NODE_ID = "node.herb.astel_backyard_01"
POISON_EFFECT_ID = "effect.ailment.poison"


class EconomyFacilityScreenTestBase(unittest.TestCase):
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


class EconomyFacilityFacadeTests(EconomyFacilityScreenTestBase):
    def test_shop_summary_and_purchase_update_gold_and_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            facade = PlayableEconomyFacilityFacade(app)

            summary = facade.shop_summary()
            potion = next(item for item in summary.items if item.item_id == POTION_ID)
            result = facade.purchase_item(POTION_ID)
            refreshed = facade.shop_summary()

            self.assertTrue(summary.success)
            self.assertEqual("港町アステル 雑貨店", summary.name)
            self.assertEqual(1, summary.facility_level)
            self.assertEqual(300, summary.gold)
            self.assertEqual(50, potion.price)
            self.assertEqual(3, potion.owned)
            self.assertTrue(potion.can_purchase)
            self.assertTrue(result.success)
            self.assertEqual(250, refreshed.gold)
            self.assertEqual(
                4,
                next(item for item in refreshed.items if item.item_id == POTION_ID).owned,
            )

    def test_shop_rejects_insufficient_gold_locked_stock_and_unknown_item(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            facade = PlayableEconomyFacilityFacade(app)
            app.inventory_state["gold"] = 0

            potion = next(
                item for item in facade.shop_summary().items if item.item_id == POTION_ID
            )
            no_gold = facade.purchase_item(POTION_ID)
            locked = facade.purchase_item(LOCKED_SHOP_ITEM_ID)
            unknown = facade.purchase_item("item.unknown")

            self.assertFalse(potion.can_purchase)
            self.assertEqual("insufficient_gold", potion.reason_code)
            self.assertEqual("insufficient_gold", no_gold.code)
            self.assertEqual("shop_stock_locked", locked.code)
            self.assertEqual("item_not_sold", unknown.code)
            self.assertEqual(3, app.inventory_state["items"][POTION_ID])

    def test_crafting_summary_separates_discovery_unlock_and_material_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            facade = PlayableEconomyFacilityFacade(app)

            recipe = next(
                entry
                for entry in facade.crafting_summary().recipes
                if entry.recipe_id == MEMORY_TONIC_RECIPE_ID
            )

            self.assertFalse(recipe.is_discovered)
            self.assertTrue(recipe.discovery_requirement_met)
            self.assertTrue(recipe.is_unlocked)
            self.assertFalse(recipe.can_craft)
            self.assertEqual("missing_material", recipe.reason_code)
            memory_shard = next(
                material for material in recipe.materials if material.item_id == MEMORY_SHARD_ID
            )
            self.assertEqual(0, memory_shard.owned)
            self.assertEqual(1, memory_shard.required)
            self.assertFalse(memory_shard.is_sufficient)
            self.assertEqual(MEMORY_TONIC_ID, recipe.outputs[0].item_id)

    def test_craft_recipe_consumes_materials_and_grants_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            app.inventory_state["items"][MEMORY_SHARD_ID] = 1
            facade = PlayableEconomyFacilityFacade(app)

            ready = next(
                entry
                for entry in facade.crafting_summary().recipes
                if entry.recipe_id == MEMORY_TONIC_RECIPE_ID
            )
            result = facade.craft_recipe(MEMORY_TONIC_RECIPE_ID)

            self.assertTrue(ready.can_craft)
            self.assertTrue(result.success)
            self.assertNotIn(MEMORY_SHARD_ID, app.inventory_state["items"])
            self.assertNotIn("item.consumable.antidote_leaf", app.inventory_state["items"])
            self.assertEqual(1, app.inventory_state["items"][MEMORY_TONIC_ID])

    def test_crafting_rejects_missing_material_locked_and_unknown_recipe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            facade = PlayableEconomyFacilityFacade(app)

            missing = facade.craft_recipe(MEMORY_TONIC_RECIPE_ID)
            locked = facade.craft_recipe("recipe.craft.tidebreaker_harness")
            unknown = facade.craft_recipe("recipe.unknown")

            self.assertEqual("missing_material", missing.code)
            self.assertIn(
                locked.code,
                {
                    "required_flag_missing",
                    "required_workshop_rank_missing",
                    "required_recipe_discovery_missing",
                },
            )
            self.assertEqual("recipe_not_available", unknown.code)

    def test_inn_summary_and_stay_restore_party_clear_effect_and_respawn_node(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            member = app.party_members[0]
            member.current_hp = 1
            member.current_sp = 2
            member.alive = False
            member.active_effects = [
                PartyActiveEffectState(effect_id=POISON_EFFECT_ID, remaining_turns=3)
            ]
            app.gathered_node_ids.add(REST_NODE_ID)
            facade = PlayableEconomyFacilityFacade(app)

            summary = facade.inn_summary()
            result = facade.stay_at_inn()
            refreshed = facade.inn_summary()

            self.assertTrue(summary.success)
            self.assertEqual("潮風亭", summary.name)
            self.assertEqual(120, summary.stay_price)
            self.assertTrue(summary.can_stay)
            self.assertIn(
                POISON_EFFECT_ID,
                summary.party_members[0].clear_on_rest_effect_ids,
            )
            self.assertTrue(result.success)
            self.assertEqual(180, refreshed.gold)
            self.assertTrue(member.alive)
            self.assertEqual(refreshed.party_members[0].max_hp, member.current_hp)
            self.assertEqual(refreshed.party_members[0].max_sp, member.current_sp)
            self.assertEqual([], member.active_effects)
            self.assertNotIn(REST_NODE_ID, app.gathered_node_ids)

    def test_inn_rejects_insufficient_gold_empty_party_and_unknown_inn(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            facade = PlayableEconomyFacilityFacade(app)
            app.inventory_state["gold"] = 0

            no_gold = facade.inn_summary()
            rejected = facade.stay_at_inn()
            unknown = facade.inn_summary("inn.unknown")
            app.party_members = []
            invalid_party = facade.inn_summary()

            self.assertFalse(no_gold.can_stay)
            self.assertEqual("insufficient_gold", no_gold.reason_code)
            self.assertEqual("insufficient_gold", rejected.code)
            self.assertFalse(unknown.success)
            self.assertEqual("inn_not_found", unknown.code)
            self.assertFalse(invalid_party.can_stay)
            self.assertEqual("invalid_party", invalid_party.reason_code)


class EconomyFacilityControllerTests(EconomyFacilityScreenTestBase):
    def test_shop_controller_rejects_disabled_and_unknown_item_without_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            app.inventory_state["gold"] = 0
            controller = ShopScreenController(PlayableEconomyFacilityFacade(app))

            disabled = controller.activate_item(POTION_ID)
            unknown = controller.activate_item("item.unknown")
            guide = controller.handle_input(MenuInputAction.SHOW_GUIDE)
            cancelled = controller.handle_input(MenuInputAction.CANCEL)

            self.assertEqual("insufficient_gold", disabled.rejection_reason)
            self.assertEqual("item_not_sold", unknown.rejection_reason)
            self.assertTrue(guide.logs[0].startswith("shop_guide:"))
            self.assertTrue(cancelled.cancel_requested)
            self.assertEqual(3, app.inventory_state["items"][POTION_ID])

    def test_crafting_controller_updates_view_and_rejects_unknown_recipe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            app.inventory_state["items"][MEMORY_SHARD_ID] = 1
            controller = CraftingScreenController(PlayableEconomyFacilityFacade(app))

            executed = controller.activate_recipe(MEMORY_TONIC_RECIPE_ID)
            unknown = controller.activate_recipe("recipe.unknown")
            guide = controller.handle_input(MenuInputAction.SHOW_GUIDE)

            self.assertIsNone(executed.rejection_reason)
            refreshed = next(
                recipe
                for recipe in executed.view.summary.recipes
                if recipe.recipe_id == MEMORY_TONIC_RECIPE_ID
            )
            self.assertFalse(refreshed.can_craft)
            self.assertEqual("recipe_not_available", unknown.rejection_reason)
            self.assertTrue(guide.logs[0].startswith("crafting_guide:"))

    def test_inn_controller_rejects_unknown_action_and_handles_guide_and_cancel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            controller = InnScreenController(PlayableEconomyFacilityFacade(app))

            unknown = controller.activate_stay("unknown")
            guide = controller.handle_input(MenuInputAction.SHOW_GUIDE)
            cancelled = controller.handle_input(MenuInputAction.CANCEL)

            self.assertEqual("unknown_action", unknown.rejection_reason)
            self.assertTrue(guide.logs[0].startswith("inn_guide:"))
            self.assertTrue(cancelled.cancel_requested)
            self.assertEqual(300, app.inventory_state["gold"])


class EconomyFacilityCliAdapterTests(EconomyFacilityScreenTestBase):
    def test_shop_cli_uses_new_controller(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")

            with patch.object(
                economy_facility_cli.base_cli,
                "_choose",
                return_value=POTION_ID,
            ):
                logs = economy_facility_cli.run_shop_screen(app)

            self.assertTrue(any(line.startswith("purchase_succeeded:") for line in logs))
            self.assertEqual(250, app.inventory_state["gold"])

    def test_crafting_cli_uses_new_controller(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            app.inventory_state["items"][MEMORY_SHARD_ID] = 1

            with patch.object(
                economy_facility_cli.base_cli,
                "_choose",
                return_value=MEMORY_TONIC_RECIPE_ID,
            ):
                logs = economy_facility_cli.run_crafting_screen(app)

            self.assertIn(f"crafted:{MEMORY_TONIC_RECIPE_ID}", logs)
            self.assertEqual(1, app.inventory_state["items"][MEMORY_TONIC_ID])

    def test_inn_cli_uses_new_controller(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            app.party_members[0].current_hp = 1

            with patch.object(
                economy_facility_cli.base_cli,
                "_choose",
                return_value=InnScreenController.STAY_ACTION_ID,
            ):
                logs = economy_facility_cli.run_inn_screen(app)

            self.assertTrue(any(line.startswith("inn_stay_succeeded:") for line in logs))
            self.assertEqual(180, app.inventory_state["gold"])


if __name__ == "__main__":
    unittest.main()
