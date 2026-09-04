# n4o-kg-profile

Tooling for publishing a collection into the **NFDI4Objects Knowledge Graph**.

You maintain one file — `metadata.yaml` — and a GitHub Action produces the
metadata RDF, the registration record the N4O KG reads, a CIDOC CRM alignment,
and a browsable SPARQL page on GitHub Pages.

[![Self-test](https://github.com/n4o-rse/n4o-kg-profile/actions/workflows/selftest.yml/badge.svg)](https://github.com/n4o-rse/n4o-kg-profile/actions/workflows/selftest.yml)

---

## Three repositories, three jobs

```
<source repository>            e.g. bb-5kbc-sites
    produces the bundle; knows nothing about the KG
        │  raw URL or Zenodo file
        ▼
<collection repository>        e.g. bb-5kbc-public          ← one per collection
    metadata.yaml              the only file you maintain
    rdf/<name>-bundle.ttl      archived copy of what was loaded
    .github/workflows/build.yml   eight lines
    dist/  docs/               generated
        │  uses: @v1
        ▼
n4o-kg-profile                 this repository, tagged v1, v1.1, …
    profile/  build/  action.yml
```

The action copies `profile/` and `build/` into the collection repository on
every run and overwrites whatever is there. A collection therefore cannot
quietly carry a divergent context or divergent shapes — the failure mode that
makes a family of repositories drift apart over years. The price is that the
profile is versioned through tags, and `@v1` is a deliberate decision of the
collection repository.

---

## Quick start for a new collection

1. **Create the repository** and add two things:

   ```
   metadata.yaml
   .github/workflows/build.yml
   ```

   Copy `example/metadata.yaml` as your starting point. The four facts the N4O
   KG needs sit at the top: `title`, `homepage` (the publication URL, e.g. a
   Zenodo DOI), `sameAs` (the Wikidata item) and `license`. Without all four,
   the SHACL gate stops the build.

2. **Point at the bundle.** Either commit it to `rdf/`, or give a `source:` and
   let the build fetch it once:

   ```yaml
   distributions:
     - role: bundle
       file: rdf/bb5kbc-bundle.ttl
       source: https://raw.githubusercontent.com/…/dist/bb5kbc-bundle.ttl
       downloadURL: https://raw.githubusercontent.com/…/dist/bb5kbc-bundle.ttl
       mediaType: https://www.iana.org/assignments/media-types/text/turtle
   ```

   Name the same file under `model.bundle`; that is what gets counted.

3. **Add the workflow** — this is the whole file:

   ```yaml
   name: Build

   on:
     push:
       branches: [main]
     workflow_dispatch:

   jobs:
     collection:
       uses: n4o-rse/n4o-kg-profile/.github/workflows/collection.yml@v1
       with:
         strict: true
   ```

4. **Enable Pages**: *Settings → Pages → Source: GitHub Actions*. Nothing else;
   the workflow uploads `docs/` itself.

5. **Push.** The workflow runs on every push to `main`, and can be started by
   hand under *Actions → Build → Run workflow* (that is what
   `workflow_dispatch` is for). Watch the job summary: it reports the triple
   count and the first forty lines of the build log.

---

## What you get

| File | Purpose |
|---|---|
| `dist/n4o-collection.ttl` | the registration record — this is what NFDI4Objects reads |
| `dist/metadata.ttl` | the full statement: DCAT, VoID statistics, CRM alignment, example queries |
| `dist/metadata.jsonld` | the same, as JSON-LD |
| `dist/crm-alignment.ttl` | `rdfs:subClassOf` / `subPropertyOf` to CIDOC CRM, loadable on its own |
| `queries.yaml` | the example queries, in the format `build_sparql.py` reads |
| `docs/index.html` | landing page: the four facts, the files, the measured graph size |
| `docs/sparql.html` | the queries, editable and runnable in the browser |
| `docs/downloads/queries/*.rq` | the same queries as plain files |

---

## Running it by hand

The action is a thin wrapper; everything works locally too.

```bash
pip install -r requirements.txt
cp -r /path/to/n4o-kg-profile/{profile,build} .
python build/make_metadata.py     # metadata, RDF, queries.yaml
python build/build_sparql.py      # docs/index.html, docs/sparql.html
```

Both scripts are configured through constants at the top of the file rather
than command-line arguments, so a VS Code "Run" needs no setup. The action
overrides two of them through the environment (`N4O_STRICT`, `N4O_REFRESH`) so
that it never has to edit a file.

To preview the query page, serve `docs/` over HTTP — the browser refuses to
fetch the Turtle file from a `file://` path:

```bash
python -m http.server -d docs
```

---

## Action inputs

Use the reusable workflow (build **and** Pages) unless you need finer control:

```yaml
jobs:
  collection:
    uses: n4o-rse/n4o-kg-profile/.github/workflows/collection.yml@v1
    with:
      metadata: metadata.yaml   # default
      strict: true              # default
      deploy-pages: true        # default
      commit-outputs: true      # write dist/ and docs/ back into the branch
```

Or call the action directly inside your own job:

```yaml
- uses: n4o-rse/n4o-kg-profile@v1
  id: n4o
  with:
    metadata: metadata.yaml
    strict: true
    refresh: false             # refetch the bundle from `source:`
    build-pages: true
    check-reproducible: true
- run: echo "${{ steps.n4o.outputs.triples }} triples"
```

---

## What the build guarantees

- **SHACL.** The four N4O facts and the NCMDP mandatory elements are
  `sh:Violation`; with `strict: true` the run stops.
- **Every example query runs.** Zero rows fails the build. SPARQL does not fail
  on a mistyped IRI — it returns nothing, so an empty result is the ordinary
  symptom of a broken graph rather than of a boring question.
- **Byte reproducibility.** A second run must produce identical files. Blank
  nodes are canonicalised (URDNA2015) and prefixes bound explicitly; a diff
  after an unchanged rebuild means the generator is wrong.
- **Checksums.** `spdx:checksum` per distribution records which version was
  actually loaded.
- **Counted, not typed in.** Class and property counts come from the bundle.
  Classes with no CIDOC CRM alignment are reported; alignments with no
  occurrence in the bundle are reported too — the usual symptom of a typo.

---

## Large graphs

The query page has two engines, chosen in `queries.yaml` under `graph.engine`,
or automatically by size:

- **`pyodide`** (default under 5 MB) — the graph is a static Turtle file parsed
  in the browser by `rdflib` under Pyodide. No endpoint, no server: an archived
  copy of the repository stays queryable with nothing to keep alive.
- **`endpoint`** — the queries run against
  `https://graph.nfdi4objects.net/api/sparql`, scoped with the collection URI.
  Right for large graphs, but the page is only as durable as the service.

For scale: a 1.4 MB / 28,500-triple bundle parses in about a second and is
comfortable in the browser. A collection with hundreds of thousands of triples
is not, and should use `endpoint`.

---

## Layout of this repository

```
action.yml                        composite action (the build)
.github/workflows/collection.yml  reusable workflow (build + Pages)
.github/workflows/selftest.yml    builds example/ on every push
profile/
  context.jsonld                  the crosswalk: one YAML key → one IRI
  profile.ttl                     the four terms this profile mints
  shapes.ttl                      the SHACL gate
  CROSSWALK.md                    the specification
build/
  make_metadata.py                metadata, RDF, queries.yaml
  build_sparql.py                 docs/index.html, docs/sparql.html
  templates/                      Jinja templates and the stylesheet
example/                          a worked collection, built by the self-test
```

## Status

Draft. The obligation levels in `profile/shapes.ttl` and the element table in
`profile/CROSSWALK.md` are still to be reconciled with the binding NCMDP list
and with OCMDP / MaCHeCO — see section 6 of the crosswalk. Placeholders are
marked `TODO` and deliberately not guessed.

## Licence

MIT for the code, CC BY 4.0 for the profile documents. See `LICENSE`.
