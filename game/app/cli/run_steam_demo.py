from __future__ import annotations

import argparse
from pathlib import Path
from typing import Callable, TypeVar

from game.app.application.demo_flow_service import DemoFlowService, SteamDemoApplication
from game.app.application.playable_slice import PlayableSliceApplication
from game.app.cli import run_game_slice as base_cli
from game.app.cli.economy_facility_cli import (
    run_crafting_controller,
    run_inn_controller,
    run_shop_controller,
)
from game.app.cli.equipment_workshop_cli import (
    run_equipment_salvage_controller,
    run_equipment_upgrade_controller,
)
from game.app.cli.item_equipment_cli import (
    run_equipment_controller,
    run_item_use_controller,
)
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
    GatheringScreenViewModel,
    TreasureScreenController,
    TreasureScreenViewModel,
)
from game.app.presentation.item_equipment_screen import (
    EquipmentScreenController,
    ItemUseScreenController,
)
from game.app.presentation.menu_view_model import SteamDemoMenuViewModel
from game.app.presentation.npc_field_event_screen import (
    FieldEventScreenController,
    FieldEventScreenMode,
    FieldEventScreenViewModel,
    NpcDialogueScreenController,
    NpcDialogueScreenMode,
    NpcDialogueScreenViewModel,
)
from game.app.presentation.quest_travel_screen import (
    QuestBoardScreenController,
    QuestBoardScreenViewModel,
    TravelScreenController,
    TravelScreenViewModel,
)
from game.app.presentation.screen_router import (
    RouteTransitionKind,
    SteamDemoRouteId,
)
from game.app.presentation.screen_runtime import (
    SteamDemoRouteScreenProtocol,
    SteamDemoScreenRuntime,
)
from game.app.steam_demo_composition import SteamDemoCompositionRoot


DEFAULT_FLOW_ID = "demo.steam.ch01.core_loop"
MASTER_ROOT = Path("data/master")

ControllerT = TypeVar("ControllerT")
CLIRouteHandler = Callable[[SteamDemoRouteScreenProtocol], list[str]]


def _print_lines(lines: list[str]) -> None:
    for line in lines:
        print(f"- {line}")


def _print_menu_view(view: SteamDemoMenuViewModel) -> None:
    print(f"- demo_menu_progress:{view.progress_label}")
    print(f"- demo_menu_objective:{view.objective_title}:{view.objective_text}")


def _menu_choices(view: SteamDemoMenuViewModel) -> list[tuple[str, str]]:
    choices: list[tuple[str, str]] = []
    for item in view.items:
        suffix = " [推奨]" if item.is_recommended else ""
        choices.append((item.action_id, f"{item.label}{suffix}"))
    return choices


def _require_controller(
    route_screen: SteamDemoRouteScreenProtocol,
    expected_type: type[ControllerT],
) -> ControllerT:
    controller = route_screen.controller
    if not isinstance(controller, expected_type):
        raise TypeError(
            "cli_route_controller_mismatch:"
            f"{route_screen.route_id.value}:expected={expected_type.__name__}:"
            f"actual={type(controller).__name__}"
        )
    return controller


def _print_quest_board_view(view: QuestBoardScreenViewModel) -> None:
    print(
        f"- quest_board:active={view.active_quest_count}/{view.max_active_quests}:"
        f"entries={len(view.entries)}"
    )
    for entry in view.entries:
        print(
            f"- quest:{entry.quest_id}:{entry.title}:status={entry.status_label}:"
            f"can_accept={entry.can_accept}:progress={entry.progress_label}"
        )


def _run_quest_board_screen(route_screen: SteamDemoRouteScreenProtocol) -> list[str]:
    controller = _require_controller(route_screen, QuestBoardScreenController)
    view = controller.current_view()
    _print_quest_board_view(view)

    choices = [("cancel", "受注しない")]
    choices.extend(
        (entry.quest_id, f"{entry.title} [{entry.status_label}]")
        for entry in view.entries
        if entry.can_accept
    )
    if len(choices) == 1:
        return ["quest_board:no_accept_available"]

    selected = base_cli._choose(choices)
    if selected == "cancel":
        return ["quest_accept_cancelled"]
    return list(controller.activate_quest(selected).logs)


def _print_travel_view(view: TravelScreenViewModel) -> None:
    print(
        f"- current_location:{view.current_location_id}:{view.current_location_name}:"
        f"destinations={len(view.destinations)}"
    )
    for destination in view.destinations:
        print(
            f"- destination:{destination.location_id}:{destination.name}:"
            f"type={destination.location_type}"
        )


def _run_travel_screen(route_screen: SteamDemoRouteScreenProtocol) -> list[str]:
    controller = _require_controller(route_screen, TravelScreenController)
    view = controller.current_view()
    _print_travel_view(view)

    choices = [("cancel", "移動しない")]
    choices.extend(
        (
            destination.location_id,
            f"{destination.name} [{destination.location_type}]",
        )
        for destination in view.destinations
    )
    if len(choices) == 1:
        return ["travel_failed:no_destination"]

    selected = base_cli._choose(choices)
    if selected == "cancel":
        return ["travel_cancelled"]
    return list(controller.activate_destination(selected).logs)


def _print_npc_dialogue_view(view: NpcDialogueScreenViewModel) -> None:
    if view.mode == NpcDialogueScreenMode.NPC_LIST:
        print(f"- npc_list:count={len(view.npcs)}")
        for npc in view.npcs:
            print(f"- npc:{npc.npc_id}:{npc.npc_name}:location={npc.location_id}")
        return

    dialogue = view.dialogue
    if dialogue is None:
        return
    print(
        f"- dialogue:{dialogue.npc_id}:{dialogue.npc_name}:"
        f"entry={dialogue.entry_id or 'fallback'}:step={dialogue.step_id or 'completed'}"
    )
    for line in dialogue.lines:
        print(f"- line:{dialogue.speaker or dialogue.npc_name}:{line}")
    for choice in dialogue.choices:
        print(f"- choice:{choice.choice_id}:{choice.text}")


def _run_npc_dialogue_screen(route_screen: SteamDemoRouteScreenProtocol) -> list[str]:
    controller = _require_controller(route_screen, NpcDialogueScreenController)
    view = controller.current_view()
    _print_npc_dialogue_view(view)
    if not view.npcs:
        return ["dialogue_unavailable:no_npc"]

    npc_choices = [("cancel", "話しかけない")]
    npc_choices.extend((npc.npc_id, npc.npc_name) for npc in view.npcs)
    selected_npc = base_cli._choose(npc_choices)
    if selected_npc == "cancel":
        return ["dialogue_cancelled"]

    interaction = controller.activate_npc(selected_npc)
    logs = list(interaction.logs)
    while interaction.view.mode == NpcDialogueScreenMode.DIALOGUE:
        _print_npc_dialogue_view(interaction.view)
        dialogue = interaction.view.dialogue
        if dialogue is None or dialogue.completed or not dialogue.choices:
            break
        choice_options = [("cancel", "会話をやめる")]
        choice_options.extend(
            (choice.choice_id, choice.text)
            for choice in dialogue.choices
        )
        selected_choice = base_cli._choose(choice_options)
        if selected_choice == "cancel":
            logs.append("dialogue_cancelled")
            break
        interaction = controller.activate_choice(selected_choice)
        logs.extend(interaction.logs)
        if interaction.rejection_reason is not None:
            break
    return logs


def _print_field_event_view(view: FieldEventScreenViewModel) -> None:
    if view.mode == FieldEventScreenMode.EVENT_LIST:
        print(f"- field_event_list:count={len(view.events)}")
        for event in view.events:
            print(
                f"- field_event:{event.event_id}:{event.name}:"
                f"can_execute={event.can_execute}:completed={event.is_completed}:"
                f"repeatable={event.repeatable}:reason={event.reason_code}"
            )
            print(f"- field_event_desc:{event.event_id}:{event.description}")
        return

    detail = view.detail
    if detail is None:
        return
    print(
        f"- field_event_detail:{detail.event_id}:{detail.name}:"
        f"repeatable={detail.repeatable}:completed={detail.is_completed}"
    )
    print(f"- field_event_desc:{detail.event_id}:{detail.description}")
    for choice in detail.choices:
        print(f"- field_event_choice:{choice.choice_id}:{choice.text}")


def _run_field_event_screen(route_screen: SteamDemoRouteScreenProtocol) -> list[str]:
    controller = _require_controller(route_screen, FieldEventScreenController)
    view = controller.current_view()
    _print_field_event_view(view)
    executable = [event for event in view.events if event.can_execute]
    if not executable:
        return ["field_event_unavailable:no_executable_event"]

    event_options = [("cancel", "探索イベントを実行しない")]
    event_options.extend((event.event_id, event.name) for event in executable)
    selected_event = base_cli._choose(event_options)
    if selected_event == "cancel":
        return ["field_event_cancelled"]

    detail_interaction = controller.activate_event(selected_event)
    if detail_interaction.rejection_reason is not None:
        return list(detail_interaction.logs)
    _print_field_event_view(detail_interaction.view)
    detail = detail_interaction.view.detail
    if detail is None or not detail.choices:
        return [f"field_event_unavailable:no_choice:{selected_event}"]

    choice_options = [("cancel", "このイベントをやめる")]
    choice_options.extend(
        (choice.choice_id, choice.text)
        for choice in detail.choices
    )
    selected_choice = base_cli._choose(choice_options)
    if selected_choice == "cancel":
        return ["field_event_cancelled"]
    return list(controller.activate_choice(selected_choice).logs)


def _print_gathering_view(view: GatheringScreenViewModel) -> None:
    print(
        f"- gathering_nodes:location={view.current_location_id}:"
        f"count={len(view.nodes)}"
    )
    for node in view.nodes:
        print(
            f"- gathering_node:{node.node_id}:{node.name}:type={node.node_type}:"
            f"can_gather={node.can_gather}:gathered={node.is_gathered}:"
            f"reason={node.reason_code}:respawn_rule={node.respawn_rule}"
        )
        print(f"- gathering_desc:{node.node_id}:{node.description}")
        if node.respawn_description:
            print(f"- gathering_respawn:{node.node_id}:{node.respawn_description}")


def _run_gathering_screen(route_screen: SteamDemoRouteScreenProtocol) -> list[str]:
    controller = _require_controller(route_screen, GatheringScreenController)
    view = controller.current_view()
    _print_gathering_view(view)
    available = [node for node in view.nodes if node.can_gather]
    if not available:
        return ["gather_failed:no_available_node"]

    choices = [("cancel", "採取しない")]
    choices.extend(
        (node.node_id, f"{node.name} [{node.node_type}]")
        for node in available
    )
    selected = base_cli._choose(choices)
    if selected == "cancel":
        return ["gather_cancelled"]
    return list(controller.activate_node(selected).logs)


def _print_treasure_view(view: TreasureScreenViewModel) -> None:
    print(
        f"- treasure_nodes:location={view.current_location_id}:"
        f"count={len(view.nodes)}"
    )
    for node in view.nodes:
        print(
            f"- treasure_node:{node.reward_node_id}:{node.name}:type={node.node_type}:"
            f"can_open={node.can_open}:opened={node.is_opened}:"
            f"one_time={node.one_time}:reason={node.reason_code}"
        )
        print(f"- treasure_desc:{node.reward_node_id}:{node.description}")


def _run_treasure_screen(route_screen: SteamDemoRouteScreenProtocol) -> list[str]:
    controller = _require_controller(route_screen, TreasureScreenController)
    view = controller.current_view()
    _print_treasure_view(view)
    openable = [node for node in view.nodes if node.can_open]
    if not openable:
        return ["treasure_open_failed:no_openable_node"]

    choices = [("cancel", "調べない")]
    choices.extend(
        (node.reward_node_id, f"{node.name} [{node.node_type}]")
        for node in openable
    )
    selected = base_cli._choose(choices)
    if selected == "cancel":
        return ["treasure_open_cancelled"]
    return list(controller.activate_node(selected).logs)


def _run_item_use_screen(route_screen: SteamDemoRouteScreenProtocol) -> list[str]:
    return run_item_use_controller(
        _require_controller(route_screen, ItemUseScreenController)
    )


def _run_equipment_screen(route_screen: SteamDemoRouteScreenProtocol) -> list[str]:
    return run_equipment_controller(
        _require_controller(route_screen, EquipmentScreenController)
    )


def _run_shop_screen(route_screen: SteamDemoRouteScreenProtocol) -> list[str]:
    return run_shop_controller(_require_controller(route_screen, ShopScreenController))


def _run_equipment_upgrade_screen(
    route_screen: SteamDemoRouteScreenProtocol,
) -> list[str]:
    return run_equipment_upgrade_controller(
        _require_controller(route_screen, EquipmentUpgradeScreenController)
    )


def _run_equipment_salvage_screen(
    route_screen: SteamDemoRouteScreenProtocol,
) -> list[str]:
    return run_equipment_salvage_controller(
        _require_controller(route_screen, EquipmentSalvageScreenController)
    )


def _run_crafting_screen(route_screen: SteamDemoRouteScreenProtocol) -> list[str]:
    return run_crafting_controller(
        _require_controller(route_screen, CraftingScreenController)
    )


def _run_inn_screen(route_screen: SteamDemoRouteScreenProtocol) -> list[str]:
    return run_inn_controller(_require_controller(route_screen, InnScreenController))


_CLI_ROUTE_HANDLERS: dict[SteamDemoRouteId, CLIRouteHandler] = {
    SteamDemoRouteId.USE_ITEM: _run_item_use_screen,
    SteamDemoRouteId.EQUIPMENT: _run_equipment_screen,
    SteamDemoRouteId.SHOP: _run_shop_screen,
    SteamDemoRouteId.EQUIPMENT_UPGRADE: _run_equipment_upgrade_screen,
    SteamDemoRouteId.EQUIPMENT_SALVAGE: _run_equipment_salvage_screen,
    SteamDemoRouteId.CRAFTING: _run_crafting_screen,
    SteamDemoRouteId.INN: _run_inn_screen,
    SteamDemoRouteId.QUEST_BOARD: _run_quest_board_screen,
    SteamDemoRouteId.TRAVEL: _run_travel_screen,
    SteamDemoRouteId.NPC_DIALOGUE: _run_npc_dialogue_screen,
    SteamDemoRouteId.GATHERING: _run_gathering_screen,
    SteamDemoRouteId.TREASURE: _run_treasure_screen,
    SteamDemoRouteId.FIELD_EVENT: _run_field_event_screen,
}


def _run_cli_route(route_screen: SteamDemoRouteScreenProtocol) -> list[str]:
    handler = _CLI_ROUTE_HANDLERS.get(route_screen.route_id)
    if handler is None:
        return [f"route_not_supported:{route_screen.route_id.value}"]
    return handler(route_screen)


def _dispatch_action(
    runtime: SteamDemoScreenRuntime,
    selected: str,
) -> list[str]:
    opened = runtime.activate_top_action(selected)
    if opened.transition.kind != RouteTransitionKind.PUSHED:
        return list(opened.logs)

    route_id = opened.frame.route_id
    if route_id not in _CLI_ROUTE_HANDLERS:
        return list(
            runtime.cancel_current_route(
                logs=(f"route_not_supported:{route_id.value}",),
            ).logs
        )

    route_screen = runtime.active_screen
    if route_screen is None:
        return list(
            runtime.reset_to_top(
                logs=(f"route_handler_rejected:{route_id.value}:active_screen_missing",),
            ).logs
        )

    try:
        logs = tuple(_run_cli_route(route_screen))
    except (TypeError, ValueError) as exc:
        logs = (f"route_handler_rejected:{route_id.value}:{exc}",)
    return list(runtime.complete_current_route(logs=logs).logs)


def run_steam_demo(save_path: Path, flow_id: str = DEFAULT_FLOW_ID) -> int:
    app = PlayableSliceApplication(master_root=MASTER_ROOT, save_file_path=save_path)
    definitions = DemoFlowMasterDataRepository(MASTER_ROOT).load()
    demo = SteamDemoApplication(
        app,
        flow_service=DemoFlowService(definitions),
        flow_id=flow_id,
    )

    while True:
        print("\n=== Project Asterveil: Steam Demo ===")
        top_choice = base_cli._choose(
            [
                ("new", "New Game"),
                ("continue", "Continue / Load"),
                ("exit", "Exit"),
            ]
        )
        if top_choice == "exit":
            print("ゲームを終了します。")
            return 0
        if top_choice == "new":
            _print_lines(app.new_game())
        else:
            ok, message = app.continue_game()
            _print_lines([message])
            if not ok:
                continue

        composition = SteamDemoCompositionRoot.build(app, demo)
        _print_lines(demo.guidance_lines())
        while True:
            frame = composition.runtime.current_frame()
            if not isinstance(frame.view, SteamDemoMenuViewModel):
                raise RuntimeError(
                    "steam_demo_top_view_type_mismatch:"
                    f"{type(frame.view).__name__}"
                )
            view = frame.view
            if view.is_completed:
                print("\n--- Steamデモ チェックポイント到達 ---")
            else:
                print("\n--- Steamデモ メニュー ---")
            _print_menu_view(view)

            selected = base_cli._choose(_menu_choices(view))
            logs = _dispatch_action(composition.runtime, selected)
            _print_lines(logs)
            if selected == "exit":
                break
            _print_lines(demo.guidance_lines())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Steamデモ向け1プレイ完結フローと初回ガイダンスのランナー"
    )
    parser.add_argument(
        "--save-path",
        default="tmp/steam_demo_slot_01.json",
        help="Steamデモ用セーブファイルパス",
    )
    parser.add_argument(
        "--flow-id",
        default=DEFAULT_FLOW_ID,
        help="実行するデモフローID",
    )
    args = parser.parse_args()
    return run_steam_demo(Path(args.save_path), args.flow_id)


if __name__ == "__main__":
    raise SystemExit(main())
