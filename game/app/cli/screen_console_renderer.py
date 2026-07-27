from __future__ import annotations

from collections.abc import Callable

from game.app.presentation.screen_renderer import (
    SteamDemoSceneBuilderRegistry,
    SteamDemoSceneModel,
)
from game.app.presentation.screen_router import SteamDemoRouteId
from game.app.presentation.screen_runtime import SteamDemoRuntimeFrame


class SteamDemoConsoleRenderer:
    """Scene Modelだけを参照し、CLI向けの安定した行形式へ変換する。"""

    def __init__(
        self,
        registry: SteamDemoSceneBuilderRegistry | None = None,
        *,
        emit: Callable[[str], None] = print,
    ) -> None:
        self._registry = registry or SteamDemoSceneBuilderRegistry()
        self._emit = emit

    @property
    def registry(self) -> SteamDemoSceneBuilderRegistry:
        return self._registry

    def render_frame(self, frame: SteamDemoRuntimeFrame) -> SteamDemoSceneModel:
        scene = self._registry.build_frame(frame)
        self.render_scene(scene)
        return scene

    def render_view(self, route_id: SteamDemoRouteId, view: object) -> SteamDemoSceneModel:
        scene = self._registry.build(route_id, view)
        self.render_scene(scene)
        return scene

    def render_scene(self, scene: SteamDemoSceneModel) -> None:
        for line in self.lines(scene):
            self._emit(line)

    @staticmethod
    def lines(scene: SteamDemoSceneModel) -> tuple[str, ...]:
        lines: list[str] = [
            f"- screen:{scene.route_id.value}:{scene.title}:completed={scene.is_completed}"
        ]
        if scene.subtitle:
            lines.append(f"- screen_subtitle:{scene.route_id.value}:{scene.subtitle}")
        for field in scene.status:
            lines.append(
                f"- screen_status:{scene.route_id.value}:{field.key}={field.value}"
            )
        for section in scene.sections:
            lines.append(
                f"- screen_section:{scene.route_id.value}:{section.section_id}:"
                f"{section.title}:count={len(section.entries)}"
            )
            for entry in section.entries:
                lines.append(
                    f"- screen_entry:{scene.route_id.value}:{section.section_id}:"
                    f"{entry.entry_id}:{entry.label}:enabled={entry.is_enabled}:"
                    f"selected={entry.is_selected}:recommended={entry.is_recommended}"
                )
                if entry.description:
                    lines.append(
                        f"- screen_entry_description:{scene.route_id.value}:"
                        f"{entry.entry_id}:{entry.description}"
                    )
                for field in entry.fields:
                    lines.append(
                        f"- screen_entry_field:{scene.route_id.value}:{entry.entry_id}:"
                        f"{field.key}={field.value}"
                    )
        for hint in scene.action_hints:
            lines.append(
                f"- screen_hint:{scene.route_id.value}:{hint.action_id}:"
                f"keyboard={hint.keyboard_label or 'none'}:"
                f"gamepad={hint.gamepad_label or 'none'}"
            )
        return tuple(lines)


_DEFAULT_RENDERER = SteamDemoConsoleRenderer()


def render_runtime_frame(frame: SteamDemoRuntimeFrame) -> SteamDemoSceneModel:
    return _DEFAULT_RENDERER.render_frame(frame)


def render_route_view(
    route_id: SteamDemoRouteId,
    view: object,
) -> SteamDemoSceneModel:
    return _DEFAULT_RENDERER.render_view(route_id, view)
