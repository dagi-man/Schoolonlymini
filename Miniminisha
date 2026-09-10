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
                    INSERT I
... 
