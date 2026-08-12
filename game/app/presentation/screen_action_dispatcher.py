from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Mapping, TypeAlias

from game.app.presentation.economy_facility_screen import (
    CraftingScreenController,
    InnScreenController,
    ShopScreenController,
)
from game.app.presentation.equipment_workshop_screen import (
    EquipmentSalvageScreenController,
    EquipmentUpgradeScreenController,
)
from game.app.presentation.gathering_treasure_screen import (
    GatheringScreenController,
    TreasureScreenController,
)
from game.app.presentation.input_actions import MenuInputAction
from game.app.presentation.item_equipment_screen import (
    EquipmentScreenController,
    EquipmentScreenMode,
    ItemUseScreenController,
    ItemUseScreenMode,
)
from game.app.presentation.npc_field_event_screen import (
    FieldEventScreenController,
    FieldEventScreenMode,
    NpcDialogueScreenController,
    NpcDialogueScreenMode,
)
from game.app.presentation.quest_travel_screen import (
    QuestBoardScreenController,
    TravelScreenController,
)
from game.app.presentation.screen_renderer import (
    SteamDemoSceneBuilderRegistry,
    SteamDemoSceneModel,
)
from game.app.presentation.screen_router import SteamDemoRouteId
from game.app.presentation.screen_runtime import (
    SteamDemoRuntimeResult,
    SteamDemoScreenRuntime,
    SteamDemoSubScreenInteractionProtocol,
)


class SteamDemoUiCommandKind(str, Enum):
    ACTIVATE_ENTRY = "activate_entry"
    INPUT_ACTION = "input_action"


@dataclass(frozen=True)
class SteamDemoUiCommand:
    kind: SteamDemoUiCommandKind
    expected_route_id: SteamDemoRouteId
    entry_id: str | None = None
    input_action: MenuInputAction | None = None

    def __post_init__(self) -> None:
        if self.kind == SteamDemoUiCommandKind.ACTIVATE_ENTRY:
            if not self.entry_id:
                raise ValueError("activate_entry_command_requires_entry_id")
            if self.input_action is not None:
                raise ValueError("activate_entry_command_must_not_have_input_action")
            return
        if self.kind == SteamDemoUiCommandKind.INPUT_ACTION:
            if self.input_action is None:
                raise ValueError("input_action_command_requires_input_action")
            if self.entry_id is not None:
                raise ValueError("input_action_command_must_not_have_entry_id")
            return
        raise ValueError(f"unsupported_ui_command_kind:{self.kind}")

    @classmethod
    def activate_entry(
        cls,
        expected_route_id: SteamDemoRouteId,
        entry_id: str,
    ) -> SteamDemoUiCommand:
        return cls(
            kind=SteamDemoUiCommandKind.ACTIVATE_ENTRY,
            expected_route_id=expected_route_id,
            entry_id=entry_id,
        )

    @classmethod
    def input(
        cls,
        expected_route_id: SteamDemoRouteId,
        action: MenuInputAction,
    ) -> SteamDemoUiCommand:
        return cls(
            kind=SteamDemoUiCommandKind.INPUT_ACTION,
            expected_route_id=expected_route_id,
            input_action=action,
        )

    def to_dict(self) -> dict[str, str | None]:
        return {
            "kind": self.kind.value,
            "expected_route_id": self.expected_route_id.value,
            "entry_id": self.entry_id,
            "input_action": self.input_action.value if self.input_action else None,
        }


@dataclass(frozen=True)
class SteamDemoUiCommandDescriptor:
    command: SteamDemoUiCommand
    section_id: str
    label: str
    is_enabled: bool
    is_selected: bool = False
    is_recommended: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "command": self.command.to_dict(),
            "section_id": self.section_id,
            "label": self.label,
            "is_enabled": self.is_enabled,
            "is_selected": self.is_selected,
            "is_recommended": self.is_recommended,
        }


@dataclass(frozen=True)
class SteamDemoInteractiveScene:
    scene: SteamDemoSceneModel
    commands: tuple[SteamDemoUiCommandDescriptor, ...]

    def command_for_entry(self, entry_id: str) -> SteamDemoUiCommandDescriptor | None:
        matches = tuple(
            descriptor
            for descriptor in self.commands
            if descriptor.command.entry_id == entry_id
        )
        if len(matches) > 1:
            raise ValueError(
                f"duplicate_interactive_scene_entry:{self.scene.route_id.value}:{entry_id}"
            )
        return matches[0] if matches else None

    def to_dict(self) -> dict[str, object]:
        return {
            "scene": self.scene.to_dict(),
            "commands": [descriptor.to_dict() for descriptor in self.commands],
        }


RouteEntryAdapter: TypeAlias = Callable[
    [object, str],
    SteamDemoSubScreenInteractionProtocol,
]


@dataclass(frozen=True)
class _RouteActionAdapter:
    controller_type: type[object]
    activate: RouteEntryAdapter


class SteamDemoSceneActionDispatcher:
    """Scene上の共通Commandを現在RouteのController操作へ変換する。"""

    def __init__(
        self,
        runtime: SteamDemoScreenRuntime,
        scene_registry: SteamDemoSceneBuilderRegistry,
        *,
        adapters: Mapping[SteamDemoRouteId, _RouteActionAdapter] | None = None,
    ) -> None:
        self._runtime = runtime
        self._scene_registry = scene_registry
        source = self._default_adapters() if adapters is None else adapters
        self._adapters = dict(source)
        self._validate_adapters()

    @property
    def runtime(self) -> SteamDemoScreenRuntime:
        return self._runtime

    def registered_routes(self) -> tuple[SteamDemoRouteId, ...]:
        return tuple(self._adapters.keys())

    def current_scene(self) -> SteamDemoInteractiveScene:
        frame = self._runtime.current_frame()
        scene = self._scene_registry.build_frame(frame)
        commands = self._command_descriptors(scene)
        return SteamDemoInteractiveScene(scene=scene, commands=commands)

    def dispatch(self, command: SteamDemoUiCommand) -> SteamDemoRuntimeResult:
        frame = self._runtime.current_frame()
        if command.expected_route_id != frame.route_id:
            return self._runtime.reject_current_action(
                "stale_scene_route",
                logs=(
                    "scene_action_rejected:stale_scene_route:"
                    f"expected={command.expected_route_id.value}:actual={frame.route_id.value}",
                ),
            )

        if command.kind == SteamDemoUiCommandKind.INPUT_ACTION:
            if command.input_action is None:
                return self._runtime.reject_current_action("input_action_missing")
            return self._runtime.handle_input(command.input_action)

        if command.entry_id is None:
            return self._runtime.reject_current_action("entry_id_missing")

        try:
            interactive_scene = self.current_scene()
            descriptor = interactive_scene.command_for_entry(command.entry_id)
        except (TypeError, ValueError) as exc:
            return self._runtime.reject_current_action(
                "scene_command_resolution_failed",
                logs=(
                    "scene_action_rejected:scene_command_resolution_failed:"
                    f"{frame.route_id.value}:{exc}",
                ),
            )
        if descriptor is None:
            return self._runtime.reject_current_action(
                "entry_not_actionable",
                logs=(
                    f"scene_action_rejected:entry_not_actionable:"
                    f"{frame.route_id.value}:{command.entry_id}",
                ),
            )
        if not descriptor.is_enabled:
            return self._runtime.reject_current_action(
                "entry_disabled",
                logs=(
                    f"scene_action_rejected:entry_disabled:"
                    f"{frame.route_id.value}:{command.entry_id}",
                ),
            )

        if frame.route_id == SteamDemoRouteId.TOP_MENU:
            return self._runtime.activate_top_action(command.entry_id)
        return self._activate_subroute_entry(frame.route_id, command.entry_id)

    def activate_entry(
        self,
        expected_route_id: SteamDemoRouteId,
        entry_id: str,
    ) -> SteamDemoRuntimeResult:
        return self.dispatch(
            SteamDemoUiCommand.activate_entry(expected_route_id, entry_id)
        )

    def handle_input(
        self,
        expected_route_id: SteamDemoRouteId,
        action: MenuInputAction,
    ) -> SteamDemoRuntimeResult:
        return self.dispatch(SteamDemoUiCommand.input(expected_route_id, action))

    def _activate_subroute_entry(
        self,
        route_id: SteamDemoRouteId,
        entry_id: str,
    ) -> SteamDemoRuntimeResult:
        active_screen = self._runtime.active_screen
        if active_screen is None:
            return self._runtime.reject_current_action("active_screen_missing")
        adapter = self._adapters.get(route_id)
        if adapter is None:
            return self._runtime.reject_current_action(
                "route_action_adapter_missing",
                logs=(f"scene_action_rejected:adapter_missing:{route_id.value}",),
            )
        controller = active_screen.controller
        if not isinstance(controller, adapter.controller_type):
            return self._runtime.reject_current_action(
                "route_controller_type_mismatch",
                logs=(
                    "scene_action_rejected:controller_type_mismatch:"
                    f"{route_id.value}:expected={adapter.controller_type.__name__}:"
                    f"actual={type(controller).__name__}",
                ),
            )
        try:
            interaction = adapter.activate(controller, entry_id)
        except (TypeError, ValueError) as exc:
            return self._runtime.reject_current_action(
                "controller_action_failed",
                logs=(
                    f"scene_action_rejected:controller_action_failed:"
                    f"{route_id.value}:{entry_id}:{exc}",
                ),
            )
        return self._runtime.apply_subscreen_interaction(interaction)

    @staticmethod
    def _command_descriptors(
        scene: SteamDemoSceneModel,
    ) -> tuple[SteamDemoUiCommandDescriptor, ...]:
        descriptors: list[SteamDemoUiCommandDescriptor] = []
        if scene.route_id == SteamDemoRouteId.INN:
            can_stay = next(
                (
                    bool(field.value)
                    for field in scene.status
                    if field.key == "can_stay"
                ),
                False,
            )
            descriptors.append(
                SteamDemoUiCommandDescriptor(
                    command=SteamDemoUiCommand.activate_entry(
                        scene.route_id,
                        InnScreenController.STAY_ACTION_ID,
                    ),
                    section_id="actions",
                    label="宿泊する",
                    is_enabled=can_stay,
                    is_selected=True,
                )
            )
            return tuple(descriptors)

        actionable_sections = None
        if scene.route_id == SteamDemoRouteId.NPC_DIALOGUE:
            actionable_sections = {"npcs", "choices"}

        for section in scene.sections:
            if actionable_sections is not None and section.section_id not in actionable_sections:
                continue
            for entry in section.entries:
                descriptors.append(
                    SteamDemoUiCommandDescriptor(
                        command=SteamDemoUiCommand.activate_entry(
                            scene.route_id,
                            entry.entry_id,
                        ),
                        section_id=section.section_id,
                        label=entry.label,
                        is_enabled=entry.is_enabled,
                        is_selected=entry.is_selected,
                        is_recommended=entry.is_recommended,
                    )
                )
        entry_ids = [descriptor.command.entry_id for descriptor in descriptors]
        if len(entry_ids) != len(set(entry_ids)):
            raise ValueError(
                f"duplicate_actionable_entry_id:{scene.route_id.value}"
            )
        return tuple(descriptors)

    @staticmethod
    def _default_adapters() -> Mapping[SteamDemoRouteId, _RouteActionAdapter]:
        return {
            SteamDemoRouteId.USE_ITEM: _RouteActionAdapter(
                ItemUseScreenController,
                SteamDemoSceneActionDispatcher._activate_item_use,
            ),
            SteamDemoRouteId.EQUIPMENT: _RouteActionAdapter(
                EquipmentScreenController,
                SteamDemoSceneActionDispatcher._activate_equipment,
            ),
            SteamDemoRouteId.SHOP: _RouteActionAdapter(
                ShopScreenController,
                lambda controller, entry_id: controller.activate_item(entry_id),
            ),
            SteamDemoRouteId.EQUIPMENT_UPGRADE: _RouteActionAdapter(
                EquipmentUpgradeScreenController,
                lambda controller, entry_id: controller.activate_equipment(entry_id),
            ),
            SteamDemoRouteId.EQUIPMENT_SALVAGE: _RouteActionAdapter(
                EquipmentSalvageScreenController,
                lambda controller, entry_id: controller.activate_equipment(entry_id),
            ),
            SteamDemoRouteId.CRAFTING: _RouteActionAdapter(
                CraftingScreenController,
                lambda controller, entry_id: controller.activate_recipe(entry_id),
            ),
            SteamDemoRouteId.INN: _RouteActionAdapter(
                InnScreenController,
                lambda controller, entry_id: controller.activate_stay(entry_id),
            ),
            SteamDemoRouteId.QUEST_BOARD: _RouteActionAdapter(
                QuestBoardScreenController,
                lambda controller, entry_id: controller.activate_quest(entry_id),
            ),
            SteamDemoRouteId.TRAVEL: _RouteActionAdapter(
                TravelScreenController,
                lambda controller, entry_id: controller.activate_destination(entry_id),
            ),
            SteamDemoRouteId.NPC_DIALOGUE: _RouteActionAdapter(
                NpcDialogueScreenController,
                SteamDemoSceneActionDispatcher._activate_npc_dialogue,
            ),
            SteamDemoRouteId.GATHERING: _RouteActionAdapter(
                GatheringScreenController,
                lambda controller, entry_id: controller.activate_node(entry_id),
            ),
            SteamDemoRouteId.TREASURE: _RouteActionAdapter(
                TreasureScreenController,
                lambda controller, entry_id: controller.activate_node(entry_id),
            ),
            SteamDemoRouteId.FIELD_EVENT: _RouteActionAdapter(
                FieldEventScreenController,
                SteamDemoSceneActionDispatcher._activate_field_event,
            ),
        }

    def _validate_adapters(self) -> None:
        # Base Dispatcherは自分が提供する既定Adapter集合だけを契約として検証する。
        # 新しいRouteは拡張Dispatcher側で追加できるよう、Route Enum全体へ依存しない。
        expected = set(self._default_adapters())
        actual = set(self._adapters)
        missing = sorted(route.value for route in expected - actual)
        extra = sorted(route.value for route in actual - expected)
        if missing or extra:
            raise ValueError(
                "invalid_scene_action_adapter_registry:"
                f"missing={','.join(missing) or 'none'}:"
                f"extra={','.join(extra) or 'none'}"
            )

    @staticmethod
    def _activate_item_use(
        controller: ItemUseScreenController,
        entry_id: str,
    ) -> SteamDemoSubScreenInteractionProtocol:
        view = controller.current_view()
        if view.mode == ItemUseScreenMode.ITEM_LIST:
            return controller.activate_item(entry_id)
        return controller.activate_target(entry_id)

    @staticmethod
    def _activate_equipment(
        controller: EquipmentScreenController,
        entry_id: str,
    ) -> SteamDemoSubScreenInteractionProtocol:
        view = controller.current_view()
        if view.mode == EquipmentScreenMode.MEMBER_LIST:
            return controller.activate_member(entry_id)
        if view.mode == EquipmentScreenMode.SLOT_LIST:
            return controller.activate_slot(entry_id)
        return controller.activate_equipment(entry_id)

    @staticmethod
    def _activate_npc_dialogue(
        controller: NpcDialogueScreenController,
        entry_id: str,
    ) -> SteamDemoSubScreenInteractionProtocol:
        view = controller.current_view()
        if view.mode == NpcDialogueScreenMode.NPC_LIST:
            return controller.activate_npc(entry_id)
        return controller.activate_choice(entry_id)

    @staticmethod
    def _activate_field_event(
        controller: FieldEventScreenController,
        entry_id: str,
    ) -> SteamDemoSubScreenInteractionProtocol:
        view = controller.current_view()
        if view.mode == FieldEventScreenMode.EVENT_LIST:
            return controller.activate_event(entry_id)
        return controller.activate_choice(entry_id)
