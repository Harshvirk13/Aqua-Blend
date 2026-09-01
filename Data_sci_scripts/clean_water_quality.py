"""
Water Quality Data Cleaning Script
Aquablend Capstone — Data Engineering Team

Transforms raw "wide" format river water quality exports into the
standardised "clean" schema used for Supabase insertion:
    site_id, source_name, measurement_date, <parameter columns>

Usage:
    python clean_water_quality.py
"""

import pandas as pd
from pathlib import Path

# ---------------------------------------------------------------------
# 1. Site configuration
#    Add one entry per river/site. Each entry defines:
#      - input_file: raw wide CSV
#      - output_file: cleaned CSV to produce
#      - site_id: numeric site identifier
#      - source_name: official site name
#      - column_map: raw column name -> clean column name
# ---------------------------------------------------------------------
SITE_CONFIG = {
    "barwon": {
        "input_file": "barwon_river_water_quality_wide.csv",
        "output_file": "barwon_river_water_quality_clean.csv",
        "site_id": 233217,
        "source_name": "BARWON RIVER @ GEELONG",
        "column_map": {
            "datetime": "measurement_date",
            "Conductivity/Salinity (uS/cm)": "Conductivity/Salinity (uS/cm)",
            "Kjeldahl Nitrogen (mg/L)": "Kjeldahl Nitrogen (mg/L)",
            "Total Phosphorus (mg/L)": "Total Phosphorus (mg/L)",
            "Total Suspended Solids (mg/L)": "TSS (mg/L)",
            "Turbidity (NTU)": "Turbidity (NTU)",
            "Water Temperature (C)": "Water Temperature (C)",
            "pH": "PH Value",
        },
    },
    "yarra": {
        "input_file": "yarra_river_water_quality_wide.csv",
        "output_file": "yarra_river_water_quality_clean.csv",
        "site_id": 229200,
        "source_name": "YARRA RIVER @ WARRANDYTE",
        "column_map": {
            "datetime": "measurement_date",
            "Conductivity/Salinity (uS/cm)": "Conductivity/Salinity (uS/cm)",
            "Turbidity (NTU)": "Turbidity (NTU)",
            "Water Temperature (C)": "Water Temperature (C)",
            "pH": "PH Value",
        },
    },
}


def clean_site_data(config: dict) -> pd.DataFrame:
    """Load a raw wide CSV and transform it into the clean schema."""

    df = pd.read_csv(config["input_file"])

    # --- basic quality checks before transforming -------------------
    n_before = len(df)
    df = df.drop_duplicates(subset="datetime")           # drop duplicate readings
    df = df.dropna(how="all")                             # drop fully empty rows
    n_after = len(df)
    if n_before != n_after:
        print(f"  removed {n_before - n_after} duplicate/empty rows")

    # --- parse and standardise the date column -----------------------
    df["datetime"] = pd.to_datetime(df["datetime"], format="%d-%m-%Y", errors="coerce")
    bad_dates = df["datetime"].isna().sum()
    if bad_dates:
        print(f"  warning: {bad_dates} unparseable dates dropped")
        df = df.dropna(subset=["datetime"])
    df["datetime"] = df["datetime"].dt.strftime("%d-%m-%Y")

    # --- flag out-of-range / negative readings for numeric columns ---
    numeric_cols = [c for c in df.columns if c != "datetime"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        neg_count = (df[col] < 0).sum()
        if neg_count:
            print(f"  warning: {neg_count} negative values in '{col}' set to NaN")
            df.loc[df[col] < 0, col] = pd.NA

    # --- rename columns to the clean schema --------------------------
    df = df.rename(columns=config["column_map"])

    # --- add site metadata --------------------------------------------
    df.insert(0, "site_id", config["site_id"])
    df.insert(1, "source_name", config["source_name"])

    # --- reorder: site_id, source_name, measurement_date, then params
    ordered_cols = ["site_id", "source_name", "measurement_date"] + [
        c for c in df.columns if c not in ("site_id", "source_name", "measurement_date")
    ]
    df = df[ordered_cols]

    return df


def main():
    for site_key, config in SITE_CONFIG.items():
        print(f"Cleaning {site_key}...")
        if not Path(config["input_file"]).exists():
            print(f"  skipped: '{config['input_file']}' not found")
            continue
        clean_df = clean_site_data(config)
        clean_df.to_csv(config["output_file"], index=False)
        print(f"  wrote {len(clean_df)} rows -> {config['output_file']}\n")


if __name__ == "__main__":
    main()
