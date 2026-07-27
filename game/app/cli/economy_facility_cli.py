from __future__ import annotations

from game.app.application.playable_economy_facility_facade import (
    PlayableEconomyFacilityFacade,
)
from game.app.application.playable_slice import PlayableSliceApplication
from game.app.cli import run_game_slice as base_cli
from game.app.cli.screen_action_cli import activate_entry
from game.app.cli.screen_console_renderer import render_route_view
from game.app.presentation.economy_facility_screen import (
    CraftingScreenController,
    CraftingScreenViewModel,
    InnScreenController,
    InnScreenViewModel,
    ShopScreenController,
    ShopScreenViewModel,
)
from game.app.presentation.screen_action_dispatcher import (
    SteamDemoSceneActionDispatcher,
)
from game.app.presentation.screen_router import SteamDemoRouteId


def _print_shop_view(view: ShopScreenViewModel) -> None:
    render_route_view(SteamDemoRouteId.SHOP, view)


def run_shop_screen(app: PlayableSliceApplication) -> list[str]:
    return run_shop_controller(ShopScreenController(PlayableEconomyFacilityFacade(app)))


def run_shop_controller(
    controller: ShopScreenController,
    dispatcher: SteamDemoSceneActionDispatcher | None = None,
) -> list[str]:
    view = controller.current_view()
    _print_shop_view(view)
    if not view.summary.success:
        return [f"shop_failed:{view.summary.code}"]

    purchasable = [item for item in view.summary.items if item.can_purchase]
    if not purchasable:
        return ["shop_purchase_failed:no_purchasable_item"]

    choices = [("cancel", "購入しない")]
    choices.extend(
        (item.item_id, f"{item.name} {item.price}G 所持{item.owned}")
        for item in purchasable
    )
    selected = base_cli._choose(choices)
    if selected == "cancel":
        return ["shop_purchase_cancelled"]
    executed = activate_entry(
        route_id=SteamDemoRouteId.SHOP,
        entry_id=selected,
        controller_action=controller.activate_item,
        dispatcher=dispatcher,
    )
    return list(executed.logs)


def _print_crafting_view(view: CraftingScreenViewModel) -> None:
    render_route_view(SteamDemoRouteId.CRAFTING, view)


def run_crafting_screen(app: PlayableSliceApplication) -> list[str]:
    return run_crafting_controller(
        CraftingScreenController(PlayableEconomyFacilityFacade(app))
    )


def run_crafting_controller(
    controller: CraftingScreenController,
    dispatcher: SteamDemoSceneActionDispatcher | None = None,
) -> list[str]:
    view = controller.current_view()
    _print_crafting_view(view)

    craftable = [recipe for recipe in view.summary.recipes if recipe.can_craft]
    if not craftable:
        return ["craft_failed:no_craftable_recipe"]

    choices = [("cancel", "クラフトしない")]
    choices.extend(
        (recipe.recipe_id, f"{recipe.name} [{recipe.category}/{recipe.recipe_tier}]")
        for recipe in craftable
    )
    selected = base_cli._choose(choices)
    if selected == "cancel":
        return ["craft_cancelled"]
    executed = activate_entry(
        route_id=SteamDemoRouteId.CRAFTING,
        entry_id=selected,
        controller_action=controller.activate_recipe,
        dispatcher=dispatcher,
    )
    return list(executed.logs)


def _print_inn_view(view: InnScreenViewModel) -> None:
    render_route_view(SteamDemoRouteId.INN, view)


def run_inn_screen(app: PlayableSliceApplication) -> list[str]:
    return run_inn_controller(InnScreenController(PlayableEconomyFacilityFacade(app)))


def run_inn_controller(
    controller: InnScreenController,
    dispatcher: SteamDemoSceneActionDispatcher | None = None,
) -> list[str]:
    view = controller.current_view()
    _print_inn_view(view)
    if not view.summary.success:
        return [f"inn_failed:{view.summary.code}"]
    if not view.summary.can_stay:
        return [f"inn_stay_failed:{view.summary.reason_code}"]

    selected = base_cli._choose(
        [
            (InnScreenController.STAY_ACTION_ID, f"宿泊する {view.summary.stay_price}G"),
            ("cancel", "やめる"),
        ]
    )
    if selected == "cancel":
        return ["inn_cancelled"]
    executed = activate_entry(
        route_id=SteamDemoRouteId.INN,
        entry_id=selected,
        controller_action=controller.activate_stay,
        dispatcher=dispatcher,
    )
    return list(executed.logs)
