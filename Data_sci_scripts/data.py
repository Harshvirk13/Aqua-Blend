import json
import os
import time

import pandas as pd
import requests

BASE_URL = "https://data.water.vic.gov.au/WMIS/cgi/webservice.exe"

STATION = "225210"  # THOMSON RIVER @ THE NARROWS
DATASOURCE = "WQ"   # water quality datasource (confirmed via get_variable_list)
START_TIME = "20230101000000"
END_TIME = "20241231235959"

# Where to save the output CSVs. Defaults to your Desktop to avoid
# permission issues some folders (e.g. Downloads) can have with scripts.
# Change this to any folder you like, e.g. os.path.expanduser("~/Documents")
OUTPUT_DIR = r"C:\Users\91817\OneDrive\Desktop\AQUA CODES"

# Variable codes confirmed against the live API's get_variable_list response
VARIABLES = {
    "pH": "210.00",
    "Water Temperature (C)": "450.00",
    "Turbidity (NTU)": "810.00",
    "Conductivity/Salinity (uS/cm)": "820.00",
    "Total Suspended Solids (mg/L)": "2172.00",
    "Total Phosphorus (mg/L)": "2363.00",
    "Kjeldahl Nitrogen (mg/L)": "2336.00",
}


def hydstra_request(payload: dict, timeout: int = 30) -> dict:
    """
    Call the Hydstra webservice.exe endpoint.

    IMPORTANT: the JSON payload must be appended to the URL RAW (unencoded
    braces/quotes/commas) -- this is confirmed working. Do NOT url-encode it
    or pass it via requests' `params=` kwarg, both of which cause the server
    to fail to parse the request (error_num 120, "missing top-level" items).
    """
    query = json.dumps(payload, separators=(",", ":"))
    url = f"{BASE_URL}?{query}"

    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()

    if data.get("error_num", 0) != 0:
        raise RuntimeError(f"API error {data['error_num']}: {data.get('error_msg')}")

    return data


def get_timeseries(variable_code: str, station: str = STATION) -> pd.DataFrame:
    """Fetch a daily-mean time series for one variable code at one station."""
    payload = {
        "function": "get_ts_traces",
        "version": 2,
        "params": {
            "site_list": station,
            "datasource": DATASOURCE,
            "varfrom": variable_code,
            "varto": variable_code,
            "start_time": START_TIME,
            "end_time": END_TIME,
            "interval": "day",
            "data_type": "mean",
            "multiplier": "1",
        },
    }
    data = hydstra_request(payload)

    traces = data.get("return", {}).get("traces", [])
    if not traces:
        return pd.DataFrame()

    points = traces[0].get("trace", [])
    df = pd.DataFrame(points)
    if df.empty:
        return df

    df = df.rename(columns={"v": "value", "t": "datetime", "q": "quality_code"})
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["datetime"] = pd.to_datetime(df["datetime"].astype(str), format="%Y%m%d%H%M%S")
    return df[["datetime", "value", "quality_code"]]


def main():
    all_frames = []

    for label, code in VARIABLES.items():
        print(f"Fetching {label} (code {code}) ...")
        try:
            df = get_timeseries(code)
        except RuntimeError as e:
            print(f"  -> error: {e}")
            continue

        if df.empty:
            print("  -> no data returned for this period")
            continue

        df["variable"] = label
        df["variable_code"] = code
        all_frames.append(df)
        print(f"  -> {len(df)} records")
        time.sleep(0.5)  # be polite to the API

    if not all_frames:
        print("No data collected.")
        return

    combined = pd.concat(all_frames, ignore_index=True)
    combined = combined[["datetime", "variable", "variable_code", "value", "quality_code"]]
    combined = combined.sort_values(["variable", "datetime"])

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    out_file = os.path.join(OUTPUT_DIR, "thomson_river_narrows_water_quality.csv")
    combined.to_csv(out_file, index=False)
    print(f"\nSaved {len(combined)} rows across {len(all_frames)} variables to {out_file}")

    # Optional: also save a pivoted wide-format version (one column per variable)
    wide = combined.pivot_table(index="datetime", columns="variable", values="value")
    wide_file = os.path.join(OUTPUT_DIR, "thomson_river_narrows_water_quality_wide.csv")
    wide.to_csv(wide_file)
    print(f"Also saved wide-format version to {wide_file}")


if __name__ == "__main__":
    main()