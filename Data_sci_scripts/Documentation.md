# Environment Setup — Aquablend Data Engineering

This document explains how to set up the local Python environment and Supabase
credentials needed to run the data cleaning scripts in this repo.

## What's in this setup

| File | Purpose |
|---|---|
| `.env.example` | Template listing which environment variables are needed. Safe to commit — contains no real secrets. |
| `.env` | Your real Supabase credentials. **Never committed** — ignored by `.gitignore`. |
| `config.py` | Loads `.env` and exposes `get_engine()` (SQLAlchemy/Postgres) and `get_supabase_client()` (Supabase API). All scripts should import credentials from here, not read `os.environ` directly. |
| `requirements.txt` | Pinned Python package versions for the whole stack (Pyomo, HiGHS, pandas, SQLAlchemy, Streamlit, geopandas, Supabase). |
| `.gitignore` | Keeps `.env`, the `venv/` folder, and other local-only files out of git. |

## Prerequisites

- **Python 3.11** — required. Newer versions (e.g. 3.13/3.14) can fail to install
  `psycopg2-binary` because pre-built wheels aren't published for them yet.
  Check your version with:
  ```
  python --version
  ```
  If it isn't 3.11.x, install Python 3.11 from
  [python.org/downloads](https://www.python.org/downloads/release/python-3119/)
  (check "Add python.exe to PATH" during install), then use `py -3.11` in the
  steps below.
- Access to the team's Supabase project (ask your team lead for the database
  password if you don't have it).

## Setup steps

1. **Clone/pull the repo** and navigate into the project folder.

2. **Create your local `.env` file** from the template:
   ```
   copy .env.example .env
   ```

3. **Fill in `.env`** with real values from the Supabase dashboard:
   - `SUPABASE_URL` — Project Settings → API → Project URL (drop the trailing `/rest/v1/`)
   - `SUPABASE_ANON_KEY` — Project Settings → API Keys → Publishable key
   - `SUPABASE_SERVICE_ROLE_KEY` — Project Settings → API Keys → Secret key (optional, admin tasks only)
   - `DATABASE_URL` — Connect → Direct connection string tab → Session pooler → URI.
     Replace `[YOUR-PASSWORD]` with the real database password.

   ⚠️ **Special characters in the password must be URL-encoded.** For example
   `@` becomes `%40`. A password like `AquaBlend@2026` must be written as
   `AquaBlend%402026` inside the connection string, otherwise the extra `@`
   breaks the URL format.

4. **Create a virtual environment on Python 3.11**:
   ```
   py -3.11 -m venv venv
   venv\Scripts\activate
   ```
   Confirm it's active and on the right version:
   ```
   python --version
   ```
   should print `Python 3.11.x`.

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

## Security notes

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
| `pip install` fails on `psycopg2-binary` with "pg_config executable not found" | Wrong Python version — rebuild the venv on Python 3.11 (see Prerequisites). |
| `config.py` raises "Missing required environment variable" | A value in `.env` is empty, misspelled, or `.env` wasn't created from `.env.example`. |
| Connection string fails to parse / auth errors | Check the password is URL-encoded (see step 3) and that you're using the Session pooler URI, not the direct connection. |
