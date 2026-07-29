#!/usr/bin/env bash
set -Eeuo pipefail

readonly APP_ROOT="${SPYBOXD_APP_ROOT:-/opt/spyboxd}"
readonly REPOSITORY_DIR="${SPYBOXD_REPOSITORY_DIR:-${APP_ROOT}/repository}"
readonly RELEASES_DIR="${SPYBOXD_RELEASES_DIR:-${APP_ROOT}/releases}"
readonly SHARED_DIR="${SPYBOXD_SHARED_DIR:-${APP_ROOT}/shared}"
readonly CURRENT_LINK="${SPYBOXD_CURRENT_LINK:-${APP_ROOT}/current}"
readonly API_ENV_FILE="${SPYBOXD_API_ENV_FILE:-/etc/spyboxd/api.env}"
readonly FRONTEND_ENV_FILE="${SPYBOXD_FRONTEND_ENV_FILE:-/etc/spyboxd/frontend.env}"
readonly RSS_ENV_FILE="${SPYBOXD_RSS_ENV_FILE:-/etc/spyboxd/rss.env}"
readonly DEPLOY_REF="${SPYBOXD_DEPLOY_REF:-refs/remotes/origin/main}"
readonly RUNTIME_USER="${SPYBOXD_RUNTIME_USER:-spyboxd}"
readonly SERVICES=(spyboxd-api.service spyboxd-rss.service spyboxd-frontend.service)

TEMP_RELEASE=""
ACTIVATION_LINK=""
TEMP_REPOSITORY=""

log() {
    printf '[spyboxd-release] %s\n' "$*"
}

fail() {
    printf '[spyboxd-release] ERROR: %s\n' "$*" >&2
    exit 1
}

cleanup() {
    local exit_status=$?
    trap - EXIT
    if [[ -n "${ACTIVATION_LINK}" && -L "${ACTIVATION_LINK}" ]]; then
        rm -f -- "${ACTIVATION_LINK}"
    fi
    if [[ -n "${TEMP_RELEASE}" && -d "${TEMP_RELEASE}" ]]; then
        rm -rf -- "${TEMP_RELEASE}"
    fi
    if [[ -n "${TEMP_REPOSITORY}" && -d "${TEMP_REPOSITORY}" ]]; then
        rm -rf -- "${TEMP_REPOSITORY}"
    fi
    exit "${exit_status}"
}
trap cleanup EXIT

usage() {
    printf 'Usage: %s <full-40-character-git-sha>\n' "$0" >&2
    exit 64
}

[[ $# -eq 1 ]] || usage
readonly RELEASE_SHA="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
[[ "${RELEASE_SHA}" =~ ^[0-9a-f]{40}$ ]] || fail "release must be a full 40-character lowercase or uppercase Git SHA"

for command_name in git tar python3 node npm curl readlink flock stat sudo seq getent grep ufw; do
    command -v "${command_name}" >/dev/null 2>&1 || fail "required command is missing: ${command_name}"
done

python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 12))' \
    || fail "Python 3.12 or newer is required"
node -e 'const [major,minor]=process.versions.node.split(".").map(Number); process.exit(major > 20 || (major === 20 && minor >= 9) ? 0 : 1)' \
    || fail "Node.js 20.9 or newer is required"
python3 - <<'PY' || fail "localhost must resolve exclusively to loopback addresses"
import ipaddress
import socket

addresses = {
    result[4][0].split("%", 1)[0]
    for result in socket.getaddrinfo("localhost", 3000, type=socket.SOCK_STREAM)
}
if not addresses or any(not ipaddress.ip_address(address).is_loopback for address in addresses):
    raise SystemExit(1)
PY

if ! id "${RUNTIME_USER}" >/dev/null 2>&1; then
    fail "runtime user '${RUNTIME_USER}' is missing. Bootstrap it with: sudo useradd --system --user-group --home /nonexistent --shell /usr/sbin/nologin ${RUNTIME_USER}; sudo usermod -aG ${RUNTIME_USER} $(id -un); then reconnect the deploy SSH session"
fi
if ! getent group "${RUNTIME_USER}" >/dev/null 2>&1; then
    fail "runtime group '${RUNTIME_USER}' is missing; the versioned systemd units require a matching user and group"
fi

runtime_uid="$(id -u "${RUNTIME_USER}")"
runtime_gid="$(id -g "${RUNTIME_USER}")"
deploy_has_runtime_group=false
for deploy_gid in $(id -G); do
    if [[ "${deploy_gid}" == "${runtime_gid}" ]]; then
        deploy_has_runtime_group=true
        break
    fi
done
if [[ "${deploy_has_runtime_group}" != true ]]; then
    fail "the deploy account must be a member of ${RUNTIME_USER}. Run: sudo usermod -aG ${RUNTIME_USER} $(id -un); then reconnect the deploy SSH session"
fi

for env_file in "${API_ENV_FILE}" "${FRONTEND_ENV_FILE}" "${RSS_ENV_FILE}"; do
    if [[ ! -r "${env_file}" ]]; then
        fail "missing readable environment file ${env_file}. Install the matching deploy/env/*.env.example as root:${RUNTIME_USER} mode 0640 and replace every placeholder"
    fi
    env_mode="$(stat -c '%a' "${env_file}")"
    env_owner="$(stat -c '%u' "${env_file}")"
    env_group="$(stat -c '%g' "${env_file}")"
    if [[ "${env_owner}" != 0 || "${env_group}" != "${runtime_gid}" || "${env_mode}" != 640 ]]; then
        fail "${env_file} must be owned by root, writable only by root, readable by ${RUNTIME_USER}, and inaccessible to other users (recommended owner/mode: root:${RUNTIME_USER} 0640)"
    fi
done

for unit in "${SERVICES[@]}"; do
    unit_state="$(sudo -n systemctl show "${unit}" --property=LoadState --value 2>/dev/null || true)"
    if [[ "${unit_state}" != "loaded" ]]; then
        fail "${unit} is not installed. Copy deploy/systemd/*.service to /etc/systemd/system, validate and install deploy/sudoers/spyboxd-deploy, run sudo systemctl daemon-reload, then enable the three Spyboxd units"
    fi
done

frontend_exec_start="$(
    sudo -n systemctl show spyboxd-frontend.service --property=ExecStart --value 2>/dev/null \
        || true
)"
if [[ "${frontend_exec_start}" != *"--hostname localhost --port 3000"* ]]; then
    fail "spyboxd-frontend.service must be the versioned loopback-only unit from deploy/systemd"
fi
frontend_environment="$(
    sudo -n systemctl show spyboxd-frontend.service --property=Environment --value 2>/dev/null \
        || true
)"
if [[ "${frontend_environment}" != *"NODE_OPTIONS=--dns-result-order=ipv4first"* ]]; then
    fail "spyboxd-frontend.service must prefer IPv4 localhost for Clerk/Next proxy compatibility"
fi

if ! sudo -n nginx -t >/dev/null 2>&1; then
    fail "nginx validation failed. Install deploy/nginx/spyboxd.conf, provision both TLS certificates, run sudo nginx -t, and grant the deploy account non-interactive permission for nginx -t"
fi

firewall_status="$(sudo -n ufw status verbose 2>/dev/null || true)"
if ! grep -q '^Status: active$' <<<"${firewall_status}"; then
    fail "UFW must be active before application services start. Allow OpenSSH and Nginx Full, set default deny incoming, then enable UFW"
fi
if ! grep -q '^Default: deny (incoming)' <<<"${firewall_status}"; then
    fail "UFW must use default deny for incoming traffic"
fi
if grep -Eq '^[[:space:]]*(3000|8000)(/tcp)?([[:space:]]|\()' <<<"${firewall_status}"; then
    fail "UFW must not expose internal application ports 3000 or 8000"
fi

if [[ -e "${CURRENT_LINK}" && ! -L "${CURRENT_LINK}" ]]; then
    fail "${CURRENT_LINK} exists but is not a symlink; move the legacy checkout aside before the first activation"
fi

app_root_mode="$(stat -c '%a' "${APP_ROOT}")"
if (( (8#${app_root_mode} & 8#005) != 8#005 )); then
    fail "${APP_ROOT} must be readable and traversable by the ${RUNTIME_USER} service account (for the current topology, use mode 0755)"
fi

umask 027
if ! mkdir -p -- "${RELEASES_DIR}"; then
    fail "the deploy account cannot initialize ${RELEASES_DIR}; create it with: sudo install -d -o $(id -un) -g $(id -gn) -m 0755 ${RELEASES_DIR}"
fi
chmod 0755 "${RELEASES_DIR}"
if [[ ! -d "${SHARED_DIR}/data" ]]; then
    fail "shared state directories are missing. Bootstrap them with: sudo install -d -o $(id -un) -g ${RUNTIME_USER} -m 0750 ${SHARED_DIR}; sudo install -d -o ${RUNTIME_USER} -g ${RUNTIME_USER} -m 0750 ${SHARED_DIR}/data"
fi
shared_identity="$(stat -c '%u:%g:%a' "${SHARED_DIR}")"
data_identity="$(stat -c '%u:%g:%a' "${SHARED_DIR}/data")"
if [[ "${shared_identity}" != "$(id -u):${runtime_gid}:750" || "${data_identity}" != "${runtime_uid}:${runtime_gid}:750" ]]; then
    fail "shared state permissions are unsafe; expected ${SHARED_DIR}=$(id -u):${runtime_gid}:750 and ${SHARED_DIR}/data=${runtime_uid}:${runtime_gid}:750. Re-run the bootstrap install commands shown for missing shared state"
fi

exec 9>"${APP_ROOT}/.release.lock"
flock -n 9 || fail "another Spyboxd release is already running"

initialize_repository() {
    local remote_url repository_tmp

    [[ ! -e "${REPOSITORY_DIR}" ]] || fail "${REPOSITORY_DIR} exists but is not a bare Git repository"

    remote_url="${SPYBOXD_GIT_REMOTE_URL:-}"
    if [[ -z "${remote_url}" && -d "${APP_ROOT}/.git" ]]; then
        remote_url="$(git -C "${APP_ROOT}" remote get-url origin 2>/dev/null || true)"
    fi
    [[ -n "${remote_url}" ]] || fail "first rollout needs SPYBOXD_GIT_REMOTE_URL, or the legacy ${APP_ROOT} checkout must have an origin remote"

    repository_tmp="${REPOSITORY_DIR}.bootstrap.$$"
    [[ ! -e "${repository_tmp}" ]] || fail "temporary repository path already exists: ${repository_tmp}"
    TEMP_REPOSITORY="${repository_tmp}"
    log "Initializing the release repository from the configured origin"
    git init --bare --quiet "${repository_tmp}"
    git --git-dir="${repository_tmp}" remote add origin "${remote_url}"
    git --git-dir="${repository_tmp}" config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
    git --git-dir="${repository_tmp}" fetch --quiet --prune --tags origin
    mv -- "${repository_tmp}" "${REPOSITORY_DIR}"
    TEMP_REPOSITORY=""
}

if [[ ! -d "${REPOSITORY_DIR}" ]] || ! git --git-dir="${REPOSITORY_DIR}" rev-parse --is-bare-repository >/dev/null 2>&1; then
    initialize_repository
fi

log "Fetching origin and validating exact release ${RELEASE_SHA}"
git --git-dir="${REPOSITORY_DIR}" fetch --quiet --force --prune --tags origin '+refs/heads/*:refs/remotes/origin/*'
resolved_sha="$(git --git-dir="${REPOSITORY_DIR}" rev-parse --verify "${RELEASE_SHA}^{commit}" 2>/dev/null || true)"
[[ "${resolved_sha}" == "${RELEASE_SHA}" ]] || fail "${RELEASE_SHA} is not an available commit from origin"
git --git-dir="${REPOSITORY_DIR}" show-ref --verify --quiet "${DEPLOY_REF}" || fail "deployment ref ${DEPLOY_REF} does not exist after fetch"
git --git-dir="${REPOSITORY_DIR}" merge-base --is-ancestor "${RELEASE_SHA}" "${DEPLOY_REF}" || fail "${RELEASE_SHA} is not reachable from ${DEPLOY_REF}"

readonly FINAL_RELEASE="${RELEASES_DIR}/${RELEASE_SHA}"
release_is_complete=false
if [[ -d "${FINAL_RELEASE}" ]]; then
    if [[ -f "${FINAL_RELEASE}/REVISION" ]] \
        && [[ "$(<"${FINAL_RELEASE}/REVISION")" == "${RELEASE_SHA}" ]] \
        && [[ -x "${FINAL_RELEASE}/.venv/bin/uvicorn" ]] \
        && [[ -f "${FINAL_RELEASE}/frontend/.next/BUILD_ID" ]] \
        && [[ -f "${FINAL_RELEASE}/frontend/node_modules/next/dist/bin/next" ]]; then
        release_is_complete=true
        log "Reusing completed release ${FINAL_RELEASE}"
    else
        fail "${FINAL_RELEASE} already exists but is incomplete; inspect and remove only that exact directory before retrying"
    fi
fi

if [[ "${release_is_complete}" != true ]]; then
    # Build at the final versioned path because Python virtualenv entry-point
    # shebangs contain absolute paths and virtualenvs are not safely relocatable.
    # The current symlink is not touched until every build and migration passes.
    TEMP_RELEASE="${FINAL_RELEASE}"
    mkdir -m 0750 -- "${TEMP_RELEASE}"
    chgrp "${RUNTIME_USER}" "${TEMP_RELEASE}"

    log "Exporting source"
    git --git-dir="${REPOSITORY_DIR}" archive --format=tar "${RELEASE_SHA}" | tar -xf - -C "${TEMP_RELEASE}"

    log "Installing Python dependencies"
    python3 -m venv "${TEMP_RELEASE}/.venv"
    "${TEMP_RELEASE}/.venv/bin/python" -m pip install --disable-pip-version-check --quiet --require-hashes -r "${TEMP_RELEASE}/requirements.lock"

    log "Installing and building frontend dependencies"
    (
        cd "${TEMP_RELEASE}/frontend"
        npm ci --no-audit --no-fund --quiet
        "${TEMP_RELEASE}/.venv/bin/python" - "${FRONTEND_ENV_FILE}" npm run build <<'PY'
import os
import sys

from dotenv import dotenv_values

env_file, *command = sys.argv[1:]
values = {key: value for key, value in dotenv_values(env_file).items() if value is not None}
required = (
    "API_URL",
    "NEXT_PUBLIC_API_BASE_URL",
    "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY",
    "CLERK_SECRET_KEY",
)
missing = [key for key in required if not values.get(key)]
placeholders = [key for key in required if "REPLACE_WITH" in values.get(key, "")]
if missing or placeholders:
    details = ", ".join(missing + placeholders)
    raise SystemExit(f"invalid frontend environment values in {env_file}: {details}")
os.execvpe(command[0], command, os.environ | values)
PY
        npm prune --omit=dev --no-audit --no-fund --quiet
    )

    [[ -f "${TEMP_RELEASE}/frontend/.next/BUILD_ID" ]] || fail "frontend build did not create .next/BUILD_ID"
    rm -rf -- "${TEMP_RELEASE}/frontend/.next/cache"
    ln -s /var/cache/spyboxd-frontend "${TEMP_RELEASE}/frontend/.next/cache"
    ln -s "${SHARED_DIR}/data" "${TEMP_RELEASE}/data"
    printf '%s\n' "${RELEASE_SHA}" >"${TEMP_RELEASE}/REVISION"
    chgrp -R "${RUNTIME_USER}" "${TEMP_RELEASE}"
    chmod -R g+rX,o-rwx "${TEMP_RELEASE}"

    TEMP_RELEASE=""
fi

"${FINAL_RELEASE}/.venv/bin/python" - "${FRONTEND_ENV_FILE}" <<'PY'
import sys

from dotenv import dotenv_values

env_file = sys.argv[1]
values = {key: value for key, value in dotenv_values(env_file).items() if value is not None}
required = (
    "API_URL",
    "NEXT_PUBLIC_API_BASE_URL",
    "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY",
    "CLERK_SECRET_KEY",
)
invalid = [
    key
    for key in required
    if not values.get(key) or "REPLACE_WITH" in values.get(key, "")
]
if invalid:
    raise SystemExit(f"invalid frontend environment values in {env_file}: {', '.join(invalid)}")
PY

log "Applying database migrations"
(
    cd "${FINAL_RELEASE}"
    "${FINAL_RELEASE}/.venv/bin/python" - "${API_ENV_FILE}" "${RSS_ENV_FILE}" "${FINAL_RELEASE}" <<'PY'
import os
import sys

from dotenv import dotenv_values

api_env_file, rss_env_file, release_dir = sys.argv[1:]
api_values = {key: value for key, value in dotenv_values(api_env_file).items() if value is not None}
rss_values = {key: value for key, value in dotenv_values(rss_env_file).items() if value is not None}

required_api = ("DATABASE_URL", "FRONTEND_URL", "CORS_ALLOWED_ORIGINS", "INGESTION_API_TOKEN")
invalid = [
    key
    for key in required_api
    if not api_values.get(key) or "REPLACE_WITH" in api_values.get(key, "")
]
clerk_urls = [
    api_values.get("CLERK_JWKS_URL", ""),
    api_values.get("CLERK_FRONTEND_API", ""),
]
if not any(value and "REPLACE_WITH" not in value for value in clerk_urls):
    invalid.append("CLERK_JWKS_URL or CLERK_FRONTEND_API")
if not rss_values.get("DATABASE_URL") or "REPLACE_WITH" in rss_values.get("DATABASE_URL", ""):
    invalid.append("rss DATABASE_URL")
if api_values.get("DATABASE_URL") != rss_values.get("DATABASE_URL"):
    invalid.append("matching API and RSS DATABASE_URL values")
if invalid:
    raise SystemExit("invalid production environment: " + ", ".join(invalid))

environment = os.environ | api_values
environment["PYTHONPATH"] = f"{release_dir}:{release_dir}/backend"
command = [
    f"{release_dir}/.venv/bin/alembic",
    "-c",
    f"{release_dir}/alembic.ini",
    "upgrade",
    "head",
]
os.execvpe(command[0], command, environment)
PY
)

old_release=""
legacy_rollback=false
if [[ -L "${CURRENT_LINK}" ]]; then
    old_release="$(readlink -f "${CURRENT_LINK}" || true)"
    if [[ "${old_release}" == "${APP_ROOT}" ]]; then
        legacy_rollback=true
    elif [[ -n "${old_release}" && "${old_release}" != "${RELEASES_DIR}/"* ]]; then
        fail "current release target is outside ${RELEASES_DIR}: ${old_release}"
    fi
elif [[ -x "${APP_ROOT}/.venv/bin/uvicorn" && -f "${APP_ROOT}/frontend/.next/BUILD_ID" ]]; then
    old_release="${APP_ROOT}"
    legacy_rollback=true
    log "A healthy-checkable legacy in-place release is available for first-rollout rollback"
fi

activate_release() {
    local release_path="$1"
    ACTIVATION_LINK="${APP_ROOT}/.current.$$"
    ln -s "${release_path}" "${ACTIVATION_LINK}"
    mv -Tf -- "${ACTIVATION_LINK}" "${CURRENT_LINK}"
    ACTIVATION_LINK=""
}

restart_services() {
    sudo -n systemctl restart "${SERVICES[@]}"
}

wait_for_http() {
    local name="$1" url="$2" expected_status="${3:-}" response attempt
    for attempt in $(seq 1 30); do
        if response="$(curl --silent --show-error --fail --max-time 5 "${url}" 2>/dev/null)"; then
            if [[ -z "${expected_status}" ]] \
                || [[ "${response}" == *"\"status\":\"${expected_status}\""* ]] \
                || [[ "${response}" == *"\"status\": \"${expected_status}\""* ]]; then
                log "${name} is ready"
                return 0
            fi
        fi
        sleep 2
    done
    return 1
}

check_readiness() {
    wait_for_http "API" "http://127.0.0.1:8000/ready" ready \
        && wait_for_http "frontend" "http://127.0.0.1:3000/" \
        && wait_for_http "public API" "https://api.spyboxd.com/ready" ready \
        && wait_for_http "public frontend" "https://spyboxd.com/"
}

check_rollback_liveness() {
    wait_for_http "rolled-back API" "http://127.0.0.1:8000/health" ok \
        && wait_for_http "rolled-back frontend" "http://127.0.0.1:3000/"
}

observe_rss_health() {
    local status_code
    status_code="$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 5 http://127.0.0.1:8000/health/rss 2>/dev/null || true)"
    if [[ "${status_code}" == 200 ]]; then
        log "RSS operational health endpoint responded successfully"
    else
        log "WARNING: RSS operational health is observational and currently returned HTTP ${status_code:-unavailable}" >&2
    fi
}

log "Activating ${FINAL_RELEASE}"
activate_release "${FINAL_RELEASE}"

if restart_services && check_readiness; then
    observe_rss_health
    log "Release ${RELEASE_SHA} is active and healthy"
    exit 0
fi

log "Health verification failed; rolling application services back"
if [[ -n "${old_release}" && -d "${old_release}" ]]; then
    activate_release "${old_release}"
    if [[ "${legacy_rollback}" == true ]]; then
        sudo -n systemctl restart spyboxd-api.service spyboxd-frontend.service || true
        sudo -n systemctl stop spyboxd-rss.service || true
    else
        restart_services || true
    fi
    if check_rollback_liveness; then
        log "Rollback to ${old_release} is healthy. Database migrations were not downgraded."
    else
        log "WARNING: rollback services did not become healthy; inspect journalctl for ${SERVICES[*]}" >&2
    fi
else
    sudo -n systemctl stop "${SERVICES[@]}" || true
    rm -f -- "${CURRENT_LINK}"
    log "First activation failed, so services were stopped and the current symlink was removed. Database migrations were not downgraded." >&2
fi

exit 1
