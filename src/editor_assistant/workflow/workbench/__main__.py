"""M3A Editor Workbench entry point.

Usage:
  PYTHONPATH=src python3 -m editor_assistant.workflow.workbench [--host HOST] [--port PORT]
  PYTHONPATH=src python3 -m editor_assistant.workflow.workbench --help

Default bind is 127.0.0.1 (localhost only). Use --host only with awareness that
there is no auth on this MVP.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading

from editor_assistant.workflow.workbench import http


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="workbench",
        description="M3A Editor Workbench — Bulgarian-first browser UI over the frozen editorial workflow.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="bind host (default 127.0.0.1; use only with awareness that there is no auth)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("WB_PORT", "8123")),
        help="bind port (default 8123; also settable via WB_PORT)",
    )
    parser.add_argument(
        "--allow-quit",
        action="store_true",
        default=os.environ.get("WB_ALLOW_QUIT", "0") not in ("0", "", "no", "false"),
        help="honor POST /quit (test-only; off by default)",
    )
    args = parser.parse_args(argv)

    if args.host != "127.0.0.1":
        print(f"[workbench] WARNING: binding to {args.host} — no auth on this MVP", file=sys.stderr)

    # D1: report the frontend serving mode at startup so the running topology is
    # never a guess. A missing build is a loud startup error, not a surprise 503
    # on the editor's first click.
    if http.spa_mod.is_spa_enabled():
        if http.spa_mod.build_available():
            print(
                f"[workbench] frontend mode: spa (serving {http.spa_mod.index_path()})",
                file=sys.stderr,
            )
        else:
            print(
                f"[workbench] ERROR: {http.spa_mod.FRONTEND_MODE_ENV}=spa but no compiled "
                f"build at {http.spa_mod.index_path()}. Run `npm ci && npm run build` in "
                f"frontend/, or set {http.spa_mod.FRONTEND_MODE_ENV}=legacy.",
                file=sys.stderr,
            )
            return 2
    else:
        print("[workbench] frontend mode: legacy (server-rendered Workbench)", file=sys.stderr)

    server = http.serve(args.port, host=args.host, quit_allowed=args.allow_quit)

    stop = threading.Event()

    def _handle_sig(sig, frame):
        stop.set()
        try:
            server.shutdown()
        except Exception:  # noqa: BLE001, S110 - signal-time shutdown is best-effort
            pass

    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    print(f"[workbench] serving http://{args.host}:{args.port}/", file=sys.stderr)
    print(
        f"[workbench] quit endpoint {'enabled' if args.allow_quit else 'disabled'}", file=sys.stderr
    )

    server.serve_forever()


if __name__ == "__main__":
    sys.exit(main() or 0)
