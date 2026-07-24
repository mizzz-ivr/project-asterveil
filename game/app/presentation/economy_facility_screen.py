from __future__ import annotations

from dataclasses import dataclass

from game.app.application.playable_economy_facility_facade import (
    CraftRecipeSummary,
    CraftingSummary,
    InnSummary,
    PlayableEconomyFacilityFacade,
    ShopItemSummary,
    ShopSummary,
)
from game.app.presentation.input_actions import MenuInputAction
from game.app.presentation.menu_view_model import (
    MenuItemViewModel,
    MenuNavigationService,
    MenuSelectionState,
)


@dataclass(frozen=True)
class ShopScreenViewModel:
    title: str
    summary: ShopSummary
    selection: MenuSelectionState


@dataclass(frozen=True)
class ShopScreenInteraction:
    view: ShopScreenViewModel
    logs: tuple[str, ...] = tuple()
    cancel_requested: bool = False
    rejection_reason: str | None = None


class ShopScreenController:
    def __init__(
        self,
        facade: PlayableEconomyFacilityFacade,
        *,
        navigation: MenuNavigationService | None = None,
    ) -> None:
        self._facade = facade
        self._navigation = navigation or MenuNavigationService()
        self._selection = MenuSelectionState(selected_index=None)

    def current_view(self) -> ShopScreenViewModel:
        summary = self._facade.shop_summary()
        selection = self._navigation.initial_selection(
            self._menu_items(summary.items),
            self._selection.selected_index or 0,
        )
        self._selection = selection
        return ShopScreenViewModel(
            title=summary.name if summary.success else "ショップ",
            summary=summary,
            selection=selection,
        )

    def handle_input(self, action: MenuInputAction) -> ShopScreenInteraction:
        view = self.current_view()
        result = self._navigation.apply(
            view.selection,
            self._menu_items(view.summary.items),
            action,
        )
        self._selection = result.selection
        if result.cancelled:
            return ShopScreenInteraction(
                view=self.current_view(),
                cancel_requested=True,
            )
        if result.guide_requested:
            purchasable = sum(1 for item in view.summary.items if item.can_purchase)
            return ShopScreenInteraction(
                view=self.current_view(),
                logs=(
                    f"shop_guide:items={len(view.summary.items)}:purchasable={purchasable}:gold={view.summary.gold}",
                ),
            )
        if result.confirmed_action_id is None:
            return ShopScreenInteraction(view=self.current_view())
        return self.activate_item(result.confirmed_action_id)

    def activate_item(self, item_id: str) -> ShopScreenInteraction:
        view = self.current_view()
        item = next(
            (entry for entry in view.summary.items if entry.item_id == item_id),
            None,
        )
        if item is None:
            result = self._facade.purchase_item(item_id)
            return ShopScreenInteraction(
                view=view,
                logs=result.logs,
                rejection_reason=result.code,
            )
        if not item.can_purchase:
            return ShopScreenInteraction(
                view=view,
                logs=(f"purchase_rejected:{item.reason_code}:{view.summary.shop_id}:{item_id}",),
                rejection_reason=item.reason_code,
            )
        result = self._facade.purchase_item(item_id)
        return ShopScreenInteraction(
            view=self.current_view(),
            logs=result.logs,
            rejection_reason=None if result.success else result.code,
        )

    @staticmethod
    def _menu_items(
        items: tuple[ShopItemSummary, ...],
    ) -> tuple[MenuItemViewModel, ...]:
        return tuple(
            MenuItemViewModel(
                action_id=item.item_id,
                label=f"{item.name} {item.price}G 所持{item.owned}",
                is_enabled=item.can_purchase,
            )
            for item in items
        )


@dataclass(frozen=True)
class CraftingScreenViewModel:
    title: str
    summary: CraftingSummary
    selection: MenuSelectionState


@dataclass(frozen=True)
class CraftingScreenInteraction:
    view: CraftingScreenViewModel
    logs: tuple[str, ...] = tuple()
    cancel_requested: bool = False
    rejection_reason: str | None = None


class CraftingScreenController:
    def __init__(
        self,
        facade: PlayableEconomyFacilityFacade,
        *,
        navigation: MenuNavigationService | None = None,
    ) -> None:
        self._facade = facade
        self._navigation = navigation or MenuNavigationService()
        self._selection = MenuSelectionState(selected_index=None)

    def current_view(self) -> CraftingScreenViewModel:
        summary = self._facade.crafting_summary()
        selection = self._navigation.initial_selection(
            self._menu_items(summary.recipes),
            self._selection.selected_index or 0,
        )
        self._selection = selection
        return CraftingScreenViewModel(
            title="クラフト",
            summary=summary,
            selection=selection,
        )

    def handle_input(self, action: MenuInputAction) -> CraftingScreenInteraction:
        view = self.current_view()
        result = self._navigation.apply(
            view.selection,
            self._menu_items(view.summary.recipes),
            action,
        )
        self._selection = result.selection
        if result.cancelled:
            return CraftingScreenInteraction(
                view=self.current_view(),
                cancel_requested=True,
            )
        if result.guide_requested:
            craftable = sum(1 for recipe in view.summary.recipes if recipe.can_craft)
            return CraftingScreenInteraction(
                view=self.current_view(),
                logs=(
                    f"crafting_guide:recipes={len(view.summary.recipes)}:craftable={craftable}:workshop_level={view.summary.workshop_level}",
                ),
            )
        if result.confirmed_action_id is None:
            return CraftingScreenInteraction(view=self.current_view())
        return self.activate_recipe(result.confirmed_action_id)

    def activate_recipe(self, recipe_id: str) -> CraftingScreenInteraction:
        view = self.current_view()
        recipe = next(
            (entry for entry in view.summary.recipes if entry.recipe_id == recipe_id),
            None,
        )
        if recipe is None:
            return CraftingScreenInteraction(
                view=view,
                logs=(f"craft_rejected:recipe_not_available:{recipe_id}",),
                rejection_reason="recipe_not_available",
            )
        if not recipe.can_craft:
            return CraftingScreenInteraction(
                view=view,
                logs=(f"craft_rejected:{recipe.reason_code}:{recipe_id}",),
                rejection_reason=recipe.reason_code,
            )
        result = self._facade.craft_recipe(recipe_id)
        return CraftingScreenInteraction(
            view=self.current_view(),
            logs=result.logs,
            rejection_reason=None if result.success else result.code,
        )

    @staticmethod
    def _menu_items(
        recipes: tuple[CraftRecipeSummary, ...],
    ) -> tuple[MenuItemViewModel, ...]:
        return tuple(
            MenuItemViewModel(
                action_id=recipe.recipe_id,
                label=f"{recipe.name} [{recipe.reason_code}]",
                is_enabled=recipe.can_craft,
            )
            for recipe in recipes
        )


@dataclass(frozen=True)
class InnScreenViewModel:
    title: str
    summary: InnSummary
    selection: MenuSelectionState


@dataclass(frozen=True)
class InnScreenInteraction:
    view: InnScreenViewModel
    logs: tuple[str, ...] = tuple()
    cancel_requested: bool = False
    rejection_reason: str | None = None


class InnScreenController:
    STAY_ACTION_ID = "stay"

    def __init__(
        self,
        facade: PlayableEconomyFacilityFacade,
        *,
        navigation: MenuNavigationService | None = None,
    ) -> None:
        self._facade = facade
        self._navigation = navigation or MenuNavigationService()
        self._selection = MenuSelectionState(selected_index=None)

    def current_view(self) -> InnScreenViewModel:
        summary = self._facade.inn_summary()
        selection = self._navigation.initial_selection(
            self._menu_items(summary),
            self._selection.selected_index or 0,
        )
        self._selection = selection
        return InnScreenViewModel(
            title=summary.name if summary.success else "宿屋",
            summary=summary,
            selection=selection,
        )

    def handle_input(self, action: MenuInputAction) -> InnScreenInteraction:
        view = self.current_view()
        result = self._navigation.apply(
            view.selection,
            self._menu_items(view.summary),
            action,
        )
        self._selection = result.selection
        if result.cancelled:
            return InnScreenInteraction(
                view=self.current_view(),
                cancel_requested=True,
            )
        if result.guide_requested:
            return InnScreenInteraction(
                view=self.current_view(),
                logs=(
                    f"inn_guide:price={view.summary.stay_price}:gold={view.summary.gold}:can_stay={view.summary.can_stay}:reason={view.summary.reason_code}",
                ),
            )
        if result.confirmed_action_id is None:
            return InnScreenInteraction(view=self.current_view())
        return self.activate_stay(result.confirmed_action_id)

    def activate_stay(self, action_id: str = STAY_ACTION_ID) -> InnScreenInteraction:
        view = self.current_view()
        if action_id != self.STAY_ACTION_ID:
            return InnScreenInteraction(
                view=view,
                logs=(f"inn_stay_rejected:unknown_action:{action_id}",),
                rejection_reason="unknown_action",
            )
        if not view.summary.success or not view.summary.can_stay:
            return InnScreenInteraction(
                view=view,
                logs=(
                    f"inn_stay_rejected:{view.summary.reason_code}:{view.summary.inn_id}",
                ),
                rejection_reason=view.summary.reason_code,
            )
        result = self._facade.stay_at_inn(view.summary.inn_id)
        return InnScreenInteraction(
            view=self.current_view(),
            logs=result.logs,
            rejection_reason=None if result.success else result.code,
        )

    @classmethod
    def _menu_items(cls, summary: InnSummary) -> tuple[MenuItemViewModel, ...]:
        return (
            MenuItemViewModel(
                action_id=cls.STAY_ACTION_ID,
                label=f"宿泊する {summary.stay_price}G",
                is_enabled=summary.success and summary.can_stay,
            ),
        )
