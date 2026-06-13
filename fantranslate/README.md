# FanTranslate v1.0 — HP Edition

Локальный CLI-инструмент для автоматизированного перевода англоязычных
фанфиков по вселенной Гарри Поттера на русский язык.

EPUB / PDF → очистка текста → перевод через Claude API с каноническим
HP-глоссарием → готовый `.docx`.

## Возможности

- **EPUB и PDF на входе** — главы извлекаются по структуре книги (EPUB)
  или эвристикой (`Chapter N`, ALL CAPS) после пайплайна очистки PDF
  (колонтитулы, номера страниц, разорванные строки).
- **Перевод через Claude API** — модель `claude-sonnet-4-6`; глоссарий
  кэшируется (prompt caching, ~90% экономии на этой части input-токенов).
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
# Перевод файла
python translate.py input.epub
python translate.py input.epub --output my_translation.docx
python translate.py input.pdf --chapters 1-5      # только главы 1–5

# Управление проектами
python translate.py list                          # список всех переводов
python translate.py resume input.epub             # продолжить прерванный
python translate.py status input.epub             # прогресс по главам

# Утилиты
python translate.py glossary list                 # показать глоссарий
python translate.py glossary add "Snape" "Снегг"  # добавить термин
python translate.py clean input.pdf --preview     # предпросмотр очистки PDF
```

Готовые переводы сохраняются в `output/`, прогресс — в `translations.db`.

## Глоссарий

`glossary.json` — канонические термины российского издания
(Дамблдор, Крестраж, маггл, Косой переулок…). Редактируется вручную или
командой `glossary add`. Инжектируется в system prompt и кэшируется,
поэтому порядок терминов детерминирован.

## Стоимость

Sonnet 4.6: $3 input / $15 output за миллион токенов; чтение кэша ×0.1.
Фанфик ~100 тыс. слов обходится примерно в $2–4.

## Тесты

```bash
python -m pytest tests/
```

Тесты не требуют API-ключа: переводчик проверяется с мок-клиентом.

## Архитектура

```
translate.py          # CLI (typer + rich)
config.py             # модель, цены, лимиты, .env
glossary.json         # HP-глоссарий
core/
  parser_epub.py      # ebooklib + BeautifulSoup → главы
  parser_pdf.py       # pdfplumber → сырой текст по страницам
  cleaner_pdf.py      # пайплайн очистки + детекция глав
  translator.py       # AsyncAnthropic: caching, чанкинг, retry, semaphore
  estimator.py        # оценка стоимости (count_tokens / эвристика)
  exporter_docx.py    # python-docx → .docx
  storage.py          # SQLite: projects / chapters / translations
```

Главы длиннее 3000 слов делятся на части с перекрытием 200 слов;
перекрытие передаётся модели как контекст и не дублируется в результате.
