"""Авто-сбор повторяющихся имён собственных и их единый перевод на книгу.

Глоссарий покрывает только канон HP. Имена ОС-персонажей, выдуманные автором
заклинания и локации в нём отсутствуют — и при пофрагментном переводе дрейфуют
(в одной главе так, в другой иначе). Здесь мы один раз извлекаем такие имена из
всего текста и фиксируем им единый перевод, добавляя его во временный глоссарий
на весь прогон.
"""

import json
import re

import config

# Заглавный токен языка-источника. Апостроф/дефис внутри слова допускаются.
TOKEN_RE = {
    "en": re.compile(r"[A-Z][a-zA-Z]+(?:['\-][A-Za-z]+)*"),
    "ru": re.compile(r"[А-ЯЁ][а-яёА-ЯЁ\-]+"),
}

# Слова, которые часто заглавные в середине предложения, но не имена.
STOPWORDS = {
    "en": {"I", "I'm", "I'll", "I've", "I'd", "Mr", "Mrs", "Ms", "Dr", "Ok", "Okay"},
    "ru": set(),
}

# Граница «начала предложения»: перед такой пунктуацией заглавная не значима.
_BOUNDARY = set(".!?…\n\r")
_QUOTE_OR_DASH = set("\"'«»“”„—–-")


def _is_sentence_initial(text: str, pos: int) -> bool:
    """True, если токен на позиции pos стоит в начале предложения/реплики."""
    k = pos - 1
    while k >= 0 and text[k] in " \t":
        k -= 1
    if k < 0:
        return True
    if text[k] in _BOUNDARY:
        return True
    # Открытие прямой речи/кавычек тоже считаем «началом» — заглавная там не довод.
    if text[k] in _QUOTE_OR_DASH:
        j = k - 1
        while j >= 0 and text[j] in " \t":
            j -= 1
        if j < 0 or text[j] in _BOUNDARY:
            return True
    return False


def _iter_phrases(text: str, token_re: re.Pattern):
    """Выдаёт и отдельные заглавные токены, и склейки соседних (через пробел).

    Отдельные токены нужны, чтобы начальное слово предложения не «слипалось» с
    идущим следом именем («Later Aria» -> кандидат всё равно «Aria»). Склейки
    ловят многословные имена («Harry Potter», «Грозный Глаз»).
    """
    matches = list(token_re.finditer(text))
    for m in matches:
        yield m.group(0), m.start()
    i = 0
    while i < len(matches):
        j = i
        while j + 1 < len(matches) and text[matches[j].end():matches[j + 1].start()] == " ":
            j += 1
        if j > i:  # только настоящие многословные склейки
            yield text[matches[i].start():matches[j].end()], matches[i].start()
        i = j + 1


def extract_candidates(
    text: str,
    source_lang: str = "en",
    min_count: int = 3,
    existing: set[str] | None = None,
    max_terms: int = 80,
) -> list[str]:
    """Повторяющиеся имена собственные из текста, отсортированные по частоте.

    Кандидат принимается, если встречается в середине предложения хотя бы раз
    (значит, заглавная не из-за начала фразы) и суммарно не реже ``min_count``.
    """
    token_re = TOKEN_RE.get(source_lang)
    if token_re is None:
        return []
    known = {e.lower() for e in (existing or set())}
    stop = STOPWORDS.get(source_lang, set())

    total: dict[str, int] = {}
    mid: dict[str, int] = {}
    for phrase, pos in _iter_phrases(text, token_re):
        if phrase in stop or len(phrase) < 2:
            continue
        total[phrase] = total.get(phrase, 0) + 1
        if not _is_sentence_initial(text, pos):
            mid[phrase] = mid.get(phrase, 0) + 1

    candidates = [
        name
        for name, count in total.items()
        if count >= min_count and mid.get(name, 0) >= 1 and name.lower() not in known
    ]
    candidates.sort(key=lambda n: total[n], reverse=True)
    return candidates[:max_terms]


def _parse_json_map(text: str) -> dict[str, str]:
    """Достаёт JSON-объект из ответа модели (возможно, в обёртке/```json```)."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return {}
    try:
        data = json.loads(text[start:end + 1])
    except (json.JSONDecodeError, ValueError):
        return {}
    return {
        str(k): str(v).strip()
        for k, v in data.items()
        if isinstance(k, str) and str(v).strip()
    }


def build_prompt(candidates: list[str], source_lang: str, target_lang: str) -> str:
    src = config.LANGUAGES.get(source_lang, source_lang)
    tgt = config.LANGUAGES.get(target_lang, target_lang)
    listing = "\n".join(f"- {c}" for c in candidates)
    return (
        f"You are preparing a glossary for translating a Harry Potter fan fiction "
        f"from {src} to {tgt}.\n"
        f"Below are recurring proper nouns (character names, places, invented "
        f"spells). Give ONE canonical {tgt} rendering for each, consistent with the "
        f"official Ukrainian HP translation where applicable.\n"
        f"Return ONLY a JSON object mapping each {src} term to its {tgt} translation, "
        f"no commentary.\n\nTerms:\n{listing}"
    )


async def collect_names(
    client,
    candidates: list[str],
    source_lang: str,
    target_lang: str,
    model: str = config.MODEL,
) -> dict[str, str]:
    """Один запрос к модели: единый перевод для каждого имени-кандидата."""
    if not candidates:
        return {}
    prompt = build_prompt(candidates, source_lang, target_lang)
    async with client.messages.stream(
        model=model,
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        message = await stream.get_final_message()
    text = "".join(block.text for block in message.content if block.type == "text")
    mapping = _parse_json_map(text)
    # Оставляем только то, что реально просили (модель не выдумала ключи).
    wanted = set(candidates)
    return {k: v for k, v in mapping.items() if k in wanted}
