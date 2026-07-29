#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
    printf 'Usage: %s <full-40-character-git-sha> <wheelhouse-directory> <output-directory>\n' "$0" >&2
    exit 64
}

[[ $# -eq 3 ]] || usage

readonly RELEASE_SHA="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
readonly WHEELHOUSE_DIR="$2"
readonly OUTPUT_DIR="$3"
readonly REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
readonly ARTIFACT_NAME="spyboxd-release-${RELEASE_SHA}.tar.gz"
readonly RELEASE_MANIFEST_NAME=".spyboxd-release-manifest.json"

[[ "${RELEASE_SHA}" =~ ^[0-9a-f]{40}$ ]] || {
    printf 'Release must be a full 40-character Git SHA\n' >&2
    exit 64
}
git -C "${REPO_ROOT}" cat-file -e "${RELEASE_SHA}^{commit}"
resolved_head="$(git -C "${REPO_ROOT}" rev-parse --verify HEAD)"
[[ "${resolved_head}" == "${RELEASE_SHA}" ]] || {
    printf 'Current HEAD does not match the requested release SHA\n' >&2
    exit 1
}
git -C "${REPO_ROOT}" diff --quiet --ignore-submodules=all "${RELEASE_SHA}" -- . || {
    printf 'Tracked worktree content differs from the requested release SHA\n' >&2
    exit 1
}
untracked_paths="$(git -C "${REPO_ROOT}" ls-files --others --exclude-standard)"
[[ -z "${untracked_paths}" ]] || {
    printf 'Untracked, non-ignored files make the release worktree non-reproducible\n' >&2
    exit 1
}
hidden_frontend_env="$(
    find "${REPO_ROOT}/frontend" -maxdepth 1 -name '.env*' \
        ! -name '.env.example' -print -quit
)"
[[ -z "${hidden_frontend_env}" ]] || {
    printf 'Ignored frontend environment files must not influence an immutable build\n' >&2
    exit 1
}

[[ -d "${WHEELHOUSE_DIR}" && ! -L "${WHEELHOUSE_DIR}" ]] || {
    printf 'Wheelhouse directory is missing: %s\n' "${WHEELHOUSE_DIR}" >&2
    exit 1
}
find "${WHEELHOUSE_DIR}" -mindepth 1 -maxdepth 1 -type f -name '*.whl' -print -quit | grep -q . || {
    printf 'Wheelhouse directory is empty: %s\n' "${WHEELHOUSE_DIR}" >&2
    exit 1
}
unexpected_wheelhouse_entry="$(
    find "${WHEELHOUSE_DIR}" -mindepth 1 -maxdepth 1 \
        \( ! -type f -o ! -name '*.whl' \) -print -quit
)"
[[ -z "${unexpected_wheelhouse_entry}" ]] || {
    printf 'Wheelhouse contains a non-wheel or non-regular entry\n' >&2
    exit 1
}
[[ -d "${REPO_ROOT}/frontend/.next" && ! -L "${REPO_ROOT}/frontend/.next" ]] \
    && [[ -f "${REPO_ROOT}/frontend/.next/BUILD_ID" ]] \
    && [[ ! -L "${REPO_ROOT}/frontend/.next/BUILD_ID" ]] || {
    printf 'The production frontend has not been built\n' >&2
    exit 1
}
[[ -d "${REPO_ROOT}/frontend/node_modules" && ! -L "${REPO_ROOT}/frontend/node_modules" ]] \
    && [[ -f "${REPO_ROOT}/frontend/node_modules/next/dist/bin/next" ]] \
    && [[ ! -L "${REPO_ROOT}/frontend/node_modules/next/dist/bin/next" ]] || {
    printf 'Production frontend dependencies are missing\n' >&2
    exit 1
}

mkdir -p -- "${OUTPUT_DIR}"
readonly FINAL_ARTIFACT="${OUTPUT_DIR}/${ARTIFACT_NAME}"
readonly FINAL_CHECKSUM="${FINAL_ARTIFACT}.sha256"
[[ ! -e "${FINAL_ARTIFACT}" && ! -L "${FINAL_ARTIFACT}" ]] \
    && [[ ! -e "${FINAL_CHECKSUM}" && ! -L "${FINAL_CHECKSUM}" ]] || {
    printf 'Release artifact output paths already exist\n' >&2
    exit 1
}
readonly STAGING_DIR="$(mktemp -d)"
readonly TEMP_ARTIFACT="$(mktemp "${OUTPUT_DIR}/.${ARTIFACT_NAME}.tmp.XXXXXX")"
readonly TEMP_CHECKSUM="$(mktemp "${OUTPUT_DIR}/.${ARTIFACT_NAME}.sha256.tmp.XXXXXX")"
PUBLISHED_ARTIFACT=""

cleanup() {
    local exit_status=$?
    rm -rf -- "${STAGING_DIR}"
    rm -f -- "${TEMP_ARTIFACT}" "${TEMP_CHECKSUM}"
    if [[ -n "${PUBLISHED_ARTIFACT}" ]]; then
        rm -f -- "${PUBLISHED_ARTIFACT}"
    fi
    exit "${exit_status}"
}
trap cleanup EXIT

mkdir -m 0750 -- "${STAGING_DIR}/app"
git -C "${REPO_ROOT}" archive --format=tar "${RELEASE_SHA}" \
    | tar -xf - -C "${STAGING_DIR}/app"

rm -rf -- "${STAGING_DIR}/app/frontend/.next" "${STAGING_DIR}/app/frontend/node_modules"
cp -a -- "${REPO_ROOT}/frontend/.next" "${STAGING_DIR}/app/frontend/.next"
cp -a -- "${REPO_ROOT}/frontend/node_modules" "${STAGING_DIR}/app/frontend/node_modules"
rm -rf -- "${STAGING_DIR}/app/frontend/.next/cache"

mkdir -m 0750 -- "${STAGING_DIR}/app/.release-wheelhouse"
cp -a -- "${WHEELHOUSE_DIR}/." "${STAGING_DIR}/app/.release-wheelhouse/"
rm -f -- \
    "${STAGING_DIR}/app/REVISION" \
    "${STAGING_DIR}/app/${RELEASE_MANIFEST_NAME}"
printf '%s\n' "${RELEASE_SHA}" >"${STAGING_DIR}/app/REVISION"
python3 - "${STAGING_DIR}/app/${RELEASE_MANIFEST_NAME}" "${RELEASE_SHA}" <<'PY'
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

manifest_path = Path(sys.argv[1])
revision = sys.argv[2]
public_keys = (
    "NEXT_PUBLIC_API_BASE_URL",
    "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY",
    "NEXT_PUBLIC_CLERK_SIGN_IN_URL",
    "NEXT_PUBLIC_CLERK_SIGN_UP_URL",
    "NEXT_PUBLIC_CLERK_SIGN_IN_FALLBACK_REDIRECT_URL",
    "NEXT_PUBLIC_CLERK_SIGN_UP_FALLBACK_REDIRECT_URL",
)
public_environment = {key: os.environ.get(key, "") for key in public_keys}
invalid = [
    key
    for key, value in public_environment.items()
    if not value.strip() or "REPLACE_WITH" in value
]
if invalid:
    raise SystemExit(
        "missing or placeholder public frontend build values: " + ", ".join(invalid)
    )

node_version = subprocess.check_output(
    ["node", "--version"],
    text=True,
).strip().removeprefix("v")
node_match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:[-+].*)?", node_version)
if node_match is None:
    raise SystemExit("could not identify the Node.js build version")

machine_aliases = {"amd64": "x86_64", "arm64": "aarch64"}
machine = platform.machine().strip().lower()
libc_family = (platform.libc_ver()[0] or "unknown").strip().lower()
manifest = {
    "format_version": 1,
    "revision": revision,
    "frontend_public_environment": public_environment,
    "build_runtime": {
        "operating_system": platform.system().strip().lower(),
        "machine": machine_aliases.get(machine, machine),
        "libc_family": libc_family,
        "python_major_minor": f"{sys.version_info.major}.{sys.version_info.minor}",
        "node_version": node_version,
        "node_major": int(node_match.group(1)),
    },
}
manifest_path.write_text(
    json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

readonly SOURCE_DATE_EPOCH="$(git -C "${REPO_ROOT}" show -s --format=%ct "${RELEASE_SHA}")"
tar \
    --sort=name \
    --mtime="@${SOURCE_DATE_EPOCH}" \
    --owner=0 \
    --group=0 \
    --numeric-owner \
    -czf "${TEMP_ARTIFACT}" \
    -C "${STAGING_DIR}" \
    app

artifact_digest="$(sha256sum "${TEMP_ARTIFACT}")"
artifact_digest="${artifact_digest%% *}"
[[ "${artifact_digest}" =~ ^[0-9a-f]{64}$ ]] || {
    printf 'Could not compute a valid release artifact digest\n' >&2
    exit 1
}
printf '%s  %s\n' "${artifact_digest}" "${ARTIFACT_NAME}" >"${TEMP_CHECKSUM}"
chmod 0640 "${TEMP_ARTIFACT}" "${TEMP_CHECKSUM}"

ln -- "${TEMP_ARTIFACT}" "${FINAL_ARTIFACT}"
PUBLISHED_ARTIFACT="${FINAL_ARTIFACT}"
if ! ln -- "${TEMP_CHECKSUM}" "${FINAL_CHECKSUM}"; then
    printf 'Could not publish the release checksum alongside its artifact\n' >&2
    exit 1
fi
PUBLISHED_ARTIFACT=""
rm -f -- "${TEMP_ARTIFACT}" "${TEMP_CHECKSUM}"

printf '%s\n' "${FINAL_ARTIFACT}"
