import os
import pandas as pd
import numpy as np

from dotenv import load_dotenv
from supabase import create_client

# Supabase Configuration

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Read CSV

df = pd.read_csv("Barwon_Final.csv")

print("CSV Loaded Successfully")
print(df.head())

# Rename columns to match Raw_Data schema

df = df.rename(columns={
    "PH Value(PH)": "ph_value",
    "Turbidity(NTU)": "turbidity",
    "Water Temperature(C)": "water_temperature",
    "Nitrogen as NOx(mg/L)": "nitrogen_nox",
    "TSS(mg/L)": "tss",
    "Colour(PCU)": "colour"
})


# Convert datetime column

df["measurement_datetime"] = pd.to_datetime(
    df["measurement_datetime"],
    errors="coerce"
)
df["measurement_datetime"] = (
    df["measurement_datetime"]
    .dt.strftime("%Y-%m-%d %H:%M:%S")
)

# Replace NaN with None

df = df.replace({np.nan: None})


# Check required columns

required_columns = [
    "site_id",
    "source_name",
    "measurement_datetime",
    "ph_value",
    "turbidity",
    "water_temperature",
    "nitrogen_nox",
    "tss",
    "colour"
]

missing_columns = [
    col for col in required_columns
    if col not in df.columns
]

if missing_columns:
    print("Missing Columns:")
    print(missing_columns)
    exit()


# Keep only required columns

df = df[required_columns]


# Convert dataframe to records

records = df.to_dict(orient="records")


# Upload to Supabase

try:

    response = (
        supabase
        .table("Raw Data")
        .insert(records)
        .execute()
    )

    print("--------------------------------")
    print("Data uploaded successfully!")
    print(f"Rows Uploaded: {len(records)}")
    print("--------------------------------")

except Exception as e:

    print("--------------------------------")
    print("Upload Failed")
    print(e)
    print("--------------------------------")