from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence


DEFAULT_CHECKLIST_PATH = Path("qa/steam_demo/checklist_v1.json")
REPORT_FILE_NAME = "report.json"
BUILD_MANIFEST_FILE_NAME = "build_manifest.json"
SUMMARY_FILE_NAME = "SUMMARY.md"

RESULT_STATUSES = {"pending", "pass", "fail", "blocked", "skipped"}
DEFECT_SEVERITIES = {"blocker", "critical", "high", "medium", "low"}
DEFECT_STATUSES = {"open", "fixed", "verified", "deferred", "duplicate"}
DECISION_STATUSES = {"pending", "approved", "rejected"}
EVIDENCE_TYPES = {"screenshot", "log", "video", "note", "other"}
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


class QaValidationError(ValueError):
    """QA定義または実行記録が契約を満たさない場合の例外。"""


class GateStatus(str, Enum):
    PASS = "pass"
    INCOMPLETE = "incomplete"
    FAIL = "fail"


@dataclass(frozen=True)
class GateEvaluation:
    status: GateStatus
    blocking_reasons: tuple[str, ...]
    incomplete_reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    result_counts: Mapping[str, int]

    @property
    def exit_code(self) -> int:
        if self.status == GateStatus.PASS:
            return 0
        if self.status == GateStatus.INCOMPLETE:
            return 2
        return 3

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "blocking_reasons": list(self.blocking_reasons),
            "incomplete_reasons": list(self.incomplete_reasons),
            "warnings": list(self.warnings),
            "result_counts": dict(self.result_counts),
            "exit_code": self.exit_code,
        }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _require_mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise QaValidationError(f"{field}_must_be_object")
    return value


def _require_list(value: object, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise QaValidationError(f"{field}_must_be_list")
    return value


def _require_string(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise QaValidationError(f"{field}_must_be_string")
    normalized = value.strip()
    if not allow_empty and not normalized:
        raise QaValidationError(f"{field}_must_not_be_empty")
    return normalized


def _require_identifier(value: object, field: str) -> str:
    identifier = _require_string(value, field)
    if not IDENTIFIER_PATTERN.fullmatch(identifier):
        raise QaValidationError(f"{field}_has_invalid_characters:{identifier}")
    return identifier


def _require_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise QaValidationError(f"{field}_must_be_boolean")
    return value


def _require_positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise QaValidationError(f"{field}_must_be_positive_integer")
    return value


def _require_string_list(value: object, field: str, *, allow_empty: bool = False) -> list[str]:
    values = _require_list(value, field)
    if not allow_empty and not values:
        raise QaValidationError(f"{field}_must_not_be_empty")
    normalized = [_require_string(item, f"{field}[{index}]") for index, item in enumerate(values)]
    if len(normalized) != len(set(normalized)):
        raise QaValidationError(f"{field}_contains_duplicates")
    return normalized


def _parse_iso_datetime(value: object, field: str, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    text = _require_string(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise QaValidationError(f"{field}_must_be_iso_datetime") from exc
    if parsed.tzinfo is None:
        raise QaValidationError(f"{field}_must_include_timezone")
    return text


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise QaValidationError(f"json_file_not_found:{path}") from exc
    except json.JSONDecodeError as exc:
        raise QaValidationError(f"invalid_json:{path}:{exc.msg}") from exc
    return dict(_require_mapping(payload, f"json:{path}"))


def write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def canonical_json_bytes(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checklist_definition_hash(checklist: Mapping[str, object]) -> str:
    return sha256_bytes(canonical_json_bytes(checklist))


def validate_checklist(checklist: Mapping[str, object]) -> dict[str, Mapping[str, Any]]:
    if checklist.get("schema_version") != 1:
        raise QaValidationError("unsupported_checklist_schema_version")
    _require_identifier(checklist.get("checklist_id"), "checklist_id")
    _require_positive_int(checklist.get("checklist_version"), "checklist_version")
    _require_string(checklist.get("title"), "checklist_title")
    _require_string(checklist.get("description"), "checklist_description")
    _require_positive_int(
        checklist.get("minimum_complete_environments"),
        "minimum_complete_environments",
    )
    blocking_severities = set(
        _require_string_list(
            checklist.get("release_blocking_defect_severities"),
            "release_blocking_defect_severities",
        )
    )
    if not blocking_severities <= DEFECT_SEVERITIES:
        unknown = sorted(blocking_severities - DEFECT_SEVERITIES)
        raise QaValidationError(
            "unknown_release_blocking_defect_severities:" + ",".join(unknown)
        )

    sections = _require_list(checklist.get("sections"), "checklist_sections")
    if not sections:
        raise QaValidationError("checklist_sections_must_not_be_empty")

    section_ids: set[str] = set()
    cases: dict[str, Mapping[str, Any]] = {}
    for section_index, section_value in enumerate(sections):
        section = _require_mapping(section_value, f"sections[{section_index}]")
        section_id = _require_identifier(section.get("id"), f"sections[{section_index}].id")
        if section_id in section_ids:
            raise QaValidationError(f"duplicate_checklist_section_id:{section_id}")
        section_ids.add(section_id)
        _require_string(section.get("title"), f"sections[{section_index}].title")
        case_values = _require_list(
            section.get("cases"),
            f"sections[{section_index}].cases",
        )
        if not case_values:
            raise QaValidationError(f"checklist_section_has_no_cases:{section_id}")

        for case_index, case_value in enumerate(case_values):
            field_prefix = f"sections[{section_index}].cases[{case_index}]"
            case = _require_mapping(case_value, field_prefix)
            case_id = _require_identifier(case.get("id"), f"{field_prefix}.id")
            if case_id in cases:
                raise QaValidationError(f"duplicate_checklist_case_id:{case_id}")
            _require_string(case.get("title"), f"{field_prefix}.title")
            _require_string(case.get("purpose"), f"{field_prefix}.purpose")
            _require_string_list(case.get("preconditions"), f"{field_prefix}.preconditions")
            _require_string_list(case.get("steps"), f"{field_prefix}.steps")
            _require_string_list(
                case.get("expected_results"),
                f"{field_prefix}.expected_results",
            )
            release_blocking = _require_bool(
                case.get("release_blocking"),
                f"{field_prefix}.release_blocking",
            )
            allow_skip = _require_bool(case.get("allow_skip"), f"{field_prefix}.allow_skip")
            _require_bool(
                case.get("evidence_required"),
                f"{field_prefix}.evidence_required",
            )
            _require_string_list(case.get("tags"), f"{field_prefix}.tags")
            if release_blocking and allow_skip:
                raise QaValidationError(
                    f"release_blocking_case_cannot_allow_skip:{case_id}"
                )
            cases[case_id] = case

    return cases


def load_checklist(path: Path = DEFAULT_CHECKLIST_PATH) -> dict[str, Any]:
    checklist = load_json_object(path)
    validate_checklist(checklist)
    return checklist


def validate_build_manifest(manifest: Mapping[str, object]) -> None:
    if manifest.get("schema_version") != 1:
        raise QaValidationError("unsupported_build_manifest_schema_version")
    _require_string(manifest.get("application_name"), "build_manifest.application_name")
    _require_string(manifest.get("artifact_name"), "build_manifest.artifact_name")
    _require_string(manifest.get("git_sha"), "build_manifest.git_sha")
    _require_string(manifest.get("version_label"), "build_manifest.version_label")
    _parse_iso_datetime(manifest.get("created_at_utc"), "build_manifest.created_at_utc")
    files = _require_list(manifest.get("files"), "build_manifest.files")
    if not files:
        raise QaValidationError("build_manifest_files_must_not_be_empty")


def _relative_run_file(run_directory: Path, relative_path: str, field: str) -> Path:
    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise QaValidationError(f"{field}_must_be_relative")
    resolved_run_directory = run_directory.resolve()
    resolved_candidate = (run_directory / candidate).resolve()
    try:
        resolved_candidate.relative_to(resolved_run_directory)
    except ValueError as exc:
        raise QaValidationError(f"{field}_escapes_run_directory:{relative_path}") from exc
    return resolved_candidate


def create_run_report(
    *,
    checklist_path: Path,
    manifest_path: Path,
    output_directory: Path,
    tester: str,
    os_name: str,
    os_version: str,
    architecture: str,
    display_resolution: str,
    dpi_scale_percent: int,
    input_methods: Sequence[str],
    run_id: str | None = None,
    artifact_digest: str = "",
    environment_notes: str = "",
) -> Path:
    checklist = load_checklist(checklist_path)
    manifest = load_json_object(manifest_path)
    validate_build_manifest(manifest)

    tester = _require_string(tester, "tester")
    os_name = _require_string(os_name, "os_name")
    os_version = _require_string(os_version, "os_version")
    architecture = _require_string(architecture, "architecture")
    display_resolution = _require_string(display_resolution, "display_resolution")
    if isinstance(dpi_scale_percent, bool) or dpi_scale_percent <= 0:
        raise QaValidationError("dpi_scale_percent_must_be_positive_integer")
    normalized_input_methods = [
        _require_identifier(value, f"input_methods[{index}]")
        for index, value in enumerate(input_methods)
    ]
    if not normalized_input_methods:
        raise QaValidationError("input_methods_must_not_be_empty")
    if len(normalized_input_methods) != len(set(normalized_input_methods)):
        raise QaValidationError("input_methods_contains_duplicates")

    now = utc_now_iso()
    resolved_run_id = run_id or (
        f"qa-{str(manifest['git_sha'])[:8]}-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    resolved_run_id = _require_identifier(resolved_run_id, "run_id")

    if output_directory.exists() and any(output_directory.iterdir()):
        raise QaValidationError(f"qa_run_directory_not_empty:{output_directory}")
    output_directory.mkdir(parents=True, exist_ok=True)
    copied_manifest = output_directory / BUILD_MANIFEST_FILE_NAME
    shutil.copy2(manifest_path, copied_manifest)

    cases = validate_checklist(checklist)
    ordered_case_ids = [
        str(case["id"])
        for section in checklist["sections"]
        for case in section["cases"]
    ]
    report: dict[str, object] = {
        "schema_version": 1,
        "run_id": resolved_run_id,
        "checklist": {
            "id": checklist["checklist_id"],
            "version": checklist["checklist_version"],
            "definition_sha256": checklist_definition_hash(checklist),
        },
        "build": {
            "manifest_file": BUILD_MANIFEST_FILE_NAME,
            "manifest_sha256": sha256_file(copied_manifest),
            "git_sha": manifest["git_sha"],
            "artifact_name": manifest["artifact_name"],
            "artifact_digest": artifact_digest.strip(),
            "version_label": manifest["version_label"],
            "created_at_utc": manifest["created_at_utc"],
        },
        "execution": {
            "tester": tester,
            "started_at_utc": now,
            "completed_at_utc": None,
            "environment": {
                "os_name": os_name,
                "os_version": os_version,
                "architecture": architecture,
                "display_resolution": display_resolution,
                "dpi_scale_percent": dpi_scale_percent,
                "input_methods": normalized_input_methods,
                "notes": environment_notes.strip(),
            },
        },
        "results": [
            {
                "case_id": case_id,
                "status": "pending",
                "notes": "",
                "evidence": [],
                "defect_ids": [],
                "executed_at_utc": None,
            }
            for case_id in ordered_case_ids
            if case_id in cases
        ],
        "defects": [],
        "decision": {
            "declared": "pending",
            "approved_by": "",
            "approved_at_utc": None,
            "notes": "",
        },
    }
    report_path = output_directory / REPORT_FILE_NAME
    write_json(report_path, report)
    summary_path = output_directory / SUMMARY_FILE_NAME
    summary_path.write_text(
        render_markdown_summary(checklist, report, evaluate_gate(checklist, report)),
        encoding="utf-8",
    )
    return report_path


def _validate_evidence(
    evidence_value: object,
    *,
    field: str,
    run_directory: Path | None,
) -> list[Mapping[str, Any]]:
    evidence_list = _require_list(evidence_value, field)
    validated: list[Mapping[str, Any]] = []
    for index, evidence_item in enumerate(evidence_list):
        evidence = _require_mapping(evidence_item, f"{field}[{index}]")
        evidence_type = _require_string(evidence.get("type"), f"{field}[{index}].type")
        if evidence_type not in EVIDENCE_TYPES:
            raise QaValidationError(
                f"unknown_evidence_type:{field}[{index}]:{evidence_type}"
            )
        reference = _require_string(
            evidence.get("reference"),
            f"{field}[{index}].reference",
        )
        _require_string(
            evidence.get("description"),
            f"{field}[{index}].description",
        )
        if run_directory is not None and not reference.startswith(("https://", "http://")):
            evidence_path = _relative_run_file(
                run_directory,
                reference,
                f"{field}[{index}].reference",
            )
            if not evidence_path.is_file():
                raise QaValidationError(f"evidence_file_not_found:{reference}")
        validated.append(evidence)
    return validated


def validate_report(
    checklist: Mapping[str, object],
    report: Mapping[str, object],
    *,
    report_path: Path | None = None,
) -> None:
    cases = validate_checklist(checklist)
    if report.get("schema_version") != 1:
        raise QaValidationError("unsupported_qa_report_schema_version")
    _require_identifier(report.get("run_id"), "report.run_id")

    checklist_ref = _require_mapping(report.get("checklist"), "report.checklist")
    if checklist_ref.get("id") != checklist.get("checklist_id"):
        raise QaValidationError("qa_report_checklist_id_mismatch")
    if checklist_ref.get("version") != checklist.get("checklist_version"):
        raise QaValidationError("qa_report_checklist_version_mismatch")
    if checklist_ref.get("definition_sha256") != checklist_definition_hash(checklist):
        raise QaValidationError("qa_report_checklist_hash_mismatch")

    run_directory = report_path.parent if report_path is not None else None
    build = _require_mapping(report.get("build"), "report.build")
    manifest_file = _require_string(build.get("manifest_file"), "report.build.manifest_file")
    manifest_hash = _require_string(
        build.get("manifest_sha256"),
        "report.build.manifest_sha256",
    )
    git_sha = _require_string(build.get("git_sha"), "report.build.git_sha")
    artifact_name = _require_string(
        build.get("artifact_name"),
        "report.build.artifact_name",
    )
    _require_string(
        build.get("artifact_digest", ""),
        "report.build.artifact_digest",
        allow_empty=True,
    )
    version_label = _require_string(
        build.get("version_label"),
        "report.build.version_label",
    )
    created_at = _parse_iso_datetime(
        build.get("created_at_utc"),
        "report.build.created_at_utc",
    )

    if run_directory is not None:
        manifest_path = _relative_run_file(
            run_directory,
            manifest_file,
            "report.build.manifest_file",
        )
        if not manifest_path.is_file():
            raise QaValidationError(f"qa_build_manifest_not_found:{manifest_file}")
        if sha256_file(manifest_path) != manifest_hash:
            raise QaValidationError("qa_build_manifest_hash_mismatch")
        manifest = load_json_object(manifest_path)
        validate_build_manifest(manifest)
        expected_pairs = {
            "git_sha": git_sha,
            "artifact_name": artifact_name,
            "version_label": version_label,
            "created_at_utc": created_at,
        }
        for field, expected in expected_pairs.items():
            if manifest.get(field) != expected:
                raise QaValidationError(f"qa_build_manifest_field_mismatch:{field}")

    execution = _require_mapping(report.get("execution"), "report.execution")
    _require_string(execution.get("tester"), "report.execution.tester")
    _parse_iso_datetime(
        execution.get("started_at_utc"),
        "report.execution.started_at_utc",
    )
    _parse_iso_datetime(
        execution.get("completed_at_utc"),
        "report.execution.completed_at_utc",
        allow_none=True,
    )
    environment = _require_mapping(
        execution.get("environment"),
        "report.execution.environment",
    )
    for field in ("os_name", "os_version", "architecture", "display_resolution"):
        _require_string(environment.get(field), f"report.execution.environment.{field}")
    _require_positive_int(
        environment.get("dpi_scale_percent"),
        "report.execution.environment.dpi_scale_percent",
    )
    _require_string_list(
        environment.get("input_methods"),
        "report.execution.environment.input_methods",
    )
    _require_string(
        environment.get("notes", ""),
        "report.execution.environment.notes",
        allow_empty=True,
    )

    result_values = _require_list(report.get("results"), "report.results")
    result_by_case: dict[str, Mapping[str, Any]] = {}
    referenced_defect_ids: set[str] = set()
    for index, result_value in enumerate(result_values):
        field_prefix = f"report.results[{index}]"
        result = _require_mapping(result_value, field_prefix)
        case_id = _require_identifier(result.get("case_id"), f"{field_prefix}.case_id")
        if case_id not in cases:
            raise QaValidationError(f"unknown_qa_case_id:{case_id}")
        if case_id in result_by_case:
            raise QaValidationError(f"duplicate_qa_case_result:{case_id}")
        status = _require_string(result.get("status"), f"{field_prefix}.status")
        if status not in RESULT_STATUSES:
            raise QaValidationError(f"unknown_qa_result_status:{case_id}:{status}")
        notes = _require_string(
            result.get("notes", ""),
            f"{field_prefix}.notes",
            allow_empty=True,
        )
        evidence = _validate_evidence(
            result.get("evidence"),
            field=f"{field_prefix}.evidence",
            run_directory=run_directory,
        )
        defect_ids = _require_string_list(
            result.get("defect_ids"),
            f"{field_prefix}.defect_ids",
            allow_empty=True,
        )
        referenced_defect_ids.update(defect_ids)
        _parse_iso_datetime(
            result.get("executed_at_utc"),
            f"{field_prefix}.executed_at_utc",
            allow_none=True,
        )

        case_definition = cases[case_id]
        if status == "pass":
            if not notes and not evidence:
                raise QaValidationError(f"passed_case_requires_notes_or_evidence:{case_id}")
            if bool(case_definition["evidence_required"]) and not evidence:
                raise QaValidationError(f"passed_case_requires_evidence:{case_id}")
        if status in {"fail", "blocked"}:
            if not notes:
                raise QaValidationError(f"failed_case_requires_notes:{case_id}")
            if not defect_ids:
                raise QaValidationError(f"failed_case_requires_defect:{case_id}")
        if status == "skipped":
            if not bool(case_definition["allow_skip"]):
                raise QaValidationError(f"qa_case_cannot_be_skipped:{case_id}")
            if not notes:
                raise QaValidationError(f"skipped_case_requires_notes:{case_id}")
        result_by_case[case_id] = result

    missing_cases = sorted(set(cases) - set(result_by_case))
    if missing_cases:
        raise QaValidationError("qa_report_missing_cases:" + ",".join(missing_cases))

    defect_values = _require_list(report.get("defects"), "report.defects")
    defects: dict[str, Mapping[str, Any]] = {}
    for index, defect_value in enumerate(defect_values):
        field_prefix = f"report.defects[{index}]"
        defect = _require_mapping(defect_value, field_prefix)
        defect_id = _require_identifier(defect.get("id"), f"{field_prefix}.id")
        if defect_id in defects:
            raise QaValidationError(f"duplicate_qa_defect_id:{defect_id}")
        _require_string(defect.get("title"), f"{field_prefix}.title")
        severity = _require_string(defect.get("severity"), f"{field_prefix}.severity")
        if severity not in DEFECT_SEVERITIES:
            raise QaValidationError(f"unknown_qa_defect_severity:{defect_id}:{severity}")
        defect_status = _require_string(defect.get("status"), f"{field_prefix}.status")
        if defect_status not in DEFECT_STATUSES:
            raise QaValidationError(
                f"unknown_qa_defect_status:{defect_id}:{defect_status}"
            )
        _require_string(
            defect.get("issue_url", ""),
            f"{field_prefix}.issue_url",
            allow_empty=True,
        )
        _require_string(defect.get("summary"), f"{field_prefix}.summary")
        related_case_ids = _require_string_list(
            defect.get("related_case_ids"),
            f"{field_prefix}.related_case_ids",
        )
        unknown_related_cases = sorted(set(related_case_ids) - set(cases))
        if unknown_related_cases:
            raise QaValidationError(
                f"qa_defect_has_unknown_cases:{defect_id}:"
                + ",".join(unknown_related_cases)
            )
        defects[defect_id] = defect

    unknown_defects = sorted(referenced_defect_ids - set(defects))
    if unknown_defects:
        raise QaValidationError(
            "qa_results_reference_unknown_defects:" + ",".join(unknown_defects)
        )

    decision = _require_mapping(report.get("decision"), "report.decision")
    declared = _require_string(decision.get("declared"), "report.decision.declared")
    if declared not in DECISION_STATUSES:
        raise QaValidationError(f"unknown_qa_decision:{declared}")
    approved_by = _require_string(
        decision.get("approved_by", ""),
        "report.decision.approved_by",
        allow_empty=True,
    )
    approved_at = _parse_iso_datetime(
        decision.get("approved_at_utc"),
        "report.decision.approved_at_utc",
        allow_none=True,
    )
    _require_string(
        decision.get("notes", ""),
        "report.decision.notes",
        allow_empty=True,
    )
    if declared in {"approved", "rejected"}:
        if not approved_by:
            raise QaValidationError("final_qa_decision_requires_approver")
        if approved_at is None:
            raise QaValidationError("final_qa_decision_requires_timestamp")


def evaluate_gate(
    checklist: Mapping[str, object],
    report: Mapping[str, object],
) -> GateEvaluation:
    cases = validate_checklist(checklist)
    results = {
        str(result["case_id"]): result
        for result in report.get("results", [])
        if isinstance(result, Mapping) and "case_id" in result
    }
    counts = {status: 0 for status in sorted(RESULT_STATUSES)}
    blocking_reasons: list[str] = []
    incomplete_reasons: list[str] = []
    warnings: list[str] = []

    for case_id, case_definition in cases.items():
        result = results.get(case_id)
        if result is None:
            incomplete_reasons.append(f"missing_case_result:{case_id}")
            continue
        status = str(result.get("status", "pending"))
        if status in counts:
            counts[status] += 1
        if bool(case_definition["release_blocking"]):
            if status == "pending":
                incomplete_reasons.append(f"release_blocking_case_pending:{case_id}")
            elif status != "pass":
                blocking_reasons.append(
                    f"release_blocking_case_not_passed:{case_id}:{status}"
                )
        elif status in {"fail", "blocked"}:
            warnings.append(f"non_blocking_case_not_passed:{case_id}:{status}")

    execution = report.get("execution", {})
    completed_at = execution.get("completed_at_utc") if isinstance(execution, Mapping) else None
    if not completed_at:
        incomplete_reasons.append("qa_execution_not_completed")

    blocking_severities = set(checklist["release_blocking_defect_severities"])
    for defect in report.get("defects", []):
        if not isinstance(defect, Mapping):
            continue
        severity = str(defect.get("severity", ""))
        status = str(defect.get("status", ""))
        if severity in blocking_severities and status not in {"fixed", "verified", "duplicate"}:
            blocking_reasons.append(
                f"open_release_blocking_defect:{defect.get('id')}:{severity}:{status}"
            )

    decision = report.get("decision", {})
    declared = decision.get("declared") if isinstance(decision, Mapping) else "pending"
    if declared == "rejected":
        blocking_reasons.append("qa_release_decision_rejected")
    elif declared != "approved":
        incomplete_reasons.append("qa_release_decision_not_approved")

    if blocking_reasons:
        status = GateStatus.FAIL
    elif incomplete_reasons:
        status = GateStatus.INCOMPLETE
    else:
        status = GateStatus.PASS

    return GateEvaluation(
        status=status,
        blocking_reasons=tuple(sorted(set(blocking_reasons))),
        incomplete_reasons=tuple(sorted(set(incomplete_reasons))),
        warnings=tuple(sorted(set(warnings))),
        result_counts=counts,
    )


def _escape_markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def render_markdown_summary(
    checklist: Mapping[str, object],
    report: Mapping[str, object],
    evaluation: GateEvaluation,
) -> str:
    build = report.get("build", {})
    execution = report.get("execution", {})
    environment = execution.get("environment", {}) if isinstance(execution, Mapping) else {}
    decision = report.get("decision", {})
    results = {
        str(result["case_id"]): result
        for result in report.get("results", [])
        if isinstance(result, Mapping) and "case_id" in result
    }

    lines = [
        f"# SteamデモQA結果: {report.get('run_id', '')}",
        "",
        f"**Release Gate: {evaluation.status.value.upper()}**",
        "",
        "## Build",
        "",
        f"- Artifact: `{build.get('artifact_name', '')}`",
        f"- Git SHA: `{build.get('git_sha', '')}`",
        f"- Version: `{build.get('version_label', '')}`",
        f"- Manifest SHA-256: `{build.get('manifest_sha256', '')}`",
        f"- Artifact Digest: `{build.get('artifact_digest', '') or '未記録'}`",
        "",
        "## 実行環境",
        "",
        f"- Tester: {_escape_markdown_cell(execution.get('tester', ''))}",
        f"- OS: {_escape_markdown_cell(environment.get('os_name', ''))} {_escape_markdown_cell(environment.get('os_version', ''))}",
        f"- Architecture: {_escape_markdown_cell(environment.get('architecture', ''))}",
        f"- Resolution / DPI: {_escape_markdown_cell(environment.get('display_resolution', ''))} / {_escape_markdown_cell(environment.get('dpi_scale_percent', ''))}%",
        f"- Input: {_escape_markdown_cell(', '.join(environment.get('input_methods', [])) if isinstance(environment.get('input_methods'), list) else '')}",
        f"- Started: `{execution.get('started_at_utc', '')}`",
        f"- Completed: `{execution.get('completed_at_utc') or '未完了'}`",
        "",
        "## 集計",
        "",
    ]
    for status in ("pass", "fail", "blocked", "pending", "skipped"):
        lines.append(f"- {status}: {evaluation.result_counts.get(status, 0)}")

    lines.extend(["", "## Gate理由", ""])
    if not evaluation.blocking_reasons and not evaluation.incomplete_reasons:
        lines.append("- 公開停止理由・未完了理由はありません。")
    else:
        for reason in evaluation.blocking_reasons:
            lines.append(f"- BLOCK: `{reason}`")
        for reason in evaluation.incomplete_reasons:
            lines.append(f"- INCOMPLETE: `{reason}`")
    for warning in evaluation.warnings:
        lines.append(f"- WARNING: `{warning}`")

    lines.extend(
        [
            "",
            "## Case結果",
            "",
            "| Case | 項目 | Blocking | Status | Notes | Defects |",
            "|---|---|---:|---|---|---|",
        ]
    )
    for section in checklist["sections"]:
        for case in section["cases"]:
            case_id = str(case["id"])
            result = results.get(case_id, {})
            lines.append(
                "| "
                + " | ".join(
                    [
                        _escape_markdown_cell(case_id),
                        _escape_markdown_cell(case["title"]),
                        "Yes" if case["release_blocking"] else "No",
                        _escape_markdown_cell(result.get("status", "missing")),
                        _escape_markdown_cell(result.get("notes", "")),
                        _escape_markdown_cell(
                            ", ".join(result.get("defect_ids", []))
                            if isinstance(result.get("defect_ids"), list)
                            else ""
                        ),
                    ]
                )
                + " |"
            )

    lines.extend(
        [
            "",
            "## Defects",
            "",
            "| ID | Severity | Status | Title | Issue |",
            "|---|---|---|---|---|",
        ]
    )
    defects = report.get("defects", [])
    if not defects:
        lines.append("| - | - | - | 登録なし | - |")
    else:
        for defect in defects:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _escape_markdown_cell(defect.get("id", "")),
                        _escape_markdown_cell(defect.get("severity", "")),
                        _escape_markdown_cell(defect.get("status", "")),
                        _escape_markdown_cell(defect.get("title", "")),
                        _escape_markdown_cell(defect.get("issue_url", "")),
                    ]
                )
                + " |"
            )

    lines.extend(
        [
            "",
            "## 公開判断",
            "",
            f"- Declared: `{decision.get('declared', 'pending')}`",
            f"- Approver: {_escape_markdown_cell(decision.get('approved_by', '') or '未設定')}",
            f"- Approved At: `{decision.get('approved_at_utc') or '未設定'}`",
            f"- Notes: {_escape_markdown_cell(decision.get('notes', '') or 'なし')}",
            "",
        ]
    )
    return "\n".join(lines)


def load_and_validate_run(
    report_path: Path,
    checklist_path: Path = DEFAULT_CHECKLIST_PATH,
) -> tuple[dict[str, Any], dict[str, Any], GateEvaluation]:
    checklist = load_checklist(checklist_path)
    report = load_json_object(report_path)
    validate_report(checklist, report, report_path=report_path)
    evaluation = evaluate_gate(checklist, report)
    return checklist, report, evaluation


def record_case_result(
    report_path: Path,
    *,
    case_id: str,
    status: str,
    notes: str,
    evidence: Sequence[str],
    defect_ids: Sequence[str],
    checklist_path: Path = DEFAULT_CHECKLIST_PATH,
) -> None:
    checklist = load_checklist(checklist_path)
    cases = validate_checklist(checklist)
    case_id = _require_identifier(case_id, "case_id")
    if case_id not in cases:
        raise QaValidationError(f"unknown_qa_case_id:{case_id}")
    if status not in RESULT_STATUSES:
        raise QaValidationError(f"unknown_qa_result_status:{status}")

    report = load_json_object(report_path)
    parsed_evidence: list[dict[str, str]] = []
    for index, raw in enumerate(evidence):
        parts = raw.split("|", 2)
        if len(parts) != 3:
            raise QaValidationError(
                f"evidence_argument_must_be_type_reference_description:{index}"
            )
        parsed_evidence.append(
            {
                "type": parts[0].strip(),
                "reference": parts[1].strip(),
                "description": parts[2].strip(),
            }
        )

    found = False
    for result in report.get("results", []):
        if isinstance(result, dict) and result.get("case_id") == case_id:
            result["status"] = status
            result["notes"] = notes.strip()
            result["evidence"] = parsed_evidence
            result["defect_ids"] = list(dict.fromkeys(defect_ids))
            result["executed_at_utc"] = None if status == "pending" else utc_now_iso()
            found = True
            break
    if not found:
        raise QaValidationError(f"qa_report_missing_case:{case_id}")
    write_json(report_path, report)


def add_or_update_defect(
    report_path: Path,
    *,
    defect_id: str,
    title: str,
    severity: str,
    status: str,
    issue_url: str,
    summary: str,
    related_case_ids: Sequence[str],
    replace: bool,
    checklist_path: Path = DEFAULT_CHECKLIST_PATH,
) -> None:
    checklist = load_checklist(checklist_path)
    cases = validate_checklist(checklist)
    defect_id = _require_identifier(defect_id, "defect_id")
    if severity not in DEFECT_SEVERITIES:
        raise QaValidationError(f"unknown_qa_defect_severity:{severity}")
    if status not in DEFECT_STATUSES:
        raise QaValidationError(f"unknown_qa_defect_status:{status}")
    unknown_cases = sorted(set(related_case_ids) - set(cases))
    if unknown_cases:
        raise QaValidationError(
            "qa_defect_has_unknown_cases:" + ",".join(unknown_cases)
        )

    report = load_json_object(report_path)
    defect_payload = {
        "id": defect_id,
        "title": title.strip(),
        "severity": severity,
        "status": status,
        "issue_url": issue_url.strip(),
        "summary": summary.strip(),
        "related_case_ids": list(dict.fromkeys(related_case_ids)),
    }
    defects = report.setdefault("defects", [])
    if not isinstance(defects, list):
        raise QaValidationError("report.defects_must_be_list")
    for index, defect in enumerate(defects):
        if isinstance(defect, Mapping) and defect.get("id") == defect_id:
            if not replace:
                raise QaValidationError(f"qa_defect_already_exists:{defect_id}")
            defects[index] = defect_payload
            break
    else:
        defects.append(defect_payload)
    write_json(report_path, report)


def finalize_run(
    report_path: Path,
    *,
    decision: str,
    approver: str,
    notes: str,
    checklist_path: Path = DEFAULT_CHECKLIST_PATH,
) -> GateEvaluation:
    if decision not in {"approved", "rejected"}:
        raise QaValidationError("final_decision_must_be_approved_or_rejected")
    report = load_json_object(report_path)
    execution = report.get("execution")
    if not isinstance(execution, dict):
        raise QaValidationError("report.execution_must_be_object")
    execution["completed_at_utc"] = utc_now_iso()
    report["decision"] = {
        "declared": decision,
        "approved_by": _require_string(approver, "approver"),
        "approved_at_utc": utc_now_iso(),
        "notes": notes.strip(),
    }

    checklist = load_checklist(checklist_path)
    validate_report(checklist, report, report_path=report_path)
    evaluation = evaluate_gate(checklist, report)
    if decision == "approved" and evaluation.status != GateStatus.PASS:
        raise QaValidationError(
            "qa_run_cannot_be_approved:" + evaluation.status.value + ":"
            + ",".join(evaluation.blocking_reasons + evaluation.incomplete_reasons)
        )
    write_json(report_path, report)
    (report_path.parent / SUMMARY_FILE_NAME).write_text(
        render_markdown_summary(checklist, report, evaluation),
        encoding="utf-8",
    )
    return evaluation


def validate_all_runs(
    reports_root: Path,
    *,
    checklist_path: Path = DEFAULT_CHECKLIST_PATH,
) -> tuple[list[dict[str, object]], int]:
    report_paths = sorted(reports_root.rglob(REPORT_FILE_NAME))
    if not report_paths:
        raise QaValidationError(f"qa_reports_not_found:{reports_root}")
    summaries: list[dict[str, object]] = []
    worst_exit_code = 0
    for report_path in report_paths:
        checklist, report, evaluation = load_and_validate_run(report_path, checklist_path)
        (report_path.parent / SUMMARY_FILE_NAME).write_text(
            render_markdown_summary(checklist, report, evaluation),
            encoding="utf-8",
        )
        summaries.append(
            {
                "report": str(report_path),
                "run_id": report["run_id"],
                "gate": evaluation.to_dict(),
            }
        )
        worst_exit_code = max(worst_exit_code, evaluation.exit_code)
    return summaries, worst_exit_code


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Steamデモの手動QA Runを作成・記録・検証する"
    )
    parser.add_argument(
        "--checklist",
        default=str(DEFAULT_CHECKLIST_PATH),
        help="QAチェックリストJSON",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Build ManifestからQA Runを作成する")
    init_parser.add_argument("--manifest", required=True)
    init_parser.add_argument("--output-dir", required=True)
    init_parser.add_argument("--tester", required=True)
    init_parser.add_argument("--os-name", required=True)
    init_parser.add_argument("--os-version", required=True)
    init_parser.add_argument("--architecture", default="x64")
    init_parser.add_argument("--resolution", required=True)
    init_parser.add_argument("--dpi-scale", type=int, default=100)
    init_parser.add_argument("--input", action="append", dest="inputs", required=True)
    init_parser.add_argument("--run-id")
    init_parser.add_argument("--artifact-digest", default="")
    init_parser.add_argument("--environment-notes", default="")

    record_parser = subparsers.add_parser("record-case", help="Case結果を記録する")
    record_parser.add_argument("--report", required=True)
    record_parser.add_argument("--case-id", required=True)
    record_parser.add_argument("--status", choices=sorted(RESULT_STATUSES), required=True)
    record_parser.add_argument("--notes", default="")
    record_parser.add_argument(
        "--evidence",
        action="append",
        default=[],
        help="type|relative-path-or-url|description",
    )
    record_parser.add_argument("--defect-id", action="append", default=[])

    defect_parser = subparsers.add_parser("add-defect", help="Defectを追加・更新する")
    defect_parser.add_argument("--report", required=True)
    defect_parser.add_argument("--defect-id", required=True)
    defect_parser.add_argument("--title", required=True)
    defect_parser.add_argument("--severity", choices=sorted(DEFECT_SEVERITIES), required=True)
    defect_parser.add_argument("--status", choices=sorted(DEFECT_STATUSES), required=True)
    defect_parser.add_argument("--issue-url", default="")
    defect_parser.add_argument("--summary", required=True)
    defect_parser.add_argument("--case-id", action="append", dest="case_ids", required=True)
    defect_parser.add_argument("--replace", action="store_true")

    validate_parser = subparsers.add_parser("validate", help="QA Runを検証する")
    validate_parser.add_argument("--report", required=True)
    validate_parser.add_argument("--summary-out")

    finalize_parser = subparsers.add_parser("finalize", help="QA Runを完了し公開判断を記録する")
    finalize_parser.add_argument("--report", required=True)
    finalize_parser.add_argument("--decision", choices=["approved", "rejected"], required=True)
    finalize_parser.add_argument("--approver", required=True)
    finalize_parser.add_argument("--notes", default="")

    all_parser = subparsers.add_parser("validate-all", help="配下の全QA Runを検証する")
    all_parser.add_argument("--reports-root", default="qa/runs")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    checklist_path = Path(args.checklist)
    try:
        if args.command == "init":
            report_path = create_run_report(
                checklist_path=checklist_path,
                manifest_path=Path(args.manifest),
                output_directory=Path(args.output_dir),
                tester=args.tester,
                os_name=args.os_name,
                os_version=args.os_version,
                architecture=args.architecture,
                display_resolution=args.resolution,
                dpi_scale_percent=args.dpi_scale,
                input_methods=args.inputs,
                run_id=args.run_id,
                artifact_digest=args.artifact_digest,
                environment_notes=args.environment_notes,
            )
            print(json.dumps({"status": "created", "report": str(report_path)}, ensure_ascii=False))
            return 0

        if args.command == "record-case":
            record_case_result(
                Path(args.report),
                case_id=args.case_id,
                status=args.status,
                notes=args.notes,
                evidence=args.evidence,
                defect_ids=args.defect_id,
                checklist_path=checklist_path,
            )
            print(json.dumps({"status": "updated", "case_id": args.case_id}, ensure_ascii=False))
            return 0

        if args.command == "add-defect":
            add_or_update_defect(
                Path(args.report),
                defect_id=args.defect_id,
                title=args.title,
                severity=args.severity,
                status=args.status,
                issue_url=args.issue_url,
                summary=args.summary,
                related_case_ids=args.case_ids,
                replace=args.replace,
                checklist_path=checklist_path,
            )
            print(json.dumps({"status": "updated", "defect_id": args.defect_id}, ensure_ascii=False))
            return 0

        if args.command == "validate":
            checklist, report, evaluation = load_and_validate_run(
                Path(args.report),
                checklist_path,
            )
            summary = render_markdown_summary(checklist, report, evaluation)
            summary_path = Path(args.summary_out) if args.summary_out else Path(args.report).parent / SUMMARY_FILE_NAME
            summary_path.write_text(summary, encoding="utf-8")
            print(json.dumps(evaluation.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
            return evaluation.exit_code

        if args.command == "finalize":
            evaluation = finalize_run(
                Path(args.report),
                decision=args.decision,
                approver=args.approver,
                notes=args.notes,
                checklist_path=checklist_path,
            )
            print(json.dumps(evaluation.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
            return evaluation.exit_code

        if args.command == "validate-all":
            summaries, exit_code = validate_all_runs(
                Path(args.reports_root),
                checklist_path=checklist_path,
            )
            print(json.dumps(summaries, ensure_ascii=False, indent=2, sort_keys=True))
            return exit_code

        parser.error(f"unsupported command: {args.command}")
    except (OSError, QaValidationError) as exc:
        print(f"QA検証エラー: {exc}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
