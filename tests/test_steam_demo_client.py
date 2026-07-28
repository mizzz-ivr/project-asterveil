from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from game.app.application.demo_flow_service import DemoFlowService, SteamDemoApplication
from game.app.application.playable_slice import PlayableSliceApplication
from game.app.client.steam_demo_client import (
    SteamDemoClientController,
    SteamDemoClientPhase,
    SteamDemoClientSettings,
    SteamDemoTitleAction,
)
from game.app.client.tk_steam_demo import format_scene_entry, format_scene_field
from game.app.infrastructure.demo_flow_repository import DemoFlowMasterDataRepository
from game.app.presentation.input_actions import MenuInputAction
from game.app.presentation.screen_renderer import SceneEntry, SceneField
from game.app.presentation.screen_router import SteamDemoRouteId


FLOW_ID = "demo.steam.ch01.core_loop"
MASTER_ROOT = Path("data/master")


class SteamDemoClientTestBase(unittest.TestCase):
    def build_controller(self, save_path: Path) -> SteamDemoClientController:
        playable = PlayableSliceApplication(
            master_root=MASTER_ROOT,
            save_file_path=save_path,
        )
        definitions = DemoFlowMasterDataRepository(MASTER_ROOT).load()
        demo = SteamDemoApplication(
            playable,
            DemoFlowService(definitions),
            FLOW_ID,
        )
        return SteamDemoClientController(playable, demo, save_path)


class SteamDemoClientControllerTests(SteamDemoClientTestBase):
    def test_title_exposes_new_continue_settings_and_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.build_controller(Path(directory) / "save.json")

            view = controller.current_view()

            self.assertEqual(SteamDemoClientPhase.TITLE, view.phase)
            self.assertFalse(view.can_continue)
            self.assertEqual(
                [
                    SteamDemoTitleAction.NEW_GAME,
                    SteamDemoTitleAction.CONTINUE,
                    SteamDemoTitleAction.SETTINGS,
                    SteamDemoTitleAction.EXIT,
                ],
                [action.action_id for action in view.title_actions],
            )
            continue_action = next(
                action
                for action in view.title_actions
                if action.action_id == SteamDemoTitleAction.CONTINUE
            )
            self.assertFalse(continue_action.is_enabled)

    def test_new_game_builds_gameplay_composition_and_top_scene(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.build_controller(Path(directory) / "save.json")

            result = controller.activate_title_action(SteamDemoTitleAction.NEW_GAME)

            self.assertIsNone(result.rejection_reason)
            self.assertEqual(SteamDemoClientPhase.GAMEPLAY, result.view.phase)
            self.assertIsNotNone(controller.composition)
            self.assertIsNotNone(result.view.scene)
            self.assertEqual(
                SteamDemoRouteId.TOP_MENU,
                result.view.scene.scene.route_id,
            )
            self.assertIn("new_game_started", result.logs)

    def test_continue_without_save_stays_on_title(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.build_controller(Path(directory) / "missing.json")

            result = controller.activate_title_action(SteamDemoTitleAction.CONTINUE)

            self.assertEqual("save_data_not_found", result.rejection_reason)
            self.assertEqual(SteamDemoClientPhase.TITLE, result.view.phase)
            self.assertIsNone(controller.composition)
            self.assertIn("セーブデータ", result.view.notification)

    def test_settings_are_validated_and_applied_without_game_save_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            save_path = Path(directory) / "save.json"
            controller = self.build_controller(save_path)
            controller.activate_title_action(SteamDemoTitleAction.SETTINGS)

            updated = controller.apply_settings(
                font_scale_percent=125,
                show_logs=False,
                show_input_hints=False,
            )
            invalid = controller.apply_settings(
                font_scale_percent=110,
                show_logs=True,
                show_input_hints=True,
            )
            returned = controller.back_to_title()

            self.assertEqual(
                SteamDemoClientSettings(
                    font_scale_percent=125,
                    show_logs=False,
                    show_input_hints=False,
                ),
                updated.view.settings,
            )
            self.assertEqual("invalid_client_settings", invalid.rejection_reason)
            self.assertEqual(SteamDemoClientPhase.TITLE, returned.view.phase)
            self.assertFalse(save_path.exists())

    def test_scene_entry_and_meaning_input_use_dispatcher(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.build_controller(Path(directory) / "save.json")
            controller.start_new_game()

            opened = controller.activate_scene_entry("quest_board")
            cancelled = controller.handle_input(MenuInputAction.CANCEL)

            self.assertIsNone(opened.rejection_reason)
            self.assertEqual(
                SteamDemoRouteId.QUEST_BOARD,
                opened.view.scene.scene.route_id,
            )
            self.assertEqual(
                SteamDemoRouteId.TOP_MENU,
                cancelled.view.scene.scene.route_id,
            )
            self.assertEqual(SteamDemoClientPhase.GAMEPLAY, cancelled.view.phase)

    def test_gameplay_exit_returns_to_title_without_exiting_window(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.build_controller(Path(directory) / "save.json")
            controller.start_new_game()

            result = controller.activate_scene_entry("exit")

            self.assertEqual(SteamDemoClientPhase.TITLE, result.view.phase)
            self.assertIsNone(controller.composition)
            self.assertIn("タイトル", result.view.notification)

    def test_save_then_continue_restores_gameplay_scene(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            save_path = Path(directory) / "save.json"
            first = self.build_controller(save_path)
            first.start_new_game()

            saved = first.activate_scene_entry("save")
            second = self.build_controller(save_path)
            continued = second.activate_title_action(SteamDemoTitleAction.CONTINUE)

            self.assertIsNone(saved.rejection_reason)
            self.assertTrue(save_path.is_file())
            self.assertIsNone(continued.rejection_reason)
            self.assertEqual(SteamDemoClientPhase.GAMEPLAY, continued.view.phase)
            self.assertEqual(
                SteamDemoRouteId.TOP_MENU,
                continued.view.scene.scene.route_id,
            )

    def test_unknown_title_action_and_scene_action_outside_gameplay_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.build_controller(Path(directory) / "save.json")

            unknown = controller.activate_title_action("unknown")
            scene = controller.activate_scene_entry("quest_board")

            self.assertEqual("unknown_title_action", unknown.rejection_reason)
            self.assertEqual(
                "scene_entry_not_allowed_from_current_phase",
                scene.rejection_reason,
            )
            self.assertEqual(SteamDemoClientPhase.TITLE, scene.view.phase)

    def test_request_exit_discards_composition_and_marks_client_exited(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.build_controller(Path(directory) / "save.json")
            controller.start_new_game()

            result = controller.request_exit()

            self.assertEqual(SteamDemoClientPhase.EXITED, result.view.phase)
            self.assertIsNone(controller.composition)
            self.assertEqual(("client_exit_requested",), result.logs)

    def test_client_view_is_json_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.build_controller(Path(directory) / "save.json")
            controller.start_new_game()

            data = controller.current_view().to_dict()

            self.assertEqual("gameplay", data["phase"])
            self.assertEqual(SteamDemoRouteId.TOP_MENU.value, data["scene"]["scene"]["route_id"])
            self.assertIsInstance(data["logs"], list)


class SteamDemoTkFormattingTests(unittest.TestCase):
    def test_scene_field_and_entry_formatters_do_not_require_tk_window(self) -> None:
        field = SceneField(key="gold", label="所持金", value=300)
        entry = SceneEntry(
            entry_id="item.potion",
            label="ポーション",
            description="HPを回復する。",
            fields=(field,),
        )

        self.assertEqual("所持金: 300", format_scene_field(field))
        self.assertEqual(
            "ポーション\nHPを回復する。\n所持金: 300",
            format_scene_entry(entry),
        )


if __name__ == "__main__":
    unittest.main()
