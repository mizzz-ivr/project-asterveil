from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from game.app.client import runtime_paths
from game.app.client.run_tk_steam_demo import main as client_main
from game.app.client.run_tk_steam_demo import run_smoke_test
from tools.build_windows_release import (
    APPLICATION_NAME,
    MANIFEST_FILE_NAME,
    RELEASE_README_FILE_NAME,
    create_release_zip,
    verify_bundle,
    verify_release_zip,
    write_manifest,
)


class RuntimePathTests(unittest.TestCase):
    def test_source_runtime_resolves_project_master_and_tmp_save(self) -> None:
        self.assertTrue(runtime_paths.default_master_root().is_dir())
        self.assertEqual(
            runtime_paths.default_save_path(),
            runtime_paths.source_project_root()
            / "tmp"
            / runtime_paths.SAVE_FILE_NAME,
        )

    def test_frozen_runtime_resolves_meipass_master_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            frozen_root = Path(tmp_dir)
            with (
                patch.object(sys, "frozen", True, create=True),
                patch.object(sys, "_MEIPASS", str(frozen_root), create=True),
            ):
                self.assertEqual(
                    runtime_paths.default_master_root(),
                    frozen_root.resolve() / "data" / "master",
                )

    def test_frozen_runtime_uses_local_app_data_for_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with (
                patch.object(sys, "frozen", True, create=True),
                patch.dict(os.environ, {"LOCALAPPDATA": tmp_dir}),
            ):
                expected = (
                    Path(tmp_dir).resolve()
                    / runtime_paths.APPLICATION_DIRECTORY_NAME
                    / runtime_paths.SAVE_FILE_NAME
                )
                self.assertEqual(runtime_paths.default_save_path(), expected)


class SteamDemoDistributionSmokeTests(unittest.TestCase):
    def test_source_smoke_test_reaches_top_scene_without_tkinter(self) -> None:
        report = run_smoke_test(master_root=Path("data/master"))
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["initial_route"], "steam_demo.top_menu")
        self.assertGreater(int(report["title_action_count"]), 0)

    def test_cli_smoke_test_returns_success(self) -> None:
        exit_code = client_main(
            [
                "--smoke-test",
                "--master-root",
                "data/master",
            ]
        )
        self.assertEqual(exit_code, 0)


class WindowsReleaseHelperTests(unittest.TestCase):
    def _create_fake_bundle(self, root: Path) -> Path:
        bundle = root / "bundle"
        master_root = bundle / "_internal" / "data" / "master"
        master_root.mkdir(parents=True)
        (bundle / f"{APPLICATION_NAME}.exe").write_bytes(b"fake-executable")
        (bundle / RELEASE_README_FILE_NAME).write_text(
            "release readme",
            encoding="utf-8",
        )
        (master_root / "demo_flows.sample.json").write_text(
            json.dumps({"schema_version": 1}),
            encoding="utf-8",
        )
        return bundle

    def test_manifest_and_zip_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            bundle = self._create_fake_bundle(root)
            with patch(
                "tools.build_windows_release.importlib.metadata.version",
                return_value="test-version",
            ):
                write_manifest(
                    bundle,
                    git_sha="test-sha",
                    version_label="test-build",
                )

            manifest = verify_bundle(bundle)
            self.assertEqual(manifest["git_sha"], "test-sha")
            self.assertGreater(len(manifest["files"]), 0)

            zip_path = root / "release.zip"
            create_release_zip(bundle, zip_path)
            verify_release_zip(zip_path)
            self.assertTrue(zip_path.is_file())

    def test_manifest_detects_modified_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            bundle = self._create_fake_bundle(root)
            with patch(
                "tools.build_windows_release.importlib.metadata.version",
                return_value="test-version",
            ):
                write_manifest(
                    bundle,
                    git_sha="test-sha",
                    version_label="test-build",
                )

            (bundle / RELEASE_README_FILE_NAME).write_text(
                "tampered",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "release_manifest"):
                verify_bundle(bundle)

    def test_manifest_file_is_not_self_hashed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            bundle = self._create_fake_bundle(root)
            with patch(
                "tools.build_windows_release.importlib.metadata.version",
                return_value="test-version",
            ):
                manifest_path = write_manifest(
                    bundle,
                    git_sha="test-sha",
                    version_label="test-build",
                )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            paths = {record["path"] for record in manifest["files"]}
            self.assertNotIn(MANIFEST_FILE_NAME, paths)


if __name__ == "__main__":
    unittest.main()
