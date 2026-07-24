from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from game.app.application.playable_slice import PlayableSliceApplication


@dataclass(frozen=True)
class MaterialRequirementSummary:
    item_id: str
    name: str
    owned: int
    required: int
    is_sufficient: bool


@dataclass(frozen=True)
class UpgradeOptionSummary:
    equipment_id: str
    name: str
    description: str
    owned: int
    current_level: int
    max_level: int
    next_level: int | None
    required_workshop_level: int | None
    workshop_level: int
    can_upgrade: bool
    reason_code: str
    required_materials: tuple[MaterialRequirementSummary, ...]
    stat_bonus: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class UpgradeExecutionResult:
    success: bool
    code: str
    equipment_id: str
    logs: tuple[str, ...] = tuple()


@dataclass(frozen=True)
class SalvageReturnSummary:
    item_id: str
    name: str
    quantity: int


@dataclass(frozen=True)
class SalvageOptionSummary:
    equipment_id: str
    name: str
    description: str
    tags: tuple[str, ...]
    owned: int
    equipped_count: int
    available: int
    upgrade_level: int
    required_workshop_level: int
    workshop_level: int
    can_salvage: bool
    reason_code: str
    returns: tuple[SalvageReturnSummary, ...]


@dataclass(frozen=True)
class SalvageExecutionResult:
    success: bool
    code: str
    equipment_id: str
    logs: tuple[str, ...] = tuple()


class PlayableEquipmentWorkshopFacade:
    """装備強化・分解を型付き契約で公開するApplication境界。"""

    def __init__(self, playable: PlayableSliceApplication) -> None:
        self._playable = playable

    @property
    def workshop_level(self) -> int:
        return self._playable.workshop_progress_state.level

    def list_upgrade_options(self) -> tuple[UpgradeOptionSummary, ...]:
        inventory_items = self._playable.inventory_state.get("items", {})
        options: list[UpgradeOptionSummary] = []
        for equipment_id, definition in sorted(
            self._playable._equipment_upgrade_definitions.items()
        ):
            if not definition.upgrade_enabled:
                continue
            owned = max(0, int(inventory_items.get(equipment_id, 0)))
            if owned <= 0:
                continue
            evaluation = self._playable._equipment_upgrade_service.evaluate_upgrade(
                equipment_id=equipment_id,
                equipment_upgrade_levels=self._playable.equipment_upgrade_levels,
                inventory_items=inventory_items,
                workshop_level=self.workshop_level,
            )
            next_level = evaluation.next_level
            materials = tuple(
                MaterialRequirementSummary(
                    item_id=requirement.item_id,
                    name=self._item_name(requirement.item_id),
                    owned=max(0, int(inventory_items.get(requirement.item_id, 0))),
                    required=requirement.quantity,
                    is_sufficient=int(inventory_items.get(requirement.item_id, 0))
                    >= requirement.quantity,
                )
                for requirement in (next_level.required_items if next_level else tuple())
            )
            equipment_definition = self._playable._equipment_definitions.get(equipment_id)
            options.append(
                UpgradeOptionSummary(
                    equipment_id=equipment_id,
                    name=(
                        equipment_definition.name
                        if equipment_definition is not None
                        else equipment_id
                    ),
                    description=(
                        next_level.description
                        if next_level is not None and next_level.description
                        else (
                            equipment_definition.description
                            if equipment_definition is not None
                            else ""
                        )
                    ),
                    owned=owned,
                    current_level=evaluation.current_level,
                    max_level=evaluation.max_level,
                    next_level=(
                        next_level.upgrade_level if next_level is not None else None
                    ),
                    required_workshop_level=(
                        next_level.required_workshop_level
                        if next_level is not None
                        else None
                    ),
                    workshop_level=self.workshop_level,
                    can_upgrade=evaluation.can_upgrade,
                    reason_code=evaluation.code,
                    required_materials=materials,
                    stat_bonus=tuple(
                        sorted(
                            (str(key), int(value))
                            for key, value in (
                                next_level.stat_bonus.items()
                                if next_level is not None
                                else []
                            )
                        )
                    ),
                )
            )
        return tuple(options)

    def upgrade_equipment(self, equipment_id: str) -> UpgradeExecutionResult:
        option = next(
            (
                entry
                for entry in self.list_upgrade_options()
                if entry.equipment_id == equipment_id
            ),
            None,
        )
        if option is None:
            return UpgradeExecutionResult(
                success=False,
                code="equipment_not_available",
                equipment_id=equipment_id,
                logs=(
                    f"equipment_upgrade_rejected:equipment_not_available:{equipment_id}",
                ),
            )
        if not option.can_upgrade:
            return UpgradeExecutionResult(
                success=False,
                code=option.reason_code,
                equipment_id=equipment_id,
                logs=(
                    f"equipment_upgrade_rejected:{option.reason_code}:{equipment_id}",
                ),
            )
        logs = tuple(self._playable.upgrade_equipment(equipment_id))
        success = any(
            line.startswith("equipment_upgrade_success:") for line in logs
        )
        return UpgradeExecutionResult(
            success=success,
            code="upgraded" if success else self._failure_code(logs, "upgrade_failed"),
            equipment_id=equipment_id,
            logs=logs,
        )

    def list_salvage_options(self) -> tuple[SalvageOptionSummary, ...]:
        inventory_items = self._playable.inventory_state.get("items", {})
        equipped_items = tuple(
            equipment_id
            for member in self._playable.party_members
            for equipment_id in member.equipped.values()
            if equipment_id
        )
        options: list[SalvageOptionSummary] = []
        for equipment_id, definition in sorted(
            self._playable._equipment_salvage_definitions.items()
        ):
            if not definition.salvage_enabled:
                continue
            owned = max(0, int(inventory_items.get(equipment_id, 0)))
            if owned <= 0:
                continue
            equipped_count = sum(
                1 for equipped_id in equipped_items if equipped_id == equipment_id
            )
            upgrade_level = self._playable._equipment_upgrade_service.current_level(
                equipment_id,
                self._playable.equipment_upgrade_levels,
            )
            evaluation = self._playable._equipment_salvage_service.evaluate_salvage(
                equipment_id=equipment_id,
                inventory_items=inventory_items,
                workshop_level=self.workshop_level,
                equipped_items=equipped_items,
                upgrade_level=upgrade_level,
            )
            equipment_definition = self._playable._equipment_definitions.get(equipment_id)
            options.append(
                SalvageOptionSummary(
                    equipment_id=equipment_id,
                    name=(
                        equipment_definition.name
                        if equipment_definition is not None
                        else equipment_id
                    ),
                    description=definition.description,
                    tags=definition.salvage_tags,
                    owned=owned,
                    equipped_count=equipped_count,
                    available=max(0, owned - equipped_count),
                    upgrade_level=upgrade_level,
                    required_workshop_level=evaluation.required_workshop_level,
                    workshop_level=self.workshop_level,
                    can_salvage=evaluation.can_salvage,
                    reason_code=evaluation.code,
                    returns=tuple(
                        SalvageReturnSummary(
                            item_id=reward.item_id,
                            name=self._item_name(reward.item_id),
                            quantity=reward.quantity,
                        )
                        for reward in evaluation.returns
                    ),
                )
            )
        return tuple(options)

    def salvage_equipment(self, equipment_id: str) -> SalvageExecutionResult:
        option = next(
            (
                entry
                for entry in self.list_salvage_options()
                if entry.equipment_id == equipment_id
            ),
            None,
        )
        if option is None:
            return SalvageExecutionResult(
                success=False,
                code="equipment_not_available",
                equipment_id=equipment_id,
                logs=(
                    f"equipment_salvage_rejected:equipment_not_available:{equipment_id}",
                ),
            )
        if not option.can_salvage:
            return SalvageExecutionResult(
                success=False,
                code=option.reason_code,
                equipment_id=equipment_id,
                logs=(
                    f"equipment_salvage_rejected:{option.reason_code}:{equipment_id}",
                ),
            )
        logs = tuple(self._playable.salvage_equipment(equipment_id))
        success = any(
            line.startswith("equipment_salvage_success:") for line in logs
        )
        return SalvageExecutionResult(
            success=success,
            code="salvaged" if success else self._failure_code(logs, "salvage_failed"),
            equipment_id=equipment_id,
            logs=logs,
        )

    def _item_name(self, item_id: str) -> str:
        definition = self._playable._item_definitions.get(item_id)
        if definition is None:
            return item_id
        return str(definition.get("name", item_id))

    @staticmethod
    def _failure_code(logs: tuple[str, ...], default: str) -> str:
        if not logs:
            return default
        parts = logs[0].split(":")
        return parts[1] if len(parts) > 1 else default
