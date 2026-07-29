#!/usr/bin/env bash
set -Eeuo pipefail

readonly SSH_ALIAS="spyboxd-production"
readonly SSH_USER="spyboxd-deploy"

require_runner_temp() {
    [[ -n "${RUNNER_TEMP:-}" && "${RUNNER_TEMP}" == /* && "${RUNNER_TEMP}" != "/" ]] \
        || { printf '[spyboxd-ssh] RUNNER_TEMP must be a safe absolute directory\n' >&2; exit 64; }
    [[ -d "${RUNNER_TEMP}" && ! -L "${RUNNER_TEMP}" ]] \
        || { printf '[spyboxd-ssh] RUNNER_TEMP is not a safe directory\n' >&2; exit 64; }
}

require_runner_temp
readonly MATERIAL_PREFIX="${RUNNER_TEMP}/spyboxd-production-ssh"
readonly KEY_PATH="${MATERIAL_PREFIX}.key"
readonly KNOWN_HOSTS_PATH="${MATERIAL_PREFIX}.known-hosts"
readonly SCANNED_HOSTS_PATH="${MATERIAL_PREFIX}.scanned-hosts"
readonly CONFIG_PATH="${MATERIAL_PREFIX}.config"
readonly CONTROL_PATH="${MATERIAL_PREFIX}.control"

require_material_path() {
    local candidate="$1"
    case "${candidate}" in
        "${RUNNER_TEMP}"/spyboxd-production-ssh*) ;;
        *)
            printf '[spyboxd-ssh] refusing a material path outside RUNNER_TEMP\n' >&2
            exit 64
            ;;
    esac
}

for material_path in \
    "${KEY_PATH}" \
    "${KNOWN_HOSTS_PATH}" \
    "${SCANNED_HOSTS_PATH}" \
    "${CONFIG_PATH}" \
    "${CONTROL_PATH}"
do
    require_material_path "${material_path}"
done

cleanup_material() {
    local cleanup_path

    if [[ -f "${CONFIG_PATH}" && ! -L "${CONFIG_PATH}" ]]; then
        timeout --signal=TERM --kill-after=2s 10s \
            ssh -4 -F "${CONFIG_PATH}" -O exit "${SSH_ALIAS}" \
            >/dev/null 2>&1 || true
    fi

    if [[ -S "${CONTROL_PATH}" ]]; then
        rm -f -- "${CONTROL_PATH}"
    elif [[ -e "${CONTROL_PATH}" || -L "${CONTROL_PATH}" ]]; then
        printf '[spyboxd-ssh] refusing to remove an unsafe control path\n' >&2
        return 1
    fi

    for cleanup_path in \
        "${KEY_PATH}" \
        "${KNOWN_HOSTS_PATH}" \
        "${SCANNED_HOSTS_PATH}" \
        "${CONFIG_PATH}"
    do
        if [[ -L "${cleanup_path}" ]]; then
            printf '[spyboxd-ssh] refusing to follow an SSH material symlink\n' >&2
            return 1
        fi
        if [[ -f "${cleanup_path}" ]]; then
            chmod 0600 "${cleanup_path}"
            shred --force --iterations=1 --zero --remove -- "${cleanup_path}"
        elif [[ -e "${cleanup_path}" ]]; then
            printf '[spyboxd-ssh] refusing to remove non-file SSH material\n' >&2
            return 1
        fi
    done
}

require_open_connection() {
    [[ -f "${CONFIG_PATH}" && ! -L "${CONFIG_PATH}" ]] \
        || { printf '[spyboxd-ssh] production SSH is not initialized\n' >&2; exit 1; }
    [[ -f "${KEY_PATH}" && ! -L "${KEY_PATH}" ]] \
        || { printf '[spyboxd-ssh] production SSH key material is unavailable\n' >&2; exit 1; }
    [[ -f "${KNOWN_HOSTS_PATH}" && ! -L "${KNOWN_HOSTS_PATH}" ]] \
        || { printf '[spyboxd-ssh] production host identity is unavailable\n' >&2; exit 1; }
}

open_connection() {
    local candidate_fingerprint key_line matching_keys ssh_attempt

    case "${SSH_HOST:-}" in
        ''|-*|*[!A-Za-z0-9.-]*)
            printf '[spyboxd-ssh] SSH_HOST must be a plain hostname or IPv4 address\n' >&2
            exit 64
            ;;
    esac
    [[ "${SSH_FINGERPRINT:-}" =~ ^SHA256:[A-Za-z0-9+/]{43}$ ]] \
        || { printf '[spyboxd-ssh] SSH_FINGERPRINT must be an exact SHA256 fingerprint\n' >&2; exit 64; }
    [[ -n "${SSH_PRIVATE_KEY:-}" ]] \
        || { printf '[spyboxd-ssh] SSH_PRIVATE_KEY is empty\n' >&2; exit 64; }

    for material_path in \
        "${KEY_PATH}" \
        "${KNOWN_HOSTS_PATH}" \
        "${SCANNED_HOSTS_PATH}" \
        "${CONFIG_PATH}" \
        "${CONTROL_PATH}"
    do
        [[ ! -e "${material_path}" && ! -L "${material_path}" ]] \
            || { printf '[spyboxd-ssh] refusing to overwrite existing SSH material\n' >&2; exit 1; }
    done

    trap cleanup_material EXIT
    trap 'exit 130' INT TERM
    umask 077
    printf '%s\n' "${SSH_PRIVATE_KEY}" >"${KEY_PATH}"
    chmod 0600 "${KEY_PATH}"
    [[ -s "${KEY_PATH}" ]]

    timeout --signal=TERM --kill-after=2s 20s \
        ssh-keyscan -4 -T 12 -t ed25519,ecdsa,rsa "${SSH_HOST}" \
        >"${SCANNED_HOSTS_PATH}" 2>/dev/null
    [[ -s "${SCANNED_HOSTS_PATH}" ]] \
        || { printf '[spyboxd-ssh] production host key scan returned no keys\n' >&2; exit 1; }

    matching_keys=0
    while IFS= read -r key_line; do
        case "${key_line}" in
            \#*|'') continue ;;
        esac
        candidate_fingerprint="$(
            printf '%s\n' "${key_line}" | ssh-keygen -lf - -E sha256 | awk '{print $2}'
        )"
        if [[ "${candidate_fingerprint}" == "${SSH_FINGERPRINT}" ]]; then
            printf '%s\n' "${key_line}" >>"${KNOWN_HOSTS_PATH}"
            ((matching_keys += 1))
        fi
    done <"${SCANNED_HOSTS_PATH}"
    (( matching_keys > 0 )) \
        || { printf '[spyboxd-ssh] scanned host keys did not match the pinned fingerprint\n' >&2; exit 1; }
    chmod 0600 "${KNOWN_HOSTS_PATH}"

    cat >"${CONFIG_PATH}" <<EOF
Host ${SSH_ALIAS}
    HostName ${SSH_HOST}
    User ${SSH_USER}
    AddressFamily inet
    BatchMode yes
    ConnectTimeout 30
    ConnectionAttempts 1
    ControlMaster auto
    ControlPath ${CONTROL_PATH}
    ControlPersist 60m
    GlobalKnownHostsFile /dev/null
    IdentitiesOnly yes
    IdentityFile ${KEY_PATH}
    KbdInteractiveAuthentication no
    LogLevel ERROR
    PasswordAuthentication no
    PreferredAuthentications publickey
    ServerAliveCountMax 6
    ServerAliveInterval 10
    StrictHostKeyChecking yes
    UserKnownHostsFile ${KNOWN_HOSTS_PATH}
EOF
    chmod 0600 "${CONFIG_PATH}"

    for ssh_attempt in 1 2; do
        if timeout --signal=TERM --kill-after=5s 45s \
            ssh -4 -F "${CONFIG_PATH}" -MNf "${SSH_ALIAS}" \
            && ssh -4 -F "${CONFIG_PATH}" -O check "${SSH_ALIAS}" >/dev/null
        then
            trap - EXIT INT TERM
            printf '[spyboxd-ssh] pinned production connection established\n'
            return 0
        fi
        timeout --signal=TERM --kill-after=2s 10s \
            ssh -4 -F "${CONFIG_PATH}" -O exit "${SSH_ALIAS}" \
            >/dev/null 2>&1 || true
        if [[ -S "${CONTROL_PATH}" ]]; then
            rm -f -- "${CONTROL_PATH}"
        fi
        if (( ssh_attempt < 2 )); then
            sleep 35
        fi
    done

    printf '[spyboxd-ssh] could not establish the pinned production connection\n' >&2
    return 1
}

run_command() {
    require_open_connection
    (( $# > 0 )) || { printf '[spyboxd-ssh] run requires a command\n' >&2; exit 64; }
    exec ssh -4 -F "${CONFIG_PATH}" -T "${SSH_ALIAS}" "$@"
}

copy_files() {
    require_open_connection
    (( $# >= 2 )) || { printf '[spyboxd-ssh] copy requires sources and a destination\n' >&2; exit 64; }
    exec timeout --signal=TERM --kill-after=15s 15m \
        scp -4 -F "${CONFIG_PATH}" -- "$@"
}

case "${1:-}" in
    open)
        [[ $# -eq 1 ]] || { printf '[spyboxd-ssh] open accepts no arguments\n' >&2; exit 64; }
        open_connection
        ;;
    run)
        shift
        run_command "$@"
        ;;
    copy)
        shift
        copy_files "$@"
        ;;
    close)
        [[ $# -eq 1 ]] || { printf '[spyboxd-ssh] close accepts no arguments\n' >&2; exit 64; }
        cleanup_material
        ;;
    *)
        printf 'Usage: %s {open|run|copy|close}\n' "$0" >&2
        exit 64
        ;;
esac
