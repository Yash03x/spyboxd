#!/usr/bin/env bash
set -Eeuo pipefail

readonly APP_ROOT="${SPYBOXD_APP_ROOT:-/opt/spyboxd}"
readonly REPOSITORY_DIR="${SPYBOXD_REPOSITORY_DIR:-${APP_ROOT}/repository}"
readonly RELEASES_DIR="${SPYBOXD_RELEASES_DIR:-${APP_ROOT}/releases}"
readonly SHARED_DIR="${SPYBOXD_SHARED_DIR:-${APP_ROOT}/shared}"
readonly RELEASE_STATE_DIR="${SPYBOXD_RELEASE_STATE_DIR:-${SHARED_DIR}/release-state}"
readonly CURRENT_LINK="${SPYBOXD_CURRENT_LINK:-${APP_ROOT}/current}"
readonly DEPLOY_REF="${SPYBOXD_DEPLOY_REF:-refs/remotes/origin/main}"
readonly SERVICES=(spyboxd-api.service spyboxd-rss.service spyboxd-frontend.service)

TEMPORARY_LINK=""

log() {
    printf '[spyboxd-reconcile] %s\n' "$*"
}

fail() {
    printf '[spyboxd-reconcile] ERROR: %s\n' "$*" >&2
    exit 1
}

cleanup() {
    local exit_status=$?
    trap - EXIT
    if [[ -n "${TEMPORARY_LINK}" && -L "${TEMPORARY_LINK}" ]]; then
        rm -f -- "${TEMPORARY_LINK}"
    fi
    exit "${exit_status}"
}
trap cleanup EXIT

usage() {
    printf 'Usage: %s <release-sha> <previous-sha|none> false\n' "$0" >&2
    exit 64
}

[[ $# -eq 3 ]] || usage
readonly RELEASE_SHA="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
readonly PREVIOUS_TARGET="$(printf '%s' "$2" | tr '[:upper:]' '[:lower:]')"
readonly CLERK_BRIDGE_MODE="$3"
readonly EXPECTED_RELEASE="${RELEASES_DIR}/${RELEASE_SHA}"

[[ "${RELEASE_SHA}" =~ ^[0-9a-f]{40}$ ]] || usage
if [[ "${PREVIOUS_TARGET}" != none ]]; then
    [[ "${PREVIOUS_TARGET}" =~ ^[0-9a-f]{40}$ ]] || usage
fi
[[ "${CLERK_BRIDGE_MODE}" == false ]] || usage

for command_name in basename chmod curl flock git id ln mv python3 readlink rm seq sleep stat sudo timeout touch tr; do
    command -v "${command_name}" >/dev/null 2>&1 \
        || fail "required recovery command is missing: ${command_name}"
done

exec 9>"${APP_ROOT}/.release.lock"
flock -w 180 9 || fail "the interrupted release did not relinquish the deployment lock"

validate_state_dir() {
    [[ -d "${RELEASE_STATE_DIR}" && ! -L "${RELEASE_STATE_DIR}" ]] \
        || fail "trusted release state is unavailable"
    [[ "$(stat -c '%u' "${RELEASE_STATE_DIR}")" == "$(id -u)" ]] \
        && [[ "$(stat -c '%a' "${RELEASE_STATE_DIR}")" == 750 ]] \
        || fail "trusted release state has unsafe ownership or permissions"
}

read_state_revision() {
    local marker_path revision
    marker_path="${RELEASE_STATE_DIR}/$1"
    [[ -f "${marker_path}" && ! -L "${marker_path}" ]] || return 1
    revision="$(<"${marker_path}")"
    [[ "${revision}" =~ ^[0-9a-f]{40}$ ]] || return 1
    printf '%s\n' "${revision}"
}

write_state_revision() {
    local name="$1" revision="$2" temporary
    [[ "${name}" == active || "${name}" == previous ]] \
        || fail "invalid release-state marker name"
    [[ "${revision}" =~ ^[0-9a-f]{40}$ ]] \
        || fail "invalid release-state revision"
    temporary="${RELEASE_STATE_DIR}/.${name}.$$"
    printf '%s\n' "${revision}" >"${temporary}"
    chmod 0640 "${temporary}"
    mv -f -- "${temporary}" "${RELEASE_STATE_DIR}/${name}"
}

clear_state_marker() {
    local marker_path
    marker_path="${RELEASE_STATE_DIR}/$1"
    if [[ -e "${marker_path}" || -L "${marker_path}" ]]; then
        [[ -f "${marker_path}" && ! -L "${marker_path}" ]] \
            || fail "refusing to remove an unsafe release-state marker"
        rm -f -- "${marker_path}"
    fi
}

active_target=""
if [[ -e "${CURRENT_LINK}" || -L "${CURRENT_LINK}" ]]; then
    [[ -L "${CURRENT_LINK}" ]] || fail "current release path is not a symlink"
    active_target="$(readlink -f "${CURRENT_LINK}" || true)"
    [[ -n "${active_target}" ]] || fail "current release symlink cannot be resolved"
fi

stop_services() {
    timeout --signal=TERM --kill-after=15s 4m \
        sudo -n systemctl stop "${SERVICES[@]}"
}

restart_services() {
    timeout --signal=TERM --kill-after=15s 4m \
        sudo -n systemctl restart "${SERVICES[@]}"
}

activate_release() {
    local release_path="$1"
    TEMPORARY_LINK="${APP_ROOT}/.current-reconcile.$$"
    [[ ! -e "${TEMPORARY_LINK}" && ! -L "${TEMPORARY_LINK}" ]] \
        || fail "temporary activation path already exists"
    ln -s "${release_path}" "${TEMPORARY_LINK}"
    mv -Tf -- "${TEMPORARY_LINK}" "${CURRENT_LINK}"
    TEMPORARY_LINK=""
    [[ "$(readlink -f "${CURRENT_LINK}" || true)" == "${release_path}" ]] \
        || fail "reconciled activation did not resolve to the expected release"
}

validate_runtime_release() {
    local release_path="$1" revision="$2" require_runtime="$3"
    [[ -d "${release_path}" && ! -L "${release_path}" ]] \
        || fail "recovery release is unavailable: ${revision}"
    [[ -f "${release_path}/REVISION" && ! -L "${release_path}/REVISION" ]] \
        && [[ "$(<"${release_path}/REVISION")" == "${revision}" ]] \
        || fail "recovery release has an invalid revision marker: ${revision}"
    [[ -f "${release_path}/.revision-health-v1" \
        && ! -L "${release_path}/.revision-health-v1" ]] \
        || fail "recovery release predates strict readiness: ${revision}"
    [[ -x "${release_path}/.venv/bin/uvicorn" ]] \
        && [[ -f "${release_path}/frontend/.next/BUILD_ID" ]] \
        && [[ -f "${release_path}/frontend/node_modules/next/dist/bin/next" ]] \
        || fail "recovery release is incomplete: ${revision}"
    if [[ "${require_runtime}" == true ]]; then
        [[ -x "${release_path}/frontend/.runtime/node" \
            && ! -L "${release_path}/frontend/.runtime/node" ]] \
            && [[ -f "${release_path}/frontend/.runtime/LICENSE.nodejs" \
                && ! -L "${release_path}/frontend/.runtime/LICENSE.nodejs" ]] \
            || fail "attempted release is missing its bundled Node runtime"
    fi
}

if [[ "${PREVIOUS_TARGET}" == none ]]; then
    case "${active_target}" in
        ""|"${EXPECTED_RELEASE}") ;;
        *) fail "first-release recovery found an unexpected active target" ;;
    esac
    if [[ -e "${RELEASE_STATE_DIR}" || -L "${RELEASE_STATE_DIR}" ]]; then
        validate_state_dir
        if [[ -e "${RELEASE_STATE_DIR}/active" || -L "${RELEASE_STATE_DIR}/active" ]]; then
            [[ "$(read_state_revision active)" == "${RELEASE_SHA}" ]] \
                || fail "first-release recovery found an unexpected active state marker"
        fi
        [[ ! -e "${RELEASE_STATE_DIR}/previous" \
            && ! -L "${RELEASE_STATE_DIR}/previous" ]] \
            || fail "first-release recovery found an impossible previous state marker"
    fi
    stop_services || fail "failed to stop services during first-release recovery"
    rm -f -- "${CURRENT_LINK}"
    if [[ -e "${RELEASE_STATE_DIR}" || -L "${RELEASE_STATE_DIR}" ]]; then
        validate_state_dir
        clear_state_marker active
        clear_state_marker previous
    fi
    log "Stopped the first failed activation because no prior release existed."
    exit 0
fi

readonly PREVIOUS_RELEASE="${RELEASES_DIR}/${PREVIOUS_TARGET}"
case "${active_target}" in
    ""|"${EXPECTED_RELEASE}"|"${PREVIOUS_RELEASE}") ;;
    *) fail "revision recovery found an unexpected active target" ;;
esac

validate_state_dir
active_marker="$(read_state_revision active)" \
    || fail "the active release-state marker is invalid"
if [[ "${active_marker}" != "${PREVIOUS_TARGET}" \
    && "${active_marker}" != "${RELEASE_SHA}" ]]; then
    fail "release-state marker does not identify either recovery revision"
fi

previous_marker=""
if [[ -e "${RELEASE_STATE_DIR}/previous" \
    || -L "${RELEASE_STATE_DIR}/previous" ]]; then
    previous_marker="$(read_state_revision previous)" \
        || fail "the previous release-state marker is invalid"
fi
if [[ "${active_marker}" == "${RELEASE_SHA}" ]]; then
    [[ "${previous_marker}" == "${PREVIOUS_TARGET}" ]] \
        || fail "the successful activation has no trustworthy previous marker"
elif [[ -n "${previous_marker}" \
    && "${previous_marker}" != "${PREVIOUS_TARGET}" \
    && "${previous_marker}" != "${RELEASE_SHA}" ]]; then
    fail "the previous release-state marker does not identify a recovery revision"
fi

validate_runtime_release "${PREVIOUS_RELEASE}" "${PREVIOUS_TARGET}" false
if [[ "${active_marker}" == "${RELEASE_SHA}" ]]; then
    validate_runtime_release "${EXPECTED_RELEASE}" "${RELEASE_SHA}" true
fi

if git --git-dir="${REPOSITORY_DIR}" rev-parse --is-bare-repository >/dev/null 2>&1; then
    repository_git() {
        git --git-dir="${REPOSITORY_DIR}" "$@"
    }
    repository_fetch() {
        timeout --signal=TERM --kill-after=15s 2m \
            git --git-dir="${REPOSITORY_DIR}" fetch "$@"
    }
elif git -C "${APP_ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    repository_git() {
        git -C "${APP_ROOT}" "$@"
    }
    repository_fetch() {
        timeout --signal=TERM --kill-after=15s 2m \
            git -C "${APP_ROOT}" fetch "$@"
    }
else
    fail "no trusted repository is available for reconciliation"
fi

repository_fetch --quiet --force --prune origin \
    '+refs/heads/main:refs/remotes/origin/main'
[[ "$(repository_git rev-parse --verify "${RELEASE_SHA}^{commit}")" == "${RELEASE_SHA}" ]] \
    || fail "attempted release is not a known repository commit"
repository_git merge-base --is-ancestor "${RELEASE_SHA}" "${DEPLOY_REF}" \
    || fail "attempted release is not reachable from the deployment ref"
[[ "$(repository_git rev-parse --verify "${PREVIOUS_TARGET}^{commit}")" == "${PREVIOUS_TARGET}" ]] \
    || fail "previous release is not a known repository commit"
repository_git merge-base --is-ancestor "${PREVIOUS_TARGET}" "${DEPLOY_REF}" \
    || fail "previous release is not reachable from the deployment ref"

health_validator="${SPYBOXD_HEALTH_VALIDATOR:-}"
if [[ -z "${health_validator}" ]]; then
    if [[ -f "${PREVIOUS_RELEASE}/deploy/check-runtime-health.py" \
        && ! -L "${PREVIOUS_RELEASE}/deploy/check-runtime-health.py" ]]; then
        health_validator="${PREVIOUS_RELEASE}/deploy/check-runtime-health.py"
    elif [[ -f "${EXPECTED_RELEASE}/deploy/check-runtime-health.py" \
        && ! -L "${EXPECTED_RELEASE}/deploy/check-runtime-health.py" ]]; then
        health_validator="${EXPECTED_RELEASE}/deploy/check-runtime-health.py"
    fi
fi
[[ -n "${health_validator}" && -f "${health_validator}" \
    && ! -L "${health_validator}" ]] \
    || fail "trusted runtime health validator is unavailable"
readonly health_validator

wait_for_http() {
    local name="$1" url="$2" expected_status="${3:-}" expected_revision="${4:-}" response attempt
    for attempt in $(seq 1 12); do
        if response="$(curl --silent --show-error --fail --max-time 5 "${url}" 2>/dev/null)"; then
            if [[ -z "${expected_status}" && -z "${expected_revision}" ]] \
                || python3 -c '
import json
import sys

expected_status, expected_revision = sys.argv[1:]
try:
    payload = json.load(sys.stdin)
except (TypeError, ValueError):
    raise SystemExit(1)
if expected_status and payload.get("status") != expected_status:
    raise SystemExit(1)
if expected_revision and payload.get("revision") != expected_revision:
    raise SystemExit(1)
' "${expected_status}" "${expected_revision}" <<<"${response}"; then
                log "${name} is ready"
                return 0
            fi
        fi
        sleep 2
    done
    return 1
}

wait_for_validated_json() {
    local name="$1" url="$2" kind="$3" expected_revision="${4:-}" response attempt
    local -a validator_args=("${kind}")
    if [[ -n "${expected_revision}" ]]; then
        validator_args+=(--revision "${expected_revision}")
    fi
    for attempt in $(seq 1 12); do
        if response="$(curl --silent --show-error --fail --max-time 5 "${url}" 2>/dev/null)" \
            && printf '%s' "${response}" \
                | python3 "${health_validator}" "${validator_args[@]}" >/dev/null; then
            log "${name} is ready"
            return 0
        fi
        sleep 2
    done
    return 1
}

check_release_readiness() {
    local revision="$1"
    wait_for_validated_json "reconciled API revision ${revision}" \
        "http://127.0.0.1:8000/ready" ready "${revision}" \
        && wait_for_validated_json "reconciled database-backed dashboard" \
            "http://127.0.0.1:8000/api/public/dashboard" dashboard \
        && wait_for_http "reconciled frontend" "http://127.0.0.1:3000/sign-in" \
        && wait_for_validated_json "public reconciled API revision ${revision}" \
            "https://api.spyboxd.com/ready" ready "${revision}" \
        && wait_for_validated_json "public reconciled database-backed dashboard" \
            "https://api.spyboxd.com/api/public/dashboard" dashboard \
        && wait_for_http "public reconciled frontend" "https://spyboxd.com/sign-in"
}

check_release_compatibility() {
    local revision="$1"
    wait_for_http "rollback-compatible API revision ${revision}" \
        "http://127.0.0.1:8000/health" ok "${revision}" \
        && wait_for_validated_json "rollback-compatible database-backed dashboard" \
            "http://127.0.0.1:8000/api/public/dashboard" dashboard \
        && wait_for_http "rollback-compatible frontend" "http://127.0.0.1:3000/sign-in" \
        && wait_for_http "public rollback-compatible API revision ${revision}" \
            "https://api.spyboxd.com/health" ok "${revision}" \
        && wait_for_validated_json "public rollback-compatible database-backed dashboard" \
            "https://api.spyboxd.com/api/public/dashboard" dashboard \
        && wait_for_http "public rollback-compatible frontend" "https://spyboxd.com/sign-in"
}

if [[ "${PREVIOUS_TARGET}" == "${RELEASE_SHA}" ]]; then
    [[ "${active_target}" == "${EXPECTED_RELEASE}" \
        && "${active_marker}" == "${RELEASE_SHA}" ]] \
        || fail "repeated-release recovery found inconsistent active state"
    check_release_readiness "${RELEASE_SHA}" \
        || fail "repeated release is not ready"
    log "The requested release was already active and healthy."
    exit 0
fi

activate_release "${PREVIOUS_RELEASE}"
previous_restarted=true
restart_services || previous_restarted=false

if [[ "${previous_restarted}" == true ]] \
    && check_release_compatibility "${PREVIOUS_TARGET}"; then
    touch "${PREVIOUS_RELEASE}/.activated-at"
    if [[ "${active_marker}" == "${RELEASE_SHA}" ]]; then
        write_state_revision previous "${RELEASE_SHA}"
        write_state_revision active "${PREVIOUS_TARGET}"
    elif [[ "${previous_marker}" == "${PREVIOUS_TARGET}" ]]; then
        clear_state_marker previous
    fi
    [[ "$(read_state_revision active)" == "${PREVIOUS_TARGET}" ]] \
        || fail "reconciled release state does not identify the previous release"
    log "Restored healthy previous release ${PREVIOUS_TARGET} after interrupted activation."
    exit 0
fi

if [[ "${active_marker}" == "${RELEASE_SHA}" ]]; then
    activate_release "${EXPECTED_RELEASE}"
    if restart_services && check_release_readiness "${RELEASE_SHA}"; then
        log "Previous-release recovery failed; restored the healthy attempted release."
    else
        log "Previous-release recovery and attempted-release restoration are unhealthy."
    fi
fi
fail "the directly restored previous release did not become healthy"
