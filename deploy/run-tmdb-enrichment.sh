#!/usr/bin/env bash
set -Eeuo pipefail

readonly APP_ROOT="${SPYBOXD_APP_ROOT:-/opt/spyboxd}"
readonly CURRENT_LINK="${SPYBOXD_CURRENT_LINK:-${APP_ROOT}/current}"

bounded_positive_integer() {
    local name="$1" value="$2" maximum="$3"
    [[ "${value}" =~ ^[1-9][0-9]*$ ]] \
        || { printf '[spyboxd-tmdb] %s must be a positive integer\n' "${name}" >&2; exit 64; }
    (( value <= maximum )) \
        || { printf '[spyboxd-tmdb] %s must not exceed %s\n' "${name}" "${maximum}" >&2; exit 64; }
    printf '%s\n' "${value}"
}

LIMIT="$(bounded_positive_integer TMDB_ENRICHMENT_LIMIT "${TMDB_ENRICHMENT_LIMIT:-50}" 100)"
BATCH_SIZE="$(bounded_positive_integer TMDB_ENRICHMENT_BATCH_SIZE "${TMDB_ENRICHMENT_BATCH_SIZE:-10}" 100)"
CACHE_DAYS="$(bounded_positive_integer TMDB_CACHE_DAYS "${TMDB_CACHE_DAYS:-30}" 365)"
REGION="$(printf '%s' "${TMDB_DEFAULT_REGION:-DE}" | tr '[:lower:]' '[:upper:]')"
LANGUAGE="${TMDB_LANGUAGE:-en-US}"
readonly LIMIT BATCH_SIZE CACHE_DAYS REGION LANGUAGE

[[ "${REGION}" =~ ^[A-Z]{2}$ ]] \
    || { printf '[spyboxd-tmdb] TMDB_DEFAULT_REGION must be a two-letter country code\n' >&2; exit 64; }
[[ "${LANGUAGE}" =~ ^[A-Za-z]{2}(-[A-Za-z]{2})?$ ]] \
    || { printf '[spyboxd-tmdb] TMDB_LANGUAGE must resemble en or en-US\n' >&2; exit 64; }
[[ -x "${CURRENT_LINK}/.venv/bin/python" && -f "${CURRENT_LINK}/scripts/enrich_tmdb.py" ]] \
    || { printf '[spyboxd-tmdb] the active release is incomplete\n' >&2; exit 1; }

printf '[spyboxd-tmdb] enriching at most %s stale or missing movies for region %s\n' "${LIMIT}" "${REGION}"
exec "${CURRENT_LINK}/.venv/bin/python" \
    "${CURRENT_LINK}/scripts/enrich_tmdb.py" \
    --region "${REGION}" \
    --language "${LANGUAGE}" \
    --cache-days "${CACHE_DAYS}" \
    --batch-size "${BATCH_SIZE}" \
    --limit "${LIMIT}"
