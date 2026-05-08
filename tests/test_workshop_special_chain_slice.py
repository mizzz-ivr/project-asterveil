from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from game.app.application.playable_slice import PlayableSliceApplication
from game.app.infrastructure.workshop_special_chain_repository import WorkshopSpecialChainMasterDataRepository


class WorkshopSpecialChainSliceTest(unittest.TestCase):
    def test_master_data_loading(self) -> None:
        repo = WorkshopSpecialChainMasterDataRepository(Path("data/master"))
        definitions = repo.load()
        self.assertTrue(any(d.chain_id == "chain.workshop.rank3.tidebreaker_legacy" for d in definitions))

    def test_progression_and_save_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = PlayableSliceApplication(master_root=Path("data/master"), save_file_path=Path(tmp_dir) / "slot.json")
            app.new_game()
            app.workshop_progress_state.level = 3
            app.quest_session.world_flags.add("flag.workshop.story.rank3.order_completed")

            unlock_logs = app.talk_to_npc("npc.astel.workshop_master")
            self.assertTrue(any(l.startswith("special_chain_unlocked:") for l in unlock_logs))

            app.defeated_miniboss_ids.add("miniboss.ch01.tidal_flats.shrine_guardian")
            logs_1 = app.talk_to_npc("npc.astel.workshop_master")
            self.assertTrue(any("special_chain_stage_completed" in l and "stage.defeat_guardian" in l for l in logs_1))

            app.inventory_state.setdefault("items", {})["equip.armor.tidebreaker_harness"] = 1
            logs_2 = app.talk_to_npc("npc.astel.workshop_master")
            self.assertTrue(any("stage.craft_harness" in l for l in logs_2))

            app.equipment_upgrade_levels["equip.armor.tidebreaker_harness"] = 1
            logs_3 = app.talk_to_npc("npc.astel.workshop_master")
            self.assertTrue(any("stage.upgrade_harness" in l for l in logs_3))

            app.quest_session.world_flags.add("flag.workshop.rank.3_blueprint_seen")
            logs_4 = app.talk_to_npc("npc.astel.workshop_master")
            self.assertTrue(any(l.startswith("special_chain_completed:") for l in logs_4))
            self.assertIn("flag.workshop.special_chain.rank3.completed", app.quest_session.world_flags)

            app.save_game()
            resumed = PlayableSliceApplication(master_root=Path("data/master"), save_file_path=Path(tmp_dir) / "slot.json")
            ok, _ = resumed.continue_game()
            self.assertTrue(ok)
            self.assertIn(
                "chain.workshop.rank3.tidebreaker_legacy",
                resumed.workshop_special_chain_state.completed_chain_ids,
            )


if __name__ == "__main__":
    unittest.main()
