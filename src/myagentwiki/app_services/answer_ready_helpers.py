from __future__ import annotations


def build_answer_ready_payload(
    query_payload: dict,
    *,
    answer_ready_output_version: str,
    page_type_profile: object,
) -> dict:
    base_payload = {
        "contract_version": answer_ready_output_version,
        "query_contract_version": query_payload.get("contract_version"),
        "workspace": query_payload.get("workspace"),
        "workspace_summary": query_payload.get("workspace_summary"),
        "query": query_payload.get("query"),
        "normalized_query": query_payload.get("normalized_query"),
        "expanded_query": query_payload.get("expanded_query"),
        "intent": query_payload.get("intent"),
        "reading_depth": query_payload.get("reading_depth"),
        "selected_result": None,
        "alternatives": [],
        "agent_brief": {
            "answer_mode": "no_match",
            "page_type_profile": "unknown",
            "recommended_read_order": [],
            "required_evidence_paths": [],
            "should_cite_sources": False,
            "should_surface_uncertainty": True,
            "fallback_action": "broaden_or_rephrase_query",
            "risk_flags": ["no_query_results"],
        },
        "answer_context": {
            "page_summary": "",
            "answer_shape": "unknown",
            "key_claims": [],
            "key_chunks": [],
            "key_sources": [],
        },
        "agent_summary": "No matched page was found. Broaden or rephrase the query before attempting an answer.",
    }

    results = query_payload.get("results", [])
    if not results:
        return base_payload

    top_result = results[0]
    reading_pack = top_result.get("reading_pack", {})
    answer_guardrails = reading_pack.get("answer_guardrails", {})
    answer_handoff = reading_pack.get("answer_handoff", {})
    evidence_context = reading_pack.get("evidence_context", {})
    retrieval_context = reading_pack.get("retrieval_context", {})
    matched_fields = retrieval_context.get("matched_fields", [])
    weak_match = (
        not matched_fields
        or (
            top_result.get("score", 0.0) < 1.0
            and not evidence_context.get("matched_claims")
            and not evidence_context.get("matched_chunks")
        )
    )
    if weak_match:
        base_payload["agent_brief"] = {
            "answer_mode": "no_match",
            "page_type_profile": "unknown",
            "recommended_read_order": [],
            "required_evidence_paths": [],
            "should_cite_sources": False,
            "should_surface_uncertainty": True,
            "fallback_action": "broaden_or_rephrase_query",
            "risk_flags": ["weak_top_match"],
        }
        base_payload["selected_result"] = {
            "rank": 1,
            "page_id": top_result.get("page_id"),
            "title": top_result.get("title", ""),
            "page_path": top_result.get("page_path", ""),
            "type": top_result.get("type", ""),
            "status": top_result.get("status", ""),
            "summary": top_result.get("summary", ""),
            "score": top_result.get("score"),
            "focus": reading_pack.get("focus"),
            "page_type_profile": "unknown",
            "ready_state": "answer_with_uncertainty",
        }
        base_payload["alternatives"] = [
            {
                "rank": index,
                "page_id": result.get("page_id"),
                "title": result.get("title", ""),
                "page_path": result.get("page_path", ""),
                "type": result.get("type", ""),
                "status": result.get("status", ""),
                "score": result.get("score"),
            }
            for index, result in enumerate(results[1:4], start=2)
        ]
        base_payload["agent_summary"] = (
            "Top query result is too weak to serve as a safe answer anchor. "
            "Broaden or rephrase the query before attempting an answer."
        )
        base_payload["answer_context"]["answer_shape"] = "unknown"
        return base_payload

    key_claims = [
        {
            "claim_id": claim.get("claim_id"),
            "text": claim.get("text", ""),
            "claim_type": claim.get("claim_type"),
            "status": claim.get("status"),
            "source_ref_count": len(claim.get("source_refs", [])),
        }
        for claim in evidence_context.get("matched_claims", [])[:3]
    ]
    key_chunks = [
        {
            "chunk_id": chunk.get("chunk_id"),
            "section_path": chunk.get("section_path"),
            "summary": chunk.get("summary") or chunk.get("text", "")[:180],
            "start_line": chunk.get("start_line"),
            "end_line": chunk.get("end_line"),
            "source_path": chunk.get("source_path"),
        }
        for chunk in evidence_context.get("matched_chunks", [])[:3]
    ]
    key_sources = (
        evidence_context.get("timeline_sources")
        or evidence_context.get("source_trail")
        or [
            {
                "source_id": source_ref.get("source_id"),
                "source_path": source_ref.get("source_path"),
                "section_path": source_ref.get("section_path"),
                "chunk_id": source_ref.get("chunk_id"),
            }
            for claim in evidence_context.get("matched_claims", [])
            for source_ref in claim.get("source_refs", [])
        ][:5]
    )
    hierarchy_hits = retrieval_context.get("hierarchy_hits", [])
    hierarchy_paths = retrieval_context.get("hierarchy_paths", [])
    hierarchy_anchor_reason = retrieval_context.get("hierarchy_anchor_reason")
    hierarchy_anchor_reason_text = retrieval_context.get("hierarchy_anchor_reason_text")
    page_type = str(top_result.get("type", "")).strip().lower()
    page_profile = page_type_profile(page_type)
    query_intent = str(query_payload.get("intent", "")).strip().lower()
    answer_shape = (
        "timeline_evidence" if query_intent == "timeline"
        else "step_by_step" if answer_handoff.get("answer_mode") == "chunks_first"
        else "worked_example" if page_profile == "example"
        else "topic_orientation" if page_profile == "topic"
        else "reference_sheet" if page_profile == "reference"
        else "timeline_evidence" if page_profile == "timeline"
        else "evidence_trace" if answer_handoff.get("answer_mode") == "sources_first"
        else "concept_summary" if page_profile == "concept"
        else "generic_summary"
    )

    if answer_handoff.get("fallback_action") == "answer_with_uncertainty":
        ready_state = "answer_with_uncertainty"
    elif answer_guardrails.get("can_answer_from_summary_only"):
        ready_state = "summary_ready"
    else:
        ready_state = "evidence_required"

    risk_flags = answer_guardrails.get("risk_flags", [])
    risk_text = ", ".join(risk_flags) if risk_flags else "none"
    selected_title = top_result.get("title", "")
    agent_summary_lines = [
        f"Use page '{selected_title}' as the answer anchor.",
        f"Answer mode: {answer_handoff.get('answer_mode', 'summary_first')}.",
        f"Read order: {' -> '.join(answer_handoff.get('recommended_read_order', [])) or 'page_context.summary'}.",
        f"Fallback action: {answer_handoff.get('fallback_action', 'read_required_evidence_before_answering')}.",
        f"Risk flags: {risk_text}.",
    ]
    if hierarchy_paths:
        agent_summary_lines.append(f"Hierarchy anchor: {' | '.join(hierarchy_paths[:3])}.")
    if hierarchy_anchor_reason_text:
        agent_summary_lines.append(f"Hierarchy reason: {hierarchy_anchor_reason_text}")
    elif hierarchy_anchor_reason:
        agent_summary_lines.append(f"Hierarchy reason: {hierarchy_anchor_reason}.")

    base_payload.update({
        "selected_result": {
            "rank": 1,
            "page_id": top_result.get("page_id"),
            "title": top_result.get("title", ""),
            "page_path": top_result.get("page_path", ""),
            "type": top_result.get("type", ""),
            "status": top_result.get("status", ""),
            "summary": top_result.get("summary", ""),
            "score": top_result.get("score"),
            "focus": reading_pack.get("focus"),
            "page_type_profile": page_profile,
            "ready_state": ready_state,
            "hierarchy_hits": hierarchy_hits,
            "hierarchy_paths": hierarchy_paths,
            "hierarchy_anchor_reason": hierarchy_anchor_reason,
            "hierarchy_anchor_reason_text": hierarchy_anchor_reason_text,
        },
        "alternatives": [
            {
                "rank": index,
                "page_id": result.get("page_id"),
                "title": result.get("title", ""),
                "page_path": result.get("page_path", ""),
                "type": result.get("type", ""),
                "status": result.get("status", ""),
                "score": result.get("score"),
            }
            for index, result in enumerate(results[1:4], start=2)
        ],
        "agent_brief": {
            "answer_mode": answer_handoff.get("answer_mode"),
            "page_type_profile": page_profile,
            "recommended_read_order": answer_handoff.get("recommended_read_order", []),
            "required_evidence_paths": answer_handoff.get("required_evidence_paths", []),
            "should_cite_sources": answer_handoff.get("should_cite_sources", False),
            "should_surface_uncertainty": answer_handoff.get("should_surface_uncertainty", False),
            "fallback_action": answer_handoff.get("fallback_action"),
            "risk_flags": risk_flags,
        },
        "answer_context": {
            "page_summary": reading_pack.get("page_summary", top_result.get("summary", "")),
            "answer_shape": answer_shape,
            "key_claims": key_claims,
            "key_chunks": key_chunks,
            "key_sources": key_sources,
            "hierarchy_hits": hierarchy_hits,
            "hierarchy_paths": hierarchy_paths,
            "hierarchy_anchor_reason": hierarchy_anchor_reason,
            "hierarchy_anchor_reason_text": hierarchy_anchor_reason_text,
        },
        "agent_summary": "\n".join(agent_summary_lines),
    })
    return base_payload


def render_answer_ready_message(answer_ready_payload: dict) -> str:
    lines = [
        f"Query: {answer_ready_payload['query']}",
        f"Intent: {answer_ready_payload['intent']}",
    ]
    selected_result = answer_ready_payload.get("selected_result")
    if selected_result is None:
        lines.append("")
        lines.append("Answer-Ready Summary:")
        lines.append("  No matched page was found.")
        lines.append("  Action: broaden or rephrase the query before answering.")
        return "\n".join(lines)

    agent_brief = answer_ready_payload.get("agent_brief", {})
    answer_context = answer_ready_payload.get("answer_context", {})
    lines.extend([
        "",
        "Answer-Ready Summary:",
        f"  anchor_page: {selected_result.get('title')} [{selected_result.get('type')}, status={selected_result.get('status')}]",
        f"  path: {selected_result.get('page_path')}",
        f"  ready_state: {selected_result.get('ready_state')}",
        f"  answer_mode: {agent_brief.get('answer_mode')}",
        f"  page_type_profile: {agent_brief.get('page_type_profile')}",
        f"  answer_shape: {answer_context.get('answer_shape')}",
        f"  fallback_action: {agent_brief.get('fallback_action')}",
        f"  read_order: {' -> '.join(agent_brief.get('recommended_read_order', []))}",
    ])
    if agent_brief.get("required_evidence_paths"):
        lines.append(f"  required_evidence: {', '.join(agent_brief['required_evidence_paths'])}")
    if agent_brief.get("risk_flags"):
        lines.append(f"  risk_flags: {', '.join(agent_brief['risk_flags'])}")
    if answer_context.get("hierarchy_paths"):
        lines.append(f"  hierarchy: {' | '.join(answer_context['hierarchy_paths'])}")
    if answer_context.get("hierarchy_anchor_reason_text"):
        lines.append(f"  hierarchy_reason: {answer_context.get('hierarchy_anchor_reason_text')}")
    elif answer_context.get("hierarchy_anchor_reason"):
        lines.append(f"  hierarchy_reason: {answer_context.get('hierarchy_anchor_reason')}")
    lines.append(f"  summary: {answer_context.get('page_summary', '')}")

    key_claims = answer_context.get("key_claims", [])
    if key_claims:
        lines.append("  key_claims:")
        for claim in key_claims:
            lines.append(f"    - {claim['claim_id']} {claim['text']}")

    key_chunks = answer_context.get("key_chunks", [])
    if key_chunks:
        lines.append("  key_chunks:")
        for chunk in key_chunks:
            lines.append(
                f"    - {chunk['chunk_id']} {chunk.get('section_path')} "
                f"(lines {chunk.get('start_line')}-{chunk.get('end_line')})"
            )

    key_sources = answer_context.get("key_sources", [])
    if key_sources:
        lines.append("  key_sources:")
        for source in key_sources[:5]:
            lines.append(
                f"    - {source.get('source_id')} {source.get('source_path')} "
                f"{source.get('section_path') or ''}".rstrip()
            )

    alternatives = answer_ready_payload.get("alternatives", [])
    if alternatives:
        lines.append("  alternatives:")
        for alternative in alternatives:
            lines.append(
                f"    - #{alternative['rank']} {alternative['title']} "
                f"[{alternative['type']}, status={alternative['status']}]"
            )
    return "\n".join(lines)


def render_answer_ready_prompt(answer_ready_payload: dict) -> str:
    selected_result = answer_ready_payload.get("selected_result")
    agent_brief = answer_ready_payload.get("agent_brief", {})
    answer_context = answer_ready_payload.get("answer_context", {})

    lines = [
        "You are the answer layer for a MyAgentWiki query handoff.",
        "Use only the provided handoff context to answer.",
        "If evidence is weak or risk flags are present, explicitly say what is uncertain.",
        "Do not invent citations or unsupported details.",
        "",
        "## Query",
        f"- user_query: {answer_ready_payload.get('query', '')}",
        f"- intent: {answer_ready_payload.get('intent', '')}",
        f"- reading_depth: {answer_ready_payload.get('reading_depth', '')}",
        "",
        "## Handoff",
        f"- answer_mode: {agent_brief.get('answer_mode', '')}",
        f"- page_type_profile: {agent_brief.get('page_type_profile', '')}",
        f"- answer_shape: {answer_context.get('answer_shape', '')}",
        f"- fallback_action: {agent_brief.get('fallback_action', '')}",
        f"- should_cite_sources: {agent_brief.get('should_cite_sources', False)}",
        f"- should_surface_uncertainty: {agent_brief.get('should_surface_uncertainty', False)}",
        f"- risk_flags: {', '.join(agent_brief.get('risk_flags', [])) or 'none'}",
        f"- recommended_read_order: {' -> '.join(agent_brief.get('recommended_read_order', [])) or 'none'}",
        f"- required_evidence_paths: {', '.join(agent_brief.get('required_evidence_paths', [])) or 'none'}",
        "",
        "## Selected Result",
    ]

    if selected_result is None:
        lines.extend([
            "- selected_result: none",
            "",
            "## Answer Instruction",
            "Explain that no reliable answer anchor was found and suggest broadening or rephrasing the query.",
        ])
        return "\n".join(lines)

    lines.extend([
        f"- title: {selected_result.get('title', '')}",
        f"- page_type: {selected_result.get('type', '')}",
        f"- page_status: {selected_result.get('status', '')}",
        f"- ready_state: {selected_result.get('ready_state', '')}",
        f"- page_path: {selected_result.get('page_path', '')}",
        f"- page_summary: {answer_context.get('page_summary', '')}",
    ])
    if answer_context.get("hierarchy_paths"):
        lines.append(f"- hierarchy_anchor: {' | '.join(answer_context.get('hierarchy_paths', [])[:3])}")
    if answer_context.get("hierarchy_hits"):
        lines.append(f"- hierarchy_hits: {'/'.join(answer_context.get('hierarchy_hits', []))}")
    if answer_context.get("hierarchy_anchor_reason_text"):
        lines.append(f"- hierarchy_reason: {answer_context.get('hierarchy_anchor_reason_text')}")
    elif answer_context.get("hierarchy_anchor_reason"):
        lines.append(f"- hierarchy_reason: {answer_context.get('hierarchy_anchor_reason')}")
    lines.extend([
        "",
        "## Key Claims",
    ])

    key_claims = answer_context.get("key_claims", [])
    if key_claims:
        for claim in key_claims:
            lines.append(
                f"- {claim.get('claim_id')}: {claim.get('text', '')} "
                f"(type={claim.get('claim_type')}, status={claim.get('status')})"
            )
    else:
        lines.append("- none")

    lines.extend([
        "",
        "## Key Chunks",
    ])
    key_chunks = answer_context.get("key_chunks", [])
    if key_chunks:
        for chunk in key_chunks:
            lines.append(
                f"- {chunk.get('chunk_id')}: {chunk.get('summary', '')} "
                f"[section={chunk.get('section_path')}, lines={chunk.get('start_line')}-{chunk.get('end_line')}, source={chunk.get('source_path')}]"
            )
    else:
        lines.append("- none")

    lines.extend([
        "",
        "## Key Sources",
    ])
    key_sources = answer_context.get("key_sources", [])
    if key_sources:
        for source in key_sources:
            lines.append(
                f"- source_id={source.get('source_id')} path={source.get('source_path')} "
                f"section={source.get('section_path') or ''} chunk_id={source.get('chunk_id') or ''}".rstrip()
            )
    else:
        lines.append("- none")

    lines.extend([
        "",
        "## Answer Instruction",
        "Write a concise answer for the user grounded only in the handoff above.",
        "If `page_type_profile` is `guide` or `answer_shape` is `step_by_step`, prefer a procedural step-by-step answer.",
        "If `page_type_profile` is `example` or `answer_shape` is `worked_example`, prefer explaining through a concrete example.",
        "If `page_type_profile` is `topic` or `answer_shape` is `topic_orientation`, first orient the user to the topic, then cite the most relevant claims.",
        "If `page_type_profile` is `reference` or `answer_shape` is `reference_sheet`, prefer a structured reference-style answer with concise keyed items.",
        "If `page_type_profile` is `timeline` or `answer_shape` is `timeline_evidence`, present events in chronological order and foreground dated evidence.",
        "If `answer_shape` is `evidence_trace`, foreground sources, chunks, and provenance instead of giving a bare summary.",
        "If `answer_shape` is `concept_summary`, prefer a concise definition-first explanation.",
        "If `should_cite_sources` is true, mention the supporting source paths or sections in the answer.",
        "If `should_surface_uncertainty` is true, include a short uncertainty note.",
        "If `fallback_action` is not `answer_from_summary_and_claims`, obey that fallback instead of overclaiming.",
    ])
    return "\n".join(lines)


def build_answer_ready_messages(answer_ready_payload: dict) -> list[dict]:
    prompt_text = render_answer_ready_prompt(answer_ready_payload)
    return [
        {
            "role": "system",
            "content": (
                "You are the answer layer for a MyAgentWiki handoff. "
                "Answer only from the provided context, surface uncertainty when required, "
                "and do not invent unsupported claims or citations."
            ),
        },
        {
            "role": "user",
            "content": prompt_text,
        },
    ]


def render_answer_ready_chatml(answer_ready_payload: dict) -> str:
    messages = build_answer_ready_messages(answer_ready_payload)
    blocks = []
    for message in messages:
        blocks.append(f"<|im_start|>{message['role']}\n{message['content']}\n<|im_end|>")
    return "\n".join(blocks)
