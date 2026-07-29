from __future__ import annotations

import argparse
from pathlib import Path

from game.app.application.demo_flow_service import DemoFlowService, SteamDemoApplication
from game.app.application.playable_slice import PlayableSliceApplication
from game.app.client.steam_demo_client import SteamDemoClientController
from game.app.client.tk_steam_demo import TkinterUnavailableError, run_tk_steam_demo
from game.app.infrastructure.demo_flow_repository import DemoFlowMasterDataRepository


DEFAULT_FLOW_ID = "demo.steam.ch01.core_loop"
MASTER_ROOT = Path("data/master")
DEFAULT_SAVE_PATH = Path("tmp/steam_demo_slot_01.json")


def build_client(
    save_path: Path,
    flow_id: str = DEFAULT_FLOW_ID,
    *,
    master_root: Path = MASTER_ROOT,
) -> SteamDemoClientController:
    playable = PlayableSliceApplication(
        master_root=master_root,
        save_file_path=save_path,
    )
    definitions = DemoFlowMasterDataRepository(master_root).load()
    demo = SteamDemoApplication(
        playable,
        flow_service=DemoFlowService(definitions),
        flow_id=flow_id,
    )
    return SteamDemoClientController(
        playable,
        demo,
        save_path,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Project Asterveil Steamデモの最小デスクトップクライアント"
    )
    parser.add_argument(
        "--save-path",
        default=str(DEFAULT_SAVE_PATH),
        help="Steamデモ用セーブファイルパス",
    )
    parser.add_argument(
        "--flow-id",
        default=DEFAULT_FLOW_ID,
        help="実行するデモフローID",
    )
    args = parser.parse_args()

    try:
        controller = build_client(Path(args.save_path), args.flow_id)
        return run_tk_steam_demo(controller)
    except TkinterUnavailableError as exc:
        print(f"デスクトップクライアントを起動できません: {exc}")
        return 2
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        print(f"Steamデモの初期化に失敗しました: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
