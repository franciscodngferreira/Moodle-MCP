"""CLI entry point.

    moodle-mcp auth [--token X]   set up / store the Moodle token
    moodle-mcp doctor            verify the stored token + list available functions
    moodle-mcp serve             run the MCP server over stdio (default)
"""
from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(prog="moodle-mcp", description="Moodle Study MCP")
    sub = parser.add_subparsers(dest="cmd")

    p_auth = sub.add_parser("auth", help="store your Moodle token (guided)")
    p_auth.add_argument("--token", help="token / base64 / moodlemobile:// redirect", default=None)

    sub.add_parser("doctor", help="check the stored token and list functions")
    sub.add_parser("serve", help="run the MCP server (stdio)")

    args = parser.parse_args()

    if args.cmd == "auth":
        from .auth import run_auth

        raise SystemExit(run_auth(args.token))

    if args.cmd == "doctor":
        raise SystemExit(_doctor())

    # default: run the server
    from .server import main as serve_main

    serve_main()


def _doctor() -> int:
    from . import config
    from .client import MoodleClient, MoodleError

    token = config.get_token()
    if not token:
        print("No token stored. Run `moodle-mcp auth`.", file=sys.stderr)
        return 1
    try:
        client = MoodleClient(token)
        info = client.site_info()
    except MoodleError as exc:
        print(f"Token check failed: {exc}", file=sys.stderr)
        return 2
    print(f"OK: {info.get('fullname')} (userid {info.get('userid')})")
    print(f"Site: {info.get('sitename')}  release {info.get('release')}")
    wanted = [
        "core_enrol_get_users_courses",
        "core_course_get_contents",
        "mod_quiz_get_quizzes_by_courses",
        "mod_quiz_get_user_attempts",
        "core_calendar_get_action_events_by_timesort",
    ]
    print("Functions:")
    for fn in wanted:
        print(f"  {'yes' if client.has_function(fn) else 'NO '}  {fn}")
    client.close()
    return 0


if __name__ == "__main__":
    main()
