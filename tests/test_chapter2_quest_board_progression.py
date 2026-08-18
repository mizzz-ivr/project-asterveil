from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from game.app.application.playable_slice import PlayableSliceApplication
from game.quest.domain.entities import BattleResult, QuestStatus


MASTER_ROOT = Path("data/master")
MIST_HARBOR_ID = "location.ch02.mist_harbor"
ECHO_PATROL_ID = "quest.ch02.echo_patrol"
MIST_TRACE_DELIVERY_ID = "quest.ch02.mist_trace_delivery"


class Chapter2QuestBoardProgressionTest(unittest.TestCase):
    def _build_app(self, tmp_dir: str) -> PlayableSliceApplication:
        app = PlayableSliceApplication(
            master_root=MASTER_ROOT,
            save_file_path=Path(tmp_dir) / "slot_01.json",
            battle_executor=lambda encounter_id, party_members=None: BattleResult(
                encounter_id=encounter_id,
                player_won=False,
                defeated_enemy_ids=tuple(),
            ),
        )
        app.new_game()
        app.party_members[0].level = 10
        app.location_state.current_location_id = MIST_HARBOR_ID
        app.location_state.unlocked_location_ids.add(MIST_HARBOR_ID)
        return app

    def _set_completed_quest(self, app: PlayableSliceApplication, quest_id: str) -> None:
        state = app.quest_session.quest_service.create_initial_state(quest_id)
        state.status = QuestStatus.COMPLETED
        state.reward_claimed = True
        app.quest_session.quest_states[quest_id] = state
        app.quest_session.world_flags.add(f"flag.quest.accepted:{quest_id}")

    def _quest_board_entry_line(
        self,
        app: PlayableSliceApplication,
        quest_id: str,
    ) -> str:
        prefix = f"quest_board_entry:{quest_id}:"
        return next(line for line in app.quest_board_lines() if line.startswith(prefix))

    def test_echo_patrol_unlocks_only_after_mist_trace_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._build_app(tmp_dir)
            self._set_completed_quest(app, "quest.ch02.first_trace")
            app.quest_session.world_flags.update(
                {
                    "flag.ch02.first_trace_complete",
                    "flag.field_event.ch02.mist_trace_collected",
                }
            )

            before_delivery = self._quest_board_entry_line(app, ECHO_PATROL_ID)
            self.assertIn("status=locked", before_delivery)
            self.assertIn("can_accept=False", before_delivery)

            accept_logs = app.accept_quest(MIST_TRACE_DELIVERY_ID)
            self.assertIn(
                f"quest_accepted:{MIST_TRACE_DELIVERY_ID}",
                accept_logs,
            )
            app.inventory_state.setdefault("items", {})["item.material.memory_shard"] = 2

            turn_in_logs = app.turn_in_quest_items(
                MIST_TRACE_DELIVERY_ID,
                auto_complete=True,
            )
            self.assertTrue(
                any(
                    log.startswith(f"turn_in_success:{MIST_TRACE_DELIVERY_ID}")
                    for log in turn_in_logs
                )
            )
            self.assertEqual(
                app.quest_session.quest_states[MIST_TRACE_DELIVERY_ID].status,
                QuestStatus.COMPLETED,
            )
            self.assertIn(
                "flag.ch02.mist_trace_delivered",
                app.quest_session.world_flags,
            )

            after_delivery = self._quest_board_entry_line(app, ECHO_PATROL_ID)
            self.assertIn("status=available", after_delivery)
            self.assertIn("can_accept=True", after_delivery)

            echo_accept_logs = app.accept_quest(ECHO_PATROL_ID)
            self.assertIn(f"quest_accepted:{ECHO_PATROL_ID}", echo_accept_logs)
            self.assertEqual(
                app.quest_session.quest_states[ECHO_PATROL_ID].status,
                QuestStatus.IN_PROGRESS,
            )


if __name__ == "__main__":
    unittest.main()
