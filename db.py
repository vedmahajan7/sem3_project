import os
from contextlib import contextmanager

import mysql.connector
from mysql.connector import errorcode

MYSQL_HOST = os.environ.get("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
MYSQL_USER = os.environ.get("MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "Vedmahajan@23541")
MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE", "facetrack")

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS students (
        enrollment VARCHAR(32) PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        registered_on VARCHAR(20) NOT NULL
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS attendance (
        id INT AUTO_INCREMENT PRIMARY KEY,
        enrollment VARCHAR(32) NOT NULL,
        name VARCHAR(255) NOT NULL,
        subject VARCHAR(255) NOT NULL,
        date VARCHAR(20) NOT NULL,
        time VARCHAR(20) NOT NULL,
        UNIQUE KEY uniq_checkin (enrollment, subject, date)
    ) ENGINE=InnoDB
    """,
]


def _ensure_database_exists():
    """Connects without selecting a database and creates it if missing."""
    conn = mysql.connector.connect(
        host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER, password=MYSQL_PASSWORD,
    )
    try:
        cur = conn.cursor()
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{MYSQL_DATABASE}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()


@contextmanager
def get_conn():
    conn = mysql.connector.connect(
        host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER,
        password=MYSQL_PASSWORD, database=MYSQL_DATABASE,
    )
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    try:
        _ensure_database_exists()
        with get_conn() as conn:
            cur = conn.cursor()
            for statement in SCHEMA:
                cur.execute(statement)
            cur.close()
    except mysql.connector.Error as err:
        if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
            raise RuntimeError(
                "MySQL access denied -- check MYSQL_USER / MYSQL_PASSWORD."
            ) from err
        raise


def add_student(enrollment: str, name: str, registered_on: str):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO students (enrollment, name, registered_on) VALUES (%s, %s, %s) "
            "ON DUPLICATE KEY UPDATE name = VALUES(name), registered_on = VALUES(registered_on)",
            (enrollment, name, registered_on),
        )
        cur.close()


def get_student(enrollment: str):
    with get_conn() as conn:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM students WHERE enrollment = %s", (enrollment,))
        row = cur.fetchone()
        cur.close()
        return row


def list_students():
    with get_conn() as conn:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM students ORDER BY name")
        rows = cur.fetchall()
        cur.close()
        return rows


def mark_attendance(enrollment: str, name: str, subject: str, date: str, time: str) -> bool:
    """Returns True if a new row was inserted, False if already marked (no duplicate)."""
    with get_conn() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO attendance (enrollment, name, subject, date, time) "
                "VALUES (%s, %s, %s, %s, %s)",
                (enrollment, name, subject, date, time),
            )
            return True
        except mysql.connector.IntegrityError:
            return False
        finally:
            cur.close()


def get_attendance(subject: str = None, date: str = None):
    query = "SELECT * FROM attendance WHERE 1=1"
    params = []
    if subject:
        query += " AND subject = %s"
        params.append(subject)
    if date:
        query += " AND date = %s"
        params.append(date)
    query += " ORDER BY date DESC, time DESC"
    with get_conn() as conn:
        cur = conn.cursor(dictionary=True)
        cur.execute(query, params)
        rows = cur.fetchall()
        cur.close()
        return rows


def list_subjects():
    with get_conn() as conn:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT DISTINCT subject FROM attendance ORDER BY subject")
        rows = cur.fetchall()
        cur.close()
        return [r["subject"] for r in rows]