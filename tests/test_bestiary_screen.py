from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from game.app.application.bestiary_playable_slice import BestiaryPlayableSliceApplication
from game.app.application.bestiary_service import BestiaryRecord, BestiaryUnlockStage
from game.app.application.demo_flow_service import DemoFlowService, SteamDemoApplication
from game.app.infrastructure.demo_flow_repository import DemoFlowMasterDataRepository
from game.app.presentation.bestiary_scene_registry import BestiarySceneBuilderRegistry
from game.app.presentation.bestiary_screen import (
    BestiaryCategoryFilter,
    BestiaryScreenController,
    BestiaryScreenMode,
)
from game.app.presentation.input_actions import MenuInputAction
from game.app.presentation.screen_router import RouteTransitionKind, SteamDemoRouteId
from game.app.steam_demo_composition import SteamDemoCompositionRoot


MASTER_ROOT = Path("data/master")
FLOW_ID = "demo.steam.ch01.core_loop"


class BestiaryScreenTests(unittest.TestCase):
    def build_app(self, save_path: Path) -> BestiaryPlayableSliceApplication:
        app = BestiaryPlayableSliceApplication(
            master_root=MASTER_ROOT,
            save_file_path=save_path,
        )
        app.new_game()
        return app

    def test_unknown_entries_use_opaque_action_ids_and_hide_enemy_information(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            controller = BestiaryScreenController(app)

            view = controller.current_view()

            self.assertEqual(BestiaryScreenMode.LIST, view.mode)
            self.assertEqual(BestiaryCategoryFilter.ALL, view.active_filter)
            self.assertEqual(7, len(view.entries))
            first = view.entries[0]
            self.assertEqual("bestiary.slot.001", first.action_id)
            self.assertEqual("？？？", first.name)
            self.assertEqual(BestiaryUnlockStage.UNKNOWN, first.stage)
            self.assertIsNone(first.category_label)
            self.assertNotIn("enemy.", repr(view))

            detail = controller.activate_entry(first.action_id).view
            self.assertEqual(BestiaryScreenMode.DETAIL, detail.mode)
            self.assertIsNotNone(detail.detail)
            assert detail.detail is not None
            self.assertEqual("？？？", detail.detail.name)
            self.assertIsNone(detail.detail.category_label)
            self.assertEqual(tuple(), detail.detail.habitat_names)
            self.assertIsNone(detail.detail.level)
            self.assertEqual(tuple(), detail.detail.stats)
            self.assertEqual(tuple(), detail.detail.weakness_elements)
            self.assertEqual(tuple(), detail.detail.weakness_weapon_types)
            self.assertIsNone(detail.detail.description)
            self.assertNotIn("enemy.", repr(detail))

    def test_category_filter_does_not_classify_unknown_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            controller = BestiaryScreenController(app)

            filtered = controller.activate_entry("bestiary.filter.boss").view

            self.assertEqual(BestiaryCategoryFilter.BOSS, filtered.active_filter)
            self.assertEqual(tuple(), filtered.entries)

    def test_encountered_and_defeated_entries_show_unlocked_information(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            app.bestiary_state["enemy.ch01.port_wraith"] = BestiaryRecord(
                encounter_count=2,
                battle_win_count=1,
                kill_count=1,
                battle_loss_count=0,
            )
            controller = BestiaryScreenController(app)

            filtered = controller.activate_entry("bestiary.filter.normal").view
            self.assertEqual(1, len(filtered.entries))
            entry = filtered.entries[0]
            self.assertEqual("港の亡霊", entry.name)
            self.assertEqual("通常敵", entry.category_label)
            self.assertEqual(BestiaryUnlockStage.DEFEATED, entry.stage)

            detail = controller.activate_entry(entry.action_id).view
            assert detail.detail is not None
            self.assertEqual("港の亡霊", detail.detail.name)
            self.assertIn("潮だまりの干潟", detail.detail.habitat_names)
            self.assertEqual(6, detail.detail.level)
            self.assertIn(("hp", 150), detail.detail.stats)
            self.assertEqual(("light",), detail.detail.weakness_elements)
            self.assertEqual(("slash",), detail.detail.weakness_weapon_types)
            self.assertIsNone(detail.detail.description)

    def test_cancel_returns_detail_to_list_then_requests_route_close(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            controller = BestiaryScreenController(app)
            controller.activate_entry("bestiary.slot.001")

            from_detail = controller.handle_input(MenuInputAction.CANCEL)
            self.assertFalse(from_detail.cancel_requested)
            self.assertEqual(BestiaryScreenMode.LIST, from_detail.view.mode)

            from_list = controller.handle_input(MenuInputAction.CANCEL)
            self.assertTrue(from_list.cancel_requested)

    def test_scene_registry_never_serializes_unknown_enemy_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            controller = BestiaryScreenController(app)
            registry = BestiarySceneBuilderRegistry()

            scene = registry.build(SteamDemoRouteId.BESTIARY, controller.current_view())
            serialized = json.dumps(scene.to_dict(), ensure_ascii=False)

            self.assertIn("bestiary.slot.001", serialized)
            self.assertNotIn("enemy.", serialized)

            detail_view = controller.activate_entry("bestiary.slot.001").view
            detail_scene = registry.build(SteamDemoRouteId.BESTIARY, detail_view)
            detail_serialized = json.dumps(detail_scene.to_dict(), ensure_ascii=False)
            self.assertNotIn("enemy.", detail_serialized)
            self.assertEqual(tuple(), detail_scene.sections)


class BestiaryRuntimeIntegrationTests(unittest.TestCase):
    def test_top_menu_opens_bestiary_route_and_back_navigation_is_two_stage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = BestiaryPlayableSliceApplication(
                master_root=MASTER_ROOT,
                save_file_path=Path(directory) / "save.json",
            )
            app.new_game()
            definitions = DemoFlowMasterDataRepository(MASTER_ROOT).load()
            demo = SteamDemoApplication(
                app,
                flow_service=DemoFlowService(definitions),
                flow_id=FLOW_ID,
            )
            composition = SteamDemoCompositionRoot.build(app, demo)

            opened = composition.action_dispatcher.activate_entry(
                SteamDemoRouteId.TOP_MENU,
                "bestiary",
            )
            self.assertEqual(RouteTransitionKind.PUSHED, opened.transition.kind)
            self.assertEqual(SteamDemoRouteId.BESTIARY, opened.frame.route_id)
            self.assertIsInstance(
                composition.runtime.active_screen.controller,
                BestiaryScreenController,
            )

            scene = composition.action_dispatcher.current_scene()
            self.assertIsNotNone(scene.command_for_entry("bestiary.slot.001"))
            self.assertNotIn("enemy.", json.dumps(scene.to_dict(), ensure_ascii=False))

            detail = composition.action_dispatcher.activate_entry(
                SteamDemoRouteId.BESTIARY,
                "bestiary.slot.001",
            )
            self.assertEqual(RouteTransitionKind.STAY, detail.transition.kind)
            self.assertEqual(BestiaryScreenMode.DETAIL, detail.frame.view.mode)

            back_to_list = composition.action_dispatcher.handle_input(
                SteamDemoRouteId.BESTIARY,
                MenuInputAction.CANCEL,
            )
            self.assertEqual(RouteTransitionKind.STAY, back_to_list.transition.kind)
            self.assertEqual(BestiaryScreenMode.LIST, back_to_list.frame.view.mode)

            back_to_top = composition.action_dispatcher.handle_input(
                SteamDemoRouteId.BESTIARY,
                MenuInputAction.CANCEL,
            )
            self.assertEqual(RouteTransitionKind.POPPED, back_to_top.transition.kind)
            self.assertEqual(SteamDemoRouteId.TOP_MENU, back_to_top.frame.route_id)


if __name__ == "__main__":
    unittest.main()
