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

Default login: username `Mohammad`, password `408809937` (or set `INIT_USERNAME`/`INIT_PASSWORD` env vars before first run).

## Deploy to Render (recommended for phone use)

This app is a single-container Flask app with SQLite. Render supports persistent disks.

1. Fork this repo to your GitHub.
2. Click the Render Blueprint (this repo has `render.yaml`), or create a new Web Service and connect the repo.
3. Set Build Command (if creating manually):
```
pip install -r requirements.txt
```
4. Set Start Command (if creating manually):
```
gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120
```
5. Environment Variables (optional):
   - `INIT_USERNAME` / `INIT_PASSWORD` to seed first user.
   - `DB_PATH` like `/opt/render/project/src/database.sqlite3` (default already points there).
6. Add a Persistent Disk (e.g. 1GB) mounted at `/opt/render/project/src` so `database.sqlite3` is saved (the blueprint already does this).

After deploy, open the public URL in your phone browser.

## Deploy to Railway (alternative)

1. Fork to GitHub → Create a Railway service from the repo.
2. Set `NIXPACKS_BUILD_CMD` to `pip install -r requirements.txt` (or rely on detection).
3. Set Start Command to `gunicorn app:app --bind 0.0.0.0:$PORT`.
4. Add a Volume and mount at `/app` and set `DB_PATH=/app/database.sqlite3`.

## Notes for production
- Use `gunicorn` instead of the Flask dev server.
- Persist `database.sqlite3` via disk/volume and set `DB_PATH` accordingly.

## Notes
- Database: SQLite file `database.sqlite3` in the project directory.
- Exports: Excel (`.xlsx`) and PDF are available from the Monthly Report page.
- Set default hourly rate on Home. Each manual record can override the rate.
