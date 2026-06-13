"""Тесты пост-проверки консистентности написаний."""

from core.consistency import find_inconsistencies, spelling_variants


def test_detects_g_vs_gh_variant():
    # каноничный «Гоґвортс», но где-то проскочил «Ґоґвортс»
    text = "Усі любили Гоґвортс. Але цей Ґоґвортс був інакшим."
    findings = find_inconsistencies(text, ["Гоґвортс"], "uk")
    assert findings
    canonical, variants = findings[0]
    assert canonical == "Гоґвортс"
    assert "Ґоґвортс" in variants


def test_clean_text_has_no_findings():
    text = "Гоґвортс завжди був Гоґвортс, і нічого більше."
    assert find_inconsistencies(text, ["Гоґвортс"], "uk") == []


def test_apostrophe_variant_detected():
    text = "Її ім'я знали всі. Але хтось писав імя без апострофа."
    findings = find_inconsistencies(text, ["ім'я"], "uk")
    assert findings
    assert "імя" in findings[0][1]


def test_spelling_variants_excludes_self():
    variants = spelling_variants("Гоґвортс", "uk")
    assert "Гоґвортс" not in variants
    assert "Ґоґвортс" in variants


def test_no_match_when_variant_absent():
    text = "Лише канонічне слово Дамблдор тут присутнє."
    assert find_inconsistencies(text, ["Дамблдор"], "uk") == []
