from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from game.app.application.equipment_service import VALID_SLOTS

if TYPE_CHECKING:
    from game.app.application.playable_slice import PlayableSliceApplication
    from game.save.domain.entities import PartyMemberState


@dataclass(frozen=True)
class PartyMemberSummary:
    character_id: str
    level: int
    current_hp: int
    max_hp: int
    current_sp: int
    max_sp: int
    atk: int
    defense: int
    spd: int
    alive: bool
    active_effect_ids: tuple[str, ...]
    equipped: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class UsableItemSummary:
    item_id: str
    name: str
    description: str
    amount: int
    target_scope: str
    effect_type: str
    effect_value: int
    remove_effect_ids: tuple[str, ...]


@dataclass(frozen=True)
class ItemTargetAvailability:
    member: PartyMemberSummary
    can_use: bool
    reason_code: str


@dataclass(frozen=True)
class ItemUseExecutionResult:
    success: bool
    code: str
    item_id: str
    target_character_id: str
    logs: tuple[str, ...] = tuple()


@dataclass(frozen=True)
class EquipmentSlotSummary:
    slot_type: str
    current_equipment_id: str | None
    current_equipment_name: str | None


@dataclass(frozen=True)
class EquipmentOptionSummary:
    equipment_id: str
    name: str
    description: str
    slot_type: str
    owned: int
    equipped_count: int
    available: int
    is_current: bool
    can_equip: bool
    upgrade_level: int
    hp_bonus: int
    sp_bonus: int
    atk_bonus: int
    defense_bonus: int
    spd_bonus: int
    passive_descriptions: tuple[str, ...]


@dataclass(frozen=True)
class EquipmentExecutionResult:
    success: bool
    code: str
    character_id: str
    slot_type: str
    equipment_id: str
    logs: tuple[str, ...] = tuple()


class PlayablePartyMenuFacade:
    """アイテム使用と装備変更を型付き契約で公開するApplication境界。"""

    def __init__(self, playable: PlayableSliceApplication) -> None:
        self._playable = playable

    def list_party_members(self) -> tuple[PartyMemberSummary, ...]:
        return tuple(self._member_summary(member) for member in self._playable.party_members)

    def list_usable_items(self) -> tuple[UsableItemSummary, ...]:
        items: list[UsableItemSummary] = []
        inventory_items = self._playable.inventory_state.get("items", {})
        for item_id in self._playable.usable_item_ids():
            definition = self._playable._item_definitions.get(item_id)
            if definition is None:
                continue
            items.append(
                UsableItemSummary(
                    item_id=item_id,
                    name=str(definition.get("name", item_id)),
                    description=str(definition.get("description", "")),
                    amount=max(0, int(inventory_items.get(item_id, 0))),
                    target_scope=str(definition.get("target_scope", "")),
                    effect_type=str(definition.get("effect_type", "")),
                    effect_value=int(definition.get("effect_value", 0)),
                    remove_effect_ids=tuple(
                        str(effect_id)
                        for effect_id in definition.get("remove_effect_ids", [])
                    ),
                )
            )
        return tuple(items)

    def list_item_targets(self, item_id: str) -> tuple[ItemTargetAvailability, ...]:
        item = next((entry for entry in self.list_usable_items() if entry.item_id == item_id), None)
        if item is None:
            return tuple()
        targets: list[ItemTargetAvailability] = []
        for member in self._playable.party_members:
            can_use, reason_code = self._can_apply_item(item, member)
            targets.append(
                ItemTargetAvailability(
                    member=self._member_summary(member),
                    can_use=can_use,
                    reason_code=reason_code,
                )
            )
        return tuple(targets)

    def use_item(self, item_id: str, target_character_id: str) -> ItemUseExecutionResult:
        item = next((entry for entry in self.list_usable_items() if entry.item_id == item_id), None)
        if item is None:
            return ItemUseExecutionResult(
                success=False,
                code="item_not_available",
                item_id=item_id,
                target_character_id=target_character_id,
                logs=(f"item_use_rejected:item_not_available:{item_id}",),
            )
        target = next(
            (member for member in self._playable.party_members if member.character_id == target_character_id),
            None,
        )
        if target is None:
            return ItemUseExecutionResult(
                success=False,
                code="target_not_available",
                item_id=item_id,
                target_character_id=target_character_id,
                logs=(f"item_use_rejected:target_not_available:{target_character_id}",),
            )
        can_use, reason_code = self._can_apply_item(item, target)
        if not can_use:
            return ItemUseExecutionResult(
                success=False,
                code=reason_code,
                item_id=item_id,
                target_character_id=target_character_id,
                logs=(f"item_use_rejected:{reason_code}:{item_id}:{target_character_id}",),
            )
        logs = tuple(self._playable.use_item(item_id, target_character_id))
        success = any(line.startswith("item_used:") for line in logs)
        code = "used" if success else self._failure_code(logs, "item_use_failed")
        return ItemUseExecutionResult(
            success=success,
            code=code,
            item_id=item_id,
            target_character_id=target_character_id,
            logs=logs,
        )

    def list_equipment_slots(self, character_id: str) -> tuple[EquipmentSlotSummary, ...]:
        member = self._member(character_id)
        if member is None:
            return tuple()
        slots: list[EquipmentSlotSummary] = []
        for slot_type in VALID_SLOTS:
            equipment_id = member.equipped.get(slot_type)
            definition = self._playable._equipment_definitions.get(equipment_id) if equipment_id else None
            slots.append(
                EquipmentSlotSummary(
                    slot_type=slot_type,
                    current_equipment_id=equipment_id,
                    current_equipment_name=definition.name if definition else None,
                )
            )
        return tuple(slots)

    def list_equipment_options(
        self,
        character_id: str,
        slot_type: str,
    ) -> tuple[EquipmentOptionSummary, ...]:
        member = self._member(character_id)
        if member is None or slot_type not in VALID_SLOTS:
            return tuple()
        inventory_items = self._playable.inventory_state.get("items", {})
        options: list[EquipmentOptionSummary] = []
        for equipment_id, definition in sorted(self._playable._equipment_definitions.items()):
            if definition.slot_type != slot_type:
                continue
            owned = max(0, int(inventory_items.get(equipment_id, 0)))
            equipped_count = sum(
                1
                for party_member in self._playable.party_members
                for equipped_id in party_member.equipped.values()
                if equipped_id == equipment_id
            )
            available = max(0, owned - equipped_count)
            is_current = member.equipped.get(slot_type) == equipment_id
            bonus = self._playable._equipment_service.compute_bonuses({slot_type: equipment_id})
            upgrade_level = self._playable._equipment_upgrade_service.current_level(
                equipment_id,
                self._playable.equipment_upgrade_levels,
            )
            options.append(
                EquipmentOptionSummary(
                    equipment_id=equipment_id,
                    name=definition.name,
                    description=definition.description,
                    slot_type=slot_type,
                    owned=owned,
                    equipped_count=equipped_count,
                    available=available,
                    is_current=is_current,
                    can_equip=is_current or available > 0,
                    upgrade_level=upgrade_level,
                    hp_bonus=int(bonus.get("hp", 0)),
                    sp_bonus=int(bonus.get("sp", 0)),
                    atk_bonus=int(bonus.get("atk", 0)),
                    defense_bonus=int(bonus.get("defense", 0)),
                    spd_bonus=int(bonus.get("spd", 0)),
                    passive_descriptions=tuple(
                        passive.description or passive.passive_id
                        for passive in definition.passive_effects
                    ),
                )
            )
        return tuple(options)

    def equip_item(
        self,
        character_id: str,
        slot_type: str,
        equipment_id: str,
    ) -> EquipmentExecutionResult:
        member = self._member(character_id)
        if member is None:
            return self._equipment_rejection(
                "member_not_available",
                character_id,
                slot_type,
                equipment_id,
            )
        if slot_type not in VALID_SLOTS:
            return self._equipment_rejection(
                "invalid_slot",
                character_id,
                slot_type,
                equipment_id,
            )
        option = next(
            (
                entry
                for entry in self.list_equipment_options(character_id, slot_type)
                if entry.equipment_id == equipment_id
            ),
            None,
        )
        if option is None:
            return self._equipment_rejection(
                "equipment_not_available",
                character_id,
                slot_type,
                equipment_id,
            )
        if not option.can_equip:
            return self._equipment_rejection(
                "insufficient_stock",
                character_id,
                slot_type,
                equipment_id,
            )
        logs = tuple(self._playable.equip_item(character_id, slot_type, equipment_id))
        success = any(line.startswith("equip_succeeded:") for line in logs)
        code = "equipped" if success else self._failure_code(logs, "equip_failed")
        return EquipmentExecutionResult(
            success=success,
            code=code,
            character_id=character_id,
            slot_type=slot_type,
            equipment_id=equipment_id,
            logs=logs,
        )

    def _member_summary(self, member: PartyMemberState) -> PartyMemberSummary:
        final = self._playable._equipment_service.resolve_final_stats(member)
        return PartyMemberSummary(
            character_id=member.character_id,
            level=member.level,
            current_hp=final["current_hp"],
            max_hp=final["max_hp"],
            current_sp=final["current_sp"],
            max_sp=final["max_sp"],
            atk=final["atk"],
            defense=final["defense"],
            spd=final["spd"],
            alive=member.alive,
            active_effect_ids=tuple(effect.effect_id for effect in member.active_effects),
            equipped=tuple(sorted(member.equipped.items())),
        )

    def _member(self, character_id: str) -> PartyMemberState | None:
        return next(
            (member for member in self._playable.party_members if member.character_id == character_id),
            None,
        )

    def _can_apply_item(
        self,
        item: UsableItemSummary,
        member: PartyMemberState,
    ) -> tuple[bool, str]:
        if item.amount <= 0:
            return False, "no_stock"
        if item.target_scope not in {"single_ally", "self"}:
            return False, "unsupported_target_scope"
        if item.effect_type == "recover_hp":
            return (
                (True, "ok")
                if member.current_hp < member.max_hp
                else (False, "hp_full")
            )
        if item.effect_type == "recover_sp":
            return (
                (True, "ok")
                if member.current_sp < member.max_sp
                else (False, "sp_full")
            )
        if item.effect_type == "cure_effect":
            removable = {
                effect_id
                for effect_id in item.remove_effect_ids
                if self._playable._status_effect_definitions.get(effect_id, {}).get(
                    "removable_by_item",
                    False,
                )
            }
            return (
                (True, "ok")
                if any(effect.effect_id in removable for effect in member.active_effects)
                else (False, "no_removable_effect")
            )
        return False, "unsupported_effect"

    @staticmethod
    def _failure_code(logs: tuple[str, ...], default: str) -> str:
        if not logs:
            return default
        parts = logs[0].split(":")
        return parts[1] if len(parts) > 1 else default

    @staticmethod
    def _equipment_rejection(
        code: str,
        character_id: str,
        slot_type: str,
        equipment_id: str,
    ) -> EquipmentExecutionResult:
        return EquipmentExecutionResult(
            success=False,
            code=code,
            character_id=character_id,
            slot_type=slot_type,
            equipment_id=equipment_id,
            logs=(
                f"equip_rejected:{code}:{character_id}:{slot_type}:{equipment_id}",
            ),
        )
