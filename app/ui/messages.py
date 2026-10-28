"""Presentation messages for the desktop UI."""

from app.ui.i18n import get_language, translate_format


def import_preview_counts(valid: int, invalid: int, duplicate: int, ambiguous: int, blockers: int) -> str:
    return translate_format(
        "Valid: {valid} · Invalid: {invalid} · Duplicate: {duplicate} · Ambiguous: {ambiguous} · Blocking errors: {blockers}. Nothing has been imported yet.",
        valid=valid, invalid=invalid, duplicate=duplicate, ambiguous=ambiguous, blockers=blockers)


def page_caption(page: int, pages: int, count: int, noun: str = "rows") -> str:
    template = "Page {page} of {pages} · {count} rows" if noun == "rows" else "Page {page} of {pages} · {count} transactions"
    return translate_format(template, page=page, pages=pages, count=count)


def import_result(status: str, added: int, skipped: int, unclassified: str,
                  duplicate: int = 0, invalid: int = 0) -> str:
    prefix = "Identical file already imported." if status == "identical_file" else "Import committed."
    template = ("{prefix} Added: {added} · Duplicate skipped: {duplicate} · Invalid: {invalid} "
                "· Unclassified added: {unclassified} · Skipped: {skipped}")
    localized = {
        "Identical file already imported.": "Ижил файл өмнө нь импортлогдсон.",
        "Import committed.": "Импорт амжилттай.",
    }.get(prefix, prefix)
    if get_language() == "mn":
        template = ("{prefix} Нэмсэн: {added} · Давхардсан: {duplicate} · Хүчингүй: {invalid} "
                    "· Алгассан: {skipped} · Нэмэгдсэн ангилаагүй: {unclassified}")
    return template.format(prefix=localized, added=added, skipped=skipped,
                           duplicate=duplicate, invalid=invalid, unclassified=unclassified)
