"""Server/tool tests with a fake client (no network).

Regression guard: get_course_overview once shadowed the outer course dict with
its file-loop variable, so course.fullname came back None. That must not recur.
"""
from __future__ import annotations

import pytest

from moodle_mcp import server


class FakeClient:
    def get_course_contents(self, courseid):
        return [{
            "name": "Materials",
            "modules": [
                {"id": 1, "modname": "folder", "name": "Old exams", "contents": [
                    {"type": "file", "filename": "CS2_exam_2019.pdf"},
                    {"type": "file", "filename": "CS2_exam_2020.pdf"},
                ]},
                {"id": 2, "modname": "resource", "name": "Vorlesung 1", "contents": [
                    {"type": "file", "filename": "vl1.pdf"},
                ]},
                {"id": 3, "modname": "url", "name": "External", "contents": [
                    {"type": "url", "fileurl": "https://x"},
                ]},
            ],
        }]

    def has_function(self, name):
        return False  # no quizzes in this fixture

    def get_upcoming_events(self):
        return {"events": []}


@pytest.fixture(autouse=True)
def fake_server(monkeypatch):
    monkeypatch.setattr(server, "_client", FakeClient())
    monkeypatch.setattr(
        server, "_courses_cache",
        [{"id": 27863, "shortname": "151-0854", "fullname": "Autonomous Mobile Robots FS2026"}],
    )
    yield


def test_overview_preserves_course_fields():
    ov = server.get_course_overview("Autonomous Mobile Robots")
    # Regression: these were None due to loop-variable shadowing.
    assert ov["course"]["fullname"] == "Autonomous Mobile Robots FS2026"
    assert ov["course"]["shortname"] == "151-0854"
    assert ov["course"]["id"] == 27863


def test_overview_counts_each_exam_file():
    ov = server.get_course_overview("Autonomous Mobile Robots")
    # Both exam PDFs in the folder are counted, not the folder as one item.
    assert ov["counts_detected"]["practice_exam"] == 2
    assert ov["counts_detected"]["lecture"] == 1


def test_resolve_ambiguous_raises():
    server._courses_cache = [
        {"id": 1, "shortname": "a", "fullname": "Thermodynamics I"},
        {"id": 2, "shortname": "b", "fullname": "Thermodynamics II"},
    ]
    with pytest.raises(ValueError):
        server._resolve_course("Thermodynamics")


def test_resolve_by_id():
    assert server._resolve_course(27863)["id"] == 27863
