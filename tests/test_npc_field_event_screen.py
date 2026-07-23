from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from game.app.application.playable_interaction_facade import PlayableInteractionFacade
from game.app.application.playable_slice import PlayableSliceApplication
from game.app.cli import run_steam_demo
from game.app.presentation.input_actions import MenuInputAction
from game.app.presentation.npc_field_event_screen import (
    FieldEventScreenController,
    FieldEventScreenMode,
    NpcDialogueScreenController,
    NpcDialogueScreenMode,
)
from game.quest.domain.entities import BattleResult


ELDER_ID = "npc.astel.elder"
FIRST_QUEST_ID = "quest.ch01.missing_port_record"
FIELD_LOCATION_ID = "location.field.tidal_flats"
DRIFT_EVENT_ID = "event.field.tidal_flats.drift_supply"
DRIFT_SAFE_CHOICE_ID = "choice.safe_collect"


class NpcFieldEventScreenTestBase(unittest.TestCase):
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


class NpcDialogueFacadeTests(NpcFieldEventScreenTestBase):
    def test_lists_current_location_npcs_as_typed_models(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            facade = PlayableInteractionFacade(app)

            npcs = facade.list_npcs()

            elder = next(npc for npc in npcs if npc.npc_id == ELDER_ID)
            self.assertEqual("港町アステル", app._travel_service.location(elder.location_id).name)
            self.assertEqual("npc.astel.elder", elder.npc_id)
            self.assertTrue(elder.npc_name)

    def test_dialogue_choice_applies_flag_and_accepts_quest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            facade = PlayableInteractionFacade(app)

            started = facade.start_dialogue(ELDER_ID)
            resolved = facade.select_dialogue_choice(started, "choice.help")

            self.assertTrue(started.success)
            self.assertFalse(started.completed)
            self.assertIn("choice.help", {choice.choice_id for choice in started.choices})
            self.assertTrue(resolved.success)
            self.assertTrue(resolved.completed)
            self.assertIn("flag.helped_npc", app.quest_session.world_flags)
            self.assertIn(FIRST_QUEST_ID, app.quest_session.quest_states)
            self.assertTrue(any(line == f"quest_accepted:{FIRST_QUEST_ID}" for line in resolved.logs))
            self.assertTrue(any("準備ができたら干潟へ" in line for line in resolved.lines))

    def test_unknown_choice_does_not_change_dialogue_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            facade = PlayableInteractionFacade(app)
            started = facade.start_dialogue(ELDER_ID)

            rejected = facade.select_dialogue_choice(started, "choice.unknown")

            self.assertFalse(rejected.success)
            self.assertFalse(rejected.completed)
            self.assertIn("choice_not_found", rejected.code)
            self.assertNotIn("flag.helped_npc", app.quest_session.world_flags)
            self.assertNotIn(FIRST_QUEST_ID, app.quest_session.quest_states)


class NpcDialogueScreenControllerTests(NpcFieldEventScreenTestBase):
    def test_controller_moves_from_npc_list_to_dialogue_and_back(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            controller = NpcDialogueScreenController(PlayableInteractionFacade(app))

            initial = controller.current_view()
            started = controller.activate_npc(ELDER_ID)
            resolved = controller.activate_choice("choice.help")
            closed = controller.handle_input(MenuInputAction.CONFIRM)

            self.assertEqual(NpcDialogueScreenMode.NPC_LIST, initial.mode)
            self.assertEqual(NpcDialogueScreenMode.DIALOGUE, started.view.mode)
            self.assertEqual(NpcDialogueScreenMode.DIALOGUE, resolved.view.mode)
            self.assertTrue(resolved.view.dialogue.completed)
            self.assertEqual(NpcDialogueScreenMode.NPC_LIST, closed.view.mode)

    def test_unknown_npc_is_rejected_without_starting_dialogue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            controller = NpcDialogueScreenController(PlayableInteractionFacade(app))

            rejected = controller.activate_npc("npc.unknown")

            self.assertEqual("npc_not_available", rejected.rejection_reason)
            self.assertEqual(NpcDialogueScreenMode.NPC_LIST, rejected.view.mode)


class FieldEventFacadeAndControllerTests(NpcFieldEventScreenTestBase):
    def build_field_controller(
        self,
        save_path: Path,
    ) -> tuple[PlayableSliceApplication, FieldEventScreenController]:
        app = self.build_app(save_path)
        app.accept_quest(FIRST_QUEST_ID)
        app.travel_to(FIELD_LOCATION_ID)
        return app, FieldEventScreenController(PlayableInteractionFacade(app))

    def test_lists_events_and_resolves_choice_with_typed_detail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app, controller = self.build_field_controller(Path(directory) / "save.json")

            initial = controller.current_view()
            detail = controller.activate_event(DRIFT_EVENT_ID)
            resolved = controller.activate_choice(DRIFT_SAFE_CHOICE_ID)

            event = next(item for item in initial.events if item.event_id == DRIFT_EVENT_ID)
            self.assertTrue(event.can_execute)
            self.assertEqual(FieldEventScreenMode.CHOICE_LIST, detail.view.mode)
            self.assertIn(
                DRIFT_SAFE_CHOICE_ID,
                {choice.choice_id for choice in detail.view.detail.choices},
            )
            self.assertIsNone(resolved.rejection_reason)
            self.assertEqual(FieldEventScreenMode.EVENT_LIST, resolved.view.mode)
            self.assertIn(DRIFT_EVENT_ID, app.completed_field_event_ids)
            self.assertEqual(
                DRIFT_SAFE_CHOICE_ID,
                app.field_event_choice_history[DRIFT_EVENT_ID],
            )

    def test_completed_nonrepeatable_event_and_unknown_choice_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, controller = self.build_field_controller(Path(directory) / "save.json")
            controller.activate_event(DRIFT_EVENT_ID)

            unknown_choice = controller.activate_choice("choice.unknown")
            self.assertEqual("choice_not_available", unknown_choice.rejection_reason)

            controller.activate_choice(DRIFT_SAFE_CHOICE_ID)
            completed = controller.activate_event(DRIFT_EVENT_ID)

            self.assertEqual("already_completed", completed.rejection_reason)

    def test_back_and_guide_are_safe_in_both_screen_modes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, controller = self.build_field_controller(Path(directory) / "save.json")

            guide = controller.handle_input(MenuInputAction.SHOW_GUIDE)
            controller.activate_event(DRIFT_EVENT_ID)
            back = controller.handle_input(MenuInputAction.CANCEL)

            self.assertTrue(guide.logs[0].startswith("field_event_guide:"))
            self.assertEqual(FieldEventScreenMode.EVENT_LIST, back.view.mode)
            self.assertFalse(back.cancel_requested)


class SteamDemoCliNpcFieldEventAdapterTests(NpcFieldEventScreenTestBase):
    def test_npc_dialogue_cli_uses_new_controller(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")

            with patch.object(
                run_steam_demo.base_cli,
                "_choose",
                side_effect=[ELDER_ID, "choice.help"],
            ):
                logs = run_steam_demo._run_npc_dialogue_screen(app)

            self.assertIn(f"quest_accepted:{FIRST_QUEST_ID}", logs)
            self.assertIn("flag.helped_npc", app.quest_session.world_flags)

    def test_field_event_cli_uses_new_controller(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            app.accept_quest(FIRST_QUEST_ID)
            app.travel_to(FIELD_LOCATION_ID)

            with patch.object(
                run_steam_demo.base_cli,
                "_choose",
                side_effect=[DRIFT_EVENT_ID, DRIFT_SAFE_CHOICE_ID],
            ):
                logs = run_steam_demo._run_field_event_screen(app)

            self.assertTrue(any(line == f"field_event_resolved:{DRIFT_EVENT_ID}" for line in logs))
            self.assertIn(DRIFT_EVENT_ID, app.completed_field_event_ids)


if __name__ == "__main__":
    unittest.main()
