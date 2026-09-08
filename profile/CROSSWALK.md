# YAML-LD → N4O KG / NCMDP crosswalk (draft v0.1)

One hand-maintained `metadata.yaml`; everything else is generated. Intended as
the template for **every** collection loaded into or updated in the NFDI4Objects
Knowledge Graph.

---

## 1. Why there is no transformation script

A YAML-LD document **is** JSON-LD; YAML → JSON-LD → RDF is specified and
lossless. The crosswalk therefore lives entirely in the `@context`: one YAML key
maps to one IRI. What a context cannot do — counting, and rendering into
non-RDF formats — the generator does.

| Layer | Artefact | Job |
|---|---|---|
| declarative | `profile/context.jsonld` | one key → one IRI |
| computed | `build/make_metadata.py` | VoID statistics from the bundle, CRM alignment, `queries.yaml` |
| projected | `dist/n4o-collection.ttl` | the subset the N4O KG reads |
| checked | `profile/shapes.ttl` | obligation levels as SHACL |

DataCite is deliberately **not** in the context: it is an XML/JSON schema, not
an ontology. Should a DataCite record be needed, it is a renderer like
`n4o-collection.ttl`, never a mapping.

---

## 2. Generated files

```
metadata.yaml
  ├── dist/metadata.ttl        everything: DCAT + VoID + CRM alignment
  ├── dist/metadata.jsonld     the same statement as JSON-LD
  ├── dist/n4o-collection.ttl  registration record for the N4O KG
  ├── dist/crm-alignment.ttl   rdfs:subClassOf / subPropertyOf, loadable alone
  ├── queries.yaml             input for build_sparql.py
  └── docs/                    index.html, sparql.html, the RDF, *.rq
```

---

## 3. What the N4O KG needs

Four facts, modelled the way `graph.nfdi4objects.net/collection/9` models itself:

| YAML | RDF | Note |
|---|---|---|
| `title` | `schema:name` (plus `dct:title` in `metadata.ttl`) | the KG reads `schema:name` |
| `homepage` | `foaf:homepage` | publication URL, e.g. a Zenodo DOI |
| `sameAs` | `schema:sameAs` | Wikidata item |
| `license` | `dct:license` | as an **IRI** |

Plus `notation` (`skos:notation`), `isPartOf`, and the type
`fabio:Database, dcat:Dataset` — exactly the shape the KG serves today.

> Observed: the KG serialises `dcterms:license` as a string literal.
> `n4o-collection.ttl` writes an IRI, because that is the correct statement.
> If the importer insists on the literal, it is one line in
> `n4o_collection_graph()`.

---

## 4. Element table

| YAML key | RDF | DCAT-AP | schema.org | Level |
|---|---|---|---|---|
| `id` | `@id` | dataset URI | `@id` | **M** |
| `type` | `fabio:Database`, `dcat:Dataset` | `dcat:Dataset` | `schema:Dataset` | **M** |
| `title` | `dct:title` (language map) | `dct:title` | `schema:name` | **M** |
| `homepage` | `foaf:homepage` | — | `schema:url` | **M**¹ |
| `sameAs` | `schema:sameAs` | — | `schema:sameAs` | **M**¹ |
| `license` | `dct:license` | `dct:license` | `schema:license` | **M** |
| `notation` | `skos:notation` | — | — | **R** |
| `isPartOf` | `dct:isPartOf` | `dct:isPartOf` | `schema:isPartOf` | **R** |
| `description` | `dct:description` (language map) | `dct:description` | `schema:description` | **R** |
| `creators[]` | `dct:creator` → `foaf:Person` / `foaf:Organization` | `dct:creator` | `schema:creator` | **M** |
| `…orcid` | `n4o:orcidId` | — | `schema:identifier` | **R** |
| `publisher` | `dct:publisher` | `dct:publisher` | `schema:publisher` | **M** |
| `issued` | `dct:issued` (`xsd:date`) | `dct:issued` | `schema:datePublished` | **M** |
| `modified` | `dct:modified` | `dct:modified` | `schema:dateModified` | **R** |
| `version` | `dcat:version` | `dcat:version` | `schema:version` | **R** |
| `resourceType` | `dct:type` | `dct:type` | `schema:additionalType` | **M** |
| `accessRights` | `dct:accessRights` | `dct:accessRights` | `schema:conditionsOfAccess` | **R** |
| `landingPage` | `dcat:landingPage` | `dcat:landingPage` | `schema:url` | **R** |
| `keywords[]` | `dcat:keyword` | `dcat:keyword` | `schema:keywords` | **R** |
| `language[]` | `dct:language` | `dct:language` | `schema:inLanguage` | **R** |
| `conformsTo[]` | `dct:conformsTo` | `dct:conformsTo` | — | **R** |
| `distributions[]` | `dcat:distribution` | `dcat:Distribution` | `schema:distribution` | **M** |
| `…role` | `dct:type` → `n4op:roleBundle` \| `roleData` \| `roleOntology` | `dct:type` | — | **M** |
| `…downloadURL` | `dcat:downloadURL` | `dcat:downloadURL` | `schema:contentUrl` | **M** |
| `…file` | — (existence check only) | — | — | **O** |
| `…source` | — (fetched once at build time) | — | — | **O** |
| — | `spdx:checksum` on the downloadURL | — | — | computed |
| — | `void:classPartition` + `void:entities` + `n4op:crmAnchor` | — | — | measured |
| — | `void:propertyPartition` + `void:triples` | — | — | measured |
| `model.classes[]` | `rdfs:subClassOf crm:…` — supplement only | — | — | **O** |
| `model.properties[]` | `rdfs:subPropertyOf crm:…` — supplement only | — | — | **O** |
| `model.external[]` | — (namespaces exempt from the anchoring report) | — | — | **O** |
| `queries[]` | `n4op:exampleQuery` → `sh:SPARQLSelectExecutable` | — | — | **R** |
| `…sparql` | `sh:select` (with prefixes injected) | — | — | **M**² |
| `prefixes` | — (injected into every query) | — | — | — |

¹ required by the N4O KG, not by the NCMDP · ² within a query

---

## 5. Modelling decisions

- **Counted, not typed in — including the alignment.** Class and property counts
  come from `model.bundle`, and so does the CIDOC CRM anchoring: the build
  follows `rdfs:subClassOf` transitively and records what each class reaches as
  `n4op:crmAnchor` on its `void:classPartition`. Transitively, because that is
  how a query reaches it — a class anchored through an intermediate superclass
  is anchored, and reporting it as a gap sends somebody hunting for a problem
  that is not there.

- **The bundle wins over the YAML.** `model.classes` is a *supplement*, for a
  class the bundle does not anchor itself. Where both speak, they are compared:
  a disagreement is printed in full and, under `strict`, fails the build. It is
  never merged, because one of the two is wrong and only a person knows which —
  guessing publishes the wrong one under a checksum. The alignment belongs
  upstream, in the ontology; this profile measures it.

- **Namespaces a collection reuses but does not own** — PROV-O, FOAF, GeoSPARQL
  and whatever `model.external` adds — are counted separately and never reported
  as gaps. Anchoring them to CIDOC CRM would be asserting something about
  somebody else's ontology.

- **`dist/crm-alignment.ttl` is written only when there is a supplement.** A
  bundle that anchors itself needs no companion file, and an empty one left over
  from an earlier run would be shipped and cited.

- **Example queries are SHACL executables.** `sh:SPARQLSelectExecutable` with
  `sh:select` is the only standard way to carry a SPARQL query in RDF. Prefixes
  are injected on write, so every query runs on its own — in the `.rq` file and
  in the graph alike.

- **Every query runs before it ships.** Zero rows is a defect, not a boring
  question: SPARQL does not fail on a mistyped IRI, it returns nothing. The
  check runs against the bundle **plus** the alignment, because that is the
  state the KG is in after import.

- **Five minted terms, no more** (`profile/profile.ttl`): `n4op:exampleQuery`,
  `n4op:crmAnchor` and the three distribution roles.

- **Blank nodes are canonicalised (URDNA2015)** and prefixes bound explicitly.
  A diff after an unchanged rebuild means something is wrong.

---

## 6. Open points

1. Fold in the binding mandatory/recommended list of the NCMDP
   (report of the 2nd NFDI Metadata Workshop, DOI `10.5281/zenodo.19709639`).
2. Reconcile with **OCMDP** and **MaCHeCO** of the NFDI4Objects TWG — the
   crosswalk responsibility sits there; this profile should reference it rather
   than duplicate it.
3. Confirm whether the importer accepts `dct:license` as an IRI (section 3).
4. Register the `n4op:` namespace under `w3id.org` and version it.
5. Decide whether `crm-alignment.ttl` is loaded into the KG or only published.
