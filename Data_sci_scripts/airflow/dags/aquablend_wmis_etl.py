"""AquaBlend WMIS ETL orchestration DAG.

Coordinates WMIS extraction, cleaning, validation, and loading into Supabase
using the project files stored under ``Data_sci_scripts``.
"""

import pendulum

from airflow.providers.papermill.operators.papermill import PapermillOperator
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

AIRFLOW_PROJECT_DIR = "/opt/airflow/project/airflow"
DATA_SCI_DIR = "/opt/airflow/project/Data_sci_scripts"

RAW_DIR = f"{AIRFLOW_PROJECT_DIR}/data/raw"
PROCESSED_DIR = f"{AIRFLOW_PROJECT_DIR}/data/processed"
EXECUTED_NOTEBOOK_DIR = f"{AIRFLOW_PROJECT_DIR}/data/executed_notebooks"
RUNTIME_DIR = f"{AIRFLOW_PROJECT_DIR}/data/runtime"

SOURCE_NOTEBOOK = f"{DATA_SCI_DIR}/wmis_scraper_notebook_v3.ipynb"
RUNTIME_NOTEBOOK = f"{RUNTIME_DIR}/wmis_scraper_notebook_v3_airflow.ipynb"
CLEANING_SCRIPT = f"{DATA_SCI_DIR}/clean_wmis_batch1_standalone.py"
UPSERT_SCRIPT = f"{DATA_SCI_DIR}/supabase_final_data_upsert.py"

RAW_CSV = f"{RAW_DIR}/wmis_raw_data.csv"
CLEANED_CSV = f"{PROCESSED_DIR}/wmis_cleaned_data.csv"


with DAG(
    dag_id="aquablend_wmis_etl",
    description="Extract WMIS data, clean it, and load it into Supabase Final_Data",
    start_date=pendulum.datetime(2026, 9, 1, tz="Australia/Melbourne"),
    schedule=None,
    catchup=False,
    tags=["aquablend", "wmis", "etl"],
    params={
        "start_time": "20230101000000",
        "end_time": "20241231235959",
    },
) as dag:

    prepare_directories = BashOperator(
        task_id="prepare_directories",
        bash_command=(
            f"mkdir -p {RAW_DIR} {PROCESSED_DIR} "
            f"{EXECUTED_NOTEBOOK_DIR} {RUNTIME_DIR}"
        ),
    )

    prepare_extraction_notebook = BashOperator(
        task_id="prepare_extraction_notebook",
        bash_command=(
            f"python {AIRFLOW_PROJECT_DIR}/scripts/prepare_wmis_notebook.py "
            f"--source {SOURCE_NOTEBOOK} "
            f"--output {RUNTIME_NOTEBOOK} "
            f"--raw-dir {RAW_DIR}"
        ),
    )

    extract_wmis = PapermillOperator(
        task_id="extract_wmis",
        input_nb=RUNTIME_NOTEBOOK,
        output_nb=(
            f"{EXECUTED_NOTEBOOK_DIR}/"
            "wmis_extraction_{{ run_id | replace(':', '_') | replace('+', '_') }}.ipynb"
        ),
        parameters={
            "START_TIME": "{{ params.start_time }}",
            "END_TIME": "{{ params.end_time }}",
        },
        log_output=True,
    )

    clean_wmis = BashOperator(
        task_id="clean_wmis",
        bash_command=(
            f"python {AIRFLOW_PROJECT_DIR}/scripts/run_wmis_cleaning.py "
            f"--cleaner {CLEANING_SCRIPT} "
            f"--input {RAW_CSV} "
            f"--output {CLEANED_CSV}"
        ),
    )

    upsert_supabase = BashOperator(
        task_id="upsert_supabase",
        bash_command=(
            f"python {UPSERT_SCRIPT} "
            f"{CLEANED_CSV} --table Final_Data"
        ),
    )

    (
        prepare_directories
        >> prepare_extraction_notebook
        >> extract_wmis
        >> clean_wmis
        >> upsert_supabase
    )
