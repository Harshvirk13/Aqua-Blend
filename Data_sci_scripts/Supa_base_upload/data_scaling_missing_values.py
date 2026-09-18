import os
import pandas as pd
from dotenv import load_dotenv
from supabase import create_client


# --------------------------------------------------
# Configuration
# --------------------------------------------------

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

TABLE_NAME = "Final_Data"
OUTPUT_FILE = "Final_Data_Processed.csv"
MISSING_REPORT = "missing_value_report.csv"
TREATMENT_REPORT = "missing_value_treatment_report.csv"
SCALING_REPORT = "scaling_summary.csv"

PAGE_SIZE = 1000

# Numerical parameters to be processed
SCALING_COLUMNS = [
    "capacity_ml",
    "cost_per_ml",
    "ph",
    "alkalinity",
    "turbidity",
    "colour",
    "temperature",
]


# --------------------------------------------------
# Supabase connection
# --------------------------------------------------

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError(
        "SUPABASE_URL and SUPABASE_KEY must be set in the .env file."
    )

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# --------------------------------------------------
# Load ALL data from Supabase
# --------------------------------------------------

all_rows = []
start = 0

print("Loading data from Supabase...")

while True:
    end = start + PAGE_SIZE - 1

    response = (
        supabase
        .table(TABLE_NAME)
        .select("*")
        .order("record_id")
        .range(start, end)
        .execute()
    )

    batch = response.data

    if not batch:
        break

    all_rows.extend(batch)

    print(
        f"Loaded rows {start + 1} to "
        f"{start + len(batch)}"
    )

    if len(batch) < PAGE_SIZE:
        break

    start += PAGE_SIZE


df = pd.DataFrame(all_rows)

if df.empty:
    raise ValueError("No data was returned from Final_Data.")

print("\nData loaded successfully.")
print(f"Total rows: {len(df)}")


# --------------------------------------------------
# Check required columns
# --------------------------------------------------

required_columns = [
    "record_id",
    "source_id",
    "source_name",
    "source_type",
    "capacity_ml",
    "measurement_datetime",
    "cost_per_ml",
    "ph",
    "alkalinity",
    "turbidity",
    "created_at",
    "colour",
    "temperature",
]

missing_columns = [
    column
    for column in required_columns
    if column not in df.columns
]

if missing_columns:
    raise ValueError(
        f"Missing required columns: {missing_columns}"
    )


# --------------------------------------------------
# Convert numerical columns
# --------------------------------------------------

for column in SCALING_COLUMNS:
    df[column] = pd.to_numeric(
        df[column],
        errors="coerce"
    )


# --------------------------------------------------
# Handle missing values using source_id median
# with overall-median fallback
# --------------------------------------------------

print("\nHandling missing values...")

treatment_results = []

for column in SCALING_COLUMNS:

    missing_before_count = int(df[column].isna().sum())

    if missing_before_count == 0:
        treatment_results.append({
            "column": column,
            "missing_before": 0,
            "filled_by_source_median": 0,
            "filled_by_overall_median": 0,
            "missing_after": 0,
            "treatment": "No missing values"
        })
        continue

    # --------------------------------------------------
    # 1. Try source_id-specific median
    # --------------------------------------------------

    source_medians = (
        df.groupby("source_id")[column]
        .transform("median")
    )

    source_fill_mask = (
        df[column].isna()
        & source_medians.notna()
    )

    filled_by_source = int(source_fill_mask.sum())

    df.loc[source_fill_mask, column] = (
        source_medians[source_fill_mask]
    )

    # --------------------------------------------------
    # 2. Use overall median for remaining missing values
    # --------------------------------------------------

    remaining_missing = df[column].isna().sum()
    overall_median = df[column].median()

    if remaining_missing > 0 and pd.notna(overall_median):

        overall_fill_mask = df[column].isna()

        filled_by_overall = int(overall_fill_mask.sum())

        df.loc[overall_fill_mask, column] = overall_median

    else:
        filled_by_overall = 0

    missing_after_count = int(df[column].isna().sum())

    # --------------------------------------------------
    # Treatment description
    # --------------------------------------------------

    if missing_before_count == 0:
        treatment = "No missing values"

    elif pd.isna(overall_median):
        treatment = (
            "No available values; NULL retained"
        )

    elif missing_after_count == 0:
        treatment = (
            "Source_id median used first; "
            "overall median used as fallback"
        )

    else:
        treatment = (
            "Source_id median used; "
            "remaining NULLs retained"
        )

    treatment_results.append({
        "column": column,
        "missing_before": missing_before_count,
        "filled_by_source_median": filled_by_source,
        "filled_by_overall_median": filled_by_overall,
        "missing_after": missing_after_count,
        "treatment": treatment
    })

    print(
        f"{column}: "
        f"before={missing_before_count}, "
        f"source_median={filled_by_source}, "
        f"overall_median={filled_by_overall}, "
        f"after={missing_after_count}, "
        f"overall_median_value={overall_median}"
    )


# --------------------------------------------------
# Save treatment report
# --------------------------------------------------

treatment_report = pd.DataFrame(treatment_results)

treatment_report.to_csv(
    TREATMENT_REPORT,
    index=False
)

print("\nMissing-value treatment report:")
print(treatment_report.to_string(index=False))


# --------------------------------------------------
# Min-Max Scaling
# --------------------------------------------------

print("\nMin-Max scaling:")

scaling_results = []

for column in SCALING_COLUMNS:

    valid_values = df[column].dropna()

    # No values available
    if valid_values.empty:

        print(
            f"{column}: skipped - no available values."
        )

        scaling_results.append({
            "column": column,
            "min": None,
            "max": None,
            "status": "Skipped - no available values"
        })

        continue

    min_value = valid_values.min()
    max_value = valid_values.max()

    if min_value == max_value:

        df[column] = df[column].where(
            df[column].isna(),
            0.0
        )

        status = "Constant values - set to 0"

    else:

        df[column] = (
            (df[column] - min_value)
            / (max_value - min_value)
        )

        status = "Scaled to 0-1"

    scaling_results.append({
        "column": column,
        "min": min_value,
        "max": max_value,
        "status": status
    })

    print(
        f"{column}: "
        f"min={min_value}, "
        f"max={max_value}"
    )


# --------------------------------------------------
# Save scaling summary
# --------------------------------------------------

scaling_summary = pd.DataFrame(
    scaling_results
)

scaling_summary.to_csv(
    SCALING_REPORT,
    index=False
)


# --------------------------------------------------
# Validate scaled values
# --------------------------------------------------

print("\nScaled-value validation:")

for column in SCALING_COLUMNS:

    valid_values = df[column].dropna()

    if valid_values.empty:
        print(
            f"{column}: no values available"
        )
        continue

    print(
        f"{column}: "
        f"min={valid_values.min():.4f}, "
        f"max={valid_values.max():.4f}"
    )

    # Safety check
    if (
        valid_values.min() < 0
        or valid_values.max() > 1
    ):
        raise ValueError(
            f"Scaling validation failed for {column}."
        )


# --------------------------------------------------
# Final missing-value summary
# --------------------------------------------------

print("\nMissing values AFTER treatment:")

for column in SCALING_COLUMNS:
    print(
        f"{column}: "
        f"{df[column].isna().sum()}"
    )


# --------------------------------------------------
# Save processed dataset
# --------------------------------------------------

df.to_csv(
    OUTPUT_FILE,
    index=False
)

print("\nProcessing complete.")
print(f"Processed data: {OUTPUT_FILE}")
print(f"Missing-value report: {MISSING_REPORT}")
print(f"Treatment report: {TREATMENT_REPORT}")
print(f"Scaling summary: {SCALING_REPORT}")

print("\nRemaining missing values:")
print(df.isna().sum())

print("\nNumber of rows:")
print(len(df))