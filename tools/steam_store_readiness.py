from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.parse import urlparse

DEFINITION_PATH = Path('release/steam/store_readiness_v1.json')
STATE_PATH = Path('release/steam/store_readiness_status.json')
SUMMARY_PATH = Path('release/steam/STORE_READINESS_SUMMARY.md')
VALID_APPROVALS = {'pending', 'approved', 'rejected'}
VALID_EVIDENCE = {'file', 'url', 'steamworks', 'github', 'commit', 'artifact'}
EXIT_CONTRACT = 1
EXIT_INCOMPLETE = 2
EXIT_FAILED = 3


class ReadinessError(ValueError):
    pass


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
        return 0 if self.status == 'pass' else EXIT_INCOMPLETE if self.status == 'incomplete' else EXIT_FAILED

    def to_dict(self) -> dict[str, Any]:
        return {
            'gate': self.gate,
            'status': self.status,
            'failures': list(self.failures),
            'incomplete': list(self.incomplete),
            'warnings': list(self.warnings),
            'due_dates': self.due_dates,
        }


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError as exc:
        raise ReadinessError(f'json_not_found:{path}') from exc
    except json.JSONDecodeError as exc:
        raise ReadinessError(f'invalid_json:{path}:line={exc.lineno}:column={exc.colno}') from exc
    if not isinstance(value, dict):
        raise ReadinessError(f'json_root_not_object:{path}')
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f'.{path.name}.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def parse_date(value: Any, field: str, allow_none: bool = False) -> date | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not value:
        raise ReadinessError(f'invalid_date:{field}')
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ReadinessError(f'invalid_date:{field}:{value}') from exc


def parse_datetime(value: Any, field: str, allow_none: bool = False) -> datetime | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not value:
        raise ReadinessError(f'invalid_datetime:{field}')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ReadinessError(f'invalid_datetime:{field}:{value}') from exc
    if parsed.tzinfo is None:
        raise ReadinessError(f'datetime_timezone_required:{field}')
    return parsed


def require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReadinessError(f'nonempty_string_required:{field}')
    return value.strip()


def ensure_unique(values: Iterable[str], field: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ReadinessError(f'duplicate:{field}:{value}')
        seen.add(value)


def item_dict(definition: dict[str, Any], raw: Any) -> dict[str, Any]:
    fields = definition.get('item_fields')
    if not isinstance(fields, list) or not all(isinstance(field, str) for field in fields):
        raise ReadinessError('item_fields_invalid')
    if not isinstance(raw, list) or len(raw) != len(fields):
        raise ReadinessError('item_shape_invalid')
    return dict(zip(fields, raw, strict=True))


def normalized_items(definition: dict[str, Any]) -> list[dict[str, Any]]:
    values = definition.get('items')
    if not isinstance(values, list) or not values:
        raise ReadinessError('items_required')
    return [item_dict(definition, raw) for raw in values]


def validate_definition(definition: dict[str, Any]) -> None:
    if definition.get('schema_version') != 1:
        raise ReadinessError('unsupported_definition_schema')
    require_string(definition.get('ledger_id'), 'ledger_id')
    parse_date(definition.get('verified_on'), 'verified_on')
    freshness = definition.get('freshness_days')
    if not isinstance(freshness, int) or freshness <= 0:
        raise ReadinessError('freshness_days_invalid')
    roles = definition.get('roles')
    gates = definition.get('gates')
    classes = definition.get('requirement_classes')
    statuses = definition.get('statuses')
    conditions = definition.get('conditions')
    if not isinstance(roles, list) or not roles:
        raise ReadinessError('roles_required')
    if not isinstance(gates, list) or set(gates) != {'store_review', 'coming_soon', 'build_review', 'demo_release'}:
        raise ReadinessError('gates_invalid')
    if not isinstance(classes, list) or set(classes) != {'official_required', 'official_recommended', 'conditional', 'project_required'}:
        raise ReadinessError('requirement_classes_invalid')
    if not isinstance(statuses, list) or set(statuses) != {'not_started', 'in_progress', 'blocked', 'ready_for_review', 'done', 'not_applicable'}:
        raise ReadinessError('statuses_invalid')
    if not isinstance(conditions, dict):
        raise ReadinessError('conditions_required')
    for flag, default in conditions.items():
        require_string(flag, 'condition')
        if default is not None and not isinstance(default, bool):
            raise ReadinessError(f'condition_default_invalid:{flag}')
    sources = definition.get('sources')
    if not isinstance(sources, dict) or not sources:
        raise ReadinessError('sources_required')
    for source_id, url in sources.items():
        parsed = urlparse(require_string(url, f'sources.{source_id}'))
        if parsed.scheme != 'https' or parsed.netloc != 'partner.steamgames.com':
            raise ReadinessError(f'official_source_invalid:{source_id}')
    items = normalized_items(definition)
    ensure_unique((require_string(item.get('id'), 'item.id') for item in items), 'item.id')
    by_id = {item['id']: item for item in items}
    for item in items:
        item_id = item['id']
        require_string(item.get('title'), f'{item_id}.title')
        if item.get('class') not in classes:
            raise ReadinessError(f'item_class_invalid:{item_id}')
        if item.get('role') not in roles:
            raise ReadinessError(f'item_role_unknown:{item_id}')
        item_gates = item.get('gates')
        if not isinstance(item_gates, list) or not set(item_gates).issubset(set(gates)):
            raise ReadinessError(f'item_gates_invalid:{item_id}')
        if item.get('anchor') not in {'release', 'coming_soon'}:
            raise ReadinessError(f'item_anchor_invalid:{item_id}')
        if not isinstance(item.get('offset'), int) or item.get('day_type') not in {'calendar', 'business'}:
            raise ReadinessError(f'item_due_rule_invalid:{item_id}')
        dependencies = item.get('dependencies')
        if not isinstance(dependencies, list) or not all(isinstance(value, str) for value in dependencies):
            raise ReadinessError(f'item_dependencies_invalid:{item_id}')
        if item_id in dependencies:
            raise ReadinessError(f'item_self_dependency:{item_id}')
        condition = item.get('condition')
        if condition is not None and condition not in conditions:
            raise ReadinessError(f'item_condition_unknown:{item_id}:{condition}')
        if item.get('class') == 'conditional' and condition is None:
            raise ReadinessError(f'conditional_item_condition_required:{item_id}')
        if not isinstance(item.get('blocking'), bool) or not isinstance(item.get('evidence'), bool):
            raise ReadinessError(f'item_boolean_invalid:{item_id}')
        source_ids = item.get('sources')
        if not isinstance(source_ids, list) or not set(source_ids).issubset(set(sources)):
            raise ReadinessError(f'item_sources_invalid:{item_id}')
        if str(item.get('class')).startswith('official_') and not source_ids:
            raise ReadinessError(f'official_item_source_required:{item_id}')
        criteria = item.get('criteria')
        if not isinstance(criteria, list) or not criteria:
            raise ReadinessError(f'item_criteria_required:{item_id}')
    for item in items:
        for dependency in item['dependencies']:
            if dependency not in by_id:
                raise ReadinessError(f'item_dependency_unknown:{item["id"]}:{dependency}')
    visiting: set[str] = set()
    visited: set[str] = set()
    def visit(item_id: str) -> None:
        if item_id in visited:
            return
        if item_id in visiting:
            raise ReadinessError(f'item_dependency_cycle:{item_id}')
        visiting.add(item_id)
        for dependency in by_id[item_id]['dependencies']:
            visit(dependency)
        visiting.remove(item_id)
        visited.add(item_id)
    for item_id in by_id:
        visit(item_id)


def condition_active(item: dict[str, Any], conditions: dict[str, bool | None]) -> bool | None:
    flag = item.get('condition')
    return True if flag is None else conditions[flag]


def resolve_file_evidence(state_path: Path, value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        raise ReadinessError(f'absolute_evidence_path_not_allowed:{value}')
    root = state_path.parent.resolve()
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ReadinessError(f'evidence_path_outside_state_directory:{value}') from exc
    return resolved


def validate_state(definition: dict[str, Any], state: dict[str, Any], state_path: Path, require_files: bool = True) -> None:
    validate_definition(definition)
    if state.get('schema_version') != 1 or state.get('ledger_id') != definition.get('ledger_id'):
        raise ReadinessError('state_identity_mismatch')
    parse_date(state.get('target_release_date'), 'target_release_date', allow_none=True)
    dates = state.get('non_working_dates')
    if not isinstance(dates, list):
        raise ReadinessError('non_working_dates_invalid')
    for index, value in enumerate(dates):
        parse_date(value, f'non_working_dates[{index}]')
    role_assignments = state.get('role_assignments')
    if not isinstance(role_assignments, dict) or set(role_assignments) != set(definition['roles']):
        raise ReadinessError('role_assignments_mismatch')
    for role, assignee in role_assignments.items():
        if assignee is not None:
            require_string(assignee, f'role_assignments.{role}')
    conditions = state.get('conditions')
    if not isinstance(conditions, dict) or set(conditions) != set(definition['conditions']):
        raise ReadinessError('conditions_mismatch')
    for flag, value in conditions.items():
        if value is not None and not isinstance(value, bool):
            raise ReadinessError(f'condition_value_invalid:{flag}')
    raw_states = state.get('items')
    if not isinstance(raw_states, list):
        raise ReadinessError('state_items_required')
    ensure_unique((require_string(value.get('id'), 'state.item.id') for value in raw_states if isinstance(value, dict)), 'state.item.id')
    state_by_id = {value['id']: value for value in raw_states if isinstance(value, dict)}
    items = normalized_items(definition)
    if set(state_by_id) != {item['id'] for item in items}:
        raise ReadinessError('state_item_ids_mismatch')
    item_by_id = {item['id']: item for item in items}
    for item_id, value in state_by_id.items():
        status = value.get('status')
        if status not in definition['statuses']:
            raise ReadinessError(f'state_status_invalid:{item_id}:{status}')
        active = condition_active(item_by_id[item_id], conditions)
        if status == 'not_applicable' and active is not False:
            raise ReadinessError(f'not_applicable_not_allowed:{item_id}')
        notes = value.get('notes')
        if not isinstance(notes, str):
            raise ReadinessError(f'notes_invalid:{item_id}')
        if status == 'blocked' and not notes.strip():
            raise ReadinessError(f'blocked_notes_required:{item_id}')
        evidence = value.get('evidence')
        if not isinstance(evidence, list):
            raise ReadinessError(f'evidence_invalid:{item_id}')
        for entry in evidence:
            if not isinstance(entry, dict) or entry.get('type') not in VALID_EVIDENCE:
                raise ReadinessError(f'evidence_entry_invalid:{item_id}')
            evidence_value = require_string(entry.get('value'), f'{item_id}.evidence.value')
            require_string(entry.get('description'), f'{item_id}.evidence.description')
            if entry['type'] == 'file':
                path = resolve_file_evidence(state_path, evidence_value)
                if require_files and not path.is_file():
                    raise ReadinessError(f'evidence_file_not_found:{item_id}:{evidence_value}')
            if entry['type'] == 'url':
                parsed = urlparse(evidence_value)
                if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
                    raise ReadinessError(f'evidence_url_invalid:{item_id}')
        if status == 'done' and item_by_id[item_id]['evidence'] and not evidence:
            raise ReadinessError(f'done_evidence_required:{item_id}')
        override = value.get('due_date_override')
        parse_date(override, f'{item_id}.due_date_override', allow_none=True)
        owner = value.get('owner_override')
        if owner is not None:
            require_string(owner, f'{item_id}.owner_override')
        if status == 'done':
            for dependency in item_by_id[item_id]['dependencies']:
                dependency_state = state_by_id[dependency]['status']
                dependency_active = condition_active(item_by_id[dependency], conditions)
                if dependency_active is not False and dependency_state != 'done':
                    raise ReadinessError(f'done_dependency_incomplete:{item_id}:{dependency}')
    approvals = state.get('gate_approvals')
    if not isinstance(approvals, dict) or set(approvals) != set(definition['gates']):
        raise ReadinessError('gate_approvals_mismatch')
    for gate, approval in approvals.items():
        if not isinstance(approval, dict) or approval.get('decision') not in VALID_APPROVALS:
            raise ReadinessError(f'gate_approval_invalid:{gate}')
        if approval['decision'] == 'pending':
            if approval.get('approver') is not None or approval.get('decided_at') is not None:
                raise ReadinessError(f'pending_gate_metadata_not_allowed:{gate}')
        else:
            require_string(approval.get('approver'), f'{gate}.approver')
            parse_datetime(approval.get('decided_at'), f'{gate}.decided_at')
    milestones = state.get('milestones')
    required_milestones = {'store_review_submitted_at', 'store_review_approved_at', 'coming_soon_published_at', 'build_review_submitted_at', 'build_review_approved_at', 'demo_released_at'}
    if not isinstance(milestones, dict) or set(milestones) != required_milestones:
        raise ReadinessError('milestones_mismatch')
    for key, value in milestones.items():
        parse_datetime(value, f'milestones.{key}', allow_none=True)


def shift_business_days(start: date, offset: int, holidays: set[date]) -> date:
    current = start
    step = 1 if offset >= 0 else -1
    remaining = abs(offset)
    while remaining:
        current += timedelta(days=step)
        if current.weekday() < 5 and current not in holidays:
            remaining -= 1
    return current


def resolve_due_dates(definition: dict[str, Any], state: dict[str, Any]) -> dict[str, date | None]:
    release = parse_date(state.get('target_release_date'), 'target_release_date', allow_none=True)
    anchors = {'release': release, 'coming_soon': None if release is None else release - timedelta(days=14)}
    holidays = {parse_date(value, 'non_working_date') for value in state.get('non_working_dates', [])}
    state_by_id = {value['id']: value for value in state['items']}
    result: dict[str, date | None] = {}
    for item in normalized_items(definition):
        override = parse_date(state_by_id[item['id']].get('due_date_override'), 'due_date_override', allow_none=True)
        if override is not None:
            result[item['id']] = override
            continue
        anchor = anchors[item['anchor']]
        if anchor is None:
            result[item['id']] = None
        elif item['day_type'] == 'business':
            result[item['id']] = shift_business_days(anchor, item['offset'], holidays)
        else:
            result[item['id']] = anchor + timedelta(days=item['offset'])
    return result


def source_warnings(definition: dict[str, Any], today: date) -> list[str]:
    verified = parse_date(definition['verified_on'], 'verified_on')
    return [] if (today - verified).days <= definition['freshness_days'] else [f'official_sources_stale:verified_on={verified.isoformat()}']


def evaluate_gate(definition: dict[str, Any], state: dict[str, Any], gate: str, state_path: Path, today: date | None = None) -> GateResult:
    validate_state(definition, state, state_path, require_files=False)
    if gate not in definition['gates']:
        raise ReadinessError(f'gate_unknown:{gate}')
    today = today or date.today()
    due_dates = resolve_due_dates(definition, state)
    state_by_id = {value['id']: value for value in state['items']}
    failures: list[str] = []
    incomplete: list[str] = []
    warnings = source_warnings(definition, today)
    for item in normalized_items(definition):
        if gate not in item['gates']:
            continue
        item_id = item['id']
        active = condition_active(item, state['conditions'])
        if active is None:
            incomplete.append(f'condition_unresolved:{item_id}:{item["condition"]}')
            continue
        if active is False:
            if state_by_id[item_id]['status'] != 'not_applicable':
                incomplete.append(f'conditional_item_not_marked_na:{item_id}')
            continue
        owner = state_by_id[item_id].get('owner_override') or state['role_assignments'][item['role']]
        if not owner:
            incomplete.append(f'owner_unassigned:{item_id}:{item["role"]}')
        status = state_by_id[item_id]['status']
        due = due_dates[item_id]
        if status == 'blocked':
            failures.append(f'item_blocked:{item_id}')
        elif status != 'done':
            if item['class'] == 'official_recommended' or not item['blocking']:
                warnings.append(f'recommended_item_incomplete:{item_id}:{status}')
            else:
                incomplete.append(f'item_incomplete:{item_id}:{status}')
        if due is None:
            incomplete.append(f'due_date_unresolved:{item_id}')
        elif status != 'done' and due < today and item['blocking']:
            failures.append(f'item_overdue:{item_id}:due={due.isoformat()}')
    milestone_requirements = {
        'coming_soon': ['store_review_approved_at', 'coming_soon_published_at'],
        'build_review': ['store_review_approved_at'],
        'demo_release': ['store_review_approved_at', 'coming_soon_published_at', 'build_review_approved_at'],
    }
    for milestone in milestone_requirements.get(gate, []):
        if state['milestones'][milestone] is None:
            incomplete.append(f'milestone_missing:{milestone}')
    if gate == 'demo_release' and state['target_release_date'] and state['milestones']['coming_soon_published_at']:
        release = parse_date(state['target_release_date'], 'target_release_date')
        published = parse_datetime(state['milestones']['coming_soon_published_at'], 'coming_soon_published_at').date()
        if (release - published).days < 14:
            failures.append(f'coming_soon_period_short:days={(release - published).days}')
    approval = state['gate_approvals'][gate]
    if approval['decision'] == 'rejected':
        failures.append(f'gate_rejected:{gate}')
    elif approval['decision'] != 'approved':
        incomplete.append(f'gate_approval_pending:{gate}')
    status = 'fail' if failures else 'incomplete' if incomplete else 'pass'
    return GateResult(gate, status, tuple(sorted(set(failures))), tuple(sorted(set(incomplete))), tuple(sorted(set(warnings))), {key: value.isoformat() if value else None for key, value in due_dates.items()})


def render_summary(definition: dict[str, Any], state: dict[str, Any], state_path: Path, today: date | None = None) -> str:
    today = today or date.today()
    due = resolve_due_dates(definition, state)
    state_by_id = {value['id']: value for value in state['items']}
    lines = ['# Steam Store Readiness Summary', '', f'- Ledger: `{definition["ledger_id"]}`', f'- Target release: `{state.get("target_release_date") or "未確定"}`', f'- Official requirements verified: `{definition["verified_on"]}`', '', '## Gates', '', '| Gate | Status | Failures | Incomplete |', '|---|---|---:|---:|']
    for gate in definition['gates']:
        result = evaluate_gate(definition, state, gate, state_path, today)
        lines.append(f'| `{gate}` | **{result.status.upper()}** | {len(result.failures)} | {len(result.incomplete)} |')
    lines.extend(['', '## Roles', ''])
    for role in definition['roles']:
        lines.append(f'- `{role}`: {state["role_assignments"].get(role) or "未割当"}')
    lines.extend(['', '## Items', '', '| ID | Class | Status | Owner | Due | Title |', '|---|---|---|---|---|---|'])
    for item in normalized_items(definition):
        value = state_by_id[item['id']]
        owner = value.get('owner_override') or state['role_assignments'][item['role']] or '未割当'
        lines.append(f'| `{item["id"]}` | {item["class"]} | {value["status"]} | {owner} | {due[item["id"]].isoformat() if due[item["id"] else "未確定"} | {item["title"]} |')
    lines.extend(['', '## Official sources', ''])
    for source_id, url in definition['sources'].items():
        lines.append(f'- `{source_id}`: {url}')
    return '\n'.join(lines) + '\n'


def evidence_arg(value: str) -> dict[str, str]:
    parts = value.split('|', 2)
    if len(parts) != 3 or parts[0] not in VALID_EVIDENCE:
        raise ReadinessError('evidence_format:type|value|description')
    return {'type': parts[0], 'value': require_string(parts[1], 'evidence.value'), 'description': require_string(parts[2], 'evidence.description')}


def load_pair(args: argparse.Namespace, require_files: bool = True) -> tuple[dict[str, Any], dict[str, Any]]:
    definition = load_json(Path(args.definition))
    state = load_json(Path(args.state))
    validate_state(definition, state, Path(args.state), require_files=require_files)
    return definition, state


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def command_validate(args: argparse.Namespace) -> int:
    definition, state = load_pair(args, require_files=not args.skip_evidence_existence)
    summary = render_summary(definition, state, Path(args.state))
    Path(args.summary).write_text(summary, encoding='utf-8')
    print(json.dumps({'status': 'valid', 'items': len(normalized_items(definition)), 'summary': args.summary}, ensure_ascii=False, indent=2))
    return 0


def command_gate(args: argparse.Namespace) -> int:
    definition, state = load_pair(args, require_files=False)
    result = evaluate_gate(definition, state, args.gate, Path(args.state))
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return result.exit_code


def command_set_plan(args: argparse.Namespace) -> int:
    state = load_json(Path(args.state))
    parse_date(args.release_date, 'release_date')
    state['target_release_date'] = args.release_date
    state['non_working_dates'] = list(dict.fromkeys(args.non_working_date))
    write_json(Path(args.state), state)
    return 0


def command_assign_role(args: argparse.Namespace) -> int:
    definition = load_json(Path(args.definition))
    state = load_json(Path(args.state))
    if args.role not in definition['roles']:
        raise ReadinessError(f'role_unknown:{args.role}')
    state['role_assignments'][args.role] = require_string(args.assignee, 'assignee')
    write_json(Path(args.state), state)
    return 0


def command_set_condition(args: argparse.Namespace) -> int:
    definition = load_json(Path(args.definition))
    state = load_json(Path(args.state))
    if args.condition not in definition['conditions']:
        raise ReadinessError(f'condition_unknown:{args.condition}')
    state['conditions'][args.condition] = None if args.value == 'unknown' else args.value == 'true'
    write_json(Path(args.state), state)
    return 0


def command_record(args: argparse.Namespace) -> int:
    definition = load_json(Path(args.definition))
    state = load_json(Path(args.state))
    item_ids = {item['id'] for item in normalized_items(definition)}
    if args.item_id not in item_ids:
        raise ReadinessError(f'item_unknown:{args.item_id}')
    if args.status not in definition['statuses']:
        raise ReadinessError(f'status_unknown:{args.status}')
    value = next(item for item in state['items'] if item['id'] == args.item_id)
    value['status'] = args.status
    if args.notes is not None:
        value['notes'] = args.notes
    if args.owner is not None:
        value['owner_override'] = args.owner
    if args.due_date is not None:
        parse_date(args.due_date, 'due_date')
        value['due_date_override'] = args.due_date
    if args.evidence:
        value['evidence'].extend(evidence_arg(entry) for entry in args.evidence)
    value['updated_at'] = now_iso()
    validate_state(definition, state, Path(args.state), require_files=False)
    write_json(Path(args.state), state)
    return 0


def command_set_milestone(args: argparse.Namespace) -> int:
    state = load_json(Path(args.state))
    if args.milestone not in state['milestones']:
        raise ReadinessError(f'milestone_unknown:{args.milestone}')
    if args.value != 'clear':
        parse_datetime(args.value, 'milestone')
    state['milestones'][args.milestone] = None if args.value == 'clear' else args.value
    write_json(Path(args.state), state)
    return 0


def command_approve(args: argparse.Namespace) -> int:
    definition, state = load_pair(args, require_files=False)
    result = evaluate_gate(definition, state, args.gate, Path(args.state))
    core_failures = result.failures
    core_incomplete = tuple(value for value in result.incomplete if value != f'gate_approval_pending:{args.gate}')
    if core_failures or core_incomplete:
        raise ReadinessError(f'gate_not_approvable:{args.gate}')
    state['gate_approvals'][args.gate] = {'decision': 'approved', 'approver': require_string(args.approver, 'approver'), 'decided_at': now_iso(), 'notes': args.notes or ''}
    write_json(Path(args.state), state)
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description='Steam Store Readiness台帳を検証・更新する')
    sub = root.add_subparsers(dest='command', required=True)
    def common(command: argparse.ArgumentParser) -> None:
        command.add_argument('--definition', default=str(DEFINITION_PATH))
        command.add_argument('--state', default=str(STATE_PATH))
    validate = sub.add_parser('validate'); common(validate); validate.add_argument('--summary', default=str(SUMMARY_PATH)); validate.add_argument('--skip-evidence-existence', action='store_true'); validate.set_defaults(handler=command_validate)
    gate = sub.add_parser('gate'); common(gate); gate.add_argument('--gate', required=True); gate.set_defaults(handler=command_gate)
    plan = sub.add_parser('set-plan'); plan.add_argument('--state', default=str(STATE_PATH)); plan.add_argument('--release-date', required=True); plan.add_argument('--non-working-date', action='append', default=[]); plan.set_defaults(handler=command_set_plan)
    role = sub.add_parser('assign-role'); common(role); role.add_argument('--role', required=True); role.add_argument('--assignee', required=True); role.set_defaults(handler=command_assign_role)
    condition = sub.add_parser('set-condition'); common(condition); condition.add_argument('--condition', required=True); condition.add_argument('--value', choices=['true', 'false', 'unknown'], required=True); condition.set_defaults(handler=command_set_condition)
    record = sub.add_parser('record'); common(record); record.add_argument('--item-id', required=True); record.add_argument('--status', required=True); record.add_argument('--notes'); record.add_argument('--owner'); record.add_argument('--due-date'); record.add_argument('--evidence', action='append', default=[]); record.set_defaults(handler=command_record)
    milestone = sub.add_parser('set-milestone'); milestone.add_argument('--state', default=str(STATE_PATH)); milestone.add_argument('--milestone', required=True); milestone.add_argument('--value', required=True); milestone.set_defaults(handler=command_set_milestone)
    approve = sub.add_parser('approve-gate'); common(approve); approve.add_argument('--gate', required=True); approve.add_argument('--approver', required=True); approve.add_argument('--notes'); approve.set_defaults(handler=command_approve)
    return root


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        return int(args.handler(args))
    except ReadinessError as exc:
        print(f'Steam Store Readiness検証エラー: {exc}', file=sys.stderr)
        return EXIT_CONTRACT


if __name__ == '__main__':
    raise SystemExit(main())
