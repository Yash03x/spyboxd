#!/usr/bin/env bash
set -Eeuo pipefail

# Exercise Compose packaging, dependency ordering, API migration, and container
# health without publishing host ports or recompiling the Next.js artifact.
# Browser-to-API behavior is covered separately by the required Playwright job.
readonly project_name="spyboxdci-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}-${PPID}"
if [[ ! "${project_name}" =~ ^[a-z0-9][a-z0-9_-]{1,62}$ ]]; then
    printf 'Unsafe Compose project name: %s\n' "${project_name}" >&2
    exit 64
fi

umask 077
env_file="$(mktemp "${RUNNER_TEMP:-/tmp}/spyboxd-compose-smoke.XXXXXX.env")"
readonly env_file
declare -ar compose=(
    docker compose
    --project-name "${project_name}"
    --env-file "${env_file}"
    -f docker-compose.yml
    -f deploy/docker-compose.ci.yml
)

cleanup() {
    local status="$?"
    trap - EXIT

    if (( status != 0 )); then
        printf '%s\n' 'Compose smoke failed; collecting bounded container diagnostics.' >&2
        timeout --signal=TERM --kill-after=5s 20s \
            "${compose[@]}" ps --all >&2 || true
        timeout --signal=TERM --kill-after=5s 30s \
            "${compose[@]}" logs --no-color --tail 200 postgres api frontend >&2 || true
    fi

    timeout --signal=TERM --kill-after=10s 90s \
        "${compose[@]}" down --volumes --remove-orphans --timeout 10 >&2 || true
    rm -f -- "${env_file}"
    exit "${status}"
}
trap cleanup EXIT

{
    printf 'POSTGRES_PASSWORD=ci-%s-%s-%s\n' \
        "${GITHUB_RUN_ID:-local}" "${GITHUB_RUN_ATTEMPT:-1}" "${RANDOM}"
    printf '%s\n' \
        'FRONTEND_URL=http://frontend:3000' \
        'CORS_ALLOWED_ORIGINS=http://frontend:3000' \
        'NEXT_PUBLIC_API_BASE_URL=http://api:8000' \
        'NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_live_Y2xlcmsuZXhhbXBsZS50ZXN0JA=='
    # Deliberately non-secret build sentinel, split to avoid resembling a credential.
    printf 'CLERK_SECRET_KEY=sk_%s_%s\n' \
        live 'Y2xlcmsuZXhhbXBsZS50ZXN0JA=='
    printf '%s\n' \
        'NEXT_PUBLIC_CLERK_SIGN_IN_URL=/sign-in' \
        'NEXT_PUBLIC_CLERK_SIGN_UP_URL=/sign-up' \
        'NEXT_PUBLIC_CLERK_SIGN_IN_FALLBACK_REDIRECT_URL=/' \
        'NEXT_PUBLIC_CLERK_SIGN_UP_FALLBACK_REDIRECT_URL=/'
} >"${env_file}"

expected_frontend_build_id="$(<frontend/.next/BUILD_ID)"
[[ -n "${expected_frontend_build_id}" && "${expected_frontend_build_id}" != *$'\n'* ]]

# Keep the normal developer Compose Dockerfile valid even though this CI smoke
# packages the already-built artifact through the prebuilt runtime Dockerfile.
timeout --signal=TERM --kill-after=5s 30s \
    docker build --check -f frontend/Dockerfile .

timeout --signal=TERM --kill-after=30s 12m \
    "${compose[@]}" build --pull api frontend

timeout --signal=TERM --kill-after=30s 5m \
    "${compose[@]}" up --detach --wait --wait-timeout 180 postgres api frontend

# The RSS worker intentionally stays out of this smoke: contacting Letterboxd
# is not needed to validate the production container graph.
if "${compose[@]}" ps --all --services | grep -Fqx 'rss-poller'; then
    printf '%s\n' 'The Compose smoke unexpectedly started rss-poller.' >&2
    exit 1
fi

timeout --signal=TERM --kill-after=5s 30s \
    "${compose[@]}" exec -T api python - <<'PY'
import json
import urllib.request

with urllib.request.urlopen("http://localhost:8000/ready", timeout=5) as response:
    report = json.load(response)

assert report["status"] == "ready", report
assert report["checks"] == {"database": "ok", "schema": "current"}, report
assert report["schema"]["current_revisions"], report
PY

expected_heads="$({
    timeout --signal=TERM --kill-after=5s 30s \
        "${compose[@]}" exec -T api python - <<'PY'
from services.operational_health import repository_schema_heads

print("\n".join(sorted(repository_schema_heads())))
PY
} | tr -d '\r')"
current_heads="$({
    timeout --signal=TERM --kill-after=5s 30s \
        "${compose[@]}" exec -T postgres \
        psql --username spyboxd --dbname spyboxd --tuples-only --no-align \
        --command 'SELECT version_num FROM alembic_version ORDER BY version_num'
} | tr -d '\r')"

[[ -n "${expected_heads}" && "${current_heads}" == "${expected_heads}" ]]
[[ "$(timeout --signal=TERM --kill-after=5s 30s \
    "${compose[@]}" exec -T postgres \
    psql --username spyboxd --dbname spyboxd --tuples-only --no-align \
    --command "SELECT to_regclass('public.profiles') IS NOT NULL" | tr -d '[:space:]')" == t ]]

timeout --signal=TERM --kill-after=5s 30s \
    "${compose[@]}" exec -T frontend \
    wget --quiet --output-document=/dev/null http://localhost:3000/

container_frontend_build_id="$({
    timeout --signal=TERM --kill-after=5s 30s \
        "${compose[@]}" exec -T frontend \
        sh -c 'cat /app/.next/BUILD_ID'
} | tr -d '\r\n')"
[[ "${container_frontend_build_id}" == "${expected_frontend_build_id}" ]]

printf '%s\n' 'Compose startup smoke passed: artifact packaged, services healthy, and migrations reached head.'
