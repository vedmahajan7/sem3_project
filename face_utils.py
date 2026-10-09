"""
Face capture / training / recognition, streamed to the browser as MJPEG
instead of the original's cv2.imshow() desktop windows (which only ever
worked on a machine with a display attached to the Python process, and
blocked the whole script while open).
"""
import os
import platform
import time
import datetime
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

BASE_DIR = Path(__file__).parent
CASCADE_PATH = str(BASE_DIR / "haarcascade_frontalface_default.xml")
TRAINING_IMAGE_DIR = BASE_DIR / "TrainingImage"
MODEL_PATH = BASE_DIR / "TrainingImageLabel" / "trainner.yml"

SAMPLES_PER_STUDENT = 60
CONFIDENCE_THRESHOLD = 70  # lower = stricter match, LBPH "distance" score


def _cascade():
    cascade = cv2.CascadeClassifier(CASCADE_PATH)
    if cascade.empty():
        raise RuntimeError(f"Could not load face cascade at {CASCADE_PATH}")
    return cascade


def open_camera(index: int = 0):
    """
    Opens the webcam. On Windows, OpenCV's default backend (MSMF) can fail
    to open the camera reliably or hang on init -- especially right after a
    previous session held it. Explicitly requesting DirectShow (CAP_DSHOW)
    is the standard fix and opens far more consistently on Windows.
    """
    if platform.system() == "Windows":
        return cv2.VideoCapture(index, cv2.CAP_DSHOW)
    return cv2.VideoCapture(index)


def gen_capture_frames(enrollment: str, name: str, progress: dict, on_complete=None):
    """
    Generator that yields MJPEG frames while saving face crops for a student.
    `progress` is a small shared dict the Flask route uses to report
    {"count": int, "done": bool} back to the page via polling (display only).

    `on_complete`, if given, is called once capture finishes -- this is what
    actually saves the student record, so registration no longer depends on
    the browser's progress-bar polling succeeding.
    """
    student_dir = TRAINING_IMAGE_DIR
    student_dir.mkdir(parents=True, exist_ok=True)

    cascade = _cascade()
    cam = open_camera()
    sample_num = 0
    progress["count"] = 0
    progress["done"] = False

    try:
        if not cam.isOpened():
            raise RuntimeError("Could not open webcam (index 0).")

        while sample_num < SAMPLES_PER_STUDENT:
            ok, frame = cam.read()
            if not ok:
                break

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, 1.3, 5)

            for (x, y, w, h) in faces:
                sample_num += 1
                filename = f"{name}.{enrollment}.{sample_num}.jpg"
                cv2.imwrite(str(student_dir / filename), gray[y:y + h, x:x + w])
                cv2.rectangle(frame, (x, y), (x + w, y + h), (37, 99, 60), 2)
                progress["count"] = sample_num
                if sample_num >= SAMPLES_PER_STUDENT:
                    break

            cv2.putText(
                frame, f"Captured {sample_num}/{SAMPLES_PER_STUDENT}",
                (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2,
            )

            ok, buf = cv2.imencode(".jpg", frame)
            if ok:
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n")
    finally:
        cam.release()
        progress["done"] = True
        if sample_num > 0 and on_complete:
            on_complete()


def get_images_and_labels(path: Path):
    face_samples, ids = [], []
    cascade = _cascade()
    id_map = {}  # numeric id (LBPH needs ints) -> enrollment string
    next_id = 1

    for image_path in sorted(Path(path).iterdir()):
        if image_path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        try:
            enrollment = image_path.name.split(".")[1]
        except IndexError:
            continue

        if enrollment not in id_map.values():
            id_map[next_id] = enrollment
            numeric_id = next_id
            next_id += 1
        else:
            numeric_id = next(k for k, v in id_map.items() if v == enrollment)

        pil_image = Image.open(image_path).convert("L")
        image_np = np.array(pil_image, "uint8")
        faces = cascade.detectMultiScale(image_np)
        for (x, y, w, h) in faces:
            face_samples.append(image_np[y:y + h, x:x + w])
            ids.append(numeric_id)

    return face_samples, ids, id_map


def train_model() -> dict:
    """Trains the LBPH recognizer on everything in TrainingImage/. Returns a status dict."""
    if not TRAINING_IMAGE_DIR.exists() or not any(TRAINING_IMAGE_DIR.iterdir()):
        return {"ok": False, "message": 'No images found. Register at least one student first.'}

    faces, ids, id_map = get_images_and_labels(TRAINING_IMAGE_DIR)
    if not faces:
        return {"ok": False, "message": "No faces could be detected in the saved training images."}

    recognizer = cv2.face.LBPHFaceRecognizer_create()
    recognizer.train(faces, np.array(ids))

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    recognizer.save(str(MODEL_PATH))

    # id_map (numeric -> enrollment) is saved alongside the model since LBPH
    # only ever deals in integers, not enrollment strings.
    with open(MODEL_PATH.with_suffix(".idmap"), "w") as f:
        for numeric_id, enrollment in id_map.items():
            f.write(f"{numeric_id},{enrollment}\n")

    return {"ok": True, "message": f"Model trained on {len(set(ids))} students, {len(faces)} face samples."}


def _load_id_map():
    id_map = {}
    map_path = MODEL_PATH.with_suffix(".idmap")
    if map_path.exists():
        with open(map_path) as f:
            for line in f:
                numeric_id, enrollment = line.strip().split(",", 1)
                id_map[int(numeric_id)] = enrollment
    return id_map


def gen_attendance_frames(subject: str, duration_seconds: int, on_recognized):
    """
    Generator that yields MJPEG frames while running recognition for
    `duration_seconds`. Calls on_recognized(enrollment) the first time each
    person is recognized in this session (the caller handles DB writes /
    duplicate suppression per student's name lookup).
    """
    import db as _db  # local import to avoid a circular import at module load

    if not MODEL_PATH.exists():
        raise RuntimeError("No trained model found. Train the model before taking attendance.")

    recognizer = cv2.face.LBPHFaceRecognizer_create()
    recognizer.read(str(MODEL_PATH))
    id_map = _load_id_map()
    cascade = _cascade()

    cam = open_camera()
    already_marked = set()
    end_time = time.time() + duration_seconds

    try:
        if not cam.isOpened():
            raise RuntimeError("Could not open webcam (index 0).")

        while time.time() < end_time:
            ok, frame = cam.read()
            if not ok:
                break

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, 1.2, 5)

            for (x, y, w, h) in faces:
                numeric_id, confidence = recognizer.predict(gray[y:y + h, x:x + w])
                enrollment = id_map.get(numeric_id)

                if enrollment and confidence < CONFIDENCE_THRESHOLD:
                    student = _db.get_student(enrollment)
                    label = student["name"] if student else enrollment
                    color = (37, 99, 60)
                    if enrollment not in already_marked:
                        already_marked.add(enrollment)
                        on_recognized(enrollment, label)
                else:
                    label = "Unknown"
                    color = (60, 60, 200)

                cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
                cv2.putText(frame, label, (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

            remaining = max(0, int(end_time - time.time()))
            cv2.putText(frame, f"{remaining}s remaining", (15, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

            ok, buf = cv2.imencode(".jpg", frame)
            if ok:
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n")
    finally:
        cam.release()
