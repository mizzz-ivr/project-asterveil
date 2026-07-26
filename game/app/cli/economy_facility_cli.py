from __future__ import annotations

from game.app.application.playable_economy_facility_facade import (
    PlayableEconomyFacilityFacade,
)
from game.app.application.playable_slice import PlayableSliceApplication
from game.app.cli import run_game_slice as base_cli
from game.app.presentation.economy_facility_screen import (
    CraftingScreenController,
    CraftingScreenViewModel,
    InnScreenController,
    InnScreenViewModel,
    ShopScreenController,
    ShopScreenViewModel,
)


def _print_shop_view(view: ShopScreenViewModel) -> None:
    summary = view.summary
    print(
        f"- shop:{summary.shop_id}:{summary.name}:facility_level={summary.facility_level}:"
        f"gold={summary.gold}:success={summary.success}:code={summary.code}"
    )
    if summary.description:
        print(f"- shop_description:{summary.shop_id}:{summary.description}")
    for item in summary.items:
        print(
            f"- shop_item:{item.item_id}:{item.name}:price={item.price}:"
            f"stock_type={item.stock_type}:owned={item.owned}:"
            f"can_purchase={item.can_purchase}:reason={item.reason_code}"
        )
        if item.description:
            print(f"- shop_item_description:{item.item_id}:{item.description}")


def run_shop_screen(app: PlayableSliceApplication) -> list[str]:
    return run_shop_controller(ShopScreenController(PlayableEconomyFacilityFacade(app)))


def run_shop_controller(controller: ShopScreenController) -> list[str]:
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
    return list(controller.activate_item(selected).logs)


def _print_crafting_view(view: CraftingScreenViewModel) -> None:
    print(
        f"- crafting:workshop_level={view.summary.workshop_level}:"
        f"recipes={len(view.summary.recipes)}"
    )
    for recipe in view.summary.recipes:
        print(
            f"- craft_recipe:{recipe.recipe_id}:{recipe.name}:category={recipe.category}:"
            f"tier={recipe.recipe_tier}:required_workshop_level={recipe.required_workshop_level}:"
            f"discovered={recipe.is_discovered}:discovery_requirement_met={recipe.discovery_requirement_met}:"
            f"unlocked={recipe.is_unlocked}:can_craft={recipe.can_craft}:"
            f"reason={recipe.reason_code}:requires_miniboss_material={recipe.requires_miniboss_material}"
        )
        if recipe.description:
            print(f"- craft_recipe_description:{recipe.recipe_id}:{recipe.description}")
        for material in recipe.materials:
            print(
                f"- craft_material:{recipe.recipe_id}:{material.item_id}:{material.name}:"
                f"owned={material.owned}:required={material.required}:"
                f"sufficient={material.is_sufficient}"
            )
        for output in recipe.outputs:
            print(
                f"- craft_output:{recipe.recipe_id}:{output.item_id}:{output.name}:"
                f"quantity={output.quantity}"
            )


def run_crafting_screen(app: PlayableSliceApplication) -> list[str]:
    return run_crafting_controller(
        CraftingScreenController(PlayableEconomyFacilityFacade(app))
    )


def run_crafting_controller(controller: CraftingScreenController) -> list[str]:
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
    return list(controller.activate_recipe(selected).logs)


def _print_inn_view(view: InnScreenViewModel) -> None:
    summary = view.summary
    print(
        f"- inn:{summary.inn_id}:{summary.name}:price={summary.stay_price}:"
        f"gold={summary.gold}:can_stay={summary.can_stay}:reason={summary.reason_code}:"
        f"revive={summary.revive_knocked_out_members}"
    )
    if summary.description:
        print(f"- inn_description:{summary.inn_id}:{summary.description}")
    for member in summary.party_members:
        print(
            f"- inn_party_member:{member.character_id}:alive={member.alive}:"
            f"hp={member.current_hp}/{member.max_hp}:sp={member.current_sp}/{member.max_sp}:"
            f"clear_on_rest={','.join(member.clear_on_rest_effect_ids) or 'none'}"
        )


def run_inn_screen(app: PlayableSliceApplication) -> list[str]:
    return run_inn_controller(InnScreenController(PlayableEconomyFacilityFacade(app)))


def run_inn_controller(controller: InnScreenController) -> list[str]:
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
    return list(controller.activate_stay(selected).logs)
