# FanTranslate v1.0 — UA Edition

Локальний CLI-інструмент для автоматизованого перекладу фанфіків по всесвіту
Гаррі Поттера **на українську мову** — з англійського або російського джерела.

```
EPUB / PDF  →  очищення тексту  →  переклад через Claude API
            →  готовий .docx з оглавленням і колонтитулами
```

---

## Встановлення

```bash
cd fantranslate
pip install -r requirements.txt
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env
```

Вимоги: Python 3.11+, ключ Claude API (https://console.anthropic.com).

---

## Швидкий старт

```bash
# EN → UK (за замовчуванням)
python translate.py input.epub

# RU → UK
python translate.py input.epub --from ru

# Якість max (Opus) з виведенням у конкретний файл
python translate.py input.epub --quality max --output my_fanfic_uk.docx

# Перекласти тільки глави 1–5
python translate.py input.epub --chapters 1-5
```

Готові переклади зберігаються в `output/` (`<ім'я>_uk.docx`), прогрес — в
`translations.db`.

---

## Основні команди

| Команда | Опис |
|---------|------|
| `python translate.py FILE` | Перекласти файл (EN→UK за замовч.) |
| `python translate.py resume FILE` | Продовжити перерваний переклад |
| `python translate.py list` | Список всіх проєктів |
| `python translate.py status FILE` | Прогрес по главах |
| `python translate.py clean FILE --preview` | Перегляд очищення PDF |
| `python translate.py glossary list` | Показати глосарій |
| `python translate.py glossary add "Snape" "Снейп" --lang uk` | Додати термін |

---

## Флаги

| Флаг | За замовч. | Опис |
|------|-----------|------|
| `--from {en,ru}` | `en` | Мова джерела |
| `--to {uk}` | `uk` | Мова перекладу |
| `--quality {fast,balanced,max}`, `-q` | `balanced` | Якість: Haiku/$0.3 / Sonnet/$1 / Opus/$1.8 на 100k слів |
| `--chapters SPEC` | всі | Глави: `1-5`, `1,3,7` |
| `--output`, `-o PATH` | `output/<назва>_uk.docx` | Вихідний файл |
| `--collect-names` / `--no-collect-names` | увімк. | Авто-збір власних імен |

---

## Рівні якості та ціни

```
fast     — claude-haiku-4-5   → ~$0.30–0.50 за 100k слів  (чернетка)
balanced — claude-sonnet-4-6  → ~$1.00–1.50 за 100k слів  (рекомендується)
max      — claude-opus-4-8    → ~$1.80–2.50 за 100k слів  (фінальна якість)
```

Авто-збір імен завжди виконується на дешевій моделі (Haiku) — це дешево
незалежно від вибраного рівня якості.

**Приклади:**

```bash
# Дешевий варіант для чернетки
python translate.py book.epub --quality fast

# Рекомендований баланс
python translate.py book.epub --quality balanced

# Максимальна якість для фінального видання
python translate.py book.epub --quality max
```

---

## Особливості

- **EN→UK та RU→UK** — напрям задається флагами `--from {en,ru}`.
- **Консистентність термінів** — канонічний глосарій (49 термінів) +
  авто-збір повторюваних ОС-імен на всю книгу.
- **Пост-перевірка** — сканування готового тексту на різнобій написань
  (г↔ґ, и↔і, е↔є, апостроф).
- **Resume-on-failure** — кожна глава зберігається в SQLite; повторний запуск
  пропускає вже перекладені.
- **Паралельність** — до 5 глав одночасно.
- **Кешування промптів** — ~90% економії на глосарії для книг (читання кешу ×0.1).
- **Форматування .docx** — Georgia 12pt, інтервал 1.5, поля 2.5 см, зміст,
  колонтитул.

---

## Двомовний глосарій

`fantranslate/glossary.json` — тримовний канон (49 термінів):

```json
{
  "Hogwarts": { "ru": "Хогвартс",  "uk": "Гоґвортс" },
  "Snape":    { "ru": "Снегг",     "uk": "Снейп"    }
}
```

Базовий UK-канон від В. Морозова / видавництва «А-БА-БА-ГА-ЛА-МА-ГА».
Спірні форми редагуються через `glossary add`.

---

## Авто-збір імен

Перед перекладом інструмент:
1. Витягує повторювані власні імена (зустрічаються ≥ 3 рази в середині речення).
2. Надсилає один запит до Haiku: «переведи ці імена для HP-фанфіку, JSON».
3. Фіксує їм єдиний переклад на всю книгу.

Таким чином ОС-персонажі, вигадані заклинання та локації мають єдиний переклад
у всіх главах.

---

## Тести

```bash
python -m pytest tests/
python -m pytest tests/ -v        # детально
```

42 тести покривають: глосарій, переводчик, авто-збір, консистентність,
чанкінг, SQLite, очищення PDF.

---

## Більше документації

Детальний опис усіх команд, архітектури, прикладів та розрахунків вартості
знаходиться в [`fantranslate/README.md`](./fantranslate/README.md).

---

## Архітектура

```
translate.py              CLI (typer + rich)
config.py                 моделі, ціни, ліміти
glossary.json             тримовний HP-глосарій

core/
  parser_epub.py          витяг глав з EPUB
  parser_pdf.py           витяг текст з PDF по сторінках
  cleaner_pdf.py          очищення (колонтитули, номери)
  translator.py           AsyncAnthropic + caching + retry
  glossary_builder.py     авто-збір повторюваних імен
  consistency.py          пост-перевірка різнобою написань
  estimator.py            оцінка вартості
  exporter_docx.py        експорт у .docx
  storage.py              SQLite: проєкти, перекладення
```

**Потік:** Файл → парсер → очищення → авто-збір імен (1 запит Haiku) →
Translator (до 5 паралельних запросів) → SQLite → .docx → перевірка консистентності.
