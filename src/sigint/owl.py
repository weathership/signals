"""SIGDG → OWL/RDF-XML serialization via owlready2."""

from __future__ import annotations

from pathlib import Path

from sigint.ontology import CATEGORIES, SENSITIVITY_LEVELS

ONTOLOGY_IRI = "https://signals360.dev/ontology/dg/"


def serialize_owl(output_path: str | Path) -> Path:
    """Serialize the SIGDG ontology as OWL/RDF-XML.

    Categories are created as owl:Class with subClassOf relationships,
    rdfs:label (full name + abbreviation), and rdfs:comment (description).
    Sensitivity levels are modeled under BFO:Quality.

    Returns the output Path.
    """
    try:
        from owlready2 import Thing, default_world, get_ontology
    except ImportError:
        raise ImportError(
            "owlready2 package required for OWL serialization. "
            "Install with: pip install owlready2"
        )

    output_path = Path(output_path)

    # Clear cached ontologies to allow re-generation
    default_world.ontologies.clear()
    onto = get_ontology(ONTOLOGY_IRI)

    # Map category code → OWL class for parent lookups
    class_map: dict[str, type] = {}

    with onto:
        # ── BFO anchor classes ────────────────────────────────────────
        # Generically Dependent Continuant (BFO:0000031) — parent for info entities
        BFO_GDC = type("BFO_0000031", (Thing,), {})
        BFO_GDC.label = ["generically dependent continuant"]

        # Quality (BFO:0000019) — parent for sensitivity levels
        BFO_Quality = type("BFO_0000019", (Thing,), {})
        BFO_Quality.label = ["quality"]

        # ── SIGDG categories ──────────────────────────────────────────
        for cat in CATEGORIES:
            if cat.parent_code is None:
                # Root: subclass of BFO generically dependent continuant
                parent_cls = BFO_GDC
            else:
                parent_cls = class_map.get(cat.parent_code, BFO_GDC)

            cls_name = f"SIGDG_{cat.code}_{cat.label}"
            owl_cls = type(cls_name, (parent_cls,), {})

            labels = [cat.label]
            if cat.abbrev:
                labels.append(cat.abbrev)
            owl_cls.label = labels

            if cat.description:
                owl_cls.comment = [cat.description]

            class_map[cat.code] = owl_cls

        # ── Sensitivity levels ────────────────────────────────────────
        for sl in SENSITIVITY_LEVELS:
            cls_name = f"SIGDG_{sl.code}_{sl.label}"
            owl_cls = type(cls_name, (BFO_Quality,), {})
            owl_cls.label = [sl.label]
            if sl.description:
                owl_cls.comment = [sl.description]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    onto.save(file=str(output_path), format="rdfxml")
    return output_path
