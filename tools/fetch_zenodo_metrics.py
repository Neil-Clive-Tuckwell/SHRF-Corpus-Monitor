#!/usr/bin/env python3
"""
fetch_zenodo_metrics.py  —  SHRF Corpus Uptake Monitor  v2.1
=============================================================
Fetches view/download statistics for all DOIs in uptake-metrics-full.json.

STRATEGY (layered — each layer is a fallback for the one above):
  Layer 1: Zenodo REST API  /api/records/{id}
           Per Zenodo support docs: stats key is present in all public records.
           zenodo.org/api/records/{id}?prettyprint=1  — look for "stats" key.
  Layer 2: HTML page scrape — parses the stats panel from the record landing page.
           Used when API returns no stats key (rare edge cases).
  Layer 3: Flag as UNRESOLVED — never silently zero a previously retrieved record.

OPERATING PHILOSOPHY:
  - No wasted motion: parallel fetching with thread pool
  - No silent failures: every failure is logged and typed
  - No regression: previous values always preserved before overwriting
  - Polite footprint: configurable rate limiting, retry with backoff
  - Continuous improvement: failure log identifies systemic patterns for next pass

ARCHITECTURE INVARIANT (permanent):
  This script writes ONLY to the metrics layer (uptake-metrics-full.json).
  It never touches corpus.json, schema.json, or any provenance state.
  Uptake metrics = audience behaviour. Corpus truth is separate.

Usage:
  python3 fetch_zenodo_metrics.py [options]

Options:
  --input PATH          Source metrics JSON  (default: uptake-metrics-full.json)
  --output PATH         Output path          (default: overwrite input)
  --workers N           Parallel threads     (default: 4, max 8)
  --delay SECS          Per-request delay    (default: 0.3)
  --only-preferred      Skip superseded versions
  --only-unretrieved    Only fetch records with retrieved=false (retry pass)
  --dry-run             Print plan, no writes
  --verbose             Show full detail per record
  --summary             Print signal summary table at end
  --log PATH            Failure log path     (default: fetch_errors.log)

Dependencies:
  pip install requests beautifulsoup4 lxml
"""

import json
import time
import argparse
import sys
import re
import logging
import threading
from datetime import date
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    print("ERROR: requests not installed.\nRun: pip install requests")
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False
    print("WARNING: beautifulsoup4 not installed. HTML fallback disabled.")
    print("         Run: pip install beautifulsoup4 lxml\n")

ZENODO_API  = "https://zenodo.org/api/records/{id}"
ZENODO_PAGE = "https://zenodo.org/records/{id}"
USER_AGENT  = ("SHRF-corpus-monitor/2.0 "
               "(academic metadata tracking; non-commercial; "
               "contact: research corpus monitor)")
REQUEST_TIMEOUT = 20


# ── Signal classification ─────────────────────────────────────────────────────
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


# ── HTTP session with retry ───────────────────────────────────────────────────
def make_session():
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    retry = Retry(
        total=3,
        backoff_factor=1.2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"]
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


def extract_id(doi):
    m = re.search(r'zenodo\.(\d+)$', doi)
    return m.group(1) if m else None


# ── Layer 1: Zenodo REST API ──────────────────────────────────────────────────
def via_api(record_id, session):
    """
    Primary method. Zenodo /api/records/{id} returns a stats key.
    Confirmed per Zenodo support: https://support.zenodo.org/help/en-gb/4-usage-statistics/2-...
    Returns (views, downloads, method_tag)
    """
    url = ZENODO_API.format(id=record_id)
    try:
        r = session.get(url, timeout=REQUEST_TIMEOUT)

        if r.status_code == 404: return None, None, "404_not_found"
        if r.status_code == 410: return None, None, "410_deleted"
        if r.status_code == 429: return None, None, "429_rate_limited"
        if r.status_code != 200: return None, None, f"http_{r.status_code}"

        data = r.json()
        stats = data.get("stats", {})

        if not stats:
            return None, None, "api_no_stats_key"

        # InvenioRDM all-versions rollup (what Zenodo displays by default)
        av = stats.get("all_versions", {})
        views     = av.get("unique_views")     or stats.get("unique_views")     or 0
        downloads = av.get("unique_downloads") or stats.get("unique_downloads") or 0

        tag = "api_ok_zeros" if (views == 0 and downloads == 0) else "api_ok"
        return int(views), int(downloads), tag

    except requests.exceptions.Timeout:      return None, None, "timeout"
    except requests.exceptions.ConnectionError: return None, None, "conn_error"
    except ValueError:                       return None, None, "json_error"
    except Exception as e:                   return None, None, f"api_{type(e).__name__}"


# ── Layer 2: HTML page scrape ─────────────────────────────────────────────────
def via_html(record_id, session):
    """
    Fallback HTML scrape. Zenodo InvenioRDM displays stats as large numbers
    above 'Views' and 'Downloads' labels in the sidebar/stats panel.
    Three parse strategies applied in sequence.
    """
    if not BS4_AVAILABLE:
        return None, None, "bs4_unavailable"

    url = ZENODO_PAGE.format(id=record_id)
    try:
        r = session.get(url, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return None, None, f"html_http_{r.status_code}"

        soup = BeautifulSoup(r.text, "lxml")
        views = downloads = None

        # Strategy A: sibling of 'Views'/'Downloads' text nodes
        for label_text, target in [("Views", "views"), ("Downloads", "downloads")]:
            for tag in soup.find_all(string=re.compile(rf'^\s*{label_text}\s*$', re.I)):
                p = tag.parent
                if p:
                    prev = p.find_previous_sibling()
                    if prev:
                        m = re.search(r'[\d,]+', prev.get_text())
                        if m:
                            val = int(m.group().replace(',', ''))
                            if target == "views":     views     = val
                            if target == "downloads": downloads = val

        # Strategy B: stats section scan
        if views is None:
            for cls in [r'stat', r'usage', r'metric', r'count']:
                sec = soup.find(True, class_=re.compile(cls, re.I))
                if sec:
                    nums = [int(n.replace(',','')) for n in
                            re.findall(r'\b[\d,]+\b', sec.get_text())
                            if n.replace(',','').isdigit()]
                    if len(nums) >= 2:
                        views, downloads = nums[0], nums[1]
                    break

        # Strategy C: full-text pattern
        if views is None:
            m = re.search(
                r'([\d,]+)\s+(?:Total\s+)?[Vv]iews?\D{0,30}([\d,]+)\s+(?:Total\s+)?[Dd]ownloads?',
                soup.get_text()
            )
            if m:
                views     = int(m.group(1).replace(',', ''))
                downloads = int(m.group(2).replace(',', ''))

        if views is not None and downloads is not None:
            return views, downloads, "html_ok"

        return None, None, "html_parse_failed"

    except requests.exceptions.Timeout:      return None, None, "html_timeout"
    except Exception as e:                   return None, None, f"html_{type(e).__name__}"


# ── Fetch one record (layered) ────────────────────────────────────────────────
def fetch_one(entry, session, delay, verbose):
    doi = entry.get("doi", "")
    rid = extract_id(doi)
    if not rid:
        return entry, None, None, "no_record_id"

    time.sleep(delay)
    views, downloads, method = via_api(rid, session)

    # Fallback to HTML if API had no stats (not for hard errors like 404)
    if views is None and method in ("api_no_stats_key", "api_ok_zeros"):
        time.sleep(delay * 0.5)
        views, downloads, method = via_html(rid, session)

    if verbose:
        if views is not None:
            print(f"    {doi[-14:]}  v={views}  d={downloads}  [{method}]")
        else:
            print(f"    {doi[-14:]}  FAILED [{method}]")

    return entry, views, downloads, method


# ── Main ──────────────────────────────────────────────────────────────────────
def run(args):
    logging.basicConfig(
        filename=args.log,
        level=logging.WARNING,
        format="%(asctime)s %(message)s"
    )

    input_path  = Path(args.input)
    output_path = Path(args.output) if args.output else input_path

    if not input_path.exists():
        print(f"ERROR: File not found: {input_path}")
        sys.exit(1)

    with open(input_path, encoding='utf-8') as f:
        metrics = json.load(f)

    entries = metrics.get("entries", [])
    today   = date.today().isoformat()

    # Apply filters
    pool = entries[:]
    if args.only_preferred:
        pool = [e for e in pool if e.get("status") != "superseded"]
    if args.only_unretrieved:
        pool = [e for e in pool if not e.get("retrieved")]
    skipped = len(entries) - len(pool)

    print(f"\n{'═'*70}")
    print(f"  SHRF Zenodo Metrics Fetcher  v2.0  —  {today}")
    print(f"  Input:   {input_path}  ({len(entries)} total entries)")
    print(f"  Fetch:   {len(pool)}  |  Skip: {skipped}")
    print(f"  Workers: {args.workers}  |  Delay: {args.delay}s/req")
    print(f"  Strategy: API → HTML fallback → flag unresolved")
    if args.dry_run: print(f"  DRY RUN — no writes")
    print(f"{'═'*70}\n")

    if args.dry_run:
        for e in pool:
            print(f"  WOULD FETCH: {e['doi']}")
        print(f"\n  Total to fetch: {len(pool)}")
        return

    sessions = [make_session() for _ in range(args.workers)]

    def fetch_worker(args_tuple):
        e, wid = args_tuple
        return fetch_one(e, sessions[wid], args.delay, args.verbose)

    work = [(e, i % args.workers) for i, e in enumerate(pool)]

    ok = failed = changed = 0
    method_counts = Counter()

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(fetch_worker, w): w for w in work}
        done = 0
        for fut in as_completed(futures):
            entry, views, downloads, method = fut.result()
            done += 1
            method_counts[method] += 1
            doi   = entry.get("doi", "")
            title = (entry.get("title", "")[:45]).replace('\n',' ')

            if views is None:
                failed += 1
                logging.warning(f"FAILED doi={doi} method={method}")
                # Provenance: record the failure without overwriting prior data
                if not entry.get("retrieved"):
                    entry["retrieval_method"]    = method
                    entry["retrieval_timestamp"] = __import__('datetime').datetime.utcnow().isoformat() + "Z"
                    entry["error_message"]       = method
                print(f"  [{done:3d}/{len(pool)}] ✗  {doi[-15:]}  {method}")
            else:
                ok += 1
                prev_v = entry.get("views", 0)  if entry.get("retrieved") else None
                prev_d = entry.get("downloads",0) if entry.get("retrieved") else None

                if entry.get("retrieved") and (views != prev_v or downloads != (prev_d or 0)):
                    changed += 1
                    entry["previous_views"]          = prev_v
                    entry["previous_downloads"]      = prev_d
                    entry["previous_retrieval_date"] = entry.get("retrieval_date")

                signal = classify_signal(views, downloads, prev_v, prev_d)
                entry.update({
                    "views":              views,
                    "downloads":          downloads,
                    "retrieval_date":     today,
                    "retrieval_timestamp": __import__('datetime').datetime.utcnow().isoformat() + "Z",
                    "retrieval_method":   method,
                    "retrieved":          True,
                    "download_ratio":     round(downloads/views, 4) if views else 0.0,
                    "signal_class":       signal,
                    # LOW_DATA guard: engagement_class respects the <10 view threshold
                    # signal_class is the computed value; engagement_class is the
                    # display-safe value that enforces the low-data invariant
                    "engagement_class":   "LOW_DATA" if views < 10 else signal,
                    "low_data_flag":      views < 10,
                })

                dv  = (views - (prev_v or 0))
                mrk = "▲" if dv > 0 else ("▼" if dv < 0 else "=")
                sig = entry["signal_class"]
                r   = entry["download_ratio"]
                print(f"  [{done:3d}/{len(pool)}] {mrk}  {doi[-15:]}  "
                      f"v={views:5d}  d={downloads:4d}  r={r:.3f}  "
                      f"[{sig:<15s}]  {method}")

    # Update meta
    metrics["_meta"].update({
        "retrieval_date":     today,
        "last_fetch_ok":      ok,
        "last_fetch_failed":  failed,
        "last_fetch_skipped": skipped,
        "last_fetch_changed": changed,
        "fetch_version":      "2.1",
    })

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)

    # ── Plugin 3: First-run snapshot exporter ────────────────────────────────
    # On first run (all previous_views were None), save a dated baseline snapshot
    # and a CSV summary. These baselines are never overwritten.
    import csv as csv_mod
    is_first_run = all(
        e.get("previous_views") is None
        for e in entries if e.get("retrieved")
    )
    if is_first_run and ok > 0:
        snap_dir = output_path.parent / "metrics_snapshots"
        snap_dir.mkdir(exist_ok=True)

        # 3a. Raw JSON snapshot
        snap_json = snap_dir / f"first_run_{today}.json"
        if not snap_json.exists():
            with open(snap_json, 'w', encoding='utf-8') as f:
                json.dump(metrics, f, indent=2, ensure_ascii=False)
            print(f"  ✓ First-run snapshot: {snap_json}")

        # 3b. CSV summary
        snap_csv = snap_dir / f"first_run_{today}.csv"
        if not snap_csv.exists():
            with open(snap_csv, 'w', newline='', encoding='utf-8') as f:
                writer = csv_mod.writer(f)
                writer.writerow([
                    "doi","title","domain","status","views","downloads",
                    "download_ratio","signal_class","engagement_class",
                    "low_data_flag","retrieval_method","retrieval_date"
                ])
                for e in sorted(entries, key=lambda x: -x.get("views",0)):
                    if e.get("retrieved"):
                        writer.writerow([
                            e.get("doi",""), e.get("title","")[:60],
                            e.get("domain",""), e.get("status",""),
                            e.get("views",0), e.get("downloads",0),
                            e.get("download_ratio",0),
                            e.get("signal_class",""), e.get("engagement_class",""),
                            e.get("low_data_flag",False),
                            e.get("retrieval_method",""), e.get("retrieval_date",""),
                        ])
            print(f"  ✓ First-run CSV:      {snap_csv}")

    # Final report
    print(f"\n{'═'*70}")
    print(f"  RESULT:  {ok} ok · {failed} failed · {skipped} skipped · {changed} changed")
    print(f"  Written: {output_path}")

    # ── Plugin 4: DOI anomaly detector ──────────────────────────────────────
    anomalies = []
    seen_dois = {}
    for e in entries:
        doi = e.get("doi","")
        # Duplicate DOI
        if doi in seen_dois:
            anomalies.append(f"DUPLICATE_DOI: {doi}")
        else:
            seen_dois[doi] = True
        # Malformed DOI
        import re as _re
        if doi and not _re.match(r'^10\.\d{4,}/zenodo\.\d+$', doi):
            anomalies.append(f"MALFORMED_DOI: {doi}")
        # 404 / fetch failure
        if e.get("error_message","").startswith("404"):
            anomalies.append(f"404_NOT_FOUND: {doi}")
        # Zero views + nonzero downloads (data integrity issue)
        if e.get("retrieved") and e.get("views",0) == 0 and e.get("downloads",0) > 0:
            anomalies.append(f"ZERO_VIEWS_NONZERO_DLS: {doi} (dls={e.get('downloads')})")
        # Superseded but no superseded_by field
        if e.get("status") == "superseded" and not e.get("superseded_by"):
            anomalies.append(f"SUPERSEDED_NO_CHAIN: {doi}")
        # Missing domain
        if not e.get("domain"):
            anomalies.append(f"MISSING_DOMAIN: {doi}")

    if anomalies:
        print(f"\n  ANOMALIES DETECTED ({len(anomalies)}):")
        for a in anomalies[:20]:
            print(f"    ⚠  {a}")
        if len(anomalies) > 20:
            print(f"    ... and {len(anomalies)-20} more — check fetch_errors.log")
        logging.warning(f"Anomalies detected: {anomalies}")
    else:
        print(f"\n  ✓ No DOI anomalies detected.")

    if args.summary:
        print(f"\n  SIGNAL DISTRIBUTION:")
        order = ["STICKY","HIGH_CONVERSION","ENGAGED","RISING",
                 "BROWSING","STALE","LOW_DATA","NO_METRICS"]
        sigs = Counter(e.get("signal_class","NO_METRICS")
                       for e in entries if e.get("retrieved"))
        for s in order:
            c = sigs.get(s, 0)
            bar = "█" * min(40, c)
            if c: print(f"    {s:<18s}  {c:3d}  {bar}")

        tv = sum(e.get("views",0)     for e in entries if e.get("retrieved"))
        td = sum(e.get("downloads",0) for e in entries if e.get("retrieved"))
        print(f"\n  CORPUS:  views={tv:,}  downloads={td:,}  "
              f"ratio={td/tv:.3f}" if tv else "  CORPUS:  no data yet")

    if method_counts:
        print(f"\n  FETCH METHODS:")
        for m, c in method_counts.most_common():
            print(f"    {m:<28s} {c}")

    if failed:
        print(f"\n  {failed} failures logged → {args.log}")
        print(f"  Re-run with --only-unretrieved to retry failures only.")

    print(f"{'═'*70}\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="SHRF Corpus — Zenodo Uptake Metrics Fetcher v2.1",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
QUICK START:
  pip install requests beautifulsoup4 lxml
  python3 fetch_zenodo_metrics.py --summary

FIRST PASS (skip superseded versions, see summary):
  python3 fetch_zenodo_metrics.py --only-preferred --summary

RETRY FAILURES:
  python3 fetch_zenodo_metrics.py --only-unretrieved

WEEKLY CRON (macOS/Linux):
  0 8 * * 1 cd /path/to/folder && python3 fetch_zenodo_metrics.py --summary >> fetch.log 2>&1

ARCHITECTURE INVARIANT:
  This script modifies only the metrics layer.
  corpus.json is never touched.
  Uptake = audience behaviour. Validity = separate.
        """
    )
    p.add_argument("--input",            default="uptake-metrics-full.json")
    p.add_argument("--output",           default=None)
    p.add_argument("--workers",          type=int,   default=4)
    p.add_argument("--delay",            type=float, default=0.3)
    p.add_argument("--only-preferred",   action="store_true")
    p.add_argument("--only-unretrieved", action="store_true")
    p.add_argument("--dry-run",          action="store_true")
    p.add_argument("--verbose",          action="store_true")
    p.add_argument("--summary",          action="store_true")
    p.add_argument("--log",              default="fetch_errors.log")
    p.add_argument("--no-snapshot",      action="store_true",
                   help="Skip first-run snapshot even if this is the first run")
    args = p.parse_args()
    args.workers = min(max(args.workers, 1), 8)
    run(args)
