from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools.steam_demo_qa_v2 import (
    ChecklistV2Error,
    materialize_checklist_v2,
    write_materialized_checklist,
)


class SteamDemoQaV2Test(unittest.TestCase):
    def test_repository_checklist_materializes_v1_and_player_support_cases(self) -> None:
        payload = materialize_checklist_v2()
        case_ids = {
            case["id"]
            for section in payload["sections"]
            for case in section["cases"]
        }
        self.assertEqual(2, payload["checklist_version"])
        self.assertIn("BUILD-001", case_ids)
        self.assertIn("FLOW-007", case_ids)
        self.assertIn("INPUT-001", case_ids)
        self.assertIn("GUIDE-001", case_ids)
        self.assertIn("SUPPORT-004", case_ids)
        self.assertGreaterEqual(len(case_ids), 31)

    def test_materialized_checklist_can_be_written_as_regular_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "checklist_v2.json"
            written = write_materialized_checklist(output_path)
            payload = json.loads(written.read_text(encoding="utf-8"))
            self.assertEqual(2, payload["checklist_version"])
            self.assertEqual(
                "qa/steam_demo/checklist_v1.json",
                payload["composed_from"]["base"],
            )

    def test_duplicate_case_between_base_and_extension_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            base_path, extension_path = self._write_minimal_files(root)
            extension = json.loads(extension_path.read_text(encoding="utf-8"))
            extension["sections"][0]["cases"][0]["id"] = "BASE-001"
            extension_path.write_text(json.dumps(extension), encoding="utf-8")
            with self.assertRaisesRegex(
                ChecklistV2Error, "duplicate_case_id:BASE-001"
            ):
                materialize_checklist_v2(base_path, extension_path)

    def test_base_reference_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            base_path, extension_path = self._write_minimal_files(root)
            extension = json.loads(extension_path.read_text(encoding="utf-8"))
            extension["base_checklist"] = "../checklist_v1.json"
            extension_path.write_text(json.dumps(extension), encoding="utf-8")
            with self.assertRaisesRegex(
                ChecklistV2Error,
                "base_checklist_reference_must_be_relative",
            ):
                materialize_checklist_v2(base_path, extension_path)

    def test_release_blocking_extension_case_cannot_allow_skip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            base_path, extension_path = self._write_minimal_files(root)
            extension = json.loads(extension_path.read_text(encoding="utf-8"))
            extension["sections"][0]["cases"][0]["allow_skip"] = True
            extension_path.write_text(json.dumps(extension), encoding="utf-8")
            with self.assertRaisesRegex(
                ChecklistV2Error,
                "release_blocking_case_cannot_allow_skip",
            ):
                materialize_checklist_v2(base_path, extension_path)

    @staticmethod
    def _write_minimal_files(root: Path) -> tuple[Path, Path]:
        case = {
            "id": "BASE-001",
            "title": "Base",
            "purpose": "Base purpose",
            "preconditions": ["ready"],
            "steps": ["run"],
            "expected_results": ["pass"],
            "release_blocking": True,
            "allow_skip": False,
            "evidence_required": False,
            "tags": ["base"],
        }
        base = {
            "schema_version": 1,
            "checklist_id": "steam-demo-publication-gate",
            "checklist_version": 1,
            "title": "Base",
            "description": "Base",
            "minimum_complete_environments": 1,
            "release_blocking_defect_severities": ["high"],
            "sections": [{"id": "base", "title": "Base", "cases": [case]}],
        }
        extension_case = copy.deepcopy(case)
        extension_case["id"] = "EXT-001"
        extension = {
            "schema_version": 1,
            "composite_checklist_version": 2,
            "checklist_id": "steam-demo-publication-gate",
            "base_checklist": "checklist_v1.json",
            "title": "V2",
            "description": "V2",
            "sections": [
                {
                    "id": "player_support_test",
                    "title": "Support",
                    "cases": [
                        extension_case,
                        {**copy.deepcopy(extension_case), "id": "EXT-002"},
                        {**copy.deepcopy(extension_case), "id": "EXT-003"},
                    ],
                }
            ],
        }
        base_path = root / "checklist_v1.json"
        extension_path = root / "extension.json"
        base_path.write_text(json.dumps(base), encoding="utf-8")
        extension_path.write_text(json.dumps(extension), encoding="utf-8")
        return base_path, extension_path


if __name__ == "__main__":
    unittest.main()
