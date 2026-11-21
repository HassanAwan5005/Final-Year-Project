#!/usr/bin/env bash
#
# SnapSphere — start everything needed for development.
#
#   ./start.sh            start MySQL, Redis and the Django API
#   ./start.sh --workers  also start the Celery worker and scheduler
#
# Works on macOS (Homebrew), Linux and Windows (Git Bash). Safe to run
# repeatedly: it checks what is already running instead of starting duplicates.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
LOG_DIR="$ROOT/.logs"

# ─── Platform ────────────────────────────────────────────────────────────────
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) OS="windows" ;;
  Darwin)               OS="mac" ;;
  *)                    OS="linux" ;;
esac

# The venv keeps executables in Scripts/ on Windows and bin/ elsewhere.
if [ -x "$BACKEND/.venv/Scripts/python.exe" ]; then
  VENV_BIN="$BACKEND/.venv/Scripts"; PY="$VENV_BIN/python.exe"
else
  VENV_BIN="$BACKEND/.venv/bin"; PY="$VENV_BIN/python"
fi

GREEN=$'\033[0;32m'; RED=$'\033[0;31m'; YELLOW=$'\033[0;33m'
BLUE=$'\033[0;34m'; BOLD=$'\033[1m'; OFF=$'\033[0m'

ok()   { echo "  ${GREEN}✓${OFF} $1"; }
warn() { echo "  ${YELLOW}!${OFF} $1"; }
fail() { echo "  ${RED}✗${OFF} $1"; }
step() { echo; echo "${BOLD}$1${OFF}"; }

# Is something listening on this local port? Portable: uses the venv's Python.
port_open() {
  "$PY" -c "import socket,sys; socket.create_connection(('127.0.0.1', $1), 1)" >/dev/null 2>&1
}
wait_for_port() {  # wait_for_port <port> <seconds>
  for _ in $(seq 1 "$2"); do port_open "$1" && return 0; sleep 1; done
  return 1
}
# Is the process in this pid file alive?
pid_alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }

mkdir -p "$LOG_DIR"

echo
echo "${BOLD}${BLUE}SnapSphere${OFF} — starting development environment ($OS)"

# ─── 1. Prerequisites ────────────────────────────────────────────────────────
step "1. Checking prerequisites"

if [ ! -x "$PY" ]; then
  fail "Python venv missing at $BACKEND/.venv"
  echo "     Run:  cd backend && python3.12 -m venv .venv  (Windows: py -3.12 -m venv .venv)"
  exit 1
fi
ok "python $("$PY" --version 2>&1 | cut -d' ' -f2)"

if [ ! -f "$BACKEND/.env" ]; then
  warn ".env missing — copying from .env.example"
  cp "$BACKEND/.env.example" "$BACKEND/.env"
fi
ok ".env present"

# ─── 2. MySQL ────────────────────────────────────────────────────────────────
step "2. MySQL"

if port_open 3306; then
  ok "already running"
else
  warn "not running — starting"
  case "$OS" in
    mac)   brew services start mysql >/dev/null 2>&1 ;;
    linux) sudo systemctl start mysql >/dev/null 2>&1 ;;
    windows)
      # A local server on the project's own data directory (mysql-data/).
      MYSQLD=$(ls -d "/c/Program Files/MySQL/MySQL Server "*/bin/mysqld.exe 2>/dev/null | tail -1)
      if [ -n "$MYSQLD" ] && [ -d "$ROOT/mysql-data" ]; then
        nohup "$MYSQLD" --datadir="$(cygpath -m "$ROOT/mysql-data")" --port=3306 \
          > "$LOG_DIR/mysql.log" 2>&1 &
        echo $! > "$LOG_DIR/mysql.pid"
      else
        fail "could not find mysqld.exe or $ROOT/mysql-data — start your MySQL service"
        exit 1
      fi
      ;;
  esac
  if wait_for_port 3306 60; then ok "started"; else fail "MySQL did not start (see .logs/mysql.log)"; exit 1; fi
fi

# Tables and users, read through Django so the .env credentials are used.
DB_STATE=$(cd "$BACKEND" && "$PY" manage.py shell -c "
from django.db import connection
from django.contrib.auth import get_user_model
print(len(connection.introspection.table_names()), get_user_model().objects.count())
" 2>/dev/null | tail -1)
TABLES=${DB_STATE%% *}; USERS=${DB_STATE##* }
if [ -z "$DB_STATE" ] || ! [[ "$TABLES" =~ ^[0-9]+$ ]]; then
  fail "cannot connect to the 'snapsphere' database"
  echo "     Create it:  CREATE DATABASE snapsphere CHARACTER SET utf8mb4;  then  manage.py migrate"
  exit 1
fi
ok "database reachable — $TABLES tables"

if [ "${USERS:-0}" -lt 10 ]; then
  warn "database looks empty ($USERS users) — run:  cd backend && $PY manage.py seed_data --flush"
else
  ok "seeded — $USERS users"
fi

# ─── 3. Redis ────────────────────────────────────────────────────────────────
step "3. Redis"

if port_open 6379; then
  ok "already running"
else
  warn "not running — starting"
  case "$OS" in
    mac)   brew services start redis >/dev/null 2>&1 ;;
    linux) sudo systemctl start redis-server >/dev/null 2>&1 ;;
    windows)
      if command -v redis-server >/dev/null 2>&1; then
        nohup redis-server > "$LOG_DIR/redis.log" 2>&1 &
        echo $! > "$LOG_DIR/redis.pid"
      else
        warn "redis-server not on PATH — start the Redis Windows service"
      fi
      ;;
  esac
  if wait_for_port 6379 30; then ok "started"; else fail "Redis is not running"; exit 1; fi
fi

# ─── 4. Django API ───────────────────────────────────────────────────────────
step "4. Django API"

if curl -s -m 3 -o /dev/null http://127.0.0.1:8000/health/ 2>/dev/null; then
  ok "already running on :8000"
else
  warn "not running — starting on :8000"
  cd "$BACKEND"
  nohup "$PY" manage.py runserver 0.0.0.0:8000 > "$LOG_DIR/django.log" 2>&1 &
  echo $! > "$LOG_DIR/django.pid"
  until curl -s -m 2 -o /dev/null http://127.0.0.1:8000/health/ 2>/dev/null; do sleep 1; done
  ok "started (pid $(cat "$LOG_DIR/django.pid"), log: .logs/django.log)"
fi

HEALTH=$(curl -s http://127.0.0.1:8000/health/)
echo "$HEALTH" | grep -q '"status": *"healthy"' \
  && ok "health check: database ok, cache ok" \
  || fail "health check reported a problem: $HEALTH"

# ─── 5. Celery (optional) ────────────────────────────────────────────────────
if [[ "${1:-}" == "--workers" ]]; then
  step "5. Celery"
  cd "$BACKEND"
  # Celery's default prefork pool does not run on Windows.
  POOL=""; [ "$OS" = "windows" ] && POOL="--pool=solo"

  if pid_alive "$LOG_DIR/celery-worker.pid"; then
    ok "worker already running"
  else
    nohup "$VENV_BIN/celery" -A config worker -l info $POOL \
      > "$LOG_DIR/celery-worker.log" 2>&1 &
    echo $! > "$LOG_DIR/celery-worker.pid"
    ok "worker started (log: .logs/celery-worker.log)"
  fi

  if pid_alive "$LOG_DIR/celery-beat.pid"; then
    ok "scheduler already running"
  else
    nohup "$VENV_BIN/celery" -A config beat -l info \
      > "$LOG_DIR/celery-beat.log" 2>&1 &
    echo $! > "$LOG_DIR/celery-beat.pid"
    ok "scheduler started (log: .logs/celery-beat.log)"
  fi
fi

# ─── Ready ───────────────────────────────────────────────────────────────────
if [ "$OS" = "windows" ]; then
  LAN_IP=$(ipconfig 2>/dev/null | grep -a "IPv4" | head -1 | sed 's/.*: *//' | tr -d '\r')
elif [ "$OS" = "mac" ]; then
  LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)
else
  LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
fi
LAN_IP=${LAN_IP:-127.0.0.1}

echo
echo "${BOLD}${GREEN}Ready.${OFF}"
echo
echo "  API docs (Swagger)   http://127.0.0.1:8000/api/v1/docs/"
echo "  Django admin         http://127.0.0.1:8000/django-admin/"
echo "  Health               http://127.0.0.1:8000/health/"
echo "  From your phone      http://$LAN_IP:8000/api/v1/"
echo
echo "  Test the API         ./test.sh"
echo "  Start the app        cd mobile && npx expo start"
echo "  Stop everything      ./stop.sh"
echo
