"""Access to the CasaOS user database and the CasaOS user service.

CasaOS (CasaOS-UserService) keeps its users in a SQLite file, table
``o_users``, and checks a login by comparing ``md5(password)`` (hex) with the
``password`` column. It reads the table on every login, so changes made here
are seen immediately, without restarting anything.
"""

import hashlib
import logging
import os
import sqlite3
from datetime import datetime

log = logging.getLogger(__name__)

DB_PATH = os.environ.get("CASAOS_DB", "/var/lib/casaos/db/user.db")
SERVICE_NAME = os.environ.get("CASAOS_USER_SERVICE", "casaos-user-service.service")


class CasaOSError(Exception):
    """An error with a message meant for the UI (a translation key)."""

    def __init__(self, key, **params):
        super().__init__(key)
        self.key = key
        self.params = params


def casaos_hash(password):
    """The hash CasaOS stores: md5 of the password, as lowercase hex."""
    return hashlib.md5(password.encode("utf-8")).hexdigest()


def _now():
    # Same layout GORM writes for SQLite time columns.
    return datetime.now().astimezone().isoformat(sep=" ")


def backup_path():
    return DB_PATH + ".bak"


def db_exists():
    return os.path.isfile(DB_PATH)


def _connect():
    if not db_exists():
        raise CasaOSError("error_db_missing", path=DB_PATH)
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.execute("SELECT 1 FROM o_users LIMIT 1")
        return conn
    except sqlite3.Error as e:
        log.error("Cannot open %s: %s", DB_PATH, e)
        raise CasaOSError("error_db", detail=str(e)) from e


def _backup(conn):
    """Copy the database to user.db.bak before a change (one copy is kept)."""
    try:
        with sqlite3.connect(backup_path()) as dest:
            conn.backup(dest)
    except sqlite3.Error as e:
        log.warning("Backup to %s failed: %s", backup_path(), e)


def list_users():
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, username, role FROM o_users ORDER BY id"
        ).fetchall()
        return [{"id": r[0], "username": r[1], "role": r[2] or ""} for r in rows]
    finally:
        conn.close()


def add_user(username, password):
    username = (username or "").strip()
    if not username or not password:
        raise CasaOSError("error_required")
    conn = _connect()
    try:
        if conn.execute(
            "SELECT 1 FROM o_users WHERE username = ?", (username,)
        ).fetchone():
            raise CasaOSError("error_user_exists", username=username)
        _backup(conn)
        now = _now()
        conn.execute(
            "INSERT INTO o_users (username, password, role, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (username, casaos_hash(password), "admin", now, now),
        )
        conn.commit()
        log.info("CasaOS user %r added", username)
    except sqlite3.Error as e:
        raise CasaOSError("error_db", detail=str(e)) from e
    finally:
        conn.close()


def set_password(user_id, password):
    if not user_id or not password:
        raise CasaOSError("error_required")
    conn = _connect()
    try:
        _backup(conn)
        cur = conn.execute(
            "UPDATE o_users SET password = ?, updated_at = ? WHERE id = ?",
            (casaos_hash(password), _now(), user_id),
        )
        if cur.rowcount == 0:
            raise CasaOSError("error_user_missing")
        conn.commit()
        log.info("Password of CasaOS user id %s changed", user_id)
    except sqlite3.Error as e:
        raise CasaOSError("error_db", detail=str(e)) from e
    finally:
        conn.close()


def remove_user(user_id):
    if not user_id:
        raise CasaOSError("error_required")
    conn = _connect()
    try:
        (count,) = conn.execute("SELECT COUNT(*) FROM o_users").fetchone()
        if count <= 1:
            raise CasaOSError("error_last_user")
        _backup(conn)
        cur = conn.execute("DELETE FROM o_users WHERE id = ?", (user_id,))
        if cur.rowcount == 0:
            raise CasaOSError("error_user_missing")
        conn.commit()
        log.info("CasaOS user id %s removed", user_id)
    except sqlite3.Error as e:
        raise CasaOSError("error_db", detail=str(e)) from e
    finally:
        conn.close()


def reset_database():
    """Delete user.db and restart the user service, which creates an empty one.

    CasaOS then shows its first-run screen to create a new account.
    Returns False when the database is gone but the restart failed.
    """
    conn = _connect()
    try:
        _backup(conn)
    finally:
        conn.close()
    os.remove(DB_PATH)
    log.warning("CasaOS user database deleted (backup in %s)", backup_path())
    return restart_service()


# --- CasaOS user service, through the host's systemd over D-Bus ------------
#
# Needs the host's /var/run/dbus/system_bus_socket mounted. Failures are not
# fatal: only "reset database" needs a restart, and the UI says when it failed.


def _systemd(conn, path, interface, method, signature="", args=()):
    from jeepney import DBusAddress, new_method_call
    from jeepney.wrappers import unwrap_msg

    addr = DBusAddress(path, bus_name="org.freedesktop.systemd1", interface=interface)
    msg = new_method_call(addr, method, signature, args)
    return unwrap_msg(conn.send_and_get_reply(msg, timeout=10))


def _manager(conn, method, signature, args):
    return _systemd(
        conn, "/org/freedesktop/systemd1", "org.freedesktop.systemd1.Manager",
        method, signature, args,
    )


def _open_bus():
    from jeepney.io.blocking import open_dbus_connection

    return open_dbus_connection(bus="SYSTEM")


def service_state():
    """ActiveState of the CasaOS user service ("active", ...), or None."""
    try:
        with _open_bus() as conn:
            (path,) = _manager(conn, "LoadUnit", "s", (SERVICE_NAME,))
            ((_, state),) = _systemd(
                conn, path, "org.freedesktop.DBus.Properties", "Get", "ss",
                ("org.freedesktop.systemd1.Unit", "ActiveState"),
            )
            return state
    except Exception as e:  # no D-Bus socket, AppArmor, no systemd...
        log.debug("Cannot read %s state: %s", SERVICE_NAME, e)
        return None


def restart_service():
    try:
        with _open_bus() as conn:
            _manager(conn, "RestartUnit", "ss", (SERVICE_NAME, "replace"))
        log.info("%s restarted", SERVICE_NAME)
        return True
    except Exception as e:
        log.error("Cannot restart %s: %s", SERVICE_NAME, e)
        return False
