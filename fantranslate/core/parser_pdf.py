"""Парсинг PDF: pdfplumber извлекает текст постранично."""

from pathlib import Path

import pdfplumber


def extract_pages(path: Path) -> list[str]:
    """Возвращает сырой текст каждой страницы."""
    pages: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    return pages
