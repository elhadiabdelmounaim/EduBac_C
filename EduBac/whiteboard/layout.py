"""
Layout déterministe pour les éléments de correction.
L'IA ne fournit pas de coordonnées ; on les assigne ici.
Ordre logique : titre → données/question → règle → étapes/calculs → résultat.
"""
from __future__ import annotations

from typing import Any

COL_WIDTH = 280
ROW_GAP = 24
COL_GAP = 40
START_X = 40
START_Y = 40
DEFAULT_H = {
    "title": 56,
    "text": 100,
    "step": 110,
    "formula": 80,
    "rule": 90,
    "calculation": 90,
    "result": 72,
    "table": 160,
    "chart": 200,
    "diagram": 200,
}


def apply_layout(doc: dict) -> dict:
    """Assigne position/size si absents ou à (0,0) pour tous les éléments."""
    elements = doc.get("elements") or []
    if not elements:
        return doc

    # Priorité de colonnes
    type_col = {
        "title": 0,
        "text": 0,
        "rule": 1,
        "step": 1,
        "formula": 1,
        "calculation": 2,
        "table": 2,
        "chart": 2,
        "diagram": 2,
        "result": 3,
    }
    columns: dict[int, list[dict]] = {0: [], 1: [], 2: [], 3: []}
    for el in elements:
        col = type_col.get(el.get("type"), 1)
        columns[col].append(el)

    for col_idx, items in columns.items():
        y = START_Y
        x = START_X + col_idx * (COL_WIDTH + COL_GAP)
        for i, el in enumerate(items):
            et = el.get("type", "text")
            h = DEFAULT_H.get(et, 90)
            # Respecter size existante si déjà posée par l'élève (x/y non nuls)
            pos = el.get("position") or {}
            if pos.get("x") or pos.get("y"):
                # déjà positionné — ne pas écraser
                continue
            el["position"] = {"x": x, "y": y}
            size = el.get("size") or {}
            w = int(size.get("width") or COL_WIDTH)
            h = int(size.get("height") or h)
            el["size"] = {"width": max(40, min(w, 2000)), "height": max(40, min(h, 2000))}
            el["zIndex"] = el.get("zIndex", col_idx * 10 + i)
            y += h + ROW_GAP

    doc["elements"] = elements
    return doc
