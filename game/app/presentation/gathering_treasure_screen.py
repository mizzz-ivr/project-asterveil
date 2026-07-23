from __future__ import annotations

from dataclasses import dataclass

from game.app.application.playable_exploration_facade import (
    GatheringNodeSummary,
    PlayableExplorationFacade,
    TreasureNodeSummary,
)
from game.app.presentation.input_actions import MenuInputAction
from game.app.presentation.menu_view_model import (
    MenuItemViewModel,
    MenuNavigationService,
    MenuSelectionState,
)


@dataclass(frozen=True)
class GatheringScreenViewModel:
    title: str
    current_location_id: str
    nodes: tuple[GatheringNodeSummary, ...]
    selection: MenuSelectionState


@dataclass(frozen=True)
class GatheringScreenInteraction:
    view: GatheringScreenViewModel
    logs: tuple[str, ...] = tuple()
    cancel_requested: bool = False
    rejection_reason: str | None = None


class GatheringScreenController:
    def __init__(
        self,
        facade: PlayableExplorationFacade,
        *,
        navigation: MenuNavigationService | None = None,
    ) -> None:
        self._facade = facade
        self._navigation = navigation or MenuNavigationService()
        self._selection = MenuSelectionState(selected_index=None)

    def current_view(self) -> GatheringScreenViewModel:
        nodes = self._facade.list_gathering_nodes()
        selection = self._navigation.initial_selection(
            self._menu_items(nodes),
            self._selection.selected_index or 0,
        )
        self._selection = selection
        return GatheringScreenViewModel(
            title="採取",
            current_location_id=self._facade.current_location_id,
            nodes=nodes,
            selection=selection,
        )

    def handle_input(self, action: MenuInputAction) -> GatheringScreenInteraction:
        view = self.current_view()
        result = self._navigation.apply(
            view.selection,
            self._menu_items(view.nodes),
            action,
        )
        self._selection = result.selection
        if result.cancelled:
            return GatheringScreenInteraction(
                view=self.current_view(),
                cancel_requested=True,
            )
        if result.guide_requested:
            available = sum(1 for node in view.nodes if node.can_gather)
            return GatheringScreenInteraction(
                view=self.current_view(),
                logs=(
                    f"gathering_guide:location={view.current_location_id}:"
                    f"nodes={len(view.nodes)}:available={available}",
                ),
            )
        if result.confirmed_action_id is None:
            return GatheringScreenInteraction(view=self.current_view())
        return self.activate_node(result.confirmed_action_id)

    def activate_node(self, node_id: str) -> GatheringScreenInteraction:
        view = self.current_view()
        node = next((item for item in view.nodes if item.node_id == node_id), None)
        if node is None:
            return GatheringScreenInteraction(
                view=view,
                logs=(f"gather_rejected:node_not_available:{node_id}",),
                rejection_reason="node_not_available",
            )
        if not node.can_gather:
            return GatheringScreenInteraction(
                view=view,
                logs=(f"gather_rejected:{node.reason_code}:{node_id}",),
                rejection_reason=node.reason_code,
            )

        result = self._facade.gather(node_id)
        return GatheringScreenInteraction(
            view=self.current_view(),
            logs=result.logs,
            rejection_reason=None if result.success else result.code,
        )

    @staticmethod
    def _menu_items(
        nodes: tuple[GatheringNodeSummary, ...],
    ) -> tuple[MenuItemViewModel, ...]:
        return tuple(
            MenuItemViewModel(
                action_id=node.node_id,
                label=f"{node.name} [{node.node_type}]",
                is_enabled=node.can_gather,
            )
            for node in nodes
        )


@dataclass(frozen=True)
class TreasureScreenViewModel:
    title: str
    current_location_id: str
    nodes: tuple[TreasureNodeSummary, ...]
    selection: MenuSelectionState


@dataclass(frozen=True)
class TreasureScreenInteraction:
    view: TreasureScreenViewModel
    logs: tuple[str, ...] = tuple()
    cancel_requested: bool = False
    rejection_reason: str | None = None


class TreasureScreenController:
    def __init__(
        self,
        facade: PlayableExplorationFacade,
        *,
        navigation: MenuNavigationService | None = None,
    ) -> None:
        self._facade = facade
        self._navigation = navigation or MenuNavigationService()
        self._selection = MenuSelectionState(selected_index=None)

    def current_view(self) -> TreasureScreenViewModel:
        nodes = self._facade.list_treasure_nodes()
        selection = self._navigation.initial_selection(
            self._menu_items(nodes),
            self._selection.selected_index or 0,
        )
        self._selection = selection
        return TreasureScreenViewModel(
            title="探索報酬",
            current_location_id=self._facade.current_location_id,
            nodes=nodes,
            selection=selection,
        )

    def handle_input(self, action: MenuInputAction) -> TreasureScreenInteraction:
        view = self.current_view()
        result = self._navigation.apply(
            view.selection,
            self._menu_items(view.nodes),
            action,
        )
        self._selection = result.selection
        if result.cancelled:
            return TreasureScreenInteraction(
                view=self.current_view(),
                cancel_requested=True,
            )
        if result.guide_requested:
            openable = sum(1 for node in view.nodes if node.can_open)
            return TreasureScreenInteraction(
                view=self.current_view(),
                logs=(
                    f"treasure_guide:location={view.current_location_id}:"
                    f"nodes={len(view.nodes)}:openable={openable}",
                ),
            )
        if result.confirmed_action_id is None:
            return TreasureScreenInteraction(view=self.current_view())
        return self.activate_node(result.confirmed_action_id)

    def activate_node(self, reward_node_id: str) -> TreasureScreenInteraction:
        view = self.current_view()
        node = next(
            (
                item
                for item in view.nodes
                if item.reward_node_id == reward_node_id
            ),
            None,
        )
        if node is None:
            return TreasureScreenInteraction(
                view=view,
                logs=(f"treasure_rejected:reward_not_available:{reward_node_id}",),
                rejection_reason="reward_not_available",
            )
        if not node.can_open:
            return TreasureScreenInteraction(
                view=view,
                logs=(f"treasure_rejected:{node.reason_code}:{reward_node_id}",),
                rejection_reason=node.reason_code,
            )

        result = self._facade.open_treasure(reward_node_id)
        return TreasureScreenInteraction(
            view=self.current_view(),
            logs=result.logs,
            rejection_reason=None if result.success else result.code,
        )

    @staticmethod
    def _menu_items(
        nodes: tuple[TreasureNodeSummary, ...],
    ) -> tuple[MenuItemViewModel, ...]:
        return tuple(
            MenuItemViewModel(
                action_id=node.reward_node_id,
                label=f"{node.name} [{node.node_type}]",
                is_enabled=node.can_open,
            )
            for node in nodes
        )
