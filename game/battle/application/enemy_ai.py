from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from game.battle.domain.entities import ActionCommand, CombatantState, SkillDefinition, Team
from game.battle.domain.services import BattleState


@dataclass(frozen=True)
class EnemyAiRule:
    rule_id: str
    priority: int
    action_type: str
    target_rule: str
    skill_id: str | None = None
    conditions: tuple[dict[str, Any], ...] = tuple()


@dataclass(frozen=True)
class EnemyAiProfile:
    ai_profile_id: str
    action_rules: tuple[EnemyAiRule, ...]


class EnemyAiService:
    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()

    def choose_command(
        self,
        state: BattleState,
        actor: CombatantState,
        profile: EnemyAiProfile | None,
        skills: dict[str, SkillDefinition],
    ) -> ActionCommand:
        if actor.team != Team.ENEMY:
            raise ValueError("EnemyAiService は敵ユニット専用です")
        fallback = self._fallback_attack(state, actor, reason="no_profile")
        if profile is None:
            return fallback

        candidates = self._sorted_rules(profile.action_rules)
        for rule in candidates:
            command = self._build_rule_command(state, actor, rule, skills)
            if command is None:
                continue
            return command
        return self._fallback_attack(state, actor, reason="no_rule_matched")

    def _build_rule_command(
        self,
        state: BattleState,
        actor: CombatantState,
        rule: EnemyAiRule,
        skills: dict[str, SkillDefinition],
    ) -> ActionCommand | None:
        if not self._conditions_met(state, actor, rule.conditions):
            return None
        if rule.action_type == "skill":
            if not rule.skill_id or rule.skill_id not in skills:
                return None
            skill = skills[rule.skill_id]
            if actor.sp < skill.sp_cost:
                return None
            target_id = self._resolve_target_id(state, actor, rule.target_rule, skill.target_scope)
            if target_id is ...:
                return None
            return ActionCommand(
                actor_id=actor.unit_id,
                action_type="skill",
                skill_id=rule.skill_id,
                target_id=target_id,
                logs=(f"enemy_ai:selected_rule={rule.rule_id}:target_rule={rule.target_rule}",),
            )
        if rule.action_type == "normal_attack":
            target_id = self._resolve_target_id(state, actor, rule.target_rule, "single_enemy")
            if target_id in (None, ...):
                return None
            return ActionCommand(
                actor_id=actor.unit_id,
                action_type="attack",
                target_id=target_id,
                logs=(f"enemy_ai:selected_rule={rule.rule_id}:target_rule={rule.target_rule}",),
            )
        return None

    def _sorted_rules(self, rules: tuple[EnemyAiRule, ...]) -> list[EnemyAiRule]:
        ordered = list(enumerate(rules))
        ordered.sort(key=lambda pair: (-pair[1].priority, pair[0]))
        return [rule for _, rule in ordered]

    def _conditions_met(
        self,
        state: BattleState,
        actor: CombatantState,
        conditions: tuple[dict[str, Any], ...],
    ) -> bool:
        for condition in conditions:
            condition_type = str(condition.get("type", ""))
            if condition_type == "self_hp_below_ratio":
                threshold = float(condition.get("value", 1.0))
                if actor.hp / max(1, actor.max_hp) >= threshold:
                    return False
                continue
            if condition_type == "self_has_effect":
                effect_id = str(condition.get("effect_id", ""))
                if not any(effect.effect_id == effect_id for effect in actor.active_effects):
                    return False
                continue
            if condition_type == "self_has_no_effect":
                effect_id = str(condition.get("effect_id", ""))
                if any(effect.effect_id == effect_id for effect in actor.active_effects):
                    return False
                continue
            if condition_type == "enemy_has_no_effect":
                effect_id = str(condition.get("effect_id", ""))
                living = self._living_enemies_of(state, actor)
                if not any(all(effect.effect_id != effect_id for effect in target.active_effects) for target in living):
                    return False
                continue
            if condition_type == "ally_needs_heal":
                ratio = float(condition.get("value", 1.0))
                allies = self._living_allies_of(state, actor)
                if not any(unit.hp / max(1, unit.max_hp) < ratio for unit in allies):
                    return False
                continue
            if condition_type == "ally_count_alive_at_least":
                need = int(condition.get("value", 1))
                if len(self._living_allies_of(state, actor)) < need:
                    return False
                continue
            return False
        return True

    def _resolve_target_id(
        self,
        state: BattleState,
        actor: CombatantState,
        target_rule: str,
        target_scope: str,
    ) -> str | None | Ellipsis:
        if target_scope in ("all_enemies", "all_allies"):
            return None
        if target_rule == "self":
            return actor.unit_id
        if target_rule == "random_enemy":
            candidates = self._living_enemies_of(state, actor)
            return self._rng.choice(candidates).unit_id if candidates else ...
        if target_rule == "lowest_hp_enemy":
            candidates = self._living_enemies_of(state, actor)
            if not candidates:
                return ...
            candidates.sort(key=lambda unit: (unit.hp / max(1, unit.max_hp), unit.hp, unit.unit_id))
            return candidates[0].unit_id
        if target_rule == "lowest_hp_ally":
            candidates = self._living_allies_of(state, actor)
            if not candidates:
                return ...
            candidates.sort(key=lambda unit: (unit.hp / max(1, unit.max_hp), unit.hp, unit.unit_id))
            return candidates[0].unit_id
        return ...

    def _fallback_attack(self, state: BattleState, actor: CombatantState, reason: str) -> ActionCommand:
        enemies = self._living_enemies_of(state, actor)
        if not enemies:
            raise ValueError("敵AIに攻撃対象が存在しません")
        enemies.sort(key=lambda unit: unit.unit_id)
        return ActionCommand(
            actor_id=actor.unit_id,
            action_type="attack",
            target_id=enemies[0].unit_id,
            logs=(f"enemy_ai:fallback=normal_attack:reason={reason}:target_rule=random_enemy",),
        )

    def _living_enemies_of(self, state: BattleState, actor: CombatantState) -> list[CombatantState]:
        target_team = Team.PLAYER if actor.team == Team.ENEMY else Team.ENEMY
        return [unit for unit in state.combatants.values() if unit.team == target_team and unit.alive]

    def _living_allies_of(self, state: BattleState, actor: CombatantState) -> list[CombatantState]:
        return [unit for unit in state.combatants.values() if unit.team == actor.team and unit.alive]
