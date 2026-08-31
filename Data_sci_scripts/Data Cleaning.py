import os
import pandas as pd
from tkinter import Tk, filedialog


# 1. SELECT THE CSV FILE

root = Tk()
root.withdraw()

file_path = filedialog.askopenfilename(
    title="Select the CSV file you want to clean",
    filetypes=[("CSV Files", "*.csv")]
)

# Stop if no file is selected
if not file_path:
    print("No file selected.")
    exit()

print("\nSelected file:")
print(file_path)


# 2. LOAD THE SELECTED CSV

df = pd.read_csv(file_path)

print("\nOriginal data shape:", df.shape)

print("\nColumns:")
print(df.columns.tolist())


# 3. CLEAN COLUMN NAMES

df.columns = df.columns.str.strip()


# 4. FIND AND CLEAN DATETIME COLUMN

# Check for common date/time column names
date_columns = [
    "datetime",
    "measurement_datetime",
    "date",
    "Date",
    "timestamp"
]

date_column = None

for col in date_columns:
    if col in df.columns:
        date_column = col
        break


if date_column:
    print(f"\nDate column found: {date_column}")

    df[date_column] = pd.to_datetime(
        df[date_column],
        errors="coerce"
    )

    # Remove rows with invalid/missing dates
    df = df.dropna(subset=[date_column])

else:
    print("\nNo date column detected.")


# 5. REMOVE DUPLICATES

before = len(df)

df = df.drop_duplicates()

after = len(df)

print("\nDuplicates removed:", before - after)


# 6. CONVERT POSSIBLE MEASUREMENT COLUMNS TO NUMERIC

# Don't convert these columns because they may contain text
text_columns = [
    "site_id",
    "source_name",
    "station",
    "station_id",
    "variable",
    "variable_code",
    "quality_code"
]

for col in df.columns:

    if col == date_column:
        continue

    if col in text_columns:
        continue

    # Try converting the column to numbers
    converted = pd.to_numeric(
        df[col],
        errors="coerce"
    )

    # Only replace the original column if it contains
    # some valid numeric data
    if converted.notna().sum() > 0:
        df[col] = converted


# 7. CHECK pH VALUES

# Look for columns containing pH
for col in df.columns:

    if "ph" in col.lower():

        if pd.api.types.is_numeric_dtype(df[col]):

            invalid_ph = (
                (df[col] < 0) |
                (df[col] > 14)
            )

            print(
                f"Invalid pH values found in {col}:",
                invalid_ph.sum()
            )

            df.loc[invalid_ph, col] = pd.NA


# 8. REMOVE COMPLETELY EMPTY ROWS

df = df.dropna(how="all")


# 9. SORT BY DATE-

if date_column:
    df = df.sort_values(date_column)


# 10. RESET INDEX

df = df.reset_index(drop=True)


# 11. SHOW MISSING VALUES

print("\nMissing values:")
print(df.isnull().sum())


# 12. CREATE OUTPUT FILE NAME

folder = os.path.dirname(file_path)

original_name = os.path.basename(file_path)

file_name, extension = os.path.splitext(original_name)

cleaned_file_name = file_name + "_cleaned.csv"

output_path = os.path.join(
    folder,
    cleaned_file_name
)

# 13. SAVE CLEANED CSV

df.to_csv(
    output_path,
    index=False
)

# 14. RESULTS

print("\n--------------------------------")
print("DATA CLEANING COMPLETED")
print("--------------------------------")

print("Original rows:", before)

print("Cleaned rows:", len(df))

print("\nCleaned file saved to:")
print(output_path)

print("\nFirst 10 rows:")
print(df.head(10))