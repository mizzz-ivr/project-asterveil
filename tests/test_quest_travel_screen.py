from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from game.app.application.playable_slice import PlayableSliceApplication
from game.app.cli import run_steam_demo
from game.app.presentation.input_actions import MenuInputAction
from game.app.presentation.quest_travel_screen import (
    QuestBoardScreenController,
    QuestBoardScreenPresenter,
    TravelScreenController,
    TravelScreenPresenter,
)
from game.quest.domain.entities import QuestBoardStatus


FIRST_QUEST_ID = "quest.ch01.missing_port_record"
LOCKED_QUEST_ID = "quest.ch01.harbor_cleanup"
HUB_LOCATION_ID = "location.town.astel"
FIELD_LOCATION_ID = "location.field.tidal_flats"


class QuestTravelScreenTestBase(unittest.TestCase):
    def build_app(self, save_path: Path) -> PlayableSliceApplication:
        app = PlayableSliceApplication(
            master_root=Path("data/master"),
            save_file_path=save_path,
        )
        app.new_game()
        return app


class QuestBoardScreenTests(QuestTravelScreenTestBase):
    def test_view_exposes_status_progress_and_acceptability(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")

            view = QuestBoardScreenPresenter().build(app)
            entries = {entry.quest_id: entry for entry in view.entries}

            self.assertEqual("クエストボード", view.title)
            self.assertEqual(2, view.max_active_quests)
            self.assertEqual(0, view.active_quest_count)
            self.assertEqual(QuestBoardStatus.AVAILABLE, entries[FIRST_QUEST_ID].status)
            self.assertTrue(entries[FIRST_QUEST_ID].can_accept)
            self.assertEqual("未開始", entries[FIRST_QUEST_ID].progress_label)
            self.assertEqual(QuestBoardStatus.LOCKED, entries[LOCKED_QUEST_ID].status)
            self.assertFalse(entries[LOCKED_QUEST_ID].can_accept)

    def test_accepting_quest_rebuilds_view_and_prevents_duplicate_accept(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            controller = QuestBoardScreenController(app)

            accepted = controller.activate_quest(FIRST_QUEST_ID)
            accepted_entries = {
                entry.quest_id: entry for entry in accepted.view.entries
            }
            duplicate = controller.activate_quest(FIRST_QUEST_ID)

            self.assertEqual((f"quest_accepted:{FIRST_QUEST_ID}",), accepted.logs)
            self.assertEqual(1, accepted.view.active_quest_count)
            self.assertEqual(
                QuestBoardStatus.IN_PROGRESS,
                accepted_entries[FIRST_QUEST_ID].status,
            )
            self.assertFalse(accepted_entries[FIRST_QUEST_ID].can_accept)
            self.assertEqual("quest_not_available", duplicate.rejection_reason)
            self.assertTrue(
                duplicate.logs[0].startswith("quest_accept_rejected:not_available:")
            )

    def test_locked_and_unknown_quests_are_rejected_without_state_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            controller = QuestBoardScreenController(app)

            locked = controller.activate_quest(LOCKED_QUEST_ID)
            unknown = controller.activate_quest("quest.unknown")

            self.assertEqual("quest_not_available", locked.rejection_reason)
            self.assertEqual("unknown_quest", unknown.rejection_reason)
            self.assertEqual(0, locked.view.active_quest_count)
            self.assertEqual(0, unknown.view.active_quest_count)

    def test_cancel_and_guide_are_screen_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            controller = QuestBoardScreenController(app)

            guide = controller.handle_input(MenuInputAction.SHOW_GUIDE)
            cancelled = controller.handle_input(MenuInputAction.CANCEL)

            self.assertTrue(guide.logs[0].startswith("quest_board_guide:"))
            self.assertFalse(guide.cancel_requested)
            self.assertTrue(cancelled.cancel_requested)
            self.assertEqual(tuple(), cancelled.logs)

    def test_invalid_log_contract_is_rejected(self) -> None:
        class InvalidQuestBoardApp:
            def quest_board_lines(self) -> list[str]:
                return [
                    "quest_board:max_active=2",
                    "quest_board_entry:broken",
                ]

        with self.assertRaisesRegex(ValueError, "invalid quest board line"):
            QuestBoardScreenPresenter().build(InvalidQuestBoardApp())  # type: ignore[arg-type]


class TravelScreenTests(QuestTravelScreenTestBase):
    def test_view_exposes_current_location_and_reachable_destinations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")

            view = TravelScreenPresenter().build(app)
            destinations = {
                destination.location_id: destination
                for destination in view.destinations
            }

            self.assertEqual("移動", view.title)
            self.assertEqual(HUB_LOCATION_ID, view.current_location_id)
            self.assertEqual("港町アステル", view.current_location_name)
            self.assertIn(FIELD_LOCATION_ID, destinations)
            self.assertEqual("field", destinations[FIELD_LOCATION_ID].location_type)
            self.assertIsNotNone(view.selection.selected_index)

    def test_travel_rebuilds_view_from_new_location(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            controller = TravelScreenController(app)

            travelled = controller.activate_destination(FIELD_LOCATION_ID)
            next_destinations = {
                destination.location_id
                for destination in travelled.view.destinations
            }

            self.assertIn(
                f"travel_succeeded:{FIELD_LOCATION_ID}",
                travelled.logs,
            )
            self.assertEqual(FIELD_LOCATION_ID, travelled.view.current_location_id)
            self.assertIn(HUB_LOCATION_ID, next_destinations)

    def test_unknown_destination_and_cancel_are_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            controller = TravelScreenController(app)

            rejected = controller.activate_destination("location.unknown")
            cancelled = controller.handle_input(MenuInputAction.CANCEL)

            self.assertEqual("destination_not_available", rejected.rejection_reason)
            self.assertEqual(HUB_LOCATION_ID, rejected.view.current_location_id)
            self.assertTrue(cancelled.cancel_requested)

    def test_invalid_travel_log_contract_is_rejected(self) -> None:
        class InvalidTravelApp:
            def travel_options_lines(self) -> list[str]:
                return [
                    "current_location:location.test:テスト",
                    "travel_option:broken",
                ]

        with self.assertRaisesRegex(ValueError, "invalid travel option line"):
            TravelScreenPresenter().build(InvalidTravelApp())  # type: ignore[arg-type]


class QuestTravelCliAdapterTests(QuestTravelScreenTestBase):
    def test_quest_board_cli_uses_new_controller(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            original_choose = run_steam_demo.base_cli._choose
            run_steam_demo.base_cli._choose = lambda _: FIRST_QUEST_ID
            try:
                logs = run_steam_demo._run_quest_board_screen(app)
            finally:
                run_steam_demo.base_cli._choose = original_choose

            self.assertEqual([f"quest_accepted:{FIRST_QUEST_ID}"], logs)

    def test_travel_cli_uses_new_controller(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self.build_app(Path(directory) / "save.json")
            original_choose = run_steam_demo.base_cli._choose
            run_steam_demo.base_cli._choose = lambda _: FIELD_LOCATION_ID
            try:
                logs = run_steam_demo._run_travel_screen(app)
            finally:
                run_steam_demo.base_cli._choose = original_choose

            self.assertIn(f"travel_succeeded:{FIELD_LOCATION_ID}", logs)


if __name__ == "__main__":
    unittest.main()
