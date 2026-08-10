from __future__ import annotations

from game.app.presentation.bestiary_screen import BestiaryScreenController
from game.app.presentation.screen_action_dispatcher import SteamDemoSceneActionDispatcher
from game.app.presentation.screen_renderer import SteamDemoSceneBuilderRegistry
from game.app.presentation.screen_router import SteamDemoRouteId
from game.app.presentation.screen_runtime import (
    SteamDemoRuntimeResult,
    SteamDemoScreenRuntime,
)


class BestiarySceneActionDispatcher(SteamDemoSceneActionDispatcher):
    """既存Action Dispatcherへ図鑑RouteのEntry操作だけを追加する。"""

    def __init__(
        self,
        runtime: SteamDemoScreenRuntime,
        scene_registry: SteamDemoSceneBuilderRegistry,
    ) -> None:
        # 基底実装は全SteamDemoRouteIdを要求するため、新Route追加時に既存Adapterを
        # 変更せず再利用できるよう、既存Adapter集合を明示的に検証して保持する。
        self._runtime = runtime
        self._scene_registry = scene_registry
        self._adapters = dict(SteamDemoSceneActionDispatcher._default_adapters())
        expected_existing_routes = set(SteamDemoRouteId) - {
            SteamDemoRouteId.TOP_MENU,
            SteamDemoRouteId.BESTIARY,
        }
        actual_existing_routes = set(self._adapters)
        if expected_existing_routes != actual_existing_routes:
            missing = sorted(
                route.value for route in expected_existing_routes - actual_existing_routes
            )
            extra = sorted(
                route.value for route in actual_existing_routes - expected_existing_routes
            )
            raise ValueError(
                "invalid_existing_scene_action_adapter_registry:"
                f"missing={','.join(missing) or 'none'}:"
                f"extra={','.join(extra) or 'none'}"
            )

    def registered_routes(self) -> tuple[SteamDemoRouteId, ...]:
        routes = super().registered_routes()
        if SteamDemoRouteId.BESTIARY in routes:
            return routes
        return (*routes, SteamDemoRouteId.BESTIARY)

    def _activate_subroute_entry(
        self,
        route_id: SteamDemoRouteId,
        entry_id: str,
    ) -> SteamDemoRuntimeResult:
        if route_id != SteamDemoRouteId.BESTIARY:
            return super()._activate_subroute_entry(route_id, entry_id)

        active_screen = self._runtime.active_screen
        if active_screen is None:
            return self._runtime.reject_current_action("active_screen_missing")
        controller = active_screen.controller
        if not isinstance(controller, BestiaryScreenController):
            return self._runtime.reject_current_action(
                "route_controller_type_mismatch",
                logs=(
                    "scene_action_rejected:controller_type_mismatch:"
                    f"{route_id.value}:expected=BestiaryScreenController:"
                    f"actual={type(controller).__name__}",
                ),
            )
        try:
            interaction = controller.activate_entry(entry_id)
        except (TypeError, ValueError) as exc:
            return self._runtime.reject_current_action(
                "controller_action_failed",
                logs=(
                    "scene_action_rejected:controller_action_failed:"
                    f"{route_id.value}:{entry_id}:{exc}",
                ),
            )
        return self._runtime.apply_subscreen_interaction(interaction)
