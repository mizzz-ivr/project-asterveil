from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from tools import steam_store_readiness as cli
from tools import steam_store_readiness_contract as contract
from tools import steam_store_readiness_gate as gate


ROOT = Path(__file__).resolve().parents[1]
DEFINITION_PATH = ROOT / "release/steam/store_readiness_v1.json"
STATE_PATH = ROOT / "release/steam/store_readiness_status.json"


class SteamStoreReadinessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.definition = contract.load_json(DEFINITION_PATH)
        self.state = contract.load_json(STATE_PATH)

    def item(self, item_id: str) -> dict:
        return next(
            item
            for item in contract.normalized_items(self.definition)
            if item["id"] == item_id
        )

    def state_item(self, state: dict, item_id: str) -> dict:
        return next(
            item for item in state["items"] if item["id"] == item_id
        )

    def test_repository_definition_and_state_are_valid(self) -> None:
        contract.validate_state(
            self.definition,
            self.state,
            STATE_PATH,
            require_files=False,
        )
        self.assertEqual(
            len(contract.normalized_items(self.definition)),
            37,
        )

    def test_official_asset_requirements_are_recorded(self) -> None:
        capsule = self.item("ASSET-001")["criteria"]
        screenshots = self.item("ASSET-004")["criteria"]
        library = self.item("ASSET-002")["criteria"]

        self.assertIn("Header 920x430", capsule)
        self.assertIn("Vertical 748x896", capsule)
        self.assertIn("Capsule 600x900", library)
        self.assertIn("Hero 3840x1240", library)
        self.assertIn("5枚以上", screenshots)
        self.assertIn("1920x1080以上", screenshots)
        self.assertIn("16:9", screenshots)
        self.assertIn("実ゲームプレイのみ", screenshots)

    def test_non_official_source_domain_is_rejected(self) -> None:
        definition = copy.deepcopy(self.definition)
        definition["sources"]["review"] = "https://example.com/review"
        with self.assertRaisesRegex(
            contract.ReadinessError,
            "official_source_invalid:review",
        ):
            contract.validate_definition(definition)

    def test_duplicate_item_id_is_rejected(self) -> None:
        definition = copy.deepcopy(self.definition)
        definition["items"].append(copy.deepcopy(definition["items"][0]))
        with self.assertRaisesRegex(
            contract.ReadinessError,
            "duplicate:item.id:ACCOUNT-001",
        ):
            contract.validate_definition(definition)

    def test_dependency_cycle_is_rejected(self) -> None:
        definition = copy.deepcopy(self.definition)
        fields = definition["item_fields"]
        id_index = fields.index("id")
        dependency_index = fields.index("dependencies")
        raw_by_id = {
            raw[id_index]: raw for raw in definition["items"]
        }
        raw_by_id["ACCOUNT-001"][dependency_index] = ["RIGHTS-001"]
        raw_by_id["RIGHTS-001"][dependency_index] = ["ACCOUNT-001"]
        with self.assertRaisesRegex(
            contract.ReadinessError,
            "item_dependency_cycle",
        ):
            contract.validate_definition(definition)

    def test_non_object_state_item_is_rejected(self) -> None:
        state = copy.deepcopy(self.state)
        state["items"][0] = "invalid"
        with self.assertRaisesRegex(
            contract.ReadinessError,
            "state_item_must_be_object",
        ):
            contract.validate_state(
                self.definition,
                state,
                STATE_PATH,
                require_files=False,
            )

    def test_false_condition_can_be_not_applicable(self) -> None:
        contract.validate_state(
            self.definition,
            self.state,
            STATE_PATH,
            require_files=False,
        )
        self.assertEqual(
            self.state_item(self.state, "STORE-003")["status"],
            "not_applicable",
        )

    def test_active_condition_cannot_remain_not_applicable(self) -> None:
        state = copy.deepcopy(self.state)
        state["conditions"]["early_access"] = True
        with self.assertRaisesRegex(
            contract.ReadinessError,
            "not_applicable_not_allowed:STORE-003",
        ):
            contract.validate_state(
                self.definition,
                state,
                STATE_PATH,
                require_files=False,
            )

    def test_done_item_requires_evidence(self) -> None:
        state = copy.deepcopy(self.state)
        self.state_item(state, "ACCOUNT-001")["status"] = "done"
        with self.assertRaisesRegex(
            contract.ReadinessError,
            "done_evidence_required:ACCOUNT-001",
        ):
            contract.validate_state(
                self.definition,
                state,
                STATE_PATH,
                require_files=False,
            )

    def test_evidence_path_cannot_escape_state_directory(self) -> None:
        state = copy.deepcopy(self.state)
        self.state_item(state, "ACCOUNT-001")["evidence"] = [
            {
                "type": "file",
                "value": "../secret.txt",
                "description": "invalid",
            }
        ]
        with self.assertRaisesRegex(
            contract.ReadinessError,
            "evidence_path_outside_state_directory",
        ):
            contract.validate_state(
                self.definition,
                state,
                STATE_PATH,
                require_files=False,
            )

    def test_business_day_shift_skips_weekend_and_holiday(self) -> None:
        shifted = gate.shift_business_days(
            date(2026, 8, 10),
            -2,
            {date(2026, 8, 7)},
        )
        self.assertEqual(shifted, date(2026, 8, 5))

    def test_release_date_resolves_coming_soon_anchor(self) -> None:
        state = copy.deepcopy(self.state)
        state["target_release_date"] = "2026-10-30"
        due_dates = gate.resolve_due_dates(self.definition, state)
        self.assertEqual(due_dates["COMING-001"], date(2026, 10, 16))
        self.assertEqual(due_dates["COMING-002"], date(2026, 10, 30))

    def test_initial_gate_is_incomplete_not_pass(self) -> None:
        result = gate.evaluate_gate(
            self.definition,
            self.state,
            "demo_release",
            STATE_PATH,
            today=date(2026, 7, 30),
        )
        self.assertEqual(result.status, "incomplete")
        self.assertIn(
            "gate_approval_pending:demo_release",
            result.incomplete,
        )

    def test_overdue_blocking_item_fails_gate(self) -> None:
        state = copy.deepcopy(self.state)
        state["target_release_date"] = "2026-07-01"
        result = gate.evaluate_gate(
            self.definition,
            state,
            "store_review",
            STATE_PATH,
            today=date(2026, 7, 30),
        )
        self.assertEqual(result.status, "fail")
        self.assertTrue(
            any(reason.startswith("item_overdue:") for reason in result.failures)
        )

    def test_stale_official_sources_are_reported(self) -> None:
        definition = copy.deepcopy(self.definition)
        definition["verified_on"] = "2025-01-01"
        result = gate.evaluate_gate(
            definition,
            self.state,
            "store_review",
            STATE_PATH,
            today=date(2026, 7, 30),
        )
        self.assertTrue(
            any(
                warning.startswith("official_sources_stale:")
                for warning in result.warnings
            )
        )

    def test_short_coming_soon_period_fails_demo_release(self) -> None:
        state = copy.deepcopy(self.state)
        state["target_release_date"] = "2026-10-20"
        state["milestones"]["coming_soon_published_at"] = (
            "2026-10-10T00:00:00+09:00"
        )
        result = gate.evaluate_gate(
            self.definition,
            state,
            "demo_release",
            STATE_PATH,
            today=date(2026, 9, 1),
        )
        self.assertIn(
            "coming_soon_period_short:days=10",
            result.failures,
        )

    def test_approval_cannot_override_incomplete_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state_path = Path(temporary) / "status.json"
            state_path.write_text(
                json.dumps(self.state, ensure_ascii=False),
                encoding="utf-8",
            )
            before = state_path.read_text(encoding="utf-8")
            args = SimpleNamespace(
                definition=str(DEFINITION_PATH),
                state=str(state_path),
                gate="store_review",
                approver="release-owner",
                notes="should fail",
            )
            with self.assertRaisesRegex(
                contract.ReadinessError,
                "gate_not_approvable:store_review",
            ):
                cli.command_approve_gate(args)
            self.assertEqual(
                state_path.read_text(encoding="utf-8"),
                before,
            )

    def test_summary_contains_gates_items_and_sources(self) -> None:
        summary = gate.render_summary(
            self.definition,
            self.state,
            STATE_PATH,
            today=date(2026, 7, 30),
        )
        self.assertIn("# Steam Store Readiness Summary", summary)
        self.assertIn("`store_review`", summary)
        self.assertIn("`ASSET-004`", summary)
        self.assertIn("partner.steamgames.com", summary)


if __name__ == "__main__":
    unittest.main()
