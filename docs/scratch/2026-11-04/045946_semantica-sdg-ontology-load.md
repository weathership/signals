# SDG ontology loaded into Semantica

Loaded `components/sdg-corpora` from `/home/rch/local/src/oss/semantica` into the
Explorer that `devenv up -d` started on `:8070`. The catalog OWL
(`ontology/sdg-ontology.owl`) was left out. A second load of the same IRI
replaces the nodes it shares.

Order:

1. `POST /api/ontology/load` — `ontology/sdg-ontology-comprehensive.owl` (xml)
2. `POST /api/ontology/load` — `ontology/sdg-vocab.ttl` (turtle), name `SDG property vocabulary`
3. `POST /api/vocabulary/import` — `vocabulary/domain-concepts.ttl`
4. `POST /api/vocabulary/import` — `vocabulary/vocabulary.ttl`
5. `POST /api/vocabulary/import` — `vocabulary/semantica-feature-overlay.ttl`

The graph was empty before the load. After it: 17,962 nodes and 16,712 edges.
That is 4,747 `owl:Class`, 4,118 object properties, 6,707 datatype properties,
2,392 `skos:Concept`, one concept scheme, and 13 `entity` nodes. Ontology IRI
`https://signals.zndx.org/sdg`. Scheme `https://signals.zndx.org/sdg/scheme`
(2,392 concepts). Search for `Laboratory` returns `LIMS`.
