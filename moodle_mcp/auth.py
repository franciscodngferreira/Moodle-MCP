"""Guided token setup for SSO Moodle instances (e.g. ETH edu-ID).

ETH logs in via SSO, so login/token.php with a password does not work. Instead
the Moodle mobile launch flow runs the login in the browser (where SSO works)
and hands back a token via a ``moodlemobile://token=<base64>`` redirect.

    moodle-mcp auth
        |
        v  open browser -> launch.php (SSO happens here)
        |  user pastes the moodlemobile://token=... redirect
        v  parse_pasted_token(): strip scheme, base64-decode, take field 1
        |  validate via site_info()
        v  store token in OS keyring

Non-interactive: ``moodle-mcp auth --token <wstoken-or-base64-or-redirect>``.
"""
from __future__ import annotations

import base64
import binascii
import random
import sys
import webbrowser

from . import config
from .client import MoodleAuthError, MoodleClient, MoodleError

_HEX32 = __import__("re").compile(r"^[0-9a-f]{32}$", __import__("re").I)


def launch_url() -> str:
    passport = random.randint(1000, 9_999_999)
    return (
        f"{config.base_url()}/admin/tool/mobile/launch.php"
        f"?service={config.MOBILE_SERVICE}&passport={passport}&urlscheme=moodlemobile"
    )


def parse_pasted_token(raw: str) -> str:
    """Extract the wstoken from whatever the user pasted.

    Accepts: a bare wstoken (32 hex), a ``moodlemobile://token=<b64>`` redirect,
    a ``token=<b64>`` fragment, or the raw base64 blob. The base64 decodes to
    ``signature:::token[:::privatetoken]``; we return the middle field.
    """
    raw = (raw or "").strip().strip('"').strip("'")
    if "token=" in raw:
        raw = raw.split("token=", 1)[1].strip()
    raw = raw.replace("%3D", "=").replace("%3d", "=")

    if _HEX32.match(raw):
        return raw  # already the decoded wstoken

    try:
        decoded = base64.b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", "replace")
    except (binascii.Error, ValueError) as exc:
        raise MoodleAuthError(f"Could not parse pasted value: {exc}")
    if ":::" in decoded:
        return decoded.split(":::")[1]
    if _HEX32.match(decoded.strip()):
        return decoded.strip()
    raise MoodleAuthError(
        "Pasted value did not contain a recognizable token. Paste the full "
        "moodlemobile://token=... redirect."
    )


def validate_and_store(token: str) -> dict:
    """Validate a token against Moodle, store it in the keyring, return site info."""
    client = MoodleClient(token)
    info = client.site_info()  # raises MoodleAuthError if the token is bad
    client.close()
    config.set_token(token)
    return info


def run_auth(token_arg: str | None = None) -> int:
    """CLI entry for `moodle-mcp auth`. Returns a process exit code."""
    if token_arg:
        raw = token_arg
    else:
        url = launch_url()
        print("ETH Moodle uses SSO, so we capture a token via the browser.\n")
        print("1. A browser window will open (log in with SSO if prompted).")
        print("2. At the end it tries to open 'moodlemobile://token=...'. That will")
        print("   fail/prompt — that's fine. Copy that whole URL from the address bar,")
        print("   or from DevTools (Ctrl+Shift+I -> Network) find the launch.php")
        print("   response containing 'token='.")
        print(f"\n   Launch URL: {url}\n")
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            print("(Could not auto-open a browser — paste the URL above manually.)")
        raw = input("\nPaste the moodlemobile://token=... value here: ").strip()

    try:
        token = parse_pasted_token(raw)
        info = validate_and_store(token)
    except MoodleAuthError as exc:
        print(f"\nAuth failed: {exc}", file=sys.stderr)
        return 1
    except MoodleError as exc:
        print(f"\nCould not reach Moodle: {exc}", file=sys.stderr)
        return 2

    print(
        f"\nToken stored in keyring. Logged in as "
        f"{info.get('fullname') or info.get('username')} (userid {info.get('userid')})."
    )
    return 0
