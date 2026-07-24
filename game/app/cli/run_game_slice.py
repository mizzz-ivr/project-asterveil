from __future__ import annotations

import argparse
from pathlib import Path

from game.app.application.playable_slice import PlayableSliceApplication
from game.app.application.equipment_service import VALID_SLOTS


def _choose(items: list[tuple[str, str]]) -> str:
    for idx, (_, label) in enumerate(items, start=1):
        print(f"{idx}. {label}")

    while True:
        raw = input("選択してください: ").strip()
        if not raw.isdigit():
            print("数字を入力してください。")
            continue
        index = int(raw)
        if index < 1 or index > len(items):
            print("範囲外です。")
            continue
        return items[index - 1][0]


def _run_use_item_flow(app: PlayableSliceApplication) -> list[str]:
    item_ids = app.usable_item_ids()
    if not item_ids:
        return ["usable_item:none"]

    item_choices = []
    for item_id in item_ids:
        amount = app.inventory_state.get("items", {}).get(item_id, 0)
        item_choices.append((item_id, f"{item_id} x{amount}"))
    selected_item_id = _choose(item_choices)

    member_choices = []
    for member_line in app.party_member_lines():
        parts = member_line.split(":")
        character_id = parts[1]
        member_choices.append((character_id, member_line))
    selected_target = _choose(member_choices)

    return app.use_item(selected_item_id, selected_target)


def _run_shop_flow(app: PlayableSliceApplication) -> list[str]:
    from game.app.cli.economy_facility_cli import run_shop_screen

    return run_shop_screen(app)


def _run_crafting_flow(app: PlayableSliceApplication) -> list[str]:
    from game.app.cli.economy_facility_cli import run_crafting_screen

    return run_crafting_screen(app)


def _run_inn_flow(app: PlayableSliceApplication) -> list[str]:
    from game.app.cli.economy_facility_cli import run_inn_screen

    return run_inn_screen(app)


def _run_equipment_flow(app: PlayableSliceApplication) -> list[str]:
    member_choices = []
    for member_line in app.party_member_lines():
        parts = member_line.split(":")
        character_id = parts[1]
        member_choices.append((character_id, member_line))
    selected_member = _choose(member_choices)

    slot_labels = {
        "weapon": "武器スロット",
        "armor": "防具スロット",
        "accessory": "アクセサリスロット",
    }
    slot_type = _choose([(slot, slot_labels.get(slot, f"{slot}スロット")) for slot in VALID_SLOTS])
    options = app.equippable_options(selected_member, slot_type)
    if not options:
        return [f"equip_failed:no_option:{selected_member}:{slot_type}"]
    selected_equipment = _choose(options)
    if selected_equipment == "cancel":
        return ["equip_cancelled"]
    return app.equip_item(selected_member, slot_type, selected_equipment)


def _run_equipment_upgrade_flow(app: PlayableSliceApplication) -> list[str]:
    from game.app.cli.equipment_workshop_cli import run_equipment_upgrade_screen

    return run_equipment_upgrade_screen(app)


def _run_equipment_salvage_flow(app: PlayableSliceApplication) -> list[str]:
    from game.app.cli.equipment_workshop_cli import run_equipment_salvage_screen

    return run_equipment_salvage_screen(app)


def _run_quest_board_flow(app: PlayableSliceApplication) -> list[str]:
    lines = app.quest_board_lines()
    for line in lines:
        print(f"- {line}")

    acceptables: list[tuple[str, str]] = [("cancel", "受注しない")]
    for line in lines:
        if not line.startswith("quest_board_entry:"):
            continue
        _, quest_id, title, status_part, can_accept_part, _ = line.split(":", 5)
        if can_accept_part != "can_accept=True":
            continue
        acceptables.append((quest_id, f"{title} ({quest_id}) {status_part}"))

    if len(acceptables) == 1:
        return ["quest_board:no_accept_available"]

    selected_quest_id = _choose(acceptables)
    if selected_quest_id == "cancel":
        return ["quest_accept_cancelled"]
    return app.accept_quest(selected_quest_id)


def _run_travel_flow(app: PlayableSliceApplication) -> list[str]:
    lines = app.travel_options_lines()
    for line in lines:
        print(f"- {line}")
    options: list[tuple[str, str]] = [("cancel", "移動しない")]
    for line in lines:
        if not line.startswith("travel_option:"):
            continue
        _, location_id, name, type_part = line.split(":", 3)
        options.append((location_id, f"{name} ({location_id}) {type_part}"))
    if len(options) == 1:
        return ["travel_failed:no_destination"]
    selected = _choose(options)
    if selected == "cancel":
        return ["travel_cancelled"]
    return app.travel_to(selected)


def _run_talk_npc_flow(app: PlayableSliceApplication) -> list[str]:
    npc_lines = app.talk_npc_options_lines()
    for line in npc_lines:
        print(f"- {line}")
    options: list[tuple[str, str]] = [("cancel", "話しかけない")]
    for line in npc_lines:
        if not line.startswith("npc:"):
            continue
        _, npc_id, npc_name = line.split(":", 2)
        options.append((npc_id, f"{npc_name} ({npc_id})"))
    if len(options) == 1:
        return ["dialogue_unavailable:no_npc"]
    selected = _choose(options)
    if selected == "cancel":
        return ["dialogue_cancelled"]
    return app.talk_to_npc(selected, choice_selector=lambda items, _step_id: _choose(items))


def _run_gathering_flow(app: PlayableSliceApplication) -> list[str]:
    node_lines = app.gathering_node_lines()
    for line in node_lines:
        print(f"- {line}")
    choices = [("cancel", "採取しない")]
    choices.extend(app.gatherable_node_choices())
    if len(choices) == 1:
        return ["gather_failed:no_available_node"]
    selected = _choose(choices)
    if selected == "cancel":
        return ["gather_cancelled"]
    return app.gather_from_node(selected)


def _run_treasure_flow(app: PlayableSliceApplication) -> list[str]:
    node_lines = app.treasure_node_lines()
    for line in node_lines:
        print(f"- {line}")
    choices = [("cancel", "調べない")]
    choices.extend(app.openable_treasure_node_choices())
    if len(choices) == 1:
        return ["treasure_open_failed:no_openable_node"]
    selected = _choose(choices)
    if selected == "cancel":
        return ["treasure_open_cancelled"]
    return app.open_treasure_node(selected)


def _run_field_event_flow(app: PlayableSliceApplication) -> list[str]:
    event_lines = app.field_event_lines()
    for line in event_lines:
        print(f"- {line}")
    choices = [("cancel", "探索イベントを実行しない")]
    choices.extend(app.executable_field_event_choices())
    if len(choices) == 1:
        return ["field_event_unavailable:no_executable_event"]
    selected_event_id = _choose(choices)
    if selected_event_id == "cancel":
        return ["field_event_cancelled"]

    choice_lines = app.field_event_choice_lines(selected_event_id)
    for line in choice_lines:
        print(f"- {line}")
    event_choice_options: list[tuple[str, str]] = [("cancel", "このイベントをやめる")]
    for line in choice_lines:
        if not line.startswith("field_event_choice:"):
            continue
        _, choice_id, text = line.split(":", 2)
        event_choice_options.append((choice_id, text))
    selected_choice_id = _choose(event_choice_options)
    if selected_choice_id == "cancel":
        return ["field_choice_cancelled"]
    return app.resolve_field_event_choice(selected_event_id, selected_choice_id)


def run_playable_vertical_slice(save_path: Path) -> int:
    app = PlayableSliceApplication(master_root=Path("data/master"), save_file_path=save_path)

    while True:
        print("\n=== Project Asterveil: Playable Vertical Slice ===")
        top_choice = _choose(
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
            for log in app.new_game():
                print(f"- {log}")
        else:
            ok, message = app.continue_game()
            print(f"- {message}")
            if not ok:
                continue

        while True:
            print("\n--- 拠点メニュー ---")
            actions = [(item.key, item.label) for item in app.available_actions()]
            selected = _choose(actions)
            if selected == "use_item":
                logs = _run_use_item_flow(app)
            elif selected == "equip":
                logs = _run_equipment_flow(app)
            elif selected == "shop":
                logs = _run_shop_flow(app)
            elif selected == "upgrade_equipment":
                logs = _run_equipment_upgrade_flow(app)
            elif selected == "salvage_equipment":
                logs = _run_equipment_salvage_flow(app)
            elif selected == "craft":
                logs = _run_crafting_flow(app)
            elif selected == "inn":
                logs = _run_inn_flow(app)
            elif selected == "quest_board":
                logs = _run_quest_board_flow(app)
            elif selected == "move":
                logs = _run_travel_flow(app)
            elif selected == "talk_npc":
                logs = _run_talk_npc_flow(app)
            elif selected == "gather":
                logs = _run_gathering_flow(app)
            elif selected == "open_treasure":
                logs = _run_treasure_flow(app)
            elif selected == "field_events":
                logs = _run_field_event_flow(app)
            else:
                logs = app.perform_action(selected)
            for log in logs:
                print(f"- {log}")
            if selected == "exit":
                break


def main() -> int:
    parser = argparse.ArgumentParser(description="最小プレイアブルVertical Sliceランナー")
    parser.add_argument("--save-path", default="tmp/playable_slice_slot_01.json", help="セーブファイルパス")
    args = parser.parse_args()
    return run_playable_vertical_slice(Path(args.save_path))


if __name__ == "__main__":
    raise SystemExit(main())
