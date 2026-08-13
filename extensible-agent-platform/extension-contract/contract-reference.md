# Contract reference

The full `ext/v1` reference lives in [`README.md`](README.md) in this directory:
the shape, the eight contract invariants, permission semantics, the `ctx`
capability surface, versioning rules and known limitations.

Other entry points:

| Artifact | Purpose |
|---|---|
| [`schema/extension.schema.json`](schema/extension.schema.json) | Machine-readable schema (JSON Schema 2020-12) |
| [`../runtime/host/contract.py`](../runtime/host/contract.py) | **Authoritative** executable schema, including the cross-field invariants |
| [`examples/`](examples/) | Four worked examples, one per extension kind, copied verbatim from the running integrations |
