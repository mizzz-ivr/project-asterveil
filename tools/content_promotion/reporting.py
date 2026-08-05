from __future__ import annotations

import json
from pathlib import Path

from tools.chapter_content_pack import KINDS

from .catalog import PromotionEvaluation


def render_summary(evaluation: PromotionEvaluation) -> str:
    plan = evaluation.plan
    lines = [
        f"# Chapter Content Promotion: {plan['chapter_id']}",
        "",
        f"- Status: **{plan['status']}**",
        f"- Pack SHA-256: `{plan['pack_sha256']}`",
        f"- Catalog SHA-256: `{plan['catalog_sha256']}`",
        "- 自動適用: 非対応",
        "",
        "## 変更分類",
    ]
    for kind in KINDS:
        values = plan["classifications"][kind]
        lines.extend(
            [
                f"### {kind}",
                f"- Add: {len(values['add'])}",
                f"- Unchanged: {len(values['unchanged'])}",
                f"- Conflict: {len(values['conflict'])}",
            ]
        )

    lines.extend(["", "## 未解決参照"])
    lines.extend(
        [
            f"- {value['source_kind']}:{value['source_id']} "
            f"`{value['field']}` → {value['target_kind']}:{value['target_id']} "
            f"({value['reason']})"
            for value in plan["unresolved_references"]
        ]
        or ["- なし"]
    )

    lines.extend(["", "## ID競合"])
    lines.extend(
        [
            f"- {value['kind']}:{value['id']} {value['reason']}"
            for value in plan["conflicts"]
        ]
        or ["- なし"]
    )

    lines.extend(
        [
            "",
            "## ローカライズ候補",
            f"- Candidate Count: {len(plan['localization_candidates'])}",
            "",
            "## Warning",
        ]
    )
    lines.extend([f"- {warning}" for warning in plan["warnings"]] or ["- なし"])
    return "\n".join(lines) + "\n"


def write_outputs(evaluation: PromotionEvaluation, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "PROMOTION_PLAN.json").write_text(
        json.dumps(evaluation.plan, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "PROMOTION_SUMMARY.md").write_text(
        render_summary(evaluation),
        encoding="utf-8",
    )
    (output / "localization.ja.candidates.json").write_text(
        json.dumps(
            {
                value["key"]: value["ja"]
                for value in evaluation.plan["localization_candidates"]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
