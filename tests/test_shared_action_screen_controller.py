from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from game.app.application.demo_flow_service import DemoFlowService, SteamDemoApplication
from game.app.application.playable_slice import PlayableSliceApplication
from game.app.cli import run_steam_demo
from game.app.infrastructure.demo_flow_repository import DemoFlowMasterDataRepository
from game.app.presentation.action_controller import (
    ActionDispatchKind,
    SteamDemoActionController,
    SteamDemoFlowId,
)
from game.app.presentation.input_actions import MenuInputAction
from game.app.presentation.quest_travel_screen import QuestBoardScreenController
from game.app.presentation.screen_controller import SteamDemoScreenController
from game.app.presentation.screen_router import SteamDemoRouteId, SteamDemoScreenRouter
from game.app.steam_demo_composition import (
    SteamDemoCompositionRoot,
    SteamDemoRouteScreen,
    SteamDemoScreenFactory,
)


FLOW_ID = "demo.steam.ch01.core_loop"


class SteamDemoControllerTestBase(unittest.TestCase):
    def build_apps(
        self,
        save_path: Path,
        *,
        start_game: bool = True,
    ) -> tuple[
        PlayableSliceApplication,
        SteamDemoApplication,
        SteamDemoActionController,
    ]:
        playable = PlayableSliceApplication(
            master_root=Path("data/master"),
            save_file_path=save_path,
        )
        definitions = DemoFlowMasterDataRepository(Path("data/master")).load()
        demo = SteamDemoApplication(
            playable,
            DemoFlowService(definitions),
            FLOW_ID,
        )
        if start_game:
            playable.new_game()
        return playable, demo, SteamDemoActionController(playable, demo)


class SteamDemoActionControllerTests(SteamDemoControllerTestBase):
    def test_executes_immediate_demo_and_playable_actions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, _, controller = self.build_apps(Path(directory) / "save.json")

            guide = controller.dispatch("demo_guide")
            status = controller.dispatch("status")

            self.assertEqual(ActionDispatchKind.EXECUTED, guide.kind)
            self.assertTrue(any(line.startswith("demo_flow:") for line in guide.logs))
            self.assertEqual(ActionDispatchKind.EXECUTED, status.kind)
            self.assertEqual("status", status.action_id)
            self.assertTrue(status.logs)

    def test_returns_flow_request_without_running_cli_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, _, controller = self.build_apps(Path(directory) / "save.json")

            result = controller.dispatch("quest_board")

            self.assertEqual(ActionDispatchKind.FLOW_REQUIRED, result.kind)
            self.assertEqual(SteamDemoFlowId.QUEST_BOARD, result.flow_id)
            self.assertEqual(tuple(), result.logs)

    def test_exit_and_unknown_action_are_explicit_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, _, controller = self.build_apps(Path(directory) / "save.json")

            exit_result = controller.dispatch("exit")
            unknown = controller.dispatch("not-supported")
            empty = controller.dispatch("   ")

            self.assertEqual(ActionDispatchKind.EXIT_REQUESTED, exit_result.kind)
            self.assertEqual(("exit_selected",), exit_result.logs)
            self.assertEqual(ActionDispatchKind.REJECTED, unknown.kind)
            self.assertEqual("action_not_available", unknown.reason_code)
            self.assertEqual(ActionDispatchKind.REJECTED, empty.kind)
            self.assertEqual("empty_action_id", empty.reason_code)

    def test_game_not_started_is_rejected_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, _, controller = self.build_apps(
                Path(directory) / "save.json",
                start_game=False,
            )

            status = controller.dispatch("status")
            guide = controller.dispatch("demo_guide")

            self.assertEqual(ActionDispatchKind.REJECTED, status.kind)
            self.assertEqual("action_not_available", status.reason_code)
            self.assertEqual(ActionDispatchKind.REJECTED, guide.kind)
            self.assertEqual("application_rejected", guide.reason_code)


class SteamDemoScreenControllerTests(SteamDemoControllerTestBase):
    def build_screen(
        self,
        save_path: Path,
    ) -> SteamDemoScreenController:
        playable, demo, controller = self.build_apps(save_path)
        return SteamDemoScreenController(
            playable,
            demo,
            action_controller=controller,
        )

    def test_meaning_input_moves_selection_and_confirms_action(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            screen = self.build_screen(Path(directory) / "save.json")

            initial = screen.current_view()
            moved = screen.handle_input(MenuInputAction.MOVE_DOWN)
            confirmed = screen.handle_input(MenuInputAction.CONFIRM)

            self.assertEqual("demo_guide", initial.items[0].action_id)
            self.assertEqual(1, moved.view.selection.selected_index)
            self.assertIsNotNone(confirmed.dispatch_result)
            self.assertEqual("status", confirmed.dispatch_result.action_id)
            self.assertEqual(ActionDispatchKind.EXECUTED, confirmed.dispatch_result.kind)
            self.assertEqual(1, confirmed.view.selection.selected_index)

    def test_guide_and_cancel_are_separate_screen_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            screen = self.build_screen(Path(directory) / "save.json")

            guide = screen.handle_input(MenuInputAction.SHOW_GUIDE)
            cancelled = screen.handle_input(MenuInputAction.CANCEL)

            self.assertIsNotNone(guide.dispatch_result)
            self.assertEqual("demo_guide", guide.dispatch_result.action_id)
            self.assertEqual(ActionDispatchKind.EXECUTED, guide.dispatch_result.kind)
            self.assertFalse(guide.cancel_requested)
            self.assertTrue(cancelled.cancel_requested)
            self.assertIsNone(cancelled.dispatch_result)

    def test_pointer_style_activation_returns_flow_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            screen = self.build_screen(Path(directory) / "save.json")

            quest_board = screen.activate_action("quest_board")
            unknown = screen.activate_action("not-in-menu")

            self.assertIsNotNone(quest_board.dispatch_result)
            self.assertEqual(ActionDispatchKind.FLOW_REQUIRED, quest_board.dispatch_result.kind)
            self.assertEqual(SteamDemoFlowId.QUEST_BOARD, quest_board.dispatch_result.flow_id)
            self.assertEqual(ActionDispatchKind.REJECTED, unknown.dispatch_result.kind)
            self.assertEqual("menu_item_not_available", unknown.dispatch_result.reason_code)


class SteamDemoCliActionAdapterTests(SteamDemoControllerTestBase):
    def build_composition(
        self,
        save_path: Path,
    ) -> tuple[PlayableSliceApplication, SteamDemoScreenRouter, SteamDemoScreenFactory]:
        playable, demo, _ = self.build_apps(save_path)
        composition = SteamDemoCompositionRoot.build(playable, demo)
        return playable, composition.router, composition.screen_factory

    def test_cli_adapter_runs_factory_screen_and_returns_to_top(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, router, screen_factory = self.build_composition(Path(directory) / "save.json")
            original = run_steam_demo._CLI_ROUTE_HANDLERS[SteamDemoRouteId.QUEST_BOARD]
            captured: list[SteamDemoRouteScreen] = []

            def route_handler(route_screen: SteamDemoRouteScreen) -> list[str]:
                captured.append(route_screen)
                return ["cli_route_called:quest_board"]

            run_steam_demo._CLI_ROUTE_HANDLERS[SteamDemoRouteId.QUEST_BOARD] = route_handler
            try:
                logs = run_steam_demo._dispatch_action(
                    router,
                    screen_factory,
                    "quest_board",
                )
            finally:
                run_steam_demo._CLI_ROUTE_HANDLERS[SteamDemoRouteId.QUEST_BOARD] = original

            self.assertEqual(["cli_route_called:quest_board"], logs)
            self.assertEqual(1, len(captured))
            self.assertEqual(SteamDemoRouteId.QUEST_BOARD, captured[0].route_id)
            self.assertIsInstance(captured[0].controller, QuestBoardScreenController)
            self.assertEqual(SteamDemoRouteId.TOP_MENU, router.state.current_route)
            self.assertEqual((SteamDemoRouteId.TOP_MENU,), router.state.route_stack)

    def test_cli_adapter_recovers_when_route_handler_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, router, screen_factory = self.build_composition(Path(directory) / "save.json")
            original = run_steam_demo._CLI_ROUTE_HANDLERS.pop(
                SteamDemoRouteId.QUEST_BOARD
            )
            try:
                logs = run_steam_demo._dispatch_action(
                    router,
                    screen_factory,
                    "quest_board",
                )
            finally:
                run_steam_demo._CLI_ROUTE_HANDLERS[SteamDemoRouteId.QUEST_BOARD] = original

            self.assertEqual(
                [f"route_not_supported:{SteamDemoRouteId.QUEST_BOARD.value}"],
                logs,
            )
            self.assertEqual(SteamDemoRouteId.TOP_MENU, router.state.current_route)

    def test_cli_adapter_recovers_from_expected_controller_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, router, screen_factory = self.build_composition(Path(directory) / "save.json")
            original = run_steam_demo._CLI_ROUTE_HANDLERS[SteamDemoRouteId.QUEST_BOARD]

            def rejected_handler(_: SteamDemoRouteScreen) -> list[str]:
                raise ValueError("expected rejection")

            run_steam_demo._CLI_ROUTE_HANDLERS[SteamDemoRouteId.QUEST_BOARD] = rejected_handler
            try:
                logs = run_steam_demo._dispatch_action(
                    router,
                    screen_factory,
                    "quest_board",
                )
            finally:
                run_steam_demo._CLI_ROUTE_HANDLERS[SteamDemoRouteId.QUEST_BOARD] = original

            self.assertEqual(
                [
                    f"route_handler_rejected:{SteamDemoRouteId.QUEST_BOARD.value}:"
                    "expected rejection"
                ],
                logs,
            )
            self.assertEqual(SteamDemoRouteId.TOP_MENU, router.state.current_route)


if __name__ == "__main__":
    unittest.main()
