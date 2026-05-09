# SHRF Corpus Monitor

**Version:** 0.7.0 — Prototype  
**Status:** Instrument awaiting first observation run  
**Live app:** [Streamlit Community Cloud](https://share.streamlit.io) *(deploy from this repo)*

---

## What this is

A local monitoring and analysis application for the [SHRF](https://doi.org/10.5281/zenodo.18761638) research corpus.

Five separated layers — none collapse into each other:

| Layer | Purpose | Source of truth |
|-------|---------|-----------------|
| **Corpus** | Canonical DOI registry, provenance graph, version chains | `data/corpus.json` |
| **Metrics** | Zenodo view/download uptake, signal classification, deltas | `data/uptake-metrics-full.json` |
| **Validation** | Schema checks, duplicate detection, cross-layer alignment | `tools/validate_corpus.py` |
| **Resolution** | Blocker register, unresolved items, evidence-gated closure | `data/resolution-register.json` |
| **Visual** | Topology, domain view, overlays — projection only | `app/shrf_corpus_monitor_app.py` |

**Core invariant (permanent):**
> Uptake metrics = audience behaviour only.  
> Corpus truth lives in `corpus.json`.  
> Visual topology is a projection layer only.  
> Unclear is not a failure state. Unlabelled unclear is.

---

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Fetch live Zenodo metrics (first run — ~70 seconds)
python3 tools/fetch_zenodo_metrics.py --only-preferred --summary

# 3. Launch the app
streamlit run app/shrf_corpus_monitor_app.py
```

Then load the data files via the sidebar.

---

## Repository structure

```
SHRF-Corpus-Monitor/
├── app/
│   └── shrf_corpus_monitor_app.py     # Streamlit app (7 tabs)
├── data/
│   ├── corpus.json                    # Canonical corpus (20 nodes, source of truth)
│   ├── uptake-metrics-full.json       # 176 DOI metrics (zeroed until fetch)
│   ├── resolution-register.json       # Blocker/resolution register
│   └── shrf-corpus-schema.json        # JSON schema for validation
├── tools/
│   ├── fetch_zenodo_metrics.py        # Zenodo API + HTML fetcher (v2.1)
│   └── validate_corpus.py             # Corpus schema validator
├── docs/
│   ├── perspective-matrix-claim-map.md  # System integrity instrument
│   └── SHRF_CORPUS_MONITOR_README.md    # Prototype package README
├── releases/
│   └── SHRF_Corpus_Monitor_Prototype_Package.zip
├── metrics_snapshots/                 # Auto-created on first fetch (gitignored)
├── .streamlit/
│   └── config.toml                    # Dark theme + server config
├── requirements.txt
├── CITATION.cff
├── LICENSE                            # CC BY 4.0
└── README.md                          # This file
```

---

## App tabs

| Tab | Function |
|-----|---------|
| 📊 Dashboard | Signal distribution, domain breakdown, priority list, full metrics table |
| 🗺 Topology | 176-node radial canvas with zoom/pan, domain overlays, gap halos |
| ✓ Validate | Corpus + metrics schema checks, cross-layer alignment |
| ⚡ Fetch Log | Per-record fetch results, method distribution, save button |
| 🔗 Version Chains | Superseded → preferred-cite uptake comparison |
| 📤 Export | CSV, JSON, priority report, failed DOIs |
| 🔲 Resolution | Blocker register, auto-detected issues, evidence-gated closure |

---

## Fetch tool

```bash
# First run (skip superseded versions)
python3 tools/fetch_zenodo_metrics.py --only-preferred --summary

# Retry failures only
python3 tools/fetch_zenodo_metrics.py --only-unretrieved

# Full run (all 176)
python3 tools/fetch_zenodo_metrics.py --summary

# Weekly cron (macOS/Linux)
0 8 * * 1 cd /path/to/SHRF-Corpus-Monitor && python3 tools/fetch_zenodo_metrics.py --only-preferred --summary >> fetch.log 2>&1
```

Fetch strategy: Zenodo REST API → HTML scrape fallback → typed failure log.  
Provenance fields written per entry: `retrieval_method`, `retrieval_timestamp`, `error_message`.

---

## Streamlit Community Cloud deployment

1. Fork or push this repo to your GitHub account
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Connect your GitHub account
4. Select this repo → `app/shrf_corpus_monitor_app.py` as the main file
5. Deploy

Note: the live deployment will have empty data files until you upload a fetched `uptake-metrics-full.json` or connect a data source. The app correctly exposes this as NO_METRICS state.

---

## Zenodo archiving

When a stable release is ready:

1. Create a GitHub release with a version tag (e.g. `v0.7.0`)
2. Go to [zenodo.org](https://zenodo.org) → GitHub sync
3. Enable the SHRF-Corpus-Monitor repo
4. The release will be automatically archived with a DOI
5. Update `CITATION.cff` with the assigned DOI

---

## Corpus DOIs

| Record | DOI |
|--------|-----|
| BASELINE-12 index | [10.5281/zenodo.18899474](https://doi.org/10.5281/zenodo.18899474) |
| USDOP v1.2 | [10.5281/zenodo.18721255](https://doi.org/10.5281/zenodo.18721255) |
| SHRF v2 | [10.5281/zenodo.18761638](https://doi.org/10.5281/zenodo.18761638) |
| IWC | [10.5281/zenodo.18764956](https://doi.org/10.5281/zenodo.18764956) |
| PRR-1 Spec | [10.5281/zenodo.20068119](https://doi.org/10.5281/zenodo.20068119) |

Full corpus: 176 DOIs in `data/uptake-metrics-full.json`

---

## Related work

- [Provenance Collapse / PRR-1](https://doi.org/10.5281/zenodo.20055987)
- [Tuckwell Corpus Index v1.1](https://doi.org/10.5281/zenodo.19942392)

---

## Citation

```
Tuckwell, N.C. (2026). SHRF Corpus Monitor (v0.7.0).
GitHub: https://github.com/NeilTuckwell/SHRF-Corpus-Monitor
```

See `CITATION.cff` for machine-readable citation.

---

## Perspective matrix

The system integrity instrument is in `docs/perspective-matrix-claim-map.md`.

Core rule:
> For every feature: "Which space does this occupy, and is it pretending to occupy another?"
