from __future__ import annotations

from myagentwiki.deterministic_processor import process


def test_deterministic_processor_handles_semantic_batch_without_llm() -> None:
    result = process({
        "task": "review_document_analysis_batch",
        "items": [{
            "item_id": "source-1",
            "normalized_path": "normalized/plain_note.md",
            "title": "Note",
        }],
    })

    assert result["decisions"][0]["decision"]["document_kind"] == "note"
    assert result["decisions"][0]["decision"]["chunk_strategy_hint"] == "paragraph_first"


def test_deterministic_processor_keeps_image_result_conservative() -> None:
    result = process({"task": "describe_image", "image_name": "diagram.png"})

    assert result["extracted_text"] == ""
    assert result["confidence"] == 0.0
    assert result["warnings"]
