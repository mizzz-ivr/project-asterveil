from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.chapter_content_pack import ContentPackError
from tools.content_promotion import (
    PromotionError,
    apply_bundle,
    evaluate_promotion,
    load_catalog,
    verify_bundle,
    write_bundle,
    write_outputs,
)
from tools.content_promotion.catalog import load_json, require_object


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="章コンテンツパックと既存Masterの統合検証・昇格計画"
    )
    parser.add_argument("--catalog", default="content/master_catalog_v1.json")
    parser.add_argument("--project-root", default=".")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("pack")
    validate_parser.add_argument("--strict", action="store_true")

    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("pack")
    plan_parser.add_argument("--output", required=True)
    plan_parser.add_argument("--strict", action="store_true")

    bundle_parser = subparsers.add_parser("bundle")
    bundle_parser.add_argument("pack")
    bundle_parser.add_argument("--output", required=True)
    bundle_parser.add_argument("--strict", action="store_true")

    verify_parser = subparsers.add_parser("verify-bundle")
    verify_parser.add_argument("bundle")

    apply_parser = subparsers.add_parser("apply-bundle")
    apply_parser.add_argument("bundle")
    apply_parser.add_argument("--confirm-catalog-sha", required=True)
    apply_parser.add_argument("--write", action="store_true")
    return parser


def _print_json(value: object) -> None:
    print(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    catalog_path = Path(args.catalog)
    project_root = Path(args.project_root)
    try:
        if args.command == "apply-bundle":
            result = apply_bundle(
                Path(args.bundle),
                catalog_path,
                project_root,
                confirm_catalog_sha=args.confirm_catalog_sha,
                write=args.write,
            )
            _print_json(result)
            return 0

        catalog = load_catalog(catalog_path, project_root)
        if args.command == "verify-bundle":
            verification = verify_bundle(Path(args.bundle), catalog)
            _print_json(
                {
                    "status": "verified",
                    "source_catalog_sha256": verification.manifest[
                        "source_catalog_sha256"
                    ],
                    "expected_catalog_sha256": verification.manifest[
                        "expected_catalog_sha256"
                    ],
                    "file_count": len(verification.files),
                    "added_entity_count": sum(
                        len(value.added_ids) for value in verification.files
                    ),
                }
            )
            return 0

        pack = require_object(load_json(Path(args.pack)), "pack")
        evaluation = evaluate_promotion(pack, catalog)
        summary = {
            "status": evaluation.plan["status"],
            "pack_sha256": evaluation.plan["pack_sha256"],
            "catalog_sha256": evaluation.plan["catalog_sha256"],
            "unresolved_reference_count": len(
                evaluation.plan["unresolved_references"]
            ),
            "conflict_count": len(evaluation.plan["conflicts"]),
            "warning_count": len(evaluation.warnings),
        }

        if args.command == "plan":
            write_outputs(evaluation, Path(args.output))
        elif args.command == "bundle":
            if evaluation.blocked:
                _print_json(summary)
                return 3
            if args.strict and evaluation.warnings:
                _print_json(summary)
                return 2
            output = Path(args.output)
            write_outputs(evaluation, output / "plan")
            manifest = write_bundle(
                evaluation,
                pack,
                catalog,
                output / "bundle",
            )
            summary["bundle"] = {
                "path": str(output / "bundle"),
                "file_count": len(manifest["files"]),
                "expected_catalog_sha256": manifest[
                    "expected_catalog_sha256"
                ],
            }

        _print_json(summary)
        if evaluation.blocked:
            return 3
        if args.strict and evaluation.warnings:
            return 2
        return 0
    except (OSError, json.JSONDecodeError, ContentPackError, PromotionError) as exc:
        print(f"chapter content promotion error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
