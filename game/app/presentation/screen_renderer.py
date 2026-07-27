from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, TypeAlias

from game.app.presentation.economy_facility_screen import (
    CraftingScreenViewModel,
    InnScreenViewModel,
    ShopScreenViewModel,
)
from game.app.presentation.equipment_workshop_screen import (
    EquipmentSalvageScreenViewModel,
    EquipmentUpgradeScreenViewModel,
)
from game.app.presentation.gathering_treasure_screen import (
    GatheringScreenViewModel,
    TreasureScreenViewModel,
)
from game.app.presentation.item_equipment_screen import (
    EquipmentScreenMode,
    EquipmentScreenViewModel,
    ItemUseScreenMode,
    ItemUseScreenViewModel,
)
from game.app.presentation.menu_view_model import (
    MenuSelectionState,
    SteamDemoMenuViewModel,
)
from game.app.presentation.npc_field_event_screen import (
    FieldEventScreenMode,
    FieldEventScreenViewModel,
    NpcDialogueScreenMode,
    NpcDialogueScreenViewModel,
)
from game.app.presentation.quest_travel_screen import (
    QuestBoardScreenViewModel,
    TravelScreenViewModel,
)
from game.app.presentation.screen_router import SteamDemoRouteId
from game.app.presentation.screen_runtime import SteamDemoRuntimeFrame


SceneScalar: TypeAlias = str | int | bool | None
SceneBuilder: TypeAlias = Callable[[object], "SteamDemoSceneModel"]


@dataclass(frozen=True)
class SceneField:
    key: str
    label: str
    value: SceneScalar

    def to_dict(self) -> dict[str, SceneScalar]:
        return {
            "key": self.key,
            "label": self.label,
            "value": self.value,
        }


@dataclass(frozen=True)
class SceneEntry:
    entry_id: str
    label: str
    description: str | None = None
    fields: tuple[SceneField, ...] = tuple()
    is_enabled: bool = True
    is_selected: bool = False
    is_recommended: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "entry_id": self.entry_id,
            "label": self.label,
            "description": self.description,
            "fields": [field.to_dict() for field in self.fields],
            "is_enabled": self.is_enabled,
            "is_selected": self.is_selected,
            "is_recommended": self.is_recommended,
        }


@dataclass(frozen=True)
class SceneSection:
    section_id: str
    title: str
    entries: tuple[SceneEntry, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "section_id": self.section_id,
            "title": self.title,
            "entries": [entry.to_dict() for entry in self.entries],
        }


@dataclass(frozen=True)
class SceneActionHint:
    action_id: str
    keyboard_label: str | None
    gamepad_label: str | None

    def to_dict(self) -> dict[str, SceneScalar]:
        return {
            "action_id": self.action_id,
            "keyboard_label": self.keyboard_label,
            "gamepad_label": self.gamepad_label,
        }


@dataclass(frozen=True)
class SteamDemoSceneModel:
    route_id: SteamDemoRouteId
    title: str
    subtitle: str | None = None
    status: tuple[SceneField, ...] = tuple()
    sections: tuple[SceneSection, ...] = tuple()
    action_hints: tuple[SceneActionHint, ...] = tuple()
    is_completed: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "route_id": self.route_id.value,
            "title": self.title,
            "subtitle": self.subtitle,
            "status": [field.to_dict() for field in self.status],
            "sections": [section.to_dict() for section in self.sections],
            "action_hints": [hint.to_dict() for hint in self.action_hints],
            "is_completed": self.is_completed,
        }


_EXPECTED_VIEW_TYPES: Mapping[SteamDemoRouteId, type[object]] = {
    SteamDemoRouteId.TOP_MENU: SteamDemoMenuViewModel,
    SteamDemoRouteId.USE_ITEM: ItemUseScreenViewModel,
    SteamDemoRouteId.EQUIPMENT: EquipmentScreenViewModel,
    SteamDemoRouteId.SHOP: ShopScreenViewModel,
    SteamDemoRouteId.EQUIPMENT_UPGRADE: EquipmentUpgradeScreenViewModel,
    SteamDemoRouteId.EQUIPMENT_SALVAGE: EquipmentSalvageScreenViewModel,
    SteamDemoRouteId.CRAFTING: CraftingScreenViewModel,
    SteamDemoRouteId.INN: InnScreenViewModel,
    SteamDemoRouteId.QUEST_BOARD: QuestBoardScreenViewModel,
    SteamDemoRouteId.TRAVEL: TravelScreenViewModel,
    SteamDemoRouteId.NPC_DIALOGUE: NpcDialogueScreenViewModel,
    SteamDemoRouteId.GATHERING: GatheringScreenViewModel,
    SteamDemoRouteId.TREASURE: TreasureScreenViewModel,
    SteamDemoRouteId.FIELD_EVENT: FieldEventScreenViewModel,
}


class SteamDemoSceneBuilderRegistry:
    """RouteとViewModel型を検証し、描画方式に依存しないScene Modelへ変換する。"""

    def __init__(
        self,
        builders: Mapping[SteamDemoRouteId, SceneBuilder] | None = None,
    ) -> None:
        source = self._default_builders() if builders is None else builders
        self._builders = dict(source)
        self._validate_registry()

    def registered_routes(self) -> tuple[SteamDemoRouteId, ...]:
        return tuple(self._builders.keys())

    def build_frame(self, frame: SteamDemoRuntimeFrame) -> SteamDemoSceneModel:
        return self.build(frame.route_id, frame.view)

    def build(self, route_id: SteamDemoRouteId, view: object) -> SteamDemoSceneModel:
        expected_type = _EXPECTED_VIEW_TYPES.get(route_id)
        if expected_type is None:
            raise ValueError(f"scene_view_type_not_registered:{route_id.value}")
        if not isinstance(view, expected_type):
            raise TypeError(
                "scene_view_type_mismatch:"
                f"{route_id.value}:expected={expected_type.__name__}:"
                f"actual={type(view).__name__}"
            )
        builder = self._builders.get(route_id)
        if builder is None:
            raise ValueError(f"scene_builder_not_registered:{route_id.value}")
        scene = builder(view)
        if scene.route_id != route_id:
            raise ValueError(
                "scene_builder_route_mismatch:"
                f"expected={route_id.value}:actual={scene.route_id.value}"
            )
        return scene

    def _default_builders(self) -> Mapping[SteamDemoRouteId, SceneBuilder]:
        return {
            SteamDemoRouteId.TOP_MENU: self._build_top_menu,
            SteamDemoRouteId.USE_ITEM: self._build_item_use,
            SteamDemoRouteId.EQUIPMENT: self._build_equipment,
            SteamDemoRouteId.SHOP: self._build_shop,
            SteamDemoRouteId.EQUIPMENT_UPGRADE: self._build_equipment_upgrade,
            SteamDemoRouteId.EQUIPMENT_SALVAGE: self._build_equipment_salvage,
            SteamDemoRouteId.CRAFTING: self._build_crafting,
            SteamDemoRouteId.INN: self._build_inn,
            SteamDemoRouteId.QUEST_BOARD: self._build_quest_board,
            SteamDemoRouteId.TRAVEL: self._build_travel,
            SteamDemoRouteId.NPC_DIALOGUE: self._build_npc_dialogue,
            SteamDemoRouteId.GATHERING: self._build_gathering,
            SteamDemoRouteId.TREASURE: self._build_treasure,
            SteamDemoRouteId.FIELD_EVENT: self._build_field_event,
        }

    def _validate_registry(self) -> None:
        expected = set(_EXPECTED_VIEW_TYPES)
        actual = set(self._builders)
        missing = sorted(route.value for route in expected - actual)
        extra = sorted(route.value for route in actual - expected)
        if missing or extra:
            raise ValueError(
                "invalid_scene_builder_registry:"
                f"missing={','.join(missing) or 'none'}:"
                f"extra={','.join(extra) or 'none'}"
            )

    @staticmethod
    def _field(key: str, value: SceneScalar, label: str | None = None) -> SceneField:
        return SceneField(key=key, label=label or key, value=value)

    @staticmethod
    def _selected(selection: MenuSelectionState, index: int) -> bool:
        return selection.selected_index == index

    @classmethod
    def _build_top_menu(cls, raw: object) -> SteamDemoSceneModel:
        view = cls._require(raw, SteamDemoMenuViewModel)
        entries = tuple(
            SceneEntry(
                entry_id=item.action_id,
                label=item.label,
                is_enabled=item.is_enabled,
                is_selected=cls._selected(view.selection, index),
                is_recommended=item.is_recommended,
            )
            for index, item in enumerate(view.items)
        )
        hints = tuple(
            SceneActionHint(
                action_id=hint.action.value,
                keyboard_label=hint.keyboard_label,
                gamepad_label=hint.gamepad_label,
            )
            for hint in view.input_hints
        )
        return SteamDemoSceneModel(
            route_id=SteamDemoRouteId.TOP_MENU,
            title=view.title,
            subtitle=view.objective_title,
            status=(
                cls._field("progress", view.progress_label, "進行"),
                cls._field("objective", view.objective_text, "現在目標"),
                cls._field("completed", view.is_completed, "完了"),
            ),
            sections=(SceneSection("actions", "アクション", entries),),
            action_hints=hints,
            is_completed=view.is_completed,
        )

    @classmethod
    def _build_quest_board(cls, raw: object) -> SteamDemoSceneModel:
        view = cls._require(raw, QuestBoardScreenViewModel)
        entries = tuple(
            SceneEntry(
                entry_id=entry.quest_id,
                label=entry.title,
                fields=(
                    cls._field("status", entry.status_label, "状態"),
                    cls._field("progress", entry.progress_label, "進行"),
                ),
                is_enabled=entry.can_accept,
                is_selected=cls._selected(view.selection, index),
            )
            for index, entry in enumerate(view.entries)
        )
        return SteamDemoSceneModel(
            route_id=SteamDemoRouteId.QUEST_BOARD,
            title=view.title,
            status=(
                cls._field("active_quests", view.active_quest_count, "進行中"),
                cls._field("max_active_quests", view.max_active_quests, "受注上限"),
            ),
            sections=(SceneSection("quests", "依頼一覧", entries),),
        )

    @classmethod
    def _build_travel(cls, raw: object) -> SteamDemoSceneModel:
        view = cls._require(raw, TravelScreenViewModel)
        entries = tuple(
            SceneEntry(
                entry_id=destination.location_id,
                label=destination.name,
                fields=(cls._field("location_type", destination.location_type, "種別"),),
                is_selected=cls._selected(view.selection, index),
            )
            for index, destination in enumerate(view.destinations)
        )
        return SteamDemoSceneModel(
            route_id=SteamDemoRouteId.TRAVEL,
            title=view.title,
            subtitle=view.current_location_name,
            status=(cls._field("current_location", view.current_location_id, "現在地"),),
            sections=(SceneSection("destinations", "移動先", entries),),
        )

    @classmethod
    def _build_npc_dialogue(cls, raw: object) -> SteamDemoSceneModel:
        view = cls._require(raw, NpcDialogueScreenViewModel)
        if view.mode == NpcDialogueScreenMode.NPC_LIST:
            entries = tuple(
                SceneEntry(
                    entry_id=npc.npc_id,
                    label=npc.npc_name,
                    fields=(cls._field("location", npc.location_id, "場所"),),
                    is_selected=cls._selected(view.selection, index),
                )
                for index, npc in enumerate(view.npcs)
            )
            return SteamDemoSceneModel(
                route_id=SteamDemoRouteId.NPC_DIALOGUE,
                title=view.title,
                sections=(SceneSection("npcs", "会話相手", entries),),
            )

        dialogue = view.dialogue
        if dialogue is None:
            raise ValueError("dialogue_view_missing_dialogue")
        line_entries = tuple(
            SceneEntry(
                entry_id=f"line.{index}",
                label=dialogue.speaker or dialogue.npc_name,
                description=line,
            )
            for index, line in enumerate(dialogue.lines)
        )
        choice_entries = tuple(
            SceneEntry(
                entry_id=choice.choice_id,
                label=choice.text,
                is_selected=cls._selected(view.selection, index),
            )
            for index, choice in enumerate(dialogue.choices)
        )
        sections = [SceneSection("dialogue", "会話", line_entries)]
        if choice_entries:
            sections.append(SceneSection("choices", "選択肢", choice_entries))
        return SteamDemoSceneModel(
            route_id=SteamDemoRouteId.NPC_DIALOGUE,
            title=view.title,
            status=(
                cls._field("npc_id", dialogue.npc_id, "NPC"),
                cls._field("entry_id", dialogue.entry_id, "会話ID"),
                cls._field("step_id", dialogue.step_id, "ステップ"),
                cls._field("completed", dialogue.completed, "完了"),
            ),
            sections=tuple(sections),
            is_completed=dialogue.completed,
        )

    @classmethod
    def _build_field_event(cls, raw: object) -> SteamDemoSceneModel:
        view = cls._require(raw, FieldEventScreenViewModel)
        if view.mode == FieldEventScreenMode.EVENT_LIST:
            entries = tuple(
                SceneEntry(
                    entry_id=event.event_id,
                    label=event.name,
                    description=event.description or None,
                    fields=(
                        cls._field("repeatable", event.repeatable, "繰り返し"),
                        cls._field("completed", event.is_completed, "完了"),
                        cls._field("reason", event.reason_code, "理由"),
                    ),
                    is_enabled=event.can_execute,
                    is_selected=cls._selected(view.selection, index),
                )
                for index, event in enumerate(view.events)
            )
            return SteamDemoSceneModel(
                route_id=SteamDemoRouteId.FIELD_EVENT,
                title=view.title,
                sections=(SceneSection("events", "イベント", entries),),
            )

        detail = view.detail
        if detail is None:
            raise ValueError("field_event_view_missing_detail")
        choices = tuple(
            SceneEntry(
                entry_id=choice.choice_id,
                label=choice.text,
                is_selected=cls._selected(view.selection, index),
            )
            for index, choice in enumerate(detail.choices)
        )
        return SteamDemoSceneModel(
            route_id=SteamDemoRouteId.FIELD_EVENT,
            title=detail.name,
            subtitle=detail.description or None,
            status=(
                cls._field("repeatable", detail.repeatable, "繰り返し"),
                cls._field("completed", detail.is_completed, "完了"),
                cls._field("reason", detail.reason_code, "理由"),
            ),
            sections=(SceneSection("choices", "選択肢", choices),),
            is_completed=detail.is_completed,
        )

    @classmethod
    def _build_gathering(cls, raw: object) -> SteamDemoSceneModel:
        view = cls._require(raw, GatheringScreenViewModel)
        entries = tuple(
            SceneEntry(
                entry_id=node.node_id,
                label=node.name,
                description=node.description or None,
                fields=(
                    cls._field("node_type", node.node_type, "種別"),
                    cls._field("gathered", node.is_gathered, "採取済み"),
                    cls._field("reason", node.reason_code, "理由"),
                    cls._field("respawn_rule", node.respawn_rule, "復活条件"),
                    cls._field("respawn_description", node.respawn_description, "復活説明"),
                ),
                is_enabled=node.can_gather,
                is_selected=cls._selected(view.selection, index),
            )
            for index, node in enumerate(view.nodes)
        )
        return SteamDemoSceneModel(
            route_id=SteamDemoRouteId.GATHERING,
            title=view.title,
            status=(cls._field("current_location", view.current_location_id, "現在地"),),
            sections=(SceneSection("nodes", "採取ポイント", entries),),
        )

    @classmethod
    def _build_treasure(cls, raw: object) -> SteamDemoSceneModel:
        view = cls._require(raw, TreasureScreenViewModel)
        entries = tuple(
            SceneEntry(
                entry_id=node.reward_node_id,
                label=node.name,
                description=node.description or None,
                fields=(
                    cls._field("node_type", node.node_type, "種別"),
                    cls._field("opened", node.is_opened, "開封済み"),
                    cls._field("one_time", node.one_time, "一度限り"),
                    cls._field("reason", node.reason_code, "理由"),
                    cls._field("required_flags", ",".join(node.required_flags) or "none", "必要フラグ"),
                    cls._field("required_facility", node.required_facility_id, "必要施設"),
                    cls._field("required_facility_level", node.required_facility_level, "必要施設Lv"),
                ),
                is_enabled=node.can_open,
                is_selected=cls._selected(view.selection, index),
            )
            for index, node in enumerate(view.nodes)
        )
        return SteamDemoSceneModel(
            route_id=SteamDemoRouteId.TREASURE,
            title=view.title,
            status=(cls._field("current_location", view.current_location_id, "現在地"),),
            sections=(SceneSection("rewards", "探索報酬", entries),),
        )

    @classmethod
    def _build_item_use(cls, raw: object) -> SteamDemoSceneModel:
        view = cls._require(raw, ItemUseScreenViewModel)
        if view.mode == ItemUseScreenMode.ITEM_LIST:
            entries = tuple(
                SceneEntry(
                    entry_id=item.item_id,
                    label=item.name,
                    description=item.description or None,
                    fields=(
                        cls._field("amount", item.amount, "所持数"),
                        cls._field("effect_type", item.effect_type, "効果"),
                        cls._field("effect_value", item.effect_value, "効果量"),
                        cls._field("target_scope", item.target_scope, "対象"),
                    ),
                    is_enabled=item.amount > 0,
                    is_selected=cls._selected(view.selection, index),
                )
                for index, item in enumerate(view.items)
            )
            return SteamDemoSceneModel(
                route_id=SteamDemoRouteId.USE_ITEM,
                title=view.title,
                sections=(SceneSection("items", "使用可能アイテム", entries),),
            )

        selected_item = view.selected_item
        if selected_item is None:
            raise ValueError("item_target_view_missing_selected_item")
        entries = tuple(
            SceneEntry(
                entry_id=target.member.character_id,
                label=target.member.character_id,
                fields=(
                    cls._field("hp", f"{target.member.current_hp}/{target.member.max_hp}", "HP"),
                    cls._field("sp", f"{target.member.current_sp}/{target.member.max_sp}", "SP"),
                    cls._field("alive", target.member.alive, "生存"),
                    cls._field("reason", target.reason_code, "理由"),
                ),
                is_enabled=target.can_use,
                is_selected=cls._selected(view.selection, index),
            )
            for index, target in enumerate(view.targets)
        )
        return SteamDemoSceneModel(
            route_id=SteamDemoRouteId.USE_ITEM,
            title=view.title,
            status=(
                cls._field("selected_item", selected_item.item_id, "選択アイテム"),
                cls._field("amount", selected_item.amount, "所持数"),
            ),
            sections=(SceneSection("targets", "使用対象", entries),),
        )

    @classmethod
    def _build_equipment(cls, raw: object) -> SteamDemoSceneModel:
        view = cls._require(raw, EquipmentScreenViewModel)
        if view.mode == EquipmentScreenMode.MEMBER_LIST:
            entries = tuple(
                SceneEntry(
                    entry_id=member.character_id,
                    label=f"{member.character_id} Lv.{member.level}",
                    fields=(
                        cls._field("hp", f"{member.current_hp}/{member.max_hp}", "HP"),
                        cls._field("sp", f"{member.current_sp}/{member.max_sp}", "SP"),
                        cls._field("atk", member.atk, "ATK"),
                        cls._field("defense", member.defense, "DEF"),
                        cls._field("spd", member.spd, "SPD"),
                    ),
                    is_selected=cls._selected(view.selection, index),
                )
                for index, member in enumerate(view.members)
            )
            return SteamDemoSceneModel(
                route_id=SteamDemoRouteId.EQUIPMENT,
                title=view.title,
                sections=(SceneSection("members", "メンバー", entries),),
            )

        if view.mode == EquipmentScreenMode.SLOT_LIST:
            entries = tuple(
                SceneEntry(
                    entry_id=slot.slot_type,
                    label=slot.slot_type,
                    fields=(
                        cls._field("equipment_id", slot.current_equipment_id, "装備ID"),
                        cls._field("equipment_name", slot.current_equipment_name or "未装備", "現在装備"),
                    ),
                    is_selected=cls._selected(view.selection, index),
                )
                for index, slot in enumerate(view.slots)
            )
            member_id = view.selected_member.character_id if view.selected_member else None
            return SteamDemoSceneModel(
                route_id=SteamDemoRouteId.EQUIPMENT,
                title=view.title,
                status=(cls._field("selected_member", member_id, "メンバー"),),
                sections=(SceneSection("slots", "装備スロット", entries),),
            )

        entries = tuple(
            SceneEntry(
                entry_id=option.equipment_id,
                label=option.name,
                description=option.description or None,
                fields=(
                    cls._field("owned", option.owned, "所持"),
                    cls._field("available", option.available, "利用可"),
                    cls._field("current", option.is_current, "現在装備"),
                    cls._field("upgrade_level", option.upgrade_level, "強化"),
                    cls._field("hp", option.hp_bonus, "HP補正"),
                    cls._field("sp", option.sp_bonus, "SP補正"),
                    cls._field("atk", option.atk_bonus, "ATK補正"),
                    cls._field("defense", option.defense_bonus, "DEF補正"),
                    cls._field("spd", option.spd_bonus, "SPD補正"),
                    cls._field("passives", ",".join(option.passive_descriptions) or "none", "パッシブ"),
                ),
                is_enabled=option.can_equip,
                is_selected=cls._selected(view.selection, index),
            )
            for index, option in enumerate(view.equipment_options)
        )
        member_id = view.selected_member.character_id if view.selected_member else None
        slot_type = view.selected_slot.slot_type if view.selected_slot else None
        return SteamDemoSceneModel(
            route_id=SteamDemoRouteId.EQUIPMENT,
            title=view.title,
            status=(
                cls._field("selected_member", member_id, "メンバー"),
                cls._field("selected_slot", slot_type, "スロット"),
            ),
            sections=(SceneSection("equipment", "装備候補", entries),),
        )

    @classmethod
    def _build_shop(cls, raw: object) -> SteamDemoSceneModel:
        view = cls._require(raw, ShopScreenViewModel)
        summary = view.summary
        entries = tuple(
            SceneEntry(
                entry_id=item.item_id,
                label=item.name,
                description=item.description or None,
                fields=(
                    cls._field("price", item.price, "価格"),
                    cls._field("stock_type", item.stock_type, "在庫種別"),
                    cls._field("owned", item.owned, "所持"),
                    cls._field("reason", item.reason_code, "理由"),
                ),
                is_enabled=item.can_purchase,
                is_selected=cls._selected(view.selection, index),
            )
            for index, item in enumerate(summary.items)
        )
        return SteamDemoSceneModel(
            route_id=SteamDemoRouteId.SHOP,
            title=view.title,
            subtitle=summary.description or None,
            status=(
                cls._field("shop_id", summary.shop_id, "ショップID"),
                cls._field("facility_level", summary.facility_level, "施設Lv"),
                cls._field("gold", summary.gold, "所持金"),
                cls._field("success", summary.success, "利用可"),
                cls._field("code", summary.code, "状態"),
            ),
            sections=(SceneSection("items", "商品", entries),),
        )

    @classmethod
    def _build_equipment_upgrade(cls, raw: object) -> SteamDemoSceneModel:
        view = cls._require(raw, EquipmentUpgradeScreenViewModel)
        entries = tuple(
            SceneEntry(
                entry_id=option.equipment_id,
                label=option.name,
                description=option.description or None,
                fields=(
                    cls._field("owned", option.owned, "所持"),
                    cls._field("current_level", option.current_level, "現在段階"),
                    cls._field("max_level", option.max_level, "最大段階"),
                    cls._field("next_level", option.next_level, "次段階"),
                    cls._field("required_workshop_level", option.required_workshop_level, "必要工房Lv"),
                    cls._field(
                        "materials",
                        ",".join(
                            f"{material.name}:{material.owned}/{material.required}"
                            for material in option.required_materials
                        ) or "none",
                        "必要素材",
                    ),
                    cls._field(
                        "stat_bonus",
                        ",".join(f"{key}+{value}" for key, value in option.stat_bonus) or "none",
                        "次段階補正",
                    ),
                    cls._field("reason", option.reason_code, "理由"),
                ),
                is_enabled=option.can_upgrade,
                is_selected=cls._selected(view.selection, index),
            )
            for index, option in enumerate(view.options)
        )
        return SteamDemoSceneModel(
            route_id=SteamDemoRouteId.EQUIPMENT_UPGRADE,
            title=view.title,
            status=(cls._field("workshop_level", view.workshop_level, "工房Lv"),),
            sections=(SceneSection("equipment", "強化候補", entries),),
        )

    @classmethod
    def _build_equipment_salvage(cls, raw: object) -> SteamDemoSceneModel:
        view = cls._require(raw, EquipmentSalvageScreenViewModel)
        entries = tuple(
            SceneEntry(
                entry_id=option.equipment_id,
                label=option.name,
                description=option.description or None,
                fields=(
                    cls._field("owned", option.owned, "所持"),
                    cls._field("equipped", option.equipped_count, "装備中"),
                    cls._field("available", option.available, "分解可能数"),
                    cls._field("upgrade_level", option.upgrade_level, "強化"),
                    cls._field("required_workshop_level", option.required_workshop_level, "必要工房Lv"),
                    cls._field(
                        "returns",
                        ",".join(f"{reward.name}x{reward.quantity}" for reward in option.returns) or "none",
                        "返却素材",
                    ),
                    cls._field("reason", option.reason_code, "理由"),
                ),
                is_enabled=option.can_salvage,
                is_selected=cls._selected(view.selection, index),
            )
            for index, option in enumerate(view.options)
        )
        return SteamDemoSceneModel(
            route_id=SteamDemoRouteId.EQUIPMENT_SALVAGE,
            title=view.title,
            status=(cls._field("workshop_level", view.workshop_level, "工房Lv"),),
            sections=(SceneSection("equipment", "分解候補", entries),),
        )

    @classmethod
    def _build_crafting(cls, raw: object) -> SteamDemoSceneModel:
        view = cls._require(raw, CraftingScreenViewModel)
        entries = tuple(
            SceneEntry(
                entry_id=recipe.recipe_id,
                label=recipe.name,
                description=recipe.description or None,
                fields=(
                    cls._field("category", recipe.category, "カテゴリ"),
                    cls._field("tier", recipe.recipe_tier, "Tier"),
                    cls._field("required_workshop_level", recipe.required_workshop_level, "必要工房Lv"),
                    cls._field("discovered", recipe.is_discovered, "発見済み"),
                    cls._field("discovery_requirement_met", recipe.discovery_requirement_met, "発見条件"),
                    cls._field("unlocked", recipe.is_unlocked, "解放済み"),
                    cls._field(
                        "materials",
                        ",".join(
                            f"{material.name}:{material.owned}/{material.required}"
                            for material in recipe.materials
                        ) or "none",
                        "素材",
                    ),
                    cls._field(
                        "outputs",
                        ",".join(f"{output.name}x{output.quantity}" for output in recipe.outputs) or "none",
                        "生成物",
                    ),
                    cls._field("reason", recipe.reason_code, "理由"),
                ),
                is_enabled=recipe.can_craft,
                is_selected=cls._selected(view.selection, index),
            )
            for index, recipe in enumerate(view.summary.recipes)
        )
        return SteamDemoSceneModel(
            route_id=SteamDemoRouteId.CRAFTING,
            title=view.title,
            status=(cls._field("workshop_level", view.summary.workshop_level, "工房Lv"),),
            sections=(SceneSection("recipes", "レシピ", entries),),
        )

    @classmethod
    def _build_inn(cls, raw: object) -> SteamDemoSceneModel:
        view = cls._require(raw, InnScreenViewModel)
        summary = view.summary
        entries = tuple(
            SceneEntry(
                entry_id=member.character_id,
                label=member.character_id,
                fields=(
                    cls._field("alive", member.alive, "生存"),
                    cls._field("hp", f"{member.current_hp}/{member.max_hp}", "HP"),
                    cls._field("sp", f"{member.current_sp}/{member.max_sp}", "SP"),
                    cls._field(
                        "clear_on_rest",
                        ",".join(member.clear_on_rest_effect_ids) or "none",
                        "休息時解除",
                    ),
                ),
            )
            for member in summary.party_members
        )
        return SteamDemoSceneModel(
            route_id=SteamDemoRouteId.INN,
            title=view.title,
            subtitle=summary.description or None,
            status=(
                cls._field("inn_id", summary.inn_id, "宿屋ID"),
                cls._field("location", summary.location_id, "場所"),
                cls._field("price", summary.stay_price, "宿泊料金"),
                cls._field("gold", summary.gold, "所持金"),
                cls._field("can_stay", summary.can_stay, "宿泊可"),
                cls._field("revive", summary.revive_knocked_out_members, "復活"),
                cls._field("reason", summary.reason_code, "理由"),
            ),
            sections=(SceneSection("party", "パーティ状態", entries),),
        )

    @staticmethod
    def _require(value: object, expected_type: type[object]):
        if not isinstance(value, expected_type):
            raise TypeError(
                f"scene_builder_input_mismatch:expected={expected_type.__name__}:"
                f"actual={type(value).__name__}"
            )
        return value
