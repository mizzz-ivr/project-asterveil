from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from game.app.application.demo_flow_service import DemoFlowService, SteamDemoApplication
from game.app.application.playable_slice import PlayableSliceApplication
from game.app.cli import run_steam_demo
from game.app.cli.screen_console_renderer import SteamDemoConsoleRenderer
from game.app.infrastructure.demo_flow_repository import DemoFlowMasterDataRepository
from game.app.presentation.screen_renderer import (
    SteamDemoSceneBuilderRegistry,
    SteamDemoSceneModel,
)
from game.app.presentation.screen_router import SteamDemoRouteId
from game.app.steam_demo_composition import SteamDemoCompositionRoot


FLOW_ID = "demo.steam.ch01.core_loop"


class ScreenRendererTestBase(unittest.TestCase):
    def build_composition(self, save_path: Path):
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
        return playable, SteamDemoCompositionRoot.build(playable, demo)


class SteamDemoSceneBuilderRegistryTests(ScreenRendererTestBase):
    def test_builds_top_frame_with_selection_hints_and_json_compatible_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, composition = self.build_composition(Path(directory) / "save.json")

            scene = composition.scene_registry.build_frame(
                composition.runtime.current_frame()
            )
            payload = scene.to_dict()

            self.assertEqual(SteamDemoRouteId.TOP_MENU, scene.route_id)
            self.assertTrue(scene.title)
            self.assertEqual("actions", scene.sections[0].section_id)
            self.assertTrue(any(entry.is_selected for entry in scene.sections[0].entries))
            self.assertTrue(scene.action_hints)
            self.assertEqual(SteamDemoRouteId.TOP_MENU.value, payload["route_id"])
            json.dumps(payload, ensure_ascii=False)

    def test_builds_scene_for_every_registered_subroute(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, composition = self.build_composition(Path(directory) / "save.json")
            built_routes: set[SteamDemoRouteId] = set()

            for route_id in composition.screen_factory.registered_routes():
                route_screen = composition.screen_factory.create(route_id)
                scene = composition.scene_registry.build(
                    route_id,
                    route_screen.controller.current_view(),
                )
                built_routes.add(scene.route_id)
                self.assertEqual(route_id, scene.route_id)
                self.assertTrue(scene.title)
                self.assertTrue(scene.sections)
                json.dumps(scene.to_dict(), ensure_ascii=False)

            self.assertEqual(
                set(composition.screen_factory.registered_routes()),
                built_routes,
            )

    def test_rejects_view_type_mismatch_and_invalid_registry(self) -> None:
        registry = SteamDemoSceneBuilderRegistry()

        with self.assertRaisesRegex(TypeError, "scene_view_type_mismatch"):
            registry.build(SteamDemoRouteId.QUEST_BOARD, object())
        with self.assertRaisesRegex(ValueError, "invalid_scene_builder_registry"):
            SteamDemoSceneBuilderRegistry(builders={})

    def test_rejects_builder_that_returns_different_route(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, composition = self.build_composition(Path(directory) / "save.json")
            base_registry = SteamDemoSceneBuilderRegistry()
            builders = {
                route_id: (
                    lambda view, current_route=route_id: base_registry.build(
                        current_route,
                        view,
                    )
                )
                for route_id in base_registry.registered_routes()
            }
            builders[SteamDemoRouteId.TOP_MENU] = lambda _: SteamDemoSceneModel(
                route_id=SteamDemoRouteId.QUEST_BOARD,
                title="Wrong Route",
            )
            registry = SteamDemoSceneBuilderRegistry(builders=builders)

            with self.assertRaisesRegex(ValueError, "scene_builder_route_mismatch"):
                registry.build_frame(composition.runtime.current_frame())

    def test_composition_root_builds_independent_scene_registries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            playable, first = self.build_composition(Path(directory) / "save.json")
            definitions = DemoFlowMasterDataRepository(Path("data/master")).load()
            second_demo = SteamDemoApplication(
                playable,
                DemoFlowService(definitions),
                FLOW_ID,
            )
            second = SteamDemoCompositionRoot.build(playable, second_demo)

            self.assertIsNot(first.scene_registry, second.scene_registry)
            self.assertEqual(
                set(first.scene_registry.registered_routes()),
                set(second.scene_registry.registered_routes()),
            )


class SteamDemoConsoleRendererTests(ScreenRendererTestBase):
    def test_console_renderer_outputs_scene_without_reading_view_model_types(self) -> None:
        emitted: list[str] = []
        renderer = SteamDemoConsoleRenderer(emit=emitted.append)
        scene = SteamDemoSceneModel(
            route_id=SteamDemoRouteId.TOP_MENU,
            title="Test Scene",
        )

        renderer.render_scene(scene)

        self.assertEqual(
            ["- screen:steam_demo.top_menu:Test Scene:completed=False"],
            emitted,
        )

    def test_console_renderer_renders_runtime_frame(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, composition = self.build_composition(Path(directory) / "save.json")
            emitted: list[str] = []
            renderer = SteamDemoConsoleRenderer(
                composition.scene_registry,
                emit=emitted.append,
            )

            scene = renderer.render_frame(composition.runtime.current_frame())

            self.assertEqual(SteamDemoRouteId.TOP_MENU, scene.route_id)
            self.assertTrue(any(line.startswith("- screen:") for line in emitted))
            self.assertTrue(any("screen_section:" in line for line in emitted))
            self.assertTrue(any("screen_hint:" in line for line in emitted))

    def test_steam_demo_cli_print_helper_uses_common_renderer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, composition = self.build_composition(Path(directory) / "save.json")
            quest_screen = composition.screen_factory.create(
                SteamDemoRouteId.QUEST_BOARD
            )
            view = quest_screen.controller.current_view()
            buffer = io.StringIO()

            with redirect_stdout(buffer):
                run_steam_demo._print_quest_board_view(view)

            output = buffer.getvalue()
            self.assertIn("screen:steam_demo.quest_board", output)
            self.assertIn("screen_section:steam_demo.quest_board:quests", output)


if __name__ == "__main__":
    unittest.main()
