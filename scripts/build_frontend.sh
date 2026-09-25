#!/bin/sh
# D2B: build the compiled React SPA that the Python server now serves by default.
#
# This is the documented production sequence from RUNBOOK.md 0.2 and nothing more:
# the three build steps plus one verification. There is deliberately no deployment
# system here - no service manager, no pipeline, no rollback logic. Rollback is one
# environment variable (WB_EDITOR_FRONTEND=legacy) and needs no rebuild at all.
#
# `npm ci` (not `npm install`) installs exactly the committed lockfile, so the
# build is reproducible.
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root/frontend"

npm ci
npm run build

# The server refuses to start without this file, so failing here gives the same
# guarantee at build time rather than at the editor's first click.
if [ ! -f dist/index.html ]; then
    echo "build_frontend: frontend/dist/index.html is missing after npm run build" >&2
    exit 1
fi

echo "build_frontend: ok - $(pwd)/dist/index.html"