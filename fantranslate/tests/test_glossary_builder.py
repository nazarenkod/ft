"""Тесты авто-сбора имён собственных."""

import asyncio
from types import SimpleNamespace

from core.glossary_builder import collect_names, extract_candidates


class FakeStream:
    def __init__(self, text):
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get_final_message(self):
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self._text)])


class FakeClient:
    def __init__(self, reply):
        self.reply = reply
        self.requests = []
        client = self

        class Messages:
            def stream(self, **kwargs):
                client.requests.append(kwargs)
                return FakeStream(client.reply)

        self.messages = Messages()


def test_extract_finds_recurring_midsentence_name():
    text = (
        "The hero met Aria in the hall. Later Aria smiled at the hero. "
        "Everyone trusted Aria completely."
    )
    names = extract_candidates(text, "en", min_count=3)
    assert "Aria" in names


def test_extract_ignores_sentence_initial_only():
    # "Later" всегда в начале предложения -> не имя
    text = "Later it rained. Later it stopped. Later it rained again."
    names = extract_candidates(text, "en", min_count=3)
    assert "Later" not in names


def test_extract_skips_known_terms():
    text = "Harry saw Harry. Harry waved. Harry left with Harry."
    names = extract_candidates(text, "en", min_count=2, existing={"Harry"})
    assert "Harry" not in names


def test_extract_russian_source():
    text = (
        "В углу сидел Воронов и молчал. Потом Воронов встал. "
        "Все смотрели на Воронова."
    )
    names = extract_candidates(text, "ru", min_count=2)
    assert any(n.startswith("Воронов") for n in names)


def test_collect_names_parses_json_reply():
    client = FakeClient('Here you go:\n```json\n{"Aria": "Арія"}\n```')
    result = asyncio.run(collect_names(client, ["Aria"], "en", "uk"))
    assert result == {"Aria": "Арія"}


def test_collect_names_filters_unrequested_keys():
    client = FakeClient('{"Aria": "Арія", "Ghost": "Привид"}')
    result = asyncio.run(collect_names(client, ["Aria"], "en", "uk"))
    assert result == {"Aria": "Арія"}


def test_collect_names_empty_candidates_no_request():
    client = FakeClient("{}")
    result = asyncio.run(collect_names(client, [], "en", "uk"))
    assert result == {}
    assert client.requests == []
