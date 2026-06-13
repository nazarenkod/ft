from pathlib import Path

import pytest

from core.models import Chapter, TranslationResult
from core.storage import Storage


@pytest.fixture
def book(tmp_path: Path) -> Path:
    path = tmp_path / "book.epub"
    path.write_bytes(b"fake epub content")
    return path


@pytest.fixture
def chapters() -> list[Chapter]:
    return [
        Chapter(idx=1, title="One", paragraphs=["Hello world."]),
        Chapter(idx=2, title="Two", paragraphs=["Goodbye world."]),
    ]


def test_create_and_find_project(tmp_path, book, chapters):
    storage = Storage(tmp_path / "db.sqlite")
    project_id = storage.get_or_create_project(book, chapters)
    assert storage.get_or_create_project(book, chapters) == project_id  # идемпотентно
    project = storage.find_project(book)
    assert project["filename"] == "book.epub"
    assert project["total_chapters"] == 2


def test_resume_skips_translated(tmp_path, book, chapters):
    storage = Storage(tmp_path / "db.sqlite")
    project_id = storage.get_or_create_project(book, chapters)
    assert storage.translated_indices(project_id) == set()

    storage.save_translation(
        project_id,
        TranslationResult(chapter_idx=1, text="Привет, мир.", cost_usd=0.05),
    )
    assert storage.translated_indices(project_id) == {1}


def test_translations_export_order(tmp_path, book, chapters):
    storage = Storage(tmp_path / "db.sqlite")
    project_id = storage.get_or_create_project(book, chapters)
    storage.save_translation(project_id, TranslationResult(chapter_idx=2, text="Пока."))
    storage.save_translation(project_id, TranslationResult(chapter_idx=1, text="Привет."))
    rows = storage.get_translations(project_id)
    assert [r["idx"] for r in rows] == [1, 2]
    assert rows[0]["text"] == "Привет."


def test_list_projects_aggregates(tmp_path, book, chapters):
    storage = Storage(tmp_path / "db.sqlite")
    project_id = storage.get_or_create_project(book, chapters)
    storage.save_translation(
        project_id, TranslationResult(chapter_idx=1, text="Привет.", cost_usd=0.09)
    )
    rows = storage.list_projects()
    assert len(rows) == 1
    assert rows[0]["done"] == 1
    assert rows[0]["spent"] == pytest.approx(0.09)


def test_save_unknown_chapter_raises(tmp_path, book, chapters):
    storage = Storage(tmp_path / "db.sqlite")
    project_id = storage.get_or_create_project(book, chapters)
    with pytest.raises(ValueError):
        storage.save_translation(project_id, TranslationResult(chapter_idx=99, text="x"))
