import json

from core.translator import build_system_blocks, load_glossary, render_glossary, save_glossary


def test_default_glossary_has_canon_terms():
    glossary = load_glossary()
    assert glossary["Dumbledore"] == "Дамблдор"
    assert glossary["Horcrux"] == "Крестраж"
    assert glossary["Muggle"] == "маггл"


def test_render_is_deterministic():
    g1 = {"B": "б", "A": "а"}
    g2 = {"A": "а", "B": "б"}
    # одинаковые байты независимо от порядка вставки — иначе ломается prompt cache
    assert render_glossary(g1) == render_glossary(g2)
    assert render_glossary(g1).splitlines()[1].startswith("A ->")


def test_system_blocks_cache_control_on_last_block():
    blocks = build_system_blocks({"Snape": "Снегг"})
    assert "cache_control" not in blocks[0]
    assert blocks[-1]["cache_control"] == {"type": "ephemeral"}
    assert "Snape -> Снегг" in blocks[-1]["text"]


def test_save_and_reload_roundtrip(tmp_path):
    path = tmp_path / "glossary.json"
    save_glossary({"Snape": "Снегг", "Auror": "аврор"}, path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert list(data) == ["Auror", "Snape"]  # отсортировано
    assert load_glossary(path) == data
