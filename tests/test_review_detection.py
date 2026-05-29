from __future__ import annotations

from myagentwiki.cli import (
    build_claim_similarity_tokens,
    claims_are_similar_for_review,
    collect_claim_review_candidate_ids,
)


def test_claim_similarity_detects_near_duplicate_with_different_prefixes() -> None:
    # 这类句子以前很容易漏掉：
    # 前半句铺垫不同，但真正的结论主体基本相同。
    left = "系统需要把结论回链到 claim 和 chunk，同时保留来源文件定位信息。"
    right = "为了后续审计与反向搜索，系统需要把结论回链到 claim 和 chunk。"

    assert claims_are_similar_for_review(left, right) is True


def test_claim_similarity_detects_conflict_pair_after_negation_removed() -> None:
    # 否定词去掉之后 base 很接近，这类句子应该进入 conflict review。
    left = "知识声明层不应该直接删除存在争议的结论。"
    right = "知识声明层应该直接删除存在争议的结论。"

    assert claims_are_similar_for_review(left, right) is True


def test_claim_similarity_avoids_false_positive_for_unrelated_claims() -> None:
    # 同属于知识库系统主题，不代表就该被丢进近重复审核。
    left = "系统需要使用 Git 管理本地版本历史。"
    right = "图片标准化阶段应优先提取 EXIF 和 OCR 元数据。"

    assert claims_are_similar_for_review(left, right) is False


def test_collect_claim_review_candidates_uses_token_index_beyond_prefix_bucket() -> None:
    # 这条回归专门验证“不是同一个前缀 bucket，也能通过 token 倒排被召回”。
    existing_claim = {
        "claim_id": "clm_existing",
        "text": "为了便于审计，系统需要把结论回链到 claim 和 chunk。",
    }
    incoming_claim = {
        "claim_id": "clm_incoming",
        "text": "系统需要把结论回链到 claim 和 chunk，同时记录来源文件位置。",
    }

    claims_by_similarity_bucket = {
        "为了便于审计，系统需要把结论回链到 ": [existing_claim],
    }
    claim_similarity_index: dict[str, set[str]] = {}
    for token in build_claim_similarity_tokens(existing_claim["text"]):
        claim_similarity_index.setdefault(token, set()).add(existing_claim["claim_id"])

    candidate_ids = collect_claim_review_candidate_ids(
        claim_record=incoming_claim,
        claims_by_similarity_bucket=claims_by_similarity_bucket,
        claim_similarity_index=claim_similarity_index,
    )

    assert "clm_existing" in candidate_ids
