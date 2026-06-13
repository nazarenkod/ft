# FanTranslate v1.0 — UA Edition

Локальный CLI-инструмент для автоматизированного перевода фанфиков по вселенной
Гарри Поттера **на украинский язык** — с английского или русского источника.

EPUB / PDF → очистка текста → перевод через Claude API с каноническим
украинским HP-глоссарием → готовый `.docx`.

## Возможности

- **EN→UK и RU→UK** — направление задаётся флагами `--from {en,ru} --to uk`.
  Для русского источника глоссарий матчится по русским формам (`Хогвартс → Гоґвортс`).
- **EPUB и PDF на входе** — главы извлекаются по структуре книги (EPUB)
  или эвристикой (`Chapter N`, ALL CAPS) после пайплайна очистки PDF
  (колонтитулы, номера страниц, разорванные строки).
- **Перевод через Claude API** — модель `claude-sonnet-4-6`; глоссарий
  кэшируется (prompt caching, ~90% экономии на этой части input-токенов).
- **Консистентность терминов — два уровня:**
  1. *Канонический глоссарий* в кэшируемом system-prompt (одинаков для всех
     глав/чанков).
  2. *Авто-сбор имён* — перед переводом из всего текста извлекаются
     повторяющиеся имена собственные (ОС-персонажи, выдуманные заклинания/места),
     им фиксируется единый перевод на всю книгу. Отключается `--no-collect-names`.
- **Пост-проверка** — после экспорта готовый текст сканируется на разнобой
  написаний (Гоґвортс / Ґоґвортс / без апострофа) и выводит предупреждения.
- **Параллельность** — до 5 глав одновременно (asyncio).
- **Resume-on-failure** — каждая глава сразу фиксируется в SQLite;
  повторный запуск пропускает уже переведённые главы.
- **Оценка стоимости до запуска** — точная через `count_tokens` API
  или эвристикой без сети.
- **Экспорт в .docx** — Georgia 12pt, интервал 1.5, поля 2.5 см,
  оглавление, колонтитул с названием и номером страницы.

## Установка

```bash
cd fantranslate
pip install -r requirements.txt
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env
```

Требования: Python 3.11+, ключ Claude API (https://console.anthropic.com).

## Использование

```bash
# Перевод (по умолчанию en -> uk)
python translate.py input.epub
python translate.py input.epub --from ru --to uk        # русский источник
python translate.py input.epub --output my.docx
python translate.py input.pdf --chapters 1-5            # только главы 1–5
python translate.py input.epub --no-collect-names       # без авто-сбора имён

# Управление проектами
python translate.py list                                # список всех переводов
python translate.py resume input.epub                   # продолжить прерванный
python translate.py status input.epub                   # прогресс по главам

# Утилиты
python translate.py glossary list                       # показать глоссарий
python translate.py glossary add "Snape" "Снейп"        # добавить UK-термин
python translate.py glossary add "Snape" "Снегг" --lang ru
python translate.py clean input.pdf --preview           # предпросмотр очистки PDF
```

Готовые переводы сохраняются в `output/` (`<имя>_uk.docx`), прогресс — в
`translations.db`.

## Глоссарий

`glossary.json` — трёхъязычный канон по английскому ключу:

```json
{ "Hogwarts": { "ru": "Хогвартс", "uk": "Гоґвортс" } }
```

Украинские формы основаны на переводе видавництва «А-БА-БА-ГА-ЛА-МА-ГА»
(В. Морозов). Часть форм спорна между изданиями — правьте под себя командой
`glossary add "English" "Ваш вариант" --lang uk` или прямо в файле. Глоссарий
рендерится в system-prompt в детерминированном порядке (стабильный кэш) и
применяется во всех грамматических формах.

## Стоимость

Sonnet 4.6: $3 input / $15 output за миллион токенов; чтение кэша ×0.1.
Фанфик ~100 тыс. слов обходится примерно в $2–4. Авто-сбор имён — один
дополнительный запрос на книгу (десятки токенов вывода).

## Тесты

```bash
python -m pytest tests/
```

Тесты не требуют API-ключа: переводчик и авто-сбор имён проверяются с
мок-клиентом.

## Архитектура

```
translate.py          # CLI (typer + rich)
config.py             # модель, языки, цены, лимиты, .env
glossary.json         # трёхъязычный HP-глоссарий
core/
  parser_epub.py      # ebooklib + BeautifulSoup → главы
  parser_pdf.py       # pdfplumber → сырой текст по страницам
  cleaner_pdf.py      # пайплайн очистки + детекция глав
  translator.py       # AsyncAnthropic: caching, чанкинг, retry, semaphore, языки
  glossary_builder.py # авто-сбор повторяющихся имён собственных
  consistency.py      # пост-проверка разнобоя написаний
  estimator.py        # оценка стоимости (count_tokens / эвристика)
  exporter_docx.py    # python-docx → .docx
  storage.py          # SQLite: projects / chapters / translations
```

Главы длиннее 3000 слов делятся на части с перекрытием 200 слов;
перекрытие передаётся модели как контекст и не дублируется в результате.
