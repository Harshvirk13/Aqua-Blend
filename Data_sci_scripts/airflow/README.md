# AquaBlend WMIS Airflow Pipeline

Apache Airflow orchestration for the AquaBlend WMIS ETL pipeline. The workflow extracts WMIS data, cleans and validates the output, and loads the processed records into the Supabase `Final_Data` table.

## Repository structure

Place the `airflow` folder inside `Data_sci_scripts`:

```text
Aqua-Blend/
└── Data_sci_scripts/
    ├── wmis_scraper_notebook_v3.ipynb
    ├── clean_wmis_batch1_standalone.py
    ├── supabase_final_data_upsert.py
    └── airflow/
        ├── dags/
        │   └── aquablend_wmis_etl.py
        ├── scripts/
        │   ├── prepare_wmis_notebook.py
        │   └── run_wmis_cleaning.py
        ├── data/
        │   ├── raw/
        │   ├── processed/
        │   ├── executed_notebooks/
        │   └── runtime/
        ├── Dockerfile
        ├── docker-compose.yaml
        ├── requirements.txt
        ├── .env.example
        ├── .gitignore
        ├── .dockerignore
        └── README.md
```

The DAG uses the WMIS extraction, cleaning, and Supabase loading files located in the parent `Data_sci_scripts` directory.

## Pipeline workflow

The DAG ID is `aquablend_wmis_etl` and tasks run in this order:

```text
prepare_directories
        ↓
prepare_extraction_notebook
        ↓
extract_wmis
        ↓
clean_wmis
        ↓
upsert_supabase
```

WMIS extraction runs in batches. Checkpoint and batch-state files are stored under `airflow/data/raw`, allowing the next DAG run to continue from the next batch.

## Notebook preparation

`scripts/prepare_wmis_notebook.py` prepares the extraction notebook for execution inside Docker and Papermill. The runtime notebook is configured with:

- output directory: `/opt/airflow/project/airflow/data/raw`
- raw output file: `wmis_raw_data.csv`
- Papermill `parameters` tag on the configuration cell containing `START_TIME` and `END_TIME`

The prepared notebook is written to `airflow/data/runtime` and generated execution notebooks are written to `airflow/data/executed_notebooks`.

## Cleaning execution

`scripts/run_wmis_cleaning.py` loads `clean_wmis_batch1_standalone.py` and calls its `clean_file()` function with the raw and processed Airflow paths. The cleaned CSV and validation report are written to `airflow/data/processed`.

## Prerequisites

Install:

- Docker Desktop
- Git

Python and Apache Airflow do not need to be installed directly on the host machine because the Airflow environment runs in Docker.

## Environment variables

From the `airflow` folder, create a local `.env` file from the example:

```powershell
Copy-Item .env.example .env
```

Set the Supabase credentials in `.env`:

```text
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key
```

The `.env` file is excluded by `.gitignore` and should contain local credentials only.

## Start Airflow

Open PowerShell in `Data_sci_scripts\airflow`. For example:

```powershell
cd "<path-to-repo>\Aqua-Blend\Data_sci_scripts\airflow"
```

Build the Airflow image:

```powershell
docker compose build
```

Initialise Airflow on the first run:

```powershell
docker compose up airflow-init
```

Start the Airflow services:

```powershell
docker compose up -d
```

Check the running services:

```powershell
docker compose ps
```

The Airflow UI is available at:

```text
http://localhost:8081
```

Default local credentials:

```text
Username: airflow
Password: airflow
```

These values can be changed in `.env` before the initial Airflow setup.

## Run the pipeline

Run the complete DAG from PowerShell:

```powershell
docker compose exec airflow-worker airflow dags test aquablend_wmis_etl
```

The DAG can also be triggered manually from the Airflow UI.

The current DAG uses `schedule=None`, so it runs only when triggered manually.

## Pipeline source files

The DAG expects these files in the parent `Data_sci_scripts` directory:

```text
Data_sci_scripts/wmis_scraper_notebook_v3.ipynb
Data_sci_scripts/clean_wmis_batch1_standalone.py
Data_sci_scripts/supabase_final_data_upsert.py
```

The cleaning task calls the `clean_file()` function from `clean_wmis_batch1_standalone.py` through `scripts/run_wmis_cleaning.py`. The wrapper supplies the Airflow raw and processed file paths without changing the cleaning logic.

The Supabase task loads the cleaned data into:

```text
Final_Data
```

The conflict key used by the load step is defined in `supabase_final_data_upsert.py`.

## Batch progress

Extraction progress is stored in:

```text
airflow/data/raw/checkpoint.json
airflow/data/raw/current_batch.json
```

The cumulative raw output is written to:

```text
airflow/data/raw/wmis_raw_data.csv
```

Keep the checkpoint and batch-state files when continuing an extraction run. Removing them resets the local extraction progress.

## Generated outputs

Cleaned data and validation output are written under:

```text
airflow/data/processed/
```

Executed notebooks are written under:

```text
airflow/data/executed_notebooks/
```

Runtime notebook files are written under:

```text
airflow/data/runtime/
```

Generated data, runtime notebooks, Airflow logs, local configuration, and credentials are excluded from version control through `.gitignore`.

## Useful commands

View worker logs:

```powershell
docker compose logs airflow-worker
```

View scheduler logs:

```powershell
docker compose logs airflow-scheduler
```

Check that Airflow can see the DAG:

```powershell
docker compose exec airflow-worker airflow dags list
```

Stop the Airflow environment:

```powershell
docker compose down
```

Remove the Airflow PostgreSQL volume only when a complete local metadata reset is required:

```powershell
docker compose down -v
```
