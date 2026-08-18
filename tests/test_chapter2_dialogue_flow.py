from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from game.app.application.playable_interaction_facade import PlayableInteractionFacade
from game.app.application.playable_slice import PlayableSliceApplication
from game.app.infrastructure.dialogue_event_repository import DialogueEventMasterDataRepository
from game.quest.domain.entities import BattleResult, QuestStatus


MASTER_ROOT = Path("data/master")
FOG_KEEPER_ID = "npc.ch02.fog_keeper"
MIST_HARBOR_ID = "location.ch02.mist_harbor"
EXPECTED_FOG_KEEPER_ENTRY_IDS = {
    "dialogue.ch02.fog_keeper.first_trace_offer",
    "dialogue.ch02.fog_keeper.first_trace_progress",
    "dialogue.ch02.fog_keeper.first_trace_ready",
    "dialogue.ch02.fog_keeper.marsh_patrol_offer",
    "dialogue.ch02.fog_keeper.marsh_patrol_progress",
    "dialogue.ch02.fog_keeper.marsh_patrol_ready",
    "dialogue.ch02.fog_keeper.mist_trace_offer",
    "dialogue.ch02.fog_keeper.mist_trace_progress",
    "dialogue.ch02.fog_keeper.echo_patrol_offer",
    "dialogue.ch02.fog_keeper.echo_patrol_progress",
    "dialogue.ch02.fog_keeper.echo_patrol_ready",
    "dialogue.ch02.fog_keeper.boss_offer",
    "dialogue.ch02.fog_keeper.boss_progress",
    "dialogue.ch02.fog_keeper.boss_ready",
    "dialogue.ch02.fog_keeper.chapter_clear",
}


class Chapter2DialogueFlowTest(unittest.TestCase):
    def _build_app(self, tmp_dir: str) -> PlayableSliceApplication:
        def battle_executor(encounter_id: str, party_members=None) -> BattleResult:
            return BattleResult(
                encounter_id=encounter_id,
                player_won=False,
                defeated_enemy_ids=tuple(),
            )

        app = PlayableSliceApplication(
            master_root=MASTER_ROOT,
            save_file_path=Path(tmp_dir) / "slot_01.json",
            battle_executor=battle_executor,
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

    def _set_ready_quest(self, app: PlayableSliceApplication, quest_id: str) -> None:
        state = app.quest_session.quest_service.create_initial_state(quest_id)
        state.status = QuestStatus.READY_TO_COMPLETE
        app.quest_session.quest_states[quest_id] = state
        app.quest_session.world_flags.add(f"flag.quest.accepted:{quest_id}")

    def test_master_loads_all_fog_keeper_chapter2_entries(self) -> None:
        definitions = DialogueEventMasterDataRepository(MASTER_ROOT).load_npc_dialogues()
        fog_keeper = definitions[FOG_KEEPER_ID]

        self.assertEqual(fog_keeper.location_id, MIST_HARBOR_ID)
        self.assertEqual(
            {entry.entry_id for entry in fog_keeper.dialogue_entries},
            EXPECTED_FOG_KEEPER_ENTRY_IDS,
        )

    def test_first_trace_can_be_accepted_and_switches_to_progress_dialogue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._build_app(tmp_dir)
            self._set_completed_quest(app, "quest.ch01.tide_serpent_subjugation")
            app.quest_session.world_flags.add("flag.ch02.access_granted")
            facade = PlayableInteractionFacade(app)

            offer = facade.start_dialogue(FOG_KEEPER_ID)
            self.assertEqual(
                offer.entry_id,
                "dialogue.ch02.fog_keeper.first_trace_offer",
            )
            self.assertEqual(
                {choice.choice_id for choice in offer.choices},
                {"choice.first_trace_accept", "choice.first_trace_later"},
            )

            accepted = facade.select_dialogue_choice(
                offer,
                "choice.first_trace_accept",
            )
            self.assertTrue(accepted.success)
            self.assertTrue(accepted.completed)
            self.assertIn(
                "quest_accepted:quest.ch02.first_trace",
                accepted.logs,
            )
            self.assertEqual(
                app.quest_session.quest_states["quest.ch02.first_trace"].status,
                QuestStatus.IN_PROGRESS,
            )
            self.assertIn(
                "flag.quest.accepted:quest.ch02.first_trace",
                app.quest_session.world_flags,
            )

            progress = facade.start_dialogue(FOG_KEEPER_ID)
            self.assertEqual(
                progress.entry_id,
                "dialogue.ch02.fog_keeper.first_trace_progress",
            )
            self.assertTrue(progress.completed)

    def test_mist_trace_turn_in_handles_shortage_then_auto_completes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._build_app(tmp_dir)
            self._set_completed_quest(app, "quest.ch02.first_trace")
            app.quest_session.world_flags.update(
                {
                    "flag.ch02.access_granted",
                    "flag.ch02.first_trace_complete",
                    "flag.field_event.ch02.mist_trace_collected",
                }
            )
            facade = PlayableInteractionFacade(app)

            offer = facade.start_dialogue(FOG_KEEPER_ID)
            self.assertEqual(
                offer.entry_id,
                "dialogue.ch02.fog_keeper.mist_trace_offer",
            )
            accepted = facade.select_dialogue_choice(
                offer,
                "choice.mist_trace_accept",
            )
            self.assertIn(
                "quest_accepted:quest.ch02.mist_trace_delivery",
                accepted.logs,
            )

            progress = facade.start_dialogue(FOG_KEEPER_ID)
            self.assertEqual(
                progress.entry_id,
                "dialogue.ch02.fog_keeper.mist_trace_progress",
            )
            insufficient = facade.select_dialogue_choice(
                progress,
                "choice.mist_trace_turn_in",
            )
            self.assertIn(
                "turn_in_failed:insufficient_items",
                insufficient.logs,
            )
            self.assertEqual(
                app.quest_session.quest_states["quest.ch02.mist_trace_delivery"].status,
                QuestStatus.IN_PROGRESS,
            )
            self.assertNotIn(
                "flag.ch02.mist_trace_delivered",
                app.quest_session.world_flags,
            )

            app.inventory_state.setdefault("items", {})["item.material.memory_shard"] = 2
            progress = facade.start_dialogue(FOG_KEEPER_ID)
            completed = facade.select_dialogue_choice(
                progress,
                "choice.mist_trace_turn_in",
            )

            self.assertTrue(
                any(log.startswith("turn_in_success:quest.ch02.mist_trace_delivery") for log in completed.logs)
            )
            self.assertEqual(
                app.quest_session.quest_states["quest.ch02.mist_trace_delivery"].status,
                QuestStatus.COMPLETED,
            )
            self.assertIn(
                "flag.ch02.mist_trace_delivered",
                app.quest_session.world_flags,
            )
            self.assertEqual(
                app.inventory_state["items"].get("item.material.memory_shard", 0),
                0,
            )

            next_offer = facade.start_dialogue(FOG_KEEPER_ID)
            self.assertEqual(
                next_offer.entry_id,
                "dialogue.ch02.fog_keeper.echo_patrol_offer",
            )

    def test_boss_report_sets_chapter_clear_and_resolves_epilogue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._build_app(tmp_dir)
            self._set_completed_quest(app, "quest.ch02.echo_patrol")
            self._set_ready_quest(app, "quest.ch02.fog_behemoth_subjugation")
            app.quest_session.world_flags.add("flag.ch02.echoing_bastion_unlocked")
            facade = PlayableInteractionFacade(app)

            ready = facade.start_dialogue(FOG_KEEPER_ID)
            self.assertEqual(
                ready.entry_id,
                "dialogue.ch02.fog_keeper.boss_ready",
            )
            reported = facade.select_dialogue_choice(
                ready,
                "choice.boss_report",
            )

            self.assertTrue(reported.success)
            self.assertEqual(
                app.quest_session.quest_states[
                    "quest.ch02.fog_behemoth_subjugation"
                ].status,
                QuestStatus.COMPLETED,
            )
            self.assertIn("flag.ch02.chapter_clear", app.quest_session.world_flags)

            epilogue = facade.start_dialogue(FOG_KEEPER_ID)
            self.assertEqual(
                epilogue.entry_id,
                "dialogue.ch02.fog_keeper.chapter_clear",
            )
            self.assertTrue(epilogue.completed)

    def test_save_and_continue_preserves_dialogue_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._build_app(tmp_dir)
            self._set_completed_quest(app, "quest.ch01.tide_serpent_subjugation")
            app.quest_session.world_flags.add("flag.ch02.access_granted")
            facade = PlayableInteractionFacade(app)

            offer = facade.start_dialogue(FOG_KEEPER_ID)
            facade.select_dialogue_choice(offer, "choice.first_trace_accept")
            app.save_game()

            resumed = PlayableSliceApplication(
                master_root=MASTER_ROOT,
                save_file_path=Path(tmp_dir) / "slot_01.json",
                battle_executor=lambda encounter_id, party_members=None: BattleResult(
                    encounter_id=encounter_id,
                    player_won=False,
                    defeated_enemy_ids=tuple(),
                ),
            )
            ok, _ = resumed.continue_game()
            self.assertTrue(ok)
            self.assertEqual(resumed.location_state.current_location_id, MIST_HARBOR_ID)

            resumed_dialogue = PlayableInteractionFacade(resumed).start_dialogue(
                FOG_KEEPER_ID
            )
            self.assertEqual(
                resumed_dialogue.entry_id,
                "dialogue.ch02.fog_keeper.first_trace_progress",
            )


if __name__ == "__main__":
    unittest.main()
