"""
shrf_corpus_monitor_app.py
==========================
SHRF Corpus Monitor  v0.6  —  Local Control Room

Launch:
    pip install streamlit pandas requests beautifulsoup4 lxml plotly
    streamlit run shrf_corpus_monitor_app.py

Layers (separated internally, never collapsed):
    corpus   — corpus.json / DOI registry / version chains
    metrics  — uptake-metrics-full.json / ratios / deltas / signals
    validate — schema checks / duplicate DOIs / supersession integrity
    visual   — topology / domain view / uptake overlays
    export   — CSV / JSON / static report

Doctrine rail (permanent):
    Uptake metrics = audience behaviour only.
    Corpus truth lives in corpus.json.
    This app renders both layers but never conflates them.
"""

import streamlit as st
import json
import re
import time
import threading
import logging
import io
import csv
from datetime import date
from pathlib import Path
from collections import Counter
from copy import deepcopy

# ── Optional imports with graceful degradation ────────────────────────────────
try:
    import pandas as pd
    PANDAS = True
except ImportError:
    PANDAS = False
    st.warning("pandas not installed — table views limited. Run: pip install pandas")

try:
    import plotly.express as px
    import plotly.graph_objects as go
    PLOTLY = True
except ImportError:
    PLOTLY = False

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    REQUESTS = True
except ImportError:
    REQUESTS = False

try:
    from bs4 import BeautifulSoup
    BS4 = True
except ImportError:
    BS4 = False

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="SHRF Corpus Monitor",
    page_icon="⬡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Styles ────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
.doctrine-rail {
    background: #0a0e08;
    border-left: 3px solid #4ab870;
    padding: 8px 16px;
    font-size: 12px;
    color: #4a7a4a;
    font-style: italic;
    margin-bottom: 16px;
}
.layer-badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 2px;
    font-size: 11px;
    font-weight: 600;
    margin-right: 6px;
}
.metric-card {
    background: #0e1118;
    border: 1px solid #1e2530;
    border-radius: 4px;
    padding: 12px 16px;
    text-align: center;
}
.sig-STICKY         { color: #c8e040; }
.sig-HIGH_CONVERSION{ color: #4ab870; }
.sig-ENGAGED        { color: #4a9eff; }
.sig-RISING         { color: #e8a24a; }
.sig-BROWSING       { color: #4a5878; }
.sig-STALE          { color: #3a4050; }
.sig-LOW_DATA       { color: #3a4858; }
.sig-NO_METRICS     { color: #2a3040; }
</style>
""", unsafe_allow_html=True)

# ── Constants ─────────────────────────────────────────────────────────────────
DEFAULT_CORPUS  = "corpus.json"
DEFAULT_METRICS = "uptake-metrics-full.json"
ZENODO_API      = "https://zenodo.org/api/records/{id}"
ZENODO_PAGE     = "https://zenodo.org/records/{id}"
USER_AGENT      = "SHRF-corpus-monitor/0.6 (academic; non-commercial)"

SIG_COLORS = {
    "STICKY":          "#c8e040",
    "HIGH_CONVERSION": "#4ab870",
    "ENGAGED":         "#4a9eff",
    "RISING":          "#e8a24a",
    "BROWSING":        "#4a5878",
    "STALE":           "#3a4050",
    "LOW_DATA":        "#3a4858",
    "NO_METRICS":      "#2a3040",
}

SIG_PRIORITY = {s: i for i, s in enumerate(
    ["STICKY","HIGH_CONVERSION","ENGAGED","RISING","BROWSING","STALE","LOW_DATA","NO_METRICS"]
)}

DOMAIN_COLORS = {
    "PHYS":"#4a9eff","PHYS-ASTRO":"#7c8cff","FRAMEWORK":"#c8e040",
    "ECO-BIO":"#4ab870","METHOD":"#e8a24a","GOV-AI":"#c06cff",
    "MED":"#ff6f91","MED-BIO":"#ff9a6a","INFRA":"#60d0ff",
    "GEO-ECO":"#77d48f","INFO":"#72c6ff","META":"#b0b0b0",
    "ECO-CHEM":"#4bd0aa","ECO-INFRA":"#9ad66b","GEO":"#b98b5a",
    "MATH":"#f0cf5a","SOC":"#d0a0ff","PHYS-BIO":"#a8d0ff",
    "EDU":"#ffd166","PHYS-CHEM":"#91d5ff","ECO":"#88cc88",
    "FOUNDATION":"#ffffff",
}

# ── Session state initialisation ──────────────────────────────────────────────
DEFAULT_RESOLUTION = "resolution-register.json"

for key, default in [
    ("corpus", None), ("metrics", None), ("resolution", None),
    ("corpus_path", DEFAULT_CORPUS), ("metrics_path", DEFAULT_METRICS),
    ("resolution_path", DEFAULT_RESOLUTION),
    ("fetch_log", []), ("fetch_running", False), ("fetch_progress", 0),
    ("validation_results", None), ("resolution_edits", {}),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ═══════════════════════════════════════════════════════════════════
# UTILITY FUNCTIONS
# ═══════════════════════════════════════════════════════════════════

def load_json(path):
    p = Path(path)
    if not p.exists():
        return None, f"File not found: {path}"
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def save_json(data, path):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return None
    except Exception as e:
        return str(e)

def extract_id(doi):
    m = re.search(r'zenodo\.(\d+)$', doi)
    return m.group(1) if m else None

def classify_signal(views, downloads, prev_views, prev_downloads):
    if not views:
        return "NO_METRICS"
    ratio = downloads / views
    if views < 10:
        return "LOW_DATA"
    if prev_views and prev_views > 0:
        dv = views - prev_views
        dd = downloads - (prev_downloads or 0)
        if dv / prev_views > 0.20:
            return "RISING"
        if dv == 0 and dd == 0:
            return "STALE"
    if ratio >= 0.30: return "STICKY"
    if ratio >= 0.15: return "HIGH_CONVERSION"
    if ratio >= 0.05: return "ENGAGED"
    return "BROWSING"

def get_metrics_entries():
    m = st.session_state.metrics
    if not m:
        return []
    return m.get("entries", [])

def get_corpus_nodes():
    c = st.session_state.corpus
    if not c:
        return []
    return c.get("nodes", [])

def ratio_color(r):
    if r is None: return "#2a3040"
    if r >= 0.30: return "#c8e040"
    if r >= 0.15: return "#4ab870"
    if r >= 0.05: return "#4a9eff"
    return "#4a5878"

# ═══════════════════════════════════════════════════════════════════
# FETCH ENGINE (runs in background thread)
# ═══════════════════════════════════════════════════════════════════

def make_session():
    if not REQUESTS:
        return None
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    retry = Retry(total=3, backoff_factor=1.0,
                  status_forcelist=[429,500,502,503,504],
                  allowed_methods=["GET"])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s

def fetch_one_api(record_id, session):
    url = ZENODO_API.format(id=record_id)
    try:
        r = session.get(url, timeout=15)
        if r.status_code == 404: return None, None, "404_not_found"
        if r.status_code == 410: return None, None, "410_deleted"
        if r.status_code == 429: return None, None, "429_rate_limited"
        if r.status_code != 200: return None, None, f"http_{r.status_code}"
        data = r.json()
        stats = data.get("stats", {})
        if not stats:
            return None, None, "api_no_stats"
        av = stats.get("all_versions", {})
        v = av.get("unique_views")     or stats.get("unique_views")     or 0
        d = av.get("unique_downloads") or stats.get("unique_downloads") or 0
        tag = "api_ok_zeros" if (v == 0 and d == 0) else "api_ok"
        return int(v), int(d), tag
    except Exception as e:
        return None, None, f"api_{type(e).__name__}"

def fetch_one_html(record_id, session):
    if not BS4:
        return None, None, "bs4_unavailable"
    url = ZENODO_PAGE.format(id=record_id)
    try:
        r = session.get(url, timeout=15)
        if r.status_code != 200:
            return None, None, f"html_{r.status_code}"
        soup = BeautifulSoup(r.text, "lxml")
        v = d = None
        # Strategy: full-text pattern
        m = re.search(
            r'([\d,]+)\s+(?:Total\s+)?[Vv]iews?\D{0,30}([\d,]+)\s+(?:Total\s+)?[Dd]ownloads?',
            soup.get_text()
        )
        if m:
            v = int(m.group(1).replace(',', ''))
            d = int(m.group(2).replace(',', ''))
        if v is not None:
            return v, d, "html_ok"
        return None, None, "html_parse_failed"
    except Exception as e:
        return None, None, f"html_{type(e).__name__}"

def run_fetch(entries, delay, only_preferred, only_unretrieved,
              log_list, progress_ref):
    """Runs in a background thread. Updates entries in-place."""
    session = make_session()
    if not session:
        log_list.append({"doi": "—", "method": "requests_unavailable", "ok": False})
        return

    pool = [e for e in entries]
    if only_preferred:
        pool = [e for e in pool if e.get("status") != "superseded"]
    if only_unretrieved:
        pool = [e for e in pool if not e.get("retrieved")]

    today = date.today().isoformat()
    total = len(pool)

    for i, entry in enumerate(pool):
        doi = entry.get("doi", "")
        rid = extract_id(doi)
        progress_ref[0] = (i + 1) / max(total, 1)

        if not rid:
            log_list.append({"doi": doi, "method": "no_record_id", "ok": False})
            continue

        time.sleep(delay)
        v, d, method = fetch_one_api(rid, session)

        if v is None and method in ("api_no_stats", "api_ok_zeros"):
            time.sleep(delay * 0.5)
            v, d, method = fetch_one_html(rid, session)

        if v is not None:
            prev_v = entry.get("views", 0) if entry.get("retrieved") else None
            prev_d = entry.get("downloads", 0) if entry.get("retrieved") else None
            if entry.get("retrieved") and (v != prev_v or d != prev_d):
                entry["previous_views"]          = prev_v
                entry["previous_downloads"]      = prev_d
                entry["previous_retrieval_date"] = entry.get("retrieval_date")
            import datetime as _dt
            sig = classify_signal(v, d, entry.get("previous_views"),
                                  entry.get("previous_downloads"))
            entry.update({
                "views":               v,
                "downloads":           d,
                "retrieval_date":      today,
                "retrieval_timestamp": _dt.datetime.utcnow().isoformat() + "Z",
                "retrieval_method":    method,
                "retrieved":           True,
                "download_ratio":      round(d/v, 4) if v else 0.0,
                "signal_class":        sig,
                "engagement_class":    "LOW_DATA" if v < 10 else sig,
                "low_data_flag":       v < 10,
                "error_message":       None,
            })
            log_list.append({"doi": doi, "method": method, "ok": True,
                             "views": v, "downloads": d, "signal": sig})
        else:
            import datetime as _dt
            if not entry.get("retrieved"):
                entry["retrieval_method"]    = method
                entry["retrieval_timestamp"] = _dt.datetime.utcnow().isoformat() + "Z"
                entry["error_message"]       = method
                entry["retrieved"]           = False
            log_list.append({"doi": doi, "method": method, "ok": False})

    progress_ref[0] = 1.0

# ═══════════════════════════════════════════════════════════════════
# VALIDATION ENGINE
# ═══════════════════════════════════════════════════════════════════

ALLOWED_STATES      = {"VERIFIED","INFERRED","SPECULATIVE","ANALOGICAL","WITHDRAWN","UNKNOWN"}
ALLOWED_TIERS       = {"T0","T1","T2","T3"}
ALLOWED_CONFIDENCE  = {"CANONICAL","DERIVED-CANONICAL","USER-CONFIRMED","INFERRED","NEEDS-REVIEW"}
DOI_PATTERN         = re.compile(r'^10\.\d{4,}/zenodo\.\d+$')

def validate_corpus(corpus):
    errors, warnings = [], []
    if not corpus:
        return ["No corpus loaded"], []

    nodes   = corpus.get("nodes", [])
    edges   = corpus.get("edges", [])
    gaps    = corpus.get("gaps", [])
    overlaps= corpus.get("overlaps", [])

    node_ids  = {}
    node_dois = {}
    b12_nums  = {}

    for i, n in enumerate(nodes):
        loc = f"node[{i}] id={n.get('id','?')}"
        nid = n.get("id", "")
        doi = n.get("doi", "")

        if nid in node_ids:
            errors.append(f"Duplicate node id: '{nid}'")
        else:
            node_ids[nid] = i

        if doi in node_dois:
            errors.append(f"Duplicate DOI: '{doi}'")
        elif doi:
            node_dois[doi] = i

        if doi and not DOI_PATTERN.match(doi):
            errors.append(f"{loc}: DOI format invalid: '{doi}'")

        if n.get("state") not in ALLOWED_STATES:
            errors.append(f"{loc}: state '{n.get('state')}' not in allowed set")

        if n.get("tier") not in ALLOWED_TIERS:
            errors.append(f"{loc}: tier '{n.get('tier')}' not in allowed set")

        if n.get("confidence") not in ALLOWED_CONFIDENCE:
            errors.append(f"{loc}: confidence '{n.get('confidence')}' not in allowed set")

        if n.get("baseline12") is True:
            bnum = n.get("baseline12_node")
            if bnum is None:
                errors.append(f"{loc}: baseline12=true but baseline12_node missing")
            elif bnum in b12_nums:
                errors.append(f"{loc}: duplicate baseline12_node={bnum}")
            else:
                b12_nums[bnum] = i

        if n.get("preferred_cite") and "version_of" not in n:
            errors.append(f"{loc}: preferred_cite=true but version_of missing")

        if "version_of" in n:
            if n["version_of"] not in node_dois:
                warnings.append(f"{loc}: version_of '{n['version_of']}' not in corpus (may be external)")

    for i, e in enumerate(edges):
        src, tgt = e.get("source",""), e.get("target","")
        if src not in node_ids:
            errors.append(f"edge[{i}]: source '{src}' not in node ids")
        if tgt not in node_ids:
            errors.append(f"edge[{i}]: target '{tgt}' not in node ids")
        if src == tgt:
            errors.append(f"edge[{i}]: self-loop on '{src}'")

    for i, g in enumerate(gaps):
        if g.get("node") not in node_ids:
            errors.append(f"gap[{i}] '{g.get('id')}': node '{g.get('node')}' not found")

    for i, o in enumerate(overlaps):
        for nref in o.get("nodes", []):
            if nref not in node_ids:
                errors.append(f"overlap[{i}] '{o.get('id')}': node '{nref}' not found")

    return errors, warnings

def validate_metrics(metrics):
    errors, warnings = [], []
    if not metrics:
        return ["No metrics loaded"], []
    entries = metrics.get("entries", [])
    dois = [e.get("doi","") for e in entries]
    seen = {}
    for i, doi in enumerate(dois):
        if doi in seen:
            errors.append(f"Duplicate DOI in metrics: '{doi}'")
        else:
            seen[doi] = i
        if doi and not DOI_PATTERN.match(doi):
            errors.append(f"entries[{i}]: DOI format invalid: '{doi}'")
    # Check supersession chains
    doi_to_entry = {e.get("doi"):e for e in entries}
    for e in entries:
        sb = e.get("superseded_by")
        if sb and sb not in doi_to_entry:
            warnings.append(f"'{e.get('doi')}': superseded_by '{sb}' not in metrics")
    return errors, warnings

# ═══════════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("## ⬡ SHRF Corpus Monitor")
    st.markdown("**v0.7** — Local Control Room + Plugins")
    st.divider()

    # File loading
    st.markdown("### Files")

    col1, col2 = st.columns([3,1])
    with col1:
        corpus_path = st.text_input("corpus.json", value=st.session_state.corpus_path,
                                    label_visibility="collapsed",
                                    placeholder="corpus.json path")
    with col2:
        if st.button("Load", key="load_corpus"):
            data, err = load_json(corpus_path)
            if err:
                st.error(err)
            else:
                st.session_state.corpus = data
                st.session_state.corpus_path = corpus_path
                st.success(f"✓ {len(data.get('nodes',[]))} nodes")

    col1, col2 = st.columns([3,1])
    with col1:
        metrics_path = st.text_input("uptake-metrics.json",
                                     value=st.session_state.metrics_path,
                                     label_visibility="collapsed",
                                     placeholder="metrics JSON path")
    with col2:
        if st.button("Load", key="load_metrics"):
            data, err = load_json(metrics_path)
            if err:
                st.error(err)
            else:
                st.session_state.metrics = data
                st.session_state.metrics_path = metrics_path
                n = len(data.get("entries",[]))
                retr = sum(1 for e in data.get("entries",[]) if e.get("retrieved"))
                st.success(f"✓ {n} entries, {retr} retrieved")

    # Upload fallback
    st.markdown("**Or upload:**")
    up_corpus = st.file_uploader("corpus.json", type="json", key="up_corpus",
                                  label_visibility="collapsed")
    if up_corpus:
        try:
            data = json.load(up_corpus)
            st.session_state.corpus = data
            st.success(f"✓ corpus: {len(data.get('nodes',[]))} nodes")
        except Exception as e:
            st.error(str(e))

    up_metrics = st.file_uploader("metrics JSON", type="json", key="up_metrics",
                                   label_visibility="collapsed")
    if up_metrics:
        try:
            data = json.load(up_metrics)
            st.session_state.metrics = data
            n = len(data.get("entries",[]))
            st.success(f"✓ metrics: {n} entries")
        except Exception as e:
            st.error(str(e))

    up_resolution = st.file_uploader("resolution-register.json", type="json",
                                       key="up_res", label_visibility="collapsed")
    if up_resolution:
        try:
            data = json.load(up_resolution)
            st.session_state.resolution = data
            n = len(data.get("items",[]))
            st.success(f"✓ resolution: {n} items")
        except Exception as e:
            st.error(str(e))

    col1, col2 = st.columns([3,1])
    with col1:
        res_path = st.text_input("resolution-register.json",
                                  value=st.session_state.resolution_path,
                                  label_visibility="collapsed",
                                  placeholder="resolution-register.json path")
    with col2:
        if st.button("Load", key="load_res"):
            data, err = load_json(res_path)
            if err:
                st.error(err)
            else:
                st.session_state.resolution = data
                st.session_state.resolution_path = res_path
                st.success(f"✓ {len(data.get('items',[]))} items")

    st.divider()

    # Fetch controls
    st.markdown("### Fetch")
    fetch_delay      = st.slider("Delay (s)", 0.1, 2.0, 0.3, 0.1)
    only_preferred   = st.checkbox("Skip superseded", value=True)
    only_unretrieved = st.checkbox("Only unretrieved", value=False)

    if not REQUESTS:
        st.warning("requests not installed")
    else:
        if st.button("🔄 Fetch Zenodo Stats", type="primary",
                     disabled=st.session_state.fetch_running or
                              st.session_state.metrics is None):
            st.session_state.fetch_running   = True
            st.session_state.fetch_log       = []
            st.session_state.fetch_progress  = 0.0
            st.session_state["fetch_done_n"] = 0
            st.rerun()

    # FIX 3+4: chunked synchronous fetch — no background thread
    # Streamlit state only written from main thread. Progress is real per-chunk.
    if st.session_state.fetch_running and st.session_state.metrics is not None:
        import datetime as _dt
        _entries = get_metrics_entries()
        _pool = _entries[:]
        if only_preferred:
            _pool = [e for e in _pool if e.get("status") != "superseded"]
        if only_unretrieved:
            _pool = [e for e in _pool if not e.get("retrieved")]
        _total  = max(len(_pool), 1)
        _done   = st.session_state.get("fetch_done_n", 0)
        _CHUNK  = 8
        _end    = min(_done + _CHUNK, len(_pool))
        _today  = date.today().isoformat()
        _log    = st.session_state.fetch_log
        _sess   = make_session()
        _pb     = st.progress(_done/_total, text=f"Fetching… {_done}/{_total}")

        for _e in _pool[_done:_end]:
            _doi = _e.get("doi","")
            _rid = extract_id(_doi)
            time.sleep(fetch_delay)
            if not _rid:
                _log.append({"doi":_doi,"method":"no_record_id","ok":False})
                continue
            _v, _d, _method = fetch_one_api(_rid, _sess)
            if _v is None and _method in ("api_no_stats","api_ok_zeros"):
                time.sleep(fetch_delay * 0.5)
                _v, _d, _method = fetch_one_html(_rid, _sess)
            if _v is not None:
                _pv = _e.get("views",0)  if _e.get("retrieved") else None
                _pd = _e.get("downloads",0) if _e.get("retrieved") else None
                if _e.get("retrieved") and (_v != _pv or _d != _pd):
                    _e["previous_views"]          = _pv
                    _e["previous_downloads"]      = _pd
                    _e["previous_retrieval_date"] = _e.get("retrieval_date")
                _sig = classify_signal(_v, _d, _e.get("previous_views"),
                                       _e.get("previous_downloads"))
                _e.update({
                    "views":_v, "downloads":_d, "retrieval_date":_today,
                    "retrieval_timestamp":_dt.datetime.utcnow().isoformat()+"Z",
                    "retrieval_method":_method, "retrieved":True,
                    "download_ratio":round(_d/_v,4) if _v else 0.0,
                    "signal_class":_sig,
                    "engagement_class":"LOW_DATA" if _v<10 else _sig,
                    "low_data_flag":_v<10, "error_message":None,
                })
                _log.append({"doi":_doi,"method":_method,"ok":True,
                             "views":_v,"downloads":_d})
            else:
                if not _e.get("retrieved"):
                    _e["retrieval_method"]    = _method
                    _e["retrieval_timestamp"] = _dt.datetime.utcnow().isoformat()+"Z"
                    _e["error_message"]       = _method
                _log.append({"doi":_doi,"method":_method,"ok":False})

        st.session_state["fetch_done_n"] = _end
        _pb.progress(_end/_total, text=f"Fetching… {_end}/{_total}")

        if _end >= len(_pool):
            st.session_state.fetch_running   = False
            st.session_state.fetch_progress  = 1.0
            st.session_state["fetch_done_n"] = 0
            _ok   = sum(1 for l in _log if l.get("ok"))
            _fail = sum(1 for l in _log if not l.get("ok"))
            st.success(f"✓ Complete — {_ok} ok · {_fail} failed")
        else:
            time.sleep(0.05)
            st.rerun()

    st.divider()
    st.markdown("""
<div style='font-size:10px;color:#3a5a3a;font-style:italic;line-height:1.6;'>
Doctrine rail:<br>
Uptake = audience behaviour.<br>
Corpus truth is separate.<br>
This app renders both layers;<br>
it never conflates them.
</div>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════
# MAIN TABS
# ═══════════════════════════════════════════════════════════════════

tabs = st.tabs([
    "📊 Dashboard",
    "🗺 Topology",
    "✓ Validate",
    "⚡ Fetch Log",
    "🔗 Version Chains",
    "📤 Export",
    "🔲 Resolution",
])

# ───────────────────────────────────────────────────────────────────
# TAB 1 — DASHBOARD
# ───────────────────────────────────────────────────────────────────
with tabs[0]:
    st.markdown('<div class="doctrine-rail">Uptake metrics = audience behaviour only · '
                'Corpus truth lives in corpus.json · These layers are separate</div>',
                unsafe_allow_html=True)

    entries = get_metrics_entries()

    if not entries:
        st.info("Load uptake-metrics-full.json using the sidebar to populate the dashboard.")
    else:
        retrieved = [e for e in entries if e.get("retrieved")]
        total_v   = sum(e.get("views",0) for e in retrieved)
        total_d   = sum(e.get("downloads",0) for e in retrieved)
        c_ratio   = total_d / total_v if total_v else None
        signals   = Counter(e.get("signal_class","NO_METRICS") for e in retrieved)
        sticky    = signals.get("STICKY",0) + signals.get("RISING",0)

        # Summary metrics row
        c1,c2,c3,c4,c5,c6 = st.columns(6)
        c1.metric("Total DOIs",    len(entries))
        c2.metric("Retrieved",     len(retrieved), delta=f"{len(entries)-len(retrieved)} pending")
        c3.metric("Total Views",   f"{total_v:,}")
        c4.metric("Total DLs",     f"{total_d:,}")
        c5.metric("Corpus Ratio",  f"{c_ratio:.3f}" if c_ratio else "—")
        c6.metric("Sticky/Rising", sticky)

        st.divider()

        col_left, col_right = st.columns([1, 1])

        with col_left:
            st.markdown("#### Signal Distribution")
            if PLOTLY and retrieved:
                order = ["STICKY","HIGH_CONVERSION","ENGAGED","RISING",
                         "BROWSING","STALE","LOW_DATA","NO_METRICS"]
                vals   = [signals.get(s,0) for s in order]
                colors = [SIG_COLORS.get(s,"#333") for s in order]
                fig = go.Figure(go.Bar(
                    x=vals, y=order, orientation='h',
                    marker_color=colors,
                    text=[f"{v}  ({100*v//max(len(entries),1)}%)" for v in vals],
                    textposition='outside',
                ))
                fig.update_layout(
                    height=320, margin=dict(l=0,r=40,t=10,b=10),
                    paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                    font_color='#9aa4b5', xaxis=dict(showgrid=False),
                    yaxis=dict(autorange="reversed")
                )
                st.plotly_chart(fig, use_container_width=True)

        with col_right:
            st.markdown("#### Top 15 by Priority")
            sorted_entries = sorted(
                entries,
                key=lambda e: (SIG_PRIORITY.get(e.get("signal_class","NO_METRICS"),8),
                               -e.get("views",0))
            )
            for e in sorted_entries[:15]:
                sig   = e.get("signal_class","NO_METRICS")
                color = SIG_COLORS.get(sig, "#333")
                title = (e.get("title","") or "").replace('[preferred]','').strip()[:50]
                ratio = e.get("download_ratio", 0) or 0
                st.markdown(
                    f'<div style="border:1px solid #1e2530;padding:5px 10px;margin-bottom:4px;'
                    f'font-size:11px;">'
                    f'<span style="color:{color};font-weight:600">[{sig}]</span> '
                    f'{title} '
                    f'<span style="color:#3a5060;float:right">'
                    f'v={e.get("views",0):,} · r={ratio:.3f}</span></div>',
                    unsafe_allow_html=True
                )

        # ── Plugin 5: Conceptual importance ≠ uptake warning ────────────────
        with st.expander("⚠ Interpretation guard — read before acting on metrics"):
            st.markdown("""
**Three separate dimensions — do not conflate:**

| Dimension | Source | Meaning |
|-----------|--------|---------|
| **Epistemic / corpus importance** | corpus.json · branch state · TRIDENT gates | Scientific weight within the framework |
| **Public uptake metrics** | Zenodo views / downloads / ratio | Audience behaviour only |
| **Resolution priority** | resolution-register.json | What is blocked or needs action |

**A high-traffic record is not more structurally important than a low-traffic anchor.**
USDOP and IWC are foundational regardless of view count.
A STICKY signal on a peripheral note does not promote it to T0.

**A low-traffic record is not a failure.**
Specialised technical notes in a niche domain may never reach broad audiences.
That is expected, not broken.

**Signals to act on:** RISING (investigate cause) · STALE (confirm still relevant) · HIGH_CONVERSION (audience is reading closely)

**Signals that require judgment before acting:** view count alone · ratio on LOW_DATA records · domain-level comparisons
            """)

        st.divider()
        st.markdown("#### Domain Breakdown")

        if PLOTLY and PANDAS:
            domain_data = {}
            for e in entries:
                d = e.get("domain","UNKNOWN")
                if d not in domain_data:
                    domain_data[d] = {"domain":d,"count":0,"views":0,"downloads":0}
                domain_data[d]["count"]     += 1
                domain_data[d]["views"]     += e.get("views",0)
                domain_data[d]["downloads"] += e.get("downloads",0)

            df = pd.DataFrame(domain_data.values()).sort_values("views", ascending=False)
            df["ratio"] = df.apply(
                lambda r: r["downloads"]/r["views"] if r["views"] > 0 else 0, axis=1
            )
            df["color"] = df["domain"].map(lambda d: DOMAIN_COLORS.get(d,"#666"))

            col_a, col_b = st.columns(2)
            with col_a:
                fig = go.Figure(go.Bar(
                    x=df["domain"], y=df["views"],
                    marker_color=df["color"].tolist(),
                    hovertext=df.apply(
                        lambda r: f"{r['domain']}: {r['count']} DOIs, {r['views']} views, ratio={r['ratio']:.3f}",
                        axis=1
                    ),
                ))
                fig.update_layout(
                    title="Views by Domain", height=300,
                    margin=dict(l=0,r=0,t=30,b=60),
                    paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                    font_color='#9aa4b5', xaxis_tickangle=-45,
                    yaxis=dict(showgrid=False)
                )
                st.plotly_chart(fig, use_container_width=True)

            with col_b:
                fig2 = go.Figure(go.Scatter(
                    x=df["views"], y=df["ratio"],
                    mode="markers+text",
                    text=df["domain"],
                    textposition="top center",
                    marker=dict(
                        size=df["count"].apply(lambda c: max(8, min(30, c*2))),
                        color=df["color"].tolist(),
                        opacity=0.8
                    ),
                ))
                fig2.update_layout(
                    title="Views vs Ratio (bubble = record count)",
                    height=300, margin=dict(l=0,r=0,t=30,b=10),
                    paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                    font_color='#9aa4b5',
                    xaxis_title="Views", yaxis_title="D/V Ratio",
                )
                fig2.add_hline(y=0.15, line_dash="dot", line_color="#4ab870",
                               annotation_text="HIGH_CONVERSION threshold")
                fig2.add_hline(y=0.30, line_dash="dot", line_color="#c8e040",
                               annotation_text="STICKY threshold")
                st.plotly_chart(fig2, use_container_width=True)

        # Full sortable table
        st.markdown("#### Full Metrics Table")
        if PANDAS and entries:
            df_full = pd.DataFrame([{
                "Domain":    e.get("domain","?"),
                "Short":     (e.get("title","") or "")[:40],
                "DOI":       e.get("doi",""),
                "Views":     e.get("views",0),
                "Downloads": e.get("downloads",0),
                "Ratio":     e.get("download_ratio") or 0,
                "ΔViews":    (e.get("views",0)-(e.get("previous_views") or e.get("views",0)))
                              if e.get("previous_views") is not None else 0,
                "Signal":    e.get("signal_class","NO_METRICS"),
                "Engagement": e.get("engagement_class", e.get("signal_class","NO_METRICS")),
                "Low Data":  "⚠" if e.get("low_data_flag") else "",
                "Status":    e.get("status","current"),
                "Retrieved": e.get("retrieval_date","—"),
            } for e in entries])

            domain_filter = st.selectbox(
                "Filter by domain",
                ["ALL"] + sorted(df_full["Domain"].unique().tolist())
            )
            if domain_filter != "ALL":
                df_full = df_full[df_full["Domain"] == domain_filter]

            st.dataframe(
                df_full.sort_values("Views", ascending=False),
                use_container_width=True,
                height=400,
            )

# ───────────────────────────────────────────────────────────────────
# TAB 2 — TOPOLOGY
# ───────────────────────────────────────────────────────────────────
with tabs[1]:
    st.markdown("#### Corpus Topology")
    st.markdown('<div class="doctrine-rail">Visual topology is a projection layer only. '
                'Node position encodes domain/tier, not epistemic weight.</div>',
                unsafe_allow_html=True)

    entries_map = {e.get("doi",""):e for e in get_metrics_entries()}
    nodes       = get_corpus_nodes()

    if not nodes and not get_metrics_entries():
        st.info("Load corpus.json or uptake-metrics-full.json to render topology.")
    else:
        # Use metrics entries if no corpus nodes (metrics has domain/angle hints)
        source = nodes if nodes else []

        # If we have metrics entries, build topology from them
        met_entries = get_metrics_entries()

        if PLOTLY and met_entries:
            import math

            # FIX 6: define overlay controls BEFORE the render loop so they control output
            ov_col1, ov_col2, ov_col3 = st.columns(3)
            show_gaps   = ov_col1.checkbox("Show gap halos", value=False)
            show_size   = ov_col2.checkbox("Node size = views", value=True)
            show_labels = ov_col3.checkbox("Show labels", value=False)

            # Assign positions by domain sector (radial layout)
            domain_list = list(dict.fromkeys(e.get("domain","?") for e in met_entries))
            n_domains   = len(domain_list)
            domain_idx  = {d: i for i, d in enumerate(domain_list)}

            MAX_R = 400
            cx, cy = 0, 0

            node_x, node_y, node_text, node_color = [], [], [], []
            node_size, node_symbol, node_label = [], [], []

            for e in met_entries:
                d    = e.get("domain","?")
                idx  = domain_idx[d]
                # Spread within sector
                sector_angle    = 2 * math.pi * idx / n_domains
                jitter_angle    = sector_angle + (hash(e["doi"]) % 100 - 50) * 0.003
                # FIX 7: domain → tier radius (domain is not tier)
                _DTIER = {
                    "FOUNDATION":0.12,"METHOD":0.20,"FRAMEWORK":0.22,"META":0.25,
                    "PHYS":0.55,"PHYS-ASTRO":0.62,"PHYS-BIO":0.60,"PHYS-CHEM":0.60,
                    "MATH":0.58,"ECO-BIO":0.65,"ECO-CHEM":0.65,"ECO-INFRA":0.68,
                    "ECO":0.65,"GEO-ECO":0.65,"GEO":0.60,"MED":0.65,"MED-BIO":0.68,
                    "GOV-AI":0.70,"INFO":0.68,"INFRA":0.72,"EDU":0.70,"SOC":0.70,
                }
                tier_r = _DTIER.get(e.get("domain","?"), 0.62)
                r = tier_r * MAX_R

                x = cx + r * math.cos(jitter_angle)
                y = cy + r * math.sin(jitter_angle)

                v      = e.get("views", 0)
                ratio  = e.get("download_ratio", 0) or 0
                signal = e.get("signal_class","NO_METRICS")
                status = e.get("status","current")

                node_x.append(x)
                node_y.append(y)
                node_color.append(DOMAIN_COLORS.get(d, "#666"))
                # FIX 6: show_size wired
                if show_size and v > 0:
                    node_size.append(max(5, min(24, 5 + v * 0.06)))
                else:
                    node_size.append(6)

                sym = "circle"
                if status == "preferred-cite": sym = "hexagon"
                if status == "superseded":     sym = "x"
                node_symbol.append(sym)
                # collect short domain label for show_labels overlay
                node_label.append((e.get("domain","?")[:5]).upper())

                title_short = (e.get("title","") or "")[:55]
                node_text.append(
                    f"{title_short}<br>{e['doi']}<br>"
                    f"Domain: {d} | Signal: {signal}<br>"
                    f"Views: {v} | DLs: {e.get('downloads',0)} | Ratio: {ratio:.3f}<br>"
                    f"<span style='color:#5a6070;font-size:10px'>"
                    f"Position = domain sector, not importance</span>"
                )

            fig = go.Figure()

            # Rings
            for frac, dash in [(0.18,"dot"),(0.45,"dash"),(0.72,"dot"),(0.95,"dash")]:
                theta = [i*0.05 for i in range(130)]
                rx = [MAX_R*frac*math.cos(t) for t in theta]
                ry = [MAX_R*frac*math.sin(t) for t in theta]
                fig.add_trace(go.Scatter(
                    x=rx, y=ry, mode="lines",
                    line=dict(color="#1e2530", width=0.5, dash=dash),
                    hoverinfo="skip", showlegend=False
                ))

            # Nodes
            fig.add_trace(go.Scatter(
                x=node_x, y=node_y,
                mode="markers",
                marker=dict(
                    color=node_color,
                    size=node_size,
                    symbol=node_symbol,
                    opacity=0.8,
                    line=dict(width=0.5, color="#1e2530")
                ),
                text=node_text,
                hovertemplate="%{text}<extra></extra>",
                showlegend=False
            ))

            # Domain labels
            for d, idx in domain_idx.items():
                angle  = 2 * math.pi * idx / n_domains
                lx = (MAX_R * 1.08) * math.cos(angle)
                ly = (MAX_R * 1.08) * math.sin(angle)
                count = sum(1 for e in met_entries if e.get("domain") == d)
                fig.add_annotation(
                    x=lx, y=ly,
                    text=f"{d} ({count})",
                    font=dict(size=10, color=DOMAIN_COLORS.get(d,"#666")),
                    showarrow=False
                )

            # FIX 6: gap halos — rings around unresolved/unretrieved nodes
            if show_gaps:
                _gap_dois = {e.get("doi","") for e in met_entries if not e.get("retrieved")}
                _res = st.session_state.get("resolution")
                if _res:
                    for _item in _res.get("items",[]):
                        if _item.get("status","").startswith("UNRESOLVED"):
                            _gap_dois.add(_item.get("doi",""))
                _gx, _gy, _gt = [], [], []
                for _e, _x, _y in zip(met_entries, node_x, node_y):
                    if _e.get("doi","") in _gap_dois:
                        _gx.append(_x); _gy.append(_y)
                        _gt.append((_e.get("title","") or "")[:40])
                if _gx:
                    fig.add_trace(go.Scatter(
                        x=_gx, y=_gy, mode="markers",
                        marker=dict(size=20, color="rgba(0,0,0,0)",
                                    line=dict(color="#ff9a3c", width=1.5)),
                        text=_gt, hovertemplate="%{text}<extra>gap/unretrieved</extra>",
                        showlegend=False,
                    ))

            # FIX 6: domain labels overlay
            if show_labels:
                fig.add_trace(go.Scatter(
                    x=node_x, y=node_y, mode="text",
                    text=node_label,
                    textfont=dict(size=7, color="#5a6878"),
                    hoverinfo="skip", showlegend=False,
                ))

            # ── Plugin 7: Topology navigation controls ────────────────────────
            fig.update_layout(
                height=650,
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(7,9,13,1)',
                font_color='#9aa4b5',
                xaxis=dict(showgrid=False, zeroline=False, showticklabels=False,
                           range=[-MAX_R*1.25, MAX_R*1.25]),
                yaxis=dict(showgrid=False, zeroline=False, showticklabels=False,
                           range=[-MAX_R*1.25, MAX_R*1.25], scaleanchor="x"),
                margin=dict(l=0,r=0,t=10,b=10),
                hoverlabel=dict(bgcolor="#0e1118", font_size=11),
                # Navigation: pan as default drag; zoom controls in modebar
                dragmode="pan",
                modebar=dict(
                    add=["zoomIn2d", "zoomOut2d", "resetScale2d", "pan2d"]
                ),
            )

            # Guardrail note — navigation only
            st.caption(
                "Plugin 7 — Topology navigation: scroll to zoom · drag to pan · "
                "double-click to reset. "
                "Zoom changes visibility only — not priority, signal class, or corpus state."
            )

            st.plotly_chart(
                fig,
                use_container_width=True,
                config={
                    "scrollZoom":             True,
                    "displayModeBar":         True,
                    "displaylogo":            False,
                    "modeBarButtonsToAdd":    ["zoomIn2d", "zoomOut2d",
                                               "resetScale2d"],
                    "modeBarButtonsToRemove": ["toImage"],
                }
            )

            # Shape legend
            st.markdown(
                "● current &nbsp;&nbsp; ⬡ preferred-cite &nbsp;&nbsp; ✕ superseded &nbsp;&nbsp; "
                "Size = view count (when data available)",
                unsafe_allow_html=False
            )

# ───────────────────────────────────────────────────────────────────
# TAB 3 — VALIDATE
# ───────────────────────────────────────────────────────────────────
with tabs[2]:
    st.markdown("#### Validation Layer")
    st.markdown("Runs schema, referential integrity, and supersession checks "
                "against loaded files. No writes.")

    col_v1, col_v2 = st.columns(2)

    with col_v1:
        st.markdown("**Corpus (corpus.json)**")
        if st.button("Validate Corpus"):
            errors, warnings = validate_corpus(st.session_state.corpus)
            st.session_state.validation_results = {
                "corpus_errors": errors, "corpus_warnings": warnings
            }

        vr = st.session_state.validation_results or {}
        if "corpus_errors" in vr:
            errs  = vr["corpus_errors"]
            warns = vr["corpus_warnings"]
            if not errs:
                st.success(f"✓ PASS — 0 errors, {len(warns)} warnings")
            else:
                st.error(f"✗ FAIL — {len(errs)} errors, {len(warns)} warnings")
            for e in errs[:20]:
                st.error(e, icon="✗")
            for w in warns[:10]:
                st.warning(w, icon="⚠")

    with col_v2:
        st.markdown("**Metrics (uptake-metrics-full.json)**")
        if st.button("Validate Metrics"):
            errors, warnings = validate_metrics(st.session_state.metrics)
            vr = st.session_state.validation_results or {}
            vr["metrics_errors"]   = errors
            vr["metrics_warnings"] = warnings
            st.session_state.validation_results = vr

        vr = st.session_state.validation_results or {}
        if "metrics_errors" in vr:
            errs  = vr["metrics_errors"]
            warns = vr["metrics_warnings"]
            if not errs:
                st.success(f"✓ PASS — 0 errors, {len(warns)} warnings")
            else:
                st.error(f"✗ FAIL — {len(errs)} errors, {len(warns)} warnings")
            for e in errs[:20]:
                st.error(e, icon="✗")
            for w in warns[:10]:
                st.warning(w, icon="⚠")

    st.divider()
    st.markdown("**Cross-layer consistency**")
    if st.button("Check Corpus ↔ Metrics alignment"):
        corpus_dois  = {n.get("doi") for n in get_corpus_nodes() if n.get("doi")}
        metrics_dois = {e.get("doi") for e in get_metrics_entries() if e.get("doi")}
        in_corpus_not_metrics = corpus_dois - metrics_dois
        in_metrics_not_corpus = metrics_dois - corpus_dois
        if not corpus_dois and not metrics_dois:
            st.info("Load both files first.")
        else:
            st.info(f"Corpus DOIs: {len(corpus_dois)} · Metrics DOIs: {len(metrics_dois)}")
            if in_corpus_not_metrics:
                st.warning(f"{len(in_corpus_not_metrics)} corpus DOIs not in metrics:")
                for d in sorted(in_corpus_not_metrics)[:10]:
                    st.code(d)
            if in_metrics_not_corpus:
                st.info(f"{len(in_metrics_not_corpus)} metrics DOIs not in corpus "
                        "(expected — metrics covers full 176, corpus covers canonical nodes).")
            if not in_corpus_not_metrics:
                st.success("✓ All corpus DOIs present in metrics file.")

# ───────────────────────────────────────────────────────────────────
# TAB 4 — FETCH LOG
# ───────────────────────────────────────────────────────────────────
with tabs[3]:
    st.markdown("#### Fetch Log")

    log = st.session_state.fetch_log
    if not log:
        st.info("No fetch run yet. Use the sidebar Fetch button to start.")
    else:
        ok_count   = sum(1 for l in log if l.get("ok"))
        fail_count = sum(1 for l in log if not l.get("ok"))
        st.metric("Fetched OK", ok_count)
        col_a, col_b = st.columns(2)
        col_a.metric("Succeeded", ok_count)
        col_b.metric("Failed",    fail_count,
                     delta=f"{fail_count} to retry" if fail_count else None,
                     delta_color="inverse")

        if fail_count:
            st.markdown("**Failures — re-run with --only-unretrieved to retry:**")
            for l in [x for x in log if not x.get("ok")][:30]:
                st.code(f"{l['doi']}  [{l['method']}]")

        st.markdown("**Method distribution:**")
        methods = Counter(l["method"] for l in log)
        if PANDAS:
            st.dataframe(
                pd.DataFrame(methods.most_common(), columns=["Method","Count"]),
                use_container_width=True, height=200
            )

        if st.button("Save metrics after fetch"):
            err = save_json(st.session_state.metrics, st.session_state.metrics_path)
            if err:
                st.error(f"Save failed: {err}")
            else:
                st.success(f"✓ Saved to {st.session_state.metrics_path}")

# ───────────────────────────────────────────────────────────────────
# TAB 5 — VERSION CHAINS
# ───────────────────────────────────────────────────────────────────
with tabs[4]:
    st.markdown("#### Version Chains")
    st.markdown("Superseded → preferred-cite relationships. "
                "Preferred cites are canonical; earlier versions are tracked but not primary.")

    entries = get_metrics_entries()
    if not entries:
        st.info("Load metrics file to see version chains.")
    else:
        doi_map = {e["doi"]: e for e in entries if e.get("doi")}

        chains = {}
        for e in entries:
            sb = e.get("superseded_by")
            if sb:
                if sb not in chains:
                    chains[sb] = []
                chains[sb].append(e)

        if not chains:
            st.info("No version chains found (no superseded_by fields set).")
        else:
            for preferred_doi, older_versions in chains.items():
                preferred = doi_map.get(preferred_doi, {})
                title = (preferred.get("title","") or preferred_doi)[:60]
                title = title.replace('[preferred]','').replace('[v2 preferred]','').strip()

                with st.expander(f"⬡  {title}"):
                    # Preferred entry
                    pv = preferred.get("views",0)
                    pd_ = preferred.get("downloads",0)
                    pr = preferred.get("download_ratio",0) or 0
                    ps = preferred.get("signal_class","NO_METRICS")
                    st.markdown(
                        f"**Preferred cite:** `{preferred_doi}`  \n"
                        f"Signal: **{ps}** · Views: {pv:,} · DLs: {pd_:,} · Ratio: {pr:.3f}"
                    )

                    # Older versions
                    for old in older_versions:
                        ov = old.get("views",0)
                        od = old.get("downloads",0)
                        or_ = old.get("download_ratio",0) or 0
                        delta_v = pv - ov
                        st.markdown(
                            f"↳ superseded: `{old['doi']}`  \n"
                            f"Views: {ov:,} · DLs: {od:,} · "
                            f"Preferred cite has {delta_v:+,} more views"
                        )

# ───────────────────────────────────────────────────────────────────
# TAB 6 — EXPORT
# ───────────────────────────────────────────────────────────────────
with tabs[5]:
    st.markdown("#### Export Layer")
    st.markdown("All exports are read-only projections. They do not modify corpus or metrics files.")

    entries = get_metrics_entries()

    col_e1, col_e2, col_e3 = st.columns(3)

    with col_e1:
        st.markdown("**Metrics CSV**")
        if entries and PANDAS:
            df_exp = pd.DataFrame([{
                "doi":           e.get("doi",""),
                "title":         (e.get("title","") or "")[:80],
                "domain":        e.get("domain",""),
                "status":        e.get("status",""),
                "views":         e.get("views",0),
                "downloads":     e.get("downloads",0),
                "download_ratio":e.get("download_ratio") or 0,
                "signal_class":  e.get("signal_class","NO_METRICS"),
                "delta_views":   (e.get("views",0)-(e.get("previous_views") or 0))
                                  if e.get("previous_views") is not None else "",
                "retrieval_date":e.get("retrieval_date",""),
            } for e in entries])
            csv_buf = io.StringIO()
            df_exp.to_csv(csv_buf, index=False)
            st.download_button(
                "Download metrics.csv",
                data=csv_buf.getvalue(),
                file_name=f"shrf_metrics_{date.today().isoformat()}.csv",
                mime="text/csv"
            )
        else:
            st.info("Load metrics to export CSV.")

    with col_e2:
        st.markdown("**Updated metrics JSON**")
        if st.session_state.metrics:
            st.download_button(
                "Download uptake-metrics.json",
                data=json.dumps(st.session_state.metrics, indent=2, ensure_ascii=False),
                file_name=f"uptake-metrics-{date.today().isoformat()}.json",
                mime="application/json"
            )
        else:
            st.info("Load metrics first.")

    with col_e3:
        st.markdown("**Priority report (JSON)**")
        if entries:
            sorted_e = sorted(
                [e for e in entries if e.get("retrieved")],
                key=lambda e: (SIG_PRIORITY.get(e.get("signal_class","NO_METRICS"),8),
                               -e.get("views",0))
            )
            report = {
                "generated":  date.today().isoformat(),
                "invariant":  "Uptake = audience behaviour. Not scientific validity.",
                "top_records": [{
                    "doi":    e["doi"],
                    "title":  (e.get("title","") or "")[:70],
                    "signal": e.get("signal_class"),
                    "views":  e.get("views",0),
                    "ratio":  e.get("download_ratio") or 0,
                } for e in sorted_e[:30]]
            }
            st.download_button(
                "Download priority_report.json",
                data=json.dumps(report, indent=2),
                file_name=f"priority_report_{date.today().isoformat()}.json",
                mime="application/json"
            )
        else:
            st.info("Load metrics first.")

    st.divider()
    st.markdown("**Failing DOIs (for retry)**")
    if st.session_state.fetch_log:
        failed = [l for l in st.session_state.fetch_log if not l.get("ok")]
        if failed:
            lines = "\n".join(l["doi"] for l in failed)
            st.download_button(
                f"Download {len(failed)} failed DOIs (.txt)",
                data=lines,
                file_name="fetch_failures.txt",
                mime="text/plain"
            )
        else:
            st.success("No failures in last fetch run.")
    else:
        st.info("Run a fetch first to see failures.")


# ───────────────────────────────────────────────────────────────────
# TAB 7 — RESOLUTION REGISTER
# ───────────────────────────────────────────────────────────────────
STATUS_COLORS = {
    "RESOLVED":                   "#4ab870",
    "AUTO_FIXABLE":               "#c8e040",
    "MANUAL_INPUT_REQUIRED":      "#4a9eff",
    "UNRESOLVED_DATA_ACCESS":     "#e8a24a",
    "UNRESOLVED_METHOD":          "#ff9a6a",
    "UNRESOLVED_VALIDATION":      "#7ecfcf",
    "UNRESOLVED_EXTERNAL_REVIEW": "#9b6fd4",
    "BACKBURNER":                 "#4a5060",
}

STATUS_ORDER = [
    "AUTO_FIXABLE", "MANUAL_INPUT_REQUIRED",
    "UNRESOLVED_DATA_ACCESS", "UNRESOLVED_METHOD",
    "UNRESOLVED_VALIDATION", "UNRESOLVED_EXTERNAL_REVIEW",
    "BACKBURNER", "RESOLVED",
]

with tabs[6]:
    st.markdown("#### Resolution Register")
    st.markdown(
        '<div class="doctrine-rail">'
        'Unresolved is a valid state, not a weakness. '
        'Auto-complete metadata only; never auto-complete evidence.</div>',
        unsafe_allow_html=True
    )

    reg = st.session_state.resolution
    entries_m = get_metrics_entries()
    fetch_log = st.session_state.fetch_log

    # ── Auto-detect resolvable items from live state ──────────────────────
    auto_items = []

    # A: Unretrieved metrics records
    unretrieved = [e for e in entries_m if not e.get("retrieved")]
    if unretrieved:
        auto_items.append({
            "id": "AUTO-001",
            "title": f"Zenodo metrics not yet fetched ({len(unretrieved)} records)",
            "status": "AUTO_FIXABLE",
            "blocked_by": "fetch_zenodo_metrics.py not run or incomplete",
            "next_action": "Use sidebar Fetch button or run fetch_zenodo_metrics.py --only-unretrieved",
            "auto_resolvable": True,
            "count": len(unretrieved),
            "source": "auto-detected",
        })

    # B: Stale retrievals (signal=STALE)
    stale = [e for e in entries_m if e.get("signal_class") == "STALE"]
    if stale:
        auto_items.append({
            "id": "AUTO-002",
            "title": f"Stale records — no change since last retrieval ({len(stale)} records)",
            "status": "AUTO_FIXABLE",
            "blocked_by": "Metrics not refreshed",
            "next_action": "Re-run fetch to confirm stale status or detect new activity",
            "auto_resolvable": True,
            "count": len(stale),
            "source": "auto-detected",
        })

    # C: Failed fetches from last run
    failed_fetches = [l for l in fetch_log if not l.get("ok")]
    if failed_fetches:
        auto_items.append({
            "id": "AUTO-003",
            "title": f"Failed fetch records ({len(failed_fetches)} from last run)",
            "status": "AUTO_FIXABLE",
            "blocked_by": "API timeout, rate limit, or parse failure",
            "next_action": "Re-run fetch with --only-unretrieved flag",
            "auto_resolvable": True,
            "count": len(failed_fetches),
            "source": "auto-detected",
        })

    # D: Corpus loaded — check for superseded nodes without preferred-cite
    corpus = st.session_state.corpus
    if corpus:
        nodes = corpus.get("nodes", [])
        orphan_superseded = [
            n for n in nodes
            if n.get("status") == "superseded" and not n.get("version_of")
        ]
        if orphan_superseded:
            auto_items.append({
                "id": "AUTO-004",
                "title": f"Superseded nodes missing version_of field ({len(orphan_superseded)})",
                "status": "AUTO_FIXABLE",
                "blocked_by": "version_of field not set",
                "next_action": "Add version_of DOI to each superseded corpus node",
                "auto_resolvable": True,
                "count": len(orphan_superseded),
                "source": "auto-detected",
            })

    # ── Summary row ──────────────────────────────────────────────────────
    reg_items = (reg.get("items", []) if reg else []) + auto_items
    total     = len(reg_items)
    resolved  = sum(1 for i in reg_items if i.get("status") == "RESOLVED")
    auto_fix  = sum(1 for i in reg_items if i.get("status") == "AUTO_FIXABLE"
                    or i.get("auto_resolvable"))
    manual    = sum(1 for i in reg_items
                    if i.get("status") == "MANUAL_INPUT_REQUIRED")
    blocked   = sum(1 for i in reg_items
                    if i.get("status","").startswith("UNRESOLVED"))

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total items",  total)
    c2.metric("Resolved",     resolved,   delta=f"{total-resolved} open" if total else None)
    c3.metric("Auto-fixable", auto_fix,   delta="run script" if auto_fix else None)
    c4.metric("Manual input", manual)
    c5.metric("Blocked",      blocked)

    st.divider()

    # ── Filters ──────────────────────────────────────────────────────────
    col_f1, col_f2 = st.columns([2, 1])
    with col_f1:
        status_filter = st.multiselect(
            "Filter by status",
            options=STATUS_ORDER,
            default=[s for s in STATUS_ORDER if s != "RESOLVED"],
        )
    with col_f2:
        show_auto = st.checkbox("Show auto-detected", value=True)

    filtered = [
        i for i in reg_items
        if (not status_filter or i.get("status") in status_filter)
        and (show_auto or i.get("source") != "auto-detected")
    ]

    # ── Item cards ───────────────────────────────────────────────────────
    st.markdown(f"**{len(filtered)} items** (filtered from {total})")

    for item in filtered:
        status     = item.get("status", "UNKNOWN")
        color      = STATUS_COLORS.get(status, "#666")
        item_id    = item.get("id", "?")
        title      = item.get("title", "")
        doi        = item.get("doi", "")
        auto       = item.get("auto_resolvable", False)
        source     = item.get("source", "register")
        confidence = item.get("confidence", "")
        count      = item.get("count")

        label = f"[{status}] {item_id} — {title[:65]}"
        if count:
            label += f" ({count})"

        with st.expander(label):
            col_s, col_a = st.columns([3, 1])

            with col_s:
                st.markdown(
                    f'<span style="color:{color};font-weight:600">'
                    f'{status}</span>',
                    unsafe_allow_html=True
                )
                if doi and doi not in ("ALL_176", "CORPUS_ALL"):
                    st.markdown(f"**DOI:** `{doi}`")

                blocked_by = item.get("blocked_by","")
                if blocked_by:
                    st.markdown(f"**Blocked by:** {blocked_by}")

                needed = item.get("needed_input","")
                if needed:
                    st.markdown(f"**Needed input:** {needed}")

                next_action = item.get("next_action","")
                if next_action:
                    st.markdown(f"**Next action:** `{next_action}`")

                closure = item.get("closure_condition","")
                if closure:
                    st.markdown(f"**Closure condition:** {closure}")

                evidence = item.get("evidence_required","")
                if evidence:
                    st.markdown(
                        f'<div style="font-size:11px;color:#4a6a9a;'
                        f'border-left:2px solid #2a3a6a;padding:4px 10px;margin-top:6px;">'
                        f'Evidence required: {evidence}</div>',
                        unsafe_allow_html=True
                    )

                notes = item.get("notes","")
                if notes:
                    st.caption(notes)

            with col_a:
                auto_str = "YES" if auto else "NO"
                conf_str = ("Confidence: " + confidence) if confidence else ""
                st.markdown(
                    f"**Auto:** {auto_str}  \n"
                    f"**Source:** {source}  \n"
                    f"{conf_str}"
                )
                if item.get("last_checked"):
                    st.caption(f"Checked: {item['last_checked']}")

                # ── Plugin 6: Resolution closure helper ──────────────────
                if status != "RESOLVED":
                    edits = st.session_state.resolution_edits
                    closure_action = st.radio(
                        "Action",
                        ["— no action —", "Mark RESOLVED", "Defer (BACKBURNER)",
                         "Escalate (MANUAL_INPUT_REQUIRED)"],
                        key=f"radio_{item_id}",
                        horizontal=True,
                        label_visibility="collapsed",
                    )
                    evidence_note = st.text_input(
                        "Evidence / note (required for RESOLVED)",
                        key=f"ev_{item_id}",
                        placeholder="What evidence closes this item?"
                    )
                    if closure_action == "Mark RESOLVED":
                        if not evidence_note.strip():
                            st.warning("Enter evidence note before marking resolved.")
                        else:
                            if st.button("Confirm RESOLVED", key=f"confirm_{item_id}"):
                                edits[item_id] = {
                                    "status": "RESOLVED",
                                    "evidence": evidence_note,
                                    "closed_date": date.today().isoformat(),
                                }
                                st.success("Marked RESOLVED with evidence. Save to persist.")
                    elif closure_action == "Defer (BACKBURNER)":
                        if st.button("Confirm defer", key=f"defer_{item_id}"):
                            edits[item_id] = {
                                "status": "BACKBURNER",
                                "evidence": evidence_note or "Deferred",
                                "closed_date": date.today().isoformat(),
                            }
                            st.info("Moved to BACKBURNER.")
                    elif closure_action == "Escalate (MANUAL_INPUT_REQUIRED)":
                        if st.button("Confirm escalate", key=f"esc_{item_id}"):
                            edits[item_id] = {
                                "status": "MANUAL_INPUT_REQUIRED",
                                "evidence": evidence_note or "Escalated",
                                "closed_date": date.today().isoformat(),
                            }
                            st.warning("Escalated to MANUAL_INPUT_REQUIRED.")

    st.divider()

    # ── New item form ──────────────────────────────────────────────────
    with st.expander("➕ Add new resolution item"):
        r_doi    = st.text_input("DOI (or ALL_176/CORPUS_ALL)", key="r_doi")
        r_title  = st.text_input("Title / description", key="r_title")
        r_status = st.selectbox("Status", STATUS_ORDER, key="r_status")
        r_block  = st.text_input("Blocked by", key="r_block")
        r_needed = st.text_input("Needed input", key="r_needed")
        r_action = st.text_input("Next action", key="r_action")
        r_closure= st.text_input("Closure condition", key="r_closure")
        r_evidence=st.text_input("Evidence required (NEVER auto-fill)", key="r_evidence")
        r_auto   = st.checkbox("Auto-resolvable?", value=False, key="r_auto")
        r_notes  = st.text_area("Notes", key="r_notes")

        if st.button("Add to register", key="add_res"):
            if not r_title:
                st.warning("Title is required.")
            else:
                new_item = {
                    "id": f"RES-{len(reg_items)+1:03d}" if reg else "RES-001",
                    "doi": r_doi or "—",
                    "title": r_title,
                    "status": r_status,
                    "blocked_by": r_block,
                    "needed_input": r_needed,
                    "next_action": r_action,
                    "closure_condition": r_closure,
                    "evidence_required": r_evidence,
                    "auto_resolvable": r_auto,
                    "confidence": "PARTIAL",
                    "last_checked": date.today().isoformat(),
                    "notes": r_notes,
                }
                if reg:
                    reg["items"].append(new_item)
                    st.session_state.resolution = reg
                    st.success(f"Added {new_item['id']}")
                else:
                    st.warning("Load a resolution-register.json first to persist additions.")

    # ── Export ───────────────────────────────────────────────────────────
    st.divider()
    col_ex1, col_ex2 = st.columns(2)

    with col_ex1:
        if reg:
            # Apply any in-session resolves
            edits = st.session_state.resolution_edits
            export_reg = deepcopy(reg)
            for item in export_reg.get("items", []):
                edit = edits.get(item.get("id"))
                if edit is None:
                    continue
                if isinstance(edit, dict):
                    item["status"]              = str(edit.get("status", item.get("status","")))
                    item["resolution_evidence"] = str(edit.get("evidence", ""))
                    item["resolved_date"]       = str(edit.get("closed_date", ""))
                else:
                    item["status"] = str(edit)
            export_reg["_meta"]["last_updated"] = date.today().isoformat()

            st.download_button(
                "Download resolution-register.json",
                data=json.dumps(export_reg, indent=2, ensure_ascii=False),
                file_name=f"resolution-register-{date.today().isoformat()}.json",
                mime="application/json"
            )
            if st.button("Save to disk", key="save_res"):
                err = save_json(export_reg, st.session_state.resolution_path)
                if err:
                    st.error(err)
                else:
                    st.success(f"✓ Saved to {st.session_state.resolution_path}")

    with col_ex2:
        if PANDAS and reg_items:
            df_res = pd.DataFrame([{
                "ID":       i.get("id",""),
                "Status":   i.get("status",""),
                "Title":    i.get("title","")[:60],
                "DOI":      i.get("doi",""),
                "Auto":     "YES" if i.get("auto_resolvable") else "NO",
                "Next action": i.get("next_action","")[:50],
                "Checked":  i.get("last_checked",""),
            } for i in reg_items])
            csv_buf = io.StringIO()
            df_res.to_csv(csv_buf, index=False)
            st.download_button(
                "Download resolution CSV",
                data=csv_buf.getvalue(),
                file_name=f"resolution-{date.today().isoformat()}.csv",
                mime="text/csv"
            )
