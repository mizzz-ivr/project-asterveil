from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EndgameOrderObjectiveDefinition:
    objective_id: str
    objective_type: str
    description: str
    requirements: dict[str, str]


@dataclass(frozen=True)
class EndgameRepeatableOrderDefinition:
    order_id: str
    name: str
    description: str
    required_unlock_flags: tuple[str, ...]
    required_workshop_level: int
    repeatable: bool
    repeat_reset_rule: str
    objectives: tuple[EndgameOrderObjectiveDefinition, ...]
    rewards: dict[str, int]
    reward_category: str


@dataclass
class EndgameRepeatableOrderState:
    unlocked_order_ids: set[str] | None = None
    active_order_id: str | None = None
    completed_order_ids_in_cycle: set[str] | None = None
    objective_progress: dict[str, int] | None = None
    completion_counts: dict[str, int] | None = None
    rewarded_cycle_ids: set[str] | None = None
    ready_to_reaccept_order_ids: set[str] | None = None

    def __post_init__(self) -> None:
        self.unlocked_order_ids = self.unlocked_order_ids or set()
        self.completed_order_ids_in_cycle = self.completed_order_ids_in_cycle or set()
        self.objective_progress = self.objective_progress or {}
        self.completion_counts = self.completion_counts or {}
        self.rewarded_cycle_ids = self.rewarded_cycle_ids or set()
        self.ready_to_reaccept_order_ids = self.ready_to_reaccept_order_ids or set()


class EndgameRepeatableOrderService:
    def unlock_available(self, *, state: EndgameRepeatableOrderState, definitions: tuple[EndgameRepeatableOrderDefinition, ...], workshop_level: int, world_flags: set[str]) -> list[str]:
        logs: list[str] = []
        for definition in definitions:
            if definition.order_id in state.unlocked_order_ids:
                continue
            if workshop_level < definition.required_workshop_level:
                continue
            if any(flag not in world_flags for flag in definition.required_unlock_flags):
                continue
            state.unlocked_order_ids.add(definition.order_id)
            logs.append(f"endgame_order_unlocked:{definition.order_id}")
        return logs

    def start(self, *, state: EndgameRepeatableOrderState, order: EndgameRepeatableOrderDefinition) -> list[str]:
        if order.order_id not in state.unlocked_order_ids:
            return [f"endgame_order_start_failed:locked:{order.order_id}"]
        if state.active_order_id == order.order_id:
            return [f"endgame_order_start_failed:already_active:{order.order_id}"]
        if state.active_order_id and state.active_order_id != order.order_id:
            return [f"endgame_order_start_failed:other_active:{state.active_order_id}"]
        if order.order_id in state.completed_order_ids_in_cycle and order.order_id not in state.ready_to_reaccept_order_ids:
            return [f"endgame_order_start_failed:already_completed_cycle:{order.order_id}"]
        state.active_order_id = order.order_id
        state.objective_progress = {obj.objective_id: 0 for obj in order.objectives}
        state.completed_order_ids_in_cycle.discard(order.order_id)
        state.rewarded_cycle_ids.discard(order.order_id)
        state.ready_to_reaccept_order_ids.discard(order.order_id)
        return [f"endgame_order_started:{order.order_id}"]

    def complete(self, *, state: EndgameRepeatableOrderState, order: EndgameRepeatableOrderDefinition) -> list[str]:
        if state.active_order_id != order.order_id:
            return [f"endgame_order_complete_failed:not_active:{order.order_id}"]
        if not self.is_all_objectives_completed(state=state, order=order):
            return [f"endgame_order_complete_failed:not_ready:{order.order_id}"]
        logs = [f"endgame_order_completed:{order.order_id}"]
        state.active_order_id = None
        state.completed_order_ids_in_cycle.add(order.order_id)
        state.completion_counts[order.order_id] = state.completion_counts.get(order.order_id, 0) + 1
        if order.repeatable and order.repeat_reset_rule == "manual_reaccept":
            state.ready_to_reaccept_order_ids.add(order.order_id)
            logs.append(f"endgame_order_ready_to_reaccept:{order.order_id}")
        return logs

    def mark_ready_to_reaccept(self, *, state: EndgameRepeatableOrderState, repeat_reset_rule: str) -> list[str]:
        logs: list[str] = []
        if repeat_reset_rule not in {"on_return_to_hub", "on_rest"}:
            return logs
        for order_id in sorted(state.completed_order_ids_in_cycle):
            state.ready_to_reaccept_order_ids.add(order_id)
            logs.append(f"endgame_order_ready_to_reaccept:{order_id}")
        return logs

    def update_objective(self, *, state: EndgameRepeatableOrderState, order: EndgameRepeatableOrderDefinition, objective_id: str, completed: bool) -> list[str]:
        if state.active_order_id != order.order_id:
            return []
        if objective_id not in state.objective_progress:
            return [f"endgame_order_progress_failed:unknown_objective:{objective_id}"]
        if not completed:
            return []
        if state.objective_progress[objective_id] >= 1:
            return []
        state.objective_progress[objective_id] = 1
        return [f"endgame_order_objective_completed:{order.order_id}:{objective_id}"]

    def is_all_objectives_completed(self, *, state: EndgameRepeatableOrderState, order: EndgameRepeatableOrderDefinition) -> bool:
        return all(state.objective_progress.get(obj.objective_id, 0) >= 1 for obj in order.objectives)
