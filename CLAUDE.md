# CasaOS User Management

Container for CasaOS with a web UI to add, remove and change the password of
CasaOS users, behind its own admin login. See README.md.

## Rules
- Reply to the user in Portuguese (pt-BR); code, comments and docs in English.
- The user's CasaOS is only reachable on their LAN/Tailscale: test against the
  fake user.db (tests/), never against the real server.
- Commits as UsuarioDeJava, straight to `main`; no PR unless asked.
- README.md (English) and README.pt-BR.md (Portuguese) are kept in sync.
- UI texts live in `app/i18n.py` (`en`, `pt_br`); a new text goes in both.

## Layout
- `app/app.py`: Flask routes; every action needs the admin session and a CSRF
  token. Messages are flashed as translation keys.
- `app/auth.py`: the admin login. Order: `DATA_DIR/admin.json` (set in the UI)
  unless ADMIN_USERNAME/ADMIN_PASSWORD changed since it was written, then the
  variables, then casaos/casaos. In-memory failed-login throttle, so gunicorn
  runs one worker.
- `app/casaos.py`: CasaOS `o_users` table (password = md5 hex, read on every
  CasaOS login, so no restart is needed) and the host's systemd over D-Bus
  (jeepney) for the user service state/restart.
- `web/`: Tailwind config and CSS, compiled by the Dockerfile's first stage
  with the Font Awesome files into `app/static/` (git-ignored).
- `Apps/casaos-user-management/docker-compose.yml`: the CasaOS app; CI zips
  `Apps/` to GitHub Pages as `store.zip`.

## Tests
- `pytest` (fake user.db with the CasaOS-UserService schema).
