from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from game.app.application.playable_slice import PlayableSliceApplication


@dataclass(frozen=True)
class GatheringNodeSummary:
    node_id: str
    location_id: str
    name: str
    node_type: str
    description: str
    can_gather: bool
    reason_code: str
    is_gathered: bool
    respawn_rule: str
    respawn_description: str


@dataclass(frozen=True)
class TreasureNodeSummary:
    reward_node_id: str
    location_id: str
    name: str
    node_type: str
    description: str
    can_open: bool
    reason_code: str
    is_opened: bool
    one_time: bool
    required_flags: tuple[str, ...]
    required_facility_id: str | None
    required_facility_level: int


@dataclass(frozen=True)
class ExplorationActionResult:
    success: bool
    code: str
    target_id: str
    logs: tuple[str, ...] = tuple()


class PlayableExplorationFacade:
    """採取と探索報酬を型付き契約で公開するApplication境界。"""

    def __init__(self, playable: PlayableSliceApplication) -> None:
        self._playable = playable

    @property
    def current_location_id(self) -> str:
        return self._playable.location_state.current_location_id

    def list_gathering_nodes(self) -> tuple[GatheringNodeSummary, ...]:
        session = self._playable.quest_session
        if session is None:
            return tuple()
        statuses = self._playable._gathering_service.list_nodes_for_location(
            nodes=self._playable._gathering_nodes,
            location_id=self.current_location_id,
            world_flags=session.world_flags,
            gathered_node_ids=self._playable.gathered_node_ids,
        )
        return tuple(
            GatheringNodeSummary(
                node_id=status.node_id,
                location_id=status.location_id,
                name=status.name,
                node_type=status.node_type,
                description=status.description,
                can_gather=status.can_gather,
                reason_code=status.reason_code,
                is_gathered=status.is_gathered,
                respawn_rule=status.respawn_rule,
                respawn_description=status.respawn_description,
            )
            for status in statuses
        )

    def gather(self, node_id: str) -> ExplorationActionResult:
        if self._playable.quest_session is None:
            return ExplorationActionResult(
                success=False,
                code="game_not_started",
                target_id=node_id,
                logs=(f"gather_rejected:game_not_started:{node_id}",),
            )
        current = next(
            (node for node in self.list_gathering_nodes() if node.node_id == node_id),
            None,
        )
        if current is None:
            return ExplorationActionResult(
                success=False,
                code="node_not_available",
                target_id=node_id,
                logs=(f"gather_rejected:node_not_available:{node_id}",),
            )
        if not current.can_gather:
            return ExplorationActionResult(
                success=False,
                code=current.reason_code,
                target_id=node_id,
                logs=(f"gather_rejected:{current.reason_code}:{node_id}",),
            )

        logs = tuple(self._playable.gather_from_node(node_id))
        success = any(line == f"gathered:{node_id}" for line in logs)
        return ExplorationActionResult(
            success=success,
            code="gathered" if success else self._failure_code(logs, "gather_failed"),
            target_id=node_id,
            logs=logs,
        )

    def list_treasure_nodes(self) -> tuple[TreasureNodeSummary, ...]:
        session = self._playable.quest_session
        if session is None:
            return tuple()
        statuses = self._playable._treasure_service.list_nodes_for_location(
            nodes=self._playable._treasure_nodes,
            location_id=self.current_location_id,
            world_flags=session.world_flags,
            opened_node_ids=self._playable.opened_treasure_node_ids,
            facility_levels=self._playable.facility_levels,
        )
        summaries: list[TreasureNodeSummary] = []
        for status in statuses:
            definition = self._playable._treasure_nodes.get(status.reward_node_id)
            if definition is None:
                raise ValueError(
                    f"treasure definition missing reward_node_id={status.reward_node_id}"
                )
            summaries.append(
                TreasureNodeSummary(
                    reward_node_id=status.reward_node_id,
                    location_id=status.location_id,
                    name=status.name,
                    node_type=status.node_type,
                    description=definition.description,
                    can_open=status.can_open,
                    reason_code=status.reason_code,
                    is_opened=status.is_opened,
                    one_time=definition.one_time,
                    required_flags=definition.required_flags,
                    required_facility_id=definition.required_facility_id,
                    required_facility_level=definition.required_facility_level,
                )
            )
        return tuple(summaries)

    def open_treasure(self, reward_node_id: str) -> ExplorationActionResult:
        if self._playable.quest_session is None:
            return ExplorationActionResult(
                success=False,
                code="game_not_started",
                target_id=reward_node_id,
                logs=(f"treasure_rejected:game_not_started:{reward_node_id}",),
            )
        current = next(
            (
                node
                for node in self.list_treasure_nodes()
                if node.reward_node_id == reward_node_id
            ),
            None,
        )
        if current is None:
            return ExplorationActionResult(
                success=False,
                code="reward_not_available",
                target_id=reward_node_id,
                logs=(f"treasure_rejected:reward_not_available:{reward_node_id}",),
            )
        if not current.can_open:
            return ExplorationActionResult(
                success=False,
                code=current.reason_code,
                target_id=reward_node_id,
                logs=(f"treasure_rejected:{current.reason_code}:{reward_node_id}",),
            )

        logs = tuple(self._playable.open_treasure_node(reward_node_id))
        success = any(line == f"treasure_opened:{reward_node_id}" for line in logs)
        return ExplorationActionResult(
            success=success,
            code="opened" if success else self._failure_code(logs, "treasure_open_failed"),
            target_id=reward_node_id,
            logs=logs,
        )

    @staticmethod
    def _failure_code(logs: tuple[str, ...], fallback: str) -> str:
        if not logs:
            return fallback
        parts = logs[0].split(":")
        if len(parts) >= 2:
            return parts[1]
        return fallback
