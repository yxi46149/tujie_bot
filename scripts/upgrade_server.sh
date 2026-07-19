#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${TUJIE_UPGRADE_REEXEC:-0}" != "1" ]]; then
    self_path="${BASH_SOURCE[0]}"
    if [[ -f "$self_path" ]]; then
        tmp_self="$(mktemp /tmp/tujie-upgrade.XXXXXX.sh)"
        cp "$self_path" "$tmp_self"
        chmod +x "$tmp_self"
        exec env TUJIE_UPGRADE_REEXEC=1 TUJIE_UPGRADE_TMP_SELF="$tmp_self" bash "$tmp_self" "$@"
    fi
fi

if [[ -n "${TUJIE_UPGRADE_TMP_SELF:-}" ]]; then
    trap 'rm -f "$TUJIE_UPGRADE_TMP_SELF"' EXIT
fi

PROJECT_DIR="${PROJECT_DIR:-$(pwd)}"
SERVICE_NAME="${SERVICE_NAME:-tujie-bot}"
BACKUP_DIR="${BACKUP_DIR:-}"
TMP_DIR="${TMP_DIR:-}"
ZIP_PATH=""
SKIP_CHECK_BOT=0
RUN_TESTS=0
NO_START=0
SERVICE_WAS_ACTIVE=0
BACKUP_PATH=""

usage() {
    cat <<'EOF'
Usage:
  bash scripts/upgrade_server.sh [release.zip]
  bash scripts/upgrade_server.sh --zip /home/ubuntu/bot/tujie_bot-v0.1.2.zip

Options:
  -z, --zip PATH          Release ZIP. If omitted, auto-detect latest tujie_bot-v*.zip.
  -d, --project-dir DIR   Project directory. Default: current directory.
  -s, --service NAME      systemd service name. Default: tujie-bot.
      --backup-dir DIR    Database backup directory. Default: ../backups.
      --tmp-dir DIR       Temporary release directory. Default: ../release_tmp.
      --skip-check-bot    Skip Telegram connectivity check.
      --run-tests         Run unittest suite before starting service.
      --no-start          Do not start systemd service after upgrade.
  -h, --help              Show this help.

Examples:
  cd /home/ubuntu/bot/tujie_bot
  bash scripts/upgrade_server.sh /home/ubuntu/bot/tujie_bot-v0.1.2.zip

  bash scripts/upgrade_server.sh --project-dir /opt/tujie_bot --service tujie-bot
EOF
}

log() {
    printf '\n[upgrade] %s\n' "$*"
}

die() {
    printf '\n[upgrade][error] %s\n' "$*" >&2
    exit 1
}

on_error() {
    local exit_code=$?
    printf '\n[upgrade][error] Upgrade failed at line %s (exit %s).\n' "${BASH_LINENO[0]:-?}" "$exit_code" >&2
    if [[ -n "$BACKUP_PATH" ]]; then
        printf '[upgrade][error] Database backup: %s\n' "$BACKUP_PATH" >&2
    fi
    if [[ "$SERVICE_WAS_ACTIVE" == "1" ]]; then
        printf '[upgrade][error] Service was stopped. After fixing the issue, run: sudo systemctl start %s\n' "$SERVICE_NAME" >&2
    fi
    exit "$exit_code"
}
trap on_error ERR

require_command() {
    local name="$1"
    command -v "$name" >/dev/null 2>&1 || die "Missing command: $name"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -z|--zip)
            [[ $# -ge 2 ]] || die "$1 requires a value."
            ZIP_PATH="$2"
            shift 2
            ;;
        -d|--project-dir)
            [[ $# -ge 2 ]] || die "$1 requires a value."
            PROJECT_DIR="$2"
            shift 2
            ;;
        -s|--service)
            [[ $# -ge 2 ]] || die "$1 requires a value."
            SERVICE_NAME="$2"
            shift 2
            ;;
        --backup-dir)
            [[ $# -ge 2 ]] || die "$1 requires a value."
            BACKUP_DIR="$2"
            shift 2
            ;;
        --tmp-dir)
            [[ $# -ge 2 ]] || die "$1 requires a value."
            TMP_DIR="$2"
            shift 2
            ;;
        --skip-check-bot)
            SKIP_CHECK_BOT=1
            shift
            ;;
        --run-tests)
            RUN_TESTS=1
            shift
            ;;
        --no-start)
            NO_START=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            if [[ -z "$ZIP_PATH" ]]; then
                ZIP_PATH="$1"
                shift
            else
                die "Unknown argument: $1"
            fi
            ;;
    esac
done

require_command realpath
require_command unzip
require_command rsync
require_command systemctl
require_command python3

SUDO=()
if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    require_command sudo
    SUDO=(sudo)
fi

PROJECT_DIR="$(realpath -m "$PROJECT_DIR")"
[[ -d "$PROJECT_DIR" ]] || die "Project directory does not exist: $PROJECT_DIR"
[[ -f "$PROJECT_DIR/requirements.txt" && -d "$PROJECT_DIR/app" ]] || die "Not a tujie_bot project directory: $PROJECT_DIR"
[[ -f "$PROJECT_DIR/.env" ]] || die "Missing .env in project directory: $PROJECT_DIR/.env"

PROJECT_PARENT="$(dirname "$PROJECT_DIR")"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_PARENT/backups}"
TMP_DIR="${TMP_DIR:-$PROJECT_PARENT/release_tmp}"
BACKUP_DIR="$(realpath -m "$BACKUP_DIR")"
TMP_DIR="$(realpath -m "$TMP_DIR")"

[[ -n "$TMP_DIR" && "$TMP_DIR" != "/" ]] || die "Unsafe temporary directory: $TMP_DIR"
case "$TMP_DIR/" in
    "$PROJECT_DIR/"*) die "Temporary directory must be outside project directory: $TMP_DIR" ;;
esac
case "$PROJECT_DIR/" in
    "$TMP_DIR/"*) die "Temporary directory cannot contain project directory: $TMP_DIR" ;;
esac

detect_zip() {
    local -a candidates=()
    shopt -s nullglob
    candidates+=("$PROJECT_PARENT"/tujie_bot-v*.zip)
    candidates+=("$(pwd)"/tujie_bot-v*.zip)
    shopt -u nullglob

    if [[ "${#candidates[@]}" -eq 0 ]]; then
        return 1
    fi

    local latest=""
    local candidate
    for candidate in "${candidates[@]}"; do
        if [[ -z "$latest" || "$candidate" -nt "$latest" ]]; then
            latest="$candidate"
        fi
    done
    printf '%s\n' "$latest"
}

if [[ -z "$ZIP_PATH" ]]; then
    ZIP_PATH="$(detect_zip || true)"
    [[ -n "$ZIP_PATH" ]] || die "No release ZIP found. Pass one explicitly, for example: bash scripts/upgrade_server.sh /home/ubuntu/bot/tujie_bot-v0.1.2.zip"
fi

ZIP_PATH="$(realpath -m "$ZIP_PATH")"
[[ -f "$ZIP_PATH" ]] || die "Release ZIP does not exist: $ZIP_PATH"

if ! unzip -Z1 "$ZIP_PATH" | grep -qx 'tujie_bot/requirements.txt'; then
    die "Release ZIP does not look like a tujie_bot package: $ZIP_PATH"
fi

SERVICE_EXISTS=0
if systemctl cat "$SERVICE_NAME" >/dev/null 2>&1; then
    SERVICE_EXISTS=1
    service_workdir="$(systemctl show "$SERVICE_NAME" --property=WorkingDirectory --value 2>/dev/null || true)"
    if [[ -n "$service_workdir" && "$service_workdir" != "-" ]]; then
        service_workdir="$(realpath -m "$service_workdir")"
        if [[ "$service_workdir" != "$PROJECT_DIR" ]]; then
            die "Service WorkingDirectory is $service_workdir, but project directory is $PROJECT_DIR. Re-run with --project-dir or fix deploy/tujie-bot.service."
        fi
    fi
fi

log "Project directory: $PROJECT_DIR"
log "Release ZIP: $ZIP_PATH"
log "Service: $SERVICE_NAME"

if [[ "$SERVICE_EXISTS" == "1" ]]; then
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        SERVICE_WAS_ACTIVE=1
    fi
    log "Stopping service..."
    "${SUDO[@]}" systemctl stop "$SERVICE_NAME"
else
    log "systemd service not found; upgrade will sync files and run checks only."
fi

if compgen -G "$PROJECT_DIR/data/bot.db*" >/dev/null; then
    timestamp="$(date +%Y%m%d-%H%M%S)"
    BACKUP_PATH="$BACKUP_DIR/bot-db-$timestamp"
    mkdir -p "$BACKUP_PATH"
    cp -a "$PROJECT_DIR"/data/bot.db* "$BACKUP_PATH"/
    log "Database backup: $BACKUP_PATH"
else
    log "No database file found; skipped database backup."
fi

log "Unpacking release..."
rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR"
unzip -q "$ZIP_PATH" -d "$TMP_DIR"
RELEASE_ROOT="$TMP_DIR/tujie_bot"
[[ -d "$RELEASE_ROOT/app" && -f "$RELEASE_ROOT/requirements.txt" ]] || die "Invalid release content under $RELEASE_ROOT"

log "Syncing application files..."
rsync -a --delete \
    --exclude '.env' \
    --exclude '.venv' \
    --exclude '.git' \
    --exclude 'data' \
    --exclude 'dist' \
    --exclude 'logs' \
    "$RELEASE_ROOT"/ "$PROJECT_DIR"/

cd "$PROJECT_DIR"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
    log "Creating virtual environment..."
    python3 -m venv "$PROJECT_DIR/.venv" || die "Failed to create venv. On Ubuntu install venv first: sudo apt install -y python3.12-venv"
fi

log "Installing dependencies..."
"$PYTHON_BIN" -m pip install -r requirements.txt

if [[ "$RUN_TESTS" == "1" ]]; then
    log "Running automated tests..."
    "$PYTHON_BIN" -m unittest discover -s tests -v
fi

log "Running local config check..."
"$PYTHON_BIN" -m scripts.check_config

if [[ "$SKIP_CHECK_BOT" == "0" ]]; then
    log "Running Telegram connectivity check..."
    "$PYTHON_BIN" -m scripts.check_bot
else
    log "Skipped Telegram connectivity check."
fi

rm -rf "$TMP_DIR"

if [[ "$NO_START" == "1" ]]; then
    log "Skipped service start because --no-start was provided."
    log "Upgrade completed."
    exit 0
fi

if [[ "$SERVICE_EXISTS" == "1" ]]; then
    log "Starting service..."
    "${SUDO[@]}" systemctl start "$SERVICE_NAME"
    sleep 2
    if ! systemctl is-active --quiet "$SERVICE_NAME"; then
        "${SUDO[@]}" systemctl status "$SERVICE_NAME" --no-pager --full || true
        die "Service failed to stay active: $SERVICE_NAME"
    fi
    "${SUDO[@]}" systemctl status "$SERVICE_NAME" --no-pager --full
else
    log "Start manually: cd \"$PROJECT_DIR\" && .venv/bin/python -m app.main"
fi

log "Upgrade completed."
