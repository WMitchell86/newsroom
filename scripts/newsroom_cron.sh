#!/bin/sh
# The newsroom's scheduled work, one entry point.
#
# V1.2-G4.5. The env is loaded by the SHELL and never by `env $(cat .env)`:
# command substitution does not strip quotes, so that form hands the process
# keys with the quotes still attached and every provider call fails while the
# summary claims the work was done. This exact failure is why a real run on
# 2026-09-28 recorded `semanticDegradedUnavailable: 5` with every counter
# looking fine - the process had no usable key and said nothing about it.
#
# Every scheduled task goes through here so that cannot happen per-job.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"
set -a
. ./.env
set +a
export PYTHONPATH=src
mkdir -p var/cron
exec python3 -m editor_assistant.workflow.cli "$@"
