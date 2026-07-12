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


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("VL3_intro.pdf", "lecture"),        # ETH lecture abbrev
        ("VL_02.pdf", "lecture"),
        ("RU05_Aufg.pdf", "problem_set"),    # Rechenübung + Aufgabe
        ("Serie3.pdf", "problem_set"),
        ("PK1_2023.pdf", "practice_exam"),   # Probeklausur abbrev
        ("CS2_exam_Lsg.pdf", "solution"),    # solution WINS over exam
        ("Serie3_Lsg.pdf", "solution"),      # solution WINS over problem_set
        ("uebung2_loesung.pdf", "solution"),
    ],
)
def test_eth_filename_abbreviations(filename, expected):
    assert classify(filename).category == expected


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


def test_nonmaterial_modname_is_other():
    from moodle_mcp.classify import classify_item

    # A "choice" module named "Klausureinsicht" must NOT become a practice exam.
    assert classify("Klausureinsicht", modname="choice") == ("other", "low")
    assert classify_item("Klausureinsicht", "", "", "choice") == ("other", "low")
    assert classify_item("Discussion", "", "", "forum") == ("other", "low")


def test_no_false_positive_on_example():
    # \bexams?\b must not fire on "example".
    assert classify("example_data.pdf").category != "practice_exam"
