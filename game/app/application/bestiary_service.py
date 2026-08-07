from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from game.quest.domain.entities import BattleResult


BESTIARY_STATE_VERSION = 1


class BestiaryUnlockStage(str, Enum):
    UNKNOWN = "unknown"
    ENCOUNTERED = "encountered"
    DEFEATED = "defeated"
    MASTERED = "mastered"


@dataclass(frozen=True)
class BestiaryDefinition:
    enemy_id: str
    display_name: str
    category: str
    habitat_location_ids: tuple[str, ...]
    description: str
    mastery_kill_count: int


@dataclass(frozen=True)
class EnemyBattleProfile:
    enemy_id: str
    level: int
    stats: Mapping[str, int]
    weakness_elements: tuple[str, ...]
    weakness_weapon_types: tuple[str, ...]


@dataclass(frozen=True)
class BestiaryCatalog:
    definitions: Mapping[str, BestiaryDefinition]
    profiles: Mapping[str, EnemyBattleProfile]
    encounter_rosters: Mapping[str, Mapping[str, int]]
    location_names: Mapping[str, str]


@dataclass(frozen=True)
class BestiaryRecord:
    encounter_count: int = 0
    battle_win_count: int = 0
    kill_count: int = 0
    battle_loss_count: int = 0


@dataclass(frozen=True)
class BestiaryEntryView:
    enemy_id: str
    stage: BestiaryUnlockStage
    category: str
    encounter_count: int
    battle_win_count: int
    kill_count: int
    battle_loss_count: int
    display_name: str | None = None
    habitat_names: tuple[str, ...] = tuple()
    level: int | None = None
    stats: Mapping[str, int] | None = None
    weakness_elements: tuple[str, ...] = tuple()
    weakness_weapon_types: tuple[str, ...] = tuple()
    description: str | None = None


@dataclass(frozen=True)
class BestiaryProgressSummary:
    category: str
    total_count: int
    encountered_count: int
    defeated_count: int
    mastered_count: int

    @property
    def encounter_rate_percent(self) -> int:
        if self.total_count == 0:
            return 0
        return int(self.encountered_count * 100 / self.total_count)

    @property
    def mastery_rate_percent(self) -> int:
        if self.total_count == 0:
            return 0
        return int(self.mastered_count * 100 / self.total_count)


BestiaryState = dict[str, BestiaryRecord]


class BestiaryService:
    def __init__(self, catalog: BestiaryCatalog) -> None:
        self._catalog = catalog
        self._validate_catalog()

    @property
    def catalog(self) -> BestiaryCatalog:
        return self._catalog

    def record_battle(
        self,
        state: BestiaryState,
        *,
        encounter_id: str,
        battle_result: BattleResult,
    ) -> tuple[str, ...]:
        if battle_result.encounter_id != encounter_id:
            raise ValueError(
                "bestiary_battle_result_encounter_mismatch:"
                f"expected={encounter_id}:actual={battle_result.encounter_id}"
            )

        roster = self._catalog.encounter_rosters.get(encounter_id)
        if roster is None:
            raise ValueError(f"bestiary_unknown_encounter_id:{encounter_id}")

        defeated_counts = Counter(battle_result.defeated_enemy_ids)
        unknown_defeated = sorted(
            enemy_id for enemy_id in defeated_counts if enemy_id not in roster
        )
        if unknown_defeated:
            raise ValueError(
                "bestiary_defeated_enemy_not_in_encounter:"
                f"encounter_id={encounter_id}:enemy_ids={','.join(unknown_defeated)}"
            )
        over_defeated = sorted(
            enemy_id
            for enemy_id, count in defeated_counts.items()
            if count > roster[enemy_id]
        )
        if over_defeated:
            raise ValueError(
                "bestiary_defeated_enemy_count_exceeds_roster:"
                f"encounter_id={encounter_id}:enemy_ids={','.join(over_defeated)}"
            )

        changed_enemy_ids: list[str] = []
        for enemy_id, encounter_enemy_count in roster.items():
            before = state.get(enemy_id, BestiaryRecord())
            after = BestiaryRecord(
                encounter_count=before.encounter_count + encounter_enemy_count,
                battle_win_count=before.battle_win_count + (1 if battle_result.player_won else 0),
                kill_count=before.kill_count + defeated_counts.get(enemy_id, 0),
                battle_loss_count=before.battle_loss_count + (0 if battle_result.player_won else 1),
            )
            state[enemy_id] = after
            changed_enemy_ids.append(enemy_id)

        return tuple(changed_enemy_ids)

    def entry_view(self, state: BestiaryState, enemy_id: str) -> BestiaryEntryView:
        definition = self._catalog.definitions.get(enemy_id)
        profile = self._catalog.profiles.get(enemy_id)
        if definition is None or profile is None:
            raise ValueError(f"bestiary_unknown_enemy_id:{enemy_id}")

        record = state.get(enemy_id, BestiaryRecord())
        stage = self.unlock_stage(definition, record)
        encountered = stage != BestiaryUnlockStage.UNKNOWN
        defeated = stage in {BestiaryUnlockStage.DEFEATED, BestiaryUnlockStage.MASTERED}
        mastered = stage == BestiaryUnlockStage.MASTERED

        return BestiaryEntryView(
            enemy_id=enemy_id,
            stage=stage,
            category=definition.category,
            encounter_count=record.encounter_count,
            battle_win_count=record.battle_win_count,
            kill_count=record.kill_count,
            battle_loss_count=record.battle_loss_count,
            display_name=definition.display_name if encountered else None,
            habitat_names=(
                tuple(
                    self._catalog.location_names[location_id]
                    for location_id in definition.habitat_location_ids
                )
                if encountered
                else tuple()
            ),
            level=profile.level if defeated else None,
            stats=dict(profile.stats) if defeated else None,
            weakness_elements=profile.weakness_elements if defeated else tuple(),
            weakness_weapon_types=profile.weakness_weapon_types if defeated else tuple(),
            description=definition.description if mastered else None,
        )

    def list_entries(self, state: BestiaryState) -> tuple[BestiaryEntryView, ...]:
        return tuple(
            self.entry_view(state, enemy_id)
            for enemy_id in self._catalog.definitions
        )

    def progress_summary(
        self,
        state: BestiaryState,
        *,
        category: str | None = None,
    ) -> BestiaryProgressSummary:
        definitions = [
            definition
            for definition in self._catalog.definitions.values()
            if category is None or definition.category == category
        ]
        encountered_count = 0
        defeated_count = 0
        mastered_count = 0
        for definition in definitions:
            stage = self.unlock_stage(
                definition,
                state.get(definition.enemy_id, BestiaryRecord()),
            )
            if stage != BestiaryUnlockStage.UNKNOWN:
                encountered_count += 1
            if stage in {BestiaryUnlockStage.DEFEATED, BestiaryUnlockStage.MASTERED}:
                defeated_count += 1
            if stage == BestiaryUnlockStage.MASTERED:
                mastered_count += 1

        return BestiaryProgressSummary(
            category=category or "overall",
            total_count=len(definitions),
            encountered_count=encountered_count,
            defeated_count=defeated_count,
            mastered_count=mastered_count,
        )

    def serialize_state(self, state: BestiaryState) -> dict[str, object]:
        records: dict[str, dict[str, int]] = {}
        for enemy_id in self._catalog.definitions:
            record = state.get(enemy_id)
            if record is None or record == BestiaryRecord():
                continue
            records[enemy_id] = {
                "encounter_count": record.encounter_count,
                "battle_win_count": record.battle_win_count,
                "kill_count": record.kill_count,
                "battle_loss_count": record.battle_loss_count,
            }
        return {
            "version": BESTIARY_STATE_VERSION,
            "records": records,
        }

    def restore_state(self, raw: object) -> BestiaryState:
        if raw is None:
            return {}
        if not isinstance(raw, Mapping):
            raise ValueError("bestiary_state_must_be_mapping")
        version = self._read_non_negative_int(raw.get("version"), "version")
        if version != BESTIARY_STATE_VERSION:
            raise ValueError(f"bestiary_state_unsupported_version:{version}")
        raw_records = raw.get("records", {})
        if not isinstance(raw_records, Mapping):
            raise ValueError("bestiary_state_records_must_be_mapping")

        restored: BestiaryState = {}
        for enemy_id, raw_record in raw_records.items():
            normalized_enemy_id = str(enemy_id)
            if normalized_enemy_id not in self._catalog.definitions:
                # Master更新で削除されたIDはゲーム進行を止めない。
                continue
            if not isinstance(raw_record, Mapping):
                raise ValueError(
                    f"bestiary_state_record_must_be_mapping:{normalized_enemy_id}"
                )
            record = BestiaryRecord(
                encounter_count=self._read_non_negative_int(
                    raw_record.get("encounter_count", 0),
                    f"{normalized_enemy_id}.encounter_count",
                ),
                battle_win_count=self._read_non_negative_int(
                    raw_record.get("battle_win_count", 0),
                    f"{normalized_enemy_id}.battle_win_count",
                ),
                kill_count=self._read_non_negative_int(
                    raw_record.get("kill_count", 0),
                    f"{normalized_enemy_id}.kill_count",
                ),
                battle_loss_count=self._read_non_negative_int(
                    raw_record.get("battle_loss_count", 0),
                    f"{normalized_enemy_id}.battle_loss_count",
                ),
            )
            self._validate_record(normalized_enemy_id, record)
            if record != BestiaryRecord():
                restored[normalized_enemy_id] = record
        return restored

    @staticmethod
    def unlock_stage(
        definition: BestiaryDefinition,
        record: BestiaryRecord,
    ) -> BestiaryUnlockStage:
        if record.encounter_count <= 0:
            return BestiaryUnlockStage.UNKNOWN
        if record.kill_count <= 0:
            return BestiaryUnlockStage.ENCOUNTERED
        if record.kill_count < definition.mastery_kill_count:
            return BestiaryUnlockStage.DEFEATED
        return BestiaryUnlockStage.MASTERED

    def _validate_catalog(self) -> None:
        if not self._catalog.definitions:
            raise ValueError("bestiary_catalog_requires_definitions")
        definition_ids = set(self._catalog.definitions)
        profile_ids = set(self._catalog.profiles)
        if definition_ids != profile_ids:
            raise ValueError(
                "bestiary_definition_profile_ids_mismatch:"
                f"definitions={sorted(definition_ids)}:profiles={sorted(profile_ids)}"
            )
        for encounter_id, roster in self._catalog.encounter_rosters.items():
            if not roster:
                raise ValueError(f"bestiary_encounter_roster_empty:{encounter_id}")
            unknown = sorted(enemy_id for enemy_id in roster if enemy_id not in definition_ids)
            if unknown:
                raise ValueError(
                    "bestiary_encounter_unknown_enemy_ids:"
                    f"encounter_id={encounter_id}:enemy_ids={','.join(unknown)}"
                )
            if any(count <= 0 for count in roster.values()):
                raise ValueError(f"bestiary_encounter_count_must_be_positive:{encounter_id}")

    @staticmethod
    def _read_non_negative_int(raw: object, field_name: str) -> int:
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise ValueError(f"bestiary_state_field_must_be_int:{field_name}")
        if raw < 0:
            raise ValueError(f"bestiary_state_field_must_be_non_negative:{field_name}")
        return raw

    @staticmethod
    def _validate_record(enemy_id: str, record: BestiaryRecord) -> None:
        if record.encounter_count == 0 and (
            record.battle_win_count > 0
            or record.kill_count > 0
            or record.battle_loss_count > 0
        ):
            raise ValueError(f"bestiary_state_progress_without_encounter:{enemy_id}")
        if record.kill_count > record.encounter_count:
            raise ValueError(f"bestiary_state_kill_count_exceeds_encounters:{enemy_id}")
        if record.battle_win_count + record.battle_loss_count > record.encounter_count:
            raise ValueError(f"bestiary_state_battle_count_exceeds_encounters:{enemy_id}")
