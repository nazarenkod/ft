"""Оценка стоимости перевода до запуска (dry-run, PRD §5.3)."""

from dataclasses import dataclass

import anthropic

import config
from core.models import Chapter
from core.translator import build_chunk_prompt, build_system_blocks, split_into_chunks


@dataclass
class Estimate:
    total_words: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    exact: bool  # True — посчитано через count_tokens API, False — эвристика


def _heuristic_tokens(words: int) -> int:
    return int(words * config.WORDS_TO_TOKENS)


def estimate_cost(
    chapters: list[Chapter],
    pairs: dict[str, str],
    source_lang: str = config.SOURCE_LANG,
    target_lang: str = config.TARGET_LANG,
    model: str = config.MODEL,
) -> Estimate:
    """Считает входные токены через count_tokens API; без ключа/сети — эвристикой."""
    total_words = sum(c.word_count for c in chapters)
    system_blocks = build_system_blocks(pairs, source_lang, target_lang)
    prices = config.MODEL_PRICES.get(model, config.MODEL_PRICES[config.MODEL])

    input_tokens = 0
    exact = False
    if config.ANTHROPIC_API_KEY:
        try:
            client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
            # Глоссарий + инструкции считаем один раз: после первого запроса
            # они читаются из кэша (~0.1x), поэтому для оценки берём полный
            # тариф один раз и cache-read для остальных запросов.
            system_tokens = client.messages.count_tokens(
                model=model,
                system=system_blocks,
                messages=[{"role": "user", "content": "x"}],
            ).input_tokens
            n_requests = 0
            for chapter in chapters:
                for chunk, overlap_count in split_into_chunks(chapter.paragraphs):
                    prompt = build_chunk_prompt(chapter.title, chunk, overlap_count)
                    chunk_tokens = client.messages.count_tokens(
                        model=model,
                        messages=[{"role": "user", "content": prompt}],
                    ).input_tokens
                    input_tokens += chunk_tokens
                    n_requests += 1
            # первый запрос пишет кэш (x1.25), остальные читают (x0.1)
            input_tokens += int(
                system_tokens * config.CACHE_WRITE_MULTIPLIER
                + system_tokens * config.CACHE_READ_MULTIPLIER * max(n_requests - 1, 0)
            )
            exact = True
        except anthropic.APIError:
            input_tokens = 0

    if not input_tokens:
        input_tokens = _heuristic_tokens(total_words) + 2500  # текст + системный промпт

    output_tokens = int(_heuristic_tokens(total_words) * config.OUTPUT_TOKENS_RATIO)
    cost = (
        input_tokens * prices["input"]
        + output_tokens * prices["output"]
    ) / 1_000_000
    return Estimate(
        total_words=total_words,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
        exact=exact,
    )
