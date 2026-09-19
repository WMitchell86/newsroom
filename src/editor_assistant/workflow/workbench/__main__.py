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
    main()
