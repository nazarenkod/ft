"""Тесты переводчика с замоканным Anthropic-клиентом (без сети)."""

import asyncio
from types import SimpleNamespace

import anthropic
import httpx
import pytest

import config
from core.models import Chapter
from core.translator import Translator, compute_cost


class FakeStream:
    def __init__(self, message):
        self._message = message

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get_final_message(self):
        return self._message


def make_message(text: str, cache_read: int = 0, cache_write: int = 0):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(
            input_tokens=1000,
            output_tokens=2000,
            cache_creation_input_tokens=cache_write,
            cache_read_input_tokens=cache_read,
        ),
    )


class FakeClient:
    """Подменяет AsyncAnthropic: запоминает запросы, отдаёт заготовленный ответ."""

    def __init__(self, reply="Перевод текста.", fail_times=0):
        self.requests = []
        self.fail_times = fail_times
        self.reply = reply
        client = self

        class Messages:
            def stream(self, **kwargs):
                client.requests.append(kwargs)
                if client.fail_times > 0:
                    client.fail_times -= 1
                    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
                    raise anthropic.APIConnectionError(request=request)
                return FakeStream(make_message(client.reply))

        self.messages = Messages()


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    monkeypatch.setattr(config, "RETRY_BASE_DELAY", 0.001)


def test_request_structure_uses_cached_system_prompt():
    client = FakeClient()
    translator = Translator({"Snape": "Снегг"}, client=client)
    chapter = Chapter(idx=1, title="One", paragraphs=["Harry met Snape."])
    asyncio.run(translator.translate_chapter(chapter))

    request = client.requests[0]
    assert request["model"] == config.MODEL
    assert request["thinking"] == {"type": "disabled"}
    assert request["output_config"] == {"effort": "low"}
    system = request["system"]
    assert system[-1]["cache_control"] == {"type": "ephemeral"}
    assert "Snape -> Снегг" in system[-1]["text"]
    assert "Harry met Snape." in request["messages"][0]["content"]


def test_retry_recovers_from_connection_errors():
    client = FakeClient(fail_times=2)  # две ошибки, третья попытка успешна
    translator = Translator({}, client=client)
    chapter = Chapter(idx=1, title="One", paragraphs=["Hello."])
    result = asyncio.run(translator.translate_chapter(chapter))
    assert result.text == "Перевод текста."
    assert len(client.requests) == 3


def test_retry_gives_up_after_attempts():
    client = FakeClient(fail_times=10)
    translator = Translator({}, client=client)
    chapter = Chapter(idx=1, title="One", paragraphs=["Hello."])
    with pytest.raises(anthropic.APIConnectionError):
        asyncio.run(translator.translate_chapter(chapter))
    assert len(client.requests) == config.RETRY_ATTEMPTS


def test_validation_rejects_untranslated_text():
    source = "Same text."
    client = FakeClient(reply=source)
    translator = Translator({}, client=client)
    chapter = Chapter(idx=1, title="One", paragraphs=[source])
    with pytest.raises(ValueError, match="совпадает с оригиналом"):
        asyncio.run(translator.translate_chapter(chapter))


def test_translate_all_isolates_failures():
    client = FakeClient(reply="")  # пустой перевод -> валидация падает
    translator = Translator({}, client=client)
    chapters = [Chapter(idx=i, title=f"C{i}", paragraphs=["Hi."]) for i in (1, 2)]
    results = asyncio.run(translator.translate_all(chapters))
    assert all(isinstance(r, ValueError) for r in results)


def test_compute_cost_with_cache():
    usage = SimpleNamespace(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_creation_input_tokens=1_000_000,
        cache_read_input_tokens=1_000_000,
    )
    cost = compute_cost(usage)
    expected = 3.00 + 15.00 + 3.00 * 1.25 + 3.00 * 0.10
    assert cost == pytest.approx(expected)
