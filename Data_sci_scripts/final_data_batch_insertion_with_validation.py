"""Validate cleaned WMIS data and batch-insert it into Supabase.

The script normalises known CSV column names to the Final_Data schema,
validates required identifiers and measurement values, reports missing
optional measurements, and inserts valid records into Supabase in batches.

Required environment variables:
    SUPABASE_URL: Supabase project URL.
    SUPABASE_KEY: Supabase API key with permission to insert into the target
        table.

The input CSV, target table, and batch size are configured using the constants
below. Credentials should be stored outside the source code, for example in a
local .env file that is excluded from version control.
"""

import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from supabase import create_client


# Configuration

# Load credentials from the environment so secrets are not hard-coded.
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

CSV_FILE = "WMIS_Batch2_cleaned (3).csv"
TABLE_NAME = "Final_Data"

# Moderate batch sizes reduce request payloads and make failed ranges easier
# to identify and retry without sending the entire dataset again.
BATCH_SIZE = 500


# Supabase connection

# Fail before any file processing if the database configuration is incomplete.
if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError(
        "SUPABASE_URL and SUPABASE_KEY must be set in the environment."
    )

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# Load input data

# Validate the input path explicitly so a missing or renamed file produces a
# clear error rather than a less useful pandas exception later.
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


# Normalise column names

# Map column names used by different source files to the canonical Final_Data
# names. If a canonical column already exists, keep it rather than overwriting
# data that may already have been standardised upstream.
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

for old_name, new_name in column_aliases.items():
    if old_name in df.columns and new_name not in df.columns:
        df = df.rename(columns={old_name: new_name})


# Validate required identifiers

# These fields identify a measurement and are required before any optional
# water-quality values are considered.
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


# Prepare optional Final_Data columns

# Current WMIS files in this pipeline contain river measurements, so use the
# river source type only when the source file does not already provide one.
if "source_type" not in df.columns:
    df["source_type"] = "Surface Water (River)"

# Optional measurements are retained as SQL NULL when a source dataset does
# not provide them. This keeps a consistent Final_Data payload across files.
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


# Clean and validate text fields

# Trim surrounding whitespace so visually identical identifiers and names do
# not become different values because of formatting in the source CSV.
for column in ["source_id", "source_name", "source_type"]:
    df[column] = df[column].astype("string").str.strip()

# Preserve provided source types and default only missing or blank values.
df["source_type"] = df["source_type"].fillna("Surface Water (River)")
df.loc[df["source_type"] == "", "source_type"] = "Surface Water (River)"

for column in ["source_id", "source_name"]:
    invalid_mask = df[column].isna() | (df[column] == "")

    if invalid_mask.any():
        # Add 2 to convert the zero-based DataFrame index to the CSV row
        # number, accounting for the header row.
        row_numbers = (df.index[invalid_mask] + 2).tolist()[:10]

        raise ValueError(
            f"Missing or blank values found in '{column}'. "
            f"Example CSV row numbers: {row_numbers}"
        )


# Validate measurement timestamps

# Invalid timestamps are converted to NaT first so the script can report the
# affected CSV rows before any records are sent to Supabase.
parsed_datetime = pd.to_datetime(
    df["measurement_datetime"],
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

# Store timestamps in a consistent representation accepted by Supabase.
df["measurement_datetime"] = parsed_datetime.dt.strftime(
    "%Y-%m-%d %H:%M:%S"
)


# Validate numeric measurements

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

    # Coerce values for validation, while separately tracking non-empty source
    # values so malformed text is not silently treated as missing data.
    converted_values = pd.to_numeric(
        original_values,
        errors="coerce"
    )

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


# Validate Final_Data measurement rules

# Mirror key database constraints in Python so invalid records are identified
# before an API request causes an entire batch to fail.
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


# Check duplicate measurements

# A source should not contain more than one measurement for the same timestamp.
# Catching duplicates here avoids inserting conflicting records downstream.
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


# Check source-name consistency

# Treat naming differences as a warning rather than a hard failure because they
# may represent legitimate aliases that require review rather than deletion.
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


# Build the database payload

# Explicitly selecting the target schema prevents unrelated CSV columns from
# being sent to Supabase if upstream files gain additional fields.
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


# Validation summary

print("\nValidation passed.")
print(f"Rows ready for insertion: {len(df)}")

# Report optional-data coverage before insertion so missing measurements remain
# visible to the operator without blocking otherwise valid records.
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


# Convert records for Supabase

# Python None is serialised as SQL NULL by the Supabase client.
df = df.astype(object).where(pd.notnull(df), None)

records = df.to_dict(orient="records")


# Insert validated records in batches

inserted_rows = 0

for i in range(0, len(records), BATCH_SIZE):
    batch = records[i:i + BATCH_SIZE]

    start_row = i + 1
    end_row = min(i + BATCH_SIZE, len(records))

    try:
        # The script only needs success or failure, so avoid returning every
        # inserted row and keep the API response payload small.
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

        # Each batch is a separate request. Earlier successful batches remain
        # committed if a later batch fails and are not rolled back here.
        print(
            "Note: Earlier successful batches remain in Supabase."
        )
        raise


print(
    f"\nUpload complete. "
    f"{inserted_rows} rows inserted into {TABLE_NAME}."
)
