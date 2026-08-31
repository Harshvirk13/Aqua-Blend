import os
import pandas as pd
from tkinter import Tk, filedialog


# =====================================================
# 1. SELECT CLEANED CSV FILE
# =====================================================

root = Tk()
root.withdraw()

file_path = filedialog.askopenfilename(
    title="Select the cleaned CSV file to validate",
    filetypes=[("CSV Files", "*.csv")]
)

if not file_path:
    print("No file selected.")
    exit()

print("\nSelected file:")
print(file_path)


# =====================================================
# 2. LOAD DATA
# =====================================================

df = pd.read_csv(file_path)

print("\n====================================")
print("DATA VALIDATION REPORT")
print("====================================")

print("\nTotal rows:", len(df))
print("Total columns:", len(df.columns))

print("\nColumns:")
for col in df.columns:
    print("-", col)


# =====================================================
# 3. CHECK DUPLICATES
# =====================================================

duplicate_count = df.duplicated().sum()

print("\n====================================")
print("DUPLICATE CHECK")
print("====================================")

print("Duplicate rows:", duplicate_count)


# =====================================================
# 4. CHECK MISSING VALUES
# =====================================================

print("\n====================================")
print("MISSING VALUE CHECK")
print("====================================")

missing_count = df.isnull().sum()

missing_percentage = (
    df.isnull().sum() / len(df) * 100
).round(2)

missing_report = pd.DataFrame({
    "Missing Values": missing_count,
    "Missing Percentage (%)": missing_percentage
})

print(missing_report)


# =====================================================
# 5. FIND DATE COLUMN
# =====================================================

possible_date_columns = [
    "datetime",
    "measurement_datetime",
    "date",
    "Date",
    "timestamp"
]

date_column = None

for col in possible_date_columns:
    if col in df.columns:
        date_column = col
        break


# =====================================================
# 6. VALIDATE DATE
# =====================================================

if date_column:

    print("\n====================================")
    print("DATE VALIDATION")
    print("====================================")

    original_date = df[date_column].copy()

    converted_date = pd.to_datetime(
        df[date_column],
        errors="coerce"
    )

    invalid_dates = (
        converted_date.isna() &
        original_date.notna()
    ).sum()

    print("Date column:", date_column)
    print("Invalid dates:", invalid_dates)

    if converted_date.notna().any():

        print(
            "Earliest date:",
            converted_date.min()
        )

        print(
            "Latest date:",
            converted_date.max()
        )


# =====================================================
# 7. IDENTIFY NUMERIC COLUMNS
# =====================================================

numeric_columns = df.select_dtypes(
    include="number"
).columns.tolist()

print("\n====================================")
print("NUMERIC COLUMNS")
print("====================================")

for col in numeric_columns:
    print("-", col)


# =====================================================
# 8. BASIC STATISTICAL VALIDATION
# =====================================================

print("\n====================================")
print("STATISTICAL SUMMARY")
print("====================================")

if numeric_columns:

    summary = df[numeric_columns].describe().T

    print(
        summary[
            ["count", "mean", "min", "50%", "max"]
        ]
    )

else:
    print("No numeric columns detected.")


# =====================================================
# 9. VALIDATE pH
# =====================================================

print("\n====================================")
print("pH VALIDATION")
print("====================================")

ph_results = {}

for col in df.columns:

    if "ph" in col.lower():

        numeric_ph = pd.to_numeric(
            df[col],
            errors="coerce"
        )

        invalid_ph = (
            (numeric_ph < 0) |
            (numeric_ph > 14)
        ).sum()

        ph_results[col] = invalid_ph

        print(
            f"{col}: {invalid_ph} values outside 0-14"
        )

if not ph_results:
    print("No pH column detected.")


# =====================================================
# 10. CHECK NEGATIVE VALUES
# =====================================================

print("\n====================================")
print("NEGATIVE VALUE CHECK")
print("====================================")

# These measurements should normally not be negative.

keywords = [
    "turbidity",
    "conductivity",
    "salinity",
    "suspended",
    "phosphorus",
    "nitrogen"
]

negative_results = {}

for col in numeric_columns:

    if any(
        keyword in col.lower()
        for keyword in keywords
    ):

        negative_count = (
            df[col] < 0
        ).sum()

        negative_results[col] = negative_count

        print(
            f"{col}: {negative_count} negative values"
        )

if not negative_results:
    print("No applicable columns detected.")


# =====================================================
# 11. OUTLIER DETECTION USING IQR
# =====================================================

print("\n====================================")
print("POSSIBLE OUTLIERS")
print("====================================")

outlier_results = {}

for col in numeric_columns:

    clean_values = df[col].dropna()

    if len(clean_values) < 4:
        continue

    Q1 = clean_values.quantile(0.25)
    Q3 = clean_values.quantile(0.75)

    IQR = Q3 - Q1

    lower_bound = Q1 - (1.5 * IQR)
    upper_bound = Q3 + (1.5 * IQR)

    outliers = (
        (df[col] < lower_bound) |
        (df[col] > upper_bound)
    )

    outlier_count = outliers.sum()

    outlier_results[col] = outlier_count

    print(
        f"{col}: {outlier_count} possible outliers"
    )


# =====================================================
# 12. CREATE VALIDATION REPORT
# =====================================================

report = []

for col in df.columns:

    missing = df[col].isnull().sum()

    missing_pct = (
        missing / len(df) * 100
        if len(df) > 0
        else 0
    )

    row = {
        "column_name": col,
        "data_type": str(df[col].dtype),
        "total_rows": len(df),
        "missing_values": missing,
        "missing_percentage": round(
            missing_pct, 2
        ),
        "possible_outliers":
            outlier_results.get(col, "N/A")
    }

    report.append(row)


validation_df = pd.DataFrame(report)


# =====================================================
# 13. SAVE VALIDATION REPORT
# =====================================================

folder = os.path.dirname(file_path)

original_name = os.path.basename(file_path)

file_name, extension = os.path.splitext(
    original_name
)

report_name = (
    file_name +
    "_validation_report.csv"
)

report_path = os.path.join(
    folder,
    report_name
)

validation_df.to_csv(
    report_path,
    index=False
)


# =====================================================
# 14. FINAL RESULT
# =====================================================

print("\n====================================")
print("VALIDATION COMPLETED")
print("====================================")

print("Total rows:", len(df))
print("Duplicate rows:", duplicate_count)

print("\nValidation report saved to:")
print(report_path)