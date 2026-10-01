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
#
# `mkdir -p var/cron` below is for a HUMAN or a test running this by hand. It
# does NOT rescue a cron job: the shell opens the crontab's `>> var/cron/x.log`
# redirect BEFORE it executes this script, so that line runs too late. When the
# log directory is missing the job dies at the redirect with no output at all,
# which is why the crontab lines create the directory themselves.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"
set -a
. ./.env
set +a
export PYTHONPATH=src
mkdir -p var/cron
exec python3 -m editor_assistant.workflow.cli "$@"
