#!/usr/bin/env bash
# Start or stop the integration test dependencies (deploy/compose/compose.test.yaml):
# Postgres on 9121, Redis on 9122 and the Floci AWS emulator on 9123.
#
#   scripts/test-deps.sh        start, wait until ready, print the environment to export
#   scripts/test-deps.sh down   stop and delete their data
#   scripts/test-deps.sh env    print the environment only
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
compose=(docker compose -p agentstudio-test -f deploy/compose/compose.test.yaml)
pg_port="${AGENTSTUDIO_TEST_PG_PORT:-9121}"
redis_port="${AGENTSTUDIO_TEST_REDIS_PORT:-9122}"
floci_port="${AGENTSTUDIO_TEST_FLOCI_PORT:-9123}"

print_env() {
  cat <<ENV
export TEST_DATABASE_URL=postgresql+asyncpg://agentstudio:agentstudio@127.0.0.1:${pg_port}/agentstudio_test
export TEST_REDIS_URL=redis://127.0.0.1:${redis_port}/0
export TEST_AWS_ENDPOINT_URL=http://127.0.0.1:${floci_port}
ENV
}

case "${1:-up}" in
  up)
    "${compose[@]}" up -d --wait postgres redis
    "${compose[@]}" up -d floci
    # The emulator image has no HTTP client for a healthcheck, so poll it from here.
    for _ in $(seq 1 60); do
      if curl -fsS -o /dev/null "http://127.0.0.1:${floci_port}/"; then
        print_env
        exit 0
      fi
      sleep 1
    done
    echo "test-deps: floci did not answer on port ${floci_port}" >&2
    exit 1
    ;;
  down)
    "${compose[@]}" down -v --remove-orphans
    ;;
  env)
    print_env
    ;;
  *)
    echo "usage: $0 [up|down|env]" >&2
    exit 2
    ;;
esac
