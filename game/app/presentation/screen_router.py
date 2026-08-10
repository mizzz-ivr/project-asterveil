from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from game.app.presentation.action_controller import (
    ActionDispatchKind,
    ActionDispatchResult,
    SteamDemoFlowId,
)
from game.app.presentation.input_actions import MenuInputAction
from game.app.presentation.menu_view_model import SteamDemoMenuViewModel
from game.app.presentation.screen_controller import SteamDemoScreenController


class SteamDemoRouteId(str, Enum):
    TOP_MENU = "steam_demo.top_menu"
    USE_ITEM = "steam_demo.use_item"
    EQUIPMENT = "steam_demo.equipment"
    SHOP = "steam_demo.shop"
    EQUIPMENT_UPGRADE = "steam_demo.equipment_upgrade"
    EQUIPMENT_SALVAGE = "steam_demo.equipment_salvage"
    CRAFTING = "steam_demo.crafting"
    INN = "steam_demo.inn"
    QUEST_BOARD = "steam_demo.quest_board"
    TRAVEL = "steam_demo.travel"
    NPC_DIALOGUE = "steam_demo.npc_dialogue"
    GATHERING = "steam_demo.gathering"
    TREASURE = "steam_demo.treasure"
    FIELD_EVENT = "steam_demo.field_event"
    BESTIARY = "steam_demo.bestiary"


DEFAULT_ROUTE_BY_FLOW: Mapping[SteamDemoFlowId, SteamDemoRouteId] = {
    SteamDemoFlowId.USE_ITEM: SteamDemoRouteId.USE_ITEM,
    SteamDemoFlowId.EQUIPMENT: SteamDemoRouteId.EQUIPMENT,
    SteamDemoFlowId.SHOP: SteamDemoRouteId.SHOP,
    SteamDemoFlowId.EQUIPMENT_UPGRADE: SteamDemoRouteId.EQUIPMENT_UPGRADE,
    SteamDemoFlowId.EQUIPMENT_SALVAGE: SteamDemoRouteId.EQUIPMENT_SALVAGE,
    SteamDemoFlowId.CRAFTING: SteamDemoRouteId.CRAFTING,
    SteamDemoFlowId.INN: SteamDemoRouteId.INN,
    SteamDemoFlowId.QUEST_BOARD: SteamDemoRouteId.QUEST_BOARD,
    SteamDemoFlowId.TRAVEL: SteamDemoRouteId.TRAVEL,
    SteamDemoFlowId.NPC_DIALOGUE: SteamDemoRouteId.NPC_DIALOGUE,
    SteamDemoFlowId.GATHERING: SteamDemoRouteId.GATHERING,
    SteamDemoFlowId.TREASURE: SteamDemoRouteId.TREASURE,
    SteamDemoFlowId.FIELD_EVENT: SteamDemoRouteId.FIELD_EVENT,
    SteamDemoFlowId.BESTIARY: SteamDemoRouteId.BESTIARY,
}


class RouteTransitionKind(str, Enum):
    STAY = "stay"
    PUSHED = "pushed"
    POPPED = "popped"
    RESET = "reset"
    EXIT_REQUESTED = "exit_requested"
    REJECTED = "rejected"


@dataclass(frozen=True)
class SteamDemoRouteState:
    route_stack: tuple[SteamDemoRouteId, ...] = (SteamDemoRouteId.TOP_MENU,)

    def __post_init__(self) -> None:
        if not self.route_stack:
            raise ValueError("route_stack must not be empty")
        if self.route_stack[0] != SteamDemoRouteId.TOP_MENU:
            raise ValueError("route_stack must start with top menu")
        if SteamDemoRouteId.TOP_MENU in self.route_stack[1:]:
            raise ValueError("top menu cannot appear after the root route")

    @property
    def current_route(self) -> SteamDemoRouteId:
        return self.route_stack[-1]

    @property
    def can_go_back(self) -> bool:
        return len(self.route_stack) > 1

    def to_dict(self) -> dict[str, object]:
        return {
            "route_stack": [route.value for route in self.route_stack],
            "current_route": self.current_route.value,
            "can_go_back": self.can_go_back,
        }


@dataclass(frozen=True)
class SteamDemoRouteTransition:
    kind: RouteTransitionKind
    state: SteamDemoRouteState
    from_route: SteamDemoRouteId
    to_route: SteamDemoRouteId
    logs: tuple[str, ...] = tuple()
    dispatch_result: ActionDispatchResult | None = None
    reason_code: str | None = None


class SteamDemoScreenRouter:
    """トップ画面とサブ画面のRoute履歴だけを管理する。"""

    def __init__(
        self,
        top_screen: SteamDemoScreenController,
        *,
        route_by_flow: Mapping[SteamDemoFlowId, SteamDemoRouteId] | None = None,
    ) -> None:
        self._top_screen = top_screen
        self._route_by_flow = dict(route_by_flow or DEFAULT_ROUTE_BY_FLOW)
        invalid_root_flows = tuple(
            flow_id.value
            for flow_id, route_id in self._route_by_flow.items()
            if route_id == SteamDemoRouteId.TOP_MENU
        )
        if invalid_root_flows:
            raise ValueError(
                f"subflow route cannot use top menu: {invalid_root_flows}"
            )
        self._state = SteamDemoRouteState()

    @property
    def state(self) -> SteamDemoRouteState:
        return self._state

    def current_top_view(self) -> SteamDemoMenuViewModel:
        return self._top_screen.current_view()

    def route_for_flow(self, flow_id: SteamDemoFlowId) -> SteamDemoRouteId | None:
        return self._route_by_flow.get(flow_id)

    def registered_routes(self) -> tuple[SteamDemoRouteId, ...]:
        return tuple(dict.fromkeys(self._route_by_flow.values()))

    def handle_top_input(self, action: MenuInputAction) -> SteamDemoRouteTransition:
        if self._state.current_route != SteamDemoRouteId.TOP_MENU:
            return self._rejected("top_input_not_allowed_from_subroute")

        interaction = self._top_screen.handle_input(action)
        if interaction.cancel_requested:
            return self.request_back()
        if interaction.dispatch_result is None:
            return self._stay()
        return self._from_dispatch(interaction.dispatch_result)

    def activate_top_action(self, action_id: str) -> SteamDemoRouteTransition:
        if self._state.current_route != SteamDemoRouteId.TOP_MENU:
            return self._rejected("top_action_not_allowed_from_subroute")
        interaction = self._top_screen.activate_action(action_id)
        if interaction.dispatch_result is None:
            return self._rejected("missing_dispatch_result")
        return self._from_dispatch(interaction.dispatch_result)

    def open_flow(self, flow_id: SteamDemoFlowId) -> SteamDemoRouteTransition:
        if self._state.current_route != SteamDemoRouteId.TOP_MENU:
            return self._rejected("subroute_already_active")
        route_id = self.route_for_flow(flow_id)
        if route_id is None:
            return self._rejected("route_not_registered")
        return self._push(route_id)

    def complete_current_route(
        self,
        logs: tuple[str, ...] = tuple(),
    ) -> SteamDemoRouteTransition:
        return self._pop(logs=logs, root_reason="cannot_complete_root")

    def cancel_current_route(
        self,
        logs: tuple[str, ...] | None = None,
    ) -> SteamDemoRouteTransition:
        if not self._state.can_go_back:
            return self._rejected("cannot_cancel_root")
        current = self._state.current_route
        cancellation_logs = logs or (f"route_cancelled:{current.value}",)
        return self._pop(logs=cancellation_logs, root_reason="cannot_cancel_root")

    def request_back(self) -> SteamDemoRouteTransition:
        if not self._state.can_go_back:
            return self._rejected("cannot_pop_root")
        current = self._state.current_route
        destination = self._state.route_stack[-2]
        return self._pop(
            logs=(f"route_back:{current.value}:{destination.value}",),
            root_reason="cannot_pop_root",
        )

    def reset_to_top(
        self,
        logs: tuple[str, ...] = tuple(),
    ) -> SteamDemoRouteTransition:
        previous = self._state.current_route
        if self._state.route_stack == (SteamDemoRouteId.TOP_MENU,):
            return self._stay(logs=logs)
        self._state = SteamDemoRouteState()
        return SteamDemoRouteTransition(
            kind=RouteTransitionKind.RESET,
            state=self._state,
            from_route=previous,
            to_route=SteamDemoRouteId.TOP_MENU,
            logs=logs,
        )

    def _from_dispatch(
        self,
        result: ActionDispatchResult,
    ) -> SteamDemoRouteTransition:
        if result.kind == ActionDispatchKind.FLOW_REQUIRED:
            if result.flow_id is None:
                return self._rejected(
                    "missing_flow_id",
                    logs=(f"route_rejected:missing_flow_id:{result.action_id}",),
                    dispatch_result=result,
                )
            route_id = self.route_for_flow(result.flow_id)
            if route_id is None:
                return self._rejected(
                    "route_not_registered",
                    logs=(
                        f"route_rejected:route_not_registered:{result.flow_id.value}",
                    ),
                    dispatch_result=result,
                )
            return self._push(route_id, dispatch_result=result)

        if result.kind == ActionDispatchKind.EXIT_REQUESTED:
            current = self._state.current_route
            return SteamDemoRouteTransition(
                kind=RouteTransitionKind.EXIT_REQUESTED,
                state=self._state,
                from_route=current,
                to_route=current,
                logs=result.logs,
                dispatch_result=result,
            )

        if result.kind == ActionDispatchKind.REJECTED:
            return self._rejected(
                result.reason_code or "action_rejected",
                logs=result.logs,
                dispatch_result=result,
            )

        return self._stay(logs=result.logs, dispatch_result=result)

    def _push(
        self,
        route_id: SteamDemoRouteId,
        *,
        dispatch_result: ActionDispatchResult | None = None,
    ) -> SteamDemoRouteTransition:
        previous = self._state.current_route
        self._state = SteamDemoRouteState(
            route_stack=self._state.route_stack + (route_id,),
        )
        return SteamDemoRouteTransition(
            kind=RouteTransitionKind.PUSHED,
            state=self._state,
            from_route=previous,
            to_route=route_id,
            logs=(f"route_opened:{route_id.value}",),
            dispatch_result=dispatch_result,
        )

    def _pop(
        self,
        *,
        logs: tuple[str, ...],
        root_reason: str,
    ) -> SteamDemoRouteTransition:
        if not self._state.can_go_back:
            return self._rejected(root_reason)
        previous = self._state.current_route
        self._state = SteamDemoRouteState(route_stack=self._state.route_stack[:-1])
        return SteamDemoRouteTransition(
            kind=RouteTransitionKind.POPPED,
            state=self._state,
            from_route=previous,
            to_route=self._state.current_route,
            logs=logs,
        )

    def _stay(
        self,
        *,
        logs: tuple[str, ...] = tuple(),
        dispatch_result: ActionDispatchResult | None = None,
    ) -> SteamDemoRouteTransition:
        current = self._state.current_route
        return SteamDemoRouteTransition(
            kind=RouteTransitionKind.STAY,
            state=self._state,
            from_route=current,
            to_route=current,
            logs=logs,
            dispatch_result=dispatch_result,
        )

    def _rejected(
        self,
        reason_code: str,
        *,
        logs: tuple[str, ...] | None = None,
        dispatch_result: ActionDispatchResult | None = None,
    ) -> SteamDemoRouteTransition:
        current = self._state.current_route
        return SteamDemoRouteTransition(
            kind=RouteTransitionKind.REJECTED,
            state=self._state,
            from_route=current,
            to_route=current,
            logs=logs or (f"route_rejected:{reason_code}:{current.value}",),
            dispatch_result=dispatch_result,
            reason_code=reason_code,
        )
