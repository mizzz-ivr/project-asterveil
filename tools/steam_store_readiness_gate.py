from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from tools.steam_store_readiness_contract import (
    ReadinessError,
    condition_active,
    normalized_items,
    parse_date,
    parse_datetime,
    validate_state,
)

EXIT_INCOMPLETE = 2
EXIT_FAILED = 3


@dataclass(frozen=True)
class GateResult:
    gate: str
    status: str
    failures: tuple[str, ...]
    incomplete: tuple[str, ...]
    warnings: tuple[str, ...]
    due_dates: dict[str, str | None]

    @property
    def exit_code(self) -> int:
        if self.status == "pass":
            return 0
        if self.status == "incomplete":
            return EXIT_INCOMPLETE
        return EXIT_FAILED

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate,
            "status": self.status,
            "failures": list(self.failures),
            "incomplete": list(self.incomplete),
            "warnings": list(self.warnings),
            "due_dates": self.due_dates,
        }


def shift_business_days(
    start: date,
    offset: int,
    non_working_dates: set[date],
) -> date:
    current = start
    step = 1 if offset >= 0 else -1
    remaining = abs(offset)
    while remaining:
        current += timedelta(days=step)
        if current.weekday() < 5 and current not in non_working_dates:
            remaining -= 1
    return current


def resolve_due_dates(
    definition: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, date | None]:
    release = parse_date(
        state.get("target_release_date"),
        "target_release_date",
        allow_none=True,
    )
    anchors = {
        "release": release,
        "coming_soon": (
            None
            if release is None
            else release - timedelta(days=14)
        ),
    }
    non_working_dates = {
        parsed
        for value in state.get("non_working_dates", [])
        if (parsed := parse_date(value, "non_working_date")) is not None
    }
    state_by_id = {value["id"]: value for value in state["items"]}
    result: dict[str, date | None] = {}
    for item in normalized_items(definition):
        override = parse_date(
            state_by_id[item["id"]].get("due_date_override"),
            f"{item['id']}.due_date_override",
            allow_none=True,
        )
        if override is not None:
            result[item["id"]] = override
            continue
        anchor = anchors[item["anchor"]]
        if anchor is None:
            result[item["id"]] = None
        elif item["day_type"] == "business":
            result[item["id"]] = shift_business_days(
                anchor,
                item["offset"],
                non_working_dates,
            )
        else:
            result[item["id"]] = anchor + timedelta(
                days=item["offset"]
            )
    return result


def source_warnings(
    definition: dict[str, Any],
    today: date,
) -> list[str]:
    verified = parse_date(definition["verified_on"], "verified_on")
    age = (today - verified).days
    if age <= definition["freshness_days"]:
        return []
    return [
        f"official_sources_stale:verified_on={verified.isoformat()}:age={age}"
    ]


def evaluate_gate(
    definition: dict[str, Any],
    state: dict[str, Any],
    gate: str,
    state_path: Path,
    *,
    today: date | None = None,
) -> GateResult:
    validate_state(
        definition,
        state,
        state_path,
        require_files=False,
    )
    if gate not in definition["gates"]:
        raise ReadinessError(f"gate_unknown:{gate}")

    today = today or date.today()
    due_dates = resolve_due_dates(definition, state)
    state_by_id = {value["id"]: value for value in state["items"]}
    failures: list[str] = []
    incomplete: list[str] = []
    warnings = source_warnings(definition, today)

    for item in normalized_items(definition):
        if gate not in item["gates"]:
            continue
        item_id = item["id"]
        active = condition_active(item, state["conditions"])
        if active is None:
            incomplete.append(
                f"condition_unresolved:{item_id}:{item['condition']}"
            )
            continue
        if active is False:
            if state_by_id[item_id]["status"] != "not_applicable":
                incomplete.append(
                    f"conditional_item_not_marked_na:{item_id}"
                )
            continue

        owner = (
            state_by_id[item_id].get("owner_override")
            or state["role_assignments"][item["role"]]
        )
        if not owner:
            incomplete.append(
                f"owner_unassigned:{item_id}:{item['role']}"
            )

        status = state_by_id[item_id]["status"]
        due = due_dates[item_id]
        if status == "blocked":
            failures.append(f"item_blocked:{item_id}")
        elif status != "done":
            reason = f"item_incomplete:{item_id}:{status}"
            if (
                item["class"] == "official_recommended"
                or not item["blocking"]
            ):
                warnings.append(reason)
            else:
                incomplete.append(reason)

        if due is None:
            incomplete.append(f"due_date_unresolved:{item_id}")
        elif (
            status != "done"
            and due < today
            and item["blocking"]
        ):
            failures.append(
                f"item_overdue:{item_id}:due={due.isoformat()}"
            )

    milestone_requirements = {
        "coming_soon": [
            "store_review_approved_at",
            "coming_soon_published_at",
        ],
        "build_review": ["store_review_approved_at"],
        "demo_release": [
            "store_review_approved_at",
            "coming_soon_published_at",
            "build_review_approved_at",
        ],
    }
    for milestone in milestone_requirements.get(gate, []):
        if state["milestones"][milestone] is None:
            incomplete.append(f"milestone_missing:{milestone}")

    if (
        gate == "demo_release"
        and state["target_release_date"]
        and state["milestones"]["coming_soon_published_at"]
    ):
        release = parse_date(
            state["target_release_date"],
            "target_release_date",
        )
        published = parse_datetime(
            state["milestones"]["coming_soon_published_at"],
            "coming_soon_published_at",
        ).date()
        period_days = (release - published).days
        if period_days < 14:
            failures.append(
                f"coming_soon_period_short:days={period_days}"
            )

    approval = state["gate_approvals"][gate]
    if approval["decision"] == "rejected":
        failures.append(f"gate_rejected:{gate}")
    elif approval["decision"] != "approved":
        incomplete.append(f"gate_approval_pending:{gate}")

    status = (
        "fail"
        if failures
        else "incomplete"
        if incomplete
        else "pass"
    )
    return GateResult(
        gate=gate,
        status=status,
        failures=tuple(sorted(set(failures))),
        incomplete=tuple(sorted(set(incomplete))),
        warnings=tuple(sorted(set(warnings))),
        due_dates={
            key: value.isoformat() if value else None
            for key, value in due_dates.items()
        },
    )


def render_summary(
    definition: dict[str, Any],
    state: dict[str, Any],
    state_path: Path,
    *,
    today: date | None = None,
) -> str:
    today = today or date.today()
    due_dates = resolve_due_dates(definition, state)
    state_by_id = {value["id"]: value for value in state["items"]}
    lines = [
        "# Steam Store Readiness Summary",
        "",
        f"- Ledger: `{definition['ledger_id']}`",
        f"- Target release: `{state.get('target_release_date') or '未確定'}`",
        f"- Official requirements verified: `{definition['verified_on']}`",
        "",
        "## Gates",
        "",
        "| Gate | Status | Failures | Incomplete | Warnings |",
        "|---|---|---:|---:|---:|",
    ]
    for gate in definition["gates"]:
        result = evaluate_gate(
            definition,
            state,
            gate,
            state_path,
            today=today,
        )
        lines.append(
            f"| `{gate}` | **{result.status.upper()}** | "
            f"{len(result.failures)} | {len(result.incomplete)} | "
            f"{len(result.warnings)} |"
        )

    lines.extend(["", "## Roles", ""])
    for role in definition["roles"]:
        assignee = state["role_assignments"].get(role) or "未割当"
        lines.append(f"- `{role}`: {assignee}")

    lines.extend(
        [
            "",
            "## Items",
            "",
            "| ID | Class | Status | Owner | Due | Title |",
            "|---|---|---|---|---|---|",
        ]
    )
    for item in normalized_items(definition):
        value = state_by_id[item["id"]]
        owner = (
            value.get("owner_override")
            or state["role_assignments"][item["role"]]
            or "未割当"
        )
        due = due_dates[item["id"]]
        due_text = due.isoformat() if due else "未確定"
        lines.append(
            f"| `{item['id']}` | {item['class']} | "
            f"{value['status']} | {owner} | {due_text} | "
            f"{item['title']} |"
        )

    lines.extend(["", "## Official sources", ""])
    for source_id, url in definition["sources"].items():
        lines.append(f"- `{source_id}`: {url}")
    return "\n".join(lines) + "\n"
