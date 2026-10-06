
import os
import re
from datetime import datetime, timedelta

import pandas as pd


# Final Supabase / Final_data columns
FINAL_COLUMNS = [
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
    "colour"
]


# Parameters we want to keep from the raw files
PARAMETER_MAP = {
    "ph": "ph",
    "ph value": "ph",
    "ph value(ph)": "ph",
    "turbidity": "turbidity",
    "turbidity (ntu)": "turbidity",
    "turbidity(ntu)": "turbidity",
    "alkalinity": "alkalinity",
    "water temperature": "water_temperature",
    "water temperature (c)": "water_temperature",
    "water temperature(c)": "water_temperature",
    "colour": "colour",
    "colour(pcu)": "colour",
    "color": "colour"
}


# Used when reading wide files
COLUMN_MAP = {
    "source_id": "source_id",
    "site_id": "source_id",
    "station": "source_id",
    "station_id": "source_id",

    "source_name": "source_name",
    "station_name": "source_name",
    "name": "source_name",

    "measurement_datetime": "measurement_datetime",
    "measurement_date": "measurement_datetime",
    "datetime": "measurement_datetime",
    "date": "measurement_datetime",

    "ph": "ph",
    "ph value": "ph",
    "ph value(ph)": "ph",

    "turbidity": "turbidity",
    "turbidity (ntu)": "turbidity",
    "turbidity(ntu)": "turbidity",

    "alkalinity": "alkalinity",

    "water temperature": "water_temperature",
    "water temperature (c)": "water_temperature",
    "water temperature(c)": "water_temperature",

    "colour": "colour",
    "colour(pcu)": "colour",
    "color": "colour",

    "capacity_ml": "capacity_ml",
    "cost_per_ml": "cost_per_ml"
}


KNOWN_PARAMETERS = [
    "ph",
    "turbidity",
    "water temperature",
    "alkalinity",
    "colour",
    "streamflow",
    "stream water level",
    "salinity (ec)"
]


# ------------------------------------------------------------
# Small helper functions
# ------------------------------------------------------------

def clean_text(value):
    if pd.isna(value):
        return ""
    return str(value).strip().lower()


def get_source_type(name):
    if pd.isna(name):
        return None

    name = str(name).upper()

    if "RESERVOIR" in name:
        return "Surface Water (Reservoir)"
    elif "RIVER" in name or re.search(r"\bR\b", name):
        return "Surface Water (River)"
    elif "CREEK" in name:
        return "Surface Water (Creek)"
    elif "DRAIN" in name:
        return "Surface Water (Drain)"
    elif "LAKE" in name:
        return "Surface Water (Lake)"

    return None


def fix_date(value, dayfirst=False):
    if pd.isna(value):
        return None

    text = str(value).strip()

    if text == "" or text.lower() in ["nan", "nat", "none"]:
        return None

    # Excel serial number
    try:
        number = float(text)
        if text.replace(".", "", 1).isdigit() and 10000 <= number <= 100000:
            excel_start = datetime(1899, 12, 30)
            date = excel_start + timedelta(days=int(number))
            return date.strftime("%Y/%m/%d")
    except:
        pass

    # Try normal date conversion
    date = pd.to_datetime(text, errors="coerce", dayfirst=dayfirst)

    if pd.isna(date):
        return None

    return date.strftime("%Y/%m/%d")


def make_final_format(df):
    df = df.copy()

    # Add missing columns
    for col in FINAL_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA

    # Convert numeric columns
    numeric_cols = [
        "source_id",
        "capacity_ml",
        "cost_per_ml",
        "ph",
        "alkalinity",
        "turbidity",
        "water_temperature",
        "colour"
    ]

    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Fill source type if it is missing
    for i in df.index:
        if pd.isna(df.loc[i, "source_type"]) or str(df.loc[i, "source_type"]).strip() == "":
            df.loc[i, "source_type"] = get_source_type(df.loc[i, "source_name"])

    # Standardise date
    df["measurement_datetime"] = df["measurement_datetime"].apply(fix_date)

    # Remove rows without ID or date
    df = df.dropna(subset=["source_id", "measurement_datetime"])

    # Remove invalid pH
    if "ph" in df.columns:
        bad_ph = (df["ph"] < 0) | (df["ph"] > 14)
        df.loc[bad_ph, "ph"] = pd.NA

    # Remove exact duplicate rows
    df = df.drop_duplicates()

    # Sort data
    df["_date_sort"] = pd.to_datetime(
        df["measurement_datetime"],
        format="%Y/%m/%d",
        errors="coerce"
    )

    df = df.sort_values(
        by=["source_id", "_date_sort"]
    ).drop(columns="_date_sort")

    df = df.reset_index(drop=True)

    return df[FINAL_COLUMNS]


# ------------------------------------------------------------
# Batch 1 repair
# ------------------------------------------------------------

def repair_batch1(df):
    # Object type makes it easier to move mixed text/numeric values between columns
    df = df.astype(object).copy()

    # Batch 1 has some shifted rows
    pattern_a = df["station_name"].astype(str).str.strip().str.lower().isin(KNOWN_PARAMETERS)

    pattern_b = (
        df["datasource"].astype(str).str.strip().str.lower().isin(KNOWN_PARAMETERS)
        & ~pattern_a
    )

    # Pattern A
    if pattern_a.any():
        old = df.loc[pattern_a].copy()

        df.loc[pattern_a, "parameter"] = old["station_name"].values
        df.loc[pattern_a, "variable_code"] = old["parameter"].values
        df.loc[pattern_a, "datasource"] = old["variable_code"].values
        df.loc[pattern_a, "matched_variable_name"] = old["datasource"].values
        df.loc[pattern_a, "datetime"] = old["matched_variable_name"].values
        df.loc[pattern_a, "value"] = old["datetime"].values
        df.loc[pattern_a, "quality_code"] = old["value"].values
        df.loc[pattern_a, "station_name"] = pd.NA

    # Pattern B
    if pattern_b.any():
        old = df.loc[pattern_b].copy()

        df.loc[pattern_b, "parameter"] = old["datasource"].values
        df.loc[pattern_b, "variable_code"] = old["matched_variable_name"].values
        df.loc[pattern_b, "datasource"] = old["datetime"].values
        df.loc[pattern_b, "matched_variable_name"] = old["value"].values
        df.loc[pattern_b, "datetime"] = old["quality_code"].values

        if "Unnamed: 9" in df.columns:
            df.loc[pattern_b, "value"] = old["Unnamed: 9"].values

        df.loc[pattern_b, "quality_code"] = pd.NA

    print("Batch 1 repair completed")
    print("Pattern A rows:", pattern_a.sum())
    print("Pattern B rows:", pattern_b.sum())

    return df


# ------------------------------------------------------------
# Long format cleaning
# ------------------------------------------------------------

def clean_long_data(df, dayfirst=False):
    df = df.copy()
    df.columns = df.columns.str.strip()

    if "station_name" not in df.columns:
        df["station_name"] = pd.NA

    # Keep only parameters that exist in Final_data
    df["clean_parameter"] = df["parameter"].apply(
        lambda x: PARAMETER_MAP.get(clean_text(x))
    )

    df = df[df["clean_parameter"].notna()].copy()

    # Fix dates and values
    df["measurement_datetime"] = df["datetime"].apply(
        lambda x: fix_date(x, dayfirst)
    )

    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    # If station name is missing, use temporary text so pivot does not remove it
    df["station_name"] = df["station_name"].fillna("MISSING_NAME")

    # Convert long data into one row per station and date
    cleaned = df.pivot_table(
        index=["station", "station_name", "measurement_datetime"],
        columns="clean_parameter",
        values="value",
        aggfunc="first"
    ).reset_index()

    cleaned["station_name"] = cleaned["station_name"].replace(
        "MISSING_NAME",
        pd.NA
    )

    cleaned = cleaned.rename(
        columns={
            "station": "source_id",
            "station_name": "source_name"
        }
    )

    return make_final_format(cleaned)


# ------------------------------------------------------------
# Thomson / O'Shannassy
# ------------------------------------------------------------

def clean_thomson_oshannassy(df):
    df = df.copy()

    df = df.rename(
        columns={
            "Site ID": "station",
            "Name": "station_name",
            "Datetime": "datetime",
            "Parameter": "parameter",
            "Value": "value"
        }
    )

    # Remove NV rows because those readings are not valid
    if "Qualifier" in df.columns:
        df = df[df["Qualifier"].astype(str).str.strip() != "NV"]

    # Make source names easier to understand
    if "station_name" in df.columns:
        df["station_name"] = df["station_name"].replace(
            {
                "THOMSON @ THOMSON AD": "Thomson Reservoir",
                "YAOSH0127": "O'Shannassy Reservoir"
            }
        )

    return clean_long_data(df, dayfirst=False)


# ------------------------------------------------------------
# Wide format cleaning
# ------------------------------------------------------------

def clean_wide_data(df, site_id=None, source_name=None):
    df = df.copy()
    df.columns = df.columns.str.strip()

    # Rename columns into Final_data names
    rename_columns = {}

    for col in df.columns:
        key = col.strip().lower()

        if key in COLUMN_MAP:
            rename_columns[col] = COLUMN_MAP[key]

    df = df.rename(columns=rename_columns)

    # Some wide raw files do not contain site details
    if "source_id" not in df.columns:
        if site_id is None:
            raise ValueError("This file needs a source/site ID")
        df["source_id"] = site_id

    if "source_name" not in df.columns:
        if source_name is None:
            raise ValueError("This file needs a source name")
        df["source_name"] = source_name

    if "measurement_datetime" not in df.columns:
        raise ValueError("No date column was found")

    df["measurement_datetime"] = df["measurement_datetime"].apply(
        lambda x: fix_date(x, dayfirst=True)
    )

    keep_columns = []

    for col in FINAL_COLUMNS:
        if col in df.columns:
            keep_columns.append(col)

    return make_final_format(df[keep_columns])


# ------------------------------------------------------------
# Detect what type of file it is
# ------------------------------------------------------------

def detect_file_type(df, file_name):
    columns = [str(col).strip().lower() for col in df.columns]
    file_name = file_name.lower()

    # Thomson / O'Shannassy
    thomson_columns = ["site id", "name", "datetime", "parameter", "value"]

    if all(col in columns for col in thomson_columns):
        return "thomson"

    if "thomson" in file_name or "oshannassy" in file_name:
        return "thomson"

    # WMIS long data
    if all(col in columns for col in ["station", "parameter", "datetime", "value"]):

        if "batch1" in file_name:
            return "batch1"

        # Check whether the rows are shifted like Batch 1
        if "station_name" in df.columns and "datasource" in df.columns:

            a = df["station_name"].astype(str).str.strip().str.lower().isin(KNOWN_PARAMETERS)
            b = df["datasource"].astype(str).str.strip().str.lower().isin(KNOWN_PARAMETERS)

            if a.any() or b.any():
                return "batch1"

        return "wmis"

    return "wide"


# ------------------------------------------------------------
# Validation
# ------------------------------------------------------------

def validate_data(df, report_path=None):
    print("\nVALIDATION REPORT")
    print("-----------------")

    print("Total rows:", len(df))
    print("Total columns:", len(df.columns))

    # Missing values
    missing_report = []

    for col in FINAL_COLUMNS:
        missing = df[col].isna().sum()
        percentage = round((missing / len(df) * 100), 2) if len(df) > 0 else 0

        missing_report.append({
            "column_name": col,
            "missing_values": missing,
            "missing_percentage": percentage
        })

    # Duplicate station/date
    duplicates = df.duplicated(
        subset=["source_id", "measurement_datetime"],
        keep=False
    ).sum()

    print("Duplicate source/date rows:", duplicates)

    # Bad pH
    ph = pd.to_numeric(df["ph"], errors="coerce")
    bad_ph = ((ph < 0) | (ph > 14)).sum()

    print("Invalid pH values:", bad_ph)

    # Invalid dates
    checked_dates = pd.to_datetime(
        df["measurement_datetime"],
        format="%Y/%m/%d",
        errors="coerce"
    )

    invalid_dates = checked_dates.isna().sum()

    print("Invalid dates:", invalid_dates)

    report = pd.DataFrame(missing_report)

    report["duplicate_source_date_rows"] = duplicates
    report["invalid_ph_values"] = bad_ph
    report["invalid_dates"] = invalid_dates

    if report_path is not None:
        report.to_csv(report_path, index=False)
        print("Validation report saved:", report_path)

    return report


# ------------------------------------------------------------
# Main cleaning function
# ------------------------------------------------------------

def clean_file(input_file, output_file=None, site_id=None, source_name=None):
    file_name = os.path.basename(input_file)

    # Load file
    if input_file.lower().endswith(".csv"):
        df = pd.read_csv(input_file, low_memory=False)
    else:
        df = pd.read_excel(input_file)

    file_type = detect_file_type(df, file_name)

    print("\nCleaning:", file_name)
    print("Detected file type:", file_type)

    if file_type == "batch1":
        df = repair_batch1(df)
        cleaned = clean_long_data(df, dayfirst=False)

    elif file_type == "wmis":
        cleaned = clean_long_data(df, dayfirst=False)

    elif file_type == "thomson":
        cleaned = clean_thomson_oshannassy(df)

    else:
        cleaned = clean_wide_data(
            df,
            site_id=site_id,
            source_name=source_name
        )

    print("Cleaned rows:", len(cleaned))

    # Save cleaned data
    if output_file is not None:
        cleaned.to_csv(output_file, index=False)
        print("Cleaned file saved:", output_file)

        report_file = output_file.replace(
            ".csv",
            "_validation_report.csv"
        )

        validate_data(cleaned, report_file)

    else:
        validate_data(cleaned)

    return cleaned


# ------------------------------------------------------------
# Example local use
# ------------------------------------------------------------
#
# clean_file(
#     "data/raw/WMIS_Batch2.csv",
#     "data/cleaned/WMIS_Batch2_cleaned.csv"
# )
#
# Airflow can call the clean_file() function using the raw file path.
