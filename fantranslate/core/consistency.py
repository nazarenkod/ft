"""Пост-проверка консистентности терминов в готовом переводе.

Ловит ровно тот баг, ради которого затевался глоссарий: один и тот же объект
записан в книге по-разному (Гоґвортс / Ґоґвортс / Гогвортс). Для каждого
канонического термина генерируем «обманчивые» написания через типичные для
украинского конфузаблы и проверяем, не просочились ли они в текст.
"""

import re

# Пары взаимозаменяемых при ошибке букв для языка-цели.
CONFUSABLES = {
    "uk": [("г", "ґ"), ("и", "і"), ("е", "є"), ("ї", "і")],
}


def spelling_variants(term: str, target_lang: str = "uk") -> set[str]:
    """Похожие написания термина: каждая конфузабельная буква флипается отдельно.

    Дрейф обычно затрагивает одну букву в одном вхождении (Гоґвортс -> Ґоґвортс),
    поэтому варианты строятся однопозиционными заменами, а не глобальными.
    """
    variants: set[str] = set()
    pairs = CONFUSABLES.get(target_lang, [])
    chars = list(term)
    for i, ch in enumerate(chars):
        low = ch.lower()
        for a, b in pairs:
            if low == a:
                repl = b
            elif low == b:
                repl = a
            else:
                continue
            new = chars.copy()
            new[i] = repl.upper() if ch.isupper() else repl
            variants.add("".join(new))
    # Вариант без апострофа — частая ошибка.
    for apos in ("'", "’", "ʼ"):
        if apos in term:
            variants.add(term.replace(apos, ""))
    variants.discard(term)
    return variants


def _contains(text: str, word: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text) is not None


def find_inconsistencies(
    text: str, terms, target_lang: str = "uk"
) -> list[tuple[str, list[str]]]:
    """Список (канонический_термин, [найденные_неканоничные_варианты]).

    Термин попадает в отчёт, если в тексте встречается хотя бы одно его
    «обманчивое» написание, отличное от канонического.
    """
    findings: list[tuple[str, list[str]]] = []
    for term in sorted(set(terms)):
        hits = sorted(
            v for v in spelling_variants(term, target_lang) if _contains(text, v)
        )
        if hits:
            findings.append((term, hits))
    return findings
