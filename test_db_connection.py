"""
Standalone MySQL connectivity check for FaceTrack AI.

Run this by itself -- completely separate from the Flask app -- to confirm
your MySQL server, credentials, and database access all work before
troubleshooting anything inside app.py:

    python test_db_connection.py

It reads the exact same environment variables as db.py (MYSQL_HOST,
MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE), so set those the
same way you would before running the real app.
"""
import os
import sys

import mysql.connector
from mysql.connector import errorcode

MYSQL_HOST = os.environ.get("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
MYSQL_USER = os.environ.get("MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE", "facetrack")


def main():
    print(f"Connecting to MySQL at {MYSQL_HOST}:{MYSQL_PORT} as '{MYSQL_USER}'...")

    # Step 1: can we reach the server and authenticate at all?
    try:
        conn = mysql.connector.connect(
            host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER, password=MYSQL_PASSWORD,
        )
        print("  Server reachable, credentials accepted.")
    except mysql.connector.Error as err:
        if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
            print("  FAILED: access denied. Your MYSQL_USER / MYSQL_PASSWORD is wrong.")
        elif "Can't connect" in str(err) or "Unknown host" in str(err):
            print(f"  FAILED: could not reach {MYSQL_HOST}:{MYSQL_PORT}.")
            print("  Is your MySQL server actually running? Check services.msc")
            print("  on Windows, or run 'mysql -u root -p' in a terminal to test manually.")
        else:
            print(f"  FAILED: {err}")
        sys.exit(1)

    # Step 2: can we create/select the facetrack database?
    try:
        cur = conn.cursor()
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{MYSQL_DATABASE}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        conn.commit()
        print(f"  Database '{MYSQL_DATABASE}' exists (or was created).")
        cur.close()
        conn.close()
    except mysql.connector.Error as err:
        print(f"  FAILED to create/select database '{MYSQL_DATABASE}': {err}")
        sys.exit(1)

    # Step 3: full round trip through db.py itself
    try:
        import db
        db.init_db()
        students = db.list_students()
        print(f"  db.py connected successfully. {len(students)} student(s) currently in the table.")
    except Exception as err:
        print(f"  FAILED when using db.py directly: {err}")
        sys.exit(1)

    print("\nAll checks passed -- MySQL is correctly connected for FaceTrack AI.")


if __name__ == "__main__":
    main()