from __future__ import annotations

from typing import Any, Mapping

from .catalog import (
    MasterCatalog,
    PromotionError,
    PromotionEvaluation,
    load_catalog,
    pack_index,
)
from .master_contracts import validate_master_contracts
from .reporting import render_summary, write_outputs
from .validation import evaluate_promotion as _evaluate_promotion


def evaluate_promotion(
    pack: Mapping[str, Any],
    catalog: MasterCatalog,
) -> PromotionEvaluation:
    index = pack_index(pack)
    validate_master_contracts(index, catalog)
    return _evaluate_promotion(pack, catalog)


__all__ = [
    "MasterCatalog",
    "PromotionError",
    "PromotionEvaluation",
    "evaluate_promotion",
    "load_catalog",
    "render_summary",
    "write_outputs",
]
