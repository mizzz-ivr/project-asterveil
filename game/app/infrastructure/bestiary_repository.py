from __future__ import annotations

import json
from pathlib import Path

from game.app.application.bestiary_service import (
    BestiaryCatalog,
    BestiaryDefinition,
    EnemyBattleProfile,
)


class BestiaryMasterDataRepository:
    def __init__(self, root: Path) -> None:
        self._root = root

    def load(self) -> BestiaryCatalog:
        definitions = self._load_definitions()
        profiles = self._load_profiles()
        encounter_rosters = self._load_encounter_rosters()
        location_names = self._load_location_names()

        definition_ids = set(definitions)
        profile_ids = set(profiles)
        if definition_ids != profile_ids:
            missing = sorted(profile_ids - definition_ids)
            extra = sorted(definition_ids - profile_ids)
            raise ValueError(
                "enemy_bestiary.sample.json coverage mismatch:"
                f"missing={','.join(missing) or 'none'}:extra={','.join(extra) or 'none'}"
            )

        for definition in definitions.values():
            unknown_locations = sorted(
                location_id
                for location_id in definition.habitat_location_ids
                if location_id not in location_names
            )
            if unknown_locations:
                raise ValueError(
                    "enemy_bestiary.sample.json unknown habitat location:"
                    f"enemy_id={definition.enemy_id}:"
                    f"location_ids={','.join(unknown_locations)}"
                )

        return BestiaryCatalog(
            definitions=definitions,
            profiles=profiles,
            encounter_rosters=encounter_rosters,
            location_names=location_names,
        )

    def _load_definitions(self) -> dict[str, BestiaryDefinition]:
        raw = self._read_json("enemy_bestiary.sample.json")
        if not isinstance(raw, list):
            raise ValueError("enemy_bestiary.sample.json root must be list")
        definitions: dict[str, BestiaryDefinition] = {}
        for entry in raw:
            if not isinstance(entry, dict):
                raise ValueError("enemy_bestiary.sample.json entry must be object")
            enemy_id = str(entry.get("enemy_id") or "")
            if not enemy_id:
                raise ValueError("enemy_bestiary.sample.json missing field=enemy_id")
            if enemy_id in definitions:
                raise ValueError(f"enemy_bestiary.sample.json duplicate enemy_id={enemy_id}")
            display_name = str(entry.get("display_name") or "").strip()
            description = str(entry.get("description") or "").strip()
            category = str(entry.get("category") or "").strip()
            if not display_name:
                raise ValueError(
                    f"enemy_bestiary.sample.json missing display_name enemy_id={enemy_id}"
                )
            if not description:
                raise ValueError(
                    f"enemy_bestiary.sample.json missing description enemy_id={enemy_id}"
                )
            if category not in {"normal", "boss"}:
                raise ValueError(
                    "enemy_bestiary.sample.json category must be normal/boss:"
                    f"enemy_id={enemy_id}:category={category}"
                )
            mastery_kill_count = self._positive_int(
                entry.get("mastery_kill_count"),
                f"enemy_id={enemy_id}:mastery_kill_count",
            )
            habitats = tuple(
                str(location_id)
                for location_id in entry.get("habitat_location_ids", [])
                if str(location_id)
            )
            if not habitats:
                raise ValueError(
                    f"enemy_bestiary.sample.json habitat required enemy_id={enemy_id}"
                )
            definitions[enemy_id] = BestiaryDefinition(
                enemy_id=enemy_id,
                display_name=display_name,
                category=category,
                habitat_location_ids=habitats,
                description=description,
                mastery_kill_count=mastery_kill_count,
            )
        return definitions

    def _load_profiles(self) -> dict[str, EnemyBattleProfile]:
        raw = self._read_json("enemies.sample.json")
        if not isinstance(raw, list):
            raise ValueError("enemies.sample.json root must be list")
        profiles: dict[str, EnemyBattleProfile] = {}
        for entry in raw:
            if not isinstance(entry, dict):
                raise ValueError("enemies.sample.json entry must be object")
            enemy_id = str(entry.get("id") or entry.get("enemy_id") or "")
            if not enemy_id:
                raise ValueError("enemies.sample.json missing field=id")
            if enemy_id in profiles:
                raise ValueError(f"enemies.sample.json duplicate enemy_id={enemy_id}")
            raw_stats = entry.get("stats")
            if not isinstance(raw_stats, dict):
                raise ValueError(f"enemies.sample.json stats must be object enemy_id={enemy_id}")
            stats = {
                str(key): self._non_negative_int(value, f"enemy_id={enemy_id}:stats.{key}")
                for key, value in raw_stats.items()
            }
            if stats.get("hp", 0) <= 0:
                raise ValueError(f"enemies.sample.json hp must be positive enemy_id={enemy_id}")
            weakness = entry.get("weakness", {})
            if not isinstance(weakness, dict):
                raise ValueError(
                    f"enemies.sample.json weakness must be object enemy_id={enemy_id}"
                )
            profiles[enemy_id] = EnemyBattleProfile(
                enemy_id=enemy_id,
                level=self._positive_int(entry.get("level"), f"enemy_id={enemy_id}:level"),
                stats=stats,
                weakness_elements=tuple(
                    str(value) for value in weakness.get("elements", []) if str(value)
                ),
                weakness_weapon_types=tuple(
                    str(value) for value in weakness.get("weapon_types", []) if str(value)
                ),
            )
        return profiles

    def _load_encounter_rosters(self) -> dict[str, dict[str, int]]:
        raw = self._read_json("encounters.sample.json")
        if not isinstance(raw, list):
            raise ValueError("encounters.sample.json root must be list")
        rosters: dict[str, dict[str, int]] = {}
        for entry in raw:
            if not isinstance(entry, dict):
                raise ValueError("encounters.sample.json entry must be object")
            encounter_id = str(entry.get("encounter_id") or "")
            if not encounter_id:
                raise ValueError("encounters.sample.json missing field=encounter_id")
            if encounter_id in rosters:
                raise ValueError(
                    f"encounters.sample.json duplicate encounter_id={encounter_id}"
                )
            enemies = entry.get("enemies", [])
            if not isinstance(enemies, list) or not enemies:
                raise ValueError(
                    f"encounters.sample.json enemies required encounter_id={encounter_id}"
                )
            roster: dict[str, int] = {}
            for enemy in enemies:
                if not isinstance(enemy, dict):
                    raise ValueError(
                        f"encounters.sample.json enemy entry must be object encounter_id={encounter_id}"
                    )
                enemy_id = str(enemy.get("enemy_id") or "")
                if not enemy_id:
                    raise ValueError(
                        f"encounters.sample.json missing enemy_id encounter_id={encounter_id}"
                    )
                count = self._positive_int(
                    enemy.get("count", 1),
                    f"encounter_id={encounter_id}:enemy_id={enemy_id}:count",
                )
                roster[enemy_id] = roster.get(enemy_id, 0) + count
            rosters[encounter_id] = roster
        return rosters

    def _load_location_names(self) -> dict[str, str]:
        raw = self._read_json("locations.sample.json")
        if not isinstance(raw, list):
            raise ValueError("locations.sample.json root must be list")
        result: dict[str, str] = {}
        for entry in raw:
            if not isinstance(entry, dict):
                raise ValueError("locations.sample.json entry must be object")
            location_id = str(entry.get("location_id") or entry.get("id") or "")
            if not location_id:
                raise ValueError("locations.sample.json missing field=location_id")
            if location_id in result:
                raise ValueError(f"locations.sample.json duplicate location_id={location_id}")
            result[location_id] = str(entry.get("name") or location_id)
        return result

    def _read_json(self, filename: str) -> object:
        return json.loads((self._root / filename).read_text(encoding="utf-8"))

    @staticmethod
    def _positive_int(raw: object, field_name: str) -> int:
        value = BestiaryMasterDataRepository._non_negative_int(raw, field_name)
        if value <= 0:
            raise ValueError(f"{field_name} must be positive")
        return value

    @staticmethod
    def _non_negative_int(raw: object, field_name: str) -> int:
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise ValueError(f"{field_name} must be int")
        if raw < 0:
            raise ValueError(f"{field_name} must be non-negative")
        return raw
