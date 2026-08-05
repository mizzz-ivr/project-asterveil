from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

ID_PATTERN = re.compile(r"^[a-z0-9_]+(?:\.[a-z0-9_]+)+$")
KINDS = ("quests", "events", "encounters", "locations", "conversations")


class ContentPackError(ValueError):
    pass


@dataclass(frozen=True)
class ValidationResult:
    warnings: tuple[str, ...]
    counts: Mapping[str, int]
    reward_totals: Mapping[str, int]


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ContentPackError("pack_root_must_be_object")
    return data


def _require_str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContentPackError(f"{field}_must_be_non_empty_string")
    return value.strip()


def _entity_id(kind: str, entity: Mapping[str, Any]) -> str:
    keys = {
        "quests": ("quest_id", "id"),
        "events": ("event_id", "id"),
        "encounters": ("encounter_id", "id"),
        "locations": ("location_id", "id"),
        "conversations": ("conversation_id", "entry_id", "id"),
    }[kind]
    aliases = [
        (key, value.strip())
        for key in keys
        if isinstance((value := entity.get(key)), str) and value.strip()
    ]
    if not aliases:
        raise ContentPackError(f"{kind}_entity_id_missing")
    if len({value for _, value in aliases}) > 1:
        details = ",".join(f"{key}={value}" for key, value in aliases)
        raise ContentPackError(f"{kind}_entity_id_alias_mismatch:{details}")
    return aliases[0][1]


def validate_pack(pack: Mapping[str, Any]) -> ValidationResult:
    if pack.get("schema_version") != 1:
        raise ContentPackError("unsupported_schema_version")
    chapter_id = _require_str(pack.get("chapter_id"), "chapter_id")
    if not re.fullmatch(r"ch[0-9]{2}", chapter_id):
        raise ContentPackError("chapter_id_must_match_chNN")
    _require_str(pack.get("title"), "title")
    content = pack.get("content")
    if not isinstance(content, Mapping):
        raise ContentPackError("content_must_be_object")

    ids: dict[str, str] = {}
    counts: dict[str, int] = {}
    warnings: list[str] = []
    all_entities: dict[str, list[Mapping[str, Any]]] = {}
    for kind in KINDS:
        values = content.get(kind, [])
        if not isinstance(values, list):
            raise ContentPackError(f"content.{kind}_must_be_list")
        entities: list[Mapping[str, Any]] = []
        for index, raw in enumerate(values):
            if not isinstance(raw, Mapping):
                raise ContentPackError(f"content.{kind}[{index}]_must_be_object")
            entity_id = _entity_id(kind, raw)
            if not ID_PATTERN.fullmatch(entity_id):
                raise ContentPackError(f"invalid_id:{entity_id}")
            if f".{chapter_id}." not in entity_id and not entity_id.startswith(f"location.{chapter_id}."):
                raise ContentPackError(f"id_outside_chapter_namespace:{entity_id}")
            if entity_id in ids:
                raise ContentPackError(f"duplicate_id:{entity_id}")
            ids[entity_id] = kind
            entities.append(raw)
        all_entities[kind] = entities
        counts[kind] = len(entities)

    quest_ids = {_entity_id("quests", q) for q in all_entities["quests"]}
    encounter_ids = {_entity_id("encounters", e) for e in all_entities["encounters"]}
    location_ids = {_entity_id("locations", e) for e in all_entities["locations"]}
    event_ids = {_entity_id("events", e) for e in all_entities["events"]}

    graph: dict[str, list[str]] = {qid: [] for qid in quest_ids}
    reward_totals = {"exp": 0, "gold": 0, "item_amount": 0}
    for quest in all_entities["quests"]:
        qid = _entity_id("quests", quest)
        availability = quest.get("availability", {})
        if not isinstance(availability, Mapping):
            raise ContentPackError(f"quest_availability_invalid:{qid}")
        prereqs = availability.get("required_quest_ids", [])
        if not isinstance(prereqs, list) or not all(isinstance(x, str) for x in prereqs):
            raise ContentPackError(f"quest_prerequisites_invalid:{qid}")
        graph[qid] = [x for x in prereqs if x in quest_ids]
        encounter_id = quest.get("encounter_id")
        if encounter_id is not None and encounter_id not in encounter_ids:
            raise ContentPackError(f"missing_encounter_reference:{qid}:{encounter_id}")
        location_id = quest.get("target_location_id")
        if location_id is not None and location_id not in location_ids:
            raise ContentPackError(f"missing_location_reference:{qid}:{location_id}")
        objectives = quest.get("objectives")
        if not isinstance(objectives, list) or not objectives:
            raise ContentPackError(f"quest_objectives_missing:{qid}")
        objective_ids: list[str] = []
        for objective in objectives:
            if not isinstance(objective, Mapping):
                raise ContentPackError(f"quest_objective_invalid:{qid}")
            oid = _require_str(objective.get("id"), f"objective_id:{qid}")
            if oid in objective_ids:
                raise ContentPackError(f"duplicate_objective_id:{qid}:{oid}")
            objective_ids.append(oid)
        sequence = quest.get("objective_sequence")
        if sequence is not None:
            if sequence != objective_ids:
                raise ContentPackError(f"objective_sequence_mismatch:{qid}")
            for index, objective in enumerate(objectives[:-1]):
                if objective.get("next_objective_id") != objective_ids[index + 1]:
                    raise ContentPackError(f"next_objective_mismatch:{qid}:{objective_ids[index]}")
        reward = quest.get("reward", {})
        if not isinstance(reward, Mapping):
            raise ContentPackError(f"quest_reward_invalid:{qid}")
        reward_totals["exp"] += int(reward.get("exp", 0))
        reward_totals["gold"] += int(reward.get("gold", 0))
        items = reward.get("items", [])
        if isinstance(items, list):
            reward_totals["item_amount"] += sum(
                int(item.get("amount", 0)) for item in items if isinstance(item, Mapping)
            )
        if int(reward.get("exp", 0)) > 1000:
            warnings.append(f"high_exp_reward:{qid}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(node: str) -> None:
        if node in visiting:
            raise ContentPackError(f"quest_dependency_cycle:{node}")
        if node in visited:
            return
        visiting.add(node)
        for dependency in graph[node]:
            dfs(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        dfs(node)

    for event in all_entities["events"]:
        event_id = _entity_id("events", event)
        next_ids = event.get("next_event_ids", [])
        if not isinstance(next_ids, list):
            raise ContentPackError(f"event_next_ids_invalid:{event_id}")
        for next_id in next_ids:
            if next_id not in event_ids:
                raise ContentPackError(f"missing_event_reference:{event_id}:{next_id}")

    estimated = pack.get("estimated_play_minutes", 0)
    if isinstance(estimated, int) and estimated > 0 and counts["quests"] == 0:
        warnings.append("play_time_without_quests")
    return ValidationResult(tuple(sorted(set(warnings))), counts, reward_totals)


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def pack_digest(pack: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(pack).encode()).hexdigest()


def generate(pack: Mapping[str, Any], output: Path) -> None:
    result = validate_pack(pack)
    output.mkdir(parents=True, exist_ok=True)
    content = pack["content"]
    for kind in KINDS:
        (output / f"{kind}.generated.json").write_text(
            json.dumps(content.get(kind, []), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    manifest = {
        "chapter_id": pack["chapter_id"],
        "schema_version": pack["schema_version"],
        "pack_sha256": pack_digest(pack),
        "counts": dict(result.counts),
        "reward_totals": dict(result.reward_totals),
        "warnings": list(result.warnings),
        "files": [f"{kind}.generated.json" for kind in KINDS],
    }
    (output / "CONTENT_PACK_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "SUMMARY.md").write_text(render_summary(pack, result), encoding="utf-8")


def diff_packs(old: Mapping[str, Any], new: Mapping[str, Any]) -> dict[str, Any]:
    validate_pack(old)
    validate_pack(new)
    report: dict[str, Any] = {
        "added": {},
        "removed": {},
        "changed": {},
        "compatibility_risks": [],
    }
    for kind in KINDS:
        old_map = {_entity_id(kind, item): item for item in old["content"].get(kind, [])}
        new_map = {_entity_id(kind, item): item for item in new["content"].get(kind, [])}
        report["added"][kind] = sorted(set(new_map) - set(old_map))
        report["removed"][kind] = sorted(set(old_map) - set(new_map))
        report["changed"][kind] = sorted(
            key
            for key in set(old_map) & set(new_map)
            if _canonical(old_map[key]) != _canonical(new_map[key])
        )
        report["compatibility_risks"].extend(
            f"removed_persistent_id:{item_id}" for item_id in report["removed"][kind]
        )
    return report


def render_summary(pack: Mapping[str, Any], result: ValidationResult) -> str:
    lines = [
        f"# Content Pack: {pack['chapter_id']} {pack['title']}",
        "",
        f"- SHA-256: `{pack_digest(pack)}`",
        f"- 想定プレイ時間: {pack.get('estimated_play_minutes', 0)}分",
        "",
        "## 件数",
    ]
    lines += [f"- {kind}: {count}" for kind, count in result.counts.items()]
    lines += [
        "",
        "## 報酬合計",
        f"- EXP: {result.reward_totals['exp']}",
        f"- Gold: {result.reward_totals['gold']}",
        f"- Item Amount: {result.reward_totals['item_amount']}",
        "",
        "## Warning",
    ]
    lines += [f"- {warning}" for warning in result.warnings] or ["- なし"]
    return "\n".join(lines) + "\n"


def create_template(chapter_id: str, title: str) -> dict[str, Any]:
    if not re.fullmatch(r"ch[0-9]{2}", chapter_id):
        raise ContentPackError("chapter_id_must_match_chNN")
    return {
        "schema_version": 1,
        "chapter_id": chapter_id,
        "title": title,
        "estimated_play_minutes": 30,
        "content": {kind: [] for kind in KINDS},
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="章コンテンツパックの生成・検証・差分確認")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("pack")
    generate_parser = subparsers.add_parser("generate")
    generate_parser.add_argument("pack")
    generate_parser.add_argument("--output", required=True)
    diff_parser = subparsers.add_parser("diff")
    diff_parser.add_argument("old")
    diff_parser.add_argument("new")
    diff_parser.add_argument("--output")
    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("--chapter-id", required=True)
    init_parser.add_argument("--title", required=True)
    init_parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "validate":
            pack = _load(Path(args.pack))
            result = validate_pack(pack)
            print(
                json.dumps(
                    {
                        "status": "ok",
                        "sha256": pack_digest(pack),
                        "counts": dict(result.counts),
                        "warnings": list(result.warnings),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.command == "generate":
            generate(_load(Path(args.pack)), Path(args.output))
            return 0
        if args.command == "diff":
            report = diff_packs(_load(Path(args.old)), _load(Path(args.new)))
            text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
            if args.output:
                Path(args.output).write_text(text, encoding="utf-8")
            else:
                print(text, end="")
            return 3 if report["compatibility_risks"] else 0
        if args.command == "init":
            Path(args.output).write_text(
                json.dumps(
                    create_template(args.chapter_id, args.title),
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            return 0
    except (OSError, json.JSONDecodeError, ContentPackError) as exc:
        print(f"content pack error: {exc}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
