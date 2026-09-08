#!/usr/bin/env python3
"""
build_sparql.py — turns queries.yaml into a browsable query layer.

    queries.yaml
        ├─ docs/query/index.html      the catalogue
        ├─ docs/query/<id>.html       one page per query
        ├─ docs/query/all.html        all of them on one page
        ├─ docs/query/rq/<id>.rq      the same queries as plain files
        ├─ docs/query/runner.js       the shared browser code
        ├─ docs/map.html              every located thing in the graph
        ├─ docs/index.html            the collection landing page
        └─ docs/<graph>.ttl           the graph itself (engine: pyodide)

Two engines, one source:

  pyodide   The graph is a static Turtle file, fetched by the browser and
            parsed client-side by rdflib under Pyodide. No endpoint, no
            server: an archived copy of this repository, unpacked years from
            now, stays queryable with nothing to keep alive. Suitable up to
            about MAX_LOCAL_MB.

  endpoint  The queries run against the N4O KG SPARQL endpoint, scoped with
            FROM <collection URI>. Right for large graphs, but the page is
            only as durable as the service behind it.

Views. A query page always shows a table. Some results read better as
something else as well, so a query may declare a `view`, drawn ABOVE the
table — above, never instead. These queries are meant to be edited, and an
edit that drops the column a view needs would otherwise leave a blank panel
with no explanation. The view says what is missing; the table stays.
"""

from __future__ import annotations

import json
import shutil
import sys
import textwrap
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parent.parent
QUERIES_YAML = ROOT / "queries.yaml"
TEMPLATES = Path(__file__).resolve().parent / "templates"
DOCS = ROOT / "docs"
QUERY_DIRNAME = "query"
RQ_DIRNAME = "rq"

# Pinned deliberately: an unpinned CDN path follows whatever ships next, and
# an rdflib that no longer parses this Turtle breaks the page silently, years
# after anyone is watching. Bump on purpose, not by omission.
PYODIDE_VERSION = "0.26.4"
RDFLIB_VERSION = "7.1.1"
LEAFLET_VERSION = "1.9.4"
LEAFLET_SRI_JS = "sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
LEAFLET_SRI_CSS = "sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="

MAX_ROWS = 500
MAX_LOCAL_MB = 5.0

VIEW_LABELS = {
    "table": "table",
    "map": "table and map",
    "barchart": "table and bar chart",
    "scatter": "table and scatter plot",
    "intervals": "table and interval bars",
}

# The columns each view reads. Declared here rather than in the template, so
# that a query asking for a view it cannot feed fails at build time with the
# query's name attached, instead of leaving a blank panel in a browser.
VIEW_COLUMNS = {
    "table": {},
    # The map finds coordinates itself: any column holding POINT(lon lat), or
    # a lat/lon pair. Naming them would be one more thing to keep in step with
    # a query the reader is invited to edit.
    "map": {"label": "label", "colour": "", "wkt": ""},
    "barchart": {"category": "category", "value": "value"},
    "scatter": {"x": "x", "y": "y", "label": "label"},
    "intervals": {"from": "from", "to": "to", "label": "label"},
}

REDIRECT_STUB = """\
<!DOCTYPE html>
<meta charset="utf-8">
<title>Moved &mdash; the query page is now at query/</title>
<link rel="canonical" href="query/">
<meta http-equiv="refresh" content="0; url=query/">
<p>The query page has moved to <a href="query/">query/</a>.</p>
"""


# --------------------------------------------------------------------------- #
# Configuration                                                                #
# --------------------------------------------------------------------------- #


def load_config() -> dict:
    if not QUERIES_YAML.is_file():
        sys.exit("  !! queries.yaml is missing. Run make_metadata.py first.")
    cfg = yaml.safe_load(QUERIES_YAML.read_text(encoding="utf-8")) or {}
    for key in ("graph", "prefixes", "queries"):
        if key not in cfg:
            sys.exit(f"  !! queries.yaml must contain the key '{key}'.")
    return cfg


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


def query_view(q: dict) -> tuple[str, dict]:
    """(view, {role: column}) for one query, defaults filled in."""
    view = q.get("view") or "table"
    if view not in VIEW_LABELS:
        sys.exit(f"  !! query '{q['id']}' asks for an unknown view '{view}'. "
                 f"Known: {', '.join(sorted(VIEW_LABELS))}.")
    cols = dict(VIEW_COLUMNS[view])
    given = q.get("view_columns") or {}
    unknown = set(given) - set(cols)
    if unknown and cols:
        sys.exit(f"  !! query '{q['id']}' names view column(s) {sorted(unknown)} "
                 f"that the '{view}' view does not use. It reads {sorted(cols)}.")
    cols.update(given)
    return view, cols


def blurb(text: str, limit: int = 220) -> str:
    flat = " ".join(str(text or "").split())
    if len(flat) <= limit:
        return flat
    cut = flat[:limit]
    stop = cut.rfind(". ")
    return cut[:stop + 1] if stop > 60 else cut.rstrip() + "\u2026"


def count_rows(cfg: dict, graph_file: Path) -> None:
    """Row counts for the catalogue, from the real graph.

    make_metadata.py has already refused to ship a query that returns
    nothing; this is the same numbers again, for display.
    """
    from rdflib import Graph

    g = Graph()
    g.parse(graph_file, format="turtle")
    for q in cfg["queries"]:
        try:
            q["rows_at_build"] = len(list(g.query(cfg["prefixes"] + "\n" + q["sparql"])))
        except Exception:  # noqa: BLE001
            q["rows_at_build"] = "?"


# --------------------------------------------------------------------------- #
# Output                                                                       #
# --------------------------------------------------------------------------- #


def write_rq_files(cfg: dict, query_dir: Path) -> None:
    """Each query as a plain .rq file, for use outside the browser."""
    out = query_dir / RQ_DIRNAME
    out.mkdir(parents=True, exist_ok=True)
    for stale in out.glob("*.rq"):   # drop leftovers from renamed queries
        stale.unlink()
    for q in cfg["queries"]:
        intro = "\n".join(f"# {line}" for line in
                          textwrap.wrap(" ".join(str(q.get("intro", "")).split()), 76))
        (out / f"{q['id']}.rq").write_text(
            f"# {q['title']}\n{intro}\n\n{cfg['prefixes'].rstrip()}\n\n"
            f"{q['sparql'].rstrip()}\n", encoding="utf-8")


def main() -> None:
    cfg = load_config()
    graph_cfg = dict(cfg["graph"])
    graph_path = ROOT / graph_cfg["file"] if graph_cfg.get("file") else None
    engine = choose_engine(cfg, graph_path)
    queries = cfg.get("queries") or []
    print(f"  engine: {engine}, {len(queries)} queries")

    DOCS.mkdir(parents=True, exist_ok=True)
    query_dir = DOCS / QUERY_DIRNAME
    query_dir.mkdir(parents=True, exist_ok=True)

    graph_cfg["url"] = graph_cfg.get("url") or (graph_path.name if graph_path else "")
    if engine == "pyodide":
        if not (graph_path and graph_path.is_file()):
            sys.exit("  !! engine 'pyodide' needs graph.file to exist")
        if graph_cfg.get("publish", True):
            shutil.copyfile(graph_path, DOCS / graph_cfg["url"])
        graph_cfg["megabytes"] = f"{graph_path.stat().st_size / 1_048_576:.1f}"
        count_rows(cfg, graph_path)
    # The pages live one directory down; the graph stays at the site root
    # because that is the citable address.
    graph_cfg["page_url"] = "../" + graph_cfg["url"]

    write_rq_files(cfg, query_dir)

    env = Environment(loader=FileSystemLoader(str(TEMPLATES)),
                      autoescape=False, keep_trailing_newline=True,
                      trim_blocks=True, lstrip_blocks=True)

    common = dict(
        graph=graph_cfg, engine=engine,
        pyodide_version=PYODIDE_VERSION, rdflib_version=RDFLIB_VERSION,
        leaflet_version=LEAFLET_VERSION,
        leaflet_sri_js=LEAFLET_SRI_JS, leaflet_sri_css=LEAFLET_SRI_CSS,
        max_rows=MAX_ROWS,
        prefixes_json=json.dumps(cfg["prefixes"]),
        graph_json=json.dumps(graph_cfg, ensure_ascii=False),
    )

    (query_dir / "runner.js").write_text(
        env.get_template("runner.js.j2").render(**common), encoding="utf-8")

    prepared, catalogue = [], []
    for q in queries:
        view, cols = query_view(q)
        item = dict(q)
        item["sparql"] = q["sparql"].rstrip("\n")
        # Size the editor to the query, so nothing hides behind a scrollbar
        # the reader has to discover first.
        item["rows"] = max(8, item["sparql"].count("\n") + 3)
        item["view"], item["view_cols"] = view, cols
        prepared.append(item)
        catalogue.append({
            "id": q["id"], "title": q["title"], "blurb": blurb(q.get("intro")),
            "view_label": VIEW_LABELS[view],
            "rows_at_build": q.get("rows_at_build", "?"),
        })

    page_tpl = env.get_template("query_page.html.j2")
    for item in prepared:
        (query_dir / f"{item['id']}.html").write_text(
            page_tpl.render(query=item, view=item["view"],
                            view_cols_json=json.dumps(item["view_cols"]),
                            query_json=json.dumps(item["sparql"], ensure_ascii=False),
                            page=cfg.get("page", {}), **common),
            encoding="utf-8")
    print(f"  → docs/query/*.html ({len(prepared)} pages)")

    (query_dir / "all.html").write_text(
        env.get_template("all.html.j2").render(
            page=cfg.get("page", {}), queries=prepared,
            queries_json=json.dumps({q["id"]: q["sparql"] for q in prepared},
                                    ensure_ascii=False),
            views_json=json.dumps({q["id"]: {"view": q["view"],
                                             "cols": q["view_cols"]}
                                   for q in prepared}),
            **common),
        encoding="utf-8")

    (query_dir / "index.html").write_text(
        env.get_template("query_index.html.j2").render(
            page=cfg.get("page", {}), queries=catalogue,
            collection=cfg.get("collection", {}), **common),
        encoding="utf-8")
    print("  → docs/query/index.html")

    (DOCS / "sparql.html").write_text(REDIRECT_STUB, encoding="utf-8")

    # One map of the whole collection, from the same graph as the queries, so
    # it cannot show a different corpus than the pages beside it.
    map_cfg = cfg.get("map")
    if map_cfg and engine == "pyodide":
        (DOCS / "map.html").write_text(
            env.get_template("map.html.j2").render(
                map=map_cfg, page=cfg.get("page", {}),
                map_sparql_json=json.dumps(map_cfg["sparql"], ensure_ascii=False),
                **common),
            encoding="utf-8")
        print("  → docs/map.html")

    collection = cfg.get("collection")
    if collection:
        (DOCS / "index.html").write_text(
            env.get_template("index.html.j2").render(
                c=collection, has_map=bool(map_cfg and engine == "pyodide")),
            encoding="utf-8")
        print("  → docs/index.html")

    for name in ("metadata.ttl", "metadata.jsonld", "n4o-collection.ttl",
                 "crm-alignment.ttl"):
        src, dst = ROOT / "dist" / name, DOCS / name
        if src.is_file():
            shutil.copyfile(src, dst)
        elif dst.is_file():
            dst.unlink()
            print(f"  - docs/{name} removed (no longer in dist/)")

    style = TEMPLATES / "style.css"
    if style.is_file():
        shutil.copyfile(style, DOCS / "style.css")
        shutil.copyfile(style, query_dir / "style.css")

    # Old address, before the query layer moved into its own folder.
    stale = DOCS / "downloads"
    if stale.is_dir():
        shutil.rmtree(stale)
        print("  - docs/downloads/ removed (queries now under docs/query/rq/)")


if __name__ == "__main__":
    main()
