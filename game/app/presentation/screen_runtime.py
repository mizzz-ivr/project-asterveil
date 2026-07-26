from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from game.app.presentation.input_actions import MenuInputAction
from game.app.presentation.screen_router import (
    RouteTransitionKind,
    SteamDemoRouteId,
    SteamDemoRouteState,
    SteamDemoRouteTransition,
    SteamDemoScreenRouter,
)


class SteamDemoSubScreenInteractionProtocol(Protocol):
    view: object
    logs: tuple[str, ...]
    cancel_requested: bool
    rejection_reason: str | None


class SteamDemoSubScreenControllerProtocol(Protocol):
    def current_view(self) -> object: ...

    def handle_input(
        self,
        action: MenuInputAction,
    ) -> SteamDemoSubScreenInteractionProtocol: ...


class SteamDemoRouteScreenProtocol(Protocol):
    route_id: SteamDemoRouteId
    controller: SteamDemoSubScreenControllerProtocol


class SteamDemoScreenFactoryProtocol(Protocol):
    def create(self, route_id: SteamDemoRouteId) -> SteamDemoRouteScreenProtocol: ...


@dataclass(frozen=True)
class SteamDemoRuntimeFrame:
    route_state: SteamDemoRouteState
    route_id: SteamDemoRouteId
    view: object
    is_top_menu: bool
    has_active_screen: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "route_state": self.route_state.to_dict(),
            "route_id": self.route_id.value,
            "is_top_menu": self.is_top_menu,
            "has_active_screen": self.has_active_screen,
        }


@dataclass(frozen=True)
class SteamDemoRuntimeResult:
    frame: SteamDemoRuntimeFrame
    transition: SteamDemoRouteTransition
    logs: tuple[str, ...] = tuple()
    rejection_reason: str | None = None
    exit_requested: bool = False


class SteamDemoScreenRuntime:
    """RouterとScreenFactoryを同期し、現在画面のライフサイクルを管理する。"""

    def __init__(
        self,
        router: SteamDemoScreenRouter,
        screen_factory: SteamDemoScreenFactoryProtocol,
    ) -> None:
        if router.state.current_route != SteamDemoRouteId.TOP_MENU:
            raise ValueError("screen_runtime_must_start_from_top_menu")
        if router.state.can_go_back:
            raise ValueError("screen_runtime_must_start_without_route_history")
        self._router = router
        self._screen_factory = screen_factory
        self._active_screen: SteamDemoRouteScreenProtocol | None = None

    @property
    def router(self) -> SteamDemoScreenRouter:
        return self._router

    @property
    def active_screen(self) -> SteamDemoRouteScreenProtocol | None:
        self._assert_synchronized()
        return self._active_screen

    def current_frame(self) -> SteamDemoRuntimeFrame:
        self._assert_synchronized()
        if self._active_screen is None:
            view = self._router.current_top_view()
        else:
            view = self._active_screen.controller.current_view()
        return self._build_frame(view)

    def handle_input(self, action: MenuInputAction) -> SteamDemoRuntimeResult:
        self._assert_synchronized()
        if self._active_screen is None:
            return self._apply_top_transition(self._router.handle_top_input(action))
        return self._handle_subscreen_input(action)

    def activate_top_action(self, action_id: str) -> SteamDemoRuntimeResult:
        self._assert_synchronized()
        if self._active_screen is not None:
            return self._runtime_rejected("top_action_not_allowed_from_subroute")
        return self._apply_top_transition(self._router.activate_top_action(action_id))

    def complete_current_route(
        self,
        logs: tuple[str, ...] = tuple(),
    ) -> SteamDemoRuntimeResult:
        self._assert_synchronized()
        if self._active_screen is None:
            return self._runtime_rejected("subscreen_not_active")
        transition = self._router.complete_current_route(logs=logs)
        if transition.kind == RouteTransitionKind.POPPED:
            self._active_screen = None
        return self._result(transition)

    def cancel_current_route(
        self,
        logs: tuple[str, ...] | None = None,
    ) -> SteamDemoRuntimeResult:
        self._assert_synchronized()
        if self._active_screen is None:
            return self._runtime_rejected("subscreen_not_active")
        transition = self._router.cancel_current_route(logs=logs)
        if transition.kind == RouteTransitionKind.POPPED:
            self._active_screen = None
        return self._result(transition)

    def reset_to_top(
        self,
        logs: tuple[str, ...] = tuple(),
    ) -> SteamDemoRuntimeResult:
        self._assert_synchronized()
        transition = self._router.reset_to_top(logs=logs)
        self._active_screen = None
        return self._result(transition)

    def _apply_top_transition(
        self,
        transition: SteamDemoRouteTransition,
    ) -> SteamDemoRuntimeResult:
        if transition.kind != RouteTransitionKind.PUSHED:
            return self._result(transition)

        route_id = transition.to_route
        try:
            route_screen = self._screen_factory.create(route_id)
            if route_screen.route_id != route_id:
                raise ValueError(
                    "screen_factory_route_mismatch:"
                    f"expected={route_id.value}:actual={route_screen.route_id.value}"
                )
        except (TypeError, ValueError) as exc:
            logs = (f"screen_open_rejected:{route_id.value}:{exc}",)
            rollback = self._router.cancel_current_route(logs=logs)
            rejected = SteamDemoRouteTransition(
                kind=RouteTransitionKind.REJECTED,
                state=rollback.state,
                from_route=route_id,
                to_route=rollback.to_route,
                logs=logs,
                dispatch_result=transition.dispatch_result,
                reason_code="screen_creation_failed",
            )
            self._active_screen = None
            return self._result(
                rejected,
                rejection_reason="screen_creation_failed",
            )

        self._active_screen = route_screen
        return self._result(transition)

    def _handle_subscreen_input(
        self,
        action: MenuInputAction,
    ) -> SteamDemoRuntimeResult:
        if self._active_screen is None:
            return self._runtime_rejected("subscreen_not_active")

        try:
            interaction = self._active_screen.controller.handle_input(action)
            view = interaction.view
            logs = self._validated_logs(interaction.logs)
            cancel_requested = bool(interaction.cancel_requested)
            rejection_reason = interaction.rejection_reason
        except ValueError as exc:
            return self._runtime_rejected(
                "subscreen_input_rejected",
                logs=(
                    f"screen_input_rejected:"
                    f"{self._router.state.current_route.value}:{exc}",
                ),
            )

        if cancel_requested:
            transition = self._router.cancel_current_route(logs=logs or None)
            if transition.kind == RouteTransitionKind.POPPED:
                self._active_screen = None
            return self._result(transition)

        if rejection_reason is not None:
            transition = self._build_transition(
                RouteTransitionKind.REJECTED,
                logs=logs,
                reason_code=rejection_reason,
            )
            return self._result(
                transition,
                view=view,
                rejection_reason=rejection_reason,
            )

        transition = self._build_transition(RouteTransitionKind.STAY, logs=logs)
        return self._result(transition, view=view)

    def _runtime_rejected(
        self,
        reason_code: str,
        *,
        logs: tuple[str, ...] | None = None,
    ) -> SteamDemoRuntimeResult:
        current = self._router.state.current_route
        rejection_logs = logs or (
            f"screen_runtime_rejected:{reason_code}:{current.value}",
        )
        transition = self._build_transition(
            RouteTransitionKind.REJECTED,
            logs=rejection_logs,
            reason_code=reason_code,
        )
        return self._result(transition, rejection_reason=reason_code)

    def _build_transition(
        self,
        kind: RouteTransitionKind,
        *,
        logs: tuple[str, ...] = tuple(),
        reason_code: str | None = None,
    ) -> SteamDemoRouteTransition:
        current = self._router.state.current_route
        return SteamDemoRouteTransition(
            kind=kind,
            state=self._router.state,
            from_route=current,
            to_route=current,
            logs=logs,
            reason_code=reason_code,
        )

    def _result(
        self,
        transition: SteamDemoRouteTransition,
        *,
        view: object | None = None,
        rejection_reason: str | None = None,
    ) -> SteamDemoRuntimeResult:
        self._assert_synchronized()
        frame = self._build_frame(view) if view is not None else self.current_frame()
        return SteamDemoRuntimeResult(
            frame=frame,
            transition=transition,
            logs=transition.logs,
            rejection_reason=rejection_reason or transition.reason_code,
            exit_requested=transition.kind == RouteTransitionKind.EXIT_REQUESTED,
        )

    def _build_frame(self, view: object) -> SteamDemoRuntimeFrame:
        route_id = self._router.state.current_route
        return SteamDemoRuntimeFrame(
            route_state=self._router.state,
            route_id=route_id,
            view=view,
            is_top_menu=route_id == SteamDemoRouteId.TOP_MENU,
            has_active_screen=self._active_screen is not None,
        )

    def _assert_synchronized(self) -> None:
        current_route = self._router.state.current_route
        if current_route == SteamDemoRouteId.TOP_MENU:
            if self._active_screen is not None:
                raise RuntimeError("active_screen_must_be_empty_on_top_menu")
            return
        if self._active_screen is None:
            raise RuntimeError(
                f"active_screen_missing_for_route:{current_route.value}"
            )
        if self._active_screen.route_id != current_route:
            raise RuntimeError(
                "active_screen_route_mismatch:"
                f"router={current_route.value}:"
                f"screen={self._active_screen.route_id.value}"
            )

    @staticmethod
    def _validated_logs(logs: tuple[str, ...]) -> tuple[str, ...]:
        if not isinstance(logs, tuple) or not all(isinstance(log, str) for log in logs):
            raise TypeError("subscreen_interaction_logs_must_be_string_tuple")
        return logs
