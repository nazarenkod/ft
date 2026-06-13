from core.cleaner_pdf import (
    clean_pdf_text,
    join_broken_lines,
    parse_pdf_chapters,
    remove_headers_footers,
    remove_page_numbers,
)


def make_page(body: str, header: str = "My Fanfic Title", number: int = 1) -> str:
    return f"{header}\n{body}\n{number}"


def test_removes_repeating_headers():
    pages = [make_page(f"Body text {i}.", number=i) for i in range(1, 6)]
    cleaned = remove_headers_footers(pages)
    assert all("My Fanfic Title" not in p for p in cleaned)
    assert "Body text 1." in cleaned[0]


def test_removes_page_numbers():
    pages = ["Some text.\n42", "More text.\nPage 3 of 10", "Final.\n- 7 -"]
    cleaned = remove_page_numbers(pages)
    assert "42" not in cleaned[0]
    assert "Page 3 of 10" not in cleaned[1]
    assert "- 7 -" not in cleaned[2]
    assert "Some text." in cleaned[0]


def test_joins_broken_lines_without_hyphen():
    text = "Harry walked slowly down\nthe corridor."
    assert join_broken_lines(text) == "Harry walked slowly down the corridor."


def test_joins_hyphenated_word():
    text = "He studied transfigura-\ntion all night."
    assert join_broken_lines(text) == "He studied transfiguration all night."


def test_does_not_join_after_sentence_end():
    text = "He stopped.\nThen he ran."
    assert join_broken_lines(text) == "He stopped.\nThen he ran."


def test_chapter_detection():
    pages = [
        "Chapter 1\n" + "Harry woke up. " * 30,
        "CHAPTER TWO\n" + "Ron was late. " * 30,
        "Глава 3: Финал\n" + "Всё закончилось. " * 30,
    ]
    chapters = parse_pdf_chapters(pages)
    assert len(chapters) == 3
    assert chapters[0].title == "Chapter 1"
    assert chapters[1].title == "CHAPTER TWO"
    assert chapters[2].title.startswith("Глава 3")
    assert chapters[0].idx == 1 and chapters[2].idx == 3


def test_full_pipeline_clean():
    header = "Best Fanfic Ever"
    pages = [
        f"{header}\nChapter 1\nHarry walked down\nthe hall.\n1",
        f"{header}\nHe saw transfigura-\ntion books.\n2",
        f"{header}\nThe end came fast.\n3",
        f"{header}\nReally fast indeed.\n4",
    ]
    text = clean_pdf_text(pages)
    assert header not in text
    assert "Harry walked down the hall." in text
    assert "transfiguration" in text
