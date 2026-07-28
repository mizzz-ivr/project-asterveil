from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, TypeAlias

from game.app.presentation.screen_action_dispatcher import (
    SteamDemoSceneActionDispatcher,
)
from game.app.presentation.screen_router import SteamDemoRouteId


class ControllerInteractionProtocol(Protocol):
    view: object
    logs: tuple[str, ...]
    rejection_reason: str | None


@dataclass(frozen=True)
class CliScreenActionResult:
    view: object
    logs: tuple[str, ...]
    rejection_reason: str | None = None


ControllerAction: TypeAlias = Callable[[str], ControllerInteractionProtocol]


def activate_entry(
    *,
    route_id: SteamDemoRouteId,
    entry_id: str,
    controller_action: ControllerAction,
    dispatcher: SteamDemoSceneActionDispatcher | None = None,
) -> CliScreenActionResult:
    if dispatcher is None:
        interaction = controller_action(entry_id)
        return CliScreenActionResult(
            view=interaction.view,
            logs=interaction.logs,
            rejection_reason=interaction.rejection_reason,
        )

    result = dispatcher.activate_entry(route_id, entry_id)
    return CliScreenActionResult(
        view=result.frame.view,
        logs=result.logs,
        rejection_reason=result.rejection_reason,
    )
