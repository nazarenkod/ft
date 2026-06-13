"""Экспорт перевода в .docx (PRD §2.5): Georgia 12pt, 1.5 интервал,
поля 2.5 см, колонтитул, оглавление."""

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt


def _set_base_style(document: Document) -> None:
    style = document.styles["Normal"]
    style.font.name = "Georgia"
    style.font.size = Pt(12)
    style.paragraph_format.line_spacing = 1.5
    style.paragraph_format.first_line_indent = Cm(1.25)

    for section in document.sections:
        section.top_margin = Cm(2.5)
        section.bottom_margin = Cm(2.5)
        section.left_margin = Cm(2.5)
        section.right_margin = Cm(2.5)


def _add_field(paragraph, instruction: str) -> None:
    """Вставляет поле Word (PAGE, TOC и т.п.) — python-docx не имеет API для полей."""
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = instruction
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(begin)
    run._r.append(instr)
    run._r.append(end)


def _add_footer(document: Document, title: str) -> None:
    footer = document.sections[0].footer
    paragraph = footer.paragraphs[0]
    paragraph.text = ""
    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    # название слева, номер страницы справа через таб
    tab_stops = paragraph.paragraph_format.tab_stops
    usable_width = (
        document.sections[0].page_width
        - document.sections[0].left_margin
        - document.sections[0].right_margin
    )
    tab_stops.add_tab_stop(usable_width, WD_TAB_ALIGNMENT.RIGHT)
    paragraph.add_run(f"{title}\t")
    _add_field(paragraph, "PAGE")


# Подпись на титуле и заголовок оглавления по языку-цели.
_SUBTITLE = {
    "uk": ("Переклад виконано FanTranslate", "Зміст"),
    "ru": ("Перевод выполнен FanTranslate", "Оглавление"),
}


def export_docx(
    title: str,
    chapters: list[tuple[str, str]],  # (заголовок главы, переведённый текст)
    output_path: Path,
    target_lang: str = "uk",
) -> Path:
    subtitle_text, toc_label = _SUBTITLE.get(target_lang, _SUBTITLE["uk"])
    document = Document()
    _set_base_style(document)
    _add_footer(document, title)

    # Титул
    heading = document.add_heading(title, level=0)
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle = document.add_paragraph(subtitle_text)
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle.paragraph_format.first_line_indent = None
    document.add_page_break()

    # Оглавление: поле TOC, Word построит его по заголовкам при открытии
    toc_title = document.add_paragraph(toc_label)
    toc_title.runs[0].bold = True
    toc_title.paragraph_format.first_line_indent = None
    toc_paragraph = document.add_paragraph()
    _add_field(toc_paragraph, 'TOC \\o "1-1" \\h \\z \\u')
    document.add_page_break()

    for chapter_title, text in chapters:
        document.add_heading(chapter_title, level=1)
        for paragraph in text.split("\n\n"):
            paragraph = paragraph.strip()
            if paragraph:
                document.add_paragraph(paragraph)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(output_path))
    return output_path
