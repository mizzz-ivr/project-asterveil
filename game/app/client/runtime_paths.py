from __future__ import annotations

import os
import sys
from pathlib import Path


APPLICATION_DIRECTORY_NAME = "ProjectAsterveil"
SAVE_FILE_NAME = "steam_demo_slot_01.json"
SUPPORT_DIRECTORY_NAME = "support"
SUPPORT_SETTINGS_FILE_NAME = "client_settings.json"


def is_frozen_runtime() -> bool:
    return bool(getattr(sys, "frozen", False))


def source_project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def runtime_resource_root() -> Path:
    """ソース実行時とPyInstaller実行時のresource rootを返す。"""

    if not is_frozen_runtime():
        return source_project_root()

    pyinstaller_root = getattr(sys, "_MEIPASS", None)
    if pyinstaller_root:
        return Path(pyinstaller_root).resolve()
    return Path(sys.executable).resolve().parent


def default_master_root() -> Path:
    return runtime_resource_root() / "data" / "master"


def user_data_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data).expanduser().resolve() / APPLICATION_DIRECTORY_NAME

    if os.name == "nt":
        return Path.home() / "AppData" / "Local" / APPLICATION_DIRECTORY_NAME
    return Path.home() / ".local" / "share" / APPLICATION_DIRECTORY_NAME


def default_save_path() -> Path:
    if is_frozen_runtime():
        return user_data_root() / SAVE_FILE_NAME
    return source_project_root() / "tmp" / SAVE_FILE_NAME


def default_support_root() -> Path:
    if is_frozen_runtime():
        return user_data_root() / SUPPORT_DIRECTORY_NAME
    return source_project_root() / "tmp" / "steam-demo-support"


def default_support_settings_path() -> Path:
    return default_support_root() / SUPPORT_SETTINGS_FILE_NAME
