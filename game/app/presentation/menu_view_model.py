from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

from game.app.presentation.input_actions import (
    InputBindingProfile,
    InputHint,
    MenuInputAction,
    build_default_input_binding_profile,
)

if TYPE_CHECKING:
    from game.app.application.demo_flow_service import SteamDemoApplication
    from game.app.application.playable_slice import PlayableSliceApplication


@dataclass(frozen=True)
class MenuItemViewModel:
    action_id: str
    label: str
    is_enabled: bool = True
    is_recommended: bool = False


@dataclass(frozen=True)
class MenuSelectionState:
    selected_index: int | None


@dataclass(frozen=True)
class MenuInteractionResult:
    selection: MenuSelectionState
    confirmed_action_id: str | None = None
    cancelled: bool = False
    guide_requested: bool = False


@dataclass(frozen=True)
class SteamDemoMenuViewModel:
    title: str
    progress_label: str
    objective_title: str
    objective_text: str
    recommended_action_id: str | None
    is_completed: bool
    items: tuple[MenuItemViewModel, ...]
    selection: MenuSelectionState
    input_hints: tuple[InputHint, ...]


class MenuNavigationService:
    """メニュー選択位置を描画・入力デバイスから独立して遷移させる。"""

    def initial_selection(
        self,
        items: Iterable[MenuItemViewModel],
        preferred_index: int = 0,
    ) -> MenuSelectionState:
        item_tuple = tuple(items)
        selectable = self._selectable_indices(item_tuple)
        if not selectable:
            return MenuSelectionState(selected_index=None)
        if preferred_index in selectable:
            return MenuSelectionState(selected_index=preferred_index)
        return MenuSelectionState(selected_index=selectable[0])

    def apply(
        self,
        state: MenuSelectionState,
        items: Iterable[MenuItemViewModel],
        action: MenuInputAction,
    ) -> MenuInteractionResult:
        item_tuple = tuple(items)
        normalized = self.initial_selection(
            item_tuple,
            preferred_index=state.selected_index if state.selected_index is not None else 0,
        )

        if action == MenuInputAction.CANCEL:
            return MenuInteractionResult(selection=normalized, cancelled=True)
        if action == MenuInputAction.SHOW_GUIDE:
            return MenuInteractionResult(selection=normalized, guide_requested=True)
        if action == MenuInputAction.CONFIRM:
            selected_index = state.selected_index
            if not self._is_enabled_index(item_tuple, selected_index):
                return MenuInteractionResult(selection=normalized)
            selected_item = item_tuple[selected_index]
            return MenuInteractionResult(
                selection=MenuSelectionState(selected_index=selected_index),
                confirmed_action_id=selected_item.action_id,
            )
        if action not in {MenuInputAction.MOVE_UP, MenuInputAction.MOVE_DOWN}:
            return MenuInteractionResult(selection=normalized)

        selectable = self._selectable_indices(item_tuple)
        if not selectable:
            return MenuInteractionResult(selection=MenuSelectionState(None))

        selected_index = state.selected_index
        if selected_index is None or not 0 <= selected_index < len(item_tuple):
            return MenuInteractionResult(selection=normalized)

        delta = -1 if action == MenuInputAction.MOVE_UP else 1
        next_index = self._find_next_enabled_index(item_tuple, selected_index, delta)
        return MenuInteractionResult(
            selection=MenuSelectionState(selected_index=next_index)
        )

    @staticmethod
    def _selectable_indices(items: tuple[MenuItemViewModel, ...]) -> tuple[int, ...]:
        return tuple(index for index, item in enumerate(items) if item.is_enabled)

    @staticmethod
    def _is_enabled_index(
        items: tuple[MenuItemViewModel, ...],
        selected_index: int | None,
    ) -> bool:
        return (
            selected_index is not None
            and 0 <= selected_index < len(items)
            and items[selected_index].is_enabled
        )

    @staticmethod
    def _find_next_enabled_index(
        items: tuple[MenuItemViewModel, ...],
        start_index: int,
        delta: int,
    ) -> int:
        for offset in range(1, len(items) + 1):
            candidate = (start_index + delta * offset) % len(items)
            if items[candidate].is_enabled:
                return candidate
        raise RuntimeError("enabled menu item must exist before navigation")


class SteamDemoMenuPresenter:
    """Steamデモ状態をUI描画用の不変ViewModelへ変換する。"""

    _RECOMMENDED_ACTION_ALIASES = {
        "inspect_workshop": "demo_workshop",
    }

    def __init__(
        self,
        input_profile: InputBindingProfile | None = None,
        navigation: MenuNavigationService | None = None,
    ) -> None:
        self._input_profile = input_profile or build_default_input_binding_profile()
        self._navigation = navigation or MenuNavigationService()

    def build(
        self,
        playable: PlayableSliceApplication,
        demo: SteamDemoApplication,
        selected_index: int = 0,
    ) -> SteamDemoMenuViewModel:
        progress = demo.progress()
        definition = demo.flow_service.definitions[demo.flow_id]
        active_step = progress.active_step
        recommended_action_id = None
        if active_step is not None:
            recommended_action_id = self._RECOMMENDED_ACTION_ALIASES.get(
                active_step.recommended_action,
                active_step.recommended_action,
            )

        raw_items: list[tuple[str, str, bool]] = [
            ("demo_guide", "現在のデモ目標を確認する", True)
        ]
        if recommended_action_id == "demo_workshop":
            raw_items.append(("demo_workshop", "デモ工房ガイドを確認する", True))
        raw_items.extend(
            (item.key, item.label, True)
            for item in playable.available_actions()
        )

        seen_action_ids: set[str] = set()
        menu_items: list[MenuItemViewModel] = []
        for action_id, label, is_enabled in raw_items:
            if action_id in seen_action_ids:
                raise ValueError(f"duplicate menu action id: {action_id}")
            seen_action_ids.add(action_id)
            menu_items.append(
                MenuItemViewModel(
                    action_id=action_id,
                    label=label,
                    is_enabled=is_enabled,
                    is_recommended=action_id == recommended_action_id,
                )
            )

        selection = self._navigation.initial_selection(menu_items, selected_index)
        if progress.is_completed:
            objective_title = "Steamデモ チェックポイント到達"
            objective_text = "デモの一区切りまで到達しました。セーブデータから再開できます。"
        elif active_step is None:
            raise RuntimeError("incomplete demo progress must have an active step")
        else:
            objective_title = active_step.title
            objective_text = active_step.guidance_text

        return SteamDemoMenuViewModel(
            title=definition.name,
            progress_label=f"{len(progress.completed_step_ids)}/{len(definition.steps)}",
            objective_title=objective_title,
            objective_text=objective_text,
            recommended_action_id=recommended_action_id,
            is_completed=progress.is_completed,
            items=tuple(menu_items),
            selection=selection,
            input_hints=self._input_profile.hints(),
        )
