"""SHACL Core aspect catalog — seed JSON to warehouse facts and proto shapes.

Aspects are NodeShapes, not products. ``signals.aspects.catalog`` is the
product that inventories them. See signals-protocol data_products.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_CATALOG = Path(__file__).resolve().parents[3] / "config/platform/data-products.json"


def _load(catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    if catalog is not None:
        return catalog
    return json.loads(_CATALOG.read_text(encoding="utf-8"))

WAREHOUSE_SPEC = "signals.spec.warehouse_product"
CATALOG_PRODUCT_ID = "signals.aspects.catalog"
DP_NS = "https://signals.zndx.org/ns/dp#"

_NODE_KIND = {
    "IRI": 1,
    "BLANK_NODE": 2,
    "LITERAL": 3,
    "BLANK_NODE_OR_IRI": 4,
    "BLANK_NODE_OR_LITERAL": 5,
    "IRI_OR_LITERAL": 6,
}


def aspects(catalog: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return list(_load(catalog).get("aspects") or [])


def product_specs(catalog: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return list(_load(catalog).get("product_specs") or [])


def aspect_ids(catalog: dict[str, Any] | None = None) -> set[str]:
    return {str(a.get("id") or "") for a in aspects(catalog) if a.get("id")}


def spec_requires(spec_id: str, catalog: dict[str, Any] | None = None) -> list[str]:
    for spec in product_specs(catalog):
        if spec.get("id") == spec_id:
            return [str(x) for x in (spec.get("requires") or [])]
    return []


def expand_product(
    product: dict[str, Any],
    *,
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Scalar details facts: spec + aspect.<id>=declared for the spec's requires."""
    out = dict(product)
    spec = str(out.get("spec_id") or out.get("spec") or WAREHOUSE_SPEC)
    out["spec"] = spec
    out["spec_id"] = spec
    for aspect_id in spec_requires(spec, catalog):
        key = f"aspect.{aspect_id}"
        if key not in out:
            out[key] = "declared"
    return out


def catalog_definition_facts(
    catalog: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Extra details.a keys on signals.aspects.catalog."""
    facts: dict[str, str] = {}
    for row in aspects(catalog):
        aid = str(row.get("id") or "")
        if not aid:
            continue
        if row.get("title"):
            facts[f"def.{aid}.title"] = str(row["title"])
        if row.get("intent"):
            facts[f"def.{aid}.intent"] = str(row["intent"])
    for spec in product_specs(catalog):
        sid = str(spec.get("id") or "")
        if not sid:
            continue
        for aspect_id in spec.get("requires") or []:
            facts[f"spec.{sid}.requires.{aspect_id}"] = "true"
    return facts


def _property_shape(raw: dict[str, Any], pb: Any) -> Any:
    ps = pb.PropertyShape()
    path = str(raw.get("path") or "")
    if path and not path.startswith("http") and ":" not in path:
        path = DP_NS + path
    ps.path.predicate = path
    if "min_count" in raw:
        ps.min_count = int(raw["min_count"])
    if "max_count" in raw:
        ps.max_count = int(raw["max_count"])
    if raw.get("datatype"):
        ps.datatype = str(raw["datatype"])
    if raw.get("class"):
        setattr(ps, "class", str(raw["class"]))
    if raw.get("node_kind"):
        ps.node_kind = _NODE_KIND.get(str(raw["node_kind"]).upper(), 0)
    if raw.get("pattern"):
        ps.pattern = str(raw["pattern"])
    if raw.get("has_value") is not None:
        ps.has_value = str(raw["has_value"])
    if raw.get("node"):
        ps.node = str(raw["node"])
    for item in raw.get("in") or []:
        getattr(ps, "in").append(str(item))
    if raw.get("message"):
        ps.message = str(raw["message"])
    return ps


def aspect_spec_proto(row: dict[str, Any], pb: Any) -> Any:
    spec = pb.AspectSpec()
    spec.title = str(row.get("title") or "")
    spec.intent = str(row.get("intent") or "")
    spec.shape.id = str(row.get("id") or "")
    for prop in row.get("properties") or []:
        spec.shape.property.append(_property_shape(prop, pb))
    for other in row.get("or") or []:
        getattr(spec.shape, "or").append(str(other))
    for other in row.get("and") or []:
        getattr(spec.shape, "and").append(str(other))
    return spec


def product_spec_proto(row: dict[str, Any], pb: Any) -> Any:
    spec = pb.ProductSpec()
    spec.title = str(row.get("title") or "")
    spec.shape.id = str(row.get("id") or "")
    for aspect_id in row.get("requires") or []:
        getattr(spec.shape, "and").append(str(aspect_id))
    return spec


def shapes_graph(pb: Any, catalog: dict[str, Any] | None = None) -> tuple[list, list]:
    """AspectSpec[] and ProductSpec[] for ServerQuery kind=ASPECTS."""
    return (
        [aspect_spec_proto(a, pb) for a in aspects(catalog) if a.get("id")],
        [product_spec_proto(s, pb) for s in product_specs(catalog) if s.get("id")],
    )
