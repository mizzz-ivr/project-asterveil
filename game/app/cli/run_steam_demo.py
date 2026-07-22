from __future__ import annotations

import argparse
from pathlib import Path

from game.app.application.demo_flow_service import DemoFlowService, SteamDemoApplication
from game.app.application.playable_slice import PlayableSliceApplication
from game.app.cli import run_game_slice as base_cli
from game.app.infrastructure.demo_flow_repository import DemoFlowMasterDataRepository
from game.app.presentation.menu_view_model import (
    SteamDemoMenuPresenter,
    SteamDemoMenuViewModel,
)


DEFAULT_FLOW_ID = "demo.steam.ch01.core_loop"
MASTER_ROOT = Path("data/master")


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


def _dispatch_action(
    app: PlayableSliceApplication,
    demo: SteamDemoApplication,
    selected: str,
) -> list[str]:
    if selected == "demo_guide":
        return demo.guidance_lines()
    if selected == "demo_workshop":
        return demo.inspect_workshop()
    if selected == "save":
        return demo.save_checkpoint()
    if selected == "use_item":
        return base_cli._run_use_item_flow(app)
    if selected == "equip":
        return base_cli._run_equipment_flow(app)
    if selected == "shop":
        return base_cli._run_shop_flow(app)
    if selected == "upgrade_equipment":
        return base_cli._run_equipment_upgrade_flow(app)
    if selected == "salvage_equipment":
        return base_cli._run_equipment_salvage_flow(app)
    if selected == "craft":
        return base_cli._run_crafting_flow(app)
    if selected == "inn":
        return base_cli._run_inn_flow(app)
    if selected == "quest_board":
        return base_cli._run_quest_board_flow(app)
    if selected == "move":
        return base_cli._run_travel_flow(app)
    if selected == "talk_npc":
        return base_cli._run_talk_npc_flow(app)
    if selected == "gather":
        return base_cli._run_gathering_flow(app)
    if selected == "open_treasure":
        return base_cli._run_treasure_flow(app)
    if selected == "field_events":
        return base_cli._run_field_event_flow(app)
    return app.perform_action(selected)


def run_steam_demo(save_path: Path, flow_id: str = DEFAULT_FLOW_ID) -> int:
    app = PlayableSliceApplication(master_root=MASTER_ROOT, save_file_path=save_path)
    definitions = DemoFlowMasterDataRepository(MASTER_ROOT).load()
    demo = SteamDemoApplication(
        app,
        flow_service=DemoFlowService(definitions),
        flow_id=flow_id,
    )
    presenter = SteamDemoMenuPresenter()

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
            logs = _dispatch_action(app, demo, selected)
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
