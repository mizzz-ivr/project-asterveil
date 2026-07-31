from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.steam_store_readiness_contract import (
    ReadinessError,
    VALID_EVIDENCE,
    load_json,
    normalized_items,
    parse_date,
    parse_datetime,
    require_string,
    validate_state,
    write_json,
)
from tools.steam_store_readiness_gate import evaluate_gate, render_summary

DEFINITION_PATH = Path("release/steam/store_readiness_v1.json")
STATE_PATH = Path("release/steam/store_readiness_status.json")
SUMMARY_PATH = Path("release/steam/STORE_READINESS_SUMMARY.md")
EXIT_CONTRACT = 1


def load_pair(args: argparse.Namespace, require_files: bool = True) -> tuple[dict, dict]:
    definition = load_json(Path(args.definition))
    state = load_json(Path(args.state))
    validate_state(definition, state, Path(args.state), require_files=require_files)
    return definition, state


def parse_evidence(value: str) -> dict[str, str]:
    parts = value.split("|", 2)
    if len(parts) != 3 or parts[0] not in VALID_EVIDENCE:
        raise ReadinessError("evidence_format:type|value|description")
    return {
        "type": parts[0],
        "value": require_string(parts[1], "evidence.value"),
        "description": require_string(parts[2], "evidence.description"),
    }


def command_validate(args: argparse.Namespace) -> int:
    definition, state = load_pair(args, not args.skip_evidence_existence)
    summary = render_summary(definition, state, Path(args.state))
    summary_path = Path(args.summary)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(summary, encoding="utf-8")
    print(json.dumps({
        "status": "valid",
        "items": len(normalized_items(definition)),
        "summary": str(summary_path),
    }, ensure_ascii=False, indent=2))
    return 0


def command_gate(args: argparse.Namespace) -> int:
    definition, state = load_pair(args, False)
    result = evaluate_gate(definition, state, args.gate, Path(args.state))
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return result.exit_code


def command_set_plan(args: argparse.Namespace) -> int:
    state = load_json(Path(args.state))
    parse_date(args.release_date, "release_date")
    for value in args.non_working_date:
        parse_date(value, "non_working_date")
    state["target_release_date"] = args.release_date
    state["non_working_dates"] = list(dict.fromkeys(args.non_working_date))
    write_json(Path(args.state), state)
    return 0


def command_assign_role(args: argparse.Namespace) -> int:
    definition = load_json(Path(args.definition))
    state = load_json(Path(args.state))
    if args.role not in definition["roles"]:
        raise ReadinessError(f"role_unknown:{args.role}")
    state["role_assignments"][args.role] = require_string(args.assignee, "assignee")
    write_json(Path(args.state), state)
    return 0


def command_set_condition(args: argparse.Namespace) -> int:
    definition = load_json(Path(args.definition))
    state = load_json(Path(args.state))
    if args.condition not in definition["conditions"]:
        raise ReadinessError(f"condition_unknown:{args.condition}")
    state["conditions"][args.condition] = (
        None if args.value == "unknown" else args.value == "true"
    )
    write_json(Path(args.state), state)
    return 0


def command_record(args: argparse.Namespace) -> int:
    definition = load_json(Path(args.definition))
    state = load_json(Path(args.state))
    if args.item_id not in {item["id"] for item in normalized_items(definition)}:
        raise ReadinessError(f"item_unknown:{args.item_id}")
    if args.status not in definition["statuses"]:
        raise ReadinessError(f"status_unknown:{args.status}")
    value = next(item for item in state["items"] if item["id"] == args.item_id)
    value["status"] = args.status
    if args.notes is not None:
        value["notes"] = args.notes
    if args.owner is not None:
        value["owner_override"] = args.owner
    if args.due_date is not None:
        parse_date(args.due_date, "due_date")
        value["due_date_override"] = args.due_date
    value["evidence"].extend(parse_evidence(entry) for entry in args.evidence)
    value["updated_at"] = datetime.now(timezone.utc).isoformat()
    validate_state(definition, state, Path(args.state), require_files=False)
    write_json(Path(args.state), state)
    return 0


def command_set_milestone(args: argparse.Namespace) -> int:
    state = load_json(Path(args.state))
    if args.milestone not in state["milestones"]:
        raise ReadinessError(f"milestone_unknown:{args.milestone}")
    if args.value != "clear":
        parse_datetime(args.value, "milestone")
    state["milestones"][args.milestone] = None if args.value == "clear" else args.value
    write_json(Path(args.state), state)
    return 0


def command_approve_gate(args: argparse.Namespace) -> int:
    definition, state = load_pair(args, False)
    result = evaluate_gate(definition, state, args.gate, Path(args.state))
    pending = f"gate_approval_pending:{args.gate}"
    core_incomplete = [reason for reason in result.incomplete if reason != pending]
    if result.failures or core_incomplete:
        raise ReadinessError(f"gate_not_approvable:{args.gate}")
    state["gate_approvals"][args.gate] = {
        "decision": "approved",
        "approver": require_string(args.approver, "approver"),
        "decided_at": datetime.now(timezone.utc).isoformat(),
        "notes": args.notes or "",
    }
    write_json(Path(args.state), state)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Steam Store Readiness台帳を検証・更新する")
    commands = parser.add_subparsers(dest="command", required=True)

    def common(command: argparse.ArgumentParser) -> None:
        command.add_argument("--definition", default=str(DEFINITION_PATH))
        command.add_argument("--state", default=str(STATE_PATH))

    validate = commands.add_parser("validate")
    common(validate)
    validate.add_argument("--summary", default=str(SUMMARY_PATH))
    validate.add_argument("--skip-evidence-existence", action="store_true")
    validate.set_defaults(handler=command_validate)

    gate = commands.add_parser("gate")
    common(gate)
    gate.add_argument("--gate", choices=["store_review", "coming_soon", "build_review", "demo_release"], required=True)
    gate.set_defaults(handler=command_gate)

    plan = commands.add_parser("set-plan")
    plan.add_argument("--state", default=str(STATE_PATH))
    plan.add_argument("--release-date", required=True)
    plan.add_argument("--non-working-date", action="append", default=[])
    plan.set_defaults(handler=command_set_plan)

    role = commands.add_parser("assign-role")
    common(role)
    role.add_argument("--role", required=True)
    role.add_argument("--assignee", required=True)
    role.set_defaults(handler=command_assign_role)

    condition = commands.add_parser("set-condition")
    common(condition)
    condition.add_argument("--condition", required=True)
    condition.add_argument("--value", choices=["true", "false", "unknown"], required=True)
    condition.set_defaults(handler=command_set_condition)

    record = commands.add_parser("record")
    common(record)
    record.add_argument("--item-id", required=True)
    record.add_argument("--status", required=True)
    record.add_argument("--notes")
    record.add_argument("--owner")
    record.add_argument("--due-date")
    record.add_argument("--evidence", action="append", default=[])
    record.set_defaults(handler=command_record)

    milestone = commands.add_parser("set-milestone")
    milestone.add_argument("--state", default=str(STATE_PATH))
    milestone.add_argument("--milestone", required=True)
    milestone.add_argument("--value", required=True)
    milestone.set_defaults(handler=command_set_milestone)

    approve = commands.add_parser("approve-gate")
    common(approve)
    approve.add_argument("--gate", choices=["store_review", "coming_soon", "build_review", "demo_release"], required=True)
    approve.add_argument("--approver", required=True)
    approve.add_argument("--notes")
    approve.set_defaults(handler=command_approve_gate)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return int(args.handler(args))
    except ReadinessError as exc:
        print(f"Steam Store Readiness検証エラー: {exc}", file=sys.stderr)
        return EXIT_CONTRACT


if __name__ == "__main__":
    raise SystemExit(main())
