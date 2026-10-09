# FaceTrack AI — Flask Edition

A rebuild of the original Tkinter attendance scripts (`AMS_Run.py`, `training.py`,
`testing.py`) as a proper local web app: Flask backend, SQLite storage, and an
HTML/CSS front end with live camera streaming in the browser instead of
`cv2.imshow()` desktop windows.

## Running it

```bash
pip install -r requirements.txt
python app.py
```

Then open `http://localhost:5000`. Default login is `admin` / `admin` — change
it by setting environment variables before starting the app:

```bash
export FACETRACK_ADMIN_USER=your_username
export FACETRACK_ADMIN_PASSWORD=a_real_password
export FACETRACK_SECRET_KEY=some_random_string
```

This has to run on the same machine as the webcam — the video feed is read
server-side with OpenCV, same as the original scripts, just streamed to the
browser as MJPEG instead of opened in a native window.

## What changed and why

**Real bugs, not just style:**

- `training.py` trained the model with `cv2.face.createFisherFaceRecognizer_create()`
  (which isn't even a valid modern OpenCV call), while `AMS_Run.py` and
  `testing.py` loaded it back with `cv2.face.LBPHFaceRecognizer_create()`.
  Those are different algorithms with incompatible saved-model files, so
  recognition against a model trained this way would never have worked
  correctly. Standardized on LBPH everywhere (`face_utils.py`).
- `take_img()` in `AMS_Run.py` wrote files to `"TrainingImage/ " + Name + ...`
  — note the stray space right after the slash. Fixed.
- The Haar cascade XML and `TrainingImage` paths were bare relative strings,
  so the scripts only worked if launched from one specific working directory.
  Now resolved relative to the project file itself.
- Every attendance session ran `"CREATE TABLE " + subject_and_timestamp`
  straight into a MySQL cursor, with the subject name typed into a text box
  by the user going directly into that string — a SQL-injection hole, and it
  also produced a brand-new table per class per day forever. Replaced with
  two fixed, parameterized SQLite tables (`students`, `attendance`), with a
  `UNIQUE(enrollment, subject, date)` constraint doing the duplicate-check
  work that the old code did manually with `drop_duplicates()`.
- The webcam (`cv2.VideoCapture`) was never released if anything raised an
  exception mid-loop, which permanently locks the camera device until the
  process is killed. Every capture loop is now wrapped in `try/finally`.
- Login was `if username == 'admin': if password == 'admin':` compared as
  plain text, hardcoded in the UI code. Now a single hashed admin credential
  read from environment variables.
- Tkinter version opened a **new** `tk.Tk()` root window for nearly every
  dialog and error popup. `Tk()` should only be called once per process —
  everything else should be a `Toplevel()` — or you get duplicate mainloops
  and windows that stop responding. This is moot now that the UI is a real
  web front end, but it's why the old app felt like it randomly froze.

**Rebuilt as a web app:**

- `db.py` — SQLite schema and queries (students, attendance).
- `face_utils.py` — capture, training, and recognition, each yielding MJPEG
  frames for the browser.
- `app.py` — Flask routes: login, dashboard, register, train, attendance,
  records (with CSV export).
- `templates/` + `static/css/style.css` — the front end. Visual identity is
  built around the subject itself (a paper attendance register): ruled
  "notebook" background, ledger-style tables, monospace figures for
  enrollment numbers and timestamps, and a rotated red "stamp" badge for
  status, rather than a generic dashboard template.

## Known limitations (same category as the original, worth knowing about)

- Single shared admin account — fine for one teacher/lab running this
  locally, not meant for multi-tenant use.
- Capture/attendance session state lives in an in-memory dict, so it's
  single-process only (don't run this behind multiple gunicorn workers
  without moving that state to something shared, like Redis).
- Recognition quality still depends entirely on lighting and the number of
  training samples per student, same as the original LBPH approach — this
  fixes the code, not the fundamental accuracy ceiling of Haar cascades + LBPH.
