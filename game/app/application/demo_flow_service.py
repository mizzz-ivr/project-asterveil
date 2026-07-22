from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping

if TYPE_CHECKING:
    from game.app.application.playable_slice import PlayableSliceApplication


@dataclass(frozen=True)
class DemoFlowStepDefinition:
    step_id: str
    title: str
    guidance_text: str
    recommended_action: str
    completion_condition: Mapping[str, object]


@dataclass(frozen=True)
class DemoFlowDefinition:
    flow_id: str
    name: str
    description: str
    steps: tuple[DemoFlowStepDefinition, ...]


@dataclass(frozen=True)
class DemoFlowContext:
    quest_statuses: Mapping[str, str]
    world_flags: frozenset[str]
    current_location_id: str
    workshop_rank: int


@dataclass(frozen=True)
class DemoFlowProgress:
    flow_id: str
    completed_step_ids: tuple[str, ...]
    active_step: DemoFlowStepDefinition | None
    is_completed: bool


class DemoFlowService:
    """既存のゲーム状態からデモ進行を読み取り専用で導出する。"""

    _SUPPORTED_CONDITION_TYPES = {
        "all",
        "any",
        "world_flag",
        "quest_status",
        "current_location",
        "workshop_rank_at_least",
    }

    def __init__(self, definitions: Mapping[str, DemoFlowDefinition]) -> None:
        self._definitions = dict(definitions)
        if not self._definitions:
            raise ValueError("demo flow definitions must not be empty")

    @property
    def definitions(self) -> Mapping[str, DemoFlowDefinition]:
        return self._definitions

    def evaluate(self, flow_id: str, context: DemoFlowContext) -> DemoFlowProgress:
        definition = self._definitions.get(flow_id)
        if definition is None:
            raise ValueError(f"demo flow not found: {flow_id}")

        completed_step_ids: list[str] = []
        active_step: DemoFlowStepDefinition | None = None
        for step in definition.steps:
            if self._condition_met(step.completion_condition, context):
                completed_step_ids.append(step.step_id)
                continue
            active_step = step
            break

        return DemoFlowProgress(
            flow_id=flow_id,
            completed_step_ids=tuple(completed_step_ids),
            active_step=active_step,
            is_completed=active_step is None,
        )

    def guidance_lines(self, flow_id: str, context: DemoFlowContext) -> list[str]:
        definition = self._definitions.get(flow_id)
        if definition is None:
            raise ValueError(f"demo flow not found: {flow_id}")
        progress = self.evaluate(flow_id, context)
        lines = [
            f"demo_flow:{flow_id}:progress={len(progress.completed_step_ids)}/{len(definition.steps)}"
        ]
        if progress.is_completed:
            lines.append(f"demo_flow_completed:{flow_id}:{definition.name}")
            return lines

        step = progress.active_step
        if step is None:
            raise RuntimeError("incomplete demo flow must have an active step")
        lines.extend(
            [
                f"demo_flow_current_step:{step.step_id}:{step.title}",
                f"demo_flow_guidance:{step.step_id}:{step.guidance_text}",
                f"demo_flow_recommended_action:{step.step_id}:{step.recommended_action}",
            ]
        )
        return lines

    def _condition_met(self, condition: Mapping[str, object], context: DemoFlowContext) -> bool:
        condition_type = str(condition.get("type", ""))
        if condition_type not in self._SUPPORTED_CONDITION_TYPES:
            raise ValueError(f"unsupported demo flow condition type: {condition_type}")

        if condition_type in {"all", "any"}:
            children = condition.get("conditions")
            if not isinstance(children, list) or not children:
                raise ValueError(f"{condition_type} condition requires non-empty conditions")
            results = [self._condition_met(self._as_condition(child), context) for child in children]
            return all(results) if condition_type == "all" else any(results)

        if condition_type == "world_flag":
            return str(condition.get("flag", "")) in context.world_flags

        if condition_type == "quest_status":
            quest_id = str(condition.get("quest_id", ""))
            statuses = condition.get("statuses")
            if not isinstance(statuses, list):
                raise ValueError("quest_status condition requires statuses")
            return context.quest_statuses.get(quest_id, "not_accepted") in {
                str(status) for status in statuses
            }

        if condition_type == "current_location":
            return context.current_location_id == str(condition.get("location_id", ""))

        if condition_type == "workshop_rank_at_least":
            try:
                minimum_rank = int(condition.get("rank", 0))
            except (TypeError, ValueError) as exc:
                raise ValueError("workshop_rank_at_least condition requires an integer rank") from exc
            return context.workshop_rank >= minimum_rank

        raise AssertionError(f"unreachable condition type: {condition_type}")

    @staticmethod
    def _as_condition(value: object) -> Mapping[str, object]:
        if not isinstance(value, dict):
            raise ValueError("nested demo flow condition must be an object")
        return value


class SteamDemoApplication:
    """PlayableSliceApplicationを変更せず、Steamデモの案内だけを合成する。"""

    WORKSHOP_CHECKED_FLAG = "flag.demo.steam.workshop_checked"
    CHECKPOINT_SAVED_FLAG = "flag.demo.steam.checkpoint_saved"

    def __init__(
        self,
        playable: PlayableSliceApplication,
        flow_service: DemoFlowService,
        flow_id: str,
    ) -> None:
        if flow_id not in flow_service.definitions:
            raise ValueError(f"demo flow not found: {flow_id}")
        self.playable = playable
        self.flow_service = flow_service
        self.flow_id = flow_id

    def context(self) -> DemoFlowContext:
        if self.playable.quest_session is None:
            raise ValueError("ゲームが開始されていません。")
        quest_statuses = {
            quest_id: state.status.value
            for quest_id, state in self.playable.quest_session.quest_states.items()
        }
        workshop_rank = int(getattr(self.playable.workshop_progress_state, "level", 1))
        return DemoFlowContext(
            quest_statuses=quest_statuses,
            world_flags=frozenset(self.playable.quest_session.world_flags),
            current_location_id=self.playable.location_state.current_location_id,
            workshop_rank=workshop_rank,
        )

    def progress(self) -> DemoFlowProgress:
        return self.flow_service.evaluate(self.flow_id, self.context())

    def guidance_lines(self) -> list[str]:
        return self.flow_service.guidance_lines(self.flow_id, self.context())

    def inspect_workshop(self) -> list[str]:
        if self.playable.quest_session is None:
            raise ValueError("ゲームが開始されていません。")
        progress = self.progress()
        lines = self.playable.crafting_recipe_lines()
        if progress.active_step is None or progress.active_step.recommended_action != "inspect_workshop":
            active_step_id = progress.active_step.step_id if progress.active_step else "completed"
            return [f"demo_workshop_checked_out_of_order:active={active_step_id}", *lines]

        self.playable.quest_session.world_flags.add(self.WORKSHOP_CHECKED_FLAG)
        return ["demo_workshop_checked", *lines]

    def save_checkpoint(self) -> list[str]:
        if self.playable.quest_session is None:
            raise ValueError("ゲームが開始されていません。")
        progress = self.progress()
        if progress.active_step is None or progress.active_step.recommended_action != "save":
            active_step_id = progress.active_step.step_id if progress.active_step else "completed"
            self.playable.save_game()
            return [f"demo_checkpoint_saved_out_of_order:active={active_step_id}", "save_completed"]

        self.playable.quest_session.world_flags.add(self.CHECKPOINT_SAVED_FLAG)
        self.playable.save_game()
        return ["demo_checkpoint_saved", "save_completed", *self.guidance_lines()]
