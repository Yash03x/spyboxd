#!/usr/bin/env bash
# Provision the restore drill's dedicated PostgreSQL role and credential file.
#
# Run ONCE, as root, on the production VPS. Everything the nightly drill needs
# that automation deliberately cannot create for itself:
#
#   1. a `spyboxd_restore` role with CREATEDB and NOT superuser, so the drill
#      can build a scratch database to restore into while the application role
#      stays NOCREATEDB;
#   2. /etc/spyboxd/restore-drill.env holding that role's DATABASE_URL,
#      root-owned, grouped to the deploy account, mode 0640.
#
# The deploy account's sudo is scoped to systemctl/nginx/ufw on purpose, which
# is why the drill could never bootstrap itself — it failed on the missing file
# every night since it was written, and nobody was told because the schedule
# skips unless PRODUCTION_RESTORE_DRILL_ENABLED is set.
#
# Idempotent: re-running rotates the password and rewrites the file. It never
# touches the application role, the application database, or any data.

set -Eeuo pipefail

API_ENV=/etc/spyboxd/api.env
DRILL_ENV=/etc/spyboxd/restore-drill.env
DRILL_ROLE=spyboxd_restore
DEPLOY_ACCOUNT="${SPYBOXD_DEPLOY_ACCOUNT:-spyboxd-deploy}"

die() {
  printf '[provision-restore-drill] %s\n' "$1" >&2
  exit 1
}

[ "$(id -u)" -eq 0 ] || die 'run this as root: it writes /etc/spyboxd and creates a database role.'

for command_name in install psql python3 openssl getent; do
  command -v "${command_name}" >/dev/null 2>&1 \
    || die "required command not found: ${command_name}"
done

[ -f "${API_ENV}" ] && [ ! -L "${API_ENV}" ] \
  || die "${API_ENV} must exist and be a regular file"

deploy_group="$(getent group "$(id -gn "${DEPLOY_ACCOUNT}" 2>/dev/null || true)" >/dev/null 2>&1 \
  && id -gn "${DEPLOY_ACCOUNT}")" \
  || die "cannot resolve the deploy account's group; set SPYBOXD_DEPLOY_ACCOUNT"

# Reuse the application's host, port and database name — the drill reads the
# same database, it just connects as a role allowed to CREATE DATABASE. The URL
# is parsed rather than pattern-matched so a password containing '@' or '/'
# cannot split it wrongly.
read -r db_host db_port db_name <<EOF
$(python3 - "${API_ENV}" <<'PY'
import sys
from pathlib import Path
from urllib.parse import urlsplit

url = None
for raw in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if line.startswith("export "):
        line = line[7:].lstrip()
    key, separator, value = line.partition("=")
    if separator and key.strip() == "DATABASE_URL":
        url = value.strip().strip('"').strip("'")
if not url:
    raise SystemExit("api.env has no DATABASE_URL")
parts = urlsplit(url)
if not parts.hostname or not parts.path.lstrip("/"):
    raise SystemExit("api.env DATABASE_URL is missing a host or database name")
print(parts.hostname, parts.port or 5432, parts.path.lstrip("/"))
PY
)
EOF

[ -n "${db_name}" ] || die 'could not read the production database name from api.env'

password="$(openssl rand -base64 33 | tr -d '\n=+/' | cut -c1-32)"
[ "${#password}" -ge 24 ] || die 'failed to generate a sufficiently long password'

# CREATEDB so the drill can build its scratch database; NOSUPERUSER because the
# drill refuses a superuser outright, and a backup verifier has no business
# holding one. CONNECT is all it needs on the production database itself.
# Values arrive on stdin via \set rather than as -v arguments: argv is world
# readable through ps, and one of these is a password. The CREATE is written as
# a generated statement run through \gexec because psql does not interpolate
# its variables inside a dollar-quoted DO block — there, `:'role'` would be
# taken literally and the role would be created with that name.
psql -v ON_ERROR_STOP=1 --quiet --no-psqlrc <<SQL
\set role '${DRILL_ROLE}'
\set password '${password}'
\set dbname '${db_name}'

SELECT format('CREATE ROLE %I LOGIN CREATEDB NOSUPERUSER', :'role')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'role')
\gexec

ALTER ROLE :"role" WITH LOGIN CREATEDB NOSUPERUSER PASSWORD :'password';
GRANT CONNECT ON DATABASE :"dbname" TO :"role";
SQL

# Written via a 0600 temp file in the same directory and moved into place, so
# the credential is never briefly world-readable.
umask 077
temp_env="$(mktemp /etc/spyboxd/.restore-drill.env.XXXXXX)"
trap 'rm -f -- "${temp_env}"' EXIT
printf 'DATABASE_URL=postgresql+psycopg://%s:%s@%s:%s/%s\n' \
  "${DRILL_ROLE}" "${password}" "${db_host}" "${db_port}" "${db_name}" >"${temp_env}"
install -o root -g "${deploy_group}" -m 0640 "${temp_env}" "${DRILL_ENV}"
rm -f -- "${temp_env}"
trap - EXIT

printf '[provision-restore-drill] %s is ready, owned root:%s mode 0640.\n' \
  "${DRILL_ENV}" "${deploy_group}"
printf '[provision-restore-drill] Now enable the nightly schedule:\n'
printf '  gh variable set PRODUCTION_RESTORE_DRILL_ENABLED --body true\n'
printf '[provision-restore-drill] Then prove it end to end:\n'
printf '  gh workflow run "PostgreSQL Restore Drill"\n'
