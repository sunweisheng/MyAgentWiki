from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from myagentwiki.cli import split_claim_candidates_from_text


def test_split_claim_candidates_keeps_independent_claims_beyond_first_three() -> None:
    text = (
        "系统需要先把原始资料标准化为稳定的 Markdown。"
        "然后按可回链的边界切成 chunk。"
        "每条 claim 都应该保留 source 和 chunk 的证据路径。"
        "冲突或近重复的 claim 应该进入 review 队列。"
        "query 返回结果时还应该附带推荐读序和风险提示。"
    )

    candidates = split_claim_candidates_from_text(text)

    assert len(candidates) >= 5
    assert "冲突或近重复的 claim 应该进入 review 队列" in candidates
    assert "query 返回结果时还应该附带推荐读序和风险提示" in candidates


def test_split_claim_candidates_keeps_short_meaningful_sentence() -> None:
    text = "系统必须保留回链。"

    candidates = split_claim_candidates_from_text(text)

    assert candidates == ["系统必须保留回链"]


def test_split_claim_candidates_keeps_short_standalone_clause_from_long_sentence() -> None:
    text = "系统会先建立索引，同时保留回链，并且支持增量更新。"

    candidates = split_claim_candidates_from_text(text)

    assert "系统会先建立索引，同时保留回链，并且支持增量更新" in candidates
    assert "保留回链" in candidates
    assert "支持增量更新" in candidates
