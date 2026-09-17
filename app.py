"""Birthday Memories — multi-user edition.

* ANYBODY can create an account with their **email ID or phone number**
  and log in with it (plus a password).
* Each user has a **private memory space**: every movie they upload is
  stored under their email/phone and only visible to them (and admins).
* All data files live in a persistent `data/` folder (users.json,
  movies.json, secret key, uploads/) so nothing is lost on restarts.
"""

import json
import os
import re
import secrets
import threading
import uuid
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

# ---------------------------------------------------------------------------
# Memory store configuration
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR / "data"))).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
USERS_FILE = DATA_DIR / "users.json"
MOVIES_FILE = DATA_DIR / "movies.json"
SECRET_FILE = DATA_DIR / "secret_key.txt"

DEFAULT_ADMIN_ID = os.environ.get("ADMIN_ID", "admin")
DEFAULT_ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "birthday@123")

VIDEO_EXT = {".mp4", ".webm", ".ogv", ".mov", ".mkv", ".m4v"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".oga", ".flac"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1500 * 1024 * 1024  # 1.5 GB per request

_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Memory store helpers (all app data lives inside DATA_DIR)
# ---------------------------------------------------------------------------
def _load_json(path: Path, default):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    tmp.replace(path)


def init_memory() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    if not SECRET_FILE.exists():
        SECRET_FILE.write_text(secrets.token_hex(32), encoding="utf-8")

    users = _load_json(USERS_FILE, {})
    if not users:
        users[DEFAULT_ADMIN_ID] = {
            "name": "Admin",
            "login": DEFAULT_ADMIN_ID,
            "type": "username",
            "password_hash": generate_password_hash(DEFAULT_ADMIN_PASSWORD),
            "role": "admin",
            "created": datetime.now().isoformat(timespec="seconds"),
        }
        _save_json(USERS_FILE, users)

    if not MOVIES_FILE.exists():
        _save_json(MOVIES_FILE, [])


init_memory()
app.secret_key = SECRET_FILE.read_text(encoding="utf-8").strip()


def get_users() -> dict:
    return _load_json(USERS_FILE, {})


def save_users(users: dict) -> None:
    _save_json(USERS_FILE, users)


def get_movies() -> list:
    return _load_json(MOVIES_FILE, [])


def save_movies(movies: list) -> None:
    _save_json(MOVIES_FILE, movies)


def movies_of(login: str) -> list:
    return [m for m in get_movies() if m.get("owner") == login]


def human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024 or unit == "TB":
            return f"{num:.1f} {unit}" if unit != "B" else f"{int(num)} B"
        num /= 1024
    return f"{num:.1f} TB"


def user_storage(login: str) -> dict:
    """Memory used by one user's data files."""
    total = 0
    files = 0
    for movie in movies_of(login):
        for key in ("video", "song", "cover"):
            if movie.get(key):
                try:
                    total += os.path.getsize(UPLOAD_DIR / movie[key])
                    files += 1
                except OSError:
                    pass
    return {"bytes": total, "files": files, "human": human_size(total)}


def storage_stats() -> dict:
    total_bytes = 0
    file_count = 0
    for root, _dirs, files in os.walk(DATA_DIR):
        for name in files:
            try:
                total_bytes += os.path.getsize(os.path.join(root, name))
                file_count += 1
            except OSError:
                pass
    return {"bytes": total_bytes, "files": file_count, "human": human_size(total_bytes)}


def unique_upload_name(original: str) -> str:
    safe = secure_filename(original or "") or "file"
    return f"{uuid.uuid4().hex[:10]}-{safe}"


def normalize_identifier(raw: str):
    """Return (login_key, display, type, error). Accepts email OR phone."""
    raw = (raw or "").strip()
    if not raw:
        return None, None, None, "Please enter your email ID or phone number."
    if "@" in raw:
        login = raw.lower()
        if not EMAIL_RE.match(login):
            return None, None, None, "That email address does not look valid."
        return login, login, "email", None
    digits = re.sub(r"[\s\-().]", "", raw)
    if not re.match(r"^\+?\d{10,15}$", digits):
        return None, None, None, (
            "Enter a valid email ID or phone number (10–15 digits, e.g. 9876543210 or +919876543210)."
        )
    return digits, digits, "phone", None


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def current_user_id():
    return session.get("user_id")


def current_user():
    uid = current_user_id()
    if not uid:
        return None
    return get_users().get(uid)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user_id():
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user or user.get("role") != "admin":
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def delete_movie_files(movie: dict) -> None:
    for key in ("video", "song", "cover"):
        if movie.get(key):
            try:
                (UPLOAD_DIR / movie[key]).unlink(missing_ok=True)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Public pages
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    user = current_user()
    return render_template("index.html", user=user, user_id=current_user_id())


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        raw_id = request.form.get("login_id") or ""
        password = request.form.get("password") or ""

        login, display, id_type, err = normalize_identifier(raw_id)
        if err:
            flash(err, "error")
            return render_template("signup.html", name=name, login_id=raw_id)
        if not name:
            flash("Please enter your name.", "error")
            return render_template("signup.html", name=name, login_id=raw_id)
        if len(password) < 6:
            flash("Password must be at least 6 characters long.", "error")
            return render_template("signup.html", name=name, login_id=raw_id)

        with _lock:
            users = get_users()
            if login in users:
                flash("An account with this email/phone already exists. Please login.", "error")
                return render_template("signup.html", name=name, login_id=raw_id)
            users[login] = {
                "name": name,
                "login": display,
                "type": id_type,
                "password_hash": generate_password_hash(password),
                "role": "user",
                "created": datetime.now().isoformat(timespec="seconds"),
            }
            save_users(users)

        session["user_id"] = login
        flash(f"Welcome, {name}! Your memory space is ready.", "success")
        return redirect(url_for("my_memories"))
    return render_template("signup.html", name="", login_id="")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        raw_id = request.form.get("login_id") or ""
        password = request.form.get("password") or ""

        users = get_users()
        user = None
        login_key = None

        # Normal email/phone lookup
        login, _display, _t, _err = normalize_identifier(raw_id)
        if login and login in users:
            login_key, user = login, users[login]
        else:
            # Fallback: plain username (e.g. the default admin ID)
            guess = raw_id.strip().lower()
            for key, info in users.items():
                if key.lower() == guess or str(info.get("login", "")).lower() == guess:
                    login_key, user = key, info
                    break

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = login_key
            flash(f"Welcome back, {user.get('name') or login_key}!", "success")
            # Everybody lands on their memory videos right after login
            return redirect(url_for("my_memories"))
        flash("Wrong email/phone or password. New here? Create an account.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    flash("Logged out. See you soon!", "success")
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# My Memories — private gallery stored under the user's email / phone
# ---------------------------------------------------------------------------
@app.route("/my")
@login_required
def my_memories():
    user = current_user()
    movies = sorted(movies_of(current_user_id()), key=lambda m: m.get("uploaded_at", ""), reverse=True)
    for movie in movies:
        try:
            movie["date_label"] = datetime.fromisoformat(movie["uploaded_at"]).strftime("%d %b %Y")
        except Exception:
            movie["date_label"] = ""
    return render_template(
        "my.html",
        user=user,
        user_id=current_user_id(),
        movies=movies,
        stats=user_storage(current_user_id()),
    )


@app.route("/my/upload", methods=["POST"])
@login_required
def upload_movie():
    title = (request.form.get("title") or "").strip()
    note = (request.form.get("note") or "").strip()
    video = request.files.get("video")
    song = request.files.get("song")
    cover = request.files.get("cover")

    if not title:
        flash("Please give the movie a title.", "error")
        return redirect(url_for("my_memories"))
    if not video or not video.filename:
        flash("Please choose the birthday movie video file.", "error")
        return redirect(url_for("my_memories"))
    if Path(video.filename).suffix.lower() not in VIDEO_EXT:
        flash(f"Video must be one of: {', '.join(sorted(VIDEO_EXT))}", "error")
        return redirect(url_for("my_memories"))

    record = {
        "id": uuid.uuid4().hex[:10],
        "title": title,
        "note": note,
        "video": None,
        "song": None,
        "cover": None,
        "owner": current_user_id(),
        "uploaded_by": current_user().get("name") or current_user_id(),
        "uploaded_at": datetime.now().isoformat(timespec="seconds"),
    }

    try:
        video_name = unique_upload_name(video.filename)
        video.save(str(UPLOAD_DIR / video_name))
        record["video"] = video_name

        if song and song.filename:
            if Path(song.filename).suffix.lower() not in AUDIO_EXT:
                flash(f"Song must be one of: {', '.join(sorted(AUDIO_EXT))}", "error")
                return redirect(url_for("my_memories"))
            song_name = unique_upload_name(song.filename)
            song.save(str(UPLOAD_DIR / song_name))
            record["song"] = song_name

        if cover and cover.filename:
            if Path(cover.filename).suffix.lower() not in IMAGE_EXT:
                flash(f"Cover image must be one of: {', '.join(sorted(IMAGE_EXT))}", "error")
                return redirect(url_for("my_memories"))
            cover_name = unique_upload_name(cover.filename)
            cover.save(str(UPLOAD_DIR / cover_name))
            record["cover"] = cover_name

        with _lock:
            movies = get_movies()
            movies.append(record)
            save_movies(movies)
    except Exception as exc:  # pragma: no cover
        flash(f"Upload failed: {exc}", "error")
        return redirect(url_for("my_memories"))

    flash(f"“{title}” was saved under {current_user_id()}.", "success")
    return redirect(url_for("my_memories"))


@app.route("/my/movie/<movie_id>/delete", methods=["POST"])
@login_required
def delete_movie(movie_id):
    with _lock:
        movies = get_movies()
        movie = next((m for m in movies if m["id"] == movie_id), None)
        if not movie:
            abort(404)
        user = current_user()
        if movie.get("owner") != current_user_id() and user.get("role") != "admin":
            abort(403)
        delete_movie_files(movie)
        save_movies([m for m in movies if m["id"] != movie_id])
    flash(f"Deleted “{movie['title']}” and its files.", "success")
    return redirect(request.referrer or url_for("my_memories"))


@app.route("/media/<path:filename>")
@login_required
def media_file(filename):
    """Serve a data file only to its owner (or an admin)."""
    user = current_user()
    movie = next(
        (m for m in get_movies() if filename in (m.get("video"), m.get("song"), m.get("cover"))),
        None,
    )
    if not movie:
        abort(404)
    if movie.get("owner") != current_user_id() and user.get("role") != "admin":
        abort(403)
    return send_from_directory(UPLOAD_DIR, filename)


# ---------------------------------------------------------------------------
# Admin panel
# ---------------------------------------------------------------------------
@app.route("/admin")
@admin_required
def admin_panel():
    users = get_users()
    movies = sorted(get_movies(), key=lambda m: m.get("uploaded_at", ""), reverse=True)
    movie_counts = {}
    for m in movies:
        movie_counts[m.get("owner")] = movie_counts.get(m.get("owner"), 0) + 1
    return render_template(
        "admin.html",
        user=current_user(),
        user_id=current_user_id(),
        users=users,
        movies=movies,
        movie_counts=movie_counts,
        stats=storage_stats(),
        data_dir=str(DATA_DIR),
    )


@app.route("/admin/users/create", methods=["POST"])
@admin_required
def create_user():
    name = (request.form.get("name") or "").strip()
    raw_id = request.form.get("login_id") or ""
    password = request.form.get("password") or ""
    role = request.form.get("role") or "user"

    login, display, id_type, err = normalize_identifier(raw_id)
    if err:
        flash(err, "error")
        return redirect(url_for("admin_panel"))
    if not name:
        name = display
    if len(password) < 6:
        flash("Password must be at least 6 characters long.", "error")
        return redirect(url_for("admin_panel"))
    if role not in ("admin", "user"):
        role = "user"

    with _lock:
        users = get_users()
        if login in users:
            flash("This email/phone already has an account.", "error")
            return redirect(url_for("admin_panel"))
        users[login] = {
            "name": name,
            "login": display,
            "type": id_type,
            "password_hash": generate_password_hash(password),
            "role": role,
            "created": datetime.now().isoformat(timespec="seconds"),
        }
        save_users(users)

    flash(f"Account created for {display}.", "success")
    return redirect(url_for("admin_panel"))


@app.route("/admin/user/<path:login_id>/delete", methods=["POST"])
@admin_required
def delete_user(login_id):
    with _lock:
        users = get_users()
        if login_id not in users:
            abort(404)
        if login_id == current_user_id():
            flash("You cannot delete the account you are using right now.", "error")
            return redirect(url_for("admin_panel"))
        admins = [k for k, v in users.items() if v.get("role") == "admin"]
        if users[login_id].get("role") == "admin" and len(admins) <= 1:
            flash("At least one admin account must remain.", "error")
            return redirect(url_for("admin_panel"))
        # Remove all data files stored under this email/phone
        for movie in movies_of(login_id):
            delete_movie_files(movie)
        save_movies([m for m in get_movies() if m.get("owner") != login_id])
        del users[login_id]
        save_users(users)
    flash(f"Account {login_id} and all of its data were deleted.", "success")
    return redirect(url_for("admin_panel"))


@app.route("/admin/movie/<movie_id>/delete", methods=["POST"])
@admin_required
def admin_delete_movie(movie_id):
    return delete_movie(movie_id)


@app.route("/admin/change-password", methods=["POST"])
@login_required
def change_password():
    uid = current_user_id()
    current = request.form.get("current_password") or ""
    new = request.form.get("new_password") or ""

    with _lock:
        users = get_users()
        user = users.get(uid)
        if not user or not check_password_hash(user["password_hash"], current):
            flash("Current password is wrong.", "error")
            return redirect(request.referrer or url_for("my_memories"))
        if len(new) < 6:
            flash("New password must be at least 6 characters long.", "error")
            return redirect(request.referrer or url_for("my_memories"))
        user["password_hash"] = generate_password_hash(new)
        users[uid] = user
        save_users(users)

    flash("Password updated.", "success")
    return redirect(request.referrer or url_for("my_memories"))


@app.route("/admin/export")
@admin_required
def export_data():
    users = get_users()
    payload = {
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "movies": get_movies(),
        "users": [
            {
                "login": info.get("login"),
                "name": info.get("name"),
                "type": info.get("type"),
                "role": info.get("role"),
                "created": info.get("created"),
            }
            for info in users.values()
        ],
    }
    return (
        json.dumps(payload, indent=2, ensure_ascii=False),
        200,
        {
            "Content-Type": "application/json",
            "Content-Disposition": 'attachment; filename="birthday-memories-backup.json"',
        },
    )


@app.route("/healthz")
def healthz():
    return {"ok": True, "data_dir": str(DATA_DIR)}


@app.errorhandler(413)
def too_large(_error):
    flash("That upload is too big for the memory store (limit 1.5 GB).", "error")
    return redirect(url_for("my_memories"))


@app.errorhandler(403)
def forbidden(_error):
    return render_template("error.html", code=403, message="You are not allowed to open this."), 403


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, message="Page not found."), 404


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=False)
