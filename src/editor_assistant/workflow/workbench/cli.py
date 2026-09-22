"""workbench subcommand: launch the M3A Editorial Workbench HTTP server.

Usage (two equivalent forms):
  PYTHONPATH=src python3 -m editor_assistant.workflow.workbench [--host HOST] [--port PORT]
  PYTHONPATH=src python3 -m editor_assistant.workflow.cli workbench [--host HOST] [--port PORT]

Default bind is 127.0.0.1:8123. --host is opt-in with a printed warning; there is
no auth on this MVP. POST /quit is refused unless WB_ALLOW_QUIT=1 / --allow-quit.
"""

from __future__ import annotations

from editor_assistant.workflow.workbench.__main__ import main as workbench_main


def add_workbench_subcommand(sub):
    """Register the `workbench` subcommand onto an existing argparse subparsers object."""
    p = sub.add_parser(
        "workbench",
        help="launch the M3A Editor Workbench HTTP server (Bulgarian-first UI, localhost only)",
    )
    p.add_argument(
        "--host",
        default="127.0.0.1",
        help="bind host (default 127.0.0.1; opt-in — no auth on this MVP)",
    )
    p.add_argument(
        "--port",
        type=int,
        default=None,
        help="bind port (default 8123; also settable via WB_PORT)",
    )
    p.add_argument(
        "--allow-quit",
        action="store_true",
        default=False,
        help="honor POST /quit (test-only; off by default)",
    )
    p.set_defaults(func=_workbench_cmd)
    return p


def _workbench_cmd(args):
    sys_argv = []
    if args.host != "127.0.0.1":
        sys_argv.append("--host")
        sys_argv.append(args.host)
    if args.port is not None:
        sys_argv.append("--port")
        sys_argv.append(str(args.port))
    if args.allow_quit:
        sys_argv.append("--allow-quit")
    workbench_main(argv=sys_argv)
