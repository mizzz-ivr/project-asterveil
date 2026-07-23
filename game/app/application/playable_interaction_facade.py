from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from game.app.application.dialogue_event_models import DialogueEntry
    from game.app.application.playable_slice import PlayableSliceApplication


@dataclass(frozen=True)
class NpcSummary:
    npc_id: str
    npc_name: str
    location_id: str


@dataclass(frozen=True)
class DialogueChoiceSummary:
    choice_id: str
    text: str


@dataclass(frozen=True)
class DialogueState:
    success: bool
    code: str
    npc_id: str
    npc_name: str
    entry_id: str | None
    step_id: str | None
    speaker: str | None
    lines: tuple[str, ...]
    choices: tuple[DialogueChoiceSummary, ...] = tuple()
    completed: bool = False
    logs: tuple[str, ...] = tuple()


@dataclass(frozen=True)
class FieldEventSummary:
    event_id: str
    name: str
    description: str
    repeatable: bool
    is_completed: bool
    can_execute: bool
    reason_code: str


@dataclass(frozen=True)
class FieldEventChoiceSummary:
    choice_id: str
    text: str


@dataclass(frozen=True)
class FieldEventDetail:
    success: bool
    code: str
    event_id: str
    name: str
    description: str
    repeatable: bool
    is_completed: bool
    can_execute: bool
    reason_code: str
    choices: tuple[FieldEventChoiceSummary, ...] = tuple()


@dataclass(frozen=True)
class FieldEventExecutionResult:
    success: bool
    code: str
    event_id: str
    choice_id: str
    logs: tuple[str, ...] = tuple()


class PlayableInteractionFacade:
    """NPC会話とフィールドイベントを型付き契約で公開するApplication境界。"""

    def __init__(self, playable: PlayableSliceApplication) -> None:
        self._playable = playable

    def list_npcs(self) -> tuple[NpcSummary, ...]:
        if self._playable.quest_session is None:
            return tuple()
        location_id = self._playable.location_state.current_location_id
        return tuple(
            NpcSummary(
                npc_id=npc.npc_id,
                npc_name=npc.npc_name,
                location_id=npc.location_id,
            )
            for npc in self._playable._dialogue_service.list_npcs_by_location(location_id)
        )

    def start_dialogue(self, npc_id: str) -> DialogueState:
        if self._playable.quest_session is None:
            return self._dialogue_failure(npc_id, "game_not_started")

        resolved = self._playable._dialogue_service.resolve(
            npc_id=npc_id,
            current_location_id=self._playable.location_state.current_location_id,
            world_flags=self._playable.quest_session.world_flags,
            quest_states=self._playable.quest_session.quest_states,
        )
        if not resolved.success:
            return DialogueState(
                success=False,
                code=resolved.code,
                npc_id=resolved.npc_id,
                npc_name=resolved.npc_name,
                entry_id=resolved.matched_entry_id,
                step_id=None,
                speaker=None,
                lines=resolved.lines,
                completed=True,
                logs=resolved.lines,
            )

        start_logs = (
            f"dialogue_started:{resolved.npc_id}:{resolved.matched_entry_id or 'fallback'}",
        )
        entry = resolved.entry
        if entry is None or not entry.steps:
            finalize_logs = self._finalize_dialogue(
                npc_id=resolved.npc_id,
                source_id=resolved.matched_entry_id or resolved.npc_id,
            )
            return DialogueState(
                success=True,
                code=resolved.code,
                npc_id=resolved.npc_id,
                npc_name=resolved.npc_name,
                entry_id=resolved.matched_entry_id,
                step_id=None,
                speaker=resolved.npc_name,
                lines=resolved.lines,
                completed=True,
                logs=(*start_logs, *finalize_logs),
            )

        first_step = self._playable._dialogue_service.initial_step(entry)
        if first_step is None:
            return self._dialogue_failure(npc_id, "initial_step_not_found")
        return self._build_step_state(
            npc_id=resolved.npc_id,
            npc_name=resolved.npc_name,
            entry=entry,
            step_id=first_step.step_id,
            base_logs=start_logs,
        )

    def select_dialogue_choice(
        self,
        state: DialogueState,
        choice_id: str,
    ) -> DialogueState:
        if self._playable.quest_session is None:
            return self._dialogue_failure(state.npc_id, "game_not_started")
        if not state.success or state.completed:
            return self._dialogue_failure(state.npc_id, "dialogue_not_active")
        if state.entry_id is None or state.step_id is None:
            return self._dialogue_failure(state.npc_id, "dialogue_state_invalid")

        entry = self._find_entry(state.npc_id, state.entry_id)
        if entry is None:
            return self._dialogue_failure(state.npc_id, "entry_not_found")

        choice_result = self._playable._dialogue_service.apply_choice(
            entry=entry,
            step_id=state.step_id,
            choice_id=choice_id,
            world_flags=self._playable.quest_session.world_flags,
        )
        if not choice_result.success:
            return DialogueState(
                success=False,
                code=choice_result.code,
                npc_id=state.npc_id,
                npc_name=state.npc_name,
                entry_id=state.entry_id,
                step_id=state.step_id,
                speaker=state.speaker,
                lines=state.lines,
                choices=state.choices,
                completed=False,
                logs=(choice_result.code,),
            )

        logs: list[str] = [
            f"choice_selected:{state.step_id}:{choice_result.selected_choice_id}",
        ]
        for flag_id in choice_result.set_flags:
            self._playable.quest_session.world_flags.add(flag_id)
            logs.append(f"flag_set:{flag_id}")
        logs.extend(self._playable._evaluate_recipe_unlocks())

        should_end = False
        for effect in choice_result.effects:
            logs.extend(
                self._playable._run_dialogue_choice_effect(
                    effect.action_type,
                    effect.params,
                )
            )
            if effect.action_type == "end_dialogue":
                should_end = True

        if should_end or not choice_result.next_step_id:
            logs.extend(
                self._finalize_dialogue(
                    npc_id=state.npc_id,
                    source_id=state.entry_id,
                )
            )
            return DialogueState(
                success=True,
                code="completed",
                npc_id=state.npc_id,
                npc_name=state.npc_name,
                entry_id=state.entry_id,
                step_id=None,
                speaker=None,
                lines=tuple(),
                completed=True,
                logs=tuple(logs),
            )

        next_step = self._playable._dialogue_service.find_step(
            entry,
            choice_result.next_step_id,
        )
        if next_step is None:
            code = f"dialogue_choice_failed:next_step_not_found:{choice_result.next_step_id}"
            return DialogueState(
                success=False,
                code=code,
                npc_id=state.npc_id,
                npc_name=state.npc_name,
                entry_id=state.entry_id,
                step_id=state.step_id,
                speaker=state.speaker,
                lines=state.lines,
                choices=state.choices,
                completed=False,
                logs=(*logs, code),
            )

        next_state = self._build_step_state(
            npc_id=state.npc_id,
            npc_name=state.npc_name,
            entry=entry,
            step_id=next_step.step_id,
            base_logs=tuple(logs),
        )
        if not next_state.choices:
            finalize_logs = self._finalize_dialogue(
                npc_id=state.npc_id,
                source_id=state.entry_id,
            )
            return DialogueState(
                success=next_state.success,
                code="completed",
                npc_id=next_state.npc_id,
                npc_name=next_state.npc_name,
                entry_id=next_state.entry_id,
                step_id=next_state.step_id,
                speaker=next_state.speaker,
                lines=next_state.lines,
                completed=True,
                logs=(*next_state.logs, *finalize_logs),
            )
        return next_state

    def list_field_events(self) -> tuple[FieldEventSummary, ...]:
        if self._playable.quest_session is None:
            return tuple()
        statuses = self._playable._field_event_service.list_events_for_location(
            location_id=self._playable.location_state.current_location_id,
            world_flags=self._playable.quest_session.world_flags,
            completed_event_ids=self._playable.completed_field_event_ids,
        )
        return tuple(
            FieldEventSummary(
                event_id=status.event_id,
                name=status.name,
                description=status.description,
                repeatable=status.repeatable,
                is_completed=status.is_completed,
                can_execute=status.can_execute,
                reason_code=status.reason_code,
            )
            for status in statuses
        )

    def field_event_detail(self, event_id: str) -> FieldEventDetail:
        summary = next(
            (item for item in self.list_field_events() if item.event_id == event_id),
            None,
        )
        if summary is None:
            return FieldEventDetail(
                success=False,
                code="event_not_available",
                event_id=event_id,
                name=event_id,
                description="",
                repeatable=False,
                is_completed=False,
                can_execute=False,
                reason_code="event_not_available",
            )
        event = self._playable._field_event_service.definitions.get(event_id)
        if event is None:
            return FieldEventDetail(
                success=False,
                code="event_definition_missing",
                event_id=event_id,
                name=summary.name,
                description=summary.description,
                repeatable=summary.repeatable,
                is_completed=summary.is_completed,
                can_execute=False,
                reason_code="event_definition_missing",
            )
        return FieldEventDetail(
            success=summary.can_execute,
            code="ok" if summary.can_execute else summary.reason_code,
            event_id=summary.event_id,
            name=summary.name,
            description=summary.description,
            repeatable=summary.repeatable,
            is_completed=summary.is_completed,
            can_execute=summary.can_execute,
            reason_code=summary.reason_code,
            choices=tuple(
                FieldEventChoiceSummary(choice_id=choice.choice_id, text=choice.text)
                for choice in event.choices
            ),
        )

    def execute_field_event_choice(
        self,
        event_id: str,
        choice_id: str,
    ) -> FieldEventExecutionResult:
        if self._playable.quest_session is None:
            return FieldEventExecutionResult(
                success=False,
                code="game_not_started",
                event_id=event_id,
                choice_id=choice_id,
            )
        validation = self._playable._field_event_service.resolve_choice(
            event_id=event_id,
            choice_id=choice_id,
            location_id=self._playable.location_state.current_location_id,
            world_flags=self._playable.quest_session.world_flags,
            completed_event_ids=self._playable.completed_field_event_ids,
        )
        if not validation.success:
            return FieldEventExecutionResult(
                success=False,
                code=validation.code,
                event_id=event_id,
                choice_id=choice_id,
                logs=(validation.code,),
            )
        logs = tuple(self._playable.resolve_field_event_choice(event_id, choice_id))
        return FieldEventExecutionResult(
            success=True,
            code="ok",
            event_id=event_id,
            choice_id=choice_id,
            logs=logs,
        )

    def _build_step_state(
        self,
        *,
        npc_id: str,
        npc_name: str,
        entry: DialogueEntry,
        step_id: str,
        base_logs: tuple[str, ...],
    ) -> DialogueState:
        if self._playable.quest_session is None:
            return self._dialogue_failure(npc_id, "game_not_started")
        step = self._playable._dialogue_service.find_step(entry, step_id)
        if step is None:
            return self._dialogue_failure(npc_id, "step_not_found")
        choices = self._playable._dialogue_service.available_choices(
            step,
            self._playable.quest_session.world_flags,
        )
        return DialogueState(
            success=True,
            code="ok",
            npc_id=npc_id,
            npc_name=npc_name,
            entry_id=entry.entry_id,
            step_id=step.step_id,
            speaker=step.speaker,
            lines=step.lines,
            choices=tuple(
                DialogueChoiceSummary(choice_id=choice.choice_id, text=choice.text)
                for choice in choices
            ),
            completed=False,
            logs=base_logs,
        )

    def _find_entry(self, npc_id: str, entry_id: str) -> DialogueEntry | None:
        definition = self._playable._dialogue_service.npc_definitions.get(npc_id)
        if definition is None:
            return None
        return next(
            (entry for entry in definition.dialogue_entries if entry.entry_id == entry_id),
            None,
        )

    def _finalize_dialogue(self, *, npc_id: str, source_id: str) -> tuple[str, ...]:
        logs = list(self._playable._apply_recipe_discovery("dialogue_event", source_id))
        if npc_id in self._playable._workshop_npc_ids:
            logs.extend(self._playable._advance_workshop_story(npc_id))
            logs.extend(self._playable.workshop_set_bonus_guidance_lines())
            logs.extend(self._playable.workshop_salvage_guidance_lines())
            logs.extend(self._playable.workshop_recipe_lines(npc_id))
            logs.extend(self._playable.workshop_progress_lines())
            logs.extend(self._playable._advance_workshop_special_chain())
            logs.extend(self._playable._update_endgame_repeatable_orders())
            logs.extend(self._playable.endgame_repeatable_order_lines())
            logs.extend(self._playable.workshop_equipment_upgrade_lines())
            logs.extend(self._playable.workshop_equipment_salvage_lines())
        return tuple(logs)

    @staticmethod
    def _dialogue_failure(npc_id: str, code: str) -> DialogueState:
        return DialogueState(
            success=False,
            code=code,
            npc_id=npc_id,
            npc_name=npc_id,
            entry_id=None,
            step_id=None,
            speaker=None,
            lines=(f"dialogue_rejected:{npc_id}:{code}",),
            completed=True,
            logs=(f"dialogue_rejected:{npc_id}:{code}",),
        )
