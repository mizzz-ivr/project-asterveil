from __future__ import annotations

from typing import Any, Mapping

from .bundle import (
    BundleVerification,
    apply_bundle,
    verify_bundle,
    write_bundle,
)
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
    "BundleVerification",
    "MasterCatalog",
    "PromotionError",
    "PromotionEvaluation",
    "apply_bundle",
    "evaluate_promotion",
    "load_catalog",
    "render_summary",
    "verify_bundle",
    "write_bundle",
    "write_outputs",
]
