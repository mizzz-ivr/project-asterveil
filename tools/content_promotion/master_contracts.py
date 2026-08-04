from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Mapping

from game.app.infrastructure.dialogue_event_repository import DialogueEventMasterDataRepository
from game.battle.infrastructure.master_data_repository import MasterDataRepository
from game.location.infrastructure.master_data_repository import LocationMasterDataRepository
from game.quest.infrastructure.master_data_repository import QuestMasterDataRepository

from .catalog import MasterCatalog, PromotionError

_REQUIRED_EVENT_ACTION_PARAMS = {
    "accept_quest": "quest_id",
    "complete_quest": "quest_id",
    "start_battle": "encounter_id",
}


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
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
            required_param = _REQUIRED_EVENT_ACTION_PARAMS.get(action_type)
            if required_param is not None:
                value = params.get(required_param)
                if not isinstance(value, str) or not value.strip():
                    raise PromotionError(
                        "master_contract_invalid:events:required_action_param_missing:"
                        f"{event_id}:{step_index}:{action_type}:{required_param}"
                    )


def validate_master_contracts(
    index: Mapping[str, Mapping[str, Mapping[str, Any]]],
    catalog: MasterCatalog,
) -> None:
    """Promotion候補を実際のMaster Repositoryで読込検証する。"""

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)

        quests = [dict(value) for value in index.get("quests", {}).values()]
        if quests:
            _write_json(root / "quests.sample.json", quests)
            try:
                QuestMasterDataRepository(root).load_quests()
            except (KeyError, TypeError, ValueError) as exc:
                raise PromotionError(f"master_contract_invalid:quests:{exc}") from exc

        events = [dict(value) for value in index.get("events", {}).values()]
        if events:
            _validate_event_actions(events)
            _write_json(root / "events.sample.json", events)
            try:
                QuestMasterDataRepository(root).load_events()
            except (KeyError, TypeError, ValueError) as exc:
                raise PromotionError(f"master_contract_invalid:events:{exc}") from exc

        encounters = [dict(value) for value in index.get("encounters", {}).values()]
        if encounters:
            _write_json(root / "encounters.sample.json", encounters)
            try:
                MasterDataRepository(root).load_encounters()
            except (KeyError, TypeError, ValueError) as exc:
                raise PromotionError(f"master_contract_invalid:encounters:{exc}") from exc

        locations = [dict(value) for value in index.get("locations", {}).values()]
        if locations:
            _write_json(root / "locations.sample.json", locations)
            try:
                LocationMasterDataRepository(root).load_locations()
            except (KeyError, TypeError, ValueError) as exc:
                raise PromotionError(f"master_contract_invalid:locations:{exc}") from exc

        conversations = [
            dict(value) for value in index.get("conversations", {}).values()
        ]
        if conversations:
            _write_json(root / "dialogues.sample.json", conversations)
            _write_json(
                root / "npcs.sample.json",
                [dict(value) for value in catalog.entities.get("npcs", {}).values()],
            )
            try:
                DialogueEventMasterDataRepository(root).load_npc_dialogues()
            except (KeyError, TypeError, ValueError) as exc:
                raise PromotionError(f"master_contract_invalid:conversations:{exc}") from exc
