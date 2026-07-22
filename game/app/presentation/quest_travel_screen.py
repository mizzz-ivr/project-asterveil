from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from game.app.presentation.input_actions import MenuInputAction
from game.app.presentation.menu_view_model import (
    MenuItemViewModel,
    MenuNavigationService,
    MenuSelectionState,
)
from game.quest.domain.entities import QuestBoardStatus

if TYPE_CHECKING:
    from game.app.application.playable_slice import PlayableSliceApplication


_QUEST_ENTRY_PATTERN = re.compile(
    r"^quest_board_entry:(?P<quest_id>[^:]+):(?P<title>.*):"
    r"status=(?P<status>[^:]+):can_accept=(?P<can_accept>True|False):"
    r"progress=(?P<progress>.*)$"
)
_TRAVEL_OPTION_PATTERN = re.compile(
    r"^travel_option:(?P<location_id>[^:]+):(?P<name>.*):type=(?P<location_type>[^:]+)$"
)
_CURRENT_LOCATION_PATTERN = re.compile(
    r"^current_location:(?P<location_id>[^:]+):(?P<name>.*)$"
)


_QUEST_STATUS_LABELS = {
    QuestBoardStatus.LOCKED: "未解放",
    QuestBoardStatus.AVAILABLE: "受注可能",
    QuestBoardStatus.IN_PROGRESS: "進行中",
    QuestBoardStatus.READY_TO_COMPLETE: "報告可能",
    QuestBoardStatus.COMPLETED: "完了",
    QuestBoardStatus.REPOST_WAITING: "再掲待ち",
    QuestBoardStatus.REACCEPTABLE: "再受注可能",
}


@dataclass(frozen=True)
class QuestBoardEntryViewModel:
    quest_id: str
    title: str
    status: QuestBoardStatus
    status_label: str
    can_accept: bool
    objective_progress: tuple[tuple[str, int], ...]

    @property
    def progress_label(self) -> str:
        if not self.objective_progress:
            return "未開始"
        return ", ".join(
            f"{objective_id}={value}"
            for objective_id, value in self.objective_progress
        )


@dataclass(frozen=True)
class QuestBoardScreenViewModel:
    title: str
    max_active_quests: int
    active_quest_count: int
    entries: tuple[QuestBoardEntryViewModel, ...]
    selection: MenuSelectionState


@dataclass(frozen=True)
class QuestBoardScreenInteraction:
    view: QuestBoardScreenViewModel
    logs: tuple[str, ...] = tuple()
    cancel_requested: bool = False
    rejection_reason: str | None = None


@dataclass(frozen=True)
class TravelDestinationViewModel:
    location_id: str
    name: str
    location_type: str


@dataclass(frozen=True)
class TravelScreenViewModel:
    title: str
    current_location_id: str
    current_location_name: str
    destinations: tuple[TravelDestinationViewModel, ...]
    selection: MenuSelectionState


@dataclass(frozen=True)
class TravelScreenInteraction:
    view: TravelScreenViewModel
    logs: tuple[str, ...] = tuple()
    cancel_requested: bool = False
    rejection_reason: str | None = None


class QuestBoardScreenPresenter:
    """既存のクエストボード出力契約を描画用ViewModelへ変換する。"""

    def __init__(self, navigation: MenuNavigationService | None = None) -> None:
        self._navigation = navigation or MenuNavigationService()

    def build(
        self,
        playable: PlayableSliceApplication,
        selected_index: int = 0,
    ) -> QuestBoardScreenViewModel:
        max_active = 0
        entries: list[QuestBoardEntryViewModel] = []

        for line in playable.quest_board_lines():
            if line.startswith("quest_board:max_active="):
                max_active = self._parse_non_negative_int(
                    line.removeprefix("quest_board:max_active="),
                    "max_active",
                )
                continue
            if not line.startswith("quest_board_entry:"):
                continue
            entries.append(self._parse_entry(line))

        menu_items = self._menu_items(entries)
        selection = self._navigation.initial_selection(menu_items, selected_index)
        active_count = sum(
            1 for entry in entries if entry.status == QuestBoardStatus.IN_PROGRESS
        )
        return QuestBoardScreenViewModel(
            title="クエストボード",
            max_active_quests=max_active,
            active_quest_count=active_count,
            entries=tuple(entries),
            selection=selection,
        )

    @staticmethod
    def menu_items(view: QuestBoardScreenViewModel) -> tuple[MenuItemViewModel, ...]:
        return QuestBoardScreenPresenter._menu_items(view.entries)

    @staticmethod
    def _menu_items(
        entries: tuple[QuestBoardEntryViewModel, ...] | list[QuestBoardEntryViewModel],
    ) -> tuple[MenuItemViewModel, ...]:
        return tuple(
            MenuItemViewModel(
                action_id=entry.quest_id,
                label=f"{entry.title} [{entry.status_label}]",
                is_enabled=entry.can_accept,
            )
            for entry in entries
        )

    @staticmethod
    def _parse_entry(line: str) -> QuestBoardEntryViewModel:
        matched = _QUEST_ENTRY_PATTERN.match(line)
        if matched is None:
            raise ValueError(f"invalid quest board line: {line}")
        try:
            status = QuestBoardStatus(matched.group("status"))
        except ValueError as exc:
            raise ValueError(f"unknown quest board status: {line}") from exc

        raw_progress = ast.literal_eval(matched.group("progress"))
        if not isinstance(raw_progress, dict):
            raise ValueError(f"quest progress must be dict: {line}")
        progress: list[tuple[str, int]] = []
        for objective_id, value in sorted(raw_progress.items()):
            if not isinstance(objective_id, str) or not isinstance(value, int):
                raise ValueError(f"invalid quest progress entry: {line}")
            progress.append((objective_id, max(0, value)))

        return QuestBoardEntryViewModel(
            quest_id=matched.group("quest_id"),
            title=matched.group("title"),
            status=status,
            status_label=_QUEST_STATUS_LABELS[status],
            can_accept=matched.group("can_accept") == "True",
            objective_progress=tuple(progress),
        )

    @staticmethod
    def _parse_non_negative_int(raw: str, field_name: str) -> int:
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError(f"{field_name} must be integer: {raw}") from exc
        if value < 0:
            raise ValueError(f"{field_name} must not be negative: {value}")
        return value


class QuestBoardScreenController:
    def __init__(
        self,
        playable: PlayableSliceApplication,
        *,
        presenter: QuestBoardScreenPresenter | None = None,
        navigation: MenuNavigationService | None = None,
    ) -> None:
        self._playable = playable
        self._navigation = navigation or MenuNavigationService()
        self._presenter = presenter or QuestBoardScreenPresenter(self._navigation)
        self._selection = MenuSelectionState(selected_index=None)

    def current_view(self) -> QuestBoardScreenViewModel:
        selected_index = self._selection.selected_index
        view = self._presenter.build(
            self._playable,
            selected_index=selected_index if selected_index is not None else 0,
        )
        self._selection = view.selection
        return view

    def handle_input(self, action: MenuInputAction) -> QuestBoardScreenInteraction:
        view = self.current_view()
        navigation_result = self._navigation.apply(
            view.selection,
            self._presenter.menu_items(view),
            action,
        )
        self._selection = navigation_result.selection
        if navigation_result.cancelled:
            return QuestBoardScreenInteraction(
                view=self.current_view(),
                cancel_requested=True,
            )
        if navigation_result.guide_requested:
            return QuestBoardScreenInteraction(
                view=self.current_view(),
                logs=(
                    f"quest_board_guide:active={view.active_quest_count}/{view.max_active_quests}",
                ),
            )
        if navigation_result.confirmed_action_id is None:
            return QuestBoardScreenInteraction(view=self.current_view())
        return self.activate_quest(navigation_result.confirmed_action_id)

    def activate_quest(self, quest_id: str) -> QuestBoardScreenInteraction:
        view = self.current_view()
        entry = next((item for item in view.entries if item.quest_id == quest_id), None)
        if entry is None:
            return QuestBoardScreenInteraction(
                view=view,
                logs=(f"quest_accept_rejected:unknown_quest:{quest_id}",),
                rejection_reason="unknown_quest",
            )
        if not entry.can_accept:
            return QuestBoardScreenInteraction(
                view=view,
                logs=(f"quest_accept_rejected:not_available:{quest_id}:{entry.status.value}",),
                rejection_reason="quest_not_available",
            )
        try:
            logs = tuple(self._playable.accept_quest(quest_id))
        except ValueError as exc:
            return QuestBoardScreenInteraction(
                view=view,
                logs=(f"quest_accept_rejected:application:{quest_id}:{exc}",),
                rejection_reason="application_rejected",
            )
        return QuestBoardScreenInteraction(view=self.current_view(), logs=logs)


class TravelScreenPresenter:
    """既存の移動候補出力契約を描画用ViewModelへ変換する。"""

    def __init__(self, navigation: MenuNavigationService | None = None) -> None:
        self._navigation = navigation or MenuNavigationService()

    def build(
        self,
        playable: PlayableSliceApplication,
        selected_index: int = 0,
    ) -> TravelScreenViewModel:
        current_location_id = "unknown"
        current_location_name = "不明"
        destinations: list[TravelDestinationViewModel] = []

        for line in playable.travel_options_lines():
            current = _CURRENT_LOCATION_PATTERN.match(line)
            if current is not None:
                current_location_id = current.group("location_id")
                current_location_name = current.group("name")
                continue
            option = _TRAVEL_OPTION_PATTERN.match(line)
            if option is None:
                if line.startswith("travel_option:"):
                    raise ValueError(f"invalid travel option line: {line}")
                continue
            destinations.append(
                TravelDestinationViewModel(
                    location_id=option.group("location_id"),
                    name=option.group("name"),
                    location_type=option.group("location_type"),
                )
            )

        menu_items = self._menu_items(destinations)
        selection = self._navigation.initial_selection(menu_items, selected_index)
        return TravelScreenViewModel(
            title="移動",
            current_location_id=current_location_id,
            current_location_name=current_location_name,
            destinations=tuple(destinations),
            selection=selection,
        )

    @staticmethod
    def menu_items(view: TravelScreenViewModel) -> tuple[MenuItemViewModel, ...]:
        return TravelScreenPresenter._menu_items(view.destinations)

    @staticmethod
    def _menu_items(
        destinations: tuple[TravelDestinationViewModel, ...] | list[TravelDestinationViewModel],
    ) -> tuple[MenuItemViewModel, ...]:
        return tuple(
            MenuItemViewModel(
                action_id=destination.location_id,
                label=f"{destination.name} [{destination.location_type}]",
            )
            for destination in destinations
        )


class TravelScreenController:
    def __init__(
        self,
        playable: PlayableSliceApplication,
        *,
        presenter: TravelScreenPresenter | None = None,
        navigation: MenuNavigationService | None = None,
    ) -> None:
        self._playable = playable
        self._navigation = navigation or MenuNavigationService()
        self._presenter = presenter or TravelScreenPresenter(self._navigation)
        self._selection = MenuSelectionState(selected_index=None)

    def current_view(self) -> TravelScreenViewModel:
        selected_index = self._selection.selected_index
        view = self._presenter.build(
            self._playable,
            selected_index=selected_index if selected_index is not None else 0,
        )
        self._selection = view.selection
        return view

    def handle_input(self, action: MenuInputAction) -> TravelScreenInteraction:
        view = self.current_view()
        navigation_result = self._navigation.apply(
            view.selection,
            self._presenter.menu_items(view),
            action,
        )
        self._selection = navigation_result.selection
        if navigation_result.cancelled:
            return TravelScreenInteraction(
                view=self.current_view(),
                cancel_requested=True,
            )
        if navigation_result.guide_requested:
            return TravelScreenInteraction(
                view=self.current_view(),
                logs=(
                    f"travel_guide:current={view.current_location_id}:destinations={len(view.destinations)}",
                ),
            )
        if navigation_result.confirmed_action_id is None:
            return TravelScreenInteraction(view=self.current_view())
        return self.activate_destination(navigation_result.confirmed_action_id)

    def activate_destination(self, location_id: str) -> TravelScreenInteraction:
        view = self.current_view()
        destination = next(
            (item for item in view.destinations if item.location_id == location_id),
            None,
        )
        if destination is None:
            return TravelScreenInteraction(
                view=view,
                logs=(f"travel_rejected:destination_not_available:{location_id}",),
                rejection_reason="destination_not_available",
            )
        try:
            logs = tuple(self._playable.travel_to(location_id))
        except ValueError as exc:
            return TravelScreenInteraction(
                view=view,
                logs=(f"travel_rejected:application:{location_id}:{exc}",),
                rejection_reason="application_rejected",
            )
        return TravelScreenInteraction(view=self.current_view(), logs=logs)
