#!/usr/bin/env python3
"""
School Academic Management Mini App — Premium Edition
=====================================================
Telegram Mini App with automatic user detection, premium UI,
clean assessment workflow, and FREE Telegram backup/restore.
"""

from flask import Flask, request, jsonify, render_template_string, has_request_context
import sqlite3
import os
import shutil
import re
import json
from datetime import datetime

try:
    import requests
except ImportError:
    requests = None

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production-please")

DB = os.environ.get("DB_PATH", "bot_database.db")
ADMIN_ID = str(os.environ.get("ADMIN_ID", "440321906"))
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()


# ============================================================
# DATABASE HELPERS
# ============================================================

def connect():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("PRAGMA journal_mode = WAL")
    return c


def all_rows(sql, args=()):
    with connect() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def one(sql, args=()):
    with connect() as c:
        r = c.execute(sql, args).fetchone()
        return dict(r) if r else None


def run(sql, args=()):
    with connect() as c:
        cur = c.execute(sql, args)
        c.commit()
        return cur.lastrowid


def now():
    return datetime.now().isoformat(timespec="seconds")


def ensure_registration_codes():
    with connect() as c:
        classes = c.execute("""
            SELECT c.id, c.grade, c.section, c.academic_year_id, y.name AS year_name
            FROM school_classes c
            LEFT JOIN academic_years y ON y.id = c.academic_year_id
            LEFT JOIN section_registration_codes rc ON rc.class_id = c.id
            WHERE rc.id IS NULL
        """).fetchall()

        for row in classes:
            yearpart = str(row["academic_year_id"])
            if row["year_name"]:
                m = re.search(r"(20\d{2})", str(row["year_name"]))
                if m:
                    yearpart = m.group(1)

            base = f"G{row['grade']}{row['section']}-{yearpart}"
            code = base
            n = 2
            while c.execute(
                "SELECT 1 FROM section_registration_codes WHERE code = ?", (code,)
            ).fetchone():
                code = f"{base}-{n}"
                n += 1

            c.execute(
                """INSERT INTO section_registration_codes
                   (class_id, code, status, created_at)
                   VALUES (?, ?, 'active', ?)""",
                (row["id"], code, now()),
            )
        c.commit()


def migrate_db():
    try:
        with connect() as c:
            try:
                c.execute("SELECT description FROM lessons LIMIT 1")
            except sqlite3.OperationalError:
                c.execute("ALTER TABLE lessons ADD COLUMN description TEXT")

            try:
                c.execute("SELECT created_at FROM lessons LIMIT 1")
            except sqlite3.OperationalError:
                c.execute("ALTER TABLE lessons ADD COLUMN created_at TEXT")

            try:
                c.execute("SELECT assessment_type_id FROM academic_assessments LIMIT 1")
                c.execute("ALTER TABLE academic_assessments RENAME TO academic_assessments_old")
                c.execute("""
                    CREATE TABLE academic_assessments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        teacher_assignment_id INTEGER NOT NULL,
                        title TEXT NOT NULL,
                        max_score REAL DEFAULT 100,
                        assessment_date TEXT,
                        created_at TEXT,
                        FOREIGN KEY (teacher_assignment_id)
                            REFERENCES teacher_assignments(id) ON DELETE CASCADE
                    )
                """)
                c.execute("""
                    INSERT INTO academic_assessments
                        (id, teacher_assignment_id, title, max_score, assessment_date, created_at)
                    SELECT id, teacher_assignment_id, title, max_score, assessment_date, created_at
                    FROM academic_assessments_old
                """)
                c.execute("DROP TABLE academic_assessments_old")
            except sqlite3.OperationalError:
                pass

            try:
                c.execute("SELECT weight FROM academic_assessments LIMIT 1")
                try:
                    c.execute("ALTER TABLE academic_assessments DROP COLUMN weight")
                except sqlite3.OperationalError:
                    pass
            except sqlite3.OperationalError:
                pass

            try:
                c.execute("SELECT 1 FROM announcements LIMIT 1")
            except sqlite3.OperationalError:
                c.execute("""
                    CREATE TABLE announcements (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        body TEXT,
                        target_type TEXT NOT NULL,
                        target_id TEXT,
                        created_by TEXT,
                        created_at TEXT
                    )
                """)

            c.commit()
            print("✓ Database migration completed")
    except Exception as e:
        print(f"Migration error: {e}")


def init_db():
    try:
        with connect() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS academic_years (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    start_date TEXT,
                    end_date TEXT,
                    status TEXT DEFAULT 'planned',
                    created_at TEXT
                );

                CREATE TABLE IF NOT EXISTS school_classes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    grade TEXT NOT NULL,
                    section TEXT NOT NULL,
                    academic_year_id INTEGER,
                    status TEXT DEFAULT 'active',
                    created_at TEXT,
                    UNIQUE(name, academic_year_id),
                    FOREIGN KEY (academic_year_id) REFERENCES academic_years(id)
                );

                CREATE TABLE IF NOT EXISTS students (
                    telegram_id TEXT PRIMARY KEY,
                    student_id TEXT UNIQUE,
                    name TEXT NOT NULL,
                    sex TEXT,
                    class_id INTEGER,
                    class_name TEXT,
                    academic_year_id INTEGER,
                    created_at TEXT,
                    FOREIGN KEY (class_id) REFERENCES school_classes(id),
                    FOREIGN KEY (academic_year_id) REFERENCES academic_years(id)
                );

                CREATE TABLE IF NOT EXISTS teachers (
                    telegram_id TEXT PRIMARY KEY,
                    teacher_id TEXT UNIQUE,
                    name TEXT NOT NULL,
                    phone TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT
                );

                CREATE TABLE IF NOT EXISTS subjects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    code TEXT UNIQUE,
                    status TEXT DEFAULT 'active',
                    created_at TEXT
                );

                CREATE TABLE IF NOT EXISTS teacher_assignments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    teacher_telegram_id TEXT NOT NULL,
                    subject_id INTEGER NOT NULL,
                    class_id INTEGER NOT NULL,
                    academic_year_id INTEGER NOT NULL,
                    status TEXT DEFAULT 'active',
                    created_at TEXT,
                    UNIQUE(teacher_telegram_id, subject_id, class_id, academic_year_id),
                    FOREIGN KEY (teacher_telegram_id) REFERENCES teachers(telegram_id),
                    FOREIGN KEY (subject_id) REFERENCES subjects(id),
                    FOREIGN KEY (class_id) REFERENCES school_classes(id),
                    FOREIGN KEY (academic_year_id) REFERENCES academic_years(id)
                );

                CREATE TABLE IF NOT EXISTS lessons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    teacher_assignment_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    lesson_date TEXT,
                    created_at TEXT,
                    FOREIGN KEY (teacher_assignment_id)
                        REFERENCES teacher_assignments(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS academic_assessments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    teacher_assignment_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    max_score REAL DEFAULT 100,
                    assessment_date TEXT,
                    created_at TEXT,
                    FOREIGN KEY (teacher_assignment_id)
                        REFERENCES teacher_assignments(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    assessment_id INTEGER NOT NULL,
                    student_telegram_id TEXT NOT NULL,
                    score REAL,
                    entered_at TEXT,
                    UNIQUE(assessment_id, student_telegram_id),
                    FOREIGN KEY (assessment_id)
                        REFERENCES academic_assessments(id) ON DELETE CASCADE,
                    FOREIGN KEY (student_telegram_id)
                        REFERENCES students(telegram_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS grading_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    minimum_score REAL,
                    maximum_score REAL,
                    grade TEXT,
                    point REAL,
                    status TEXT DEFAULT 'active',
                    created_at TEXT
                );

                CREATE TABLE IF NOT EXISTS section_registration_codes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    class_id INTEGER NOT NULL UNIQUE,
                    code TEXT NOT NULL UNIQUE,
                    status TEXT DEFAULT 'active',
                    created_at TEXT,
                    FOREIGN KEY (class_id) REFERENCES school_classes(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS announcements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    body TEXT,
                    target_type TEXT NOT NULL,
                    target_id TEXT,
                    created_by TEXT,
                    created_at TEXT
                );
            """)
            c.commit()
            print("✓ Database initialized")
    except Exception as e:
        print(f"Database initialization error: {e}")


# ============================================================
# AUTH HELPERS
# ============================================================

def uid():
    if not has_request_context():
        return ""
    return str(request.args.get("id", "")).strip()


def is_admin():
    return uid() == ADMIN_ID


def get_role():
    user_id = uid()
    if not user_id:
        return None
    if user_id == ADMIN_ID:
        return "admin"
    try:
        if one("SELECT 1 FROM students WHERE telegram_id = ?", (user_id,)):
            return "student"
        teacher = one(
            "SELECT status FROM teachers WHERE telegram_id = ?", (user_id,)
        )
        if teacher:
            return "teacher"
    except Exception as e:
        print(f"get_role error: {e}")
    return None


def require_admin():
    return is_admin()


def teacher_owns_assignment(assignment_id, user_id):
    if is_admin():
        return True
    row = one(
        "SELECT teacher_telegram_id FROM teacher_assignments WHERE id = ?",
        (assignment_id,),
    )
    return row and str(row["teacher_telegram_id"]) == str(user_id)


def teacher_owns_lesson(lesson_id, user_id):
    if is_admin():
        return True
    row = one("""
        SELECT ta.teacher_telegram_id
        FROM lessons l
        JOIN teacher_assignments ta ON ta.id = l.teacher_assignment_id
        WHERE l.id = ?
    """, (lesson_id,))
    return row and str(row["teacher_telegram_id"]) == str(user_id)


def teacher_owns_assessment(assessment_id, user_id):
    if is_admin():
        return True
    row = one("""
        SELECT ta.teacher_telegram_id
        FROM academic_assessments aa
        JOIN teacher_assignments ta ON ta.id = aa.teacher_assignment_id
        WHERE aa.id = ?
    """, (assessment_id,))
    return row and str(row["teacher_telegram_id"]) == str(user_id)


# ============================================================
# TELEGRAM HELPERS (free backup storage)
# ============================================================

def send_telegram_document(chat_id, file_path, caption=""):
    """Send a file to a Telegram chat using Bot API. Returns (ok, message)."""
    if not BOT_TOKEN:
        return False, "BOT_TOKEN is not set. Add it in Render Environment variables."
    if requests is None:
        return False, "requests library missing. Add 'requests' to requirements.txt"
    if not os.path.isfile(file_path):
        return False, f"Database file not found: {file_path}"

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    try:
        with open(file_path, "rb") as f:
            resp = requests.post(
                url,
                data={
                    "chat_id": str(chat_id),
                    "caption": caption[:1024] if caption else "",
                },
                files={"document": (os.path.basename(file_path), f)},
                timeout=120,
            )
        data = resp.json()
        if data.get("ok"):
            return True, "Backup sent to your Telegram successfully."
        return False, data.get("description", "Telegram API error")
    except Exception as e:
        return False, str(e)


def send_telegram_message(chat_id, text):
    if not BOT_TOKEN or requests is None:
        return False
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": str(chat_id), "text": text[:4000]},
            timeout=30,
        )
        return True
    except Exception:
        return False


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():
    role = get_role()
    if not role:
        return render_template_string(UNAUTHORIZED_HTML, user_id=uid() or "—"), 403
    return render_template_string(HTML, user_id=uid(), user_role=role)


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/api/dashboard")
def dashboard():
    if not require_admin():
        return jsonify(error="Unauthorized"), 403

    tables = [
        "students", "teachers", "school_classes", "subjects",
        "lessons", "academic_assessments", "academic_years", "teacher_assignments"
    ]
    result = {}
    for t in tables:
        try:
            result[t] = one(f"SELECT COUNT(*) AS n FROM {t}")["n"]
        except Exception:
            result[t] = 0

    result["active_year"] = one("""
        SELECT id, name FROM academic_years
        WHERE status = 'active' ORDER BY id DESC LIMIT 1
    """)
    result["bot_token_set"] = bool(BOT_TOKEN)
    return jsonify(result)


# ============================================================
# TABLE DATA
# ============================================================

@app.route("/api/table/<name>")
def table(name):
    if not require_admin():
        return jsonify(error="Unauthorized"), 403

    queries = {
        "students": """
            SELECT st.*, c.name AS class_display, c.grade, c.section, y.name AS year_name
            FROM students st
            LEFT JOIN school_classes c ON c.id = st.class_id
            LEFT JOIN academic_years y ON y.id = st.academic_year_id
            ORDER BY st.name
        """,
        "teachers": """
            SELECT * FROM teachers
            ORDER BY CASE WHEN status = 'pending' THEN 0 ELSE 1 END, name
        """,
        "school_classes": """
            SELECT c.*, y.name AS year_name, rc.code AS registration_code
            FROM school_classes c
            LEFT JOIN academic_years y ON y.id = c.academic_year_id
            LEFT JOIN section_registration_codes rc ON rc.class_id = c.id
            ORDER BY CAST(c.grade AS INTEGER), c.section, c.name
        """,
        "subjects": "SELECT * FROM subjects ORDER BY name",
        "academic_years": "SELECT * FROM academic_years ORDER BY id DESC",
        "teacher_assignments": """
            SELECT ta.*, t.name AS teacher_name, t.teacher_id,
                   s.name AS subject_name, c.name AS class_name,
                   c.grade, c.section, y.name AS year_name
            FROM teacher_assignments ta
            LEFT JOIN teachers t ON t.telegram_id = ta.teacher_telegram_id
            LEFT JOIN subjects s ON s.id = ta.subject_id
            LEFT JOIN school_classes c ON c.id = ta.class_id
            LEFT JOIN academic_years y ON y.id = ta.academic_year_id
            ORDER BY CAST(c.grade AS INTEGER), c.section, s.name, t.name
        """,
        "lessons": """
            SELECT l.*, t.name AS teacher_name, s.name AS subject_name,
                   c.name AS class_name, c.grade, c.section, y.name AS year_name
            FROM lessons l
            LEFT JOIN teacher_assignments ta ON ta.id = l.teacher_assignment_id
            LEFT JOIN teachers t ON t.telegram_id = ta.teacher_telegram_id
            LEFT JOIN subjects s ON s.id = ta.subject_id
            LEFT JOIN school_classes c ON c.id = ta.class_id
            LEFT JOIN academic_years y ON y.id = ta.academic_year_id
            ORDER BY l.lesson_date DESC, l.id DESC
        """,
        "academic_assessments": """
            SELECT a.*, t.name AS teacher_name, s.name AS subject_name,
                   c.name AS class_name, c.grade, c.section
            FROM academic_assessments a
            LEFT JOIN teacher_assignments ta ON ta.id = a.teacher_assignment_id
            LEFT JOIN teachers t ON t.telegram_id = ta.teacher_telegram_id
            LEFT JOIN subjects s ON s.id = ta.subject_id
            LEFT JOIN school_classes c ON c.id = ta.class_id
            ORDER BY a.assessment_date DESC, a.id DESC
        """,
        "grading_rules": "SELECT * FROM grading_rules ORDER BY minimum_score DESC",
    }

    if name not in queries:
        return jsonify(error="Invalid section"), 400

    try:
        return jsonify(all_rows(queries[name]))
    except Exception as e:
        return jsonify(error=str(e)), 500


# ============================================================
# OPTIONS
# ============================================================

@app.route("/api/options")
def options():
    if not require_admin():
        return jsonify(error="Unauthorized"), 403

    ensure_registration_codes()

    teachers = all_rows(
        "SELECT telegram_id, name, teacher_id, status FROM teachers ORDER BY name"
    )
    classes = all_rows("""
        SELECT c.id, c.name, c.grade, c.section, c.academic_year_id, c.status,
               y.name AS year_name, rc.code AS registration_code
        FROM school_classes c
        LEFT JOIN academic_years y ON y.id = c.academic_year_id
        LEFT JOIN section_registration_codes rc ON rc.class_id = c.id
        ORDER BY CAST(c.grade AS INTEGER), c.section, c.name
    """)
    subjects = all_rows(
        "SELECT id, name, code, status FROM subjects ORDER BY name"
    )
    years = all_rows(
        "SELECT id, name, status FROM academic_years ORDER BY id DESC"
    )
    assignments = all_rows("""
        SELECT ta.id, ta.teacher_telegram_id, ta.subject_id, ta.class_id,
               ta.academic_year_id, t.name AS teacher_name, t.teacher_id,
               s.name AS subject_name, c.name AS class_name,
               c.grade, c.section, y.name AS year_name
        FROM teacher_assignments ta
        JOIN teachers t ON t.telegram_id = ta.teacher_telegram_id
        JOIN subjects s ON s.id = ta.subject_id
        JOIN school_classes c ON c.id = ta.class_id
        JOIN academic_years y ON y.id = ta.academic_year_id
        WHERE ta.status = 'active'
        ORDER BY CAST(c.grade AS INTEGER), c.section, s.name
    """)
    grading_rules = all_rows("""
        SELECT id, name, minimum_score, maximum_score, grade, point
        FROM grading_rules WHERE status = 'active'
        ORDER BY minimum_score DESC
    """)

    return jsonify(
        teachers=teachers,
        classes=classes,
        subjects=subjects,
        years=years,
        assignments=assignments,
        grading_rules=grading_rules,
    )


# ============================================================
# CREATE / SAVE
# ============================================================

@app.route("/api/save/<name>", methods=["POST"])
def save(name):
    user_id = uid()
    role = get_role()
    d = request.get_json(silent=True) or {}
    created = now()

    teacher_allowed = name == "lessons"

    if role == "admin":
        pass
    elif role == "teacher" and teacher_allowed:
        pass
    else:
        return jsonify(error="Unauthorized"), 403

    try:
        with connect() as c:
            if name == "students":
                return jsonify(error="Students register themselves via the bot."), 403
            if name == "teachers":
                return jsonify(error="Teachers register themselves via the bot."), 403

            if name == "school_classes":
                if role != "admin":
                    return jsonify(error="Unauthorized"), 403
                grade = str(d.get("grade", "")).strip()
                section = str(d.get("section", "")).strip().upper()
                year_id = d.get("academic_year_id")
                if not re.fullmatch(r"[0-9]+", grade):
                    return jsonify(error="Grade must contain numbers only."), 400
                if not re.fullmatch(r"[A-Z]+", section):
                    return jsonify(error="Section must contain letters only."), 400
                if not year_id:
                    return jsonify(error="Academic year is required"), 400
                if not one("SELECT id FROM academic_years WHERE id = ?", (year_id,)):
                    return jsonify(error="Academic year not found"), 400
                class_name = f"Grade {grade}{section}"
                if one(
                    "SELECT id FROM school_classes WHERE name = ? AND academic_year_id = ?",
                    (class_name, year_id),
                ):
                    return jsonify(error="This class already exists in that academic year."), 400
                cur = c.execute(
                    """INSERT INTO school_classes
                       (name, grade, section, academic_year_id, status, created_at)
                       VALUES (?, ?, ?, ?, 'active', ?)""",
                    (class_name, grade, section, year_id, created),
                )
                class_id = cur.lastrowid
                yearrow = one("SELECT name FROM academic_years WHERE id = ?", (year_id,))
                m = re.search(r"(20\d{2})", str(yearrow.get("name") if yearrow else ""))
                yearpart = m.group(1) if m else str(year_id)
                base = f"G{grade}{section}-{yearpart}"
                code = base
                n = 2
                while c.execute(
                    "SELECT 1 FROM section_registration_codes WHERE code = ?", (code,)
                ).fetchone():
                    code = f"{base}-{n}"
                    n += 1
                c.execute(
                    """INSERT INTO section_registration_codes
                       (class_id, code, status, created_at) VALUES (?, ?, 'active', ?)""",
                    (class_id, code, created),
                )

            elif name == "subjects":
                if role != "admin":
                    return jsonify(error="Unauthorized"), 403
                subject_name = str(d.get("name", "")).strip()
                code = str(d.get("code", "")).strip() or None
                if not subject_name:
                    return jsonify(error="Subject name is required"), 400
                if one("SELECT id FROM subjects WHERE LOWER(name) = LOWER(?)", (subject_name,)):
                    return jsonify(error="This subject already exists."), 400
                if code and one("SELECT id FROM subjects WHERE code = ?", (code,)):
                    return jsonify(error="This subject code already exists."), 400
                c.execute(
                    "INSERT INTO subjects (name, code, status, created_at) VALUES (?, ?, 'active', ?)",
                    (subject_name, code, created),
                )

            elif name == "academic_years":
                if role != "admin":
                    return jsonify(error="Unauthorized"), 403
                year_name = str(d.get("name", "")).strip()
                start_date = d.get("start_date") or ""
                end_date = d.get("end_date") or ""
                status = d.get("status") or "planned"
                if not year_name:
                    return jsonify(error="Academic year name is required"), 400
                if one("SELECT id FROM academic_years WHERE LOWER(name) = LOWER(?)", (year_name,)):
                    return jsonify(error="This academic year already exists."), 400
                if status == "active":
                    c.execute("UPDATE academic_years SET status = 'planned'")
                c.execute(
                    """INSERT INTO academic_years
                       (name, start_date, end_date, status, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (year_name, start_date, end_date, status, created),
                )

            elif name == "teacher_assignments":
                if role != "admin":
                    return jsonify(error="Unauthorized"), 403
                teacher = str(d.get("teacher_telegram_id", "")).strip()
                subject = d.get("subject_id")
                class_id = d.get("class_id")
                year_id = d.get("academic_year_id")
                if not all([teacher, subject, class_id, year_id]):
                    return jsonify(error="All fields are required"), 400
                teacher_row = one(
                    "SELECT telegram_id, status FROM teachers WHERE telegram_id = ?",
                    (teacher,),
                )
                if not teacher_row:
                    return jsonify(error="Teacher is not registered."), 400
                if teacher_row["status"] != "approved":
                    return jsonify(error="Teacher is not approved yet."), 400
                if not one("SELECT id FROM subjects WHERE id = ?", (subject,)):
                    return jsonify(error="Subject not found"), 400
                if not one("SELECT id FROM school_classes WHERE id = ?", (class_id,)):
                    return jsonify(error="Class not found"), 400
                if not one("SELECT id FROM academic_years WHERE id = ?", (year_id,)):
                    return jsonify(error="Academic year not found"), 400
                if one(
                    """SELECT id FROM teacher_assignments
                       WHERE teacher_telegram_id = ? AND subject_id = ?
                         AND class_id = ? AND academic_year_id = ?""",
                    (teacher, subject, class_id, year_id),
                ):
                    return jsonify(error="This teacher is already assigned to this subject and class."), 400
                c.execute(
                    """INSERT INTO teacher_assignments
                       (teacher_telegram_id, subject_id, class_id, academic_year_id, status, created_at)
                       VALUES (?, ?, ?, ?, 'active', ?)""",
                    (teacher, subject, class_id, year_id, created),
                )

            elif name == "lessons":
                assignment_id = d.get("teacher_assignment_id")
                title = str(d.get("title", "")).strip()
                description = str(d.get("description", "")).strip()
                lesson_date = d.get("lesson_date") or datetime.now().strftime("%Y-%m-%d")
                if not assignment_id:
                    return jsonify(error="Class assignment is required"), 400
                if not title:
                    return jsonify(error="Message title is required"), 400
                if not teacher_owns_assignment(assignment_id, user_id):
                    return jsonify(error="You do not own this assignment"), 403
                c.execute(
                    """INSERT INTO lessons
                       (teacher_assignment_id, title, description, lesson_date, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (assignment_id, title, description, lesson_date, created),
                )

            elif name == "academic_assessments":
                if role != "admin":
                    return jsonify(error="Only admins can create assessments."), 403
                assignment_id = d.get("teacher_assignment_id")
                title = str(d.get("title", "")).strip()
                try:
                    max_score = float(d.get("max_score") or 100)
                except (TypeError, ValueError):
                    return jsonify(error="Invalid max score"), 400
                assessment_date = d.get("assessment_date") or datetime.now().strftime("%Y-%m-%d")
                if not assignment_id:
                    return jsonify(error="Class assignment is required"), 400
                if not title:
                    return jsonify(error="Assessment name is required"), 400
                if max_score <= 0 or max_score > 100:
                    return jsonify(error="Out of % must be between 0.01 and 100."), 400
                if not one("SELECT id FROM teacher_assignments WHERE id = ?", (assignment_id,)):
                    return jsonify(error="Invalid assignment"), 400
                c.execute(
                    """INSERT INTO academic_assessments
                       (teacher_assignment_id, title, max_score, assessment_date, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (assignment_id, title, max_score, assessment_date, created),
                )

            elif name == "grading_rules":
                if role != "admin":
                    return jsonify(error="Unauthorized"), 403
                c.execute(
                    """INSERT INTO grading_rules
                       (name, minimum_score, maximum_score, grade, point, status, created_at)
                       VALUES (?, ?, ?, ?, ?, 'active', ?)""",
                    (
                        d.get("name", ""),
                        d.get("minimum_score"),
                        d.get("maximum_score"),
                        d.get("grade"),
                        d.get("point"),
                        created,
                    ),
                )
            else:
                return jsonify(error="This section is not writable"), 400

            c.commit()
            return jsonify(ok=True)

    except sqlite3.IntegrityError as e:
        return jsonify(error="Database constraint: " + str(e)), 400
    except Exception as e:
        return jsonify(error=str(e)), 500


# ============================================================
# DELETE
# ============================================================

@app.route("/api/delete/<name>/<item_id>", methods=["DELETE"])
def delete(name, item_id):
    user_id = uid()
    role = get_role()
    teacher_allowed = name == "lessons"

    if role == "admin":
        pass
    elif role == "teacher" and teacher_allowed:
        pass
    else:
        return jsonify(error="Unauthorized"), 403

    try:
        with connect() as c:
            if name == "students":
                if role != "admin":
                    return jsonify(error="Unauthorized"), 403
                c.execute("DELETE FROM results WHERE student_telegram_id = ?", (item_id,))
                c.execute("DELETE FROM students WHERE telegram_id = ?", (item_id,))
                c.commit()
                return jsonify(ok=True)

            if name == "teachers":
                if role != "admin":
                    return jsonify(error="Unauthorized"), 403
                assignments = c.execute(
                    "SELECT id FROM teacher_assignments WHERE teacher_telegram_id = ?",
                    (item_id,),
                ).fetchall()
                for a in assignments:
                    aid = a["id"]
                    c.execute(
                        "DELETE FROM results WHERE assessment_id IN "
                        "(SELECT id FROM academic_assessments WHERE teacher_assignment_id = ?)",
                        (aid,),
                    )
                    c.execute("DELETE FROM academic_assessments WHERE teacher_assignment_id = ?", (aid,))
                    c.execute("DELETE FROM lessons WHERE teacher_assignment_id = ?", (aid,))
                c.execute("DELETE FROM teacher_assignments WHERE teacher_telegram_id = ?", (item_id,))
                c.execute("DELETE FROM teachers WHERE telegram_id = ?", (item_id,))
                c.commit()
                return jsonify(ok=True)

            if name == "school_classes":
                if role != "admin":
                    return jsonify(error="Unauthorized"), 403
                class_id = item_id
                if not c.execute("SELECT id FROM school_classes WHERE id = ?", (class_id,)).fetchone():
                    return jsonify(error="Class not found"), 404
                c.execute("""
                    DELETE FROM results WHERE assessment_id IN (
                        SELECT aa.id FROM academic_assessments aa
                        JOIN teacher_assignments ta ON ta.id = aa.teacher_assignment_id
                        WHERE ta.class_id = ?)""", (class_id,))
                c.execute("""
                    DELETE FROM academic_assessments WHERE teacher_assignment_id IN (
                        SELECT id FROM teacher_assignments WHERE class_id = ?)""", (class_id,))
                c.execute("""
                    DELETE FROM lessons WHERE teacher_assignment_id IN (
                        SELECT id FROM teacher_assignments WHERE class_id = ?)""", (class_id,))
                c.execute("DELETE FROM teacher_assignments WHERE class_id = ?", (class_id,))
                c.execute("UPDATE students SET class_id = NULL, class_name = '' WHERE class_id = ?", (class_id,))
                try:
                    c.execute("DELETE FROM section_registration_codes WHERE class_id = ?", (class_id,))
                except sqlite3.OperationalError:
                    pass
                c.execute("DELETE FROM school_classes WHERE id = ?", (class_id,))
                c.commit()
                return jsonify(ok=True)

            if name == "subjects":
                if role != "admin":
                    return jsonify(error="Unauthorized"), 403
                subject_id = item_id
                if not c.execute("SELECT id FROM subjects WHERE id = ?", (subject_id,)).fetchone():
                    return jsonify(error="Subject not found"), 404
                c.execute("""
                    DELETE FROM results WHERE assessment_id IN (
                        SELECT aa.id FROM academic_assessments aa
                        JOIN teacher_assignments ta ON ta.id = aa.teacher_assignment_id
                        WHERE ta.subject_id = ?)""", (subject_id,))
                c.execute("""
                    DELETE FROM academic_assessments WHERE teacher_assignment_id IN (
                        SELECT id FROM teacher_assignments WHERE subject_id = ?)""", (subject_id,))
                c.execute("""
                    DELETE FROM lessons WHERE teacher_assignment_id IN (
                        SELECT id FROM teacher_assignments WHERE subject_id = ?)""", (subject_id,))
                c.execute("DELETE FROM teacher_assignments WHERE subject_id = ?", (subject_id,))
                c.execute("DELETE FROM subjects WHERE id = ?", (subject_id,))
                c.commit()
                return jsonify(ok=True)

            if name == "academic_years":
                if role != "admin":
                    return jsonify(error="Unauthorized"), 403
                year_id = item_id
                if not c.execute("SELECT id FROM academic_years WHERE id = ?", (year_id,)).fetchone():
                    return jsonify(error="Academic year not found"), 404
                c.execute(
                    "UPDATE students SET academic_year_id = NULL, class_id = NULL, class_name = '' WHERE academic_year_id = ?",
                    (year_id,),
                )
                c.execute("""
                    DELETE FROM results WHERE assessment_id IN (
                        SELECT aa.id FROM academic_assessments aa
                        JOIN teacher_assignments ta ON ta.id = aa.teacher_assignment_id
                        WHERE ta.academic_year_id = ?)""", (year_id,))
                c.execute("""
                    DELETE FROM academic_assessments WHERE teacher_assignment_id IN (
                        SELECT id FROM teacher_assignments WHERE academic_year_id = ?)""", (year_id,))
                c.execute("""
                    DELETE FROM lessons WHERE teacher_assignment_id IN (
                        SELECT id FROM teacher_assignments WHERE academic_year_id = ?)""", (year_id,))
                c.execute("DELETE FROM teacher_assignments WHERE academic_year_id = ?", (year_id,))
                c.execute("DELETE FROM school_classes WHERE academic_year_id = ?", (year_id,))
                c.execute("DELETE FROM academic_years WHERE id = ?", (year_id,))
                c.commit()
                return jsonify(ok=True)

            if name == "teacher_assignments":
                if role != "admin":
                    return jsonify(error="Unauthorized"), 403
                assignment_id = item_id
                c.execute("""
                    DELETE FROM results WHERE assessment_id IN (
                        SELECT id FROM academic_assessments WHERE teacher_assignment_id = ?)""", (assignment_id,))
                c.execute("DELETE FROM academic_assessments WHERE teacher_assignment_id = ?", (assignment_id,))
                c.execute("DELETE FROM lessons WHERE teacher_assignment_id = ?", (assignment_id,))
                c.execute("DELETE FROM teacher_assignments WHERE id = ?", (assignment_id,))
                c.commit()
                return jsonify(ok=True)

            if name == "lessons":
                if not teacher_owns_lesson(item_id, user_id):
                    return jsonify(error="You do not own this message"), 403
                c.execute("DELETE FROM lessons WHERE id = ?", (item_id,))
                c.commit()
                return jsonify(ok=True)

            if name == "academic_assessments":
                if not teacher_owns_assessment(item_id, user_id):
                    return jsonify(error="You do not own this assessment"), 403
                c.execute("DELETE FROM results WHERE assessment_id = ?", (item_id,))
                c.execute("DELETE FROM academic_assessments WHERE id = ?", (item_id,))
                c.commit()
                return jsonify(ok=True)

            if name == "grading_rules":
                if role != "admin":
                    return jsonify(error="Unauthorized"), 403
                c.execute("DELETE FROM grading_rules WHERE id = ?", (item_id,))
                c.commit()
                return jsonify(ok=True)

            return jsonify(error="Invalid section"), 400

    except sqlite3.OperationalError as e:
        return jsonify(error=f"Database error: {str(e)}"), 500
    except Exception as e:
        return jsonify(error=str(e)), 500


# ============================================================
# STUDENT SEARCH & TEACHER STATUS
# ============================================================

@app.route("/api/students/search")
def student_search():
    if not require_admin():
        return jsonify(error="Unauthorized"), 403
    q = str(request.args.get("q", "")).strip()
    class_id = request.args.get("class_id")
    if class_id:
        try:
            class_id = int(class_id)
        except (TypeError, ValueError):
            return jsonify(error="Invalid class ID"), 400
    if not q and not class_id:
        return jsonify(students=[])
    sql = """
        SELECT st.telegram_id, st.name, st.sex, st.student_id, st.class_id,
               st.class_name, st.academic_year_id, c.name AS class_display,
               c.grade, c.section, y.name AS year_name
        FROM students st
        LEFT JOIN school_classes c ON c.id = st.class_id
        LEFT JOIN academic_years y ON y.id = st.academic_year_id
        WHERE 1 = 1
    """
    args = []
    if q:
        sql += " AND LOWER(st.name) LIKE LOWER(?)"
        args.append("%" + q + "%")
    if class_id:
        sql += " AND st.class_id = ?"
        args.append(class_id)
    sql += " ORDER BY st.name LIMIT 200"
    try:
        return jsonify(students=all_rows(sql, args))
    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route("/api/teacher/status/<teacher_id>", methods=["POST"])
def teacher_status(teacher_id):
    if not require_admin():
        return jsonify(error="Unauthorized"), 403
    d = request.get_json(silent=True) or {}
    status = d.get("status")
    if status not in ("approved", "pending", "rejected"):
        return jsonify(error="Invalid teacher status"), 400
    try:
        run("UPDATE teachers SET status = ? WHERE telegram_id = ?", (status, teacher_id))
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(error=str(e)), 500


# ============================================================
# ASSESSMENT STUDENTS & SCORE FEED
# ============================================================

@app.route("/api/assessment/students")
def assessment_students():
    user_id = uid()
    if not user_id:
        return jsonify(error="Unauthorized"), 401
    assignment_id = request.args.get("assignment_id")
    assessment_id = request.args.get("assessment_id")
    if not assignment_id or not assessment_id:
        return jsonify(error="Assignment and assessment required"), 400

    assignment = one("""
        SELECT ta.id, ta.class_id, ta.academic_year_id, ta.teacher_telegram_id,
               c.name AS class_name, c.grade, c.section, s.name AS subject_name
        FROM teacher_assignments ta
        JOIN school_classes c ON c.id = ta.class_id
        JOIN subjects s ON s.id = ta.subject_id
        WHERE ta.id = ?
    """, (assignment_id,))
    if not assignment:
        return jsonify(error="Assignment not found"), 404
    if not is_admin() and str(assignment["teacher_telegram_id"]) != str(user_id):
        return jsonify(error="You don't have permission for this assessment"), 403

    assessment = one(
        "SELECT id, max_score, teacher_assignment_id, title FROM academic_assessments WHERE id = ?",
        (assessment_id,),
    )
    if not assessment:
        return jsonify(error="Assessment not found"), 404
    if str(assessment["teacher_assignment_id"]) != str(assignment_id):
        return jsonify(error="Assessment and assignment do not match."), 400

    students = all_rows("""
        SELECT st.telegram_id, st.student_id, st.name, st.sex,
               r.score, r.id AS result_id
        FROM students st
        LEFT JOIN results r
               ON r.student_telegram_id = st.telegram_id AND r.assessment_id = ?
        WHERE st.class_id = ?
          AND (st.academic_year_id = ? OR st.academic_year_id IS NULL OR ? IS NULL)
        ORDER BY st.name
    """, (assessment_id, assignment["class_id"], assignment["academic_year_id"], assignment["academic_year_id"]))

    return jsonify(assignment=assignment, assessment=assessment, students=students)


@app.route("/api/assessment/feed", methods=["POST"])
def assessment_feed():
    user_id = uid()
    if not user_id:
        return jsonify(error="Unauthorized"), 401
    d = request.get_json(silent=True) or {}
    assessment_id = d.get("assessment_id")
    scores = d.get("scores", [])
    if not assessment_id:
        return jsonify(error="Assessment required"), 400
    try:
        assessment_id = int(assessment_id)
    except (TypeError, ValueError):
        return jsonify(error="Invalid assessment id"), 400
    if not scores:
        return jsonify(error="No scores submitted"), 400

    meta = one("""
        SELECT aa.id, aa.max_score, ta.teacher_telegram_id
        FROM academic_assessments aa
        JOIN teacher_assignments ta ON ta.id = aa.teacher_assignment_id
        WHERE aa.id = ?
    """, (assessment_id,))
    if not meta:
        return jsonify(error="Assessment not found"), 404
    if not is_admin() and str(meta["teacher_telegram_id"]) != str(user_id):
        return jsonify(error="You don't have permission for this assessment"), 403

    max_s = float(meta["max_score"] or 100)
    saved = 0
    errors = []

    try:
        c = sqlite3.connect(DB, timeout=30)
        c.row_factory = sqlite3.Row
        try:
            c.execute("PRAGMA foreign_keys = OFF")
            c.execute("BEGIN")
            for entry in scores:
                telegram_id = str(entry.get("telegram_id") or "").strip()
                student_code = str(entry.get("student_id") or "").strip()
                raw_score = entry.get("score")
                if raw_score in ("", None):
                    continue
                try:
                    score = float(raw_score)
                except (TypeError, ValueError):
                    errors.append(f"Invalid score: {raw_score}")
                    continue
                if score < 0 or score > max_s:
                    errors.append(f"Score {score} out of range (max {max_s})")
                    continue
                student = None
                if telegram_id:
                    student = c.execute(
                        "SELECT telegram_id FROM students WHERE CAST(telegram_id AS TEXT) = ?",
                        (telegram_id,),
                    ).fetchone()
                if not student and student_code:
                    student = c.execute(
                        "SELECT telegram_id FROM students WHERE CAST(student_id AS TEXT) = ?",
                        (student_code,),
                    ).fetchone()
                if not student and student_code:
                    student = c.execute(
                        "SELECT telegram_id FROM students WHERE CAST(telegram_id AS TEXT) = ?",
                        (student_code,),
                    ).fetchone()
                if not student:
                    errors.append(f"Student not found (tg={telegram_id or '-'}, code={student_code or '-'})")
                    continue
                tg = str(student["telegram_id"]).strip()
                existing = c.execute(
                    """SELECT id FROM results
                       WHERE assessment_id = ? AND CAST(student_telegram_id AS TEXT) = ?""",
                    (assessment_id, tg),
                ).fetchone()
                try:
                    if existing:
                        c.execute(
                            "UPDATE results SET score = ?, entered_at = ? WHERE id = ?",
                            (score, now(), existing["id"]),
                        )
                    else:
                        c.execute(
                            """INSERT INTO results
                               (assessment_id, student_telegram_id, score, entered_at)
                               VALUES (?, ?, ?, ?)""",
                            (assessment_id, tg, score, now()),
                        )
                    saved += 1
                except Exception as ie:
                    errors.append(f"{tg}: {ie}")
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

        if saved == 0:
            msg = "No scores saved."
            if errors:
                msg += " " + "; ".join(errors[:5])
            return jsonify(error=msg), 400
        return jsonify(ok=True, saved=saved, errors=errors[:10] if errors else [])
    except Exception as e:
        return jsonify(error=str(e)), 500


# ============================================================
# STUDENT API
# ============================================================

def student_info(student_id):
    return one("""
        SELECT st.*, c.name AS class_display, c.grade, c.section, y.name AS year_name
        FROM students st
        LEFT JOIN school_classes c ON c.id = st.class_id
        LEFT JOIN academic_years y ON y.id = st.academic_year_id
        WHERE st.telegram_id = ?
    """, (student_id,))


def student_average(student_id, year_id):
    subjects = all_rows("""
        SELECT DISTINCT ta.subject_id, s.name
        FROM results r
        JOIN academic_assessments aa ON aa.id = r.assessment_id
        JOIN teacher_assignments ta ON ta.id = aa.teacher_assignment_id
        JOIN subjects s ON s.id = ta.subject_id
        WHERE r.student_telegram_id = ? AND ta.academic_year_id = ?
        ORDER BY s.name
    """, (student_id, year_id))
    averages = []
    for subject in subjects:
        rows = all_rows("""
            SELECT r.score, aa.max_score
            FROM results r
            JOIN academic_assessments aa ON aa.id = r.assessment_id
            JOIN teacher_assignments ta ON ta.id = aa.teacher_assignment_id
            WHERE r.student_telegram_id = ?
              AND ta.subject_id = ?
              AND ta.academic_year_id = ?
        """, (student_id, subject["subject_id"], year_id))
        if not rows:
            continue
        total = sum(
            (row["score"] / row["max_score"]) * 100
            for row in rows if row["max_score"] and row["max_score"] > 0
        )
        avg = total / len(rows) if rows else 0
        averages.append({"subject": subject["name"], "average": round(avg, 2)})
    return averages


@app.route("/api/student")
def student_api():
    if get_role() != "student":
        return jsonify(error="Unauthorized"), 403
    student_id = uid()
    student = student_info(student_id)
    if not student:
        return jsonify(error="Student not found"), 404
    lessons = all_rows("""
        SELECT l.id, l.title, l.description, l.lesson_date,
               s.name AS subject_name, t.name AS teacher_name
        FROM lessons l
        JOIN teacher_assignments ta ON ta.id = l.teacher_assignment_id
        JOIN subjects s ON s.id = ta.subject_id
        JOIN teachers t ON t.telegram_id = ta.teacher_telegram_id
        WHERE ta.class_id = ? AND ta.academic_year_id = ?
        ORDER BY l.lesson_date DESC, l.id DESC
    """, (student["class_id"], student["academic_year_id"]))
    results = all_rows("""
        SELECT aa.id, aa.title, s.name AS subject_name, aa.max_score,
               r.score, aa.assessment_date
        FROM results r
        JOIN academic_assessments aa ON aa.id = r.assessment_id
        JOIN teacher_assignments ta ON ta.id = aa.teacher_assignment_id
        JOIN subjects s ON s.id = ta.subject_id
        WHERE r.student_telegram_id = ?
        ORDER BY aa.assessment_date DESC, aa.id DESC
    """, (student_id,))
    averages = student_average(student_id, student["academic_year_id"])
    overall = (
        round(sum(x["average"] for x in averages) / len(averages), 2)
        if averages else None
    )
    return jsonify(student=student, lessons=lessons, results=results, averages=averages, overall=overall)


# ============================================================
# TEACHER API
# ============================================================

@app.route("/api/teacher")
def teacher_api():
    user_id = uid()
    if not user_id:
        return jsonify(error="No user ID provided"), 401
    role = get_role()
    if role not in ("teacher", "admin"):
        check = one("SELECT telegram_id, status FROM teachers WHERE telegram_id = ?", (user_id,))
        if not check:
            return jsonify(error="You are not registered as a teacher."), 403
        if check.get("status") != "approved":
            return jsonify(error=f"Your teacher account is {check.get('status')}."), 403

    teacher = one(
        "SELECT telegram_id, name, teacher_id, status, created_at FROM teachers WHERE telegram_id = ?",
        (user_id,),
    )
    if not teacher:
        return jsonify(error="Teacher not found"), 404

    assignments = all_rows("""
        SELECT ta.id, ta.class_id, ta.subject_id, ta.academic_year_id,
               c.name AS class_name, c.grade, c.section,
               s.name AS subject_name, s.code AS subject_code,
               y.name AS year_name
        FROM teacher_assignments ta
        LEFT JOIN school_classes c ON c.id = ta.class_id
        LEFT JOIN subjects s ON s.id = ta.subject_id
        LEFT JOIN academic_years y ON y.id = ta.academic_year_id
        WHERE ta.teacher_telegram_id = ?
        ORDER BY c.grade ASC, c.section ASC, s.name ASC
    """, (user_id,))
    messages = all_rows("""
        SELECT l.id, l.title, l.description, l.lesson_date, l.created_at,
               s.name AS subject_name, c.name AS class_name, c.grade, c.section
        FROM lessons l
        LEFT JOIN teacher_assignments ta ON ta.id = l.teacher_assignment_id
        LEFT JOIN subjects s ON s.id = ta.subject_id
        LEFT JOIN school_classes c ON c.id = ta.class_id
        WHERE ta.teacher_telegram_id = ?
        ORDER BY l.lesson_date DESC, l.id DESC
    """, (user_id,))
    assessments = all_rows("""
        SELECT aa.id, aa.title, aa.max_score, aa.assessment_date, aa.created_at,
               aa.teacher_assignment_id, s.name AS subject_name,
               c.name AS class_name, c.grade, c.section
        FROM academic_assessments aa
        LEFT JOIN teacher_assignments ta ON ta.id = aa.teacher_assignment_id
        LEFT JOIN subjects s ON s.id = ta.subject_id
        LEFT JOIN school_classes c ON c.id = ta.class_id
        WHERE ta.teacher_telegram_id = ?
        ORDER BY aa.assessment_date DESC, aa.id DESC
    """, (user_id,))
    return jsonify({"teacher": teacher, "assignments": assignments, "messages": messages, "assessments": assessments})


# ============================================================
# REPORTS
# ============================================================

@app.route("/api/reports")
def reports():
    if not require_admin():
        return jsonify(error="Unauthorized"), 403
    year_id = request.args.get("year_id")
    if not year_id:
        active = one("SELECT id FROM academic_years WHERE status = 'active' ORDER BY id DESC LIMIT 1")
        if active:
            year_id = active["id"]
    if not year_id:
        return jsonify(error="No academic year"), 400

    sql = """
        SELECT st.telegram_id, st.name, st.student_id,
               c.id AS class_id, c.name AS class_name, c.grade, c.section
        FROM students st
        LEFT JOIN school_classes c ON c.id = st.class_id
        WHERE st.academic_year_id = ?
    """
    args = [year_id]
    class_id = request.args.get("class_id")
    grade = request.args.get("grade")
    section = request.args.get("section")
    student_id = request.args.get("student_id")
    if class_id:
        sql += " AND c.id = ?"
        args.append(class_id)
    if grade:
        sql += " AND c.grade = ?"
        args.append(grade)
    if section:
        sql += " AND c.section = ?"
        args.append(section)
    if student_id:
        sql += " AND st.student_id = ?"
        args.append(student_id)
    sql += " ORDER BY CAST(c.grade AS INTEGER), c.section, st.name"
    students = all_rows(sql, tuple(args))

    student_rows = []
    for student in students:
        av = student_average(student["telegram_id"], year_id)
        average = round(sum(x["average"] for x in av) / len(av), 2) if av else None
        student_rows.append({**student, "average": average})

    ranked = sorted(
        [x for x in student_rows if x["average"] is not None],
        key=lambda x: (-x["average"], str(x["name"]).lower()),
    )
    for i, row in enumerate(ranked, 1):
        row["rank"] = i

    school_values = [x["average"] for x in student_rows if x["average"] is not None]
    school_average = round(sum(school_values) / len(school_values), 2) if school_values else None

    return jsonify(
        year_id=year_id,
        rows=student_rows,
        ranking=ranked,
        school_average=school_average,
    )


# ============================================================
# ANNOUNCEMENTS
# ============================================================

@app.route("/api/announcements", methods=["GET"])
def list_announcements():
    if not require_admin():
        return jsonify(error="Unauthorized"), 403
    rows = all_rows("SELECT * FROM announcements ORDER BY created_at DESC, id DESC LIMIT 200")
    return jsonify(announcements=rows)


@app.route("/api/announcements", methods=["POST"])
def create_announcement():
    if not require_admin():
        return jsonify(error="Unauthorized"), 403
    d = request.get_json(silent=True) or {}
    title = str(d.get("title", "")).strip()
    body = str(d.get("body", "")).strip()
    target_type = str(d.get("target_type", "")).strip()
    target_id = str(d.get("target_id", "")).strip() or None
    allowed = ("all_students", "all_teachers", "class", "student", "teacher")
    if not title:
        return jsonify(error="Title is required"), 400
    if target_type not in allowed:
        return jsonify(error="Invalid target type"), 400
    if target_type in ("class", "student", "teacher") and not target_id:
        return jsonify(error="Target is required for this filter"), 400
    try:
        run("""
            INSERT INTO announcements (title, body, target_type, target_id, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (title, body, target_type, target_id, uid(), now()))
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route("/api/announcements/<int:aid>", methods=["DELETE"])
def delete_announcement(aid):
    if not require_admin():
        return jsonify(error="Unauthorized"), 403
    try:
        run("DELETE FROM announcements WHERE id = ?", (aid,))
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route("/api/my-announcements")
def my_announcements():
    user_id = uid()
    role = get_role()
    if not user_id or role not in ("student", "teacher", "admin"):
        return jsonify(error="Unauthorized"), 403
    rows = []
    if role == "admin":
        rows = all_rows("SELECT * FROM announcements ORDER BY created_at DESC LIMIT 50")
    elif role == "student":
        st = one("SELECT class_id FROM students WHERE telegram_id = ?", (user_id,))
        class_id = str(st["class_id"]) if st and st.get("class_id") else None
        rows = all_rows("""
            SELECT * FROM announcements
            WHERE target_type = 'all_students'
               OR (target_type = 'class' AND target_id = ?)
               OR (target_type = 'student' AND target_id = ?)
            ORDER BY created_at DESC LIMIT 50
        """, (class_id, user_id))
    elif role == "teacher":
        rows = all_rows("""
            SELECT * FROM announcements
            WHERE target_type = 'all_teachers'
               OR (target_type = 'teacher' AND target_id = ?)
            ORDER BY created_at DESC LIMIT 50
        """, (user_id,))
    return jsonify(announcements=rows)


# ============================================================
# BACKUP + TELEGRAM BACKUP + RESTORE
# ============================================================

@app.route("/api/backup")
def backup():
    """Create a local timestamped copy of the database."""
    if not require_admin():
        return jsonify(error="Unauthorized"), 403
    try:
        if not os.path.isfile(DB):
            return jsonify(error="Database file not found"), 404
        filename = f"bot_database_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        shutil.copy2(DB, filename)
        return jsonify(ok=True, file=filename)
    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route("/api/backup/telegram", methods=["POST"])
def backup_to_telegram():
    """Send the current database file to the admin's Telegram chat (FREE storage)."""
    if not require_admin():
        return jsonify(error="Unauthorized"), 403
    if not BOT_TOKEN:
        return jsonify(error="BOT_TOKEN is not set. Add it in Render → Environment."), 400
    if not os.path.isfile(DB):
        return jsonify(error="Database file not found on server"), 404

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    caption = (
        f"📦 School Academic Database Backup\n"
        f"📅 {stamp}\n"
        f"Keep this file safe in Saved Messages.\n"
        f"To restore later: open the Mini App → Backup → Upload & Restore."
    )
    ok, msg = send_telegram_document(ADMIN_ID, DB, caption)
    if ok:
        return jsonify(ok=True, message=msg)
    return jsonify(error=msg), 500


@app.route("/api/restore", methods=["POST"])
def restore_database():
    """
    Restore database from an uploaded .db file.
    Admin downloads the backup from Telegram, then uploads it here.
    """
    if not require_admin():
        return jsonify(error="Unauthorized"), 403

    if "file" not in request.files:
        return jsonify(error="No file uploaded. Choose a .db backup file."), 400

    f = request.files["file"]
    if not f or not f.filename:
        return jsonify(error="Empty file"), 400

    filename = f.filename.lower()
    if not (filename.endswith(".db") or filename.endswith(".sqlite") or filename.endswith(".sqlite3")):
        return jsonify(error="File must be a .db (SQLite) backup"), 400

    # Safety: save to a temp path first, then replace
    tmp_path = DB + ".restore_tmp"
    try:
        f.save(tmp_path)
        # Quick validation: try opening as SQLite
        test = sqlite3.connect(tmp_path)
        test.execute("SELECT 1")
        test.close()

        # Replace live database
        # Close any potential locks by using a new name then rename
        bak_path = DB + ".before_restore"
        if os.path.isfile(DB):
            shutil.copy2(DB, bak_path)
        shutil.move(tmp_path, DB)

        # Run migrations on the restored DB
        migrate_db()

        send_telegram_message(
            ADMIN_ID,
            f"✅ Database restored successfully at {now()}\n"
            f"Previous copy kept as .before_restore on server (temporary)."
        )
        return jsonify(ok=True, message="Database restored successfully. Reload the page.")
    except Exception as e:
        if os.path.isfile(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        return jsonify(error=f"Restore failed: {e}"), 500


@app.route("/api/backup/status")
def backup_status():
    if not require_admin():
        return jsonify(error="Unauthorized"), 403
    size = 0
    exists = os.path.isfile(DB)
    if exists:
        size = os.path.getsize(DB)
    return jsonify(
        exists=exists,
        size_bytes=size,
        size_kb=round(size / 1024, 1),
        path=DB,
        bot_token_set=bool(BOT_TOKEN),
        admin_id=ADMIN_ID,
    )


# ============================================================
# UNAUTHORIZED PAGE
# ============================================================

UNAUTHORIZED_HTML = r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
  <title>School Academic</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    :root { --bg:#06080f; --card:#121826; --border:#1e293b; --text:#f1f5f9; --muted:#64748b; --accent:#22d3ee; }
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}
    .card{background:linear-gradient(165deg,#151b2d,#0c1220);border:1px solid var(--border);border-radius:24px;padding:2.5rem 2rem;max-width:380px;width:100%;text-align:center;box-shadow:0 25px 50px -12px rgb(0 0 0/.6)}
    .icon{width:64px;height:64px;margin:0 auto 1.25rem;background:linear-gradient(135deg,#0e7490,#6366f1);border-radius:18px;display:grid;place-items:center;font-size:28px}
    h1{font-size:1.5rem;margin-bottom:.5rem;font-weight:700}
    p{color:var(--muted);font-size:.95rem;line-height:1.55;margin:.4rem 0}
    .id{font-family:ui-monospace,monospace;background:#0a0e17;padding:.4rem .75rem;border-radius:8px;font-size:.8rem;color:var(--accent);display:inline-block;margin-top:.75rem}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">🔒</div>
    <h1>Access Required</h1>
    <p>Please open this app from the Telegram bot after registration.</p>
    <p class="id">ID: {{ user_id }}</p>
  </div>
  <script>
    if (window.Telegram && Telegram.WebApp) {
      Telegram.WebApp.ready();
      Telegram.WebApp.expand();
      const u = Telegram.WebApp.initDataUnsafe?.user;
      if (u && u.id) {
        const url = new URL(window.location.href);
        if (!url.searchParams.get("id")) {
          url.searchParams.set("id", String(u.id));
          window.location.replace(url.toString());
        }
      }
    }
  </script>
</body>
</html>
"""


# ============================================================
# PREMIUM HTML FRONTEND
# ============================================================

HTML = r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<title>School Academic</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root {
  --bg: #06080f; --bg2: #0a0e17; --surface: #0f1520; --card: #141c2b; --card-hover: #1a2436;
  --border: #1e2a3d; --border-light: #2a3a52; --text: #f1f5f9; --text2: #cbd5e1; --muted: #64748b;
  --accent: #22d3ee; --accent2: #818cf8; --accent-dim: rgba(34,211,238,.12);
  --success: #34d399; --success-bg: rgba(52,211,153,.12);
  --danger: #f87171; --danger-bg: rgba(248,113,113,.12);
  --warning: #fbbf24; --warning-bg: rgba(251,191,36,.12);
  --radius: 16px; --radius-sm: 10px; --shadow: 0 8px 30px -8px rgba(0,0,0,.5);
  --font: 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
}
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
html{scroll-behavior:smooth}
body{font-family:var(--font);background:var(--bg);color:var(--text);line-height:1.5;min-height:100vh;min-height:100dvh;overflow-x:hidden}
header{background:linear-gradient(180deg,#0c1220,#0a0e17);padding:14px 18px;position:sticky;top:0;z-index:60;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:12px;backdrop-filter:blur(12px)}
.logo{width:36px;height:36px;background:linear-gradient(135deg,#0e7490,#4f46e5);border-radius:11px;display:grid;place-items:center;font-size:16px;box-shadow:0 4px 14px rgba(14,116,144,.35);flex-shrink:0}
header h1{font-size:1.1rem;font-weight:700;letter-spacing:-.02em;background:linear-gradient(90deg,#f1f5f9,#94a3b8);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
nav{display:flex;gap:6px;overflow-x:auto;background:var(--bg2);padding:10px 12px;position:sticky;top:57px;z-index:50;border-bottom:1px solid var(--border);scrollbar-width:none}
nav::-webkit-scrollbar{display:none}
nav button{background:transparent;color:var(--muted);border:1px solid transparent;border-radius:999px;padding:8px 14px;white-space:nowrap;font-weight:600;font-size:12.5px;cursor:pointer;transition:all .18s;font-family:inherit}
nav button:hover{color:var(--text2);background:var(--card)}
nav button.active{background:linear-gradient(135deg,#0e7490,#6366f1);color:#fff;border-color:transparent;box-shadow:0 4px 12px rgba(99,102,241,.3)}
main{max-width:720px;margin:0 auto;padding:16px 14px 90px}
.card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:18px;margin-bottom:14px;box-shadow:var(--shadow);transition:border-color .2s}
.card:hover{border-color:var(--border-light)}
.hero{background:linear-gradient(145deg,#151b2d 0%,#1a1040 50%,#0c1220 100%);border-radius:20px;padding:22px 20px;margin-bottom:16px;border:1px solid rgba(99,102,241,.2);position:relative;overflow:hidden}
.hero::before{content:'';position:absolute;top:-40%;right:-20%;width:200px;height:200px;background:radial-gradient(circle,rgba(34,211,238,.08),transparent 70%);pointer-events:none}
.hero h2{margin:0 0 4px;font-size:1.35rem;font-weight:750;letter-spacing:-.02em}
.hero p{margin:0;color:#a5b4fc;font-size:.9rem}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-bottom:14px}
@media(min-width:560px){.grid{grid-template-columns:repeat(4,1fr)}}
.stat{text-align:center;padding:16px 10px}
.stat .muted{font-size:11px;text-transform:uppercase;letter-spacing:.04em;margin-bottom:4px}
.num,.number{font-size:1.7rem;font-weight:800;background:linear-gradient(135deg,var(--accent),var(--accent2));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;letter-spacing:-.03em}
.muted{color:var(--muted);font-size:13px}
h2{margin:0 0 12px;font-size:1.2rem;font-weight:700}
h3{margin:0 0 10px;font-size:1rem;font-weight:650;color:var(--text2)}
.toolbar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;align-items:flex-end}
button,.btn{border:0;border-radius:var(--radius-sm);padding:10px 16px;background:linear-gradient(135deg,#0e7490,#6366f1);color:#fff;font-weight:650;font-size:13px;cursor:pointer;transition:transform .12s,opacity .15s,box-shadow .15s;font-family:inherit;box-shadow:0 4px 12px rgba(99,102,241,.25)}
button:hover{opacity:.95;box-shadow:0 6px 16px rgba(99,102,241,.35)}
button:active{transform:scale(.97)}
button.alt{background:var(--surface);color:var(--text2);border:1px solid var(--border);box-shadow:none}
button.danger{background:var(--danger-bg);color:var(--danger);border:1px solid rgba(248,113,113,.25);box-shadow:none}
button.ok{background:var(--success-bg);color:var(--success);border:1px solid rgba(52,211,153,.25);box-shadow:none}
button:disabled{opacity:.45;cursor:not-allowed;transform:none}
input,select,textarea{width:100%;padding:11px 13px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--surface);color:var(--text);font-size:14px;margin:4px 0 10px;font-family:inherit;transition:border-color .15s,box-shadow .15s}
input:focus,select:focus,textarea:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-dim)}
label{font-size:11.5px;font-weight:650;color:var(--muted);display:block;text-transform:uppercase;letter-spacing:.03em}
.formgrid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
@media(max-width:520px){.formgrid{grid-template-columns:1fr}}
.tablewrap{overflow-x:auto;border-radius:12px;border:1px solid var(--border);-webkit-overflow-scrolling:touch}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:12px 14px;text-align:left;border-bottom:1px solid var(--border);white-space:nowrap}
th{background:var(--surface);color:var(--muted);font-weight:650;font-size:11px;text-transform:uppercase;letter-spacing:.04em}
tr:last-child td{border-bottom:0}
tr:hover td{background:rgba(255,255,255,.02)}
.badge{display:inline-block;padding:3px 10px;border-radius:999px;background:var(--surface);font-size:11.5px;font-weight:650;border:1px solid var(--border)}
.badge.pending{background:var(--warning-bg);color:var(--warning);border-color:rgba(251,191,36,.25)}
.badge.approved{background:var(--success-bg);color:var(--success);border-color:rgba(52,211,153,.25)}
.badge.rejected{background:var(--danger-bg);color:var(--danger);border-color:rgba(248,113,113,.25)}
.lesson{border-left:3px solid var(--accent);padding:14px 16px;background:var(--surface);border-radius:0 12px 12px 0;margin:8px 0;transition:background .15s}
.lesson:hover{background:var(--card-hover)}
.lesson b{display:block;margin-bottom:3px;font-size:14px}
.empty{color:var(--muted);font-style:italic;text-align:center;padding:28px 16px;font-size:14px}
.student-card{display:grid;grid-template-columns:1fr auto;gap:14px;align-items:center}
.student-name{font-size:1.05rem;font-weight:700}
.code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-weight:650;letter-spacing:.4px;background:var(--surface);padding:3px 9px;border-radius:6px;font-size:12px;border:1px solid var(--border);color:var(--accent)}
.filterbox{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:12px}
.toast{position:fixed;bottom:28px;left:50%;transform:translateX(-50%) translateY(20px);background:var(--card);border:1px solid var(--border-light);color:var(--text);padding:12px 22px;border-radius:14px;box-shadow:0 12px 40px rgba(0,0,0,.5);z-index:200;font-weight:600;font-size:13.5px;opacity:0;pointer-events:none;transition:opacity .25s,transform .25s;max-width:90vw;text-align:center}
.toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
.loading{display:flex;justify-content:center;align-items:center;padding:48px;color:var(--muted);gap:10px}
.spinner{width:22px;height:22px;border:2.5px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin .7s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
footer{text-align:center;padding:18px 14px 28px;color:#475569;font-size:11.5px;border-top:1px solid var(--border);margin-top:12px}
footer b{color:var(--muted)}
.score-input{width:100px!important;margin:0!important;text-align:center;font-weight:650}
#app{animation:fadeIn .25s ease}
@keyframes fadeIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}
.info-box{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:14px 16px;margin:12px 0;font-size:13px;line-height:1.55;color:var(--text2)}
.info-box b{color:var(--accent)}
</style>
</head>
<body>
<header>
  <div class="logo">✦</div>
  <h1>School Academic</h1>
</header>
<nav id="nav"></nav>
<main id="app"><div class="loading"><div class="spinner"></div> Loading…</div></main>
<footer>Built by <b>Magnificent Technologies</b> · Dagim Tariku</footer>
<div id="toast" class="toast"></div>

<script>
(function initTelegram() {
  if (window.Telegram && Telegram.WebApp) {
    const tg = Telegram.WebApp;
    tg.ready();
    tg.expand();
    try { tg.setHeaderColor('#0c1220'); } catch(_){}
    try { tg.setBackgroundColor('#06080f'); } catch(_){}
    const user = tg.initDataUnsafe && tg.initDataUnsafe.user;
    if (user && user.id) {
      const url = new URL(window.location.href);
      if (!url.searchParams.get("id")) {
        url.searchParams.set("id", String(user.id));
        window.location.replace(url.toString());
        return;
      }
    }
  }
})();

const ID   = {{ user_id|tojson }};
const ROLE = {{ user_role|tojson }};

function api(url, options = {}) {
  const sep = url.includes("?") ? "&" : "?";
  return fetch(url + sep + "id=" + encodeURIComponent(ID), options)
    .then(async res => {
      let data = {};
      try { data = await res.json(); } catch (_) {}
      if (!res.ok) throw new Error(data.error || ("Request failed (" + res.status + ")"));
      return data;
    });
}

function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, m => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]));
}

function toast(msg, ms = 2800) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(window._toastT);
  window._toastT = setTimeout(() => el.classList.remove("show"), ms);
}

function setNav(items) {
  document.getElementById("nav").innerHTML = items.map(([key, label]) =>
    `<button onclick="show('${key}')" id="n_${key}">${label}</button>`
  ).join("");
}

function active(key) {
  document.querySelectorAll("nav button").forEach(b => b.classList.remove("active"));
  const b = document.getElementById("n_" + key);
  if (b) b.classList.add("active");
}

function show(key) {
  active(key);
  const pages = {
    dashboard: adminDashboard, students, teachers, classes, subjects, assignments,
    lessons, announcements, assessments, years, reports, backup,
    studentHome, teacherHome, teacherMessages, teacherAssessments
  };
  if (pages[key]) pages[key]();
}

function selectHTML(label, name, options, required = true) {
  return `<div>
    <label>${label}</label>
    <select name="${name}" ${required ? "required" : ""}>
      <option value="">Select…</option>
      ${options.map(x => `<option value="${esc(x[0])}">${esc(x[1])}</option>`).join("")}
    </select>
  </div>`;
}

function showError(e) {
  document.getElementById("app").innerHTML =
    `<div class="card"><h2>Something went wrong</h2><p class="muted">${esc(e.message)}</p>
     <button class="alt" onclick="location.reload()">Reload</button></div>`;
}

async function adminDashboard() {
  try {
    const d = await api("/api/dashboard");
    const items = [
      ["students","Students"], ["teachers","Teachers"],
      ["school_classes","Classes"], ["subjects","Subjects"],
      ["teacher_assignments","Assignments"], ["lessons","Messages"],
      ["academic_assessments","Assessments"], ["academic_years","Years"]
    ];
    document.getElementById("app").innerHTML = `
      <div class="hero">
        <h2>Admin Dashboard</h2>
        <p>Overview of the entire school system</p>
      </div>
      <div class="grid">${items.map(x => `
        <div class="card stat">
          <div class="muted">${x[1]}</div>
          <div class="num">${d[x[0]] ?? 0}</div>
        </div>
      `).join("")}</div>
      <div class="card">
        <span class="muted">Active academic year</span><br>
        <b style="font-size:1.1rem;margin-top:4px;display:inline-block">${esc(d.active_year?.name || "Not set")}</b>
      </div>
      ${d.bot_token_set
        ? `<div class="info-box">✅ Telegram backup is configured. Use <b>Backup</b> tab to save data to your Telegram.</div>`
        : `<div class="info-box">⚠️ <b>BOT_TOKEN</b> not set. Add it in Render → Environment to enable free Telegram backups.</div>`}`;
  } catch (e) { showError(e); }
}

async function students() {
  try {
    const o = await api("/api/options");
    document.getElementById("app").innerHTML = `
      <div class="hero"><h2>Students</h2><p>Search and manage enrolled students</p></div>
      <div class="card">
        <div class="toolbar">
          <div style="flex:2"><label>Search by name</label>
            <input id="studentSearch" placeholder="Type a name…"></div>
          <div style="flex:1"><label>Class</label>
            <select id="studentClass">
              <option value="">All classes</option>
              ${o.classes.map(x => `<option value="${esc(x.id)}">${esc(x.name)}</option>`).join("")}
            </select>
          </div>
          <button onclick="searchStudents()">Search</button>
          <button class="alt" onclick="students()">Clear</button>
        </div>
      </div>
      <div id="studentResults"><div class="card empty">Search for a student to begin.</div></div>`;
  } catch (e) { showError(e); }
}

async function searchStudents() {
  const q = document.getElementById("studentSearch").value.trim();
  const c = document.getElementById("studentClass").value;
  if (!q && !c) { toast("Enter a name or select a class"); return; }
  try {
    const p = new URLSearchParams();
    if (q) p.set("q", q);
    if (c) p.set("class_id", c);
    const d = await api("/api/students/search?" + p.toString());
    document.getElementById("studentResults").innerHTML = d.students.length
      ? d.students.map(x => `
        <div class="card student-card">
          <div>
            <div class="student-name">${esc(x.name)}</div>
            <div class="muted">ID: ${esc(x.student_id)} · TG: ${esc(x.telegram_id)}</div>
            <p style="margin-top:6px"><b>Class:</b> ${esc(x.class_display || "Unassigned")}
               · <b>Sex:</b> ${esc(x.sex || "—")}</p>
          </div>
          <button class="danger" onclick="deleteItem('students','${esc(x.telegram_id)}','student')">Delete</button>
        </div>`).join("")
      : `<div class="card empty">No matching students found.</div>`;
  } catch (e) { toast(e.message); }
}

async function teachers() {
  try {
    const data = await api("/api/table/teachers");
    document.getElementById("app").innerHTML = `
      <div class="hero"><h2>Teachers</h2><p>Approve or manage teacher accounts</p></div>
      <div class="tablewrap"><table>
        <thead><tr><th>Name</th><th>ID</th><th>Telegram</th><th>Status</th><th>Action</th></tr></thead>
        <tbody>${data.map(r => `
          <tr>
            <td><b>${esc(r.name)}</b></td>
            <td>${esc(r.teacher_id)}</td>
            <td>${esc(r.telegram_id)}</td>
            <td><span class="badge ${esc(r.status)}">${esc(r.status)}</span></td>
            <td>
              ${r.status === "pending" ? `
                <button class="ok" onclick="setTeacherStatus('${esc(r.telegram_id)}','approved')">Approve</button>
                <button class="danger" onclick="setTeacherStatus('${esc(r.telegram_id)}','rejected')">Reject</button>
              ` : `<button class="danger" onclick="deleteItem('teachers','${esc(r.telegram_id)}','teacher')">Delete</button>`}
            </td>
          </tr>`).join("") || `<tr><td colspan="5" class="empty">No teachers yet.</td></tr>`}
        </tbody>
      </table></div>`;
  } catch (e) { showError(e); }
}

async function setTeacherStatus(id, status) {
  try {
    await api("/api/teacher/status/" + id, {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ status })
    });
    toast(status === "approved" ? "Teacher approved" : "Teacher rejected");
    teachers();
  } catch (e) { toast(e.message); }
}

async function classes() {
  try {
    const [data, o] = await Promise.all([api("/api/table/school_classes"), api("/api/options")]);
    document.getElementById("app").innerHTML = `
      <div class="hero"><h2>Classes</h2><p>Create and manage grade sections</p></div>
      <div class="card">
        <h3>Add Class</h3>
        <form onsubmit="saveClass(event)">
          <div class="formgrid">
            <div><label>Grade (numbers only)</label><input name="grade" pattern="[0-9]+" placeholder="6" required></div>
            <div><label>Section (letters only)</label><input name="section" pattern="[A-Za-z]+" placeholder="A" required></div>
            ${selectHTML("Academic Year", "academic_year_id", o.years.map(x => [x.id, x.name + (x.status === "active" ? " — ACTIVE" : "")]))}
          </div>
          <button>＋ Add Class</button>
        </form>
      </div>
      <div class="tablewrap"><table>
        <thead><tr><th>Class</th><th>Grade</th><th>Section</th><th>Year</th><th>Code</th><th></th></tr></thead>
        <tbody>${data.map(r => `
          <tr>
            <td><b>${esc(r.name)}</b></td>
            <td>${esc(r.grade)}</td>
            <td>${esc(r.section)}</td>
            <td>${esc(r.year_name || r.academic_year_id)}</td>
            <td><span class="code">${esc(r.registration_code || "—")}</span></td>
            <td><button class="danger" onclick="deleteItem('school_classes','${esc(r.id)}','class')">Delete</button></td>
          </tr>`).join("") || `<tr><td colspan="6" class="empty">No classes yet.</td></tr>`}
        </tbody>
      </table></div>`;
  } catch (e) { showError(e); }
}

async function saveClass(e) {
  e.preventDefault();
  const d = Object.fromEntries(new FormData(e.target));
  if (!/^[0-9]+$/.test(d.grade) || !/^[A-Za-z]+$/.test(d.section)) {
    toast("Grade = numbers only, Section = letters only"); return;
  }
  try {
    await api("/api/save/school_classes", {
      method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(d)
    });
    toast("Class created"); classes();
  } catch (err) { toast(err.message); }
}

async function subjects() {
  try {
    const data = await api("/api/table/subjects");
    document.getElementById("app").innerHTML = `
      <div class="hero"><h2>Subjects</h2><p>Manage curriculum subjects</p></div>
      <div class="card">
        <h3>Add Subject</h3>
        <form onsubmit="saveSubject(event)">
          <div class="formgrid">
            <div><label>Name</label><input name="name" placeholder="Mathematics" required></div>
            <div><label>Code (optional)</label><input name="code" placeholder="MATH"></div>
          </div>
          <button>＋ Add Subject</button>
        </form>
      </div>
      <div class="tablewrap"><table>
        <thead><tr><th>ID</th><th>Subject</th><th>Code</th><th></th></tr></thead>
        <tbody>${data.map(r => `
          <tr>
            <td>${esc(r.id)}</td><td>${esc(r.name)}</td><td>${esc(r.code || "—")}</td>
            <td><button class="danger" onclick="deleteItem('subjects','${esc(r.id)}','subject')">Delete</button></td>
          </tr>`).join("") || `<tr><td colspan="4" class="empty">No subjects.</td></tr>`}
        </tbody>
      </table></div>`;
  } catch (e) { showError(e); }
}

async function saveSubject(e) {
  e.preventDefault();
  try {
    await api("/api/save/subjects", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify(Object.fromEntries(new FormData(e.target)))
    });
    toast("Subject added"); subjects();
  } catch (err) { toast(err.message); }
}

async function years() {
  try {
    const data = await api("/api/table/academic_years");
    document.getElementById("app").innerHTML = `
      <div class="hero"><h2>Academic Years</h2><p>Define school years and set the active one</p></div>
      <div class="card">
        <h3>Add Year</h3>
        <form onsubmit="saveYear(event)">
          <div class="formgrid">
            <div><label>Name</label><input name="name" placeholder="2017 E.C." required></div>
            <div><label>Start</label><input type="date" name="start_date"></div>
            <div><label>End</label><input type="date" name="end_date"></div>
            <div><label>Status</label>
              <select name="status">
                <option value="planned">Planned</option>
                <option value="active">Active</option>
                <option value="closed">Closed</option>
              </select>
            </div>
          </div>
          <button>＋ Add Year</button>
        </form>
      </div>
      <div class="tablewrap"><table>
        <thead><tr><th>ID</th><th>Name</th><th>Start</th><th>End</th><th>Status</th><th></th></tr></thead>
        <tbody>${data.map(r => `
          <tr>
            <td>${esc(r.id)}</td><td><b>${esc(r.name)}</b></td>
            <td>${esc(r.start_date || "—")}</td><td>${esc(r.end_date || "—")}</td>
            <td><span class="badge">${esc(r.status)}</span></td>
            <td><button class="danger" onclick="deleteItem('academic_years','${esc(r.id)}','year')">Delete</button></td>
          </tr>`).join("") || `<tr><td colspan="6" class="empty">No years defined.</td></tr>`}
        </tbody>
      </table></div>`;
  } catch (e) { showError(e); }
}

async function saveYear(e) {
  e.preventDefault();
  try {
    await api("/api/save/academic_years", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify(Object.fromEntries(new FormData(e.target)))
    });
    toast("Year created"); years();
  } catch (err) { toast(err.message); }
}

async function assignments() {
  try {
    const o = await api("/api/options");
    const teachers = o.teachers.filter(t => t.status === "approved").map(t => [t.telegram_id, `${t.name} (${t.teacher_id})`]);
    const classes = o.classes.map(c => [c.id, `Grade ${c.grade}${c.section}`]);
    const subjects = o.subjects.map(s => [s.id, s.name]);
    const years = o.years.map(y => [y.id, y.name]);
    document.getElementById("app").innerHTML = `
      <div class="hero"><h2>Teacher Assignments</h2><p>Link teachers to subjects & classes</p></div>
      <div class="card">
        <h3>New Assignment</h3>
        <form onsubmit="saveAssignment(event)">
          <div class="formgrid">
            ${selectHTML("Teacher", "teacher_telegram_id", teachers)}
            ${selectHTML("Class", "class_id", classes)}
            ${selectHTML("Subject", "subject_id", subjects)}
            ${selectHTML("Year", "academic_year_id", years)}
          </div>
          <button>🔗 Assign</button>
        </form>
      </div>
      <div class="tablewrap"><table>
        <thead><tr><th>Teacher</th><th>Class</th><th>Subject</th><th>Year</th><th></th></tr></thead>
        <tbody>${o.assignments.map(x => `
          <tr>
            <td>${esc(x.teacher_name)}</td>
            <td>Grade ${esc(x.grade)}${esc(x.section)}</td>
            <td>${esc(x.subject_name)}</td>
            <td>${esc(x.year_name)}</td>
            <td><button class="danger" onclick="deleteItem('teacher_assignments','${esc(x.id)}','assignment')">Delete</button></td>
          </tr>`).join("") || `<tr><td colspan="5" class="empty">No assignments yet.</td></tr>`}
        </tbody>
      </table></div>`;
  } catch (e) { showError(e); }
}

async function saveAssignment(e) {
  e.preventDefault();
  try {
    await api("/api/save/teacher_assignments", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify(Object.fromEntries(new FormData(e.target)))
    });
    toast("Assignment created"); assignments();
  } catch (err) { toast(err.message); }
}

async function lessons() {
  try {
    const data = await api("/api/table/lessons");
    document.getElementById("app").innerHTML = `
      <div class="hero"><h2>Teacher Messages</h2><p>All messages sent by teachers</p></div>
      <div id="lessonsList"></div>`;
    const box = document.getElementById("lessonsList");
    if (!data.length) { box.innerHTML = `<div class="card empty">No messages yet.</div>`; return; }
    box.innerHTML = data.map(x => `
      <div class="lesson">
        <b>📩 ${esc(x.title || "Message")}</b>
        👨‍🏫 ${esc(x.teacher_name || "—")} · 📚 ${esc(x.subject_name || "—")}<br>
        🏫 Grade ${esc(x.grade || "—")}${esc(x.section || "")} · 📅 ${esc(x.lesson_date || "—")}
        ${x.description ? `<div class="muted" style="margin-top:6px">${esc(x.description)}</div>` : ""}
      </div>`).join("");
  } catch (e) { showError(e); }
}

async function announcements() {
  try {
    const [list, o] = await Promise.all([api("/api/announcements"), api("/api/options")]);
    const targetLabels = { all_students:"All Students", all_teachers:"All Teachers", class:"Specific Class", student:"Specific Student", teacher:"Specific Teacher" };
    document.getElementById("app").innerHTML = `
      <div class="hero"><h2>📢 Broadcast Messages</h2><p>Send messages to students, teachers, a class, or a person</p></div>
      <div class="card">
        <h3>New Announcement</h3>
        <form onsubmit="sendAnnouncement(event)">
          <div class="formgrid">
            <div>
              <label>Target</label>
              <select name="target_type" id="annTargetType" required onchange="toggleAnnTarget()">
                <option value="all_students">All Students</option>
                <option value="all_teachers">All Teachers</option>
                <option value="class">Specific Class</option>
                <option value="student">Specific Student</option>
                <option value="teacher">Specific Teacher</option>
              </select>
            </div>
            <div id="annTargetWrap" style="display:none">
              <label id="annTargetLabel">Select</label>
              <select name="target_id" id="annTargetId"><option value="">Select…</option></select>
            </div>
            <div style="grid-column:1/-1"><label>Title</label><input name="title" placeholder="Announcement title…" required></div>
            <div style="grid-column:1/-1"><label>Message</label><textarea name="body" rows="3" placeholder="Write the message…"></textarea></div>
          </div>
          <button>📢 Send Broadcast</button>
        </form>
      </div>
      <div class="card">
        <h3>Recent Announcements</h3>
        ${(list.announcements || []).length
          ? list.announcements.map(a => `
              <div class="lesson">
                <b>📢 ${esc(a.title)}</b>
                <div class="muted">Target: <b>${esc(targetLabels[a.target_type] || a.target_type)}</b>
                  ${a.target_id ? " · ID: " + esc(a.target_id) : ""} · ${esc(a.created_at || "")}</div>
                ${a.body ? `<div style="margin-top:6px">${esc(a.body)}</div>` : ""}
                <button class="danger" style="margin-top:8px" onclick="deleteAnnouncement(${a.id})">Delete</button>
              </div>`).join("")
          : "<p class='empty'>No announcements yet.</p>"}
      </div>`;
    window._annOptions = o;
    toggleAnnTarget();
  } catch (e) { showError(e); }
}

function toggleAnnTarget() {
  const type = document.getElementById("annTargetType")?.value;
  const wrap = document.getElementById("annTargetWrap");
  const sel = document.getElementById("annTargetId");
  const label = document.getElementById("annTargetLabel");
  if (!wrap || !sel) return;
  if (type === "class" || type === "student" || type === "teacher") {
    wrap.style.display = "block";
    const o = window._annOptions || {};
    let opts = [];
    if (type === "class") {
      label.textContent = "Class";
      opts = (o.classes || []).map(c => [c.id, `Grade ${c.grade}${c.section} (${c.name})`]);
    } else if (type === "student") {
      label.textContent = "Student (paste Telegram ID if needed)";
      sel.innerHTML = `<option value="">Paste student telegram ID…</option>`;
      return;
    } else if (type === "teacher") {
      label.textContent = "Teacher";
      opts = (o.teachers || []).filter(t => t.status === "approved").map(t => [t.telegram_id, `${t.name} (${t.teacher_id})`]);
    }
    sel.innerHTML = `<option value="">Select…</option>` + opts.map(x => `<option value="${esc(x[0])}">${esc(x[1])}</option>`).join("");
  } else wrap.style.display = "none";
}

async function sendAnnouncement(e) {
  e.preventDefault();
  const fd = new FormData(e.target);
  const target_type = fd.get("target_type");
  let target_id = fd.get("target_id") || null;
  if (target_type === "student" && !target_id) {
    target_id = prompt("Enter student Telegram ID:");
    if (!target_id) { toast("Student ID required"); return; }
  }
  try {
    await api("/api/announcements", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({ title: fd.get("title"), body: fd.get("body"), target_type, target_id })
    });
    toast("Announcement sent"); announcements();
  } catch (err) { toast(err.message); }
}

async function deleteAnnouncement(id) {
  if (!confirm("Delete this announcement?")) return;
  try {
    await api("/api/announcements/" + id, { method: "DELETE" });
    toast("Deleted"); announcements();
  } catch (err) { toast(err.message); }
}

async function assessments() {
  try {
    const [data, o] = await Promise.all([api("/api/table/academic_assessments"), api("/api/options")]);
    document.getElementById("app").innerHTML = `
      <div class="hero"><h2>Assessments</h2><p>Create assessments with a name and max score only</p></div>
      <div class="card">
        <h3>Create Assessment</h3>
        <form onsubmit="createAssessment(event)">
          <div class="formgrid">
            <div>
              <label>Class Assignment</label>
              <select name="teacher_assignment_id" required>
                <option value="">Select…</option>
                ${o.assignments.map(x => `
                  <option value="${esc(x.id)}">Grade ${esc(x.grade)}${esc(x.section)} — ${esc(x.subject_name)} (${esc(x.teacher_name)})</option>`).join("")}
              </select>
            </div>
            <div><label>Assessment Name</label><input name="title" placeholder="e.g. Mid-term Exam" required></div>
            <div><label>Out of %</label><input name="max_score" type="number" min="0.01" max="100" step="0.01" value="100" required></div>
            <div><label>Date</label><input name="assessment_date" type="date" value="${new Date().toISOString().slice(0,10)}"></div>
          </div>
          <button>📝 Create Assessment</button>
        </form>
      </div>
      <div class="tablewrap"><table>
        <thead><tr><th>Assessment</th><th>Class</th><th>Subject</th><th>Teacher</th><th>Max</th><th>Date</th><th></th></tr></thead>
        <tbody>${data.length ? data.map(x => `
          <tr>
            <td><b>${esc(x.title)}</b></td>
            <td>Grade ${esc(x.grade)}${esc(x.section)}</td>
            <td>${esc(x.subject_name)}</td>
            <td>${esc(x.teacher_name)}</td>
            <td>${esc(x.max_score)}</td>
            <td>${esc(x.assessment_date)}</td>
            <td><button class="danger" onclick="deleteItem('academic_assessments','${esc(x.id)}','assessment')">Delete</button></td>
          </tr>`).join("") : `<tr><td colspan="7" class="empty">No assessments yet.</td></tr>`}
        </tbody>
      </table></div>`;
  } catch (e) { showError(e); }
}

async function createAssessment(e) {
  e.preventDefault();
  const fd = new FormData(e.target);
  try {
    await api("/api/save/academic_assessments", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({
        teacher_assignment_id: fd.get("teacher_assignment_id"),
        title: fd.get("title"),
        max_score: fd.get("max_score"),
        assessment_date: fd.get("assessment_date")
      })
    });
    toast("Assessment created"); assessments();
  } catch (err) { toast(err.message); }
}

async function reports() {
  try {
    const options = await api("/api/options");
    document.getElementById("app").innerHTML = `
      <div class="hero"><h2>Reports</h2><p>School-wide performance analytics</p></div>
      <div class="card">
        <div class="filterbox">
          <div>
            <label>Academic Year</label>
            <select id="reportYear">
              <option value="">Select…</option>
              ${options.years.map(y => `<option value="${esc(y.id)}" ${y.status === "active" ? "selected" : ""}>${esc(y.name)}</option>`).join("")}
            </select>
          </div>
        </div>
        <button onclick="runReport()">📊 Generate Report</button>
      </div>
      <div id="reportOutput"><div class="card empty">Choose a year and generate a report.</div></div>`;
  } catch (e) { showError(e); }
}

async function runReport() {
  const year = document.getElementById("reportYear").value;
  if (!year) { toast("Select a year first"); return; }
  try {
    const d = await api("/api/reports?year_id=" + year);
    document.getElementById("reportOutput").innerHTML = `
      <div class="grid">
        <div class="card stat"><div class="muted">School Average</div>
          <div class="number">${d.school_average == null ? "—" : d.school_average.toFixed(1) + "%"}</div></div>
        <div class="card stat"><div class="muted">Students Ranked</div>
          <div class="number">${d.ranking.length}</div></div>
      </div>
      <div class="card">
        <h3>Student Ranking</h3>
        <div class="tablewrap"><table>
          <thead><tr><th>Rank</th><th>Student</th><th>Grade</th><th>Section</th><th>Average</th></tr></thead>
          <tbody>${d.ranking.map(x => `
            <tr>
              <td><b>#${x.rank}</b></td><td>${esc(x.name)}</td>
              <td>${esc(x.grade)}</td><td>${esc(x.section)}</td>
              <td><b>${x.average.toFixed(1)}%</b></td>
            </tr>`).join("") || `<tr><td colspan="5" class="empty">No results.</td></tr>`}
          </tbody>
        </table></div>
      </div>`;
  } catch (e) { showError(e); }
}

/* ========== BACKUP (Telegram + Restore) ========== */
async function backup() {
  let status = { bot_token_set: false, size_kb: 0, exists: false };
  try { status = await api("/api/backup/status"); } catch(_){}

  document.getElementById("app").innerHTML = `
    <div class="hero">
      <h2>💾 Backup & Restore</h2>
      <p>Free storage using your Telegram account</p>
    </div>

    <div class="card">
      <h3>Current Database</h3>
      <p class="muted">
        ${status.exists
          ? `Size: <b>${status.size_kb} KB</b> · Path: ${esc(status.path || "—")}`
          : "No database file found yet."}
      </p>
      <p class="muted" style="margin-top:6px">
        Telegram backup: ${status.bot_token_set
          ? '<span style="color:var(--success)">✅ Ready</span>'
          : '<span style="color:var(--warning)">⚠️ BOT_TOKEN missing</span>'}
      </p>
    </div>

    <div class="card">
      <h3>1. Send backup to Telegram (recommended)</h3>
      <p class="muted" style="margin-bottom:12px">
        Sends the full database file to <b>your</b> Telegram chat.
        Save it in <b>Saved Messages</b>. Completely free.
      </p>
      <button onclick="sendBackupToTelegram()" ${status.bot_token_set ? "" : "disabled"}>
        📤 Send Database to My Telegram
      </button>
    </div>

    <div class="card">
      <h3>2. Restore from a backup file</h3>
      <p class="muted" style="margin-bottom:12px">
        Download the .db file from your Telegram Saved Messages,
        then upload it here to restore all data.
      </p>
      <input type="file" id="restoreFile" accept=".db,.sqlite,.sqlite3" style="margin-bottom:12px">
      <button class="ok" onclick="restoreFromFile()">♻️ Upload & Restore Database</button>
    </div>

    <div class="info-box">
      <b>How free Telegram storage works</b><br>
      1. Click “Send Database to My Telegram” → file arrives in your chat.<br>
      2. Forward it to <b>Saved Messages</b> so it never disappears.<br>
      3. If Render restarts and data is lost, download the file and use Restore.<br>
      4. Do this regularly (e.g. after important changes).
    </div>
  `;
}

async function sendBackupToTelegram() {
  try {
    toast("Sending backup to Telegram…");
    const r = await api("/api/backup/telegram", { method: "POST" });
    toast(r.message || "Backup sent! Check your Telegram.");
  } catch (e) {
    toast(e.message);
  }
}

async function restoreFromFile() {
  const input = document.getElementById("restoreFile");
  if (!input || !input.files || !input.files[0]) {
    toast("Please choose a .db backup file first");
    return;
  }
  if (!confirm("This will REPLACE the current database with the uploaded file. Continue?")) return;

  const fd = new FormData();
  fd.append("file", input.files[0]);

  try {
    toast("Restoring database…");
    const sep = "?";
    const res = await fetch("/api/restore" + sep + "id=" + encodeURIComponent(ID), {
      method: "POST",
      body: fd
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "Restore failed");
    toast(data.message || "Database restored!");
    setTimeout(() => location.reload(), 1500);
  } catch (e) {
    toast(e.message);
  }
}

async function deleteItem(name, id, label) {
  if (!confirm(`Delete this ${label}? This cannot be undone.`)) return;
  try {
    await api("/api/delete/" + name + "/" + encodeURIComponent(id), { method: "DELETE" });
    toast("Deleted");
    if (ROLE === "admin") show("dashboard");
    else if (ROLE === "teacher") show("teacherHome");
  } catch (e) { toast(e.message); }
}

async function studentHome() {
  try {
    const [d, ann] = await Promise.all([
      api("/api/student"),
      api("/api/my-announcements").catch(() => ({ announcements: [] }))
    ]);
    const s = d.student;
    setNav([["studentHome", "🏠 Dashboard"]]);
    active("studentHome");
    document.getElementById("app").innerHTML = `
      <div class="hero">
        <h2>Hello, ${esc(s.name)}</h2>
        <p>ID ${esc(s.student_id)} · Grade ${esc(s.grade || "")}${esc(s.section || "")}</p>
      </div>
      <div class="grid">
        <div class="card stat"><div class="muted">Overall Average</div>
          <div class="num">${d.overall == null ? "—" : d.overall.toFixed(1) + "%"}</div></div>
        <div class="card stat"><div class="muted">Assessments</div>
          <div class="num">${d.results.length}</div></div>
      </div>
      ${(ann.announcements || []).length ? `
      <div class="card"><h3>📢 School Announcements</h3>
        ${ann.announcements.map(a => `
          <div class="lesson"><b>${esc(a.title)}</b>
            ${a.body ? `<div class="muted" style="margin-top:4px">${esc(a.body)}</div>` : ""}
            <div class="muted" style="margin-top:4px;font-size:11px">${esc(a.created_at || "")}</div>
          </div>`).join("")}
      </div>` : ""}
      <div class="card"><h3>Subject Averages</h3>
        ${d.averages.length ? d.averages.map(x => `<p><b>${esc(x.subject)}</b> — ${x.average.toFixed(1)}%</p>`).join("") : "<p class='empty'>No results yet.</p>"}
      </div>
      <div class="card"><h3>Recent Results</h3>
        ${d.results.length ? d.results.map(x =>
          `<p><b>${esc(x.subject_name)}</b> · ${esc(x.title || "")} — ${esc(x.score)}/${esc(x.max_score)}</p>`
        ).join("") : "<p class='empty'>No results yet.</p>"}
      </div>
      <div class="card"><h3>Messages from Teachers</h3>
        ${d.lessons.length ? d.lessons.map(x => `
          <div class="lesson"><b>📨 ${esc(x.title)}</b>
            👨‍🏫 ${esc(x.teacher_name)} · 📚 ${esc(x.subject_name)}
            ${x.description ? `<div class="muted" style="margin-top:4px">${esc(x.description)}</div>` : ""}
          </div>`).join("") : "<p class='empty'>No messages yet.</p>"}
      </div>`;
  } catch (e) { showError(e); }
}

async function teacherHome() {
  try {
    const [d, ann] = await Promise.all([
      api("/api/teacher"),
      api("/api/my-announcements").catch(() => ({ announcements: [] }))
    ]);
    const t = d.teacher;
    document.getElementById("app").innerHTML = `
      <div class="hero"><h2>Teacher Dashboard</h2><p>Welcome back, ${esc(t.name)}</p></div>
      <div class="grid">
        <div class="card stat"><div class="muted">Classes</div><div class="number">${d.assignments.length}</div></div>
        <div class="card stat"><div class="muted">Messages</div><div class="number">${d.messages.length}</div></div>
        <div class="card stat"><div class="muted">Assessments</div><div class="number">${d.assessments.length}</div></div>
      </div>
      ${(ann.announcements || []).length ? `
      <div class="card"><h3>📢 School Announcements</h3>
        ${ann.announcements.slice(0,5).map(a => `
          <div class="lesson"><b>${esc(a.title)}</b>
            ${a.body ? `<div class="muted" style="margin-top:4px">${esc(a.body)}</div>` : ""}
          </div>`).join("")}
      </div>` : ""}
      <div class="card"><h3>My Classes</h3>
        ${d.assignments.length ? d.assignments.map(x =>
          `<div class="lesson">Grade ${esc(x.grade)}${esc(x.section)} — ${esc(x.subject_name)} (${esc(x.year_name)})</div>`
        ).join("") : "<p class='empty'>No assignments yet. Contact admin.</p>"}
      </div>
      <div class="card"><h3>Recent Messages</h3>
        ${d.messages.slice(0,3).map(x =>
          `<div class="lesson"><b>${esc(x.title)}</b><div class="muted">${esc(x.description || "")}</div></div>`
        ).join("") || "<p class='empty'>No messages yet.</p>"}
        <button style="margin-top:10px" onclick="show('teacherMessages')">＋ New Message</button>
      </div>
      <div class="card"><h3>Recent Assessments</h3>
        ${d.assessments.slice(0,3).map(x => `
          <div class="lesson"><b>${esc(x.title)}</b> (${esc(x.max_score)}%)
            <div style="margin-top:8px">
              <button onclick="feedScores('${esc(x.id)}','${esc(x.teacher_assignment_id)}')">Enter Scores</button>
            </div>
          </div>`).join("") || "<p class='empty'>No assessments yet. Admin will create them.</p>"}
        <button style="margin-top:10px" class="alt" onclick="show('teacherAssessments')">View All Assessments</button>
      </div>`;
  } catch (e) { showError(e); }
}

async function teacherMessages() {
  try {
    const d = await api("/api/teacher");
    document.getElementById("app").innerHTML = `
      <div class="hero"><h2>My Messages</h2><p>Send announcements to your classes</p></div>
      <div class="card">
        <h3>Send Message</h3>
        <form onsubmit="sendTeacherMessage(event)">
          <div class="formgrid">
            <div>
              <label>Class</label>
              <select name="assignment_id" required>
                <option value="">Select…</option>
                ${d.assignments.map(x =>
                  `<option value="${esc(x.id)}">Grade ${esc(x.grade)}${esc(x.section)} — ${esc(x.subject_name)}</option>`
                ).join("")}
              </select>
            </div>
            <div><label>Title</label><input name="title" placeholder="Topic…" required></div>
            <div style="grid-column:1/-1"><label>Content</label>
              <textarea name="description" rows="3" placeholder="Write your message…"></textarea></div>
          </div>
          <button>📨 Send</button>
        </form>
      </div>
      <div class="card"><h3>All Messages</h3>
        ${d.messages.length ? d.messages.map(x => `
          <div class="lesson">
            <b>📩 ${esc(x.title)}</b>
            📚 ${esc(x.subject_name)} · 🏫 Grade ${esc(x.grade)}${esc(x.section)}
            <div class="muted" style="margin-top:4px">${esc(x.description || "")}</div>
            <button class="danger" style="margin-top:8px" onclick="deleteItem('lessons','${esc(x.id)}','message')">Delete</button>
          </div>`).join("") : "<p class='empty'>No messages yet.</p>"}
      </div>`;
  } catch (e) { showError(e); }
}

async function sendTeacherMessage(e) {
  e.preventDefault();
  const fd = new FormData(e.target);
  try {
    await api("/api/save/lessons", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({
        teacher_assignment_id: fd.get("assignment_id"),
        title: fd.get("title"),
        description: fd.get("description"),
        lesson_date: new Date().toISOString().slice(0,10)
      })
    });
    toast("Message sent"); teacherMessages();
  } catch (err) { toast(err.message); }
}

async function teacherAssessments() {
  try {
    const d = await api("/api/teacher");
    document.getElementById("app").innerHTML = `
      <div class="hero"><h2>My Assessments</h2><p>Assessments created by admin — enter scores for your classes</p></div>
      <div class="card"><h3>Assigned Assessments</h3>
        ${(d.assessments || []).length ? d.assessments.map(x => `
          <div class="lesson">
            <b>📝 ${esc(x.title)}</b> (${esc(x.max_score)}%)
            <div class="muted">📚 ${esc(x.subject_name)} · 🏫 Grade ${esc(x.grade)}${esc(x.section)} · 📅 ${esc(x.assessment_date || "—")}</div>
            <div style="margin-top:8px">
              <button onclick="feedScores('${esc(x.id)}','${esc(x.teacher_assignment_id)}')">📝 Enter Scores</button>
            </div>
          </div>`).join("") : "<p class='empty'>No assessments assigned yet. Admin will create them.</p>"}
      </div>`;
  } catch (e) { showError(e); }
}

async function feedScores(assessmentId, assignmentId) {
  try {
    const data = await api(`/api/assessment/students?assessment_id=${assessmentId}&assignment_id=${assignmentId}`);
    const maxScore = data.assessment.max_score;
    document.getElementById("app").innerHTML = `
      <div class="hero">
        <h2>Enter Scores</h2>
        <p><b>${esc(data.assessment.title || "Assessment")}</b><br>
          🏫 ${esc(data.assignment.class_name)} · 📚 ${esc(data.assignment.subject_name)} · Out of <b>${esc(maxScore)}</b></p>
      </div>
      <div class="card">
        <form onsubmit="saveScores(event, '${esc(assessmentId)}')">
          <div class="tablewrap"><table>
            <thead><tr><th>Student</th><th>ID</th><th>Score ( / ${esc(maxScore)})</th></tr></thead>
            <tbody>${data.students.length ? data.students.map(s => `
              <tr>
                <td><b>${esc(s.name)}</b></td>
                <td class="muted">${esc(s.student_id || s.telegram_id)}</td>
                <td>
                  <input type="number" step="0.01" min="0" max="${esc(maxScore)}"
                    data-telegram="${esc(s.telegram_id)}"
                    data-student-id="${esc(s.student_id || "")}"
                    class="score-input"
                    value="${s.score !== null && s.score !== undefined ? esc(s.score) : ""}"
                    placeholder="0">
                </td>
              </tr>`).join("") : `<tr><td colspan="3" class="empty">No students in this class.</td></tr>`}
            </tbody>
          </table></div>
          <div style="margin-top:14px;display:flex;gap:10px;flex-wrap:wrap">
            <button type="submit">💾 Save Scores</button>
            <button type="button" class="alt" onclick="show('teacherAssessments')">← Back</button>
          </div>
        </form>
      </div>`;
  } catch (e) { toast(e.message); }
}

async function saveScores(e, assessmentId) {
  e.preventDefault();
  const inputs = e.target.querySelectorAll(".score-input");
  const scores = [];
  inputs.forEach(inp => {
    const val = inp.value.trim();
    if (val === "") return;
    scores.push({
      telegram_id: inp.getAttribute("data-telegram") || "",
      student_id: inp.getAttribute("data-student-id") || "",
      score: parseFloat(val)
    });
  });
  if (!scores.length) { toast("Enter at least one score"); return; }
  try {
    const res = await api("/api/assessment/feed", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({ assessment_id: parseInt(assessmentId, 10), scores })
    });
    toast(`Saved ${res.saved || scores.length} score(s)`);
    show("teacherAssessments");
  } catch (err) { toast(err.message); }
}

const adminSections = {
  dashboard: "📊 Dashboard", students: "👨‍🎓 Students", teachers: "👨‍🏫 Teachers",
  classes: "🏫 Classes", subjects: "📚 Subjects", assignments: "🔗 Assignments",
  lessons: "📨 Class Msgs", announcements: "📢 Broadcast", assessments: "📝 Assessments",
  years: "📅 Years", reports: "📈 Reports", backup: "💾 Backup"
};

if (ROLE === "admin") {
  setNav(Object.entries(adminSections));
  show("dashboard");
} else if (ROLE === "student") {
  setNav([["studentHome", "🏠 Dashboard"]]);
  show("studentHome");
} else if (ROLE === "teacher") {
  setNav([
    ["teacherHome", "👨‍🏫 Dashboard"],
    ["teacherMessages", "📨 Messages"],
    ["teacherAssessments", "📝 Assessments"]
  ]);
  show("teacherHome");
}
</script>
</body>
</html>
"""


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    if not os.path.exists(DB):
        print("Creating new database…")
        init_db()
    else:
        print("Database found — running migration…")
        migrate_db()

    port = int(os.environ.get("PORT", 5000))
    print("━" * 50)
    print("  School Academic Mini App — Premium Edition")
    print("  Built by Magnificent Technologies · Dagim Tariku")
    print("━" * 50)
    print(f"  Port       : {port}")
    print(f"  Database   : {DB}")
    print(f"  Admin ID   : {ADMIN_ID}")
    print(f"  BOT_TOKEN  : {'SET' if BOT_TOKEN else 'NOT SET'}")
    print("━" * 50)
    app.run(host="0.0.0.0", port=port, debug=False)
