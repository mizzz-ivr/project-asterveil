from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class InputDevice(str, Enum):
    KEYBOARD = "keyboard"
    GAMEPAD = "gamepad"


class MenuInputAction(str, Enum):
    MOVE_UP = "move_up"
    MOVE_DOWN = "move_down"
    CONFIRM = "confirm"
    CANCEL = "cancel"
    SHOW_GUIDE = "show_guide"


@dataclass(frozen=True)
class InputBinding:
    device: InputDevice
    token: str
    action: MenuInputAction
    display_label: str


@dataclass(frozen=True)
class InputHint:
    action: MenuInputAction
    keyboard_label: str | None
    gamepad_label: str | None


class InputBindingProfile:
    """物理入力トークンをメニュー操作の意味アクションへ解決する。"""

    def __init__(self, bindings: Iterable[InputBinding]) -> None:
        normalized_bindings: list[InputBinding] = []
        lookup: dict[tuple[InputDevice, str], MenuInputAction] = {}
        labels: dict[tuple[InputDevice, MenuInputAction], list[str]] = {}

        for binding in bindings:
            token = self._normalize_token(binding.token)
            if not token:
                raise ValueError("input binding token must not be empty")
            if not binding.display_label.strip():
                raise ValueError("input binding display_label must not be empty")

            lookup_key = (binding.device, token)
            if lookup_key in lookup:
                raise ValueError(
                    "duplicate input binding: "
                    f"device={binding.device.value}:token={binding.token}"
                )

            normalized = InputBinding(
                device=binding.device,
                token=token,
                action=binding.action,
                display_label=binding.display_label.strip(),
            )
            normalized_bindings.append(normalized)
            lookup[lookup_key] = binding.action
            labels.setdefault((binding.device, binding.action), []).append(
                normalized.display_label
            )

        if not normalized_bindings:
            raise ValueError("input binding profile must not be empty")

        self._bindings = tuple(normalized_bindings)
        self._lookup = lookup
        self._labels = {
            key: tuple(values)
            for key, values in labels.items()
        }

    @property
    def bindings(self) -> tuple[InputBinding, ...]:
        return self._bindings

    def resolve(self, device: InputDevice, token: str) -> MenuInputAction | None:
        normalized_token = self._normalize_token(token)
        if not normalized_token:
            return None
        return self._lookup.get((device, normalized_token))

    def labels_for(
        self,
        device: InputDevice,
        action: MenuInputAction,
    ) -> tuple[str, ...]:
        return self._labels.get((device, action), tuple())

    def primary_label(
        self,
        device: InputDevice,
        action: MenuInputAction,
    ) -> str | None:
        labels = self.labels_for(device, action)
        return labels[0] if labels else None

    def hints(
        self,
        actions: Iterable[MenuInputAction] | None = None,
    ) -> tuple[InputHint, ...]:
        target_actions = tuple(actions) if actions is not None else tuple(MenuInputAction)
        return tuple(
            InputHint(
                action=action,
                keyboard_label=self.primary_label(InputDevice.KEYBOARD, action),
                gamepad_label=self.primary_label(InputDevice.GAMEPAD, action),
            )
            for action in target_actions
        )

    @staticmethod
    def _normalize_token(token: str) -> str:
        return token.strip().lower()


def build_default_input_binding_profile() -> InputBindingProfile:
    return InputBindingProfile(
        (
            InputBinding(InputDevice.KEYBOARD, "arrow_up", MenuInputAction.MOVE_UP, "↑"),
            InputBinding(InputDevice.KEYBOARD, "w", MenuInputAction.MOVE_UP, "W"),
            InputBinding(InputDevice.KEYBOARD, "arrow_down", MenuInputAction.MOVE_DOWN, "↓"),
            InputBinding(InputDevice.KEYBOARD, "s", MenuInputAction.MOVE_DOWN, "S"),
            InputBinding(InputDevice.KEYBOARD, "enter", MenuInputAction.CONFIRM, "Enter"),
            InputBinding(InputDevice.KEYBOARD, "space", MenuInputAction.CONFIRM, "Space"),
            InputBinding(InputDevice.KEYBOARD, "escape", MenuInputAction.CANCEL, "Esc"),
            InputBinding(InputDevice.KEYBOARD, "backspace", MenuInputAction.CANCEL, "Backspace"),
            InputBinding(InputDevice.KEYBOARD, "g", MenuInputAction.SHOW_GUIDE, "G"),
            InputBinding(InputDevice.GAMEPAD, "dpad_up", MenuInputAction.MOVE_UP, "D-pad ↑"),
            InputBinding(
                InputDevice.GAMEPAD,
                "left_stick_up",
                MenuInputAction.MOVE_UP,
                "左スティック ↑",
            ),
            InputBinding(InputDevice.GAMEPAD, "dpad_down", MenuInputAction.MOVE_DOWN, "D-pad ↓"),
            InputBinding(
                InputDevice.GAMEPAD,
                "left_stick_down",
                MenuInputAction.MOVE_DOWN,
                "左スティック ↓",
            ),
            InputBinding(InputDevice.GAMEPAD, "button_south", MenuInputAction.CONFIRM, "A"),
            InputBinding(InputDevice.GAMEPAD, "button_east", MenuInputAction.CANCEL, "B"),
            InputBinding(InputDevice.GAMEPAD, "button_north", MenuInputAction.SHOW_GUIDE, "Y"),
        )
    )
