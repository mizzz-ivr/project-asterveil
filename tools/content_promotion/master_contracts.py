from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .catalog import MasterCatalog, PromotionError

_REQUIRED_EVENT_ACTION_PARAMS = {
    "accept_quest": "quest_id",
    "complete_quest": "quest_id",
    "start_battle": "encounter_id",
    "set_flag": "flag_id",
}

_REQUIRED_DIALOGUE_EFFECT_PARAMS = {
    "accept_quest": "quest_id",
    "turn_in_quest": "quest_id",
    "report_quest": "quest_id",
    "start_battle": "encounter_id",
    "set_flag": "flag_id",
}


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _require_action_param(
    *,
    action_scope: str,
    source_id: str,
    position: str,
    action_type: str,
    params: Mapping[str, Any],
    required_params: Mapping[str, str],
) -> None:
    required_param = required_params.get(action_type)
    if required_param is None:
        return
    value = params.get(required_param)
    if not isinstance(value, str) or not value.strip():
        raise PromotionError(
            f"master_contract_invalid:{action_scope}:required_action_param_missing:"
            f"{source_id}:{position}:{action_type}:{required_param}"
        )


def _validate_event_actions(events: list[Mapping[str, Any]]) -> None:
    for event in events:
        event_id = str(event.get("id") or event.get("event_id") or "<unknown>")
        steps = event.get("steps", [])
        if not isinstance(steps, list):
            raise PromotionError(f"master_contract_invalid:events:steps_must_be_list:{event_id}")
        for step_index, step in enumerate(steps):
            if not isinstance(step, Mapping):
                raise PromotionError(
                    f"master_contract_invalid:events:step_must_be_object:{event_id}:{step_index}"
                )
            action = step.get("action")
            if action is None:
                continue
            if not isinstance(action, Mapping):
                raise PromotionError(
                    f"master_contract_invalid:events:action_must_be_object:{event_id}:{step_index}"
                )
            action_type = action.get("type")
            if not isinstance(action_type, str) or not action_type.strip():
                raise PromotionError(
                    f"master_contract_invalid:events:action_type_missing:{event_id}:{step_index}"
                )
            params = action.get("params", {})
            if not isinstance(params, Mapping):
                raise PromotionError(
                    f"master_contract_invalid:events:action_params_must_be_object:{event_id}:{step_index}"
                )
            _require_action_param(
                action_scope="events",
                source_id=event_id,
                position=str(step_index),
                action_type=action_type,
                params=params,
                required_params=_REQUIRED_EVENT_ACTION_PARAMS,
            )


def _validate_string_list(value: object, error_code: str) -> None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise PromotionError(error_code)


def _validate_conversation_contracts(
    conversations: list[Mapping[str, Any]],
) -> None:
    """DialogueEventMasterDataRepository.load_npc_dialoguesの入力契約を検証する。

    `game.app.application.__init__`がPlayableSliceを公開しているため、Repositoryを
    検証Toolから直接importすると循環importになる。ここでは同Repositoryの公開入力
    契約と実行時に必須となるEffect Paramを明示的に再現し、Repositoryファイル変更時
    はWorkflowのpath監視で必ず再検証する。
    """

    for row in conversations:
        entry_id = str(row.get("entry_id") or "<unknown>")
        for field in ("entry_id", "npc_id", "priority", "lines"):
            if field not in row:
                raise PromotionError(
                    f"master_contract_invalid:conversations:missing_field:"
                    f"{entry_id}:{field}"
                )
        try:
            int(row["priority"])
        except (TypeError, ValueError) as exc:
            raise PromotionError(
                f"master_contract_invalid:conversations:priority_must_be_integer:{entry_id}"
            ) from exc
        _validate_string_list(
            row["lines"],
            f"master_contract_invalid:conversations:lines_must_be_string_list:{entry_id}",
        )
        condition = row.get("condition", {})
        if not isinstance(condition, Mapping):
            raise PromotionError(
                f"master_contract_invalid:conversations:condition_must_be_object:{entry_id}"
            )
        for field in ("required_flags", "excluded_flags"):
            if field in condition:
                _validate_string_list(
                    condition[field],
                    f"master_contract_invalid:conversations:condition_{field}_must_be_string_list:{entry_id}",
                )
        required_status = condition.get("required_quest_status", {})
        if not isinstance(required_status, Mapping):
            raise PromotionError(
                "master_contract_invalid:conversations:required_quest_status_must_be_object:"
                f"{entry_id}"
            )

        steps = row.get("steps", [])
        if not isinstance(steps, list):
            raise PromotionError(
                f"master_contract_invalid:conversations:steps_must_be_list:{entry_id}"
            )
        for step_index, step in enumerate(steps):
            if not isinstance(step, Mapping):
                raise PromotionError(
                    "master_contract_invalid:conversations:step_must_be_object:"
                    f"{entry_id}:{step_index}"
                )
            for field in ("step_id", "speaker"):
                if field not in step:
                    raise PromotionError(
                        "master_contract_invalid:conversations:step_missing_field:"
                        f"{entry_id}:{step_index}:{field}"
                    )
            line_values = step.get("lines")
            if line_values is None and "line" in step:
                line_values = [step.get("line")]
            if line_values is not None:
                _validate_string_list(
                    line_values,
                    "master_contract_invalid:conversations:step_lines_must_be_string_list:"
                    f"{entry_id}:{step_index}",
                )
            choices = step.get("choices", [])
            if not isinstance(choices, list):
                raise PromotionError(
                    "master_contract_invalid:conversations:choices_must_be_list:"
                    f"{entry_id}:{step_index}"
                )
            for choice_index, choice in enumerate(choices):
                if not isinstance(choice, Mapping):
                    raise PromotionError(
                        "master_contract_invalid:conversations:choice_must_be_object:"
                        f"{entry_id}:{step_index}:{choice_index}"
                    )
                for field in ("choice_id", "text", "next_step_id"):
                    if field not in choice:
                        raise PromotionError(
                            "master_contract_invalid:conversations:choice_missing_field:"
                            f"{entry_id}:{step_index}:{choice_index}:{field}"
                        )
                for field in ("set_flags", "required_flags", "excluded_flags"):
                    if field in choice:
                        _validate_string_list(
                            choice[field],
                            "master_contract_invalid:conversations:choice_"
                            f"{field}_must_be_string_list:{entry_id}:{step_index}:{choice_index}",
                        )
                effects = choice.get("effects", [])
                if not isinstance(effects, list):
                    raise PromotionError(
                        "master_contract_invalid:conversations:effects_must_be_list:"
                        f"{entry_id}:{step_index}:{choice_index}"
                    )
                for effect_index, effect in enumerate(effects):
                    if not isinstance(effect, Mapping):
                        raise PromotionError(
                            "master_contract_invalid:conversations:effect_must_be_object:"
                            f"{entry_id}:{step_index}:{choice_index}:{effect_index}"
                        )
                    action_type = effect.get("action_type")
                    if not isinstance(action_type, str) or not action_type.strip():
                        raise PromotionError(
                            "master_contract_invalid:conversations:effect_action_type_missing:"
                            f"{entry_id}:{step_index}:{choice_index}:{effect_index}"
                        )
                    params = effect.get("params", {})
                    if not isinstance(params, Mapping):
                        raise PromotionError(
                            "master_contract_invalid:conversations:effect_params_must_be_object:"
                            f"{entry_id}:{step_index}:{choice_index}:{effect_index}"
                        )
                    _require_action_param(
                        action_scope="conversations",
                        source_id=entry_id,
                        position=f"{step_index}:{choice_index}:{effect_index}",
                        action_type=action_type,
                        params=params,
                        required_params=_REQUIRED_DIALOGUE_EFFECT_PARAMS,
                    )


def validate_master_contracts(
    index: Mapping[str, Mapping[str, Mapping[str, Any]]],
    catalog: MasterCatalog,
) -> None:
    """Promotion候補を実際のMaster Repository契約で読込・構造検証する。"""

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)

        quests = [dict(value) for value in index.get("quests", {}).values()]
        if quests:
            from game.quest.infrastructure.master_data_repository import (
                QuestMasterDataRepository,
            )

            _write_json(root / "quests.sample.json", quests)
            try:
                QuestMasterDataRepository(root).load_quests()
            except (KeyError, TypeError, ValueError) as exc:
                raise PromotionError(f"master_contract_invalid:quests:{exc}") from exc

        events = [dict(value) for value in index.get("events", {}).values()]
        if events:
            from game.quest.infrastructure.master_data_repository import (
                QuestMasterDataRepository,
            )

            _validate_event_actions(events)
            _write_json(root / "events.sample.json", events)
            try:
                QuestMasterDataRepository(root).load_events()
            except (KeyError, TypeError, ValueError) as exc:
                raise PromotionError(f"master_contract_invalid:events:{exc}") from exc

        encounters = [dict(value) for value in index.get("encounters", {}).values()]
        if encounters:
            from game.battle.infrastructure.master_data_repository import (
                MasterDataRepository,
            )

            _write_json(root / "encounters.sample.json", encounters)
            try:
                MasterDataRepository(root).load_encounters()
            except (KeyError, TypeError, ValueError) as exc:
                raise PromotionError(f"master_contract_invalid:encounters:{exc}") from exc

        locations = [dict(value) for value in index.get("locations", {}).values()]
        if locations:
            from game.location.infrastructure.master_data_repository import (
                LocationMasterDataRepository,
            )

            _write_json(root / "locations.sample.json", locations)
            try:
                LocationMasterDataRepository(root).load_locations()
            except (KeyError, TypeError, ValueError) as exc:
                raise PromotionError(f"master_contract_invalid:locations:{exc}") from exc

        conversations = [
            dict(value) for value in index.get("conversations", {}).values()
        ]
        if conversations:
            _validate_conversation_contracts(conversations)
            known_npcs = catalog.ids("npcs")
            for conversation in conversations:
                npc_id = conversation.get("npc_id")
                if not isinstance(npc_id, str) or npc_id not in known_npcs:
                    raise PromotionError(
                        "master_contract_invalid:conversations:npc_not_found:"
                        f"{conversation.get('entry_id')}:{npc_id}"
                    )
