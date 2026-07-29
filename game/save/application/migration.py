from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from game.save.domain.entities import SAVE_VERSION, SaveData


LEGACY_V0_TIMESTAMP = "1970-01-01T00:00:00+00:00"
SavePayload = dict[str, Any]
SaveMigrationFunction = Callable[[SavePayload], SavePayload]


@dataclass(frozen=True)
class SaveMigrationStep:
    from_version: int
    to_version: int
    name: str
    migrate: SaveMigrationFunction

    def __post_init__(self) -> None:
        if self.from_version < 0:
            raise ValueError("save_migration_from_version_must_not_be_negative")
        if self.to_version != self.from_version + 1:
            raise ValueError(
                "save_migration_step_must_increment_by_one:"
                f"from={self.from_version}:to={self.to_version}"
            )
        if not self.name.strip():
            raise ValueError("save_migration_step_name_must_not_be_empty")


@dataclass(frozen=True)
class SaveMigrationResult:
    save_data: SaveData
    payload: SavePayload
    original_version: int
    current_version: int
    applied_steps: tuple[str, ...]

    @property
    def migrated(self) -> bool:
        return self.original_version != self.current_version

    def to_dict(self) -> dict[str, object]:
        return {
            "original_version": self.original_version,
            "current_version": self.current_version,
            "migrated": self.migrated,
            "applied_steps": list(self.applied_steps),
        }


class SaveMigrationService:
    """Version付きセーブpayloadを現在契約へ決定的に移行する。"""

    def __init__(
        self,
        *,
        current_version: int = SAVE_VERSION,
        steps: Mapping[int, SaveMigrationStep] | None = None,
    ) -> None:
        if current_version < 1:
            raise ValueError("current_save_version_must_be_positive")
        self._current_version = current_version
        source_steps = self._default_steps() if steps is None else steps
        self._steps = dict(source_steps)
        self._validate_registry()

    @property
    def current_version(self) -> int:
        return self._current_version

    def registered_versions(self) -> tuple[int, ...]:
        return tuple(sorted(self._steps))

    def migrate(self, raw: Mapping[str, Any]) -> SaveMigrationResult:
        if not isinstance(raw, Mapping):
            raise ValueError("save_payload_must_be_mapping")

        payload = deepcopy(dict(raw))
        original_version = self._read_version(payload)
        if original_version > self._current_version:
            raise ValueError(
                "future_save_version_not_supported:"
                f"version={original_version}:current={self._current_version}"
            )

        applied_steps: list[str] = []
        version = original_version
        while version < self._current_version:
            step = self._steps.get(version)
            if step is None:
                raise ValueError(
                    "save_migration_step_missing:"
                    f"from={version}:to={version + 1}"
                )
            migrated_payload = step.migrate(deepcopy(payload))
            if not isinstance(migrated_payload, dict):
                raise ValueError(
                    f"save_migration_step_returned_non_mapping:{step.name}"
                )
            migrated_version = self._read_version(migrated_payload)
            if migrated_version != step.to_version:
                raise ValueError(
                    "save_migration_step_version_mismatch:"
                    f"step={step.name}:expected={step.to_version}:actual={migrated_version}"
                )
            payload = migrated_payload
            version = migrated_version
            applied_steps.append(step.name)

        save_data = SaveData.from_dict(payload)
        canonical_payload = save_data.to_dict()
        return SaveMigrationResult(
            save_data=save_data,
            payload=canonical_payload,
            original_version=original_version,
            current_version=self._current_version,
            applied_steps=tuple(applied_steps),
        )

    def _validate_registry(self) -> None:
        for from_version, step in self._steps.items():
            if from_version != step.from_version:
                raise ValueError(
                    "save_migration_registry_key_mismatch:"
                    f"key={from_version}:step={step.from_version}"
                )
            if step.to_version > self._current_version:
                raise ValueError(
                    "save_migration_step_exceeds_current_version:"
                    f"step={step.name}:to={step.to_version}:current={self._current_version}"
                )

    @staticmethod
    def _read_version(payload: Mapping[str, Any]) -> int:
        if "save_version" not in payload:
            raise ValueError("save_data missing field=save_version")
        raw_version = payload["save_version"]
        if isinstance(raw_version, bool):
            raise ValueError("save_version_must_be_integer")
        try:
            version = int(raw_version)
        except (TypeError, ValueError) as exc:
            raise ValueError("save_version_must_be_integer") from exc
        if version < 0:
            raise ValueError("save_version_must_not_be_negative")
        return version

    @staticmethod
    def _default_steps() -> Mapping[int, SaveMigrationStep]:
        return {
            0: SaveMigrationStep(
                from_version=0,
                to_version=1,
                name="save_v0_to_v1",
                migrate=_migrate_v0_to_v1,
            )
        }


def _migrate_v0_to_v1(raw: SavePayload) -> SavePayload:
    payload = deepcopy(raw)
    payload["save_version"] = 1

    player_profile = payload.get("player_profile")
    if isinstance(player_profile, dict):
        player_profile.setdefault("last_saved_at", LEGACY_V0_TIMESTAMP)

    party_state = payload.get("party_state")
    if isinstance(party_state, dict):
        members = party_state.get("members")
        if isinstance(members, list):
            for member in members:
                if not isinstance(member, dict):
                    continue
                current_hp = member.get("current_hp", 1)
                current_sp = member.get("current_sp", 0)
                member.setdefault("current_exp", 0)
                member.setdefault("next_level_exp", 100)
                member.setdefault("max_hp", current_hp)
                member.setdefault("max_sp", current_sp)
                member.setdefault("atk", 1)
                member.setdefault("defense", 1)
                member.setdefault("spd", 1)
                member.setdefault("equipped", {})
                member.setdefault("unlocked_skill_ids", [])
                member.setdefault("active_effects", [])

    quest_state = payload.get("quest_state")
    if isinstance(quest_state, dict):
        for quest in quest_state.values():
            if not isinstance(quest, dict):
                continue
            quest.setdefault("objective_item_progress", [])
            quest.setdefault("reward_claimed", False)
            quest.setdefault("repeat_ready", False)

    payload.setdefault("progression", {})
    payload.setdefault("inventory_state", {})
    payload.setdefault("meta", {})
    return payload
