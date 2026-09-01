import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from supabase import create_client


# --------------------------------------------------
# Configuration
# --------------------------------------------------

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

CSV_FILE = "wmis_batch1_cleaned.csv"
TABLE_NAME = "Final_Data"
BATCH_SIZE = 500


# --------------------------------------------------
# Supabase connection
# --------------------------------------------------

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError(
        "SUPABASE_URL and SUPABASE_KEY must be set in the environment."
    )

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# --------------------------------------------------
# Load CSV
# --------------------------------------------------

if not Path(CSV_FILE).exists():
    raise FileNotFoundError(f"CSV file not found: {CSV_FILE}")

df = pd.read_csv(
    CSV_FILE,
    dtype={"source_id": "string", "site_id": "string"},
    low_memory=False
)

if df.empty:
    raise ValueError("The CSV file contains no data.")

print("CSV loaded successfully.")
print(f"Rows found: {len(df)}")


# --------------------------------------------------
# Rename common CSV columns to Final_Data names
# --------------------------------------------------

column_aliases = {
    "site_id": "source_id",
    "PH Value(PH)": "ph",
    "ph_value": "ph",
    "Turbidity(NTU)": "turbidity",
    "Water Temperature(C)": "temperature",
    "water_temperature": "temperature",
    "Temperature(C)": "temperature",
    "Colour(PCU)": "colour"
}

# Rename only when the Final_Data column does not already exist
for old_name, new_name in column_aliases.items():
    if old_name in df.columns and new_name not in df.columns:
        df = df.rename(columns={old_name: new_name})


# --------------------------------------------------
# Check required identification columns
# --------------------------------------------------

required_identity_columns = [
    "source_id",
    "source_name",
    "measurement_datetime"
]

missing_identity_columns = [
    column
    for column in required_identity_columns
    if column not in df.columns
]

if missing_identity_columns:
    raise ValueError(
        f"Missing required columns: {missing_identity_columns}"
    )

# Batch 1 contains rows where WMIS did not provide a source_name.
# For now, skip those rows and upload only rows that already have
# a valid source_name. The skipped rows can be repaired later using
# the WMIS station-name lookup process.
missing_source_name_mask = (
    df["source_name"].isna()
    | df["source_name"].astype("string").str.strip().eq("")
)

skipped_missing_source_name = int(missing_source_name_mask.sum())

if skipped_missing_source_name:
    print(
        f"Skipping {skipped_missing_source_name} rows with missing "
        "source_name for this upload."
    )
    df = df.loc[~missing_source_name_mask].copy()

if df.empty:
    raise ValueError(
        "No rows with source_name are available for insertion."
    )


# --------------------------------------------------
# Add columns that may be NULL in Final_Data
# --------------------------------------------------

if "source_type" not in df.columns:
    df["source_type"] = "Surface Water (River)"

optional_columns = [
    "capacity_ml",
    "cost_per_ml",
    "ph",
    "alkalinity",
    "turbidity",
    "colour",
    "temperature"
]

for column in optional_columns:
    if column not in df.columns:
        df[column] = None
        print(
            f"Warning: '{column}' was not found in the CSV. "
            "NULL values will be inserted for this column."
        )


# --------------------------------------------------
# Clean and validate text fields
# --------------------------------------------------

for column in ["source_id", "source_name", "source_type"]:
    df[column] = df[column].astype("string").str.strip()

# Fill blank source_type with the default river type
df["source_type"] = df["source_type"].fillna("Surface Water (River)")
df.loc[df["source_type"] == "", "source_type"] = "Surface Water (River)"

for column in ["source_id", "source_name"]:
    invalid_mask = df[column].isna() | (df[column] == "")

    if invalid_mask.any():
        row_numbers = (df.index[invalid_mask] + 2).tolist()[:10]

        raise ValueError(
            f"Missing or blank values found in '{column}'. "
            f"Example CSV row numbers: {row_numbers}"
        )


# --------------------------------------------------
# Validate measurement datetime
# --------------------------------------------------

parsed_datetime = pd.to_datetime(
    df["measurement_datetime"],
    format="mixed",
    dayfirst=True,
    errors="coerce"
)

invalid_datetime_mask = parsed_datetime.isna()

if invalid_datetime_mask.any():
    row_numbers = (
        df.index[invalid_datetime_mask] + 2
    ).tolist()[:10]

    raise ValueError(
        "Invalid or missing measurement_datetime values found. "
        f"Example CSV row numbers: {row_numbers}"
    )

df["measurement_datetime"] = parsed_datetime.dt.strftime(
    "%Y-%m-%d %H:%M:%S"
)


# --------------------------------------------------
# Convert and validate numeric columns
# --------------------------------------------------

numeric_columns = [
    "capacity_ml",
    "cost_per_ml",
    "ph",
    "alkalinity",
    "turbidity",
    "colour",
    "temperature"
]

for column in numeric_columns:
    original_values = df[column]

    converted_values = pd.to_numeric(
        original_values,
        errors="coerce"
    )

    # Detect non-empty values that could not be converted to numbers
    non_empty_mask = (
        original_values.notna()
        & original_values.astype(str).str.strip().ne("")
    )

    invalid_numeric_mask = non_empty_mask & converted_values.isna()

    if invalid_numeric_mask.any():
        row_numbers = (
            df.index[invalid_numeric_mask] + 2
        ).tolist()[:10]

        raise ValueError(
            f"Invalid numeric values found in '{column}'. "
            f"Example CSV row numbers: {row_numbers}"
        )

    df[column] = converted_values


# --------------------------------------------------
# Final_Data value checks
# --------------------------------------------------

# pH must be between 0 and 14 when present
invalid_ph_mask = df["ph"].notna() & (
    (df["ph"] < 0) | (df["ph"] > 14)
)

if invalid_ph_mask.any():
    row_numbers = (
        df.index[invalid_ph_mask] + 2
    ).tolist()[:10]

    raise ValueError(
        "pH values outside the valid range 0-14 were found. "
        f"Example CSV row numbers: {row_numbers}"
    )

# These values should not be negative
non_negative_columns = [
    "capacity_ml",
    "cost_per_ml",
    "alkalinity",
    "turbidity",
    "colour"
]

for column in non_negative_columns:
    invalid_mask = df[column].notna() & (df[column] < 0)

    if invalid_mask.any():
        row_numbers = (
            df.index[invalid_mask] + 2
        ).tolist()[:10]

        raise ValueError(
            f"Negative values found in '{column}'. "
            f"Example CSV row numbers: {row_numbers}"
        )


# --------------------------------------------------
# Check duplicate source measurements
# --------------------------------------------------

duplicate_mask = df.duplicated(
    subset=["source_id", "measurement_datetime"],
    keep=False
)

if duplicate_mask.any():
    duplicate_rows = df.loc[
        duplicate_mask,
        ["source_id", "source_name", "measurement_datetime"]
    ].head(10)

    print("\nDuplicate source/date records found:")
    print(duplicate_rows.to_string(index=False))

    raise ValueError(
        "Duplicate records found for source_id + "
        "measurement_datetime. Remove duplicates before insertion."
    )


# --------------------------------------------------
# Warn about inconsistent source names
# --------------------------------------------------

source_name_counts = (
    df.groupby("source_id")["source_name"]
    .nunique(dropna=True)
)

inconsistent_sources = source_name_counts[
    source_name_counts > 1
]

if not inconsistent_sources.empty:
    print(
        "\nWarning: Some source_id values have more than one "
        "source_name. Check spelling/capitalisation before insertion."
    )
    print(inconsistent_sources)


# --------------------------------------------------
# Keep only Final_Data columns
# --------------------------------------------------

final_columns = [
    "source_id",
    "source_name",
    "source_type",
    "capacity_ml",
    "measurement_datetime",
    "cost_per_ml",
    "ph",
    "alkalinity",
    "turbidity",
    "colour",
    "temperature"
]

df = df[final_columns]


# --------------------------------------------------
# Validation summary
# --------------------------------------------------

print("\nValidation passed.")
print(f"Rows ready for insertion: {len(df)}")

null_counts = df[
    [
        "capacity_ml",
        "cost_per_ml",
        "ph",
        "alkalinity",
        "turbidity",
        "colour",
        "temperature"
    ]
].isna().sum()

print("\nMissing measurement values:")
print(null_counts.to_string())


# --------------------------------------------------
# Convert missing values to SQL NULL
# --------------------------------------------------

df = df.astype(object).where(pd.notnull(df), None)

records = df.to_dict(orient="records")


# --------------------------------------------------
# Insert into Supabase in batches
# --------------------------------------------------

inserted_rows = 0

for i in range(0, len(records), BATCH_SIZE):
    batch = records[i:i + BATCH_SIZE]

    start_row = i + 1
    end_row = min(i + BATCH_SIZE, len(records))

    try:
        supabase.table(TABLE_NAME).insert(
            batch,
            returning="minimal"
        ).execute()

        inserted_rows += len(batch)

        print(
            f"Inserted records {start_row} to {end_row}"
        )

    except Exception as e:
        print("\nUpload failed.")
        print(f"Failed batch: records {start_row} to {end_row}")
        print(f"Rows successfully inserted before failure: {inserted_rows}")
        print(f"Error: {e}")
        print(
            "Note: Earlier successful batches remain in Supabase."
        )
        raise


print(
    f"\nUpload complete. "
    f"{inserted_rows} rows inserted into {TABLE_NAME}."
)

if skipped_missing_source_name:
    print(
        f"{skipped_missing_source_name} rows were skipped because "
        "source_name is missing. These can be repaired and uploaded later."
    )
