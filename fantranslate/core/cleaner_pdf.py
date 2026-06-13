"""Пайплайн очистки PDF-текста (PRD §2.2).

Сырой текст по страницам
  -> удаление колонтитулов (повторяющиеся строки)
  -> удаление номеров страниц
  -> склейка разорванных строк
  -> нормализация пробелов и пустых строк
  -> детекция и разбивка на главы (эвристика)
"""

import re
from collections import Counter

from core.models import Chapter

PAGE_NUMBER_RE = re.compile(r"^\s*(?:-\s*)?\d+(?:\s*-)?\s*$|^\s*page\s+\d+(\s+of\s+\d+)?\s*$", re.I)
CHAPTER_RE = re.compile(r"^\s*(?:chapter|глава)\s+(\d+|[ivxlc]+)\b.{0,60}$", re.I)
# Строка, оканчивающая предложение — после неё абзац не склеиваем
SENTENCE_END_RE = re.compile(r'[.!?…"\'»”]\s*$')


def remove_headers_footers(pages: list[str], min_repeats: int = 3) -> list[str]:
    """Удаляет строки, повторяющиеся в начале/конце многих страниц."""
    if len(pages) < min_repeats:
        return pages
    counter: Counter[str] = Counter()
    for page in pages:
        lines = [line.strip() for line in page.splitlines() if line.strip()]
        # колонтитулы живут на краях страницы
        for line in lines[:2] + lines[-2:]:
            counter[line] += 1
    repeated = {line for line, n in counter.items() if n >= min_repeats and len(line) < 120}
    cleaned = []
    for page in pages:
        kept = [line for line in page.splitlines() if line.strip() not in repeated]
        cleaned.append("\n".join(kept))
    return cleaned


def remove_page_numbers(pages: list[str]) -> list[str]:
    cleaned = []
    for page in pages:
        kept = [line for line in page.splitlines() if not PAGE_NUMBER_RE.match(line)]
        cleaned.append("\n".join(kept))
    return cleaned


def join_broken_lines(text: str) -> str:
    """Склеивает строки, разорванные версткой PDF.

    Строка без завершающей пунктуации продолжается следующей; перенос
    слова с дефисом ("transfigura-\\ntion") склеивается без пробела.
    """
    lines = text.splitlines()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            out.append("")
            continue
        if out and out[-1]:
            prev = out[-1]
            if prev.endswith("-") and stripped and stripped[0].islower():
                out[-1] = prev[:-1] + stripped
                continue
            if not SENTENCE_END_RE.search(prev) and not _looks_like_heading(prev):
                out[-1] = prev + " " + stripped
                continue
        out.append(stripped)
    return "\n".join(out)


def normalize_whitespace(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _looks_like_heading(line: str) -> bool:
    stripped = line.strip()
    if CHAPTER_RE.match(stripped):
        return True
    # короткая строка целиком ЗАГЛАВНЫМИ — вероятный заголовок
    letters = [ch for ch in stripped if ch.isalpha()]
    return bool(letters) and len(stripped) <= 60 and all(ch.isupper() for ch in letters)


def split_chapters(text: str) -> list[Chapter]:
    """Делит чистый текст на главы по строкам-разделителям."""
    sections: list[tuple[str, list[str]]] = []
    title = ""
    buf: list[str] = []
    for block in text.split("\n"):
        block = block.strip()
        if not block:
            continue
        if _looks_like_heading(block):
            if buf:
                sections.append((title, buf))
                buf = []
            title = block
        else:
            buf.append(block)
    if buf:
        sections.append((title, buf))

    if not sections:
        return []
    return [
        Chapter(idx=i, title=t or f"Часть {i}", paragraphs=p)
        for i, (t, p) in enumerate(sections, start=1)
    ]


def clean_pdf_text(pages: list[str]) -> str:
    """Полный пайплайн очистки; возвращает чистый текст одним куском."""
    pages = remove_headers_footers(pages)
    pages = remove_page_numbers(pages)
    text = "\n".join(pages)
    text = join_broken_lines(text)
    return normalize_whitespace(text)


def parse_pdf_chapters(pages: list[str]) -> list[Chapter]:
    return split_chapters(clean_pdf_text(pages))
