from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from game.app.client.client_diagnostics import (
    CrashReportWriter,
    DiagnosticSeverity,
    StructuredDiagnosticLogger,
    SupportBundleExporter,
)
from game.app.client.gamepad_input import (
    GamepadBackend,
    GamepadInputInterpreter,
    InputDeviceTracker,
    build_default_gamepad_backend,
)
from game.app.client.player_support import (
    SteamDemoGuideSession,
    SteamDemoSupportSettings,
    SteamDemoSupportSettingsRepository,
    build_default_guide_catalog,
)
from game.app.client.steam_demo_client import (
    SteamDemoClientController,
    SteamDemoClientPhase,
    SteamDemoClientViewModel,
)
from game.app.client.tk_steam_demo import SteamDemoTkWindow
from game.app.presentation.input_actions import (
    InputDevice,
    MenuInputAction,
    build_default_input_binding_profile,
)


class SteamDemoEnhancedTkWindow(SteamDemoTkWindow):
    """既存Scene描画へ入力切替、ガイド、診断機能を重ねる。"""

    GAMEPAD_POLL_INTERVAL_MS = 50

    def __init__(
        self,
        controller: SteamDemoClientController,
        *,
        support_root: Path,
        save_path: Path | None = None,
        settings_repository: SteamDemoSupportSettingsRepository | None = None,
        diagnostics: StructuredDiagnosticLogger | None = None,
        gamepad_backend: GamepadBackend | None = None,
        root: Any | None = None,
    ) -> None:
        self._support_root = Path(support_root)
        self._support_root.mkdir(parents=True, exist_ok=True)
        self._settings_repository = settings_repository or SteamDemoSupportSettingsRepository(
            self._support_root / "client_settings.json"
        )
        settings_result = self._settings_repository.load()
        self._support_settings = settings_result.settings
        self._guide_session = SteamDemoGuideSession(build_default_guide_catalog())
        self._input_profile = build_default_input_binding_profile()
        self._input_tracker = InputDeviceTracker()
        self._gamepad_backend = gamepad_backend or build_default_gamepad_backend(
            self._support_settings.gamepad_user_index
        )
        self._gamepad_interpreter = self._build_gamepad_interpreter()
        self._gamepad_poll_after_id: object | None = None
        self._diagnostics = diagnostics or StructuredDiagnosticLogger(
            self._support_root / "diagnostics",
            enabled=self._support_settings.diagnostics_enabled,
        )
        self._crash_writer = CrashReportWriter(
            self._support_root / "crashes",
            session_id=self._diagnostics.session_id,
        )
        self._bundle_exporter = SupportBundleExporter(
            self._support_root,
            settings_path=self._settings_repository.path,
            save_path=save_path,
        )
        super().__init__(controller, root=root)
        if hasattr(self._root, "report_callback_exception"):
            self._root.report_callback_exception = self._handle_tk_callback_exception
        self._diagnostics.log(
            "client_started",
            "Enhanced Steam demo client started.",
            context={
                "settings_recovered": settings_result.recovered_from_invalid_file,
                "gamepad_backend": self._gamepad_backend.backend_name,
                "gamepad_available": self._gamepad_backend.is_available,
            },
        )
        for warning in settings_result.warnings:
            self._diagnostics.log(
                "support_settings_recovered",
                warning,
                severity=DiagnosticSeverity.WARNING,
            )
        if (
            self._support_settings.show_first_run_guide
            and not self._support_settings.tutorial_completed
        ):
            self._guide_session.open_topic(
                "welcome", opened_from="first_run", first_run=True
            )
            self.render()
        self._schedule_gamepad_poll()

    @property
    def support_settings(self) -> SteamDemoSupportSettings:
        return self._support_settings

    @property
    def input_tracker(self) -> InputDeviceTracker:
        return self._input_tracker

    @property
    def guide_session(self) -> SteamDemoGuideSession:
        return self._guide_session

    def render(self) -> None:
        if self._guide_session.visible:
            view = self._controller.current_view()
            if view.phase == SteamDemoClientPhase.EXITED:
                self._root.destroy()
                return
            self._configure_styles(view)
            self._clear_root()
            self._render_guide(view)
            return
        super().render()

    def _configure_styles(self, view: SteamDemoClientViewModel) -> None:
        super()._configure_styles(view)
        if not self._support_settings.high_contrast:
            return
        style = self._ttk.Style(self._root)
        self._root.configure(background="#000000")
        for style_name in ("Client.TFrame", "TFrame"):
            style.configure(style_name, background="#000000")
        for style_name, foreground in (
            ("Title.TLabel", "#FFFFFF"),
            ("Subtitle.TLabel", "#F2F2F2"),
            ("Heading.TLabel", "#FFFF00"),
            ("Body.TLabel", "#FFFFFF"),
            ("Notice.TLabel", "#00FFFF"),
        ):
            style.configure(style_name, foreground=foreground, background="#000000")

    def _render_title(self, view: SteamDemoClientViewModel) -> None:
        super()._render_title(view)
        container = self._root.winfo_children()[0]
        frame = self._ttk.Frame(container)
        frame.pack(pady=(14, 0))
        self._ttk.Button(
            frame,
            text="遊び方・ヘルプ",
            command=lambda: self._open_guide("welcome", "title"),
        ).pack(side="left", padx=4)
        self._ttk.Button(
            frame,
            text="サポートZIPを作成",
            command=self._export_support_bundle,
        ).pack(side="left", padx=4)
        self._render_input_status(container)

    def _render_settings(self, view: SteamDemoClientViewModel) -> None:
        super()._render_settings(view)
        container = self._root.winfo_children()[0]
        frame = self._ttk.LabelFrame(
            container,
            text="アクセシビリティ・入力・サポート",
            style="Section.TLabelframe",
        )
        frame.pack(fill="x", pady=8)
        variables = {
            "high_contrast": self._tk.BooleanVar(value=self._support_settings.high_contrast),
            "reduced_motion": self._tk.BooleanVar(value=self._support_settings.reduced_motion),
            "gamepad_enabled": self._tk.BooleanVar(value=self._support_settings.gamepad_enabled),
            "show_context_tips": self._tk.BooleanVar(value=self._support_settings.show_context_tips),
            "diagnostics_enabled": self._tk.BooleanVar(value=self._support_settings.diagnostics_enabled),
        }
        for key, label in (
            ("high_contrast", "ハイコントラスト表示"),
            ("reduced_motion", "低モーション表示"),
            ("gamepad_enabled", "ゲームパッド入力を有効にする"),
            ("show_context_tips", "画面ごとのヒントを表示する"),
            ("diagnostics_enabled", "ローカル診断ログを保存する"),
        ):
            self._ttk.Checkbutton(
                frame, text=label, variable=variables[key]
            ).pack(anchor="w", padx=12, pady=4)
        actions = self._ttk.Frame(frame)
        actions.pack(fill="x", padx=12, pady=10)
        self._ttk.Button(
            actions,
            text="サポート設定を反映",
            command=lambda: self._apply_support_settings(
                **{key: bool(variable.get()) for key, variable in variables.items()}
            ),
        ).pack(side="left", padx=4)
        self._ttk.Button(
            actions,
            text="初回ガイドを再表示",
            command=self._reset_tutorial,
        ).pack(side="left", padx=4)
        self._ttk.Button(
            actions,
            text="サポートZIPを作成",
            command=self._export_support_bundle,
        ).pack(side="left", padx=4)
        self._render_input_status(container)

    def _render_gameplay(self, view: SteamDemoClientViewModel) -> None:
        show_hints = view.settings.show_input_hints
        base_view = view
        if show_hints:
            base_view = replace(
                view,
                settings=replace(view.settings, show_input_hints=False),
            )
        super()._render_gameplay(base_view)
        container = self._root.winfo_children()[0]
        if show_hints and view.scene is not None:
            labels = []
            for hint in view.scene.scene.action_hints:
                label = (
                    hint.gamepad_label
                    if self._input_tracker.active_device == InputDevice.GAMEPAD
                    else hint.keyboard_label
                )
                labels.append(f"{hint.action_id}: {label or '-'}")
            if labels:
                self._ttk.Label(
                    container,
                    text="   ".join(labels),
                    style="Body.TLabel",
                    wraplength=1050,
                ).pack(anchor="w", pady=4)
        if self._support_settings.show_context_tips:
            route_id = self._current_route_id()
            topic_id = self._guide_session.catalog.topic_for_route(route_id)
            page = self._guide_session.catalog.get(topic_id)
            hint_frame = self._ttk.Frame(container)
            hint_frame.pack(fill="x", pady=(4, 0))
            self._ttk.Label(
                hint_frame,
                text=f"ヒント: {page.summary}",
                style="Body.TLabel",
                wraplength=930,
            ).pack(side="left", fill="x", expand=True)
            self._ttk.Button(
                hint_frame,
                text="詳しく見る",
                command=lambda: self._open_guide(topic_id, f"route:{route_id}"),
            ).pack(side="right", padx=4)
        self._render_input_status(container)

    def _render_input_status(self, parent: Any) -> None:
        active = (
            "ゲームパッド"
            if self._input_tracker.active_device == InputDevice.GAMEPAD
            else "キーボード"
        )
        connection = "接続中" if self._input_tracker.gamepad_connected else "未接続"
        self._ttk.Label(
            parent,
            text=(
                f"現在の入力: {active} / ゲームパッド: {connection} "
                f"({self._gamepad_backend.backend_name})"
            ),
            style="Body.TLabel",
        ).pack(anchor="e", pady=(4, 0))

    def _render_guide(self, view: SteamDemoClientViewModel) -> None:
        guide = self._guide_session.current_view()
        page = guide.page
        if page is None:
            self._guide_session.close()
            super().render()
            return
        container = self._ttk.Frame(self._root, style="Client.TFrame", padding=36)
        container.pack(fill="both", expand=True)
        self._ttk.Label(
            container, text="遊び方・ヘルプ", style="Subtitle.TLabel"
        ).pack(anchor="w")
        self._ttk.Label(container, text=page.title, style="Title.TLabel").pack(
            anchor="w", pady=(4, 10)
        )
        self._ttk.Label(
            container,
            text=page.summary,
            style="Body.TLabel",
            wraplength=1050,
            justify="left",
        ).pack(anchor="w", fill="x", pady=(0, 12))
        steps_frame = self._ttk.LabelFrame(
            container, text="確認ポイント", style="Section.TLabelframe"
        )
        steps_frame.pack(fill="both", expand=True, pady=8)
        for index, step in enumerate(page.steps, start=1):
            self._ttk.Label(
                steps_frame,
                text=f"{index}. {step}",
                style="Body.TLabel",
                wraplength=980,
                justify="left",
            ).pack(anchor="w", fill="x", padx=12, pady=5)
        controls = []
        if page.keyboard_controls:
            controls.append("キーボード: " + " / ".join(page.keyboard_controls))
        if page.gamepad_controls:
            controls.append("ゲームパッド: " + " / ".join(page.gamepad_controls))
        if controls:
            self._ttk.Label(
                container,
                text="\n".join(controls),
                style="Body.TLabel",
                wraplength=1050,
                justify="left",
            ).pack(anchor="w", fill="x", pady=8)
        navigation = self._ttk.Frame(container)
        navigation.pack(fill="x", pady=(12, 0))
        previous = self._ttk.Button(
            navigation, text="前へ", command=self._previous_guide_page
        )
        previous.pack(side="left", padx=4)
        if guide.page_index <= 0:
            previous.state(["disabled"])
        is_last = guide.page_index >= guide.page_count - 1
        self._ttk.Button(
            navigation,
            text="完了" if is_last else "次へ",
            command=self._close_guide if is_last else self._next_guide_page,
        ).pack(side="left", padx=4)
        self._ttk.Button(
            navigation, text="閉じる", command=self._close_guide
        ).pack(side="left", padx=4)
        self._ttk.Label(
            navigation,
            text=f"{guide.page_index + 1} / {guide.page_count}",
            style="Body.TLabel",
        ).pack(side="right")
        self._render_input_status(container)

    def _bind_keyboard(self) -> None:
        bindings = {
            "<Up>": "arrow_up",
            "<Key-w>": "w",
            "<Down>": "arrow_down",
            "<Key-s>": "s",
            "<Return>": "enter",
            "<space>": "space",
            "<Escape>": "escape",
            "<BackSpace>": "backspace",
            "<F1>": "g",
            "<Key-g>": "g",
        }
        for sequence, token in bindings.items():
            self._root.bind(
                sequence,
                lambda _event, physical_token=token: self._handle_physical_input(
                    InputDevice.KEYBOARD, physical_token
                ),
            )
        self._root.bind("<Left>", lambda _event: self._previous_guide_page())
        self._root.bind("<Right>", lambda _event: self._next_guide_page())
        self._root.bind("<F2>", lambda _event: self._export_support_bundle())

    def _handle_physical_input(self, device: InputDevice, token: str) -> str | None:
        action = self._input_profile.resolve(device, token)
        if action is None:
            return None
        if self._input_tracker.observe(device):
            self._diagnostics.log(
                "input_device_changed",
                f"Active input changed to {device.value}.",
                category="input",
                context=self._input_tracker.to_dict(),
            )
        self._handle_semantic_action(action)
        return "break"

    def _handle_semantic_action(self, action: MenuInputAction) -> None:
        if self._guide_session.visible:
            guide = self._guide_session.current_view()
            if action == MenuInputAction.MOVE_UP:
                self._previous_guide_page()
            elif action == MenuInputAction.MOVE_DOWN:
                self._next_guide_page()
            elif action == MenuInputAction.CONFIRM:
                if guide.page_index >= guide.page_count - 1:
                    self._close_guide()
                else:
                    self._next_guide_page()
            elif action in {MenuInputAction.CANCEL, MenuInputAction.SHOW_GUIDE}:
                self._close_guide()
            return
        if action == MenuInputAction.SHOW_GUIDE:
            self._guide_session.open_for_route(self._current_route_id())
            self._diagnostics.log(
                "guide_opened", "Context guide opened.", category="guide"
            )
            self.render()
            return
        if self._controller.phase == SteamDemoClientPhase.GAMEPLAY:
            self._invoke(lambda: self._controller.handle_input(action))

    def _schedule_gamepad_poll(self) -> None:
        try:
            self._gamepad_poll_after_id = self._root.after(
                self.GAMEPAD_POLL_INTERVAL_MS, self._poll_gamepad
            )
        except Exception:
            self._gamepad_poll_after_id = None

    def _poll_gamepad(self) -> None:
        self._gamepad_poll_after_id = None
        try:
            if self._support_settings.gamepad_enabled:
                state = self._gamepad_backend.poll()
                connection_changed = self._input_tracker.update_gamepad_connection(
                    state.connected
                )
                if connection_changed:
                    self._diagnostics.log(
                        "gamepad_connection_changed",
                        "Gamepad connection changed.",
                        category="input",
                        context={"connected": state.connected},
                    )
                    self.render()
                for event in self._gamepad_interpreter.process(
                    state, now_ms=int(time.monotonic() * 1000)
                ):
                    self._input_tracker.observe(InputDevice.GAMEPAD)
                    self._handle_semantic_action(event.action)
            else:
                self._input_tracker.update_gamepad_connection(False)
                self._gamepad_interpreter.reset()
        except Exception as exc:
            self._record_exception(exc, operation="gamepad_poll")
        finally:
            if self._controller.phase != SteamDemoClientPhase.EXITED:
                self._schedule_gamepad_poll()

    def _build_gamepad_interpreter(self) -> GamepadInputInterpreter:
        return GamepadInputInterpreter(
            self._input_profile,
            stick_deadzone=self._support_settings.stick_deadzone,
            repeat_delay_ms=self._support_settings.repeat_delay_ms,
            repeat_interval_ms=self._support_settings.repeat_interval_ms,
        )

    def _apply_support_settings(self, **values: bool) -> None:
        updated = replace(self._support_settings, **values)
        self._settings_repository.save(updated)
        self._support_settings = updated
        self._diagnostics.set_enabled(updated.diagnostics_enabled)
        self._gamepad_interpreter = self._build_gamepad_interpreter()
        self._ui_error = "サポート設定を保存しました。"
        self.render()

    def _reset_tutorial(self) -> None:
        self._support_settings = self._settings_repository.reset_tutorial()
        self._guide_session.open_topic(
            "welcome", opened_from="settings_reset", first_run=True
        )
        self.render()

    def _open_guide(self, topic_id: str, opened_from: str) -> None:
        self._guide_session.open_topic(topic_id, opened_from=opened_from)
        self.render()

    def _next_guide_page(self) -> str | None:
        if self._guide_session.visible:
            self._guide_session.next_page()
            self.render()
            return "break"
        return None

    def _previous_guide_page(self) -> str | None:
        if self._guide_session.visible:
            self._guide_session.previous_page()
            self.render()
            return "break"
        return None

    def _close_guide(self) -> str | None:
        completed_first_run = self._guide_session.close()
        if completed_first_run and not self._support_settings.tutorial_completed:
            self._support_settings = self._support_settings.with_tutorial_completed()
            self._settings_repository.save(self._support_settings)
        self.render()
        return "break"

    def _export_support_bundle(self) -> str | None:
        try:
            path = self._bundle_exporter.export(
                session_id=self._diagnostics.session_id,
                include_save_metadata=self._support_settings.save_metadata_in_support_bundle,
                additional_context={
                    "phase": self._controller.phase.value,
                    "route_id": self._current_route_id(),
                    "input": self._input_tracker.to_dict(),
                },
            )
            self._ui_error = f"サポートZIPを作成しました: {path}"
        except Exception as exc:
            self._record_exception(exc, operation="support_bundle_export")
            self._ui_error = f"サポートZIPを作成できませんでした: {exc}"
        self.render()
        return "break"

    def _invoke(self, operation: Callable[[], object]) -> None:
        try:
            operation()
            self._ui_error = None
        except Exception as exc:
            report_path = self._record_exception(exc, operation="ui_operation")
            self._ui_error = f"操作中にエラーが発生しました。診断レポート: {report_path}"
        self.render()

    def _handle_tk_callback_exception(
        self,
        exception_type: type[BaseException],
        exception: BaseException,
        traceback_object: object,
    ) -> None:
        del exception_type
        if hasattr(exception, "with_traceback"):
            exception = exception.with_traceback(traceback_object)  # type: ignore[arg-type]
        report_path = self._record_exception(exception, operation="tk_callback")
        self._ui_error = f"画面処理中にエラーが発生しました。診断レポート: {report_path}"
        self.render()

    def _record_exception(self, exception: BaseException, *, operation: str) -> Path:
        route_id = self._current_route_id()
        self._diagnostics.log(
            "client_exception",
            str(exception),
            category="crash",
            severity=DiagnosticSeverity.ERROR,
            context={
                "operation": operation,
                "phase": self._controller.phase.value,
                "route_id": route_id,
                "exception_type": type(exception).__name__,
            },
        )
        return self._crash_writer.write(
            exception,
            phase=self._controller.phase.value,
            route_id=route_id,
            context={"operation": operation},
        )

    def _current_route_id(self) -> str | None:
        try:
            view = self._controller.current_view()
        except Exception:
            return None
        if view.scene is None:
            return None
        return view.scene.scene.route_id.value

    def _close_window(self) -> None:
        if self._gamepad_poll_after_id is not None:
            try:
                self._root.after_cancel(self._gamepad_poll_after_id)
            except Exception:
                pass
            self._gamepad_poll_after_id = None
        super()._close_window()


def run_enhanced_tk_steam_demo(
    controller: SteamDemoClientController,
    *,
    support_root: Path,
    save_path: Path | None = None,
    settings_repository: SteamDemoSupportSettingsRepository | None = None,
    diagnostics: StructuredDiagnosticLogger | None = None,
    gamepad_backend: GamepadBackend | None = None,
) -> int:
    return SteamDemoEnhancedTkWindow(
        controller,
        support_root=support_root,
        save_path=save_path,
        settings_repository=settings_repository,
        diagnostics=diagnostics,
        gamepad_backend=gamepad_backend,
    ).run()
