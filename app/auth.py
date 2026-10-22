"""The admin login of this app (not a CasaOS user).

Where the login comes from, in order:

1. ``DATA_DIR/admin.json``, written when the login is changed in the web UI.
   It also records a fingerprint of ADMIN_USERNAME/ADMIN_PASSWORD at that
   moment: if those variables are edited later (e.g. in the CasaOS app
   settings), the variables win and the file is dropped. The latest change
   wins, wherever it was made.
2. The ADMIN_USERNAME and ADMIN_PASSWORD variables (surrounding spaces and
   quotes removed).
3. casaos / casaos.

RESET_ADMIN=true deletes admin.json at startup.
"""

import hashlib
import hmac
import json
import logging
import os
import threading
import time

from werkzeug.security import check_password_hash, generate_password_hash

log = logging.getLogger(__name__)

DEFAULT_USERNAME = "casaos"
DEFAULT_PASSWORD = "casaos"

MAX_FAILURES = 5
FAILURE_WINDOW = 10 * 60
LOCK_TIME = 5 * 60


def _clean(value):
    value = (value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1]
    return value


class AdminAuth:
    def __init__(self, data_dir, env=os.environ):
        self.path = os.path.join(data_dir, "admin.json")
        self.env_username = _clean(env.get("ADMIN_USERNAME")) or DEFAULT_USERNAME
        self.env_password = _clean(env.get("ADMIN_PASSWORD")) or DEFAULT_PASSWORD
        self._from_env = bool(_clean(env.get("ADMIN_PASSWORD")))
        self._from_env_user = bool(_clean(env.get("ADMIN_USERNAME")))
        self._env_fp = self._fingerprint(self.env_username, self.env_password)
        self._lock = threading.Lock()
        self._failures = {}

        if _clean(env.get("RESET_ADMIN")).lower() in ("1", "true", "yes"):
            self._remove_file("RESET_ADMIN is set")
        self._load()

    @staticmethod
    def _fingerprint(username, password):
        return hashlib.sha256(f"{username}\0{password}".encode()).hexdigest()

    def _remove_file(self, reason):
        try:
            os.remove(self.path)
            log.warning("Removed %s (%s)", self.path, reason)
        except FileNotFoundError:
            pass

    def _load(self):
        data = None
        try:
            with open(self.path) as f:
                data = json.load(f)
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:
            log.error("Ignoring unreadable %s: %s", self.path, e)

        if data and data.get("env_fingerprint") != self._env_fp:
            self._remove_file("ADMIN_USERNAME/ADMIN_PASSWORD changed since")
            data = None

        if data:
            self.source = "web"
            self.username = data["username"]
            self.password_hash = data["password_hash"]
            log.info("Admin login: user %r, set in the web UI", self.username)
        else:
            self.source = "env"
            self.username = self.env_username
            self.password_hash = generate_password_hash(self.env_password)
            # Lengths only, never the password: enough to spot a mangled value.
            log.info(
                "Admin login: user %r (%d characters), password of %d characters, "
                "from %s",
                self.username, len(self.username), len(self.env_password),
                "ADMIN_USERNAME/ADMIN_PASSWORD"
                if self._from_env else "the defaults",
            )

    @property
    def is_default(self):
        return (
            self.source == "env"
            and self.env_username == DEFAULT_USERNAME
            and self.env_password == DEFAULT_PASSWORD
        )

    @property
    def version(self):
        """Changes whenever the login changes; stored in the session."""
        if self.source == "env":
            return self._env_fp[:16]
        return self._fingerprint(self.username, self.password_hash)[:16]

    def _user_ok(self, username):
        # Case-insensitive: "UsuarioDeJava" and "usuariodejava" are the same.
        typed = (username or "").strip().casefold().encode()
        return hmac.compare_digest(typed, self.username.casefold().encode())

    def check(self, username, password):
        user_ok = self._user_ok(username)
        pass_ok = check_password_hash(self.password_hash, password or "")
        return user_ok and pass_ok

    def swapped(self, username, password):
        """True when the typed login matches ADMIN_USERNAME/ADMIN_PASSWORD
        with the two values swapped (CasaOS does not always list the variables
        in the same order, so they are easy to fill in the wrong field)."""
        if self.source != "env":
            return False
        typed_user = (username or "").strip()
        return (
            hmac.compare_digest(typed_user.encode(), self.env_password.encode())
            and hmac.compare_digest((password or "").strip().casefold().encode(),
                                    self.env_username.casefold().encode())
        )

    def explain_failure(self, username, password):
        """Why a login failed, for the log (never shows a password)."""
        source = ("set in the web UI" if self.source == "web"
                  else "from ADMIN_USERNAME" if self._from_env_user
                  else "the default")
        if self.swapped(username, password):
            return "ADMIN_USERNAME and ADMIN_PASSWORD are swapped"
        if not self._user_ok(username):
            return (f"user {(username or '').strip()!r} is not the configured "
                    f"user {self.username!r} ({source})")
        typed = len(password or "")
        if self.source == "env":
            return (f"wrong password: {typed} characters typed, the configured "
                    f"one has {len(self.env_password)}")
        return f"wrong password ({typed} characters typed)"

    def change(self, username, password):
        username = username.strip()
        data = {
            "username": username,
            "password_hash": generate_password_hash(password),
            "env_fingerprint": self._env_fp,
        }
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)
        self.source = "web"
        self.username = username
        self.password_hash = data["password_hash"]
        log.info("Admin login changed in the web UI (user %r)", username)

    # --- brute-force throttle, per client address ---

    def locked_for(self, client):
        """Seconds left before ``client`` may try again (0 = may try)."""
        with self._lock:
            entry = self._failures.get(client)
            if entry and entry["locked_until"] > time.time():
                return int(entry["locked_until"] - time.time()) + 1
            return 0

    def record_failure(self, client):
        now = time.time()
        with self._lock:
            entry = self._failures.get(client)
            if not entry or now - entry["first"] > FAILURE_WINDOW:
                entry = {"first": now, "count": 0, "locked_until": 0}
                self._failures[client] = entry
            entry["count"] += 1
            if entry["count"] >= MAX_FAILURES:
                entry["locked_until"] = now + LOCK_TIME
                entry["count"] = 0
                entry["first"] = now
                log.warning("Too many failed logins from %s, locked", client)

    def record_success(self, client):
        with self._lock:
            self._failures.pop(client, None)
