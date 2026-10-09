
import csv
import datetime
import io
import os
import time
import uuid

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, Response, send_file, jsonify
)
from werkzeug.security import generate_password_hash, check_password_hash

import db
import face_utils

app = Flask(__name__)
app.secret_key = os.environ.get("FACETRACK_SECRET_KEY", os.urandom(24))


ADMIN_USERNAME = os.environ.get("FACETRACK_ADMIN_USER", "admin")
ADMIN_PASSWORD_HASH = generate_password_hash(os.environ.get("FACETRACK_ADMIN_PASSWORD", "admin"))

_capture_progress = {}
_attendance_state = {}

db.init_db()


def login_required(view):
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    wrapped.__name__ = view.__name__
    return wrapped


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session["logged_in"] = True
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("Incorrect username or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    students = db.list_students()
    recent = db.get_attendance()[:8]
    model_trained = face_utils.MODEL_PATH.exists()
    return render_template(
        "dashboard.html",
        student_count=len(students),
        recent=recent,
        model_trained=model_trained,
    )


# ---------- Register a student ----------

@app.route("/register", methods=["GET", "POST"])
@login_required
def register():
    if request.method == "POST":
        enrollment = request.form.get("enrollment", "").strip()
        name = request.form.get("name", "").strip()
        if not enrollment or not name:
            flash("Enrollment and name are both required.", "error")
            return render_template("register.html")
        if not enrollment.isdigit():
            flash("Enrollment should be numeric.", "error")
            return render_template("register.html")

        token = str(uuid.uuid4())
        _capture_progress[token] = {"count": 0, "done": False, "enrollment": enrollment, "name": name}
        return render_template("capture.html", token=token, enrollment=enrollment, name=name,
                                total=face_utils.SAMPLES_PER_STUDENT)

    return render_template("register.html")

@app.route("/register/stream/<token>")
@login_required
def register_stream(token):
    state = _capture_progress.get(token)
    if not state:
        return "Unknown capture session", 404

    def on_complete():
       
        db.add_student(state["enrollment"], state["name"], datetime.date.today().isoformat())

    return Response(
        face_utils.gen_capture_frames(state["enrollment"], state["name"], state, on_complete=on_complete),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/register/progress/<token>")
@login_required
def register_progress(token):
   
    state = _capture_progress.get(token, {})
    return jsonify(count=state.get("count", 0), total=face_utils.SAMPLES_PER_STUDENT, done=state.get("done", False))


# ---------- Train the model ----------

@app.route("/train", methods=["GET", "POST"])
@login_required
def train():
    result = None
    if request.method == "POST":
        result = face_utils.train_model()
    return render_template("train.html", result=result)


# ---------- Take attendance ----------

@app.route("/attendance", methods=["GET", "POST"])
@login_required
def attendance():
    if request.method == "POST":
        subject = request.form.get("subject", "").strip()
        if not subject:
            flash("Enter a subject name.", "error")
            return render_template("attendance.html")
        if not face_utils.MODEL_PATH.exists():
            flash("No trained model yet. Train the model before taking attendance.", "error")
            return render_template("attendance.html")

        token = str(uuid.uuid4())
        _attendance_state[token] = {"subject": subject, "marked": []}
        return render_template("attendance_live.html", token=token, subject=subject, duration=20)

    return render_template("attendance.html")


@app.route("/attendance/stream/<token>")
@login_required
def attendance_stream(token):
    state = _attendance_state.get(token)
    if not state:
        return "Unknown attendance session", 404

    def on_recognized(enrollment, name):
        now = datetime.datetime.now()
        inserted = db.mark_attendance(
            enrollment, name, state["subject"],
            now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"),
        )
        if inserted:
            state["marked"].append({"enrollment": enrollment, "name": name, "time": now.strftime("%H:%M:%S")})

    return Response(
        face_utils.gen_attendance_frames(state["subject"], duration_seconds=20, on_recognized=on_recognized),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/attendance/progress/<token>")
@login_required
def attendance_progress(token):
    state = _attendance_state.get(token, {})
    return jsonify(marked=state.get("marked", []))


# ---------- Records ----------

@app.route("/records")
@login_required
def records():
    subject = request.args.get("subject") or None
    date = request.args.get("date") or None
    rows = db.get_attendance(subject=subject, date=date)
    subjects = db.list_subjects()
    return render_template("records.html", rows=rows, subjects=subjects,
                            selected_subject=subject, selected_date=date)


@app.route("/records/export")
@login_required
def export_records():
    subject = request.args.get("subject") or None
    date = request.args.get("date") or None
    rows = db.get_attendance(subject=subject, date=date)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Enrollment", "Name", "Subject", "Date", "Time"])
    for r in rows:
        writer.writerow([r["enrollment"], r["name"], r["subject"], r["date"], r["time"]])

    mem = io.BytesIO(buf.getvalue().encode("utf-8"))
    filename = f"attendance_{subject or 'all'}_{date or 'all'}.csv"
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name=filename)


if __name__ == "__main__":
  app.run(debug=True, use_reloader=False, host="0.0.0.0", port=5000, threaded=True)
