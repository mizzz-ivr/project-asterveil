from __future__ import annotations

import argparse
from pathlib import Path
from typing import Callable

from game.app.application.demo_flow_service import DemoFlowService, SteamDemoApplication
from game.app.application.playable_exploration_facade import PlayableExplorationFacade
from game.app.application.playable_interaction_facade import PlayableInteractionFacade
from game.app.application.playable_slice import PlayableSliceApplication
from game.app.cli import run_game_slice as base_cli
from game.app.infrastructure.demo_flow_repository import DemoFlowMasterDataRepository
from game.app.presentation.action_controller import (
    ActionDispatchKind,
    SteamDemoActionController,
    SteamDemoFlowId,
)
from game.app.presentation.gathering_treasure_screen import (
    GatheringScreenController,
    GatheringScreenViewModel,
    TreasureScreenController,
    TreasureScreenViewModel,
)
from game.app.presentation.menu_view_model import (
    SteamDemoMenuPresenter,
    SteamDemoMenuViewModel,
)
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


DEFAULT_FLOW_ID = "demo.steam.ch01.core_loop"
MASTER_ROOT = Path("data/master")

CLIFlowHandler = Callable[[PlayableSliceApplication], list[str]]


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


def _run_quest_board_screen(app: PlayableSliceApplication) -> list[str]:
    controller = QuestBoardScreenController(app)
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


def _run_travel_screen(app: PlayableSliceApplication) -> list[str]:
    controller = TravelScreenController(app)
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


def _run_npc_dialogue_screen(app: PlayableSliceApplication) -> list[str]:
    controller = NpcDialogueScreenController(PlayableInteractionFacade(app))
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


def _run_field_event_screen(app: PlayableSliceApplication) -> list[str]:
    controller = FieldEventScreenController(PlayableInteractionFacade(app))
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


def _run_gathering_screen(app: PlayableSliceApplication) -> list[str]:
    controller = GatheringScreenController(PlayableExplorationFacade(app))
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


def _run_treasure_screen(app: PlayableSliceApplication) -> list[str]:
    controller = TreasureScreenController(PlayableExplorationFacade(app))
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


_CLI_FLOW_HANDLERS: dict[SteamDemoFlowId, CLIFlowHandler] = {
    SteamDemoFlowId.USE_ITEM: base_cli._run_use_item_flow,
    SteamDemoFlowId.EQUIPMENT: base_cli._run_equipment_flow,
    SteamDemoFlowId.SHOP: base_cli._run_shop_flow,
    SteamDemoFlowId.EQUIPMENT_UPGRADE: base_cli._run_equipment_upgrade_flow,
    SteamDemoFlowId.EQUIPMENT_SALVAGE: base_cli._run_equipment_salvage_flow,
    SteamDemoFlowId.CRAFTING: base_cli._run_crafting_flow,
    SteamDemoFlowId.INN: base_cli._run_inn_flow,
    SteamDemoFlowId.QUEST_BOARD: _run_quest_board_screen,
    SteamDemoFlowId.TRAVEL: _run_travel_screen,
    SteamDemoFlowId.NPC_DIALOGUE: _run_npc_dialogue_screen,
    SteamDemoFlowId.GATHERING: _run_gathering_screen,
    SteamDemoFlowId.TREASURE: _run_treasure_screen,
    SteamDemoFlowId.FIELD_EVENT: _run_field_event_screen,
}


def _run_cli_flow(
    app: PlayableSliceApplication,
    flow_id: SteamDemoFlowId,
) -> list[str]:
    handler = _CLI_FLOW_HANDLERS.get(flow_id)
    if handler is None:
        return [f"flow_not_supported:{flow_id.value}"]
    return handler(app)


def _dispatch_action(
    app: PlayableSliceApplication,
    controller: SteamDemoActionController,
    selected: str,
) -> list[str]:
    result = controller.dispatch(selected)
    if result.kind == ActionDispatchKind.FLOW_REQUIRED:
        if result.flow_id is None:
            return [f"flow_dispatch_failed:missing_flow_id:{selected}"]
        return _run_cli_flow(app, result.flow_id)
    return list(result.logs)


def run_steam_demo(save_path: Path, flow_id: str = DEFAULT_FLOW_ID) -> int:
    app = PlayableSliceApplication(master_root=MASTER_ROOT, save_file_path=save_path)
    definitions = DemoFlowMasterDataRepository(MASTER_ROOT).load()
    demo = SteamDemoApplication(
        app,
        flow_service=DemoFlowService(definitions),
        flow_id=flow_id,
    )
    presenter = SteamDemoMenuPresenter()
    action_controller = SteamDemoActionController(app, demo)

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

        _print_lines(demo.guidance_lines())
        while True:
            view = presenter.build(app, demo)
            if view.is_completed:
                print("\n--- Steamデモ チェックポイント到達 ---")
            else:
                print("\n--- Steamデモ メニュー ---")
            _print_menu_view(view)

            selected = base_cli._choose(_menu_choices(view))
            logs = _dispatch_action(app, action_controller, selected)
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
