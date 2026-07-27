from __future__ import annotations

from game.app.application.playable_party_menu_facade import PlayablePartyMenuFacade
from game.app.application.playable_slice import PlayableSliceApplication
from game.app.cli import run_game_slice as base_cli
from game.app.cli.screen_action_cli import activate_entry
from game.app.cli.screen_console_renderer import render_route_view
from game.app.presentation.item_equipment_screen import (
    EquipmentScreenController,
    EquipmentScreenViewModel,
    ItemUseScreenController,
    ItemUseScreenViewModel,
)
from game.app.presentation.screen_action_dispatcher import (
    SteamDemoSceneActionDispatcher,
)
from game.app.presentation.screen_router import SteamDemoRouteId


def _print_item_use_view(view: ItemUseScreenViewModel) -> None:
    render_route_view(SteamDemoRouteId.USE_ITEM, view)


def run_item_use_screen(app: PlayableSliceApplication) -> list[str]:
    return run_item_use_controller(
        ItemUseScreenController(PlayablePartyMenuFacade(app))
    )


def run_item_use_controller(
    controller: ItemUseScreenController,
    dispatcher: SteamDemoSceneActionDispatcher | None = None,
) -> list[str]:
    view = controller.current_view()
    _print_item_use_view(view)
    if not view.items:
        return ["usable_item:none"]

    item_choices = [("cancel", "アイテムを使わない")]
    item_choices.extend(
        (item.item_id, f"{item.name} x{item.amount}")
        for item in view.items
        if item.amount > 0
    )
    selected_item = base_cli._choose(item_choices)
    if selected_item == "cancel":
        return ["item_use_cancelled"]

    selected = activate_entry(
        route_id=SteamDemoRouteId.USE_ITEM,
        entry_id=selected_item,
        controller_action=controller.activate_item,
        dispatcher=dispatcher,
    )
    selected_view = selected.view
    _print_item_use_view(selected_view)
    available_targets = [
        target for target in selected_view.targets if target.can_use
    ]
    if not available_targets:
        return [f"item_use_failed:no_valid_target:{selected_item}"]

    target_choices = [("cancel", "対象を選ばない")]
    target_choices.extend(
        (
            target.member.character_id,
            f"{target.member.character_id} "
            f"HP {target.member.current_hp}/{target.member.max_hp} "
            f"SP {target.member.current_sp}/{target.member.max_sp}",
        )
        for target in available_targets
    )
    selected_target = base_cli._choose(target_choices)
    if selected_target == "cancel":
        return ["item_use_cancelled"]
    executed = activate_entry(
        route_id=SteamDemoRouteId.USE_ITEM,
        entry_id=selected_target,
        controller_action=controller.activate_target,
        dispatcher=dispatcher,
    )
    return list(executed.logs)


def _print_equipment_view(view: EquipmentScreenViewModel) -> None:
    render_route_view(SteamDemoRouteId.EQUIPMENT, view)


def run_equipment_screen(app: PlayableSliceApplication) -> list[str]:
    return run_equipment_controller(
        EquipmentScreenController(PlayablePartyMenuFacade(app))
    )


def run_equipment_controller(
    controller: EquipmentScreenController,
    dispatcher: SteamDemoSceneActionDispatcher | None = None,
) -> list[str]:
    view = controller.current_view()
    _print_equipment_view(view)
    if not view.members:
        return ["equip_failed:no_member"]

    member_choices = [("cancel", "装備を変更しない")]
    member_choices.extend(
        (member.character_id, f"{member.character_id} Lv.{member.level}")
        for member in view.members
    )
    selected_member = base_cli._choose(member_choices)
    if selected_member == "cancel":
        return ["equip_cancelled"]

    member_interaction = activate_entry(
        route_id=SteamDemoRouteId.EQUIPMENT,
        entry_id=selected_member,
        controller_action=controller.activate_member,
        dispatcher=dispatcher,
    )
    member_view = member_interaction.view
    _print_equipment_view(member_view)
    slot_choices = [("cancel", "スロットを選ばない")]
    slot_choices.extend(
        (
            slot.slot_type,
            f"{slot.slot_type}: {slot.current_equipment_name or '未装備'}",
        )
        for slot in member_view.slots
    )
    selected_slot = base_cli._choose(slot_choices)
    if selected_slot == "cancel":
        return ["equip_cancelled"]

    slot_interaction = activate_entry(
        route_id=SteamDemoRouteId.EQUIPMENT,
        entry_id=selected_slot,
        controller_action=controller.activate_slot,
        dispatcher=dispatcher,
    )
    slot_view = slot_interaction.view
    _print_equipment_view(slot_view)
    available_options = [
        option for option in slot_view.equipment_options if option.can_equip
    ]
    if not available_options:
        return [f"equip_failed:no_option:{selected_member}:{selected_slot}"]

    equipment_choices = [("cancel", "変更しない")]
    equipment_choices.extend(
        (
            option.equipment_id,
            f"{option.name} 所持={option.owned} 利用可={option.available} "
            f"ATK+{option.atk_bonus} DEF+{option.defense_bonus}",
        )
        for option in available_options
    )
    selected_equipment = base_cli._choose(equipment_choices)
    if selected_equipment == "cancel":
        return ["equip_cancelled"]
    executed = activate_entry(
        route_id=SteamDemoRouteId.EQUIPMENT,
        entry_id=selected_equipment,
        controller_action=controller.activate_equipment,
        dispatcher=dispatcher,
    )
    return list(executed.logs)
