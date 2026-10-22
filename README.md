# CasaOS User Management

**English** | [Português (Brasil)](README.pt-BR.md)

A web page to add, remove and change the password of [CasaOS](https://casaos.io)
users, with its own login. Useful when you forgot the CasaOS password.

> [!NOTE]
> **This is a fork of [BigBearCasaOS User Management](https://github.com/bigbeartechworld/big-bear-docker-images/tree/main/Apps/big-bear-casaos-user-management) only.**
> That app is a single folder (`Apps/big-bear-casaos-user-management`) of the
> [big-bear-docker-images](https://github.com/bigbeartechworld/big-bear-docker-images) repository, which holds many other images, so
> it cannot be forked on GitHub by itself. This repository started from that
> folder alone (version 0.1.1) and nothing else from big-bear-docker-images.
> The original is itself based on [casaos-user-management](https://github.com/carlbomsdata/casaos-user-management).
> Not affiliated with BigBearTechWorld.

## What changed from the BigBear version

- **The login works when you change it.** The old one compared the browser's
  Basic Auth prompt with `ADMIN_USERNAME`/`ADMIN_PASSWORD` character by
  character, and gave no hint when they differed. Now:
  - there is a real login page (session cookie, log out button);
  - spaces and quotes around the variables are removed;
  - the login can be changed **in the page** (key button), and it survives
    restarts and updates;
  - the log says which login is in use and its length
    (`Admin login: user 'casaos' (6 characters), password of 11 characters`),
    so a mangled value is easy to spot;
  - `RESET_ADMIN=true` brings back the variables' login if you are locked out.
- **Every action needs the login.** Before, only the user list was protected:
  adding, removing and changing CasaOS users worked without logging in.
  Forms are also protected against CSRF, and 5 wrong logins lock the address
  for 5 minutes.
- Success and error messages are shown (they never were).
- You cannot remove the last CasaOS user; a copy of `user.db` is kept in
  `user.db.bak` before every change.
- No debug server in production (gunicorn), a random session key, a
  healthcheck, no `privileged` container, no systemd package in the image
  (the user service is reached over D-Bus).
- The UI works without internet (CSS and icons are inside the image) and
  follows the browser language (English, Portuguese).

## Install on CasaOS

1. Uninstall the BigBear version if you have it (both use port 5000).
2. **App Store → More apps**, add
   `https://usuariodejava.github.io/CasaOS-User-Management/store.zip` (it shows up
   as **CasaOS-User-Management**), then install **CasaOS User Management**.

   Or **App Store → Custom install → Import**, and paste
   [`Apps/casaos-user-management/docker-compose.yml`](Apps/casaos-user-management/docker-compose.yml).
3. Open the app (port 5000) and sign in with **casaos / casaos**.
4. Change that login right away: key button at the top.

## The login of this page

It is not a CasaOS account. It comes from, in order:

1. The login set in the page (key button), kept in
   `/DATA/AppData/casaos-user-management/admin.json` (password hashed).
2. The `ADMIN_USERNAME` and `ADMIN_PASSWORD` variables (CasaOS: app
   settings).
3. `casaos` / `casaos`.

The most recent change wins: if you edit the variables in CasaOS after
changing the login in the page, the variables are used from then on.

The username ignores upper/lower case; the password does not.

**Login refused?** The app's log (CasaOS: app settings → *Logs*, or
`docker logs casaos-user-management`) says which login is in use at startup
and why each attempt failed, e.g. `user 'casaos' is not the configured user
'UsuarioDeJava' (from ADMIN_USERNAME)` or `wrong password: 9 characters typed,
the configured one has 10`. Passwords never appear in the log.

CasaOS does not always list `ADMIN_USERNAME` and `ADMIN_PASSWORD` in the same
order, so they are easy to swap: when that happens, the login page says so.

**Locked out?** Set `RESET_ADMIN` to `true` in the app settings, save (the app
restarts with the variables' login), sign in, and set it back to `false`.

A `$` in a variable must be written `$$` in a docker-compose file, or Docker
replaces it. Changing the login in the page has no such limit.

## Variables

| Variable | Default | |
| --- | --- | --- |
| `ADMIN_USERNAME` | `casaos` | Username of this page |
| `ADMIN_PASSWORD` | `casaos` | Password of this page |
| `RESET_ADMIN` | `false` | `true` forgets the login set in the page |
| `SECRET_KEY` | random, kept in `/data/secret_key` | Session cookie key |
| `CASAOS_DB` | `/var/lib/casaos/db/user.db` | CasaOS user database |
| `LOG_LEVEL` | `INFO` | |

## Volumes

| Container | Host | |
| --- | --- | --- |
| `/var/lib/casaos/db` | `/var/lib/casaos/db` | CasaOS user database |
| `/data` | `/DATA/AppData/casaos-user-management` | Login of this page |
| `/var/run/dbus/system_bus_socket` | same | Optional: shows the CasaOS user service state and restarts it after *Reset database* |

`apparmor:unconfined` is only needed for the D-Bus part (the default Docker
AppArmor profile blocks it). Without the socket, everything else works, and
after *Reset database* you restart CasaOS yourself
(`sudo systemctl restart casaos-user-service`).

## How it changes CasaOS users

CasaOS (CasaOS-UserService) keeps users in the SQLite table `o_users` and
checks a login by comparing `md5(password)` with the `password` column, reading
the table on every login. So a change made here is used by the next CasaOS
login, no restart needed. *Reset database* deletes `user.db` and restarts the
user service, which creates an empty one; CasaOS then shows its first-run
screen.

## Development

```bash
pip install -r requirements.txt pytest
pytest                      # tests against a fake CasaOS user.db
docker build -t casaos-user-management .
```

Run it locally (CSS and icons are built by the Dockerfile, so use the image):

```bash
docker run --rm -p 5000:5000 \
  -v /var/lib/casaos/db:/var/lib/casaos/db \
  -v "$PWD/data:/data" casaos-user-management
```

CI (`.github/workflows/ci.yml`) runs the tests, publishes
`ghcr.io/usuariodejava/casaos-user-management` (amd64, arm/v7, arm64) from
`main`, and publishes `Apps/` as `store.zip` on GitHub Pages.

## License

MIT, see [LICENSE](LICENSE).
