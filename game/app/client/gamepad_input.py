from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from typing import Protocol

from game.app.presentation.input_actions import (
    InputBindingProfile,
    InputDevice,
    MenuInputAction,
    build_default_input_binding_profile,
)


XINPUT_GAMEPAD_DPAD_UP = 0x0001
XINPUT_GAMEPAD_DPAD_DOWN = 0x0002
XINPUT_GAMEPAD_A = 0x1000
XINPUT_GAMEPAD_B = 0x2000
XINPUT_GAMEPAD_Y = 0x8000
ERROR_SUCCESS = 0


class _XInputGamepad(ctypes.Structure):
    _fields_ = [
        ("wButtons", ctypes.c_ushort),
        ("bLeftTrigger", ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX", ctypes.c_short),
        ("sThumbLY", ctypes.c_short),
        ("sThumbRX", ctypes.c_short),
        ("sThumbRY", ctypes.c_short),
    ]


class _XInputState(ctypes.Structure):
    _fields_ = [
        ("dwPacketNumber", ctypes.c_ulong),
        ("Gamepad", _XInputGamepad),
    ]


@dataclass(frozen=True)
class GamepadState:
    connected: bool
    packet_number: int = 0
    buttons: int = 0
    left_thumb_x: int = 0
    left_thumb_y: int = 0

    @classmethod
    def disconnected(cls) -> "GamepadState":
        return cls(connected=False)


class GamepadBackend(Protocol):
    @property
    def backend_name(self) -> str:
        ...

    @property
    def is_available(self) -> bool:
        ...

    def poll(self) -> GamepadState:
        ...


class NullGamepadBackend:
    @property
    def backend_name(self) -> str:
        return "none"

    @property
    def is_available(self) -> bool:
        return False

    def poll(self) -> GamepadState:
        return GamepadState.disconnected()


class XInputGamepadBackend:
    """Windows XInputを標準ライブラリctypesだけで読み取る。"""

    DLL_CANDIDATES = ("xinput1_4", "xinput1_3", "xinput9_1_0")

    def __init__(self, user_index: int = 0) -> None:
        if user_index < 0 or user_index > 3:
            raise ValueError("xinput_user_index_must_be_between_0_and_3")
        self._user_index = user_index
        self._library = None
        self._get_state = None
        self._backend_name = "unavailable"
        self._load_library()

    @property
    def backend_name(self) -> str:
        return self._backend_name

    @property
    def is_available(self) -> bool:
        return self._get_state is not None

    def _load_library(self) -> None:
        if os.name != "nt":
            return
        win_dll = getattr(ctypes, "WinDLL", None)
        if win_dll is None:
            return
        for candidate in self.DLL_CANDIDATES:
            try:
                library = win_dll(candidate)
                get_state = library.XInputGetState
                get_state.argtypes = [ctypes.c_uint, ctypes.POINTER(_XInputState)]
                get_state.restype = ctypes.c_uint
            except (AttributeError, OSError):
                continue
            self._library = library
            self._get_state = get_state
            self._backend_name = candidate
            return

    def poll(self) -> GamepadState:
        if self._get_state is None:
            return GamepadState.disconnected()
        state = _XInputState()
        try:
            result = int(self._get_state(self._user_index, ctypes.byref(state)))
        except (OSError, ValueError):
            return GamepadState.disconnected()
        if result != ERROR_SUCCESS:
            return GamepadState.disconnected()
        gamepad = state.Gamepad
        return GamepadState(
            connected=True,
            packet_number=int(state.dwPacketNumber),
            buttons=int(gamepad.wButtons),
            left_thumb_x=int(gamepad.sThumbLX),
            left_thumb_y=int(gamepad.sThumbLY),
        )


def build_default_gamepad_backend(user_index: int = 0) -> GamepadBackend:
    backend = XInputGamepadBackend(user_index=user_index)
    if backend.is_available:
        return backend
    return NullGamepadBackend()


@dataclass(frozen=True)
class GamepadInputEvent:
    action: MenuInputAction
    source_token: str
    repeated: bool = False


class GamepadInputInterpreter:
    """XInput状態を意味入力へ変換し、移動入力だけ安全にリピートする。"""

    REPEATABLE_ACTIONS = frozenset(
        {
            MenuInputAction.MOVE_UP,
            MenuInputAction.MOVE_DOWN,
        }
    )

    def __init__(
        self,
        profile: InputBindingProfile | None = None,
        *,
        stick_deadzone: int = 12000,
        repeat_delay_ms: int = 420,
        repeat_interval_ms: int = 130,
    ) -> None:
        if stick_deadzone < 0 or stick_deadzone > 32767:
            raise ValueError("gamepad_stick_deadzone_out_of_range")
        if repeat_delay_ms < 0:
            raise ValueError("gamepad_repeat_delay_must_be_non_negative")
        if repeat_interval_ms <= 0:
            raise ValueError("gamepad_repeat_interval_must_be_positive")
        self._profile = profile or build_default_input_binding_profile()
        self._stick_deadzone = stick_deadzone
        self._repeat_delay_ms = repeat_delay_ms
        self._repeat_interval_ms = repeat_interval_ms
        self._pressed_since: dict[MenuInputAction, int] = {}
        self._last_emitted_at: dict[MenuInputAction, int] = {}

    def reset(self) -> None:
        self._pressed_since.clear()
        self._last_emitted_at.clear()

    def process(
        self,
        state: GamepadState,
        *,
        now_ms: int,
    ) -> tuple[GamepadInputEvent, ...]:
        if now_ms < 0:
            raise ValueError("gamepad_now_ms_must_be_non_negative")
        if not state.connected:
            self.reset()
            return tuple()

        action_tokens = self._active_action_tokens(state)
        active_actions = set(action_tokens)
        for action in tuple(self._pressed_since):
            if action not in active_actions:
                self._pressed_since.pop(action, None)
                self._last_emitted_at.pop(action, None)

        events: list[GamepadInputEvent] = []
        for action, token in action_tokens.items():
            if action not in self._pressed_since:
                self._pressed_since[action] = now_ms
                self._last_emitted_at[action] = now_ms
                events.append(GamepadInputEvent(action=action, source_token=token))
                continue
            if action not in self.REPEATABLE_ACTIONS:
                continue
            pressed_since = self._pressed_since[action]
            last_emitted = self._last_emitted_at[action]
            if now_ms - pressed_since < self._repeat_delay_ms:
                continue
            if now_ms - last_emitted < self._repeat_interval_ms:
                continue
            self._last_emitted_at[action] = now_ms
            events.append(
                GamepadInputEvent(
                    action=action,
                    source_token=token,
                    repeated=True,
                )
            )
        return tuple(events)

    def _active_action_tokens(
        self,
        state: GamepadState,
    ) -> dict[MenuInputAction, str]:
        tokens: list[str] = []
        if state.buttons & XINPUT_GAMEPAD_DPAD_UP:
            tokens.append("dpad_up")
        elif state.left_thumb_y >= self._stick_deadzone:
            tokens.append("left_stick_up")

        if state.buttons & XINPUT_GAMEPAD_DPAD_DOWN:
            tokens.append("dpad_down")
        elif state.left_thumb_y <= -self._stick_deadzone:
            tokens.append("left_stick_down")

        if state.buttons & XINPUT_GAMEPAD_A:
            tokens.append("button_south")
        if state.buttons & XINPUT_GAMEPAD_B:
            tokens.append("button_east")
        if state.buttons & XINPUT_GAMEPAD_Y:
            tokens.append("button_north")

        resolved: dict[MenuInputAction, str] = {}
        for token in tokens:
            action = self._profile.resolve(InputDevice.GAMEPAD, token)
            if action is not None and action not in resolved:
                resolved[action] = token
        return resolved


@dataclass
class InputDeviceTracker:
    active_device: InputDevice = InputDevice.KEYBOARD
    gamepad_connected: bool = False
    switch_count: int = 0

    def observe(self, device: InputDevice) -> bool:
        changed = device != self.active_device
        if changed:
            self.active_device = device
            self.switch_count += 1
        return changed

    def update_gamepad_connection(self, connected: bool) -> bool:
        changed = bool(connected) != self.gamepad_connected
        self.gamepad_connected = bool(connected)
        if not self.gamepad_connected and self.active_device == InputDevice.GAMEPAD:
            self.observe(InputDevice.KEYBOARD)
        return changed

    def to_dict(self) -> dict[str, object]:
        return {
            "active_device": self.active_device.value,
            "gamepad_connected": self.gamepad_connected,
            "switch_count": self.switch_count,
        }
