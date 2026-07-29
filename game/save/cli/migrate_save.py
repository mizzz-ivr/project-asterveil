from __future__ import annotations

import argparse
import json
from pathlib import Path

from game.save.infrastructure.repository import JsonFileSaveRepository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Project Asterveilのセーブデータを現在Versionへ移行します。"
    )
    parser.add_argument("save_path", type=Path, help="移行対象のセーブJSON")
    parser.add_argument(
        "--backup-path",
        type=Path,
        default=None,
        help="更新前バックアップの保存先。省略時は対象ファイル名から自動生成します。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="移行可否だけを検証し、ファイルを書き換えません。",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repository = JsonFileSaveRepository(args.save_path)

    try:
        if args.dry_run:
            migration = repository.load_with_report()
            result = {
                **migration.to_dict(),
                "source_path": str(args.save_path),
                "backup_path": None,
                "file_updated": False,
                "dry_run": True,
            }
        else:
            file_result = repository.migrate_file(backup_path=args.backup_path)
            result = {
                **file_result.to_dict(),
                "dry_run": False,
            }
    except (FileNotFoundError, FileExistsError, json.JSONDecodeError, ValueError) as exc:
        print(f"save_migration_failed:{type(exc).__name__}:{exc}")
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
