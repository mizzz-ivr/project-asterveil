from __future__ import annotations

import json
from pathlib import Path

from game.app.application.workshop_special_chain_service import (
    WorkshopSpecialChainDefinition,
    WorkshopSpecialChainStageDefinition,
)


class WorkshopSpecialChainMasterDataRepository:
    def __init__(self, root: Path) -> None:
        self._root = root

    def load(self) -> tuple[WorkshopSpecialChainDefinition, ...]:
        path = self._root / "workshop_special_chains.sample.json"
        if not path.exists():
            return tuple()
        rows = json.loads(path.read_text(encoding="utf-8"))
        defs: list[WorkshopSpecialChainDefinition] = []
        for row in rows:
            chain_id = str(row.get("chain_id") or "")
            if not chain_id:
                raise ValueError("workshop_special_chains.sample.json missing field=chain_id")
            stage_defs = tuple(
                WorkshopSpecialChainStageDefinition(
                    stage_id=str(s.get("stage_id") or ""),
                    stage_type=str(s.get("stage_type") or ""),
                    description=str(s.get("description") or ""),
                    requirements={str(k): str(v) for k, v in dict(s.get("requirements", {})).items()},
                    rewards=tuple(str(v) for v in s.get("rewards", [])),
                )
                for s in row.get("stages", [])
            )
            if not stage_defs:
                raise ValueError(f"workshop_special_chains.sample.json stages required chain_id={chain_id}")
            defs.append(
                WorkshopSpecialChainDefinition(
                    chain_id=chain_id,
                    name=str(row.get("name") or chain_id),
                    description=str(row.get("description") or ""),
                    required_workshop_level=max(1, int(row.get("required_workshop_level", 1))),
                    stages=stage_defs,
                    final_rewards=tuple(str(v) for v in row.get("final_rewards", [])),
                    unlock_flags=tuple(str(v) for v in row.get("unlock_flags", [])),
                )
            )
        return tuple(defs)
