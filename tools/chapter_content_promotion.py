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
    evaluate_promotion,
    load_catalog,
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        catalog = load_catalog(Path(args.catalog), Path(args.project_root))
        pack = require_object(load_json(Path(args.pack)), "pack")
        evaluation = evaluate_promotion(pack, catalog)
        if args.command == "plan":
            write_outputs(evaluation, Path(args.output))

        print(
            json.dumps(
                {
                    "status": evaluation.plan["status"],
                    "pack_sha256": evaluation.plan["pack_sha256"],
                    "catalog_sha256": evaluation.plan["catalog_sha256"],
                    "unresolved_reference_count": len(
                        evaluation.plan["unresolved_references"]
                    ),
                    "conflict_count": len(evaluation.plan["conflicts"]),
                    "warning_count": len(evaluation.warnings),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
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
