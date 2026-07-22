from __future__ import annotations

import argparse
from pathlib import Path

from game.app.application.demo_flow_service import SteamDemoApplication
from game.app.application.playable_slice import ActionItem, PlayableSliceApplication
from game.app.cli import run_game_slice as base_cli
from game.app.infrastructure.demo_flow_repository import DemoFlowMasterDataRepository


DEFAULT_FLOW_ID = "demo.steam.ch01.core_loop"
MASTER_ROOT = Path("data/master")


def _print_lines(lines: list[str]) -> None:
    for line in lines:
        print(f"- {line}")


def _demo_actions(
    app: PlayableSliceApplication,
    demo: SteamDemoApplication,
) -> list[ActionItem]:
    items = [ActionItem("demo_guide", "現在のデモ目標を確認する")]
    progress = demo.progress()
    if (
        progress.active_step is not None
        and progress.active_step.recommended_action == "inspect_workshop"
    ):
        items.append(ActionItem("demo_workshop", "デモ工房ガイドを確認する"))
    items.extend(app.available_actions())
    return items


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
    demo = SteamDemoApplication(app, flow_service=_flow_service(definitions), flow_id=flow_id)

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
            progress = demo.progress()
            if progress.is_completed:
                print("\n--- Steamデモ チェックポイント到達 ---")
            else:
                print("\n--- Steamデモ メニュー ---")

            actions = [(item.key, item.label) for item in _demo_actions(app, demo)]
            selected = base_cli._choose(actions)
            logs = _dispatch_action(app, demo, selected)
            _print_lines(logs)
            if selected == "exit":
                break
            _print_lines(demo.guidance_lines())


def _flow_service(definitions: dict[str, object]):
    # 循環importを避けつつ、CLIから進行サービスを構築する最小ファクトリ。
    from game.app.application.demo_flow_service import DemoFlowService

    return DemoFlowService(definitions)


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
