from __future__ import annotations

from dataclasses import dataclass

from game.app.application.playable_equipment_workshop_facade import (
    PlayableEquipmentWorkshopFacade,
    SalvageOptionSummary,
    UpgradeOptionSummary,
)
from game.app.presentation.input_actions import MenuInputAction
from game.app.presentation.menu_view_model import (
    MenuItemViewModel,
    MenuNavigationService,
    MenuSelectionState,
)


@dataclass(frozen=True)
class EquipmentUpgradeScreenViewModel:
    title: str
    workshop_level: int
    options: tuple[UpgradeOptionSummary, ...]
    selection: MenuSelectionState


@dataclass(frozen=True)
class EquipmentUpgradeScreenInteraction:
    view: EquipmentUpgradeScreenViewModel
    logs: tuple[str, ...] = tuple()
    cancel_requested: bool = False
    rejection_reason: str | None = None


class EquipmentUpgradeScreenController:
    def __init__(
        self,
        facade: PlayableEquipmentWorkshopFacade,
        *,
        navigation: MenuNavigationService | None = None,
    ) -> None:
        self._facade = facade
        self._navigation = navigation or MenuNavigationService()
        self._selection = MenuSelectionState(selected_index=None)

    def current_view(self) -> EquipmentUpgradeScreenViewModel:
        options = self._facade.list_upgrade_options()
        selection = self._navigation.initial_selection(
            self._menu_items(options),
            self._selection.selected_index or 0,
        )
        self._selection = selection
        return EquipmentUpgradeScreenViewModel(
            title="装備強化",
            workshop_level=self._facade.workshop_level,
            options=options,
            selection=selection,
        )

    def handle_input(
        self,
        action: MenuInputAction,
    ) -> EquipmentUpgradeScreenInteraction:
        view = self.current_view()
        result = self._navigation.apply(
            view.selection,
            self._menu_items(view.options),
            action,
        )
        self._selection = result.selection
        if result.cancelled:
            return EquipmentUpgradeScreenInteraction(
                view=self.current_view(),
                cancel_requested=True,
            )
        if result.guide_requested:
            upgradable = sum(1 for option in view.options if option.can_upgrade)
            return EquipmentUpgradeScreenInteraction(
                view=self.current_view(),
                logs=(
                    f"equipment_upgrade_guide:options={len(view.options)}:upgradable={upgradable}",
                ),
            )
        if result.confirmed_action_id is None:
            return EquipmentUpgradeScreenInteraction(view=self.current_view())
        return self.activate_equipment(result.confirmed_action_id)

    def activate_equipment(
        self,
        equipment_id: str,
    ) -> EquipmentUpgradeScreenInteraction:
        view = self.current_view()
        option = next(
            (entry for entry in view.options if entry.equipment_id == equipment_id),
            None,
        )
        if option is None:
            return EquipmentUpgradeScreenInteraction(
                view=view,
                logs=(
                    f"equipment_upgrade_rejected:equipment_not_available:{equipment_id}",
                ),
                rejection_reason="equipment_not_available",
            )
        if not option.can_upgrade:
            return EquipmentUpgradeScreenInteraction(
                view=view,
                logs=(
                    f"equipment_upgrade_rejected:{option.reason_code}:{equipment_id}",
                ),
                rejection_reason=option.reason_code,
            )
        result = self._facade.upgrade_equipment(equipment_id)
        return EquipmentUpgradeScreenInteraction(
            view=self.current_view(),
            logs=result.logs,
            rejection_reason=None if result.success else result.code,
        )

    @staticmethod
    def _menu_items(
        options: tuple[UpgradeOptionSummary, ...],
    ) -> tuple[MenuItemViewModel, ...]:
        return tuple(
            MenuItemViewModel(
                action_id=option.equipment_id,
                label=(
                    f"{option.name} +{option.current_level}/{option.max_level} "
                    f"[{option.reason_code}]"
                ),
                is_enabled=option.can_upgrade,
            )
            for option in options
        )


@dataclass(frozen=True)
class EquipmentSalvageScreenViewModel:
    title: str
    workshop_level: int
    options: tuple[SalvageOptionSummary, ...]
    selection: MenuSelectionState


@dataclass(frozen=True)
class EquipmentSalvageScreenInteraction:
    view: EquipmentSalvageScreenViewModel
    logs: tuple[str, ...] = tuple()
    cancel_requested: bool = False
    rejection_reason: str | None = None


class EquipmentSalvageScreenController:
    def __init__(
        self,
        facade: PlayableEquipmentWorkshopFacade,
        *,
        navigation: MenuNavigationService | None = None,
    ) -> None:
        self._facade = facade
        self._navigation = navigation or MenuNavigationService()
        self._selection = MenuSelectionState(selected_index=None)

    def current_view(self) -> EquipmentSalvageScreenViewModel:
        options = self._facade.list_salvage_options()
        selection = self._navigation.initial_selection(
            self._menu_items(options),
            self._selection.selected_index or 0,
        )
        self._selection = selection
        return EquipmentSalvageScreenViewModel(
            title="装備分解",
            workshop_level=self._facade.workshop_level,
            options=options,
            selection=selection,
        )

    def handle_input(
        self,
        action: MenuInputAction,
    ) -> EquipmentSalvageScreenInteraction:
        view = self.current_view()
        result = self._navigation.apply(
            view.selection,
            self._menu_items(view.options),
            action,
        )
        self._selection = result.selection
        if result.cancelled:
            return EquipmentSalvageScreenInteraction(
                view=self.current_view(),
                cancel_requested=True,
            )
        if result.guide_requested:
            salvageable = sum(1 for option in view.options if option.can_salvage)
            return EquipmentSalvageScreenInteraction(
                view=self.current_view(),
                logs=(
                    f"equipment_salvage_guide:options={len(view.options)}:salvageable={salvageable}",
                ),
            )
        if result.confirmed_action_id is None:
            return EquipmentSalvageScreenInteraction(view=self.current_view())
        return self.activate_equipment(result.confirmed_action_id)

    def activate_equipment(
        self,
        equipment_id: str,
    ) -> EquipmentSalvageScreenInteraction:
        view = self.current_view()
        option = next(
            (entry for entry in view.options if entry.equipment_id == equipment_id),
            None,
        )
        if option is None:
            return EquipmentSalvageScreenInteraction(
                view=view,
                logs=(
                    f"equipment_salvage_rejected:equipment_not_available:{equipment_id}",
                ),
                rejection_reason="equipment_not_available",
            )
        if not option.can_salvage:
            return EquipmentSalvageScreenInteraction(
                view=view,
                logs=(
                    f"equipment_salvage_rejected:{option.reason_code}:{equipment_id}",
                ),
                rejection_reason=option.reason_code,
            )
        result = self._facade.salvage_equipment(equipment_id)
        return EquipmentSalvageScreenInteraction(
            view=self.current_view(),
            logs=result.logs,
            rejection_reason=None if result.success else result.code,
        )

    @staticmethod
    def _menu_items(
        options: tuple[SalvageOptionSummary, ...],
    ) -> tuple[MenuItemViewModel, ...]:
        return tuple(
            MenuItemViewModel(
                action_id=option.equipment_id,
                label=(
                    f"{option.name} 所持{option.owned} 利用可{option.available} "
                    f"[{option.reason_code}]"
                ),
                is_enabled=option.can_salvage,
            )
            for option in options
        )
