from __future__ import annotations

from typing import Any, Callable

from game.app.client.steam_demo_client import (
    SteamDemoClientController,
    SteamDemoClientPhase,
    SteamDemoClientViewModel,
    SteamDemoTitleAction,
)
from game.app.presentation.input_actions import MenuInputAction
from game.app.presentation.screen_action_dispatcher import (
    SteamDemoInteractiveScene,
    SteamDemoUiCommand,
    SteamDemoUiCommandDescriptor,
)
from game.app.presentation.screen_renderer import SceneEntry, SceneField


class TkinterUnavailableError(RuntimeError):
    pass


def format_scene_field(field: SceneField) -> str:
    value = "-" if field.value is None else str(field.value)
    return f"{field.label}: {value}"


def format_scene_entry(entry: SceneEntry) -> str:
    lines = [entry.label]
    if entry.description:
        lines.append(entry.description)
    if entry.fields:
        lines.append(" / ".join(format_scene_field(field) for field in entry.fields))
    return "\n".join(lines)


def _load_tkinter() -> tuple[Any, Any]:
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError as exc:
        raise TkinterUnavailableError("tkinter_module_not_available") from exc
    return tk, ttk


class SteamDemoTkWindow:
    """Scene ModelとUiCommandだけを描画・送信する最小Tkinterクライアント。"""

    def __init__(
        self,
        controller: SteamDemoClientController,
        *,
        root: Any | None = None,
    ) -> None:
        self._tk, self._ttk = _load_tkinter()
        try:
            self._root = root or self._tk.Tk()
        except Exception as exc:
            raise TkinterUnavailableError(
                f"tkinter_window_initialization_failed:{exc}"
            ) from exc
        self._controller = controller
        self._ui_error: str | None = None
        self._root.title("Project Asterveil - Steam Demo")
        self._root.geometry("1180x760")
        self._root.minsize(900, 620)
        self._root.protocol("WM_DELETE_WINDOW", self._close_window)
        self._bind_keyboard()
        self.render()

    @property
    def root(self) -> Any:
        return self._root

    def run(self) -> int:
        self._root.mainloop()
        return 0

    def render(self) -> None:
        view = self._controller.current_view()
        if view.phase == SteamDemoClientPhase.EXITED:
            self._root.destroy()
            return
        self._configure_styles(view)
        self._clear_root()
        if view.phase == SteamDemoClientPhase.TITLE:
            self._render_title(view)
        elif view.phase == SteamDemoClientPhase.SETTINGS:
            self._render_settings(view)
        elif view.phase == SteamDemoClientPhase.GAMEPLAY:
            self._render_gameplay(view)
        else:
            self._render_error(f"未対応のクライアントPhaseです: {view.phase.value}")

    def _configure_styles(self, view: SteamDemoClientViewModel) -> None:
        scale = view.settings.font_scale_percent / 100
        style = self._ttk.Style(self._root)
        style.configure("Client.TFrame", padding=12)
        style.configure("Title.TLabel", font=("TkDefaultFont", round(30 * scale), "bold"))
        style.configure("Subtitle.TLabel", font=("TkDefaultFont", round(15 * scale)))
        style.configure("Heading.TLabel", font=("TkDefaultFont", round(18 * scale), "bold"))
        style.configure("Section.TLabelframe.Label", font=("TkDefaultFont", round(13 * scale), "bold"))
        style.configure("Action.TButton", font=("TkDefaultFont", round(12 * scale)), padding=8)
        style.configure("Selected.Action.TButton", font=("TkDefaultFont", round(12 * scale), "bold"), padding=8)
        style.configure("Body.TLabel", font=("TkDefaultFont", round(11 * scale)))
        style.configure("Notice.TLabel", font=("TkDefaultFont", round(11 * scale), "bold"))

    def _clear_root(self) -> None:
        for child in self._root.winfo_children():
            child.destroy()

    def _render_title(self, view: SteamDemoClientViewModel) -> None:
        container = self._ttk.Frame(self._root, style="Client.TFrame", padding=48)
        container.pack(fill="both", expand=True)

        self._ttk.Label(container, text=view.title, style="Title.TLabel").pack(pady=(80, 4))
        self._ttk.Label(container, text=view.subtitle, style="Subtitle.TLabel").pack(pady=(0, 36))

        button_frame = self._ttk.Frame(container)
        button_frame.pack()
        for action in view.title_actions:
            button = self._ttk.Button(
                button_frame,
                text=action.label,
                style="Action.TButton",
                width=24,
                command=lambda action_id=action.action_id: self._invoke(
                    lambda: self._controller.activate_title_action(action_id)
                ),
            )
            if not action.is_enabled:
                button.state(["disabled"])
            button.pack(fill="x", pady=6)

        self._render_feedback(container, view)

    def _render_settings(self, view: SteamDemoClientViewModel) -> None:
        container = self._ttk.Frame(self._root, style="Client.TFrame", padding=36)
        container.pack(fill="both", expand=True)
        self._ttk.Label(container, text="Settings", style="Title.TLabel").pack(anchor="w", pady=(10, 24))

        scale_var = self._tk.IntVar(value=view.settings.font_scale_percent)
        show_logs_var = self._tk.BooleanVar(value=view.settings.show_logs)
        show_hints_var = self._tk.BooleanVar(value=view.settings.show_input_hints)

        scale_frame = self._ttk.LabelFrame(container, text="文字サイズ", style="Section.TLabelframe")
        scale_frame.pack(fill="x", pady=8)
        for value in view.settings.ALLOWED_FONT_SCALES:
            self._ttk.Radiobutton(
                scale_frame,
                text=f"{value}%",
                value=value,
                variable=scale_var,
            ).pack(side="left", padx=12, pady=12)

        option_frame = self._ttk.LabelFrame(container, text="表示項目", style="Section.TLabelframe")
        option_frame.pack(fill="x", pady=8)
        self._ttk.Checkbutton(
            option_frame,
            text="操作ログを表示する",
            variable=show_logs_var,
        ).pack(anchor="w", padx=12, pady=8)
        self._ttk.Checkbutton(
            option_frame,
            text="入力ヒントを表示する",
            variable=show_hints_var,
        ).pack(anchor="w", padx=12, pady=8)

        action_frame = self._ttk.Frame(container)
        action_frame.pack(fill="x", pady=24)
        self._ttk.Button(
            action_frame,
            text="設定を反映",
            style="Action.TButton",
            command=lambda: self._invoke(
                lambda: self._controller.apply_settings(
                    font_scale_percent=int(scale_var.get()),
                    show_logs=bool(show_logs_var.get()),
                    show_input_hints=bool(show_hints_var.get()),
                )
            ),
        ).pack(side="left", padx=(0, 8))
        self._ttk.Button(
            action_frame,
            text="タイトルへ戻る",
            style="Action.TButton",
            command=lambda: self._invoke(self._controller.back_to_title),
        ).pack(side="left")

        self._render_feedback(container, view)

    def _render_gameplay(self, view: SteamDemoClientViewModel) -> None:
        interactive = view.scene
        if interactive is None:
            self._render_error("ゲームプレイSceneがありません。")
            return

        container = self._ttk.Frame(self._root, style="Client.TFrame", padding=16)
        container.pack(fill="both", expand=True)

        header = self._ttk.Frame(container)
        header.pack(fill="x", pady=(0, 8))
        self._ttk.Label(header, text=interactive.scene.title, style="Heading.TLabel").pack(anchor="w")
        if interactive.scene.subtitle:
            self._ttk.Label(
                header,
                text=interactive.scene.subtitle,
                style="Subtitle.TLabel",
            ).pack(anchor="w")
        self._ttk.Label(
            header,
            text=interactive.scene.route_id.value,
            style="Body.TLabel",
        ).pack(anchor="e")

        if interactive.scene.status:
            status = self._ttk.LabelFrame(container, text="状態", style="Section.TLabelframe")
            status.pack(fill="x", pady=(0, 8))
            self._ttk.Label(
                status,
                text="   ".join(format_scene_field(field) for field in interactive.scene.status),
                style="Body.TLabel",
                wraplength=1050,
                justify="left",
            ).pack(anchor="w", padx=10, pady=8)

        body = self._ttk.Frame(container)
        body.pack(fill="both", expand=True)
        canvas = self._tk.Canvas(body, highlightthickness=0)
        scrollbar = self._ttk.Scrollbar(body, orient="vertical", command=canvas.yview)
        scroll_content = self._ttk.Frame(canvas)
        window_id = canvas.create_window((0, 0), window=scroll_content, anchor="nw")
        scroll_content.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(window_id, width=event.width),
        )
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self._render_scene_sections(scroll_content, interactive)

        nav = self._ttk.Frame(container)
        nav.pack(fill="x", pady=(10, 4))
        for label, action in (
            ("↑", MenuInputAction.MOVE_UP),
            ("↓", MenuInputAction.MOVE_DOWN),
            ("決定", MenuInputAction.CONFIRM),
            ("戻る", MenuInputAction.CANCEL),
            ("ガイド", MenuInputAction.SHOW_GUIDE),
        ):
            self._ttk.Button(
                nav,
                text=label,
                command=lambda input_action=action: self._invoke(
                    lambda: self._controller.handle_input(input_action)
                ),
            ).pack(side="left", padx=3)

        if view.settings.show_input_hints and interactive.scene.action_hints:
            hints = "   ".join(
                f"{hint.action_id}: {hint.keyboard_label or '-'} / {hint.gamepad_label or '-'}"
                for hint in interactive.scene.action_hints
            )
            self._ttk.Label(container, text=hints, style="Body.TLabel").pack(anchor="w", pady=4)

        if view.settings.show_logs:
            self._render_logs(container, view.logs)
        self._render_feedback(container, view)

    def _render_scene_sections(
        self,
        parent: Any,
        interactive: SteamDemoInteractiveScene,
    ) -> None:
        descriptors = {
            (descriptor.section_id, descriptor.command.entry_id): descriptor
            for descriptor in interactive.commands
        }
        rendered_commands: set[SteamDemoUiCommand] = set()

        for section in interactive.scene.sections:
            frame = self._ttk.LabelFrame(
                parent,
                text=section.title,
                style="Section.TLabelframe",
            )
            frame.pack(fill="x", padx=4, pady=6)
            if not section.entries:
                self._ttk.Label(frame, text="項目はありません。", style="Body.TLabel").pack(
                    anchor="w", padx=10, pady=8
                )
                continue
            for entry in section.entries:
                descriptor = descriptors.get((section.section_id, entry.entry_id))
                if descriptor is None:
                    self._ttk.Label(
                        frame,
                        text=format_scene_entry(entry),
                        style="Body.TLabel",
                        wraplength=1020,
                        justify="left",
                    ).pack(fill="x", anchor="w", padx=10, pady=6)
                    continue
                rendered_commands.add(descriptor.command)
                self._render_command_button(frame, entry, descriptor)

        remaining = tuple(
            descriptor
            for descriptor in interactive.commands
            if descriptor.command not in rendered_commands
        )
        if remaining:
            frame = self._ttk.LabelFrame(parent, text="操作", style="Section.TLabelframe")
            frame.pack(fill="x", padx=4, pady=6)
            for descriptor in remaining:
                self._render_command_button(
                    frame,
                    SceneEntry(entry_id=descriptor.command.entry_id or "", label=descriptor.label),
                    descriptor,
                )

    def _render_command_button(
        self,
        parent: Any,
        entry: SceneEntry,
        descriptor: SteamDemoUiCommandDescriptor,
    ) -> None:
        prefix = "▶ " if descriptor.is_selected else ""
        if descriptor.is_recommended:
            prefix += "★ "
        button = self._ttk.Button(
            parent,
            text=prefix + format_scene_entry(entry),
            style="Selected.Action.TButton" if descriptor.is_selected else "Action.TButton",
            command=lambda command=descriptor.command: self._invoke(
                lambda: self._controller.dispatch_scene_command(command)
            ),
        )
        if not descriptor.is_enabled:
            button.state(["disabled"])
        button.pack(fill="x", padx=10, pady=5)

    def _render_logs(self, parent: Any, logs: tuple[str, ...]) -> None:
        frame = self._ttk.LabelFrame(parent, text="操作ログ", style="Section.TLabelframe")
        frame.pack(fill="x", pady=(6, 0))
        text = self._tk.Text(frame, height=7, wrap="word")
        scrollbar = self._ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.insert("1.0", "\n".join(logs[-50:]) if logs else "ログはありません。")
        text.configure(state="disabled")
        text.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        scrollbar.pack(side="right", fill="y", padx=(0, 8), pady=8)

    def _render_feedback(self, parent: Any, view: SteamDemoClientViewModel) -> None:
        messages = [message for message in (view.notification, self._ui_error) if message]
        if not messages:
            return
        self._ttk.Label(
            parent,
            text="\n".join(messages),
            style="Notice.TLabel",
            wraplength=1050,
            justify="left",
        ).pack(fill="x", anchor="w", pady=8)

    def _render_error(self, message: str) -> None:
        container = self._ttk.Frame(self._root, style="Client.TFrame", padding=36)
        container.pack(fill="both", expand=True)
        self._ttk.Label(container, text="Client Error", style="Title.TLabel").pack(anchor="w")
        self._ttk.Label(
            container,
            text=message,
            style="Body.TLabel",
            wraplength=1000,
        ).pack(anchor="w", pady=16)
        self._ttk.Button(
            container,
            text="終了",
            command=self._close_window,
        ).pack(anchor="w")

    def _invoke(self, operation: Callable[[], object]) -> None:
        try:
            operation()
            self._ui_error = None
        except Exception as exc:
            self._ui_error = f"操作中にエラーが発生しました: {exc}"
        self.render()

    def _bind_keyboard(self) -> None:
        bindings = {
            "<Up>": MenuInputAction.MOVE_UP,
            "<Key-w>": MenuInputAction.MOVE_UP,
            "<Down>": MenuInputAction.MOVE_DOWN,
            "<Key-s>": MenuInputAction.MOVE_DOWN,
            "<Return>": MenuInputAction.CONFIRM,
            "<space>": MenuInputAction.CONFIRM,
            "<Escape>": MenuInputAction.CANCEL,
            "<BackSpace>": MenuInputAction.CANCEL,
            "<F1>": MenuInputAction.SHOW_GUIDE,
            "<Key-g>": MenuInputAction.SHOW_GUIDE,
        }
        for token, action in bindings.items():
            self._root.bind(
                token,
                lambda _event, input_action=action: self._handle_keyboard(input_action),
            )

    def _handle_keyboard(self, action: MenuInputAction) -> str | None:
        if self._controller.phase != SteamDemoClientPhase.GAMEPLAY:
            return None
        self._invoke(lambda: self._controller.handle_input(action))
        return "break"

    def _close_window(self) -> None:
        if self._controller.phase != SteamDemoClientPhase.EXITED:
            self._controller.request_exit()
        self._root.destroy()


def run_tk_steam_demo(controller: SteamDemoClientController) -> int:
    return SteamDemoTkWindow(controller).run()
