from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from game.app.application.demo_flow_service import DemoFlowService, SteamDemoApplication
from game.app.application.playable_slice import PlayableSliceApplication
from game.app.infrastructure.demo_flow_repository import DemoFlowMasterDataRepository
from game.app.presentation.input_actions import MenuInputAction
from game.app.presentation.screen_action_dispatcher import (
    SteamDemoInteractiveScene,
    SteamDemoSceneActionDispatcher,
    SteamDemoUiCommand,
    SteamDemoUiCommandKind,
)
from game.app.presentation.screen_renderer import (
    SceneEntry,
    SceneSection,
    SteamDemoSceneModel,
)
from game.app.presentation.screen_router import (
    RouteTransitionKind,
    SteamDemoRouteId,
)
from game.app.steam_demo_composition import SteamDemoCompositionRoot


FLOW_ID = "demo.steam.ch01.core_loop"


class ScreenActionDispatcherTestBase(unittest.TestCase):
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


class SteamDemoUiCommandTests(unittest.TestCase):
    def test_command_requires_fields_matching_kind_and_serializes(self) -> None:
        command = SteamDemoUiCommand.activate_entry(
            SteamDemoRouteId.QUEST_BOARD,
            "quest.test",
        )

        self.assertEqual(SteamDemoUiCommandKind.ACTIVATE_ENTRY, command.kind)
        self.assertEqual(
            {
                "kind": "activate_entry",
                "expected_route_id": SteamDemoRouteId.QUEST_BOARD.value,
                "entry_id": "quest.test",
                "input_action": None,
            },
            command.to_dict(),
        )
        json.dumps(command.to_dict())
        with self.assertRaisesRegex(ValueError, "requires_entry_id"):
            SteamDemoUiCommand(
                kind=SteamDemoUiCommandKind.ACTIVATE_ENTRY,
                expected_route_id=SteamDemoRouteId.TOP_MENU,
            )
        with self.assertRaisesRegex(ValueError, "requires_input_action"):
            SteamDemoUiCommand(
                kind=SteamDemoUiCommandKind.INPUT_ACTION,
                expected_route_id=SteamDemoRouteId.TOP_MENU,
            )


class SteamDemoSceneActionDispatcherTests(ScreenActionDispatcherTestBase):
    def test_top_scene_exposes_commands_and_opens_subroute(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, composition = self.build_composition(Path(directory) / "save.json")
            dispatcher = composition.action_dispatcher

            interactive = dispatcher.current_scene()
            descriptor = interactive.command_for_entry("quest_board")
            opened = dispatcher.activate_entry(
                SteamDemoRouteId.TOP_MENU,
                "quest_board",
            )

            self.assertIsInstance(interactive, SteamDemoInteractiveScene)
            self.assertIsNotNone(descriptor)
            self.assertTrue(descriptor.is_enabled)
            self.assertEqual(RouteTransitionKind.PUSHED, opened.transition.kind)
            self.assertEqual(SteamDemoRouteId.QUEST_BOARD, opened.frame.route_id)
            json.dumps(interactive.to_dict(), ensure_ascii=False)

    def test_stale_route_command_is_rejected_without_changing_route(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, composition = self.build_composition(Path(directory) / "save.json")
            dispatcher = composition.action_dispatcher
            dispatcher.activate_entry(SteamDemoRouteId.TOP_MENU, "quest_board")

            rejected = dispatcher.activate_entry(
                SteamDemoRouteId.TOP_MENU,
                "demo_guide",
            )

            self.assertEqual(RouteTransitionKind.REJECTED, rejected.transition.kind)
            self.assertEqual("stale_scene_route", rejected.rejection_reason)
            self.assertEqual(SteamDemoRouteId.QUEST_BOARD, rejected.frame.route_id)
            self.assertIsNotNone(composition.runtime.active_screen)

    def test_unknown_and_disabled_scene_entries_are_rejected_before_controller(self) -> None:
        @dataclass
        class FixedRegistry:
            def build_frame(self, frame):
                return SteamDemoSceneModel(
                    route_id=frame.route_id,
                    title="Fixed",
                    sections=(
                        SceneSection(
                            "actions",
                            "Actions",
                            (
                                SceneEntry(
                                    entry_id="disabled",
                                    label="Disabled",
                                    is_enabled=False,
                                ),
                            ),
                        ),
                    ),
                )

        with tempfile.TemporaryDirectory() as directory:
            _, composition = self.build_composition(Path(directory) / "save.json")
            dispatcher = SteamDemoSceneActionDispatcher(
                composition.runtime,
                FixedRegistry(),
            )

            unknown = dispatcher.activate_entry(
                SteamDemoRouteId.TOP_MENU,
                "unknown",
            )
            disabled = dispatcher.activate_entry(
                SteamDemoRouteId.TOP_MENU,
                "disabled",
            )

            self.assertEqual("entry_not_actionable", unknown.rejection_reason)
            self.assertEqual("entry_disabled", disabled.rejection_reason)
            self.assertEqual(SteamDemoRouteId.TOP_MENU, disabled.frame.route_id)

    def test_semantic_input_uses_runtime_and_cancel_discards_controller(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, composition = self.build_composition(Path(directory) / "save.json")
            dispatcher = composition.action_dispatcher
            dispatcher.activate_entry(SteamDemoRouteId.TOP_MENU, "quest_board")

            moved = dispatcher.handle_input(
                SteamDemoRouteId.QUEST_BOARD,
                MenuInputAction.MOVE_DOWN,
            )
            cancelled = dispatcher.handle_input(
                SteamDemoRouteId.QUEST_BOARD,
                MenuInputAction.CANCEL,
            )

            self.assertEqual(RouteTransitionKind.STAY, moved.transition.kind)
            self.assertEqual(RouteTransitionKind.POPPED, cancelled.transition.kind)
            self.assertEqual(SteamDemoRouteId.TOP_MENU, cancelled.frame.route_id)
            self.assertIsNone(composition.runtime.active_screen)

    def test_item_and_equipment_multistep_routes_use_current_screen_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, composition = self.build_composition(Path(directory) / "save.json")
            dispatcher = composition.action_dispatcher

            item_opened = dispatcher.activate_entry(
                SteamDemoRouteId.TOP_MENU,
                "use_item",
            )
            self.assertEqual(RouteTransitionKind.PUSHED, item_opened.transition.kind)
            item_scene = dispatcher.current_scene()
            item_command = next(
                descriptor
                for descriptor in item_scene.commands
                if descriptor.is_enabled
            )
            target_result = dispatcher.dispatch(item_command.command)
            target_scene = dispatcher.current_scene()
            self.assertEqual(RouteTransitionKind.STAY, target_result.transition.kind)
            self.assertTrue(target_scene.commands)
            self.assertEqual("targets", target_scene.commands[0].section_id)
            composition.runtime.cancel_current_route()

            equipment_opened = dispatcher.activate_entry(
                SteamDemoRouteId.TOP_MENU,
                "equip",
            )
            self.assertEqual(RouteTransitionKind.PUSHED, equipment_opened.transition.kind)
            member = next(
                descriptor
                for descriptor in dispatcher.current_scene().commands
                if descriptor.is_enabled
            )
            dispatcher.dispatch(member.command)
            slot_scene = dispatcher.current_scene()
            self.assertEqual("slots", slot_scene.commands[0].section_id)
            dispatcher.dispatch(slot_scene.commands[0].command)
            option_scene = dispatcher.current_scene()
            self.assertEqual("equipment", option_scene.commands[0].section_id)

    def test_inn_exposes_explicit_stay_command_instead_of_party_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, composition = self.build_composition(Path(directory) / "save.json")
            dispatcher = composition.action_dispatcher

            opened = dispatcher.activate_entry(SteamDemoRouteId.TOP_MENU, "inn")
            interactive = dispatcher.current_scene()

            self.assertEqual(RouteTransitionKind.PUSHED, opened.transition.kind)
            self.assertEqual(1, len(interactive.commands))
            self.assertEqual("stay", interactive.commands[0].command.entry_id)
            self.assertEqual("actions", interactive.commands[0].section_id)

    def test_npc_dialogue_text_entries_are_not_exposed_as_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, composition = self.build_composition(Path(directory) / "save.json")
            dispatcher = composition.action_dispatcher

            opened = dispatcher.activate_entry(
                SteamDemoRouteId.TOP_MENU,
                "talk_npc",
            )
            self.assertEqual(RouteTransitionKind.PUSHED, opened.transition.kind)
            initial = dispatcher.current_scene()
            if initial.commands:
                dispatcher.dispatch(initial.commands[0].command)
                dialogue = dispatcher.current_scene()
                self.assertFalse(
                    any(
                        descriptor.command.entry_id.startswith("line.")
                        for descriptor in dialogue.commands
                    )
                )

    def test_dispatcher_adapter_registry_matches_screen_factory_routes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, composition = self.build_composition(Path(directory) / "save.json")

            self.assertEqual(
                set(composition.screen_factory.registered_routes()),
                set(composition.action_dispatcher.registered_routes()),
            )


if __name__ == "__main__":
    unittest.main()
