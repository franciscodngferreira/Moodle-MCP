"""Tests for the cache: extraction, incremental sync, module-type branch, search."""
from __future__ import annotations

import pytest

from moodle_mcp import cache, config


@pytest.fixture(autouse=True)
def tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    yield tmp_path


class FakeClient:
    def __init__(self, contents, body="hello world calculus"):
        self._contents = contents
        self.body = body
        self.downloads: list[str] = []

    def get_course_contents(self, courseid):
        return self._contents

    def download_file(self, fileurl, dest):
        self.downloads.append(fileurl)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(self.body, encoding="utf-8")
        return dest


def _contents(timemod=100, include_file=True):
    modules = []
    if include_file:
        modules.append({
            "id": 1, "modname": "resource", "name": "Vorlesung 1",
            "contents": [{
                "type": "file", "filename": "vorlesung1.txt",
                "fileurl": "https://m.test/f/1", "timemodified": timemod, "filesize": 20,
            }],
        })
    modules.append({
        "id": 2, "modname": "url", "name": "External link",
        "contents": [{"type": "url", "fileurl": "https://example.com"}],
    })
    return [{"name": "Woche 1", "modules": modules}]


# -- extraction ------------------------------------------------------------
def test_extract_txt(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("some notes", encoding="utf-8")
    text, ok = cache.extract_text(p)
    assert ok and "some notes" in text


def test_extract_html_strips_tags(tmp_path):
    p = tmp_path / "a.html"
    p.write_text("<p>Hello <b>world</b></p><script>x=1</script>", encoding="utf-8")
    text, ok = cache.extract_text(p)
    assert ok and "Hello world" in text and "x=1" not in text


def test_extract_unknown_suffix_fails_gracefully(tmp_path):
    p = tmp_path / "a.xyz"
    p.write_text("data", encoding="utf-8")
    assert cache.extract_text(p) == ("", False)


# -- sync ------------------------------------------------------------------
def test_first_sync_downloads_and_links():
    client = FakeClient(_contents())
    r = cache.sync_course(client, 42, "Analysis")
    assert r.downloaded == 1
    assert r.links == 1            # mod_url stored as a link, not downloaded
    assert len(client.downloads) == 1
    assert r.items == 2


def test_unchanged_sync_skips_download():
    client = FakeClient(_contents(timemod=100))
    cache.sync_course(client, 42, "Analysis")
    client.downloads.clear()
    r2 = cache.sync_course(client, 42, "Analysis")
    assert r2.skipped == 1
    assert r2.downloaded == 0
    assert client.downloads == []  # the incremental contract: NO re-download


def test_changed_timemodified_redownloads():
    client = FakeClient(_contents(timemod=100))
    cache.sync_course(client, 42, "Analysis")
    client.downloads.clear()
    client._contents = _contents(timemod=200)
    r2 = cache.sync_course(client, 42, "Analysis")
    assert r2.downloaded == 1
    assert client.downloads == ["https://m.test/f/1"]


def test_prune_removed_item_deletes_from_disk():
    client = FakeClient(_contents())
    cache.sync_course(client, 42, "Analysis")
    fpath = cache._file_dest(cache._course_dir(42) / "files", "1:vorlesung1.txt", "vorlesung1.txt")
    tpath = cache._course_dir(42) / "text" / f"{cache._safe_filename('1:vorlesung1.txt')}.txt"
    assert fpath.exists() and tpath.exists()

    client._contents = _contents(include_file=False)
    r2 = cache.sync_course(client, 42, "Analysis")
    assert r2.pruned == 1
    assert not fpath.exists()   # prune actually deletes the cached file
    assert not tpath.exists()   # and its extracted text


def test_url_module_not_downloaded():
    client = FakeClient(_contents(include_file=False))
    r = cache.sync_course(client, 42, "Analysis")
    assert client.downloads == []
    assert r.links == 1


# -- search ----------------------------------------------------------------
def test_search_finds_synced_text():
    client = FakeClient(_contents(), body="eigenvalues and eigenvectors")
    cache.sync_course(client, 42, "Analysis")
    hits = cache.search("eigenvalues", courseid=42)
    assert hits and hits[0]["courseid"] == 42


def test_search_scoped_to_course():
    cache.sync_course(FakeClient(_contents(), body="thermodynamics entropy"), 1, "Thermo")
    cache.sync_course(FakeClient(_contents(), body="fluid dynamics viscosity"), 2, "Fluids")
    assert cache.search("entropy", courseid=1)
    assert not cache.search("entropy", courseid=2)
    assert cache.search("viscosity")  # all courses
