"""Run the WMIS cleaning module from the Airflow pipeline."""

from __future__ import annotations

import argparse
import runpy
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cleaner", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.cleaner.exists():
        raise FileNotFoundError(f"Cleaning script not found: {args.cleaner}")
    if not args.input.exists():
        raise FileNotFoundError(f"Raw WMIS CSV not found: {args.input}")

    namespace = runpy.run_path(str(args.cleaner))
    clean_file = namespace.get("clean_file")
    if not callable(clean_file):
        raise RuntimeError(
            f"Expected a callable clean_file() function in {args.cleaner}"
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    clean_file(str(args.input), str(args.output))


if __name__ == "__main__":
    main()
