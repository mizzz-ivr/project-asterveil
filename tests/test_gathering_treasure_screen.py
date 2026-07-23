from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from game.app.application.playable_exploration_facade import PlayableExplorationFacade
from game.app.application.playable_slice import PlayableSliceApplication
from game.app.cli import run_steam_demo
from game.app.presentation.gathering_treasure_screen import (
    GatheringScreenController,
    TreasureScreenController,
)
from game.app.presentation.input_actions import MenuInputAction


TOWN_GATHERING_NODE_ID = "node.herb.astel_backyard_01"
TOWN_TREASURE_ID = "reward.treasure.astel_storehouse_chest"
LOCKED_TREASURE_ID = "reward.discovery.astel_locked_cache"


class GatheringTreasureScreenTestBase(unittest.TestCase):
    def build_app(self, save_path: Path) -> PlayableSliceApplication:
        app = PlayableSliceApplication(
            master_root=Path("data/master"),
            save_file_path=save_path,
        )
        app.new_game()
        return app


class PlayableExplorationFacadeTests(GatheringTreasureScreenTestBase):
    def test_lists_gathering_nodes_with_respawn_information(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            facade = PlayableExplorationFacade(app)

            nodes = facade.list_gathering_nodes()

            node = next(item for item in nodes if item.node_id == TOWN_GATHERING_NODE_ID)
            self.assertTrue(node.can_gather)
            self.assertFalse(node.is_gathered)
            self.assertEqual("on_rest", node.respawn_rule)
            self.assertIn("宿屋", node.respawn_description)
            self.assertTrue(node.description)

    def test_gather_applies_inventory_and_refreshes_availability(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            facade = PlayableExplorationFacade(app)
            before = app.inventory_state.get("items", {}).get(
                "item.consumable.antidote_leaf",
                0,
            )

            result = facade.gather(TOWN_GATHERING_NODE_ID)
            refreshed = next(
                item
                for item in facade.list_gathering_nodes()
                if item.node_id == TOWN_GATHERING_NODE_ID
            )

            self.assertTrue(result.success)
            self.assertIn(f"gathered:{TOWN_GATHERING_NODE_ID}", result.logs)
            self.assertGreater(
                app.inventory_state["items"]["item.consumable.antidote_leaf"],
                before,
            )
            self.assertTrue(refreshed.is_gathered)
            self.assertFalse(refreshed.can_gather)
            self.assertEqual("already_gathered", refreshed.reason_code)

    def test_lists_treasure_nodes_with_lock_conditions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            facade = PlayableExplorationFacade(app)

            nodes = facade.list_treasure_nodes()

            openable = next(
                item for item in nodes if item.reward_node_id == TOWN_TREASURE_ID
            )
            locked = next(
                item for item in nodes if item.reward_node_id == LOCKED_TREASURE_ID
            )
            self.assertTrue(openable.can_open)
            self.assertTrue(openable.one_time)
            self.assertTrue(openable.description)
            self.assertFalse(locked.can_open)
            self.assertEqual("required_flag_missing", locked.reason_code)
            self.assertIn("flag.ch01.port_record_restored", locked.required_flags)

    def test_open_treasure_applies_inventory_and_prevents_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            facade = PlayableExplorationFacade(app)
            before = app.inventory_state.get("items", {}).get(
                "item.consumable.focus_drop",
                0,
            )

            result = facade.open_treasure(TOWN_TREASURE_ID)
            reopened = facade.open_treasure(TOWN_TREASURE_ID)

            self.assertTrue(result.success)
            self.assertIn(f"treasure_opened:{TOWN_TREASURE_ID}", result.logs)
            self.assertGreater(
                app.inventory_state["items"]["item.consumable.focus_drop"],
                before,
            )
            self.assertFalse(reopened.success)
            self.assertEqual("already_opened", reopened.code)
            self.assertIn(TOWN_TREASURE_ID, app.opened_treasure_node_ids)


class GatheringScreenControllerTests(GatheringTreasureScreenTestBase):
    def test_controller_executes_node_and_rebuilds_view(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            controller = GatheringScreenController(PlayableExplorationFacade(app))

            initial = controller.current_view()
            executed = controller.activate_node(TOWN_GATHERING_NODE_ID)
            repeated = controller.activate_node(TOWN_GATHERING_NODE_ID)

            self.assertTrue(any(node.can_gather for node in initial.nodes))
            executed_node = next(
                node
                for node in executed.view.nodes
                if node.node_id == TOWN_GATHERING_NODE_ID
            )
            self.assertFalse(executed_node.can_gather)
            self.assertIsNone(executed.rejection_reason)
            self.assertEqual("already_gathered", repeated.rejection_reason)

    def test_unknown_node_back_and_guide_are_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            controller = GatheringScreenController(PlayableExplorationFacade(app))

            unknown = controller.activate_node("node.unknown")
            guide = controller.handle_input(MenuInputAction.SHOW_GUIDE)
            back = controller.handle_input(MenuInputAction.CANCEL)

            self.assertEqual("node_not_available", unknown.rejection_reason)
            self.assertTrue(guide.logs[0].startswith("gathering_guide:"))
            self.assertTrue(back.cancel_requested)


class TreasureScreenControllerTests(GatheringTreasureScreenTestBase):
    def test_controller_opens_reward_and_disables_opened_node(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            controller = TreasureScreenController(PlayableExplorationFacade(app))

            opened = controller.activate_node(TOWN_TREASURE_ID)
            repeated = controller.activate_node(TOWN_TREASURE_ID)

            opened_node = next(
                node
                for node in opened.view.nodes
                if node.reward_node_id == TOWN_TREASURE_ID
            )
            self.assertTrue(opened_node.is_opened)
            self.assertFalse(opened_node.can_open)
            self.assertIsNone(opened.rejection_reason)
            self.assertEqual("already_opened", repeated.rejection_reason)

    def test_locked_unknown_back_and_guide_are_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            controller = TreasureScreenController(PlayableExplorationFacade(app))

            locked = controller.activate_node(LOCKED_TREASURE_ID)
            unknown = controller.activate_node("reward.unknown")
            guide = controller.handle_input(MenuInputAction.SHOW_GUIDE)
            back = controller.handle_input(MenuInputAction.CANCEL)

            self.assertEqual("required_flag_missing", locked.rejection_reason)
            self.assertEqual("reward_not_available", unknown.rejection_reason)
            self.assertTrue(guide.logs[0].startswith("treasure_guide:"))
            self.assertTrue(back.cancel_requested)


class SteamDemoCliGatheringTreasureAdapterTests(GatheringTreasureScreenTestBase):
    def test_gathering_cli_uses_new_controller(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")

            with patch.object(
                run_steam_demo.base_cli,
                "_choose",
                return_value=TOWN_GATHERING_NODE_ID,
            ):
                logs = run_steam_demo._run_gathering_screen(app)

            self.assertIn(f"gathered:{TOWN_GATHERING_NODE_ID}", logs)
            self.assertIn(TOWN_GATHERING_NODE_ID, app.gathered_node_ids)

    def test_treasure_cli_uses_new_controller(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")

            with patch.object(
                run_steam_demo.base_cli,
                "_choose",
                return_value=TOWN_TREASURE_ID,
            ):
                logs = run_steam_demo._run_treasure_screen(app)

            self.assertIn(f"treasure_opened:{TOWN_TREASURE_ID}", logs)
            self.assertIn(TOWN_TREASURE_ID, app.opened_treasure_node_ids)


if __name__ == "__main__":
    unittest.main()
