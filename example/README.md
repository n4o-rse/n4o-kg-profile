# Worked example — Linked Open Ogham (collection 9)

A complete, buildable collection repository. The self-test workflow builds it on
every push, so a change to the profile, the shapes or a generator cannot be
released without having produced a valid collection at least once.

The instance data in `rdf/example-bundle.ttl` is synthetic: five entities, just
enough to keep the build and both example queries running. Replace it with a
real bundle when copying this as a template.

```bash
cp -r ../profile ../build .
python build/make_metadata.py
python build/build_sparql.py
python -m http.server -d docs      # then open http://localhost:8000/
```
