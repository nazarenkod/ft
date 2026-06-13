"""Парсинг EPUB: ebooklib читает spine, BeautifulSoup чистит HTML."""

from pathlib import Path

from bs4 import BeautifulSoup
from ebooklib import ITEM_DOCUMENT, epub

from config import CHUNK_WORDS
from core.models import Chapter


def parse_epub(path: Path) -> list[Chapter]:
    book = epub.read_epub(str(path))

    sections: list[tuple[str, list[str]]] = []  # (заголовок, абзацы)
    for item in book.get_items_of_type(ITEM_DOCUMENT):
        # служебные документы (оглавление и т.п.) — не главы
        if isinstance(item, epub.EpubNav) or "nav" in (item.properties or []):
            continue
        soup = BeautifulSoup(item.get_content(), "html.parser")
        if soup.find("nav"):  # nav-документ, прочитанный как обычный HTML
            continue
        title = ""
        for tag in soup.find_all(["h1", "h2"]):
            title = tag.get_text(strip=True)
            break
        paragraphs = [
            p.get_text(" ", strip=True)
            for p in soup.find_all("p")
            if p.get_text(strip=True)
        ]
        if not paragraphs:
            # документ без <p> — берём весь текст, если он есть
            text = soup.get_text("\n", strip=True)
            paragraphs = [line for line in text.split("\n") if line.strip()]
            if title and paragraphs and paragraphs[0] == title:
                paragraphs = paragraphs[1:]
        if paragraphs:
            sections.append((title, paragraphs))

    chapters = [
        Chapter(idx=i, title=title or f"Chapter {i}", paragraphs=paragraphs)
        for i, (title, paragraphs) in enumerate(sections, start=1)
    ]

    # Fallback (PRD §6): EPUB без чёткой структуры глав — один гигантский
    # документ. Разбиваем по размеру блока ~CHUNK_WORDS слов.
    if len(chapters) == 1 and chapters[0].word_count > CHUNK_WORDS * 2:
        chapters = _split_by_size(chapters[0])
    return chapters


def _split_by_size(chapter: Chapter) -> list[Chapter]:
    result: list[Chapter] = []
    current: list[str] = []
    words = 0
    for p in chapter.paragraphs:
        current.append(p)
        words += len(p.split())
        if words >= CHUNK_WORDS:
            result.append(Chapter(idx=len(result) + 1, title="", paragraphs=current))
            current, words = [], 0
    if current:
        result.append(Chapter(idx=len(result) + 1, title="", paragraphs=current))
    for c in result:
        c.title = f"{chapter.title} — часть {c.idx}" if chapter.title else f"Часть {c.idx}"
    return result
