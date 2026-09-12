# Aquablend Data Engineering — Documentation

This document covers, in order: the data cleaning scripts used to convert raw
WMIS/reservoir exports into the Supabase target schema, the local environment
setup needed to run them, and the WMIS Surface Water Hydrology Scraper used
to extract the raw data in the first place.

---

## 1. Data Cleaning Scripts

Two standalone cleaning scripts convert raw WMIS/reservoir exports into the
Supabase target schema. Both only depend on packages already in
`requirements.txt` (`pandas`, and `openpyxl` for the second one) — no setup
beyond the Environment Setup steps below is needed to run them.

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

---

## 2. Environment Setup

Explains how to set up the local Python environment and Supabase credentials
needed to run the data cleaning scripts above.

### What's in this setup

| File | Purpose |
|---|---|
| `.env.example` | Template listing which environment variables are needed. Safe to commit — contains no real secrets. |
| `.env` | Your real Supabase credentials. **Never committed** — ignored by `.gitignore`. |
| `config.py` | Loads `.env` and exposes `get_engine()` (SQLAlchemy/Postgres) and `get_supabase_client()` (Supabase API). All scripts should import credentials from here, not read `os.environ` directly. |
| `requirements.txt` | Pinned Python package versions matching what the code actually imports: pandas, numpy, openpyxl, requests, python-dotenv, supabase. |
| `.gitignore` | Keeps `.env`, the `venv/` folder, and other local-only files out of git. |

### Prerequisites

- **Python 3.9+** — any reasonably recent Python 3 works. All current packages
  (pandas, numpy, openpyxl, requests, python-dotenv, supabase) have pre-built
  wheels for modern Python versions, so there's no specific version pin needed.
  Check your version with:
  ```
  python --version
  ```
- Access to the team's Supabase project (ask your team lead for the API keys
  and database credentials if you don't have them).

### Setup steps

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

### Using credentials in scripts

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

### Security Notes

- `.env` must never be committed. `.gitignore` already blocks it — check with
  `git status` before every commit; `.env` should never appear in the list.
- Database passwords should be shared privately (DM/password manager), never
  pasted into a group chat or committed to the repo.
- If the database password is ever reset, every team member must update the
  `DATABASE_URL` in their own local `.env` — resetting it breaks the
  connection for everyone using the old password.

### Troubleshooting

| Problem | Fix |
|---|---|
| A script has a Supabase key hardcoded as a fallback value instead of reading `.env` | Remove the hardcoded default — the script should fail loudly if the env var is missing, not silently fall back to a baked-in key. Flag any script found doing this for immediate cleanup, and rotate the key if it's a secret/service_role key. |
| `config.py` raises "Missing required environment variable" | A value in `.env` is empty, misspelled, or `.env` wasn't created from `.env.example`. |
| Connection string fails to parse / auth errors | Check the password is URL-encoded (see step 3) and that you're using the Session pooler URI, not the direct connection. |

---

## 3. WMIS Surface Water Hydrology Scraper (v4)

Extracts **Streamflow**, **Stream Water Level**, and (as a fallback) **Storage
Water Level** from Victoria's Water Measurement Information System (WMIS),
for every surface-water station where data is available, over 2023–2024.
Every row is tagged with the station's **latitude**, **longitude**, and
**zone**.

### What this does differently from earlier versions

The original scraper used `stations.json` to discover candidate stations
(fast, avoids slow/timeout-prone `webservice.exe` calls) and confirmed 7 WQ
parameters against a known stream gauge. This version narrows the scope to
just the hydrology fields needed, and fixes two real bugs found during
extraction:

1. **Latitude/longitude were always blank.** The auto-detector looked for
   field names like `latitude`, `lat`, `Latitude`, etc. — but `stations.json`
   actually uses `station_latitude` / `station_longitude`. Fixed by
   prioritizing the real field names.
2. **A blank station record was picked as a "real" station.** Pandas
   silently converts a missing (`None`) station ID into the literal text
   `"None"` when the column is cast to string. That fake ID then looked like
   a valid candidate. Fixed by dropping missing IDs *before* the string
   conversion.

`zone` was also added — it's a plain top-level field on every station record
that wasn't being carried through to the output.

### The capacity/storage fallback

Streamflow and Stream Water Level are tried first (confirmed codes `141.00`
and `100.00` under the `WQ` datasource, per the original notebook). For any
station where **neither** is available, the script falls back to **Storage
Water Level** — the closest real proxy to "capacity" that exists in this
system (there's no field literally called "capacity").

This code was **not guessed** — it was confirmed empirically by querying a
handful of real storage-type stations across four different datasources
(`WQ`, `A`, `TELEM`, `PUBLISH`), because storage data turned out not to live
under `WQ` like the other parameters do. The finding:

| Variable Code | Name | Datasource |
|---|---|---|
| `130.00` | Storage Water Level (m) | `A` (also appears in `TELEM`/`PUBLISH`) |

This is set in the script as `CAPACITY_PARAM_CODE = "130.00"` and
`CAPACITY_DATASOURCE = "A"`.

### How to run it

Requires `pandas` and `requests` (see `requirements.txt`).

```bash
python "wmis_scraper_v4_hydro.py"
```

The script processes candidate stations in batches of 20 and checkpoints
progress to disk, so it's safe to stop and re-run — it automatically picks
up the next batch each time. Re-run the same command until it prints:

```
All N batches already completed.
```

#### Output files (written to `~/Desktop/wmis_export/`)

| File | Purpose |
|---|---|
| `wmis_hydro_long.csv` | Final long-format dataset (one row per station/parameter/day) |
| `stations_raw_cache.json` | Cached copy of `stations.json`, so re-runs don't re-download it |
| `checkpoint_hydro.json` | Set of (station, parameter) pairs already fetched — enables safe resume |
| `current_batch_hydro.json` | Tracks which batch to run next |
| `skipped_stations_hydro.log` | Every skipped station with the reason why |
| `failures_hydro.log` | Any fetch that errored out (network/API issues) |

#### Output columns

| Column | Description |
|---|---|
| `station` | Station ID |
| `station_name` | Station name |
| `latitude`, `longitude` | Station coordinates |
| `zone` | Station zone |
| `parameter` | `Streamflow`, `Stream Water Level`, or `Storage Water Level` |
| `parameter_mode` | `primary` (streamflow/water level) or `capacity` (storage fallback) |
| `variable_code` | Hydstra variable code used |
| `datasource` | `WQ` for primary params, `A` for the capacity fallback |
| `matched_variable_name` | Name as returned by the live API |
| `datetime` | Reading date |
| `value` | Reading value |
| `quality_code` | Hydstra quality code for that reading |

### Results from the full run (2023–2024, this network)

- **160,089 rows** across **142 stations**
- **65,059** Streamflow readings, **93,568** Stream Water Level readings,
  **1,462** Storage Water Level (capacity fallback) readings
- **158,627** rows from primary parameters, **1,462** from the capacity
  fallback — confirming the fallback only activates when neither primary
  parameter exists
- Zero nulls, zero duplicate (station, parameter, datetime) rows, date range
  confirmed as exactly 2023-01-01 to 2024-12-31
- Of ~1,518 candidate stations identified from `stations.json`, most came
  back with **no WQ variables available at all** — this reflects real
  coverage gaps in the network for this datasource/date range, not a bug in
  the script.

#### Sanity check: Station 221201 (Cann River, West Branch @ Weeragua)

Monthly average streamflow shows a realistic hydrograph — low, steady
baseflow through mid-2023 (~44–52 ML/day), then a sharp flood spike in July
2024 (~2,044 ML/day, roughly 20x baseline), followed by recession back to
normal. This physically plausible pattern was used as a spot-check that the
extraction pipeline is producing trustworthy data rather than artifacts.

### Known limitations

- Coverage is limited by what's actually published under the `WQ` (and, for
  the fallback, `A`) datasource for each station — a station missing from
  the output may still have data under a different datasource not queried
  here.
- The capacity/storage fallback currently only checks one variable
  (`130.00`, Storage Water Level). Other storage-related variables (e.g.
  storage volume) were not investigated.
