"""
Validate cleaned WMIS data and batch-upsert it into Supabase Final_Data.

Default input:
    data/processed/wmis_cleaned_data.csv

Conflict key:
    source_id, measurement_datetime

The database must have a UNIQUE constraint or UNIQUE index on these two
columns for on_conflict to work.

By default, existing rows with the same conflict key are preserved and new
rows are inserted. This makes repeated pipeline runs safe and avoids replacing
existing non-WMIS values (for example capacity_ml or cost_per_ml) with NULL.

Set --update-existing if a pipeline run should update existing rows instead.
"""

import argparse
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from supabase import create_client


DEFAULT_CSV_FILE = Path("data/processed/wmis_cleaned_data.csv")
DEFAULT_TABLE_NAME = "Final_Data"
DEFAULT_BATCH_SIZE = 500
CONFLICT_KEY = "source_id,measurement_datetime"


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=DEFAULT_CSV_FILE,
        help=f"Cleaned WMIS CSV path (default: {DEFAULT_CSV_FILE})",
    )
    parser.add_argument(
        "--table",
        default=DEFAULT_TABLE_NAME,
        help=f"Supabase target table (default: {DEFAULT_TABLE_NAME})",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Rows per Supabase request (default: {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--update-existing",
        action="store_true",
        help=(
            "Update existing rows when the conflict key matches. "
            "Without this flag, conflicting existing rows are preserved."
        ),
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.batch_size <= 0:
        raise ValueError("--batch-size must be greater than zero.")

    load_dotenv()

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")

    if not supabase_url or not supabase_key:
        raise ValueError(
            "SUPABASE_URL and SUPABASE_KEY must be set in the environment."
        )

    if not args.input.exists():
        raise FileNotFoundError(f"Cleaned WMIS CSV not found: {args.input}")

    supabase = create_client(supabase_url, supabase_key)

    df = pd.read_csv(
        args.input,
        dtype={"source_id": "string", "site_id": "string"},
        low_memory=False,
    )

    if df.empty:
        raise ValueError("The cleaned WMIS CSV contains no data.")

    print(f"CSV loaded: {args.input}")
    print(f"Rows found: {len(df)}")

    column_aliases = {
        "site_id": "source_id",
        "PH Value(PH)": "ph",
        "ph_value": "ph",
        "Turbidity(NTU)": "turbidity",
        "Water Temperature(C)": "temperature",
        "water_temperature": "temperature",
        "Temperature(C)": "temperature",
        "Colour(PCU)": "colour",
    }

    for old_name, new_name in column_aliases.items():
        if old_name in df.columns and new_name not in df.columns:
            df = df.rename(columns={old_name: new_name})

    required_identity_columns = [
        "source_id",
        "source_name",
        "measurement_datetime",
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

    if "source_type" not in df.columns:
        df["source_type"] = "Surface Water"

    optional_columns = [
        "capacity_ml",
        "cost_per_ml",
        "ph",
        "alkalinity",
        "turbidity",
        "colour",
        "temperature",
    ]

    for column in optional_columns:
        if column not in df.columns:
            df[column] = None
            print(
                f"Warning: '{column}' not found. NULL values will be used."
            )

    for column in ["source_id", "source_name", "source_type"]:
        df[column] = df[column].astype("string").str.strip()

    df["source_type"] = df["source_type"].fillna("Surface Water")
    df.loc[df["source_type"] == "", "source_type"] = "Surface Water"

    for column in ["source_id", "source_name"]:
        invalid_mask = df[column].isna() | (df[column] == "")
        if invalid_mask.any():
            row_numbers = (df.index[invalid_mask] + 2).tolist()[:10]
            raise ValueError(
                f"Missing or blank values in '{column}'. "
                f"Example CSV rows: {row_numbers}"
            )

    parsed_datetime = pd.to_datetime(
        df["measurement_datetime"],
        errors="coerce",
    )

    invalid_datetime_mask = parsed_datetime.isna()
    if invalid_datetime_mask.any():
        row_numbers = (
            df.index[invalid_datetime_mask] + 2
        ).tolist()[:10]
        raise ValueError(
            "Invalid or missing measurement_datetime values. "
            f"Example CSV rows: {row_numbers}"
        )

    df["measurement_datetime"] = parsed_datetime.dt.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    numeric_columns = [
        "capacity_ml",
        "cost_per_ml",
        "ph",
        "alkalinity",
        "turbidity",
        "colour",
        "temperature",
    ]

    for column in numeric_columns:
        original_values = df[column]
        converted_values = pd.to_numeric(
            original_values,
            errors="coerce",
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
                f"Invalid numeric values in '{column}'. "
                f"Example CSV rows: {row_numbers}"
            )

        df[column] = converted_values

    invalid_ph_mask = df["ph"].notna() & (
        (df["ph"] < 0) | (df["ph"] > 14)
    )
    if invalid_ph_mask.any():
        row_numbers = (
            df.index[invalid_ph_mask] + 2
        ).tolist()[:10]
        raise ValueError(
            "pH values outside 0-14 were found. "
            f"Example CSV rows: {row_numbers}"
        )

    non_negative_columns = [
        "capacity_ml",
        "cost_per_ml",
        "alkalinity",
        "turbidity",
        "colour",
    ]

    for column in non_negative_columns:
        invalid_mask = df[column].notna() & (df[column] < 0)
        if invalid_mask.any():
            row_numbers = (
                df.index[invalid_mask] + 2
            ).tolist()[:10]
            raise ValueError(
                f"Negative values in '{column}'. "
                f"Example CSV rows: {row_numbers}"
            )

    # Upsert cannot reliably resolve multiple rows with the same conflict key
    # inside one payload, so fail before sending ambiguous data.
    duplicate_mask = df.duplicated(
        subset=["source_id", "measurement_datetime"],
        keep=False,
    )
    if duplicate_mask.any():
        duplicate_rows = df.loc[
            duplicate_mask,
            ["source_id", "source_name", "measurement_datetime"],
        ].head(10)

        print("\nDuplicate conflict keys found in the cleaned CSV:")
        print(duplicate_rows.to_string(index=False))
        raise ValueError(
            "Duplicate source_id + measurement_datetime rows exist in the "
            "cleaned CSV. Resolve them before loading."
        )

    source_name_counts = (
        df.groupby("source_id")["source_name"]
        .nunique(dropna=True)
    )
    inconsistent_sources = source_name_counts[source_name_counts > 1]

    if not inconsistent_sources.empty:
        print(
            "\nWarning: some source_id values have more than one source_name."
        )
        print(inconsistent_sources)

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
        "temperature",
    ]

    df = df[final_columns]

    print("\nValidation passed.")
    print(f"Rows ready for upsert: {len(df)}")
    print(f"Conflict key: {CONFLICT_KEY}")

    null_counts = df[
        [
            "capacity_ml",
            "cost_per_ml",
            "ph",
            "alkalinity",
            "turbidity",
            "colour",
            "temperature",
        ]
    ].isna().sum()

    print("\nMissing measurement values:")
    print(null_counts.to_string())

    df = df.astype(object).where(pd.notnull(df), None)
    records = df.to_dict(orient="records")

    processed_rows = 0
    ignore_existing = not args.update_existing

    print(
        "\nUpsert mode: "
        + (
            "preserve existing conflicting rows"
            if ignore_existing
            else "update existing conflicting rows"
        )
    )

    for start in range(0, len(records), args.batch_size):
        batch = records[start:start + args.batch_size]

        start_row = start + 1
        end_row = min(start + args.batch_size, len(records))

        try:
            supabase.table(args.table).upsert(
                batch,
                on_conflict=CONFLICT_KEY,
                ignore_duplicates=ignore_existing,
                returning="minimal",
            ).execute()

            processed_rows += len(batch)
            print(f"Upserted records {start_row} to {end_row}")

        except Exception as exc:
            print("\nUpsert failed.")
            print(f"Failed batch: records {start_row} to {end_row}")
            print(f"Rows processed before failure: {processed_rows}")
            print(f"Error: {exc}")
            print(
                "Check that Final_Data has a UNIQUE constraint/index on "
                "(source_id, measurement_datetime)."
            )
            raise

    print(
        f"\nUpload complete. {processed_rows} rows processed for "
        f"{args.table}."
    )


if __name__ == "__main__":
    main()
