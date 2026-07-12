"""Moodle Web Services REST client.

Every request goes through ONE chokepoint, ``_call``, which:
  - appends the token + ``moodlewsrestformat=json``,
  - flattens nested list/dict params into Moodle's ``key[0][name]`` form,
  - parses the body for an exception EVEN ON HTTP 200 (Moodle returns errors
    with a 200 status + an ``exception``/``errorcode`` JSON body — the single
    biggest gotcha of this API),
  - retries transient network failures with backoff,
  - raises a typed exception, never a bare Exception.

    request                     _call()                         Moodle
   ----------   flatten+token   ------------------   POST form   ----------
   wsfunction ---------------->  server.php?...     ----------->  REST API
                                     |  parse JSON body
                                     |  exception? -> raise typed
                                     v  else -> return dict/list
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx

from . import config


class MoodleError(Exception):
    """Base class for all Moodle client errors."""


class MoodleAuthError(MoodleError):
    """Token is missing, invalid, or expired (errorcode invalidtoken)."""


class MoodleFunctionUnavailable(MoodleError):
    """The web service function is not exposed to this token/service."""


class MoodleAPIError(MoodleError):
    """Network failure, non-200 status, malformed body, or other API error."""


# errorcodes that mean "your token is bad" -> re-auth.
_AUTH_ERRORCODES = {"invalidtoken", "invalidlogin", "accessexception:tokennotfound"}
# errorcodes that mean "this function isn't available to you".
_UNAVAILABLE_ERRORCODES = {
    "accessexception",
    "webservicerequireslogin",
    "servicenotavailable",
    "functionnotenabled",
}


def flatten_params(obj: Any, prefix: str = "") -> dict[str, str]:
    """Flatten nested dict/list params into Moodle's REST wire format.

    ``{"courseids": [23189]}`` -> ``{"courseids[0]": "23189"}``
    ``{"options": [{"name": "x", "value": 1}]}``
        -> ``{"options[0][name]": "x", "options[0][value]": "1"}``
    Booleans become ``"1"``/``"0"``; everything else is stringified.
    """
    out: dict[str, str] = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            child = f"{prefix}[{key}]" if prefix else str(key)
            out.update(flatten_params(value, child))
    elif isinstance(obj, (list, tuple)):
        for i, value in enumerate(obj):
            out.update(flatten_params(value, f"{prefix}[{i}]"))
    elif isinstance(obj, bool):
        out[prefix] = "1" if obj else "0"
    elif obj is None:
        pass  # omit None params entirely
    else:
        out[prefix] = str(obj)
    return out


class MoodleClient:
    def __init__(
        self,
        token: str,
        base_url: str | None = None,
        *,
        timeout: float = 30.0,
        max_retries: int = 3,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not token:
            raise MoodleAuthError("No token provided. Run `moodle-mcp auth` first.")
        self.token = token
        self.base_url = (base_url or config.base_url()).rstrip("/")
        self.max_retries = max_retries
        self._client = http_client or httpx.Client(timeout=timeout, follow_redirects=True)
        self._owns_client = http_client is None
        self._site_info: dict[str, Any] | None = None
        self._functions: set[str] | None = None

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "MoodleClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- the one chokepoint ------------------------------------------------
    def _call(self, wsfunction: str, **params: Any) -> Any:
        """Call a web service function. Raises a typed MoodleError on failure."""
        data = flatten_params(params)
        data.update(
            wstoken=self.token,
            wsfunction=wsfunction,
            moodlewsrestformat="json",
        )
        endpoint = f"{self.base_url}/webservice/rest/server.php"

        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = self._client.post(endpoint, data=data)
            except httpx.HTTPError as exc:  # network/timeout/transport
                last_exc = exc
                if attempt < self.max_retries - 1:
                    time.sleep(0.5 * (2**attempt))
                    continue
                raise MoodleAPIError(
                    f"{wsfunction}: network error after {self.max_retries} tries: {exc}"
                ) from exc

            if resp.status_code != 200:
                raise MoodleAPIError(f"{wsfunction}: HTTP {resp.status_code}")

            # Moodle can return an empty body for void functions.
            if not resp.content:
                return None
            try:
                body = resp.json()
            except ValueError as exc:
                raise MoodleAPIError(f"{wsfunction}: malformed JSON body") from exc

            self._raise_if_exception(wsfunction, body)
            return body

        # Unreachable, but keeps type checkers happy.
        raise MoodleAPIError(f"{wsfunction}: exhausted retries") from last_exc

    @staticmethod
    def _raise_if_exception(wsfunction: str, body: Any) -> None:
        """Moodle signals errors as a dict with an ``exception`` key, HTTP 200."""
        if not isinstance(body, dict) or "exception" not in body:
            return
        errorcode = str(body.get("errorcode", "")).lower()
        message = body.get("message", body.get("exception", "unknown error"))
        if errorcode in _AUTH_ERRORCODES:
            raise MoodleAuthError(f"{wsfunction}: {message} (re-run `moodle-mcp auth`)")
        if errorcode in _UNAVAILABLE_ERRORCODES:
            raise MoodleFunctionUnavailable(f"{wsfunction}: {message}")
        raise MoodleAPIError(f"{wsfunction}: {message} [{errorcode}]")

    # -- discovery ---------------------------------------------------------
    def site_info(self, *, refresh: bool = False) -> dict[str, Any]:
        """Cached ``core_webservice_get_site_info`` (functions + userid)."""
        if self._site_info is None or refresh:
            self._site_info = self._call("core_webservice_get_site_info")
            self._functions = {
                f["name"] for f in self._site_info.get("functions", []) if "name" in f
            }
        return self._site_info

    def available_functions(self) -> set[str]:
        if self._functions is None:
            self.site_info()
        return self._functions or set()

    def has_function(self, name: str) -> bool:
        return name in self.available_functions()

    @property
    def userid(self) -> int:
        return int(self.site_info()["userid"])

    # -- domain calls ------------------------------------------------------
    def get_users_courses(self, userid: int | None = None) -> list[dict[str, Any]]:
        return self._call(
            "core_enrol_get_users_courses", userid=userid or self.userid
        )

    def get_course_contents(self, courseid: int) -> list[dict[str, Any]]:
        return self._call("core_course_get_contents", courseid=courseid)

    def get_quizzes_by_courses(self, courseids: list[int]) -> dict[str, Any]:
        return self._call("mod_quiz_get_quizzes_by_courses", courseids=courseids)

    def get_user_quiz_attempts(self, quizid: int, userid: int | None = None) -> dict[str, Any]:
        return self._call(
            "mod_quiz_get_user_attempts",
            quizid=quizid,
            userid=userid or self.userid,
            status="all",
        )

    def get_upcoming_events(self, timesortfrom: int | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if timesortfrom is not None:
            params["timesortfrom"] = timesortfrom
        return self._call("core_calendar_get_action_events_by_timesort", **params)

    # -- file download -----------------------------------------------------
    def download_file(self, fileurl: str, dest: Path) -> Path:
        """Download a webservice pluginfile URL, appending the token.

        ``fileurl`` from ``core_course_get_contents`` points at
        ``/webservice/pluginfile.php/...`` and needs ``?token=<wstoken>``.
        """
        sep = "&" if "?" in fileurl else "?"
        url = f"{fileurl}{sep}token={self.token}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    raise MoodleAPIError(f"download {fileurl}: HTTP {resp.status_code}")
                with open(dest, "wb") as fh:
                    for chunk in resp.iter_bytes():
                        fh.write(chunk)
        except httpx.HTTPError as exc:
            # Do NOT interpolate exc (its message can contain the tokened request
            # URL). Report the caller-supplied (untokened) fileurl + error type.
            raise MoodleAPIError(f"download {fileurl}: {type(exc).__name__}") from exc
        return dest
