import json

from core.translator import (
    build_system_blocks,
    glossary_pairs,
    load_glossary,
    render_glossary,
    save_glossary,
)


def test_default_glossary_has_canon_terms():
    glossary = load_glossary()
    assert glossary["Dumbledore"]["uk"] == "Дамблдор"
    assert glossary["Hogwarts"]["uk"] == "Гоґвортс"
    assert glossary["Muggle"]["uk"] == "маґл"
    # русские формы сохранены
    assert glossary["Snape"]["ru"] == "Снегг"


def test_glossary_pairs_en_to_uk():
    glossary = load_glossary()
    pairs = glossary_pairs(glossary, "en", "uk")
    assert pairs["Hogwarts"] == "Гоґвортс"
    assert pairs["Snape"] == "Снейп"


def test_glossary_pairs_ru_to_uk_matches_russian_source():
    glossary = load_glossary()
    pairs = glossary_pairs(glossary, "ru", "uk")
    # русский источник матчится по русскому ключу
    assert pairs["Хогвартс"] == "Гоґвортс"
    assert pairs["Снегг"] == "Снейп"


def test_render_is_deterministic():
    g1 = {"B": "б", "A": "а"}
    g2 = {"A": "а", "B": "б"}
    # одинаковые байты независимо от порядка вставки — иначе ломается prompt cache
    assert render_glossary(g1, "en", "uk") == render_glossary(g2, "en", "uk")
    assert render_glossary(g1, "en", "uk").splitlines()[1].startswith("A ->")


def test_system_blocks_cache_control_on_last_block():
    blocks = build_system_blocks({"Snape": "Снейп"}, "en", "uk")
    assert "cache_control" not in blocks[0]
    assert blocks[-1]["cache_control"] == {"type": "ephemeral"}
    assert "Snape -> Снейп" in blocks[-1]["text"]
    # направление отражено в инструкциях
    assert "Ukrainian" in blocks[0]["text"]


def test_save_and_reload_roundtrip(tmp_path):
    path = tmp_path / "glossary.json"
    save_glossary(
        {"Snape": {"uk": "Снейп", "ru": "Снегг"}, "Auror": {"uk": "аврор"}}, path
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert list(data) == ["Auror", "Snape"]  # ключи отсортированы
    assert load_glossary(path) == data
    assert data["Snape"]["uk"] == "Снейп"
