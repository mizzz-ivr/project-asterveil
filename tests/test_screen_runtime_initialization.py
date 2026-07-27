from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from game.app.application.demo_flow_service import DemoFlowService, SteamDemoApplication
from game.app.application.playable_slice import PlayableSliceApplication
from game.app.infrastructure.demo_flow_repository import DemoFlowMasterDataRepository
from game.app.presentation.input_actions import MenuInputAction
from game.app.presentation.screen_controller import SteamDemoScreenController
from game.app.presentation.screen_router import (
    RouteTransitionKind,
    SteamDemoRouteId,
    SteamDemoScreenRouter,
)
from game.app.presentation.screen_runtime import SteamDemoScreenRuntime


FLOW_ID = "demo.steam.ch01.core_loop"


class BrokenController:
    def current_view(self) -> object:
        raise ValueError("initial_view_failed")

    def handle_input(self, action: MenuInputAction) -> object:
        raise AssertionError(f"unexpected input: {action.value}")


@dataclass(frozen=True)
class BrokenRouteScreen:
    route_id: SteamDemoRouteId
    controller: BrokenController


class BrokenFactory:
    def create(self, route_id: SteamDemoRouteId) -> BrokenRouteScreen:
        return BrokenRouteScreen(route_id=route_id, controller=BrokenController())


class SteamDemoScreenRuntimeInitializationTests(unittest.TestCase):
    def test_initial_view_failure_rolls_route_back_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            playable = PlayableSliceApplication(
                master_root=Path("data/master"),
                save_file_path=Path(directory) / "save.json",
            )
            definitions = DemoFlowMasterDataRepository(Path("data/master")).load()
            demo = SteamDemoApplication(
                playable,
                DemoFlowService(definitions),
                FLOW_ID,
            )
            playable.new_game()
            router = SteamDemoScreenRouter(SteamDemoScreenController(playable, demo))
            runtime = SteamDemoScreenRuntime(router, BrokenFactory())

            result = runtime.activate_top_action("quest_board")

            self.assertEqual(RouteTransitionKind.REJECTED, result.transition.kind)
            self.assertEqual("screen_creation_failed", result.rejection_reason)
            self.assertEqual(SteamDemoRouteId.TOP_MENU, result.frame.route_id)
            self.assertEqual((SteamDemoRouteId.TOP_MENU,), router.state.route_stack)
            self.assertIsNone(runtime.active_screen)
            self.assertIn("initial_view_failed", result.logs[0])


if __name__ == "__main__":
    unittest.main()
