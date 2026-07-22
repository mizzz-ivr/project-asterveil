from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from game.app.application.demo_flow_service import DemoFlowService, SteamDemoApplication
from game.app.application.playable_slice import PlayableSliceApplication
from game.app.infrastructure.demo_flow_repository import DemoFlowMasterDataRepository
from game.app.presentation.input_actions import (
    InputBinding,
    InputBindingProfile,
    InputDevice,
    MenuInputAction,
    build_default_input_binding_profile,
)
from game.app.presentation.menu_view_model import (
    MenuItemViewModel,
    MenuNavigationService,
    MenuSelectionState,
    SteamDemoMenuPresenter,
)
from game.quest.domain.entities import QuestStatus


FLOW_ID = "demo.steam.ch01.core_loop"
FIRST_QUEST_ID = "quest.ch01.missing_port_record"


class InputBindingProfileTests(unittest.TestCase):
    def test_default_profile_resolves_keyboard_and_gamepad_inputs(self) -> None:
        profile = build_default_input_binding_profile()

        self.assertEqual(
            MenuInputAction.MOVE_UP,
            profile.resolve(InputDevice.KEYBOARD, " Arrow_Up "),
        )
        self.assertEqual(
            MenuInputAction.CONFIRM,
            profile.resolve(InputDevice.KEYBOARD, "ENTER"),
        )
        self.assertEqual(
            MenuInputAction.CANCEL,
            profile.resolve(InputDevice.GAMEPAD, "button_east"),
        )
        self.assertEqual(
            MenuInputAction.SHOW_GUIDE,
            profile.resolve(InputDevice.GAMEPAD, "BUTTON_NORTH"),
        )

    def test_unknown_or_empty_input_is_not_resolved(self) -> None:
        profile = build_default_input_binding_profile()

        self.assertIsNone(profile.resolve(InputDevice.KEYBOARD, "unknown"))
        self.assertIsNone(profile.resolve(InputDevice.KEYBOARD, "  "))

    def test_duplicate_binding_in_same_device_is_rejected(self) -> None:
        bindings = (
            InputBinding(
                InputDevice.KEYBOARD,
                "enter",
                MenuInputAction.CONFIRM,
                "Enter",
            ),
            InputBinding(
                InputDevice.KEYBOARD,
                "ENTER",
                MenuInputAction.CANCEL,
                "Enter",
            ),
        )

        with self.assertRaisesRegex(ValueError, "duplicate input binding"):
            InputBindingProfile(bindings)

    def test_hints_expose_primary_keyboard_and_gamepad_labels(self) -> None:
        profile = build_default_input_binding_profile()
        hints = {hint.action: hint for hint in profile.hints()}

        self.assertEqual("↑", hints[MenuInputAction.MOVE_UP].keyboard_label)
        self.assertEqual("D-pad ↑", hints[MenuInputAction.MOVE_UP].gamepad_label)
        self.assertEqual("Enter", hints[MenuInputAction.CONFIRM].keyboard_label)
        self.assertEqual("A", hints[MenuInputAction.CONFIRM].gamepad_label)


class MenuNavigationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.navigation = MenuNavigationService()

    def test_empty_menu_has_no_selection_and_confirm_is_safe(self) -> None:
        state = self.navigation.initial_selection(tuple())
        result = self.navigation.apply(state, tuple(), MenuInputAction.CONFIRM)

        self.assertIsNone(state.selected_index)
        self.assertIsNone(result.confirmed_action_id)
        self.assertFalse(result.cancelled)

    def test_single_item_menu_keeps_the_only_selection(self) -> None:
        items = (MenuItemViewModel("status", "ステータス"),)
        state = self.navigation.initial_selection(items)

        moved_down = self.navigation.apply(state, items, MenuInputAction.MOVE_DOWN)
        moved_up = self.navigation.apply(state, items, MenuInputAction.MOVE_UP)

        self.assertEqual(0, moved_down.selection.selected_index)
        self.assertEqual(0, moved_up.selection.selected_index)

    def test_multiple_item_menu_wraps_and_skips_disabled_items(self) -> None:
        items = (
            MenuItemViewModel("one", "1"),
            MenuItemViewModel("disabled", "無効", is_enabled=False),
            MenuItemViewModel("three", "3"),
        )
        state = MenuSelectionState(selected_index=0)

        moved_up = self.navigation.apply(state, items, MenuInputAction.MOVE_UP)
        moved_down = self.navigation.apply(state, items, MenuInputAction.MOVE_DOWN)

        self.assertEqual(2, moved_up.selection.selected_index)
        self.assertEqual(2, moved_down.selection.selected_index)

    def test_confirm_cancel_and_guide_are_reported_without_mutating_items(self) -> None:
        items = (
            MenuItemViewModel("status", "ステータス"),
            MenuItemViewModel("save", "セーブ"),
        )
        state = MenuSelectionState(selected_index=1)

        confirmed = self.navigation.apply(state, items, MenuInputAction.CONFIRM)
        cancelled = self.navigation.apply(state, items, MenuInputAction.CANCEL)
        guide = self.navigation.apply(state, items, MenuInputAction.SHOW_GUIDE)

        self.assertEqual("save", confirmed.confirmed_action_id)
        self.assertTrue(cancelled.cancelled)
        self.assertTrue(guide.guide_requested)
        self.assertEqual(state, confirmed.selection)


class SteamDemoMenuPresenterTests(unittest.TestCase):
    def _build_apps(self, save_path: Path) -> tuple[PlayableSliceApplication, SteamDemoApplication]:
        playable = PlayableSliceApplication(
            master_root=Path("data/master"),
            save_file_path=save_path,
        )
        playable.new_game()
        definitions = DemoFlowMasterDataRepository(Path("data/master")).load()
        demo = SteamDemoApplication(
            playable,
            DemoFlowService(definitions),
            FLOW_ID,
        )
        return playable, demo

    def _accept_and_complete_first_quest(self, playable: PlayableSliceApplication) -> None:
        self.assertEqual(
            [f"quest_accepted:{FIRST_QUEST_ID}"],
            playable.accept_quest(FIRST_QUEST_ID),
        )
        playable.quest_session.quest_states[FIRST_QUEST_ID].status = QuestStatus.COMPLETED

    def test_new_game_view_model_recommends_the_quest_board(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            playable, demo = self._build_apps(Path(directory) / "save.json")

            view = SteamDemoMenuPresenter().build(playable, demo)

            self.assertEqual("0/6", view.progress_label)
            self.assertEqual("quest_board", view.recommended_action_id)
            recommended = [item.action_id for item in view.items if item.is_recommended]
            self.assertEqual(["quest_board"], recommended)
            self.assertEqual("demo_guide", view.items[0].action_id)
            self.assertEqual(5, len(view.input_hints))

    def test_completed_quest_view_model_exposes_workshop_action(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            playable, demo = self._build_apps(Path(directory) / "save.json")
            self._accept_and_complete_first_quest(playable)

            view = SteamDemoMenuPresenter().build(playable, demo)

            self.assertEqual("demo_workshop", view.recommended_action_id)
            self.assertTrue(
                any(
                    item.action_id == "demo_workshop" and item.is_recommended
                    for item in view.items
                )
            )

    def test_completed_demo_view_model_has_no_recommended_action(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            playable, demo = self._build_apps(Path(directory) / "save.json")
            self._accept_and_complete_first_quest(playable)
            playable.quest_session.world_flags.update(
                {
                    SteamDemoApplication.WORKSHOP_CHECKED_FLAG,
                    SteamDemoApplication.CHECKPOINT_SAVED_FLAG,
                }
            )

            view = SteamDemoMenuPresenter().build(playable, demo)

            self.assertTrue(view.is_completed)
            self.assertEqual("6/6", view.progress_label)
            self.assertIsNone(view.recommended_action_id)
            self.assertFalse(any(item.is_recommended for item in view.items))


if __name__ == "__main__":
    unittest.main()
