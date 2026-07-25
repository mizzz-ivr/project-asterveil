from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from game.app.application.playable_slice import BASE_INN_ID, BASE_SHOP_ID

if TYPE_CHECKING:
    from game.app.application.playable_slice import PlayableSliceApplication
    from game.save.domain.entities import PartyMemberState


@dataclass(frozen=True)
class ShopItemSummary:
    item_id: str
    name: str
    description: str
    price: int
    stock_type: str
    owned: int
    can_purchase: bool
    reason_code: str


@dataclass(frozen=True)
class ShopSummary:
    success: bool
    code: str
    shop_id: str
    name: str
    description: str
    facility_level: int
    gold: int
    items: tuple[ShopItemSummary, ...]


@dataclass(frozen=True)
class PurchaseExecutionResult:
    success: bool
    code: str
    shop_id: str
    item_id: str
    logs: tuple[str, ...] = tuple()


@dataclass(frozen=True)
class MaterialSummary:
    item_id: str
    name: str
    owned: int
    required: int
    is_sufficient: bool


@dataclass(frozen=True)
class CraftOutputSummary:
    item_id: str
    name: str
    quantity: int


@dataclass(frozen=True)
class CraftRecipeSummary:
    recipe_id: str
    name: str
    description: str
    category: str
    recipe_tier: str
    required_workshop_level: int
    current_workshop_level: int
    is_discovered: bool
    discovery_requirement_met: bool
    is_unlocked: bool
    can_craft: bool
    reason_code: str
    requires_miniboss_material: bool
    materials: tuple[MaterialSummary, ...]
    outputs: tuple[CraftOutputSummary, ...]


@dataclass(frozen=True)
class CraftingSummary:
    workshop_level: int
    recipes: tuple[CraftRecipeSummary, ...]


@dataclass(frozen=True)
class CraftExecutionResult:
    success: bool
    code: str
    recipe_id: str
    logs: tuple[str, ...] = tuple()


@dataclass(frozen=True)
class InnPartyMemberSummary:
    character_id: str
    alive: bool
    current_hp: int
    max_hp: int
    current_sp: int
    max_sp: int
    clear_on_rest_effect_ids: tuple[str, ...]


@dataclass(frozen=True)
class InnSummary:
    success: bool
    code: str
    inn_id: str
    name: str
    description: str
    location_id: str
    stay_price: int
    gold: int
    revive_knocked_out_members: bool
    can_stay: bool
    reason_code: str
    party_members: tuple[InnPartyMemberSummary, ...]


@dataclass(frozen=True)
class InnStayExecutionResult:
    success: bool
    code: str
    inn_id: str
    logs: tuple[str, ...] = tuple()


class PlayableEconomyFacilityFacade:
    """ショップ・クラフト・宿屋を型付き契約で公開するApplication境界。"""

    def __init__(self, playable: PlayableSliceApplication) -> None:
        self._playable = playable

    def shop_summary(self, shop_id: str = BASE_SHOP_ID) -> ShopSummary:
        shop = self._playable._shops.get(shop_id)
        if shop is None:
            return ShopSummary(
                success=False,
                code="shop_not_found",
                shop_id=shop_id,
                name=shop_id,
                description="",
                facility_level=0,
                gold=max(0, int(self._playable.inventory_state.get("gold", 0))),
                items=tuple(),
            )

        gold = max(0, int(self._playable.inventory_state.get("gold", 0)))
        inventory_items = self._playable.inventory_state.get("items", {})
        entries = self._playable._available_shop_entries(shop)
        return ShopSummary(
            success=True,
            code="ok",
            shop_id=shop.shop_id,
            name=shop.name,
            description=shop.description,
            facility_level=max(
                0,
                int(self._playable.facility_levels.get("facility.hub.general_store", 0)),
            ),
            gold=gold,
            items=tuple(
                ShopItemSummary(
                    item_id=entry.item_id,
                    name=self._display_name(entry.item_id),
                    description=entry.description or self._display_description(entry.item_id),
                    price=entry.price,
                    stock_type=entry.stock_type,
                    owned=max(0, int(inventory_items.get(entry.item_id, 0))),
                    can_purchase=entry.price >= 0 and gold >= entry.price,
                    reason_code=(
                        "purchasable"
                        if entry.price >= 0 and gold >= entry.price
                        else ("invalid_price" if entry.price < 0 else "insufficient_gold")
                    ),
                )
                for entry in entries
            ),
        )

    def purchase_item(
        self,
        item_id: str,
        *,
        shop_id: str = BASE_SHOP_ID,
    ) -> PurchaseExecutionResult:
        shop = self._playable._shops.get(shop_id)
        if shop is None:
            return self._purchase_rejection("shop_not_found", shop_id, item_id)

        sold_ids = {entry.item_id for entry in shop.entries}
        if item_id not in sold_ids:
            return self._purchase_rejection("item_not_sold", shop_id, item_id)

        available_ids = {
            entry.item_id for entry in self._playable._available_shop_entries(shop)
        }
        if item_id not in available_ids:
            return self._purchase_rejection("shop_stock_locked", shop_id, item_id)

        summary = self.shop_summary(shop_id)
        item = next((entry for entry in summary.items if entry.item_id == item_id), None)
        if item is None:
            return self._purchase_rejection("item_not_available", shop_id, item_id)
        if not item.can_purchase:
            return self._purchase_rejection(item.reason_code, shop_id, item_id)

        logs = tuple(self._playable.buy_item(item_id, quantity=1, shop_id=shop_id))
        success = any(line.startswith("purchase_succeeded:") for line in logs)
        return PurchaseExecutionResult(
            success=success,
            code="purchased" if success else self._log_code(logs, "purchase_failed"),
            shop_id=shop_id,
            item_id=item_id,
            logs=logs,
        )

    def crafting_summary(self) -> CraftingSummary:
        inventory_items = self._playable.inventory_state.get("items", {})
        statuses = self._playable._recipe_unlock_service.build_availability(
            recipes=self._playable._crafting_recipes,
            unlocked_recipe_ids=self._playable.unlocked_recipe_ids,
            world_flags=(
                self._playable.quest_session.world_flags
                if self._playable.quest_session is not None
                else set()
            ),
            completed_quest_ids=self._playable._completed_quest_ids(),
            current_location_id=self._playable.location_state.current_location_id,
            crafting_service=self._playable._crafting_service,
            inventory_items=inventory_items,
        )
        recipes: list[CraftRecipeSummary] = []
        workshop_level = self._playable.workshop_progress_state.level
        for status in statuses:
            recipe = self._playable._crafting_recipes[status.recipe_id]
            resolution = self._playable._crafting_service.resolve(
                recipe=recipe,
                inventory_items=inventory_items,
            )
            facility_unlocked = self._playable._is_recipe_unlocked_by_facility(
                recipe.recipe_id
            )
            workshop_unlocked = self._playable._is_recipe_unlocked_by_workshop_rank(
                recipe.recipe_id
            )
            discovery_met = self._playable._is_recipe_discovery_requirement_met(recipe)
            is_unlocked = (
                status.unlocked
                and facility_unlocked
                and workshop_unlocked
                and discovery_met
            )
            can_craft = is_unlocked and resolution.can_craft
            reason_code = self._craft_reason(
                status_unlocked=status.unlocked,
                status_lock_reason=status.lock_reason,
                facility_unlocked=facility_unlocked,
                workshop_unlocked=workshop_unlocked,
                discovery_met=discovery_met,
                materials_ready=resolution.can_craft,
            )
            recipes.append(
                CraftRecipeSummary(
                    recipe_id=recipe.recipe_id,
                    name=recipe.name,
                    description=recipe.description,
                    category=recipe.category,
                    recipe_tier=recipe.recipe_tier,
                    required_workshop_level=recipe.required_workshop_level,
                    current_workshop_level=workshop_level,
                    is_discovered=(
                        recipe.recipe_id in self._playable.discovered_recipe_ids
                    ),
                    discovery_requirement_met=discovery_met,
                    is_unlocked=is_unlocked,
                    can_craft=can_craft,
                    reason_code=reason_code,
                    requires_miniboss_material=self._playable._recipe_requires_miniboss_material(
                        recipe
                    ),
                    materials=tuple(
                        MaterialSummary(
                            item_id=req.item_id,
                            name=self._display_name(req.item_id),
                            owned=req.owned,
                            required=req.required,
                            is_sufficient=req.owned >= req.required,
                        )
                        for req in resolution.required_materials
                    ),
                    outputs=tuple(
                        CraftOutputSummary(
                            item_id=item_id,
                            name=self._display_name(item_id),
                            quantity=amount,
                        )
                        for item_id, amount in sorted(
                            resolution.aggregated_outputs.items()
                        )
                    ),
                )
            )
        return CraftingSummary(workshop_level=workshop_level, recipes=tuple(recipes))

    def craft_recipe(self, recipe_id: str) -> CraftExecutionResult:
        recipe = next(
            (
                entry
                for entry in self.crafting_summary().recipes
                if entry.recipe_id == recipe_id
            ),
            None,
        )
        if recipe is None:
            return self._craft_rejection("recipe_not_available", recipe_id)
        if not recipe.can_craft:
            return self._craft_rejection(recipe.reason_code, recipe_id)

        logs = tuple(self._playable.craft_recipe(recipe_id, count=1))
        success = any(line == f"crafted:{recipe_id}" for line in logs)
        return CraftExecutionResult(
            success=success,
            code="crafted" if success else self._log_code(logs, "craft_failed"),
            recipe_id=recipe_id,
            logs=logs,
        )

    def inn_summary(self, inn_id: str = BASE_INN_ID) -> InnSummary:
        inn = self._playable._inn_service.get_inn(inn_id)
        gold = max(0, int(self._playable.inventory_state.get("gold", 0)))
        if inn is None:
            return InnSummary(
                success=False,
                code="inn_not_found",
                inn_id=inn_id,
                name=inn_id,
                description="",
                location_id="",
                stay_price=0,
                gold=gold,
                revive_knocked_out_members=False,
                can_stay=False,
                reason_code="inn_not_found",
                party_members=tuple(),
            )

        party = tuple(self._inn_member_summary(member) for member in self._playable.party_members)
        if not party:
            reason_code = "invalid_party"
        elif any(
            member.max_hp <= 0 or member.max_sp < 0
            for member in self._playable.party_members
        ):
            reason_code = "invalid_party"
        elif gold < inn.stay_price:
            reason_code = "insufficient_gold"
        else:
            reason_code = "stay_available"
        return InnSummary(
            success=True,
            code="ok",
            inn_id=inn.inn_id,
            name=inn.name,
            description=inn.description,
            location_id=inn.location_id,
            stay_price=inn.stay_price,
            gold=gold,
            revive_knocked_out_members=inn.revive_knocked_out_members,
            can_stay=reason_code == "stay_available",
            reason_code=reason_code,
            party_members=party,
        )

    def stay_at_inn(self, inn_id: str = BASE_INN_ID) -> InnStayExecutionResult:
        summary = self.inn_summary(inn_id)
        if not summary.success or not summary.can_stay:
            return InnStayExecutionResult(
                success=False,
                code=summary.reason_code,
                inn_id=inn_id,
                logs=(f"inn_stay_rejected:{summary.reason_code}:{inn_id}",),
            )
        logs = tuple(self._playable.stay_at_inn(inn_id))
        success = any(line.startswith("inn_stay_succeeded:") for line in logs)
        return InnStayExecutionResult(
            success=success,
            code="stayed" if success else self._log_code(logs, "inn_stay_failed"),
            inn_id=inn_id,
            logs=logs,
        )

    def _inn_member_summary(self, member: PartyMemberState) -> InnPartyMemberSummary:
        final = self._playable._equipment_service.resolve_final_stats(member)
        clear_effect_ids = tuple(
            effect.effect_id
            for effect in member.active_effects
            if self._playable._status_effect_definitions.get(effect.effect_id, {}).get(
                "clear_on_rest",
                False,
            )
        )
        return InnPartyMemberSummary(
            character_id=member.character_id,
            alive=member.alive,
            current_hp=final["current_hp"],
            max_hp=final["max_hp"],
            current_sp=final["current_sp"],
            max_sp=final["max_sp"],
            clear_on_rest_effect_ids=clear_effect_ids,
        )

    def _display_name(self, item_id: str) -> str:
        item = self._playable._item_definitions.get(item_id)
        if item is not None:
            return str(item.get("name", item_id))
        equipment = self._playable._equipment_definitions.get(item_id)
        if equipment is not None:
            return equipment.name
        return item_id

    def _display_description(self, item_id: str) -> str:
        item = self._playable._item_definitions.get(item_id)
        if item is not None:
            return str(item.get("description", ""))
        equipment = self._playable._equipment_definitions.get(item_id)
        if equipment is not None:
            return equipment.description
        return ""

    @staticmethod
    def _craft_reason(
        *,
        status_unlocked: bool,
        status_lock_reason: str,
        facility_unlocked: bool,
        workshop_unlocked: bool,
        discovery_met: bool,
        materials_ready: bool,
    ) -> str:
        if not status_unlocked:
            return status_lock_reason or "recipe_locked"
        if not facility_unlocked or not workshop_unlocked:
            return "required_workshop_rank_missing"
        if not discovery_met:
            return "required_recipe_discovery_missing"
        if not materials_ready:
            return "missing_material"
        return "craftable"

    @staticmethod
    def _log_code(logs: tuple[str, ...], default: str) -> str:
        if not logs:
            return default
        parts = logs[0].split(":")
        return parts[1] if len(parts) > 1 else default

    @staticmethod
    def _purchase_rejection(
        code: str,
        shop_id: str,
        item_id: str,
    ) -> PurchaseExecutionResult:
        return PurchaseExecutionResult(
            success=False,
            code=code,
            shop_id=shop_id,
            item_id=item_id,
            logs=(f"purchase_rejected:{code}:{shop_id}:{item_id}",),
        )

    @staticmethod
    def _craft_rejection(code: str, recipe_id: str) -> CraftExecutionResult:
        return CraftExecutionResult(
            success=False,
            code=code,
            recipe_id=recipe_id,
            logs=(f"craft_rejected:{code}:{recipe_id}",),
        )
