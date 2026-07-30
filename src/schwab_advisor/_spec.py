"""OpenAPI spec introspection shared by the model-coverage audit
(scripts/audit_models.py), the CI regression guard (tests/test_models.py),
and the prod drift checks (tests/test_production_integration.py).

One resolver, one walk semantics. These three call sites used to carry
hand-copied variants that had already diverged (only one handled array
nodes), which let the CI guard and the prod drift printer disagree about
which fields a spec declares.
"""

import functools
import json
from pathlib import Path


@functools.cache
def _load_schemas(spec_path: str) -> dict:
    """Parse a spec file once per path; every schema_path walk reuses it."""
    return json.loads(Path(spec_path).read_text())["components"]["schemas"]


def spec_properties(spec_path: str | Path, schema_path: str) -> frozenset:
    """Resolve an OpenAPI schema to its set of property names.

    schema_path uses "/" walk notation — e.g.
    "StandingInstructionDetail/data/attributes": the first part names a
    components.schemas entry; each later part descends into that
    property. $ref and allOf are expanded; array nodes descend into
    their items.
    """
    schemas = _load_schemas(str(spec_path))

    def expand(o, seen: frozenset = frozenset()):
        if not isinstance(o, dict):
            return {}
        if "$ref" in o:
            name = o["$ref"].split("/")[-1]
            if name in seen:  # circular $ref (allOf cycles happen in
                return {}     # generated specs) — stop, don't recurse
            return expand(schemas.get(name, {}), seen | {name})
        if "allOf" in o:
            merged = {}
            for sub in o["allOf"]:
                merged.update(expand(sub, seen))
            return merged
        if o.get("type") == "array":
            return expand(o.get("items", {}), seen)
        return o.get("properties", {}) or {}

    parts = schema_path.split("/")
    cur = schemas.get(parts[0])
    if cur is None:
        return frozenset()
    cur_props = expand(cur)
    for p in parts[1:]:
        nxt = cur_props.get(p) if isinstance(cur_props, dict) else None
        if nxt is None and isinstance(cur, dict):
            nxt = cur.get(p)
        if nxt is None:
            return frozenset()
        cur_props = expand(nxt) if isinstance(nxt, dict) else {}
        cur = nxt
    return frozenset(cur_props)
