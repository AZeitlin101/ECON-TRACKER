#!/usr/bin/env python3
"""
fetch_indicators.py

Pulls the current reading for each configured series (data/sources.json),
merges in the hand-maintained PMI/manual figures (data/manual.json), and
writes the combined result to data/indicators.json for the dashboard to read.

Run manually:
    FRED_API_KEY=xxxx python fetch_indicators.py

Run on a schedule: see .github/workflows/update-data.yml
"""

import json
import os
import sys
import datetime
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCES_PATH = os.path.join(HERE, "data", "sources.json")
MANUAL_PATH = os.path.join(HERE, "data", "manual.json")
OUTPUT_PATH = os.path.join(HERE, "data", "indicators.json")

FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"


def http_get_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "econ-tracker/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_fred(series_id, transform="level"):
    """Fetch the latest non-missing observation for a FRED series."""
    if not FRED_API_KEY:
        raise RuntimeError(
            "FRED_API_KEY not set. Get a free key at https://fred.stlouisfed.org/docs/api/api_key.html "
            "and export it as an environment variable (or add it as a GitHub Actions secret)."
        )
    url = (
        f"{FRED_BASE}?series_id={series_id}&api_key={FRED_API_KEY}"
        f"&file_type=json&sort_order=desc&limit=14"
    )
    data = http_get_json(url)
    obs = [o for o in data.get("observations", []) if o.get("value") not in (".", "", None)]
    if not obs:
        raise RuntimeError(f"No observations returned for FRED series {series_id}")

    if transform == "level":
        latest = obs[0]
        return float(latest["value"]), latest["date"]

    if transform == "yoy_pct":
        # obs are monthly, sorted desc; find the same month one year back
        latest = obs[0]
        latest_date = datetime.date.fromisoformat(latest["date"])
        target = latest_date.replace(year=latest_date.year - 1)
        prior = next((o for o in obs if o["date"] == target.isoformat()), None)
        if prior is None:
            # not enough history in the 14-point window; fetch more
            url2 = (
                f"{FRED_BASE}?series_id={series_id}&api_key={FRED_API_KEY}"
                f"&file_type=json&sort_order=desc&limit=15&observation_start=2000-01-01"
            )
            data2 = http_get_json(url2)
            obs2 = [o for o in data2.get("observations", []) if o.get("value") not in (".", "", None)]
            prior = next((o for o in obs2 if o["date"] == target.isoformat()), None)
        if prior is None:
            raise RuntimeError(f"Could not find year-ago observation for {series_id}")
        pct = (float(latest["value"]) / float(prior["value"]) - 1.0) * 100.0
        return round(pct, 2), latest["date"]

    raise ValueError(f"Unknown transform: {transform}")


def fetch_oecd(url):
    """Fetch the latest observation from an OECD SDMX-JSON query URL."""
    if "format=jsondata" not in url and "format=" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}format=jsondata"
    data = http_get_json(url)

    # SDMX-JSON: observations live under data.dataSets[0].observations,
    # keyed by dimension index tuple, e.g. "0:0:0". The time dimension's
    # labels are in structure.dimensions.observation[...].values
    datasets = data.get("data", {}).get("dataSets") or data.get("dataSets")
    structure = data.get("data", {}).get("structure") or data.get("structure")
    if not datasets or not structure:
        raise RuntimeError("Unexpected OECD SDMX-JSON shape; check the query URL")

    obs_dim = structure["dimensions"]["observation"][0]
    time_values = obs_dim["values"]  # list of {id, name} in time order

    observations = datasets[0].get("observations", {})
    if not observations:
        raise RuntimeError("OECD query returned no observations — check the series filters")

    # Find the observation with the highest time index = most recent
    best_idx, best_val = None, None
    for key, val in observations.items():
        idx = int(key.split(":")[-1])
        if best_idx is None or idx > best_idx:
            best_idx, best_val = idx, val

    value = best_val[0]
    period_label = time_values[best_idx]["name"]
    return round(float(value), 2), period_label


def load_json(path):
    with open(path) as f:
        return json.load(f)


def main():
    sources = load_json(SOURCES_PATH)
    manual = load_json(MANUAL_PATH)

    result = {"_generated_at": datetime.datetime.utcnow().isoformat() + "Z", "countries": {}}
    errors = []

    for country_key, country_cfg in sources.items():
        if country_key.startswith("_"):
            continue
        flag = country_cfg.get("flag", "")
        metrics = {}

        for metric_key, cfg in country_cfg.items():
            if metric_key == "flag":
                continue

            mtype = cfg.get("type")
            try:
                if mtype == "fred":
                    value, period = fetch_fred(cfg["series"], cfg.get("transform", "level"))
                    metrics[metric_key] = {"value": value, "period": period, "source": "FRED"}

                elif mtype == "oecd":
                    if cfg.get("url", "FILL_ME") == "FILL_ME":
                        raise RuntimeError("URL not filled in yet — see HOW_TO_FILL_OECD_URLS.md")
                    value, period = fetch_oecd(cfg["url"])
                    metrics[metric_key] = {"value": value, "period": period, "source": "OECD"}

                elif mtype == "manual":
                    man = manual.get(country_key, {}).get(metric_key)
                    if man:
                        metrics[metric_key] = {
                            "value": man["value"], "period": man["period"], "source": "manual"
                        }
                    else:
                        metrics[metric_key] = {"value": None, "period": None, "source": "manual (unset)"}

                else:
                    raise RuntimeError(f"Unknown source type: {mtype}")

            except Exception as e:
                errors.append(f"{country_key}.{metric_key}: {e}")
                # keep previous value if we have an existing indicators.json
                metrics[metric_key] = {"value": None, "period": None, "source": "error", "error": str(e)}

        result["countries"][country_key] = {"flag": flag, "metrics": metrics}

    with open(OUTPUT_PATH, "w") as f:
        json.dump(result, f, indent=2)

    print(f"Wrote {OUTPUT_PATH}")
    if errors:
        print("\nSome series did not update:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        # don't fail the whole run over missing OECD URLs / manual gaps
        sys.exit(0)


if __name__ == "__main__":
    main()
