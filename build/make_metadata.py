#!/usr/bin/env python3
"""
make_metadata.py — derives everything else from metadata.yaml (YAML-LD).

    metadata.yaml
        │
        ├─ dist/metadata.ttl        the full statement: DCAT + VoID + CRM alignment
        ├─ dist/metadata.jsonld     the same statement as JSON-LD
        ├─ dist/n4o-collection.ttl  only what the N4O KG reads to register a collection
        ├─ dist/crm-alignment.ttl   the CIDOC CRM alignment, loadable on its own
        ├─ queries.yaml             input for build_sparql.py (docs/sparql.html)
        └─ docs/downloads/queries/*.rq

Counted, not typed in: class and property counts come from the bundle
(model.bundle), never from the YAML. Classes without a CRM alignment are
reported rather than guessed.

Adjust the constants below; there are no command-line arguments.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.request
import warnings
from pathlib import Path

import yaml
from rdflib import Graph, Literal, Namespace, URIRef, BNode
from rdflib.namespace import RDF, RDFS, XSD
from rdflib.compare import to_canonical_graph

# --------------------------------------------------------------------------- #
# Configuration                                                                #
# --------------------------------------------------------------------------- #

ROOT = Path(__file__).resolve().parent.parent
SOURCE_YAML = ROOT / os.environ.get("N4O_METADATA", "metadata.yaml")
CONTEXT_FILE = ROOT / "profile" / "context.jsonld"
SHAPES_FILE = ROOT / "profile" / "shapes.ttl"
DIST = ROOT / "dist"
QUERIES_YAML = ROOT / "queries.yaml"
RQ_DIR = ROOT / "docs" / "downloads" / "queries"

CONTEXT_URI = "https://w3id.org/nfdi4objects/profile/v0.1/context.jsonld"

WRITE_JSONLD = True
WRITE_TURTLE = True
WRITE_N4O_COLLECTION = True
WRITE_QUERIES = True
COUNT_FROM_BUNDLE = True
FETCH_SOURCES = True      # fetch a distribution's `source:` when `file` is absent
REFRESH_SOURCES = False   # True: always refetch, even if the copy is present
RUN_SHACL = True
STRICT = False

# Switchable from the GitHub Action without editing this file; locally the
# constants above still govern (a VS Code "Run" needs no arguments).
STRICT = os.environ.get("N4O_STRICT", "1" if STRICT else "0") == "1"
REFRESH_SOURCES = os.environ.get("N4O_REFRESH", "0") == "1"

DCAT = Namespace("http://www.w3.org/ns/dcat#")
DCT = Namespace("http://purl.org/dc/terms/")
VOID = Namespace("http://rdfs.org/ns/void#")
SCHEMA = Namespace("https://schema.org/")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
FOAF = Namespace("http://xmlns.com/foaf/0.1/")
FABIO = Namespace("http://purl.org/spar/fabio/")
SH = Namespace("http://www.w3.org/ns/shacl#")
N4OP = Namespace("https://w3id.org/nfdi4objects/profile/v0.1/")
SPDX = Namespace("http://spdx.org/rdf/terms#")

NAMESPACES = {
    "dcat": DCAT, "dct": DCT, "void": VOID, "schema": SCHEMA, "skos": SKOS,
    "foaf": FOAF, "fabio": FABIO, "sh": SH, "n4op": N4OP, "spdx": SPDX,
    "rdfs": RDFS, "xsd": XSD,
    "dcmitype": Namespace("http://purl.org/dc/dcmitype/"),
    "crm": Namespace("http://www.cidoc-crm.org/cidoc-crm/"),
    "n4o": Namespace("https://nfdi4objects.net/ontology#"),
}

PREFER_LANG = ("en", "de")

# Filled by add_model_statistics, read by write_queries for the landing page.
STATS: dict[str, int] = {}


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def load_yaml_ld(path: Path) -> dict:
    """YAML-LD Basic Profile: the parse result already is a JSON-LD document.
    The %YAML 1.2 directive is correct, but PyYAML implements 1.1 — so drop it."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        text = path.read_text(encoding="utf-8")
        if text.lstrip().startswith("%YAML"):
            text = "\n".join(text.splitlines()[1:])
        return yaml.safe_load(text)


def pick(value, prefer=PREFER_LANG):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for lang in prefer:
            if lang in value:
                return " ".join(str(value[lang]).split())
        if value:
            return " ".join(str(next(iter(value.values()))).split())
    return None


def with_prefixes(sparql: str, prefixes: str) -> str:
    """Maintain the prefix block once, but inject it into every query that ships —
    otherwise neither the .rq file nor the sh:select runs on its own."""
    return f"{(prefixes or '').strip()}\n\n{sparql.strip()}\n".lstrip()


# --------------------------------------------------------------------------- #
# RDF                                                                          #
# --------------------------------------------------------------------------- #


def ensure_local_copy(dist: dict, root: Path) -> Path | None:
    """The bundle is built in the source repository, not here. `source:` fetches it
    exactly once; the copy stays, so that the build is reproducible offline and
    the collection repository holds a citable archive of the version that was
    actually loaded."""
    rel = dist.get("file")
    if not rel:
        return None
    target = root / rel
    if target.is_file() and not REFRESH_SOURCES:
        return target
    source = dist.get("source")
    if not source:
        print(f"  ! declared file missing and no source: {rel}")
        return None
    if not FETCH_SOURCES:
        print(f"  ! {rel} missing; FETCH_SOURCES is off")
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"  fetching {source}")
    with urllib.request.urlopen(source) as resp:
        target.write_bytes(resp.read())
    print(f"  → {rel} ({target.stat().st_size} bytes)")
    return target


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def add_checksums(g: Graph, doc: dict, root: Path) -> None:
    """One checksum per distribution. It is the only statement that later proves
    which version was actually loaded into the graph."""
    for dist in doc.get("distributions", []):
        rel, url = dist.get("file"), dist.get("downloadURL")
        if not (rel and url):
            continue
        path = root / rel
        if not path.is_file():
            continue
        node = BNode()
        g.add((URIRef(url), SPDX.checksum, node))
        g.add((node, SPDX.algorithm, SPDX.checksumAlgorithm_sha256))
        g.add((node, SPDX.checksumValue, Literal(sha256(path))))


def to_rdf(doc: dict, context_file: Path) -> Graph:
    local = dict(doc)
    local["@context"] = json.loads(context_file.read_text(encoding="utf-8"))["@context"]
    g = Graph()
    g.parse(data=json.dumps(local), format="json-ld")
    return g


META_NAMESPACES = (
    "http://www.w3.org/2002/07/owl#",
    "http://www.w3.org/2000/01/rdf-schema#",
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "http://www.w3.org/2004/02/skos/core#",
)


def add_model_statistics(g: Graph, subject: URIRef, model: dict, root: Path) -> Graph:
    """Count void:classPartition / void:propertyPartition from the bundle and add
    the CRM alignment as rdfs:subClassOf / rdfs:subPropertyOf."""
    alignment = Graph()
    if not model:
        return alignment
    bundle_path = root / model.get("bundle", "")
    if not bundle_path.is_file():
        print(f"  ! bundle not found: {model.get('bundle')} — no statistics")
        return alignment

    data = Graph()
    data.parse(bundle_path, format="turtle")
    g.add((subject, VOID.triples, Literal(len(data), datatype=XSD.integer)))
    STATS["triples"] = len(data)
    print(f"  bundle: {bundle_path.name} — {len(data)} triples")

    class_counts: dict[URIRef, int] = {}
    for _, _, o in data.triples((None, RDF.type, None)):
        if isinstance(o, URIRef):
            class_counts[o] = class_counts.get(o, 0) + 1

    prop_counts: dict[URIRef, int] = {}
    for _, p, _ in data:
        prop_counts[p] = prop_counts.get(p, 0) + 1

    crm_class = {URIRef(e["class"]): URIRef(e["crm"])
                 for e in model.get("classes", []) if e.get("crm")}
    crm_prop = {URIRef(e["property"]): URIRef(e["crm"])
                for e in model.get("properties", []) if e.get("crm")}

    for cls, count in sorted(class_counts.items(), key=lambda kv: (-kv[1], str(kv[0]))):
        part = BNode()
        g.add((subject, VOID.classPartition, part))
        g.add((part, VOID["class"], cls))
        g.add((part, VOID.entities, Literal(count, datatype=XSD.integer)))
        if cls in crm_class:
            alignment.add((cls, RDFS.subClassOf, crm_class[cls]))

    for prop, count in sorted(prop_counts.items(), key=lambda kv: (-kv[1], str(kv[0]))):
        part = BNode()
        g.add((subject, VOID.propertyPartition, part))
        g.add((part, VOID.property, prop))
        g.add((part, VOID.triples, Literal(count, datatype=XSD.integer)))
        if prop in crm_prop:
            alignment.add((prop, RDFS.subPropertyOf, crm_prop[prop]))

    # Do not guess: report missing alignments rather than inventing them.
    # owl:/rdfs:/rdf:/skos: are the ontology's own meta level and are exempt.
    missing = [c for c in class_counts
               if c not in crm_class and not str(c).startswith(META_NAMESPACES)]
    if missing:
        print(f"  ! {len(missing)} class(es) with no CRM alignment:")
        for c in sorted(missing, key=str)[:10]:
            print(f"      {c}")
    STATS["classes"] = len(class_counts)
    STATS["properties"] = len(prop_counts)
    STATS["aligned"] = len([c for c in class_counts if c in crm_class])
    stale = [c for c in crm_class if c not in class_counts]
    if stale:
        print(f"  ! {len(stale)} CRM alignment(s) with no occurrence in the bundle:")
        for c in sorted(stale, key=str):
            print(f"      {c}")
    g += alignment
    return alignment


def finalise(g: Graph) -> Graph:
    """Canonicalise and bind prefixes explicitly — otherwise the file is 'modified'
    after every run and its diff is worthless."""
    canon = to_canonical_graph(g)
    out = Graph()
    for triple in canon:
        out.add(triple)
    for prefix, ns in NAMESPACES.items():
        out.bind(prefix, ns, override=True, replace=True)
    return out


def n4o_collection_graph(doc: dict) -> Graph:
    """The subset the N4O KG reads to register a collection: title, publication
    URL, Wikidata ID, licence — plus where it sits."""
    g = Graph()
    s = URIRef(doc["id"])
    g.add((s, RDF.type, FABIO.Database))
    g.add((s, RDF.type, DCAT.Dataset))
    for lang, value in (doc.get("title") or {}).items():
        g.add((s, SCHEMA.name, Literal(value, lang=lang)))
    if doc.get("homepage"):
        g.add((s, FOAF.homepage, URIRef(doc["homepage"])))
    if doc.get("sameAs"):
        g.add((s, SCHEMA.sameAs, URIRef(doc["sameAs"])))
    if doc.get("license"):
        g.add((s, DCT.license, URIRef(doc["license"])))
    if doc.get("notation"):
        g.add((s, SKOS.notation, Literal(str(doc["notation"]))))
    if doc.get("isPartOf"):
        g.add((s, DCT.isPartOf, URIRef(doc["isPartOf"])))
    if doc.get("issued"):
        g.add((s, DCT.issued, Literal(doc["issued"], datatype=XSD.date)))
    for dist in doc.get("distributions", []):
        if dist.get("downloadURL"):
            g.add((s, DCAT.downloadURL, URIRef(dist["downloadURL"])))
    return finalise(g)


# --------------------------------------------------------------------------- #
# Queries                                                                      #
# --------------------------------------------------------------------------- #


def write_queries(doc: dict) -> None:
    """Write queries.yaml in the format build_sparql.py expects, plus the .rq files.
    Monolingual, because the query page is monolingual."""
    queries = doc.get("queries") or []
    if not queries:
        return
    prefixes = doc.get("prefixes", "")

    bundle = (doc.get("model") or {}).get("bundle")
    out = {
        "graph": {
            "file": bundle,
            "url": Path(bundle or "graph.ttl").name,
            "publish": True,
            # Left unset on purpose: build_sparql.py picks the engine from the
            # graph size unless a collection overrides it here.
            "engine": (doc.get("sparql") or {}).get("engine"),
            "endpoint": (doc.get("sparql") or {}).get(
                "endpoint", "https://graph.nfdi4objects.net/api/sparql"),
            "from": doc.get("id"),
        },
        "page": {
            "title": pick(doc.get("title")),
            "intro": pick(doc.get("description")),
        },
        # Everything the landing page shows, so index.html needs no second
        # reader for metadata.yaml.
        "collection": {
            "id": doc.get("id"),
            "title": pick(doc.get("title")),
            "description": pick(doc.get("description")),
            "homepage": doc.get("homepage"),
            "wikidata": doc.get("sameAs"),
            "licence": doc.get("license"),
            "version": doc.get("version"),
            "issued": str(doc.get("issued", "")),
            "landing_page": doc.get("landingPage"),
            "creators": [c.get("name") for c in doc.get("creators", [])],
            "distributions": [
                {"title": pick(d.get("title")), "url": d.get("downloadURL")}
                for d in doc.get("distributions", [])
            ],
            "triples": STATS.get("triples"),
            "classes": STATS.get("classes"),
            "properties": STATS.get("properties"),
            "aligned": STATS.get("aligned"),
        },
        "prefixes": prefixes,
        "queries": [
            {
                "id": q["id"],
                "title": pick(q.get("title")),
                "intro": pick(q.get("intro")),
                "sparql": q["sparql"].strip() + "\n",
            }
            for q in queries
        ],
    }
    QUERIES_YAML.write_text(
        yaml.safe_dump(out, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )
    print(f"  → {QUERIES_YAML.name} ({len(queries)} queries)")

    RQ_DIR.mkdir(parents=True, exist_ok=True)
    for q in queries:
        (RQ_DIR / f"{q['id']}.rq").write_text(
            with_prefixes(q["sparql"], prefixes), encoding="utf-8"
        )
    print(f"  → docs/downloads/queries/*.rq")


def verify_queries(doc: dict, root: Path, alignment: Graph) -> bool:
    """Run every example query against the bundle. Zero rows counts as a defect:
    SPARQL does not fail on a mistyped IRI, it returns nothing."""
    queries = doc.get("queries") or []
    bundle = root / (doc.get("model") or {}).get("bundle", "")
    if not queries or not bundle.is_file():
        return True
    data = Graph()
    data.parse(bundle, format="turtle")
    # The CRM alignment is not in the bundle, but it is in the KG after import —
    # so the verification has to run against it too.
    data += alignment
    ok = True
    for q in queries:
        try:
            rows = len(list(data.query(with_prefixes(q["sparql"], doc.get("prefixes", "")))))
        except Exception as exc:  # noqa: BLE001
            print(f"  ! query {q['id']} is malformed: {exc}")
            ok = False
            continue
        mark = "" if rows else "  ← no rows!"
        print(f"    {q['id']}: {rows} rows{mark}")
        ok = ok and rows > 0
    return ok


# --------------------------------------------------------------------------- #
# Main                                                                         #
# --------------------------------------------------------------------------- #


def main() -> None:
    DIST.mkdir(parents=True, exist_ok=True)
    doc = load_yaml_ld(SOURCE_YAML)
    print(f"read: {SOURCE_YAML.name}")

    for dist in doc.get("distributions", []):
        ensure_local_copy(dist, ROOT)

    rdf_doc = json.loads(json.dumps(doc))
    for q in rdf_doc.get("queries", []):
        q["sparql"] = with_prefixes(q["sparql"], rdf_doc.get("prefixes", ""))
        q.setdefault("type", ["Query"])

    graph = to_rdf(rdf_doc, CONTEXT_FILE)
    alignment = Graph()
    if COUNT_FROM_BUNDLE:
        alignment = add_model_statistics(graph, URIRef(doc["id"]), doc.get("model"), ROOT)
    add_checksums(graph, doc, ROOT)
    graph = finalise(graph)
    print(f"  RDF: {len(graph)} triples")

    if WRITE_TURTLE:
        (DIST / "metadata.ttl").write_bytes(graph.serialize(format="turtle", encoding="utf-8"))
        print("  → dist/metadata.ttl")

    if WRITE_JSONLD:
        published = dict(doc)
        published["@context"] = CONTEXT_URI
        (DIST / "metadata.jsonld").write_text(
            json.dumps(published, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print("  → dist/metadata.jsonld")

    if WRITE_N4O_COLLECTION:
        (DIST / "n4o-collection.ttl").write_bytes(
            n4o_collection_graph(doc).serialize(format="turtle", encoding="utf-8")
        )
        print("  → dist/n4o-collection.ttl")

    if len(alignment):
        (DIST / "crm-alignment.ttl").write_bytes(
            finalise(alignment).serialize(format="turtle", encoding="utf-8")
        )
        print(f"  → dist/crm-alignment.ttl ({len(alignment)} alignments)")

    if WRITE_QUERIES:
        write_queries(doc)
        queries_ok = verify_queries(doc, ROOT, alignment)
    else:
        queries_ok = True

    conforms = True
    if RUN_SHACL and SHAPES_FILE.exists():
        from pyshacl import validate

        conforms, _, text = validate(
            graph, shacl_graph=Graph().parse(SHAPES_FILE, format="turtle"), advanced=True
        )
        print(f"  SHACL: {'PASS' if conforms else 'FAIL'}")
        if not conforms:
            print(text)

    if STRICT and not (conforms and queries_ok):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
