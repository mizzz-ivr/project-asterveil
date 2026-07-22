from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from game.app.application.demo_flow_service import DemoFlowService, SteamDemoApplication
from game.app.application.playable_slice import PlayableSliceApplication
from game.app.infrastructure.demo_flow_repository import DemoFlowMasterDataRepository
from game.quest.domain.entities import QuestStatus


FLOW_ID = "demo.steam.ch01.core_loop"
FIRST_QUEST_ID = "quest.ch01.missing_port_record"


class SteamDemoSaveLoadTests(unittest.TestCase):
    def test_checkpoint_flags_and_completed_progress_survive_save_load(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            save_path = Path(directory) / "steam-demo-save.json"
            definitions = DemoFlowMasterDataRepository(Path("data/master")).load()

            playable = PlayableSliceApplication(
                master_root=Path("data/master"),
                save_file_path=save_path,
            )
            playable.new_game()
            playable.accept_quest(FIRST_QUEST_ID)
            playable.quest_session.quest_states[FIRST_QUEST_ID].status = QuestStatus.COMPLETED
            playable.quest_session.world_flags.add(SteamDemoApplication.WORKSHOP_CHECKED_FLAG)
            demo = SteamDemoApplication(
                playable,
                DemoFlowService(definitions),
                FLOW_ID,
            )

            self.assertEqual("save_demo_checkpoint", demo.progress().active_step.step_id)
            self.assertEqual("demo_checkpoint_saved", demo.save_checkpoint()[0])
            self.assertTrue(save_path.exists())

            loaded_playable = PlayableSliceApplication(
                master_root=Path("data/master"),
                save_file_path=save_path,
            )
            loaded, message = loaded_playable.continue_game()
            loaded_demo = SteamDemoApplication(
                loaded_playable,
                DemoFlowService(definitions),
                FLOW_ID,
            )

            self.assertTrue(loaded, message)
            self.assertIn(
                SteamDemoApplication.WORKSHOP_CHECKED_FLAG,
                loaded_playable.quest_session.world_flags,
            )
            self.assertIn(
                SteamDemoApplication.CHECKPOINT_SAVED_FLAG,
                loaded_playable.quest_session.world_flags,
            )
            self.assertTrue(loaded_demo.progress().is_completed)


if __name__ == "__main__":
    unittest.main()
