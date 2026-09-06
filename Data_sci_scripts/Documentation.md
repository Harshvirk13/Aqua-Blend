# Data_sci_scripts — Environment & Dependencies

Owner: Sandeep Mallipeddi
Branch: `data-engineering-sandeep`
Last updated: 6 September 2026

## Purpose

This folder holds the data engineering scripts for AquaBlend, along with the
Python dependency definition the whole team installs from. The goal of pinning
dependencies is that everyone runs identical package versions, so a script that
works on one machine works on all of them.

## Python version

This project is standardised on **Python 3.11**.

Do not use 3.12 or newer. Some of our dependencies have no pre-built wheels for
newer versions and will try to compile from source, which fails on Windows
without a C toolchain and a local Postgres install. `psycopg2-binary` is the
usual culprit — it fails with an error about a missing `pg_config` executable.

Check what you have:

```
py -0
```

If `-V:3.11` is not in that list, install it from python.org and tick
"Add python.exe to PATH" during setup.

## Setting up your environment

From the repository root:

```
py -3.11 -m venv venv
venv\Scripts\activate
pip install -r Data_sci_scripts\requirements.txt
```

On macOS or Linux the activate line is `source venv/bin/activate`.

To confirm the environment is on the right interpreter after activating:

```
python --version
```

It should print 3.11.x. If it prints anything else, the virtual environment was
built on the wrong interpreter — delete the `venv` folder and rebuild it with
the explicit `py -3.11` command above.

## Dependencies

Pinned in `requirements.txt`. The stack covers:

| Package | Used for |
|---|---|
| pandas | data loading, cleaning and transformation |
| SQLAlchemy | database connections and queries |
| psycopg2-binary | Postgres driver used by SQLAlchemy |
| Pyomo | modelling layer for the MILP optimisation |
| HiGHS | solver backend for Pyomo |
| Streamlit | dashboard front end |
| geopandas | GIS and spatial data handling |
| supabase | client for the hosted database |

<!-- TODO: replace with the actual pinned versions from requirements.txt,
     e.g. pandas==2.2.2. Copy them exactly as they appear in the file — do
     not retype from memory. -->

### Adding a new dependency

1. Install it in your active virtual environment and confirm your script runs.
2. Find the exact installed version with `pip show <package>`.
3. Add the line `package==x.y.z` to `requirements.txt`. Always pin with `==`.
4. Verify a clean install still works (see next section).
5. Commit `requirements.txt` on its own, with a message saying what you added
   and why.

Never run `pip freeze > requirements.txt`. It captures every transitive
dependency of whatever happens to be installed on your machine, including
things unrelated to this project, and makes the file unreadable.

## Verifying a clean install

Before committing a change to `requirements.txt`, prove it installs from
scratch in a throwaway environment:

```
py -3.11 -m venv test_venv
test_venv\Scripts\activate
pip install -r Data_sci_scripts\requirements.txt
```

If that completes with no errors, tear it down:

```
deactivate
rmdir /s /q test_venv
```

This catches the case where a package works for you only because it was
installed earlier by something else and never made it into the file.

## Files in this folder

| File | What it is |
|---|---|
| `requirements.txt` | pinned Python dependencies for the whole team |
| `config.py` | loads configuration and database credentials from environment variables |
| `Data_validation.py` | validation checks on incoming source data |
| `Documentation.md` | this file |

<!-- TODO: The following were removed from this branch on 6 Sep and should be
     restored before this doc is accurate:
       .gitignore        — keeps venv/, __pycache__/ and .env out of commits
       .env.example      — template listing the variables config.py expects
       data cleaning script - batch 2.py
       data cleaning script - murray and goulburn.py
     They still exist in git history and in local clones, so nothing is lost.
     Delete this block once they are back, and add them to the table above. -->

## Configuration and secrets

`config.py` reads credentials from environment variables rather than having
them written into the code. Copy `.env.example` to `.env` and fill in your own
values.

Never commit a real `.env` file. It contains live database credentials, and
anything pushed to a public repository should be treated as permanently
exposed even if deleted afterwards. `.gitignore` is what stops this happening
by accident, which is why restoring it matters.

## Common problems

**`py` is not recognised** — Python isn't installed, or wasn't added to PATH
during install. Reinstall 3.11 with the PATH box ticked, then open a *new*
terminal. An already-open window won't pick up the change.

**`psycopg2-binary` fails with a `pg_config` error** — you are almost certainly
installing on the wrong Python version. Check `python --version` inside the
activated environment; if it isn't 3.11.x, delete the venv and rebuild it.

**A script fails on an import that works for a teammate** — the package is
installed on their machine but missing from `requirements.txt`. Add it, pin it,
and verify with the clean-install check above.
