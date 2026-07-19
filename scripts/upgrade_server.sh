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

if [[ -n "${PROJECT_DIR:-}" ]]; then
    PROJECT_DIR_EXPLICIT=1
else
    PROJECT_DIR_EXPLICIT=0
    PROJECT_DIR="$(pwd)"
fi
SERVICE_NAME="${SERVICE_NAME:-tujie-bot}"
BACKUP_DIR="${BACKUP_DIR:-}"
TMP_DIR="${TMP_DIR:-}"
UPGRADE_SCRIPT_PATH="${UPGRADE_SCRIPT_PATH:-}"
ZIP_PATH=""
SKIP_CHECK_BOT=0
RUN_TESTS=0
NO_START=0
ALLOW_DELETE_EXTRA=0
SERVICE_WAS_ACTIVE=0
BACKUP_PATH=""
DATABASE_FILE=""

usage() {
    cat <<'EOF'
用法：
  cd /home/ubuntu/bot
  bash upgrade_server.sh [release.zip]

  bash scripts/upgrade_server.sh [release.zip]
  bash scripts/upgrade_server.sh --zip /home/ubuntu/bot/tujie_bot-v0.1.2.zip

参数：
  -z, --zip PATH          发布 ZIP。未填写时自动查找最新的 tujie_bot-v*.zip。
  -d, --project-dir DIR   项目目录。默认：当前目录；若当前目录下有 tujie_bot/，则自动使用它。
  -s, --service NAME      systemd 服务名。默认：tujie-bot。
      --backup-dir DIR    数据库备份目录。默认：../backups。
      --tmp-dir DIR       临时解压目录。默认：../release_tmp。
      --upgrade-script PATH
                            外置升级脚本保存位置。默认：项目上级目录/upgrade_server.sh。
      --skip-check-bot    跳过 Telegram 联通性检查。
      --run-tests         启动服务前运行单元测试。
      --no-start          升级完成后不启动 systemd 服务。
      --allow-delete-extra
                            允许 rsync 删除非程序文件。生产环境不建议使用。
  -h, --help              显示帮助。

示例：
  cd /home/ubuntu/bot
  bash upgrade_server.sh
  bash upgrade_server.sh tujie_bot-v0.1.2.zip

  cd /home/ubuntu/bot/tujie_bot
  bash scripts/upgrade_server.sh /home/ubuntu/bot/tujie_bot-v0.1.2.zip

  bash scripts/upgrade_server.sh --project-dir /opt/tujie_bot --service tujie-bot
EOF
}

log() {
    printf '\n[升级] %s\n' "$*"
}

die() {
    printf '\n[升级][失败] %s\n' "$*" >&2
    exit 1
}

on_error() {
    local exit_code=$?
    printf '\n[升级][失败] 脚本在第 %s 行失败，退出码 %s。\n' "${BASH_LINENO[0]:-?}" "$exit_code" >&2
    if [[ -n "$BACKUP_PATH" ]]; then
        printf '[升级][失败] 数据库备份位置：%s\n' "$BACKUP_PATH" >&2
    fi
    if [[ "$SERVICE_WAS_ACTIVE" == "1" ]]; then
        printf '[升级][失败] 服务已经停止。修复问题后可执行：sudo systemctl start %s\n' "$SERVICE_NAME" >&2
    fi
    exit "$exit_code"
}
trap on_error ERR

require_command() {
    local name="$1"
    command -v "$name" >/dev/null 2>&1 || die "缺少命令：$name"
}

trim() {
    local value="$1"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    printf '%s' "$value"
}

resolve_database_file() {
    local database_value=""
    local line=""
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="$(trim "$line")"
        line="${line#export }"
        [[ "$line" == DATABASE_PATH=* ]] || continue
        database_value="${line#DATABASE_PATH=}"
    done < "$PROJECT_DIR/.env"

    database_value="$(trim "${database_value:-data/bot.db}")"
    if [[ "$database_value" == \"*\" && "$database_value" == *\" ]]; then
        database_value="${database_value:1:${#database_value}-2}"
    elif [[ "$database_value" == \'*\' && "$database_value" == *\' ]]; then
        database_value="${database_value:1:${#database_value}-2}"
    fi

    if [[ "$database_value" = /* ]]; then
        realpath -m "$database_value"
    else
        realpath -m "$PROJECT_DIR/$database_value"
    fi
}

prepare_tmp_dir() {
    if [[ -e "$TMP_DIR" && ! -f "$TMP_DIR/.tujie-upgrade-tmp" ]]; then
        die "临时目录已存在且没有升级脚本标记，为避免误删拒绝清理：$TMP_DIR"
    fi
    rm -rf "$TMP_DIR"
    mkdir -p "$TMP_DIR"
    touch "$TMP_DIR/.tujie-upgrade-tmp"
}

install_external_upgrade_script() {
    local source_path="$PROJECT_DIR/scripts/upgrade_server.sh"
    if [[ ! -f "$source_path" ]]; then
        log "未找到新版升级脚本，跳过外置脚本更新：$source_path"
        return 0
    fi
    if [[ "$UPGRADE_SCRIPT_PATH/" == "$PROJECT_DIR/"* ]]; then
        log "外置脚本路径位于项目目录内，跳过自动更新：$UPGRADE_SCRIPT_PATH"
        return 0
    fi
    if cp "$source_path" "$UPGRADE_SCRIPT_PATH" 2>/dev/null; then
        chmod +x "$UPGRADE_SCRIPT_PATH" 2>/dev/null || true
        log "已更新外置升级脚本：$UPGRADE_SCRIPT_PATH"
    else
        log "未能更新外置升级脚本，请手动执行：cp \"$source_path\" \"$UPGRADE_SCRIPT_PATH\""
    fi
}

is_expected_delete() {
    local path="${1#./}"
    case "$path" in
        app/*|deploy/*|docs/*|scripts/*|tests/*) return 0 ;;
        __pycache__/*|*/__pycache__/*|*.pyc|*.pyo) return 0 ;;
        .dockerignore|.env.example|.gitignore|.gitattributes) return 0 ;;
        compose.yaml|Dockerfile|README.md|requirements.txt|VERSION) return 0 ;;
    esac
    return 1
}

check_rsync_deletions() {
    local dry_run_file="$1"
    local blocked=()
    local line=""
    local path=""
    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ "$line" == \*deleting* ]] || continue
        path="${line#*deleting}"
        path="$(trim "$path")"
        [[ -n "$path" ]] || continue
        if ! is_expected_delete "$path"; then
            blocked+=("$path")
        fi
    done < "$dry_run_file"

    if [[ "${#blocked[@]}" -eq 0 || "$ALLOW_DELETE_EXTRA" == "1" ]]; then
        return 0
    fi

    printf '\n[升级][失败] 同步新版本时将删除以下非程序文件，已中止以保护生产数据：\n' >&2
    local item=""
    for item in "${blocked[@]}"; do
        printf '  - %s\n' "$item" >&2
    done
    printf '\n这些文件可能是生产卡密、临时资料或手工上传文件。请先移动或备份它们。\n' >&2
    printf '确认这些文件可以删除时，再显式追加参数：--allow-delete-extra\n' >&2
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -z|--zip)
            [[ $# -ge 2 ]] || die "$1 需要填写参数值。"
            ZIP_PATH="$2"
            shift 2
            ;;
        -d|--project-dir)
            [[ $# -ge 2 ]] || die "$1 需要填写参数值。"
            PROJECT_DIR="$2"
            PROJECT_DIR_EXPLICIT=1
            shift 2
            ;;
        -s|--service)
            [[ $# -ge 2 ]] || die "$1 需要填写参数值。"
            SERVICE_NAME="$2"
            shift 2
            ;;
        --backup-dir)
            [[ $# -ge 2 ]] || die "$1 需要填写参数值。"
            BACKUP_DIR="$2"
            shift 2
            ;;
        --tmp-dir)
            [[ $# -ge 2 ]] || die "$1 需要填写参数值。"
            TMP_DIR="$2"
            shift 2
            ;;
        --upgrade-script)
            [[ $# -ge 2 ]] || die "$1 需要填写参数值。"
            UPGRADE_SCRIPT_PATH="$2"
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
        --allow-delete-extra)
            ALLOW_DELETE_EXTRA=1
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
                die "无法识别的参数：$1"
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
if [[ "$PROJECT_DIR_EXPLICIT" == "0" ]]; then
    if [[ ! -f "$PROJECT_DIR/requirements.txt" && -d "$PROJECT_DIR/tujie_bot" ]]; then
        PROJECT_CANDIDATE="$(realpath -m "$PROJECT_DIR/tujie_bot")"
        if [[ -f "$PROJECT_CANDIDATE/requirements.txt" && -d "$PROJECT_CANDIDATE/app" ]]; then
            PROJECT_DIR="$PROJECT_CANDIDATE"
        fi
    fi
fi
[[ -d "$PROJECT_DIR" ]] || die "项目目录不存在：$PROJECT_DIR"
[[ -f "$PROJECT_DIR/requirements.txt" && -d "$PROJECT_DIR/app" ]] || die "这不是 tujie_bot 项目目录：$PROJECT_DIR"
[[ -f "$PROJECT_DIR/.env" ]] || die "项目目录缺少 .env：$PROJECT_DIR/.env"

PROJECT_PARENT="$(dirname "$PROJECT_DIR")"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_PARENT/backups}"
TMP_DIR="${TMP_DIR:-$PROJECT_PARENT/release_tmp}"
UPGRADE_SCRIPT_PATH="${UPGRADE_SCRIPT_PATH:-$PROJECT_PARENT/upgrade_server.sh}"
BACKUP_DIR="$(realpath -m "$BACKUP_DIR")"
TMP_DIR="$(realpath -m "$TMP_DIR")"
UPGRADE_SCRIPT_PATH="$(realpath -m "$UPGRADE_SCRIPT_PATH")"
DATABASE_FILE="$(resolve_database_file)"

[[ -n "$TMP_DIR" && "$TMP_DIR" != "/" ]] || die "临时目录不安全：$TMP_DIR"
case "$TMP_DIR/" in
    "$PROJECT_DIR/"*) die "临时目录必须放在项目目录外：$TMP_DIR" ;;
esac
case "$PROJECT_DIR/" in
    "$TMP_DIR/"*) die "临时目录不能包含项目目录：$TMP_DIR" ;;
esac
case "$BACKUP_DIR/" in
    "$TMP_DIR/"*) die "备份目录不能放在临时目录内：$BACKUP_DIR" ;;
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
    [[ -n "$ZIP_PATH" ]] || die "没有找到发布 ZIP。请显式传入，例如：bash scripts/upgrade_server.sh /home/ubuntu/bot/tujie_bot-v0.1.2.zip"
fi

ZIP_PATH="$(realpath -m "$ZIP_PATH")"
[[ -f "$ZIP_PATH" ]] || die "发布 ZIP 不存在：$ZIP_PATH"

if ! unzip -Z1 "$ZIP_PATH" | grep -qx 'tujie_bot/requirements.txt'; then
    die "发布 ZIP 看起来不是 tujie_bot 包：$ZIP_PATH"
fi

SERVICE_EXISTS=0
if systemctl cat "$SERVICE_NAME" >/dev/null 2>&1; then
    SERVICE_EXISTS=1
    service_workdir="$(systemctl show "$SERVICE_NAME" --property=WorkingDirectory --value 2>/dev/null || true)"
    if [[ -n "$service_workdir" && "$service_workdir" != "-" ]]; then
        service_workdir="$(realpath -m "$service_workdir")"
        if [[ "$service_workdir" != "$PROJECT_DIR" ]]; then
            die "systemd 服务目录是 $service_workdir，但本次项目目录是 $PROJECT_DIR。请用 --project-dir 指定正确目录，或修正 deploy/tujie-bot.service。"
        fi
    fi
fi

log "项目目录：$PROJECT_DIR"
log "发布包：$ZIP_PATH"
log "服务名：$SERVICE_NAME"
log "数据库文件：$DATABASE_FILE"
log "外置升级脚本：$UPGRADE_SCRIPT_PATH"

if [[ "$SERVICE_EXISTS" == "1" ]]; then
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        SERVICE_WAS_ACTIVE=1
    fi
    log "正在停止服务..."
    "${SUDO[@]}" systemctl stop "$SERVICE_NAME"
else
    log "未找到 systemd 服务；本次只同步文件并执行检查。"
fi

if compgen -G "$DATABASE_FILE*" >/dev/null; then
    timestamp="$(date +%Y%m%d-%H%M%S)"
    BACKUP_PATH="$BACKUP_DIR/bot-db-$timestamp"
    mkdir -p "$BACKUP_PATH"
    cp -a "$DATABASE_FILE"* "$BACKUP_PATH"/
    log "已备份数据库：$BACKUP_PATH"
else
    log "未找到数据库文件，跳过数据库备份。"
fi

log "正在解压发布包..."
prepare_tmp_dir
unzip -q "$ZIP_PATH" -d "$TMP_DIR"
RELEASE_ROOT="$TMP_DIR/tujie_bot"
[[ -d "$RELEASE_ROOT/app" && -f "$RELEASE_ROOT/requirements.txt" ]] || die "发布包内容不完整：$RELEASE_ROOT"

RSYNC_EXCLUDES=(
    --exclude '.env' \
    --exclude '.venv' \
    --exclude '.git' \
    --exclude 'data' \
    --exclude 'dist' \
    --exclude 'logs' \
    --exclude 'backups' \
    --exclude '*.db' \
    --exclude '*.db-wal' \
    --exclude '*.db-shm' \
    --exclude '*.sqlite' \
    --exclude '*.sqlite3' \
    --exclude '*.log'
)
if [[ "$DATABASE_FILE" == "$PROJECT_DIR/"* ]]; then
    database_relative="$(realpath -m --relative-to="$PROJECT_DIR" "$DATABASE_FILE")"
    RSYNC_EXCLUDES+=(
        --exclude "$database_relative"
        --exclude "$database_relative-wal"
        --exclude "$database_relative-shm"
    )
fi

log "正在预检查同步删除清单..."
DRY_RUN_FILE="$(mktemp /tmp/tujie-rsync-check.XXXXXX)"
rsync -a --delete --dry-run --itemize-changes "${RSYNC_EXCLUDES[@]}" "$RELEASE_ROOT"/ "$PROJECT_DIR"/ > "$DRY_RUN_FILE"
check_rsync_deletions "$DRY_RUN_FILE"
rm -f "$DRY_RUN_FILE"

log "正在同步程序文件..."
rsync -a --delete "${RSYNC_EXCLUDES[@]}" "$RELEASE_ROOT"/ "$PROJECT_DIR"/
install_external_upgrade_script

cd "$PROJECT_DIR"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
    log "正在创建虚拟环境..."
    python3 -m venv "$PROJECT_DIR/.venv" || die "创建虚拟环境失败。Ubuntu 请先安装：sudo apt install -y python3.12-venv"
fi

log "正在安装依赖..."
"$PYTHON_BIN" -m pip install -r requirements.txt

if [[ "$RUN_TESTS" == "1" ]]; then
    log "正在运行自动化测试..."
    "$PYTHON_BIN" -m unittest discover -s tests -v
fi

log "正在执行本地配置检查..."
"$PYTHON_BIN" -m scripts.check_config

if [[ "$SKIP_CHECK_BOT" == "0" ]]; then
    log "正在执行 Telegram 联通性检查..."
    "$PYTHON_BIN" -m scripts.check_bot
else
    log "已跳过 Telegram 联通性检查。"
fi

rm -rf "$TMP_DIR"

if [[ "$NO_START" == "1" ]]; then
    log "已按 --no-start 跳过服务启动。"
    log "升级完成。"
    exit 0
fi

if [[ "$SERVICE_EXISTS" == "1" ]]; then
    log "正在启动服务..."
    "${SUDO[@]}" systemctl start "$SERVICE_NAME"
    sleep 2
    if ! systemctl is-active --quiet "$SERVICE_NAME"; then
        "${SUDO[@]}" systemctl status "$SERVICE_NAME" --no-pager --full || true
        die "服务启动后未保持运行：$SERVICE_NAME"
    fi
    "${SUDO[@]}" systemctl status "$SERVICE_NAME" --no-pager --full
else
    log "可手动启动：cd \"$PROJECT_DIR\" && .venv/bin/python -m app.main"
fi

log "升级完成。"
