from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from game.app.application.demo_flow_service import SteamDemoApplication
    from game.app.application.playable_slice import PlayableSliceApplication


class ActionDispatchKind(str, Enum):
    EXECUTED = "executed"
    FLOW_REQUIRED = "flow_required"
    EXIT_REQUESTED = "exit_requested"
    REJECTED = "rejected"


class SteamDemoFlowId(str, Enum):
    USE_ITEM = "use_item"
    EQUIPMENT = "equip"
    SHOP = "shop"
    EQUIPMENT_UPGRADE = "upgrade_equipment"
    EQUIPMENT_SALVAGE = "salvage_equipment"
    CRAFTING = "craft"
    INN = "inn"
    QUEST_BOARD = "quest_board"
    TRAVEL = "move"
    NPC_DIALOGUE = "talk_npc"
    GATHERING = "gather"
    TREASURE = "open_treasure"
    FIELD_EVENT = "field_events"
    BESTIARY = "bestiary"


@dataclass(frozen=True)
class ActionDispatchResult:
    action_id: str
    kind: ActionDispatchKind
    logs: tuple[str, ...] = tuple()
    flow_id: SteamDemoFlowId | None = None
    reason_code: str | None = None


class SteamDemoActionController:
    """CLIやGUIに依存せず、Steamデモのトップレベル操作を振り分ける。"""

    _FLOW_BY_ACTION = {
        flow.value: flow
        for flow in SteamDemoFlowId
    }

    def __init__(
        self,
        playable: PlayableSliceApplication,
        demo: SteamDemoApplication,
    ) -> None:
        self._playable = playable
        self._demo = demo

    def dispatch(self, action_id: str) -> ActionDispatchResult:
        normalized_action_id = action_id.strip()
        if not normalized_action_id:
            return self._rejected(action_id, "empty_action_id")

        if normalized_action_id == "exit":
            return ActionDispatchResult(
                action_id=normalized_action_id,
                kind=ActionDispatchKind.EXIT_REQUESTED,
                logs=("exit_selected",),
            )

        if normalized_action_id == "demo_guide":
            return self._execute(normalized_action_id, self._demo.guidance_lines)
        if normalized_action_id == "demo_workshop":
            return self._execute(normalized_action_id, self._demo.inspect_workshop)
        if normalized_action_id == "save":
            return self._execute(normalized_action_id, self._demo.save_checkpoint)

        available_action_ids = {
            item.key
            for item in self._playable.available_actions()
        }
        if normalized_action_id not in available_action_ids:
            return self._rejected(normalized_action_id, "action_not_available")

        flow_id = self._FLOW_BY_ACTION.get(normalized_action_id)
        if flow_id is not None:
            return ActionDispatchResult(
                action_id=normalized_action_id,
                kind=ActionDispatchKind.FLOW_REQUIRED,
                flow_id=flow_id,
            )

        return self._execute(
            normalized_action_id,
            lambda: self._playable.perform_action(normalized_action_id),
        )

    def _execute(
        self,
        action_id: str,
        operation: Callable[[], list[str]],
    ) -> ActionDispatchResult:
        try:
            logs = tuple(operation())
        except ValueError as exc:
            return ActionDispatchResult(
                action_id=action_id,
                kind=ActionDispatchKind.REJECTED,
                logs=(f"action_rejected:{action_id}:{exc}",),
                reason_code="application_rejected",
            )
        return ActionDispatchResult(
            action_id=action_id,
            kind=ActionDispatchKind.EXECUTED,
            logs=logs,
        )

    @staticmethod
    def _rejected(action_id: str, reason_code: str) -> ActionDispatchResult:
        return ActionDispatchResult(
            action_id=action_id,
            kind=ActionDispatchKind.REJECTED,
            logs=(f"action_rejected:{action_id}:{reason_code}",),
            reason_code=reason_code,
        )
