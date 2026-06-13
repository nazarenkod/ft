"""Перевод глав через Claude API: prompt caching, asyncio, retry, чанкинг."""

import asyncio
import json
import time
from collections.abc import Callable
from pathlib import Path

import anthropic

import config
from core.models import Chapter, TranslationResult

STYLE_INSTRUCTIONS = """\
You are a professional literary translator. Translate English Harry Potter \
fan fiction into Russian.

Rules:
- Preserve the author's style, tone, pacing and intonation.
- Translate dialogue naturally; use Russian punctuation for dialogue (em dash).
- Use the canonical Russian terminology from the glossary below (official \
Rosman edition). Apply glossary terms in all grammatical forms.
- Keep paragraph breaks exactly as in the source: one source paragraph -> \
one translated paragraph.
- Output ONLY the translation, no comments, notes or preface.\
"""


def load_glossary(path: Path | None = None) -> dict[str, str]:
    with open(path or config.GLOSSARY_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_glossary(glossary: dict[str, str], path: Path | None = None) -> None:
    with open(path or config.GLOSSARY_PATH, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(glossary.items())), f, ensure_ascii=False, indent=2)
        f.write("\n")


def render_glossary(glossary: dict[str, str]) -> str:
    # Детерминированный порядок: иначе префикс меняется и кэш не переиспользуется
    lines = [f"{en} -> {ru}" for en, ru in sorted(glossary.items())]
    return "GLOSSARY (English -> Russian):\n" + "\n".join(lines)


def build_system_blocks(glossary: dict[str, str]) -> list[dict]:
    """Стабильный system prompt; кэшируется целиком по последнему блоку."""
    return [
        {"type": "text", "text": STYLE_INSTRUCTIONS},
        {
            "type": "text",
            "text": render_glossary(glossary),
            "cache_control": {"type": "ephemeral"},
        },
    ]


def split_into_chunks(
    paragraphs: list[str],
    chunk_words: int = config.CHUNK_WORDS,
    overlap_words: int = config.CHUNK_OVERLAP_WORDS,
) -> list[tuple[list[str], int]]:
    """Делит главу на чанки по границам абзацев с перекрытием.

    Возвращает список (абзацы, overlap_count): первые overlap_count абзацев
    чанка повторяют хвост предыдущего — они дают модели контекст и при
    переводе не дублируются в результате.
    """
    total = sum(len(p.split()) for p in paragraphs)
    if total <= chunk_words:
        return [(paragraphs, 0)]

    chunks: list[tuple[list[str], int]] = []
    current: list[str] = []
    overlap_count = 0
    words = 0
    for p in paragraphs:
        current.append(p)
        words += len(p.split())
        if words >= chunk_words:
            chunks.append((current, overlap_count))
            # хвост текущего чанка становится перекрытием следующего
            overlap: list[str] = []
            ow = 0
            for prev in reversed(current):
                overlap.insert(0, prev)
                ow += len(prev.split())
                if ow >= overlap_words:
                    break
            current = list(overlap)
            overlap_count = len(overlap)
            words = ow
    # незакрытый остаток (что-то сверх чистого перекрытия)
    if len(current) > overlap_count:
        chunks.append((current, overlap_count))
    return chunks


def compute_cost(usage) -> float:
    """Точная стоимость запроса по полям usage."""
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cost = (
        inp * config.PRICE_INPUT_PER_MTOK
        + cache_write * config.PRICE_INPUT_PER_MTOK * config.CACHE_WRITE_MULTIPLIER
        + cache_read * config.PRICE_INPUT_PER_MTOK * config.CACHE_READ_MULTIPLIER
        + out * config.PRICE_OUTPUT_PER_MTOK
    )
    return cost / 1_000_000


def build_chunk_prompt(chapter_title: str, chunk: list[str], overlap_count: int) -> str:
    if overlap_count:
        context = "\n\n".join(chunk[:overlap_count])
        body = "\n\n".join(chunk[overlap_count:])
        return (
            f"Chapter: {chapter_title}\n\n"
            f"[CONTEXT — end of the previous part, do NOT translate it again:]\n"
            f"{context}\n\n"
            f"[TRANSLATE only the following continuation:]\n{body}"
        )
    body = "\n\n".join(chunk)
    return f"Chapter: {chapter_title}\n\nTranslate this text:\n\n{body}"


class Translator:
    def __init__(self, glossary: dict[str, str], client: anthropic.AsyncAnthropic | None = None):
        if client is None:
            if not config.ANTHROPIC_API_KEY:
                raise RuntimeError(
                    "ANTHROPIC_API_KEY не задан. Создайте fantranslate/.env "
                    "со строкой ANTHROPIC_API_KEY=sk-ant-..."
                )
            client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
        self.client = client
        self.system_blocks = build_system_blocks(glossary)
        self.semaphore = asyncio.Semaphore(config.MAX_CONCURRENT)

    async def _request(self, user_text: str):
        """Один вызов API с retry поверх встроенных ретраев SDK."""
        last_exc: Exception | None = None
        for attempt in range(config.RETRY_ATTEMPTS):
            try:
                async with self.client.messages.stream(
                    model=config.MODEL,
                    max_tokens=config.MAX_TOKENS,
                    thinking={"type": "disabled"},
                    output_config={"effort": "low"},
                    system=self.system_blocks,
                    messages=[{"role": "user", "content": user_text}],
                ) as stream:
                    return await stream.get_final_message()
            except (anthropic.APIConnectionError, anthropic.RateLimitError,
                    anthropic.InternalServerError) as exc:
                last_exc = exc
                await asyncio.sleep(config.RETRY_BASE_DELAY * 2 ** attempt)
        raise last_exc  # type: ignore[misc]

    async def translate_chapter(self, chapter: Chapter) -> TranslationResult:
        async with self.semaphore:
            started = time.monotonic()
            parts: list[str] = []
            input_tokens = output_tokens = 0
            cost = 0.0

            for chunk, overlap_count in split_into_chunks(chapter.paragraphs):
                user_text = build_chunk_prompt(chapter.title, chunk, overlap_count)
                response = await self._request(user_text)
                text = "".join(
                    block.text for block in response.content if block.type == "text"
                ).strip()
                self._validate(chapter, "\n\n".join(chunk[overlap_count:]), text)
                parts.append(text)

                usage = response.usage
                input_tokens += (usage.input_tokens or 0) + (
                    getattr(usage, "cache_creation_input_tokens", 0) or 0
                ) + (getattr(usage, "cache_read_input_tokens", 0) or 0)
                output_tokens += usage.output_tokens or 0
                cost += compute_cost(usage)

            return TranslationResult(
                chapter_idx=chapter.idx,
                text="\n\n".join(parts),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost,
                duration_sec=time.monotonic() - started,
            )

    @staticmethod
    def _validate(chapter: Chapter, source: str, translation: str) -> None:
        if not translation:
            raise ValueError(f"Глава {chapter.idx}: пустой перевод")
        if translation.strip() == source.strip():
            raise ValueError(f"Глава {chapter.idx}: перевод совпадает с оригиналом")

    async def translate_all(
        self,
        chapters: list[Chapter],
        on_done: Callable[[TranslationResult | Exception, Chapter], None] | None = None,
    ) -> list[TranslationResult | Exception]:
        """Переводит главы параллельно (до MAX_CONCURRENT одновременно)."""

        async def worker(ch: Chapter):
            try:
                result = await self.translate_chapter(ch)
            except Exception as exc:  # noqa: BLE001 — глава падает, остальные продолжают
                if on_done:
                    on_done(exc, ch)
                return exc
            if on_done:
                on_done(result, ch)
            return result

        return await asyncio.gather(*(worker(c) for c in chapters))
