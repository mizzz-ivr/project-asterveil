from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from game.app.application.demo_flow_service import DemoFlowService, SteamDemoApplication
from game.app.application.playable_slice import PlayableSliceApplication
from game.app.infrastructure.demo_flow_repository import DemoFlowMasterDataRepository
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
from game.app.presentation.screen_router import SteamDemoRouteId
from game.app.steam_demo_composition import (
    SteamDemoCompositionRoot,
    SteamDemoScreenFactory,
)


FLOW_ID = "demo.steam.ch01.core_loop"

EXPECTED_CONTROLLER_TYPES = {
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


class SteamDemoCompositionTestBase(unittest.TestCase):
    def build_apps(
        self,
        save_path: Path,
    ) -> tuple[PlayableSliceApplication, SteamDemoApplication]:
        playable = PlayableSliceApplication(
            master_root=Path("data/master"),
            save_file_path=save_path,
        )
        definitions = DemoFlowMasterDataRepository(Path("data/master")).load()
        demo = SteamDemoApplication(
            playable,
            DemoFlowService(definitions),
            FLOW_ID,
        )
        playable.new_game()
        return playable, demo


class SteamDemoScreenFactoryTests(SteamDemoCompositionTestBase):
    def test_factory_registers_all_subroutes_with_expected_controller_types(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            playable, _ = self.build_apps(Path(directory) / "save.json")
            factory = SteamDemoScreenFactory(playable)

            self.assertEqual(
                set(EXPECTED_CONTROLLER_TYPES),
                set(factory.registered_routes()),
            )
            for route_id, expected_type in EXPECTED_CONTROLLER_TYPES.items():
                route_screen = factory.create(route_id)
                self.assertEqual(route_id, route_screen.route_id)
                self.assertIsInstance(route_screen.controller, expected_type)

    def test_factory_creates_fresh_controller_for_each_route_open(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            playable, _ = self.build_apps(Path(directory) / "save.json")
            factory = SteamDemoScreenFactory(playable)

            first = factory.create(SteamDemoRouteId.NPC_DIALOGUE)
            second = factory.create(SteamDemoRouteId.NPC_DIALOGUE)

            self.assertIsNot(first.controller, second.controller)
            self.assertIsInstance(first.controller, NpcDialogueScreenController)
            self.assertIsInstance(second.controller, NpcDialogueScreenController)

    def test_factory_controllers_read_latest_shared_application_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            playable, _ = self.build_apps(Path(directory) / "save.json")
            factory = SteamDemoScreenFactory(playable)
            playable.inventory_state["gold"] = 123

            first = factory.create(SteamDemoRouteId.SHOP)
            self.assertIsInstance(first.controller, ShopScreenController)
            self.assertEqual(123, first.controller.current_view().summary.gold)

            playable.inventory_state["gold"] = 77
            second = factory.create(SteamDemoRouteId.SHOP)
            self.assertIsInstance(second.controller, ShopScreenController)
            self.assertEqual(77, second.controller.current_view().summary.gold)

    def test_factory_rejects_top_route_and_incomplete_registry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            playable, _ = self.build_apps(Path(directory) / "save.json")
            factory = SteamDemoScreenFactory(playable)

            with self.assertRaisesRegex(ValueError, "top_menu_is_not_subscreen"):
                factory.create(SteamDemoRouteId.TOP_MENU)
            with self.assertRaisesRegex(ValueError, "invalid_screen_builder_registry"):
                SteamDemoScreenFactory(playable, builders={})


class SteamDemoCompositionRootTests(SteamDemoCompositionTestBase):
    def test_composition_root_builds_top_screen_router_and_factory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            playable, demo = self.build_apps(Path(directory) / "save.json")

            composition = SteamDemoCompositionRoot.build(playable, demo)

            self.assertEqual(
                composition.top_screen.current_view(),
                composition.router.current_top_view(),
            )
            self.assertEqual(
                set(EXPECTED_CONTROLLER_TYPES),
                set(composition.screen_factory.registered_routes()),
            )
            self.assertEqual(
                (SteamDemoRouteId.TOP_MENU,),
                composition.router.state.route_stack,
            )

    def test_composition_root_builds_independent_session_objects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            playable, demo = self.build_apps(Path(directory) / "save.json")

            first = SteamDemoCompositionRoot.build(playable, demo)
            second = SteamDemoCompositionRoot.build(playable, demo)

            self.assertIsNot(first.top_screen, second.top_screen)
            self.assertIsNot(first.router, second.router)
            self.assertIsNot(first.screen_factory, second.screen_factory)


if __name__ == "__main__":
    unittest.main()
