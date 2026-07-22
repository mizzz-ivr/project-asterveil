from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from game.app.application.demo_flow_service import (
    DemoFlowContext,
    DemoFlowDefinition,
    DemoFlowService,
    DemoFlowStepDefinition,
    SteamDemoApplication,
)
from game.app.application.playable_slice import PlayableSliceApplication
from game.app.infrastructure.demo_flow_repository import DemoFlowMasterDataRepository
from game.quest.domain.entities import QuestStatus


FLOW_ID = "demo.steam.ch01.core_loop"
FIRST_QUEST_ID = "quest.ch01.missing_port_record"
HUB_LOCATION_ID = "location.town.astel"
FIELD_LOCATION_ID = "location.field.tidal_flats"


def _condition_step(
    step_id: str,
    condition: dict[str, object],
    recommended_action: str,
) -> DemoFlowStepDefinition:
    return DemoFlowStepDefinition(
        step_id=step_id,
        title=step_id,
        guidance_text=f"guide:{step_id}",
        recommended_action=recommended_action,
        completion_condition=condition,
    )


def _definition() -> DemoFlowDefinition:
    return DemoFlowDefinition(
        flow_id=FLOW_ID,
        name="Steamデモ",
        description="テスト用フロー",
        steps=(
            _condition_step(
                "accept",
                {
                    "type": "quest_status",
                    "quest_id": FIRST_QUEST_ID,
                    "statuses": ["in_progress", "ready_to_complete", "completed"],
                },
                "quest_board",
            ),
            _condition_step(
                "travel",
                {
                    "type": "any",
                    "conditions": [
                        {"type": "current_location", "location_id": FIELD_LOCATION_ID},
                        {
                            "type": "quest_status",
                            "quest_id": FIRST_QUEST_ID,
                            "statuses": ["ready_to_complete", "completed"],
                        },
                    ],
                },
                "move",
            ),
            _condition_step(
                "battle",
                {
                    "type": "quest_status",
                    "quest_id": FIRST_QUEST_ID,
                    "statuses": ["ready_to_complete", "completed"],
                },
                "hunt",
            ),
            _condition_step(
                "report",
                {
                    "type": "quest_status",
                    "quest_id": FIRST_QUEST_ID,
                    "statuses": ["completed"],
                },
                "report",
            ),
            _condition_step(
                "workshop",
                {"type": "world_flag", "flag": SteamDemoApplication.WORKSHOP_CHECKED_FLAG},
                "inspect_workshop",
            ),
            _condition_step(
                "save",
                {"type": "world_flag", "flag": SteamDemoApplication.CHECKPOINT_SAVED_FLAG},
                "save",
            ),
        ),
    )


def _context(
    *,
    quest_status: str = "not_accepted",
    location_id: str = HUB_LOCATION_ID,
    flags: set[str] | None = None,
) -> DemoFlowContext:
    return DemoFlowContext(
        quest_statuses={FIRST_QUEST_ID: quest_status},
        world_flags=frozenset(flags or set()),
        current_location_id=location_id,
        workshop_rank=1,
    )


class _FakePlayable:
    def __init__(
        self,
        *,
        quest_status: QuestStatus,
        flags: set[str] | None = None,
        location_id: str = HUB_LOCATION_ID,
    ) -> None:
        self.quest_session = SimpleNamespace(
            quest_states={FIRST_QUEST_ID: SimpleNamespace(status=quest_status)},
            world_flags=set(flags or set()),
        )
        self.location_state = SimpleNamespace(current_location_id=location_id)
        self.workshop_progress_state = SimpleNamespace(level=1)
        self.saved_world_flags: set[str] | None = None

    def crafting_recipe_lines(self) -> list[str]:
        return ["craft_recipe:test.recipe:テストレシピ"]

    def save_game(self) -> None:
        self.saved_world_flags = set(self.quest_session.world_flags)


class DemoFlowRepositoryTests(unittest.TestCase):
    def test_loads_default_demo_flow(self) -> None:
        definitions = DemoFlowMasterDataRepository(Path("data/master")).load()

        self.assertIn(FLOW_ID, definitions)
        self.assertEqual(6, len(definitions[FLOW_ID].steps))
        self.assertEqual("accept_first_quest", definitions[FLOW_ID].steps[0].step_id)

    def test_rejects_duplicate_step_id(self) -> None:
        raw = [
            {
                "flow_id": "demo.test",
                "name": "test",
                "description": "test",
                "steps": [
                    {
                        "step_id": "same",
                        "title": "one",
                        "guidance_text": "one",
                        "recommended_action": "guide",
                        "completion_condition": {"type": "world_flag", "flag": "flag.one"},
                    },
                    {
                        "step_id": "same",
                        "title": "two",
                        "guidance_text": "two",
                        "recommended_action": "guide",
                        "completion_condition": {"type": "world_flag", "flag": "flag.two"},
                    },
                ],
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "demo_flows.sample.json").write_text(
                json.dumps(raw, ensure_ascii=False), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "duplicate demo flow step id"):
                DemoFlowMasterDataRepository(root).load()

    def test_rejects_unsupported_condition(self) -> None:
        raw = [
            {
                "flow_id": "demo.test",
                "name": "test",
                "description": "test",
                "steps": [
                    {
                        "step_id": "step",
                        "title": "step",
                        "guidance_text": "step",
                        "recommended_action": "guide",
                        "completion_condition": {"type": "unknown_condition"},
                    }
                ],
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "demo_flows.sample.json").write_text(
                json.dumps(raw, ensure_ascii=False), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "unsupported demo flow condition type"):
                DemoFlowMasterDataRepository(root).load()


class DemoFlowServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = DemoFlowService({FLOW_ID: _definition()})

    def test_progresses_through_the_ordered_demo_steps(self) -> None:
        cases = [
            (_context(), "accept"),
            (_context(quest_status="in_progress"), "travel"),
            (
                _context(quest_status="in_progress", location_id=FIELD_LOCATION_ID),
                "battle",
            ),
            (_context(quest_status="ready_to_complete"), "report"),
            (_context(quest_status="completed"), "workshop"),
            (
                _context(
                    quest_status="completed",
                    flags={SteamDemoApplication.WORKSHOP_CHECKED_FLAG},
                ),
                "save",
            ),
        ]

        for context, expected_step_id in cases:
            with self.subTest(expected_step_id=expected_step_id):
                progress = self.service.evaluate(FLOW_ID, context)
                self.assertFalse(progress.is_completed)
                self.assertIsNotNone(progress.active_step)
                self.assertEqual(expected_step_id, progress.active_step.step_id)

        completed = self.service.evaluate(
            FLOW_ID,
            _context(
                quest_status="completed",
                flags={
                    SteamDemoApplication.WORKSHOP_CHECKED_FLAG,
                    SteamDemoApplication.CHECKPOINT_SAVED_FLAG,
                },
            ),
        )
        self.assertTrue(completed.is_completed)
        self.assertIsNone(completed.active_step)

    def test_later_conditions_do_not_skip_an_incomplete_earlier_step(self) -> None:
        progress = self.service.evaluate(
            FLOW_ID,
            _context(
                flags={
                    SteamDemoApplication.WORKSHOP_CHECKED_FLAG,
                    SteamDemoApplication.CHECKPOINT_SAVED_FLAG,
                }
            ),
        )

        self.assertEqual("accept", progress.active_step.step_id)
        self.assertEqual(tuple(), progress.completed_step_ids)

    def test_guidance_reports_completion(self) -> None:
        lines = self.service.guidance_lines(
            FLOW_ID,
            _context(
                quest_status="completed",
                flags={
                    SteamDemoApplication.WORKSHOP_CHECKED_FLAG,
                    SteamDemoApplication.CHECKPOINT_SAVED_FLAG,
                },
            ),
        )

        self.assertIn(f"demo_flow_completed:{FLOW_ID}:Steamデモ", lines)


class SteamDemoApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = DemoFlowService({FLOW_ID: _definition()})

    def test_inspect_workshop_does_not_complete_out_of_order(self) -> None:
        playable = _FakePlayable(quest_status=QuestStatus.IN_PROGRESS)
        demo = SteamDemoApplication(playable, self.service, FLOW_ID)

        lines = demo.inspect_workshop()

        self.assertTrue(lines[0].startswith("demo_workshop_checked_out_of_order"))
        self.assertNotIn(
            SteamDemoApplication.WORKSHOP_CHECKED_FLAG,
            playable.quest_session.world_flags,
        )

    def test_inspect_workshop_marks_the_active_demo_step(self) -> None:
        playable = _FakePlayable(quest_status=QuestStatus.COMPLETED)
        demo = SteamDemoApplication(playable, self.service, FLOW_ID)

        lines = demo.inspect_workshop()

        self.assertEqual("demo_workshop_checked", lines[0])
        self.assertIn(
            SteamDemoApplication.WORKSHOP_CHECKED_FLAG,
            playable.quest_session.world_flags,
        )
        self.assertEqual("save", demo.progress().active_step.step_id)

    def test_save_checkpoint_sets_the_flag_before_persisting(self) -> None:
        playable = _FakePlayable(
            quest_status=QuestStatus.COMPLETED,
            flags={SteamDemoApplication.WORKSHOP_CHECKED_FLAG},
        )
        demo = SteamDemoApplication(playable, self.service, FLOW_ID)

        lines = demo.save_checkpoint()

        self.assertEqual("demo_checkpoint_saved", lines[0])
        self.assertIsNotNone(playable.saved_world_flags)
        self.assertIn(
            SteamDemoApplication.CHECKPOINT_SAVED_FLAG,
            playable.saved_world_flags,
        )
        self.assertTrue(demo.progress().is_completed)

    def test_real_playable_slice_starts_at_first_quest_and_advances_after_accept(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            save_path = Path(directory) / "demo-save.json"
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

            self.assertEqual("accept_first_quest", demo.progress().active_step.step_id)
            self.assertEqual(
                [f"quest_accepted:{FIRST_QUEST_ID}"],
                playable.accept_quest(FIRST_QUEST_ID),
            )
            self.assertEqual("travel_to_tidal_flats", demo.progress().active_step.step_id)


if __name__ == "__main__":
    unittest.main()
