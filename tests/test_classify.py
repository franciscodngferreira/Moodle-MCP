"""Table tests for the classifier — German + English, confidence, fallback."""
from __future__ import annotations

import pytest

from moodle_mcp.classify import classify


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Vorlesung 3 Folien", "lecture"),
        ("Lecture 05 slides", "lecture"),
        ("Skript Kapitel 2", "lecture"),
        ("Übung 7", "problem_set"),
        ("Uebung 7", "problem_set"),
        ("Serie 4", "problem_set"),
        ("Exercise Sheet 2", "problem_set"),
        ("Problem Set 1", "problem_set"),
        ("Probeklausur HS2024", "practice_exam"),
        ("Past exam 2023", "practice_exam"),
        ("Mock Exam", "practice_exam"),
        ("Musterlösung Serie 3", "solution"),
        ("Loesung Uebung 1", "solution"),
        ("Solution 4", "solution"),
        ("Random announcement", "other"),
    ],
)
def test_title_classification(title, expected):
    c = classify(title)
    assert c.category == expected
    if expected != "other":
        assert c.confidence == "high"
    else:
        assert c.confidence == "low"


def test_modname_quiz_wins():
    c = classify("Weekly check", modname="quiz")
    assert c.category == "quiz"
    assert c.confidence == "high"


def test_modname_assign_maps_to_problem_set():
    assert classify("Hand-in", modname="assign").category == "problem_set"


def test_section_match_is_medium_confidence():
    c = classify("file_02", section="Übungen")
    assert c.category == "problem_set"
    assert c.confidence == "medium"


def test_unknown_is_other_low():
    c = classify("xyz", section="misc")
    assert c == ("other", "low")
