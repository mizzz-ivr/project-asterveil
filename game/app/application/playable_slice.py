from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from game.app.application.equipment_service import EquipmentPassiveDefinition, EquipmentService, VALID_SLOTS
from game.app.application.equipment_set_service import EquipmentSetService
from game.app.application.equipment_salvage_service import EquipmentSalvageService
from game.app.application.equipment_upgrade_service import EquipmentUpgradeService
from game.app.application.inn_service import InnService
from game.app.application.item_use_service import ItemUseService
from game.app.application.skill_learning_service import LearnableSkill, SkillLearningService
from game.app.application.dialogue_event_service import DialogueService, LocationEventService
from game.app.application.endgame_repeatable_order_service import EndgameRepeatableOrderService, EndgameRepeatableOrderState
from game.app.application.facility_progression_service import FacilityProgressContext, FacilityProgressService
from game.app.application.reward_services import RewardApplicationService
from game.app.application.workshop_progress_service import WorkshopProgressService, WorkshopProgressState
from game.app.application.workshop_special_chain_service import WorkshopSpecialChainService, WorkshopSpecialChainState
from game.app.application.workshop_story_service import WorkshopStoryService, WorkshopStoryState
from game.app.infrastructure.dialogue_event_repository import DialogueEventMasterDataRepository
from game.app.infrastructure.endgame_repeatable_order_repository import EndgameRepeatableOrderMasterDataRepository
from game.app.infrastructure.equipment_salvage_repository import EquipmentSalvageMasterDataRepository
from game.app.infrastructure.equipment_upgrade_repository import EquipmentUpgradeMasterDataRepository
from game.app.infrastructure.facility_master_data_repository import FacilityMasterDataRepository
from game.app.infrastructure.master_data_repository import AppMasterDataRepository
from game.app.infrastructure.workshop_order_repository import WorkshopOrderMasterDataRepository
from game.app.infrastructure.workshop_special_chain_repository import WorkshopSpecialChainMasterDataRepository
from game.app.infrastructure.workshop_story_repository import WorkshopStoryMasterDataRepository
from game.crafting.domain.entities import CraftingRecipeDefinition
from game.crafting.domain.services import CraftingService, RecipeDiscoveryService, RecipeUnlockService
from game.crafting.infrastructure.master_data_repository import CraftingMasterDataRepository
from game.gathering.domain.services import GatheringRespawnService, GatheringService
from game.gathering.infrastructure.master_data_repository import GatheringNodeMasterDataRepository
from game.location.application.travel_service import TravelService
from game.location.domain.entities import LocationState
from game.location.domain.field_event_service import FieldEventService
from game.location.domain.miniboss_service import MinibossService
from game.location.domain.treasure_services import TreasureService
from game.location.infrastructure.field_event_repository import FieldEventMasterDataRepository
from game.location.infrastructure.master_data_repository import LocationMasterDataRepository
from game.location.infrastructure.miniboss_repository import MinibossMasterDataRepository
from game.location.infrastructure.treasure_repository import TreasureMasterDataRepository
from game.quest.application.session import QuestSliceSession
from game.quest.cli.run_quest_slice import build_battle_executor
from game.quest.domain.entities import BattleResult, QuestBoardStatus, QuestState, QuestStatus
from game.quest.domain.services import QuestBoardService, QuestProgressService
from game.quest.infrastructure.master_data_repository import QuestMasterDataRepository
from game.save.application.session import SaveSliceApplicationService
from game.save.domain.entities import PartyActiveEffectState, PartyMemberState
from game.save.infrastructure.repository import JsonFileSaveRepository
from game.shop.domain.services import ShopService
from game.shop.infrastructure.master_data_repository import ShopMasterDataRepository


BASE_SHOP_ID = "shop.astel.general_store"
BASE_INN_ID = "inn.astel.seaside_inn"
HUB_LOCATION_ID = "location.town.astel"


@dataclass
class ActionItem:
    key: str
    label: str


class PlayableSliceApplication:
    def __init__(
        self,
        master_root: Path,
        save_file_path: Path,
        battle_executor: Callable[[str], BattleResult] | None = None,
    ) -> None:
        self._quest_repo = QuestMasterDataRepository(master_root)
        self._app_master_repo = AppMasterDataRepository(master_root)
        self._dialogue_event_repo = DialogueEventMasterDataRepository(master_root)
        self._endgame_order_repo = EndgameRepeatableOrderMasterDataRepository(master_root)
        self._equipment_salvage_repo = EquipmentSalvageMasterDataRepository(master_root)
        self._equipment_upgrade_repo = EquipmentUpgradeMasterDataRepository(master_root)
        self._facility_repo = FacilityMasterDataRepository(master_root)
        self._workshop_order_repo = WorkshopOrderMasterDataRepository(master_root)
        self._workshop_story_repo = WorkshopStoryMasterDataRepository(master_root)
        self._workshop_special_chain_repo = WorkshopSpecialChainMasterDataRepository(master_root)
        self._crafting_repo = CraftingMasterDataRepository(master_root)
        self._gathering_repo = GatheringNodeMasterDataRepository(master_root)
        self._treasure_repo = TreasureMasterDataRepository(master_root)
        self._field_event_repo = FieldEventMasterDataRepository(master_root)
        self._miniboss_repo = MinibossMasterDataRepository(master_root)
        self._save_repo = JsonFileSaveRepository(save_file_path)
        self._save_service = SaveSliceApplicationService()
        self._character_initial_skill_ids = self._app_master_repo.load_initial_skill_ids_by_character()
        raw_skill_learns = self._app_master_repo.load_skill_learns()
        self._skill_learning_service = SkillLearningService(
            learnable_by_character={
                character_id: tuple(
                    LearnableSkill(
                        skill_id=entry["skill_id"],
                        required_level=entry["required_level"],
                        learn_type=entry.get("learn_type", "auto"),
                        description=entry.get("description", ""),
                    )
                    for entry in entries
                )
                for character_id, entries in raw_skill_learns.items()
            },
            initial_skill_ids_by_character=self._character_initial_skill_ids,
        )
        self._reward_service = RewardApplicationService(skill_learning=self._skill_learning_service)
        self._item_use_service = ItemUseService()
        self._shop_repo = ShopMasterDataRepository(master_root)
        self._location_repo = LocationMasterDataRepository(master_root)
        self._battle_executor = battle_executor or build_battle_executor(master_root)
        self._item_definitions = self._app_master_repo.load_items()
        self._status_effect_definitions = self._app_master_repo.load_status_effects()
        self._equipment_definitions = self._app_master_repo.load_equipment()
        self._equipment_set_definitions = self._app_master_repo.load_equipment_sets(set(self._equipment_definitions))
        self._equipment_set_service = EquipmentSetService(self._equipment_set_definitions)
        self._equipment_upgrade_definitions = self._equipment_upgrade_repo.load(
            valid_equipment_ids=set(self._equipment_definitions),
            valid_item_ids=set(self._item_definitions),
        )
        self._equipment_salvage_definitions = self._equipment_salvage_repo.load(
            valid_equipment_ids=set(self._equipment_definitions),
            valid_item_ids=set(self._item_definitions),
        )
        self.equipment_upgrade_levels: dict[str, int] = {}
        self._equipment_upgrade_service = EquipmentUpgradeService(self._equipment_upgrade_definitions)
        self._equipment_salvage_service = EquipmentSalvageService(self._equipment_salvage_definitions)
        self._crafting_service = CraftingService()
        self._recipe_unlock_service = RecipeUnlockService()
        self._crafting_recipes = self._crafting_repo.load_recipes(
            valid_item_ids=set(self._item_definitions),
            valid_equipment_ids=set(self._equipment_definitions),
        )
        self._recipe_discovery_service = RecipeDiscoveryService(
            self._crafting_repo.load_recipe_discoveries(),
            valid_recipe_ids=set(self._crafting_recipes),
        )
        self._facility_progress_service = FacilityProgressService()
        self._facility_definitions = self._facility_repo.load_facilities()
        self._workshop_progress_service = WorkshopProgressService()
        self._workshop_order_definitions, self._workshop_rank_definitions = self._workshop_order_repo.load()
        self._workshop_npc_ids = self._crafting_repo.load_workshop_npc_ids()
        self._equipment_service = EquipmentService(
            self._equipment_definitions,
            upgrade_bonus_resolver=lambda equipment_id: self._equipment_upgrade_service.stat_bonus_for_equipment(
                equipment_id=equipment_id,
                equipment_upgrade_levels=self.equipment_upgrade_levels,
            ),
            upgrade_level_resolver=lambda equipment_id: self._equipment_upgrade_service.current_level(
                equipment_id, self.equipment_upgrade_levels
            ),
            set_stat_bonus_resolver=lambda equipped: self._equipment_set_service.compute_stat_bonus(equipped),
            set_passive_resolver=lambda equipped: self._resolve_set_passives(equipped),
        )
        self._shops = self._shop_repo.load_shops()
        self._shop_service = ShopService(self._shops, self._item_definitions)
        self._inns = self._app_master_repo.load_inns()
        self._inn_service = InnService(self._inns, self._equipment_service, self._status_effect_definitions)
        self._battle_rewards = self._app_master_repo.load_battle_rewards(set(self._item_definitions))
        raw_encounters = json.loads((master_root / "encounters.sample.json").read_text(encoding="utf-8"))
        encounter_ids = {str(entry.get("encounter_id", "")) for entry in raw_encounters if entry.get("encounter_id")}
        self._miniboss_service = MinibossService(
            self._miniboss_repo.load_definitions(
                valid_item_ids=set(self._item_definitions),
                valid_encounter_ids=encounter_ids,
            )
        )
        self._quest_board_service = QuestBoardService(self._quest_repo.load_quests(), max_active_quests=2)
        self._location_definitions = self._location_repo.load_locations()
        self._travel_service = TravelService(self._location_definitions, hub_location_id=HUB_LOCATION_ID)
        self._gathering_service = GatheringService()
        self._gathering_respawn_service = GatheringRespawnService()
        self._treasure_service = TreasureService()
        self._gathering_nodes = self._gathering_repo.load_nodes(
            valid_item_ids=set(self._item_definitions),
            valid_location_ids=set(self._location_definitions),
        )
        self._treasure_nodes = self._treasure_repo.load_nodes(
            valid_item_ids=set(self._item_definitions),
            valid_equipment_ids=set(self._equipment_definitions),
            valid_location_ids=set(self._location_definitions),
        )
        self._dialogue_service = DialogueService(self._dialogue_event_repo.load_npc_dialogues())
        self._location_event_service = LocationEventService(self._dialogue_event_repo.load_location_events())
        self._field_event_service = FieldEventService(self._field_event_repo.load_events())
        self._workshop_story_service = WorkshopStoryService()
        self._workshop_special_chain_service = WorkshopSpecialChainService()
        self._endgame_order_service = EndgameRepeatableOrderService()
        self._workshop_story_definitions = self._workshop_story_repo.load(
            valid_npc_ids=set(self._dialogue_service.npc_definitions),
            valid_quest_ids=set(self._quest_board_service.definitions),
            valid_recipe_ids=set(self._crafting_recipes),
            valid_location_ids=set(self._location_definitions),
            valid_field_event_ids=set(self._field_event_service.definitions),
        )

        self._workshop_special_chain_definitions = self._workshop_special_chain_repo.load()
        self._endgame_order_definitions = self._endgame_order_repo.load()

        self.quest_session: QuestSliceSession | None = None
        self.party_members: list[PartyMemberState] = []
        self.last_event_id: str | None = None
        self.inventory_state: dict = {}
        self.completed_location_event_ids: set[str] = set()
        self.completed_field_event_ids: set[str] = set()
        self.field_event_choice_history: dict[str, str] = {}
        self.defeated_miniboss_ids: set[str] = set()
        self.miniboss_first_clear_reward_claimed_ids: set[str] = set()
        self.gathered_node_ids: set[str] = set()
        self.unlocked_recipe_ids: set[str] = set()
        self.discovered_recipe_ids: set[str] = set()
        self.discovered_recipe_book_ids: set[str] = set()
        self.opened_treasure_node_ids: set[str] = set()
        self.facility_levels: dict[str, int] = {}
        self.facility_unlocked_recipe_ids: set[str] = set()
        self.facility_unlocked_shop_stock_ids: set[str] = set()
        self.turn_in_completion_count: int = 0
        self.workshop_progress_state = WorkshopProgressState()
        self.workshop_story_state = WorkshopStoryState()
        self.workshop_special_chain_state = WorkshopSpecialChainState()
        self.workshop_order_completion_counts: dict[str, int] = {}
        self.endgame_order_state = EndgameRepeatableOrderState()
        self.active_set_bonus_keys_by_member: dict[str, set[str]] = {}
        self.location_state = LocationState(current_location_id=HUB_LOCATION_ID, unlocked_location_ids={HUB_LOCATION_ID})

    def new_game(self) -> list[str]:
        self.quest_session = self._build_session()
        self.party_members = self._build_initial_party()
        self.inventory_state = {
            "gold": 300,
            "items": {
                "item.consumable.mini_potion": 3,
                "item.consumable.focus_drop": 2,
                "item.consumable.antidote_leaf": 1,
                "equip.weapon.bronze_blade": 1,
            },
        }
        self.quest_session.world_flags.add("flag.game.new_game_started")
        self.location_state = LocationState(current_location_id=HUB_LOCATION_ID, unlocked_location_ids={HUB_LOCATION_ID})
        self.completed_location_event_ids = set()
        self.completed_field_event_ids = set()
        self.field_event_choice_history = {}
        self.defeated_miniboss_ids = set()
        self.miniboss_first_clear_reward_claimed_ids = set()
        self.gathered_node_ids = set()
        self.unlocked_recipe_ids = set()
        self.discovered_recipe_ids = set()
        self.discovered_recipe_book_ids = set()
        self.opened_treasure_node_ids = set()
        self.facility_levels = {}
        self.facility_unlocked_recipe_ids = set()
        self.facility_unlocked_shop_stock_ids = set()
        self.turn_in_completion_count = 0
        self.workshop_progress_state = WorkshopProgressState()
        self.workshop_story_state = WorkshopStoryState()
        self.workshop_special_chain_state = WorkshopSpecialChainState()
        self.workshop_order_completion_counts = {}
        self.endgame_order_state = EndgameRepeatableOrderState()
        self.equipment_upgrade_levels = {}
        self.active_set_bonus_keys_by_member = {}
        self._travel_service.evaluate_unlocks(self.location_state, self.quest_session.world_flags)
        self._initialize_facility_state()
        self._initialize_workshop_progress_state()
        self._evaluate_recipe_unlocks()
        self._refresh_all_quest_objective_flags()
        self._initialize_active_set_bonus_cache()
        self.last_event_id = "event.system.new_game_intro"

        return [
            "new_game_started",
            "intro:narration:港町アステルに朝日が差し込む。",
            "intro:guide:長老に話しかけ、依頼を受けよう。",
        ]

    def continue_game(self) -> tuple[bool, str]:
        try:
            save_data = self._save_repo.load()
        except FileNotFoundError:
            return False, "セーブデータが見つかりません。先に New Game を開始してください。"
        except json.JSONDecodeError:
            return False, "セーブデータのJSONが破損しています。"
        except ValueError as exc:
            return False, f"セーブデータの整合性エラー: {exc}"

        self.quest_session = self._build_session()
        self.last_event_id = self._save_service.restore_quest_session(self.quest_session, save_data)
        self.party_members = save_data.party_members
        self.inventory_state = save_data.inventory_state or {"gold": 0, "items": {}}
        location_meta = save_data.meta.get("location_state", {})
        self.location_state = LocationState(
            current_location_id=str(location_meta.get("current_location_id", HUB_LOCATION_ID)),
            unlocked_location_ids=set(location_meta.get("unlocked_location_ids", [HUB_LOCATION_ID])),
        )
        event_meta = save_data.meta.get("event_state", {})
        self.completed_location_event_ids = set(event_meta.get("completed_location_event_ids", []))
        self.completed_field_event_ids = set(event_meta.get("completed_field_event_ids", []))
        self.field_event_choice_history = {
            str(event_id): str(choice_id)
            for event_id, choice_id in event_meta.get("field_event_choice_history", {}).items()
        }
        miniboss_meta = save_data.meta.get("miniboss_state", {})
        self.defeated_miniboss_ids = self._restore_defeated_miniboss_ids(miniboss_meta)
        self.miniboss_first_clear_reward_claimed_ids = self._restore_miniboss_first_clear_reward_claimed_ids(
            miniboss_meta
        )
        gathering_meta = save_data.meta.get("gathering_state", {})
        self.gathered_node_ids = self._restore_gathered_node_ids(gathering_meta)
        crafting_meta = save_data.meta.get("crafting_state", {})
        self.unlocked_recipe_ids = set(crafting_meta.get("unlocked_recipe_ids", []))
        self.discovered_recipe_ids = set(crafting_meta.get("discovered_recipe_ids", []))
        self.discovered_recipe_book_ids = set(crafting_meta.get("discovered_recipe_book_ids", []))
        treasure_meta = save_data.meta.get("treasure_state", {})
        self.opened_treasure_node_ids = self._restore_opened_treasure_node_ids(treasure_meta)
        facility_meta = save_data.meta.get("facility_state", {})
        self.facility_levels = {
            str(facility_id): int(level)
            for facility_id, level in facility_meta.get("facility_levels", {}).items()
        }
        self.facility_unlocked_recipe_ids = set(facility_meta.get("unlocked_recipe_ids", []))
        self.facility_unlocked_shop_stock_ids = set(facility_meta.get("unlocked_shop_stock_ids", []))
        self.turn_in_completion_count = int(facility_meta.get("turn_in_completion_count", 0))
        workshop_meta = save_data.meta.get("workshop_state", {})
        self.workshop_progress_state = WorkshopProgressState(
            level=max(1, int(workshop_meta.get("rank", 1))),
            progress=max(0, int(workshop_meta.get("progress", 0))),
            unlocked_recipe_ids=set(workshop_meta.get("unlocked_recipe_ids", [])),
            applied_completion_markers=set(workshop_meta.get("applied_completion_markers", [])),
        )
        workshop_story_meta = save_data.meta.get("workshop_story_state", {})
        self.workshop_story_state = WorkshopStoryState(
            seen_stage_ids=set(workshop_story_meta.get("seen_stage_ids", [])),
            unlocked_quest_ids=set(workshop_story_meta.get("unlocked_quest_ids", [])),
            unlocked_recipe_ids=set(workshop_story_meta.get("unlocked_recipe_ids", [])),
            unlocked_location_ids=set(workshop_story_meta.get("unlocked_location_ids", [])),
            unlocked_field_event_ids=set(workshop_story_meta.get("unlocked_field_event_ids", [])),
        )
        special_chain_meta = save_data.meta.get("workshop_special_chain_state", {})
        self.workshop_special_chain_state = WorkshopSpecialChainState(
            unlocked_chain_ids=set(special_chain_meta.get("unlocked_chain_ids", [])),
            active_chain_id=special_chain_meta.get("active_chain_id"),
            active_stage_id=special_chain_meta.get("active_stage_id"),
            completed_stage_ids=set(special_chain_meta.get("completed_stage_ids", [])),
            completed_chain_ids=set(special_chain_meta.get("completed_chain_ids", [])),
            rewarded_chain_ids=set(special_chain_meta.get("rewarded_chain_ids", [])),
        )
        self.workshop_order_completion_counts = {
            str(order_id): int(count)
            for order_id, count in workshop_meta.get("order_completion_counts", {}).items()
        }
        endgame_meta = save_data.meta.get("endgame_repeatable_order_state", {})
        self.endgame_order_state = EndgameRepeatableOrderState(
            unlocked_order_ids=set(endgame_meta.get("unlocked_order_ids", [])),
            active_order_id=endgame_meta.get("active_order_id"),
            completed_order_ids_in_cycle=set(endgame_meta.get("completed_order_ids_in_cycle", [])),
            objective_progress={str(k): int(v) for k, v in endgame_meta.get("objective_progress", {}).items()},
            completion_counts={str(k): int(v) for k, v in endgame_meta.get("completion_counts", {}).items()},
            rewarded_cycle_ids=set(endgame_meta.get("rewarded_cycle_ids", [])),
            ready_to_reaccept_order_ids=set(endgame_meta.get("ready_to_reaccept_order_ids", [])),
        )
        equipment_meta = save_data.meta.get("equipment_state", {})
        self.equipment_upgrade_levels = {
            str(equipment_id): int(level)
            for equipment_id, level in equipment_meta.get("upgrade_levels", {}).items()
            if int(level) > 0
        }
        unknown_upgrade_ids = sorted(
            equipment_id
            for equipment_id in self.equipment_upgrade_levels
            if equipment_id not in self._equipment_upgrade_definitions
        )
        if unknown_upgrade_ids:
            raise ValueError(f"save_data has unknown equipment upgrade ids={unknown_upgrade_ids}")
        if HUB_LOCATION_ID not in self.location_state.unlocked_location_ids:
            self.location_state.unlocked_location_ids.add(HUB_LOCATION_ID)
        self._travel_service.evaluate_unlocks(self.location_state, self.quest_session.world_flags)
        self._initialize_facility_state()
        self._initialize_workshop_progress_state()
        self._evaluate_facility_progression()
        self._evaluate_recipe_unlocks()
        self._refresh_all_quest_objective_flags()
        self._initialize_active_set_bonus_cache()
        return True, "セーブデータをロードしました。"

    def available_actions(self) -> list[ActionItem]:
        if self.quest_session is None:
            return []

        items = [
            ActionItem("status", "ステータス確認"),
            ActionItem("inventory", "所持品確認"),
            ActionItem("use_item", "アイテムを使う"),
            ActionItem("equip", "装備変更"),
            ActionItem("upgrade_equipment", "装備強化"),
            ActionItem("salvage_equipment", "装備分解"),
            ActionItem("shop", "ショップに行く"),
            ActionItem("craft", "クラフトする"),
            ActionItem("inn", "宿屋に泊まる"),
            ActionItem("quest_board", "クエストボードを見る"),
            ActionItem("move", "移動する"),
            ActionItem("current_location", "現在地を確認する"),
            ActionItem("treasure_nodes", "探索報酬を確認する"),
            ActionItem("open_treasure", "探索報酬を調べる"),
            ActionItem("gather_nodes", "採取ポイント確認"),
            ActionItem("gather", "採取する"),
            ActionItem("talk_npc", "NPCと話す"),
            ActionItem("field_events", "探索イベントを調べる"),
        ]
        if self._has_active_quest() and self._location_can_hunt():
            items.append(ActionItem("hunt", "討伐へ進む"))
        if self._has_reportable_quest():
            items.append(ActionItem("report", "報告する"))

        items.extend(
            [
                ActionItem("quests", "受注中クエスト確認"),
                ActionItem("save", "セーブする"),
                ActionItem("load", "ロードする"),
                ActionItem("exit", "終了する"),
            ]
        )
        return items

    def perform_action(self, action_key: str) -> list[str]:
        if self.quest_session is None:
            raise ValueError("ゲームが開始されていません。")

        if action_key == "status":
            return self._status_lines()
        if action_key == "quests":
            return self._quest_lines()
        if action_key == "quest_board":
            return self.quest_board_lines()
        if action_key == "move":
            return self.travel_options_lines()
        if action_key == "current_location":
            return self.current_location_lines()
        if action_key == "treasure_nodes":
            return self.treasure_node_lines()
        if action_key == "open_treasure":
            return ["treasure_open_failed:selection_required"]
        if action_key == "gather_nodes":
            return self.gathering_node_lines()
        if action_key == "gather":
            return ["gather_failed:selection_required"]
        if action_key == "talk_npc":
            return self.talk_npc_options_lines()
        if action_key == "field_events":
            return self.field_event_lines()
        if action_key == "inventory":
            return self._inventory_lines()
        if action_key == "use_item":
            return self._usable_item_lines()
        if action_key == "equip":
            return self.equipment_overview_lines()
        if action_key == "upgrade_equipment":
            return self.workshop_equipment_upgrade_lines()
        if action_key == "salvage_equipment":
            return self.workshop_equipment_salvage_lines()
        if action_key == "shop":
            return self.shop_catalog_lines()
        if action_key == "craft":
            return self.crafting_recipe_lines()
        if action_key == "inn":
            return self.inn_info_lines()
        if action_key == "hunt":
            return self._run_hunt()
        if action_key == "report":
            return self.report_ready_quest()
        if action_key == "save":
            self.save_game()
            return ["save_completed"]
        if action_key == "load":
            ok, message = self.continue_game()
            prefix = "load_completed" if ok else "load_failed"
            return [f"{prefix}:{message}"]
        if action_key == "exit":
            return ["exit_selected"]

        raise ValueError(f"不明なアクションです: {action_key}")

    def quest_board_lines(self) -> list[str]:
        if self.quest_session is None:
            raise ValueError("ゲームが開始されていません。")
        entries = self._quest_board_service.list_entries(
            self.quest_session.quest_states,
            self.quest_session.world_flags,
            self._party_level(),
        )
        lines = [f"quest_board:max_active={self._quest_board_service.max_active_quests}"]
        for entry in entries:
            lines.append(
                f"quest_board_entry:{entry.quest_id}:{entry.title}:status={entry.status.value}:"
                f"can_accept={entry.can_accept}:progress={entry.objective_progress}"
            )
        return lines

    def accept_quest(self, quest_id: str) -> list[str]:
        if self.quest_session is None:
            raise ValueError("ゲームが開始されていません。")

        status = self._quest_board_service.evaluate_status(
            quest_id,
            self.quest_session.quest_states,
            self.quest_session.world_flags,
            self._party_level(),
        )
        if status == QuestBoardStatus.LOCKED:
            return [f"quest_accept_failed:locked:{quest_id}"]
        if status not in {QuestBoardStatus.AVAILABLE, QuestBoardStatus.REACCEPTABLE}:
            return [f"quest_accept_failed:status={status.value}:{quest_id}"]
        if not self._quest_board_service.can_accept_more(self.quest_session.quest_states):
            return [f"quest_accept_failed:active_limit:{self._quest_board_service.max_active_quests}"]

        state = self.quest_session.quest_states.get(quest_id) or self.quest_session.quest_service.create_initial_state(quest_id)
        self.quest_session.quest_states[quest_id] = state
        if status == QuestBoardStatus.REACCEPTABLE:
            self.quest_session.quest_service.reaccept(state)
            self._refresh_quest_objective_flags(quest_id)
            self.last_event_id = f"event.system.quest_reaccepted:{quest_id}"
            return [f"quest_reaccepted:{quest_id}"]
        self.quest_session.quest_service.accept(state)
        self.quest_session.world_flags.add(f"flag.quest.accepted:{quest_id}")
        self._refresh_quest_objective_flags(quest_id)
        self.last_event_id = f"event.system.quest_accepted:{quest_id}"
        return [f"quest_accepted:{quest_id}"]

    def report_ready_quest(self) -> list[str]:
        if self.quest_session is None:
            raise ValueError("ゲームが開始されていません。")
        quest_id = self._ready_to_complete_quest_id()
        if quest_id is None:
            return ["report_unavailable:no_ready_quest"]
        return self._complete_quest(quest_id)

    def turn_in_quest_items(self, quest_id: str, *, auto_complete: bool = False) -> list[str]:
        if self.quest_session is None:
            raise ValueError("ゲームが開始されていません。")
        definition = self.quest_session.quest_service.definitions.get(quest_id)
        if definition is None:
            return [f"turn_in_failed:quest_not_found:{quest_id}"]
        if definition.reporting_npc_id:
            npc_ids = {npc.npc_id for npc in self._dialogue_service.list_npcs_by_location(self.location_state.current_location_id)}
            if definition.reporting_npc_id not in npc_ids:
                return [f"turn_in_failed:wrong_location_for_reporting_npc:{definition.reporting_npc_id}"]

        state = self.quest_session.quest_states.get(quest_id)
        if state is None:
            return [f"turn_in_failed:quest_not_accepted:{quest_id}"]

        turn_in_plan = self.quest_session.quest_service.build_turn_in_plan(
            state=state,
            inventory_items=self.inventory_state.get("items", {}),
        )
        if not turn_in_plan.success:
            return [turn_in_plan.code]

        self.quest_session.quest_service.consume_turn_in_items(self.inventory_state, turn_in_plan)
        logs = self.quest_session.quest_service.apply_turn_in_progress(state, turn_in_plan)
        self._refresh_quest_objective_flags(quest_id)
        logs.extend(self._evaluate_facility_progression())
        if auto_complete and state.status == QuestStatus.READY_TO_COMPLETE:
            logs.extend(self._complete_quest(quest_id))
        self.last_event_id = f"event.system.quest_turn_in:{quest_id}"
        return logs

    def save_game(self) -> None:
        if self.quest_session is None:
            raise ValueError("ゲームが開始されていません。")

        save_data = self._save_service.build_save_data(
            quest_session=self.quest_session,
            party_members=self.party_members,
            last_event_id=self.last_event_id,
            play_time_sec=0,
            inventory_state=self.inventory_state,
            meta={
                "mode": "playable_vertical_slice",
                "location_state": {
                    "current_location_id": self.location_state.current_location_id,
                    "unlocked_location_ids": sorted(self.location_state.unlocked_location_ids),
                },
                "event_state": {
                    "completed_location_event_ids": sorted(self.completed_location_event_ids),
                    "completed_field_event_ids": sorted(self.completed_field_event_ids),
                    "field_event_choice_history": dict(sorted(self.field_event_choice_history.items())),
                },
                "miniboss_state": {
                    "defeated_miniboss_ids": sorted(self.defeated_miniboss_ids),
                    "first_clear_reward_claimed_ids": sorted(self.miniboss_first_clear_reward_claimed_ids),
                },
                "gathering_state": {
                    "gathered_node_ids": sorted(self.gathered_node_ids),
                },
                "crafting_state": {
                    "unlocked_recipe_ids": sorted(self.unlocked_recipe_ids),
                    "discovered_recipe_ids": sorted(self.discovered_recipe_ids),
                    "discovered_recipe_book_ids": sorted(self.discovered_recipe_book_ids),
                },
                "treasure_state": {
                    "opened_reward_node_ids": sorted(self.opened_treasure_node_ids),
                },
                "facility_state": {
                    "facility_levels": dict(sorted(self.facility_levels.items())),
                    "unlocked_recipe_ids": sorted(self.facility_unlocked_recipe_ids),
                    "unlocked_shop_stock_ids": sorted(self.facility_unlocked_shop_stock_ids),
                    "turn_in_completion_count": self.turn_in_completion_count,
                },
                "equipment_state": {
                    "upgrade_levels": dict(sorted(self.equipment_upgrade_levels.items())),
                },
                "workshop_state": {
                    "rank": self.workshop_progress_state.level,
                    "progress": self.workshop_progress_state.progress,
                    "unlocked_recipe_ids": sorted(self.workshop_progress_state.unlocked_recipe_ids),
                    "order_completion_counts": dict(sorted(self.workshop_order_completion_counts.items())),
                    "applied_completion_markers": sorted(self.workshop_progress_state.applied_completion_markers),
                },
                "workshop_story_state": {
                    "seen_stage_ids": sorted(self.workshop_story_state.seen_stage_ids),
                    "unlocked_quest_ids": sorted(self.workshop_story_state.unlocked_quest_ids),
                    "unlocked_recipe_ids": sorted(self.workshop_story_state.unlocked_recipe_ids),
                    "unlocked_location_ids": sorted(self.workshop_story_state.unlocked_location_ids),
                    "unlocked_field_event_ids": sorted(self.workshop_story_state.unlocked_field_event_ids),
                },
                "workshop_special_chain_state": {
                    "unlocked_chain_ids": sorted(self.workshop_special_chain_state.unlocked_chain_ids),
                    "active_chain_id": self.workshop_special_chain_state.active_chain_id,
                    "active_stage_id": self.workshop_special_chain_state.active_stage_id,
                    "completed_stage_ids": sorted(self.workshop_special_chain_state.completed_stage_ids),
                    "completed_chain_ids": sorted(self.workshop_special_chain_state.completed_chain_ids),
                    "rewarded_chain_ids": sorted(self.workshop_special_chain_state.rewarded_chain_ids),
                },
                "endgame_repeatable_order_state": {
                    "unlocked_order_ids": sorted(self.endgame_order_state.unlocked_order_ids),
                    "active_order_id": self.endgame_order_state.active_order_id,
                    "completed_order_ids_in_cycle": sorted(self.endgame_order_state.completed_order_ids_in_cycle),
                    "objective_progress": dict(sorted(self.endgame_order_state.objective_progress.items())),
                    "completion_counts": dict(sorted(self.endgame_order_state.completion_counts.items())),
                    "rewarded_cycle_ids": sorted(self.endgame_order_state.rewarded_cycle_ids),
                    "ready_to_reaccept_order_ids": sorted(self.endgame_order_state.ready_to_reaccept_order_ids),
                },
            },
        )
        self._save_repo.save(save_data)

    def travel_options_lines(self) -> list[str]:
        current = self._travel_service.location(self.location_state.current_location_id)
        lines = [f"current_location:{self.location_state.current_location_id}:{current.name if current else 'unknown'}"]
        for destination in self._travel_service.list_destinations(self.location_state):
            lines.append(
                f"travel_option:{destination.location_id}:{destination.name}:type={destination.location_type}"
            )
        return lines

    def travel_to(self, location_id: str) -> list[str]:
        previous_location_id = self.location_state.current_location_id
        result = self._travel_service.travel_to(self.location_state, location_id)
        if not result.success:
            return [result.message]
        destination = self._travel_service.location(location_id)
        lines = [result.message, f"current_location:{location_id}:{destination.name if destination else location_id}"]
        if location_id == HUB_LOCATION_ID and previous_location_id != HUB_LOCATION_ID:
            lines.extend(self._apply_gathering_respawn("on_return_to_hub"))
            lines.extend(self._apply_repeatable_quest_updates("on_return_to_hub"))
            lines.extend(self._mark_endgame_orders_reaccept_ready("on_return_to_hub"))
        lines.extend(self._run_on_enter_location_events(location_id))
        return lines

    def current_location_lines(self) -> list[str]:
        definition = self._travel_service.location(self.location_state.current_location_id)
        if definition is None:
            return [f"current_location:unknown:{self.location_state.current_location_id}"]
        node_statuses = self._gathering_service.list_nodes_for_location(
            nodes=self._gathering_nodes,
            location_id=self.location_state.current_location_id,
            world_flags=self.quest_session.world_flags if self.quest_session else set(),
            gathered_node_ids=self.gathered_node_ids,
        )
        treasure_statuses = self._treasure_service.list_nodes_for_location(
            nodes=self._treasure_nodes,
            location_id=self.location_state.current_location_id,
            world_flags=self.quest_session.world_flags if self.quest_session else set(),
            opened_node_ids=self.opened_treasure_node_ids,
            facility_levels=self.facility_levels,
        )
        return [
            f"current_location:{definition.location_id}:{definition.name}:type={definition.location_type}",
            f"location_description:{definition.description}",
            f"treasure_nodes:total={len(treasure_statuses)}:openable={sum(1 for status in treasure_statuses if status.can_open)}",
            f"gathering_nodes:total={len(node_statuses)}:available={sum(1 for status in node_statuses if status.can_gather)}",
        ]

    def treasure_node_lines(self) -> list[str]:
        if self.quest_session is None:
            raise ValueError("ゲームが開始されていません。")
        statuses = self._treasure_service.list_nodes_for_location(
            nodes=self._treasure_nodes,
            location_id=self.location_state.current_location_id,
            world_flags=self.quest_session.world_flags,
            opened_node_ids=self.opened_treasure_node_ids,
            facility_levels=self.facility_levels,
        )
        if not statuses:
            return [f"treasure_node:none:location={self.location_state.current_location_id}"]
        lines = [f"treasure_nodes:location={self.location_state.current_location_id}"]
        for status in statuses:
            state = "未開封" if status.can_open else ("開封済み" if status.is_opened else "条件未達")
            lines.append(
                f"treasure_node:{status.reward_node_id}:{status.name}:type={status.node_type}:"
                f"can_open={status.can_open}:reason={status.reason_code}:state={state}"
            )
        return lines

    def open_treasure_node(self, reward_node_id: str) -> list[str]:
        if self.quest_session is None:
            raise ValueError("ゲームが開始されていません。")
        node = self._treasure_nodes.get(reward_node_id)
        if node is None:
            return [f"treasure_open_failed:node_not_found:{reward_node_id}"]
        result = self._treasure_service.open_node(
            node=node,
            current_location_id=self.location_state.current_location_id,
            world_flags=self.quest_session.world_flags,
            opened_node_ids=self.opened_treasure_node_ids,
            facility_levels=self.facility_levels,
        )
        if not result.success:
            if result.code == "already_opened":
                return [f"treasure_already_opened:{reward_node_id}"]
            return [result.message]
        self._treasure_service.apply_to_inventory(
            inventory_state=self.inventory_state,
            gained_items=result.gained_items,
        )
        lines = [result.message]
        if result.message_on_open:
            lines.append(f"treasure_open_message:{result.reward_node_id}:{result.message_on_open}")
        for item_id, amount in sorted(result.gained_items.items()):
            lines.append(f"treasure_gained:{item_id}:x{amount}")
        recipe_logs = self._apply_recipe_discovery_for_items(set(result.gained_items))
        lines.extend(recipe_logs)
        for line in recipe_logs:
            if line.startswith("recipe_discovered:") or line.startswith("recipe_book_discovered:"):
                lines.append(f"recipe_discovered_from_treasure:{reward_node_id}:{line}")
        return lines

    def openable_treasure_node_choices(self) -> list[tuple[str, str]]:
        if self.quest_session is None:
            raise ValueError("ゲームが開始されていません。")
        statuses = self._treasure_service.list_nodes_for_location(
            nodes=self._treasure_nodes,
            location_id=self.location_state.current_location_id,
            world_flags=self.quest_session.world_flags,
            opened_node_ids=self.opened_treasure_node_ids,
            facility_levels=self.facility_levels,
        )
        choices: list[tuple[str, str]] = []
        for status in statuses:
            if not status.can_open:
                continue
            choices.append((status.reward_node_id, f"{status.name} ({status.node_type})"))
        return choices

    def gathering_node_lines(self) -> list[str]:
        if self.quest_session is None:
            raise ValueError("ゲームが開始されていません。")
        statuses = self._gathering_service.list_nodes_for_location(
            nodes=self._gathering_nodes,
            location_id=self.location_state.current_location_id,
            world_flags=self.quest_session.world_flags,
            gathered_node_ids=self.gathered_node_ids,
        )
        if not statuses:
            return [f"gather_node:none:location={self.location_state.current_location_id}"]
        lines = [f"gather_nodes:location={self.location_state.current_location_id}"]
        for status in statuses:
            lines.append(
                f"gather_node:{status.node_id}:{status.name}:type={status.node_type}:"
                f"can_gather={status.can_gather}:reason={status.reason_code}:gathered={status.is_gathered}:"
                f"respawn_rule={status.respawn_rule}:respawn={status.respawn_description or 'none'}"
            )
        return lines

    def gather_from_node(self, node_id: str) -> list[str]:
        if self.quest_session is None:
            raise ValueError("ゲームが開始されていません。")
        node = self._gathering_nodes.get(node_id)
        if node is None:
            return [f"gather_failed:node_not_found:{node_id}"]
        result = self._gathering_service.gather(
            node=node,
            current_location_id=self.location_state.current_location_id,
            world_flags=self.quest_session.world_flags,
            gathered_node_ids=self.gathered_node_ids,
        )
        lines = [result.message]
        if not result.success:
            return lines
        self._gathering_service.apply_to_inventory(
            inventory_state=self.inventory_state,
            gained_items=result.gained_items,
        )
        for item_id, amount in sorted(result.gained_items.items()):
            lines.append(f"gathered_item:{item_id}:x{amount}")
        lines.extend(self._apply_quest_gather_progress(result.gained_items))
        lines.extend(self._apply_recipe_discovery_for_items(set(result.gained_items)))
        return lines

    def gatherable_node_choices(self) -> list[tuple[str, str]]:
        if self.quest_session is None:
            raise ValueError("ゲームが開始されていません。")
        statuses = self._gathering_service.list_nodes_for_location(
            nodes=self._gathering_nodes,
            location_id=self.location_state.current_location_id,
            world_flags=self.quest_session.world_flags,
            gathered_node_ids=self.gathered_node_ids,
        )
        choices: list[tuple[str, str]] = []
        for status in statuses:
            if not status.can_gather:
                continue
            choices.append((status.node_id, f"{status.name} ({status.node_type})"))
        return choices

    def talk_npc_options_lines(self) -> list[str]:
        npcs = self._dialogue_service.list_npcs_by_location(self.location_state.current_location_id)
        if not npcs:
            return [f"npc:none:location={self.location_state.current_location_id}"]
        return [f"npc:{npc.npc_id}:{npc.npc_name}" for npc in npcs]

    def field_event_lines(self) -> list[str]:
        if self.quest_session is None:
            raise ValueError("ゲームが開始されていません。")
        statuses = self._field_event_service.list_events_for_location(
            location_id=self.location_state.current_location_id,
            world_flags=self.quest_session.world_flags,
            completed_event_ids=self.completed_field_event_ids,
        )
        if not statuses:
            return [f"field_event:none:location={self.location_state.current_location_id}"]
        lines = [f"field_event_list:location={self.location_state.current_location_id}"]
        for status in statuses:
            state_label = "[再実行可]" if status.repeatable else ("[実行済み]" if status.is_completed else "[未実行]")
            lines.append(
                f"field_event:{status.event_id}:{status.name}:{state_label}:"
                f"can_execute={status.can_execute}:reason={status.reason_code}"
            )
            lines.append(f"field_event_desc:{status.event_id}:{status.description}")
            miniboss_status = self._miniboss_service.event_status_label(status.event_id, self.defeated_miniboss_ids)
            if miniboss_status is not None:
                lines.append(miniboss_status)
        return lines

    def executable_field_event_choices(self) -> list[tuple[str, str]]:
        if self.quest_session is None:
            raise ValueError("ゲームが開始されていません。")
        statuses = self._field_event_service.list_events_for_location(
            location_id=self.location_state.current_location_id,
            world_flags=self.quest_session.world_flags,
            completed_event_ids=self.completed_field_event_ids,
        )
        choices: list[tuple[str, str]] = []
        for status in statuses:
            if not status.can_execute:
                continue
            choices.append((status.event_id, f"{status.name} ({status.event_id})"))
        return choices

    def field_event_choice_lines(self, event_id: str) -> list[str]:
        event = self._field_event_service.definitions.get(event_id)
        if event is None:
            return [f"field_event_failed:event_not_found:{event_id}"]
        if event.location_id != self.location_state.current_location_id:
            return [f"field_event_failed:location_mismatch:{event_id}:{self.location_state.current_location_id}"]
        lines = [f"field_event_choices:{event.event_id}:{event.name}"]
        for choice in event.choices:
            lines.append(f"field_event_choice:{choice.choice_id}:{choice.text}")
        return lines

    def resolve_field_event_choice(self, event_id: str, choice_id: str) -> list[str]:
        if self.quest_session is None:
            raise ValueError("ゲームが開始されていません。")
        resolved = self._field_event_service.resolve_choice(
            event_id=event_id,
            choice_id=choice_id,
            location_id=self.location_state.current_location_id,
            world_flags=self.quest_session.world_flags,
            completed_event_ids=self.completed_field_event_ids,
        )
        if not resolved.success:
            return [resolved.code]
        if resolved.event is None or resolved.choice is None:
            return ["field_event_failed:definition_error"]
        lines = [f"field_event_resolved:{resolved.event.event_id}"]
        lines.append(f"field_choice_selected:{resolved.event.event_id}:{resolved.choice.choice_id}")
        self.field_event_choice_history[resolved.event.event_id] = resolved.choice.choice_id
        for outcome in resolved.choice.outcomes:
            lines.extend(
                self._run_field_event_outcome(
                    outcome.outcome_type,
                    outcome.params,
                    source_event_id=resolved.event.event_id,
                )
            )
        if resolved.should_mark_completed:
            self.completed_field_event_ids.add(resolved.event.event_id)
        self.last_event_id = resolved.event.event_id
        return lines

    def talk_to_npc(
        self,
        npc_id: str,
        choice_selector: Callable[[list[tuple[str, str]], str], str] | None = None,
    ) -> list[str]:
        if self.quest_session is None:
            raise ValueError("ゲームが開始されていません。")
        resolved = self._dialogue_service.resolve(
            npc_id=npc_id,
            current_location_id=self.location_state.current_location_id,
            world_flags=self.quest_session.world_flags,
            quest_states=self.quest_session.quest_states,
        )
        if not resolved.success:
            return list(resolved.lines)
        lines = [f"dialogue:{resolved.npc_id}:{resolved.npc_name}:entry={resolved.matched_entry_id or 'fallback'}"]
        entry = resolved.entry
        if entry is None or not entry.steps:
            lines.extend(f"line:{resolved.npc_id}:{line}" for line in resolved.lines)
        else:
            current_step = self._dialogue_service.initial_step(entry)
            while current_step is not None:
                lines.extend(f"line:{current_step.speaker}:{line}" for line in current_step.lines)
                available_choices = self._dialogue_service.available_choices(current_step, self.quest_session.world_flags)
                if not available_choices:
                    break
                lines.extend(
                    f"choice:{index}:{choice.choice_id}:{choice.text}"
                    for index, choice in enumerate(available_choices, start=1)
                )
                if choice_selector is None:
                    lines.append(f"dialogue_choice_pending:step={current_step.step_id}")
                    break
                selected_choice_id = choice_selector(
                    [(choice.choice_id, choice.text) for choice in available_choices],
                    current_step.step_id,
                )
                choice_result = self._dialogue_service.apply_choice(
                    entry=entry,
                    step_id=current_step.step_id,
                    choice_id=selected_choice_id,
                    world_flags=self.quest_session.world_flags,
                )
                if not choice_result.success:
                    lines.append(choice_result.code)
                    break
                lines.append(f"choice_selected:{current_step.step_id}:{choice_result.selected_choice_id}")
                for flag_id in choice_result.set_flags:
                    self.quest_session.world_flags.add(flag_id)
                    lines.append(f"flag_set:{flag_id}")
                lines.extend(self._evaluate_recipe_unlocks())
                should_end = False
                for effect in choice_result.effects:
                    effect_logs = self._run_dialogue_choice_effect(effect.action_type, effect.params)
                    lines.extend(effect_logs)
                    if effect.action_type == "end_dialogue":
                        should_end = True
                if should_end:
                    break
                if not choice_result.next_step_id:
                    break
                current_step = self._dialogue_service.find_step(entry, choice_result.next_step_id)
                if current_step is None:
                    lines.append(f"dialogue_choice_failed:next_step_not_found:{choice_result.next_step_id}")
                    break
        lines.extend(self._apply_recipe_discovery("dialogue_event", resolved.matched_entry_id or npc_id))
        if npc_id in self._workshop_npc_ids:
            lines.extend(self._advance_workshop_story(npc_id))
            lines.extend(self.workshop_set_bonus_guidance_lines())
            lines.extend(self.workshop_salvage_guidance_lines())
            lines.extend(self.workshop_recipe_lines(npc_id))
            lines.extend(self.workshop_progress_lines())
            lines.extend(self._advance_workshop_special_chain())
            lines.extend(self._update_endgame_repeatable_orders())
            lines.extend(self.endgame_repeatable_order_lines())
            lines.extend(self.workshop_equipment_upgrade_lines())
            lines.extend(self.workshop_equipment_salvage_lines())
        return lines

    def _mark_endgame_orders_reaccept_ready(self, repeat_reset_rule: str) -> list[str]:
        return self._endgame_order_service.mark_ready_to_reaccept(
            state=self.endgame_order_state,
            repeat_reset_rule=repeat_reset_rule,
        )

    def endgame_repeatable_order_lines(self) -> list[str]:
        lines: list[str] = []
        for order in self._endgame_order_definitions:
            unlocked = order.order_id in self.endgame_order_state.unlocked_order_ids
            active = self.endgame_order_state.active_order_id == order.order_id
            ready = order.order_id in self.endgame_order_state.ready_to_reaccept_order_ids
            lines.append(
                f"endgame_order:{order.order_id}:unlocked={unlocked}:active={active}:ready_to_reaccept={ready}:completed={self.endgame_order_state.completion_counts.get(order.order_id, 0)}"
            )
        return lines

    def _update_endgame_repeatable_orders(self) -> list[str]:
        if self.quest_session is None:
            return []
        logs = self._endgame_order_service.unlock_available(
            state=self.endgame_order_state,
            definitions=self._endgame_order_definitions,
            workshop_level=self.workshop_progress_state.level,
            world_flags=self.quest_session.world_flags,
        )
        if self.endgame_order_state.active_order_id is None:
            for order in self._endgame_order_definitions:
                if order.order_id in self.endgame_order_state.unlocked_order_ids:
                    logs.extend(self._endgame_order_service.start(state=self.endgame_order_state, order=order))
                    break
        active_id = self.endgame_order_state.active_order_id
        if not active_id:
            return logs
        order = next((o for o in self._endgame_order_definitions if o.order_id == active_id), None)
        if order is None:
            return logs + [f"endgame_order_failed:unknown_order:{active_id}"]
        for obj in order.objectives:
            clear = False
            req = obj.requirements
            if obj.objective_type == "defeat_miniboss":
                clear = req.get("miniboss_id") in self.defeated_miniboss_ids
            elif obj.objective_type == "craft_equipment":
                clear = self.inventory_state.get("items", {}).get(req.get("equipment_id", ""), 0) > 0
            elif obj.objective_type == "upgrade_equipment":
                clear = self.equipment_upgrade_levels.get(req.get("equipment_id", ""), 0) >= int(req.get("min_level", "1"))
            elif obj.objective_type == "activate_set_bonus":
                active_bonus_keys = set().union(*self.active_set_bonus_keys_by_member.values()) if self.active_set_bonus_keys_by_member else set()
                clear = req.get("set_bonus_id", "") in active_bonus_keys
            logs.extend(self._endgame_order_service.update_objective(state=self.endgame_order_state, order=order, objective_id=obj.objective_id, completed=clear))
        if self._endgame_order_service.is_all_objectives_completed(state=self.endgame_order_state, order=order):
            logs.extend(self._endgame_order_service.complete(state=self.endgame_order_state, order=order))
            if order.order_id not in self.endgame_order_state.rewarded_cycle_ids:
                self.endgame_order_state.rewarded_cycle_ids.add(order.order_id)
                for item_id, amount in order.rewards.items():
                    self.inventory_state.setdefault("items", {})
                    self.inventory_state["items"][item_id] = self.inventory_state["items"].get(item_id, 0) + amount
                    logs.append(f"endgame_order_reward:{order.order_id}:{item_id}:x{amount}")
        return logs

    def _advance_workshop_story(self, npc_id: str) -> list[str]:
        if self.quest_session is None:
            return []
        lines: list[str] = []
        matched = self._workshop_story_service.resolve_for_npc(
            npc_id=npc_id,
            workshop_level=self.workshop_progress_state.level,
            world_flags=self.quest_session.world_flags,
            state=self.workshop_story_state,
            stage_definitions=self._workshop_story_definitions,
        )
        for stage in matched:
            stage_logs = self._workshop_story_service.apply_stage(
                stage=stage,
                state=self.workshop_story_state,
                world_flags=self.quest_session.world_flags,
            )
            lines.extend(stage_logs)
            for quest_id in stage.unlock_rewards.quest_ids:
                self.quest_session.world_flags.add(f"flag.workshop.story.quest_unlocked:{quest_id}")
            for recipe_id in stage.unlock_rewards.recipe_ids:
                if recipe_id not in self.unlocked_recipe_ids:
                    self.unlocked_recipe_ids.add(recipe_id)
                    self.discovered_recipe_ids.add(recipe_id)
                    lines.append(f"recipe_unlocked:workshop_story:{recipe_id}")
        lines.extend(self._evaluate_recipe_unlocks())
        return lines

    def _advance_workshop_special_chain(self) -> list[str]:
        if self.quest_session is None:
            return []
        logs = self._workshop_special_chain_service.unlock_available(
            state=self.workshop_special_chain_state,
            definitions=self._workshop_special_chain_definitions,
            workshop_level=self.workshop_progress_state.level,
            world_flags=self.quest_session.world_flags,
        )
        active_id = self.workshop_special_chain_state.active_chain_id
        if not active_id:
            return logs
        chain = next((c for c in self._workshop_special_chain_definitions if c.chain_id == active_id), None)
        if chain is None:
            return logs + [f"special_chain_failed:unknown_chain:{active_id}"]
        stage_id = self.workshop_special_chain_state.active_stage_id
        stage = next((s for s in chain.stages if s.stage_id == stage_id), None) if stage_id else None
        if stage is None:
            return logs
        req = stage.requirements
        clear = False
        if stage.stage_type == "defeat_miniboss":
            clear = req.get("miniboss_id") in self.defeated_miniboss_ids
        elif stage.stage_type == "craft_equipment":
            clear = self.inventory_state.get("items", {}).get(req.get("equipment_id", ""), 0) > 0
        elif stage.stage_type == "upgrade_equipment":
            clear = self.equipment_upgrade_levels.get(req.get("equipment_id", ""), 0) >= int(req.get("min_level", "1"))
        elif stage.stage_type == "turn_in_items":
            clear = req.get("required_flag") in self.quest_session.world_flags
        logs.extend(self._workshop_special_chain_service.advance(state=self.workshop_special_chain_state, chain=chain, stage_clear=clear))
        for line in logs:
            if line.startswith("special_chain_final_reward:"):
                reward = line.split(":", 3)[-1]
                if reward.startswith("recipe."):
                    self.unlocked_recipe_ids.add(reward)
                    self.discovered_recipe_ids.add(reward)
                if reward.startswith("flag."):
                    self.quest_session.world_flags.add(reward)
        return logs

    def _run_dialogue_choice_effect(self, action_type: str, params: dict[str, str]) -> list[str]:
        if self.quest_session is None:
            raise ValueError("ゲームが開始されていません。")
        if action_type == "set_flag":
            flag_id = params["flag_id"]
            self.quest_session.world_flags.add(flag_id)
            logs = [f"flag_set:{flag_id}"]
            logs.extend(self._evaluate_recipe_unlocks())
            return logs
        if action_type == "accept_quest":
            return self.accept_quest(params["quest_id"])
        if action_type == "turn_in_quest":
            return self.turn_in_quest_items(
                params["quest_id"],
                auto_complete=params.get("auto_complete", "false").lower() == "true",
            )
        if action_type == "report_quest":
            return self._complete_quest(params["quest_id"])
        if action_type == "unlock_recipe":
            source_id = params.get("source_id") or "dialogue_choice"
            return self._apply_recipe_discovery("dialogue_event", source_id)
        if action_type == "start_battle":
            return self._run_event_battle(params["encounter_id"])
        if action_type == "end_dialogue":
            return ["dialogue_ended_by_effect"]
        return [f"dialogue_choice_effect_skipped:unsupported:{action_type}"]

    def use_item(self, item_id: str, target_character_id: str) -> list[str]:
        result = self._item_use_service.use_item(
            item_id=item_id,
            target_character_id=target_character_id,
            item_definitions=self._item_definitions,
            status_effect_definitions=self._status_effect_definitions,
            party_members=self.party_members,
            inventory_state=self.inventory_state,
        )
        return [result.message]

    def shop_catalog_lines(self, shop_id: str = BASE_SHOP_ID) -> list[str]:
        ok, message, shop = self._shop_service.list_entries(shop_id)
        if not ok or shop is None:
            return [f"shop_failed:{message}"]

        available_entries = self._available_shop_entries(shop)
        shop_level = self.facility_levels.get("facility.hub.general_store", 0)
        lines = [
            f"shop:{shop.shop_id}:{shop.name}",
            f"shop_facility_level:facility.hub.general_store:{shop_level}",
            f"gold:{self.inventory_state.get('gold', 0)}",
        ]
        for entry in available_entries:
            item_name = self._item_definitions.get(entry.item_id, {}).get("name", entry.item_id)
            lines.append(
                f"shop_item:{entry.item_id}:{item_name}:price={entry.price}:stock_type={entry.stock_type}"
            )
        return lines

    def buy_item(self, item_id: str, quantity: int = 1, shop_id: str = BASE_SHOP_ID) -> list[str]:
        shop = self._shops.get(shop_id)
        if shop is None:
            return [f"purchase_failed:shop_not_found:{shop_id}"]
        sold_item_ids = {entry.item_id for entry in shop.entries}
        if item_id not in sold_item_ids:
            result = self._shop_service.purchase(
                inventory_state=self.inventory_state,
                shop_id=shop_id,
                item_id=item_id,
                quantity=quantity,
            )
            return [result.message]
        available_item_ids = {entry.item_id for entry in self._available_shop_entries(shop)}
        if item_id not in available_item_ids:
            return [f"purchase_failed:shop_stock_locked:{shop_id}:{item_id}"]
        result = self._shop_service.purchase(
            inventory_state=self.inventory_state,
            shop_id=shop_id,
            item_id=item_id,
            quantity=quantity,
        )
        return [result.message]

    def crafting_recipe_lines(self) -> list[str]:
        workshop_level = self.workshop_progress_state.level
        lines = [
            "crafting:recipes",
            f"workshop_rank:workshop:{workshop_level}",
        ]
        inventory_items = self.inventory_state.get("items", {})
        statuses = self._recipe_unlock_service.build_availability(
            recipes=self._crafting_recipes,
            unlocked_recipe_ids=self.unlocked_recipe_ids,
            world_flags=self.quest_session.world_flags if self.quest_session else set(),
            completed_quest_ids=self._completed_quest_ids(),
            current_location_id=self.location_state.current_location_id,
            crafting_service=self._crafting_service,
            inventory_items=inventory_items,
        )
        for status in statuses:
            recipe_id = status.recipe_id
            recipe = self._crafting_recipes[recipe_id]
            resolution = self._crafting_service.resolve(recipe=recipe, inventory_items=inventory_items)
            outputs = ",".join(f"{item_id}x{amount}" for item_id, amount in sorted(resolution.aggregated_outputs.items()))
            ingredients = ",".join(
                f"{req.item_id}:{req.owned}/{req.required}" for req in resolution.required_materials
            )
            discovery_state = "発見済み" if recipe_id in self.discovered_recipe_ids else "未発見"
            facility_unlocked = self._is_recipe_unlocked_by_facility(recipe_id)
            workshop_unlocked = self._is_recipe_unlocked_by_workshop_rank(recipe_id)
            discovery_requirement_met = self._is_recipe_discovery_requirement_met(recipe)
            unlock_state = (
                "解放済み"
                if status.unlocked and facility_unlocked and workshop_unlocked and discovery_requirement_met
                else "未解放"
            )
            can_craft = (
                status.unlocked and facility_unlocked and workshop_unlocked and discovery_requirement_met and resolution.can_craft
            )
            material_state = "素材充足" if resolution.can_craft else "素材不足"
            state_tag = self._crafting_state_tag(
                unlocked=status.unlocked,
                discovery_requirement_met=discovery_requirement_met,
                rank_unlocked=(facility_unlocked and workshop_unlocked),
                material_ready=resolution.can_craft,
            )
            lock_reason_code = status.lock_reason
            if status.unlocked and (not facility_unlocked or not workshop_unlocked):
                lock_reason_code = "required_workshop_rank_missing"
            if status.unlocked and not discovery_requirement_met:
                lock_reason_code = "required_recipe_discovery_missing"
            lock_reason = f":lock_reason={lock_reason_code}" if not can_craft else ""
            lines.append(
                f"craft_recipe:{recipe_id}:{recipe.name}:category={recipe.category}:tier={recipe.recipe_tier}:"
                f"required_workshop_level={recipe.required_workshop_level}:discovery={discovery_state}:unlock={unlock_state}:"
                f"materials={material_state}:can_craft={can_craft}:"
                f"status={state_tag}:ingredients={ingredients}:outputs={outputs}{lock_reason}"
            )
            lines.append(f"requires_miniboss_material:{recipe_id}:{self._recipe_requires_miniboss_material(recipe)}")
            if recipe.recipe_tier == "advanced" and status.unlocked and discovery_requirement_met:
                lines.append(f"advanced_recipe_unlocked:{recipe_id}")
        return lines

    def workshop_recipe_lines(self, workshop_npc_id: str) -> list[str]:
        workshop_level = self.workshop_progress_state.level
        lines = [
            f"workshop_npc:{workshop_npc_id}:recipe_status",
            f"workshop_rank:workshop:{workshop_level}",
        ]
        for recipe_id, recipe in sorted(self._crafting_recipes.items()):
            discovered = recipe_id in self.discovered_recipe_ids
            unlocked = recipe_id in self.unlocked_recipe_ids
            facility_unlocked = self._is_recipe_unlocked_by_facility(recipe_id)
            workshop_unlocked = self._is_recipe_unlocked_by_workshop_rank(recipe_id)
            discovery_requirement_met = self._is_recipe_discovery_requirement_met(recipe)
            resolution = self._crafting_service.resolve(
                recipe=recipe,
                inventory_items=self.inventory_state.get("items", {}),
            )
            discovery_state = "発見済み" if discovered else "未発見"
            craft_state = self._crafting_state_tag(
                unlocked=unlocked,
                discovery_requirement_met=discovery_requirement_met,
                rank_unlocked=(facility_unlocked and workshop_unlocked),
                material_ready=resolution.can_craft,
            )
            lines.append(
                f"workshop_recipe:{recipe_id}:{recipe.name}:discovery={discovery_state}:unlocked={unlocked}:"
                f"facility_unlock={facility_unlocked}:rank_unlock={workshop_unlocked}:tier={recipe.recipe_tier}:craft={craft_state}"
            )
        return lines

    def craft_recipe(self, recipe_id: str, count: int = 1) -> list[str]:
        recipe = self._crafting_recipes.get(recipe_id)
        if recipe is None:
            return [f"craft_failed:recipe_not_found:{recipe_id}"]
        if recipe_id not in self.unlocked_recipe_ids:
            return [f"craft_failed:recipe_locked:{recipe_id}"]
        if not self._is_recipe_unlocked_by_facility(recipe_id) or not self._is_recipe_unlocked_by_workshop_rank(recipe_id):
            return [f"craft_failed:required_workshop_rank:recipe={recipe_id}"]
        if not self._is_recipe_discovery_requirement_met(recipe):
            required = recipe.required_recipe_discovery or "unknown"
            return [f"craft_failed:required_recipe_discovery:recipe={recipe_id}:required={required}"]
        result = self._crafting_service.craft(recipe=recipe, inventory_state=self.inventory_state, count=count)
        lines = [result.message]
        if not result.success:
            return lines
        if recipe.recipe_tier == "advanced":
            lines.append(f"advanced_crafting_success:{recipe_id}")
        if result.crafted:
            for item_id, amount in sorted(result.crafted.items()):
                lines.append(f"crafted_item:{item_id}:x{amount}")
            lines.extend(self._apply_quest_craft_progress(result.crafted))
        return lines

    def inn_info_lines(self, inn_id: str = BASE_INN_ID) -> list[str]:
        inn = self._inn_service.get_inn(inn_id)
        if inn is None:
            return [f"inn_failed:inn_not_found:{inn_id}"]
        return [
            f"inn:{inn.inn_id}:{inn.name}",
            f"inn_stay_price:{inn.stay_price}",
            f"gold:{self.inventory_state.get('gold', 0)}",
            f"inn_policy:revive_knocked_out_members={inn.revive_knocked_out_members}",
            f"inn_description:{inn.description}",
        ]

    def stay_at_inn(self, inn_id: str = BASE_INN_ID) -> list[str]:
        result = self._inn_service.stay(
            inn_id=inn_id,
            party_members=self.party_members,
            inventory_state=self.inventory_state,
        )
        lines = [result.message]
        if result.success:
            lines.extend(self._apply_gathering_respawn("on_rest"))
            lines.extend(self._apply_repeatable_quest_updates("on_rest"))
            lines.extend(self.party_member_lines())
        return lines

    def equipment_overview_lines(self) -> list[str]:
        lines = ["equipment:members"]
        lines.extend(self.party_member_lines())
        return lines

    def equippable_options(self, character_id: str, slot_type: str) -> list[tuple[str, str]]:
        member = next((m for m in self.party_members if m.character_id == character_id), None)
        if member is None or slot_type not in VALID_SLOTS:
            return []
        options = [("cancel", "変更しない")]
        for equipment_id, definition in sorted(self._equipment_definitions.items()):
            if definition.slot_type != slot_type:
                continue
            owned = int(self.inventory_state.get("items", {}).get(equipment_id, 0))
            equipped_count = sum(
                1 for unit in self.party_members for eq in unit.equipped.values() if eq == equipment_id
            )
            available = max(0, owned - equipped_count)
            bonus = self._equipment_service.compute_bonuses({slot_type: equipment_id})
            passive_summary = ", ".join(
                f"{passive.passive_type}:{passive.description}" for passive in definition.passive_effects
            ) or "none"
            options.append(
                (
                    equipment_id,
                    f"{definition.name} ({equipment_id}) owned={owned} available={available} "
                    f"atk+{bonus['atk']} def+{bonus['defense']} hp+{bonus['hp']} spd+{bonus['spd']} "
                    f"passives={passive_summary}",
                )
            )
        return options

    def workshop_equipment_upgrade_lines(self) -> list[str]:
        lines = [
            f"workshop_rank:workshop:{self.workshop_progress_state.level}",
            "equipment_upgrade:status",
        ]
        options = self.upgradable_equipment_options()
        if not options:
            lines.append("equipment_upgrade:none")
            return lines
        for equipment_id, _ in options:
            evaluation = self._equipment_upgrade_service.evaluate_upgrade(
                equipment_id=equipment_id,
                equipment_upgrade_levels=self.equipment_upgrade_levels,
                inventory_items=self.inventory_state.get("items", {}),
                workshop_level=self.workshop_progress_state.level,
            )
            state_tag = {
                "upgradable": "[強化可能]",
                "insufficient_materials": "[素材不足]",
                "insufficient_workshop_level": "[工房ランク不足]",
                "max_level": "[最大強化]",
            }.get(evaluation.code, "[未対応]")
            material_summary = "none"
            next_level = evaluation.next_level
            if next_level is not None:
                material_summary = ",".join(
                    f"{req.item_id}:{self.inventory_state.get('items', {}).get(req.item_id, 0)}/{req.quantity}"
                    for req in next_level.required_items
                )
            lines.append(
                f"equipment_upgrade_status:{equipment_id}:current_level={evaluation.current_level}:"
                f"max_level={evaluation.max_level}:next_workshop_level={next_level.required_workshop_level if next_level else '-'}:"
                f"required_items={material_summary}:status={state_tag}"
            )
        return lines

    def workshop_salvage_guidance_lines(self) -> list[str]:
        if self.workshop_progress_state.level < 3:
            return [
                "workshop_salvage_guide:不要装備の分解には工房ランクが必要です。",
                "workshop_salvage_guide:rank3で上位装備の分解が解禁されます。",
            ]
        return [
            "workshop_salvage_guide:不要装備を素材へ戻し、クラフトと強化へ再利用できます。",
            "workshop_salvage_guide:強化済み装備は強化段階に応じて追加素材を回収できます。",
        ]

    def workshop_equipment_salvage_lines(self) -> list[str]:
        lines = [
            f"workshop_rank:workshop:{self.workshop_progress_state.level}",
            "equipment_salvage:status",
        ]
        options = self.salvageable_equipment_options()
        if not options:
            lines.append("equipment_salvage:none")
            return lines
        for equipment_id, _ in options:
            upgrade_level = self._equipment_upgrade_service.current_level(equipment_id, self.equipment_upgrade_levels)
            evaluation = self._equipment_salvage_service.evaluate_salvage(
                equipment_id=equipment_id,
                inventory_items=self.inventory_state.get("items", {}),
                workshop_level=self.workshop_progress_state.level,
                equipped_items=tuple(
                    equipped
                    for member in self.party_members
                    for equipped in member.equipped.values()
                    if equipped
                ),
                upgrade_level=upgrade_level,
            )
            definition = self._equipment_salvage_definitions[equipment_id]
            status_tag = {
                "salvageable": "[分解可能]",
                "equipped": "[装備中]",
                "insufficient_workshop_level": "[工房ランク不足]",
                "not_owned": "[未所持]",
            }.get(evaluation.code, "[未対応]")
            resolved_returns = ",".join(f"{item.item_id}:x{item.quantity}" for item in evaluation.returns) or "none"
            lines.append(
                f"equipment_salvage_status:{equipment_id}:required_workshop_level={definition.required_workshop_level}:"
                f"upgrade_level={upgrade_level}:returns={resolved_returns}:status={status_tag}"
            )
        return lines

    def salvageable_equipment_options(self) -> list[tuple[str, str]]:
        options: list[tuple[str, str]] = []
        for equipment_id, definition in sorted(self._equipment_salvage_definitions.items()):
            if not definition.salvage_enabled:
                continue
            owned = int(self.inventory_state.get("items", {}).get(equipment_id, 0))
            if owned <= 0:
                continue
            name = self._equipment_definitions.get(equipment_id).name if equipment_id in self._equipment_definitions else equipment_id
            options.append(
                (
                    equipment_id,
                    f"{name} ({equipment_id}) 所持={owned} 必要工房ランク={definition.required_workshop_level}",
                )
            )
        return options

    def salvage_equipment(self, equipment_id: str) -> list[str]:
        upgrade_level = self._equipment_upgrade_service.current_level(equipment_id, self.equipment_upgrade_levels)
        result = self._equipment_salvage_service.apply_salvage(
            equipment_id=equipment_id,
            inventory_state=self.inventory_state,
            workshop_level=self.workshop_progress_state.level,
            equipped_items=tuple(
                equipped
                for member in self.party_members
                for equipped in member.equipped.values()
                if equipped
            ),
            upgrade_level=upgrade_level,
        )
        if not result.success:
            return [result.message]

        lines = [result.message]
        for reward in result.returns:
            lines.append(f"equipment_salvage_return:{reward.item_id}:x{reward.quantity}")
        if int(self.inventory_state.get("items", {}).get(equipment_id, 0)) <= 0:
            self.equipment_upgrade_levels.pop(equipment_id, None)
        lines.extend(self.workshop_equipment_salvage_lines())
        return lines

    def upgradable_equipment_options(self) -> list[tuple[str, str]]:
        options: list[tuple[str, str]] = []
        for equipment_id, definition in sorted(self._equipment_upgrade_definitions.items()):
            if not definition.upgrade_enabled:
                continue
            owned = int(self.inventory_state.get("items", {}).get(equipment_id, 0))
            if owned <= 0:
                continue
            current_level = self._equipment_upgrade_service.current_level(equipment_id, self.equipment_upgrade_levels)
            max_level = max((level.upgrade_level for level in definition.upgrade_levels), default=0)
            name = self._equipment_definitions.get(equipment_id).name if equipment_id in self._equipment_definitions else equipment_id
            options.append((equipment_id, f"{name} ({equipment_id}) 強化段階 {current_level}/{max_level}"))
        return options

    def upgrade_equipment(self, equipment_id: str) -> list[str]:
        result = self._equipment_upgrade_service.apply_upgrade(
            equipment_id=equipment_id,
            equipment_upgrade_levels=self.equipment_upgrade_levels,
            inventory_state=self.inventory_state,
            workshop_level=self.workshop_progress_state.level,
        )
        lines = [result.message]
        if not result.success:
            return lines
        lines.append(f"upgrade_level:+1:{equipment_id}:current={result.applied_level}")
        lines.extend(self.equipment_overview_lines())
        return lines

    def equip_item(self, character_id: str, slot_type: str, equipment_id: str) -> list[str]:
        result = self._equipment_service.equip_item(
            party_members=self.party_members,
            inventory_state=self.inventory_state,
            character_id=character_id,
            slot_type=slot_type,
            equipment_id=equipment_id,
        )
        lines = [result.message]
        if result.success:
            member = next((m for m in self.party_members if m.character_id == character_id), None)
            if member is not None:
                lines.extend(self._set_bonus_transition_lines(member))
            lines.extend(self.party_member_lines())
        return lines

    def party_member_lines(self) -> list[str]:
        lines: list[str] = []
        for member in self.party_members:
            final = self._equipment_service.resolve_final_stats(member)
            equipped_upgrade_levels = {
                slot: self._equipment_upgrade_service.current_level(equipment_id, self.equipment_upgrade_levels)
                for slot, equipment_id in member.equipped.items()
                if equipment_id
            }
            lines.append(
                f"member:{member.character_id}:lv={member.level}:exp={member.current_exp}/{member.next_level_exp}:"
                f"hp={final['current_hp']}/{final['max_hp']}:sp={final['current_sp']}/{final['max_sp']}:"
                f"atk={final['atk']}:def={final['defense']}:spd={final['spd']}:equipped={member.equipped}:"
                f"equipment_upgrade_levels={equipped_upgrade_levels}:"
                f"effects={[f'{effect.effect_id}:{effect.remaining_turns}' for effect in member.active_effects]}:"
                f"skills={member.unlocked_skill_ids}:"
                f"passives={self._equipment_service.passive_summary(member.equipped)}:"
                f"active_set_bonuses={self._active_set_bonus_labels(member.equipped)}"
            )
        return lines

    def workshop_set_bonus_guidance_lines(self) -> list[str]:
        if not self.party_members or not self._equipment_set_definitions:
            return []
        member = self.party_members[0]
        active_by_set: dict[str, set[int]] = {}
        for bonus in self._equipment_set_service.resolve_active_bonuses(member.equipped):
            active_by_set.setdefault(bonus.set_id, set()).add(bonus.required_piece_count)
        lines: list[str] = []
        for set_definition in self._equipment_set_definitions.values():
            total = len(set_definition.member_equipment_ids)
            active_counts = active_by_set.get(set_definition.set_id, set())
            if total in active_counts:
                lines.append(f"workshop_set_bonus_hint:{set_definition.set_id}:全段階発動中")
                continue
            if active_counts:
                max_active = max(active_counts)
                lines.append(f"workshop_set_bonus_hint:{set_definition.set_id}:{max_active}/{total}部位達成")
                continue
            lines.append(f"workshop_set_bonus_hint:{set_definition.set_id}:未成立")
        return lines

    def _resolve_set_passives(self, equipped: dict[str, str]) -> tuple[EquipmentPassiveDefinition, ...]:
        passives: list[EquipmentPassiveDefinition] = []
        for bonus in self._equipment_set_service.resolve_active_bonuses(equipped):
            if bonus.bonus_type not in {"passive_effect", "status_resistance"}:
                continue
            parameters = dict(bonus.parameters)
            resolved_passive_type = str(
                parameters.get("passive_type") or ("status_resistance" if bonus.bonus_type == "status_resistance" else "")
            )
            if not resolved_passive_type:
                continue
            passives.append(
                EquipmentPassiveDefinition(
                    passive_id=str(parameters.get("passive_id") or f"{bonus.set_id}.{bonus.required_piece_count}"),
                    passive_type=resolved_passive_type,
                    target=str(parameters.get("target", "self")),
                    parameters=dict(parameters.get("parameters", {})),
                    description=bonus.bonus_description,
                )
            )
        return tuple(passives)

    def _active_set_bonus_labels(self, equipped: dict[str, str]) -> list[str]:
        labels: list[str] = []
        for bonus in self._equipment_set_service.resolve_active_bonuses(equipped):
            labels.append(
                f"[{bonus.required_piece_count}部位発動]{bonus.set_name}:{bonus.bonus_type}:{bonus.bonus_description}"
            )
        return labels

    def _active_set_bonus_keys(self, equipped: dict[str, str]) -> set[str]:
        return {
            f"{bonus.set_id}:{bonus.required_piece_count}:{bonus.bonus_type}"
            for bonus in self._equipment_set_service.resolve_active_bonuses(equipped)
        }

    def _set_bonus_transition_lines(self, member: PartyMemberState) -> list[str]:
        previous = self.active_set_bonus_keys_by_member.get(member.character_id, set())
        current = self._active_set_bonus_keys(member.equipped)
        lines: list[str] = []
        for key in sorted(current - previous):
            lines.append(f"set_bonus_activated:{member.character_id}:{key}")
        for key in sorted(previous - current):
            lines.append(f"set_bonus_deactivated:{member.character_id}:{key}")
        self.active_set_bonus_keys_by_member[member.character_id] = set(current)
        return lines

    def _initialize_active_set_bonus_cache(self) -> None:
        self.active_set_bonus_keys_by_member = {
            member.character_id: self._active_set_bonus_keys(member.equipped) for member in self.party_members
        }

    def usable_item_ids(self) -> list[str]:
        items = self.inventory_state.get("items", {})
        ids: list[str] = []
        for item_id, amount in sorted(items.items()):
            definition = self._item_definitions.get(item_id)
            if definition is None:
                continue
            if definition.get("category") != "consumable":
                continue
            if int(amount) <= 0:
                continue
            ids.append(item_id)
        return ids

    def _run_hunt(self) -> list[str]:
        if self.quest_session is None:
            raise ValueError("ゲームが開始されていません。")
        quest_id = self._active_quest_id()
        if quest_id is None:
            return ["hunt_unavailable:no_active_quest"]
        quest_definition = self.quest_session.quest_service.definitions[quest_id]
        current_location = self._travel_service.location(self.location_state.current_location_id)
        if current_location is None:
            return ["hunt_unavailable:unknown_current_location"]
        if current_location.location_type == "town":
            return ["hunt_unavailable:town_location"]

        target_location_id = self._travel_service.resolve_quest_target_location_id(
            quest_definition.encounter_id,
            quest_definition.target_location_id,
        )
        if target_location_id and target_location_id != self.location_state.current_location_id:
            return [f"hunt_unavailable:wrong_location:required={target_location_id}"]
        encounter_id = quest_definition.encounter_id or current_location.default_encounter_id
        if quest_definition.encounter_id and quest_definition.encounter_id not in current_location.available_encounter_ids:
            return [f"hunt_unavailable:encounter_not_in_location:{quest_definition.encounter_id}"]
        if encounter_id is None:
            return ["hunt_unavailable:no_encounter"]

        battle_party = []
        for member in self.party_members:
            final = self._equipment_service.resolve_final_stats(member)
            battle_party.append(
                PartyMemberState(
                    character_id=member.character_id,
                    level=member.level,
                    current_exp=member.current_exp,
                    next_level_exp=member.next_level_exp,
                    max_hp=final["max_hp"],
                    current_hp=final["current_hp"],
                    max_sp=final["max_sp"],
                    current_sp=final["current_sp"],
                    atk=final["atk"],
                    defense=final["defense"],
                    spd=final["spd"],
                    alive=member.alive,
                    equipped=dict(member.equipped),
                    unlocked_skill_ids=list(member.unlocked_skill_ids),
                    active_effects=[effect for effect in member.active_effects],
                )
            )
        pre_battle_logs = [
            f"battle_passives:{member.character_id}:{self._equipment_service.passive_summary(member.equipped)}"
            for member in battle_party
            if self._equipment_service.passive_summary(member.equipped)
        ]
        try:
            battle_result = self._battle_executor(encounter_id, battle_party)
        except TypeError:
            battle_result = self._battle_executor(encounter_id)
        logs = [*pre_battle_logs, f"battle_finished:{encounter_id}:player_won={battle_result.player_won}"]
        for member in battle_party:
            actual = next((m for m in self.party_members if m.character_id == member.character_id), None)
            if actual is None:
                continue
            actual.current_hp = max(0, member.current_hp)
            actual.current_sp = max(0, member.current_sp)
            actual.alive = bool(member.alive and member.current_hp > 0)
            actual.active_effects = [effect for effect in member.active_effects]
        if battle_result.player_won:
            battle_reward = self._battle_rewards.get(encounter_id)
            if battle_reward is not None:
                gained_item_ids = {item.item_id for item in battle_reward.rewards_on_win.items if item.amount > 0}
                logs.extend(self._reward_service.apply(battle_reward.rewards_on_win, self.party_members, self.inventory_state))
                logs.extend(self._apply_recipe_discovery_for_items(gained_item_ids))
        for state in self.quest_session.quest_states.values():
            before = state.status
            self.quest_session.quest_service.apply_battle_result(state, battle_result)
            self._refresh_quest_objective_flags(state.quest_id)
            if before != state.status:
                logs.append(f"quest_status_changed:{state.quest_id}:{state.status.value}")

        self.last_event_id = f"event.system.hunt:{quest_id}"
        self.quest_session.world_flags.add(f"flag.quest.battle_seen:{quest_id}")
        if current_location.can_return_to_hub:
            self.location_state.current_location_id = HUB_LOCATION_ID
            logs.append(f"returned_to_hub:{HUB_LOCATION_ID}")
            logs.extend(self._apply_gathering_respawn("on_return_to_hub"))
            logs.extend(self._apply_repeatable_quest_updates("on_return_to_hub"))
        return logs

    def _apply_gathering_respawn(self, trigger: str) -> list[str]:
        respawned_node_ids = self._gathering_respawn_service.respawn_by_trigger(
            trigger=trigger,
            nodes=self._gathering_nodes,
            gathered_node_ids=self.gathered_node_ids,
        )
        if not respawned_node_ids:
            return [f"gathering_respawned:{trigger}:count=0"]
        lines = [f"gathering_respawned:{trigger}:count={len(respawned_node_ids)}"]
        lines.extend(f"gathering_respawned_node:{trigger}:{node_id}" for node_id in respawned_node_ids)
        return lines

    def _apply_repeatable_quest_updates(self, trigger: str) -> list[str]:
        if self.quest_session is None:
            return []
        ready_ids: list[str] = []
        for quest_id, state in sorted(self.quest_session.quest_states.items()):
            if self.quest_session.quest_service.apply_repeat_reset_trigger(state, trigger):
                ready_ids.append(quest_id)
        if not ready_ids:
            return [f"quest_repeat_ready:{trigger}:count=0"]
        lines = [f"quest_repeat_ready:{trigger}:count={len(ready_ids)}"]
        lines.extend(f"quest_repeat_ready_id:{trigger}:{quest_id}" for quest_id in ready_ids)
        return lines

    def _restore_gathered_node_ids(self, gathering_meta: dict) -> set[str]:
        gathered_node_ids = {str(node_id) for node_id in gathering_meta.get("gathered_node_ids", [])}
        unknown_node_ids = sorted(node_id for node_id in gathered_node_ids if node_id not in self._gathering_nodes)
        if unknown_node_ids:
            raise ValueError(f"save_data has unknown gathered_node_ids={unknown_node_ids}")
        return gathered_node_ids

    def _restore_opened_treasure_node_ids(self, treasure_meta: dict) -> set[str]:
        opened_node_ids = {str(node_id) for node_id in treasure_meta.get("opened_reward_node_ids", [])}
        unknown_node_ids = sorted(node_id for node_id in opened_node_ids if node_id not in self._treasure_nodes)
        if unknown_node_ids:
            raise ValueError(f"save_data has unknown opened_reward_node_ids={unknown_node_ids}")
        return opened_node_ids

    def _restore_defeated_miniboss_ids(self, miniboss_meta: dict) -> set[str]:
        defeated_ids = {str(miniboss_id) for miniboss_id in miniboss_meta.get("defeated_miniboss_ids", [])}
        unknown_ids = sorted(miniboss_id for miniboss_id in defeated_ids if miniboss_id not in self._miniboss_service.definitions)
        if unknown_ids:
            raise ValueError(f"save_data has unknown defeated_miniboss_ids={unknown_ids}")
        return defeated_ids

    def _restore_miniboss_first_clear_reward_claimed_ids(self, miniboss_meta: dict) -> set[str]:
        claimed_ids = {
            str(miniboss_id) for miniboss_id in miniboss_meta.get("first_clear_reward_claimed_ids", [])
        }
        unknown_ids = sorted(miniboss_id for miniboss_id in claimed_ids if miniboss_id not in self._miniboss_service.definitions)
        if unknown_ids:
            raise ValueError(f"save_data has unknown first_clear_reward_claimed_ids={unknown_ids}")
        return claimed_ids

    def _run_on_enter_location_events(self, location_id: str) -> list[str]:
        if self.quest_session is None:
            raise ValueError("ゲームが開始されていません。")
        events = self._location_event_service.resolve_on_enter(
            location_id=location_id,
            world_flags=self.quest_session.world_flags,
            quest_states=self.quest_session.quest_states,
            completed_event_ids=self.completed_location_event_ids,
        )
        lines: list[str] = []
        for event in events:
            lines.append(f"location_event_started:{event.event_id}")
            lines.extend(f"line:narration:{line}" for line in event.dialogue_lines)
            for action in event.actions:
                lines.extend(self._run_location_event_action(action.action_type, action.params))
            if not event.repeatable:
                self.completed_location_event_ids.add(event.event_id)
            self.last_event_id = event.event_id
            lines.append(f"location_event_completed:{event.event_id}")
        return lines

    def _run_location_event_action(self, action_type: str, params: dict[str, str]) -> list[str]:
        if self.quest_session is None:
            raise ValueError("ゲームが開始されていません。")
        if action_type == "set_flag":
            flag_id = params["flag_id"]
            self.quest_session.world_flags.add(flag_id)
            unlocked = self._travel_service.evaluate_unlocks(self.location_state, self.quest_session.world_flags)
            logs = [f"flag_set:{flag_id}"]
            logs.extend(f"location_unlocked:{location_id}" for location_id in unlocked)
            logs.extend(self._evaluate_recipe_unlocks())
            return logs
        if action_type == "unlock_recipe":
            source_id = params.get("source_id") or params.get("event_id") or "dialogue_choice"
            return self._apply_recipe_discovery("dialogue_event", source_id)
        if action_type == "accept_quest":
            return self.accept_quest(params["quest_id"])
        if action_type == "start_battle":
            return self._run_event_battle(params["encounter_id"])
        return [f"location_event_action_skipped:unsupported:{action_type}"]

    def _run_field_event_outcome(
        self,
        outcome_type: str,
        params: dict[str, str],
        *,
        source_event_id: str,
    ) -> list[str]:
        if self.quest_session is None:
            raise ValueError("ゲームが開始されていません。")
        if outcome_type == "show_message":
            return [f"field_event_message:{params.get('message', '')}"]
        if outcome_type == "set_flag":
            flag_id = params.get("flag_id", "")
            if not flag_id:
                return ["field_event_outcome_failed:set_flag_missing_flag_id"]
            self.quest_session.world_flags.add(flag_id)
            logs = [f"flag_set:{flag_id}"]
            logs.extend(f"location_unlocked:{location_id}" for location_id in self._travel_service.evaluate_unlocks(self.location_state, self.quest_session.world_flags))
            logs.extend(self._evaluate_recipe_unlocks())
            return logs
        if outcome_type == "grant_items":
            item_id = params.get("item_id", "")
            if item_id not in self._item_definitions:
                return [f"field_event_outcome_failed:unknown_item_id:{item_id}"]
            amount = int(params.get("amount", "1"))
            if amount <= 0:
                return [f"field_event_outcome_failed:invalid_amount:{amount}"]
            items = self.inventory_state.setdefault("items", {})
            items[item_id] = int(items.get(item_id, 0)) + amount
            logs = [f"field_event_item_granted:{item_id}:x{amount}"]
            logs.extend(self._apply_recipe_discovery_for_items({item_id}))
            logs.extend(self._apply_quest_gather_progress({item_id: amount}))
            return logs
        if outcome_type == "start_battle":
            encounter_id = params.get("encounter_id", "")
            if not encounter_id:
                return ["field_event_outcome_failed:start_battle_missing_encounter_id"]
            return self._run_event_battle(encounter_id)
        if outcome_type == "start_miniboss_battle":
            miniboss_id = params.get("miniboss_id", "")
            if not miniboss_id:
                return ["field_event_outcome_failed:start_miniboss_missing_miniboss_id"]
            return self._run_miniboss_battle(miniboss_id=miniboss_id, source_event_id=source_event_id)
        if outcome_type == "apply_effect_to_party":
            effect_id = params.get("effect_id", "")
            if effect_id not in self._status_effect_definitions:
                return [f"field_event_outcome_failed:unknown_effect_id:{effect_id}"]
            turns = int(params.get("remaining_turns", "2"))
            for member in self.party_members:
                member.active_effects = [effect for effect in member.active_effects if effect.effect_id != effect_id]
                member.active_effects.append(PartyActiveEffectState(effect_id=effect_id, remaining_turns=turns))
            return [f"field_event_effect_applied:{effect_id}:turns={turns}:targets={len(self.party_members)}"]
        if outcome_type == "unlock_treasure_node":
            reward_node_id = params.get("reward_node_id", "")
            if reward_node_id not in self._treasure_nodes:
                return [f"field_event_outcome_failed:unknown_treasure_node:{reward_node_id}"]
            unlock_flag = params.get("flag_id") or f"flag.treasure.unlocked:{reward_node_id}"
            self.quest_session.world_flags.add(unlock_flag)
            return [f"field_event_treasure_unlocked:{reward_node_id}:{unlock_flag}"]
        return [f"field_event_outcome_skipped:unsupported:{outcome_type}"]

    def _run_miniboss_battle(self, *, miniboss_id: str, source_event_id: str) -> list[str]:
        if self.quest_session is None:
            raise ValueError("ゲームが開始されていません。")
        start = self._miniboss_service.resolve_start(
            miniboss_id=miniboss_id,
            trigger_event_id=source_event_id,
            location_id=self.location_state.current_location_id,
            defeated_miniboss_ids=self.defeated_miniboss_ids,
        )
        if not start.success:
            return [start.code]
        if start.definition is None:
            return ["miniboss_failed:definition_error"]

        logs = [
            f"miniboss_encounter_started:{start.definition.miniboss_id}:{start.definition.encounter_id}:{start.definition.display_name}"
        ]
        battle_logs = self._run_event_battle(start.definition.encounter_id)
        logs.extend(battle_logs)

        if not any(
            line == f"battle_finished:{start.definition.encounter_id}:player_won=True"
            for line in battle_logs
        ):
            return logs

        self.defeated_miniboss_ids.add(start.definition.miniboss_id)
        self.quest_session.world_flags.add(start.definition.defeat_flag)
        logs.append(f"miniboss_defeated:{start.definition.miniboss_id}:{start.definition.defeat_flag}")

        reward_resolution = self._miniboss_service.resolve_rewards(
            definition=start.definition,
            is_first_clear=start.is_first_clear,
            first_clear_reward_claimed_ids=self.miniboss_first_clear_reward_claimed_ids,
        )
        if reward_resolution.grant_first_clear:
            self.miniboss_first_clear_reward_claimed_ids.add(start.definition.miniboss_id)

        if reward_resolution.items:
            items = self.inventory_state.setdefault("items", {})
            for reward in reward_resolution.items:
                items[reward.item_id] = int(items.get(reward.item_id, 0)) + reward.amount
            logs.extend(reward_resolution.logs)
            logs.extend(self._apply_recipe_discovery_for_items({reward.item_id for reward in reward_resolution.items}))
        else:
            logs.extend(reward_resolution.logs)
        return logs

    def _evaluate_recipe_unlocks(self) -> list[str]:
        if self.quest_session is None:
            return []
        unlocked_recipe_ids = self._recipe_unlock_service.evaluate_and_apply_unlocks(
            recipes=self._crafting_recipes,
            unlocked_recipe_ids=self.unlocked_recipe_ids,
            world_flags=self.quest_session.world_flags,
            completed_quest_ids=self._completed_quest_ids(),
            current_location_id=self.location_state.current_location_id,
        )
        logs: list[str] = []
        for recipe_id in unlocked_recipe_ids:
            recipe = self._crafting_recipes[recipe_id]
            unlock_message = recipe.unlock_message or f"recipe_unlocked:{recipe_id}"
            logs.append(f"recipe_unlocked:{recipe_id}:{unlock_message}")
            if recipe.recipe_tier == "advanced":
                logs.append(f"advanced_recipe_unlocked:{recipe_id}")
            self.discovered_recipe_ids.add(recipe_id)
        return logs

    def _completed_quest_ids(self) -> set[str]:
        if self.quest_session is None:
            return set()
        return {
            quest_id
            for quest_id, state in self.quest_session.quest_states.items()
            if state.status == QuestStatus.COMPLETED
        }

    def _run_event_battle(self, encounter_id: str) -> list[str]:
        if self.quest_session is None:
            raise ValueError("ゲームが開始されていません。")
        battle_party = []
        for member in self.party_members:
            final = self._equipment_service.resolve_final_stats(member)
            battle_party.append(
                PartyMemberState(
                    character_id=member.character_id,
                    level=member.level,
                    current_exp=member.current_exp,
                    next_level_exp=member.next_level_exp,
                    max_hp=final["max_hp"],
                    current_hp=final["current_hp"],
                    max_sp=final["max_sp"],
                    current_sp=final["current_sp"],
                    atk=final["atk"],
                    defense=final["defense"],
                    spd=final["spd"],
                    alive=member.alive,
                    equipped=dict(member.equipped),
                    unlocked_skill_ids=list(member.unlocked_skill_ids),
                    active_effects=[effect for effect in member.active_effects],
                )
            )
        try:
            battle_result = self._battle_executor(encounter_id, battle_party)
        except TypeError:
            battle_result = self._battle_executor(encounter_id)
        logs = [f"battle_finished:{encounter_id}:player_won={battle_result.player_won}"]
        for member in battle_party:
            actual = next((m for m in self.party_members if m.character_id == member.character_id), None)
            if actual is None:
                continue
            actual.current_hp = max(0, member.current_hp)
            actual.current_sp = max(0, member.current_sp)
            actual.alive = bool(member.alive and member.current_hp > 0)
            actual.active_effects = [effect for effect in member.active_effects]
        if battle_result.player_won:
            battle_reward = self._battle_rewards.get(encounter_id)
            if battle_reward is not None:
                logs.extend(self._reward_service.apply(battle_reward.rewards_on_win, self.party_members, self.inventory_state))
                gained_item_ids = {item.item_id for item in battle_reward.rewards_on_win.items if item.amount > 0}
                logs.extend(self._apply_recipe_discovery_for_items(gained_item_ids))
        for state in self.quest_session.quest_states.values():
            before = state.status
            self.quest_session.quest_service.apply_battle_result(state, battle_result)
            self._refresh_quest_objective_flags(state.quest_id)
            if before != state.status:
                logs.append(f"quest_status_changed:{state.quest_id}:{state.status.value}")
        return logs

    def _build_session(self) -> QuestSliceSession:
        return QuestSliceSession(
            quest_service=QuestProgressService(self._quest_board_service.definitions),
            events=self._quest_repo.load_events(),
            battle_executor=self._battle_executor,
        )

    def _build_initial_party(self) -> list[PartyMemberState]:
        return [
            PartyMemberState(
                character_id="char.main.rion",
                level=8,
                current_exp=0,
                next_level_exp=450,
                max_hp=120,
                current_hp=120,
                max_sp=100,
                current_sp=100,
                atk=24,
                defense=16,
                spd=18,
                alive=True,
                equipped={"weapon": "equip.weapon.bronze_blade"},
                unlocked_skill_ids=list(self._skill_learning_service.initial_skill_ids_for_character("char.main.rion")),
            )
        ]

    def _status_lines(self) -> list[str]:
        if self.quest_session is None:
            raise ValueError("ゲームが開始されていません。")

        lines = [
            f"location:{self.location_state.current_location_id}",
            f"party_members:{len(self.party_members)}",
            f"last_event_id:{self.last_event_id}",
            f"gold:{self.inventory_state.get('gold', 0)}",
            f"world_flags:{sorted(self.quest_session.world_flags)}",
        ]
        lines.extend(self.party_member_lines())
        lines.extend(self._quest_lines())
        return lines

    def _inventory_lines(self) -> list[str]:
        items = self.inventory_state.get("items", {})
        lines = [f"gold:{self.inventory_state.get('gold', 0)}"]
        if not items:
            lines.append("inventory:none")
            return lines
        for item_id, amount in sorted(items.items()):
            item_name = self._item_definitions.get(item_id, {}).get("name", item_id)
            lines.append(f"item:{item_id}:{item_name}:x{amount}")
        return lines

    def _usable_item_lines(self) -> list[str]:
        item_ids = self.usable_item_ids()
        if not item_ids:
            return ["usable_item:none"]

        lines: list[str] = []
        items = self.inventory_state.get("items", {})
        for item_id in item_ids:
            definition = self._item_definitions[item_id]
            lines.append(
                f"usable_item:{item_id}:{definition.get('name', item_id)}:stock={items.get(item_id, 0)}:"
                f"effect={definition.get('effect_type')}:{definition.get('effect_value')}"
            )
        return lines

    def _quest_lines(self) -> list[str]:
        if self.quest_session is None:
            raise ValueError("ゲームが開始されていません。")
        if not self.quest_session.quest_states:
            return ["quest:none"]

        lines: list[str] = []
        for quest_id, state in sorted(self.quest_session.quest_states.items()):
            lines.append(
                f"quest:{quest_id}:status={state.status.value}:progress={state.objective_progress}:"
                f"reward_claimed={state.reward_claimed}"
            )
            current_objective_id = self.quest_session.quest_service.active_objective_id(state)
            lines.append(f"current_objective:{quest_id}:{current_objective_id or 'none'}")
            definition = self.quest_session.quest_service.definitions[quest_id]
            for objective in definition.objectives:
                if objective.objective_type != "turn_in_items":
                    continue
                for item_id, required in objective.required_items:
                    owned = int(self.inventory_state.get("items", {}).get(item_id, 0))
                    submitted = int(state.objective_item_progress.get(objective.id, {}).get(item_id, 0))
                    lines.append(
                        f"quest_turn_in:{quest_id}:{objective.id}:{item_id}:owned={owned}:"
                        f"submitted={submitted}/{required}"
                    )
        return lines

    def _party_level(self) -> int:
        if not self.party_members:
            return 1
        return max(member.level for member in self.party_members)

    def _active_quest_id(self) -> str | None:
        if self.quest_session is None:
            return None
        for quest_id, state in sorted(self.quest_session.quest_states.items()):
            if state.status == QuestStatus.IN_PROGRESS:
                return quest_id
        return None

    def _ready_to_complete_quest_id(self) -> str | None:
        if self.quest_session is None:
            return None
        for quest_id, state in sorted(self.quest_session.quest_states.items()):
            if state.status == QuestStatus.READY_TO_COMPLETE:
                return quest_id
        return None

    def _has_active_quest(self) -> bool:
        return self._active_quest_id() is not None

    def _location_can_hunt(self) -> bool:
        current = self._travel_service.location(self.location_state.current_location_id)
        if current is None:
            return False
        return current.location_type != "town"

    def _has_reportable_quest(self) -> bool:
        return self._ready_to_complete_quest_id() is not None

    def quest_state(self, quest_id: str = "quest.ch01.missing_port_record") -> QuestState | None:
        if self.quest_session is None:
            return None
        return self.quest_session.quest_states.get(quest_id)

    def _complete_quest(self, quest_id: str) -> list[str]:
        if self.quest_session is None:
            raise ValueError("ゲームが開始されていません。")
        state = self.quest_session.quest_states.get(quest_id)
        if state is None:
            return [f"report_failed:quest_not_found:{quest_id}"]
        if state.status != QuestStatus.READY_TO_COMPLETE:
            return [f"report_failed:not_ready:{quest_id}"]

        self.quest_session.quest_service.complete(state)
        self._refresh_quest_objective_flags(quest_id)
        self._increment_turn_in_completion_count(quest_id)
        quest_reward = self.quest_session.quest_service.definitions[quest_id].reward
        logs = [f"quest_completed:{quest_id}"]
        logs.extend(
            self._reward_service.apply(
                self._reward_service.from_quest_reward(quest_reward),
                self.party_members,
                self.inventory_state,
            )
        )
        gained_item_ids = {item_id for item_id, amount in quest_reward.items if amount > 0}
        logs.extend(self._apply_recipe_discovery_for_items(gained_item_ids))
        logs.extend(self._apply_recipe_discovery("quest_complete", quest_id))
        if quest_reward.completion_flag:
            self.quest_session.world_flags.add(quest_reward.completion_flag)
            logs.append(f"flag_set:{quest_reward.completion_flag}")
        for unlocked in self._travel_service.evaluate_unlocks(self.location_state, self.quest_session.world_flags):
            logs.append(f"location_unlocked:{unlocked}")
        logs.extend(self._evaluate_facility_progression())
        logs.extend(self._apply_workshop_order_progress(quest_id))
        logs.extend(self._evaluate_recipe_unlocks())
        if state.repeat_ready:
            logs.append(f"quest_repeat_ready:manual_reaccept:{quest_id}")
        self.last_event_id = f"event.system.quest_report:{quest_id}"
        return logs

    def _refresh_all_quest_objective_flags(self) -> None:
        if self.quest_session is None:
            return
        for quest_id in sorted(self.quest_session.quest_states):
            self._refresh_quest_objective_flags(quest_id)

    def _apply_recipe_discovery(self, unlock_source_type: str, source_id: str) -> list[str]:
        before = set(self.discovered_recipe_ids)
        discovered, already_known, warnings = self._recipe_discovery_service.discover_by_source(
            unlock_source_type=unlock_source_type,
            source_id=source_id,
            discovered_recipe_ids=self.discovered_recipe_ids,
            discovered_recipe_book_ids=self.discovered_recipe_book_ids,
            unlocked_recipe_ids=self.unlocked_recipe_ids,
        )
        logs = [*discovered, *already_known, *warnings]
        new_recipes = self.discovered_recipe_ids - before
        logs.extend(self._apply_quest_recipe_discovery_progress(new_recipes))
        return logs

    def _apply_recipe_discovery_for_items(self, gained_item_ids: set[str]) -> list[str]:
        if not gained_item_ids:
            return []
        before = set(self.discovered_recipe_ids)
        discovered, already_known, warnings = self._recipe_discovery_service.discover_from_items(
            gained_item_ids=gained_item_ids,
            discovered_recipe_ids=self.discovered_recipe_ids,
            discovered_recipe_book_ids=self.discovered_recipe_book_ids,
            unlocked_recipe_ids=self.unlocked_recipe_ids,
        )
        logs = [*discovered, *already_known, *warnings]
        new_recipes = self.discovered_recipe_ids - before
        logs.extend(self._apply_quest_recipe_discovery_progress(new_recipes))
        return logs

    def _apply_quest_gather_progress(self, gained_items: dict[str, int]) -> list[str]:
        if self.quest_session is None:
            return []
        logs: list[str] = []
        for quest_id, state in sorted(self.quest_session.quest_states.items()):
            progress_logs = self.quest_session.quest_service.apply_gather_item_progress(state, gained_items)
            if not progress_logs:
                continue
            logs.extend(progress_logs)
            self._refresh_quest_objective_flags(quest_id)
        return logs

    def _apply_quest_recipe_discovery_progress(self, discovered_recipe_ids: set[str]) -> list[str]:
        if self.quest_session is None or not discovered_recipe_ids:
            return []
        logs: list[str] = []
        for quest_id, state in sorted(self.quest_session.quest_states.items()):
            progress_logs = self.quest_session.quest_service.apply_recipe_discovery_progress(state, discovered_recipe_ids)
            if not progress_logs:
                continue
            logs.extend(progress_logs)
            self._refresh_quest_objective_flags(quest_id)
        return logs

    def _apply_quest_craft_progress(self, crafted_items: dict[str, int]) -> list[str]:
        if self.quest_session is None:
            return []
        logs: list[str] = []
        for quest_id, state in sorted(self.quest_session.quest_states.items()):
            progress_logs = self.quest_session.quest_service.apply_craft_item_progress(state, crafted_items)
            if not progress_logs:
                continue
            logs.extend(progress_logs)
            self._refresh_quest_objective_flags(quest_id)
        return logs

    def _refresh_quest_objective_flags(self, quest_id: str) -> None:
        if self.quest_session is None:
            return
        state = self.quest_session.quest_states.get(quest_id)
        if state is None:
            return
        prefixes = (
            f"flag.quest.objective.active:{quest_id}:",
            f"flag.quest.objective.completed:{quest_id}:",
        )
        for flag_id in list(self.quest_session.world_flags):
            if flag_id.startswith(prefixes):
                self.quest_session.world_flags.discard(flag_id)
        active_objective_id = self.quest_session.quest_service.active_objective_id(state)
        if active_objective_id:
            self.quest_session.world_flags.add(f"flag.quest.objective.active:{quest_id}:{active_objective_id}")
        for objective_id in self.quest_session.quest_service.completed_objective_ids(state):
            self.quest_session.world_flags.add(f"flag.quest.objective.completed:{quest_id}:{objective_id}")

    def _initialize_facility_state(self) -> None:
        if self.quest_session is None:
            return
        for facility_id, definition in self._facility_definitions.items():
            current_level = int(self.facility_levels.get(facility_id, 0))
            if current_level <= 0:
                current_level = 1
                self.facility_levels[facility_id] = current_level
            for level_definition in definition.levels:
                if level_definition.level > current_level:
                    break
                for recipe_id in level_definition.unlocks.recipe_ids:
                    self.facility_unlocked_recipe_ids.add(recipe_id)
                for stock_id in level_definition.unlocks.shop_stock_ids:
                    self.facility_unlocked_shop_stock_ids.add(stock_id)
                for flag_id in level_definition.unlocks.dialogue_flags:
                    self.quest_session.world_flags.add(flag_id)

    def _evaluate_facility_progression(self) -> list[str]:
        if self.quest_session is None or not self._facility_definitions:
            return []
        context = FacilityProgressContext(
            completed_quest_ids=self._completed_quest_ids(),
            world_flags=self.quest_session.world_flags,
            turn_in_count=self.turn_in_completion_count,
        )
        level_up_results = self._facility_progress_service.evaluate_level_up(
            definitions=self._facility_definitions,
            facility_levels=self.facility_levels,
            context=context,
        )
        return self._facility_progress_service.apply_unlocks(
            level_up_results=level_up_results,
            unlocked_recipe_ids=self.facility_unlocked_recipe_ids,
            unlocked_shop_stock_ids=self.facility_unlocked_shop_stock_ids,
            world_flags=self.quest_session.world_flags,
        )


    def _initialize_workshop_progress_state(self) -> None:
        self._workshop_progress_service.ensure_initial_unlocks(
            state=self.workshop_progress_state,
            rank_definitions=self._workshop_rank_definitions,
        )
        if self.quest_session is None:
            return
        self.quest_session.world_flags.add(f"flag.workshop.rank.{self.workshop_progress_state.level}")

    def _apply_workshop_order_progress(self, quest_id: str) -> list[str]:
        order = self._workshop_order_definitions.get(quest_id)
        if order is None:
            return []
        completion_index = self.workshop_order_completion_counts.get(quest_id, 0) + 1
        marker = f"{quest_id}:{completion_index}"
        logs = self._workshop_progress_service.apply_order_completion(
            state=self.workshop_progress_state,
            order=order,
            rank_definitions=self._workshop_rank_definitions,
            completion_marker=marker,
        )
        if not any(line.startswith("workshop_progress_skipped:duplicate_completion") for line in logs):
            self.workshop_order_completion_counts[quest_id] = completion_index
            if self.quest_session is not None:
                self.quest_session.world_flags.add(f"flag.workshop.rank.{self.workshop_progress_state.level}")
        return logs

    def workshop_progress_lines(self) -> list[str]:
        next_rank, remain = self._workshop_progress_service.progress_to_next_rank(
            state=self.workshop_progress_state,
            rank_definitions=self._workshop_rank_definitions,
        )
        lines = [
            f"workshop_progress:rank={self.workshop_progress_state.level}:total={self.workshop_progress_state.progress}",
        ]
        if next_rank is None:
            lines.append("workshop_progress_next:max_rank")
        else:
            lines.append(f"workshop_progress_next:rank={next_rank}:remaining={remain}")
        for order_id, order in sorted(self._workshop_order_definitions.items()):
            completed = self.workshop_order_completion_counts.get(order_id, 0)
            lines.append(
                f"workshop_order:{order_id}:{order.name}:repeatable={order.repeatable}:"
                f"progress_value={order.workshop_progress_value}:completed={completed}"
            )
        lines.append(f"workshop_unlocked_recipes:{sorted(self.workshop_progress_state.unlocked_recipe_ids)}")
        return lines

    def _is_recipe_unlocked_by_workshop_rank(self, recipe_id: str) -> bool:
        recipe = self._crafting_recipes.get(recipe_id)
        if recipe is None:
            return False
        unlocked_by_rank_table = self._workshop_progress_service.is_recipe_unlocked(
            recipe_id=recipe_id,
            state=self.workshop_progress_state,
            rank_definitions=self._workshop_rank_definitions,
        )
        return unlocked_by_rank_table and self.workshop_progress_state.level >= recipe.required_workshop_level

    def _is_recipe_discovery_requirement_met(self, recipe: CraftingRecipeDefinition) -> bool:
        if not recipe.required_recipe_discovery:
            return True
        key = recipe.required_recipe_discovery
        return key in self.discovered_recipe_ids or key in self.discovered_recipe_book_ids or key in self.unlocked_recipe_ids

    def _recipe_requires_miniboss_material(self, recipe: CraftingRecipeDefinition) -> bool:
        return any(".miniboss." in ingredient.item_id for ingredient in recipe.ingredients)

    def _crafting_state_tag(
        self,
        *,
        unlocked: bool,
        discovery_requirement_met: bool,
        rank_unlocked: bool,
        material_ready: bool,
    ) -> str:
        if not unlocked or not discovery_requirement_met:
            return "[未発見]"
        if not rank_unlocked:
            return "[工房ランク不足]"
        if not material_ready:
            return "[素材不足]"
        return "[作成可能]"

    def _is_recipe_unlocked_by_facility(self, recipe_id: str) -> bool:
        if recipe_id in self.facility_unlocked_recipe_ids:
            return True
        return recipe_id not in self._facility_recipe_lock_targets()

    def _facility_recipe_lock_targets(self) -> set[str]:
        recipe_ids: set[str] = set()
        for definition in self._facility_definitions.values():
            for level_definition in definition.levels:
                recipe_ids.update(level_definition.unlocks.recipe_ids)
        return recipe_ids

    def _available_shop_entries(self, shop) -> tuple:
        lock_targets = self._facility_shop_lock_targets()
        if not lock_targets:
            return shop.entries
        return tuple(
            entry
            for entry in shop.entries
            if entry.item_id not in lock_targets or entry.item_id in self.facility_unlocked_shop_stock_ids
        )

    def _facility_shop_lock_targets(self) -> set[str]:
        stock_ids: set[str] = set()
        for definition in self._facility_definitions.values():
            for level_definition in definition.levels:
                stock_ids.update(level_definition.unlocks.shop_stock_ids)
        return stock_ids

    def _increment_turn_in_completion_count(self, quest_id: str) -> None:
        if self.quest_session is None:
            return
        definition = self.quest_session.quest_service.definitions.get(quest_id)
        if definition is None:
            return
        if any(objective.objective_type == "turn_in_items" for objective in definition.objectives):
            self.turn_in_completion_count += 1
