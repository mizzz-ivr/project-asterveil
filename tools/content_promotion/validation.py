from __future__ import annotations

import copy
import re
from typing import Any, Mapping

from tools.chapter_content_pack import ContentPackError, KINDS, pack_digest, validate_pack

from .catalog import (
    MasterCatalog,
    PromotionError,
    PromotionEvaluation,
    canonical,
    digest,
    pack_index,
)

INLINE_TEXT_FIELDS = {"title", "description", "name", "line", "text", "dialogue_line"}


def _validate_pack_with_catalog(
    pack: Mapping[str, Any],
    index: Mapping[str, Mapping[str, Mapping[str, Any]]],
    catalog: MasterCatalog,
) -> None:
    sanitized = copy.deepcopy(dict(pack))
    local_encounters = set(index["encounters"])
    local_locations = set(index["locations"])
    local_events = set(index["events"])

    for quest in sanitized["content"].get("quests", []):
        if quest.get("encounter_id") in catalog.ids("encounters") - local_encounters:
            quest.pop("encounter_id", None)
        if quest.get("target_location_id") in catalog.ids("locations") - local_locations:
            quest.pop("target_location_id", None)
    for event in sanitized["content"].get("events", []):
        event["next_event_ids"] = [
            value
            for value in event.get("next_event_ids", [])
            if value in local_events or value not in catalog.ids("events")
        ]
    try:
        validate_pack(sanitized)
    except ContentPackError as exc:
        raise PromotionError(str(exc)) from exc


def _dependencies(quest: Mapping[str, Any]) -> list[str]:
    availability = quest.get("availability", {})
    values = availability.get("required_quest_ids", []) if isinstance(availability, Mapping) else []
    return [str(value) for value in values] if isinstance(values, list) else []


def _validate_cycles(
    catalog: MasterCatalog,
    index: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> None:
    graph = {
        quest_id: _dependencies(quest)
        for quest_id, quest in catalog.entities.get("quests", {}).items()
    }
    for quest_id, quest in index["quests"].items():
        existing = catalog.entities.get("quests", {}).get(quest_id)
        if existing is not None and canonical(existing) != canonical(quest):
            continue
        graph[quest_id] = _dependencies(quest)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str, path: list[str]) -> None:
        if node in visiting:
            start = path.index(node) if node in path else 0
            raise PromotionError("quest_dependency_cycle:" + "->".join(path[start:] + [node]))
        if node in visited or node not in graph:
            return
        visiting.add(node)
        for dependency in graph[node]:
            visit(dependency, path + [node])
        visiting.remove(node)
        visited.add(node)

    for quest_id in graph:
        visit(quest_id, [])


def _reference(
    references: list[dict[str, str]],
    unresolved: list[dict[str, str]],
    *,
    source_kind: str,
    source_id: str,
    field: str,
    target_kind: str,
    target_id: object,
    available: set[str],
) -> None:
    if target_id in {None, ""}:
        return
    record = {
        "source_kind": source_kind,
        "source_id": source_id,
        "field": field,
        "target_kind": target_kind,
        "target_id": str(target_id),
    }
    references.append(record)
    if not isinstance(target_id, str) or target_id not in available:
        unresolved.append({**record, "reason": "target_not_found"})


def _collect_references(
    catalog: MasterCatalog,
    index: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    references: list[dict[str, str]] = []
    unresolved: list[dict[str, str]] = []
    available = {
        kind: catalog.ids(kind) | set(index.get(kind, {}))
        for kind in set(catalog.entities) | set(index)
    }

    for quest_id, quest in index["quests"].items():
        for dependency in _dependencies(quest):
            _reference(
                references,
                unresolved,
                source_kind="quests",
                source_id=quest_id,
                field="availability.required_quest_ids",
                target_kind="quests",
                target_id=dependency,
                available=available.get("quests", set()),
            )
        for field, target_kind in (
            ("encounter_id", "encounters"),
            ("target_location_id", "locations"),
            ("reporting_npc_id", "npcs"),
        ):
            _reference(
                references,
                unresolved,
                source_kind="quests",
                source_id=quest_id,
                field=field,
                target_kind=target_kind,
                target_id=quest.get(field),
                available=available.get(target_kind, set()),
            )
        for objective_index, objective in enumerate(quest.get("objectives", [])):
            if not isinstance(objective, Mapping):
                continue
            _reference(
                references,
                unresolved,
                source_kind="quests",
                source_id=quest_id,
                field=f"objectives[{objective_index}].target_enemy_id",
                target_kind="enemies",
                target_id=objective.get("target_enemy_id"),
                available=available.get("enemies", set()),
            )
            for item_index, item in enumerate(objective.get("required_items", [])):
                if isinstance(item, Mapping):
                    _reference(
                        references,
                        unresolved,
                        source_kind="quests",
                        source_id=quest_id,
                        field=f"objectives[{objective_index}].required_items[{item_index}].item_id",
                        target_kind="items",
                        target_id=item.get("item_id"),
                        available=available.get("items", set()),
                    )
        reward = quest.get("reward", {})
        reward_items = reward.get("items", []) if isinstance(reward, Mapping) else []
        for item_index, item in enumerate(reward_items):
            if isinstance(item, Mapping):
                _reference(
                    references,
                    unresolved,
                    source_kind="quests",
                    source_id=quest_id,
                    field=f"reward.items[{item_index}].item_id",
                    target_kind="items",
                    target_id=item.get("item_id"),
                    available=available.get("items", set()),
                )

    for encounter_id, encounter in index["encounters"].items():
        for enemy_index, enemy in enumerate(encounter.get("enemies", [])):
            if isinstance(enemy, Mapping):
                _reference(
                    references,
                    unresolved,
                    source_kind="encounters",
                    source_id=encounter_id,
                    field=f"enemies[{enemy_index}].enemy_id",
                    target_kind="enemies",
                    target_id=enemy.get("enemy_id"),
                    available=available.get("enemies", set()),
                )

    for location_id, location in index["locations"].items():
        for position, value in enumerate(location.get("accessible_from", [])):
            _reference(
                references,
                unresolved,
                source_kind="locations",
                source_id=location_id,
                field=f"accessible_from[{position}]",
                target_kind="locations",
                target_id=value,
                available=available.get("locations", set()),
            )
        for position, value in enumerate(location.get("available_encounter_ids", [])):
            _reference(
                references,
                unresolved,
                source_kind="locations",
                source_id=location_id,
                field=f"available_encounter_ids[{position}]",
                target_kind="encounters",
                target_id=value,
                available=available.get("encounters", set()),
            )
        _reference(
            references,
            unresolved,
            source_kind="locations",
            source_id=location_id,
            field="default_encounter_id",
            target_kind="encounters",
            target_id=location.get("default_encounter_id"),
            available=available.get("encounters", set()),
        )

    for event_id, event in index["events"].items():
        for position, value in enumerate(event.get("next_event_ids", [])):
            _reference(
                references,
                unresolved,
                source_kind="events",
                source_id=event_id,
                field=f"next_event_ids[{position}]",
                target_kind="events",
                target_id=value,
                available=available.get("events", set()),
            )
        for step_index, step in enumerate(event.get("steps", [])):
            action = step.get("action") if isinstance(step, Mapping) else None
            params = action.get("params", {}) if isinstance(action, Mapping) else {}
            action_type = action.get("type") if isinstance(action, Mapping) else None
            if action_type in {"accept_quest", "complete_quest"}:
                _reference(
                    references,
                    unresolved,
                    source_kind="events",
                    source_id=event_id,
                    field=f"steps[{step_index}].action.params.quest_id",
                    target_kind="quests",
                    target_id=params.get("quest_id"),
                    available=available.get("quests", set()),
                )
            if action_type == "start_battle":
                _reference(
                    references,
                    unresolved,
                    source_kind="events",
                    source_id=event_id,
                    field=f"steps[{step_index}].action.params.encounter_id",
                    target_kind="encounters",
                    target_id=params.get("encounter_id"),
                    available=available.get("encounters", set()),
                )

    for conversation_id, conversation in index["conversations"].items():
        _reference(
            references,
            unresolved,
            source_kind="conversations",
            source_id=conversation_id,
            field="npc_id",
            target_kind="npcs",
            target_id=conversation.get("npc_id"),
            available=available.get("npcs", set()),
        )
        for step_index, step in enumerate(conversation.get("steps", [])):
            if not isinstance(step, Mapping):
                continue
            for choice_index, choice in enumerate(step.get("choices", [])):
                if not isinstance(choice, Mapping):
                    continue
                for effect_index, effect in enumerate(choice.get("effects", [])):
                    if not isinstance(effect, Mapping):
                        continue
                    action_type = effect.get("action_type")
                    params = effect.get("params", {})
                    if not isinstance(params, Mapping):
                        continue
                    if action_type in {"accept_quest", "turn_in_quest", "report_quest"}:
                        _reference(
                            references,
                            unresolved,
                            source_kind="conversations",
                            source_id=conversation_id,
                            field=(
                                f"steps[{step_index}].choices[{choice_index}]."
                                f"effects[{effect_index}].params.quest_id"
                            ),
                            target_kind="quests",
                            target_id=params.get("quest_id"),
                            available=available.get("quests", set()),
                        )
                    if action_type == "start_battle":
                        _reference(
                            references,
                            unresolved,
                            source_kind="conversations",
                            source_id=conversation_id,
                            field=(
                                f"steps[{step_index}].choices[{choice_index}]."
                                f"effects[{effect_index}].params.encounter_id"
                            ),
                            target_kind="encounters",
                            target_id=params.get("encounter_id"),
                            available=available.get("encounters", set()),
                        )
    return references, unresolved


def _localization_candidates(
    index: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> list[dict[str, str]]:
    candidates: dict[str, dict[str, str]] = {}

    def walk(entity_id: str, value: object, path: list[str]) -> None:
        if isinstance(value, Mapping):
            for field, child in value.items():
                next_path = path + [str(field)]
                if field in INLINE_TEXT_FIELDS and isinstance(child, str) and child.strip():
                    suffix = ".".join(
                        re.sub(r"[^a-z0-9_]+", "_", segment.lower()).strip("_")
                        for segment in next_path
                    )
                    key = f"content.{entity_id}.{suffix}"
                    candidates[key] = {
                        "key": key,
                        "source_id": entity_id,
                        "field": ".".join(next_path),
                        "ja": child.strip(),
                    }
                walk(entity_id, child, next_path)
        elif isinstance(value, list):
            for position, child in enumerate(value):
                walk(entity_id, child, path + [str(position)])

    for kind in KINDS:
        for entity_id, entity in index[kind].items():
            walk(entity_id, entity, [])
    return [candidates[key] for key in sorted(candidates)]


def evaluate_promotion(
    pack: Mapping[str, Any],
    catalog: MasterCatalog,
) -> PromotionEvaluation:
    index = pack_index(pack)
    _validate_pack_with_catalog(pack, index, catalog)
    _validate_cycles(catalog, index)
    references, unresolved = _collect_references(catalog, index)

    classifications: dict[str, dict[str, list[str]]] = {}
    conflicts: list[dict[str, str]] = []
    target_files: dict[str, str] = {}

    for kind in KINDS:
        add: list[str] = []
        unchanged: list[str] = []
        conflict: list[str] = []
        existing = catalog.entities.get(kind, {})
        for entity_id, entity in index[kind].items():
            if entity_id not in existing:
                add.append(entity_id)
            elif canonical(existing[entity_id]) == canonical(entity):
                unchanged.append(entity_id)
            else:
                conflict.append(entity_id)
                conflicts.append(
                    {
                        "kind": kind,
                        "id": entity_id,
                        "reason": "content_changed",
                        "existing_sha256": digest(existing[entity_id]),
                        "incoming_sha256": digest(entity),
                    }
                )
        definition = catalog.definition.get(kind)
        if definition is None or definition.get("promotable") is not True:
            if add or conflict:
                conflicts.append(
                    {
                        "kind": kind,
                        "id": "*",
                        "reason": "catalog_collection_not_promotable",
                    }
                )
        else:
            target_files[kind] = str(definition["path"])
        classifications[kind] = {
            "add": sorted(add),
            "unchanged": sorted(unchanged),
            "conflict": sorted(conflict),
        }

    localization = _localization_candidates(index)
    warnings = tuple(
        f"inline_localization_candidate:{candidate['key']}"
        for candidate in localization
    )
    blocked = bool(unresolved or conflicts)
    plan = {
        "schema_version": 1,
        "chapter_id": pack.get("chapter_id"),
        "pack_sha256": pack_digest(pack),
        "catalog_sha256": catalog.digest,
        "status": "blocked" if blocked else "ready_for_review",
        "classifications": classifications,
        "target_files": target_files,
        "references": sorted(
            references,
            key=lambda value: (
                value["source_kind"],
                value["source_id"],
                value["field"],
                value["target_kind"],
                value["target_id"],
            ),
        ),
        "unresolved_references": sorted(
            unresolved,
            key=lambda value: (
                value["source_kind"],
                value["source_id"],
                value["field"],
                value["target_kind"],
                value["target_id"],
            ),
        ),
        "conflicts": sorted(conflicts, key=lambda value: (value["kind"], value["id"])),
        "localization_candidates": localization,
        "warnings": list(warnings),
        "apply_supported": False,
    }
    return PromotionEvaluation(plan, blocked, warnings)
