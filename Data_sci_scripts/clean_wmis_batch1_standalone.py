"""
FULL STANDALONE script to repair and clean wmis_batch1.csv.

This is self-contained - it does NOT require clean_water_quality.py or
any other file from this project. Only pandas/openpyxl (both standard
data-science packages) are needed.

Produces the Supabase target schema:

    source_id, source_name, source_type, capacity_ml,
    measurement_datetime, cost_per_ml, ph, alkalinity, turbidity,
    water_temperature, colour

STEP 1 - REPAIR (specific to wmis_batch1.csv)
-----------------------------------------------
wmis_batch1.csv has a raw data corruption: for 34 of its 52 stations,
one or two fields are missing mid-row in the source file, silently
shifting every value after that point left by 1 or 2 columns.

  Pattern A (122,808 rows / 36 stations, e.g. station 227200):
    'station_name' is missing entirely, so what should be in
    'parameter' lands in 'station_name', what should be in
    'variable_code' lands in 'parameter', and so on - everything one
    column left of where it belongs.

  Pattern B (8,041 rows / 2 stations, e.g. station 226402):
    'station_name' is present and correct, but BOTH 'parameter' and
    'variable_code' are missing, shifting everything from 'datasource'
    onward two columns left instead of one.

Both patterns are detected by checking which column an unmistakably
parameter-like value (pH / Turbidity / Water Temperature / Salinity
(EC) / Streamflow / Stream Water Level / Alkalinity) has landed in,
and the repair is confirmed by checking that 'datasource' is 'WQ' for
every row afterward (it wasn't, before the fix).

NOT recoverable: for the 36 Pattern-A stations, the real station_name
was dropped from the source file entirely and doesn't exist anywhere
else in the file, so source_name/source_type are left blank for those
rows (24,854 of them). Pattern-B's quality_code has nowhere left to
shift into and is also left blank for those 8,041 rows.

STEP 2 - CLEAN (same logic as the general-purpose cleaning script)
---------------------------------------------------------------------
After repair, the file is in normal long/tidy format (one row per
station+parameter+date) and is pivoted into the wide target schema:
only ph, turbidity, water_temperature, alkalinity, colour are kept
(Streamflow, Stream Water Level, Salinity (EC) have no column in this
schema and are dropped). source_type is inferred from keywords in
source_name (River/Creek/Drain/Lake/Reservoir, including the "R"
abbreviation e.g. "MORWELL R"), formatted as "Surface Water (X)".
capacity_ml and cost_per_ml have no source in this raw file and are
always blank. measurement_datetime is normalised to YYYY/MM/DD.

USAGE
-----
    python3 clean_wmis_batch1_standalone.py wmis_batch1.csv [--out OUTPUT.csv]

If --out is omitted, output is written next to the input as
<input_stem>_cleaned.csv
"""

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

TARGET_COLUMNS = [
    "source_id",
    "source_name",
    "source_type",
    "capacity_ml",
    "measurement_datetime",
    "cost_per_ml",
    "ph",
    "alkalinity",
    "turbidity",
    "water_temperature",
    "colour",
]

# Parameter names used to detect which column a row's values have
# shifted into (see module docstring for the two corruption patterns).
KNOWN_PARAMETER_NAMES = {
    "pH", "Streamflow", "Stream Water Level", "Salinity (EC)",
    "Water Temperature", "Turbidity", "Alkalinity",
}

# Maps a source 'parameter' value -> target schema column name.
# Parameters with no entry here (Streamflow, Salinity (EC), Stream
# Water Level) are dropped, since this schema has no column for them.
PARAMETER_ALIASES = {
    "ph": "ph",
    "turbidity": "turbidity",
    "alkalinity": "alkalinity",
    "water temperature": "water_temperature",
    "colour": "colour",
}

# Keyword -> source_type, checked in this order against source_name.
# Regex word-boundaries so e.g. "R" only matches as a standalone token
# (abbreviation for River, as seen in "MORWELL R @ YALLOURN"), not
# inside another word.
SOURCE_TYPE_KEYWORDS = [
    (r"RESERVOIR", "Surface Water (Reservoir)"),
    (r"RIVER", "Surface Water (River)"),
    (r"\bR\b", "Surface Water (River)"),
    (r"CREEK", "Surface Water (Creek)"),
    (r"DRAIN", "Surface Water (Drain)"),
    (r"LAKE", "Surface Water (Lake)"),
]


def infer_source_type(source_name):
    if not source_name:
        return None
    upper = str(source_name).upper()
    for pattern, label in SOURCE_TYPE_KEYWORDS:
        if re.search(pattern, upper):
            return label
    return None


def fix_datetime(val):
    """Parse an 'M/D/YY' text date (confirmed format for this file -
    dates increment day-by-day within a month) into YYYY/MM/DD."""
    s = str(val).strip()
    if not s or s.lower() == "nan":
        return None
    m, d, y = s.split("/")
    y = int(y)
    y += 2000 if y < 70 else 1900
    return f"{y:04d}/{int(m):02d}/{int(d):02d}"


def repair(raw_path: Path) -> pd.DataFrame:
    """Detect and fix the two column-shift corruption patterns."""
    df = pd.read_csv(raw_path, encoding="utf-8-sig", low_memory=False, dtype=str)

    mask_a = df["station_name"].isin(KNOWN_PARAMETER_NAMES)
    mask_b = df["datasource"].isin(KNOWN_PARAMETER_NAMES) & ~mask_a

    print(f"Pattern A rows (missing station_name, 1-column shift): {mask_a.sum()}")
    print(f"Pattern B rows (missing parameter+variable_code, 2-column shift): {mask_b.sum()}")

    fixed = df.copy()

    subA = df.loc[mask_a]
    fixed.loc[mask_a, "parameter"] = subA["station_name"].values
    fixed.loc[mask_a, "variable_code"] = subA["parameter"].values
    fixed.loc[mask_a, "datasource"] = subA["variable_code"].values
    fixed.loc[mask_a, "matched_variable_name"] = subA["datasource"].values
    fixed.loc[mask_a, "datetime"] = subA["matched_variable_name"].values
    fixed.loc[mask_a, "value"] = subA["datetime"].values
    fixed.loc[mask_a, "quality_code"] = subA["value"].values
    fixed.loc[mask_a, "station_name"] = pd.NA

    subB = df.loc[mask_b]
    fixed.loc[mask_b, "parameter"] = subB["datasource"].values
    fixed.loc[mask_b, "variable_code"] = subB["matched_variable_name"].values
    fixed.loc[mask_b, "datasource"] = subB["datetime"].values
    fixed.loc[mask_b, "matched_variable_name"] = subB["value"].values
    fixed.loc[mask_b, "datetime"] = subB["quality_code"].values
    if "Unnamed: 9" in subB.columns:
        fixed.loc[mask_b, "value"] = subB["Unnamed: 9"].values
    fixed.loc[mask_b, "quality_code"] = pd.NA

    still_bad = (fixed["datasource"] != "WQ").sum()
    print(f"Rows where 'datasource' still isn't 'WQ' after repair (should be 0): {still_bad}")
    if still_bad:
        print("WARNING: repair may be incomplete - inspect these rows before trusting the output.", file=sys.stderr)

    return fixed


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Pivot the repaired long/tidy data into the wide target schema."""
    df = df.copy()
    df.columns = [c.strip() for c in df.columns]

    known_params = [p for p in df["parameter"].dropna().unique() if p.strip().lower() in PARAMETER_ALIASES]
    dropped_params = sorted(set(df["parameter"].dropna().unique()) - set(known_params))
    if dropped_params:
        print(f"WARNING: dropping parameters with no target-schema column: {dropped_params}", file=sys.stderr)

    df = df[df["parameter"].str.strip().str.lower().isin(PARAMETER_ALIASES)].copy()
    df["target_col"] = df["parameter"].str.strip().str.lower().map(PARAMETER_ALIASES)
    df["measurement_datetime"] = df["datetime"].apply(fix_datetime)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    # pivot_table silently DROPS rows whose group key (station_name here)
    # is NaN, which would silently discard entire stations since many of
    # them have a genuinely missing (unrecoverable) station_name after
    # repair. Substitute a sentinel so those rows survive the pivot,
    # then restore the true missing value afterwards.
    _MISSING_NAME = "\x00__MISSING_STATION_NAME__\x00"
    df["station_name"] = df["station_name"].fillna(_MISSING_NAME)

    pivot = df.pivot_table(
        index=["station", "station_name", "measurement_datetime"],
        columns="target_col",
        values="value",
        aggfunc="first",
    ).reset_index()

    pivot["station_name"] = pivot["station_name"].replace(_MISSING_NAME, None)

    pivot = pivot.rename(columns={"station": "source_id", "station_name": "source_name"})
    pivot["source_id"] = pivot["source_id"].astype(int)
    pivot["source_type"] = pivot["source_name"].apply(infer_source_type)

    for col in TARGET_COLUMNS:
        if col not in pivot.columns:
            pivot[col] = None
    pivot = pivot[TARGET_COLUMNS]

    # --- QA checks ---
    missing_type = pivot["source_type"].isna().sum()
    if missing_type:
        print(f"WARNING: {missing_type} rows have a source_name that didn't match any known "
              f"source_type keyword (River/Creek/Drain/Lake/Reservoir) - source_type left blank.", file=sys.stderr)
    print("NOTE: 'capacity_ml' has no data in this raw source - left blank.", file=sys.stderr)
    print("NOTE: 'cost_per_ml' has no data in this raw source - left blank.", file=sys.stderr)

    print(f"Total cleaned rows: {len(pivot)}")
    print("Rows per source_id:")
    print(pivot["source_id"].value_counts().to_string())

    dupmask = pivot.duplicated(subset=["source_id", "measurement_datetime"], keep=False)
    print(f"Duplicate source_id + measurement_datetime combos: {dupmask.sum()}")

    pivot["_sort_dt"] = pd.to_datetime(pivot["measurement_datetime"], format="%Y/%m/%d", errors="coerce")
    pivot = pivot.sort_values(["source_id", "_sort_dt"]).drop(columns="_sort_dt").reset_index(drop=True)

    return pivot


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path, help="Path to the raw wmis_batch1.csv file")
    parser.add_argument("--out", type=Path, default=None, help="Output CSV path")
    args = parser.parse_args()

    out_path = args.out or args.input.with_name(args.input.stem + "_cleaned.csv")

    repaired_df = repair(args.input)
    cleaned_df = clean(repaired_df)
    cleaned_df.to_csv(out_path, index=False)

    print(f"\nWrote {len(cleaned_df)} rows to {out_path}")


if __name__ == "__main__":
    main()
