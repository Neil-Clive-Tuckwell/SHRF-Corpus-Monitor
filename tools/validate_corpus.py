#!/usr/bin/env python3
"""
SHRF Corpus Validator
Run: python3 validate_corpus.py shrf-corpus-v04.json

Checks:
  - Schema conformance (structural)
  - Cross-reference integrity (relational)
  - DOI format consistency
  - State/tier enum validity
  - No duplicate IDs or DOIs
  - Edge referential integrity
  - Gap node references exist
  - Overlap node references exist
  - Preferred cite / version_of consistency
  - Baseline-12 node number uniqueness

Exit 0 = PASS. Exit 1 = FAIL (details printed).
"""

import json
import sys
import re
from collections import defaultdict

ALLOWED_STATES = {"VERIFIED","INFERRED","SPECULATIVE","ANALOGICAL","WITHDRAWN","UNKNOWN"}
ALLOWED_TIERS  = {"T0","T1","T2","T3"}
ALLOWED_LAYERS = {"METHOD","FRAMEWORK","FOUNDATION","BRANCH","NOTE","CASE"}
ALLOWED_CONFIDENCE = {"CANONICAL","DERIVED-CANONICAL","USER-CONFIRMED","INFERRED","NEEDS-REVIEW"}
ALLOWED_EDGE_TYPES = {
    "IsFoundationFor","IsContinuedBy","IsAppliedIn","IsAdjacentTo",
    "References","IsVersionOf","IsPartOf","IsCitedBy","Cites"
}
ALLOWED_GAP_SEVERITY = {"high","medium","low"}
ALLOWED_GAP_TYPES = {"observational","empirical","theoretical","annotation","metadata"}
ALLOWED_OVL_TYPES = {
    "domain-overlap","framework-overlap","branch-continuity",
    "spine-continuity","conceptual-overlap","evidence-overlap"
}
DOI_PATTERN = re.compile(r'^10\.\d{4,}/zenodo\.\d+$')

def validate(path):
    errors = []
    warnings = []

    # ── Load ──────────────────────────────────────────────────────────
    try:
        with open(path) as f:
            corpus = json.load(f)
    except Exception as e:
        print(f"FATAL: Cannot load {path}: {e}")
        sys.exit(1)

    # ── Top-level structure ──────────────────────────────────────────
    for key in ["_meta","nodes","edges","gaps","overlaps"]:
        if key not in corpus:
            errors.append(f"Missing top-level key: '{key}'")

    if errors:
        _report(errors, warnings, path)
        sys.exit(1)

    nodes   = corpus["nodes"]
    edges   = corpus["edges"]
    gaps    = corpus["gaps"]
    overlaps= corpus["overlaps"]
    meta    = corpus["_meta"]

    # ── Meta ─────────────────────────────────────────────────────────
    for mkey in ["schema","source","canonical_doi","renderer_rule","last_updated","version"]:
        if mkey not in meta:
            errors.append(f"_meta missing key: '{mkey}'")
    if "canonical_doi" in meta and not DOI_PATTERN.match(meta["canonical_doi"]):
        errors.append(f"_meta.canonical_doi DOI format invalid: {meta['canonical_doi']}")

    # ── Build ID and DOI sets ─────────────────────────────────────────
    node_ids  = {}
    node_dois = {}
    b12_nums  = {}

    for i, n in enumerate(nodes):
        loc = f"nodes[{i}] (id={n.get('id','?')})"

        # Required fields
        for req in ["id","doi","title","short","tier","layer","branch","state","confidence","status","baseline12","angle_hint","radius_hint","description","open_gaps","falsifiers"]:
            if req not in n:
                errors.append(f"{loc}: missing required field '{req}'")

        nid = n.get("id","")
        doi = n.get("doi","")

        # Duplicate IDs
        if nid in node_ids:
            errors.append(f"Duplicate node id: '{nid}' (nodes[{node_ids[nid]}] and {loc})")
        else:
            node_ids[nid] = i

        # Duplicate DOIs
        if doi and doi in node_dois:
            errors.append(f"Duplicate node doi: '{doi}' (nodes[{node_dois[doi]}] and {loc})")
        elif doi:
            node_dois[doi] = i

        # DOI format
        if doi and not DOI_PATTERN.match(doi):
            errors.append(f"{loc}: doi format invalid: '{doi}'")

        # Enum checks
        if n.get("state") not in ALLOWED_STATES:
            errors.append(f"{loc}: state '{n.get('state')}' not in {ALLOWED_STATES}")
        if n.get("tier") not in ALLOWED_TIERS:
            errors.append(f"{loc}: tier '{n.get('tier')}' not in {ALLOWED_TIERS}")
        if n.get("layer") not in ALLOWED_LAYERS:
            errors.append(f"{loc}: layer '{n.get('layer')}' not in {ALLOWED_LAYERS}")
        if n.get("confidence") not in ALLOWED_CONFIDENCE:
            errors.append(f"{loc}: confidence '{n.get('confidence')}' not in {ALLOWED_CONFIDENCE}")

        # Range checks
        ah = n.get("angle_hint")
        rh = n.get("radius_hint")
        if ah is not None and not (0 <= ah <= 360):
            errors.append(f"{loc}: angle_hint {ah} out of range [0,360]")
        if rh is not None and not (0.0 <= rh <= 1.0):
            errors.append(f"{loc}: radius_hint {rh} out of range [0.0,1.0]")

        # short label length
        if len(n.get("short","")) > 16:
            warnings.append(f"{loc}: short '{n['short']}' exceeds 16 chars (display may truncate)")

        # Baseline-12 consistency
        if n.get("baseline12") is True:
            bnum = n.get("baseline12_node")
            if bnum is None:
                errors.append(f"{loc}: baseline12=true but baseline12_node missing")
            elif bnum in b12_nums:
                errors.append(f"{loc}: duplicate baseline12_node={bnum} (also at nodes[{b12_nums[bnum]}])")
            else:
                b12_nums[bnum] = i

        # preferred_cite / version_of consistency
        if n.get("preferred_cite") is True and "version_of" not in n:
            errors.append(f"{loc}: preferred_cite=true but version_of missing")
        if "version_of" in n:
            if not DOI_PATTERN.match(n["version_of"]):
                errors.append(f"{loc}: version_of DOI format invalid: '{n['version_of']}'")
            # Check if the versioned DOI exists in corpus (warning if not — may be external)
            if n["version_of"] not in node_dois:
                warnings.append(f"{loc}: version_of '{n['version_of']}' not found in corpus nodes (may be external version)")

    # ── Edge integrity ───────────────────────────────────────────────
    for i, e in enumerate(edges):
        loc = f"edges[{i}]"
        for req in ["source","target","type","strength","confidence"]:
            if req not in e:
                errors.append(f"{loc}: missing required field '{req}'")

        src, tgt = e.get("source",""), e.get("target","")
        if src and src not in node_ids:
            errors.append(f"{loc}: source '{src}' not found in node ids")
        if tgt and tgt not in node_ids:
            errors.append(f"{loc}: target '{tgt}' not found in node ids")
        if src and tgt and src == tgt:
            errors.append(f"{loc}: self-loop edge source==target=='{src}'")

        etype = e.get("type","")
        if etype not in ALLOWED_EDGE_TYPES:
            errors.append(f"{loc}: edge type '{etype}' not in allowed set")

        strength = e.get("strength")
        if strength is not None and not (0.0 <= strength <= 1.0):
            errors.append(f"{loc}: strength {strength} out of range [0.0,1.0]")

        if e.get("confidence") not in ALLOWED_CONFIDENCE:
            errors.append(f"{loc}: confidence '{e.get('confidence')}' not in allowed set")

    # ── Gap integrity ────────────────────────────────────────────────
    gap_ids = set()
    for i, g in enumerate(gaps):
        loc = f"gaps[{i}]"
        for req in ["id","node","description","severity","type"]:
            if req not in g:
                errors.append(f"{loc}: missing required field '{req}'")

        gid = g.get("id","")
        if gid in gap_ids:
            errors.append(f"{loc}: duplicate gap id '{gid}'")
        else:
            gap_ids.add(gid)

        if not gid.startswith("GAP-"):
            errors.append(f"{loc}: gap id '{gid}' must start with 'GAP-'")

        gnode = g.get("node","")
        if gnode and gnode not in node_ids:
            errors.append(f"{loc}: gap node '{gnode}' not found in node ids")

        if g.get("severity") not in ALLOWED_GAP_SEVERITY:
            errors.append(f"{loc}: severity '{g.get('severity')}' not in {ALLOWED_GAP_SEVERITY}")
        if g.get("type") not in ALLOWED_GAP_TYPES:
            errors.append(f"{loc}: type '{g.get('type')}' not in {ALLOWED_GAP_TYPES}")

    # ── Overlap integrity ────────────────────────────────────────────
    ovl_ids = set()
    for i, o in enumerate(overlaps):
        loc = f"overlaps[{i}]"
        for req in ["id","nodes","description","type"]:
            if req not in o:
                errors.append(f"{loc}: missing required field '{req}'")

        oid = o.get("id","")
        if oid in ovl_ids:
            errors.append(f"{loc}: duplicate overlap id '{oid}'")
        else:
            ovl_ids.add(oid)

        if not oid.startswith("OVL-"):
            errors.append(f"{loc}: overlap id '{oid}' must start with 'OVL-'")

        onodes = o.get("nodes",[])
        if len(onodes) < 2:
            errors.append(f"{loc}: overlap must reference at least 2 nodes")
        for nref in onodes:
            if nref not in node_ids:
                errors.append(f"{loc}: overlap node '{nref}' not found in node ids")

        if o.get("type") not in ALLOWED_OVL_TYPES:
            errors.append(f"{loc}: type '{o.get('type')}' not in allowed set")

    _report(errors, warnings, path, corpus)

def _report(errors, warnings, path, corpus=None):
    print(f"\n{'═'*60}")
    print(f"  SHRF Corpus Validator")
    print(f"  File: {path}")
    if corpus:
        meta = corpus.get("_meta",{})
        print(f"  Version: {meta.get('version','?')}  Updated: {meta.get('last_updated','?')}")
        print(f"  Nodes: {len(corpus.get('nodes',[]))}  Edges: {len(corpus.get('edges',[]))}  Gaps: {len(corpus.get('gaps',[]))}  Overlaps: {len(corpus.get('overlaps',[]))}")
    print(f"{'═'*60}\n")

    if warnings:
        print(f"  WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"    ⚠  {w}")
        print()

    if errors:
        print(f"  ERRORS ({len(errors)}):")
        for e in errors:
            print(f"    ✗  {e}")
        print(f"\n  STATUS: FAIL — {len(errors)} error(s), {len(warnings)} warning(s)")
        print(f"{'═'*60}\n")
        sys.exit(1)
    else:
        print(f"  STATUS: PASS — 0 errors, {len(warnings)} warning(s)")
        print(f"{'═'*60}\n")
        sys.exit(0)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 validate_corpus.py <corpus.json>")
        sys.exit(1)
    validate(sys.argv[1])
