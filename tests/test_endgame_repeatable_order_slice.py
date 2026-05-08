from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from game.app.application.playable_slice import PlayableSliceApplication
from game.app.infrastructure.endgame_repeatable_order_repository import EndgameRepeatableOrderMasterDataRepository


class EndgameRepeatableOrderSliceTest(unittest.TestCase):
    def test_master_data_loading(self) -> None:
        repo = EndgameRepeatableOrderMasterDataRepository(Path("data/master"))
        definitions = repo.load()
        self.assertTrue(any(d.order_id == "order.endgame.tidebreaker_rearm" for d in definitions))

    def test_unlock_progress_complete_reaccept_and_save_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = PlayableSliceApplication(master_root=Path("data/master"), save_file_path=Path(tmp_dir) / "slot.json")
            app.new_game()
            app.workshop_progress_state.level = 3

            locked_logs = app.talk_to_npc("npc.astel.workshop_master")
            self.assertFalse(any("endgame_order_unlocked:" in line for line in locked_logs))

            app.quest_session.world_flags.add("flag.workshop.special_chain.rank3.completed")
            app.defeated_miniboss_ids.add("miniboss.ch01.tidal_flats.shrine_guardian")
            app.inventory_state.setdefault("items", {})["equip.armor.tidebreaker_harness"] = 1
            app.equipment_upgrade_levels["equip.armor.tidebreaker_harness"] = 2
            app.active_set_bonus_keys_by_member = {"char.main.rion": {"set_bonus.tidebreaker.2"}}
            logs = app.talk_to_npc("npc.astel.workshop_master")
            self.assertTrue(any(line.startswith("endgame_order_unlocked:") for line in logs))
            self.assertTrue(any(line.startswith("endgame_order_started:") for line in logs))
            self.assertTrue(any("endgame_order_objective_completed:" in line for line in logs))
            self.assertTrue(any(line.startswith("endgame_order_completed:") for line in logs))
            self.assertTrue(any(line.startswith("endgame_order_reward:") for line in logs))
            reward_before = app.inventory_state["items"].get("item.material.miniboss.guardian_core", 0)

            duplicate_logs = app.talk_to_npc("npc.astel.workshop_master")
            self.assertFalse(any(line.startswith("endgame_order_reward:") for line in duplicate_logs))

            app.travel_to("location.field.tidal_flats")
            app.travel_to("location.town.astel")
            ready_logs = app.talk_to_npc("npc.astel.workshop_master")
            self.assertTrue(any(line.startswith("endgame_order_started:") for line in ready_logs))
            self.assertNotIn("order.endgame.tidebreaker_rearm", app.endgame_order_state.ready_to_reaccept_order_ids)
            self.assertGreaterEqual(app.inventory_state["items"].get("item.material.miniboss.guardian_core", 0), reward_before)

            app.save_game()
            resumed = PlayableSliceApplication(master_root=Path("data/master"), save_file_path=Path(tmp_dir) / "slot.json")
            ok, _ = resumed.continue_game()
            self.assertTrue(ok)
            self.assertIn("order.endgame.tidebreaker_rearm", resumed.endgame_order_state.unlocked_order_ids)
            self.assertIsNotNone(resumed.endgame_order_state.completion_counts.get("order.endgame.tidebreaker_rearm"))


if __name__ == "__main__":
    unittest.main()
