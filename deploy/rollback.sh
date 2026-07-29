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

ACTIVATION_LINK=""

log() {
    printf '[spyboxd-rollback] %s\n' "$*"
}

fail() {
    printf '[spyboxd-rollback] ERROR: %s\n' "$*" >&2
    exit 1
}

cleanup() {
    local exit_status=$?
    trap - EXIT
    if [[ -n "${ACTIVATION_LINK}" && -L "${ACTIVATION_LINK}" ]]; then
        rm -f -- "${ACTIVATION_LINK}"
    fi
    exit "${exit_status}"
}
trap cleanup EXIT

usage() {
    printf 'Usage: %s <full-40-character-git-sha|previous>\n' "$0" >&2
    exit 64
}

[[ $# -eq 1 ]] || usage
requested_target="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"

for command_name in git python3 curl readlink flock stat sudo seq basename; do
    command -v "${command_name}" >/dev/null 2>&1 \
        || fail "required command is missing: ${command_name}"
done

[[ -d "${RELEASE_STATE_DIR}" && ! -L "${RELEASE_STATE_DIR}" ]] \
    || fail "trusted release state is unavailable at ${RELEASE_STATE_DIR}"
state_mode="$(stat -c '%a' "${RELEASE_STATE_DIR}")"
state_owner="$(stat -c '%u' "${RELEASE_STATE_DIR}")"
[[ "${state_owner}" == "$(id -u)" && "${state_mode}" == 750 ]] \
    || fail "release state must be owned by the deploy account and mode 0750"

read_state_revision() {
    local name="$1" marker revision
    marker="${RELEASE_STATE_DIR}/${name}"
    [[ -f "${marker}" && ! -L "${marker}" ]] || fail "release state marker '${name}' is unavailable"
    revision="$(<"${marker}")"
    [[ "${revision}" =~ ^[0-9a-f]{40}$ ]] || fail "release state marker '${name}' is invalid"
    printf '%s\n' "${revision}"
}

if [[ "${requested_target}" == "previous" || "${requested_target}" == "--previous" ]]; then
    target_revision="$(read_state_revision previous)"
else
    target_revision="${requested_target}"
fi
[[ "${target_revision}" =~ ^[0-9a-f]{40}$ ]] \
    || fail "rollback target must be 'previous' or a full 40-character Git SHA"

exec 9>"${APP_ROOT}/.release.lock"
flock -n 9 || fail "another Spyboxd release or rollback is already running"

[[ -L "${CURRENT_LINK}" ]] || fail "${CURRENT_LINK} is not an active release symlink"
current_release="$(readlink -f "${CURRENT_LINK}" || true)"
[[ -n "${current_release}" && "${current_release}" == "${RELEASES_DIR}/"* ]] \
    || fail "the active release is outside ${RELEASES_DIR}"
current_revision="$(basename "${current_release}")"
[[ "${current_revision}" =~ ^[0-9a-f]{40}$ ]] \
    || fail "the active release directory does not identify an exact revision"
[[ "$(read_state_revision active)" == "${current_revision}" ]] \
    || fail "trusted release state does not match the active symlink"

target_release="${RELEASES_DIR}/${target_revision}"
[[ "${target_revision}" != "${current_revision}" ]] || fail "target is already active"
[[ -d "${target_release}" && ! -L "${target_release}" ]] \
    || fail "rollback target is not a retained release: ${target_revision}"
[[ -f "${target_release}/REVISION" ]] \
    && [[ "$(<"${target_release}/REVISION")" == "${target_revision}" ]] \
    || fail "rollback target has an invalid revision marker"
if [[ ! -f "${target_release}/.revision-health-v1" ]]; then
    [[ "$(read_state_revision previous)" == "${target_revision}" ]] \
        || fail "only the trusted previous release may use transitional legacy health verification"
fi
[[ -x "${target_release}/.venv/bin/uvicorn" ]] \
    && [[ -f "${target_release}/frontend/.next/BUILD_ID" ]] \
    && [[ -f "${target_release}/frontend/node_modules/next/dist/bin/next" ]] \
    || fail "rollback target is incomplete"
[[ -f "${current_release}/.revision-health-v1" ]] \
    || fail "the active release cannot be safely restored if rollback health verification fails"

[[ -d "${REPOSITORY_DIR}" ]] \
    && git --git-dir="${REPOSITORY_DIR}" rev-parse --is-bare-repository >/dev/null 2>&1 \
    || fail "the trusted bare release repository is unavailable"
resolved_revision="$(git --git-dir="${REPOSITORY_DIR}" rev-parse --verify "${target_revision}^{commit}" 2>/dev/null || true)"
[[ "${resolved_revision}" == "${target_revision}" ]] \
    || fail "rollback target is not a known repository commit"
git --git-dir="${REPOSITORY_DIR}" show-ref --verify --quiet "${DEPLOY_REF}" \
    || fail "trusted deployment ref ${DEPLOY_REF} is unavailable"
git --git-dir="${REPOSITORY_DIR}" merge-base --is-ancestor "${target_revision}" "${DEPLOY_REF}" \
    || fail "rollback target is not reachable from ${DEPLOY_REF}"

activate_release() {
    local release_path="$1"
    ACTIVATION_LINK="${APP_ROOT}/.current.rollback.$$"
    ln -s "${release_path}" "${ACTIVATION_LINK}"
    mv -Tf -- "${ACTIVATION_LINK}" "${CURRENT_LINK}"
    ACTIVATION_LINK=""
    [[ "$(readlink -f "${CURRENT_LINK}" || true)" == "${release_path}" ]] \
        || fail "activation symlink did not resolve to ${release_path}"
}

restart_services() {
    sudo -n systemctl restart "${SERVICES[@]}"
}

wait_for_http() {
    local name="$1" url="$2" expected_status="${3:-}" expected_revision="${4:-}" response attempt
    for attempt in $(seq 1 30); do
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

check_release() {
    local revision="$1" label="$2" release_path="$3"
    if [[ -f "${release_path}/.revision-health-v1" ]]; then
        wait_for_http "${label} API revision ${revision}" "http://127.0.0.1:8000/health" ok "${revision}" \
            && wait_for_http "${label} frontend" "http://127.0.0.1:3000/" \
            && wait_for_http "${label} public API revision ${revision}" "https://api.spyboxd.com/health" ok "${revision}" \
            && wait_for_http "${label} public frontend" "https://spyboxd.com/"
        return
    fi

    log "${label} release predates revision-aware health; verifying its exact symlink target and liveness"
    wait_for_http "${label} API" "http://127.0.0.1:8000/health" ok \
        && wait_for_http "${label} frontend" "http://127.0.0.1:3000/" \
        && wait_for_http "${label} public API" "https://api.spyboxd.com/health" ok \
        && wait_for_http "${label} public frontend" "https://spyboxd.com/"
}

write_release_state() {
    local name="$1" revision="$2" temporary
    [[ "${name}" == "active" || "${name}" == "previous" ]] || fail "invalid release state marker"
    [[ "${revision}" =~ ^[0-9a-f]{40}$ ]] || fail "invalid state revision"
    temporary="${RELEASE_STATE_DIR}/.${name}.$$"
    printf '%s\n' "${revision}" >"${temporary}"
    chmod 0640 "${temporary}"
    mv -f -- "${temporary}" "${RELEASE_STATE_DIR}/${name}"
}

log "Rolling back ${current_revision} to retained release ${target_revision}"
log "Database migrations will not be downgraded"
activate_release "${target_release}"

if restart_services && check_release "${target_revision}" "rolled-back" "${target_release}"; then
    touch "${target_release}/.activated-at"
    write_release_state previous "${current_revision}"
    write_release_state active "${target_revision}"
    log "Rollback to ${target_revision} is active and healthy"
    exit 0
fi

log "Rollback health verification failed; restoring ${current_revision}"
activate_release "${current_release}"
restart_services || true
if check_release "${current_revision}" "restored" "${current_release}"; then
    log "Original release ${current_revision} was restored successfully"
else
    log "WARNING: original release health could not be verified; inspect systemd logs immediately" >&2
fi
exit 1
