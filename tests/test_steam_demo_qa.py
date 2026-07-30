from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.steam_demo_qa import (
    BUILD_MANIFEST_FILE_NAME,
    GateStatus,
    QaValidationError,
    add_or_update_defect,
    checklist_definition_hash,
    create_run_report,
    evaluate_gate,
    finalize_run,
    load_and_validate_run,
    load_checklist,
    load_json_object,
    main,
    record_case_result,
    render_markdown_summary,
    validate_checklist,
    validate_report,
    write_json,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHECKLIST_PATH = PROJECT_ROOT / "qa" / "steam_demo" / "checklist_v1.json"


class SteamDemoQaGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_directory.name)
        self.manifest_path = self.root / "BUILD_MANIFEST.json"
        self.manifest = {
            "schema_version": 1,
            "build_script_version": 1,
            "application_name": "ProjectAsterveilSteamDemo",
            "artifact_name": "project-asterveil-steam-demo-windows-x64",
            "git_sha": "0123456789abcdef",
            "version_label": "qa-candidate",
            "created_at_utc": "2026-07-30T00:00:00+00:00",
            "platform": "Windows-11",
            "machine": "AMD64",
            "python_version": "3.11.9",
            "pyinstaller_version": "6.21.0",
            "files": [
                {
                    "path": "ProjectAsterveilSteamDemo.exe",
                    "size_bytes": 123,
                    "sha256": "0" * 64,
                }
            ],
        }
        write_json(self.manifest_path, self.manifest)
        self.run_directory = self.root / "qa-run"
        self.report_path = create_run_report(
            checklist_path=CHECKLIST_PATH,
            manifest_path=self.manifest_path,
            output_directory=self.run_directory,
            tester="qa-user",
            os_name="Windows",
            os_version="11 24H2",
            architecture="x64",
            display_resolution="1920x1080",
            dpi_scale_percent=100,
            input_methods=("keyboard_mouse",),
            run_id="qa-test-run",
            artifact_digest="sha256:test-artifact",
        )

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def _load(self) -> tuple[dict[str, object], dict[str, object]]:
        return load_checklist(CHECKLIST_PATH), load_json_object(self.report_path)

    def _write_report(self, report: dict[str, object]) -> None:
        write_json(self.report_path, report)

    def _mark_all_passed(self, report: dict[str, object]) -> None:
        checklist = load_checklist(CHECKLIST_PATH)
        case_definitions = validate_checklist(checklist)
        evidence_directory = self.run_directory / "evidence"
        evidence_directory.mkdir(exist_ok=True)
        for result in report["results"]:
            case_id = result["case_id"]
            result["status"] = "pass"
            result["notes"] = f"{case_id}の期待結果を確認した。"
            result["executed_at_utc"] = "2026-07-30T01:00:00+00:00"
            result["defect_ids"] = []
            if case_definitions[case_id]["evidence_required"]:
                evidence_path = evidence_directory / f"{case_id}.txt"
                evidence_path.write_text("evidence", encoding="utf-8")
                result["evidence"] = [
                    {
                        "type": "log",
                        "reference": f"evidence/{case_id}.txt",
                        "description": f"{case_id}の確認証跡",
                    }
                ]
            else:
                result["evidence"] = []

    def test_checklist_contains_required_core_flow_cases(self) -> None:
        checklist = load_checklist(CHECKLIST_PATH)
        cases = validate_checklist(checklist)

        self.assertEqual("steam-demo-publication-gate", checklist["checklist_id"])
        self.assertEqual(1, checklist["checklist_version"])
        self.assertTrue(
            {
                "BUILD-001",
                "TITLE-001",
                "FLOW-001",
                "FLOW-004",
                "FLOW-007",
                "SAVE-001",
                "NAV-001",
                "STABILITY-001",
            }.issubset(cases)
        )
        self.assertTrue(all(case["release_blocking"] for case in cases.values()))

    def test_create_run_copies_manifest_and_initializes_all_cases(self) -> None:
        checklist, report = self._load()
        cases = validate_checklist(checklist)

        self.assertTrue((self.run_directory / BUILD_MANIFEST_FILE_NAME).is_file())
        self.assertEqual(set(cases), {result["case_id"] for result in report["results"]})
        self.assertTrue(all(result["status"] == "pending" for result in report["results"]))
        self.assertEqual(
            checklist_definition_hash(checklist),
            report["checklist"]["definition_sha256"],
        )
        evaluation = evaluate_gate(checklist, report)
        self.assertEqual(GateStatus.INCOMPLETE, evaluation.status)
        self.assertIn("qa_execution_not_completed", evaluation.incomplete_reasons)

    def test_report_rejects_modified_build_manifest(self) -> None:
        copied_manifest = self.run_directory / BUILD_MANIFEST_FILE_NAME
        copied_manifest.write_text("{}\n", encoding="utf-8")
        checklist, report = self._load()

        with self.assertRaisesRegex(QaValidationError, "qa_build_manifest_hash_mismatch"):
            validate_report(checklist, report, report_path=self.report_path)

    def test_report_rejects_build_metadata_mismatch(self) -> None:
        checklist, report = self._load()
        report["build"]["git_sha"] = "different"
        self._write_report(report)

        with self.assertRaisesRegex(
            QaValidationError,
            "qa_build_manifest_field_mismatch:git_sha",
        ):
            load_and_validate_run(self.report_path, CHECKLIST_PATH)

    def test_report_rejects_unknown_duplicate_and_missing_cases(self) -> None:
        checklist, report = self._load()
        report["results"][0]["case_id"] = "UNKNOWN-001"
        with self.assertRaisesRegex(QaValidationError, "unknown_qa_case_id"):
            validate_report(checklist, report, report_path=self.report_path)

        _, report = self._load()
        report["results"][1]["case_id"] = report["results"][0]["case_id"]
        with self.assertRaisesRegex(QaValidationError, "duplicate_qa_case_result"):
            validate_report(checklist, report, report_path=self.report_path)

        _, report = self._load()
        report["results"].pop()
        with self.assertRaisesRegex(QaValidationError, "qa_report_missing_cases"):
            validate_report(checklist, report, report_path=self.report_path)

    def test_pass_requires_notes_and_required_evidence(self) -> None:
        checklist, report = self._load()
        first_result = report["results"][0]
        first_result["status"] = "pass"
        first_result["executed_at_utc"] = "2026-07-30T01:00:00+00:00"

        with self.assertRaisesRegex(
            QaValidationError,
            "passed_case_requires_notes_or_evidence",
        ):
            validate_report(checklist, report, report_path=self.report_path)

        first_result["notes"] = "確認済み"
        with self.assertRaisesRegex(QaValidationError, "passed_case_requires_evidence"):
            validate_report(checklist, report, report_path=self.report_path)

    def test_evidence_must_stay_inside_run_directory(self) -> None:
        checklist, report = self._load()
        first_result = report["results"][0]
        first_result.update(
            {
                "status": "pass",
                "notes": "確認済み",
                "executed_at_utc": "2026-07-30T01:00:00+00:00",
                "evidence": [
                    {
                        "type": "log",
                        "reference": "../outside.txt",
                        "description": "外部ファイル",
                    }
                ],
            }
        )
        with self.assertRaisesRegex(QaValidationError, "escapes_run_directory"):
            validate_report(checklist, report, report_path=self.report_path)

    def test_fail_and_blocked_require_registered_defect(self) -> None:
        checklist, report = self._load()
        first_result = report["results"][0]
        first_result.update(
            {
                "status": "fail",
                "notes": "起動時にクラッシュする",
                "executed_at_utc": "2026-07-30T01:00:00+00:00",
                "defect_ids": ["BUG-001"],
            }
        )
        with self.assertRaisesRegex(
            QaValidationError,
            "qa_results_reference_unknown_defects",
        ):
            validate_report(checklist, report, report_path=self.report_path)

    def test_record_case_and_add_defect_commands_update_report(self) -> None:
        add_or_update_defect(
            self.report_path,
            defect_id="BUG-001",
            title="タイトル起動時にクラッシュする",
            severity="critical",
            status="open",
            issue_url="https://github.com/mizzz-ivr/project-asterveil/issues/999",
            summary="配布exe起動直後に終了する。",
            related_case_ids=("BUILD-002",),
            replace=False,
            checklist_path=CHECKLIST_PATH,
        )
        record_case_result(
            self.report_path,
            case_id="BUILD-002",
            status="blocked",
            notes="起動できないため後続確認不可。",
            evidence=(),
            defect_ids=("BUG-001",),
            checklist_path=CHECKLIST_PATH,
        )
        checklist, report, evaluation = load_and_validate_run(
            self.report_path,
            CHECKLIST_PATH,
        )

        result = next(item for item in report["results"] if item["case_id"] == "BUILD-002")
        self.assertEqual("blocked", result["status"])
        self.assertEqual(["BUG-001"], result["defect_ids"])
        self.assertEqual(GateStatus.FAIL, evaluation.status)
        self.assertTrue(
            any(reason.startswith("open_release_blocking_defect:BUG-001") for reason in evaluation.blocking_reasons)
        )
        self.assertEqual("Steamデモ公開前手動QA", checklist["title"].split("Project Asterveil ")[-1])

    def test_all_passed_cases_can_be_approved(self) -> None:
        _, report = self._load()
        self._mark_all_passed(report)
        self._write_report(report)

        evaluation = finalize_run(
            self.report_path,
            decision="approved",
            approver="release-owner",
            notes="全Release Blocking Caseを確認した。",
            checklist_path=CHECKLIST_PATH,
        )
        _, finalized_report, loaded_evaluation = load_and_validate_run(
            self.report_path,
            CHECKLIST_PATH,
        )

        self.assertEqual(GateStatus.PASS, evaluation.status)
        self.assertEqual(GateStatus.PASS, loaded_evaluation.status)
        self.assertEqual("approved", finalized_report["decision"]["declared"])
        self.assertIsNotNone(finalized_report["execution"]["completed_at_utc"])
        self.assertTrue((self.run_directory / "SUMMARY.md").is_file())

    def test_approval_is_rejected_when_blocking_case_is_pending(self) -> None:
        with self.assertRaisesRegex(QaValidationError, "qa_run_cannot_be_approved"):
            finalize_run(
                self.report_path,
                decision="approved",
                approver="release-owner",
                notes="誤承認",
                checklist_path=CHECKLIST_PATH,
            )
        report = load_json_object(self.report_path)
        self.assertEqual("pending", report["decision"]["declared"])
        self.assertIsNone(report["execution"]["completed_at_utc"])

    def test_open_high_defect_blocks_even_when_all_cases_pass(self) -> None:
        _, report = self._load()
        self._mark_all_passed(report)
        report["defects"] = [
            {
                "id": "BUG-002",
                "title": "再開時に進行状態がずれる",
                "severity": "high",
                "status": "deferred",
                "issue_url": "https://github.com/mizzz-ivr/project-asterveil/issues/998",
                "summary": "再現済みだが未修正。",
                "related_case_ids": ["SAVE-001"],
            }
        ]
        self._write_report(report)

        with self.assertRaisesRegex(QaValidationError, "qa_run_cannot_be_approved:fail"):
            finalize_run(
                self.report_path,
                decision="approved",
                approver="release-owner",
                notes="承認不可",
                checklist_path=CHECKLIST_PATH,
            )

    def test_verified_high_defect_does_not_block_release(self) -> None:
        _, report = self._load()
        self._mark_all_passed(report)
        report["defects"] = [
            {
                "id": "BUG-003",
                "title": "修正済みの起動不具合",
                "severity": "high",
                "status": "verified",
                "issue_url": "https://github.com/mizzz-ivr/project-asterveil/issues/997",
                "summary": "修正Buildで再確認済み。",
                "related_case_ids": ["BUILD-002"],
            }
        ]
        self._write_report(report)

        evaluation = finalize_run(
            self.report_path,
            decision="approved",
            approver="release-owner",
            notes="修正確認済み。",
            checklist_path=CHECKLIST_PATH,
        )
        self.assertEqual(GateStatus.PASS, evaluation.status)

    def test_markdown_summary_contains_gate_build_cases_and_defects(self) -> None:
        checklist, report = self._load()
        evaluation = evaluate_gate(checklist, report)
        summary = render_markdown_summary(checklist, report, evaluation)

        self.assertIn("Release Gate: INCOMPLETE", summary)
        self.assertIn("0123456789abcdef", summary)
        self.assertIn("FLOW-004", summary)
        self.assertIn("登録なし", summary)

    def test_cli_init_and_validate_return_expected_codes(self) -> None:
        cli_run_directory = self.root / "cli-run"
        init_code = main(
            [
                "--checklist",
                str(CHECKLIST_PATH),
                "init",
                "--manifest",
                str(self.manifest_path),
                "--output-dir",
                str(cli_run_directory),
                "--tester",
                "cli-user",
                "--os-name",
                "Windows",
                "--os-version",
                "11",
                "--resolution",
                "1920x1080",
                "--input",
                "keyboard_mouse",
                "--run-id",
                "qa-cli-run",
            ]
        )
        validate_code = main(
            [
                "--checklist",
                str(CHECKLIST_PATH),
                "validate",
                "--report",
                str(cli_run_directory / "report.json"),
            ]
        )

        self.assertEqual(0, init_code)
        self.assertEqual(2, validate_code)
        self.assertTrue((cli_run_directory / "SUMMARY.md").is_file())


if __name__ == "__main__":
    unittest.main()
