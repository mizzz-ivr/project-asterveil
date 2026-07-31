from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence


SUPPORT_SETTINGS_VERSION = 1


@dataclass(frozen=True)
class SteamDemoSupportSettings:
    settings_version: int = SUPPORT_SETTINGS_VERSION
    high_contrast: bool = False
    reduced_motion: bool = False
    gamepad_enabled: bool = True
    show_first_run_guide: bool = True
    show_context_tips: bool = True
    tutorial_completed: bool = False
    diagnostics_enabled: bool = True
    save_metadata_in_support_bundle: bool = True
    gamepad_user_index: int = 0
    stick_deadzone: int = 12000
    repeat_delay_ms: int = 420
    repeat_interval_ms: int = 130

    def __post_init__(self) -> None:
        if self.settings_version != SUPPORT_SETTINGS_VERSION:
            raise ValueError(
                f"unsupported_support_settings_version:{self.settings_version}"
            )
        for field_name in (
            "high_contrast",
            "reduced_motion",
            "gamepad_enabled",
            "show_first_run_guide",
            "show_context_tips",
            "tutorial_completed",
            "diagnostics_enabled",
            "save_metadata_in_support_bundle",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise TypeError(f"support_setting_must_be_boolean:{field_name}")
        if self.gamepad_user_index < 0 or self.gamepad_user_index > 3:
            raise ValueError("support_gamepad_user_index_out_of_range")
        if self.stick_deadzone < 0 or self.stick_deadzone > 32767:
            raise ValueError("support_stick_deadzone_out_of_range")
        if self.repeat_delay_ms < 0:
            raise ValueError("support_repeat_delay_must_be_non_negative")
        if self.repeat_interval_ms <= 0:
            raise ValueError("support_repeat_interval_must_be_positive")

    def to_dict(self) -> dict[str, object]:
        return {
            "settings_version": self.settings_version,
            "high_contrast": self.high_contrast,
            "reduced_motion": self.reduced_motion,
            "gamepad_enabled": self.gamepad_enabled,
            "show_first_run_guide": self.show_first_run_guide,
            "show_context_tips": self.show_context_tips,
            "tutorial_completed": self.tutorial_completed,
            "diagnostics_enabled": self.diagnostics_enabled,
            "save_metadata_in_support_bundle": self.save_metadata_in_support_bundle,
            "gamepad_user_index": self.gamepad_user_index,
            "stick_deadzone": self.stick_deadzone,
            "repeat_delay_ms": self.repeat_delay_ms,
            "repeat_interval_ms": self.repeat_interval_ms,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "SteamDemoSupportSettings":
        if not isinstance(payload, Mapping):
            raise TypeError("support_settings_payload_must_be_object")
        version = payload.get("settings_version", SUPPORT_SETTINGS_VERSION)
        if isinstance(version, bool) or not isinstance(version, int):
            raise TypeError("support_settings_version_must_be_integer")
        defaults = cls()
        values = defaults.to_dict()
        values.update(payload)
        return cls(
            settings_version=version,
            high_contrast=_require_bool(values["high_contrast"], "high_contrast"),
            reduced_motion=_require_bool(values["reduced_motion"], "reduced_motion"),
            gamepad_enabled=_require_bool(values["gamepad_enabled"], "gamepad_enabled"),
            show_first_run_guide=_require_bool(
                values["show_first_run_guide"], "show_first_run_guide"
            ),
            show_context_tips=_require_bool(
                values["show_context_tips"], "show_context_tips"
            ),
            tutorial_completed=_require_bool(
                values["tutorial_completed"], "tutorial_completed"
            ),
            diagnostics_enabled=_require_bool(
                values["diagnostics_enabled"], "diagnostics_enabled"
            ),
            save_metadata_in_support_bundle=_require_bool(
                values["save_metadata_in_support_bundle"],
                "save_metadata_in_support_bundle",
            ),
            gamepad_user_index=_require_int(
                values["gamepad_user_index"], "gamepad_user_index"
            ),
            stick_deadzone=_require_int(values["stick_deadzone"], "stick_deadzone"),
            repeat_delay_ms=_require_int(values["repeat_delay_ms"], "repeat_delay_ms"),
            repeat_interval_ms=_require_int(
                values["repeat_interval_ms"], "repeat_interval_ms"
            ),
        )

    def with_tutorial_completed(self, completed: bool = True) -> "SteamDemoSupportSettings":
        return replace(self, tutorial_completed=bool(completed))


def _require_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"support_setting_must_be_boolean:{field_name}")
    return value


def _require_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"support_setting_must_be_integer:{field_name}")
    return value


@dataclass(frozen=True)
class SupportSettingsLoadResult:
    settings: SteamDemoSupportSettings
    recovered_from_invalid_file: bool = False
    backup_path: Path | None = None
    warnings: tuple[str, ...] = tuple()


class SteamDemoSupportSettingsRepository:
    def __init__(
        self,
        path: Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._path = Path(path)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> SupportSettingsLoadResult:
        if not self._path.is_file():
            return SupportSettingsLoadResult(settings=SteamDemoSupportSettings())
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            return SupportSettingsLoadResult(
                settings=SteamDemoSupportSettings.from_dict(payload)
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            backup_path = self._backup_invalid_file()
            settings = SteamDemoSupportSettings()
            try:
                self.save(settings)
            except OSError:
                pass
            return SupportSettingsLoadResult(
                settings=settings,
                recovered_from_invalid_file=True,
                backup_path=backup_path,
                warnings=(f"support_settings_recovered:{type(exc).__name__}:{exc}",),
            )

    def save(self, settings: SteamDemoSupportSettings) -> None:
        if not isinstance(settings, SteamDemoSupportSettings):
            raise TypeError("support_settings_repository_requires_settings")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self._path.with_name(f".{self._path.name}.tmp")
        encoded = json.dumps(
            settings.to_dict(), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"
        try:
            with temporary_path.open("w", encoding="utf-8", newline="\n") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self._path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink(missing_ok=True)

    def reset_tutorial(self) -> SteamDemoSupportSettings:
        settings = replace(
            self.load().settings,
            tutorial_completed=False,
            show_first_run_guide=True,
        )
        self.save(settings)
        return settings

    def _backup_invalid_file(self) -> Path | None:
        if not self._path.exists():
            return None
        timestamp = self._clock().astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        candidate = self._path.with_name(f"{self._path.name}.invalid-{timestamp}.json")
        suffix = 1
        while candidate.exists():
            candidate = self._path.with_name(
                f"{self._path.name}.invalid-{timestamp}-{suffix}.json"
            )
            suffix += 1
        try:
            self._path.replace(candidate)
        except OSError:
            return None
        return candidate


@dataclass(frozen=True)
class GuidePage:
    topic_id: str
    title: str
    summary: str
    steps: tuple[str, ...]
    keyboard_controls: tuple[str, ...] = tuple()
    gamepad_controls: tuple[str, ...] = tuple()
    route_ids: tuple[str, ...] = tuple()

    def __post_init__(self) -> None:
        if not self.topic_id.strip():
            raise ValueError("guide_topic_id_must_not_be_empty")
        if not self.title.strip():
            raise ValueError("guide_title_must_not_be_empty")
        if not self.summary.strip():
            raise ValueError("guide_summary_must_not_be_empty")
        if not self.steps:
            raise ValueError(f"guide_steps_must_not_be_empty:{self.topic_id}")

    def to_dict(self) -> dict[str, object]:
        return {
            "topic_id": self.topic_id,
            "title": self.title,
            "summary": self.summary,
            "steps": list(self.steps),
            "keyboard_controls": list(self.keyboard_controls),
            "gamepad_controls": list(self.gamepad_controls),
            "route_ids": list(self.route_ids),
        }


class SteamDemoGuideCatalog:
    def __init__(self, pages: Sequence[GuidePage]) -> None:
        normalized = tuple(pages)
        if not normalized:
            raise ValueError("guide_catalog_must_not_be_empty")
        by_id: dict[str, GuidePage] = {}
        route_map: dict[str, str] = {}
        for page in normalized:
            if page.topic_id in by_id:
                raise ValueError(f"duplicate_guide_topic:{page.topic_id}")
            by_id[page.topic_id] = page
            for route_id in page.route_ids:
                route_map.setdefault(route_id, page.topic_id)
        self._pages = normalized
        self._by_id = by_id
        self._route_map = route_map

    @property
    def pages(self) -> tuple[GuidePage, ...]:
        return self._pages

    def get(self, topic_id: str) -> GuidePage:
        try:
            return self._by_id[topic_id]
        except KeyError as exc:
            raise ValueError(f"unknown_guide_topic:{topic_id}") from exc

    def index_of(self, topic_id: str) -> int:
        for index, page in enumerate(self._pages):
            if page.topic_id == topic_id:
                return index
        raise ValueError(f"unknown_guide_topic:{topic_id}")

    def topic_for_route(self, route_id: str | None) -> str:
        if route_id is None:
            return "welcome"
        return self._route_map.get(str(route_id), "objectives")


@dataclass(frozen=True)
class GuideViewModel:
    visible: bool
    page: GuidePage | None
    page_index: int
    page_count: int
    opened_from: str | None
    first_run: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "visible": self.visible,
            "page": self.page.to_dict() if self.page is not None else None,
            "page_index": self.page_index,
            "page_count": self.page_count,
            "opened_from": self.opened_from,
            "first_run": self.first_run,
        }


class SteamDemoGuideSession:
    def __init__(self, catalog: SteamDemoGuideCatalog) -> None:
        self._catalog = catalog
        self._visible = False
        self._page_index = 0
        self._opened_from: str | None = None
        self._first_run = False

    @property
    def catalog(self) -> SteamDemoGuideCatalog:
        return self._catalog

    @property
    def visible(self) -> bool:
        return self._visible

    @property
    def current_page(self) -> GuidePage:
        return self._catalog.pages[self._page_index]

    def current_view(self) -> GuideViewModel:
        return GuideViewModel(
            visible=self._visible,
            page=self.current_page if self._visible else None,
            page_index=self._page_index,
            page_count=len(self._catalog.pages),
            opened_from=self._opened_from,
            first_run=self._first_run,
        )

    def open_topic(
        self,
        topic_id: str,
        *,
        opened_from: str,
        first_run: bool = False,
    ) -> GuideViewModel:
        self._page_index = self._catalog.index_of(topic_id)
        self._visible = True
        self._opened_from = opened_from
        self._first_run = bool(first_run)
        return self.current_view()

    def open_for_route(self, route_id: str | None) -> GuideViewModel:
        return self.open_topic(
            self._catalog.topic_for_route(route_id),
            opened_from=f"route:{route_id or 'unknown'}",
        )

    def next_page(self) -> GuideViewModel:
        if self._visible and self._page_index < len(self._catalog.pages) - 1:
            self._page_index += 1
        return self.current_view()

    def previous_page(self) -> GuideViewModel:
        if self._visible and self._page_index > 0:
            self._page_index -= 1
        return self.current_view()

    def close(self) -> bool:
        completed_first_run = self._visible and self._first_run
        self._visible = False
        self._opened_from = None
        self._first_run = False
        return completed_first_run


def build_default_guide_catalog() -> SteamDemoGuideCatalog:
    return SteamDemoGuideCatalog(
        (
            GuidePage(
                topic_id="welcome",
                title="Project Asterveilへようこそ",
                summary="このデモでは、依頼を受け、移動し、戦闘に勝利して、工房とセーブまでを体験します。",
                steps=(
                    "New Gameを選ぶと、画面上部に現在の目標が表示されます。",
                    "★印の操作は、現在のデモ進行で推奨される行動です。",
                    "F1またはYボタンで、いつでも現在画面のガイドを開けます。",
                ),
                keyboard_controls=("Enter: 決定", "Esc: 戻る", "F1: ガイド"),
                gamepad_controls=("A: 決定", "B: 戻る", "Y: ガイド"),
                route_ids=("top_menu",),
            ),
            GuidePage(
                topic_id="controls",
                title="基本操作",
                summary="最後に操作した入力方式に合わせて、画面の操作ヒントが自動で切り替わります。",
                steps=(
                    "上下で項目を移動します。",
                    "決定で選択中の操作を実行します。",
                    "戻るでサブ画面から前の画面へ戻ります。",
                    "ゲームパッドを外した場合は、自動でキーボード表示へ戻ります。",
                ),
                keyboard_controls=("↑/W: 上", "↓/S: 下", "Enter/Space: 決定", "Esc: 戻る"),
                gamepad_controls=("D-pad/左スティック: 移動", "A: 決定", "B: 戻る"),
            ),
            GuidePage(
                topic_id="objectives",
                title="現在目標と推奨操作",
                summary="デモは順番に進みます。画面の現在目標と★印を確認してください。",
                steps=(
                    "未完了の最初の目標が現在目標として表示されます。",
                    "後の条件だけを満たしても、前の段階は飛び越えません。",
                    "迷った場合はトップ画面へ戻り、★印の操作を選びます。",
                ),
                route_ids=("item_use", "equipment", "inn"),
            ),
            GuidePage(
                topic_id="quest",
                title="依頼の受注と報告",
                summary="クエストボードでは、依頼の受注・進行状態・報告可否を確認できます。",
                steps=(
                    "最初の依頼を選択して受注します。",
                    "討伐条件を満たした後、クエストボードへ戻ります。",
                    "報酬は報告時に一度だけ受け取れます。",
                ),
                route_ids=("quest_board",),
            ),
            GuidePage(
                topic_id="travel",
                title="移動と探索",
                summary="移動画面で目的地を選び、採取・宝箱・イベント・戦闘へ進みます。",
                steps=(
                    "依頼の対象ロケーションを選びます。",
                    "無効な目的地は選択できません。",
                    "現在地が変わると、利用可能な探索行動も更新されます。",
                ),
                route_ids=("travel", "gathering", "treasure", "field_event", "npc_dialogue"),
            ),
            GuidePage(
                topic_id="battle",
                title="戦闘の進め方",
                summary="行動を選び、ターンを進めて敵を倒します。",
                steps=(
                    "選択可能な行動から実行するコマンドを選びます。",
                    "HP・SPと状態変化を確認しながら進めます。",
                    "勝利後はクエスト進行と現在目標が更新されます。",
                    "敗北や操作不能が発生した場合はサポートZIPを作成してください。",
                ),
                route_ids=("battle",),
            ),
            GuidePage(
                topic_id="workshop",
                title="工房・クラフト・装備",
                summary="素材を使ったクラフト、装備強化、分解、購入ができます。",
                steps=(
                    "必要素材と所持数を確認します。",
                    "無効なレシピや対象は実行できません。",
                    "装備変更ではメンバー、部位、装備候補の順に選びます。",
                ),
                route_ids=("shop", "crafting", "equipment_upgrade", "equipment_salvage"),
            ),
            GuidePage(
                topic_id="save_continue",
                title="セーブとContinue",
                summary="デモチェックポイントを保存すると、タイトルのContinueから再開できます。",
                steps=(
                    "チェックポイント保存後、タイトルへ戻ります。",
                    "Continueを選び、現在地・依頼・所持品が復元されることを確認します。",
                    "セーブが読み込めない場合でも、元ファイルを自動上書きしません。",
                ),
            ),
            GuidePage(
                topic_id="troubleshooting",
                title="トラブルシューティング",
                summary="不具合報告には、対象Buildと診断情報を添えると調査が早くなります。",
                steps=(
                    "タイトルまたは設定画面からサポートZIPを作成します。",
                    "ZIPにはログ・クラッシュレポート・設定・環境情報が含まれます。",
                    "セーブ本体は含まれず、ファイルサイズとSHA-256などのメタデータだけを記録します。",
                    "再現手順、期待結果、実際の結果をGitHub Issueへ記載します。",
                ),
            ),
        )
    )
