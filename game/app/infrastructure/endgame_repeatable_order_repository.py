from __future__ import annotations

import json
from pathlib import Path

from game.app.application.endgame_repeatable_order_service import (
    EndgameOrderObjectiveDefinition,
    EndgameRepeatableOrderDefinition,
)


class EndgameRepeatableOrderMasterDataRepository:
    def __init__(self, root: Path) -> None:
        self._root = root

    def load(self) -> tuple[EndgameRepeatableOrderDefinition, ...]:
        path = self._root / "endgame_repeatable_orders.sample.json"
        if not path.exists():
            return tuple()
        rows = json.loads(path.read_text(encoding="utf-8"))
        definitions: list[EndgameRepeatableOrderDefinition] = []
        for row in rows:
            order_id = str(row.get("order_id") or "")
            if not order_id:
                raise ValueError("endgame_repeatable_orders.sample.json missing field=order_id")
            objective_defs = tuple(
                EndgameOrderObjectiveDefinition(
                    objective_id=str(obj.get("objective_id") or ""),
                    objective_type=str(obj.get("objective_type") or ""),
                    description=str(obj.get("description") or ""),
                    requirements={str(k): str(v) for k, v in dict(obj.get("requirements", {})).items()},
                )
                for obj in row.get("objectives", [])
            )
            if not objective_defs:
                raise ValueError(f"endgame_repeatable_orders.sample.json objectives required order_id={order_id}")
            definitions.append(
                EndgameRepeatableOrderDefinition(
                    order_id=order_id,
                    name=str(row.get("name") or order_id),
                    description=str(row.get("description") or ""),
                    required_unlock_flags=tuple(str(v) for v in row.get("required_unlock_flags", [])),
                    required_workshop_level=max(1, int(row.get("required_workshop_level", 1))),
                    repeatable=bool(row.get("repeatable", False)),
                    repeat_reset_rule=str(row.get("repeat_reset_rule") or "manual_reaccept"),
                    objectives=objective_defs,
                    rewards={str(k): int(v) for k, v in dict(row.get("rewards", {})).items()},
                    reward_category=str(row.get("reward_category") or "materials"),
                )
            )
        return tuple(definitions)
