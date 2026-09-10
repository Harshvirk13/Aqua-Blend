"""
FULL STANDALONE script to clean WMIS_Batch2.csv.

This is self-contained - it does NOT require clean_water_quality.py or
any other file from this project. Only pandas (a standard data-science
package) is needed.

Produces the Supabase target schema:

    source_id, source_name, source_type, capacity_ml,
    measurement_datetime, cost_per_ml, ph, alkalinity, turbidity,
    water_temperature, colour

WHAT THIS SCRIPT DOES
-----------------------
WMIS_Batch2.csv is in long/tidy format: one row per station + parameter
+ date, with a 'parameter' column naming the measurement and a 'value'
column holding the number (e.g. one row for a station's pH on a given
day, another row for that same station's Turbidity on that same day).
This script PIVOTS that into one row per station+date, with each
parameter spread into its own column.

Only parameters with a home in the target schema are kept: pH,
Turbidity, Water Temperature. Alkalinity is also kept if present.
Streamflow, Stream Water Level, and Salinity (EC) are DROPPED, since
this schema has no column for them.

WHY THIS SCRIPT EXISTS (the date bug it fixes)
-------------------------------------------------
Different stations in this file store their date in TWO different
encodings:
  - some stations: a plain Excel serial number as text (e.g. "44927",
    meaning 44927 days after 1899-12-30)
  - other stations: a US-style "M/D/YY" text string (e.g. "1/1/23")

This was confirmed by checking that dates within a station increment
day-by-day within a month (e.g. 1/1/23, 1/2/23 ... 1/9/23, 1/10/23,
1/11/23 - which only makes sense as month/day, not day/month). Both
encodings are detected per-cell and converted to a single consistent
YYYY/MM/DD format.

OTHER NOTES
------------
- source_type is inferred from keywords in source_name: River / Creek
  / Drain / Lake, formatted as "Surface Water (X)". This file has no
  reservoirs.
- capacity_ml, cost_per_ml, colour have no data anywhere in this raw
  file and are always blank.
- quality_code, variable_code, datasource, matched_variable_name exist
  in the raw file but have no column in this schema - dropped.

USAGE
-----
    python3 clean_wmis_batch2_standalone.py WMIS_Batch2.csv [--out OUTPUT.csv]

If --out is omitted, output is written next to the input as
<input_stem>_cleaned.csv
"""

import argparse
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

EXCEL_EPOCH = datetime(1899, 12, 30)

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
# Regex word-boundary on "R" so it only matches as a standalone token
# (an abbreviation for River seen in some WMIS station names), not
# inside another word.
SOURCE_TYPE_KEYWORDS = [
    (r"RESERVOIR", "Surface Water (On-stream Reservoir)"),
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
    """Return YYYY/MM/DD, or None. Handles both date encodings seen in
    this file: pure-digit Excel serial numbers, and 'M/D/YY' text.
    On any unexpected format, logs a warning and returns None rather
    than raising, so one bad cell doesn't kill the whole run."""
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() == "nan":
        return None

    if s.isdigit():
        try:
            d = EXCEL_EPOCH + timedelta(days=int(s))
            return d.strftime("%Y/%m/%d")
        except (OverflowError, ValueError) as e:
            print(f"WARNING: invalid Excel serial date '{s}' ({e}) - treating as missing", file=sys.stderr)
            return None

    parts = s.split("/")
    if len(parts) != 3:
        print(f"WARNING: unexpected date format '{s}' (expected M/D/YY or a serial number) - treating as missing", file=sys.stderr)
        return None

    m, d, y = parts
    try:
        m, d, y = int(m), int(d), int(y)
    except ValueError:
        print(f"WARNING: non-numeric date parts in '{s}' - treating as missing", file=sys.stderr)
        return None

    y += 2000 if y < 70 else 1900

    try:
        # Validates the date is real (catches e.g. month=13, day=32)
        datetime(y, m, d)
    except ValueError:
        print(f"WARNING: invalid calendar date '{s}' (parsed as {y:04d}/{m:02d}/{d:02d}) - treating as missing", file=sys.stderr)
        return None

    return f"{y:04d}/{m:02d}/{d:02d}"


def clean(path: Path) -> pd.DataFrame:
    # utf-8-sig quietly strips a BOM if present, common in WMIS exports
    df = pd.read_csv(path, encoding="utf-8-sig", low_memory=False, dtype=str)
    df.columns = [c.strip() for c in df.columns]

    known_params = [p for p in df["parameter"].dropna().unique() if p.strip().lower() in PARAMETER_ALIASES]
    dropped_params = sorted(set(df["parameter"].dropna().unique()) - set(known_params))
    if dropped_params:
        print(f"WARNING: dropping parameters with no target-schema column: {dropped_params}", file=sys.stderr)

    df = df[df["parameter"].str.strip().str.lower().isin(PARAMETER_ALIASES)].copy()
    df["target_col"] = df["parameter"].str.strip().str.lower().map(PARAMETER_ALIASES)
    df["measurement_datetime"] = df["datetime"].apply(fix_datetime)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    # --- Check for duplicate station/date/parameter combos before pivoting ---
    # pivot_table's aggfunc="first" below would otherwise silently keep
    # only the first reading and drop any others for the same combo.
    dup_mask = df.duplicated(subset=["station", "measurement_datetime", "target_col"], keep=False)
    if dup_mask.any():
        dup_rows = df[dup_mask].sort_values(["station", "measurement_datetime", "target_col"])
        print(f"WARNING: {dup_mask.sum()} rows share the same station/date/parameter - "
              f"only the first value will be kept, others dropped:", file=sys.stderr)
        print(dup_rows[["station", "station_name", "measurement_datetime", "target_col", "value"]].to_string(), file=sys.stderr)

    pivot = df.pivot_table(
        index=["station", "station_name", "measurement_datetime"],
        columns="target_col",
        values="value",
        aggfunc="first",
    ).reset_index()

    pivot = pivot.rename(columns={"station": "source_id", "station_name": "source_name"})

    # --- Validate station IDs before converting to int ---
    # A blank or non-numeric ID would otherwise make astype(int) raise
    # and crash the whole script.
    bad_id_mask = ~pivot["source_id"].astype(str).str.strip().str.isdigit()
    if bad_id_mask.any():
        bad_ids = pivot.loc[bad_id_mask, "source_id"].tolist()
        print(f"WARNING: {bad_id_mask.sum()} rows have a blank or non-numeric station ID "
              f"and will be dropped: {bad_ids}", file=sys.stderr)
        pivot = pivot[~bad_id_mask].copy()

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
              f"source_type keyword (River/Creek/Drain/Lake) - source_type left blank.", file=sys.stderr)
    print("NOTE: 'capacity_ml', 'cost_per_ml', 'colour' have no data in this raw source - left blank.", file=sys.stderr)

    print(f"Total cleaned rows: {len(pivot)}")
    print("Rows per source_id:")
    print(pivot["source_id"].value_counts().to_string())

    dupmask = pivot.duplicated(subset=["source_id", "measurement_datetime"], keep=False)
    print(f"Duplicate source_id + measurement_datetime combos: {dupmask.sum()}")
    if dupmask.sum():
        print(pivot[dupmask].sort_values(["source_id", "measurement_datetime"]).to_string())

    pivot["_sort_dt"] = pd.to_datetime(pivot["measurement_datetime"], format="%Y/%m/%d", errors="coerce")
    pivot = pivot.sort_values(["source_id", "_sort_dt"]).drop(columns="_sort_dt").reset_index(drop=True)

    return pivot


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path, help="Path to the raw WMIS_Batch2.csv file")
    parser.add_argument("--out", type=Path, default=None, help="Output CSV path")
    args = parser.parse_args()

    out_path = args.out or args.input.with_name(args.input.stem + "_cleaned.csv")

    df = clean(args.input)
    df.to_csv(out_path, index=False)
    print(f"\nWrote {len(df)} rows to {out_path}")


if __name__ == "__main__":
    main()