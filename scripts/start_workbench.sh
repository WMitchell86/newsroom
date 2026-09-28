#!/bin/sh
# Start the Editorial Workbench with the real .env.
#
# The env must be loaded by the SHELL, not by `env $(grep . .env)`: command
# substitution does not remove quotes, so that form hands the process
# GEMINI_API_KEY="AIza..." WITH the double quotes still attached. Gemini then
# rejects it as an invalid key and every model call fails with HTTP 400 while
# the error the editor sees claims the source is unavailable.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"
set -a
. ./.env
set +a
export PYTHONPATH=src
exec python3 -m editor_assistant.workflow.cli workbench --port "${WB_PORT:-8123}"
