from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Sequence

from game.app.application.demo_flow_service import DemoFlowService, SteamDemoApplication
from game.app.application.playable_slice import PlayableSliceApplication
from game.app.client.runtime_paths import default_master_root, default_save_path
from game.app.client.steam_demo_client import (
    SteamDemoClientController,
    SteamDemoClientPhase,
)
from game.app.client.tk_steam_demo import TkinterUnavailableError, run_tk_steam_demo
from game.app.infrastructure.demo_flow_repository import DemoFlowMasterDataRepository
from game.app.presentation.screen_router import SteamDemoRouteId


DEFAULT_FLOW_ID = "demo.steam.ch01.core_loop"


def build_client(
    save_path: Path,
    flow_id: str = DEFAULT_FLOW_ID,
    *,
    master_root: Path | None = None,
) -> SteamDemoClientController:
    resolved_master_root = Path(master_root or default_master_root()).resolve()
    playable = PlayableSliceApplication(
        master_root=resolved_master_root,
        save_file_path=Path(save_path),
    )
    definitions = DemoFlowMasterDataRepository(resolved_master_root).load()
    demo = SteamDemoApplication(
        playable,
        flow_service=DemoFlowService(definitions),
        flow_id=flow_id,
    )
    return SteamDemoClientController(
        playable,
        demo,
        Path(save_path),
    )


def run_smoke_test(
    *,
    master_root: Path,
    flow_id: str = DEFAULT_FLOW_ID,
) -> dict[str, object]:
    """Tkinterを生成せず、配布物の初期化とNew Game導線を検証する。"""

    with tempfile.TemporaryDirectory(prefix="asterveil-smoke-") as temporary_directory:
        save_path = Path(temporary_directory) / "smoke-save.json"
        controller = build_client(
            save_path,
            flow_id,
            master_root=master_root,
        )

        title_view = controller.current_view()
        if title_view.phase != SteamDemoClientPhase.TITLE:
            raise RuntimeError("smoke_test_title_phase_invalid")

        result = controller.start_new_game()
        if result.rejection_reason is not None:
            raise RuntimeError(
                f"smoke_test_new_game_rejected:{result.rejection_reason}"
            )
        if result.view.phase != SteamDemoClientPhase.GAMEPLAY:
            raise RuntimeError("smoke_test_gameplay_phase_invalid")
        if result.view.scene is None:
            raise RuntimeError("smoke_test_scene_missing")
        if result.view.scene.scene.route_id != SteamDemoRouteId.TOP_MENU:
            raise RuntimeError(
                "smoke_test_initial_route_invalid:"
                f"{result.view.scene.scene.route_id.value}"
            )

        controller.request_exit()
        return {
            "status": "ok",
            "flow_id": flow_id,
            "master_root": str(master_root.resolve()),
            "initial_route": SteamDemoRouteId.TOP_MENU.value,
            "title_action_count": len(title_view.title_actions),
            "scene_command_count": len(result.view.scene.commands),
        }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Project Asterveil Steamデモの最小デスクトップクライアント"
    )
    parser.add_argument(
        "--save-path",
        default=None,
        help="Steamデモ用セーブファイルパス",
    )
    parser.add_argument(
        "--master-root",
        default=None,
        help="マスターデータルート。通常は自動解決します。",
    )
    parser.add_argument(
        "--flow-id",
        default=DEFAULT_FLOW_ID,
        help="実行するデモフローID",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="GUIを生成せず、配布物の初期化とNew Game導線を検証する",
    )
    args = parser.parse_args(argv)

    master_root = Path(args.master_root) if args.master_root else default_master_root()
    save_path = Path(args.save_path) if args.save_path else default_save_path()

    try:
        if args.smoke_test:
            report = run_smoke_test(master_root=master_root, flow_id=args.flow_id)
            print(json.dumps(report, ensure_ascii=False, sort_keys=True))
            return 0

        controller = build_client(
            save_path,
            args.flow_id,
            master_root=master_root,
        )
        return run_tk_steam_demo(controller)
    except TkinterUnavailableError as exc:
        print(f"デスクトップクライアントを起動できません: {exc}")
        return 2
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        print(f"Steamデモの初期化に失敗しました: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
