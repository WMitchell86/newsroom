"""M3A Editor Workbench entry point.

Usage:
  PYTHONPATH=src python3 -m editor_assistant.workflow.workbench [--host HOST] [--port PORT]
  PYTHONPATH=src python3 -m editor_assistant.workflow.workbench --help

Default bind is 127.0.0.1 (localhost only). Use --host only with awareness that
there is no auth on this MVP.
"""

from __future__ import annotations

import argparse
import logging
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

    # V1.2-G4.6: request logging. The workbench printed three startup lines and
    # then said nothing, so an editor click was invisible until model usage
    # records appeared - which is a downstream trace, and it cannot show a click
    # that never reached a model at all. Debugging "I clicked and nothing
    # happened" was guesswork for exactly that reason.
    #
    # INFO on the workbench logger, stderr, so it interleaves with the startup
    # lines in the same terminal. WB_LOG_LEVEL=DEBUG raises the detail for
    # whoever is chasing a single request. The Idempotency-Key is never logged.
    logging.basicConfig(
        level=getattr(logging, os.environ.get("WB_LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="[api] %(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    # A damaged ledger must never stop the editor from starting: the worst case
    # is a lost history, which is exactly what it already was.
    from editor_assistant.workflow import story_operations

    try:
        restored = story_operations.load_ledger()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        restored = 0
        print(f"[workbench] operation history not restored: {exc}", file=sys.stderr)
    if restored:
        print(
            f"[workbench] restored {restored} operation(s) from the previous run",
            file=sys.stderr,
        )

    # D2B: the editor frontend is reported at startup so the running topology is
    # never a guess. An invalid mode is a loud configuration failure and a
    # missing build is a loud deployment failure — neither ever silently becomes
    # a different editor than the one that was configured.
    try:
        mode = http.spa_mod.validate_frontend_mode()
    except http.spa_mod.FrontendConfigError as exc:
        print(f"[workbench] ERROR: {exc}", file=sys.stderr)
        return 2

    if mode == http.spa_mod.MODE_SPA:
        entry = http.spa_mod.index_path()
        if http.spa_mod.build_available():
            print(f"[workbench] Editor frontend: SPA (serving {entry})", file=sys.stderr)
        else:
            # D2B: the SPA is the default, so a missing build must be obvious
            # rather than quietly downgraded to the legacy Workbench.
            print(
                f"[workbench] ERROR: the default editor frontend (SPA) has no compiled "
                f"build at {entry}. Run `npm ci && npm run build` in frontend/, or set "
                f"{http.spa_mod.FRONTEND_MODE_ENV}=legacy.",
                file=sys.stderr,
            )
            return 2
    else:
        print(
            "[workbench] Editor frontend: legacy (server-rendered Workbench)",
            file=sys.stderr,
        )

    server = http.serve(args.port, host=args.host, quit_allowed=args.allow_quit)

    stop = threading.Event()

    def _handle_sig(sig, frame):
        stop.set()
        # `shutdown()` BLOCKS until `serve_forever()` returns, so calling it from
        # this handler deadlocks: a signal handler runs on the MAIN thread, which
        # is the very thread sitting inside `serve_forever()`. It waits for that
        # loop to notice, and the loop cannot progress because the main thread is
        # stuck here. Measured on 2026-10-02: the server ignored SIGTERM for
        # 15+ s and had to be SIGKILLed, parked in `futex_do_wait`.
        #
        # Handing the call to a separate thread breaks the cycle. This is the
        # same trick the /quit endpoint already uses (http.py::_quit).
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    print(f"[workbench] serving http://{args.host}:{args.port}/", file=sys.stderr)
    print(
        f"[workbench] quit endpoint {'enabled' if args.allow_quit else 'disabled'}", file=sys.stderr
    )

    server.serve_forever()


if __name__ == "__main__":
    sys.exit(main() or 0)
