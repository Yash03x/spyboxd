#!/usr/bin/env bash
set -Eeuo pipefail

readonly NODE_VERSION="24.18.1"
readonly NODE_ARCHIVE="node-v${NODE_VERSION}-linux-x64.tar.xz"
readonly NODE_ARCHIVE_SHA256="d6c664df3f3f61458e8c277585571328522d705166723a7c7823a9253a4d15a0"
readonly NODE_RELEASE_BASE_URL="https://nodejs.org/dist/v${NODE_VERSION}"

usage() {
    printf 'Usage: %s <empty-output-directory>\n' "$0" >&2
    exit 64
}

[[ $# -eq 1 ]] || usage
readonly OUTPUT_DIR="$1"
[[ ! -e "${OUTPUT_DIR}" && ! -L "${OUTPUT_DIR}" ]] || {
    printf 'Node runtime output path already exists: %s\n' "${OUTPUT_DIR}" >&2
    exit 1
}

for command_name in curl install mktemp sha256sum tar uname; do
    command -v "${command_name}" >/dev/null 2>&1 || {
        printf 'Required command is missing: %s\n' "${command_name}" >&2
        exit 1
    }
done
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || {
    printf 'Pinned production Node runtime supports Linux x86_64 only\n' >&2
    exit 1
}

readonly TEMP_DIR="$(mktemp -d)"
cleanup() {
    local exit_status=$?
    rm -rf -- "${TEMP_DIR}"
    if (( exit_status != 0 )); then
        rm -rf -- "${OUTPUT_DIR}"
    fi
    exit "${exit_status}"
}
trap cleanup EXIT

curl \
    --fail \
    --location \
    --connect-timeout 10 \
    --max-time 120 \
    --proto '=https' \
    --retry 3 \
    --retry-all-errors \
    --retry-delay 2 \
    --silent \
    --show-error \
    --tlsv1.2 \
    --output "${TEMP_DIR}/${NODE_ARCHIVE}" \
    "${NODE_RELEASE_BASE_URL}/${NODE_ARCHIVE}"
printf '%s  %s\n' "${NODE_ARCHIVE_SHA256}" "${TEMP_DIR}/${NODE_ARCHIVE}" \
    | sha256sum --check --strict -

tar \
    --extract \
    --file "${TEMP_DIR}/${NODE_ARCHIVE}" \
    --directory "${TEMP_DIR}" \
    --xz \
    --no-same-owner \
    --no-same-permissions \
    "node-v${NODE_VERSION}-linux-x64/bin/node" \
    "node-v${NODE_VERSION}-linux-x64/LICENSE"

install -d -m 0750 -- "${OUTPUT_DIR}"
install -m 0750 \
    "${TEMP_DIR}/node-v${NODE_VERSION}-linux-x64/bin/node" \
    "${OUTPUT_DIR}/node"
install -m 0640 \
    "${TEMP_DIR}/node-v${NODE_VERSION}-linux-x64/LICENSE" \
    "${OUTPUT_DIR}/LICENSE.nodejs"

[[ "$("${OUTPUT_DIR}/node" --version)" == "v${NODE_VERSION}" ]] || {
    printf 'Extracted Node runtime reported an unexpected version\n' >&2
    exit 1
}
node_digest="$(sha256sum "${OUTPUT_DIR}/node")"
node_digest="${node_digest%% *}"
[[ "${node_digest}" =~ ^[0-9a-f]{64}$ ]] || {
    printf 'Could not hash the extracted Node runtime\n' >&2
    exit 1
}
