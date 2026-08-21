from __future__ import annotations

import random
import unittest
from pathlib import Path

from game.battle.application.enemy_ai import EnemyAiService
from game.battle.application.session import BattleSession
from game.battle.domain.services import execute_turn
from game.battle.infrastructure.master_data_repository import MasterDataRepository


MASTER_ROOT = Path("data/master")
ENCOUNTER_ID = "encounter.ch02.fog_behemoth_boss"
BOSS_ENEMY_ID = "enemy.ch02.fog_behemoth"
PHASE2_ID = "phase.fog_behemoth.pressure_storm"
CHARGE_SKILL_ID = "skill.enemy.fog_pressure_charge"
MAELSTROM_SKILL_ID = "skill.enemy.fog_maelstrom"
FOG_PRESSURE_EFFECT_ID = "effect.buff.fog_pressure"


class Chapter2BossPhaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = MasterDataRepository(MASTER_ROOT)
        self.skills = self.repo.load_skills()
        self.effects = self.repo.load_status_effects()
        self.ai_profiles = self.repo.load_enemy_ai_profiles()
        self.ai_bindings = self.repo.load_enemy_ai_bindings()
        self.boss_defs = self.repo.load_boss_encounters()
        self.player = self.repo.load_character("char.main.rion")

    def _boss_session(self) -> tuple[BattleSession, object]:
        enemies, runtime_enemy_map = self.repo.build_enemy_party(ENCOUNTER_ID)
        session = BattleSession.create(
            [self.player],
            enemies,
            self.skills,
            self.effects,
            enemy_ai_profiles=self.ai_profiles,
            enemy_ai_by_enemy_id=self.ai_bindings,
            runtime_enemy_map=runtime_enemy_map,
            enemy_ai_service=EnemyAiService(random.Random(0)),
            encounter_id=ENCOUNTER_ID,
            boss_encounters=self.boss_defs,
        )
        session.bind_unit_skills(
            {
                self.player.id: self.player.skill_ids,
                **{enemy.id: enemy.skill_ids for enemy in enemies},
            }
        )
        boss = next(
            unit
            for unit in session.state.combatants.values()
            if runtime_enemy_map.get(unit.unit_id) == BOSS_ENEMY_ID
        )
        return session, boss

    def test_master_defines_fog_behemoth_phase2_and_telegraphed_skills(self) -> None:
        definition = self.boss_defs[ENCOUNTER_ID]
        self.assertEqual(definition.boss_enemy_id, BOSS_ENEMY_ID)
        self.assertEqual(len(definition.phases), 2)

        phase2 = definition.phases[1]
        self.assertEqual(phase2.phase_id, PHASE2_ID)
        self.assertEqual(phase2.enter_condition.condition_type, "hp_ratio_below")
        self.assertEqual(phase2.enter_condition.value, 0.6)
        self.assertEqual(phase2.ai_profile_id, "enemy_ai.fog_behemoth.phase2")
        self.assertTrue(
            any(
                event.event_type == "show_message"
                and event.message
                and "大技に備えろ" in event.message
                for event in phase2.on_enter_events
            )
        )

        enemy = self.repo.load_enemy(BOSS_ENEMY_ID)
        self.assertIn(CHARGE_SKILL_ID, enemy.skill_ids)
        self.assertIn(MAELSTROM_SKILL_ID, enemy.skill_ids)

        charge = self.skills[CHARGE_SKILL_ID]
        self.assertEqual(charge.effect_kind, "apply_effect")
        self.assertEqual(charge.target_scope, "single_ally")
        self.assertIn(FOG_PRESSURE_EFFECT_ID, charge.apply_effect_ids)

        maelstrom = self.skills[MAELSTROM_SKILL_ID]
        self.assertEqual(maelstrom.effect_kind, "damage")
        self.assertEqual(maelstrom.target_scope, "all_enemies")
        self.assertEqual(maelstrom.power, 1.35)

        fog_pressure = self.effects[FOG_PRESSURE_EFFECT_ID]
        self.assertEqual(fog_pressure.target_stat, "atk")
        self.assertEqual(fog_pressure.magnitude, 0.2)
        self.assertEqual(fog_pressure.duration_turns, 2)

    def test_phase2_starts_at_sixty_percent_and_uses_charge_then_maelstrom(self) -> None:
        session, boss = self._boss_session()

        boss.hp = int(boss.max_hp * 0.61)
        before_threshold = session.default_command_factory(session.state, boss)
        self.assertEqual(before_threshold.skill_id, "skill.enemy.fog_crush")
        self.assertFalse(any("boss_phase_transition" in log for log in before_threshold.logs))

        boss.hp = int(boss.max_hp * 0.60)
        charge_turn = execute_turn(
            session.state,
            boss.unit_id,
            session.default_command_factory,
            session.skills,
            session.effect_definitions,
        )
        self.assertTrue(charge_turn.acted)
        self.assertEqual(charge_turn.summary.skill_id, CHARGE_SKILL_ID)
        self.assertTrue(
            any(
                f"boss_phase_transition:{boss.unit_id}:" in log and f"->{PHASE2_ID}" in log
                for log in charge_turn.logs
            )
        )
        self.assertTrue(any("boss_phase_message" in log and "大技に備えろ" in log for log in charge_turn.logs))
        self.assertTrue(any("selected_rule=rule.fog_behemoth.phase2.charge" in log for log in charge_turn.logs))
        self.assertTrue(
            any(
                effect.effect_id == FOG_PRESSURE_EFFECT_ID and effect.remaining_turns == 1
                for effect in boss.active_effects
            )
        )

        player_hp_before = session.state.combatants[self.player.id].hp
        maelstrom_turn = execute_turn(
            session.state,
            boss.unit_id,
            session.default_command_factory,
            session.skills,
            session.effect_definitions,
        )
        self.assertEqual(maelstrom_turn.summary.skill_id, MAELSTROM_SKILL_ID)
        self.assertTrue(any("selected_rule=rule.fog_behemoth.phase2.maelstrom" in log for log in maelstrom_turn.logs))
        self.assertFalse(any("boss_phase_transition" in log for log in maelstrom_turn.logs))
        self.assertTrue(any(f"effect_expired:{boss.unit_id}:{FOG_PRESSURE_EFFECT_ID}" in log for log in maelstrom_turn.logs))
        self.assertFalse(any(effect.effect_id == FOG_PRESSURE_EFFECT_ID for effect in boss.active_effects))
        self.assertLess(session.state.combatants[self.player.id].hp, player_hp_before)

        next_cycle = session.default_command_factory(session.state, boss)
        self.assertEqual(next_cycle.skill_id, CHARGE_SKILL_ID)
        self.assertTrue(any("selected_rule=rule.fog_behemoth.phase2.charge" in log for log in next_cycle.logs))
        self.assertFalse(any("boss_phase_transition" in log for log in next_cycle.logs))


if __name__ == "__main__":
    unittest.main()
