from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

from game.app.application.demo_flow_service import SteamDemoApplication
from game.app.application.playable_slice import PlayableSliceApplication
from game.app.presentation.input_actions import MenuInputAction
from game.app.presentation.screen_action_dispatcher import (
    SteamDemoInteractiveScene,
    SteamDemoUiCommand,
)
from game.app.steam_demo_composition import (
    SteamDemoCompositionRoot,
    SteamDemoSessionComposition,
)


class SteamDemoClientPhase(str, Enum):
    TITLE = "title"
    SETTINGS = "settings"
    GAMEPLAY = "gameplay"
    EXITED = "exited"


class SteamDemoTitleAction(str, Enum):
    NEW_GAME = "new_game"
    CONTINUE = "continue"
    SETTINGS = "settings"
    EXIT = "exit"


@dataclass(frozen=True)
class SteamDemoClientSettings:
    font_scale_percent: int = 100
    show_logs: bool = True
    show_input_hints: bool = True

    ALLOWED_FONT_SCALES = (100, 125, 150)

    def __post_init__(self) -> None:
        if self.font_scale_percent not in self.ALLOWED_FONT_SCALES:
            raise ValueError(
                "unsupported_font_scale:"
                f"{self.font_scale_percent}:"
                f"allowed={','.join(str(value) for value in self.ALLOWED_FONT_SCALES)}"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "font_scale_percent": self.font_scale_percent,
            "show_logs": self.show_logs,
            "show_input_hints": self.show_input_hints,
        }


@dataclass(frozen=True)
class SteamDemoTitleActionViewModel:
    action_id: SteamDemoTitleAction
    label: str
    is_enabled: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "action_id": self.action_id.value,
            "label": self.label,
            "is_enabled": self.is_enabled,
        }


@dataclass(frozen=True)
class SteamDemoClientViewModel:
    phase: SteamDemoClientPhase
    title: str
    subtitle: str
    can_continue: bool
    title_actions: tuple[SteamDemoTitleActionViewModel, ...]
    settings: SteamDemoClientSettings
    scene: SteamDemoInteractiveScene | None = None
    logs: tuple[str, ...] = tuple()
    notification: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "phase": self.phase.value,
            "title": self.title,
            "subtitle": self.subtitle,
            "can_continue": self.can_continue,
            "title_actions": [action.to_dict() for action in self.title_actions],
            "settings": self.settings.to_dict(),
            "scene": self.scene.to_dict() if self.scene is not None else None,
            "logs": list(self.logs),
            "notification": self.notification,
        }


@dataclass(frozen=True)
class SteamDemoClientResult:
    view: SteamDemoClientViewModel
    logs: tuple[str, ...] = tuple()
    rejection_reason: str | None = None


SessionCompositionBuilder = Callable[
    [PlayableSliceApplication, SteamDemoApplication],
    SteamDemoSessionComposition,
]


class SteamDemoClientController:
    """タイトル導線とSteamデモ1セッションのライフサイクルを管理する。"""

    MAX_LOG_LINES = 200

    def __init__(
        self,
        playable: PlayableSliceApplication,
        demo: SteamDemoApplication,
        save_path: Path,
        *,
        settings: SteamDemoClientSettings | None = None,
        composition_builder: SessionCompositionBuilder | None = None,
    ) -> None:
        self._playable = playable
        self._demo = demo
        self._save_path = Path(save_path)
        self._settings = settings or SteamDemoClientSettings()
        self._composition_builder = composition_builder or SteamDemoCompositionRoot.build
        self._composition: SteamDemoSessionComposition | None = None
        self._phase = SteamDemoClientPhase.TITLE
        self._logs: tuple[str, ...] = tuple()
        self._notification: str | None = None

    @property
    def phase(self) -> SteamDemoClientPhase:
        return self._phase

    @property
    def settings(self) -> SteamDemoClientSettings:
        return self._settings

    @property
    def composition(self) -> SteamDemoSessionComposition | None:
        return self._composition

    @property
    def can_continue(self) -> bool:
        return self._save_path.is_file()

    def current_view(self) -> SteamDemoClientViewModel:
        scene: SteamDemoInteractiveScene | None = None
        if self._phase == SteamDemoClientPhase.GAMEPLAY:
            composition = self._require_gameplay_composition()
            scene = composition.action_dispatcher.current_scene()

        return SteamDemoClientViewModel(
            phase=self._phase,
            title="Project Asterveil",
            subtitle="Steam Demo",
            can_continue=self.can_continue,
            title_actions=self._title_actions()
            if self._phase == SteamDemoClientPhase.TITLE
            else tuple(),
            settings=self._settings,
            scene=scene,
            logs=self._logs,
            notification=self._notification,
        )

    def activate_title_action(
        self,
        action_id: SteamDemoTitleAction | str,
    ) -> SteamDemoClientResult:
        if self._phase != SteamDemoClientPhase.TITLE:
            return self._rejected("title_action_not_allowed_from_current_phase")

        try:
            action = (
                action_id
                if isinstance(action_id, SteamDemoTitleAction)
                else SteamDemoTitleAction(str(action_id).strip())
            )
        except ValueError:
            return self._rejected(
                "unknown_title_action",
                logs=(f"client_title_action_rejected:unknown:{action_id}",),
            )

        if action == SteamDemoTitleAction.NEW_GAME:
            return self.start_new_game()
        if action == SteamDemoTitleAction.CONTINUE:
            return self.continue_game()
        if action == SteamDemoTitleAction.SETTINGS:
            self._phase = SteamDemoClientPhase.SETTINGS
            self._notification = None
            return self._result()
        if action == SteamDemoTitleAction.EXIT:
            return self.request_exit()
        return self._rejected("unsupported_title_action")

    def start_new_game(self) -> SteamDemoClientResult:
        if self._phase != SteamDemoClientPhase.TITLE:
            return self._rejected("new_game_not_allowed_from_current_phase")
        try:
            logs = tuple(self._playable.new_game())
            composition = self._composition_builder(self._playable, self._demo)
        except (OSError, TypeError, ValueError, RuntimeError) as exc:
            self._composition = None
            self._phase = SteamDemoClientPhase.TITLE
            return self._rejected(
                "new_game_start_failed",
                logs=(f"client_new_game_rejected:{exc}",),
                notification="New Gameの開始に失敗しました。",
            )

        self._composition = composition
        self._phase = SteamDemoClientPhase.GAMEPLAY
        self._notification = "New Gameを開始しました。"
        return self._result(logs=logs)

    def continue_game(self) -> SteamDemoClientResult:
        if self._phase != SteamDemoClientPhase.TITLE:
            return self._rejected("continue_not_allowed_from_current_phase")
        if not self.can_continue:
            return self._rejected(
                "save_data_not_found",
                logs=("client_continue_rejected:save_data_not_found",),
                notification="セーブデータが見つかりません。",
            )

        try:
            success, message = self._playable.continue_game()
        except (OSError, TypeError, ValueError, RuntimeError) as exc:
            return self._rejected(
                "continue_failed",
                logs=(f"client_continue_rejected:{exc}",),
                notification="セーブデータを読み込めませんでした。",
            )
        if not success:
            return self._rejected(
                "continue_failed",
                logs=(message,),
                notification=message,
            )

        try:
            composition = self._composition_builder(self._playable, self._demo)
        except (OSError, TypeError, ValueError, RuntimeError) as exc:
            return self._rejected(
                "continue_session_build_failed",
                logs=(message, f"client_continue_session_rejected:{exc}"),
                notification="ロード後の画面初期化に失敗しました。",
            )

        self._composition = composition
        self._phase = SteamDemoClientPhase.GAMEPLAY
        self._notification = "セーブデータから再開しました。"
        return self._result(logs=(message,))

    def apply_settings(
        self,
        *,
        font_scale_percent: int,
        show_logs: bool,
        show_input_hints: bool,
    ) -> SteamDemoClientResult:
        if self._phase != SteamDemoClientPhase.SETTINGS:
            return self._rejected("settings_update_not_allowed_from_current_phase")
        try:
            settings = SteamDemoClientSettings(
                font_scale_percent=font_scale_percent,
                show_logs=bool(show_logs),
                show_input_hints=bool(show_input_hints),
            )
        except ValueError as exc:
            return self._rejected(
                "invalid_client_settings",
                logs=(f"client_settings_rejected:{exc}",),
                notification="設定値が不正です。",
            )

        self._settings = settings
        self._notification = "表示設定を反映しました。"
        return self._result(logs=("client_settings_updated",))

    def back_to_title(self) -> SteamDemoClientResult:
        if self._phase not in {
            SteamDemoClientPhase.SETTINGS,
            SteamDemoClientPhase.GAMEPLAY,
        }:
            return self._rejected("back_to_title_not_allowed_from_current_phase")
        self._composition = None
        self._phase = SteamDemoClientPhase.TITLE
        self._notification = "タイトルへ戻りました。"
        return self._result(logs=("client_returned_to_title",))

    def dispatch_scene_command(
        self,
        command: SteamDemoUiCommand,
    ) -> SteamDemoClientResult:
        if self._phase != SteamDemoClientPhase.GAMEPLAY:
            return self._rejected("scene_command_not_allowed_from_current_phase")
        composition = self._require_gameplay_composition()
        result = composition.action_dispatcher.dispatch(command)
        if result.exit_requested:
            self._composition = None
            self._phase = SteamDemoClientPhase.TITLE
            self._notification = "ゲームを終了し、タイトルへ戻りました。"
        else:
            self._notification = (
                f"操作を実行できませんでした: {result.rejection_reason}"
                if result.rejection_reason is not None
                else None
            )
        return self._result(
            logs=result.logs,
            rejection_reason=result.rejection_reason,
        )

    def activate_scene_entry(self, entry_id: str) -> SteamDemoClientResult:
        if self._phase != SteamDemoClientPhase.GAMEPLAY:
            return self._rejected("scene_entry_not_allowed_from_current_phase")
        composition = self._require_gameplay_composition()
        scene = composition.action_dispatcher.current_scene()
        return self.dispatch_scene_command(
            SteamDemoUiCommand.activate_entry(scene.scene.route_id, entry_id)
        )

    def handle_input(self, action: MenuInputAction) -> SteamDemoClientResult:
        if self._phase != SteamDemoClientPhase.GAMEPLAY:
            return self._rejected("input_not_allowed_from_current_phase")
        composition = self._require_gameplay_composition()
        scene = composition.action_dispatcher.current_scene()
        return self.dispatch_scene_command(
            SteamDemoUiCommand.input(scene.scene.route_id, action)
        )

    def request_exit(self) -> SteamDemoClientResult:
        self._composition = None
        self._phase = SteamDemoClientPhase.EXITED
        self._notification = "クライアントを終了します。"
        return self._result(logs=("client_exit_requested",))

    def _title_actions(self) -> tuple[SteamDemoTitleActionViewModel, ...]:
        return (
            SteamDemoTitleActionViewModel(
                SteamDemoTitleAction.NEW_GAME,
                "New Game",
                True,
            ),
            SteamDemoTitleActionViewModel(
                SteamDemoTitleAction.CONTINUE,
                "Continue",
                self.can_continue,
            ),
            SteamDemoTitleActionViewModel(
                SteamDemoTitleAction.SETTINGS,
                "Settings",
                True,
            ),
            SteamDemoTitleActionViewModel(
                SteamDemoTitleAction.EXIT,
                "Exit",
                True,
            ),
        )

    def _require_gameplay_composition(self) -> SteamDemoSessionComposition:
        if self._composition is None:
            raise RuntimeError("gameplay_composition_missing")
        return self._composition

    def _rejected(
        self,
        reason: str,
        *,
        logs: tuple[str, ...] | None = None,
        notification: str | None = None,
    ) -> SteamDemoClientResult:
        rejection_logs = logs or (f"client_action_rejected:{reason}",)
        if notification is not None:
            self._notification = notification
        return self._result(logs=rejection_logs, rejection_reason=reason)

    def _result(
        self,
        *,
        logs: tuple[str, ...] = tuple(),
        rejection_reason: str | None = None,
    ) -> SteamDemoClientResult:
        if not isinstance(logs, tuple) or not all(isinstance(line, str) for line in logs):
            raise TypeError("client_logs_must_be_string_tuple")
        if logs:
            self._logs = (self._logs + logs)[-self.MAX_LOG_LINES :]
        return SteamDemoClientResult(
            view=self.current_view(),
            logs=logs,
            rejection_reason=rejection_reason,
        )
