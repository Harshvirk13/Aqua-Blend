"""
WMIS Surface Water — Hydrology Scraper v4
==========================================

Builds on the v3 notebook's approach (stations.json for fast station
discovery + webservice.exe for the authoritative fetch), with three changes:

1. FIX: lat/lon extraction. The v3 auto-detector never found real coordinates
   because it looked for keys like "latitude"/"lat"/"Longitude", but the
   actual fields in stations.json are `station_latitude` / `station_longitude`.
2. ADD: `zone` is pulled straight from the station record into station metadata.
3. ADD: Streamflow + Stream Water Level are treated as the primary targets.
   For any station where NEITHER is available, we fall back to trying a
   "capacity" parameter (Storage Water Level, i.e. reservoir/storage level —
   the closest proxy to "capacity" that actually exists as a WQ variable).

IMPORTANT — one thing you need to do before a full run:
   The Storage Water Level variable code is NOT confirmed yet (unlike the
   original 7 params, which were checked against a known stream gauge).
   Run Step 3 below (`confirm_capacity_code`) once, look at the printed
   variable list for a real storage station, and fill in CAPACITY_PARAM_CODE
   with the correct code before doing a full batch run. Until then the
   capacity fallback will just log "capacity code not yet confirmed" and skip.
"""

import json
import os
import time
from datetime import datetime

import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Step 0 — Config
# ---------------------------------------------------------------------------

BASE_URL = "https://data.water.vic.gov.au/WMIS/cgi/webservice.exe"
STATIONS_JSON_URL = "https://data.water.vic.gov.au/WMIS/data/anon/internet/stations/stations.json"

START_TIME = "20230101000000"
END_TIME = "20241231235959"

OUTPUT_DIR = os.path.expanduser("~/Desktop/wmis_export")
os.makedirs(OUTPUT_DIR, exist_ok=True)

CHECKPOINT_FILE = os.path.join(OUTPUT_DIR, "checkpoint_hydro.json")
LONG_CSV = os.path.join(OUTPUT_DIR, "wmis_hydro_long.csv")
SKIPPED_LOG = os.path.join(OUTPUT_DIR, "skipped_stations_hydro.log")
FAILURES_LOG = os.path.join(OUTPUT_DIR, "failures_hydro.log")
STATIONS_CACHE = os.path.join(OUTPUT_DIR, "stations_raw_cache.json")
BATCH_STATE_FILE = os.path.join(OUTPUT_DIR, "current_batch_hydro.json")

REQUEST_DELAY = 0.4
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0
BATCH_SIZE = 20

DATASOURCE = "WQ"

# Primary targets — confirmed against station 225210 (known stream gauge).
PRIMARY_PARAM_CODES = {
    "Streamflow": "141.00",
    "Stream Water Level": "100.00",
}

# Fallback for stations with neither primary param.
# CONFIRMED against stations 226041, 226602, 226605, 226606, 226608 — all
# show variable 130.00 "Storage Water Level (m)" as Available for release
# under datasource "A" (also present under TELEM/PUBLISH, but A is cleanest).
CAPACITY_PARAM_CODE = "130.00"
CAPACITY_DATASOURCE = "A"
CAPACITY_PARAM_NAME = "Storage Water Level"


def hydstra_request(payload: dict, timeout: int = DEFAULT_TIMEOUT) -> dict:
    query = json.dumps(payload, separators=(",", ":"))
    url = f"{BASE_URL}?{query}"

    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            if data.get("error_num", 0) != 0:
                raise RuntimeError(f"API error {data['error_num']}: {data.get('error_msg')}")
            return data
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF * attempt
                print(f"  retrying ({attempt}/{MAX_RETRIES}) after error: {e}")
                time.sleep(wait)
            else:
                raise last_err
    raise last_err


# ---------------------------------------------------------------------------
# Step 1 — Load station metadata (cached)
# ---------------------------------------------------------------------------

def load_raw_stations():
    if os.path.exists(STATIONS_CACHE):
        print("Loading cached stations.json...")
        with open(STATIONS_CACHE) as f:
            return json.load(f)
    print("Downloading stations.json (this may take a minute)...")
    resp = requests.get(STATIONS_JSON_URL, timeout=180)
    resp.raise_for_status()
    raw = resp.json()
    with open(STATIONS_CACHE, "w") as f:
        json.dump(raw, f)
    print("Downloaded and cached.")
    return raw


# ---------------------------------------------------------------------------
# Step 2 — Build cleaned surface-water station table
#           FIX: correct lat/lon field names + zone field added
# ---------------------------------------------------------------------------

def build_stations_df(raw_stations):
    surface_records = [r for r in raw_stations if r.get("sitetype") != "GW"]
    print(f"{len(surface_records)} surface-water station records "
          f"(out of {len(raw_stations)} total)")

    # FIX: stations.json actually uses station_latitude / station_longitude,
    # not "latitude"/"lat"/"Longitude" etc. Keep the old names as fallback
    # candidates in case a future export changes field names again, but put
    # the confirmed real ones first.
    LAT_KEY_CANDIDATES = ["station_latitude", "latitude", "lat", "y"]
    LON_KEY_CANDIDATES = ["station_longitude", "longitude", "lon", "x"]

    def _find_key(records, candidates):
        for key in candidates:
            for r in records:
                if r.get(key) not in (None, ""):
                    return key
        return None

    lat_key = _find_key(surface_records, LAT_KEY_CANDIDATES)
    lon_key = _find_key(surface_records, LON_KEY_CANDIDATES)
    print(f"Using latitude field: {lat_key!r}, longitude field: {lon_key!r}")
    if lat_key is None or lon_key is None:
        print("WARNING: still couldn't find lat/lon fields. Available keys:")
        print(sorted(surface_records[0].keys()) if surface_records else "no records")

    rows = []
    for r in surface_records:
        rows.append({
            "station": r.get("station"),
            "station_name": r.get("station_name"),
            "sitetype": r.get("sitetype"),
            "sitetype_decode": r.get("sitetype_decode"),
            "basin_decode": r.get("basin_decode"),
            "active": r.get("active"),
            "latitude": r.get(lat_key) if lat_key else None,
            "longitude": r.get(lon_key) if lon_key else None,
            "zone": r.get("zone"),          # ADDED
            "parametertype": r.get("parametertype", []),
        })

    df = pd.DataFrame(rows)
    # Drop rows with a genuinely missing station BEFORE converting to string —
    # otherwise pandas turns a real None into the literal text "None", which
    # then looks like a valid (but fake) station ID.
    df = df[df["station"].notna()]
    df["station"] = df["station"].astype(str).str.strip()
    df = df[
        (df["station"] != "")
        & (df["station"] != "0")
        & (df["station"].str.lower() != "none")
        & (df["station"].str.lower() != "nan")
    ]
    df = df.drop_duplicates(subset="station")

    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")

    n_with_coords = df["latitude"].notna().sum()
    print(f"{len(df)} stations after cleanup — {n_with_coords} have coordinates")

    return df


def has_primary_param_slug(parametertype_list):
    """Coarse pre-filter: does this station's slug list even suggest
    streamflow or stream water level (before hitting the live API)?"""
    slugs = [s.lower() for s in parametertype_list]
    return any("streamflow" in s or "streamwaterlevel" in s for s in slugs)


def has_capacity_param_slug(parametertype_list):
    slugs = [s.lower() for s in parametertype_list]
    return any("storagewaterlevel" in s for s in slugs)


# ---------------------------------------------------------------------------
# Step 3 — Confirm the capacity/storage variable code (run this ONCE)
# ---------------------------------------------------------------------------

def confirm_capacity_code(stations_df: pd.DataFrame):
    """
    Finds real stations whose parametertype list contains 'storagewaterlevel'
    and prints their FULL variable list (including ones not currently marked
    "available for release"), so we can see where the storage/reservoir level
    variable actually shows up, even if the first station tried doesn't have
    it live under the WQ datasource.
    """
    candidates = stations_df[
        stations_df["parametertype"].apply(has_capacity_param_slug)
    ]["station"].tolist()

    if not candidates:
        print("No stations with a 'storagewaterlevel' slug found — "
              "capacity fallback may not be available on this network at all.")
        return

    to_try = candidates[:5]
    datasources_to_try = ["WQ", "A", "TELEM", "PUBLISH"]
    print(f"{len(candidates)} candidate storage stations found. "
          f"Checking the first {len(to_try)} across datasources {datasources_to_try}: {to_try}\n")

    found_anything = False
    for test_station in to_try:
        for ds in datasources_to_try:
            try:
                data = hydstra_request({
                    "function": "get_variable_list",
                    "version": 1,
                    "params": {"site_list": test_station, "datasource": ds},
                })
            except Exception as e:
                print(f"--- Station {test_station} (datasource={ds}) --- error: {e}")
                continue

            sites = data.get("return", {}).get("sites", [])
            if not sites:
                continue
            variables = sites[0].get("variables", [])
            if not variables:
                continue

            print(f"--- Station {test_station} (datasource={ds}) ---")
            for v in variables:
                status = v.get("subdesc", "").strip() or "(no status)"
                name = v.get("name", "")
                marker = "  <-- LOOKS LIKE STORAGE/CAPACITY" if (
                    "storage" in name.lower() or "reservoir" in name.lower() or "volume" in name.lower()
                ) else ""
                print(f"  {v.get('variable')}: {name}  [{status}]{marker}")
                if marker:
                    found_anything = True
            print()

    if not found_anything:
        print("--> Still nothing found across WQ / A / TELEM / PUBLISH. "
              "Tell Claude what printed above (or that nothing printed at "
              "all) so we can dig further with a different approach.")
    else:
        print("--> Found a likely match above (marked with <-- LOOKS LIKE "
              "STORAGE/CAPACITY). Set CAPACITY_PARAM_CODE to that variable "
              "code AND set CAPACITY_DATASOURCE to the datasource shown in "
              "that station's header.")


# ---------------------------------------------------------------------------
# Step 4 — Parameter matching, with primary + capacity fallback
# ---------------------------------------------------------------------------

def _periods_overlap(p_start, p_end, target_start, target_end):
    try:
        return not (p_end < target_start or p_start > target_end)
    except Exception:
        return True


def match_hydro_parameters_for_station(station: str):
    """
    Returns (matches, mode, skip_reason).
      mode: "primary" if Streamflow/Stream Water Level found,
            "capacity" if we fell back to storage level,
            None if nothing matched.
    """
    try:
        data = hydstra_request({
            "function": "get_variable_list",
            "version": 1,
            "params": {"site_list": station, "datasource": DATASOURCE},
        })
    except Exception as e:
        return [], None, f"get_variable_list error: {e}"

    sites = data.get("return", {}).get("sites", [])
    if not sites:
        return [], None, "no site entry returned"

    variables = sites[0].get("variables", [])
    if not variables:
        return [], None, "no WQ variables available at this station"

    available = {
        v["variable"]: v
        for v in variables
        if "variable" in v and v.get("subdesc", "").strip().lower() == "available for release"
    }
    if not available:
        return [], None, "WQ variables present but none marked 'Available for release'"

    # --- Try primary params first (Streamflow, Stream Water Level) ---
    matches = []
    for param, code_ in PRIMARY_PARAM_CODES.items():
        if code_ not in available:
            continue
        v = available[code_]
        p_start, p_end = v.get("period_start", ""), v.get("period_end", "")
        if p_start and p_end and not _periods_overlap(p_start, p_end, START_TIME, END_TIME):
            continue
        matches.append({
            "parameter": param,
            "variable_code": code_,
            "datasource": DATASOURCE,
            "matched_name": v.get("name", ""),
        })

    if matches:
        return matches, "primary", None

    # --- Neither primary param available: fall back to capacity ---
    if CAPACITY_PARAM_CODE is None:
        return [], None, "no streamflow/water level, and capacity code not yet confirmed (see confirm_capacity_code)"

    if CAPACITY_DATASOURCE == DATASOURCE:
        capacity_available = available
    else:
        # Capacity lives under a different datasource — look it up separately.
        try:
            cap_data = hydstra_request({
                "function": "get_variable_list",
                "version": 1,
                "params": {"site_list": station, "datasource": CAPACITY_DATASOURCE},
            })
        except Exception as e:
            return [], None, f"get_variable_list error (capacity datasource): {e}"
        cap_sites = cap_data.get("return", {}).get("sites", [])
        if not cap_sites:
            return [], None, "no streamflow/water level, and no site entry under capacity datasource"
        cap_variables = cap_sites[0].get("variables", [])
        capacity_available = {
            v["variable"]: v
            for v in cap_variables
            if "variable" in v and v.get("subdesc", "").strip().lower() == "available for release"
        }

    if CAPACITY_PARAM_CODE in capacity_available:
        v = capacity_available[CAPACITY_PARAM_CODE]
        p_start, p_end = v.get("period_start", ""), v.get("period_end", "")
        if p_start and p_end and not _periods_overlap(p_start, p_end, START_TIME, END_TIME):
            return [], None, "capacity variable exists but no data in target date range"
        return [{
            "parameter": CAPACITY_PARAM_NAME,
            "variable_code": CAPACITY_PARAM_CODE,
            "datasource": CAPACITY_DATASOURCE,
            "matched_name": v.get("name", ""),
        }], "capacity", None

    return [], None, "no streamflow/water level, and no capacity variable at this station"


# ---------------------------------------------------------------------------
# Step 5 — Time series fetch (unchanged logic from v3)
# ---------------------------------------------------------------------------

def get_timeseries(station: str, variable_code: str, datasource: str = DATASOURCE) -> pd.DataFrame:
    payload = {
        "function": "get_ts_traces",
        "version": 2,
        "params": {
            "site_list": station,
            "datasource": datasource,
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


# ---------------------------------------------------------------------------
# Step 6 — Checkpointing + logging
# ---------------------------------------------------------------------------

def load_checkpoint() -> set:
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE) as f:
            return set(tuple(x) for x in json.load(f))
    return set()


def save_checkpoint(done: set):
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(list(done), f)


def append_rows(df: pd.DataFrame):
    header = not os.path.exists(LONG_CSV)
    df.to_csv(LONG_CSV, mode="a", header=header, index=False)


def log_skip(station: str, reason: str):
    with open(SKIPPED_LOG, "a") as f:
        f.write(f"{datetime.now().isoformat()}  station={station}  reason={reason}\n")


def log_failure(station: str, parameter: str, error):
    with open(FAILURES_LOG, "a") as f:
        f.write(f"{datetime.now().isoformat()}  station={station}  parameter={parameter}  error={error}\n")


# ---------------------------------------------------------------------------
# Step 7 — Pipeline: fetch primary params, fall back to capacity, tag with
#          lat/lon + zone
# ---------------------------------------------------------------------------

def process_stations(station_ids, done, station_meta):
    total_rows = 0
    skipped = 0
    capacity_fallback_count = 0

    for i, station in enumerate(station_ids, 1):
        print(f"[{i}/{len(station_ids)}] station {station}", end="  ")
        matches, mode, skip_reason = match_hydro_parameters_for_station(station)

        meta = station_meta.get(station, {})
        station_name = meta.get("station_name")
        latitude = meta.get("latitude")
        longitude = meta.get("longitude")
        zone = meta.get("zone")

        if skip_reason:
            print(f"-> skipped ({skip_reason})")
            log_skip(station, skip_reason)
            skipped += 1
            time.sleep(REQUEST_DELAY)
            continue

        if mode == "capacity":
            capacity_fallback_count += 1
            print(f"-> no streamflow/water level; using capacity fallback ({len(matches)} param)")
        else:
            print(f"-> {len(matches)} primary parameter(s) matched")

        for m in matches:
            key = (station, m["parameter"])
            if key in done:
                continue
            try:
                df = get_timeseries(station, m["variable_code"], m["datasource"])
            except Exception as e:
                print(f"    {m['parameter']}: fetch failed ({e})")
                log_failure(station, m["parameter"], e)
                time.sleep(REQUEST_DELAY)
                continue

            if not df.empty:
                df["station"] = station
                df["station_name"] = station_name
                df["latitude"] = latitude
                df["longitude"] = longitude
                df["zone"] = zone
                df["parameter"] = m["parameter"]
                df["parameter_mode"] = mode  # "primary" or "capacity"
                df["variable_code"] = m["variable_code"]
                df["datasource"] = m["datasource"]
                df["matched_variable_name"] = m["matched_name"]
                df = df[["station", "station_name", "latitude", "longitude", "zone",
                          "parameter", "parameter_mode", "variable_code", "datasource",
                          "matched_variable_name", "datetime", "value", "quality_code"]]
                append_rows(df)
                total_rows += len(df)
                print(f"    {m['parameter']}: {len(df)} rows (running total {total_rows})")
            else:
                print(f"    {m['parameter']}: no data in date range")

            done.add(key)
            save_checkpoint(done)
            time.sleep(REQUEST_DELAY)

    return total_rows, skipped, capacity_fallback_count


# ---------------------------------------------------------------------------
# Step 8 — Batch runner
# ---------------------------------------------------------------------------

def run_next_batch(candidate_stations, station_meta):
    n_batches = (len(candidate_stations) - 1) // BATCH_SIZE + 1

    if os.path.exists(BATCH_STATE_FILE):
        with open(BATCH_STATE_FILE) as f:
            next_batch_num = json.load(f)["next_batch"]
    else:
        next_batch_num = 1

    if next_batch_num > n_batches:
        print(f"All {n_batches} batches already completed.")
        return

    batch_start = (next_batch_num - 1) * BATCH_SIZE
    batch_stations = candidate_stations[batch_start:batch_start + BATCH_SIZE]
    batch_end = batch_start + len(batch_stations)

    print(f"\n=== Running batch {next_batch_num}/{n_batches}: "
          f"stations {batch_start + 1}-{batch_end} ===")

    done = load_checkpoint()
    total_rows, skipped, capacity_count = process_stations(batch_stations, done, station_meta)

    print(f"\nBatch {next_batch_num} done. {total_rows} rows written, "
          f"{skipped} stations skipped, {capacity_count} used the capacity fallback.")

    with open(BATCH_STATE_FILE, "w") as f:
        json.dump({"next_batch": next_batch_num + 1}, f)

    remaining = n_batches - next_batch_num
    print(f"Re-run to process batch {next_batch_num + 1} "
          f"({'none remaining' if remaining <= 0 else f'{remaining} batches left'}).")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    raw = load_raw_stations()
    stations_df = build_stations_df(raw)

    station_meta = stations_df.set_index("station")[
        ["station_name", "latitude", "longitude", "zone"]
    ].to_dict("index")

    # Pre-filter: keep any station that plausibly has streamflow, water
    # level, OR storage/capacity data, before hitting the live API.
    relevant = stations_df[
        stations_df["parametertype"].apply(
            lambda p: has_primary_param_slug(p) or has_capacity_param_slug(p)
        )
    ]
    candidate_stations = relevant["station"].tolist()
    print(f"{len(candidate_stations)} / {len(stations_df)} stations look relevant "
          f"(streamflow, water level, or storage level)")

    # --- STEP A: run with only this line active first. It will print a real
    #     storage station's variable list. Find the storage/reservoir level
    #     row in that printout, copy its variable code, and paste it into
    #     CAPACITY_PARAM_CODE near the top of this file. ---
    if CAPACITY_PARAM_CODE is None:
        confirm_capacity_code(stations_df)
        print("\nCAPACITY_PARAM_CODE is not set yet — set it above using the "
              "output printed here, then re-run this script to start extracting.")
    else:
        # --- STEP B: once CAPACITY_PARAM_CODE is set, this runs the actual
        #     extraction, one batch of 20 stations at a time. Re-run the
        #     script repeatedly (e.g. in a loop, or via cron) to work through
        #     all candidate stations. Progress is checkpointed, so it's safe
        #     to stop and resume. ---
        run_next_batch(candidate_stations, station_meta)