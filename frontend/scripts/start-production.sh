#!/bin/sh
set -eu

runtime_node=./.runtime/node
next_entrypoint=./node_modules/next/dist/bin/next
runtime_proof_preload=./scripts/runtime-proof.cjs

if [ -z "${SPYBOXD_RUNTIME_PROOF_FILE:-}" ] \
    && [ -d /var/cache/spyboxd-frontend ]; then
    SPYBOXD_RUNTIME_PROOF_FILE=/var/cache/spyboxd-frontend/runtime-proof.json
    export SPYBOXD_RUNTIME_PROOF_FILE
fi

if [ -x "${runtime_node}" ] && [ ! -L "${runtime_node}" ] \
    && [ -f "${runtime_proof_preload}" ] \
    && [ ! -L "${runtime_proof_preload}" ]; then
    exec "${runtime_node}" --require "${runtime_proof_preload}" \
        "${next_entrypoint}" start "$@"
fi

if command -v node >/dev/null 2>&1 \
    && node -e 'const [major] = process.versions.node.split(".").map(Number); process.exit(major === 24 ? 0 : 1)'; then
    exec node --require "${runtime_proof_preload}" "${next_entrypoint}" start "$@"
fi

if [ "${NODE_ENV:-}" = production ]; then
    printf 'A trusted Node.js 24 production runtime is unavailable.\n' >&2
    exit 1
fi

exec node "${next_entrypoint}" start "$@"
