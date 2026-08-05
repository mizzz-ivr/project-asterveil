from __future__ import annotations

import difflib
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools.chapter_content_pack import KINDS

from .catalog import (
    MasterCatalog,
    PromotionError,
    PromotionEvaluation,
    canonical,
    catalog_digest,
    entity_id,
    load_catalog,
    load_json,
    pack_index,
    require_object,
    require_string,
)

BUNDLE_TYPE = "chapter_content_promotion_add_only"


@dataclass(frozen=True)
class VerifiedBundleFile:
    kind: str
    target_path: Path
    candidate_bytes: bytes
    original_bytes: bytes
    added_ids: tuple[str, ...]


@dataclass(frozen=True)
class BundleVerification:
    manifest: Mapping[str, Any]
    files: tuple[VerifiedBundleFile, ...]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")


def _safe_relative_path(value: object, field: str) -> Path:
    relative = Path(require_string(value, field))
    if relative.is_absolute() or ".." in relative.parts:
        raise PromotionError(f"{field}_must_be_safe_relative_path")
    return relative


def _write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


def _entity_ids(
    rows: Sequence[object],
    fields: Sequence[str],
    source: str,
) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for position, value in enumerate(rows):
        row = require_object(value, f"{source}[{position}]")
        item_id = entity_id(row, fields, f"{source}:{position}")
        if item_id in seen:
            raise PromotionError(f"promotion_bundle_duplicate_id:{source}:{item_id}")
        seen.add(item_id)
        ids.append(item_id)
    return ids


def _render_bundle_summary(manifest: Mapping[str, Any]) -> str:
    lines = [
        f"# Chapter Content Promotion Bundle: {manifest['chapter_id']}",
        "",
        f"- Bundle Type: `{manifest['bundle_type']}`",
        f"- Pack SHA-256: `{manifest['pack_sha256']}`",
        f"- Source Catalog SHA-256: `{manifest['source_catalog_sha256']}`",
        f"- Expected Catalog SHA-256: `{manifest['expected_catalog_sha256']}`",
        f"- Target File Count: {len(manifest['files'])}",
        "- 適用方式: add-only / 明示確認必須",
        "",
        "## 対象ファイル",
    ]
    for file_entry in manifest["files"]:
        lines.extend(
            [
                f"### {file_entry['kind']}",
                f"- Target: `{file_entry['target_path']}`",
                f"- Added IDs: {len(file_entry['added_ids'])}",
                f"- Before SHA-256: `{file_entry['before_sha256']}`",
                f"- After SHA-256: `{file_entry['after_sha256']}`",
                f"- Candidate: `{file_entry['candidate_path']}`",
                f"- Diff: `{file_entry['diff_path']}`",
            ]
        )
    lines.extend(
        [
            "",
            "## 安全条件",
            "- 既存Entityの更新・削除・並び替えは禁止",
            "- Source Catalog SHAと現在値が一致すること",
            "- 各MasterのBefore SHAと現在値が一致すること",
            "- Candidate／DiffのSHAがManifestと一致すること",
            "- 書込みには`--write`と`--confirm-catalog-sha`が必要",
        ]
    )
    return "\n".join(lines) + "\n"


def write_bundle(
    evaluation: PromotionEvaluation,
    pack: Mapping[str, Any],
    catalog: MasterCatalog,
    output: Path,
) -> Mapping[str, Any]:
    if evaluation.blocked or evaluation.plan.get("status") != "ready_for_review":
        raise PromotionError("promotion_bundle_requires_ready_for_review")
    if output.exists() and any(output.iterdir()):
        raise PromotionError("promotion_bundle_output_must_be_empty")

    index = pack_index(pack)
    updated_entities = {
        kind: dict(values)
        for kind, values in catalog.entities.items()
    }
    files: list[dict[str, Any]] = []

    for kind in KINDS:
        classification = evaluation.plan["classifications"][kind]
        added_ids = sorted(str(value) for value in classification.get("add", []))
        if not added_ids:
            continue
        if classification.get("conflict"):
            raise PromotionError(f"promotion_bundle_conflict_present:{kind}")

        definition = catalog.definition.get(kind)
        if definition is None or definition.get("promotable") is not True:
            raise PromotionError(f"promotion_bundle_collection_not_promotable:{kind}")
        target_relative = _safe_relative_path(
            definition.get("path"),
            f"catalog.collections.{kind}.path",
        )
        target_path = catalog.root / target_relative
        original_bytes = target_path.read_bytes()
        original_rows = load_json(target_path)
        if not isinstance(original_rows, list):
            raise PromotionError(f"promotion_bundle_target_must_be_list:{kind}")

        additions: list[Mapping[str, Any]] = []
        for item_id in added_ids:
            entity = index[kind].get(item_id)
            if entity is None:
                raise PromotionError(f"promotion_bundle_entity_missing:{kind}:{item_id}")
            if item_id in catalog.entities.get(kind, {}):
                raise PromotionError(f"promotion_bundle_add_id_already_exists:{kind}:{item_id}")
            additions.append(dict(entity))
            updated_entities.setdefault(kind, {})[item_id] = dict(entity)

        candidate_rows = list(original_rows) + additions
        candidate_bytes = _json_bytes(candidate_rows)
        candidate_relative = Path("candidate") / target_relative
        diff_relative = Path("diff") / f"{kind}.patch"
        diff_text = "".join(
            difflib.unified_diff(
                original_bytes.decode("utf-8").splitlines(keepends=True),
                candidate_bytes.decode("utf-8").splitlines(keepends=True),
                fromfile=target_relative.as_posix(),
                tofile=f"{target_relative.as_posix()}.candidate",
            )
        )
        diff_bytes = diff_text.encode("utf-8")

        _write_bytes(output / candidate_relative, candidate_bytes)
        _write_bytes(output / diff_relative, diff_bytes)
        files.append(
            {
                "kind": kind,
                "target_path": target_relative.as_posix(),
                "candidate_path": candidate_relative.as_posix(),
                "diff_path": diff_relative.as_posix(),
                "before_sha256": _sha256_bytes(original_bytes),
                "after_sha256": _sha256_bytes(candidate_bytes),
                "diff_sha256": _sha256_bytes(diff_bytes),
                "existing_count": len(original_rows),
                "candidate_count": len(candidate_rows),
                "added_ids": added_ids,
            }
        )

    if not files:
        raise PromotionError("promotion_bundle_no_additions")

    manifest = {
        "schema_version": 1,
        "bundle_type": BUNDLE_TYPE,
        "chapter_id": require_string(pack.get("chapter_id"), "chapter_id"),
        "pack_sha256": evaluation.plan["pack_sha256"],
        "source_catalog_sha256": catalog.digest,
        "expected_catalog_sha256": catalog_digest(
            catalog.definition,
            updated_entities,
        ),
        "mode": "add_only",
        "files": files,
        "write_requires": {
            "explicit_write": True,
            "confirm_catalog_sha": catalog.digest,
        },
    }
    _write_bytes(output / "BUNDLE_MANIFEST.json", _json_bytes(manifest))
    _write_bytes(
        output / "BUNDLE_SUMMARY.md",
        _render_bundle_summary(manifest).encode("utf-8"),
    )
    return manifest


def verify_bundle(bundle_root: Path, catalog: MasterCatalog) -> BundleVerification:
    manifest = require_object(
        load_json(bundle_root / "BUNDLE_MANIFEST.json"),
        "bundle_manifest",
    )
    if manifest.get("schema_version") != 1:
        raise PromotionError("unsupported_promotion_bundle_schema_version")
    if manifest.get("bundle_type") != BUNDLE_TYPE or manifest.get("mode") != "add_only":
        raise PromotionError("unsupported_promotion_bundle_type")
    source_catalog_sha = require_string(
        manifest.get("source_catalog_sha256"),
        "bundle_manifest.source_catalog_sha256",
    )
    if source_catalog_sha != catalog.digest:
        raise PromotionError(
            f"promotion_bundle_catalog_stale:expected={source_catalog_sha}:actual={catalog.digest}"
        )

    file_values = manifest.get("files")
    if not isinstance(file_values, list) or not file_values:
        raise PromotionError("promotion_bundle_files_must_be_non_empty_list")

    verified_files: list[VerifiedBundleFile] = []
    updated_entities = {
        kind: dict(values)
        for kind, values in catalog.entities.items()
    }
    seen_kinds: set[str] = set()
    seen_targets: set[str] = set()

    for position, value in enumerate(file_values):
        entry = require_object(value, f"bundle_manifest.files[{position}]")
        kind = require_string(entry.get("kind"), f"bundle_manifest.files[{position}].kind")
        if kind not in KINDS or kind in seen_kinds:
            raise PromotionError(f"promotion_bundle_invalid_or_duplicate_kind:{kind}")
        seen_kinds.add(kind)

        definition = catalog.definition.get(kind)
        if definition is None or definition.get("promotable") is not True:
            raise PromotionError(f"promotion_bundle_collection_not_promotable:{kind}")
        target_relative = _safe_relative_path(
            entry.get("target_path"),
            f"bundle_manifest.files[{position}].target_path",
        )
        expected_target = _safe_relative_path(
            definition.get("path"),
            f"catalog.collections.{kind}.path",
        )
        if target_relative != expected_target:
            raise PromotionError(f"promotion_bundle_target_mismatch:{kind}")
        if target_relative.as_posix() in seen_targets:
            raise PromotionError(f"promotion_bundle_duplicate_target:{target_relative.as_posix()}")
        seen_targets.add(target_relative.as_posix())

        target_path = catalog.root / target_relative
        original_bytes = target_path.read_bytes()
        expected_before = require_string(
            entry.get("before_sha256"),
            f"bundle_manifest.files[{position}].before_sha256",
        )
        if _sha256_bytes(original_bytes) != expected_before:
            raise PromotionError(f"promotion_bundle_master_changed:{kind}")

        candidate_relative = _safe_relative_path(
            entry.get("candidate_path"),
            f"bundle_manifest.files[{position}].candidate_path",
        )
        candidate_bytes = (bundle_root / candidate_relative).read_bytes()
        expected_after = require_string(
            entry.get("after_sha256"),
            f"bundle_manifest.files[{position}].after_sha256",
        )
        if _sha256_bytes(candidate_bytes) != expected_after:
            raise PromotionError(f"promotion_bundle_candidate_tampered:{kind}")

        diff_relative = _safe_relative_path(
            entry.get("diff_path"),
            f"bundle_manifest.files[{position}].diff_path",
        )
        diff_bytes = (bundle_root / diff_relative).read_bytes()
        expected_diff = require_string(
            entry.get("diff_sha256"),
            f"bundle_manifest.files[{position}].diff_sha256",
        )
        if _sha256_bytes(diff_bytes) != expected_diff:
            raise PromotionError(f"promotion_bundle_diff_tampered:{kind}")

        original_rows = json.loads(original_bytes.decode("utf-8"))
        candidate_rows = json.loads(candidate_bytes.decode("utf-8"))
        if not isinstance(original_rows, list) or not isinstance(candidate_rows, list):
            raise PromotionError(f"promotion_bundle_candidate_must_be_list:{kind}")
        existing_count = entry.get("existing_count")
        candidate_count = entry.get("candidate_count")
        if existing_count != len(original_rows) or candidate_count != len(candidate_rows):
            raise PromotionError(f"promotion_bundle_count_mismatch:{kind}")

        added_values = entry.get("added_ids")
        if not isinstance(added_values, list) or not all(
            isinstance(item_id, str) and item_id for item_id in added_values
        ):
            raise PromotionError(f"promotion_bundle_added_ids_invalid:{kind}")
        added_ids = tuple(added_values)
        if len(candidate_rows) != len(original_rows) + len(added_ids):
            raise PromotionError(f"promotion_bundle_add_only_count_mismatch:{kind}")
        if canonical(candidate_rows[: len(original_rows)]) != canonical(original_rows):
            raise PromotionError(f"promotion_bundle_existing_entities_changed:{kind}")

        fields = definition.get("id_fields")
        if not isinstance(fields, list) or not fields:
            raise PromotionError(f"promotion_bundle_id_fields_invalid:{kind}")
        original_ids = _entity_ids(original_rows, tuple(fields), f"bundle:{kind}:existing")
        candidate_ids = _entity_ids(candidate_rows, tuple(fields), f"bundle:{kind}:candidate")
        trailing_ids = tuple(candidate_ids[len(original_ids) :])
        if trailing_ids != added_ids:
            raise PromotionError(f"promotion_bundle_added_ids_mismatch:{kind}")
        if set(added_ids) & set(original_ids):
            raise PromotionError(f"promotion_bundle_added_id_already_exists:{kind}")

        for item_id, row in zip(added_ids, candidate_rows[len(original_rows) :]):
            updated_entities.setdefault(kind, {})[item_id] = dict(
                require_object(row, f"bundle:{kind}:{item_id}")
            )
        verified_files.append(
            VerifiedBundleFile(
                kind=kind,
                target_path=target_path,
                candidate_bytes=candidate_bytes,
                original_bytes=original_bytes,
                added_ids=added_ids,
            )
        )

    expected_catalog_sha = require_string(
        manifest.get("expected_catalog_sha256"),
        "bundle_manifest.expected_catalog_sha256",
    )
    actual_expected_sha = catalog_digest(catalog.definition, updated_entities)
    if actual_expected_sha != expected_catalog_sha:
        raise PromotionError("promotion_bundle_expected_catalog_digest_mismatch")

    return BundleVerification(manifest=manifest, files=tuple(verified_files))


def _stage_file(target: Path, value: bytes) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
        delete=False,
    ) as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
        return Path(handle.name)


def apply_bundle(
    bundle_root: Path,
    catalog_path: Path,
    project_root: Path,
    *,
    confirm_catalog_sha: str,
    write: bool = False,
) -> Mapping[str, Any]:
    catalog = load_catalog(catalog_path, project_root)
    verification = verify_bundle(bundle_root, catalog)
    required_confirmation = require_string(
        verification.manifest.get("source_catalog_sha256"),
        "bundle_manifest.source_catalog_sha256",
    )
    if confirm_catalog_sha != required_confirmation:
        raise PromotionError("promotion_bundle_catalog_confirmation_mismatch")

    result = {
        "status": "verified" if not write else "applied",
        "written": bool(write),
        "source_catalog_sha256": required_confirmation,
        "expected_catalog_sha256": verification.manifest["expected_catalog_sha256"],
        "file_count": len(verification.files),
        "added_entity_count": sum(len(value.added_ids) for value in verification.files),
    }
    if not write:
        return result

    staged: list[tuple[VerifiedBundleFile, Path]] = []
    try:
        for value in verification.files:
            staged.append((value, _stage_file(value.target_path, value.candidate_bytes)))
        for value, staged_path in staged:
            os.replace(staged_path, value.target_path)

        after_catalog = load_catalog(catalog_path, project_root)
        if after_catalog.digest != verification.manifest["expected_catalog_sha256"]:
            raise PromotionError("promotion_bundle_post_apply_catalog_digest_mismatch")
    except Exception as exc:
        rollback_errors: list[str] = []
        for value in verification.files:
            try:
                rollback_path = _stage_file(value.target_path, value.original_bytes)
                os.replace(rollback_path, value.target_path)
            except Exception as rollback_exc:
                rollback_errors.append(f"{value.kind}:{rollback_exc}")
        if rollback_errors:
            raise PromotionError(
                "promotion_bundle_apply_and_rollback_failed:"
                + "|".join(rollback_errors)
            ) from exc
        if isinstance(exc, PromotionError):
            raise
        raise PromotionError(f"promotion_bundle_apply_failed:{exc}") from exc
    finally:
        for _, staged_path in staged:
            if staged_path.exists():
                staged_path.unlink()

    return result
