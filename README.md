# راتبي - My Salary Tracker

A simple personal web app to track working hours and calculate monthly salary.

## Quick Start (Windows)

1. Open PowerShell in this folder.
2. Create a virtual environment and install dependencies:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt
```

3. Run the app:

```powershell
.venv\Scripts\python app.py
```

Then open `http://localhost:5000` in your browser.

Default login: username `admin`, password `admin` (you can change in DB or set `INIT_USERNAME`/`INIT_PASSWORD` env vars before first run).

## Notes
- Database: SQLite file `database.sqlite3` in the project directory.
- Exports: Excel (`.xlsx`) and PDF are available from the Monthly Report page.
- Set default hourly rate on Home. Each manual record can override the rate.
