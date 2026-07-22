from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from game.app.presentation.action_controller import (
    ActionDispatchKind,
    ActionDispatchResult,
    SteamDemoActionController,
)
from game.app.presentation.input_actions import MenuInputAction
from game.app.presentation.menu_view_model import (
    MenuNavigationService,
    MenuSelectionState,
    SteamDemoMenuPresenter,
    SteamDemoMenuViewModel,
)

if TYPE_CHECKING:
    from game.app.application.demo_flow_service import SteamDemoApplication
    from game.app.application.playable_slice import PlayableSliceApplication


@dataclass(frozen=True)
class SteamDemoScreenInteraction:
    view: SteamDemoMenuViewModel
    dispatch_result: ActionDispatchResult | None = None
    cancel_requested: bool = False


class SteamDemoScreenController:
    """意味入力と画面状態を統合し、描画層へ更新後ViewModelを返す。"""

    def __init__(
        self,
        playable: PlayableSliceApplication,
        demo: SteamDemoApplication,
        *,
        presenter: SteamDemoMenuPresenter | None = None,
        navigation: MenuNavigationService | None = None,
        action_controller: SteamDemoActionController | None = None,
    ) -> None:
        self._playable = playable
        self._demo = demo
        self._presenter = presenter or SteamDemoMenuPresenter()
        self._navigation = navigation or MenuNavigationService()
        self._actions = action_controller or SteamDemoActionController(playable, demo)
        self._selection = MenuSelectionState(selected_index=None)

    def current_view(self) -> SteamDemoMenuViewModel:
        preferred_index = self._selection.selected_index
        view = self._presenter.build(
            self._playable,
            self._demo,
            selected_index=preferred_index if preferred_index is not None else 0,
        )
        self._selection = view.selection
        return view

    def handle_input(self, action: MenuInputAction) -> SteamDemoScreenInteraction:
        view = self.current_view()
        interaction = self._navigation.apply(
            view.selection,
            view.items,
            action,
        )
        self._selection = interaction.selection

        dispatch_result: ActionDispatchResult | None = None
        if interaction.guide_requested:
            dispatch_result = self._actions.dispatch("demo_guide")
        elif interaction.confirmed_action_id is not None:
            dispatch_result = self._actions.dispatch(interaction.confirmed_action_id)

        return SteamDemoScreenInteraction(
            view=self.current_view(),
            dispatch_result=dispatch_result,
            cancel_requested=interaction.cancelled,
        )

    def activate_action(self, action_id: str) -> SteamDemoScreenInteraction:
        view = self.current_view()
        selected_index = next(
            (
                index
                for index, item in enumerate(view.items)
                if item.action_id == action_id and item.is_enabled
            ),
            None,
        )
        if selected_index is None:
            rejected = ActionDispatchResult(
                action_id=action_id,
                kind=ActionDispatchKind.REJECTED,
                logs=(f"action_rejected:{action_id}:menu_item_not_available",),
                reason_code="menu_item_not_available",
            )
            return SteamDemoScreenInteraction(
                view=view,
                dispatch_result=rejected,
            )

        self._selection = MenuSelectionState(selected_index=selected_index)
        dispatch_result = self._actions.dispatch(action_id)
        return SteamDemoScreenInteraction(
            view=self.current_view(),
            dispatch_result=dispatch_result,
        )
