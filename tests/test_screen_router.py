from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from game.app.application.demo_flow_service import DemoFlowService, SteamDemoApplication
from game.app.application.playable_slice import PlayableSliceApplication
from game.app.infrastructure.demo_flow_repository import DemoFlowMasterDataRepository
from game.app.presentation.action_controller import ActionDispatchKind, SteamDemoFlowId
from game.app.presentation.input_actions import MenuInputAction
from game.app.presentation.screen_controller import SteamDemoScreenController
from game.app.presentation.screen_router import (
    DEFAULT_ROUTE_BY_FLOW,
    RouteTransitionKind,
    SteamDemoRouteId,
    SteamDemoScreenRouter,
)


FLOW_ID = "demo.steam.ch01.core_loop"


class SteamDemoScreenRouterTests(unittest.TestCase):
    def build_router(
        self,
        save_path: Path,
        *,
        route_by_flow=None,
    ) -> tuple[PlayableSliceApplication, SteamDemoScreenRouter]:
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
        top_screen = SteamDemoScreenController(playable, demo)
        return playable, SteamDemoScreenRouter(
            top_screen,
            route_by_flow=route_by_flow,
        )

    def test_initial_state_is_serializable_and_all_flows_are_registered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, router = self.build_router(Path(directory) / "save.json")

            state = router.state
            serialized = json.dumps(state.to_dict(), ensure_ascii=False)

            self.assertEqual((SteamDemoRouteId.TOP_MENU,), state.route_stack)
            self.assertEqual(SteamDemoRouteId.TOP_MENU, state.current_route)
            self.assertFalse(state.can_go_back)
            self.assertIn(SteamDemoRouteId.QUEST_BOARD.value, serialized)
            self.assertEqual(len(SteamDemoFlowId), len(router.registered_routes()))

    def test_top_action_pushes_route_and_completion_returns_to_top(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, router = self.build_router(Path(directory) / "save.json")

            opened = router.activate_top_action("quest_board")
            completed = router.complete_current_route(("quest_board_completed",))

            self.assertEqual(RouteTransitionKind.PUSHED, opened.kind)
            self.assertEqual(SteamDemoRouteId.TOP_MENU, opened.from_route)
            self.assertEqual(SteamDemoRouteId.QUEST_BOARD, opened.to_route)
            self.assertEqual(
                (SteamDemoRouteId.TOP_MENU, SteamDemoRouteId.QUEST_BOARD),
                opened.state.route_stack,
            )
            self.assertEqual(ActionDispatchKind.FLOW_REQUIRED, opened.dispatch_result.kind)
            self.assertEqual(RouteTransitionKind.POPPED, completed.kind)
            self.assertEqual(SteamDemoRouteId.TOP_MENU, completed.state.current_route)
            self.assertEqual(("quest_board_completed",), completed.logs)

    def test_cancel_and_back_do_not_corrupt_root_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, router = self.build_router(Path(directory) / "save.json")

            root_back = router.request_back()
            root_cancel = router.cancel_current_route()
            root_complete = router.complete_current_route()
            opened = router.open_flow(SteamDemoFlowId.TRAVEL)
            cancelled = router.cancel_current_route()

            self.assertEqual(RouteTransitionKind.REJECTED, root_back.kind)
            self.assertEqual("cannot_pop_root", root_back.reason_code)
            self.assertEqual("cannot_cancel_root", root_cancel.reason_code)
            self.assertEqual("cannot_complete_root", root_complete.reason_code)
            self.assertEqual(RouteTransitionKind.PUSHED, opened.kind)
            self.assertEqual(RouteTransitionKind.POPPED, cancelled.kind)
            self.assertEqual(SteamDemoRouteId.TOP_MENU, cancelled.state.current_route)
            self.assertEqual(
                (f"route_cancelled:{SteamDemoRouteId.TRAVEL.value}",),
                cancelled.logs,
            )

    def test_immediate_action_and_exit_do_not_change_route_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, router = self.build_router(Path(directory) / "save.json")

            status = router.activate_top_action("status")
            exit_requested = router.activate_top_action("exit")

            self.assertEqual(RouteTransitionKind.STAY, status.kind)
            self.assertEqual(ActionDispatchKind.EXECUTED, status.dispatch_result.kind)
            self.assertEqual((SteamDemoRouteId.TOP_MENU,), status.state.route_stack)
            self.assertEqual(RouteTransitionKind.EXIT_REQUESTED, exit_requested.kind)
            self.assertEqual(("exit_selected",), exit_requested.logs)
            self.assertEqual((SteamDemoRouteId.TOP_MENU,), exit_requested.state.route_stack)

    def test_missing_route_and_top_action_from_subroute_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            route_by_flow = dict(DEFAULT_ROUTE_BY_FLOW)
            route_by_flow.pop(SteamDemoFlowId.QUEST_BOARD)
            _, router = self.build_router(
                Path(directory) / "save.json",
                route_by_flow=route_by_flow,
            )

            missing = router.activate_top_action("quest_board")
            opened = router.open_flow(SteamDemoFlowId.TRAVEL)
            nested_action = router.activate_top_action("status")
            nested_input = router.handle_top_input(MenuInputAction.CONFIRM)

            self.assertEqual(RouteTransitionKind.REJECTED, missing.kind)
            self.assertEqual("route_not_registered", missing.reason_code)
            self.assertEqual(RouteTransitionKind.PUSHED, opened.kind)
            self.assertEqual("top_action_not_allowed_from_subroute", nested_action.reason_code)
            self.assertEqual("top_input_not_allowed_from_subroute", nested_input.reason_code)
            self.assertEqual(SteamDemoRouteId.TRAVEL, router.state.current_route)

    def test_top_cancel_is_explicit_root_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, router = self.build_router(Path(directory) / "save.json")

            cancelled = router.handle_top_input(MenuInputAction.CANCEL)

            self.assertEqual(RouteTransitionKind.REJECTED, cancelled.kind)
            self.assertEqual("cannot_pop_root", cancelled.reason_code)
            self.assertEqual(SteamDemoRouteId.TOP_MENU, cancelled.state.current_route)

    def test_reset_discards_subroute_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, router = self.build_router(Path(directory) / "save.json")
            router.open_flow(SteamDemoFlowId.NPC_DIALOGUE)

            reset = router.reset_to_top(("session_restarted",))

            self.assertEqual(RouteTransitionKind.RESET, reset.kind)
            self.assertEqual(SteamDemoRouteId.NPC_DIALOGUE, reset.from_route)
            self.assertEqual(SteamDemoRouteId.TOP_MENU, reset.to_route)
            self.assertEqual((SteamDemoRouteId.TOP_MENU,), reset.state.route_stack)
            self.assertEqual(("session_restarted",), reset.logs)


if __name__ == "__main__":
    unittest.main()
