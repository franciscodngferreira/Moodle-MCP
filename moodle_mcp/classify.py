"""Heuristic content classifier.

Moodle does not label items as "problem set" vs "practice exam" vs "lecture" —
those are just filenames and section names. This module buckets an item by
matching regex fragments (loaded from taxonomy.yaml) against its title, and at
lower confidence its section name.

The counts this produces are DETECTED, not authoritative. Every classified item
carries its raw title and a confidence so the caller (Claude) can eyeball and
correct. That honesty is the whole point — a silent miscategorization would skew
the "how many problem sets" answer the user actually cares about.

    title + section + modname
            |
            v
    modname == quiz? --------> ("quiz", "high")
            |
            v
    for category in ORDER:            # practice_exam > solution > problem_set > lecture
        regex matches title?  ------> (category, "high")
        regex matches section? -----> (category, "medium")
            |
            v
    no match ------------------------> ("other", "low")
"""
from __future__ import annotations

import functools
import re
from pathlib import Path
from typing import NamedTuple

import yaml

_TAXONOMY_PATH = Path(__file__).with_name("taxonomy.yaml")

# Moodle module names that map directly to a category, no regex needed.
_MODNAME_CATEGORY = {
    "quiz": "quiz",
    "assign": "problem_set",
}

CATEGORIES = ("lecture", "problem_set", "practice_exam", "solution", "quiz", "other")


class Classification(NamedTuple):
    category: str
    confidence: str  # "high" | "medium" | "low"


@functools.lru_cache(maxsize=1)
def _load_taxonomy(path: str | None = None) -> list[tuple[str, re.Pattern[str]]]:
    """Load taxonomy.yaml into an ordered list of (category, compiled_regex)."""
    src = Path(path) if path else _TAXONOMY_PATH
    raw = yaml.safe_load(src.read_text(encoding="utf-8")) or {}
    compiled: list[tuple[str, re.Pattern[str]]] = []
    for category, fragments in raw.items():
        for fragment in fragments or []:
            compiled.append((category, re.compile(fragment, re.IGNORECASE)))
    return compiled


def classify(
    title: str,
    section: str = "",
    modname: str = "",
    *,
    taxonomy_path: str | None = None,
) -> Classification:
    """Classify one course item. See module docstring for the decision tree."""
    modname = (modname or "").lower()
    if modname in _MODNAME_CATEGORY:
        return Classification(_MODNAME_CATEGORY[modname], "high")

    title = title or ""
    section = section or ""
    rules = _load_taxonomy(taxonomy_path)

    # First pass: a title match is high confidence.
    for category, pattern in rules:
        if pattern.search(title):
            return Classification(category, "high")

    # Second pass: only the section name matched -> medium confidence.
    for category, pattern in rules:
        if pattern.search(section):
            return Classification(category, "medium")

    return Classification("other", "low")


def classify_item(
    module_name: str,
    filename: str = "",
    section: str = "",
    modname: str = "",
    *,
    taxonomy_path: str | None = None,
) -> Classification:
    """Classify a single file, using its FILENAME first, then the module name.

    A folder module ("Old exams") holds many differently-named files
    (``CS2_exam_2019.pdf``, ``..._solution.pdf``), so classifying per file by
    filename is what makes the "how many practice exams" count accurate.
    Falls back to the module name when the filename alone is uninformative.
    """
    modname_l = (modname or "").lower()
    if modname_l in _MODNAME_CATEGORY:
        return Classification(_MODNAME_CATEGORY[modname_l], "high")

    primary = classify(filename or module_name, section, "", taxonomy_path=taxonomy_path)
    if primary.category != "other":
        return primary
    if filename and module_name and module_name != filename:
        fallback = classify(module_name, section, "", taxonomy_path=taxonomy_path)
        if fallback.category != "other":
            return fallback
    return primary
