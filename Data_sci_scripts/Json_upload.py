#!/usr/bin/env python3
"""
upload_json_to_supabase.py

Uploads local JSON files to a Supabase Storage bucket using a direct
connection string (project URL + API key) via the Supabase Storage REST API.

No supabase-py SDK required — just `requests`.

------------------------------------------------------------------------
CONFIGURE THESE (direct string connection — no env vars needed)
------------------------------------------------------------------------
"""

import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

import requests

# ---------------------------------------------------------------------------
# 1. CONNECTION SETTINGS — fill these in directly (or use env vars below)
# ---------------------------------------------------------------------------
SUPABASE_URL = os.environ.get(
    "SUPABASE_URL", "https://afthemgcztvadtpeipoq.supabase.co"
)  # project base URL (no /rest/v1 suffix)
SUPABASE_KEY = os.environ.get(
    "SUPABASE_SERVICE_ROLE_KEY",
    os.environ.get(
        "SUPABASE_KEY",
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFmdGhlbWdjenR2YWR0cGVpcG9xIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODQ1MjA0OTIsImV4cCI6MjEwMDA5NjQ5Mn0.D2NELlribVfmcM_wfc00OzxbjUPnLXC6nwmKH62fPrA",
    ),
)  # service_role key required for uploads (anon key hits RLS)
BUCKET_NAME = os.environ.get("SUPABASE_BUCKET", "milp_model_output json")

# Path (folder) inside the bucket where files will be placed. Use "" for bucket root.
BUCKET_DEST_FOLDER = ""

# Overwrite existing files with the same namße? (Supabase returns 409 if False and file exists)
UPSERT = True

# ---------------------------------------------------------------------------
# 2. CORE UPLOAD FUNCTION
# ---------------------------------------------------------------------------
def upload_json_file(local_path: str, remote_name: str | None = None) -> dict:
    """
    Upload a single local JSON file to the configured Supabase Storage bucket.

    Args:
        local_path: path to the local .json file
        remote_name: optional override for the filename in the bucket
                     (defaults to the local file's name)

    Returns:
        dict with the parsed JSON response from Supabase (or raises on error)
    """
    local_path = Path(local_path)
    if not local_path.exists():
        raise FileNotFoundError(f"No such file: {local_path}")

    # Validate it's actually valid JSON before uploading
    with open(local_path, "r", encoding="utf-8") as f:
        try:
            json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"{local_path} is not valid JSON: {e}")

    remote_name = remote_name or local_path.name
    dest_path = f"{BUCKET_DEST_FOLDER}/{remote_name}" if BUCKET_DEST_FOLDER else remote_name

    encoded_bucket = quote(BUCKET_NAME, safe="")
    encoded_dest = quote(dest_path, safe="/")
    url = f"{SUPABASE_URL}/storage/v1/object/{encoded_bucket}/{encoded_dest}"

    headers = {
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "apikey": SUPABASE_KEY,
        "Content-Type": "application/json",
        "x-upsert": "true" if UPSERT else "false",
    }

    with open(local_path, "rb") as f:
        response = requests.post(url, headers=headers, data=f)

    if response.status_code not in (200, 201):
        hint = ""
        if response.status_code == 400 and "row-level security" in response.text.lower():
            hint = (
                " Hint: storage uploads need the service_role key "
                "(Dashboard → Project Settings → API → service_role)."
            )
        raise RuntimeError(
            f"Upload failed for {local_path} -> {dest_path} "
            f"[{response.status_code}]: {response.text}{hint}"
        )

    print(f"✓ Uploaded {local_path.name} -> {BUCKET_NAME}/{dest_path}")
    return response.json()


def upload_json_directory(local_dir: str) -> None:
    """Upload every .json file in a local directory to the bucket."""
    local_dir = Path(local_dir)
    if not local_dir.is_dir():
        raise NotADirectoryError(f"No such directory: {local_dir}")

    json_files = sorted(local_dir.glob("*.json"))
    if not json_files:
        print(f"No .json files found in {local_dir}")
        return

    successes, failures = 0, 0
    for jf in json_files:
        try:
            upload_json_file(jf)
            successes += 1
        except Exception as e:
            print(f"✗ Failed: {jf.name} — {e}", file=sys.stderr)
            failures += 1

    print(f"\nDone. {successes} succeeded, {failures} failed.")


# ---------------------------------------------------------------------------
# 3. CLI ENTRY POINT
# ---------------------------------------------------------------------------
def main():
    if len(sys.argv) < 2:
        print(
            "Usage:\n"
            "  python upload_json_to_supabase.py <file.json>          # upload one file\n"
            "  python upload_json_to_supabase.py <folder/>            # upload all .json in folder\n"
        )
        sys.exit(1)

    target = sys.argv[1]

    if SUPABASE_URL.startswith("https://YOUR-PROJECT-REF") or "YOUR-" in SUPABASE_KEY:
        print(
            "⚠ Please edit SUPABASE_URL / SUPABASE_KEY / BUCKET_NAME at the top "
            "of this script before running."
        )
        sys.exit(1)

    if os.path.isdir(target):
        upload_json_directory(target)
    else:
        upload_json_file(target)


if __name__ == "__main__":
    main()
