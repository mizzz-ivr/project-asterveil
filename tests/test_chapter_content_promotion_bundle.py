from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.content_promotion import (
    PromotionError,
    apply_bundle,
    load_catalog,
    verify_bundle,
    write_bundle,
)
from tools.content_promotion.catalog import PromotionEvaluation
from tools.chapter_content_pack import pack_digest


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class ChapterContentPromotionBundleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.catalog_path = self.root / "content/master_catalog_v1.json"
        self.encounter_path = self.root / "data/master/encounters.sample.json"
        self.location_path = self.root / "data/master/locations.sample.json"
        self.enemy_path = self.root / "data/master/enemies.sample.json"
        write_json(
            self.encounter_path,
            [
                {
                    "encounter_id": "encounter.ch01.slime",
                    "enemies": [
                        {"enemy_id": "enemy.ch01.slime", "count": 1}
                    ],
                }
            ],
        )
        write_json(
            self.location_path,
            [
                {
                    "location_id": "location.ch01.town",
                    "name": "始まりの町",
                    "location_type": "town",
                    "description": "第一章の拠点。",
                    "accessible_from": [],
                    "available_encounter_ids": ["encounter.ch01.slime"],
                    "default_encounter_id": "encounter.ch01.slime",
                }
            ],
        )
        write_json(
            self.enemy_path,
            [{"id": "enemy.ch01.slime"}],
        )
        write_json(
            self.catalog_path,
            {
                "schema_version": 1,
                "collections": {
                    "encounters": {
                        "path": "data/master/encounters.sample.json",
                        "id_fields": ["encounter_id", "id"],
                        "promotable": True,
                    },
                    "locations": {
                        "path": "data/master/locations.sample.json",
                        "id_fields": ["location_id", "id"],
                        "promotable": True,
                    },
                    "enemies": {
                        "path": "data/master/enemies.sample.json",
                        "id_fields": ["enemy_id", "id"],
                        "promotable": False,
                    },
                },
            },
        )
        self.pack = {
            "schema_version": 1,
            "chapter_id": "ch02",
            "title": "第二章",
            "estimated_play_minutes": 30,
            "content": {
                "quests": [],
                "events": [],
                "encounters": [
                    {
                        "encounter_id": "encounter.ch02.forest_slime",
                        "enemies": [
                            {"enemy_id": "enemy.ch01.slime", "count": 2}
                        ],
                    }
                ],
                "locations": [
                    {
                        "location_id": "location.ch02.forest",
                        "name": "霧の森",
                        "location_type": "field",
                        "description": "町の北に広がる森。",
                        "accessible_from": ["location.ch01.town"],
                        "available_encounter_ids": [
                            "encounter.ch02.forest_slime"
                        ],
                        "default_encounter_id": "encounter.ch02.forest_slime",
                    }
                ],
                "conversations": [],
            },
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _catalog(self):
        return load_catalog(self.catalog_path, self.root)

    def _evaluation(
        self,
        *,
        add_encounter: bool = True,
        add_location: bool = True,
        blocked: bool = False,
    ) -> PromotionEvaluation:
        catalog = self._catalog()
        classifications = {
            "quests": {"add": [], "unchanged": [], "conflict": []},
            "events": {"add": [], "unchanged": [], "conflict": []},
            "encounters": {
                "add": ["encounter.ch02.forest_slime"] if add_encounter else [],
                "unchanged": [],
                "conflict": [],
            },
            "locations": {
                "add": ["location.ch02.forest"] if add_location else [],
                "unchanged": [],
                "conflict": [],
            },
            "conversations": {"add": [], "unchanged": [], "conflict": []},
        }
        plan = {
            "schema_version": 1,
            "chapter_id": "ch02",
            "pack_sha256": pack_digest(self.pack),
            "catalog_sha256": catalog.digest,
            "status": "blocked" if blocked else "ready_for_review",
            "classifications": classifications,
            "target_files": {
                "encounters": "data/master/encounters.sample.json",
                "locations": "data/master/locations.sample.json",
            },
            "references": [],
            "unresolved_references": ([{"reason": "target_not_found"}] if blocked else []),
            "conflicts": [],
            "localization_candidates": [],
            "warnings": [],
            "apply_supported": False,
        }
        return PromotionEvaluation(plan=plan, blocked=blocked, warnings=())

    def _write_bundle(self, **evaluation_kwargs) -> Path:
        output = self.root / "tmp/bundle"
        write_bundle(
            self._evaluation(**evaluation_kwargs),
            self.pack,
            self._catalog(),
            output,
        )
        return output

    def test_bundle_contains_source_pack_manifest_candidates_and_diffs(self) -> None:
        output = self._write_bundle()
        manifest = json.loads(
            (output / "BUNDLE_MANIFEST.json").read_text(encoding="utf-8")
        )
        self.assertEqual("add_only", manifest["mode"])
        self.assertEqual(2, len(manifest["files"]))
        self.assertTrue((output / "source/pack.json").exists())
        encounter_candidate = json.loads(
            (output / "candidate/data/master/encounters.sample.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("encounter.ch01.slime", encounter_candidate[0]["encounter_id"])
        self.assertEqual(
            "encounter.ch02.forest_slime",
            encounter_candidate[1]["encounter_id"],
        )
        self.assertTrue((output / "diff/encounters.patch").read_text(encoding="utf-8"))
        self.assertTrue((output / "BUNDLE_SUMMARY.md").exists())

    def test_blocked_plan_cannot_create_bundle(self) -> None:
        with self.assertRaisesRegex(
            PromotionError,
            "promotion_bundle_requires_ready_for_review",
        ):
            self._write_bundle(blocked=True)

    def test_bundle_without_additions_is_rejected(self) -> None:
        with self.assertRaisesRegex(PromotionError, "promotion_bundle_no_additions"):
            self._write_bundle(add_encounter=False, add_location=False)

    def test_source_pack_tampering_is_rejected(self) -> None:
        output = self._write_bundle()
        source_pack = output / "source/pack.json"
        value = json.loads(source_pack.read_text(encoding="utf-8"))
        value["title"] = "改ざんされた第二章"
        write_json(source_pack, value)
        with self.assertRaisesRegex(PromotionError, "source_pack_tampered"):
            verify_bundle(output, self._catalog())

    def test_candidate_tampering_is_rejected(self) -> None:
        output = self._write_bundle()
        candidate = output / "candidate/data/master/encounters.sample.json"
        candidate.write_text("[]\n", encoding="utf-8")
        with self.assertRaisesRegex(PromotionError, "candidate_tampered"):
            verify_bundle(output, self._catalog())

    def test_candidate_addition_must_match_source_pack(self) -> None:
        output = self._write_bundle()
        candidate = output / "candidate/data/master/encounters.sample.json"
        rows = json.loads(candidate.read_text(encoding="utf-8"))
        rows[-1]["enemies"][0]["count"] = 99
        write_json(candidate, rows)
        manifest_path = output / "BUNDLE_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        encounter_entry = next(
            value for value in manifest["files"] if value["kind"] == "encounters"
        )
        encounter_entry["after_sha256"] = sha256_bytes(candidate.read_bytes())
        write_json(manifest_path, manifest)
        with self.assertRaisesRegex(PromotionError, "candidate_source_mismatch"):
            verify_bundle(output, self._catalog())

    def test_existing_entity_change_is_rejected_even_with_updated_hash(self) -> None:
        output = self._write_bundle()
        candidate = output / "candidate/data/master/locations.sample.json"
        rows = json.loads(candidate.read_text(encoding="utf-8"))
        rows[0]["name"] = "改ざんされた町"
        write_json(candidate, rows)
        manifest_path = output / "BUNDLE_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        location_entry = next(
            value for value in manifest["files"] if value["kind"] == "locations"
        )
        location_entry["after_sha256"] = sha256_bytes(candidate.read_bytes())
        write_json(manifest_path, manifest)
        with self.assertRaisesRegex(
            PromotionError,
            "existing_entities_changed",
        ):
            verify_bundle(output, self._catalog())

    def test_catalog_change_after_bundle_is_rejected(self) -> None:
        output = self._write_bundle()
        rows = json.loads(self.location_path.read_text(encoding="utf-8"))
        rows[0]["name"] = "更新後の町"
        write_json(self.location_path, rows)
        with self.assertRaisesRegex(PromotionError, "catalog_stale"):
            verify_bundle(output, self._catalog())

    def test_apply_dry_run_does_not_modify_master(self) -> None:
        output = self._write_bundle()
        before = self.encounter_path.read_bytes()
        catalog_sha = self._catalog().digest
        result = apply_bundle(
            output,
            self.catalog_path,
            self.root,
            confirm_catalog_sha=catalog_sha,
            write=False,
        )
        self.assertEqual("verified", result["status"])
        self.assertFalse(result["written"])
        self.assertEqual(before, self.encounter_path.read_bytes())

    def test_apply_requires_matching_catalog_confirmation(self) -> None:
        output = self._write_bundle()
        with self.assertRaisesRegex(PromotionError, "confirmation_mismatch"):
            apply_bundle(
                output,
                self.catalog_path,
                self.root,
                confirm_catalog_sha="invalid",
                write=True,
            )

    def test_apply_appends_only_new_entities(self) -> None:
        output = self._write_bundle()
        manifest = json.loads(
            (output / "BUNDLE_MANIFEST.json").read_text(encoding="utf-8")
        )
        result = apply_bundle(
            output,
            self.catalog_path,
            self.root,
            confirm_catalog_sha=manifest["source_catalog_sha256"],
            write=True,
        )
        self.assertEqual("applied", result["status"])
        encounter_rows = json.loads(self.encounter_path.read_text(encoding="utf-8"))
        location_rows = json.loads(self.location_path.read_text(encoding="utf-8"))
        self.assertEqual(
            ["encounter.ch01.slime", "encounter.ch02.forest_slime"],
            [value["encounter_id"] for value in encounter_rows],
        )
        self.assertEqual(
            ["location.ch01.town", "location.ch02.forest"],
            [value["location_id"] for value in location_rows],
        )
        self.assertEqual(
            manifest["expected_catalog_sha256"],
            self._catalog().digest,
        )

    def test_partial_write_failure_rolls_back_all_master_files(self) -> None:
        output = self._write_bundle()
        encounter_before = self.encounter_path.read_bytes()
        location_before = self.location_path.read_bytes()
        manifest = json.loads(
            (output / "BUNDLE_MANIFEST.json").read_text(encoding="utf-8")
        )
        real_replace = os.replace
        call_count = 0

        def fail_second_replace(source: object, target: object) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise OSError("simulated replace failure")
            real_replace(source, target)

        with patch(
            "tools.content_promotion.bundle.os.replace",
            side_effect=fail_second_replace,
        ):
            with self.assertRaisesRegex(PromotionError, "apply_failed"):
                apply_bundle(
                    output,
                    self.catalog_path,
                    self.root,
                    confirm_catalog_sha=manifest["source_catalog_sha256"],
                    write=True,
                )
        self.assertEqual(encounter_before, self.encounter_path.read_bytes())
        self.assertEqual(location_before, self.location_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
