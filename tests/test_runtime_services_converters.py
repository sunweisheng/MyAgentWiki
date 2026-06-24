from __future__ import annotations

from unittest import mock

from myagentwiki.app_services import runtime_services


def test_runtime_services_legacy_doc_converter_extracts_visible_snippets(tmp_path) -> None:
    raw_path = tmp_path / "legacy.doc"
    payload = (
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
        + b"\x00\x01BinaryPrefix"
        + b"Project Plan 2026"
        + b"\x00\x02"
        + "知识声明层需要可追踪".encode("utf-16le")
        + b"\x00\x03Tail"
    )
    raw_path.write_bytes(payload)

    markdown, metadata = runtime_services.convert_legacy_doc_to_markdown(raw_path)

    assert "# legacy" in markdown
    assert metadata["extraction_quality"] == "partial"
    assert "legacy_doc_binary_fallback" in metadata["warnings"]


def test_runtime_services_image_converter_without_tesseract_keeps_metadata_only(tmp_path) -> None:
    raw_path = tmp_path / "diagram.png"
    raw_path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\x0dIHDR"
        + (32).to_bytes(4, "big")
        + (16).to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )

    with mock.patch("myagentwiki.app_services.runtime_services.command_exists", return_value=False):
        markdown, metadata = runtime_services.convert_image_to_markdown(raw_path)

    assert "# diagram" in markdown
    assert metadata["extraction_quality"] == "partial"
    assert "tesseract_missing" in metadata["warnings"]
