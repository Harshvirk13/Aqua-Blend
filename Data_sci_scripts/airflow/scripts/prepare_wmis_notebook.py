"""Prepare the WMIS extraction notebook for Airflow execution.

Creates a runtime notebook with Docker output paths and a Papermill
``parameters`` tag on the START_TIME/END_TIME configuration cell.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--raw-dir",
        default="/opt/airflow/project/airflow/data/raw",
        help="Runtime directory for WMIS raw outputs.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.source.exists():
        raise FileNotFoundError(f"WMIS source notebook not found: {args.source}")

    notebook = json.loads(args.source.read_text(encoding="utf-8"))

    config_cell = None
    for cell in notebook.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        source = "".join(cell.get("source", []))
        if "START_TIME" in source and "END_TIME" in source and "OUTPUT_DIR" in source:
            config_cell = cell
            break

    if config_cell is None:
        raise RuntimeError(
            "Could not find the WMIS configuration cell containing "
            "START_TIME, END_TIME and OUTPUT_DIR."
        )

    updated_lines = []
    output_dir_replaced = False
    long_csv_replaced = False

    for line in config_cell.get("source", []):
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]

        if stripped.startswith("OUTPUT_DIR ="):
            line = f'{indent}OUTPUT_DIR = "{args.raw_dir}"\n'
            output_dir_replaced = True
        elif stripped.startswith("LONG_CSV ="):
            line = f'{indent}LONG_CSV = os.path.join(OUTPUT_DIR, "wmis_raw_data.csv")\n'
            long_csv_replaced = True

        updated_lines.append(line)

    if not output_dir_replaced or not long_csv_replaced:
        raise RuntimeError(
            "Expected OUTPUT_DIR and LONG_CSV assignments were not found in "
            "the WMIS configuration cell."
        )

    config_cell["source"] = updated_lines
    metadata = config_cell.setdefault("metadata", {})
    tags = metadata.setdefault("tags", [])
    if "parameters" not in tags:
        tags.append("parameters")

    # Clear stored notebook output before runtime execution.
    for cell in notebook.get("cells", []):
        if cell.get("cell_type") == "code":
            cell["execution_count"] = None
            cell["outputs"] = []

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(notebook, indent=1), encoding="utf-8")

    print(f"Prepared Airflow notebook: {args.output}")
    print(f"Raw output directory: {args.raw_dir}")
    print("Papermill parameters tag: ready")


if __name__ == "__main__":
    main()
