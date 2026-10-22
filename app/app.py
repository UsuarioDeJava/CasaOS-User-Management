import logging
import os
import secrets
from datetime import timedelta
from functools import wraps

from flask import (Flask, abort, flash, g, get_flashed_messages, redirect,
                   render_template, request, session, url_for)
from flask_wtf.csrf import CSRFError, CSRFProtect

import casaos
from auth import AdminAuth
from i18n import pick_language, translate

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("app")

DATA_DIR = os.environ.get("DATA_DIR", "/data")


def _secret_key():
    """SECRET_KEY, or a random key kept in DATA_DIR so logins survive restarts."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    path = os.path.join(DATA_DIR, "secret_key")
    try:
        with open(path) as f:
            key = f.read().strip()
        if key:
            return key
    except FileNotFoundError:
        pass
    key = secrets.token_hex(32)
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(path, "w") as f:
            f.write(key)
        os.chmod(path, 0o600)
    except OSError as e:
        log.warning("Cannot save %s (%s): you will be logged out on restart", path, e)
    return key


app = Flask(__name__)
app.config.update(
    SECRET_KEY=_secret_key(),
    SESSION_COOKIE_NAME="casaos_um_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    WTF_CSRF_TIME_LIMIT=None,
)
csrf = CSRFProtect(app)
admin = AdminAuth(DATA_DIR)


@app.before_request
def set_language():
    g.lang = pick_language(request.accept_languages)


@app.context_processor
def template_globals():
    def t(key, **params):
        return translate(g.lang, key, **params)

    def messages():
        return [
            (category, translate(g.lang, key, **params))
            for category, (key, params) in get_flashed_messages(with_categories=True)
        ]

    return {"t": t, "messages": messages, "lang": g.lang, "admin": admin,
            "logged_in": logged_in()}


def notify(key, category="success", **params):
    flash((key, params), category)


def logged_in():
    return session.get("admin") == admin.version


def requires_login(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not logged_in():
            if request.method == "GET":
                return redirect(url_for("login", next=request.path))
            abort(401)
        return f(*args, **kwargs)

    return decorated


def client_address():
    return request.remote_addr or "?"


@app.errorhandler(CSRFError)
def csrf_error(e):
    notify("csrf_error", "error")
    return redirect(url_for("index"))


@app.get("/healthz")
def healthz():
    return "ok"


@app.route("/login", methods=["GET", "POST"])
def login():
    if logged_in():
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        client = client_address()
        wait = admin.locked_for(client)
        if wait:
            error = translate(g.lang, "locked", seconds=wait)
        elif admin.check(request.form.get("username"), request.form.get("password")):
            admin.record_success(client)
            session.clear()
            session.permanent = True
            session["admin"] = admin.version
            log.info("Admin logged in from %s", client)
            target = request.args.get("next", "")
            if not target.startswith("/") or target.startswith("//"):
                target = url_for("index")
            return redirect(target)
        else:
            admin.record_failure(client)
            log.warning("Failed admin login from %s (user %r)",
                        client, request.form.get("username"))
            error = translate(g.lang, "wrong_login")
    return render_template("login.html", error=error), (401 if error else 200)


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
@requires_login
def index():
    users, db_error = [], None
    try:
        users = casaos.list_users()
    except casaos.CasaOSError as e:
        db_error = translate(g.lang, e.key, **e.params)
    return render_template(
        "index.html",
        users=users,
        db_error=db_error,
        service_state=casaos.service_state(),
    )


def run(action, success_key, **params):
    try:
        action()
        notify(success_key, **params)
    except casaos.CasaOSError as e:
        notify(e.key, "error", **e.params)
    return redirect(url_for("index"))


@app.post("/users")
@requires_login
def add_user():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    if password != request.form.get("confirm_password"):
        notify("passwords_differ", "error")
        return redirect(url_for("index"))
    return run(lambda: casaos.add_user(username, password),
               "user_added", username=username)


@app.post("/users/<int:user_id>/password")
@requires_login
def set_password(user_id):
    password = request.form.get("password") or ""
    if password != request.form.get("confirm_password"):
        notify("passwords_differ", "error")
        return redirect(url_for("index"))
    return run(lambda: casaos.set_password(user_id, password), "password_changed")


@app.post("/users/<int:user_id>/remove")
@requires_login
def remove_user(user_id):
    return run(lambda: casaos.remove_user(user_id), "user_removed")


@app.post("/reset")
@requires_login
def reset_database():
    if request.form.get("confirm") != "RESET":
        return redirect(url_for("index"))
    try:
        restarted = casaos.reset_database()
        notify("db_reset" if restarted else "db_reset_no_restart",
               "success" if restarted else "error")
    except casaos.CasaOSError as e:
        notify(e.key, "error", **e.params)
    return redirect(url_for("index"))


@app.post("/admin")
@requires_login
def change_admin():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    if not admin.check(admin.username, request.form.get("current_password")):
        notify("wrong_current", "error")
    elif not username or not password:
        notify("error_required", "error")
    elif password != request.form.get("confirm_password"):
        notify("passwords_differ", "error")
    else:
        try:
            admin.change(username, password)
        except OSError as e:
            notify("error_db", "error", detail=str(e))
            return redirect(url_for("index"))
        session["admin"] = admin.version
        notify("admin_changed")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
