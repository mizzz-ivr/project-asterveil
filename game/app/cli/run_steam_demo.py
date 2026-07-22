from __future__ import annotations

import argparse
from pathlib import Path
from typing import Callable

from game.app.application.demo_flow_service import DemoFlowService, SteamDemoApplication
from game.app.application.playable_slice import PlayableSliceApplication
from game.app.cli import run_game_slice as base_cli
from game.app.infrastructure.demo_flow_repository import DemoFlowMasterDataRepository
from game.app.presentation.action_controller import (
    ActionDispatchKind,
    SteamDemoActionController,
    SteamDemoFlowId,
)
from game.app.presentation.menu_view_model import (
    SteamDemoMenuPresenter,
    SteamDemoMenuViewModel,
)


DEFAULT_FLOW_ID = "demo.steam.ch01.core_loop"
MASTER_ROOT = Path("data/master")

CLIFlowHandler = Callable[[PlayableSliceApplication], list[str]]

_CLI_FLOW_HANDLERS: dict[SteamDemoFlowId, CLIFlowHandler] = {
    SteamDemoFlowId.USE_ITEM: base_cli._run_use_item_flow,
    SteamDemoFlowId.EQUIPMENT: base_cli._run_equipment_flow,
    SteamDemoFlowId.SHOP: base_cli._run_shop_flow,
    SteamDemoFlowId.EQUIPMENT_UPGRADE: base_cli._run_equipment_upgrade_flow,
    SteamDemoFlowId.EQUIPMENT_SALVAGE: base_cli._run_equipment_salvage_flow,
    SteamDemoFlowId.CRAFTING: base_cli._run_crafting_flow,
    SteamDemoFlowId.INN: base_cli._run_inn_flow,
    SteamDemoFlowId.QUEST_BOARD: base_cli._run_quest_board_flow,
    SteamDemoFlowId.TRAVEL: base_cli._run_travel_flow,
    SteamDemoFlowId.NPC_DIALOGUE: base_cli._run_talk_npc_flow,
    SteamDemoFlowId.GATHERING: base_cli._run_gathering_flow,
    SteamDemoFlowId.TREASURE: base_cli._run_treasure_flow,
    SteamDemoFlowId.FIELD_EVENT: base_cli._run_field_event_flow,
}


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
