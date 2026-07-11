"""FastMCP server exposing Moodle study tools to Claude.

The MCP fetches, counts, and categorizes. Claude does the reasoning. Tools are
thin wrappers over MoodleClient (live API) + cache (local corpus).

Tools:
    list_courses()                       -> enrolled courses
    get_course_overview(course)          -> categorized counts + raw items (detected)
    sync_course(course)                  -> download + extract into local corpus
    list_quizzes(course)                 -> quizzes + your attempt counts
    search_materials(query, course)      -> full-text search across synced text
    get_material(course, cid)            -> extracted text of one item
"""
from __future__ import annotations

import html
import time
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import cache, classify, config
from .client import (
    MoodleAuthError,
    MoodleClient,
    MoodleError,
    MoodleFunctionUnavailable,
)

mcp = FastMCP("moodle-study")

_client: MoodleClient | None = None
_courses_cache: list[dict[str, Any]] | None = None


def get_client() -> MoodleClient:
    """Build (once) a MoodleClient from the keyring token, retrying on network drop."""
    global _client
    if _client is not None:
        return _client
    token = config.get_token()
    if not token:
        raise MoodleAuthError(
            "No token stored. Run `python -m moodle_mcp auth` to set one up."
        )
    last: Exception | None = None
    for attempt in range(3):
        try:
            client = MoodleClient(token)
            client.site_info()  # validate + warm the function cache
            _client = client
            return client
        except MoodleAuthError:
            raise
        except MoodleError as exc:  # transient network / API — back off and retry
            last = exc
            time.sleep(2 * (attempt + 1))
    raise MoodleError(f"Could not reach Moodle after retries: {last}")


def _courses() -> list[dict[str, Any]]:
    global _courses_cache
    if _courses_cache is None:
        _courses_cache = get_client().get_users_courses()
    return _courses_cache


def _resolve_course(course: str | int) -> dict[str, Any]:
    """Resolve a course by numeric id or a case-insensitive name/shortname match."""
    courses = _courses()
    text = str(course).strip().lower()
    if text.isdigit():
        cid = int(text)
        for c in courses:
            if int(c["id"]) == cid:
                return c
    matches = [
        c for c in courses
        if text in c.get("shortname", "").lower() or text in c.get("fullname", "").lower()
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ValueError(f"No course matches '{course}'. Use list_courses to see options.")
    names = ", ".join(f"{c['id']}={c['shortname']}" for c in matches[:10])
    raise ValueError(f"'{course}' is ambiguous ({len(matches)} matches): {names}")


@mcp.tool()
def list_courses() -> list[dict[str, Any]]:
    """List your enrolled Moodle courses (id, shortname, fullname)."""
    return [
        {"id": c["id"], "shortname": c.get("shortname", ""), "fullname": c.get("fullname", "")}
        for c in _courses()
    ]


@mcp.tool()
def get_course_overview(course: str) -> dict[str, Any]:
    """Categorized picture of a course for exam planning.

    Returns detected counts (lectures / problem_sets / practice_exams / solutions
    / quizzes / other), the raw item list with each item's guessed category and
    confidence (so you can correct miscategorization), quizzes with attempt
    status, and upcoming deadlines. Counts are DETECTED, not authoritative.
    """
    client = get_client()
    c = _resolve_course(course)
    courseid = int(c["id"])
    contents = client.get_course_contents(courseid)

    items: list[dict[str, Any]] = []
    counts: dict[str, int] = {cat: 0 for cat in classify.CATEGORIES}

    def add(name: str, section_name: str, modname: str, cls: classify.Classification) -> None:
        counts[cls.category] = counts.get(cls.category, 0) + 1
        items.append({
            "name": name, "section": section_name, "modname": modname,
            "category": cls.category, "confidence": cls.confidence,
        })

    for section in contents:
        section_name = html.unescape(section.get("name", ""))
        for module in section.get("modules", []):
            modname = module.get("modname", "")
            mod_name = html.unescape(module.get("name", ""))
            file_contents = [c for c in (module.get("contents") or []) if c.get("type") == "file"]
            if file_contents:
                multi = len(file_contents) > 1
                for c in file_contents:
                    fn = c.get("filename", "")
                    cls = classify.classify_item(mod_name, fn, section_name, modname)
                    add(fn if multi else (mod_name or fn), section_name, modname, cls)
            else:
                add(mod_name, section_name, modname,
                    classify.classify_item(mod_name, "", section_name, modname))

    notes: list[str] = []
    quizzes = _quizzes_for(client, courseid, notes)
    deadlines = _deadlines_for(client, courseid, notes)

    return {
        "course": {"id": courseid, "shortname": c.get("shortname"), "fullname": c.get("fullname")},
        "counts_detected": counts,
        "items": items,
        "quizzes": quizzes,
        "deadlines": deadlines,
        "notes": notes + [
            "Counts are DETECTED by a filename heuristic - verify against the raw "
            "'items' list before relying on them."
        ],
    }


def _quizzes_for(client: MoodleClient, courseid: int, notes: list[str]) -> list[dict[str, Any]]:
    if not client.has_function("mod_quiz_get_quizzes_by_courses"):
        notes.append("Quizzes unavailable: mod_quiz not exposed to this token.")
        return []
    try:
        data = client.get_quizzes_by_courses([courseid])
    except MoodleFunctionUnavailable:
        notes.append("Quizzes unavailable on this instance.")
        return []
    except MoodleError as exc:
        notes.append(f"Quiz fetch failed: {exc}")
        return []

    out: list[dict[str, Any]] = []
    can_attempts = client.has_function("mod_quiz_get_user_attempts")
    for q in data.get("quizzes", []):
        attempts = None
        if can_attempts:
            try:
                a = client.get_user_quiz_attempts(int(q["id"]))
                attempts = len(a.get("attempts", []))
            except MoodleError:
                attempts = None
        out.append({
            "id": q.get("id"),
            "name": q.get("name"),
            "attempts_made": attempts,
            "timeclose": q.get("timeclose") or None,
        })
    return out


def _deadlines_for(client: MoodleClient, courseid: int, notes: list[str]) -> list[dict[str, Any]]:
    try:
        data = client.get_upcoming_events()
    except MoodleError as exc:
        notes.append(f"Deadlines unavailable: {exc}")
        return []
    events = data.get("events", []) if isinstance(data, dict) else []
    out = []
    for e in events:
        ec = e.get("course", {}).get("id") if isinstance(e.get("course"), dict) else e.get("courseid")
        if ec and int(ec) == courseid:
            out.append({
                "name": e.get("name"),
                "timesort": e.get("timesort"),
                "modulename": e.get("modulename"),
            })
    return out


@mcp.tool()
def sync_course(course: str) -> dict[str, Any]:
    """Download and text-extract all materials for a course into the local corpus.

    Incremental: only re-downloads files whose timemodified changed. Required
    before search_materials / get_material can see a course's content.
    """
    client = get_client()
    c = _resolve_course(course)
    r = cache.sync_course(client, int(c["id"]), c.get("fullname", ""))
    return {
        "course": c.get("fullname"),
        "items": r.items,
        "downloaded": r.downloaded,
        "skipped_unchanged": r.skipped,
        "external_links": r.links,
        "pruned": r.pruned,
        "extract_failures": r.extract_failures,
        "errors": r.errors,
    }


@mcp.tool()
def list_quizzes(course: str) -> list[dict[str, Any]]:
    """List a course's quizzes with how many attempts you've made on each."""
    client = get_client()
    c = _resolve_course(course)
    notes: list[str] = []
    quizzes = _quizzes_for(client, int(c["id"]), notes)
    if not quizzes and notes:
        return [{"note": n} for n in notes]
    return quizzes


@mcp.tool()
def search_materials(query: str, course: str = "all") -> list[dict[str, Any]]:
    """Full-text search across synced materials. course='all' searches every synced course."""
    courseid = None
    if course and course != "all":
        courseid = int(_resolve_course(course)["id"])
    return cache.search(query, courseid=courseid)


@mcp.tool()
def get_material(course: str, cid: str) -> dict[str, Any]:
    """Get the extracted text of one synced item (by its cid from search/overview)."""
    courseid = int(_resolve_course(course)["id"])
    text = cache.get_material_text(courseid, cid)
    if text is None:
        return {"error": f"No cached text for cid={cid}. Run sync_course first."}
    return {"cid": cid, "chars": len(text), "text": text}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
