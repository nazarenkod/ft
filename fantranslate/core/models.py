"""Общие типы данных."""

from dataclasses import dataclass, field


@dataclass
class Chapter:
    """Глава исходной книги."""

    idx: int                 # порядковый номер, с 1
    title: str
    paragraphs: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(self.paragraphs)

    @property
    def word_count(self) -> int:
        return len(self.text.split())


@dataclass
class TranslationResult:
    """Результат перевода одной главы."""

    chapter_idx: int
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    duration_sec: float = 0.0
