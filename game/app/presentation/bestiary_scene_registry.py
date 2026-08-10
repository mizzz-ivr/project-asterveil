from __future__ import annotations

from game.app.presentation.bestiary_screen import (
    BestiaryScreenMode,
    BestiaryScreenViewModel,
)
from game.app.presentation.screen_renderer import (
    SceneEntry,
    SceneField,
    SceneSection,
    SteamDemoSceneBuilderRegistry,
    SteamDemoSceneModel,
)
from game.app.presentation.screen_router import SteamDemoRouteId


class BestiarySceneBuilderRegistry(SteamDemoSceneBuilderRegistry):
    """既存Scene Registryを変更せず、図鑑Routeだけを追加する拡張。"""

    def registered_routes(self) -> tuple[SteamDemoRouteId, ...]:
        routes = super().registered_routes()
        if SteamDemoRouteId.BESTIARY in routes:
            return routes
        return (*routes, SteamDemoRouteId.BESTIARY)

    def build(self, route_id: SteamDemoRouteId, view: object) -> SteamDemoSceneModel:
        if route_id != SteamDemoRouteId.BESTIARY:
            return super().build(route_id, view)
        if not isinstance(view, BestiaryScreenViewModel):
            raise TypeError(
                "scene_view_type_mismatch:"
                f"{route_id.value}:expected=BestiaryScreenViewModel:"
                f"actual={type(view).__name__}"
            )
        return self._build_bestiary(view)

    @classmethod
    def _build_bestiary(cls, view: BestiaryScreenViewModel) -> SteamDemoSceneModel:
        if view.mode == BestiaryScreenMode.DETAIL:
            return cls._build_detail(view)
        return cls._build_list(view)

    @classmethod
    def _build_list(cls, view: BestiaryScreenViewModel) -> SteamDemoSceneModel:
        filter_entries = tuple(
            SceneEntry(
                entry_id=item.action_id,
                label=item.label,
                is_selected=view.selection.selected_index == index,
                is_recommended=item.is_active,
            )
            for index, item in enumerate(view.filters)
        )
        entry_offset = len(view.filters)
        enemy_entries = tuple(
            SceneEntry(
                entry_id=item.action_id,
                label=f"{item.slot_label}  {item.name}",
                fields=tuple(
                    field
                    for field in (
                        SceneField("stage", "解放段階", item.stage_label),
                        SceneField("category", "種別", item.category_label),
                        SceneField("encounters", "遭遇", item.encounter_count),
                        SceneField("wins", "勝利", item.battle_win_count),
                        SceneField("kills", "討伐", item.kill_count),
                        SceneField("losses", "敗北", item.battle_loss_count),
                    )
                    if field.value is not None
                ),
                is_selected=view.selection.selected_index == entry_offset + index,
            )
            for index, item in enumerate(view.entries)
        )

        progress_by_category = {item.category: item for item in view.progress}
        overall = progress_by_category.get("overall")
        normal = progress_by_category.get("normal")
        boss = progress_by_category.get("boss")
        status: list[SceneField] = [
            SceneField("filter", "表示", cls._filter_label(view)),
        ]
        if overall is not None:
            status.extend(
                [
                    SceneField(
                        "overall_encountered",
                        "全体遭遇",
                        f"{overall.encountered_count}/{overall.total_count} ({overall.encounter_rate_percent}%)",
                    ),
                    SceneField(
                        "overall_mastered",
                        "全体熟練",
                        f"{overall.mastered_count}/{overall.total_count} ({overall.mastery_rate_percent}%)",
                    ),
                ]
            )
        if normal is not None:
            status.append(
                SceneField(
                    "normal_progress",
                    "通常敵",
                    f"遭遇 {normal.encountered_count}/{normal.total_count} / 熟練 {normal.mastered_count}/{normal.total_count}",
                )
            )
        if boss is not None:
            status.append(
                SceneField(
                    "boss_progress",
                    "Boss",
                    f"遭遇 {boss.encountered_count}/{boss.total_count} / 熟練 {boss.mastered_count}/{boss.total_count}",
                )
            )

        return SteamDemoSceneModel(
            route_id=SteamDemoRouteId.BESTIARY,
            title=view.title,
            subtitle="遭遇と討伐を重ねると、攻略情報が段階的に解放されます。",
            status=tuple(status),
            sections=(
                SceneSection("filters", "表示フィルター", filter_entries),
                SceneSection("enemies", "モンスター一覧", enemy_entries),
            ),
        )

    @classmethod
    def _build_detail(cls, view: BestiaryScreenViewModel) -> SteamDemoSceneModel:
        detail = view.detail
        if detail is None:
            raise ValueError("bestiary_detail_view_missing")

        status: list[SceneField] = [
            SceneField("stage", "解放段階", detail.stage_label),
        ]
        if detail.category_label is not None:
            status.append(SceneField("category", "種別", detail.category_label))
        if detail.habitat_names:
            status.append(
                SceneField("habitat", "生息地", " / ".join(detail.habitat_names))
            )
        if detail.encounter_count > 0:
            status.extend(
                [
                    SceneField("encounters", "遭遇", detail.encounter_count),
                    SceneField("wins", "勝利", detail.battle_win_count),
                    SceneField("kills", "討伐", detail.kill_count),
                    SceneField("losses", "敗北", detail.battle_loss_count),
                ]
            )
        if detail.level is not None:
            status.append(SceneField("level", "Lv", detail.level))
        for stat_name, value in detail.stats:
            status.append(
                SceneField(
                    f"stat_{stat_name}",
                    stat_name.upper(),
                    value,
                )
            )
        if detail.weakness_elements:
            status.append(
                SceneField(
                    "weakness_elements",
                    "弱点属性",
                    " / ".join(detail.weakness_elements),
                )
            )
        if detail.weakness_weapon_types:
            status.append(
                SceneField(
                    "weakness_weapon_types",
                    "弱点武器",
                    " / ".join(detail.weakness_weapon_types),
                )
            )

        subtitle = detail.description
        if subtitle is None:
            subtitle = {
                "unknown": "まだ遭遇していません。",
                "encountered": "討伐すると能力値と弱点が解放されます。",
                "defeated": "討伐を重ねると詳細な生態情報が解放されます。",
            }.get(detail.stage.value, "情報を収集中です。")

        return SteamDemoSceneModel(
            route_id=SteamDemoRouteId.BESTIARY,
            title=detail.name,
            subtitle=subtitle,
            status=tuple(status),
            sections=tuple(),
            is_completed=detail.stage.value == "mastered",
        )

    @staticmethod
    def _filter_label(view: BestiaryScreenViewModel) -> str:
        return {
            "all": "すべて",
            "normal": "通常敵",
            "boss": "Boss",
        }[view.active_filter.value]
