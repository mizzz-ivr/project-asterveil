from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, TypeAlias

from game.app.application.demo_flow_service import SteamDemoApplication
from game.app.application.playable_economy_facility_facade import (
    PlayableEconomyFacilityFacade,
)
from game.app.application.playable_equipment_workshop_facade import (
    PlayableEquipmentWorkshopFacade,
)
from game.app.application.playable_exploration_facade import PlayableExplorationFacade
from game.app.application.playable_interaction_facade import PlayableInteractionFacade
from game.app.application.playable_party_menu_facade import PlayablePartyMenuFacade
from game.app.application.playable_slice import PlayableSliceApplication
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
from game.app.presentation.item_equipment_screen import (
    EquipmentScreenController,
    ItemUseScreenController,
)
from game.app.presentation.npc_field_event_screen import (
    FieldEventScreenController,
    NpcDialogueScreenController,
)
from game.app.presentation.quest_travel_screen import (
    QuestBoardScreenController,
    TravelScreenController,
)
from game.app.presentation.screen_controller import SteamDemoScreenController
from game.app.presentation.screen_router import (
    SteamDemoRouteId,
    SteamDemoScreenRouter,
)
from game.app.presentation.screen_runtime import SteamDemoScreenRuntime


SteamDemoSubScreenController: TypeAlias = (
    ItemUseScreenController
    | EquipmentScreenController
    | ShopScreenController
    | EquipmentUpgradeScreenController
    | EquipmentSalvageScreenController
    | CraftingScreenController
    | InnScreenController
    | QuestBoardScreenController
    | TravelScreenController
    | NpcDialogueScreenController
    | GatheringScreenController
    | TreasureScreenController
    | FieldEventScreenController
)

ScreenBuilder: TypeAlias = Callable[[], SteamDemoSubScreenController]


_EXPECTED_CONTROLLER_TYPES: Mapping[
    SteamDemoRouteId,
    type[SteamDemoSubScreenController],
] = {
    SteamDemoRouteId.USE_ITEM: ItemUseScreenController,
    SteamDemoRouteId.EQUIPMENT: EquipmentScreenController,
    SteamDemoRouteId.SHOP: ShopScreenController,
    SteamDemoRouteId.EQUIPMENT_UPGRADE: EquipmentUpgradeScreenController,
    SteamDemoRouteId.EQUIPMENT_SALVAGE: EquipmentSalvageScreenController,
    SteamDemoRouteId.CRAFTING: CraftingScreenController,
    SteamDemoRouteId.INN: InnScreenController,
    SteamDemoRouteId.QUEST_BOARD: QuestBoardScreenController,
    SteamDemoRouteId.TRAVEL: TravelScreenController,
    SteamDemoRouteId.NPC_DIALOGUE: NpcDialogueScreenController,
    SteamDemoRouteId.GATHERING: GatheringScreenController,
    SteamDemoRouteId.TREASURE: TreasureScreenController,
    SteamDemoRouteId.FIELD_EVENT: FieldEventScreenController,
}


@dataclass(frozen=True)
class SteamDemoRouteScreen:
    route_id: SteamDemoRouteId
    controller: SteamDemoSubScreenController


class SteamDemoScreenFactory:
    """Route IDから、そのRoute専用の新しいControllerを生成する。"""

    def __init__(
        self,
        playable: PlayableSliceApplication,
        *,
        builders: Mapping[SteamDemoRouteId, ScreenBuilder] | None = None,
    ) -> None:
        self._playable = playable
        source_builders = self._default_builders() if builders is None else builders
        self._builders = dict(source_builders)
        self._validate_registry()

    def registered_routes(self) -> tuple[SteamDemoRouteId, ...]:
        return tuple(self._builders.keys())

    def create(self, route_id: SteamDemoRouteId) -> SteamDemoRouteScreen:
        if route_id == SteamDemoRouteId.TOP_MENU:
            raise ValueError("top_menu_is_not_subscreen")
        builder = self._builders.get(route_id)
        if builder is None:
            raise ValueError(f"screen_builder_not_registered:{route_id.value}")
        controller = builder()
        expected_type = _EXPECTED_CONTROLLER_TYPES.get(route_id)
        if expected_type is None:
            raise ValueError(f"expected_controller_not_registered:{route_id.value}")
        if not isinstance(controller, expected_type):
            raise TypeError(
                "screen_controller_type_mismatch:"
                f"{route_id.value}:expected={expected_type.__name__}:"
                f"actual={type(controller).__name__}"
            )
        return SteamDemoRouteScreen(route_id=route_id, controller=controller)

    def _default_builders(self) -> Mapping[SteamDemoRouteId, ScreenBuilder]:
        playable = self._playable
        return {
            SteamDemoRouteId.USE_ITEM: lambda: ItemUseScreenController(
                PlayablePartyMenuFacade(playable)
            ),
            SteamDemoRouteId.EQUIPMENT: lambda: EquipmentScreenController(
                PlayablePartyMenuFacade(playable)
            ),
            SteamDemoRouteId.SHOP: lambda: ShopScreenController(
                PlayableEconomyFacilityFacade(playable)
            ),
            SteamDemoRouteId.EQUIPMENT_UPGRADE: lambda: EquipmentUpgradeScreenController(
                PlayableEquipmentWorkshopFacade(playable)
            ),
            SteamDemoRouteId.EQUIPMENT_SALVAGE: lambda: EquipmentSalvageScreenController(
                PlayableEquipmentWorkshopFacade(playable)
            ),
            SteamDemoRouteId.CRAFTING: lambda: CraftingScreenController(
                PlayableEconomyFacilityFacade(playable)
            ),
            SteamDemoRouteId.INN: lambda: InnScreenController(
                PlayableEconomyFacilityFacade(playable)
            ),
            SteamDemoRouteId.QUEST_BOARD: lambda: QuestBoardScreenController(playable),
            SteamDemoRouteId.TRAVEL: lambda: TravelScreenController(playable),
            SteamDemoRouteId.NPC_DIALOGUE: lambda: NpcDialogueScreenController(
                PlayableInteractionFacade(playable)
            ),
            SteamDemoRouteId.GATHERING: lambda: GatheringScreenController(
                PlayableExplorationFacade(playable)
            ),
            SteamDemoRouteId.TREASURE: lambda: TreasureScreenController(
                PlayableExplorationFacade(playable)
            ),
            SteamDemoRouteId.FIELD_EVENT: lambda: FieldEventScreenController(
                PlayableInteractionFacade(playable)
            ),
        }

    def _validate_registry(self) -> None:
        expected_routes = set(_EXPECTED_CONTROLLER_TYPES)
        actual_routes = set(self._builders)
        missing_routes = sorted(route.value for route in expected_routes - actual_routes)
        extra_routes = sorted(route.value for route in actual_routes - expected_routes)
        if missing_routes or extra_routes:
            raise ValueError(
                "invalid_screen_builder_registry:"
                f"missing={','.join(missing_routes) or 'none'}:"
                f"extra={','.join(extra_routes) or 'none'}"
            )


@dataclass(frozen=True)
class SteamDemoSessionComposition:
    top_screen: SteamDemoScreenController
    router: SteamDemoScreenRouter
    screen_factory: SteamDemoScreenFactory
    runtime: SteamDemoScreenRuntime


class SteamDemoCompositionRoot:
    """Steamデモ1セッション分の具象依存を組み立てる唯一の入口。"""

    @staticmethod
    def build(
        playable: PlayableSliceApplication,
        demo: SteamDemoApplication,
    ) -> SteamDemoSessionComposition:
        top_screen = SteamDemoScreenController(playable, demo)
        router = SteamDemoScreenRouter(top_screen)
        screen_factory = SteamDemoScreenFactory(playable)
        runtime = SteamDemoScreenRuntime(router, screen_factory)
        return SteamDemoSessionComposition(
            top_screen=top_screen,
            router=router,
            screen_factory=screen_factory,
            runtime=runtime,
        )
