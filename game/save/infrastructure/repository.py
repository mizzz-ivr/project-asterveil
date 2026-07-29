from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from game.save.application.migration import (
    SaveMigrationResult,
    SaveMigrationService,
)
from game.save.domain.entities import SAVE_VERSION, SaveData


@dataclass(frozen=True)
class SaveFileMigrationResult:
    migration: SaveMigrationResult
    source_path: Path
    backup_path: Path | None
    file_updated: bool

    def to_dict(self) -> dict[str, object]:
        return {
            **self.migration.to_dict(),
            "source_path": str(self.source_path),
            "backup_path": str(self.backup_path) if self.backup_path else None,
            "file_updated": self.file_updated,
        }


class JsonFileSaveRepository:
    def __init__(
        self,
        save_file_path: Path,
        *,
        migration_service: SaveMigrationService | None = None,
    ) -> None:
        self._save_file_path = save_file_path
        self._migration_service = migration_service or SaveMigrationService()

    @property
    def save_file_path(self) -> Path:
        return self._save_file_path

    def save(self, save_data: SaveData) -> None:
        if save_data.save_version != SAVE_VERSION:
            raise ValueError(
                "save_data_version_mismatch:"
                f"expected={SAVE_VERSION}:actual={save_data.save_version}"
            )
        self._atomic_write_payload(save_data.to_dict())

    def load(self) -> SaveData:
        return self.load_with_report().save_data

    def load_with_report(self) -> SaveMigrationResult:
        raw = self._read_payload()
        return self._migration_service.migrate(raw)

    def migrate_file(
        self,
        *,
        backup_path: Path | None = None,
    ) -> SaveFileMigrationResult:
        source_text = self._save_file_path.read_text(encoding="utf-8")
        raw = json.loads(source_text)
        migration = self._migration_service.migrate(raw)
        if not migration.migrated:
            return SaveFileMigrationResult(
                migration=migration,
                source_path=self._save_file_path,
                backup_path=None,
                file_updated=False,
            )

        resolved_backup = backup_path or self._default_backup_path(
            migration.original_version
        )
        if resolved_backup == self._save_file_path:
            raise ValueError("save_backup_path_must_differ_from_source")
        if resolved_backup.exists():
            raise FileExistsError(f"save_backup_already_exists:{resolved_backup}")

        backup_created = False
        try:
            self._write_backup_exclusive(resolved_backup, source_text)
            backup_created = True
            self._atomic_write_payload(migration.payload)
        except Exception:
            if backup_created:
                try:
                    resolved_backup.unlink()
                except FileNotFoundError:
                    pass
            raise

        return SaveFileMigrationResult(
            migration=migration,
            source_path=self._save_file_path,
            backup_path=resolved_backup,
            file_updated=True,
        )

    def _read_payload(self) -> dict[str, Any]:
        raw = json.loads(self._save_file_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("save_payload_must_be_mapping")
        return raw

    def _atomic_write_payload(self, payload: dict[str, Any]) -> None:
        self._save_file_path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(payload, ensure_ascii=False, indent=2)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._save_file_path.parent,
                prefix=f".{self._save_file_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(serialized)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, self._save_file_path)
            temporary_path = None
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except FileNotFoundError:
                    pass

    def _default_backup_path(self, original_version: int) -> Path:
        return self._save_file_path.with_name(
            f"{self._save_file_path.name}.pre-v{SAVE_VERSION}.from-v{original_version}.bak"
        )

    @staticmethod
    def _write_backup_exclusive(path: Path, source_text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as backup:
            backup.write(source_text)
            backup.flush()
            os.fsync(backup.fileno())


class InMemorySaveRepository:
    def __init__(self) -> None:
        self._payload: dict | None = None
        self._migration_service = SaveMigrationService()

    def save(self, save_data: SaveData) -> None:
        self._payload = save_data.to_dict()

    def load(self) -> SaveData:
        if self._payload is None:
            raise ValueError("save_data not found")
        return self._migration_service.migrate(self._payload).save_data
