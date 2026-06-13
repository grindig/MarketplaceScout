"""Tests for seen-ID persistence."""

import json

from storage import load_seen, save_seen


def test_load_seen_missing_file(tmp_path):
    assert load_seen(str(tmp_path / "seen.json")) == set()


def test_roundtrip(tmp_path):
    path = str(tmp_path / "seen.json")
    save_seen({"3", "1", "2"}, path)
    assert load_seen(path) == {"1", "2", "3"}


def test_save_is_sorted_json(tmp_path):
    path = str(tmp_path / "seen.json")
    save_seen({"b", "a"}, path)
    with open(path, encoding="utf-8") as f:
        assert json.load(f) == ["a", "b"]


def test_save_leaves_no_tmp_file(tmp_path):
    path = str(tmp_path / "seen.json")
    save_seen({"1"}, path)
    assert list(tmp_path.iterdir()) == [tmp_path / "seen.json"]


def test_load_seen_corrupt_file(tmp_path):
    path = tmp_path / "seen.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_seen(str(path)) == set()
