from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools.chapter_content_pack import KINDS

PACK_ID_FIELDS = {
    "quests": ("quest_id", "id"),
    "events": ("event_id", "id"),
    "encounters": ("encounter_id", "id"),
    "locations": ("location_id", "id"),
    "conversations": ("conversation_id", "entry_id", "id"),
}


class PromotionError(ValueError):
    pass


@dataclass(frozen=True)
class MasterCatalog:
    root: Path
    definition: Mapping[str, Mapping[str, Any]]
    entities: Mapping[str, Mapping[str, Mapping[str, Any]]]
    digest: str

    def ids(self, kind: str) -> set[str]:
        return set(self.entities.get(kind, {}))


@dataclass(frozen=True)
class PromotionEvaluation:
    plan: Mapping[str, Any]
    blocked: bool
    warnings: tuple[str, ...]


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def catalog_digest(
    definitions: Mapping[str, Mapping[str, Any]],
    entities: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> str:
    digest_source = {
        kind: {
            "definition": dict(definitions[kind]),
            "entities": {
                item_id: digest(entity)
                for item_id, entity in sorted(index.items())
            },
        }
        for kind, index in sorted(entities.items())
    }
    return digest(digest_source)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def require_object(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PromotionError(f"{field}_must_be_object")
    return value


def require_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PromotionError(f"{field}_must_be_non_empty_string")
    return value.strip()


def entity_id(row: Mapping[str, Any], fields: Sequence[str], source: str) -> str:
    aliases = {
        field: value.strip()
        for field in fields
        if isinstance((value := row.get(field)), str) and value.strip()
    }
    if not aliases:
        raise PromotionError(f"entity_id_missing:{source}")
    values = set(aliases.values())
    if len(values) != 1:
        details = ",".join(f"{field}={value}" for field, value in aliases.items())
        raise PromotionError(f"entity_id_alias_mismatch:{source}:{details}")
    return next(iter(values))


def load_catalog(definition_path: Path, project_root: Path | None = None) -> MasterCatalog:
    raw = require_object(load_json(definition_path), "catalog")
    if raw.get("schema_version") != 1:
        raise PromotionError("unsupported_catalog_schema_version")
    root = (project_root or definition_path.resolve().parents[1]).resolve()
    definitions = require_object(raw.get("collections"), "catalog.collections")
    entities: dict[str, dict[str, Mapping[str, Any]]] = {}

    for kind, definition_value in definitions.items():
        definition = require_object(definition_value, f"catalog.collections.{kind}")
        path = Path(require_string(definition.get("path"), f"catalog.collections.{kind}.path"))
        fields = definition.get("id_fields")
        if not isinstance(fields, list) or not fields or not all(isinstance(v, str) and v for v in fields):
            raise PromotionError(f"catalog.collections.{kind}.id_fields_invalid")
        source = root / path
        if not source.exists():
            if definition.get("optional") is True:
                entities[kind] = {}
                continue
            raise PromotionError(f"catalog_source_missing:{kind}:{path.as_posix()}")
        rows = load_json(source)
        if not isinstance(rows, list):
            raise PromotionError(f"catalog_source_must_be_list:{kind}")
        index: dict[str, Mapping[str, Any]] = {}
        for position, row in enumerate(rows):
            row = require_object(row, f"catalog.{kind}[{position}]")
            item_id = entity_id(row, tuple(fields), f"{kind}:{position}")
            if item_id in index:
                raise PromotionError(f"catalog_duplicate_id:{kind}:{item_id}")
            index[item_id] = dict(row)
        entities[kind] = index

    return MasterCatalog(root, definitions, entities, catalog_digest(definitions, entities))


def pack_index(pack: Mapping[str, Any]) -> dict[str, dict[str, Mapping[str, Any]]]:
    content = require_object(pack.get("content"), "pack.content")
    result: dict[str, dict[str, Mapping[str, Any]]] = {}
    globally_seen: dict[str, str] = {}
    for kind in KINDS:
        rows = content.get(kind, [])
        if not isinstance(rows, list):
            raise PromotionError(f"pack.content.{kind}_must_be_list")
        index: dict[str, Mapping[str, Any]] = {}
        for position, row in enumerate(rows):
            row = require_object(row, f"pack.content.{kind}[{position}]")
            item_id = entity_id(row, PACK_ID_FIELDS[kind], f"pack:{kind}:{position}")
            if item_id in index:
                raise PromotionError(f"pack_duplicate_id:{kind}:{item_id}")
            if item_id in globally_seen:
                raise PromotionError(
                    f"pack_cross_kind_duplicate_id:{item_id}:{globally_seen[item_id]}:{kind}"
                )
            index[item_id] = dict(row)
            globally_seen[item_id] = kind
        result[kind] = index
    return result
