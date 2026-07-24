from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from game.app.application.equipment_service import VALID_SLOTS
from game.app.application.playable_party_menu_facade import (
    EquipmentOptionSummary,
    EquipmentSlotSummary,
    ItemTargetAvailability,
    PartyMemberSummary,
    PlayablePartyMenuFacade,
    UsableItemSummary,
)
from game.app.presentation.input_actions import MenuInputAction
from game.app.presentation.menu_view_model import (
    MenuItemViewModel,
    MenuNavigationService,
    MenuSelectionState,
)


class ItemUseScreenMode(str, Enum):
    ITEM_LIST = "item_list"
    TARGET_LIST = "target_list"


@dataclass(frozen=True)
class ItemUseScreenViewModel:
    title: str
    mode: ItemUseScreenMode
    items: tuple[UsableItemSummary, ...]
    selected_item: UsableItemSummary | None
    targets: tuple[ItemTargetAvailability, ...]
    selection: MenuSelectionState


@dataclass(frozen=True)
class ItemUseScreenInteraction:
    view: ItemUseScreenViewModel
    logs: tuple[str, ...] = tuple()
    cancel_requested: bool = False
    rejection_reason: str | None = None


class ItemUseScreenController:
    def __init__(
        self,
        facade: PlayablePartyMenuFacade,
        *,
        navigation: MenuNavigationService | None = None,
    ) -> None:
        self._facade = facade
        self._navigation = navigation or MenuNavigationService()
        self._selected_item_id: str | None = None
        self._selection = MenuSelectionState(selected_index=None)

    def current_view(self) -> ItemUseScreenViewModel:
        if self._selected_item_id is None:
            items = self._facade.list_usable_items()
            selection = self._navigation.initial_selection(
                self._item_menu_items(items),
                self._selection.selected_index or 0,
            )
            self._selection = selection
            return ItemUseScreenViewModel(
                title="アイテム使用",
                mode=ItemUseScreenMode.ITEM_LIST,
                items=items,
                selected_item=None,
                targets=tuple(),
                selection=selection,
            )

        items = self._facade.list_usable_items()
        selected_item = next(
            (item for item in items if item.item_id == self._selected_item_id),
            None,
        )
        if selected_item is None:
            self._selected_item_id = None
            self._selection = MenuSelectionState(selected_index=None)
            return self.current_view()
        targets = self._facade.list_item_targets(selected_item.item_id)
        selection = self._navigation.initial_selection(
            self._target_menu_items(targets),
            self._selection.selected_index or 0,
        )
        self._selection = selection
        return ItemUseScreenViewModel(
            title=f"{selected_item.name}の使用対象",
            mode=ItemUseScreenMode.TARGET_LIST,
            items=tuple(),
            selected_item=selected_item,
            targets=targets,
            selection=selection,
        )

    def handle_input(self, action: MenuInputAction) -> ItemUseScreenInteraction:
        view = self.current_view()
        if view.mode == ItemUseScreenMode.ITEM_LIST:
            return self._handle_item_input(view, action)
        return self._handle_target_input(view, action)

    def activate_item(self, item_id: str) -> ItemUseScreenInteraction:
        view = self.current_view()
        item = next((entry for entry in view.items if entry.item_id == item_id), None)
        if item is None:
            return ItemUseScreenInteraction(
                view=view,
                logs=(f"item_use_rejected:item_not_available:{item_id}",),
                rejection_reason="item_not_available",
            )
        self._selected_item_id = item_id
        self._selection = MenuSelectionState(selected_index=None)
        return ItemUseScreenInteraction(view=self.current_view())

    def activate_target(self, character_id: str) -> ItemUseScreenInteraction:
        view = self.current_view()
        if view.mode != ItemUseScreenMode.TARGET_LIST or view.selected_item is None:
            return ItemUseScreenInteraction(
                view=view,
                logs=(f"item_use_rejected:target_without_item:{character_id}",),
                rejection_reason="item_not_selected",
            )
        target = next(
            (entry for entry in view.targets if entry.member.character_id == character_id),
            None,
        )
        if target is None:
            return ItemUseScreenInteraction(
                view=view,
                logs=(f"item_use_rejected:target_not_available:{character_id}",),
                rejection_reason="target_not_available",
            )
        if not target.can_use:
            return ItemUseScreenInteraction(
                view=view,
                logs=(
                    f"item_use_rejected:{target.reason_code}:{view.selected_item.item_id}:{character_id}",
                ),
                rejection_reason=target.reason_code,
            )
        result = self._facade.use_item(view.selected_item.item_id, character_id)
        if not result.success:
            return ItemUseScreenInteraction(
                view=self.current_view(),
                logs=result.logs,
                rejection_reason=result.code,
            )
        self._selected_item_id = None
        self._selection = MenuSelectionState(selected_index=None)
        return ItemUseScreenInteraction(view=self.current_view(), logs=result.logs)

    def _handle_item_input(
        self,
        view: ItemUseScreenViewModel,
        action: MenuInputAction,
    ) -> ItemUseScreenInteraction:
        result = self._navigation.apply(
            view.selection,
            self._item_menu_items(view.items),
            action,
        )
        self._selection = result.selection
        if result.cancelled:
            return ItemUseScreenInteraction(view=self.current_view(), cancel_requested=True)
        if result.guide_requested:
            return ItemUseScreenInteraction(
                view=self.current_view(),
                logs=(f"item_use_guide:items={len(view.items)}",),
            )
        if result.confirmed_action_id is None:
            return ItemUseScreenInteraction(view=self.current_view())
        return self.activate_item(result.confirmed_action_id)

    def _handle_target_input(
        self,
        view: ItemUseScreenViewModel,
        action: MenuInputAction,
    ) -> ItemUseScreenInteraction:
        if action == MenuInputAction.CANCEL:
            self._selected_item_id = None
            self._selection = MenuSelectionState(selected_index=None)
            return ItemUseScreenInteraction(view=self.current_view())
        if action == MenuInputAction.SHOW_GUIDE:
            available = sum(1 for target in view.targets if target.can_use)
            return ItemUseScreenInteraction(
                view=view,
                logs=(f"item_target_guide:targets={len(view.targets)}:available={available}",),
            )
        result = self._navigation.apply(
            view.selection,
            self._target_menu_items(view.targets),
            action,
        )
        self._selection = result.selection
        if result.confirmed_action_id is None:
            return ItemUseScreenInteraction(view=self.current_view())
        return self.activate_target(result.confirmed_action_id)

    @staticmethod
    def _item_menu_items(
        items: tuple[UsableItemSummary, ...],
    ) -> tuple[MenuItemViewModel, ...]:
        return tuple(
            MenuItemViewModel(
                action_id=item.item_id,
                label=f"{item.name} x{item.amount}",
                is_enabled=item.amount > 0,
            )
            for item in items
        )

    @staticmethod
    def _target_menu_items(
        targets: tuple[ItemTargetAvailability, ...],
    ) -> tuple[MenuItemViewModel, ...]:
        return tuple(
            MenuItemViewModel(
                action_id=target.member.character_id,
                label=(
                    f"{target.member.character_id} "
                    f"HP {target.member.current_hp}/{target.member.max_hp} "
                    f"SP {target.member.current_sp}/{target.member.max_sp}"
                ),
                is_enabled=target.can_use,
            )
            for target in targets
        )


class EquipmentScreenMode(str, Enum):
    MEMBER_LIST = "member_list"
    SLOT_LIST = "slot_list"
    EQUIPMENT_LIST = "equipment_list"


@dataclass(frozen=True)
class EquipmentScreenViewModel:
    title: str
    mode: EquipmentScreenMode
    members: tuple[PartyMemberSummary, ...]
    selected_member: PartyMemberSummary | None
    slots: tuple[EquipmentSlotSummary, ...]
    selected_slot: EquipmentSlotSummary | None
    equipment_options: tuple[EquipmentOptionSummary, ...]
    selection: MenuSelectionState


@dataclass(frozen=True)
class EquipmentScreenInteraction:
    view: EquipmentScreenViewModel
    logs: tuple[str, ...] = tuple()
    cancel_requested: bool = False
    rejection_reason: str | None = None


class EquipmentScreenController:
    def __init__(
        self,
        facade: PlayablePartyMenuFacade,
        *,
        navigation: MenuNavigationService | None = None,
    ) -> None:
        self._facade = facade
        self._navigation = navigation or MenuNavigationService()
        self._selected_member_id: str | None = None
        self._selected_slot_type: str | None = None
        self._selection = MenuSelectionState(selected_index=None)

    def current_view(self) -> EquipmentScreenViewModel:
        members = self._facade.list_party_members()
        selected_member = next(
            (member for member in members if member.character_id == self._selected_member_id),
            None,
        )
        if self._selected_member_id is None or selected_member is None:
            self._selected_member_id = None
            self._selected_slot_type = None
            selection = self._navigation.initial_selection(
                self._member_menu_items(members),
                self._selection.selected_index or 0,
            )
            self._selection = selection
            return EquipmentScreenViewModel(
                title="装備変更",
                mode=EquipmentScreenMode.MEMBER_LIST,
                members=members,
                selected_member=None,
                slots=tuple(),
                selected_slot=None,
                equipment_options=tuple(),
                selection=selection,
            )

        slots = self._facade.list_equipment_slots(selected_member.character_id)
        selected_slot = next(
            (slot for slot in slots if slot.slot_type == self._selected_slot_type),
            None,
        )
        if self._selected_slot_type is None or selected_slot is None:
            self._selected_slot_type = None
            selection = self._navigation.initial_selection(
                self._slot_menu_items(slots),
                self._selection.selected_index or 0,
            )
            self._selection = selection
            return EquipmentScreenViewModel(
                title=f"{selected_member.character_id}の装備スロット",
                mode=EquipmentScreenMode.SLOT_LIST,
                members=tuple(),
                selected_member=selected_member,
                slots=slots,
                selected_slot=None,
                equipment_options=tuple(),
                selection=selection,
            )

        options = self._facade.list_equipment_options(
            selected_member.character_id,
            selected_slot.slot_type,
        )
        selection = self._navigation.initial_selection(
            self._equipment_menu_items(options),
            self._selection.selected_index or 0,
        )
        self._selection = selection
        return EquipmentScreenViewModel(
            title=f"{selected_member.character_id} / {selected_slot.slot_type}",
            mode=EquipmentScreenMode.EQUIPMENT_LIST,
            members=tuple(),
            selected_member=selected_member,
            slots=tuple(),
            selected_slot=selected_slot,
            equipment_options=options,
            selection=selection,
        )

    def handle_input(self, action: MenuInputAction) -> EquipmentScreenInteraction:
        view = self.current_view()
        if view.mode == EquipmentScreenMode.MEMBER_LIST:
            return self._handle_member_input(view, action)
        if view.mode == EquipmentScreenMode.SLOT_LIST:
            return self._handle_slot_input(view, action)
        return self._handle_equipment_input(view, action)

    def activate_member(self, character_id: str) -> EquipmentScreenInteraction:
        view = self.current_view()
        member = next((entry for entry in view.members if entry.character_id == character_id), None)
        if member is None:
            return EquipmentScreenInteraction(
                view=view,
                logs=(f"equip_rejected:member_not_available:{character_id}",),
                rejection_reason="member_not_available",
            )
        self._selected_member_id = character_id
        self._selected_slot_type = None
        self._selection = MenuSelectionState(selected_index=None)
        return EquipmentScreenInteraction(view=self.current_view())

    def activate_slot(self, slot_type: str) -> EquipmentScreenInteraction:
        view = self.current_view()
        if view.mode != EquipmentScreenMode.SLOT_LIST or slot_type not in VALID_SLOTS:
            return EquipmentScreenInteraction(
                view=view,
                logs=(f"equip_rejected:invalid_slot:{slot_type}",),
                rejection_reason="invalid_slot",
            )
        if not any(slot.slot_type == slot_type for slot in view.slots):
            return EquipmentScreenInteraction(
                view=view,
                logs=(f"equip_rejected:slot_not_available:{slot_type}",),
                rejection_reason="slot_not_available",
            )
        self._selected_slot_type = slot_type
        self._selection = MenuSelectionState(selected_index=None)
        return EquipmentScreenInteraction(view=self.current_view())

    def activate_equipment(self, equipment_id: str) -> EquipmentScreenInteraction:
        view = self.current_view()
        if (
            view.mode != EquipmentScreenMode.EQUIPMENT_LIST
            or view.selected_member is None
            or view.selected_slot is None
        ):
            return EquipmentScreenInteraction(
                view=view,
                logs=(f"equip_rejected:equipment_without_context:{equipment_id}",),
                rejection_reason="equipment_context_missing",
            )
        option = next(
            (entry for entry in view.equipment_options if entry.equipment_id == equipment_id),
            None,
        )
        if option is None:
            return EquipmentScreenInteraction(
                view=view,
                logs=(f"equip_rejected:equipment_not_available:{equipment_id}",),
                rejection_reason="equipment_not_available",
            )
        if not option.can_equip:
            return EquipmentScreenInteraction(
                view=view,
                logs=(f"equip_rejected:insufficient_stock:{equipment_id}",),
                rejection_reason="insufficient_stock",
            )
        result = self._facade.equip_item(
            view.selected_member.character_id,
            view.selected_slot.slot_type,
            equipment_id,
        )
        if not result.success:
            return EquipmentScreenInteraction(
                view=self.current_view(),
                logs=result.logs,
                rejection_reason=result.code,
            )
        return EquipmentScreenInteraction(view=self.current_view(), logs=result.logs)

    def _handle_member_input(
        self,
        view: EquipmentScreenViewModel,
        action: MenuInputAction,
    ) -> EquipmentScreenInteraction:
        result = self._navigation.apply(
            view.selection,
            self._member_menu_items(view.members),
            action,
        )
        self._selection = result.selection
        if result.cancelled:
            return EquipmentScreenInteraction(view=self.current_view(), cancel_requested=True)
        if result.guide_requested:
            return EquipmentScreenInteraction(
                view=self.current_view(),
                logs=(f"equipment_member_guide:members={len(view.members)}",),
            )
        if result.confirmed_action_id is None:
            return EquipmentScreenInteraction(view=self.current_view())
        return self.activate_member(result.confirmed_action_id)

    def _handle_slot_input(
        self,
        view: EquipmentScreenViewModel,
        action: MenuInputAction,
    ) -> EquipmentScreenInteraction:
        if action == MenuInputAction.CANCEL:
            self._selected_member_id = None
            self._selection = MenuSelectionState(selected_index=None)
            return EquipmentScreenInteraction(view=self.current_view())
        if action == MenuInputAction.SHOW_GUIDE:
            return EquipmentScreenInteraction(
                view=view,
                logs=(f"equipment_slot_guide:slots={len(view.slots)}",),
            )
        result = self._navigation.apply(
            view.selection,
            self._slot_menu_items(view.slots),
            action,
        )
        self._selection = result.selection
        if result.confirmed_action_id is None:
            return EquipmentScreenInteraction(view=self.current_view())
        return self.activate_slot(result.confirmed_action_id)

    def _handle_equipment_input(
        self,
        view: EquipmentScreenViewModel,
        action: MenuInputAction,
    ) -> EquipmentScreenInteraction:
        if action == MenuInputAction.CANCEL:
            self._selected_slot_type = None
            self._selection = MenuSelectionState(selected_index=None)
            return EquipmentScreenInteraction(view=self.current_view())
        if action == MenuInputAction.SHOW_GUIDE:
            available = sum(1 for option in view.equipment_options if option.can_equip)
            return EquipmentScreenInteraction(
                view=view,
                logs=(
                    f"equipment_option_guide:options={len(view.equipment_options)}:available={available}",
                ),
            )
        result = self._navigation.apply(
            view.selection,
            self._equipment_menu_items(view.equipment_options),
            action,
        )
        self._selection = result.selection
        if result.confirmed_action_id is None:
            return EquipmentScreenInteraction(view=self.current_view())
        return self.activate_equipment(result.confirmed_action_id)

    @staticmethod
    def _member_menu_items(
        members: tuple[PartyMemberSummary, ...],
    ) -> tuple[MenuItemViewModel, ...]:
        return tuple(
            MenuItemViewModel(
                action_id=member.character_id,
                label=f"{member.character_id} Lv.{member.level}",
            )
            for member in members
        )

    @staticmethod
    def _slot_menu_items(
        slots: tuple[EquipmentSlotSummary, ...],
    ) -> tuple[MenuItemViewModel, ...]:
        return tuple(
            MenuItemViewModel(
                action_id=slot.slot_type,
                label=f"{slot.slot_type}: {slot.current_equipment_name or '未装備'}",
            )
            for slot in slots
        )

    @staticmethod
    def _equipment_menu_items(
        options: tuple[EquipmentOptionSummary, ...],
    ) -> tuple[MenuItemViewModel, ...]:
        return tuple(
            MenuItemViewModel(
                action_id=option.equipment_id,
                label=(
                    f"{option.name} 所持{option.owned} 利用可{option.available} "
                    f"ATK+{option.atk_bonus} DEF+{option.defense_bonus}"
                ),
                is_enabled=option.can_equip,
            )
            for option in options
        )
