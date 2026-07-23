from __future__ import annotations

from game.app.application.playable_party_menu_facade import PlayablePartyMenuFacade
from game.app.application.playable_slice import PlayableSliceApplication
from game.app.cli import run_game_slice as base_cli
from game.app.presentation.item_equipment_screen import (
    EquipmentScreenController,
    EquipmentScreenMode,
    EquipmentScreenViewModel,
    ItemUseScreenController,
    ItemUseScreenMode,
    ItemUseScreenViewModel,
)


def _print_item_use_view(view: ItemUseScreenViewModel) -> None:
    if view.mode == ItemUseScreenMode.ITEM_LIST:
        print(f"- usable_items:count={len(view.items)}")
        for item in view.items:
            print(
                f"- usable_item:{item.item_id}:{item.name}:amount={item.amount}:"
                f"effect={item.effect_type}:{item.effect_value}:target={item.target_scope}"
            )
            if item.description:
                print(f"- usable_item_desc:{item.item_id}:{item.description}")
        return

    selected_item = view.selected_item
    if selected_item is None:
        return
    print(f"- item_targets:item={selected_item.item_id}:count={len(view.targets)}")
    for target in view.targets:
        member = target.member
        print(
            f"- item_target:{member.character_id}:"
            f"hp={member.current_hp}/{member.max_hp}:sp={member.current_sp}/{member.max_sp}:"
            f"can_use={target.can_use}:reason={target.reason_code}"
        )


def run_item_use_screen(app: PlayableSliceApplication) -> list[str]:
    controller = ItemUseScreenController(PlayablePartyMenuFacade(app))
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

    selected = controller.activate_item(selected_item)
    _print_item_use_view(selected.view)
    available_targets = [target for target in selected.view.targets if target.can_use]
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
    return list(controller.activate_target(selected_target).logs)


def _print_equipment_view(view: EquipmentScreenViewModel) -> None:
    if view.mode == EquipmentScreenMode.MEMBER_LIST:
        print(f"- equipment_members:count={len(view.members)}")
        for member in view.members:
            print(
                f"- equipment_member:{member.character_id}:lv={member.level}:"
                f"hp={member.current_hp}/{member.max_hp}:sp={member.current_sp}/{member.max_sp}:"
                f"atk={member.atk}:def={member.defense}:spd={member.spd}"
            )
        return

    if view.mode == EquipmentScreenMode.SLOT_LIST:
        member_id = view.selected_member.character_id if view.selected_member else "unknown"
        print(f"- equipment_slots:member={member_id}:count={len(view.slots)}")
        for slot in view.slots:
            print(
                f"- equipment_slot:{slot.slot_type}:"
                f"current={slot.current_equipment_id or 'none'}:"
                f"name={slot.current_equipment_name or '未装備'}"
            )
        return

    member_id = view.selected_member.character_id if view.selected_member else "unknown"
    slot_type = view.selected_slot.slot_type if view.selected_slot else "unknown"
    print(
        f"- equipment_options:member={member_id}:slot={slot_type}:"
        f"count={len(view.equipment_options)}"
    )
    for option in view.equipment_options:
        print(
            f"- equipment_option:{option.equipment_id}:{option.name}:"
            f"owned={option.owned}:available={option.available}:current={option.is_current}:"
            f"can_equip={option.can_equip}:upgrade={option.upgrade_level}:"
            f"hp={option.hp_bonus}:sp={option.sp_bonus}:atk={option.atk_bonus}:"
            f"def={option.defense_bonus}:spd={option.spd_bonus}"
        )


def run_equipment_screen(app: PlayableSliceApplication) -> list[str]:
    controller = EquipmentScreenController(PlayablePartyMenuFacade(app))
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

    member_interaction = controller.activate_member(selected_member)
    _print_equipment_view(member_interaction.view)
    slot_choices = [("cancel", "スロットを選ばない")]
    slot_choices.extend(
        (
            slot.slot_type,
            f"{slot.slot_type}: {slot.current_equipment_name or '未装備'}",
        )
        for slot in member_interaction.view.slots
    )
    selected_slot = base_cli._choose(slot_choices)
    if selected_slot == "cancel":
        return ["equip_cancelled"]

    slot_interaction = controller.activate_slot(selected_slot)
    _print_equipment_view(slot_interaction.view)
    available_options = [
        option for option in slot_interaction.view.equipment_options if option.can_equip
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
    return list(controller.activate_equipment(selected_equipment).logs)
