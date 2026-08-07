from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Sequence

from game.app.application.bestiary_playable_slice import BestiaryPlayableSliceApplication
from game.app.application.demo_flow_service import DemoFlowService, SteamDemoApplication
from game.app.client.client_diagnostics import (
    CrashReportWriter,
    DiagnosticSeverity,
    StructuredDiagnosticLogger,
    SupportBundleExporter,
)
from game.app.client.enhanced_tk_steam_demo import run_enhanced_tk_steam_demo
from game.app.client.gamepad_input import NullGamepadBackend
from game.app.client.player_support import (
    SteamDemoSupportSettingsRepository,
    build_default_guide_catalog,
)
from game.app.client.runtime_paths import (
    default_master_root,
    default_save_path,
    default_support_root,
)
from game.app.client.steam_demo_client import (
    SteamDemoClientController,
    SteamDemoClientPhase,
)
from game.app.client.tk_steam_demo import TkinterUnavailableError
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
    playable = BestiaryPlayableSliceApplication(
        master_root=resolved_master_root,
        save_file_path=Path(save_path),
    )
    definitions = DemoFlowMasterDataRepository(resolved_master_root).load()
    demo = SteamDemoApplication(
        playable,
        flow_service=DemoFlowService(definitions),
        flow_id=flow_id,
    )
    return SteamDemoClientController(playable, demo, Path(save_path))


def run_smoke_test(
    *,
    master_root: Path,
    flow_id: str = DEFAULT_FLOW_ID,
    support_root: Path | None = None,
) -> dict[str, object]:
    """Tkinterを生成せず、配布物・New Game・Support契約を検証する。"""

    with tempfile.TemporaryDirectory(prefix="asterveil-smoke-") as temporary_directory:
        save_path = Path(temporary_directory) / "smoke-save.json"
        resolved_support_root = (
            Path(support_root)
            if support_root is not None
            else Path(temporary_directory) / "support"
        )
        settings_repository = SteamDemoSupportSettingsRepository(
            resolved_support_root / "client_settings.json"
        )
        settings = settings_repository.load().settings
        settings_repository.save(settings)
        guide_catalog = build_default_guide_catalog()
        controller = build_client(save_path, flow_id, master_root=master_root)
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
        if len(guide_catalog.pages) < 9:
            raise RuntimeError("smoke_test_guide_catalog_incomplete")
        if not settings_repository.path.is_file():
            raise RuntimeError("smoke_test_support_settings_missing")
        controller.request_exit()
        return {
            "status": "ok",
            "flow_id": flow_id,
            "master_root": str(master_root.resolve()),
            "initial_route": SteamDemoRouteId.TOP_MENU.value,
            "title_action_count": len(title_view.title_actions),
            "scene_command_count": len(result.view.scene.commands),
            "guide_topic_count": len(guide_catalog.pages),
            "support_settings_version": settings.settings_version,
        }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Project Asterveil Steamデモのデスクトップクライアント"
    )
    parser.add_argument("--save-path", default=None)
    parser.add_argument("--master-root", default=None)
    parser.add_argument("--support-root", default=None)
    parser.add_argument("--flow-id", default=DEFAULT_FLOW_ID)
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--export-support-bundle", action="store_true")
    parser.add_argument("--reset-tutorial", action="store_true")
    parser.add_argument("--disable-gamepad", action="store_true")
    args = parser.parse_args(argv)

    master_root = Path(args.master_root) if args.master_root else default_master_root()
    save_path = Path(args.save_path) if args.save_path else default_save_path()
    support_root = Path(args.support_root) if args.support_root else default_support_root()
    settings_repository = SteamDemoSupportSettingsRepository(
        support_root / "client_settings.json"
    )
    settings_result = settings_repository.load()
    if args.reset_tutorial:
        settings_repository.reset_tutorial()
        settings_result = settings_repository.load()

    diagnostics = StructuredDiagnosticLogger(
        support_root / "diagnostics",
        enabled=settings_result.settings.diagnostics_enabled,
    )
    crash_writer = CrashReportWriter(
        support_root / "crashes",
        session_id=diagnostics.session_id,
    )
    bundle_exporter = SupportBundleExporter(
        support_root,
        settings_path=settings_repository.path,
        save_path=save_path,
    )

    try:
        diagnostics.log(
            "client_entrypoint",
            "Steam demo entrypoint started.",
            context={
                "smoke_test": bool(args.smoke_test),
                "export_support_bundle": bool(args.export_support_bundle),
                "gamepad_disabled": bool(args.disable_gamepad),
            },
        )
        if args.export_support_bundle:
            bundle_path = bundle_exporter.export(
                session_id=diagnostics.session_id,
                include_save_metadata=(
                    settings_result.settings.save_metadata_in_support_bundle
                ),
                additional_context={"mode": "headless_export"},
            )
            print(
                json.dumps(
                    {
                        "status": "ok",
                        "support_bundle": str(bundle_path),
                        "save_file_included": False,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0
        if args.smoke_test:
            report = run_smoke_test(
                master_root=master_root,
                flow_id=args.flow_id,
                support_root=support_root / "smoke-test",
            )
            diagnostics.log(
                "smoke_test_completed",
                "Smoke test completed.",
                context=report,
            )
            print(json.dumps(report, ensure_ascii=False, sort_keys=True))
            return 0
        controller = build_client(save_path, args.flow_id, master_root=master_root)
        return run_enhanced_tk_steam_demo(
            controller,
            support_root=support_root,
            save_path=save_path,
            settings_repository=settings_repository,
            diagnostics=diagnostics,
            gamepad_backend=(NullGamepadBackend() if args.disable_gamepad else None),
        )
    except TkinterUnavailableError as exc:
        diagnostics.log(
            "tkinter_unavailable", str(exc), severity=DiagnosticSeverity.ERROR
        )
        print(f"デスクトップクライアントを起動できません: {exc}")
        return 2
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        crash_path = crash_writer.write(
            exc,
            context={"entrypoint": "expected_initialization_error"},
        )
        diagnostics.log(
            "client_initialization_failed",
            str(exc),
            severity=DiagnosticSeverity.ERROR,
            context={"crash_report": crash_path},
        )
        print(
            "Steamデモの初期化に失敗しました: "
            f"{exc} / 診断レポート: {crash_path}"
        )
        return 1
    except Exception as exc:
        crash_path = crash_writer.write(
            exc,
            context={"entrypoint": "unexpected_error"},
        )
        diagnostics.log(
            "client_unexpected_failure",
            str(exc),
            severity=DiagnosticSeverity.CRITICAL,
            context={"crash_report": crash_path},
        )
        print(
            "Steamデモで予期しないエラーが発生しました: "
            f"{exc} / 診断レポート: {crash_path}"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
