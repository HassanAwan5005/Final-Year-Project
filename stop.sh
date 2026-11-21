#!/usr/bin/env bash
#
# SnapSphere — stop the development servers.
#
#   ./stop.sh          stop Django and Celery
#   ./stop.sh --all    also stop MySQL and Redis
#
# MySQL and Redis are left running by default: they are shared services that
# other projects may also be using, and stopping them is rarely what you want.
# Works on macOS, Linux and Windows (Git Bash).

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$ROOT/.logs"

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) OS="windows" ;;
  Darwin)               OS="mac" ;;
  *)                    OS="linux" ;;
esac

GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; BOLD=$'\033[1m'; OFF=$'\033[0m'
ok()   { echo "  ${GREEN}✓${OFF} $1"; }
warn() { echo "  ${YELLOW}!${OFF} $1"; }

# stop_pid <pid file>: stop the process start.sh recorded. Returns 1 if none.
stop_pid() {
  [ -f "$1" ] || return 1
  local pid; pid=$(cat "$1"); rm -f "$1"
  kill -0 "$pid" 2>/dev/null || return 1
  kill "$pid" 2>/dev/null
}
# pkill does not exist in Git Bash; fall back silently.
stop_matching() { command -v pkill >/dev/null 2>&1 && pkill -f "$1" 2>/dev/null; }

echo
echo "${BOLD}Stopping SnapSphere${OFF}"
echo

# ─── Django ──────────────────────────────────────────────────────────────────
if stop_pid "$LOG_DIR/django.pid" || stop_matching "manage.py runserver"; then
  ok "Django stopped"
else
  warn "Django was not running"
fi

# ─── Celery ──────────────────────────────────────────────────────────────────
STOPPED=0
stop_pid "$LOG_DIR/celery-worker.pid" && STOPPED=1
stop_pid "$LOG_DIR/celery-beat.pid" && STOPPED=1
stop_matching "celery -A config" && STOPPED=1
if [ "$STOPPED" = 1 ]; then ok "Celery stopped"; else warn "Celery was not running"; fi

# ─── Expo ────────────────────────────────────────────────────────────────────
if stop_matching "expo start"; then
  ok "Expo bundler stopped"
fi

# ─── Optional: databases ─────────────────────────────────────────────────────
if [[ "${1:-}" == "--all" ]]; then
  case "$OS" in
    mac)
      brew services stop mysql >/dev/null 2>&1 && ok "MySQL stopped"
      brew services stop redis >/dev/null 2>&1 && ok "Redis stopped"
      ;;
    linux)
      sudo systemctl stop mysql >/dev/null 2>&1 && ok "MySQL stopped"
      sudo systemctl stop redis-server >/dev/null 2>&1 && ok "Redis stopped"
      ;;
    windows)
      # Only what start.sh itself launched; Windows services are left alone.
      stop_pid "$LOG_DIR/mysql.pid" && ok "MySQL stopped"
      stop_pid "$LOG_DIR/redis.pid" && ok "Redis stopped"
      ;;
  esac
else
  warn "MySQL and Redis left running (use --all to stop them too)"
fi

echo
