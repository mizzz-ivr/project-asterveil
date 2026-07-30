from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

VALID_APPROVALS = {"pending", "approved", "rejected"}
VALID_EVIDENCE = {"file", "url", "steamworks", "github", "commit", "artifact"}


class ReadinessError(ValueError):
    """Steam Store Readiness契約違反。"""


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReadinessError(f"json_not_found:{path}") from exc
    except json.JSONDecodeError as exc:
        raise ReadinessError(
            f"invalid_json:{path}:line={exc.lineno}:column={exc.colno}"
        ) from exc
    if not isinstance(value, dict):
        raise ReadinessError(f"json_root_not_object:{path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def parse_date(value: Any, field: str, *, allow_none: bool = False) -> date | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not value:
        raise ReadinessError(f"invalid_date:{field}")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ReadinessError(f"invalid_date:{field}:{value}") from exc


def parse_datetime(
    value: Any,
    field: str,
    *,
    allow_none: bool = False,
) -> datetime | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not value:
        raise ReadinessError(f"invalid_datetime:{field}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReadinessError(f"invalid_datetime:{field}:{value}") from exc
    if parsed.tzinfo is None:
        raise ReadinessError(f"datetime_timezone_required:{field}")
    return parsed


def require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReadinessError(f"nonempty_string_required:{field}")
    return value.strip()


def string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ReadinessError(f"list_required:{field}")
    return [
        require_string(item, f"{field}[{index}]")
        for index, item in enumerate(value)
    ]


def ensure_unique(values: Iterable[str], field: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ReadinessError(f"duplicate:{field}:{value}")
        seen.add(value)


def item_dict(definition: dict[str, Any], raw: Any) -> dict[str, Any]:
    fields = definition.get("item_fields")
    if not isinstance(fields, list) or not all(
        isinstance(field, str) for field in fields
    ):
        raise ReadinessError("item_fields_invalid")
    if not isinstance(raw, list) or len(raw) != len(fields):
        raise ReadinessError("item_shape_invalid")
    return dict(zip(fields, raw, strict=True))


def normalized_items(definition: dict[str, Any]) -> list[dict[str, Any]]:
    values = definition.get("items")
    if not isinstance(values, list) or not values:
        raise ReadinessError("items_required")
    return [item_dict(definition, value) for value in values]


def validate_definition(definition: dict[str, Any]) -> None:
    if definition.get("schema_version") != 1:
        raise ReadinessError("unsupported_definition_schema")
    require_string(definition.get("ledger_id"), "ledger_id")
    parse_date(definition.get("verified_on"), "verified_on")
    freshness = definition.get("freshness_days")
    if not isinstance(freshness, int) or freshness <= 0:
        raise ReadinessError("freshness_days_invalid")

    roles = string_list(definition.get("roles"), "roles")
    ensure_unique(roles, "roles")
    gates = string_list(definition.get("gates"), "gates")
    if set(gates) != {
        "store_review",
        "coming_soon",
        "build_review",
        "demo_release",
    }:
        raise ReadinessError("gates_invalid")
    classes = string_list(
        definition.get("requirement_classes"),
        "requirement_classes",
    )
    if set(classes) != {
        "official_required",
        "official_recommended",
        "conditional",
        "project_required",
    }:
        raise ReadinessError("requirement_classes_invalid")
    statuses = string_list(definition.get("statuses"), "statuses")
    if set(statuses) != {
        "not_started",
        "in_progress",
        "blocked",
        "ready_for_review",
        "done",
        "not_applicable",
    }:
        raise ReadinessError("statuses_invalid")

    conditions = definition.get("conditions")
    if not isinstance(conditions, dict):
        raise ReadinessError("conditions_required")
    for flag, default in conditions.items():
        require_string(flag, "condition")
        if default is not None and not isinstance(default, bool):
            raise ReadinessError(f"condition_default_invalid:{flag}")

    sources = definition.get("sources")
    if not isinstance(sources, dict) or not sources:
        raise ReadinessError("sources_required")
    for source_id, url in sources.items():
        parsed = urlparse(require_string(url, f"sources.{source_id}"))
        if parsed.scheme != "https" or parsed.netloc != "partner.steamgames.com":
            raise ReadinessError(f"official_source_invalid:{source_id}")

    items = normalized_items(definition)
    ensure_unique(
        (require_string(item.get("id"), "item.id") for item in items),
        "item.id",
    )
    by_id = {item["id"]: item for item in items}
    for item in items:
        item_id = item["id"]
        require_string(item.get("title"), f"{item_id}.title")
        if item.get("class") not in classes:
            raise ReadinessError(f"item_class_invalid:{item_id}")
        if item.get("role") not in roles:
            raise ReadinessError(f"item_role_unknown:{item_id}")
        item_gates = string_list(item.get("gates"), f"{item_id}.gates")
        ensure_unique(item_gates, f"{item_id}.gates")
        if not set(item_gates).issubset(set(gates)):
            raise ReadinessError(f"item_gates_invalid:{item_id}")
        if item.get("anchor") not in {"release", "coming_soon"}:
            raise ReadinessError(f"item_anchor_invalid:{item_id}")
        if not isinstance(item.get("offset"), int):
            raise ReadinessError(f"item_offset_invalid:{item_id}")
        if item.get("day_type") not in {"calendar", "business"}:
            raise ReadinessError(f"item_day_type_invalid:{item_id}")
        dependencies = string_list(
            item.get("dependencies"),
            f"{item_id}.dependencies",
        )
        ensure_unique(dependencies, f"{item_id}.dependencies")
        if item_id in dependencies:
            raise ReadinessError(f"item_self_dependency:{item_id}")
        condition = item.get("condition")
        if condition is not None and condition not in conditions:
            raise ReadinessError(
                f"item_condition_unknown:{item_id}:{condition}"
            )
        if item.get("class") == "conditional" and condition is None:
            raise ReadinessError(
                f"conditional_item_condition_required:{item_id}"
            )
        if not isinstance(item.get("blocking"), bool):
            raise ReadinessError(f"item_blocking_invalid:{item_id}")
        if not isinstance(item.get("evidence"), bool):
            raise ReadinessError(f"item_evidence_invalid:{item_id}")
        source_ids = string_list(item.get("sources"), f"{item_id}.sources")
        if not set(source_ids).issubset(set(sources)):
            raise ReadinessError(f"item_sources_invalid:{item_id}")
        if str(item.get("class")).startswith("official_") and not source_ids:
            raise ReadinessError(f"official_item_source_required:{item_id}")
        if not string_list(item.get("criteria"), f"{item_id}.criteria"):
            raise ReadinessError(f"item_criteria_required:{item_id}")

    for item in items:
        for dependency in item["dependencies"]:
            if dependency not in by_id:
                raise ReadinessError(
                    f"item_dependency_unknown:{item['id']}:{dependency}"
                )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(item_id: str) -> None:
        if item_id in visited:
            return
        if item_id in visiting:
            raise ReadinessError(f"item_dependency_cycle:{item_id}")
        visiting.add(item_id)
        for dependency in by_id[item_id]["dependencies"]:
            visit(dependency)
        visiting.remove(item_id)
        visited.add(item_id)

    for item_id in by_id:
        visit(item_id)


def condition_active(
    item: dict[str, Any],
    conditions: dict[str, bool | None],
) -> bool | None:
    flag = item.get("condition")
    return True if flag is None else conditions[flag]


def resolve_file_evidence(state_path: Path, value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        raise ReadinessError(f"absolute_evidence_path_not_allowed:{value}")
    root = state_path.parent.resolve()
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ReadinessError(
            f"evidence_path_outside_state_directory:{value}"
        ) from exc
    return resolved


def validate_state(
    definition: dict[str, Any],
    state: dict[str, Any],
    state_path: Path,
    *,
    require_files: bool = True,
) -> None:
    validate_definition(definition)
    if state.get("schema_version") != 1:
        raise ReadinessError("unsupported_state_schema")
    if state.get("ledger_id") != definition.get("ledger_id"):
        raise ReadinessError("state_identity_mismatch")
    definition_sha = state.get("definition_sha256")
    if definition_sha is not None:
        if not isinstance(definition_sha, str):
            raise ReadinessError("definition_sha256_invalid")
        if definition_sha != canonical_hash(definition):
            raise ReadinessError("definition_sha256_mismatch")

    parse_date(
        state.get("target_release_date"),
        "target_release_date",
        allow_none=True,
    )
    non_working_dates = state.get("non_working_dates")
    if not isinstance(non_working_dates, list):
        raise ReadinessError("non_working_dates_invalid")
    for index, value in enumerate(non_working_dates):
        parse_date(value, f"non_working_dates[{index}]")

    roles = state.get("role_assignments")
    if not isinstance(roles, dict) or set(roles) != set(definition["roles"]):
        raise ReadinessError("role_assignments_mismatch")
    for role, assignee in roles.items():
        if assignee is not None:
            require_string(assignee, f"role_assignments.{role}")

    conditions = state.get("conditions")
    if (
        not isinstance(conditions, dict)
        or set(conditions) != set(definition["conditions"])
    ):
        raise ReadinessError("conditions_mismatch")
    for flag, value in conditions.items():
        if value is not None and not isinstance(value, bool):
            raise ReadinessError(f"condition_value_invalid:{flag}")

    raw_states = state.get("items")
    if not isinstance(raw_states, list):
        raise ReadinessError("state_items_required")
    if not all(isinstance(value, dict) for value in raw_states):
        raise ReadinessError("state_item_must_be_object")
    ensure_unique(
        (
            require_string(value.get("id"), "state.item.id")
            for value in raw_states
        ),
        "state.item.id",
    )
    state_by_id = {value["id"]: value for value in raw_states}
    items = normalized_items(definition)
    if set(state_by_id) != {item["id"] for item in items}:
        raise ReadinessError("state_item_ids_mismatch")
    item_by_id = {item["id"]: item for item in items}

    for item_id, value in state_by_id.items():
        status = value.get("status")
        if status not in definition["statuses"]:
            raise ReadinessError(f"state_status_invalid:{item_id}:{status}")
        active = condition_active(item_by_id[item_id], conditions)
        if status == "not_applicable" and active is not False:
            raise ReadinessError(f"not_applicable_not_allowed:{item_id}")
        notes = value.get("notes")
        if not isinstance(notes, str):
            raise ReadinessError(f"notes_invalid:{item_id}")
        if status == "blocked" and not notes.strip():
            raise ReadinessError(f"blocked_notes_required:{item_id}")
        evidence = value.get("evidence")
        if not isinstance(evidence, list):
            raise ReadinessError(f"evidence_invalid:{item_id}")
        for entry in evidence:
            if not isinstance(entry, dict) or entry.get("type") not in VALID_EVIDENCE:
                raise ReadinessError(f"evidence_entry_invalid:{item_id}")
            evidence_value = require_string(
                entry.get("value"),
                f"{item_id}.evidence.value",
            )
            require_string(
                entry.get("description"),
                f"{item_id}.evidence.description",
            )
            if entry["type"] == "file":
                path = resolve_file_evidence(state_path, evidence_value)
                if require_files and not path.is_file():
                    raise ReadinessError(
                        f"evidence_file_not_found:{item_id}:{evidence_value}"
                    )
            elif entry["type"] == "url":
                parsed = urlparse(evidence_value)
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    raise ReadinessError(f"evidence_url_invalid:{item_id}")
        if status == "done" and item_by_id[item_id]["evidence"] and not evidence:
            raise ReadinessError(f"done_evidence_required:{item_id}")
        parse_date(
            value.get("due_date_override"),
            f"{item_id}.due_date_override",
            allow_none=True,
        )
        if value.get("owner_override") is not None:
            require_string(value["owner_override"], f"{item_id}.owner_override")
        parse_datetime(
            value.get("updated_at"),
            f"{item_id}.updated_at",
            allow_none=True,
        )
        if status == "done":
            for dependency in item_by_id[item_id]["dependencies"]:
                dependency_active = condition_active(
                    item_by_id[dependency],
                    conditions,
                )
                if (
                    dependency_active is not False
                    and state_by_id[dependency]["status"] != "done"
                ):
                    raise ReadinessError(
                        f"done_dependency_incomplete:{item_id}:{dependency}"
                    )

    approvals = state.get("gate_approvals")
    if (
        not isinstance(approvals, dict)
        or set(approvals) != set(definition["gates"])
    ):
        raise ReadinessError("gate_approvals_mismatch")
    for gate, approval in approvals.items():
        if not isinstance(approval, dict):
            raise ReadinessError(f"gate_approval_must_be_object:{gate}")
        decision = approval.get("decision")
        if decision not in VALID_APPROVALS:
            raise ReadinessError(f"gate_approval_invalid:{gate}:{decision}")
        if not isinstance(approval.get("notes"), str):
            raise ReadinessError(f"gate_approval_notes_invalid:{gate}")
        if decision == "pending":
            if (
                approval.get("approver") is not None
                or approval.get("decided_at") is not None
            ):
                raise ReadinessError(
                    f"pending_gate_metadata_not_allowed:{gate}"
                )
        else:
            require_string(approval.get("approver"), f"{gate}.approver")
            parse_datetime(approval.get("decided_at"), f"{gate}.decided_at")

    milestones = state.get("milestones")
    required_milestones = {
        "store_review_submitted_at",
        "store_review_approved_at",
        "coming_soon_published_at",
        "build_review_submitted_at",
        "build_review_approved_at",
        "demo_released_at",
    }
    if (
        not isinstance(milestones, dict)
        or set(milestones) != required_milestones
    ):
        raise ReadinessError("milestones_mismatch")
    for key, value in milestones.items():
        parse_datetime(value, f"milestones.{key}", allow_none=True)
