# Global Macro Board — auto-updating setup

This turns the dashboard into something that refreshes itself daily, for free,
using official data sources instead of scraping Trading Economics.

## What updates automatically vs. what you maintain

| Source | Covers | Effort |
|---|---|---|
| **FRED** (free, official, US only) | US inflation, GDP growth, unemployment, consumer confidence | Automatic once you add one API key |
| **OECD SDMX API** (free, no key, 7 non-US economies) | Inflation, GDP growth, unemployment, business confidence, consumer confidence | ~2 min one-time setup *per series* (see below) |
| **Manual** (`data/manual.json`) | Manufacturing PMI + Services PMI for all 8, plus a few confidence gauges that aren't freely available via API (Swiss KOF, Canada, NZ) | You edit a JSON file once a month, takes under a minute |

PMI is proprietary S&P Global data — there is no free, legal API for it anywhere.
Trying to auto-fetch it would mean scraping, which is what we're avoiding.

## Step 1 — Get a free FRED API key

1. Sign up at https://fred.stlouisfed.org/docs/api/api_key.html (free, instant).
2. Copy the key.

## Step 2 — Fill in the OECD URLs (~2 minutes each, 30ish series total)

For each `"url": "FILL_ME"` entry in `data/sources.json`:

1. Go to https://data-explorer.oecd.org
2. Search for the indicator (e.g. "Consumer price index", "Harmonised unemployment
   rate", "Business confidence indicator", "Consumer confidence indicator",
   "Quarterly GDP growth").
3. Filter the table down to just the one country and the shortest useful
   time window (e.g. last 2 years) — you don't need history, just the latest point.
4. Click the **"Developer API"** icon above the data table (looks like `</>`).
5. Copy the **Data query** URL it generates and paste it into the matching
   `"url"` field in `data/sources.json`.

This is the reliable way to get these — SDMX dimension codes vary by dataset
and are easy to get wrong by guessing, but the Data Explorer builds the exact
URL for the exact series you're looking at.

Tip: do all 5 series for one country before moving to the next — it's faster
once you're in the rhythm.

## Step 3 — Test locally

```bash
pip install --break-system-packages requests   # only stdlib actually used, but handy to have
export FRED_API_KEY=your_key_here
python fetch_indicators.py
cat data/indicators.json
```

Fix any `FILL_ME` or error lines it prints before moving on.

## Step 4 — Push to GitHub and turn on automation

1. Create a new GitHub repo, push this whole folder to it.
2. In the repo, go to **Settings → Secrets and variables → Actions** and add
   a secret named `FRED_API_KEY` with your key.
3. The workflow in `.github/workflows/update-data.yml` will now run every day
   at 07:00 UTC and commit a fresh `data/indicators.json`. You can also trigger
   it manually from the **Actions** tab (`workflow_dispatch`).

## Step 5 — Host the dashboard

Easiest option: **GitHub Pages**.
1. Repo **Settings → Pages → Deploy from branch → main → /site**.
2. Your dashboard will be live at `https://<you>.github.io/<repo>/`.

The page in `site/index.html` fetches `../data/indicators.json` at load time,
so it always shows whatever the last automated run produced — no rebuild step
needed.

## Updating PMI monthly

Open `data/manual.json`, update the `value` and `period` for whichever PMI
releases just came out, commit and push. Takes under a minute and the
dashboard picks it up on the next load.
