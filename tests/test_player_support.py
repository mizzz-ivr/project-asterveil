from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from game.app.client.client_diagnostics import (
    CrashReportWriter,
    DiagnosticSeverity,
    StructuredDiagnosticLogger,
    SupportBundleExporter,
)
from game.app.client.gamepad_input import (
    GamepadInputInterpreter,
    GamepadState,
    InputDeviceTracker,
    XINPUT_GAMEPAD_A,
    XINPUT_GAMEPAD_B,
    XINPUT_GAMEPAD_DPAD_DOWN,
    XINPUT_GAMEPAD_DPAD_UP,
    XINPUT_GAMEPAD_Y,
)
from game.app.client.player_support import (
    SteamDemoGuideSession,
    SteamDemoSupportSettings,
    SteamDemoSupportSettingsRepository,
    build_default_guide_catalog,
)
from game.app.presentation.input_actions import InputDevice, MenuInputAction


FIXED_TIME = datetime(2026, 7, 31, 0, 0, tzinfo=timezone.utc)


class GamepadInputInterpreterTest(unittest.TestCase):
    def test_dpad_and_buttons_are_converted_to_semantic_actions(self) -> None:
        interpreter = GamepadInputInterpreter()
        state = GamepadState(
            connected=True,
            buttons=(
                XINPUT_GAMEPAD_DPAD_UP
                | XINPUT_GAMEPAD_A
                | XINPUT_GAMEPAD_B
                | XINPUT_GAMEPAD_Y
            ),
        )
        events = interpreter.process(state, now_ms=1000)
        self.assertEqual(
            {
                MenuInputAction.MOVE_UP,
                MenuInputAction.CONFIRM,
                MenuInputAction.CANCEL,
                MenuInputAction.SHOW_GUIDE,
            },
            {event.action for event in events},
        )

    def test_left_stick_uses_deadzone(self) -> None:
        interpreter = GamepadInputInterpreter(stick_deadzone=12000)
        self.assertEqual(
            tuple(),
            interpreter.process(
                GamepadState(connected=True, left_thumb_y=11999), now_ms=0
            ),
        )
        above = interpreter.process(
            GamepadState(connected=True, left_thumb_y=12000), now_ms=10
        )
        self.assertEqual(MenuInputAction.MOVE_UP, above[0].action)

    def test_only_navigation_actions_repeat_after_delay(self) -> None:
        interpreter = GamepadInputInterpreter(
            repeat_delay_ms=400,
            repeat_interval_ms=100,
        )
        state = GamepadState(
            connected=True,
            buttons=XINPUT_GAMEPAD_DPAD_DOWN | XINPUT_GAMEPAD_A,
        )
        first = interpreter.process(state, now_ms=0)
        before_delay = interpreter.process(state, now_ms=399)
        first_repeat = interpreter.process(state, now_ms=400)
        before_interval = interpreter.process(state, now_ms=450)
        second_repeat = interpreter.process(state, now_ms=500)
        self.assertEqual(
            {MenuInputAction.MOVE_DOWN, MenuInputAction.CONFIRM},
            {event.action for event in first},
        )
        self.assertEqual(tuple(), before_delay)
        self.assertEqual(
            [(MenuInputAction.MOVE_DOWN, True)],
            [(event.action, event.repeated) for event in first_repeat],
        )
        self.assertEqual(tuple(), before_interval)
        self.assertEqual(
            [(MenuInputAction.MOVE_DOWN, True)],
            [(event.action, event.repeated) for event in second_repeat],
        )

    def test_disconnect_resets_pressed_state(self) -> None:
        interpreter = GamepadInputInterpreter()
        pressed = GamepadState(connected=True, buttons=XINPUT_GAMEPAD_DPAD_UP)
        interpreter.process(pressed, now_ms=0)
        interpreter.process(GamepadState.disconnected(), now_ms=10)
        reconnected = interpreter.process(pressed, now_ms=20)
        self.assertEqual(1, len(reconnected))
        self.assertFalse(reconnected[0].repeated)

    def test_input_tracker_returns_to_keyboard_after_disconnect(self) -> None:
        tracker = InputDeviceTracker()
        tracker.update_gamepad_connection(True)
        tracker.observe(InputDevice.GAMEPAD)
        self.assertTrue(tracker.update_gamepad_connection(False))
        self.assertEqual(InputDevice.KEYBOARD, tracker.active_device)
        self.assertFalse(tracker.gamepad_connected)


class SupportSettingsRepositoryTest(unittest.TestCase):
    def test_settings_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "client_settings.json"
            repository = SteamDemoSupportSettingsRepository(path)
            expected = SteamDemoSupportSettings(
                high_contrast=True,
                reduced_motion=True,
                tutorial_completed=True,
                gamepad_user_index=2,
                stick_deadzone=14000,
            )
            repository.save(expected)
            actual = repository.load()
            self.assertFalse(actual.recovered_from_invalid_file)
            self.assertEqual(expected, actual.settings)

    def test_invalid_settings_are_backed_up_and_reset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "client_settings.json"
            path.write_text("{invalid-json", encoding="utf-8")
            repository = SteamDemoSupportSettingsRepository(
                path, clock=lambda: FIXED_TIME
            )
            result = repository.load()
            self.assertTrue(result.recovered_from_invalid_file)
            self.assertIsNotNone(result.backup_path)
            self.assertTrue(result.backup_path.is_file())
            self.assertEqual(SteamDemoSupportSettings(), result.settings)
            self.assertEqual(SteamDemoSupportSettings(), repository.load().settings)

    def test_unsupported_version_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            ValueError, "unsupported_support_settings_version"
        ):
            SteamDemoSupportSettings.from_dict({"settings_version": 99})


class GuideCatalogTest(unittest.TestCase):
    def test_catalog_contains_nine_topics_and_context_routes(self) -> None:
        catalog = build_default_guide_catalog()
        self.assertEqual(9, len(catalog.pages))
        self.assertEqual("quest", catalog.topic_for_route("quest_board"))
        self.assertEqual("travel", catalog.topic_for_route("gathering"))
        self.assertEqual("workshop", catalog.topic_for_route("crafting"))
        self.assertEqual("objectives", catalog.topic_for_route("unknown_route"))

    def test_first_run_guide_completion_is_reported_on_close(self) -> None:
        session = SteamDemoGuideSession(build_default_guide_catalog())
        session.open_topic("welcome", opened_from="first_run", first_run=True)
        session.next_page()
        self.assertTrue(session.close())
        self.assertFalse(session.visible)

    def test_route_guide_can_move_between_pages(self) -> None:
        session = SteamDemoGuideSession(build_default_guide_catalog())
        opened = session.open_for_route("quest_board")
        previous = session.previous_page()
        next_page = session.next_page()
        self.assertEqual("quest", opened.page.topic_id)
        self.assertEqual(opened.page_index - 1, previous.page_index)
        self.assertEqual(opened.page_index, next_page.page_index)


class ClientDiagnosticsTest(unittest.TestCase):
    def test_structured_log_redacts_sensitive_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            logger = StructuredDiagnosticLogger(
                Path(temporary_directory),
                session_id="session-test",
                clock=lambda: FIXED_TIME,
            )
            logger.log(
                "test_event",
                "message",
                context={
                    "access_token": "secret-value",
                    "nested": {"password": "do-not-write"},
                },
            )
            payload = json.loads(logger.log_path.read_text(encoding="utf-8"))
            self.assertEqual("[REDACTED]", payload["context"]["access_token"])
            self.assertEqual(
                "[REDACTED]", payload["context"]["nested"]["password"]
            )

    def test_log_rotation_keeps_bounded_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            logger = StructuredDiagnosticLogger(
                root,
                session_id="rotation",
                max_file_bytes=100,
                max_files=3,
                clock=lambda: FIXED_TIME,
            )
            for index in range(10):
                logger.log(
                    "large_event",
                    "x" * 200,
                    severity=DiagnosticSeverity.INFO,
                    context={"index": index},
                )
            self.assertLessEqual(len(tuple(root.iterdir())), 3)
            self.assertTrue(logger.log_path.is_file())

    def test_crash_report_contains_context_without_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            writer = CrashReportWriter(
                Path(temporary_directory),
                session_id="crash-session",
                clock=lambda: FIXED_TIME,
            )
            path = writer.write(
                RuntimeError("boom"),
                phase="gameplay",
                route_id="quest_board",
                context={"api_key": "secret"},
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("RuntimeError", payload["exception"]["type"])
            self.assertEqual("gameplay", payload["client"]["phase"])
            self.assertEqual("[REDACTED]", payload["context"]["api_key"])

    def test_support_bundle_excludes_save_content_and_includes_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            diagnostics_root = root / "diagnostics"
            diagnostics_root.mkdir()
            (diagnostics_root / "session.ndjson").write_text(
                '{"event":"ok"}\n', encoding="utf-8"
            )
            settings_path = root / "client_settings.json"
            settings_path.write_text('{"settings_version":1}\n', encoding="utf-8")
            save_path = root / "steam_demo_slot_01.json"
            secret_marker = "DO_NOT_INCLUDE_SAVE_BODY"
            save_path.write_text(
                json.dumps(
                    {
                        "save_version": 1,
                        "secret_test_marker": secret_marker,
                    }
                ),
                encoding="utf-8",
            )
            exporter = SupportBundleExporter(
                root,
                settings_path=settings_path,
                save_path=save_path,
                clock=lambda: FIXED_TIME,
            )
            bundle_path = exporter.export(
                session_id="bundle-session", include_save_metadata=True
            )
            with zipfile.ZipFile(bundle_path) as archive:
                names = set(archive.namelist())
                self.assertIn("save/save_metadata.json", names)
                self.assertIn("settings/client_settings.json", names)
                self.assertNotIn(save_path.name, names)
                combined = b"".join(archive.read(name) for name in names)
                self.assertNotIn(secret_marker.encode("utf-8"), combined)
                metadata = json.loads(archive.read("save/save_metadata.json"))
                self.assertFalse(metadata["content_included"])
                self.assertEqual(1, metadata["save_version"])

    def test_disabled_logger_does_not_create_log_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            logger = StructuredDiagnosticLogger(
                Path(temporary_directory), enabled=False
            )
            logger.log("disabled", "not written")
            self.assertFalse(logger.log_path.exists())


if __name__ == "__main__":
    unittest.main()
