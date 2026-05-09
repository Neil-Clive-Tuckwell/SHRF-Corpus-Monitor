# SHRF Corpus Monitor — GitHub Push & Deployment Guide
# Generated: 2026-05-09
# Status: repo locally committed, ready to push

---

## Step 1 — Create the GitHub repository

1. Go to https://github.com/new
2. Repository name: `SHRF-Corpus-Monitor`
3. Description: `SHRF research corpus monitoring app — uptake metrics, validation, topology, resolution register`
4. Visibility: **Public** (required for free Streamlit Community Cloud deployment)
5. **Do NOT** initialise with README, .gitignore, or LICENSE — we already have these
6. Click **Create repository**
7. Copy the repo URL shown: `https://github.com/NeilTuckwell/SHRF-Corpus-Monitor.git`

---

## Step 2 — Push from your local machine

Open Terminal in the folder containing the extracted zip, then:

```bash
# Navigate into the repo folder
cd SHRF-Corpus-Monitor

# Add the GitHub remote
git remote add origin https://github.com/NeilTuckwell/SHRF-Corpus-Monitor.git

# Push to GitHub
git push -u origin main
```

If prompted for credentials:
- Username: your GitHub username
- Password: a GitHub Personal Access Token (not your password)
  - GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
  - Scopes needed: `repo`, `workflow`

---

## Step 3 — Enable GitHub Actions permissions

1. Go to your repo on GitHub
2. Settings → Actions → General
3. Under "Workflow permissions": select **Read and write permissions**
4. Check **Allow GitHub Actions to create and approve pull requests**
5. Save

This allows the weekly fetch workflow to commit updated metrics back to the repo.

---

## Step 4 — Verify CI runs

1. Go to Actions tab in your repo
2. You should see "Corpus Monitor CI" running on the initial commit
3. It will run: syntax check, AST check, corpus validator, JSON structure check, invariant check
4. Expected result: all green

If CI fails: check the error message — most likely a file path issue.

---

## Step 5 — Deploy to Streamlit Community Cloud

1. Go to https://share.streamlit.io
2. Sign in with your GitHub account
3. Click **New app**
4. Repository: `NeilTuckwell/SHRF-Corpus-Monitor`
5. Branch: `main`
6. Main file path: `app/shrf_corpus_monitor_app.py`
7. Click **Deploy**

Deployment takes 2-3 minutes. The app will open with empty data (correct — shows NO_METRICS honestly).

Copy the app URL — format: `https://neiltuckwell-shrf-corpus-monitor-app-....streamlit.app`

Update the README.md live app link with this URL, then push the update.

---

## Step 6 — First manual fetch (run locally, NOT via GitHub Actions)

```bash
# In your local SHRF-Corpus-Monitor folder
pip install requests beautifulsoup4 lxml

python3 tools/fetch_zenodo_metrics.py \
  --input data/uptake-metrics-full.json \
  --output data/uptake-metrics-full.json \
  --only-preferred \
  --summary

# Review the output — check signal distribution
# Then commit and push the result
git add data/uptake-metrics-full.json
git commit -m "data: first Zenodo metrics fetch $(date +%Y-%m-%d)"
git push
```

Streamlit will auto-redeploy within 1-2 minutes of the push.

---

## Step 7 — Enable weekly automation

The weekly fetch workflow is already in `.github/workflows/weekly-fetch.yml`.
It runs every Monday at 08:00 UTC automatically once the repo is on GitHub.

To trigger it manually:
1. Actions tab → Weekly Metrics Fetch → Run workflow

---

## Step 8 — Archive to Zenodo for DOI

After the first stable release (when app is live and first fetch is done):

1. Go to https://zenodo.org
2. Sign in → GitHub (connect your GitHub account)
3. Find `SHRF-Corpus-Monitor` in the list and **toggle ON**
4. Go back to GitHub → Releases → Create a new release
   - Tag: `v0.7.0`
   - Title: `SHRF Corpus Monitor v0.7.0 — Prototype`
   - Description: paste from CITATION.cff abstract
5. Zenodo automatically creates a DOI for the release
6. Copy the DOI and add it to:
   - `CITATION.cff` (citation DOI field)
   - `README.md` (badge at top)
   - Push the update

---

## Automation boundary (permanent rule)

| Layer | Auto-updates | How |
|-------|-------------|-----|
| `data/uptake-metrics-full.json` | YES | Weekly GitHub Action |
| `metrics_snapshots/` | YES | fetch script on first run |
| `app/shrf_corpus_monitor_app.py` | Only on manual push | Never auto-edited |
| `data/corpus.json` | NO — manual only | Human judgment required |
| `data/resolution-register.json` | Partial — via app save | Evidence required for closure |

---

## Ongoing monitoring loop (once deployed)

```
Every Monday:
  GitHub Action → fetch_zenodo_metrics.py → commit updated metrics → Streamlit redeploys

When you see something unexpected:
  Open Streamlit app → Dashboard → check signal distribution
  Open Resolution tab → check auto-detected items
  If spike: investigate before adding to resolution register

When new DOIs are published:
  Add to uptake-metrics-full.json manually or via app
  Run validate_corpus.py if adding to corpus.json
  Push

When new corpus node is confirmed:
  Edit corpus.json manually
  Run validator
  Push → CI checks
```

---

## Recovery (if something breaks)

Local backup: keep the zip on Google Drive  
GitHub: full version history — `git log`, `git revert`  
Zenodo: each released version is permanently archived  
Data files: metrics are regeneratable (fetch again); corpus.json is the critical file to protect
