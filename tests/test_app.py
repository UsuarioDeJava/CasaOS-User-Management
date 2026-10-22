"""End-to-end tests of the web app against a fake CasaOS user.db.

Run: pip install -r requirements.txt pytest && pytest
"""

import hashlib
import importlib
import json
import os
import re
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

# Same table CasaOS-UserService creates (model.UserDBModel).
SCHEMA = """
CREATE TABLE o_users (
  id integer PRIMARY KEY AUTOINCREMENT, username text, password text,
  role text, email text, nickname text, avatar text, description text,
  created_at datetime, updated_at datetime
)
"""


def md5(s):
    return hashlib.md5(s.encode()).hexdigest()


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = tmp_path / "db" / "user.db"
    db.parent.mkdir()
    with sqlite3.connect(db) as conn:
        conn.execute(SCHEMA)
        conn.execute(
            "INSERT INTO o_users (username, password, role) VALUES ('casa', ?, 'admin')",
            (md5("old"),),
        )
    monkeypatch.setenv("CASAOS_DB", str(db))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    for name in ("ADMIN_USERNAME", "ADMIN_PASSWORD", "RESET_ADMIN", "SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)
    return {"db": db, "data": tmp_path / "data", "monkeypatch": monkeypatch}


def make_client(env):
    for mod in ("casaos", "auth", "app"):
        sys.modules.pop(mod, None)
    app_module = importlib.import_module("app")
    casaos = sys.modules["casaos"]
    env["monkeypatch"].setattr(casaos, "service_state", lambda: "active")
    env["monkeypatch"].setattr(casaos, "restart_service", lambda: True)
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def csrf(client, path="/"):
    page = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)


def login(client, username="casaos", password="casaos"):
    return client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": csrf(client, "/login")},
    )


def post(client, path, **data):
    data["csrf_token"] = csrf(client)
    return client.post(path, data=data, follow_redirects=True)


def users(env):
    with sqlite3.connect(env["db"]) as conn:
        return dict(conn.execute("SELECT username, password FROM o_users").fetchall())


# --- admin login ---


def test_default_login_and_warning(env):
    client = make_client(env)
    assert client.get("/").headers["Location"].startswith("/login")
    assert login(client).status_code == 302
    page = client.get("/").get_data(as_text=True)
    assert "casa" in page and "casaos / casaos" in page


def test_wrong_login(env):
    client = make_client(env)
    r = login(client, password="nope")
    assert r.status_code == 401
    assert client.get("/").status_code == 302


@pytest.mark.parametrize("raw", ["Senha Forte!", "  Senha Forte!  ", '"Senha Forte!"', "'Senha Forte!'"])
def test_env_password_is_cleaned(env, raw):
    env["monkeypatch"].setenv("ADMIN_USERNAME", " matheus ")
    env["monkeypatch"].setenv("ADMIN_PASSWORD", raw)
    client = make_client(env)
    assert login(client, "casaos", "casaos").status_code == 401
    assert login(client, "matheus", "Senha Forte!").status_code == 302
    assert "casaos / casaos" not in client.get("/").get_data(as_text=True)


def test_username_ignores_case(env):
    env["monkeypatch"].setenv("ADMIN_USERNAME", "UsuarioDeJava")
    env["monkeypatch"].setenv("ADMIN_PASSWORD", "segredo")
    client = make_client(env)
    assert login(client, "usuariodejava", "segredo").status_code == 302


def test_failed_login_is_explained_in_the_log(env, caplog):
    env["monkeypatch"].setenv("ADMIN_USERNAME", "UsuarioDeJava")
    env["monkeypatch"].setenv("ADMIN_PASSWORD", "segredo")
    client = make_client(env)
    login(client, "casaos", "segredo")
    assert "user 'casaos' is not the configured user 'UsuarioDeJava'" in caplog.text
    login(client, "usuariodejava", "errada")
    assert "6 characters typed, the configured one has 7" in caplog.text
    assert "errada" not in caplog.text and "segredo" not in caplog.text


def test_swapped_variables_are_detected(env, caplog):
    env["monkeypatch"].setenv("ADMIN_USERNAME", "21102004M")
    env["monkeypatch"].setenv("ADMIN_PASSWORD", "usuariodejava")
    client = make_client(env)
    r = login(client, "usuariodejava", "21102004M")
    assert r.status_code == 401 and "swapped" in r.get_data(as_text=True)
    assert "ADMIN_USERNAME and ADMIN_PASSWORD are swapped" in caplog.text
    assert "swapped" not in login(client, "usuariodejava", "x").get_data(as_text=True)


def test_unicode_password(env):
    env["monkeypatch"].setenv("ADMIN_PASSWORD", "café$ção")
    client = make_client(env)
    assert login(client, "casaos", "café$ção").status_code == 302


def test_change_admin_in_ui_survives_restart(env):
    client = make_client(env)
    login(client)
    post(client, "/admin", current_password="casaos", username="eu",
         password="nova", confirm_password="nova")
    assert client.get("/").status_code == 200  # still logged in

    client = make_client(env)  # "restart"
    assert login(client).status_code == 401
    assert login(client, "eu", "nova").status_code == 302
    stored = json.loads((env["data"] / "admin.json").read_text())
    assert "nova" not in json.dumps(stored)


def test_change_admin_needs_current_password(env):
    client = make_client(env)
    login(client)
    r = post(client, "/admin", current_password="wrong", username="eu",
             password="nova", confirm_password="nova")
    assert "current password is wrong" in r.get_data(as_text=True)
    assert not (env["data"] / "admin.json").exists()


def test_env_change_after_ui_change_wins(env):
    client = make_client(env)
    login(client)
    post(client, "/admin", current_password="casaos", username="eu",
         password="nova", confirm_password="nova")

    env["monkeypatch"].setenv("ADMIN_USERNAME", "outro")
    env["monkeypatch"].setenv("ADMIN_PASSWORD", "da-env")
    client = make_client(env)
    assert login(client, "eu", "nova").status_code == 401
    assert login(client, "outro", "da-env").status_code == 302


def test_reset_admin(env):
    client = make_client(env)
    login(client)
    post(client, "/admin", current_password="casaos", username="eu",
         password="nova", confirm_password="nova")
    env["monkeypatch"].setenv("RESET_ADMIN", "true")
    client = make_client(env)
    assert login(client).status_code == 302


def test_lockout(env):
    client = make_client(env)
    for _ in range(5):
        login(client, password="nope")
    r = login(client)  # right password, but locked
    assert r.status_code == 401 and "Try again" in r.get_data(as_text=True)


def test_actions_need_login(env):
    client = make_client(env)
    token = csrf(client, "/login")
    for path in ("/users", "/users/1/password", "/users/1/remove", "/reset", "/admin"):
        r = client.post(path, data={"csrf_token": token, "username": "x", "password": "x",
                                    "confirm_password": "x", "confirm": "RESET"})
        assert r.status_code == 401, path
    assert set(users(env)) == {"casa"}


def test_csrf_required(env):
    client = make_client(env)
    login(client)
    client.post("/users", data={"username": "x", "password": "x", "confirm_password": "x"})
    assert set(users(env)) == {"casa"}


# --- CasaOS users ---


def test_add_edit_remove(env):
    client = make_client(env)
    login(client)
    post(client, "/users", username=" nova ", password="p1", confirm_password="p1")
    assert users(env)["nova"] == md5("p1")

    r = post(client, "/users", username="nova", password="p", confirm_password="p")
    assert "already exists" in r.get_data(as_text=True)

    post(client, "/users/1/password", password="nova-senha", confirm_password="nova-senha")
    assert users(env)["casa"] == md5("nova-senha")

    post(client, "/users/1/remove")
    assert set(users(env)) == {"nova"}
    assert os.path.exists(str(env["db"]) + ".bak")


def test_cannot_remove_last_user(env):
    client = make_client(env)
    login(client)
    r = post(client, "/users/1/remove")
    assert "at least one user" in r.get_data(as_text=True)
    assert set(users(env)) == {"casa"}


def test_passwords_must_match(env):
    client = make_client(env)
    login(client)
    post(client, "/users/1/password", password="a", confirm_password="b")
    assert users(env)["casa"] == md5("old")


def test_reset_database(env):
    client = make_client(env)
    login(client)
    post(client, "/reset", confirm="nope")
    assert env["db"].exists()
    r = post(client, "/reset", confirm="RESET")
    assert not env["db"].exists()
    assert "Database reset" in r.get_data(as_text=True)


def test_missing_database(env):
    env["db"].unlink()
    client = make_client(env)
    login(client)
    r = client.get("/")
    assert r.status_code == 200
    assert "database not found" in r.get_data(as_text=True)


def test_portuguese(env):
    client = make_client(env)
    page = client.get("/login", headers={"Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"})
    assert "Entrar" in page.get_data(as_text=True)
