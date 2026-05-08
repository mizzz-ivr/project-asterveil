from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkshopSpecialChainStageDefinition:
    stage_id: str
    stage_type: str
    description: str
    requirements: dict[str, str]
    rewards: tuple[str, ...] = tuple()


@dataclass(frozen=True)
class WorkshopSpecialChainDefinition:
    chain_id: str
    name: str
    description: str
    required_workshop_level: int
    stages: tuple[WorkshopSpecialChainStageDefinition, ...]
    final_rewards: tuple[str, ...]
    unlock_flags: tuple[str, ...] = tuple()


@dataclass
class WorkshopSpecialChainState:
    unlocked_chain_ids: set[str] | None = None
    active_chain_id: str | None = None
    active_stage_id: str | None = None
    completed_stage_ids: set[str] | None = None
    completed_chain_ids: set[str] | None = None
    rewarded_chain_ids: set[str] | None = None

    def __post_init__(self) -> None:
        self.unlocked_chain_ids = self.unlocked_chain_ids or set()
        self.completed_stage_ids = self.completed_stage_ids or set()
        self.completed_chain_ids = self.completed_chain_ids or set()
        self.rewarded_chain_ids = self.rewarded_chain_ids or set()


class WorkshopSpecialChainService:
    def unlock_available(self, *, state: WorkshopSpecialChainState, definitions: tuple[WorkshopSpecialChainDefinition, ...], workshop_level: int, world_flags: set[str]) -> list[str]:
        logs: list[str] = []
        for chain in definitions:
            if chain.chain_id in state.unlocked_chain_ids:
                continue
            if workshop_level < chain.required_workshop_level:
                continue
            if any(flag not in world_flags for flag in chain.unlock_flags):
                continue
            state.unlocked_chain_ids.add(chain.chain_id)
            if state.active_chain_id is None:
                state.active_chain_id = chain.chain_id
                state.active_stage_id = chain.stages[0].stage_id if chain.stages else None
            logs.append(f"special_chain_unlocked:{chain.chain_id}")
        return logs

    def advance(self, *, state: WorkshopSpecialChainState, chain: WorkshopSpecialChainDefinition, stage_clear: bool) -> list[str]:
        logs: list[str] = []
        if state.active_chain_id != chain.chain_id or not state.active_stage_id:
            return logs
        if not stage_clear:
            logs.append(f"current_special_chain_stage:{chain.chain_id}:{state.active_stage_id}")
            return logs
        if state.active_stage_id in state.completed_stage_ids:
            return [f"special_chain_stage_skipped:already_completed:{state.active_stage_id}"]
        state.completed_stage_ids.add(state.active_stage_id)
        logs.append(f"special_chain_stage_completed:{chain.chain_id}:{state.active_stage_id}")
        current_index = next((i for i, s in enumerate(chain.stages) if s.stage_id == state.active_stage_id), -1)
        if current_index < 0:
            return [f"special_chain_failed:unknown_stage:{state.active_stage_id}"]
        if current_index + 1 < len(chain.stages):
            state.active_stage_id = chain.stages[current_index + 1].stage_id
            logs.append(f"special_chain_next_stage:{chain.chain_id}:{state.active_stage_id}")
            return logs
        state.completed_chain_ids.add(chain.chain_id)
        state.active_stage_id = None
        logs.append(f"special_chain_completed:{chain.chain_id}")
        if chain.chain_id not in state.rewarded_chain_ids:
            state.rewarded_chain_ids.add(chain.chain_id)
            for reward in chain.final_rewards:
                logs.append(f"special_chain_final_reward:{chain.chain_id}:{reward}")
        return logs
