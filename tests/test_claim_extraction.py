from __future__ import annotations

from myagentwiki.cli import split_claim_candidates_from_text


def test_split_claim_candidates_filters_headings_and_paths() -> None:
    # 标题、目录路径、纯链接这类噪声不应该直接变成 claim。
    text = """
    # 项目说明
    raw/topic.md
    https://example.com/reference
    - 系统需要保留知识声明到原始文档切块的回链能力。
    """

    candidates = split_claim_candidates_from_text(text)

    assert candidates == ["系统需要保留知识声明到原始文档切块的回链能力"]


def test_split_claim_candidates_breaks_long_chinese_paragraph_into_multiple_claims() -> None:
    # 长段落里如果包含多个明确结论，应该尽量拆成多个 claim，而不是整段吞掉。
    text = (
        "LLM Wiki 不只是查询时临时拼接答案，而是持续维护一个带交叉引用的知识集合，"
        "因此系统需要把结论回链到 claim 和 chunk，"
        "同时还要把冲突和近似重复结论送入人工审核队列。"
    )

    candidates = split_claim_candidates_from_text(text)

    assert len(candidates) >= 2
    assert any("持续维护一个带交叉引用的知识集合" in item for item in candidates)
    assert any("把结论回链到 claim 和 chunk" in item for item in candidates)


def test_split_claim_candidates_keeps_useful_fallback_when_only_one_sentence_exists() -> None:
    # 如果正文只有一条长句，也不该因为清洗过度把它扔空。
    text = "知识声明层应该能反向查到自己被多少个 Wiki 页面引用。"

    candidates = split_claim_candidates_from_text(text)

    assert candidates == ["知识声明层应该能反向查到自己被多少个 Wiki 页面引用"]
