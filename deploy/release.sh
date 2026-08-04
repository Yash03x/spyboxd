#!/usr/bin/env bash
set -Eeuo pipefail

readonly APP_ROOT="${SPYBOXD_APP_ROOT:-/opt/spyboxd}"
readonly REPOSITORY_DIR="${SPYBOXD_REPOSITORY_DIR:-${APP_ROOT}/repository}"
readonly RELEASES_DIR="${SPYBOXD_RELEASES_DIR:-${APP_ROOT}/releases}"
readonly SHARED_DIR="${SPYBOXD_SHARED_DIR:-${APP_ROOT}/shared}"
readonly RELEASE_STATE_DIR="${SPYBOXD_RELEASE_STATE_DIR:-${SHARED_DIR}/release-state}"
readonly CURRENT_LINK="${SPYBOXD_CURRENT_LINK:-${APP_ROOT}/current}"
readonly API_ENV_FILE="${SPYBOXD_API_ENV_FILE:-/etc/spyboxd/api.env}"
readonly FRONTEND_ENV_FILE="${SPYBOXD_FRONTEND_ENV_FILE:-/etc/spyboxd/frontend.env}"
readonly RSS_ENV_FILE="${SPYBOXD_RSS_ENV_FILE:-/etc/spyboxd/rss.env}"
readonly FRONTEND_RUNTIME_PROOF_FILE="/var/cache/spyboxd-frontend/runtime-proof.json"
readonly DEPLOY_REF="${SPYBOXD_DEPLOY_REF:-refs/remotes/origin/main}"
readonly RUNTIME_USER="${SPYBOXD_RUNTIME_USER:-spyboxd}"
readonly RELEASE_RETENTION="${SPYBOXD_RELEASE_RETENTION:-5}"
readonly CLERK_BRIDGE_EDGE="${SPYBOXD_CLERK_BRIDGE_EDGE:-}"
readonly RELEASE_MANIFEST_NAME=".spyboxd-release-manifest.json"
readonly MAX_BUNDLE_MEMBERS="${SPYBOXD_MAX_BUNDLE_MEMBERS:-150000}"
readonly MAX_BUNDLE_UNCOMPRESSED_BYTES="${SPYBOXD_MAX_BUNDLE_UNCOMPRESSED_BYTES:-4294967296}"
readonly SERVICES=(spyboxd-api.service spyboxd-rss.service spyboxd-frontend.service)
SOURCE_NPM_CLI=""

TEMP_RELEASE=""
ACTIVATION_LINK=""
TEMP_REPOSITORY=""
TEMP_BUNDLE_DIR=""

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
    if [[ -n "${TEMP_BUNDLE_DIR}" && -d "${TEMP_BUNDLE_DIR}" ]]; then
        rm -rf -- "${TEMP_BUNDLE_DIR}"
    fi
    exit "${exit_status}"
}
trap cleanup EXIT

usage() {
    printf 'Usage: %s <full-40-character-git-sha> [verified-release-bundle]\n' "$0" >&2
    exit 64
}

[[ $# -ge 1 && $# -le 2 ]] || usage
readonly RELEASE_SHA="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
readonly RELEASE_BUNDLE="${2:-}"
[[ "${RELEASE_SHA}" =~ ^[0-9a-f]{40}$ ]] || fail "release must be a full 40-character lowercase or uppercase Git SHA"

bridge_from_revision=""
bridge_to_revision=""
if [[ -n "${CLERK_BRIDGE_EDGE}" ]]; then
    if [[ ! "${CLERK_BRIDGE_EDGE}" =~ ^([0-9a-f]{40}):([0-9a-f]{40})$ ]]; then
        fail "SPYBOXD_CLERK_BRIDGE_EDGE must be two lowercase full Git SHAs separated by one colon"
    fi
    bridge_from_revision="${BASH_REMATCH[1]}"
    bridge_to_revision="${BASH_REMATCH[2]}"
    [[ "${bridge_to_revision}" == "${RELEASE_SHA}" ]] \
        || fail "SPYBOXD_CLERK_BRIDGE_EDGE does not authorize this release SHA"
    [[ "${bridge_from_revision}" != "${bridge_to_revision}" ]] \
        || fail "SPYBOXD_CLERK_BRIDGE_EDGE must identify a real source-to-target transition"
fi

for command_name in git tar python3 curl readlink basename flock stat sudo seq getent grep ufw find sort touch sha256sum mktemp timeout uname; do
    command -v "${command_name}" >/dev/null 2>&1 || fail "required command is missing: ${command_name}"
done
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] \
    || fail "production releases require the verified Linux x86_64 runtime target"
if [[ -z "${RELEASE_BUNDLE}" ]]; then
    command -v npm >/dev/null 2>&1 \
        || fail "source-based release requires the npm CLI"
    SOURCE_NPM_CLI="$(readlink -f "$(command -v npm)")"
    [[ -f "${SOURCE_NPM_CLI}" && ! -L "${SOURCE_NPM_CLI}" ]] \
        || fail "source-based release could not resolve a regular npm CLI entrypoint"
fi

if [[ -n "${RELEASE_BUNDLE}" ]]; then
    expected_bundle_name="spyboxd-release-${RELEASE_SHA}.tar.gz"
    bundle_name="${RELEASE_BUNDLE##*/}"
    bundle_checksum="${RELEASE_BUNDLE}.sha256"
    [[ "${bundle_name}" == "${expected_bundle_name}" ]] \
        || fail "release bundle name does not match ${RELEASE_SHA}"
    [[ -f "${RELEASE_BUNDLE}" && ! -L "${RELEASE_BUNDLE}" ]] \
        || fail "release bundle is missing or is not a regular file: ${RELEASE_BUNDLE}"
    [[ -f "${bundle_checksum}" && ! -L "${bundle_checksum}" ]] \
        || fail "release bundle checksum is missing or is not a regular file"
    [[ "$(stat -c '%s' "${bundle_checksum}")" -le 256 ]] \
        || fail "release bundle checksum file is unexpectedly large"
    mapfile -t checksum_lines <"${bundle_checksum}"
    [[ "${#checksum_lines[@]}" -eq 1 ]] \
        || fail "release bundle checksum must contain exactly one line"
    read -r expected_bundle_digest checksum_bundle_name checksum_extra <<<"${checksum_lines[0]}"
    [[ "${expected_bundle_digest}" =~ ^[0-9a-f]{64}$ ]] \
        || fail "release bundle checksum is invalid"
    [[ "${checksum_bundle_name}" == "${expected_bundle_name}" && -z "${checksum_extra:-}" ]] \
        || fail "release bundle checksum names an unexpected file"
    actual_bundle_digest="$(sha256sum "${RELEASE_BUNDLE}")"
    actual_bundle_digest="${actual_bundle_digest%% *}"
    [[ "${actual_bundle_digest}" == "${expected_bundle_digest}" ]] \
        || fail "release bundle checksum verification failed"
fi

[[ "${RELEASE_RETENTION}" =~ ^[3-5]$ ]] \
    || fail "SPYBOXD_RELEASE_RETENTION must be an integer from 3 through 5"
[[ "${MAX_BUNDLE_MEMBERS}" =~ ^[1-9][0-9]*$ ]] \
    && (( MAX_BUNDLE_MEMBERS <= 500000 )) \
    || fail "SPYBOXD_MAX_BUNDLE_MEMBERS must be a positive integer no greater than 500000"
[[ "${MAX_BUNDLE_UNCOMPRESSED_BYTES}" =~ ^[1-9][0-9]*$ ]] \
    && (( MAX_BUNDLE_UNCOMPRESSED_BYTES <= 8589934592 )) \
    || fail "SPYBOXD_MAX_BUNDLE_UNCOMPRESSED_BYTES must be a positive integer no greater than 8 GiB"

python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 12))' \
    || fail "Python 3.12 or newer is required"
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
if [[ "${frontend_exec_start}" == *"frontend/.runtime/node"* ]]; then
    [[ "${frontend_exec_start}" == *"--require /opt/spyboxd/current/frontend/scripts/runtime-proof.cjs"* ]] \
        || fail "the direct frontend unit must preload the bundled runtime proof"
    log "The installed frontend unit directly launches the release-bundled Node runtime"
elif [[ "${frontend_exec_start}" == *"/usr/bin/npm run start -- --hostname localhost --port 3000"* ]]; then
    log "WARNING: the installed frontend unit uses the bounded npm transition; the activated process must still resolve to the release-bundled Node runtime"
else
    fail "spyboxd-frontend.service has an unsupported production launcher"
fi
frontend_environment="$(
    sudo -n systemctl show spyboxd-frontend.service --property=Environment --value 2>/dev/null \
        || true
)"
if [[ "${frontend_environment}" != *"NODE_OPTIONS=--dns-result-order=ipv4first"* ]]; then
    fail "spyboxd-frontend.service must prefer IPv4 localhost for Clerk/Next proxy compatibility"
fi
if [[ "${frontend_exec_start}" == *"frontend/.runtime/node"* ]] \
    && [[ "${frontend_environment}" != *"SPYBOXD_RUNTIME_PROOF_FILE=${FRONTEND_RUNTIME_PROOF_FILE}"* ]]; then
    fail "the direct frontend unit must write its proof inside the private systemd cache"
fi
if grep -Eq '(^|[[:space:]])SPYBOXD_E2E_AUTH_BYPASS=([^[:space:]]+)' \
    <<<"${frontend_environment}"; then
    fail "spyboxd-frontend.service must not enable the browser-test auth bypass"
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
if [[ -e "${RELEASE_STATE_DIR}" && ( ! -d "${RELEASE_STATE_DIR}" || -L "${RELEASE_STATE_DIR}" ) ]]; then
    fail "${RELEASE_STATE_DIR} must be a real directory, not a file or symlink"
fi
if [[ ! -d "${RELEASE_STATE_DIR}" ]]; then
    mkdir -m 0750 -- "${RELEASE_STATE_DIR}"
    chgrp "${RUNTIME_USER}" "${RELEASE_STATE_DIR}"
fi
state_identity="$(stat -c '%u:%g:%a' "${RELEASE_STATE_DIR}")"
if [[ "${state_identity}" != "$(id -u):${runtime_gid}:750" ]]; then
    fail "${RELEASE_STATE_DIR} must be owned by the deploy account, grouped to ${RUNTIME_USER}, and mode 0750"
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
    timeout --signal=TERM --kill-after=15s 2m \
        git --git-dir="${repository_tmp}" fetch --quiet --prune --tags origin
    mv -- "${repository_tmp}" "${REPOSITORY_DIR}"
    TEMP_REPOSITORY=""
}

if [[ ! -d "${REPOSITORY_DIR}" ]] || ! git --git-dir="${REPOSITORY_DIR}" rev-parse --is-bare-repository >/dev/null 2>&1; then
    initialize_repository
fi

refresh_and_require_deploy_tip() {
    local resolved_sha deploy_tip

    log "Fetching origin and requiring ${RELEASE_SHA} at ${DEPLOY_REF}"
    timeout --signal=TERM --kill-after=15s 2m \
        git --git-dir="${REPOSITORY_DIR}" fetch \
            --quiet --force --prune --tags origin '+refs/heads/*:refs/remotes/origin/*'
    resolved_sha="$(git --git-dir="${REPOSITORY_DIR}" rev-parse --verify "${RELEASE_SHA}^{commit}" 2>/dev/null || true)"
    [[ "${resolved_sha}" == "${RELEASE_SHA}" ]] \
        || fail "${RELEASE_SHA} is not an available commit from origin"
    deploy_tip="$(git --git-dir="${REPOSITORY_DIR}" rev-parse --verify "${DEPLOY_REF}^{commit}" 2>/dev/null || true)"
    [[ -n "${deploy_tip}" ]] \
        || fail "deployment ref ${DEPLOY_REF} does not exist after fetch"
    if [[ "${deploy_tip}" != "${RELEASE_SHA}" ]]; then
        # Being superseded mid-flight is a yield, not a failure: nothing that
        # ran so far mutated the active release (migrations are additive-only
        # when the pre-activation recheck fires), and the newer deploy owns
        # production from here. Exit 75 so the workflow records a clean skip.
        log "deployment ref ${DEPLOY_REF} is now ${deploy_tip}; yielding superseded release ${RELEASE_SHA} to the newer deploy" >&2
        exit 75
    fi
}

refresh_and_require_deploy_tip

readonly FINAL_RELEASE="${RELEASES_DIR}/${RELEASE_SHA}"
release_is_complete=false
if [[ -d "${FINAL_RELEASE}" ]]; then
    if [[ -f "${FINAL_RELEASE}/REVISION" ]] \
        && [[ "$(<"${FINAL_RELEASE}/REVISION")" == "${RELEASE_SHA}" ]] \
        && [[ -f "${FINAL_RELEASE}/.revision-health-v1" ]] \
        && [[ -x "${FINAL_RELEASE}/.venv/bin/uvicorn" ]] \
        && [[ -f "${FINAL_RELEASE}/frontend/.next/BUILD_ID" ]] \
        && [[ -f "${FINAL_RELEASE}/frontend/node_modules/next/dist/bin/next" ]] \
        && [[ -x "${FINAL_RELEASE}/frontend/.runtime/node" ]] \
        && [[ ! -L "${FINAL_RELEASE}/frontend/.runtime/node" ]] \
        && [[ -f "${FINAL_RELEASE}/frontend/.runtime/LICENSE.nodejs" ]] \
        && [[ ! -L "${FINAL_RELEASE}/frontend/.runtime/LICENSE.nodejs" ]] \
        && [[ -f "${FINAL_RELEASE}/${RELEASE_MANIFEST_NAME}" ]] \
        && [[ ! -L "${FINAL_RELEASE}/${RELEASE_MANIFEST_NAME}" ]] \
        && [[ -f "${FINAL_RELEASE}/deploy/check-runtime-health.py" ]] \
        && [[ ! -L "${FINAL_RELEASE}/deploy/check-runtime-health.py" ]] \
        && [[ -f "${FINAL_RELEASE}/deploy/check-frontend-runtime.py" ]] \
        && [[ ! -L "${FINAL_RELEASE}/deploy/check-frontend-runtime.py" ]] \
        && [[ -f "${FINAL_RELEASE}/frontend/scripts/runtime-proof.cjs" ]] \
        && [[ ! -L "${FINAL_RELEASE}/frontend/scripts/runtime-proof.cjs" ]]; then
        release_is_complete=true
        log "Reusing completed release ${FINAL_RELEASE}"
    else
        fail "${FINAL_RELEASE} already exists but is incomplete; inspect and remove only that exact directory before retrying"
    fi
fi

extract_release_bundle() {
    local bundle_path="$1" destination="$2" bundle_root

    bundle_root="$(mktemp -d "${RELEASES_DIR}/.bundle-${RELEASE_SHA}.XXXXXX")"
    TEMP_BUNDLE_DIR="${bundle_root}"
    python3 - \
        "${bundle_path}" \
        "${bundle_root}" \
        "${RELEASE_SHA}" \
        "${RELEASE_MANIFEST_NAME}" \
        "${MAX_BUNDLE_MEMBERS}" \
        "${MAX_BUNDLE_UNCOMPRESSED_BYTES}" <<'PY'
import json
from pathlib import Path, PurePosixPath
import sys
import tarfile

(
    bundle_path,
    destination,
    expected_revision,
    manifest_name,
    max_members_raw,
    max_uncompressed_bytes_raw,
) = sys.argv[1:]
destination_path = Path(destination)
max_members = int(max_members_raw)
max_uncompressed_bytes = int(max_uncompressed_bytes_raw)

with tarfile.open(bundle_path, mode="r:gz") as archive:
    members = archive.getmembers()
    if not members:
        raise SystemExit("release bundle is empty")
    if len(members) > max_members:
        raise SystemExit("release bundle contains too many members")
    total_uncompressed_bytes = sum(max(int(member.size), 0) for member in members)
    if total_uncompressed_bytes > max_uncompressed_bytes:
        raise SystemExit("release bundle exceeds the uncompressed size limit")
    seen_names = set()
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or not path.parts or path.parts[0] != "app" or ".." in path.parts:
            raise SystemExit(f"unsafe release bundle member: {member.name}")
        if member.name in seen_names:
            raise SystemExit(f"duplicate release bundle member: {member.name}")
        seen_names.add(member.name)

    revision_members = [member for member in members if member.name == "app/REVISION"]
    if len(revision_members) != 1 or not revision_members[0].isfile():
        raise SystemExit("release bundle must contain one regular revision marker")
    revision_member = revision_members[0]
    if revision_member.size > 128:
        raise SystemExit("release bundle revision marker is unexpectedly large")
    revision_file = archive.extractfile(revision_member)
    if revision_file is None:
        raise SystemExit("release bundle revision marker is unreadable")
    revision = revision_file.read().decode("ascii", errors="strict").strip().lower()
    if revision != expected_revision:
        raise SystemExit("release bundle revision does not match requested release")

    manifest_path = f"app/{manifest_name}"
    manifest_members = [member for member in members if member.name == manifest_path]
    if len(manifest_members) != 1 or not manifest_members[0].isfile():
        raise SystemExit("release bundle must contain one regular release manifest")
    manifest_member = manifest_members[0]
    if manifest_member.size > 65536:
        raise SystemExit("release bundle manifest is unexpectedly large")
    manifest_file = archive.extractfile(manifest_member)
    if manifest_file is None:
        raise SystemExit("release bundle manifest is unreadable")
    try:
        manifest = json.load(manifest_file)
    except (UnicodeError, ValueError) as exc:
        raise SystemExit("release bundle manifest is invalid") from exc
    if not isinstance(manifest, dict) or manifest.get("format_version") != 2:
        raise SystemExit("release bundle manifest format is unsupported")
    if manifest.get("revision") != expected_revision:
        raise SystemExit("release bundle manifest revision does not match requested release")
    archive.extractall(destination_path, filter="data")

app_path = destination_path / "app"
if not app_path.is_dir() or app_path.is_symlink():
    raise SystemExit("release bundle did not contain a regular app directory")
PY
    [[ ! -e "${destination}" ]] || fail "release destination appeared during bundle extraction"
    mv -- "${bundle_root}/app" "${destination}"
    rmdir -- "${bundle_root}"
    TEMP_BUNDLE_DIR=""
}

if [[ "${release_is_complete}" != true ]]; then
    # Build at the final versioned path because Python virtualenv entry-point
    # shebangs contain absolute paths and virtualenvs are not safely relocatable.
    # The current symlink is not touched until every build and migration passes.
    TEMP_RELEASE="${FINAL_RELEASE}"
    if [[ -n "${RELEASE_BUNDLE}" ]]; then
        log "Extracting verified immutable release bundle"
        extract_release_bundle "${RELEASE_BUNDLE}" "${TEMP_RELEASE}"
        chgrp "${RUNTIME_USER}" "${TEMP_RELEASE}"

        [[ -d "${TEMP_RELEASE}/.release-wheelhouse" && ! -L "${TEMP_RELEASE}/.release-wheelhouse" ]] \
            || fail "release bundle does not contain a trusted Python wheelhouse"
        log "Installing locked Python dependencies from the release bundle"
        python3 -m venv "${TEMP_RELEASE}/.venv"
        "${TEMP_RELEASE}/.venv/bin/python" -m pip install \
            --disable-pip-version-check \
            --quiet \
            --no-index \
            --find-links "${TEMP_RELEASE}/.release-wheelhouse" \
            --require-hashes \
            -r "${TEMP_RELEASE}/requirements.lock"
        rm -rf -- "${TEMP_RELEASE}/.release-wheelhouse"
    else
        mkdir -m 0750 -- "${TEMP_RELEASE}"
        chgrp "${RUNTIME_USER}" "${TEMP_RELEASE}"

        log "Exporting source"
        git --git-dir="${REPOSITORY_DIR}" archive --format=tar "${RELEASE_SHA}" | tar -xf - -C "${TEMP_RELEASE}"

        log "Fetching the pinned self-contained Node.js runtime"
        "${TEMP_RELEASE}/deploy/fetch-node-runtime.sh" \
            "${TEMP_RELEASE}/frontend/.runtime"

        log "Installing Python dependencies"
        python3 -m venv "${TEMP_RELEASE}/.venv"
        "${TEMP_RELEASE}/.venv/bin/python" -m pip install --disable-pip-version-check --quiet --require-hashes -r "${TEMP_RELEASE}/requirements.lock"

        log "Installing and building frontend dependencies"
        (
            cd "${TEMP_RELEASE}/frontend"
            export PATH="${TEMP_RELEASE}/frontend/.runtime:${PATH}"
            "${TEMP_RELEASE}/frontend/.runtime/node" "${SOURCE_NPM_CLI}" \
                ci --no-audit --no-fund --quiet
            "${TEMP_RELEASE}/.venv/bin/python" - \
                "${FRONTEND_ENV_FILE}" \
                "${TEMP_RELEASE}/frontend/.runtime/node" \
                "${SOURCE_NPM_CLI}" run build <<'PY'
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
            "${TEMP_RELEASE}/frontend/.runtime/node" "${SOURCE_NPM_CLI}" \
                prune --omit=dev --no-audit --no-fund --quiet
        )

        log "Recording the source-built release runtime identity"
        "${TEMP_RELEASE}/.venv/bin/python" - \
            "${TEMP_RELEASE}/${RELEASE_MANIFEST_NAME}" \
            "${FRONTEND_ENV_FILE}" \
            "${RELEASE_SHA}" \
            "${TEMP_RELEASE}/frontend/.runtime/node" <<'PY'
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess
import sys

from dotenv import dotenv_values

manifest_path, frontend_env_path, revision, runtime_node_path_raw = sys.argv[1:]
runtime_node_path = Path(runtime_node_path_raw)
public_keys = (
    "NEXT_PUBLIC_API_BASE_URL",
    "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY",
    "NEXT_PUBLIC_CLERK_SIGN_IN_URL",
    "NEXT_PUBLIC_CLERK_SIGN_UP_URL",
    "NEXT_PUBLIC_CLERK_SIGN_IN_FALLBACK_REDIRECT_URL",
    "NEXT_PUBLIC_CLERK_SIGN_UP_FALLBACK_REDIRECT_URL",
)
values = {
    key: str(value).strip()
    for key, value in dotenv_values(frontend_env_path).items()
    if value is not None
}
invalid = [
    key
    for key in public_keys
    if not values.get(key) or "REPLACE_WITH" in values.get(key, "")
]
if invalid:
    raise SystemExit(
        "production frontend environment is missing public build values: "
        + ", ".join(invalid)
    )
node_version = subprocess.check_output(
    [runtime_node_path, "--version"],
    text=True,
).strip().removeprefix("v")
node_match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:[-+].*)?", node_version)
if node_match is None or int(node_match.group(1)) != 24:
    raise SystemExit("source release runtime must be Node.js 24")
machine_aliases = {"amd64": "x86_64", "arm64": "aarch64"}
machine = platform.machine().strip().lower()
manifest = {
    "format_version": 2,
    "revision": revision,
    "frontend_public_environment": {key: values[key] for key in public_keys},
    "build_runtime": {
        "operating_system": platform.system().strip().lower(),
        "machine": machine_aliases.get(machine, machine),
        "libc_family": (platform.libc_ver()[0] or "unknown").strip().lower(),
        "python_major_minor": f"{sys.version_info.major}.{sys.version_info.minor}",
        "node_version": node_version,
        "node_major": int(node_match.group(1)),
        "node_sha256": hashlib.sha256(runtime_node_path.read_bytes()).hexdigest(),
    },
}
Path(manifest_path).write_text(
    json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY
    fi
fi

readonly runtime_node="${FINAL_RELEASE}/frontend/.runtime/node"
readonly runtime_node_license="${FINAL_RELEASE}/frontend/.runtime/LICENSE.nodejs"
[[ -x "${runtime_node}" && ! -L "${runtime_node}" ]] \
    || fail "release is missing its executable self-contained Node.js runtime"
[[ -f "${runtime_node_license}" && ! -L "${runtime_node_license}" ]] \
    || fail "release is missing the Node.js license"
"${runtime_node}" -e \
    'const [major]=process.versions.node.split(".").map(Number); process.exit(major === 24 ? 0 : 1)' \
    || fail "release runtime must be Node.js 24 LTS"

readonly release_manifest="${FINAL_RELEASE}/${RELEASE_MANIFEST_NAME}"
[[ -f "${release_manifest}" && ! -L "${release_manifest}" ]] \
    || fail "release manifest is missing or unsafe"
"${FINAL_RELEASE}/.venv/bin/python" - \
    "${release_manifest}" \
    "${FRONTEND_ENV_FILE}" \
    "${RELEASE_SHA}" \
    "${runtime_node}" <<'PY'
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess
import sys

from dotenv import dotenv_values

manifest_path, frontend_env_path, expected_revision, runtime_node_path_raw = sys.argv[1:]
runtime_node_path = Path(runtime_node_path_raw)
try:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
except (OSError, UnicodeError, ValueError) as exc:
    raise SystemExit("release manifest could not be decoded") from exc

public_keys = (
    "NEXT_PUBLIC_API_BASE_URL",
    "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY",
    "NEXT_PUBLIC_CLERK_SIGN_IN_URL",
    "NEXT_PUBLIC_CLERK_SIGN_UP_URL",
    "NEXT_PUBLIC_CLERK_SIGN_IN_FALLBACK_REDIRECT_URL",
    "NEXT_PUBLIC_CLERK_SIGN_UP_FALLBACK_REDIRECT_URL",
)
if manifest.get("format_version") != 2 or manifest.get("revision") != expected_revision:
    raise SystemExit("release manifest identity does not match the requested release")

build_public_environment = manifest.get("frontend_public_environment")
if not isinstance(build_public_environment, dict) or set(build_public_environment) != set(public_keys):
    raise SystemExit("release manifest contains an unexpected public frontend environment")
runtime_values = {
    key: str(value).strip()
    for key, value in dotenv_values(frontend_env_path).items()
    if value is not None
}
invalid_runtime_keys = [
    key
    for key in public_keys
    if not runtime_values.get(key) or "REPLACE_WITH" in runtime_values.get(key, "")
]
if invalid_runtime_keys:
    raise SystemExit(
        "production frontend environment is missing public build values: "
        + ", ".join(invalid_runtime_keys)
    )
mismatched_public_keys = [
    key
    for key in public_keys
    if build_public_environment.get(key) != runtime_values.get(key)
]
if mismatched_public_keys:
    raise SystemExit(
        "CI-built public frontend values differ from production: "
        + ", ".join(mismatched_public_keys)
    )

build_runtime = manifest.get("build_runtime")
required_runtime_keys = {
    "operating_system",
    "machine",
    "libc_family",
    "python_major_minor",
    "node_version",
    "node_major",
    "node_sha256",
}
if not isinstance(build_runtime, dict) or set(build_runtime) != required_runtime_keys:
    raise SystemExit("release manifest contains invalid build runtime metadata")

node_version = subprocess.check_output(
    [runtime_node_path, "--version"],
    text=True,
).strip().removeprefix("v")
node_match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:[-+].*)?", node_version)
build_node_version = str(build_runtime.get("node_version") or "")
build_node_match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:[-+].*)?", build_node_version)
if node_match is None or build_node_match is None:
    raise SystemExit("release manifest contains an invalid Node.js version")

machine_aliases = {"amd64": "x86_64", "arm64": "aarch64"}
machine = platform.machine().strip().lower()
current_runtime = {
    "operating_system": platform.system().strip().lower(),
    "machine": machine_aliases.get(machine, machine),
    "libc_family": (platform.libc_ver()[0] or "unknown").strip().lower(),
    "python_major_minor": f"{sys.version_info.major}.{sys.version_info.minor}",
    "node_major": int(node_match.group(1)),
    "node_sha256": hashlib.sha256(runtime_node_path.read_bytes()).hexdigest(),
}
runtime_mismatches = [
    key
    for key, current_value in current_runtime.items()
    if build_runtime.get(key) != current_value
]
if int(build_runtime.get("node_major", -1)) != int(build_node_match.group(1)):
    runtime_mismatches.append("node_version")
if node_version != build_node_version:
    runtime_mismatches.append("node_version")
if runtime_mismatches:
    raise SystemExit(
        "CI build runtime is incompatible with production: "
        + ", ".join(sorted(set(runtime_mismatches)))
    )
PY

if [[ "${release_is_complete}" != true ]]; then
    [[ -f "${TEMP_RELEASE}/frontend/.next/BUILD_ID" ]] || fail "frontend build did not create .next/BUILD_ID"
    [[ -f "${TEMP_RELEASE}/frontend/node_modules/next/dist/bin/next" ]] \
        || fail "frontend production dependencies are missing"
    rm -rf -- "${TEMP_RELEASE}/frontend/.next/cache"
    ln -s /var/cache/spyboxd-frontend "${TEMP_RELEASE}/frontend/.next/cache"
    ln -s "${SHARED_DIR}/data" "${TEMP_RELEASE}/data"
    printf '%s\n' "${RELEASE_SHA}" >"${TEMP_RELEASE}/REVISION"
    : >"${TEMP_RELEASE}/.revision-health-v1"
    chgrp -R "${RUNTIME_USER}" "${TEMP_RELEASE}"
    chmod -R g+rX,o-rwx "${TEMP_RELEASE}"

    TEMP_RELEASE=""
fi

readonly clerk_validator="${FINAL_RELEASE}/deploy/validate-clerk-production.py"
[[ -f "${clerk_validator}" && ! -L "${clerk_validator}" ]] \
    || fail "release is missing the production Clerk configuration validator"
readonly health_validator="${FINAL_RELEASE}/deploy/check-runtime-health.py"
[[ -f "${health_validator}" && ! -L "${health_validator}" ]] \
    || fail "release is missing the runtime health validator"
readonly frontend_runtime_validator="${FINAL_RELEASE}/deploy/check-frontend-runtime.py"
[[ -f "${frontend_runtime_validator}" && ! -L "${frontend_runtime_validator}" ]] \
    || fail "release is missing the frontend runtime proof validator"
clerk_validation_args=(
    runtime
    --frontend-env "${FRONTEND_ENV_FILE}"
    --api-env "${API_ENV_FILE}"
    --verify-remote
    --manifest "${release_manifest}"
)
"${FINAL_RELEASE}/.venv/bin/python" \
    "${clerk_validator}" \
    "${clerk_validation_args[@]}"

old_release=""
old_revision=""
legacy_rollback=false
clerk_bridge_mode=false
if [[ -L "${CURRENT_LINK}" ]]; then
    old_release="$(readlink -f "${CURRENT_LINK}" || true)"
    [[ -n "${old_release}" ]] \
        || fail "current release symlink does not resolve to an existing release"
    if [[ "${old_release}" == "${APP_ROOT}" ]]; then
        legacy_rollback=true
    elif [[ -n "${old_release}" && "${old_release}" != "${RELEASES_DIR}/"* ]]; then
        fail "current release target is outside ${RELEASES_DIR}: ${old_release}"
    elif [[ -n "${old_release}" ]]; then
        old_revision="$(basename "${old_release}")"
        if [[ ! "${old_revision}" =~ ^[0-9a-f]{40}$ ]] \
            || [[ ! -f "${old_release}/REVISION" ]] \
            || [[ "$(<"${old_release}/REVISION")" != "${old_revision}" ]]; then
            fail "current release does not have a trustworthy revision marker: ${old_release}"
        fi
    fi
elif [[ -x "${APP_ROOT}/.venv/bin/uvicorn" && -f "${APP_ROOT}/frontend/.next/BUILD_ID" ]]; then
    old_release="${APP_ROOT}"
    legacy_rollback=true
    log "A healthy-checkable legacy in-place release is available for first-rollout rollback"
fi

if [[ -n "${old_release}" ]]; then
    [[ "${legacy_rollback}" != true ]] \
        || fail "legacy in-place release cannot be retained as a Clerk-compatible rollback target"
    previous_manifest="${old_release}/${RELEASE_MANIFEST_NAME}"
    [[ -f "${previous_manifest}" && ! -L "${previous_manifest}" ]] \
        || fail "current release has no immutable Clerk-compatible release manifest"
    previous_manifest_format="$("${FINAL_RELEASE}/.venv/bin/python" - \
        "${previous_manifest}" "${old_revision}" <<'PY'
import json
from pathlib import Path
import sys

path, expected_revision = sys.argv[1:]
try:
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
except (OSError, UnicodeError, ValueError):
    raise SystemExit(1)
if (
    not isinstance(manifest, dict)
    or manifest.get("format_version") not in {1, 2}
    or manifest.get("revision") != expected_revision
):
    raise SystemExit(1)
print(manifest["format_version"])
PY
)" || fail "current release manifest identity is invalid"
    if [[ "${previous_manifest_format}" == 2 ]]; then
        [[ -x "${old_release}/frontend/.runtime/node" ]] \
            && [[ ! -L "${old_release}/frontend/.runtime/node" ]] \
            && [[ -f "${old_release}/frontend/.runtime/LICENSE.nodejs" ]] \
            && [[ ! -L "${old_release}/frontend/.runtime/LICENSE.nodejs" ]] \
            || fail "runtime-aware rollback release is missing its self-contained Node.js runtime"
    fi
    if [[ -n "${CLERK_BRIDGE_EDGE}" ]]; then
        [[ "${old_revision}" == "${bridge_from_revision}" ]] \
            || fail "SPYBOXD_CLERK_BRIDGE_EDGE does not identify the active source release"
        candidate_manifest="${FINAL_RELEASE}/${RELEASE_MANIFEST_NAME}"
        [[ -f "${candidate_manifest}" && ! -L "${candidate_manifest}" ]] \
            || fail "one-time Clerk bridge requires an immutable candidate release manifest"

        if "${FINAL_RELEASE}/.venv/bin/python" \
            "${clerk_validator}" \
            runtime \
            --frontend-env "${FRONTEND_ENV_FILE}" \
            --api-env "${API_ENV_FILE}" \
            --manifest "${previous_manifest}"; then
            fail "SPYBOXD_CLERK_BRIDGE_EDGE was supplied but the active release is already Clerk-compatible"
        fi
        "${FINAL_RELEASE}/.venv/bin/python" \
            "${clerk_validator}" \
            development-manifest \
            --manifest "${previous_manifest}" \
            --expected-revision "${old_revision}" \
            || fail "one-time Clerk bridge is limited to an exact development-key source artifact"

        clerk_bridge_mode=true
        log "WARNING: authorizing exact one-time Clerk development-to-live bridge ${bridge_from_revision} -> ${bridge_to_revision}; automatic rollback is unavailable"
        old_release=""
        old_revision=""
        legacy_rollback=false
    else
        log "Validating the automatic rollback target against production Clerk configuration"
        "${FINAL_RELEASE}/.venv/bin/python" \
            "${clerk_validator}" \
            runtime \
            --frontend-env "${FRONTEND_ENV_FILE}" \
            --api-env "${API_ENV_FILE}" \
            --manifest "${previous_manifest}" \
            || fail "current release is incompatible with production Clerk configuration and cannot be retained for automatic rollback"
    fi
elif [[ -n "${CLERK_BRIDGE_EDGE}" ]]; then
    fail "SPYBOXD_CLERK_BRIDGE_EDGE was supplied but there is no versioned active source release"
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

log "Revalidating the deployment tip before database migrations"
refresh_and_require_deploy_tip
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

required_api = (
    "DATABASE_URL",
    "FRONTEND_URL",
    "CORS_ALLOWED_ORIGINS",
    "INGESTION_API_TOKEN",
    "CLERK_ISSUER",
    "CLERK_AUTHORIZED_PARTIES",
)
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

activate_release() {
    local release_path="$1"
    ACTIVATION_LINK="${APP_ROOT}/.current.$$"
    ln -s "${release_path}" "${ACTIVATION_LINK}"
    mv -Tf -- "${ACTIVATION_LINK}" "${CURRENT_LINK}"
    ACTIVATION_LINK=""
    [[ "$(readlink -f "${CURRENT_LINK}" || true)" == "${release_path}" ]] \
        || fail "activation symlink did not resolve to ${release_path}"
}

restart_services() {
    timeout --signal=TERM --kill-after=15s 4m \
        sudo -n systemctl restart "${SERVICES[@]}"
}

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

check_readiness() {
    wait_for_validated_json "API revision ${RELEASE_SHA}" "http://127.0.0.1:8000/ready" ready "${RELEASE_SHA}" \
        && wait_for_validated_json "database-backed dashboard" "http://127.0.0.1:8000/api/public/dashboard" dashboard \
        && wait_for_http "frontend sign-in" "http://127.0.0.1:3000/sign-in" \
        && wait_for_validated_json "public API revision ${RELEASE_SHA}" "https://api.spyboxd.com/ready" ready "${RELEASE_SHA}" \
        && wait_for_validated_json "public database-backed dashboard" "https://api.spyboxd.com/api/public/dashboard" dashboard \
        && wait_for_http "public frontend sign-in" "https://spyboxd.com/sign-in"
}

require_bundled_frontend_process() {
    "${FINAL_RELEASE}/.venv/bin/python" "${frontend_runtime_validator}" \
        --proof "${FRONTEND_RUNTIME_PROOF_FILE}" \
        --revision "${RELEASE_SHA}" \
        --node "${runtime_node}" \
        --next-entrypoint "${FINAL_RELEASE}/frontend/node_modules/next/dist/bin/next" \
        --runtime-uid "${runtime_uid}" \
        --runtime-gid "${runtime_gid}" \
        --control-group /system.slice/spyboxd-frontend.service
}

check_rollback_liveness() {
    if [[ -f "${old_release}/.revision-health-v1" ]]; then
        wait_for_http "rolled-back API revision ${old_revision}" "http://127.0.0.1:8000/health" ok "${old_revision}" \
            && wait_for_validated_json "rolled-back database-backed dashboard" "http://127.0.0.1:8000/api/public/dashboard" dashboard \
            && wait_for_http "rolled-back frontend" "http://127.0.0.1:3000/sign-in" \
            && wait_for_http "public rolled-back API revision ${old_revision}" "https://api.spyboxd.com/health" ok "${old_revision}" \
            && wait_for_validated_json "public rolled-back database-backed dashboard" "https://api.spyboxd.com/api/public/dashboard" dashboard \
            && wait_for_http "public rolled-back frontend" "https://spyboxd.com/sign-in"
        return
    fi

    # The release immediately predating revision-aware health cannot report its
    # SHA. This one-time transition still has an exact, validated symlink target
    # plus successful local liveness after systemd restarts both services.
    wait_for_http "rolled-back legacy API" "http://127.0.0.1:8000/health" ok \
        && wait_for_validated_json "rolled-back legacy database-backed dashboard" "http://127.0.0.1:8000/api/public/dashboard" dashboard \
        && wait_for_http "rolled-back legacy frontend" "http://127.0.0.1:3000/sign-in"
}

write_release_state() {
    local name="$1" revision="$2" temporary
    [[ "${name}" == "active" || "${name}" == "previous" ]] \
        || fail "invalid release state marker: ${name}"
    [[ "${revision}" =~ ^[0-9a-f]{40}$ ]] \
        || fail "refusing to write an invalid release revision"
    temporary="${RELEASE_STATE_DIR}/.${name}.$$"
    printf '%s\n' "${revision}" >"${temporary}"
    chmod 0640 "${temporary}"
    mv -f -- "${temporary}" "${RELEASE_STATE_DIR}/${name}"
}

record_successful_activation() {
    touch "${FINAL_RELEASE}/.activated-at"
    if [[ -n "${old_revision}" && "${old_revision}" != "${RELEASE_SHA}" ]]; then
        write_release_state previous "${old_revision}"
    elif [[ -z "${old_revision}" ]]; then
        rm -f -- "${RELEASE_STATE_DIR}/previous"
    fi
    write_release_state active "${RELEASE_SHA}"
}

prune_old_releases() {
    local release_path release_name activated_at total previous_revision=""
    local -a known_releases=() ordered_releases=()

    if [[ -f "${RELEASE_STATE_DIR}/previous" ]]; then
        previous_revision="$(<"${RELEASE_STATE_DIR}/previous")"
        [[ "${previous_revision}" =~ ^[0-9a-f]{40}$ ]] || previous_revision=""
    fi

    for release_path in "${RELEASES_DIR}"/*; do
        [[ -d "${release_path}" && ! -L "${release_path}" ]] || continue
        release_name="$(basename "${release_path}")"
        [[ "${release_name}" =~ ^[0-9a-f]{40}$ ]] || continue
        [[ -f "${release_path}/REVISION" ]] || continue
        [[ "$(<"${release_path}/REVISION")" == "${release_name}" ]] || continue
        [[ -x "${release_path}/.venv/bin/uvicorn" ]] || continue
        [[ -f "${release_path}/frontend/.next/BUILD_ID" ]] || continue
        activated_at="$(stat -c '%Y' "${release_path}/.activated-at" 2>/dev/null || stat -c '%Y' "${release_path}")"
        known_releases+=("${activated_at} ${release_name}")
    done

    total="${#known_releases[@]}"
    (( total > RELEASE_RETENTION )) || return 0
    mapfile -t ordered_releases < <(printf '%s\n' "${known_releases[@]}" | sort -n)
    for release_path in "${ordered_releases[@]}"; do
        (( total > RELEASE_RETENTION )) || break
        release_name="${release_path#* }"
        if [[ "${release_name}" == "${RELEASE_SHA}" || "${release_name}" == "${previous_revision}" ]]; then
            continue
        fi
        release_path="${RELEASES_DIR}/${release_name}"
        [[ "${release_path}" == "${RELEASES_DIR}/"[0-9a-f][0-9a-f]* ]] \
            || { log "WARNING: retention guard rejected ${release_path}" >&2; return 1; }
        log "Pruning superseded release ${release_name}"
        if ! rm -rf -- "${release_path}"; then
            log "WARNING: could not prune ${release_name}; leaving it in place" >&2
            return 1
        fi
        total=$((total - 1))
    done
}

observe_rss_health() {
    local response
    if response="$(curl --silent --show-error --fail --max-time 5 http://127.0.0.1:8000/health/rss 2>/dev/null)" \
        && printf '%s' "${response}" | python3 "${health_validator}" rss >/dev/null; then
        log "RSS operational health is healthy"
    else
        log "WARNING: RSS operational health is degraded; deployment remains active because RSS health is observational" >&2
    fi
}

log "Revalidating the deployment tip before activation"
refresh_and_require_deploy_tip
log "Activating ${FINAL_RELEASE}"
activate_release "${FINAL_RELEASE}"

if restart_services && check_readiness && require_bundled_frontend_process; then
    observe_rss_health
    record_successful_activation
    prune_old_releases || log "WARNING: release retention cleanup was incomplete" >&2
    log "Release ${RELEASE_SHA} is active and healthy"
    exit 0
fi

describe_health_failure() {
    # Two consecutive releases failed at "frontend sign-in" with nothing in
    # this log to say why, and the deploy user's sudo allowlist cannot reach
    # journalctl — so the failure must describe itself from within existing
    # privileges. Connection refused and an HTTP error are opposite diagnoses:
    # the first is a process that will not start, the second an app that did.
    local probe
    for probe in \
        "local API|http://127.0.0.1:8000/health" \
        "local frontend|http://127.0.0.1:3000/sign-in"; do
        local label="${probe%%|*}" url="${probe#*|}" status body
        status="$(curl --silent --output /tmp/spyboxd-health-probe.$$ \
            --write-out '%{http_code} %{errormsg}' --max-time 8 "${url}" 2>&1 || true)"
        body="$(head -c 300 /tmp/spyboxd-health-probe.$$ 2>/dev/null | tr -d '\0' | tr '\n' ' ')"
        rm -f "/tmp/spyboxd-health-probe.$$"
        log "DIAGNOSTIC ${label}: ${status}; body starts: ${body:-<empty>}" >&2
    done
    # Which start path the unit resolved to — the bundled runtime or the npm
    # fallback — is in the sudo allowlist already.
    log "DIAGNOSTIC frontend ExecStart: $(timeout --signal=TERM 10s \
        sudo -n systemctl show spyboxd-frontend.service --property=ExecStart --value 2>&1 \
        | head -c 400 || true)" >&2
    # A full disk kills the frontend (it writes caches) long before the API
    # (already running, appending little), which fits a code-independent,
    # deterministic failure exactly.
    log "DIAGNOSTIC disk: $(df -h /opt /var /tmp 2>&1 | tr '\n' '; ' || true)" >&2

    # The 500's actual stack goes to the service's stderr, which lands in a
    # journal the deploy user is not allowed to read. So run the release's own
    # frontend in the foreground for one probe and read the stderr directly.
    # Env values are never echoed by Next; the grep drops any line that names
    # one anyway.
    local oneshot_log="/tmp/spyboxd-frontend-oneshot.$$"
    if [[ -d "${FINAL_RELEASE}/frontend" ]]; then
        (
            cd "${FINAL_RELEASE}/frontend" || exit 1
            set -a
            # shellcheck disable=SC1091
            [[ -f /etc/spyboxd/frontend.env ]] && . /etc/spyboxd/frontend.env
            set +a
            export NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
            local_node="./.runtime/node"
            [[ -x "${local_node}" && ! -L "${local_node}" ]] || local_node="node"
            timeout --signal=TERM --kill-after=5s 25s \
                "${local_node}" node_modules/next/dist/bin/next start \
                --hostname 127.0.0.1 --port 3999 >"${oneshot_log}" 2>&1 &
            server_pid=$!
            for _ in $(seq 1 10); do
                sleep 1
                if curl --silent --output /dev/null --max-time 4 http://127.0.0.1:3999/sign-in; then
                    break
                fi
            done
            curl --silent --output /dev/null --max-time 6 http://127.0.0.1:3999/sign-in || true
            sleep 1
            kill "${server_pid}" 2>/dev/null || true
        ) || true
        log "DIAGNOSTIC one-shot frontend stderr follows" >&2
        grep -aiv -e 'key' -e 'secret' -e 'token' "${oneshot_log}" 2>/dev/null \
            | tail -n 40 | sed 's/^/[oneshot] /' >&2 || true
        rm -f "${oneshot_log}"
    fi
}

describe_health_failure
log "Health verification failed; rolling application services back"
if [[ -n "${old_release}" && -d "${old_release}" ]]; then
    activate_release "${old_release}"
    if [[ "${legacy_rollback}" == true ]]; then
        timeout --signal=TERM --kill-after=15s 4m \
            sudo -n systemctl restart spyboxd-api.service spyboxd-frontend.service || true
        timeout --signal=TERM --kill-after=15s 2m \
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
    if [[ "${clerk_bridge_mode}" == true ]]; then
        timeout --signal=TERM --kill-after=15s 4m \
            sudo -n systemctl stop "${SERVICES[@]}" \
            || fail "Clerk bridge candidate is unhealthy and its services could not be stopped"
    else
        timeout --signal=TERM --kill-after=15s 4m \
            sudo -n systemctl stop "${SERVICES[@]}" || true
    fi
    rm -f -- "${CURRENT_LINK}"
    if [[ "${clerk_bridge_mode}" == true ]]; then
        log "Clerk bridge activation failed, so services were stopped and no incompatible rollback was activated. Database migrations were not downgraded." >&2
    else
        log "First activation failed, so services were stopped and the current symlink was removed. Database migrations were not downgraded." >&2
    fi
fi

exit 1
