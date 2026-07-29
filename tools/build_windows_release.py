from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


APPLICATION_NAME = "ProjectAsterveilSteamDemo"
ARTIFACT_NAME = "project-asterveil-steam-demo-windows-x64"
MANIFEST_FILE_NAME = "BUILD_MANIFEST.json"
RELEASE_README_FILE_NAME = "README_RELEASE.txt"
BUILD_SCRIPT_VERSION = 1


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_file_records(bundle_directory: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for path in sorted(bundle_directory.rglob("*")):
        if not path.is_file() or path.name == MANIFEST_FILE_NAME:
            continue
        records.append(
            {
                "path": path.relative_to(bundle_directory).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return records


def write_manifest(
    bundle_directory: Path,
    *,
    git_sha: str,
    version_label: str,
) -> Path:
    manifest_path = bundle_directory / MANIFEST_FILE_NAME
    manifest = {
        "schema_version": 1,
        "build_script_version": BUILD_SCRIPT_VERSION,
        "application_name": APPLICATION_NAME,
        "artifact_name": ARTIFACT_NAME,
        "git_sha": git_sha,
        "version_label": version_label,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "pyinstaller_version": importlib.metadata.version("pyinstaller"),
        "files": collect_file_records(bundle_directory),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def verify_bundle(bundle_directory: Path) -> dict[str, object]:
    required_paths = (
        Path(f"{APPLICATION_NAME}.exe"),
        Path(RELEASE_README_FILE_NAME),
        Path(MANIFEST_FILE_NAME),
        Path("_internal/data/master/demo_flows.sample.json"),
    )
    missing_paths = [
        path.as_posix()
        for path in required_paths
        if not (bundle_directory / path).is_file()
    ]
    if missing_paths:
        raise RuntimeError(
            "release_bundle_missing_required_files:" + ",".join(missing_paths)
        )

    manifest_path = bundle_directory / MANIFEST_FILE_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = manifest.get("files")
    if not isinstance(records, list) or not records:
        raise RuntimeError("release_manifest_files_missing")

    for record in records:
        relative_path = Path(str(record["path"]))
        target = bundle_directory / relative_path
        if not target.is_file():
            raise RuntimeError(f"release_manifest_file_missing:{relative_path.as_posix()}")
        actual_size = target.stat().st_size
        expected_size = int(record["size_bytes"])
        if actual_size != expected_size:
            raise RuntimeError(
                "release_manifest_size_mismatch:"
                f"{relative_path.as_posix()}:expected={expected_size}:actual={actual_size}"
            )
        actual_hash = sha256_file(target)
        expected_hash = str(record["sha256"])
        if actual_hash != expected_hash:
            raise RuntimeError(
                "release_manifest_hash_mismatch:"
                f"{relative_path.as_posix()}:expected={expected_hash}:actual={actual_hash}"
            )

    return manifest


def create_release_zip(bundle_directory: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(bundle_directory.rglob("*")):
            if not path.is_file():
                continue
            archive_name = Path(ARTIFACT_NAME) / path.relative_to(bundle_directory)
            archive.write(path, archive_name.as_posix())


def verify_release_zip(zip_path: Path) -> None:
    required_names = {
        f"{ARTIFACT_NAME}/{APPLICATION_NAME}.exe",
        f"{ARTIFACT_NAME}/{RELEASE_README_FILE_NAME}",
        f"{ARTIFACT_NAME}/{MANIFEST_FILE_NAME}",
        f"{ARTIFACT_NAME}/_internal/data/master/demo_flows.sample.json",
    }
    with zipfile.ZipFile(zip_path, "r") as archive:
        corrupted_file = archive.testzip()
        if corrupted_file is not None:
            raise RuntimeError(f"release_zip_corrupted:{corrupted_file}")
        names = set(archive.namelist())
    missing = sorted(required_names - names)
    if missing:
        raise RuntimeError("release_zip_missing_required_files:" + ",".join(missing))


def run_smoke_test(executable_path: Path) -> None:
    completed = subprocess.run(
        [str(executable_path), "--smoke-test"],
        cwd=executable_path.parent,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "release_smoke_test_failed:"
            f"exit={completed.returncode}:stdout={completed.stdout.strip()}:"
            f"stderr={completed.stderr.strip()}"
        )


def run_pyinstaller(project_root: Path, output_root: Path) -> Path:
    spec_path = project_root / "packaging" / "windows" / f"{APPLICATION_NAME}.spec"
    work_path = output_root / "pyinstaller-work"
    dist_path = output_root / "pyinstaller-dist"

    for path in (work_path, dist_path):
        if path.exists():
            shutil.rmtree(path)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--workpath",
        str(work_path),
        "--distpath",
        str(dist_path),
        str(spec_path),
    ]
    subprocess.run(command, cwd=project_root, check=True)

    bundle = dist_path / APPLICATION_NAME
    if not bundle.is_dir():
        raise RuntimeError(f"pyinstaller_bundle_not_found:{bundle}")
    return bundle


def build_release(
    *,
    project_root: Path,
    output_root: Path,
    git_sha: str,
    version_label: str,
    run_smoke: bool,
) -> dict[str, object]:
    if os.name != "nt":
        raise RuntimeError("windows_release_build_requires_windows")

    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    built_bundle = run_pyinstaller(project_root, output_root)

    release_bundle = output_root / ARTIFACT_NAME
    if release_bundle.exists():
        shutil.rmtree(release_bundle)
    shutil.copytree(built_bundle, release_bundle)
    shutil.copy2(
        project_root / "packaging" / "windows" / RELEASE_README_FILE_NAME,
        release_bundle / RELEASE_README_FILE_NAME,
    )

    executable = release_bundle / f"{APPLICATION_NAME}.exe"
    if run_smoke:
        run_smoke_test(executable)

    write_manifest(
        release_bundle,
        git_sha=git_sha,
        version_label=version_label,
    )
    manifest = verify_bundle(release_bundle)

    zip_path = output_root / f"{ARTIFACT_NAME}.zip"
    create_release_zip(release_bundle, zip_path)
    verify_release_zip(zip_path)

    return {
        "status": "ok",
        "bundle_directory": str(release_bundle),
        "zip_path": str(zip_path),
        "zip_sha256": sha256_file(zip_path),
        "file_count": len(manifest["files"]),
        "git_sha": git_sha,
        "version_label": version_label,
        "smoke_test_executed": run_smoke,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Project Asterveil Windows Steamデモ配布物を生成・検証する"
    )
    parser.add_argument(
        "--output-root",
        default="build/windows-release",
        help="Build作業ディレクトリと成果物の出力先",
    )
    parser.add_argument("--git-sha", default=os.environ.get("GITHUB_SHA", "local"))
    parser.add_argument("--version-label", default="development")
    parser.add_argument("--skip-smoke-test", action="store_true")
    args = parser.parse_args(argv)

    project_root = Path(__file__).resolve().parents[1]
    report = build_release(
        project_root=project_root,
        output_root=Path(args.output_root),
        git_sha=str(args.git_sha),
        version_label=str(args.version_label),
        run_smoke=not args.skip_smoke_test,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
