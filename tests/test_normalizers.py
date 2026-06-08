from __future__ import annotations

import json
import os
from unittest import mock
from pathlib import Path

from myagentwiki.cli import (
    apply_alias_override_action,
    convert_image_to_markdown,
    convert_legacy_doc_to_markdown,
    convert_legacy_xls_to_markdown,
    enrich_markdown_with_embedded_images,
    load_page_alias_overrides,
    sanitize_page_filename,
    sanitize_page_slug,
    source_summary_page_path,
    update_page_alias_overrides_with_lock,
)


def test_convert_legacy_doc_to_markdown_extracts_visible_snippets(tmp_path: Path) -> None:
    # 这里不追求构造真正的 .doc 二进制，只验证当前 fallback 的行为契约：
    # 有可见文本片段时，应生成 partial 级 normalized 文本并附带明确 warnings。
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

    markdown, metadata = convert_legacy_doc_to_markdown(raw_path)

    assert "# legacy" in markdown
    assert "Project Plan 2026" in markdown or "知识声明层需要可追踪" in markdown
    assert metadata["extraction_quality"] == "partial"
    assert "legacy_doc_binary_fallback" in metadata["warnings"]
    assert metadata["location_map"]["type"] == "binary_snippet_map"
    assert metadata["location_map"]["is_ole_container"] is True


def test_convert_legacy_xls_to_markdown_without_text_marks_poor_quality(tmp_path: Path) -> None:
    # 当 `.xls` 里捞不到可读文本时，也不应该直接异常中断；
    # 而是产出 poor 质量的占位 normalized 文本并保留清晰 warning。
    raw_path = tmp_path / "legacy.xls"
    raw_path.write_bytes(
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00\x01\x02\x03\x04\x05" * 16
    )

    markdown, metadata = convert_legacy_xls_to_markdown(raw_path)

    assert "# legacy" in markdown
    assert "当前纯 Python fallback 未提取到可读工作簿文本" in markdown
    assert metadata["extraction_quality"] == "poor"
    assert "legacy_xls_no_text_snippets" in metadata["warnings"]
    assert metadata["location_map"]["type"] == "binary_snippet_map"
    assert metadata["location_map"]["is_ole_container"] is True


def test_convert_image_to_markdown_without_tesseract_keeps_metadata_only(tmp_path: Path) -> None:
    # 没有 tesseract 时，图片标准化仍应稳定产出元数据级 normalized 文本。
    raw_path = tmp_path / "diagram.png"
    raw_path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\x0dIHDR"
        + (32).to_bytes(4, "big")
        + (16).to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )

    with mock.patch("myagentwiki.cli.command_exists", return_value=False):
        markdown, metadata = convert_image_to_markdown(raw_path)

    assert "# diagram" in markdown
    assert "当前环境未检测到 tesseract" in markdown
    assert metadata["extraction_quality"] == "partial"
    assert "tesseract_missing" in metadata["warnings"]
    assert metadata["location_map"]["ocr"]["used"] is False
    assert metadata["location_map"]["image"]["width"] == 32
    assert metadata["location_map"]["image"]["height"] == 16


def test_convert_image_to_markdown_with_ocr_text_includes_ocr_section(tmp_path: Path) -> None:
    # 有 OCR 文本时，normalized 文档里应包含 OCR 区块，并提升 extraction_method。
    raw_path = tmp_path / "scan.png"
    raw_path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\x0dIHDR"
        + (48).to_bytes(4, "big")
        + (48).to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )

    fake_completed = mock.Mock(returncode=0, stdout="知识库需要来源追踪和审核闭环", stderr="")
    with mock.patch("myagentwiki.cli.command_exists", return_value=True), mock.patch(
        "myagentwiki.cli.subprocess.run",
        return_value=fake_completed,
    ):
        markdown, metadata = convert_image_to_markdown(raw_path)

    assert "## OCR 文本 / OCR Text" in markdown
    assert "知识库需要来源追踪和审核闭环" in markdown
    assert metadata["extraction_method"] == "python_only+tesseract"
    assert metadata["location_map"]["ocr"]["used"] is True
    assert metadata["location_map"]["ocr"]["ok"] is True
    assert metadata["location_map"]["ocr"]["char_count"] > 0


def test_convert_image_to_markdown_uses_agent_assisted_fallback_when_ocr_missing(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "workspace"
    (workspace_dir / "config").mkdir(parents=True)
    (workspace_dir / "config" / "project.yml").write_text(
        'workspace:\n  schema_version: "v1"\nautomation:\n  image_to_text:\n    strategy: "agent_assisted"\n    command: ["python3", "-m", "myagentwiki.agent_hook"]\n    timeout_seconds: 30\n    min_confidence: 0.7\npaths:\n  raw: "../raw"\n  assets: "../assets"\n',
        encoding="utf-8",
    )
    raw_path = tmp_path / "diagram.png"
    raw_path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\x0dIHDR"
        + (32).to_bytes(4, "big")
        + (16).to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )

    with mock.patch("myagentwiki.cli.command_exists", return_value=False), mock.patch(
        "myagentwiki.cli.run_json_automation_command",
        return_value={
            "confidence": 0.92,
            "reason": "mock_llm_image_understanding",
            "summary": "识别到一张流程图",
            "extracted_text": "步骤一：收集资料。步骤二：进入 normalized。",
        },
    ):
        markdown, metadata = convert_image_to_markdown(raw_path, target=workspace_dir)

    assert "## LLM 图片理解 / LLM Image Understanding" in markdown
    assert "步骤一：收集资料。步骤二：进入 normalized。" in markdown
    assert metadata["location_map"]["llm_image_understanding"]["used"] is True
    assert metadata["location_map"]["llm_image_understanding"]["ok"] is True
    assert metadata["extraction_method"] == "python_only+agent_assisted"


def test_enrich_markdown_with_embedded_images_downloads_remote_assets_and_embeds_ocr(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "workspace"
    raw_dir = tmp_path / "raw"
    assets_dir = tmp_path / "assets"
    (workspace_dir / "config").mkdir(parents=True)
    raw_dir.mkdir()
    assets_dir.mkdir()
    (workspace_dir / "config" / "project.yml").write_text(
        'workspace:\n  schema_version: "v1"\npaths:\n  raw: "../raw"\n  assets: "../assets"\n',
        encoding="utf-8",
    )
    raw_path = raw_dir / "note.md"
    raw_path.write_text("# Note\n\n![diagram](https://example.com/diagram.png)\n", encoding="utf-8")
    source_record = {
        "source_id": "src_note_hash123456",
        "source_path": "../raw/note.md",
    }

    fake_png = (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\x0dIHDR"
        + (24).to_bytes(4, "big")
        + (24).to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )

    class FakeResponse:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload
            self.headers = {"Content-Type": "image/png"}

        def read(self) -> bytes:
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    fake_completed = mock.Mock(returncode=0, stdout="图里有可读文本", stderr="")
    with mock.patch("myagentwiki.cli.urllib.request.urlopen", return_value=FakeResponse(fake_png)), mock.patch(
        "myagentwiki.cli.command_exists", return_value=True
    ), mock.patch("myagentwiki.cli.subprocess.run", return_value=fake_completed):
        markdown, metadata = enrich_markdown_with_embedded_images(
            target=workspace_dir,
            source_record=source_record,
            raw_path=raw_path,
            raw_text=raw_path.read_text(encoding="utf-8"),
        )

    assert "## 内嵌图片内容 / Embedded Image Content" in markdown
    assert "图里有可读文本" in markdown
    assert metadata["location_map"]["image_count"] == 1
    saved_asset = Path(metadata["location_map"]["images"][0]["asset_path"])
    assert saved_asset.exists()
    assert saved_asset.parent.parent == assets_dir
    assert metadata["extraction_method"] == "python_only+remote_assets+tesseract"


def test_enrich_markdown_with_embedded_images_can_use_agent_assisted_fallback(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "workspace"
    raw_dir = tmp_path / "raw"
    assets_dir = tmp_path / "assets"
    (workspace_dir / "config").mkdir(parents=True)
    raw_dir.mkdir()
    assets_dir.mkdir()
    (workspace_dir / "config" / "project.yml").write_text(
        'workspace:\n  schema_version: "v1"\nautomation:\n  image_to_text:\n    strategy: "agent_assisted"\n    command: ["python3", "-m", "myagentwiki.agent_hook"]\n    timeout_seconds: 30\n    min_confidence: 0.7\npaths:\n  raw: "../raw"\n  assets: "../assets"\n',
        encoding="utf-8",
    )
    raw_path = raw_dir / "note.md"
    raw_path.write_text("# Note\n\n![diagram](https://example.com/diagram.png)\n", encoding="utf-8")
    source_record = {
        "source_id": "src_note_hashagent",
        "source_path": "../raw/note.md",
    }
    fake_png = (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\x0dIHDR"
        + (24).to_bytes(4, "big")
        + (24).to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )

    class FakeResponse:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload
            self.headers = {"Content-Type": "image/png"}

        def read(self) -> bytes:
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    with mock.patch("myagentwiki.cli.urllib.request.urlopen", return_value=FakeResponse(fake_png)), mock.patch(
        "myagentwiki.cli.command_exists", return_value=False
    ), mock.patch(
        "myagentwiki.cli.run_json_automation_command",
        return_value={
            "confidence": 0.93,
            "reason": "mock_llm_image_understanding",
            "summary": "思维导图摘要",
            "extracted_text": "主题A 连接到主题B，并附带两条说明。",
        },
    ):
        markdown, metadata = enrich_markdown_with_embedded_images(
            target=workspace_dir,
            source_record=source_record,
            raw_path=raw_path,
            raw_text=raw_path.read_text(encoding="utf-8"),
        )

    assert "## LLM 图片理解 / LLM Image Understanding" in markdown
    assert "主题A 连接到主题B" in markdown
    assert metadata["location_map"]["images"][0]["image_metadata"]["llm_image_understanding"]["used"] is True


def test_enrich_markdown_with_embedded_images_marks_out_of_raw_local_image_as_unconvertible(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "workspace"
    raw_dir = tmp_path / "raw"
    (workspace_dir / "config").mkdir(parents=True)
    raw_dir.mkdir()
    (workspace_dir / "config" / "project.yml").write_text(
        'workspace:\n  schema_version: "v1"\npaths:\n  raw: "../raw"\n  assets: "../assets"\n',
        encoding="utf-8",
    )
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    raw_path = raw_dir / "note.md"
    raw_path.write_text("# Note\n\n![diagram](../outside/diagram.png)\n", encoding="utf-8")
    (outside_dir / "diagram.png").write_bytes(b"not-important")
    source_record = {
        "source_id": "src_note_hash654321",
        "source_path": "../raw/note.md",
    }

    markdown, metadata = enrich_markdown_with_embedded_images(
        target=workspace_dir,
        source_record=source_record,
        raw_path=raw_path,
        raw_text=raw_path.read_text(encoding="utf-8"),
    )

    assert "源文件包含图片，但内容暂时无法转换为文本" in markdown
    assert any(item.startswith("markdown_image_conversion_failed:1:ValueError") for item in metadata["warnings"])


def test_update_page_alias_overrides_with_lock_preserves_sequential_alias_updates(tmp_path: Path) -> None:
    # 覆盖层更新应基于锁内最新状态叠加，避免后一轮把前一轮 alias 写丢。
    workspace_dir = tmp_path / "workspace"
    (workspace_dir / "state").mkdir(parents=True)
    live_aliases_by_page_id = {
        "page-a": ["原有别名A"],
        "page-b": ["原有别名B"],
    }

    def assign_alias(alias_value: str, primary_page_id: str) -> None:
        def updater(overrides: dict) -> dict:
            return apply_alias_override_action(
                overrides=overrides,
                live_aliases_by_page_id=live_aliases_by_page_id,
                candidate_page_ids=["page-a", "page-b"],
                primary_page_id=primary_page_id,
                alias_value=alias_value,
                action="assign_alias",
            )

        update_page_alias_overrides_with_lock(workspace_dir, updater)

    assign_alias("共享术语一", "page-a")
    assign_alias("共享术语二", "page-b")

    overrides = load_page_alias_overrides(workspace_dir)
    assert "共享术语一" in overrides["page_aliases"]["page-a"]["aliases"]
    assert "共享术语二" in overrides["page_aliases"]["page-b"]["aliases"]
    assert "原有别名A" in overrides["page_aliases"]["page-a"]["aliases"]
    assert "原有别名B" in overrides["page_aliases"]["page-b"]["aliases"]


def test_sanitize_page_filename_truncates_long_multibyte_titles_stably() -> None:
    title = "超长标题" * 80

    filename = sanitize_page_filename(title)

    assert len(filename.encode("utf-8")) <= 240
    assert filename
    assert sanitize_page_filename(title) == filename


def test_sanitize_page_filename_keeps_distinct_long_titles_distinct() -> None:
    title_a = ("知识声明层设计说明" * 40) + "A"
    title_b = ("知识声明层设计说明" * 40) + "B"

    filename_a = sanitize_page_filename(title_a)
    filename_b = sanitize_page_filename(title_b)

    assert filename_a != filename_b


def test_source_summary_page_path_limits_long_slug_and_source_id() -> None:
    title = "来源摘要标题" * 70
    source_id = "src_" + ("nested_topic_note_" * 40)

    page_path = source_summary_page_path(source_id, title)

    assert page_path.parent == Path("wiki") / "sources"
    assert len(page_path.name.encode("utf-8")) <= 240
    assert page_path.suffix == ".md"
    assert page_path.stem
