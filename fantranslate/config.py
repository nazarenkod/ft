"""Конфигурация FanTranslate: API-ключ, модель, лимиты, цены."""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Модель перевода (выбор PRD: баланс качества и цены)
MODEL = "claude-sonnet-4-6"

# Языки: источник (en/ru) и цель (uk). Меняются флагами --from/--to.
SOURCE_LANG = "en"
TARGET_LANG = "uk"
LANGUAGES = {
    "en": "English",
    "ru": "Russian",
    "uk": "Ukrainian",
}

# Параллельность: лимит одновременных запросов к API
MAX_CONCURRENT = 5

# Чанкинг: главы длиннее CHUNK_WORDS слов делятся на части
CHUNK_WORDS = 3000
CHUNK_OVERLAP_WORDS = 200

# Максимум выходных токенов на один запрос
MAX_TOKENS = 16000

# Retry поверх SDK: число попыток и базовая задержка (сек)
RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 2.0

# Цены claude-sonnet-4-6, $ за миллион токенов
PRICE_INPUT_PER_MTOK = 3.00
PRICE_OUTPUT_PER_MTOK = 15.00
CACHE_WRITE_MULTIPLIER = 1.25  # запись в кэш
CACHE_READ_MULTIPLIER = 0.10   # чтение из кэша

# Эвристика "слова -> токены" для оффлайн-оценки стоимости
WORDS_TO_TOKENS = 1.35
# Перевод на кириллицу (рус./укр.) обычно длиннее оригинала по токенам
OUTPUT_TOKENS_RATIO = 1.6

# Минимальный размер главы (слов) — меньше считается подозрительным
MIN_CHAPTER_WORDS = 100

GLOSSARY_PATH = BASE_DIR / "glossary.json"
DB_PATH = BASE_DIR / "translations.db"
OUTPUT_DIR = BASE_DIR / "output"
