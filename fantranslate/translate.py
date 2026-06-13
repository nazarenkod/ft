#!/usr/bin/env python3
"""FanTranslate — CLI перевода HP-фанфиков (EPUB/PDF -> русский .docx)."""

import asyncio
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
from core import glossary_builder as gb
from core import translator as tr
from core.cleaner_pdf import clean_pdf_text, parse_pdf_chapters
from core.consistency import find_inconsistencies
from core.estimator import estimate_cost
from core.exporter_docx import export_docx
from core.models import Chapter, TranslationResult
from core.parser_epub import parse_epub
from core.parser_pdf import extract_pages
from core.storage import Storage

app = typer.Typer(help="FanTranslate v1.0 — UA Edition (EN/RU -> UK)", add_completion=False)
glossary_app = typer.Typer(help="Управление HP-глоссарием")
app.add_typer(glossary_app, name="glossary")
console = Console()


def _load_chapters(path: Path, warn_short: bool = True) -> list[Chapter]:
    suffix = path.suffix.lower()
    if suffix == ".epub":
        chapters = parse_epub(path)
    elif suffix == ".pdf":
        chapters = parse_pdf_chapters(extract_pages(path))
    else:
        console.print(f"[red]Неподдерживаемый формат: {suffix} (нужен .epub или .pdf)[/red]")
        raise typer.Exit(1)

    if not chapters:
        console.print("[red]Не удалось извлечь текст из файла.[/red]")
        raise typer.Exit(1)

    if warn_short:
        chapters = _filter_short_chapters(chapters)
    return chapters


def _filter_short_chapters(chapters: list[Chapter]) -> list[Chapter]:
    """PRD §2.2: глава < 100 слов — предупреждение, пропустить или оставить."""
    kept: list[Chapter] = []
    for chapter in chapters:
        if chapter.word_count < config.MIN_CHAPTER_WORDS:
            console.print(
                f"[yellow]⚠ Глава {chapter.idx} «{chapter.title}» содержит всего "
                f"{chapter.word_count} слов.[/yellow]"
            )
            # в неинтерактивном режиме переводим как есть, не блокируя пайплайн
            if sys.stdin.isatty() and not typer.confirm("Перевести как есть?", default=True):
                continue
        kept.append(chapter)
    # после пропусков нумерация остаётся исходной — важно для resume
    return kept


def _parse_range(spec: str, maximum: int) -> set[int]:
    """'1-5,8' -> {1,2,3,4,5,8}."""
    selected: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            selected.update(range(int(lo), int(hi) + 1))
        elif part:
            selected.add(int(part))
    return {i for i in selected if 1 <= i <= maximum}


def _run_translation(
    path: Path,
    output: str | None,
    chapters_spec: str | None,
    source_lang: str = config.SOURCE_LANG,
    target_lang: str = config.TARGET_LANG,
    collect_names: bool = True,
    model: str = config.MODEL,
) -> None:
    glossary = tr.load_glossary()
    pairs = tr.glossary_pairs(glossary, source_lang, target_lang)
    chapters = _load_chapters(path)
    storage = Storage(config.DB_PATH)
    project_id = storage.get_or_create_project(path, chapters)

    done = storage.translated_indices(project_id)
    todo = [c for c in chapters if c.idx not in done]
    if chapters_spec:
        wanted = _parse_range(chapters_spec, max(c.idx for c in chapters))
        todo = [c for c in todo if c.idx in wanted]

    total_words = sum(c.word_count for c in chapters)
    console.print("\n[bold]FanTranslate v1.0 — UA Edition[/bold]\n")
    console.print(f"Файл:    \"{path.name}\"")
    console.print(
        f"Напрям:  {config.LANGUAGES[source_lang]} -> {config.LANGUAGES[target_lang]}"
    )
    console.print(f"Модель:  {model}")

    estimate = estimate_cost(todo, pairs, source_lang, target_lang, model)
    marker = "" if estimate.exact else " (эвристика)"
    console.print(
        f"Глав:    {len(chapters)}  |  Слов: ~{total_words:,}  |  "
        f"Оценка: ~${estimate.cost_usd:.2f}{marker}"
    )
    if done:
        console.print(f"[green]Уже переведено: {len(done)} глав — пропускаем (resume).[/green]")
    if not todo:
        console.print("[green]Все главы уже переведены.[/green]")
    else:
        try:
            client = tr.make_client()
        except RuntimeError as exc:
            console.print(f"[red]{exc}[/red]")
            storage.close()
            raise typer.Exit(1)
        if collect_names:
            pairs = _collect_names(client, chapters, pairs, source_lang, target_lang)
        translator = tr.Translator(pairs, source_lang, target_lang, client=client, model=model)
        _translate_with_progress(translator, storage, project_id, todo)

    _export(storage, project_id, path, output, target_lang, pairs)
    storage.close()


def _collect_names(
    client,
    chapters: list[Chapter],
    pairs: dict[str, str],
    source_lang: str,
    target_lang: str,
) -> dict[str, str]:
    """Авто-сбор повторяющихся имён: фиксирует им единый перевод на всю книгу."""
    full_text = "\n\n".join(c.text for c in chapters)
    existing = set(pairs) | set(pairs.values())
    candidates = gb.extract_candidates(full_text, source_lang, existing=existing)
    if not candidates:
        return pairs
    try:
        collected = asyncio.run(
            gb.collect_names(client, candidates, source_lang, target_lang)
        )
    except Exception as exc:  # noqa: BLE001 — сбор имён не критичен для перевода
        console.print(f"[yellow]Авто-сбор имён пропущен: {exc}[/yellow]")
        return pairs
    if collected:
        console.print(
            f"[green]Зафиксировано имён для консистентности: {len(collected)}[/green]"
        )
    # Ручной канон приоритетнее авто-собранного.
    return {**collected, **pairs}


def _translate_with_progress(
    translator: "tr.Translator", storage: Storage, project_id: int, todo: list[Chapter]
) -> None:
    spent = 0.0
    failed: list[tuple[Chapter, Exception]] = []
    progress = Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    )

    def on_done(result: TranslationResult | Exception, chapter: Chapter) -> None:
        nonlocal spent
        if isinstance(result, Exception):
            failed.append((chapter, result))
            console.print(f"[red]✗ Глава {chapter.idx} «{chapter.title}» — {result}[/red]")
        else:
            storage.save_translation(project_id, result)
            spent += result.cost_usd
            minutes, seconds = divmod(int(result.duration_sec), 60)
            console.print(
                f"[green]✓[/green] Глава {chapter.idx:>2}  —  "
                f"{chapter.word_count:,} слов  —  ${result.cost_usd:.2f}  —  "
                f"{minutes:02d}:{seconds:02d}"
            )
        progress.advance(task)

    with progress:
        task = progress.add_task("Перевод", total=len(todo))
        asyncio.run(translator.translate_all(todo, on_done=on_done))

    console.print(f"\nИтого потрачено: ${spent:.2f}")
    if failed:
        console.print(
            f"[yellow]{len(failed)} глав не переведено — повторите запуск "
            f"(resume продолжит с места остановки).[/yellow]"
        )


def _export(
    storage: Storage,
    project_id: int,
    path: Path,
    output: str | None,
    target_lang: str = config.TARGET_LANG,
    pairs: dict[str, str] | None = None,
) -> None:
    rows = storage.get_translations(project_id)
    if not rows:
        console.print("[yellow]Нет переведённых глав — экспорт пропущен.[/yellow]")
        return
    out_path = (
        Path(output) if output else config.OUTPUT_DIR / f"{path.stem}_{target_lang}.docx"
    )
    export_docx(path.stem, [(r["title"], r["text"]) for r in rows], out_path, target_lang)
    storage.set_output_path(project_id, str(out_path))
    console.print(f"[bold green]Сохранено: {out_path}[/bold green]")

    if pairs:
        _report_inconsistencies(rows, pairs, target_lang)


def _report_inconsistencies(rows, pairs: dict[str, str], target_lang: str) -> None:
    """Сканирует готовый перевод на разнобой написаний терминов."""
    full_text = "\n\n".join(r["text"] for r in rows)
    findings = find_inconsistencies(full_text, pairs.values(), target_lang)
    if not findings:
        return
    console.print(
        f"\n[yellow]⚠ Возможный разнобой написаний ({len(findings)}):[/yellow]"
    )
    for canonical, variants in findings:
        console.print(
            f"  [yellow]{canonical}[/yellow] — встречаются также: "
            f"{', '.join(variants)}"
        )
    console.print(
        "[dim]Поправьте вручную или зафиксируйте форму: "
        "glossary add \"English\" \"Канон\" --lang " + target_lang + "[/dim]"
    )


def _resolve_model(quality: str) -> str:
    """Преобразует --quality в ID модели; неизвестное значение = balanced."""
    return config.QUALITY_MODELS.get(quality, config.MODEL)


def _check_langs(source_lang: str, target_lang: str) -> None:
    if source_lang not in config.LANGUAGES or source_lang not in ("en", "ru"):
        console.print(f"[red]Язык-источник должен быть en или ru, не {source_lang}.[/red]")
        raise typer.Exit(1)
    if target_lang not in config.LANGUAGES:
        console.print(f"[red]Неизвестный язык-цель: {target_lang}.[/red]")
        raise typer.Exit(1)
    if source_lang == target_lang:
        console.print("[red]Язык-источник и язык-цель совпадают.[/red]")
        raise typer.Exit(1)


@app.command(name="translate")
def translate_cmd(
    file: Path = typer.Argument(..., exists=True, readable=True, help="EPUB или PDF файл"),
    output: str | None = typer.Option(None, "--output", "-o", help="Путь к .docx"),
    chapters: str | None = typer.Option(None, "--chapters", help="Например: 1-5 или 1,3,7"),
    source_lang: str = typer.Option(config.SOURCE_LANG, "--from", help="Язык-источник: en или ru"),
    target_lang: str = typer.Option(config.TARGET_LANG, "--to", help="Язык-цель: uk"),
    collect_names: bool = typer.Option(
        True, "--collect-names/--no-collect-names",
        help="Авто-сбор повторяющихся имён для консистентности перевода",
    ),
    quality: str = typer.Option(
        "balanced", "--quality", "-q",
        help="Качество/стоимость: fast (Haiku, ~$0.3/100k слов), "
             "balanced (Sonnet, ~$1, по умолчанию), max (Opus, ~$2)",
    ),
):
    """Перевести фанфик (основная команда)."""
    _check_langs(source_lang, target_lang)
    model = _resolve_model(quality)
    _run_translation(file, output, chapters, source_lang, target_lang, collect_names, model)


@app.command(name="resume")
def resume_cmd(
    file: Path = typer.Argument(..., exists=True, readable=True),
    output: str | None = typer.Option(None, "--output", "-o"),
    source_lang: str = typer.Option(config.SOURCE_LANG, "--from", help="Язык-источник: en или ru"),
    target_lang: str = typer.Option(config.TARGET_LANG, "--to", help="Язык-цель: uk"),
    collect_names: bool = typer.Option(
        True, "--collect-names/--no-collect-names",
        help="Авто-сбор повторяющихся имён для консистентности перевода",
    ),
    quality: str = typer.Option(
        "balanced", "--quality", "-q",
        help="Качество/стоимость: fast (Haiku), balanced (Sonnet), max (Opus)",
    ),
):
    """Продолжить прерванный перевод (синоним translate: главы из БД пропускаются)."""
    _check_langs(source_lang, target_lang)
    model = _resolve_model(quality)
    _run_translation(file, output, None, source_lang, target_lang, collect_names, model)


@app.command(name="list")
def list_cmd():
    """Список всех переводов."""
    storage = Storage(config.DB_PATH)
    rows = storage.list_projects()
    storage.close()
    if not rows:
        console.print("Переводов пока нет.")
        return
    table = Table(title="Переводы")
    table.add_column("ID", justify="right")
    table.add_column("Файл")
    table.add_column("Прогресс", justify="center")
    table.add_column("Потрачено", justify="right")
    table.add_column("Создан")
    for r in rows:
        table.add_row(
            str(r["id"]), r["filename"],
            f"{r['done']}/{r['total_chapters']}",
            f"${r['spent']:.2f}", r["created_at"],
        )
    console.print(table)


@app.command(name="status")
def status_cmd(file: Path = typer.Argument(..., exists=True, readable=True)):
    """Прогресс перевода по главам."""
    storage = Storage(config.DB_PATH)
    project = storage.find_project(file)
    if project is None:
        console.print("Этот файл ещё не переводился.")
        storage.close()
        return
    table = Table(title=f"{project['filename']}")
    table.add_column("№", justify="right")
    table.add_column("Глава")
    table.add_column("Слов", justify="right")
    table.add_column("Статус")
    table.add_column("Цена", justify="right")
    for r in storage.chapter_status(project["id"]):
        status = "[green]✓ готово[/green]" if r["status"] == "done" else "[dim]ожидает[/dim]"
        cost = f"${r['cost_usd']:.2f}" if r["cost_usd"] is not None else "—"
        table.add_row(str(r["idx"]), r["title"], f"{r['word_count']:,}", status, cost)
    console.print(table)
    storage.close()


@app.command(name="clean")
def clean_cmd(
    file: Path = typer.Argument(..., exists=True, readable=True, help="PDF файл"),
    preview: bool = typer.Option(False, "--preview", help="Показать очищенный текст"),
):
    """Прогнать пайплайн очистки PDF и показать результат."""
    if file.suffix.lower() != ".pdf":
        console.print("[red]Команда clean работает только с PDF.[/red]")
        raise typer.Exit(1)
    pages = extract_pages(file)
    text = clean_pdf_text(pages)
    chapters = parse_pdf_chapters(pages)
    console.print(
        f"Страниц: {len(pages)}  |  Глав найдено: {len(chapters)}  |  "
        f"Слов: ~{len(text.split()):,}"
    )
    if preview:
        for chapter in chapters:
            console.print(f"\n[bold]── Глава {chapter.idx}: {chapter.title} "
                          f"({chapter.word_count} слов)[/bold]")
            snippet = chapter.text[:500]
            console.print(snippet + ("…" if len(chapter.text) > 500 else ""))


@glossary_app.command(name="list")
def glossary_list():
    """Показать глоссарий."""
    glossary = tr.load_glossary()
    table = Table(title=f"HP-глоссарий ({len(glossary)} терминов)")
    table.add_column("English")
    table.add_column("Русский")
    table.add_column("Українська")
    for en, forms in sorted(glossary.items()):
        table.add_row(en, forms.get("ru", "—"), forms.get("uk", "—"))
    console.print(table)


@glossary_app.command(name="add")
def glossary_add(
    english: str,
    translation: str,
    lang: str = typer.Option("uk", "--lang", help="Язык перевода: uk или ru"),
):
    """Добавить/обновить термин: glossary add "Snape" "Снейп" --lang uk."""
    if lang not in ("uk", "ru"):
        console.print("[red]--lang должен быть uk или ru.[/red]")
        raise typer.Exit(1)
    glossary = tr.load_glossary()
    forms = glossary.setdefault(english, {})
    old = forms.get(lang)
    forms[lang] = translation
    tr.save_glossary(glossary)
    if old:
        console.print(f"Обновлено [{lang}]: {english} -> {translation} (было: {old})")
    else:
        console.print(f"Добавлено [{lang}]: {english} -> {translation}")


def main() -> None:
    # `python translate.py book.epub` без подкоманды — синоним translate
    known = {"translate", "resume", "list", "status", "clean", "glossary", "--help", "--install-completion", "--show-completion"}
    if len(sys.argv) > 1 and sys.argv[1] not in known:
        sys.argv.insert(1, "translate")
    app()


if __name__ == "__main__":
    main()
