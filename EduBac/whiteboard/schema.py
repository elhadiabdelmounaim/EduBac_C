"""
Validation serveur du document Whiteboard de correction (v1).
Source de vérité — ne jamais faire confiance au client ni à l'IA.
"""
from __future__ import annotations

import json
import re
from typing import Any

SCHEMA_VERSION = 1
MAX_ELEMENTS = 60
MAX_CONNECTIONS = 100
MAX_JSON_BYTES = 200_000
MAX_TITLE = 120
MAX_TEXT = 2000
MAX_LABEL = 40
MAX_LATEX = 500
ID_RE = re.compile(r"^[a-z0-9_-]{1,40}$")

ALLOWED_TYPES = frozenset({
    "title", "text", "step", "formula", "rule",
    "calculation", "result", "table", "chart", "diagram",
})
ALLOWED_EMPHASIS = frozenset({"normal", "success", "warning", "error"})
ALLOWED_ANCHORS = frozenset({"top", "bottom", "left", "right"})
ALLOWED_CHART_KINDS = frozenset({"line", "bar", "scatter"})
ALLOWED_DIAGRAM_KINDS = frozenset({"geometry", "flow"})
ALLOWED_PRIMITIVES = frozenset({
    "point", "segment", "circle", "polygon", "angle_mark", "label", "node", "edge",
})


class SchemaError(ValueError):
    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(message)
        self.code = code


def _int_in(v: Any, lo: int, hi: int, name: str) -> int:
    if not isinstance(v, int) or isinstance(v, bool):
        raise SchemaError(f"{name} doit être un entier", "type")
    if v < lo or v > hi:
        raise SchemaError(f"{name} hors limites ({lo}…{hi})", "bounds")
    return v


def _str_max(v: Any, n: int, name: str, required: bool = True) -> str:
    if v is None:
        if required:
            raise SchemaError(f"{name} requis", "required")
        return ""
    if not isinstance(v, str):
        raise SchemaError(f"{name} doit être une chaîne", "type")
    # Rejeter HTML / scripts évidents
    low = v.lower()
    for bad in ("<script", "javascript:", "onerror=", "onload=", "<iframe", "<svg"):
        if bad in low:
            raise SchemaError(f"{name} contient du contenu interdit", "unsafe")
    if len(v) > n:
        raise SchemaError(f"{name} trop long (max {n})", "length")
    return v


def _validate_element(el: dict, seen_ids: set[str]) -> dict:
    if not isinstance(el, dict):
        raise SchemaError("élément invalide", "type")
    eid = el.get("id")
    if not isinstance(eid, str) or not ID_RE.match(eid):
        raise SchemaError(f"id invalide: {eid!r}", "id")
    if eid in seen_ids:
        raise SchemaError(f"id dupliqué: {eid}", "duplicate")
    seen_ids.add(eid)

    etype = el.get("type")
    if etype not in ALLOWED_TYPES:
        raise SchemaError(f"type inconnu: {etype}", "type")

    pos = el.get("position") or {}
    if not isinstance(pos, dict):
        raise SchemaError("position invalide", "type")
    x = _int_in(int(pos.get("x", 0)), -5000, 5000, "position.x")
    y = _int_in(int(pos.get("y", 0)), -5000, 5000, "position.y")

    size = el.get("size") or {}
    if not isinstance(size, dict):
        raise SchemaError("size invalide", "type")
    w = _int_in(int(size.get("width", 220)), 40, 2000, "size.width")
    h = _int_in(int(size.get("height", 80)), 40, 2000, "size.height")

    z = int(el.get("zIndex", 0))
    locked = bool(el.get("locked", False))
    group = el.get("group")
    if group is not None:
        group = _str_max(str(group), 40, "group")

    style = el.get("style") or {}
    emphasis = "normal"
    if isinstance(style, dict):
        em = style.get("emphasis", "normal")
        if em not in ALLOWED_EMPHASIS:
            raise SchemaError(f"emphasis invalide: {em}", "style")
        emphasis = em

    out: dict[str, Any] = {
        "id": eid,
        "type": etype,
        "position": {"x": x, "y": y},
        "size": {"width": w, "height": h},
        "zIndex": z,
        "locked": locked,
        "style": {"emphasis": emphasis},
    }
    if group:
        out["group"] = group

    # Contenu par type
    if etype in ("title", "text", "rule", "result"):
        out["text"] = _str_max(el.get("text"), MAX_TEXT, "text")
    elif etype == "step":
        out["text"] = _str_max(el.get("text"), MAX_TEXT, "text")
        out["label"] = _str_max(el.get("label", "Étape"), MAX_LABEL, "label", required=False) or "Étape"
    elif etype in ("formula", "calculation"):
        out["latex"] = _str_max(el.get("latex") or el.get("text", ""), MAX_LATEX, "latex")
    elif etype == "table":
        headers = el.get("headers") or []
        rows = el.get("rows") or []
        if not isinstance(headers, list) or len(headers) > 8:
            raise SchemaError("table.headers invalide", "table")
        if not isinstance(rows, list) or len(rows) > 20:
            raise SchemaError("table.rows invalide", "table")
        out["headers"] = [_str_max(str(h), 100, "header") for h in headers]
        clean_rows = []
        for row in rows:
            if not isinstance(row, list):
                raise SchemaError("ligne de tableau invalide", "table")
            clean_rows.append([_str_max(str(c), 100, "cell") for c in row[:8]])
        out["rows"] = clean_rows
    elif etype == "chart":
        kind = el.get("kind", "line")
        if kind not in ALLOWED_CHART_KINDS:
            raise SchemaError("chart.kind invalide", "chart")
        series = el.get("series") or []
        if not isinstance(series, list) or len(series) > 5:
            raise SchemaError("chart.series invalide", "chart")
        clean_series = []
        for s in series:
            if not isinstance(s, dict):
                raise SchemaError("série invalide", "chart")
            pts = s.get("points") or []
            if not isinstance(pts, list) or len(pts) > 200:
                raise SchemaError("trop de points", "chart")
            clean_pts = []
            for p in pts:
                if not isinstance(p, (list, tuple)) or len(p) < 2:
                    continue
                try:
                    clean_pts.append([float(p[0]), float(p[1])])
                except (TypeError, ValueError):
                    raise SchemaError("point non numérique", "chart")
            clean_series.append({
                "label": _str_max(str(s.get("label", "")), 60, "series.label", required=False),
                "points": clean_pts,
            })
        axes = el.get("axes") or {}
        out["kind"] = kind
        out["series"] = clean_series
        out["axes"] = {
            "xLabel": _str_max(str(axes.get("xLabel", "x")), 40, "axes.x", required=False),
            "yLabel": _str_max(str(axes.get("yLabel", "y")), 40, "axes.y", required=False),
        }
    elif etype == "diagram":
        kind = el.get("kind", "geometry")
        if kind not in ALLOWED_DIAGRAM_KINDS:
            raise SchemaError("diagram.kind invalide", "diagram")
        prims = el.get("primitives") or []
        if not isinstance(prims, list) or len(prims) > 30:
            raise SchemaError("primitives invalides", "diagram")
        clean_p = []
        for pr in prims:
            if not isinstance(pr, dict):
                continue
            pk = pr.get("kind")
            if pk not in ALLOWED_PRIMITIVES:
                raise SchemaError(f"primitive interdite: {pk}", "diagram")
            # Coordonnées bornées uniquement, pas de SVG
            clean_p.append({
                "kind": pk,
                "data": {
                    k: v for k, v in (pr.get("data") or {}).items()
                    if isinstance(k, str) and len(k) < 30
                    and isinstance(v, (int, float, str, list))
                },
            })
        out["kind"] = kind
        out["primitives"] = clean_p

    return out


def _validate_connection(c: dict, ids: set[str], seen_c: set[str]) -> dict:
    if not isinstance(c, dict):
        raise SchemaError("connexion invalide", "type")
    cid = c.get("id")
    if not isinstance(cid, str) or not ID_RE.match(cid):
        raise SchemaError(f"connection.id invalide: {cid!r}", "id")
    if cid in seen_c:
        raise SchemaError(f"connection id dupliqué: {cid}", "duplicate")
    seen_c.add(cid)

    def _end(key: str) -> dict:
        end = c.get(key) or {}
        if not isinstance(end, dict):
            raise SchemaError(f"{key} invalide", "connection")
        eid = end.get("elementId")
        if eid not in ids:
            raise SchemaError(f"référence inconnue: {eid}", "ref")
        anchor = end.get("anchor", "bottom")
        if anchor not in ALLOWED_ANCHORS:
            raise SchemaError(f"anchor invalide: {anchor}", "connection")
        return {"elementId": eid, "anchor": anchor}

    frm = _end("from")
    to = _end("to")
    if frm["elementId"] == to["elementId"]:
        raise SchemaError("auto-référence interdite", "connection")
    label = _str_max(c.get("label", ""), 60, "connection.label", required=False)
    return {"id": cid, "from": frm, "to": to, "label": label}


def validate_document(raw: Any) -> dict:
    """
    Valide et normalise un document whiteboard.
    Lève SchemaError si invalide.
    """
    if isinstance(raw, str):
        if len(raw.encode("utf-8")) > MAX_JSON_BYTES:
            raise SchemaError("document trop volumineux", "size")
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as e:
            raise SchemaError(f"JSON invalide: {e}", "json") from e

    if not isinstance(raw, dict):
        raise SchemaError("document doit être un objet", "type")

    blob = json.dumps(raw, ensure_ascii=False)
    if len(blob.encode("utf-8")) > MAX_JSON_BYTES:
        raise SchemaError("document trop volumineux", "size")

    version = raw.get("version", SCHEMA_VERSION)
    if version != SCHEMA_VERSION:
        raise SchemaError(f"version non supportée: {version}", "version")

    title = _str_max(raw.get("title", "Correction"), MAX_TITLE, "title", required=False) or "Correction"
    elements_in = raw.get("elements") or []
    connections_in = raw.get("connections") or []
    if not isinstance(elements_in, list) or len(elements_in) > MAX_ELEMENTS:
        raise SchemaError("elements invalide ou trop nombreux", "elements")
    if not isinstance(connections_in, list) or len(connections_in) > MAX_CONNECTIONS:
        raise SchemaError("connections invalide ou trop nombreuses", "connections")

    seen: set[str] = set()
    elements = [_validate_element(el, seen) for el in elements_in]
    seen_c: set[str] = set()
    connections = [_validate_connection(c, seen, seen_c) for c in connections_in]

    # Vérifier groups
    for el in elements:
        g = el.get("group")
        if g and g not in seen:
            el.pop("group", None)

    return {
        "version": SCHEMA_VERSION,
        "title": title,
        "elements": elements,
        "connections": connections,
    }


def empty_document(title: str = "Correction") -> dict:
    return {
        "version": SCHEMA_VERSION,
        "title": (title or "Correction")[:MAX_TITLE],
        "elements": [],
        "connections": [],
    }
