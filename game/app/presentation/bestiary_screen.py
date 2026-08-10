from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from game.app.application.bestiary_service import (
    BestiaryEntryView,
    BestiaryProgressSummary,
    BestiaryUnlockStage,
)
from game.app.presentation.input_actions import MenuInputAction
from game.app.presentation.menu_view_model import (
    MenuItemViewModel,
    MenuNavigationService,
    MenuSelectionState,
)


class BestiaryScreenMode(str, Enum):
    LIST = "list"
    DETAIL = "detail"


class BestiaryCategoryFilter(str, Enum):
    ALL = "all"
    NORMAL = "normal"
    BOSS = "boss"


@dataclass(frozen=True)
class BestiaryProgressViewModel:
    category: str
    label: str
    total_count: int
    encountered_count: int
    defeated_count: int
    mastered_count: int
    encounter_rate_percent: int
    mastery_rate_percent: int


@dataclass(frozen=True)
class BestiaryFilterViewModel:
    action_id: str
    category_filter: BestiaryCategoryFilter
    label: str
    is_active: bool


@dataclass(frozen=True)
class BestiaryListEntryViewModel:
    action_id: str
    slot_label: str
    name: str
    stage: BestiaryUnlockStage
    stage_label: str
    category_label: str | None
    encounter_count: int
    battle_win_count: int
    kill_count: int
    battle_loss_count: int


@dataclass(frozen=True)
class BestiaryDetailViewModel:
    action_id: str
    name: str
    stage: BestiaryUnlockStage
    stage_label: str
    category_label: str | None
    habitat_names: tuple[str, ...]
    level: int | None
    stats: tuple[tuple[str, int], ...]
    weakness_elements: tuple[str, ...]
    weakness_weapon_types: tuple[str, ...]
    description: str | None
    encounter_count: int
    battle_win_count: int
    kill_count: int
    battle_loss_count: int


@dataclass(frozen=True)
class BestiaryScreenViewModel:
    title: str
    mode: BestiaryScreenMode
    active_filter: BestiaryCategoryFilter
    progress: tuple[BestiaryProgressViewModel, ...]
    filters: tuple[BestiaryFilterViewModel, ...]
    entries: tuple[BestiaryListEntryViewModel, ...]
    detail: BestiaryDetailViewModel | None
    selection: MenuSelectionState


@dataclass(frozen=True)
class BestiaryScreenInteraction:
    view: BestiaryScreenViewModel
    logs: tuple[str, ...] = tuple()
    cancel_requested: bool = False
    rejection_reason: str | None = None


class BestiaryScreenController:
    """図鑑一覧・カテゴリ切替・詳細閲覧を意味入力だけで扱う。"""

    FILTER_ACTION_PREFIX = "bestiary.filter."
    ENTRY_ACTION_PREFIX = "bestiary.slot."

    def __init__(
        self,
        playable: object,
        *,
        navigation: MenuNavigationService | None = None,
    ) -> None:
        self._playable = playable
        self._navigation = navigation or MenuNavigationService()
        self._mode = BestiaryScreenMode.LIST
        self._active_filter = BestiaryCategoryFilter.ALL
        self._selection = MenuSelectionState(selected_index=None)
        self._detail_enemy_id: str | None = None

    def current_view(self) -> BestiaryScreenViewModel:
        progress = tuple(self._to_progress_view(item) for item in self._progress())
        filters = self._filter_views()
        entries = self._list_entry_views()

        if self._mode == BestiaryScreenMode.DETAIL:
            if self._detail_enemy_id is None:
                raise ValueError("bestiary_detail_enemy_missing")
            return BestiaryScreenViewModel(
                title="モンスター図鑑",
                mode=self._mode,
                active_filter=self._active_filter,
                progress=progress,
                filters=filters,
                entries=tuple(),
                detail=self._detail_view(self._detail_enemy_id),
                selection=MenuSelectionState(selected_index=None),
            )

        menu_items = self._menu_items(filters, entries)
        preferred_index = self._selection.selected_index
        selection = self._navigation.initial_selection(
            menu_items,
            preferred_index if preferred_index is not None else 0,
        )
        self._selection = selection
        return BestiaryScreenViewModel(
            title="モンスター図鑑",
            mode=self._mode,
            active_filter=self._active_filter,
            progress=progress,
            filters=filters,
            entries=entries,
            detail=None,
            selection=selection,
        )

    def handle_input(self, action: MenuInputAction) -> BestiaryScreenInteraction:
        if self._mode == BestiaryScreenMode.DETAIL:
            view = self.current_view()
            if action == MenuInputAction.CANCEL:
                self._mode = BestiaryScreenMode.LIST
                self._detail_enemy_id = None
                return BestiaryScreenInteraction(
                    view=self.current_view(),
                    logs=("bestiary_detail_closed",),
                )
            if action == MenuInputAction.SHOW_GUIDE:
                detail = view.detail
                stage = detail.stage.value if detail is not None else "unknown"
                return BestiaryScreenInteraction(
                    view=view,
                    logs=(f"bestiary_guide:mode=detail:stage={stage}",),
                )
            return BestiaryScreenInteraction(view=view)

        view = self.current_view()
        menu_items = self._menu_items(view.filters, view.entries)
        result = self._navigation.apply(view.selection, menu_items, action)
        self._selection = result.selection
        if result.cancelled:
            return BestiaryScreenInteraction(
                view=self.current_view(),
                cancel_requested=True,
            )
        if result.guide_requested:
            return BestiaryScreenInteraction(
                view=self.current_view(),
                logs=(
                    "bestiary_guide:mode=list:"
                    f"filter={self._active_filter.value}:visible={len(view.entries)}",
                ),
            )
        if result.confirmed_action_id is None:
            return BestiaryScreenInteraction(view=self.current_view())
        return self.activate_entry(result.confirmed_action_id)

    def activate_entry(self, action_id: str) -> BestiaryScreenInteraction:
        normalized = action_id.strip()
        filter_value = self._filter_from_action(normalized)
        if filter_value is not None:
            self._active_filter = filter_value
            self._selection = MenuSelectionState(
                selected_index=list(BestiaryCategoryFilter).index(filter_value)
            )
            return BestiaryScreenInteraction(
                view=self.current_view(),
                logs=(f"bestiary_filter_changed:{filter_value.value}",),
            )

        source = self._source_by_public_action_id().get(normalized)
        if source is None:
            return BestiaryScreenInteraction(
                view=self.current_view(),
                logs=(f"bestiary_entry_rejected:not_available:{normalized}",),
                rejection_reason="bestiary_entry_not_available",
            )

        self._detail_enemy_id = source.enemy_id
        self._mode = BestiaryScreenMode.DETAIL
        return BestiaryScreenInteraction(
            view=self.current_view(),
            logs=(f"bestiary_detail_opened:{normalized}",),
        )

    def _progress(self) -> tuple[BestiaryProgressSummary, ...]:
        operation = self._require_operation("bestiary_progress")
        result = operation()
        if not isinstance(result, tuple) or not all(
            isinstance(item, BestiaryProgressSummary) for item in result
        ):
            raise ValueError("bestiary_progress_contract_invalid")
        return result

    def _entries(self) -> tuple[BestiaryEntryView, ...]:
        operation = self._require_operation("bestiary_entries")
        result = operation()
        if not isinstance(result, tuple) or not all(
            isinstance(item, BestiaryEntryView) for item in result
        ):
            raise ValueError("bestiary_entries_contract_invalid")
        return result

    def _entry(self, enemy_id: str) -> BestiaryEntryView:
        operation = self._require_operation("bestiary_entry")
        result = operation(enemy_id)
        if not isinstance(result, BestiaryEntryView):
            raise ValueError("bestiary_entry_contract_invalid")
        return result

    def _require_operation(self, name: str) -> Callable[..., object]:
        operation = getattr(self._playable, name, None)
        if not callable(operation):
            raise ValueError(f"bestiary_capability_not_available:{name}")
        return operation

    def _filter_views(self) -> tuple[BestiaryFilterViewModel, ...]:
        return tuple(
            BestiaryFilterViewModel(
                action_id=f"{self.FILTER_ACTION_PREFIX}{item.value}",
                category_filter=item,
                label=self._filter_label(item),
                is_active=item == self._active_filter,
            )
            for item in BestiaryCategoryFilter
        )

    def _list_entry_views(self) -> tuple[BestiaryListEntryViewModel, ...]:
        rows: list[BestiaryListEntryViewModel] = []
        for slot_index, entry in enumerate(self._entries(), start=1):
            if not self._matches_filter(entry):
                continue
            rows.append(
                BestiaryListEntryViewModel(
                    action_id=self._public_action_id(slot_index),
                    slot_label=f"No.{slot_index:03d}",
                    name=entry.display_name or "？？？",
                    stage=entry.stage,
                    stage_label=self._stage_label(entry.stage),
                    category_label=(
                        self._category_label(entry.category)
                        if entry.stage != BestiaryUnlockStage.UNKNOWN
                        else None
                    ),
                    encounter_count=entry.encounter_count,
                    battle_win_count=entry.battle_win_count,
                    kill_count=entry.kill_count,
                    battle_loss_count=entry.battle_loss_count,
                )
            )
        return tuple(rows)

    def _detail_view(self, enemy_id: str) -> BestiaryDetailViewModel:
        entry = self._entry(enemy_id)
        action_id = next(
            (
                self._public_action_id(index)
                for index, item in enumerate(self._entries(), start=1)
                if item.enemy_id == enemy_id
            ),
            None,
        )
        if action_id is None:
            raise ValueError("bestiary_detail_enemy_not_in_catalog")
        return BestiaryDetailViewModel(
            action_id=action_id,
            name=entry.display_name or "？？？",
            stage=entry.stage,
            stage_label=self._stage_label(entry.stage),
            category_label=(
                self._category_label(entry.category)
                if entry.stage != BestiaryUnlockStage.UNKNOWN
                else None
            ),
            habitat_names=entry.habitat_names,
            level=entry.level,
            stats=tuple(sorted((entry.stats or {}).items())),
            weakness_elements=entry.weakness_elements,
            weakness_weapon_types=entry.weakness_weapon_types,
            description=entry.description,
            encounter_count=entry.encounter_count,
            battle_win_count=entry.battle_win_count,
            kill_count=entry.kill_count,
            battle_loss_count=entry.battle_loss_count,
        )

    def _source_by_public_action_id(self) -> dict[str, BestiaryEntryView]:
        result: dict[str, BestiaryEntryView] = {}
        for slot_index, entry in enumerate(self._entries(), start=1):
            if self._matches_filter(entry):
                result[self._public_action_id(slot_index)] = entry
        return result

    def _matches_filter(self, entry: BestiaryEntryView) -> bool:
        if self._active_filter == BestiaryCategoryFilter.ALL:
            return True
        if entry.stage == BestiaryUnlockStage.UNKNOWN:
            # 未遭遇Enemyのカテゴリをフィルター結果から推測できないようにする。
            return False
        return entry.category == self._active_filter.value

    @classmethod
    def _menu_items(
        cls,
        filters: tuple[BestiaryFilterViewModel, ...],
        entries: tuple[BestiaryListEntryViewModel, ...],
    ) -> tuple[MenuItemViewModel, ...]:
        return tuple(
            [
                MenuItemViewModel(
                    action_id=item.action_id,
                    label=item.label,
                    is_recommended=item.is_active,
                )
                for item in filters
            ]
            + [
                MenuItemViewModel(
                    action_id=item.action_id,
                    label=f"{item.slot_label} {item.name} [{item.stage_label}]",
                )
                for item in entries
            ]
        )

    @classmethod
    def _filter_from_action(
        cls,
        action_id: str,
    ) -> BestiaryCategoryFilter | None:
        if not action_id.startswith(cls.FILTER_ACTION_PREFIX):
            return None
        raw = action_id.removeprefix(cls.FILTER_ACTION_PREFIX)
        try:
            return BestiaryCategoryFilter(raw)
        except ValueError:
            return None

    @classmethod
    def _public_action_id(cls, slot_index: int) -> str:
        return f"{cls.ENTRY_ACTION_PREFIX}{slot_index:03d}"

    @staticmethod
    def _to_progress_view(summary: BestiaryProgressSummary) -> BestiaryProgressViewModel:
        label = {
            "overall": "全体",
            "normal": "通常敵",
            "boss": "Boss",
        }.get(summary.category, summary.category)
        return BestiaryProgressViewModel(
            category=summary.category,
            label=label,
            total_count=summary.total_count,
            encountered_count=summary.encountered_count,
            defeated_count=summary.defeated_count,
            mastered_count=summary.mastered_count,
            encounter_rate_percent=summary.encounter_rate_percent,
            mastery_rate_percent=summary.mastery_rate_percent,
        )

    @staticmethod
    def _stage_label(stage: BestiaryUnlockStage) -> str:
        return {
            BestiaryUnlockStage.UNKNOWN: "未遭遇",
            BestiaryUnlockStage.ENCOUNTERED: "遭遇済み",
            BestiaryUnlockStage.DEFEATED: "討伐済み",
            BestiaryUnlockStage.MASTERED: "熟練",
        }[stage]

    @staticmethod
    def _category_label(category: str) -> str:
        return {
            "normal": "通常敵",
            "boss": "Boss",
        }.get(category, category)

    @staticmethod
    def _filter_label(category_filter: BestiaryCategoryFilter) -> str:
        return {
            BestiaryCategoryFilter.ALL: "すべて",
            BestiaryCategoryFilter.NORMAL: "通常敵",
            BestiaryCategoryFilter.BOSS: "Boss",
        }[category_filter]
