# SHRF Corpus Monitor — Perspective Matrix Claim Map
# Version: 0.1 — working instrument
# Rule: Nothing occupies the wrong space.
# For every feature: "Which space does this occupy, and is it pretending to occupy another?"

---

## Object → Layer → Perspective → Claim Type → Evidence State → Action

### Evaluation grid

| Object | Layer | Perspective | Claim Type | Evidence State | Verdict | Action |
|--------|-------|-------------|------------|----------------|---------|--------|
| corpus.json | CORPUS | Factual | Tested | syntax-pass, data-pass (validator PASS) | CLEAN | — |
| corpus.json node count (20) | CORPUS | Factual | Tested | user-confirmed | CLEAN | — |
| uptake-metrics-full.json | METRICS | Factual | Untested | syntax-pass only — no fetch run | PENDING | Run fetch |
| signal_class field | METRICS | Factual | Theoretical | syntax-pass — no real data | THEORETICAL | Mark pending first fetch |
| engagement_class field | METRICS | Factual | Theoretical | syntax-pass — written but unverified | THEORETICAL | Verify after fetch |
| low_data_flag | METRICS | Factual | Tested | logic tested in classify_signal | CLEAN | — |
| download_ratio | METRICS | Factual | Theoretical | formula correct — no real denominators yet | THEORETICAL | Verify after fetch |
| domain classification (176 entries) | METRICS | Factual | User-confirmed | Neil confirmed DOI list | CLEAN | — |
| version chains (superseded_by) | METRICS | Factual | User-confirmed | extracted from DOI document | CLEAN | — |
| Topology node positions | VISUAL | Creative/theoretical | Theoretical | angle_hint/radius_hint are design choices | LABELLED | Doctrine rail present |
| Topology node size = views | VISUAL | Visual | Theoretical | no real view data yet | PENDING | Wire confirmed — data pending |
| Signal distribution chart | VISUAL | Visual | Theoretical | renders zeros correctly | PENDING | Meaningful after fetch |
| Domain tier radii | VISUAL | Visual | Theoretical | domain→tier map is design choice | LABELLED | FIX 7 applied |
| Resolution register items | RESOLUTION | Factual | User-confirmed | 8 items drawn from real corpus gaps | CLEAN | — |
| Auto-detected resolution items | RESOLUTION | Factual | Inferred | derived from loaded state — may miss gaps | INFERRED | Label as auto-detected |
| "Mark RESOLVED" requires evidence | RESOLUTION | Operational | Tested | UI enforces evidence field | CLEAN | — |
| Fetch progress bar | OPERATIONAL | Factual | Tested | chunked sync — real per-chunk progress | CLEAN (after FIX 3+4) | — |
| retrieval_method field | METRICS | Factual | Tested | written on both success/failure paths | CLEAN (after FIX 2) | — |
| Validator PASS claim | VALIDATION | Factual | Tested | 0 errors, 2 acceptable warnings | CLEAN | — |
| Benchmark readiness schema | CORPUS | Theoretical | Design-locked | explicitly marked DESIGN_LOCKED | CLEAN | Implement post-fetch |
| corpus-index-full schema | CORPUS | Theoretical | Design-locked | explicitly marked DESIGN_LOCKED | CLEAN | Implement post-decision |
| "Uptake = behaviour, not validity" | DOCTRINE | Factual | User-confirmed | invariant in _meta, rail, sidebar, tab headers | CLEAN | Monitor for drift |

---

## Space occupation failures — current known list

| Feature | Claims to occupy | Actually occupies | Failure type | Status |
|---------|-----------------|-------------------|--------------|--------|
| signal_class before first fetch | Factual (metrics) | Theoretical (zeros) | Premature factual claim | PENDING — first fetch resolves |
| topology positions | Evidence space | Design/creative space | Visual misleading | MITIGATED — doctrine rail present |
| engagement_class before fetch | Factual | Theoretical | Premature factual claim | PENDING — fetch resolves |
| benchmark_readiness (if built now) | Tested | Theoretical | Theory occupying test space | BLOCKED — design-locked correctly |
| domain rankings in dashboard | Factual comparison | Theoretical (all zeros) | Comparative claim without data | PENDING — fetch resolves |

**All current space-occupation failures resolve after the first fetch run.**
No structural failures remain — only data-pending states.

---

## Perspective matrix — applied per layer

### CORPUS layer
- **Internal:** nodes, edges, gaps, overlaps validated. DOI format clean. 0 errors. ✓
- **External:** 20 nodes visible in topology. New user would not see 176-record scope. △ (corpus-index-full will address)
- **Factual:** all DOIs user-confirmed or deposited. ✓
- **Visual:** topology renders 20 nodes with domain colour. No misleading claims. ✓
- **Spoken:** "20 canonical nodes representing the core framework and branches." ✓
- **Verbatim:** field names stable across corpus.json, schema.json, validator. ✓
- **Tested:** validator passes. Schema enforced. ✓

### METRICS layer
- **Internal:** 176 entries, correct structure, provenance fields written. ✓
- **External:** all values zero — new auditor sees empty dashboard. HONEST — not misleading. ✓
- **Factual:** DOIs traceable to deposited records. ✓ — values pending fetch. △
- **Visual:** charts render zeros. No false signal displayed. ✓
- **Spoken:** "Metrics await first fetch. Values are zeroed placeholders, not real data." ✓
- **Verbatim:** field names (views, downloads, retrieval_method, engagement_class) stable. ✓
- **Tested:** fetch script syntax-pass. Runtime-pass pending first execution. △

### VALIDATION layer
- **Internal:** all 7 checks implemented. Cross-layer alignment check present. ✓
- **External:** PASS/FAIL clearly displayed with error counts. ✓
- **Factual:** 0 errors, 2 warnings correctly reported. ✓
- **Tested:** validator run against corpus.json. Passed. ✓

### TOPOLOGY layer
- **Internal:** nodes positioned by design-choice radii. Overlays wired after FIX 6+7. ✓
- **External:** doctrine rail states "projection layer only." ✓
- **Visual:** node size encodes views (wired but pending data). Domain colours are labels not scores. ✓
- **Creative:** radial layout is a design metaphor. Correctly labelled as such. ✓
- **Risk:** if a user interprets central position as "more important" — doctrine rail mitigates but does not eliminate.
  - **Recommended addition:** tooltip on hover stating "position = domain sector, not importance." △

### RESOLUTION layer
- **Internal:** 8 real items. Auto-detection from live state. Closure requires evidence. ✓
- **External:** status classes are self-explanatory. ✓
- **Factual:** items traceable to corpus skill pending-updates.md and real gaps. ✓
- **Creative:** "resolution priority" is not scientific priority — correctly separated. ✓
- **Tested:** evidence field enforced in UI. ✓

### EXPORT layer
- **Internal:** CSV, JSON, priority report all read-only projections. ✓
- **External:** files labelled with date. ✓
- **Factual:** exports reflect loaded state only. No inference. ✓
- **Tested:** fix 1 applied — dict no longer written into status field. ✓

---

## Invariants — must hold at all times

1. **Metrics must not occupy epistemic truth space.**
   Signal class is behaviour, not validity. Enforced in doctrine rail, _meta, and sidebar.

2. **Visuals must not occupy evidence space.**
   Topology is projection. Charts are rendering. Neither produces claims.

3. **Theory must not occupy tested space.**
   Design-locked schemas are explicitly marked. Benchmark readiness blocked until post-fetch.

4. **Creative framing must not occupy factual reporting space.**
   Metaphors (spiral, topology, snowflake) are in the visual companion, not the corpus.

5. **Internal logic must not substitute for outside-auditor clarity.**
   Every layer has a user-visible description of what it is and is not.

---

## Next pressure-test trigger conditions

| Condition | What to test |
|-----------|-------------|
| First fetch completes | Signal classes become real — verify distribution makes sense |
| Any new field added | Which space does it occupy? Is it labelled correctly? |
| Any new visual | Does it encode state without implying evidence? |
| Any new claim in UI | Factual or theoretical? Tested or assumed? |
| External reviewer opens app | Can they read the system without the full context Neil has? |
| Corpus expansion to 176 nodes | Does topology remain readable or become noise? |

---

## Action queue — from this analysis

| Priority | Action | Reason |
|----------|--------|--------|
| 1 | Run first fetch | Resolves all PENDING evidence states |
| 2 | Add hover tooltip "position = domain sector, not importance" to topology | Closes remaining visual space-occupation risk |
| 3 | Mark signal_class/engagement_class displays with "pending first fetch" until retrieved=True | Prevents premature factual interpretation |
| 4 | After fetch: verify signal distribution makes sense against known corpus | First real data validation |
| 5 | After fetch: close AUTO-detected resolution items that are now resolved | Cleans queue |

---

## Hard rule

> For every feature: "Which space does this occupy, and is it pretending to occupy another?"

If the answer is yes: fix before shipping.
If the answer is unclear: label it explicitly until it becomes clear.
Unclear is not a failure state. Unlabelled unclear is.
