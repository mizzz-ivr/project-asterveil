from __future__ import annotations

from game.app.application.playable_equipment_workshop_facade import (
    PlayableEquipmentWorkshopFacade,
)
from game.app.application.playable_slice import PlayableSliceApplication
from game.app.cli import run_game_slice as base_cli
from game.app.cli.screen_console_renderer import render_route_view
from game.app.presentation.equipment_workshop_screen import (
    EquipmentSalvageScreenController,
    EquipmentSalvageScreenViewModel,
    EquipmentUpgradeScreenController,
    EquipmentUpgradeScreenViewModel,
)
from game.app.presentation.screen_router import SteamDemoRouteId


def _print_upgrade_view(view: EquipmentUpgradeScreenViewModel) -> None:
    render_route_view(SteamDemoRouteId.EQUIPMENT_UPGRADE, view)


def run_equipment_upgrade_screen(app: PlayableSliceApplication) -> list[str]:
    return run_equipment_upgrade_controller(
        EquipmentUpgradeScreenController(PlayableEquipmentWorkshopFacade(app))
    )


def run_equipment_upgrade_controller(
    controller: EquipmentUpgradeScreenController,
) -> list[str]:
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
    render_route_view(SteamDemoRouteId.EQUIPMENT_SALVAGE, view)


def run_equipment_salvage_screen(app: PlayableSliceApplication) -> list[str]:
    return run_equipment_salvage_controller(
        EquipmentSalvageScreenController(PlayableEquipmentWorkshopFacade(app))
    )


def run_equipment_salvage_controller(
    controller: EquipmentSalvageScreenController,
) -> list[str]:
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
