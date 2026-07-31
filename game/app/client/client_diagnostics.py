from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import sys
import traceback
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Mapping, Sequence


SENSITIVE_KEY_PATTERN = re.compile(
    r"(token|secret|password|authorization|cookie|api[_-]?key)",
    re.IGNORECASE,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DiagnosticSeverity(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass(frozen=True)
class DiagnosticEvent:
    timestamp: str
    session_id: str
    severity: DiagnosticSeverity
    category: str
    event_name: str
    message: str
    context: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "severity": self.severity.value,
            "category": self.category,
            "event_name": self.event_name,
            "message": self.message,
            "context": dict(self.context),
        }


class StructuredDiagnosticLogger:
    """ローカル保存だけを行うNDJSON診断ログ。外部送信はしない。"""

    def __init__(
        self,
        root: Path,
        *,
        session_id: str | None = None,
        max_file_bytes: int = 1_000_000,
        max_files: int = 5,
        clock: Callable[[], datetime] | None = None,
        enabled: bool = True,
    ) -> None:
        if max_file_bytes <= 0:
            raise ValueError("diagnostic_max_file_bytes_must_be_positive")
        if max_files <= 0:
            raise ValueError("diagnostic_max_files_must_be_positive")
        self._root = Path(root)
        self._session_id = session_id or uuid.uuid4().hex
        self._max_file_bytes = max_file_bytes
        self._max_files = max_files
        self._clock = clock or utc_now
        self._enabled = bool(enabled)
        self._root.mkdir(parents=True, exist_ok=True)
        self._log_path = self._root / f"session-{self._session_id}.ndjson"

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def log_path(self) -> Path:
        return self._log_path

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)

    def log(
        self,
        event_name: str,
        message: str,
        *,
        category: str = "client",
        severity: DiagnosticSeverity = DiagnosticSeverity.INFO,
        context: Mapping[str, object] | None = None,
    ) -> DiagnosticEvent:
        event = DiagnosticEvent(
            timestamp=self._clock().astimezone(timezone.utc).replace(microsecond=0).isoformat(),
            session_id=self._session_id,
            severity=severity,
            category=_normalized_text(category, "diagnostic_category"),
            event_name=_normalized_text(event_name, "diagnostic_event_name"),
            message=str(message),
            context=_sanitize_mapping(context or {}),
        )
        if not self._enabled:
            return event
        self._rotate_if_needed()
        encoded = json.dumps(
            event.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"
        with self._log_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded)
            stream.flush()
        return event

    def _rotate_if_needed(self) -> None:
        if not self._log_path.exists():
            return
        try:
            size = self._log_path.stat().st_size
        except OSError:
            return
        if size < self._max_file_bytes:
            return
        for index in range(self._max_files - 1, 0, -1):
            source = self._root / f"{self._log_path.name}.{index}"
            target = self._root / f"{self._log_path.name}.{index + 1}"
            if source.exists():
                if index + 1 >= self._max_files:
                    source.unlink(missing_ok=True)
                else:
                    os.replace(source, target)
        os.replace(self._log_path, self._root / f"{self._log_path.name}.1")


class CrashReportWriter:
    def __init__(
        self,
        root: Path,
        *,
        session_id: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._root = Path(root)
        self._session_id = session_id
        self._clock = clock or utc_now
        self._root.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        exception: BaseException,
        *,
        phase: str | None = None,
        route_id: str | None = None,
        context: Mapping[str, object] | None = None,
    ) -> Path:
        timestamp = self._clock().astimezone(timezone.utc).replace(microsecond=0)
        path = self._root / (
            f"crash-{timestamp.strftime('%Y%m%dT%H%M%SZ')}-{self._session_id}.json"
        )
        payload = {
            "schema_version": 1,
            "created_at": timestamp.isoformat(),
            "session_id": self._session_id,
            "exception": {
                "type": type(exception).__name__,
                "message": str(exception),
                "traceback": "".join(
                    traceback.format_exception(
                        type(exception), exception, exception.__traceback__
                    )
                ),
            },
            "client": {"phase": phase, "route_id": route_id},
            "environment": runtime_environment(),
            "context": _sanitize_mapping(context or {}),
        }
        _write_json_atomic(path, payload)
        return path


class SupportBundleExporter:
    """ログ・クラッシュ・設定・環境情報をZIP化する。セーブ本体は含めない。"""

    def __init__(
        self,
        support_root: Path,
        *,
        settings_path: Path | None = None,
        save_path: Path | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._support_root = Path(support_root)
        self._settings_path = Path(settings_path) if settings_path is not None else None
        self._save_path = Path(save_path) if save_path is not None else None
        self._clock = clock or utc_now

    def export(
        self,
        *,
        session_id: str,
        include_save_metadata: bool = True,
        additional_context: Mapping[str, object] | None = None,
    ) -> Path:
        timestamp = self._clock().astimezone(timezone.utc).replace(microsecond=0)
        output_root = self._support_root / "support-bundles"
        output_root.mkdir(parents=True, exist_ok=True)
        output_path = output_root / (
            f"asterveil-support-{timestamp.strftime('%Y%m%dT%H%M%SZ')}-{session_id}.zip"
        )
        manifest: dict[str, object] = {
            "schema_version": 1,
            "created_at": timestamp.isoformat(),
            "session_id": session_id,
            "privacy": {
                "save_file_included": False,
                "automatic_upload": False,
                "notes": "セーブ本体・認証情報・個人情報は自動収集しません。",
            },
            "environment": runtime_environment(),
            "context": _sanitize_mapping(additional_context or {}),
            "included_files": [],
        }
        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            included_files: list[dict[str, object]] = []
            for source, archive_path in self._iter_diagnostic_files():
                archive.write(source, archive_path)
                included_files.append(_file_record(source, archive_path))
            if self._settings_path is not None and self._settings_path.is_file():
                archive_path = "settings/client_settings.json"
                archive.write(self._settings_path, archive_path)
                included_files.append(_file_record(self._settings_path, archive_path))
            if include_save_metadata:
                archive.writestr(
                    "save/save_metadata.json",
                    json.dumps(
                        self._build_save_metadata(),
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    ) + "\n",
                )
                included_files.append(
                    {"path": "save/save_metadata.json", "source": "generated"}
                )
            archive.writestr(
                "README.txt",
                "Project Asterveil Support Bundle\n"
                "このZIPは手動で作成された診断資料です。\n"
                "セーブファイル本体は含まれていません。\n"
                "送付前に内容を確認し、不要な情報を削除してください。\n",
            )
            included_files.append({"path": "README.txt", "source": "generated"})
            manifest["included_files"] = included_files
            archive.writestr(
                "SUPPORT_MANIFEST.json",
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            )
        return output_path

    def _iter_diagnostic_files(self) -> Sequence[tuple[Path, str]]:
        collected: list[tuple[Path, str]] = []
        for directory_name, archive_root in (
            ("diagnostics", "diagnostics"),
            ("crashes", "crashes"),
        ):
            directory = self._support_root / directory_name
            if not directory.is_dir():
                continue
            for path in sorted(directory.iterdir()):
                if path.is_file() and path.suffix.lower() in {".json", ".ndjson"}:
                    collected.append((path, f"{archive_root}/{path.name}"))
        return tuple(collected[-20:])

    def _build_save_metadata(self) -> dict[str, object]:
        path = self._save_path
        if path is None or not path.is_file():
            return {"exists": False, "content_included": False}
        try:
            raw = path.read_bytes()
            modified_at = path.stat().st_mtime
        except OSError as exc:
            return {
                "exists": True,
                "content_included": False,
                "read_error": type(exc).__name__,
            }
        save_version: object = None
        try:
            payload = json.loads(raw.decode("utf-8"))
            if isinstance(payload, Mapping):
                save_version = payload.get("save_version")
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        return {
            "exists": True,
            "content_included": False,
            "file_name": path.name,
            "size_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "save_version": save_version,
            "last_modified_at": datetime.fromtimestamp(
                modified_at, tz=timezone.utc
            ).replace(microsecond=0).isoformat(),
        }


def runtime_environment() -> dict[str, object]:
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "executable_name": Path(sys.executable).name,
    }


def _sanitize_mapping(mapping: Mapping[str, object]) -> dict[str, object]:
    return {str(key): _sanitize_value(str(key), value) for key, value in mapping.items()}


def _sanitize_value(key: str, value: object) -> object:
    if SENSITIVE_KEY_PATTERN.search(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return _sanitize_mapping(value)
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_sanitize_value(key, item) for item in value]
    if isinstance(value, Path):
        return _sanitize_path(value)
    if isinstance(value, str):
        return _sanitize_string(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


def _sanitize_path(path: Path) -> str:
    try:
        home = Path.home().resolve()
        resolved = path.expanduser().resolve()
        if resolved == home:
            return "~"
        if home in resolved.parents:
            return str(Path("~") / resolved.relative_to(home))
        return str(resolved)
    except OSError:
        return str(path)


def _sanitize_string(value: str) -> str:
    home = str(Path.home())
    return value.replace(home, "~") if home and home in value else value


def _normalized_text(value: str, field_name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field_name}_must_not_be_empty")
    return normalized


def _file_record(path: Path, archive_path: str) -> dict[str, object]:
    raw = path.read_bytes()
    return {
        "path": archive_path,
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        with temporary_path.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink(missing_ok=True)
