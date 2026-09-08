# Environment Setup — Aquablend Data Engineering

This document explains how to set up the local Python environment and Supabase
credentials needed to run the data cleaning scripts in this repo, and
documents what each cleaning script does (see "Data cleaning scripts" below).

## What's in this setup

| File | Purpose |
|---|---|
| `.env.example` | Template listing which environment variables are needed. Safe to commit — contains no real secrets. |
| `.env` | Your real Supabase credentials. **Never committed** — ignored by `.gitignore`. |
| `config.py` | Loads `.env` and exposes `get_engine()` (SQLAlchemy/Postgres) and `get_supabase_client()` (Supabase API). All scripts should import credentials from here, not read `os.environ` directly. |
| `requirements.txt` | Pinned Python package versions matching what the code actually imports: pandas, numpy, openpyxl, requests, python-dotenv, supabase. |
| `.gitignore` | Keeps `.env`, the `venv/` folder, and other local-only files out of git. |

## Prerequisites

- **Python 3.9+** — any reasonably recent Python 3 works. All current packages
  (pandas, numpy, openpyxl, requests, python-dotenv, supabase) have pre-built
  wheels for modern Python versions, so there's no specific version pin needed.
  Check your version with:
  ```
  python --version
  ```
- Access to the team's Supabase project (ask your team lead for the API keys
  and database credentials if you don't have them).

## Setup steps

1. **Clone/pull the repo** and navigate into the project folder.

2. **Create your local `.env` file** from the template:
   ```
   copy .env.example .env
   ```

3. **Fill in `.env`** with real values from the Supabase dashboard:
   - `SUPABASE_URL` — Project Settings → API → Project URL (drop the trailing `/rest/v1/`) — **required**, used by every upload script
   - `SUPABASE_ANON_KEY` — Project Settings → API Keys → Publishable key — required for read-level operations
   - `SUPABASE_SERVICE_ROLE_KEY` — Project Settings → API Keys → Secret key — **required for uploads** (e.g. Storage uploads hit row-level security errors with the anon key)
   - `DATABASE_URL` — Connect → Direct connection string tab → Session pooler → URI. Not currently used by any script in the repo (no SQLAlchemy/psycopg2 code exists yet), but kept in the template in case a future script needs a direct Postgres connection. Replace `[YOUR-PASSWORD]` with the real database password if you do end up needing it.

   ⚠️ **Special characters in the password must be URL-encoded.** For example
   `@` becomes `%40`. A password like `AquaBlend@2026` must be written as
   `AquaBlend%402026` inside the connection string, otherwise the extra `@`
   breaks the URL format.

4. **Create a virtual environment**:
   ```
   python -m venv venv
   venv\Scripts\activate
   ```
   Confirm it's active — your terminal prompt should now start with `(venv)`.

5. **Install dependencies**:
   ```
   pip install -r requirements.txt
   ```

6. **Verify the setup**:
   ```
   python config.py
   ```
   Expected output:
   ```
   Environment: development
   Supabase URL: https://<your-project-ref>.supabase.co
   DATABASE_URL loaded: yes
   ```

## Using credentials in scripts

Never hardcode a key or connect string in any script. Import from `config.py`
instead:

```python
from config import get_engine, get_supabase_client

# Pandas / SQLAlchemy route
engine = get_engine()
df = pd.read_sql("SELECT * FROM sources", engine)

# Supabase client route
supabase = get_supabase_client()
data = supabase.table("sources").select("*").execute()
```

## Data cleaning scripts

Two standalone cleaning scripts convert raw WMIS/reservoir exports into the
Supabase target schema. Both only depend on packages already in
`requirements.txt` (`pandas`, and `openpyxl` for the second one) — no setup
beyond the steps above is needed to run them.

### `data cleaning script - batch 2.py`

Cleans `WMIS_Batch2.csv` (long/tidy format — one row per station +
parameter + date) into the schema:

```
source_id, source_name, source_type, capacity_ml, measurement_datetime,
cost_per_ml, ph, alkalinity, turbidity, water_temperature, colour
```

**What it handles:**
- Pivots the long/tidy format into one row per station+date, spreading each
  parameter (pH, turbidity, alkalinity, water temperature, colour) into its
  own column. Streamflow, Stream Water Level, and Salinity (EC) are dropped
  — this schema has no column for them.
- Fixes a date-encoding bug: different stations in this file store dates in
  two different formats — a plain Excel serial number (e.g. `"44927"`) or a
  US-style `M/D/YY` text string (e.g. `"1/1/23"`). Both are detected
  per-cell and converted to a consistent `YYYY/MM/DD` format.
- Infers `source_type` from keywords in the station name (River, Creek,
  Drain, Lake, Reservoir), labelled as e.g. `"Surface Water (River)"`.
- Runs QA checks on output: row counts per source, duplicate
  source+date combinations, and a warning for any source name that didn't
  match a known type keyword.

**Usage:**
```
python3 "data cleaning script - batch 2.py" WMIS_Batch2.csv [--out OUTPUT.csv]
```

### `data cleaning script - murray and goulburn.py`

Cleans river/reservoir exports (`.xlsx` or `.csv`) into the schema:

```
site_id, source_name, measurement_datetime, PH Value(PH), Turbidity(NTU),
Water Temperature(C), Nitrogen as NOx(mg/L), TSS(mg/L), Colour(PCU)
```

**What it handles:**
- Auto-detects and handles **two different raw shapes**: wide format (one
  row per site+date, one column per parameter already spread out — e.g.
  `O_shannassy_river.xlsx`) and long/tidy format (one row per
  site+parameter+date — e.g. `WMIS_Batch2.csv`), pivoting the latter into
  the same wide target shape automatically.
- Fixes an Excel day/month swap bug: dates originally entered as text in
  Australian `dd/mm/yyyy` format got silently reinterpreted by Excel as
  `mm/dd/yyyy` whenever the day was ≤ 12, swapping month and day in the
  stored datetime. The script detects which cells were affected and
  reconstructs the correct calendar date.
- Fixes the same mixed date-encoding issue as the batch 2 script (Excel
  serial numbers vs `M/D/Y` text) for long/tidy sources.
- Supports a `--split-by-site` mode to write one CSV per site instead of a
  single combined file.

**Usage:**
```
python3 "data cleaning script - murray and goulburn.py" INPUT.xlsx [--sheet SHEET_NAME] [--out OUTPUT.csv]
python3 "data cleaning script - murray and goulburn.py" INPUT.csv [--site-id ID --source-name "NAME"]
```
`--site-id` / `--source-name` are required only for "bare wide" files that
have no site identifier columns of their own.



- `.env` must never be committed. `.gitignore` already blocks it — check with
  `git status` before every commit; `.env` should never appear in the list.
- Database passwords should be shared privately (DM/password manager), never
  pasted into a group chat or committed to the repo.
- If the database password is ever reset, every team member must update the
  `DATABASE_URL` in their own local `.env` — resetting it breaks the
  connection for everyone using the old password.

## Troubleshooting

| Problem | Fix |
|---|---|
| A script has a Supabase key hardcoded as a fallback value instead of reading `.env` | Remove the hardcoded default — the script should fail loudly if the env var is missing, not silently fall back to a baked-in key. Flag any script found doing this for immediate cleanup, and rotate the key if it's a secret/service_role key. |
| `config.py` raises "Missing required environment variable" | A value in `.env` is empty, misspelled, or `.env` wasn't created from `.env.example`. |
| Connection string fails to parse / auth errors | Check the password is URL-encoded (see step 3) and that you're using the Session pooler URI, not the direct connection. |
