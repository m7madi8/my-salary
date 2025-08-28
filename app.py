from __future__ import annotations

import os
import sqlite3
import secrets
from contextlib import closing
from datetime import datetime, date, timedelta
from io import BytesIO

from passlib.hash import bcrypt
from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_cors import CORS

APP_NAME = "  My Salary Tracker"
DB_PATH = os.path.join(os.path.dirname(__file__), "database.sqlite3")
SECRET_KEY = os.environ.get("SECRET_KEY", "change-this-secret-key")
DEFAULT_USERNAME = os.environ.get("INIT_USERNAME", "Mohammad")
DEFAULT_PASSWORD = os.environ.get("INIT_PASSWORD", "408809937")

# In-memory token store for a single-user app
TOKENS: set[str] = set()


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.update(SECRET_KEY=SECRET_KEY)
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    with app.app_context():
        init_db()
        ensure_default_user()
        ensure_default_settings()

    register_routes(app)
    register_api(app)
    return app


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with closing(get_db_connection()) as conn, conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS work_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                work_date TEXT NOT NULL,
                check_in TEXT,
                check_out TEXT,
                total_hours REAL,
                hourly_rate REAL,
                daily_salary REAL
            );
            """
        )


def ensure_default_user() -> None:
    with closing(get_db_connection()) as conn, conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM user").fetchone()
        if row["c"] == 0:
            conn.execute(
                "INSERT INTO user (username, password_hash) VALUES (?, ?)",
                (DEFAULT_USERNAME, bcrypt.hash(DEFAULT_PASSWORD)),
            )


def ensure_default_settings() -> None:
    if get_setting("default_hourly_rate") is None:
        set_setting("default_hourly_rate", "5.0")


def get_setting(key: str) -> str | None:
    with closing(get_db_connection()) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    with closing(get_db_connection()) as conn, conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)\n             ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def is_logged_in() -> bool:
    return bool(session.get("user_id"))


def login_required(view_func):
    from functools import wraps

    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not is_logged_in():
            return redirect(url_for("login", next=request.path))
        return view_func(*args, **kwargs)

    return wrapper


def get_today_entry() -> sqlite3.Row | None:
    today_str = date.today().isoformat()
    with closing(get_db_connection()) as conn:
        row = conn.execute(
            "SELECT * FROM work_entries WHERE work_date = ? ORDER BY id DESC LIMIT 1",
            (today_str,),
        ).fetchone()
        return row


def open_entry_for_date(target_date: date) -> sqlite3.Row | None:
    with closing(get_db_connection()) as conn:
        row = conn.execute(
            "SELECT * FROM work_entries WHERE work_date = ? AND check_out IS NULL ORDER BY id DESC LIMIT 1",
            (target_date.isoformat(),),
        ).fetchone()
        return row


def compute_total_hours(check_in_str: str, check_out_str: str) -> float:
    fmt = "%H:%M"
    start_dt = datetime.strptime(check_in_str, fmt)
    end_dt = datetime.strptime(check_out_str, fmt)
    if end_dt < start_dt:
        end_dt += timedelta(days=1)
    delta = end_dt - start_dt
    hours = delta.total_seconds() / 3600.0
    return round(hours, 2)


def register_routes(app: Flask) -> None:
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            with closing(get_db_connection()) as conn:
                row = conn.execute("SELECT * FROM user WHERE username = ?", (username,)).fetchone()
                if row and bcrypt.verify(password, row["password_hash"]):
                    session["user_id"] = row["id"]
                    session["username"] = row["username"]
                    next_url = request.args.get("next") or url_for("home")
                    return redirect(next_url)
            flash("Invalid credentials", "error")
        return render_template("login.html", app_name=APP_NAME)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/")
    @login_required
    def home():
        default_rate = float(get_setting("default_hourly_rate") or 0)
        today = date.today()
        today_entry = get_today_entry()
        yesterday = today - timedelta(days=1)
        forgotten_open = open_entry_for_date(yesterday)
        return render_template(
            "home.html",
            app_name=APP_NAME,
            username=session.get("username"),
            default_rate=default_rate,
            today_entry=today_entry,
            forgotten_open=forgotten_open,
            today=today,
        )

    @app.route("/settings/rate", methods=["POST"])
    @login_required
    def update_default_rate():
        try:
            new_rate = float(request.form.get("hourly_rate", "0").strip())
        except ValueError:
            flash("Invalid rate", "error")
            return redirect(url_for("home"))
        set_setting("default_hourly_rate", str(new_rate))
        flash("Default hourly rate updated", "success")
        return redirect(url_for("home"))

    @app.route("/check_in", methods=["POST"])
    @login_required
    def check_in():
        today = date.today()
        open_entry = open_entry_for_date(today)
        if open_entry:
            flash("Already checked in today.", "warning")
            return redirect(url_for("home"))
        now_time = datetime.now().strftime("%H:%M")
        default_rate = float(get_setting("default_hourly_rate") or 0)
        with closing(get_db_connection()) as conn, conn:
            conn.execute(
                """
                INSERT INTO work_entries (work_date, check_in, hourly_rate)
                VALUES (?, ?, ?)
                """,
                (today.isoformat(), now_time, default_rate),
            )
        flash(f"Checked in at {now_time}", "success")
        return redirect(url_for("home"))

    @app.route("/check_out", methods=["POST"])
    @login_required
    def check_out():
        today = date.today()
        open_entry = open_entry_for_date(today)
        if not open_entry:
            flash("No open check-in for today.", "warning")
            return redirect(url_for("home"))
        now_time = datetime.now().strftime("%H:%M")
        total_hours = compute_total_hours(open_entry["check_in"], now_time)
        hourly_rate = float(open_entry["hourly_rate"] or (get_setting("default_hourly_rate") or 0))
        daily_salary = round(total_hours * hourly_rate, 2)
        with closing(get_db_connection()) as conn, conn:
            conn.execute(
                """
                UPDATE work_entries
                SET check_out = ?, total_hours = ?, daily_salary = ?
                WHERE id = ?
                """,
                (now_time, total_hours, daily_salary, open_entry["id"]),
            )
        flash(f"Checked out at {now_time}", "success")
        return redirect(url_for("home"))

    @app.route("/records/add", methods=["GET", "POST"])
    @login_required
    def add_record():
        if request.method == "POST":
            work_date = request.form.get("work_date", "").strip()
            check_in = request.form.get("check_in", "").strip()
            check_out = request.form.get("check_out", "").strip()
            try:
                hourly_rate = float(request.form.get("hourly_rate", "0").strip())
            except ValueError:
                hourly_rate = float(get_setting("default_hourly_rate") or 0)
            total_hours = None
            daily_salary = None
            if check_in and check_out:
                total_hours = compute_total_hours(check_in, check_out)
                daily_salary = round(total_hours * hourly_rate, 2)
            with closing(get_db_connection()) as conn, conn:
                conn.execute(
                    """
                    INSERT INTO work_entries (work_date, check_in, check_out, total_hours, hourly_rate, daily_salary)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (work_date, check_in or None, check_out or None, total_hours, hourly_rate, daily_salary),
                )
            flash("Record added", "success")
            return redirect(url_for("report"))
        default_rate = float(get_setting("default_hourly_rate") or 0)
        return render_template("add_record.html", app_name=APP_NAME, default_rate=default_rate)

    @app.route("/records/<int:record_id>/edit", methods=["GET", "POST"])
    @login_required
    def edit_record(record_id: int):
        with closing(get_db_connection()) as conn:
            row = conn.execute("SELECT * FROM work_entries WHERE id = ?", (record_id,)).fetchone()
            if not row:
                abort(404)
        if request.method == "POST":
            work_date = request.form.get("work_date", "").strip()
            check_in = request.form.get("check_in", "").strip()
            check_out = request.form.get("check_out", "").strip()
            try:
                hourly_rate = float(request.form.get("hourly_rate", "0").strip())
            except ValueError:
                hourly_rate = float(get_setting("default_hourly_rate") or 0)
            total_hours = None
            daily_salary = None
            if check_in and check_out:
                total_hours = compute_total_hours(check_in, check_out)
                daily_salary = round(total_hours * hourly_rate, 2)
            with closing(get_db_connection()) as conn, conn:
                conn.execute(
                    """
                    UPDATE work_entries
                    SET work_date = ?, check_in = ?, check_out = ?, total_hours = ?, hourly_rate = ?, daily_salary = ?
                    WHERE id = ?
                    """,
                    (work_date, check_in or None, check_out or None, total_hours, hourly_rate, daily_salary, record_id),
                )
            flash("Record updated", "success")
            return redirect(url_for("report"))
        return render_template("edit_record.html", app_name=APP_NAME, record=row)

    @app.route("/records/<int:record_id>/delete", methods=["POST"])
    @login_required
    def delete_record(record_id: int):
        with closing(get_db_connection()) as conn, conn:
            conn.execute("DELETE FROM work_entries WHERE id = ?", (record_id,))
        flash("Record deleted", "success")
        return redirect(url_for("report"))

    @app.route("/report")
    @login_required
    def report():
        month = request.args.get("month")
        if month:
            try:
                start_date = datetime.strptime(month + "-01", "%Y-%m-%d").date()
            except ValueError:
                start_date = date.today().replace(day=1)
        else:
            start_date = date.today().replace(day=1)
        next_month = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1)
        end_date = next_month - timedelta(days=1)
        with closing(get_db_connection()) as conn:
            rows = conn.execute(
                """
                SELECT * FROM work_entries
                WHERE work_date BETWEEN ? AND ?
                ORDER BY work_date ASC
                """,
                (start_date.isoformat(), end_date.isoformat()),
            ).fetchall()
        total_hours = round(sum((r["total_hours"] or 0) for r in rows), 2)
        total_salary = round(sum((r["daily_salary"] or 0) for r in rows), 2)
        return render_template(
            "monthly_report.html",
            app_name=APP_NAME,
            rows=rows,
            start_date=start_date,
            end_date=end_date,
            total_hours=total_hours,
            total_salary=total_salary,
            month_selector=start_date.strftime("%Y-%m"),
        )

    @app.route("/report/export/excel")
    @login_required
    def export_excel():
        from openpyxl import Workbook
        month = request.args.get("month")
        if month:
            try:
                start_date = datetime.strptime(month + "-01", "%Y-%m-%d").date()
            except ValueError:
                start_date = date.today().replace(day=1)
        else:
            start_date = date.today().replace(day=1)
        next_month = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1)
        end_date = next_month - timedelta(days=1)
        with closing(get_db_connection()) as conn:
            rows = conn.execute(
                "SELECT * FROM work_entries WHERE work_date BETWEEN ? AND ? ORDER BY work_date ASC",
                (start_date.isoformat(), end_date.isoformat()),
            ).fetchall()
        wb = Workbook()
        ws = wb.active
        ws.title = "Report"
        ws.append(["Date", "Check In", "Check Out", "Hours", "Rate", "Daily Salary"])
        for r in rows:
            ws.append([
                r["work_date"],
                r["check_in"] or "",
                r["check_out"] or "",
                r["total_hours"] or 0,
                r["hourly_rate"] or 0,
                r["daily_salary"] or 0,
            ])
        ws.append([])
        ws.append(["Totals", "", "", round(sum((r["total_hours"] or 0) for r in rows), 2), "", round(sum((r["daily_salary"] or 0) for r in rows), 2)])
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        filename = f"salary_report_{start_date.strftime('%Y_%m')}.xlsx"
        return send_file(output, as_attachment=True, download_name=filename, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @app.route("/report/export/pdf")
    @login_required
    def export_pdf():
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet
        month = request.args.get("month")
        if month:
            try:
                start_date = datetime.strptime(month + "-01", "%Y-%m-%d").date()
            except ValueError:
                start_date = date.today().replace(day=1)
        else:
            start_date = date.today().replace(day=1)
        next_month = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1)
        end_date = next_month - timedelta(days=1)
        with closing(get_db_connection()) as conn:
            rows = conn.execute(
                "SELECT * FROM work_entries WHERE work_date BETWEEN ? AND ? ORDER BY work_date ASC",
                (start_date.isoformat(), end_date.isoformat()),
            ).fetchall()
        data = [["Date", "Check In", "Check Out", "Hours", "Rate", "Daily Salary"]]
        for r in rows:
            data.append([
                r["work_date"],
                r["check_in"] or "",
                r["check_out"] or "",
                r["total_hours"] or 0,
                r["hourly_rate"] or 0,
                r["daily_salary"] or 0,
            ])
        data.append(["Totals", "", "", round(sum((r["total_hours"] or 0) for r in rows), 2), "", round(sum((r["daily_salary"] or 0) for r in rows), 2)])
        output = BytesIO()
        doc = SimpleDocTemplate(output, pagesize=landscape(A4))
        styles = getSampleStyleSheet()
        elements = [Paragraph(f"Monthly Report - {start_date.strftime('%Y-%m')}", styles["Title"])]
        table = Table(data)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0f0")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
                    ("BACKGROUND", (0, 1), (-1, -2), colors.white),
                    ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#fafafa")),
                ]
            )
        )
        elements.append(table)
        doc.build(elements)
        output.seek(0)
        filename = f"salary_report_{start_date.strftime('%Y_%m')}.pdf"
        return send_file(output, as_attachment=True, download_name=filename, mimetype="application/pdf")


def register_api(app: Flask) -> None:
    def require_token():
        token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
        if not token or token not in TOKENS:
            return False
        return True

    @app.post("/api/login")
    def api_login():
        data = request.get_json(silent=True) or {}
        username = str(data.get("username", "")).strip()
        password = str(data.get("password", ""))
        with closing(get_db_connection()) as conn:
            row = conn.execute("SELECT * FROM user WHERE username = ?", (username,)).fetchone()
            if row and bcrypt.verify(password, row["password_hash"]):
                token = secrets.token_hex(16)
                TOKENS.add(token)
                return jsonify({"token": token, "username": username})
        return jsonify({"error": "invalid_credentials"}), 401

    @app.post("/api/logout")
    def api_logout():
        token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
        if token in TOKENS:
            TOKENS.remove(token)
        return jsonify({"ok": True})

    @app.get("/api/me")
    def api_me():
        if not require_token():
            return jsonify({"error": "unauthorized"}), 401
        return jsonify({"username": session.get("username", DEFAULT_USERNAME)})

    @app.get("/api/today")
    def api_today():
        if not require_token():
            return jsonify({"error": "unauthorized"}), 401
        row = get_today_entry()
        return jsonify({
            "today": date.today().isoformat(),
            "entry": dict(row) if row else None,
            "default_rate": float(get_setting("default_hourly_rate") or 0),
        })

    @app.post("/api/check-in")
    def api_check_in():
        if not require_token():
            return jsonify({"error": "unauthorized"}), 401
        today = date.today()
        open_entry = open_entry_for_date(today)
        if open_entry:
            return jsonify({"error": "already_checked_in"}), 400
        now_time = datetime.now().strftime("%H:%M")
        default_rate = float(get_setting("default_hourly_rate") or 0)
        with closing(get_db_connection()) as conn, conn:
            conn.execute(
                "INSERT INTO work_entries (work_date, check_in, hourly_rate) VALUES (?, ?, ?)",
                (today.isoformat(), now_time, default_rate),
            )
        return jsonify({"ok": True, "check_in": now_time})

    @app.post("/api/check-out")
    def api_check_out():
        if not require_token():
            return jsonify({"error": "unauthorized"}), 401
        today = date.today()
        open_entry = open_entry_for_date(today)
        if not open_entry:
            return jsonify({"error": "no_open_entry"}), 400
        now_time = datetime.now().strftime("%H:%M")
        total_hours = compute_total_hours(open_entry["check_in"], now_time)
        hourly_rate = float(open_entry["hourly_rate"] or (get_setting("default_hourly_rate") or 0))
        daily_salary = round(total_hours * hourly_rate, 2)
        with closing(get_db_connection()) as conn, conn:
            conn.execute(
                "UPDATE work_entries SET check_out=?, total_hours=?, daily_salary=? WHERE id=?",
                (now_time, total_hours, daily_salary, open_entry["id"]),
            )
        return jsonify({"ok": True, "check_out": now_time, "hours": total_hours, "salary": daily_salary})

    @app.get("/api/report")
    def api_report():
        if not require_token():
            return jsonify({"error": "unauthorized"}), 401
        month = request.args.get("month")
        if month:
            try:
                start_date = datetime.strptime(month + "-01", "%Y-%m-%d").date()
            except ValueError:
                start_date = date.today().replace(day=1)
        else:
            start_date = date.today().replace(day=1)
        next_month = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1)
        end_date = next_month - timedelta(days=1)
        with closing(get_db_connection()) as conn:
            rows = conn.execute(
                "SELECT * FROM work_entries WHERE work_date BETWEEN ? AND ? ORDER BY work_date ASC",
                (start_date.isoformat(), end_date.isoformat()),
            ).fetchall()
        serial = [dict(r) for r in rows]
        total_hours = round(sum((r.get("total_hours") or 0) for r in serial), 2)
        total_salary = round(sum((r.get("daily_salary") or 0) for r in serial), 2)
        return jsonify({
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "rows": serial,
            "total_hours": total_hours,
            "total_salary": total_salary,
        })


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
