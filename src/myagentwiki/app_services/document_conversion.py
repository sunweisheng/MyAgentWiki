from __future__ import annotations

from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

try:
    from markitdown import MarkItDown
except ImportError:  # pragma: no cover - doctor reports the missing required package
    MarkItDown = None


class MarkItDownConversionError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def get_markitdown_converter():
    if MarkItDown is None:
        raise MarkItDownConversionError(
            "MarkItDown is not installed. Run `python -m pip install -e .` first."
        )
    return MarkItDown(enable_plugins=False)


@lru_cache(maxsize=1)
def get_markitdown_version() -> str:
    try:
        return version("markitdown")
    except PackageNotFoundError:  # pragma: no cover - import and metadata normally agree
        return "unknown"


def convert_local_document(raw_path: Path) -> tuple[str, dict]:
    result = get_markitdown_converter().convert_local(raw_path)
    markdown = str(getattr(result, "markdown", "") or "").strip()
    if not markdown:
        raise MarkItDownConversionError("MarkItDown returned empty Markdown output.")

    title = str(getattr(result, "title", "") or "").strip() or None
    normalized_markdown = markdown + "\n"
    return normalized_markdown, {
        "content_format": "markdown",
        "extraction_method": "markitdown",
        "extraction_quality": "good",
        "warnings": [],
        "location_map": {
            "type": "markitdown",
            "source_path": str(raw_path),
            "converter": "microsoft/markitdown",
            "converter_version": get_markitdown_version(),
            "document_title": title,
            "normalized_line_range": f"1-{len(normalized_markdown.splitlines()) or 1}",
        },
    }
