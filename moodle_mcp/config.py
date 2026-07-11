"""Central configuration and secret storage.

Host is overridable via the MOODLE_URL env var; defaults to ETH.
The wstoken lives ONLY in the OS keyring — never in code, env, or the cache.
"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_BASE_URL = "https://moodle-app2.let.ethz.ch"
MOBILE_SERVICE = "moodle_mobile_app"

# OS keyring coordinates for the token.
KEYRING_SERVICE = "moodle-mcp"
KEYRING_ACCOUNT = "wstoken"

CACHE_DIR = Path(os.environ.get("MOODLE_MCP_CACHE", Path.home() / ".moodle-mcp"))


def base_url() -> str:
    return os.environ.get("MOODLE_URL", DEFAULT_BASE_URL).rstrip("/")


def rest_endpoint() -> str:
    return f"{base_url()}/webservice/rest/server.php"


def get_token() -> str | None:
    """Read the stored token from the OS keyring. None if not set up."""
    import keyring

    return keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)


def set_token(token: str) -> None:
    import keyring

    keyring.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, token)


def delete_token() -> None:
    import keyring

    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
    except keyring.errors.PasswordDeleteError:
        pass
