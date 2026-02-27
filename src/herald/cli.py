"""Command-line interface for herald."""

import argparse
import asyncio
import logging
import os
import sys

from herald.sender import resolve_recipients, send


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="herald",
        description="Secure desktop notifications from root to user sessions",
    )
    sub = parser.add_subparsers(dest="command")

    # -- herald send --
    sp = sub.add_parser("send", help="Send a notification (requires root)")
    sp.add_argument("title", help="Notification title")
    sp.add_argument("body", nargs="?", default="", help="Notification body")
    sp.add_argument("--urgency", choices=("low", "normal", "critical"),
                    default="normal", help="Urgency level (default: normal)")
    sp.add_argument("--icon", default="", help="FreeDesktop icon name")
    sp.add_argument("--timeout", type=int, default=-1,
                    help="Display timeout in ms (-1 = server default, 0 = persistent)")

    target = sp.add_mutually_exclusive_group(required=True)
    target.add_argument("--users", nargs="+", metavar="USER",
                        help="Send to specific users")
    target.add_argument("--group", nargs="+", metavar="GROUP",
                        help="Send to all members of Unix groups")
    target.add_argument("--everyone", action="store_true",
                        help="Send to all human users")

    # -- herald receive --
    sub.add_parser("receive", help="Watch for and display notifications")

    return parser


def main(argv=None):
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "send":
        if os.getuid() != 0:
            print("herald send: must be run as root", file=sys.stderr)
            sys.exit(1)

        logging.basicConfig(level=logging.WARNING, format="%(message)s")

        try:
            recipients = resolve_recipients(
                users=args.users,
                groups=args.group,
                everyone=args.everyone,
            )
        except ValueError as e:
            print(f"herald send: {e}", file=sys.stderr)
            sys.exit(1)

        count = send(
            title=args.title,
            body=args.body,
            urgency=args.urgency,
            icon=args.icon,
            timeout=args.timeout,
            recipients=recipients,
        )
        print(f"Sent to {count} user(s)")

    elif args.command == "receive":
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
        )

        from herald.receiver import run

        asyncio.run(run())
