from __future__ import annotations

from game.app.application.playable_equipment_workshop_facade import (
    PlayableEquipmentWorkshopFacade,
)
from game.app.application.playable_slice import PlayableSliceApplication
from game.app.cli import run_game_slice as base_cli
from game.app.presentation.equipment_workshop_screen import (
    EquipmentSalvageScreenController,
    EquipmentSalvageScreenViewModel,
    EquipmentUpgradeScreenController,
    EquipmentUpgradeScreenViewModel,
)


def _print_upgrade_view(view: EquipmentUpgradeScreenViewModel) -> None:
    print(
        f"- equipment_upgrade_screen:workshop_level={view.workshop_level}:"
        f"count={len(view.options)}"
    )
    for option in view.options:
        print(
            f"- equipment_upgrade_option:{option.equipment_id}:{option.name}:"
            f"owned={option.owned}:current={option.current_level}:max={option.max_level}:"
            f"next={option.next_level}:required_workshop={option.required_workshop_level}:"
            f"can_upgrade={option.can_upgrade}:reason={option.reason_code}"
        )
        for material in option.required_materials:
            print(
                f"- equipment_upgrade_material:{option.equipment_id}:{material.item_id}:"
                f"{material.name}:owned={material.owned}:required={material.required}:"
                f"sufficient={material.is_sufficient}"
            )
        if option.stat_bonus:
            summary = ",".join(f"{key}+{value}" for key, value in option.stat_bonus)
            print(f"- equipment_upgrade_bonus:{option.equipment_id}:{summary}")
        if option.description:
            print(f"- equipment_upgrade_desc:{option.equipment_id}:{option.description}")


def run_equipment_upgrade_screen(app: PlayableSliceApplication) -> list[str]:
    controller = EquipmentUpgradeScreenController(
        PlayableEquipmentWorkshopFacade(app)
    )
    view = controller.current_view()
    _print_upgrade_view(view)
    if not view.options:
        return ["equipment_upgrade:none"]

    available = [option for option in view.options if option.can_upgrade]
    if not available:
        return ["equipment_upgrade:none_available"]

    choices = [("cancel", "強化しない")]
    choices.extend(
        (
            option.equipment_id,
            f"{option.name} +{option.current_level} → +{option.next_level}",
        )
        for option in available
    )
    selected = base_cli._choose(choices)
    if selected == "cancel":
        return ["equipment_upgrade_cancelled"]
    return list(controller.activate_equipment(selected).logs)


def _print_salvage_view(view: EquipmentSalvageScreenViewModel) -> None:
    print(
        f"- equipment_salvage_screen:workshop_level={view.workshop_level}:"
        f"count={len(view.options)}"
    )
    for option in view.options:
        print(
            f"- equipment_salvage_option:{option.equipment_id}:{option.name}:"
            f"owned={option.owned}:equipped={option.equipped_count}:"
            f"available={option.available}:upgrade={option.upgrade_level}:"
            f"required_workshop={option.required_workshop_level}:"
            f"can_salvage={option.can_salvage}:reason={option.reason_code}"
        )
        for reward in option.returns:
            print(
                f"- equipment_salvage_return:{option.equipment_id}:{reward.item_id}:"
                f"{reward.name}:x{reward.quantity}"
            )
        if option.description:
            print(f"- equipment_salvage_desc:{option.equipment_id}:{option.description}")


def run_equipment_salvage_screen(app: PlayableSliceApplication) -> list[str]:
    controller = EquipmentSalvageScreenController(
        PlayableEquipmentWorkshopFacade(app)
    )
    view = controller.current_view()
    _print_salvage_view(view)
    if not view.options:
        return ["equipment_salvage:none"]

    available = [option for option in view.options if option.can_salvage]
    if not available:
        return ["equipment_salvage:none_available"]

    choices = [("cancel", "分解しない")]
    choices.extend(
        (
            option.equipment_id,
            f"{option.name} 所持={option.owned} 利用可={option.available}",
        )
        for option in available
    )
    selected = base_cli._choose(choices)
    if selected == "cancel":
        return ["equipment_salvage_cancelled"]
    return list(controller.activate_equipment(selected).logs)
