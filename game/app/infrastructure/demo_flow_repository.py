from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from game.app.application.demo_flow_service import (
    DemoFlowDefinition,
    DemoFlowStepDefinition,
)
from game.quest.domain.entities import QuestStatus


class DemoFlowMasterDataRepository:
    """Steamデモの静的フロー定義を読み込み、起動時に整合性を検証する。"""

    _SUPPORTED_CONDITION_TYPES = {
        "all",
        "any",
        "world_flag",
        "quest_status",
        "current_location",
        "workshop_rank_at_least",
    }
    _QUEST_STATUSES = {status.value for status in QuestStatus}

    def __init__(self, master_root: Path) -> None:
        self._master_root = master_root

    def load(self) -> dict[str, DemoFlowDefinition]:
        path = self._master_root / "demo_flows.sample.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ValueError(f"demo flow master file not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"demo flow master file is invalid JSON: {path}: {exc.msg}") from exc

        if not isinstance(raw, list) or not raw:
            raise ValueError("demo flow master root must be a non-empty list")

        definitions: dict[str, DemoFlowDefinition] = {}
        for index, flow_raw in enumerate(raw):
            if not isinstance(flow_raw, dict):
                raise ValueError(f"demo flow entry must be an object: index={index}")
            definition = self._parse_flow(flow_raw, index=index)
            if definition.flow_id in definitions:
                raise ValueError(f"duplicate demo flow id: {definition.flow_id}")
            definitions[definition.flow_id] = definition
        return definitions

    def _parse_flow(self, raw: Mapping[str, object], *, index: int) -> DemoFlowDefinition:
        flow_id = self._required_string(raw, "flow_id", context=f"flow index={index}")
        name = self._required_string(raw, "name", context=f"flow={flow_id}")
        description = self._required_string(raw, "description", context=f"flow={flow_id}")
        steps_raw = raw.get("steps")
        if not isinstance(steps_raw, list) or not steps_raw:
            raise ValueError(f"demo flow requires non-empty steps: flow={flow_id}")

        steps: list[DemoFlowStepDefinition] = []
        step_ids: set[str] = set()
        for step_index, step_raw in enumerate(steps_raw):
            if not isinstance(step_raw, dict):
                raise ValueError(
                    f"demo flow step must be an object: flow={flow_id}:index={step_index}"
                )
            step = self._parse_step(step_raw, flow_id=flow_id, index=step_index)
            if step.step_id in step_ids:
                raise ValueError(f"duplicate demo flow step id: flow={flow_id}:step={step.step_id}")
            step_ids.add(step.step_id)
            steps.append(step)

        return DemoFlowDefinition(
            flow_id=flow_id,
            name=name,
            description=description,
            steps=tuple(steps),
        )

    def _parse_step(
        self,
        raw: Mapping[str, object],
        *,
        flow_id: str,
        index: int,
    ) -> DemoFlowStepDefinition:
        context = f"flow={flow_id}:step_index={index}"
        step_id = self._required_string(raw, "step_id", context=context)
        title = self._required_string(raw, "title", context=f"flow={flow_id}:step={step_id}")
        guidance_text = self._required_string(
            raw,
            "guidance_text",
            context=f"flow={flow_id}:step={step_id}",
        )
        recommended_action = self._required_string(
            raw,
            "recommended_action",
            context=f"flow={flow_id}:step={step_id}",
        )
        condition_raw = raw.get("completion_condition")
        if not isinstance(condition_raw, dict):
            raise ValueError(
                f"completion_condition must be an object: flow={flow_id}:step={step_id}"
            )
        self._validate_condition(
            condition_raw,
            context=f"flow={flow_id}:step={step_id}:completion_condition",
        )
        return DemoFlowStepDefinition(
            step_id=step_id,
            title=title,
            guidance_text=guidance_text,
            recommended_action=recommended_action,
            completion_condition=dict(condition_raw),
        )

    def _validate_condition(self, condition: Mapping[str, object], *, context: str) -> None:
        condition_type = self._required_string(condition, "type", context=context)
        if condition_type not in self._SUPPORTED_CONDITION_TYPES:
            raise ValueError(
                f"unsupported demo flow condition type: {condition_type}: context={context}"
            )

        if condition_type in {"all", "any"}:
            children = condition.get("conditions")
            if not isinstance(children, list) or not children:
                raise ValueError(
                    f"{condition_type} condition requires non-empty conditions: context={context}"
                )
            for index, child in enumerate(children):
                if not isinstance(child, dict):
                    raise ValueError(
                        f"nested condition must be an object: context={context}:index={index}"
                    )
                self._validate_condition(child, context=f"{context}:conditions[{index}]")
            return

        if condition_type == "world_flag":
            self._required_string(condition, "flag", context=context)
            return

        if condition_type == "quest_status":
            self._required_string(condition, "quest_id", context=context)
            statuses = condition.get("statuses")
            if not isinstance(statuses, list) or not statuses:
                raise ValueError(f"quest_status requires non-empty statuses: context={context}")
            normalized_statuses: set[str] = set()
            for status in statuses:
                if not isinstance(status, str) or not status.strip():
                    raise ValueError(f"quest_status contains invalid status: context={context}")
                normalized_statuses.add(status.strip())
            unknown = sorted(normalized_statuses - self._QUEST_STATUSES)
            if unknown:
                raise ValueError(
                    f"quest_status contains unsupported statuses={unknown}: context={context}"
                )
            return

        if condition_type == "current_location":
            self._required_string(condition, "location_id", context=context)
            return

        if condition_type == "workshop_rank_at_least":
            rank = condition.get("rank")
            if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
                raise ValueError(
                    f"workshop_rank_at_least requires integer rank >= 1: context={context}"
                )
            return

        raise AssertionError(f"unreachable condition type: {condition_type}")

    @staticmethod
    def _required_string(raw: Mapping[str, object], key: str, *, context: str) -> str:
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} must be a non-empty string: context={context}")
        return value.strip()
