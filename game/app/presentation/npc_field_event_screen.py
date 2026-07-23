from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from game.app.application.playable_interaction_facade import (
    DialogueState,
    FieldEventDetail,
    FieldEventSummary,
    NpcSummary,
    PlayableInteractionFacade,
)
from game.app.presentation.input_actions import MenuInputAction
from game.app.presentation.menu_view_model import (
    MenuItemViewModel,
    MenuNavigationService,
    MenuSelectionState,
)


class NpcDialogueScreenMode(str, Enum):
    NPC_LIST = "npc_list"
    DIALOGUE = "dialogue"


@dataclass(frozen=True)
class NpcDialogueScreenViewModel:
    title: str
    mode: NpcDialogueScreenMode
    npcs: tuple[NpcSummary, ...]
    dialogue: DialogueState | None
    selection: MenuSelectionState


@dataclass(frozen=True)
class NpcDialogueScreenInteraction:
    view: NpcDialogueScreenViewModel
    logs: tuple[str, ...] = tuple()
    cancel_requested: bool = False
    rejection_reason: str | None = None


class NpcDialogueScreenController:
    def __init__(
        self,
        facade: PlayableInteractionFacade,
        *,
        navigation: MenuNavigationService | None = None,
    ) -> None:
        self._facade = facade
        self._navigation = navigation or MenuNavigationService()
        self._dialogue: DialogueState | None = None
        self._selection = MenuSelectionState(selected_index=None)

    def current_view(self) -> NpcDialogueScreenViewModel:
        if self._dialogue is None:
            npcs = self._facade.list_npcs()
            items = self._npc_items(npcs)
            selection = self._navigation.initial_selection(
                items,
                self._selection.selected_index or 0,
            )
            self._selection = selection
            return NpcDialogueScreenViewModel(
                title="NPC会話",
                mode=NpcDialogueScreenMode.NPC_LIST,
                npcs=npcs,
                dialogue=None,
                selection=selection,
            )

        items = self._choice_items(self._dialogue)
        selection = self._navigation.initial_selection(
            items,
            self._selection.selected_index or 0,
        )
        self._selection = selection
        return NpcDialogueScreenViewModel(
            title=self._dialogue.npc_name,
            mode=NpcDialogueScreenMode.DIALOGUE,
            npcs=tuple(),
            dialogue=self._dialogue,
            selection=selection,
        )

    def handle_input(self, action: MenuInputAction) -> NpcDialogueScreenInteraction:
        view = self.current_view()
        if view.mode == NpcDialogueScreenMode.NPC_LIST:
            return self._handle_npc_list_input(view, action)
        return self._handle_dialogue_input(view, action)

    def activate_npc(self, npc_id: str) -> NpcDialogueScreenInteraction:
        view = self.current_view()
        npc = next((item for item in view.npcs if item.npc_id == npc_id), None)
        if npc is None:
            return NpcDialogueScreenInteraction(
                view=view,
                logs=(f"dialogue_rejected:{npc_id}:npc_not_available",),
                rejection_reason="npc_not_available",
            )
        self._dialogue = self._facade.start_dialogue(npc_id)
        self._selection = MenuSelectionState(selected_index=None)
        if not self._dialogue.success:
            failed = self._dialogue
            self._dialogue = None
            return NpcDialogueScreenInteraction(
                view=self.current_view(),
                logs=failed.logs,
                rejection_reason=failed.code,
            )
        return NpcDialogueScreenInteraction(
            view=self.current_view(),
            logs=self._dialogue.logs,
        )

    def activate_choice(self, choice_id: str) -> NpcDialogueScreenInteraction:
        if self._dialogue is None:
            return NpcDialogueScreenInteraction(
                view=self.current_view(),
                logs=(f"dialogue_choice_rejected:{choice_id}:dialogue_not_active",),
                rejection_reason="dialogue_not_active",
            )
        if choice_id not in {choice.choice_id for choice in self._dialogue.choices}:
            return NpcDialogueScreenInteraction(
                view=self.current_view(),
                logs=(f"dialogue_choice_rejected:{choice_id}:choice_not_available",),
                rejection_reason="choice_not_available",
            )
        self._dialogue = self._facade.select_dialogue_choice(
            self._dialogue,
            choice_id,
        )
        self._selection = MenuSelectionState(selected_index=None)
        if not self._dialogue.success:
            return NpcDialogueScreenInteraction(
                view=self.current_view(),
                logs=self._dialogue.logs,
                rejection_reason=self._dialogue.code,
            )
        return NpcDialogueScreenInteraction(
            view=self.current_view(),
            logs=self._dialogue.logs,
        )

    def close_dialogue(self) -> NpcDialogueScreenInteraction:
        self._dialogue = None
        self._selection = MenuSelectionState(selected_index=None)
        return NpcDialogueScreenInteraction(view=self.current_view())

    def _handle_npc_list_input(
        self,
        view: NpcDialogueScreenViewModel,
        action: MenuInputAction,
    ) -> NpcDialogueScreenInteraction:
        result = self._navigation.apply(
            view.selection,
            self._npc_items(view.npcs),
            action,
        )
        self._selection = result.selection
        if result.cancelled:
            return NpcDialogueScreenInteraction(
                view=self.current_view(),
                cancel_requested=True,
            )
        if result.guide_requested:
            return NpcDialogueScreenInteraction(
                view=self.current_view(),
                logs=(f"npc_dialogue_guide:npcs={len(view.npcs)}",),
            )
        if result.confirmed_action_id is None:
            return NpcDialogueScreenInteraction(view=self.current_view())
        return self.activate_npc(result.confirmed_action_id)

    def _handle_dialogue_input(
        self,
        view: NpcDialogueScreenViewModel,
        action: MenuInputAction,
    ) -> NpcDialogueScreenInteraction:
        dialogue = view.dialogue
        if dialogue is None:
            return self.close_dialogue()
        if action == MenuInputAction.CANCEL:
            return self.close_dialogue()
        if action == MenuInputAction.SHOW_GUIDE:
            return NpcDialogueScreenInteraction(
                view=view,
                logs=(
                    f"dialogue_guide:npc={dialogue.npc_id}:choices={len(dialogue.choices)}:completed={dialogue.completed}",
                ),
            )
        if dialogue.completed or not dialogue.choices:
            if action == MenuInputAction.CONFIRM:
                return self.close_dialogue()
            return NpcDialogueScreenInteraction(view=view)
        result = self._navigation.apply(
            view.selection,
            self._choice_items(dialogue),
            action,
        )
        self._selection = result.selection
        if result.confirmed_action_id is None:
            return NpcDialogueScreenInteraction(view=self.current_view())
        return self.activate_choice(result.confirmed_action_id)

    @staticmethod
    def _npc_items(npcs: tuple[NpcSummary, ...]) -> tuple[MenuItemViewModel, ...]:
        return tuple(
            MenuItemViewModel(action_id=npc.npc_id, label=npc.npc_name)
            for npc in npcs
        )

    @staticmethod
    def _choice_items(dialogue: DialogueState) -> tuple[MenuItemViewModel, ...]:
        return tuple(
            MenuItemViewModel(action_id=choice.choice_id, label=choice.text)
            for choice in dialogue.choices
        )


class FieldEventScreenMode(str, Enum):
    EVENT_LIST = "event_list"
    CHOICE_LIST = "choice_list"


@dataclass(frozen=True)
class FieldEventScreenViewModel:
    title: str
    mode: FieldEventScreenMode
    events: tuple[FieldEventSummary, ...]
    detail: FieldEventDetail | None
    selection: MenuSelectionState


@dataclass(frozen=True)
class FieldEventScreenInteraction:
    view: FieldEventScreenViewModel
    logs: tuple[str, ...] = tuple()
    cancel_requested: bool = False
    rejection_reason: str | None = None


class FieldEventScreenController:
    def __init__(
        self,
        facade: PlayableInteractionFacade,
        *,
        navigation: MenuNavigationService | None = None,
    ) -> None:
        self._facade = facade
        self._navigation = navigation or MenuNavigationService()
        self._detail: FieldEventDetail | None = None
        self._selection = MenuSelectionState(selected_index=None)

    def current_view(self) -> FieldEventScreenViewModel:
        if self._detail is None:
            events = self._facade.list_field_events()
            selection = self._navigation.initial_selection(
                self._event_items(events),
                self._selection.selected_index or 0,
            )
            self._selection = selection
            return FieldEventScreenViewModel(
                title="フィールドイベント",
                mode=FieldEventScreenMode.EVENT_LIST,
                events=events,
                detail=None,
                selection=selection,
            )

        selection = self._navigation.initial_selection(
            self._choice_items(self._detail),
            self._selection.selected_index or 0,
        )
        self._selection = selection
        return FieldEventScreenViewModel(
            title=self._detail.name,
            mode=FieldEventScreenMode.CHOICE_LIST,
            events=tuple(),
            detail=self._detail,
            selection=selection,
        )

    def handle_input(self, action: MenuInputAction) -> FieldEventScreenInteraction:
        view = self.current_view()
        if view.mode == FieldEventScreenMode.EVENT_LIST:
            return self._handle_event_list_input(view, action)
        return self._handle_choice_input(view, action)

    def activate_event(self, event_id: str) -> FieldEventScreenInteraction:
        detail = self._facade.field_event_detail(event_id)
        if not detail.success:
            return FieldEventScreenInteraction(
                view=self.current_view(),
                logs=(f"field_event_rejected:{event_id}:{detail.code}",),
                rejection_reason=detail.code,
            )
        self._detail = detail
        self._selection = MenuSelectionState(selected_index=None)
        return FieldEventScreenInteraction(view=self.current_view())

    def activate_choice(self, choice_id: str) -> FieldEventScreenInteraction:
        if self._detail is None:
            return FieldEventScreenInteraction(
                view=self.current_view(),
                logs=(f"field_event_choice_rejected:{choice_id}:event_not_active",),
                rejection_reason="event_not_active",
            )
        if choice_id not in {choice.choice_id for choice in self._detail.choices}:
            return FieldEventScreenInteraction(
                view=self.current_view(),
                logs=(f"field_event_choice_rejected:{choice_id}:choice_not_available",),
                rejection_reason="choice_not_available",
            )
        result = self._facade.execute_field_event_choice(
            self._detail.event_id,
            choice_id,
        )
        if not result.success:
            return FieldEventScreenInteraction(
                view=self.current_view(),
                logs=result.logs,
                rejection_reason=result.code,
            )
        self._detail = None
        self._selection = MenuSelectionState(selected_index=None)
        return FieldEventScreenInteraction(
            view=self.current_view(),
            logs=result.logs,
        )

    def close_detail(self) -> FieldEventScreenInteraction:
        self._detail = None
        self._selection = MenuSelectionState(selected_index=None)
        return FieldEventScreenInteraction(view=self.current_view())

    def _handle_event_list_input(
        self,
        view: FieldEventScreenViewModel,
        action: MenuInputAction,
    ) -> FieldEventScreenInteraction:
        result = self._navigation.apply(
            view.selection,
            self._event_items(view.events),
            action,
        )
        self._selection = result.selection
        if result.cancelled:
            return FieldEventScreenInteraction(
                view=self.current_view(),
                cancel_requested=True,
            )
        if result.guide_requested:
            executable = sum(1 for event in view.events if event.can_execute)
            return FieldEventScreenInteraction(
                view=self.current_view(),
                logs=(f"field_event_guide:events={len(view.events)}:executable={executable}",),
            )
        if result.confirmed_action_id is None:
            return FieldEventScreenInteraction(view=self.current_view())
        return self.activate_event(result.confirmed_action_id)

    def _handle_choice_input(
        self,
        view: FieldEventScreenViewModel,
        action: MenuInputAction,
    ) -> FieldEventScreenInteraction:
        detail = view.detail
        if detail is None:
            return self.close_detail()
        if action == MenuInputAction.CANCEL:
            return self.close_detail()
        if action == MenuInputAction.SHOW_GUIDE:
            return FieldEventScreenInteraction(
                view=view,
                logs=(f"field_event_choice_guide:event={detail.event_id}:choices={len(detail.choices)}",),
            )
        result = self._navigation.apply(
            view.selection,
            self._choice_items(detail),
            action,
        )
        self._selection = result.selection
        if result.confirmed_action_id is None:
            return FieldEventScreenInteraction(view=self.current_view())
        return self.activate_choice(result.confirmed_action_id)

    @staticmethod
    def _event_items(
        events: tuple[FieldEventSummary, ...],
    ) -> tuple[MenuItemViewModel, ...]:
        return tuple(
            MenuItemViewModel(
                action_id=event.event_id,
                label=event.name,
                is_enabled=event.can_execute,
            )
            for event in events
        )

    @staticmethod
    def _choice_items(
        detail: FieldEventDetail,
    ) -> tuple[MenuItemViewModel, ...]:
        return tuple(
            MenuItemViewModel(action_id=choice.choice_id, label=choice.text)
            for choice in detail.choices
        )
