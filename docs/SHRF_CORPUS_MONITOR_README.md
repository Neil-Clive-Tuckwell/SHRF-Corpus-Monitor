# SHRF Corpus Monitor — Prototype Package

## Package status

This is a working prototype under the agreed definition:

A working prototype is not a system that already produces correct live results. It is a system that correctly exposes what it does not yet know.

## Included files

- shrf_corpus_monitor_app.py
- perspective-matrix-claim-map.md
- SHRF_CORPUS_MONITOR_README.md

## Syntax check

shrf_corpus_monitor_app.py passes Python compilation with:

python -m py_compile shrf_corpus_monitor_app.py

## Required runtime files not included in this bundle

Place these beside the app before running the full workflow:

- corpus.json
- uptake-metrics-full.json
- resolution-register.json
- fetch_zenodo_metrics.py

## Install

pip install streamlit pandas requests beautifulsoup4 lxml plotly

## Launch app

streamlit run shrf_corpus_monitor_app.py

## First observation run

python3 fetch_zenodo_metrics.py --only-preferred --summary

Then load the produced metrics JSON into the app.

## Core invariant

Uptake metrics are audience behaviour only.
Corpus truth lives in corpus.json.
Visual topology is a projection layer only.
Unclear is not a failure state. Unlabelled unclear is.
