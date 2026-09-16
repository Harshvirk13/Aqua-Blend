```python
import pandas as pd


# Load cleaned Barwon dataset
df = pd.read_csv("Barwon_Cleaned.csv")


# Validate required input columns
required_input_columns = [
    "Site ID",
    "Name",
    "Datetime",
    "Parameter",
    "Value"
]

missing_columns = [
    col for col in required_input_columns
    if col not in df.columns
]

if missing_columns:
    raise ValueError(
        f"Missing required columns: {missing_columns}"
    )


# Rename columns to standard names
df = df.rename(columns={
    "Site ID": "site_id",
    "Name": "source_name",
    "Datetime": "measurement_datetime"
})


# Reshape parameter rows into separate columns
final_df = df.pivot_table(
    index=[
        "site_id",
        "source_name",
        "measurement_datetime"
    ],
    columns="Parameter",
    values="Value",
    # Keep the first value if duplicate measurements exist
    # for the same site, datetime and parameter.
    aggfunc="first"
).reset_index()


# Remove the columns index name created by pivot_table
final_df.columns.name = None


# Rename water quality parameter columns
final_df = final_df.rename(columns={
    "pH": "PH Value(PH)",
    "Turbidity": "Turbidity(NTU)",
    "Water Temperature": "Water Temperature(C)",
    "Nitrogen as NOx": "Nitrogen as NOx(mg/L)",
    "Total Suspended Solids (TSS)": "TSS(mg/L)",
    "Colour (True Filtered) (PCU)": "Colour(PCU)"
})


# Define the required final column structure
required_columns = [
    "site_id",
    "source_name",
    "measurement_datetime",
    "PH Value(PH)",
    "Turbidity(NTU)",
    "Water Temperature(C)",
    "Nitrogen as NOx(mg/L)",
    "TSS(mg/L)",
    "Colour(PCU)"
]


# Add missing parameter columns with NA values
for col in required_columns:
    if col not in final_df.columns:
        final_df[col] = pd.NA


# Keep only required columns in the specified order
final_df = final_df[required_columns]


# Save the final transformed dataset
final_df.to_csv("Barwon_Final.csv", index=False)


# Display a preview of the final dataset
print("Barwon dataset processed successfully.")
print("Rows:", len(final_df))
print("Columns:", len(final_df.columns))
print("\nFinal columns:")
print(final_df.columns.tolist())
print("\nPreview:")
print(final_df.head())
```
