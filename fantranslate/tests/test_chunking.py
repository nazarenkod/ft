from core.translator import build_chunk_prompt, split_into_chunks


def para(words: int, tag: str) -> str:
    return " ".join([tag] * words)


def test_short_chapter_single_chunk():
    paragraphs = [para(100, "a"), para(100, "b")]
    chunks = split_into_chunks(paragraphs, chunk_words=3000, overlap_words=200)
    assert chunks == [(paragraphs, 0)]


def test_long_chapter_split_with_overlap():
    paragraphs = [para(500, f"p{i}") for i in range(10)]  # 5000 слов
    chunks = split_into_chunks(paragraphs, chunk_words=3000, overlap_words=200)
    assert len(chunks) >= 2
    first, first_overlap = chunks[0]
    second, second_overlap = chunks[1]
    assert first_overlap == 0
    assert second_overlap >= 1
    # перекрытие: начало второго чанка == хвост первого
    assert second[:second_overlap] == first[-second_overlap:]


def test_all_paragraphs_covered_exactly_once():
    paragraphs = [para(400, f"p{i}") for i in range(12)]
    chunks = split_into_chunks(paragraphs, chunk_words=2000, overlap_words=300)
    translated: list[str] = []
    for chunk, overlap in chunks:
        translated.extend(chunk[overlap:])
    assert translated == paragraphs


def test_no_trailing_overlap_only_chunk():
    # остаток, целиком состоящий из перекрытия, не должен стать отдельным чанком
    paragraphs = [para(1000, f"p{i}") for i in range(3)]
    chunks = split_into_chunks(paragraphs, chunk_words=3000, overlap_words=200)
    for chunk, overlap in chunks:
        assert len(chunk) > overlap


def test_prompt_marks_overlap_as_context():
    prompt = build_chunk_prompt("Ch. 1", ["old tail", "new body"], overlap_count=1)
    assert "do NOT translate" in prompt
    assert "old tail" in prompt
    assert "new body" in prompt


def test_prompt_without_overlap():
    prompt = build_chunk_prompt("Ch. 1", ["only body"], overlap_count=0)
    assert "CONTEXT" not in prompt
    assert "only body" in prompt
