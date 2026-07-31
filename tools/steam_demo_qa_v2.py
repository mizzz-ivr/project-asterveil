from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Mapping, Sequence


DEFAULT_BASE_PATH = Path("qa/steam_demo/checklist_v1.json")
DEFAULT_EXTENSION_PATH = Path("qa/steam_demo/checklist_v2_extension.json")


class ChecklistV2Error(ValueError):
    pass


def load_json_object(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ChecklistV2Error(f"invalid_json:{path}:{exc}") from exc
    if not isinstance(payload, dict):
        raise ChecklistV2Error(f"checklist_must_be_object:{path}")
    return payload


def materialize_checklist_v2(
    base_path: Path = DEFAULT_BASE_PATH,
    extension_path: Path = DEFAULT_EXTENSION_PATH,
) -> dict[str, object]:
    base = load_json_object(base_path)
    extension = load_json_object(extension_path)
    _validate_extension_reference(extension, base_path, extension_path)
    if base.get("checklist_id") != extension.get("checklist_id"):
        raise ChecklistV2Error("checklist_id_mismatch")
    if base.get("checklist_version") != 1:
        raise ChecklistV2Error("base_checklist_version_must_be_1")
    if extension.get("composite_checklist_version") != 2:
        raise ChecklistV2Error("extension_version_must_be_2")
    result = copy.deepcopy(base)
    result["checklist_version"] = 2
    result["title"] = _require_string(extension.get("title"), "extension.title")
    result["description"] = _require_string(
        extension.get("description"), "extension.description"
    )
    result["composed_from"] = {
        "base": str(base_path.as_posix()),
        "extension": str(extension_path.as_posix()),
    }
    base_sections = result.get("sections")
    extension_sections = extension.get("sections")
    if not isinstance(base_sections, list):
        raise ChecklistV2Error("base.sections_must_be_list")
    if not isinstance(extension_sections, list) or not extension_sections:
        raise ChecklistV2Error("extension.sections_must_be_non_empty_list")
    base_sections.extend(copy.deepcopy(extension_sections))
    _validate_unique_identifiers(result)
    _validate_cases(result)
    return result


def write_materialized_checklist(
    output_path: Path,
    *,
    base_path: Path = DEFAULT_BASE_PATH,
    extension_path: Path = DEFAULT_EXTENSION_PATH,
) -> Path:
    payload = materialize_checklist_v2(base_path, extension_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


def _validate_extension_reference(
    extension: Mapping[str, object],
    base_path: Path,
    extension_path: Path,
) -> None:
    reference = _require_string(
        extension.get("base_checklist"), "extension.base_checklist"
    )
    if Path(reference).is_absolute() or ".." in Path(reference).parts:
        raise ChecklistV2Error("base_checklist_reference_must_be_relative")
    if Path(reference).name != base_path.name:
        raise ChecklistV2Error(
            f"base_checklist_reference_mismatch:{reference}:{base_path.name}"
        )
    if extension_path.resolve() == base_path.resolve():
        raise ChecklistV2Error("base_and_extension_must_be_different_files")


def _validate_unique_identifiers(checklist: Mapping[str, object]) -> None:
    sections = checklist.get("sections")
    if not isinstance(sections, list):
        raise ChecklistV2Error("sections_must_be_list")
    section_ids: set[str] = set()
    case_ids: set[str] = set()
    for section_index, section in enumerate(sections):
        if not isinstance(section, Mapping):
            raise ChecklistV2Error(f"section_must_be_object:{section_index}")
        section_id = _require_string(
            section.get("id"), f"sections[{section_index}].id"
        )
        if section_id in section_ids:
            raise ChecklistV2Error(f"duplicate_section_id:{section_id}")
        section_ids.add(section_id)
        cases = section.get("cases")
        if not isinstance(cases, list) or not cases:
            raise ChecklistV2Error(f"section_cases_must_be_non_empty:{section_id}")
        for case_index, case in enumerate(cases):
            if not isinstance(case, Mapping):
                raise ChecklistV2Error(
                    f"case_must_be_object:{section_id}:{case_index}"
                )
            case_id = _require_string(
                case.get("id"), f"{section_id}.cases[{case_index}].id"
            )
            if case_id in case_ids:
                raise ChecklistV2Error(f"duplicate_case_id:{case_id}")
            case_ids.add(case_id)


def _validate_cases(checklist: Mapping[str, object]) -> None:
    sections = checklist["sections"]
    assert isinstance(sections, list)
    for section in sections:
        assert isinstance(section, Mapping)
        section_id = str(section["id"])
        cases = section["cases"]
        assert isinstance(cases, list)
        for case in cases:
            assert isinstance(case, Mapping)
            case_id = str(case["id"])
            for field in ("title", "purpose"):
                _require_string(case.get(field), f"{case_id}.{field}")
            for field in ("preconditions", "steps", "expected_results", "tags"):
                value = case.get(field)
                if not isinstance(value, list) or not value:
                    raise ChecklistV2Error(
                        f"{case_id}.{field}_must_be_non_empty_list"
                    )
                if not all(isinstance(item, str) and item.strip() for item in value):
                    raise ChecklistV2Error(
                        f"{case_id}.{field}_must_contain_strings"
                    )
            for field in ("release_blocking", "allow_skip", "evidence_required"):
                if not isinstance(case.get(field), bool):
                    raise ChecklistV2Error(f"{case_id}.{field}_must_be_boolean")
            if case["release_blocking"] and case["allow_skip"]:
                raise ChecklistV2Error(
                    f"release_blocking_case_cannot_allow_skip:{case_id}"
                )
        if section_id.startswith("player_support_") and len(cases) < 3:
            raise ChecklistV2Error(
                "player_support_section_requires_at_least_three_cases:"
                f"{section_id}"
            )


def _require_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ChecklistV2Error(f"{field}_must_be_non_empty_string")
    return value.strip()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="SteamデモQA v1とPlayer Support拡張をv2へ合成する"
    )
    parser.add_argument("--base", default=str(DEFAULT_BASE_PATH))
    parser.add_argument("--extension", default=str(DEFAULT_EXTENSION_PATH))
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--json", action="store_true")
    materialize_parser = subparsers.add_parser("materialize")
    materialize_parser.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        payload = materialize_checklist_v2(
            Path(args.base), Path(args.extension)
        )
        case_count = sum(
            len(section["cases"])
            for section in payload["sections"]
            if isinstance(section, Mapping)
        )
        summary = {
            "status": "ok",
            "checklist_id": payload["checklist_id"],
            "checklist_version": payload["checklist_version"],
            "section_count": len(payload["sections"]),
            "case_count": case_count,
        }
        if args.command == "materialize":
            output = write_materialized_checklist(
                Path(args.output),
                base_path=Path(args.base),
                extension_path=Path(args.extension),
            )
            summary["output"] = str(output)
        print(
            json.dumps(
                summary,
                ensure_ascii=False,
                indent=2 if getattr(args, "json", False) else None,
                sort_keys=True,
            )
        )
        return 0
    except (OSError, ChecklistV2Error) as exc:
        print(f"QA v2検証エラー: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
