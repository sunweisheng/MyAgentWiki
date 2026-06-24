from __future__ import annotations

import argparse

from .cli_components.doctor_bootstrap import register_doctor_bootstrap_subparsers


def build_parser(
    *,
    command_init,
    command_ingest,
    command_lint,
    command_query,
    command_answer_query,
    command_render_page,
    command_semantic_batch,
    command_claim_set_status,
    command_review_list,
    command_review_auto,
    command_review_apply,
    query_reading_depth_limits: dict,
    query_link_expansion_choices: tuple[str, ...],
    semantic_task_names: tuple[str, ...],
    supported_page_render_targets,
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="myagentwiki",
        description="MyAgentWiki CLI scaffold.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize a new MyAgentWiki workspace.")
    init_parser.add_argument(
        "--source-dir",
        help="Optional path to the sibling raw directory. If omitted, create/use ../raw next to the workspace.",
    )
    init_parser.add_argument("--project-name", required=True, help="Name of the new wiki workspace.")
    init_parser.add_argument("--target-dir", help="Optional explicit target directory.")
    init_parser.add_argument("--json", action="store_true", help="Output JSON.")
    init_parser.set_defaults(handler=command_init)

    ingest_parser = subparsers.add_parser("ingest", help="Register raw files into workspace metadata.")
    ingest_parser.add_argument("--target-dir", help="Workspace directory. Defaults to current directory.")
    ingest_parser.add_argument(
        "--disable-insecure-download-retry",
        action="store_true",
        help="Disable the automatic one-time insecure retry for certificate verification failures when downloading remote Markdown images.",
    )
    ingest_parser.add_argument("--json", action="store_true", help="Output JSON.")
    ingest_parser.set_defaults(handler=command_ingest)

    register_doctor_bootstrap_subparsers(subparsers)

    lint_parser = subparsers.add_parser("lint")
    lint_parser.add_argument("--target-dir", help="Optional workspace directory to lint.")
    lint_parser.add_argument("--json", action="store_true", help="Output JSON.")
    lint_parser.set_defaults(handler=command_lint)

    query_parser = subparsers.add_parser("query", help="Search generated wiki pages with weighted BM25 ranking.")
    query_parser.add_argument("text", help="Search query text.")
    query_parser.add_argument("--target-dir", help="Workspace directory. Defaults to current directory.")
    query_parser.add_argument("--limit", type=int, default=5, help="Maximum number of results to return.")
    query_parser.add_argument(
        "--reading-depth",
        choices=tuple(query_reading_depth_limits.keys()),
        default="standard",
        help="Preset reading-pack thickness. `deep` returns more matched claims and chunks per page.",
    )
    query_parser.add_argument(
        "--answer-ready",
        action="store_true",
        help="Render reading_pack as an answer-ready handoff summary for an upper-layer Agent.",
    )
    query_parser.add_argument(
        "--format",
        choices=("summary", "prompt", "messages", "chatml"),
        default="summary",
        help="When used with --answer-ready, choose summary view or direct prompt view.",
    )
    query_parser.add_argument("--claim-limit", type=int, help="Maximum matched claims per page. Overrides reading-depth default.")
    query_parser.add_argument("--chunk-limit", type=int, help="Maximum matched chunks per page. Overrides reading-depth default.")
    query_parser.add_argument("--intent", choices=("lookup", "overview", "definition", "compare", "timeline", "reference", "how_to", "evidence"), help="Explicit query intent. Overrides lightweight automatic detection.")
    query_parser.add_argument(
        "--link-expansion",
        choices=query_link_expansion_choices,
        default="auto",
        help="Control whether query reading_pack expands to linked pages.",
    )
    query_parser.add_argument("--json", action="store_true", help="Output JSON.")
    query_parser.set_defaults(handler=command_query)

    answer_query_parser = subparsers.add_parser(
        "answer-query",
        help="Return an answer-ready handoff summary derived from query reading_pack.",
    )
    answer_query_parser.add_argument("text", help="Search query text.")
    answer_query_parser.add_argument("--target-dir", help="Workspace directory. Defaults to current directory.")
    answer_query_parser.add_argument("--limit", type=int, default=5, help="Maximum number of results to inspect.")
    answer_query_parser.add_argument(
        "--reading-depth",
        choices=tuple(query_reading_depth_limits.keys()),
        default="standard",
        help="Preset reading-pack thickness. `deep` returns more matched claims and chunks per page.",
    )
    answer_query_parser.add_argument(
        "--format",
        choices=("summary", "prompt", "messages", "chatml"),
        default="summary",
        help="Choose answer-ready summary view or direct prompt view.",
    )
    answer_query_parser.add_argument("--claim-limit", type=int, help="Maximum matched claims per page. Overrides reading-depth default.")
    answer_query_parser.add_argument("--chunk-limit", type=int, help="Maximum matched chunks per page. Overrides reading-depth default.")
    answer_query_parser.add_argument("--intent", choices=("lookup", "overview", "definition", "compare", "timeline", "reference", "how_to", "evidence"), help="Explicit query intent. Overrides lightweight automatic detection.")
    answer_query_parser.add_argument(
        "--link-expansion",
        choices=query_link_expansion_choices,
        default="auto",
        help="Control whether query reading_pack expands to linked pages.",
    )
    answer_query_parser.add_argument("--json", action="store_true", help="Output JSON.")
    answer_query_parser.set_defaults(handler=command_answer_query)

    render_page_parser = subparsers.add_parser(
        "render-page",
        help="Rebuild and inspect rendered wiki page(s) by render target.",
    )
    render_page_parser.add_argument("--target-dir", help="Workspace directory. Defaults to current directory.")
    render_page_parser.add_argument(
        "--render-target",
        choices=supported_page_render_targets(),
        required=True,
        help="Render target family to rebuild and inspect.",
    )
    render_page_selector_group = render_page_parser.add_mutually_exclusive_group()
    render_page_selector_group.add_argument("--page-id", help="Specific page_id to render.")
    render_page_selector_group.add_argument("--canonical-id", help="Specific canonical_id to render.")
    render_page_selector_group.add_argument("--claim-id", help="Render the page that references this claim.")
    render_page_parser.add_argument("--json", action="store_true", help="Output JSON.")
    render_page_parser.set_defaults(handler=command_render_page)

    semantic_batch_parser = subparsers.add_parser(
        "semantic-batch",
        help="Run one semantic analysis batch task and persist structured semantic decisions.",
    )
    semantic_batch_parser.add_argument("--target-dir", help="Workspace directory. Defaults to current directory.")
    semantic_batch_parser.add_argument(
        "--task",
        choices=semantic_task_names,
        required=True,
        help="Semantic task family to run.",
    )
    semantic_batch_parser.add_argument("--dry-run", action="store_true", help="Plan batches without writing semantic decisions.")
    semantic_batch_parser.add_argument("--json", action="store_true", help="Output JSON.")
    semantic_batch_parser.set_defaults(handler=command_semantic_batch)

    claim_status_parser = subparsers.add_parser("claim-set-status", help="Update one claim status and rebuild dependent pages.")
    claim_status_parser.add_argument("claim_id", help="Claim id to update.")
    claim_status_parser.add_argument("status", choices=("draft", "stable", "disputed", "needs_review"), help="New claim status.")
    claim_status_parser.add_argument("--target-dir", help="Workspace directory. Defaults to current directory.")
    claim_status_parser.add_argument("--json", action="store_true", help="Output JSON.")
    claim_status_parser.set_defaults(handler=command_claim_set_status)

    review_list_parser = subparsers.add_parser("review-list", help="List review items and candidate claims.")
    review_list_parser.add_argument("--target-dir", help="Workspace directory. Defaults to current directory.")
    review_list_parser.add_argument("--status", choices=("open", "resolved"), help="Optional review status filter.")
    review_list_parser.add_argument("--json", action="store_true", help="Output JSON.")
    review_list_parser.set_defaults(handler=command_review_list)

    review_auto_parser = subparsers.add_parser(
        "review-auto",
        help="Conservatively auto-resolve high-confidence review items and escalate the rest.",
    )
    review_auto_parser.add_argument("--target-dir", help="Workspace directory. Defaults to current directory.")
    review_auto_parser.add_argument("--dry-run", action="store_true", help="Plan auto actions without mutating workspace state.")
    review_auto_parser.add_argument(
        "--format",
        choices=("summary", "prompt", "messages", "chatml"),
        default="summary",
        help="Choose summary view or direct Agent handoff format.",
    )
    review_auto_parser.add_argument("--json", action="store_true", help="Output JSON.")
    review_auto_parser.set_defaults(handler=command_review_auto)

    review_apply_parser = subparsers.add_parser("review-apply", help="Apply an action to a review item.")
    review_apply_parser.add_argument("review_id", help="Review id to apply action to.")
    review_apply_parser.add_argument(
        "action",
        choices=("keep_both", "archive_one", "merge", "edit_then_resume", "assign_alias", "remove_alias"),
        help="Decision action to apply.",
    )
    review_apply_parser.add_argument("--primary-claim-id", help="Primary claim id for archive_one / merge.")
    review_apply_parser.add_argument("--secondary-claim-id", help="Secondary claim id for merge.")
    review_apply_parser.add_argument("--primary-page-id", help="Primary page id for alias-conflict assign_alias.")
    review_apply_parser.add_argument("--alias-value", help="Alias value to assign during alias-conflict handling.")
    review_apply_parser.add_argument("--target-dir", help="Workspace directory. Defaults to current directory.")
    review_apply_parser.add_argument("--json", action="store_true", help="Output JSON.")
    review_apply_parser.set_defaults(handler=command_review_apply)

    return parser
