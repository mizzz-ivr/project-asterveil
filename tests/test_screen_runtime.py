from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from game.app.application.demo_flow_service import DemoFlowService, SteamDemoApplication
from game.app.application.playable_slice import PlayableSliceApplication
from game.app.infrastructure.demo_flow_repository import DemoFlowMasterDataRepository
from game.app.presentation.action_controller import SteamDemoFlowId
from game.app.presentation.input_actions import MenuInputAction
from game.app.presentation.quest_travel_screen import QuestBoardScreenController
from game.app.presentation.screen_controller import SteamDemoScreenController
from game.app.presentation.screen_router import (
    RouteTransitionKind,
    SteamDemoRouteId,
    SteamDemoScreenRouter,
)
from game.app.presentation.screen_runtime import SteamDemoScreenRuntime
from game.app.steam_demo_composition import (
    SteamDemoCompositionRoot,
    SteamDemoRouteScreen,
)


FLOW_ID = "demo.steam.ch01.core_loop"


class ScreenRuntimeTestBase(unittest.TestCase):
    def build_apps(
        self,
        save_path: Path,
    ) -> tuple[PlayableSliceApplication, SteamDemoApplication]:
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
        playable.new_game()
        return playable, demo


class SteamDemoScreenRuntimeTests(ScreenRuntimeTestBase):
    def test_initial_frame_exposes_top_view_and_serializable_route_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            playable, demo = self.build_apps(Path(directory) / "save.json")
            runtime = SteamDemoCompositionRoot.build(playable, demo).runtime

            frame = runtime.current_frame()

            self.assertEqual(SteamDemoRouteId.TOP_MENU, frame.route_id)
            self.assertTrue(frame.is_top_menu)
            self.assertFalse(frame.has_active_screen)
            self.assertIsNone(runtime.active_screen)
            self.assertEqual(
                {
                    "route_state": {
                        "route_stack": [SteamDemoRouteId.TOP_MENU.value],
                        "current_route": SteamDemoRouteId.TOP_MENU.value,
                        "can_go_back": False,
                    },
                    "route_id": SteamDemoRouteId.TOP_MENU.value,
                    "is_top_menu": True,
                    "has_active_screen": False,
                },
                frame.to_dict(),
            )

    def test_top_action_opens_factory_screen_and_complete_discards_controller(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            playable, demo = self.build_apps(Path(directory) / "save.json")
            runtime = SteamDemoCompositionRoot.build(playable, demo).runtime

            opened = runtime.activate_top_action("quest_board")
            active = runtime.active_screen
            completed = runtime.complete_current_route(
                logs=("quest_route_completed",),
            )

            self.assertEqual(RouteTransitionKind.PUSHED, opened.transition.kind)
            self.assertEqual(SteamDemoRouteId.QUEST_BOARD, opened.frame.route_id)
            self.assertFalse(opened.frame.is_top_menu)
            self.assertTrue(opened.frame.has_active_screen)
            self.assertIsNotNone(active)
            self.assertEqual(SteamDemoRouteId.QUEST_BOARD, active.route_id)
            self.assertIsInstance(active.controller, QuestBoardScreenController)
            self.assertEqual(RouteTransitionKind.POPPED, completed.transition.kind)
            self.assertEqual(("quest_route_completed",), completed.logs)
            self.assertEqual(SteamDemoRouteId.TOP_MENU, completed.frame.route_id)
            self.assertIsNone(runtime.active_screen)

    def test_subscreen_meaning_input_stays_and_cancel_returns_to_top(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            playable, demo = self.build_apps(Path(directory) / "save.json")
            runtime = SteamDemoCompositionRoot.build(playable, demo).runtime
            runtime.activate_top_action("quest_board")
            active_before = runtime.active_screen

            moved = runtime.handle_input(MenuInputAction.MOVE_DOWN)
            active_after_move = runtime.active_screen
            cancelled = runtime.handle_input(MenuInputAction.CANCEL)

            self.assertEqual(RouteTransitionKind.STAY, moved.transition.kind)
            self.assertEqual(SteamDemoRouteId.QUEST_BOARD, moved.frame.route_id)
            self.assertIs(active_before, active_after_move)
            self.assertEqual(RouteTransitionKind.POPPED, cancelled.transition.kind)
            self.assertEqual(SteamDemoRouteId.TOP_MENU, cancelled.frame.route_id)
            self.assertIsNone(runtime.active_screen)
            self.assertEqual(
                (f"route_cancelled:{SteamDemoRouteId.QUEST_BOARD.value}",),
                cancelled.logs,
            )

    def test_exit_and_immediate_actions_do_not_create_subscreen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            playable, demo = self.build_apps(Path(directory) / "save.json")
            runtime = SteamDemoCompositionRoot.build(playable, demo).runtime

            status = runtime.activate_top_action("status")
            exited = runtime.activate_top_action("exit")

            self.assertEqual(RouteTransitionKind.STAY, status.transition.kind)
            self.assertFalse(status.exit_requested)
            self.assertEqual(RouteTransitionKind.EXIT_REQUESTED, exited.transition.kind)
            self.assertTrue(exited.exit_requested)
            self.assertEqual(SteamDemoRouteId.TOP_MENU, exited.frame.route_id)
            self.assertIsNone(runtime.active_screen)

    def test_explicit_cancel_and_reset_discard_active_controller(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            playable, demo = self.build_apps(Path(directory) / "save.json")
            runtime = SteamDemoCompositionRoot.build(playable, demo).runtime

            runtime.activate_top_action("quest_board")
            cancelled = runtime.cancel_current_route(logs=("cancelled_by_host",))
            reopened = runtime.activate_top_action("quest_board")
            reset = runtime.reset_to_top(logs=("session_reset",))

            self.assertEqual(RouteTransitionKind.POPPED, cancelled.transition.kind)
            self.assertEqual(("cancelled_by_host",), cancelled.logs)
            self.assertEqual(RouteTransitionKind.PUSHED, reopened.transition.kind)
            self.assertEqual(RouteTransitionKind.RESET, reset.transition.kind)
            self.assertEqual(("session_reset",), reset.logs)
            self.assertEqual(SteamDemoRouteId.TOP_MENU, reset.frame.route_id)
            self.assertIsNone(runtime.active_screen)

    def test_factory_failure_rolls_route_back_atomically(self) -> None:
        class FailingFactory:
            def create(self, route_id: SteamDemoRouteId) -> SteamDemoRouteScreen:
                raise ValueError(f"failed:{route_id.value}")

        with tempfile.TemporaryDirectory() as directory:
            playable, demo = self.build_apps(Path(directory) / "save.json")
            router = SteamDemoScreenRouter(SteamDemoScreenController(playable, demo))
            runtime = SteamDemoScreenRuntime(router, FailingFactory())

            result = runtime.activate_top_action("quest_board")

            self.assertEqual(RouteTransitionKind.REJECTED, result.transition.kind)
            self.assertEqual("screen_creation_failed", result.rejection_reason)
            self.assertEqual(SteamDemoRouteId.TOP_MENU, result.frame.route_id)
            self.assertIsNone(runtime.active_screen)
            self.assertEqual((SteamDemoRouteId.TOP_MENU,), router.state.route_stack)
            self.assertTrue(result.logs[0].startswith("screen_open_rejected:"))

    def test_factory_route_mismatch_rolls_route_back(self) -> None:
        @dataclass(frozen=True)
        class MismatchedScreen:
            route_id: SteamDemoRouteId
            controller: QuestBoardScreenController

        class MismatchedFactory:
            def __init__(self, controller: QuestBoardScreenController) -> None:
                self._controller = controller

            def create(self, route_id: SteamDemoRouteId) -> MismatchedScreen:
                return MismatchedScreen(
                    route_id=SteamDemoRouteId.TRAVEL,
                    controller=self._controller,
                )

        with tempfile.TemporaryDirectory() as directory:
            playable, demo = self.build_apps(Path(directory) / "save.json")
            router = SteamDemoScreenRouter(SteamDemoScreenController(playable, demo))
            runtime = SteamDemoScreenRuntime(
                router,
                MismatchedFactory(QuestBoardScreenController(playable)),
            )

            result = runtime.activate_top_action("quest_board")

            self.assertEqual(RouteTransitionKind.REJECTED, result.transition.kind)
            self.assertEqual("screen_creation_failed", result.rejection_reason)
            self.assertEqual(SteamDemoRouteId.TOP_MENU, result.frame.route_id)
            self.assertIsNone(runtime.active_screen)

    def test_external_router_mutation_is_detected_as_runtime_inconsistency(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            playable, demo = self.build_apps(Path(directory) / "save.json")
            composition = SteamDemoCompositionRoot.build(playable, demo)

            composition.router.open_flow(SteamDemoFlowId.QUEST_BOARD)

            with self.assertRaisesRegex(
                RuntimeError,
                "active_screen_missing_for_route",
            ):
                composition.runtime.current_frame()

    def test_complete_and_cancel_without_subscreen_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            playable, demo = self.build_apps(Path(directory) / "save.json")
            runtime = SteamDemoCompositionRoot.build(playable, demo).runtime

            completed = runtime.complete_current_route()
            cancelled = runtime.cancel_current_route()

            self.assertEqual(RouteTransitionKind.REJECTED, completed.transition.kind)
            self.assertEqual("subscreen_not_active", completed.rejection_reason)
            self.assertEqual(RouteTransitionKind.REJECTED, cancelled.transition.kind)
            self.assertEqual("subscreen_not_active", cancelled.rejection_reason)
            self.assertEqual(SteamDemoRouteId.TOP_MENU, cancelled.frame.route_id)


if __name__ == "__main__":
    unittest.main()
