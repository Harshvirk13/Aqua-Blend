"""
Victorian WMIS groundwater extractor.

Purpose:
- Work with groundwater bore IDs such as 100017.
- Find the datasource(s) even when WMIS returns a different JSON shape.
- Find pH, turbidity and total alkalinity automatically.
- Download available readings and save clean CSV + raw CSV.

Run:
    python groundwater_fixed.py
"""

import json
import os
import re
import time
from datetime import datetime

import pandas as pd
import requests

BASE_URL = "https://data.water.vic.gov.au/WMIS/cgi/webservice.exe"
OUTPUT_DIR = os.path.join(os.getcwd(), "groundwater_data")

# Use 100017 first to confirm the API is working.
DEFAULT_SITES = "100017"

TARGETS = {
    "ph": [
        r"(^|[^a-z])ph([^a-z]|$)",
        r"phwq",
    ],
    "turbidity": [
        r"turbid",
    ],
    "alkalinity": [
        r"alkalinitytotal",
        r"total.*alkal",
        r"alkal.*total",
        r"alkalinit",
    ],
}


def hydstra_request(payload, timeout=60):
    """Send a raw JSON query to the WMIS Hydstra endpoint."""
    query = json.dumps(payload, separators=(",", ":"))
    url = f"{BASE_URL}?{query}"

    response = requests.get(url, timeout=timeout)
    response.raise_for_status()

    try:
        data = response.json()
    except ValueError:
        raise RuntimeError(f"WMIS did not return JSON: {response.text[:300]}")

    if data.get("error_num", 0) != 0:
        raise RuntimeError(
            f"API error {data.get('error_num')}: {data.get('error_msg', '')}"
        )
    return data


def get_site_name(site):
    payload = {
        "function": "get_db_info",
        "version": 3,
        "params": {
            "table_name": "site",
            "return_type": "hash",
            "filter_values": {"station": site},
        },
    }

    data = hydstra_request(payload)
    result = data.get("return", {})

    def walk(obj):
        if isinstance(obj, dict):
            yield obj
            for value in obj.values():
                yield from walk(value)
        elif isinstance(obj, list):
            for value in obj:
                yield from walk(value)

    for row in walk(result):
        station = str(
            row.get("station")
            or row.get("site")
            or row.get("station_no")
            or ""
        ).strip()

        if station == str(site):
            return str(
                row.get("stname")
                or row.get("station_name")
                or row.get("name")
                or row.get("short_name")
                or site
            )

    return str(site)


def _collect_datasource_values(obj, found):
    """
    WMIS has returned get_datasources_by_site in more than one JSON layout.
    Recursively collect datasource values instead of assuming result['sites'].
    """
    if isinstance(obj, dict):
        for key, value in obj.items():
            key_l = str(key).lower()

            if key_l in {"datasource", "data_source", "datasource_code"}:
                if isinstance(value, (str, int, float)):
                    text = str(value).strip()
                    if text:
                        found.add(text)

            elif key_l == "datasources":
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, (str, int, float)):
                            text = str(item).strip()
                            if text:
                                found.add(text)
                        elif isinstance(item, dict):
                            _collect_datasource_values(item, found)
                elif isinstance(value, (str, int, float)):
                    text = str(value).strip()
                    if text:
                        found.add(text)
                else:
                    _collect_datasource_values(value, found)
            else:
                _collect_datasource_values(value, found)

    elif isinstance(obj, list):
        for item in obj:
            _collect_datasource_values(item, found)


def get_datasources(site, show_debug=False):
    payload = {
        "function": "get_datasources_by_site",
        "version": 1,
        "params": {"site_list": str(site)},
    }

    data = hydstra_request(payload)

    if show_debug:
        print("\nDEBUG - get_datasources_by_site response:")
        print(json.dumps(data, indent=2)[:5000])

    found = set()
    _collect_datasource_values(data.get("return", {}), found)

    # Common WMIS/Hydstra datasource fallbacks. They are only tried if the
    # datasource-discovery response itself does not expose a usable code.
    if not found:
        for candidate in ["A", "GW", "TELEM"]:
            try:
                vars_found = get_variables(site, candidate)
                if vars_found:
                    found.add(candidate)
            except Exception:
                pass

    return sorted(found)


def _period_to_date(value):
    text = str(value or "").strip()
    digits = re.sub(r"\D", "", text)
    if len(digits) < 8:
        return ""
    return f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}"


def _walk_dicts(obj):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk_dicts(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk_dicts(value)


def get_variables(site, datasource):
    payload = {
        "function": "get_variable_list",
        "version": 1,
        "params": {
            "site_list": str(site),
            "datasource": str(datasource),
        },
    }

    data = hydstra_request(payload)
    result = data.get("return", {})

    variables = {}

    for row in _walk_dicts(result):
        code = str(
            row.get("variable")
            or row.get("variable_code")
            or row.get("var")
            or ""
        ).strip()

        # Avoid treating higher-level dictionaries as variables.
        if not code:
            continue

        name = str(
            row.get("name")
            or row.get("variable_name")
            or row.get("description")
            or code
        ).strip()

        first = _period_to_date(
            row.get("period_start")
            or row.get("start_time")
            or row.get("start")
        )
        last = _period_to_date(
            row.get("period_end")
            or row.get("end_time")
            or row.get("end")
        )

        variables[code] = {
            "code": code,
            "name": name,
            "first": first,
            "last": last,
            "datasource": str(datasource),
        }

    return list(variables.values())


def classify_variable(variable):
    text = f"{variable['code']} {variable['name']}".lower()

    # Prevent pH from matching phosphorus-type variables.
    if "phosph" in text:
        ph_match = False
    else:
        ph_match = any(re.search(p, text, re.I) for p in TARGETS["ph"])

    if ph_match:
        return "ph"

    if any(re.search(p, text, re.I) for p in TARGETS["turbidity"]):
        return "turbidity"

    if any(re.search(p, text, re.I) for p in TARGETS["alkalinity"]):
        return "alkalinity"

    return None


def choose_best(matches, target):
    if not matches:
        return None

    if target == "alkalinity":
        total = [
            v for v in matches
            if "total" in f"{v['code']} {v['name']}".lower()
        ]
        if total:
            return total[0]

    return matches[0]


def find_target_variables(site, datasources):
    all_variables = []

    for datasource in datasources:
        try:
            variables = get_variables(site, datasource)
            all_variables.extend(variables)
        except Exception as exc:
            print(f"  Could not read variables from datasource {datasource}: {exc}")

    selected = {}
    for target in ["ph", "turbidity", "alkalinity"]:
        matches = [v for v in all_variables if classify_variable(v) == target]
        selected[target] = choose_best(matches, target)

    return selected, all_variables


def to_hydstra_time(date_text, end=False):
    dt = datetime.strptime(date_text, "%Y-%m-%d")
    return dt.strftime("%Y%m%d") + ("235959" if end else "000000")


def get_timeseries(site, variable):
    first = variable["first"]
    last = variable["last"]

    if not first or not last:
        raise RuntimeError("WMIS did not supply the period of record")

    payload = {
        "function": "get_ts_traces",
        "version": 2,
        "params": {
            "site_list": str(site),
            "datasource": variable["datasource"],
            "varfrom": variable["code"],
            "varto": variable["code"],
            "start_time": to_hydstra_time(first),
            "end_time": to_hydstra_time(last, end=True),
            "interval": "day",
            "data_type": "point",
            "multiplier": "1",
        },
    }

    data = hydstra_request(payload)
    frames = []

    for row in _walk_dicts(data.get("return", {})):
        points = row.get("trace")
        if not isinstance(points, list) or not points:
            continue

        # A trace point should contain at least time/value keys.
        if not isinstance(points[0], dict):
            continue

        df = pd.DataFrame(points).rename(
            columns={"v": "value", "t": "datetime", "q": "quality_code"}
        )

        if "value" not in df.columns or "datetime" not in df.columns:
            continue

        df["site"] = str(site)
        df["variable_code"] = variable["code"]
        df["variable"] = variable["name"]
        df["datasource"] = variable["datasource"]
        frames.append(df)

    if not frames:
        return pd.DataFrame()

    out = pd.concat(frames, ignore_index=True)
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    out["datetime"] = pd.to_datetime(
        out["datetime"].astype(str),
        format="%Y%m%d%H%M%S",
        errors="coerce",
    )
    out.loc[out["value"] <= -9999, "value"] = pd.NA
    out = out.dropna(subset=["datetime"])
    return out


def main():
    print("=" * 72)
    print("Victorian WMIS Groundwater - pH / Turbidity / Total Alkalinity")
    print("=" * 72)

    raw = input(
        f"Groundwater site ID(s), comma-separated [{DEFAULT_SITES}]: "
    ).strip()
    raw = raw or DEFAULT_SITES
    sites = [s.strip() for s in raw.split(",") if s.strip()]

    all_downloaded = []
    summary_rows = []
    site_names = {}

    for site in sites:
        print("\n" + "-" * 72)
        print(f"SITE {site}")
        print("-" * 72)

        try:
            site_names[site] = get_site_name(site)
        except Exception:
            site_names[site] = site

        print(f"Name: {site_names[site]}")

        try:
            # Set show_debug=True if datasource discovery fails again.
            datasources = get_datasources(site, show_debug=False)
        except Exception as exc:
            print(f"Could not discover datasources: {exc}")
            continue

        if not datasources:
            print("No datasource found.")
            print("Change show_debug=False to show_debug=True and run again.")
            continue

        print("Datasources:", ", ".join(datasources))

        selected, all_variables = find_target_variables(site, datasources)

        print("\nRequired parameters:")
        for target in ["ph", "turbidity", "alkalinity"]:
            v = selected[target]
            if v:
                print(
                    f"  YES  {target:<11} "
                    f"code={v['code']}  datasource={v['datasource']}  "
                    f"{v['first'] or '?'} to {v['last'] or '?'}"
                )
            else:
                print(f"  NO   {target:<11} not found")

        has_all_three = all(selected.values())
        summary_rows.append(
            {
                "site_id": site,
                "source_name": site_names[site],
                "ph": "YES" if selected["ph"] else "NO",
                "turbidity": "YES" if selected["turbidity"] else "NO",
                "alkalinity": "YES" if selected["alkalinity"] else "NO",
                "all_three": "YES" if has_all_three else "NO",
            }
        )

        if not has_all_three:
            print("\nThis site does NOT contain all three required parameters.")
            print("Available variable names/codes:")
            for v in all_variables:
                print(f"  {v['code']:<35} {v['name']}")
            continue

        print("\nAll 3 parameters found. Downloading readings...")

        for target, variable in selected.items():
            try:
                df = get_timeseries(site, variable)
            except Exception as exc:
                print(f"  {target}: download failed - {exc}")
                continue

            if df.empty:
                print(f"  {target}: no readings returned")
                continue

            df["parameter"] = target
            all_downloaded.append(df)
            print(f"  {target}: {len(df)} readings downloaded")
            time.sleep(0.4)

    print("\n" + "=" * 72)
    print("SITE CHECK SUMMARY")
    print("=" * 72)

    if summary_rows:
        summary = pd.DataFrame(summary_rows)
        print(summary.to_string(index=False))
    else:
        print("No sites could be checked.")

    if not all_downloaded:
        print("\nNo complete three-parameter dataset was downloaded yet.")
        return

    long_df = pd.concat(all_downloaded, ignore_index=True)
    long_df["measurement_date"] = long_df["datetime"].dt.strftime("%Y-%m-%d")

    wide = (
        long_df.pivot_table(
            index=["site", "measurement_date"],
            columns="parameter",
            values="value",
            aggfunc="mean",
        )
        .reset_index()
        .rename(columns={"site": "source_id"})
    )

    wide["source_name"] = wide["source_id"].map(site_names).fillna("")
    wide["source_type"] = "Groundwater (Bore)"

    for col in ["ph", "turbidity", "alkalinity"]:
        if col not in wide.columns:
            wide[col] = pd.NA

    wide = wide[
        [
            "source_id",
            "source_name",
            "source_type",
            "measurement_date",
            "ph",
            "turbidity",
            "alkalinity",
        ]
    ].sort_values(["source_id", "measurement_date"])

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d")

    clean_path = os.path.join(
        OUTPUT_DIR, f"groundwater_ph_turbidity_alkalinity_{stamp}.csv"
    )
    raw_path = os.path.join(
        OUTPUT_DIR, f"groundwater_raw_{stamp}.csv"
    )

    wide.to_csv(clean_path, index=False)
    long_df.to_csv(raw_path, index=False)

    print("\nSaved:")
    print(" Clean CSV:", clean_path)
    print(" Raw CSV  :", raw_path)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped by user.")
