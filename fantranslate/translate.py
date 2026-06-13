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
from core import translator as tr
from core.cleaner_pdf import clean_pdf_text, parse_pdf_chapters
from core.estimator import estimate_cost
from core.exporter_docx import export_docx
from core.models import Chapter, TranslationResult
from core.parser_epub import parse_epub
from core.parser_pdf import extract_pages
from core.storage import Storage

app = typer.Typer(help="FanTranslate v1.0 — HP Edition", add_completion=False)
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


def _run_translation(path: Path, output: str | None, chapters_spec: str | None) -> None:
    glossary = tr.load_glossary()
    chapters = _load_chapters(path)
    storage = Storage(config.DB_PATH)
    project_id = storage.get_or_create_project(path, chapters)

    done = storage.translated_indices(project_id)
    todo = [c for c in chapters if c.idx not in done]
    if chapters_spec:
        wanted = _parse_range(chapters_spec, max(c.idx for c in chapters))
        todo = [c for c in todo if c.idx in wanted]

    total_words = sum(c.word_count for c in chapters)
    console.print("\n[bold]FanTranslate v1.0 — HP Edition[/bold]\n")
    console.print(f"Файл:    \"{path.name}\"")

    estimate = estimate_cost(todo, glossary)
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
            translator = tr.Translator(glossary)
        except RuntimeError as exc:
            console.print(f"[red]{exc}[/red]")
            storage.close()
            raise typer.Exit(1)
        _translate_with_progress(translator, storage, project_id, todo)

    _export(storage, project_id, path, output)
    storage.close()


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


def _export(storage: Storage, project_id: int, path: Path, output: str | None) -> None:
    rows = storage.get_translations(project_id)
    if not rows:
        console.print("[yellow]Нет переведённых глав — экспорт пропущен.[/yellow]")
        return
    out_path = Path(output) if output else config.OUTPUT_DIR / f"{path.stem}_ru.docx"
    export_docx(path.stem, [(r["title"], r["text"]) for r in rows], out_path)
    storage.set_output_path(project_id, str(out_path))
    console.print(f"[bold green]Сохранено: {out_path}[/bold green]")


@app.command(name="translate")
def translate_cmd(
    file: Path = typer.Argument(..., exists=True, readable=True, help="EPUB или PDF файл"),
    output: str | None = typer.Option(None, "--output", "-o", help="Путь к .docx"),
    chapters: str | None = typer.Option(None, "--chapters", help="Например: 1-5 или 1,3,7"),
):
    """Перевести фанфик (основная команда)."""
    _run_translation(file, output, chapters)


@app.command(name="resume")
def resume_cmd(
    file: Path = typer.Argument(..., exists=True, readable=True),
    output: str | None = typer.Option(None, "--output", "-o"),
):
    """Продолжить прерванный перевод (синоним translate: главы из БД пропускаются)."""
    _run_translation(file, output, None)


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
    for en, ru in sorted(glossary.items()):
        table.add_row(en, ru)
    console.print(table)


@glossary_app.command(name="add")
def glossary_add(english: str, russian: str):
    """Добавить термин: glossary add "Snape" "Снейп"."""
    glossary = tr.load_glossary()
    old = glossary.get(english)
    glossary[english] = russian
    tr.save_glossary(glossary)
    if old:
        console.print(f"Обновлено: {english} -> {russian} (было: {old})")
    else:
        console.print(f"Добавлено: {english} -> {russian}")


def main() -> None:
    # `python translate.py book.epub` без подкоманды — синоним translate
    known = {"translate", "resume", "list", "status", "clean", "glossary", "--help", "--install-completion", "--show-completion"}
    if len(sys.argv) > 1 and sys.argv[1] not in known:
        sys.argv.insert(1, "translate")
    app()


if __name__ == "__main__":
    main()
