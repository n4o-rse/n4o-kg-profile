#!/usr/bin/env python3
"""
build_sparql.py — turns queries.yaml into a browsable query page.

    queries.yaml  →  docs/sparql.html            (the published page)
                  →  docs/downloads/queries/*.rq (written by make_metadata.py)
                  →  docs/<graph>.ttl            (copied, engine: pyodide only)

Two engines, one source:

  pyodide   The graph is a static Turtle file, fetched by the browser and
            parsed client-side by rdflib under Pyodide. No endpoint, no server:
            an archived copy of this repository, unpacked years from now, stays
            queryable with nothing to keep alive. Suitable up to roughly
            MAX_LOCAL_MB; beyond that the page becomes painful on a phone.

  endpoint  The queries run against the N4O KG SPARQL endpoint, scoped with
            FROM <collection URI>. Right for large graphs, but the page is only
            as durable as the service behind it.

The engine is chosen in queries.yaml (`graph.engine`). If it is absent, the
size of the local graph decides, and the decision is printed.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent.parent
QUERIES_YAML = ROOT / "queries.yaml"
TEMPLATES = Path(__file__).resolve().parent / "templates"
DOCS = ROOT / "docs"

# Pinned deliberately: an unpinned CDN path follows whatever ships next, and an
# rdflib that no longer parses this Turtle breaks the page silently, years after
# anyone is watching. Bump on purpose, not by omission.
PYODIDE_VERSION = "0.26.4"
RDFLIB_VERSION = "7.1.1"

MAX_ROWS = 500
MAX_LOCAL_MB = 5.0  # above this, `pyodide` is a bad idea; see module docstring


def choose_engine(cfg: dict, graph_path: Path | None) -> str:
    engine = (cfg.get("graph") or {}).get("engine")
    if engine:
        return engine
    if graph_path and graph_path.is_file():
        mb = graph_path.stat().st_size / 1_048_576
        if mb > MAX_LOCAL_MB:
            print(f"  graph is {mb:.1f} MB (> {MAX_LOCAL_MB} MB) → engine: endpoint")
            return "endpoint"
    return "pyodide"


def main() -> None:
    if not QUERIES_YAML.is_file():
        print("no queries.yaml — nothing to build")
        return

    cfg = yaml.safe_load(QUERIES_YAML.read_text(encoding="utf-8"))
    graph_cfg = cfg.get("graph") or {}
    page = cfg.get("page") or {}
    queries = cfg.get("queries") or []
    prefixes = cfg.get("prefixes", "")

    graph_path = ROOT / graph_cfg["file"] if graph_cfg.get("file") else None
    engine = choose_engine(cfg, graph_path)
    print(f"  engine: {engine}, {len(queries)} queries")

    DOCS.mkdir(parents=True, exist_ok=True)

    graph_url = graph_cfg.get("url") or (graph_path.name if graph_path else "")
    megabytes = None
    if engine == "pyodide":
        if not (graph_path and graph_path.is_file()):
            raise SystemExit("engine 'pyodide' needs graph.file to exist")
        if graph_cfg.get("publish", True):
            shutil.copyfile(graph_path, DOCS / graph_url)
        megabytes = f"{graph_path.stat().st_size / 1_048_576:.1f}"

    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    html = env.get_template("sparql.html.j2").render(
        page=page,
        engine=engine,
        queries=queries,
        prefixes=prefixes,
        prefixes_json=json.dumps(prefixes),
        queries_json=json.dumps({q["id"]: q["sparql"].rstrip() for q in queries}),
        graph_json=json.dumps(
            {
                "file": graph_cfg.get("file"),
                "url": graph_url,
                "megabytes": megabytes,
                "endpoint": graph_cfg.get("endpoint"),
                "from": graph_cfg.get("from"),
            }
        ),
        pyodide_version=PYODIDE_VERSION,
        rdflib_version=RDFLIB_VERSION,
        max_rows=MAX_ROWS,
    )
    (DOCS / "sparql.html").write_text(html, encoding="utf-8")
    print("  → docs/sparql.html")

    collection = cfg.get("collection")
    if collection:
        (DOCS / "index.html").write_text(
            env.get_template("index.html.j2").render(c=collection), encoding="utf-8"
        )
        print("  → docs/index.html")

    # The generated RDF belongs next to the page it describes.
    for name in ("metadata.ttl", "metadata.jsonld", "n4o-collection.ttl",
                 "crm-alignment.ttl"):
        src = ROOT / "dist" / name
        if src.is_file():
            shutil.copyfile(src, DOCS / name)

    style = TEMPLATES / "style.css"
    if style.is_file():
        shutil.copyfile(style, DOCS / "style.css")
        print("  → docs/style.css")


if __name__ == "__main__":
    main()
