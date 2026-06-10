from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import importlib
from pathlib import Path
from urllib.parse import quote


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args: str, cwd: Path | None = None) -> dict:
    command = [sys.executable, "-m", "myagentwiki.cli", *args, "--json"]
    completed = subprocess.run(
        command,
        cwd=str(cwd or REPO_ROOT),
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


def run_cli_expect_exit(*args: str, expected_exit_code: int, cwd: Path | None = None) -> dict:
    command = [sys.executable, "-m", "myagentwiki.cli", *args, "--json"]
    completed = subprocess.run(
        command,
        cwd=str(cwd or REPO_ROOT),
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == expected_exit_code, completed.stdout or completed.stderr
    return json.loads(completed.stdout)


def load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_jsonl(path: Path, records: list[dict]) -> None:
    text = "\n".join(json.dumps(record, ensure_ascii=False) for record in records)
    if text:
        text += "\n"
    path.write_text(text, encoding="utf-8")


def configure_llm_assisted_readable_concept(workspace_dir: Path, script_path: Path) -> None:
    config_path = workspace_dir / "config" / "project.yml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + "\n"
        + "rendering:\n"
        + "  readable_concept:\n"
        + '    mode: "llm_assisted"\n'
        + "    command:\n"
        + '      - "python3"\n'
        + f'      - "{script_path}"\n'
        + "    timeout_seconds: 20\n",
        encoding="utf-8",
    )


def configure_llm_assisted_overview(workspace_dir: Path, script_path: Path) -> None:
    config_path = workspace_dir / "config" / "project.yml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + "\n"
        + "rendering:\n"
        + "  overview:\n"
        + '    mode: "llm_assisted"\n'
        + "    command:\n"
        + '      - "python3"\n'
        + f'      - "{script_path}"\n'
        + "    timeout_seconds: 20\n",
        encoding="utf-8",
    )


def configure_llm_assisted_concept_quality(workspace_dir: Path, script_path: Path) -> None:
    config_path = workspace_dir / "config" / "project.yml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + "\n"
        + "rendering:\n"
        + "  concept_update:\n"
        + '    mode: "llm_assisted"\n'
        + "    command:\n"
        + '      - "python3"\n'
        + f'      - "{script_path}"\n'
        + "    timeout_seconds: 20\n",
        encoding="utf-8",
    )


def create_workspace_with_two_concepts(tmp_path: Path, project_name: str) -> Path:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "claim.md").write_text(
        "# Claim\n\n"
        "Claim 是位于 chunk 与 wiki 之间的独立知识声明层。\n\n"
        "Claim 用于承载可追踪、可合并、可审计的结论。\n",
        encoding="utf-8",
    )
    (source_dir / "chunk.md").write_text(
        "# Chunk\n\n"
        "Chunk 是用于承载局部原文切片的证据单元。\n\n"
        "Chunk 用于把原始资料拆成可追踪、可回链的阅读片段。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", project_name,
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    claim_records = load_jsonl(workspace_dir / "state" / "claims.jsonl")
    definition_claim_ids = [
        record["claim_id"]
        for record in claim_records
        if record.get("claim_type") == "definition"
    ]
    assert len(definition_claim_ids) >= 2
    for claim_id in definition_claim_ids:
        run_cli(
            "claim-set-status",
            claim_id,
            "stable",
            "--target-dir", str(workspace_dir),
        )
    return workspace_dir


def inject_shared_alias_override(
    workspace_dir: Path,
    shared_alias: str,
    page_ids: list[str] | None = None,
) -> list[str]:
    live_pages = [
        record for record in load_jsonl(workspace_dir / "state" / "pages.jsonl")
        if not record.get("removed")
        and record.get("lifecycle_status", "active") == "active"
        and record.get("type") in {"concept", "topic", "guide", "example"}
    ]
    if page_ids is None:
        page_ids = [record["page_id"] for record in live_pages[:2]]
    assert len(page_ids) >= 2

    live_page_map = {record["page_id"]: record for record in live_pages}
    overrides_path = workspace_dir / "state" / "page_alias_overrides.json"
    overrides = {"page_aliases": {}}
    if overrides_path.exists():
        overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
    page_aliases = overrides.setdefault("page_aliases", {})

    for page_id in page_ids:
        page_record = live_page_map[page_id]
        page_override = page_aliases.setdefault(page_id, {})
        aliases = sorted(set(page_override.get("aliases", page_record.get("aliases", []))))
        if shared_alias not in aliases:
            aliases.append(shared_alias)
        page_override["aliases"] = sorted(set(aliases))

    overrides_path.write_text(
        json.dumps(overrides, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return page_ids


def test_query_returns_alias_hits_and_canonical_targets(tmp_path: Path) -> None:
    # 这条回归验证 query_normalizer 已经真正接入：
    # 用 alias 命中时，不只返回页面，还要回传 alias/canonical 线索。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# 知识声明层\n\n"
        "知识声明层应该支持从 Wiki 页面反查到 Claim、Chunk 和 Source。\n\n"
        "知识声明层还应该记录自己被多少个页面引用。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "AliasQueryRegression",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    result = run_cli("query", "知识声明层", "--target-dir", str(workspace_dir))

    assert result["summary"]["returned_page_count"] >= 1
    assert result["alias_hits"]
    assert result["canonical_targets"]
    assert result["intent"] == "lookup"
    assert any(target["canonical_id"].startswith("concept:") for target in result["canonical_targets"])
    assert result["results"][0]["exact_match_boost"] >= 1.2


def test_workspace_schema_guard_blocks_unsupported_workspace_commands(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# Topic\n\n"
        "知识声明层用于承载可追踪、可合并、可审计的结论。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "SchemaGuardUnsupported",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    config_path = workspace_dir / "config" / "project.yml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace('schema_version: "v1"', 'schema_version: "v999"'),
        encoding="utf-8",
    )

    command = [sys.executable, "-m", "myagentwiki.cli", "query", "知识声明层", "--target-dir", str(workspace_dir), "--json"]
    completed = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "Workspace schema guard failed" in completed.stderr
    assert "workspace.schema_version=v999" in completed.stderr


def test_compat_report_can_plan_workspace_schema_migration(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "SchemaMigrationCompat")
    config_path = workspace_dir / "config" / "project.yml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace('schema_version: "v1"', 'schema_version: "unversioned"'),
        encoding="utf-8",
    )

    result = run_cli("compat-report", "--target-dir", str(workspace_dir))

    assert result["schema_guard"]["status"] == "needs_migration"
    assert result["summary"]["schema_migration_candidate_count"] == 1
    schema_candidates = [
        item for item in result["migration_candidates"]
        if item.get("migration_scope") == "workspace_schema"
    ]
    assert len(schema_candidates) == 1
    assert schema_candidates[0]["suggested_action"] == "upgrade_workspace_schema_to_v1"
    assert schema_candidates[0]["path_length"] == 1
    assert schema_candidates[0]["transition_path"][0]["action"] == "upgrade_workspace_schema_to_v1"
    assert schema_candidates[0]["transition_path"][0]["prerequisites"] == ["config/project.yml exists"]
    assert schema_candidates[0]["transition_path"][0]["rollback_strategy"] == "restore_config_snapshot"
    assert schema_candidates[0]["requires_confirmation"] is False
    assert schema_candidates[0]["action_contract"]["risk_level"] == "medium"


def test_compat_report_marks_missing_schema_version_as_report_only_followup(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "SchemaMigrationMissingVersion")
    config_path = workspace_dir / "config" / "project.yml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace('  schema_version: "v1"\n', ""),
        encoding="utf-8",
    )

    result = run_cli("compat-report", "--target-dir", str(workspace_dir))

    assert result["schema_guard"]["status"] == "missing_schema_version"
    assert result["summary"]["schema_migration_candidate_count"] == 1
    assert result["summary"]["schema_report_only_candidate_count"] == 1
    schema_candidates = [
        item for item in result["migration_candidates"]
        if item.get("migration_scope") == "workspace_schema"
    ]
    assert len(schema_candidates) == 1
    assert schema_candidates[0]["planning_decision"] == "report_only"
    assert schema_candidates[0]["suggested_action"] == "inspect_missing_workspace_schema_version"
    assert schema_candidates[0]["action_contract"]["risk_level"] == "high"


def test_compat_report_marks_confirmation_required_schema_path_as_report_only(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "SchemaMigrationNeedsConfirm")
    config_path = workspace_dir / "config" / "project.yml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace('schema_version: "v1"', 'schema_version: "unversioned"'),
        encoding="utf-8",
    )

    sys.path.insert(0, str(REPO_ROOT / "src"))
    try:
        cli_module = importlib.import_module("myagentwiki.cli")
    finally:
        sys.path.pop(0)

    original_transitions = cli_module.WORKSPACE_SCHEMA_TRANSITIONS
    cli_module.WORKSPACE_SCHEMA_TRANSITIONS = (
        {
            "from_version": "unversioned",
            "to_version": "v1",
            "action": "upgrade_workspace_schema_to_v1",
            "prerequisites": ["config/project.yml exists"],
            "rollback_strategy": "restore_config_snapshot",
            "requires_confirmation": True,
            "notes": "Confirmation required for test.",
        },
    )
    try:
        result = cli_module.build_compat_report_payload(workspace_dir)
    finally:
        cli_module.WORKSPACE_SCHEMA_TRANSITIONS = original_transitions

    assert result["summary"]["schema_migration_candidate_count"] == 1
    assert result["summary"]["schema_report_only_candidate_count"] == 1
    schema_candidates = [
        item for item in result["migration_candidates"]
        if item.get("migration_scope") == "workspace_schema"
    ]
    assert len(schema_candidates) == 1
    assert schema_candidates[0]["planning_decision"] == "report_only"
    assert schema_candidates[0]["suggested_action"] == "confirm_workspace_schema_transition_path"
    assert schema_candidates[0]["requires_confirmation"] is True
    assert schema_candidates[0]["action_contract"]["risk_level"] == "high"


def test_compat_report_can_plan_supported_workspace_toward_explicit_future_schema_version(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "SchemaMigrationFutureTarget")

    sys.path.insert(0, str(REPO_ROOT / "src"))
    try:
        cli_module = importlib.import_module("myagentwiki.cli")
    finally:
        sys.path.pop(0)

    original_transitions = cli_module.WORKSPACE_SCHEMA_TRANSITIONS
    original_order = cli_module.WORKSPACE_SCHEMA_VERSION_ORDER
    cli_module.WORKSPACE_SCHEMA_TRANSITIONS = (
        *original_transitions,
        {
            "from_version": "v1",
            "to_version": "v2",
            "action": "future_schema_upgrade_placeholder",
            "prerequisites": ["state/schema_confirmations.jsonl exists"],
            "rollback_strategy": "restore_config_snapshot",
            "requires_confirmation": False,
            "notes": "Future schema target test.",
        },
    )
    cli_module.WORKSPACE_SCHEMA_VERSION_ORDER = ("v1", "v2")
    try:
        result = cli_module.build_compat_report_payload(workspace_dir, target_schema_version="v2")
    finally:
        cli_module.WORKSPACE_SCHEMA_TRANSITIONS = original_transitions
        cli_module.WORKSPACE_SCHEMA_VERSION_ORDER = original_order

    assert result["target_schema_version"] == "v2"
    assert result["summary"]["schema_migration_candidate_count"] == 1
    schema_candidates = [
        item for item in result["migration_candidates"]
        if item.get("migration_scope") == "workspace_schema"
    ]
    assert len(schema_candidates) == 1
    assert schema_candidates[0]["from_schema_version"] == "v1"
    assert schema_candidates[0]["to_schema_version"] == "v2"
    assert schema_candidates[0]["suggested_action"] == "future_schema_upgrade_placeholder"
    assert schema_candidates[0]["planning_decision"] == "auto_plan"
    assert schema_candidates[0]["path_length"] == 1
    assert schema_candidates[0]["transition_path"][0]["action"] == "future_schema_upgrade_placeholder"


def test_compat_report_marks_unregistered_explicit_future_schema_target_as_report_only(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "SchemaMigrationUnknownTarget")
    sys.path.insert(0, str(REPO_ROOT / "src"))
    try:
        cli_module = importlib.import_module("myagentwiki.cli")
    finally:
        sys.path.pop(0)

    original_order = cli_module.WORKSPACE_SCHEMA_VERSION_ORDER
    try:
        cli_module.WORKSPACE_SCHEMA_VERSION_ORDER = ("v1", "v2")
        result = cli_module.build_compat_report_payload(workspace_dir, target_schema_version="v2")
    finally:
        cli_module.WORKSPACE_SCHEMA_VERSION_ORDER = original_order

    assert result["target_schema_version"] == "v2"
    assert result["summary"]["schema_migration_candidate_count"] == 1
    assert result["summary"]["schema_report_only_candidate_count"] == 1
    schema_candidates = [
        item for item in result["migration_candidates"]
        if item.get("migration_scope") == "workspace_schema"
    ]
    assert len(schema_candidates) == 1
    assert schema_candidates[0]["from_schema_version"] == "v1"
    assert schema_candidates[0]["to_schema_version"] == "v2"
    assert schema_candidates[0]["planning_decision"] == "report_only"
    assert schema_candidates[0]["suggested_action"] == "schema_transition_not_registered"


def test_compat_report_marks_unknown_explicit_future_schema_target_as_report_only(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "SchemaMigrationUnknownRegistryTarget")

    result = run_cli(
        "compat-report",
        "--target-dir", str(workspace_dir),
        "--to-schema-version", "v9",
    )

    assert result["target_schema_version"] == "v9"
    assert result["summary"]["schema_migration_candidate_count"] == 1
    schema_candidates = [
        item for item in result["migration_candidates"]
        if item.get("migration_scope") == "workspace_schema"
    ]
    assert len(schema_candidates) == 1
    assert schema_candidates[0]["from_schema_version"] == "v1"
    assert schema_candidates[0]["to_schema_version"] == "v9"
    assert schema_candidates[0]["planning_decision"] == "report_only"
    assert schema_candidates[0]["suggested_action"] == "inspect_target_workspace_schema_version"


def test_workspace_schema_registry_validation_passes_for_default_registry() -> None:
    sys.path.insert(0, str(REPO_ROOT / "src"))
    try:
        cli_module = importlib.import_module("myagentwiki.cli")
    finally:
        sys.path.pop(0)

    assert cli_module.validate_workspace_schema_registry() == []


def test_workspace_schema_registry_validation_detects_unknown_versions_and_missing_contract(tmp_path: Path) -> None:
    del tmp_path
    sys.path.insert(0, str(REPO_ROOT / "src"))
    try:
        cli_module = importlib.import_module("myagentwiki.cli")
    finally:
        sys.path.pop(0)

    original_transitions = cli_module.WORKSPACE_SCHEMA_TRANSITIONS
    original_order = cli_module.WORKSPACE_SCHEMA_VERSION_ORDER
    cli_module.WORKSPACE_SCHEMA_VERSION_ORDER = ("v1", "v2")
    cli_module.WORKSPACE_SCHEMA_TRANSITIONS = (
        {
            "from_version": "v2",
            "to_version": "v3",
            "action": "missing_contract_action",
            "prerequisites": [],
            "rollback_strategy": "restore_config_snapshot",
            "requires_confirmation": False,
            "notes": "broken registry test",
        },
    )
    try:
        issues = cli_module.validate_workspace_schema_registry()
    finally:
        cli_module.WORKSPACE_SCHEMA_TRANSITIONS = original_transitions
        cli_module.WORKSPACE_SCHEMA_VERSION_ORDER = original_order

    assert any("Unknown transition to_version: v3" in issue for issue in issues)
    assert any("Missing migration action contract for workspace schema transition: missing_contract_action" in issue for issue in issues)


def test_schema_migration_confirmation_reenables_auto_plan(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "SchemaMigrationConfirmResume")
    config_path = workspace_dir / "config" / "project.yml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace('schema_version: "v1"', 'schema_version: "unversioned"'),
        encoding="utf-8",
    )

    sys.path.insert(0, str(REPO_ROOT / "src"))
    try:
        cli_module = importlib.import_module("myagentwiki.cli")
    finally:
        sys.path.pop(0)

    original_transitions = cli_module.WORKSPACE_SCHEMA_TRANSITIONS
    cli_module.WORKSPACE_SCHEMA_TRANSITIONS = (
        {
            "from_version": "unversioned",
            "to_version": "v1",
            "action": "upgrade_workspace_schema_to_v1",
            "prerequisites": ["config/project.yml exists"],
            "rollback_strategy": "restore_config_snapshot",
            "requires_confirmation": True,
            "notes": "Confirmation required for resume test.",
        },
    )
    try:
        before = cli_module.build_migrate_plan_payload(workspace_dir)
        assert before["summary"]["schema_manual_followup_count"] == 1
        assert before["summary"]["schema_planned_action_count"] == 0
        followup = before["schema_migration"]["manual_followups"][0]

        confirm_result = cli_module.command_migrate_schema_confirm(
            argparse.Namespace(
                target_dir=str(workspace_dir),
                confirm=True,
                from_version="unversioned",
                to_version="v1",
                path_signature=followup["path_signature"],
                notes="approved",
                json=True,
            )
        )
        refreshed = confirm_result.payload["refreshed_plan"]
    finally:
        cli_module.WORKSPACE_SCHEMA_TRANSITIONS = original_transitions

    assert refreshed["summary"]["schema_manual_followup_count"] == 0
    assert refreshed["summary"]["schema_planned_action_count"] == 1
    assert refreshed["schema_migration"]["planned_actions"][0]["action"] == "upgrade_workspace_schema_to_v1"


def test_migrate_apply_can_upgrade_workspace_schema_and_rollback(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "SchemaMigrationApply")
    config_path = workspace_dir / "config" / "project.yml"
    original_config_text = config_path.read_text(encoding="utf-8")
    config_path.write_text(
        original_config_text.replace('schema_version: "v1"', 'schema_version: "unversioned"'),
        encoding="utf-8",
    )

    plan_result = run_cli("migrate", "--target-dir", str(workspace_dir))
    assert plan_result["summary"]["schema_planned_action_count"] == 1
    assert plan_result["summary"]["compatibility_planned_action_count"] == 0
    schema_actions = [
        item for item in plan_result["planned_actions"]
        if item["action"] == "upgrade_workspace_schema_to_v1"
    ]
    assert len(schema_actions) == 1
    assert len(plan_result["schema_migration"]["planned_actions"]) == 1
    assert plan_result["schema_migration"]["planned_actions"][0]["action"] == "upgrade_workspace_schema_to_v1"
    assert plan_result["schema_migration"]["planned_actions"][0]["path_length"] == 1

    apply_result = run_cli("migrate", "--apply", "--target-dir", str(workspace_dir))
    assert apply_result["summary"]["applied_action_count"] >= 1
    applied_schema_actions = [
        item for item in apply_result["applied_actions"]
        if item["action"] == "upgrade_workspace_schema_to_v1"
    ]
    assert len(applied_schema_actions) == 1
    assert 'schema_version: "v1"' in config_path.read_text(encoding="utf-8")
    latest_backup_path = workspace_dir / "state" / "backups" / "migrate_latest.json"
    assert latest_backup_path.exists()

    rollback_result = run_cli("migrate", "--rollback", "--target-dir", str(workspace_dir))
    assert rollback_result["summary"]["restored_entry_count"] >= 1
    assert 'schema_version: "unversioned"' in config_path.read_text(encoding="utf-8")
    migration_runs = load_jsonl(workspace_dir / "state" / "migration_runs.jsonl")
    assert migration_runs
    assert any(record["mode"] == "plan" for record in migration_runs)
    assert any(record["mode"] == "apply" for record in migration_runs)
    assert any(record["mode"] == "rollback" for record in migration_runs)


def test_query_detects_definition_intent_and_prefers_concept_pages(tmp_path: Path) -> None:
    # “什么是...” 这类问法应该识别为 definition，并把概念页轻微前推。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# 知识声明层\n\n"
        "知识声明层是位于 chunk 与 wiki 之间的独立知识声明层。\n\n"
        "知识声明层用于承载可追踪、可合并、可审计的结论。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "IntentQueryRegression",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    result = run_cli("query", "什么是知识声明层", "--target-dir", str(workspace_dir))

    assert result["intent"] == "definition"
    assert result["results"]
    assert result["results"][0]["type"] == "concept"
    assert result["results"][0]["intent_boost"] >= 1.0


def test_query_answer_ready_returns_agent_consumable_summary(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "AnswerReadyQueryRegression")

    result = run_cli(
        "query",
        "什么是 Claim",
        "--target-dir", str(workspace_dir),
        "--answer-ready",
    )

    assert result["contract_version"] == "answer_ready_query/v1"
    assert result["query_contract_version"] == "query_answer_handoff/v1"
    assert result["selected_result"]["title"]
    assert result["selected_result"]["ready_state"] == "summary_ready"
    assert result["selected_result"]["page_type_profile"] == "concept"
    assert result["agent_brief"]["answer_mode"] == "summary_first"
    assert result["agent_brief"]["page_type_profile"] == "concept"
    assert result["agent_brief"]["fallback_action"] == "answer_from_summary_and_claims"
    assert result["answer_context"]["page_summary"]
    assert result["answer_context"]["answer_shape"] == "concept_summary"
    assert result["answer_context"]["key_claims"]


def test_query_answer_ready_exposes_page_type_driven_answer_shape(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "guide.md").write_text(
        "# 导入流程\n\n"
        "首先扫描 raw 目录。\n\n"
        "然后生成 normalized 文档。\n\n"
        "最后写入 chunk 与 claim。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "AnswerReadyGuideShape",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    result = run_cli(
        "query",
        "如何生成 normalized 文档",
        "--target-dir", str(workspace_dir),
        "--answer-ready",
    )

    assert result["contract_version"] == "answer_ready_query/v1"
    assert result["selected_result"]["page_type_profile"] in {"guide", "source"}
    if result["selected_result"]["page_type_profile"] == "guide":
        assert result["agent_brief"]["answer_mode"] == "chunks_first"
        assert result["answer_context"]["answer_shape"] == "step_by_step"


def test_query_answer_ready_exposes_reference_page_shape(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "reference.md").write_text(
        "# FAQ Reference\n\n"
        "参数列表用于说明系统的关键配置项。\n\n"
        "规则清单用于列出处理约束。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "AnswerReadyReferenceShape",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    result = run_cli(
        "query",
        "参数列表是什么",
        "--target-dir", str(workspace_dir),
        "--answer-ready",
    )

    assert result["selected_result"]["page_type_profile"] in {"reference", "source"}
    if result["selected_result"]["page_type_profile"] == "reference":
        assert result["answer_context"]["answer_shape"] == "reference_sheet"


def test_query_answer_ready_exposes_timeline_page_shape(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "timeline.md").write_text(
        "# Timeline\n\n"
        "起初系统只支持 source-summary。\n\n"
        "随后加入 claim 层。\n\n"
        "后来引入 semantic batch。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "AnswerReadyTimelineShape",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    result = run_cli(
        "query",
        "系统的时间线",
        "--target-dir", str(workspace_dir),
        "--answer-ready",
    )

    assert result["answer_context"]["answer_shape"] == "timeline_evidence"


def test_answer_query_matches_query_answer_ready_view(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "AnswerQueryAliasRegression")

    answer_ready_from_query = run_cli(
        "query",
        "Claim 和 Chunk 的区别",
        "--target-dir", str(workspace_dir),
        "--answer-ready",
        "--reading-depth", "deep",
    )
    answer_ready_from_alias = run_cli(
        "answer-query",
        "Claim 和 Chunk 的区别",
        "--target-dir", str(workspace_dir),
        "--reading-depth", "deep",
    )

    assert answer_ready_from_alias == answer_ready_from_query


def test_answer_query_prompt_format_returns_prompt_text(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "AnswerQueryPromptRegression")

    result = run_cli(
        "answer-query",
        "什么是 Claim",
        "--target-dir", str(workspace_dir),
        "--format", "prompt",
    )

    assert result["contract_version"] == "answer_ready_query/v1"
    assert "prompt_text" in result
    assert "## Query" in result["prompt_text"]
    assert "## Answer Instruction" in result["prompt_text"]
    assert "user_query: 什么是 Claim" in result["prompt_text"]
    assert "page_type_profile:" in result["prompt_text"]
    assert "answer_shape:" in result["prompt_text"]


def test_query_answer_ready_prompt_matches_answer_query_prompt(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "QueryAnswerReadyPromptParity")

    from_query = run_cli(
        "query",
        "这个结论的来源证据是什么",
        "--target-dir", str(workspace_dir),
        "--answer-ready",
        "--format", "prompt",
        "--reading-depth", "deep",
    )
    from_alias = run_cli(
        "answer-query",
        "这个结论的来源证据是什么",
        "--target-dir", str(workspace_dir),
        "--format", "prompt",
        "--reading-depth", "deep",
    )

    assert from_query == from_alias


def test_answer_query_messages_format_returns_api_ready_messages(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "AnswerQueryMessagesRegression")

    result = run_cli(
        "answer-query",
        "什么是 Claim",
        "--target-dir", str(workspace_dir),
        "--format", "messages",
    )

    assert result["contract_version"] == "answer_ready_query/v1"
    assert "messages" in result
    assert len(result["messages"]) == 2
    assert result["messages"][0]["role"] == "system"
    assert result["messages"][1]["role"] == "user"
    assert "## Query" in result["messages"][1]["content"]
    assert "page_type_profile:" in result["messages"][1]["content"]
    assert "answer_shape:" in result["messages"][1]["content"]


def test_answer_query_chatml_format_returns_chatml_and_messages(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "AnswerQueryChatMLRegression")

    result = run_cli(
        "answer-query",
        "什么是 Claim",
        "--target-dir", str(workspace_dir),
        "--format", "chatml",
    )

    assert result["contract_version"] == "answer_ready_query/v1"
    assert "messages" in result
    assert "chatml_text" in result
    assert "<|im_start|>system" in result["chatml_text"]
    assert "<|im_start|>user" in result["chatml_text"]
    assert "page_type_profile:" in result["chatml_text"]
    assert "answer_shape:" in result["chatml_text"]


def test_query_no_longer_exposes_legacy_concept_summary_view(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "LegacyConceptSummaryCompatibility")

    result = run_cli(
        "query",
        "Claim",
        "--target-dir", str(workspace_dir),
        "--reading-depth", "deep",
    )
    assert all(item["type"] != "concept-summary" for item in result["results"])
    assert any(item["type"] == "concept" for item in result["results"])

    answer_ready = run_cli(
        "query",
        "Claim",
        "--target-dir", str(workspace_dir),
        "--answer-ready",
    )
    assert answer_ready["selected_result"]["type"] == "concept"
    assert answer_ready["selected_result"]["page_type_profile"] == "concept"
    assert answer_ready["selected_result"]["compat_mode"] == "current"


def test_wiki_index_no_longer_lists_legacy_evidence_view_section(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "LegacyWikiIndex")

    wiki_index = (workspace_dir / "wiki" / "index.md").read_text(encoding="utf-8")
    assert "## 兼容证据页 / Legacy Evidence Views" not in wiki_index
    assert "compat=legacy" not in wiki_index


def test_workspace_summary_exposes_compatibility_report(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "CompatibilityReportSummary")

    result = run_cli("query", "Claim", "--target-dir", str(workspace_dir))
    compatibility_report = result["workspace_summary"]["compatibility_report"]
    assert compatibility_report["legacy_page_count"] == 0
    assert compatibility_report["legacy_page_types"] == {}
    assert compatibility_report["canonical_families_with_legacy"] == 0
    assert compatibility_report["legacy_pages"] == []


def test_compat_report_lists_migration_candidates(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "CompatReportCandidates")

    result = run_cli("compat-report", "--target-dir", str(workspace_dir))
    assert result["action_catalog"]
    catalog_actions = {item["action"] for item in result["action_catalog"]}
    assert "archive_legacy_concept_summary" not in catalog_actions
    assert "needs_current_successor_before_migration" not in catalog_actions
    assert result["compatibility_report"]["legacy_page_count"] == 0
    assert result["summary"]["migration_candidate_count"] == 0
    assert result["summary"]["auto_applicable_candidate_count"] == 0
    assert result["migration_candidates"] == []


def test_migrate_returns_planned_actions_for_legacy_families(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "MigratePlanCandidates")

    result = run_cli("migrate", "--target-dir", str(workspace_dir))
    assert result["action_catalog"]
    assert result["summary"]["schema_planned_action_count"] == 0
    assert result["summary"]["planned_action_count"] == 0
    assert result["summary"]["manual_followup_count"] == 0
    assert result["planned_actions"] == []
    assert result["compatibility_cleanup"]["planned_actions"] == []
    report = result["migration_report"]
    assert Path(report["report_dir"]).exists()
    assert Path(report["report_json_path"]).exists()
    assert Path(report["report_md_path"]).exists()
    latest_json = json.loads(Path(report["latest_json_path"]).read_text(encoding="utf-8"))
    assert latest_json["mode"] == "plan"


def test_migrate_plan_flag_matches_default_plan_output(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "MigrateExplicitPlan")

    default_result = run_cli("migrate", "--target-dir", str(workspace_dir))
    explicit_plan_result = run_cli("migrate", "--plan", "--target-dir", str(workspace_dir))

    assert explicit_plan_result["summary"] == default_result["summary"]
    assert explicit_plan_result["action_catalog"] == default_result["action_catalog"]
    assert explicit_plan_result["planned_actions"] == default_result["planned_actions"]
    assert explicit_plan_result["migration_candidates"] == default_result["migration_candidates"]
    assert explicit_plan_result["manual_followups"] == default_result["manual_followups"]
    assert explicit_plan_result["migration_report"]["mode"] == "plan"
    assert default_result["migration_report"]["mode"] == "plan"


def test_migrate_reports_manual_followup_when_legacy_has_no_current_successor(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "MigrateManualFollowup")

    page_records = load_jsonl(workspace_dir / "state" / "pages.jsonl")
    kept_records = []
    for record in page_records:
        if record.get("type") == "concept" and not record.get("removed"):
            page_path = workspace_dir / record["page_path"]
            if page_path.exists():
                page_path.unlink()
            continue
        kept_records.append(record)
    write_jsonl(workspace_dir / "state" / "pages.jsonl", kept_records)

    compat_result = run_cli("compat-report", "--target-dir", str(workspace_dir))
    assert compat_result["summary"]["migration_candidate_count"] == 0
    assert compat_result["summary"]["auto_applicable_candidate_count"] == 0
    assert compat_result["summary"]["report_only_candidate_count"] == 0
    assert compat_result["migration_candidates"] == []

    migrate_result = run_cli("migrate", "--target-dir", str(workspace_dir))
    assert migrate_result["summary"]["schema_manual_followup_count"] == 0
    assert migrate_result["summary"]["compatibility_manual_followup_count"] == 0
    assert migrate_result["summary"]["planned_action_count"] == 0
    assert migrate_result["summary"]["manual_followup_count"] == 0
    assert migrate_result["planned_actions"] == []
    assert migrate_result["manual_followups"] == []
    assert migrate_result["compatibility_cleanup"]["manual_followups"] == []


def test_migrate_prompt_handoff_focuses_on_report_only_candidates(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "MigratePromptHandoff")

    page_records = load_jsonl(workspace_dir / "state" / "pages.jsonl")
    kept_records = []
    for record in page_records:
        if record.get("type") == "concept" and not record.get("removed"):
            page_path = workspace_dir / record["page_path"]
            if page_path.exists():
                page_path.unlink()
            continue
        kept_records.append(record)
    write_jsonl(workspace_dir / "state" / "pages.jsonl", kept_records)

    result = run_cli("migrate", "--format", "prompt", "--target-dir", str(workspace_dir))
    assert result["contract_version"] == "migrate_handoff/v1"
    assert result["agent_brief"]["should_invoke_llm"] is False
    assert result["agent_brief"]["next_action"] == "apply_supported_actions_or_continue"
    assert result["manual_followups"] == []
    assert result["batching"]["batch_count"] == 0
    assert "Do not reinterpret or override apply_supported actions" in result["prompt_text"]
    assert "## Batches" in result["prompt_text"]
    assert "## Report-only Candidates" in result["prompt_text"]


def test_migrate_messages_handoff_exposes_action_catalog(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "MigrateMessagesHandoff")

    result = run_cli("migrate", "--format", "messages", "--target-dir", str(workspace_dir))
    assert result["contract_version"] == "migrate_handoff/v1"
    assert result["messages"]
    assert result["action_catalog"]
    assert all("risk_level" in item for item in result["action_catalog"])
    assert result["agent_brief"]["next_action"] == "apply_supported_actions_or_continue"


def test_migrate_handoff_batches_report_only_candidates(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "MigrateBatching")

    page_records = load_jsonl(workspace_dir / "state" / "pages.jsonl")
    kept_records = []
    for record in page_records:
        if record.get("type") == "concept" and not record.get("removed"):
            page_path = workspace_dir / record["page_path"]
            if page_path.exists():
                page_path.unlink()
            continue
        kept_records.append(record)
    write_jsonl(workspace_dir / "state" / "pages.jsonl", kept_records)

    source_dir = workspace_dir.parent / "raw"
    (source_dir / "new_topic.md").write_text(
        "# New Topic\n\n"
        "新的主题仍然只生成 legacy 概念页，用于制造更多 report_only 候选。\n",
        encoding="utf-8",
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    page_records = load_jsonl(workspace_dir / "state" / "pages.jsonl")
    kept_records = []
    for record in page_records:
        if record.get("type") == "concept" and not record.get("removed"):
            page_path = workspace_dir / record["page_path"]
            if page_path.exists():
                page_path.unlink()
            continue
        kept_records.append(record)
    write_jsonl(workspace_dir / "state" / "pages.jsonl", kept_records)

    result = run_cli("migrate", "--format", "prompt", "--batch-size", "1", "--target-dir", str(workspace_dir))
    assert result["batching"]["batch_size"] == 1
    assert result["batching"]["batch_count"] == 0
    assert len(result["batch_reports"]) == 0


def test_migrate_decisions_ingest_and_apply_roundtrip(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "MigrateDecisionRoundtrip")

    page_records = load_jsonl(workspace_dir / "state" / "pages.jsonl")
    kept_records = []
    for record in page_records:
        if record.get("type") == "concept" and not record.get("removed"):
            page_path = workspace_dir / record["page_path"]
            if page_path.exists():
                page_path.unlink()
            continue
        kept_records.append(record)
    write_jsonl(workspace_dir / "state" / "pages.jsonl", kept_records)

    canonical_id = "concept:claim"

    decision_record = {
        "ledger_version": "migration_decision/v1",
        "canonical_id": canonical_id,
        "decision_action": "promote_to_current_successor_needed",
        "rationale": "This family still needs a current successor page before migration can continue.",
        "confidence": 0.91,
        "source_suggested_action": None,
        "followup_action": None,
        "migration_class": "manual_test_followup",
        "created_at": "2026-06-10T00:00:00Z",
    }
    write_jsonl(workspace_dir / "state" / "migration_decisions.jsonl", [decision_record])

    ledger_records = load_jsonl(workspace_dir / "state" / "migration_decisions.jsonl")
    assert ledger_records
    assert ledger_records[0]["canonical_id"] == canonical_id
    assert ledger_records[0]["decision_action"] == "promote_to_current_successor_needed"

    sys.path.insert(0, str(REPO_ROOT / "src"))
    try:
        cli_module = importlib.import_module("myagentwiki.cli")
    finally:
        sys.path.pop(0)

    original_builder = cli_module.build_migrate_plan_payload

    def fake_builder(target: Path, target_schema_version: str | None = None) -> dict:
        payload = original_builder(target, target_schema_version=target_schema_version)
        followup = {
            "canonical_id": canonical_id,
            "action": "wait_for_current_successor",
            "suggested_action": "inspect_workspace_schema_transition",
            "migration_class": "manual_test_followup",
        }
        payload["manual_followups"] = [followup]
        payload["migration_candidates"] = [followup]
        payload["summary"] = {
            **payload["summary"],
            "manual_followup_count": 1,
            "migration_candidate_count": 1,
            "compatibility_manual_followup_count": 1,
        }
        return payload

    cli_module.build_migrate_plan_payload = fake_builder
    try:
        apply_result = cli_module.apply_migration_decision_records(workspace_dir, ledger_records)
    finally:
        cli_module.build_migrate_plan_payload = original_builder

    assert apply_result["summary"]["applied_decision_count"] == 1
    assert apply_result["summary"]["promoted_action_count"] == 1
    assert apply_result["summary"]["followup_queue_count"] == 1
    assert apply_result["promoted_actions"][0]["canonical_id"] == canonical_id
    followup_queue = load_jsonl(workspace_dir / "state" / "migration_followups.jsonl")
    assert followup_queue
    assert followup_queue[0]["canonical_id"] == canonical_id
    assert followup_queue[0]["queue_action"] == "create_current_successor_required"
    assert followup_queue[0]["status"] == "pending"

    followups_result = run_cli("migrate-followups", "--target-dir", str(workspace_dir))
    assert followups_result["summary"]["followup_count"] == 1
    assert followups_result["summary"]["pending_count"] == 1
    assert followups_result["items"][0]["canonical_id"] == canonical_id

    complete_result = run_cli("migrate-followups", "--complete", canonical_id, "--target-dir", str(workspace_dir))
    assert complete_result["completed_followup"]["canonical_id"] == canonical_id
    assert complete_result["completed_followup"]["status"] == "completed"

    completed_list = run_cli("migrate-followups", "--status", "completed", "--target-dir", str(workspace_dir))
    assert completed_list["summary"]["completed_count"] == 1
    assert completed_list["items"][0]["canonical_id"] == canonical_id


def test_migrate_followup_can_be_promoted_to_review(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "MigrateFollowupReview")

    page_records = load_jsonl(workspace_dir / "state" / "pages.jsonl")
    kept_records = []
    for record in page_records:
        if record.get("type") == "concept" and not record.get("removed"):
            page_path = workspace_dir / record["page_path"]
            if page_path.exists():
                page_path.unlink()
            continue
        kept_records.append(record)
    write_jsonl(workspace_dir / "state" / "pages.jsonl", kept_records)

    canonical_id = "concept:claim"
    write_jsonl(
        workspace_dir / "state" / "migration_followups.jsonl",
        [
            {
                "canonical_id": canonical_id,
                "queue_action": "create_current_successor_required",
                "source_decision_action": "promote_to_current_successor_needed",
                "status": "pending",
                "reason": "Need a tracked review item for current successor creation.",
                "confidence": 0.95,
                "migration_class": "manual_test_followup",
                "created_at": "2026-06-10T00:00:00Z",
                "updated_at": "2026-06-10T00:00:00Z",
            }
        ],
    )

    promote_result = run_cli("migrate-followups", "--promote-to-review", canonical_id, "--target-dir", str(workspace_dir))
    assert promote_result["canonical_id"] == canonical_id
    assert promote_result["review_record"]["kind"] == "migration_followup"
    assert promote_result["review_record"]["migration_followup"]["canonical_id"] == canonical_id

    review_list = run_cli("review-list", "--target-dir", str(workspace_dir))
    assert any(item["kind"] == "migration_followup" for item in review_list["items"])


def test_migrate_apply_removes_legacy_pages_when_current_family_exists(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "MigrateApplyRejected")

    before_pages = load_jsonl(workspace_dir / "state" / "pages.jsonl")
    result = run_cli("migrate", "--apply", "--target-dir", str(workspace_dir))

    assert result["summary"]["applied_action_count"] == 0
    assert result["summary"]["removed_legacy_page_count"] == 0
    assert result["summary"]["migration_candidate_count"] == 0
    assert result["summary"]["legacy_page_count"] == 0
    assert result["applied_actions"] == []
    assert "unsupported_actions" not in result
    assert result["migration_report"]["mode"] == "apply-plan"
    assert "backup" not in result

    compat_result = run_cli("compat-report", "--target-dir", str(workspace_dir))
    assert compat_result["summary"]["migration_candidate_count"] == 0
    assert compat_result["compatibility_report"]["legacy_page_count"] == 0

    lint_result = run_cli("lint", "--target-dir", str(workspace_dir))
    assert lint_result["summary"]["ok"] is True


def test_migrate_apply_marks_unsupported_planned_action_without_crashing(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "MigrateUnsupportedAction")

    sys.path.insert(0, str(REPO_ROOT / "src"))
    try:
        cli_module = importlib.import_module("myagentwiki.cli")
    finally:
        sys.path.pop(0)

    original_builder = cli_module.build_migrate_plan_payload

    def fake_builder(target: Path) -> dict:
        payload = original_builder(target)
        payload["planned_actions"] = payload["planned_actions"] + [
            {
                "action": "future_schema_upgrade_placeholder",
                "action_class": "schema_upgrade",
                "execution_mode": "apply_supported",
                "canonical_id": "workspace:schema",
                "legacy_page_ids": [],
                "current_page_ids": [],
                "legacy_types": [],
                "current_types": [],
                "migration_class": "future_schema_upgrade_placeholder",
                "reason": "placeholder",
            }
        ]
        payload["summary"] = {
            **payload["summary"],
            "planned_action_count": len(payload["planned_actions"]),
        }
        return payload

    cli_module.build_migrate_plan_payload = fake_builder
    try:
        result = cli_module.apply_migrate_plan(workspace_dir)
    finally:
        cli_module.build_migrate_plan_payload = original_builder

    assert result["applied_actions"] == []
    assert result["unsupported_actions"]
    assert result["unsupported_actions"][0]["action"] == "future_schema_upgrade_placeholder"
    assert result["unsupported_actions"][0]["status"] == "unsupported_action"


def test_migrate_apply_expands_multi_step_schema_transition_path(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "MigrateMultiStepSchema")

    sys.path.insert(0, str(REPO_ROOT / "src"))
    try:
        cli_module = importlib.import_module("myagentwiki.cli")
    finally:
        sys.path.pop(0)

    original_builder = cli_module.build_migrate_plan_payload
    original_handlers = dict(cli_module.MIGRATION_ACTION_HANDLERS)
    call_order: list[str] = []

    def fake_builder(target: Path) -> dict:
        payload = original_builder(target)
        payload["planned_actions"] = [
            {
                "action": "upgrade_workspace_schema_to_v1",
                "action_class": "schema_upgrade",
                "execution_mode": "apply_supported",
                "canonical_id": "workspace:schema_version",
                "migration_scope": "workspace_schema",
                "from_schema_version": "v0",
                "to_schema_version": "v2",
                "transition_path": [
                    {
                        "from_version": "v0",
                        "to_version": "v1",
                        "action": "fake_schema_step_one",
                    },
                    {
                        "from_version": "v1",
                        "to_version": "v2",
                        "action": "fake_schema_step_two",
                    },
                ],
                "path_length": 2,
                "legacy_page_ids": [],
                "current_page_ids": [],
                "legacy_types": [],
                "current_types": [],
                "migration_class": "workspace_schema_upgrade_to_v2",
                "reason": "multi-step upgrade",
                "risk_level": "high",
            }
        ]
        payload["schema_migration"] = {
            "planned_actions": payload["planned_actions"],
            "manual_followups": [],
        }
        payload["compatibility_cleanup"] = {
            "planned_actions": [],
            "manual_followups": [],
        }
        payload["summary"] = {
            **payload["summary"],
            "planned_action_count": 1,
            "manual_followup_count": 0,
            "migration_candidate_count": 1,
            "schema_planned_action_count": 1,
            "schema_manual_followup_count": 0,
            "compatibility_planned_action_count": 0,
            "compatibility_manual_followup_count": 0,
        }
        return payload

    def make_handler(name: str, to_version: str):
        def apply(target: Path, action: dict, page_records_by_id: dict, live_claims_by_id: dict, live_reviews_by_id: dict) -> dict:
            del page_records_by_id, live_claims_by_id, live_reviews_by_id
            call_order.append(name)
            cli_module.update_workspace_schema_version(target, to_version)
            return {
                "status": "applied",
                "removed_legacy_page_ids": [],
                "changed_page_records": [],
            }
        return {
            "backup_entries": lambda target, action, page_records_by_id, backup_dir: [],
            "apply": apply,
        }

    cli_module.build_migrate_plan_payload = fake_builder
    cli_module.MIGRATION_ACTION_HANDLERS["fake_schema_step_one"] = make_handler("fake_schema_step_one", "v1")
    cli_module.MIGRATION_ACTION_HANDLERS["fake_schema_step_two"] = make_handler("fake_schema_step_two", "v2")
    try:
        result = cli_module.apply_migrate_plan(workspace_dir)
    finally:
        cli_module.build_migrate_plan_payload = original_builder
        cli_module.MIGRATION_ACTION_HANDLERS.clear()
        cli_module.MIGRATION_ACTION_HANDLERS.update(original_handlers)

    assert call_order == ["fake_schema_step_one", "fake_schema_step_two"]
    applied_actions = [item for item in result["applied_actions"] if item["action"].startswith("fake_schema_step_")]
    assert len(applied_actions) == 2
    assert applied_actions[0]["transition_step_index"] == 1
    assert applied_actions[1]["transition_step_index"] == 2


def test_lint_migration_warning_uses_action_contract_metadata(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "LintMigrationContract")

    result = run_cli("lint", "--target-dir", str(workspace_dir))
    checks = {check["name"]: check for check in result["checks"]}
    assert "migration_candidates_absent" in checks
    check = checks["migration_candidates_absent"]
    assert check["ok"] is True


def test_answer_query_prompt_includes_page_type_driven_instruction_for_guide(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "guide.md").write_text(
        "# 导入流程\n\n"
        "首先扫描 raw 目录。\n\n"
        "然后生成 normalized 文档。\n\n"
        "最后写入 chunk 与 claim。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "AnswerQueryGuidePrompt",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    result = run_cli(
        "answer-query",
        "如何生成 normalized 文档",
        "--target-dir", str(workspace_dir),
        "--format", "prompt",
    )

    if "page_type_profile: guide" in result["prompt_text"]:
        assert "answer_shape: step_by_step" in result["prompt_text"]
        assert "prefer a procedural step-by-step answer" in result["prompt_text"]


def test_query_answer_ready_messages_matches_answer_query_messages(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "QueryAnswerReadyMessagesParity")

    from_query = run_cli(
        "query",
        "什么是 Claim",
        "--target-dir", str(workspace_dir),
        "--answer-ready",
        "--format", "messages",
    )
    from_alias = run_cli(
        "answer-query",
        "什么是 Claim",
        "--target-dir", str(workspace_dir),
        "--format", "messages",
    )

    assert from_query == from_alias


def test_answer_query_no_match_returns_fallback_brief(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "AnswerQueryNoMatchRegression")

    result = run_cli(
        "answer-query",
        "完全不存在的主题 xyz",
        "--target-dir", str(workspace_dir),
    )

    assert result["contract_version"] == "answer_ready_query/v1"
    assert result["selected_result"]["ready_state"] == "answer_with_uncertainty"
    assert result["agent_brief"]["fallback_action"] in {"answer_with_uncertainty", "broaden_or_rephrase_query"}
    assert result["agent_brief"]["should_surface_uncertainty"] is True
    assert result["agent_brief"]["risk_flags"]


def test_claim_set_status_stable_generates_readable_concept_page(tmp_path: Path) -> None:
    # 稳定 claim 会收口到唯一的正式 concept 页，并保留可读摘要与证据入口。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# 知识声明层\n\n"
        "知识声明层是位于 chunk 与 wiki 之间的独立知识声明层。\n\n"
        "知识声明层用于承载可追踪、可合并、可审计的结论。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "ReadableConceptGeneration",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    claim_records = load_jsonl(workspace_dir / "state" / "claims.jsonl")
    definition_claim = next(record for record in claim_records if record.get("claim_type") == "definition")
    run_cli(
        "claim-set-status",
        definition_claim["claim_id"],
        "stable",
        "--target-dir", str(workspace_dir),
    )

    page_records = load_jsonl(workspace_dir / "state" / "pages.jsonl")
    readable_concept_page = next(record for record in page_records if record.get("type") == "concept")
    assert readable_concept_page["status"] == "stable"
    assert readable_concept_page["page_path"].endswith("/知识声明层.md")
    assert readable_concept_page["claim_ids"] == [definition_claim["claim_id"]]

    page_text = (workspace_dir / readable_concept_page["page_path"]).read_text(encoding="utf-8")
    assert "# 知识声明层" in page_text
    assert "## 摘要 / Summary" in page_text
    assert "## 关键要点 / Key Points" in page_text
    assert "当前版本基于 1 条稳定 Claim、1 个来源整理。" in page_text


def test_query_definition_prefers_readable_concept_once_stable_page_exists(tmp_path: Path) -> None:
    # 一旦 stable claim 产出了 concept 页，定义类问题应优先命中可读页，而不是证据摘要页。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# 知识声明层\n\n"
        "知识声明层是位于 chunk 与 wiki 之间的独立知识声明层。\n\n"
        "知识声明层用于承载可追踪、可合并、可审计的结论。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "ReadableConceptQueryPreference",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    claim_records = load_jsonl(workspace_dir / "state" / "claims.jsonl")
    definition_claim = next(record for record in claim_records if record.get("claim_type") == "definition")
    run_cli(
        "claim-set-status",
        definition_claim["claim_id"],
        "stable",
        "--target-dir", str(workspace_dir),
    )

    result = run_cli("query", "什么是知识声明层", "--target-dir", str(workspace_dir))

    assert result["intent"] == "definition"
    assert result["results"]
    assert result["results"][0]["type"] == "concept"
    assert result["results"][0]["status"] == "stable"
    assert result["results"][0]["intent_boost_reason"] == "intent_definition_prefers_concept"
    assert all(item["type"] != "concept-summary" for item in result["results"])


def test_concept_page_title_and_path_are_human_readable_for_question_headings(tmp_path: Path) -> None:
    # FAQ 风格标题不应把编号、问句尾巴和内部 page_id 暴露成最终页面主标题。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# 1. Claim 是什么\n\n"
        "Claim 是位于 chunk 与 wiki 之间的独立知识声明层。\n\n"
        "Claim 用于承载可追踪、可合并、可审计的结论。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "ConceptTitleRegression",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    pages_path = workspace_dir / "state" / "pages.jsonl"
    page_records = [
        json.loads(line)
        for line in pages_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    concept_page = next(record for record in page_records if record.get("type") == "concept")

    assert concept_page["title"] == "Claim"
    assert concept_page["canonical_id"] == "concept:claim"
    assert concept_page["page_path"].startswith(f"wiki/concepts/{concept_page['page_id']}/")
    assert concept_page["page_path"].endswith("/Claim.md")
    assert "__page_cpt_" not in concept_page["page_path"]

    page_text = (workspace_dir / concept_page["page_path"]).read_text(encoding="utf-8")
    assert "# Claim" in page_text
    assert "规范概念键: `claim`" in page_text


def test_concept_page_title_keeps_full_date_headings(tmp_path: Path) -> None:
    # 日期标题不应被当作“编号前缀”裁成 05-24 这种残缺标题。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# 2026-05-24\n\n"
        "<!-- turn_id: t001, speaker: Alice, time: 10:03 -->\n\n"
        "Alice: 我们需要先定义 source_id。\n\n"
        "Bob: 然后再确定 chunk_id 的生成规则。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "DateHeadingRegression",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    pages_path = workspace_dir / "state" / "pages.jsonl"
    page_records = [
        json.loads(line)
        for line in pages_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    concept_page = next(record for record in page_records if record.get("type") == "concept")

    assert concept_page["title"] == "2026-05-24"
    assert concept_page["page_path"].endswith("/2026-05-24.md")


def test_concept_page_ignores_yaml_examples_inside_definition_section(tmp_path: Path) -> None:
    # “Claim 是什么”小节里的 YAML 示例不应被当成真正的 claim 并抢占代表陈述。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "## 问题 9：知识声明 Claim 层如何在第一版实现\n\n"
        "### 1. Claim 是什么\n\n"
        "Claim 是从 chunk 中抽取出来的一条相对原子的知识声明。\n\n"
        "它不是普通摘要，也不是整段原文。\n\n"
        "例如：\n\n"
        "```yaml\n"
        "claim_id: claim_20260527_bm25_001\n"
        "text: BM25 是一种用于关键词检索的相关性排序算法。\n"
        "claim_type: definition\n"
        "```\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "ClaimExampleRegression",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    pages_path = workspace_dir / "state" / "pages.jsonl"
    page_records = [
        json.loads(line)
        for line in pages_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    concept_page = next(
        record
        for record in page_records
        if record.get("type") == "concept" and record.get("canonical_id") == "concept:claim"
    )

    page_text = (workspace_dir / concept_page["page_path"]).read_text(encoding="utf-8")
    assert "代表陈述: Claim 是从 chunk 中抽取出来的一条相对原子的知识声明" in page_text
    assert "代表陈述: Claim 是从 chunk 中抽取出来的一条相对原子的知识声明" in page_text
    assert "BM25 是一种用于关键词检索的相关性排序算法。" not in page_text


def test_concept_page_prefers_standalone_definition_over_dependent_clause(tmp_path: Path) -> None:
    # 概念页的代表陈述应优先选择可独立理解的定义句，而不是被长句切出来的从句残片。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# LLM Wiki\n\n"
        "**一种利用 LLM 构建个人知识库的模式。**\n\n"
        "这是一份思路文件，旨在复制粘贴到你自己的 LLM Agent 中"
        "（如 OpenAI Codex、Claude Code、OpenCode / Pi 等）。"
        "它的目标是传达高层思想，具体细节由你的 Agent 与你共同构建。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "CanonicalClaimReadabilityRegression",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    page_records = [
        json.loads(line)
        for line in (workspace_dir / "state" / "pages.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    concept_page = next(
        record
        for record in page_records
        if record.get("type") == "concept" and record.get("canonical_id") == "concept:llm_wiki"
    )

    page_text = (workspace_dir / concept_page["page_path"]).read_text(encoding="utf-8")
    assert "代表陈述: LLM Wiki 一种利用 LLM 构建个人知识库的模式" in page_text
    assert "## 核心陈述 / Canonical Claim" in page_text
    assert "旨在复制粘贴到你自己的 LLM Agent 中" in page_text
    assert "具体细节由你的 Agent 与你共同构建" in page_text


def test_concept_page_prefers_claim_aligned_with_section_topic(tmp_path: Path) -> None:
    # 同一来源里即使出现共享词汇的其他陈述，概念页代表陈述也应优先贴合当前 section 主题。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# BM25 和向量检索的差异\n\n"
        "BM25 和向量检索的差异在于，BM25 主要依赖关键词匹配和词频统计。\n\n"
        "向量检索主要依赖语义相似度，因此更适合补充语义召回。\n\n"
        "这句话语义上仍然是在问 raw/wiki 分离，但字面词不完全一样。这时向量检索可以补充召回。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "ConceptTopicAlignmentRegression",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    page_records = [
        json.loads(line)
        for line in (workspace_dir / "state" / "pages.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    concept_page = next(
        record
        for record in page_records
        if record.get("type") == "concept" and record.get("canonical_id") == "concept:bm25_和向量检索的差异"
    )

    page_text = (workspace_dir / concept_page["page_path"]).read_text(encoding="utf-8")
    assert "# BM25 和向量检索的差异" in page_text
    assert "代表陈述: BM25 和向量检索的差异在于，BM25 主要依赖关键词匹配和词频统计" in page_text
    assert "代表陈述: 这句话语义上仍然是在问 raw/wiki 分离" not in page_text


def test_concept_page_claim_type_label_is_not_rendered_as_markdown_link(tmp_path: Path) -> None:
    # claim_type 应显示为代码标签，而不是 [definition] 这种容易被查看器误判为链接的写法。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# Chunk Lint\n\n"
        "Chunk Lint 检查 chunk 是否可用： chunk 是否超过 hard max tokens。\n\n"
        "chunk 是否过短且未合并。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "ClaimTypeLabelRegression",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    pages_path = workspace_dir / "state" / "pages.jsonl"
    page_records = [
        json.loads(line)
        for line in pages_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    concept_page = next(record for record in page_records if record.get("type") == "concept")

    page_text = (workspace_dir / concept_page["page_path"]).read_text(encoding="utf-8")
    assert "`definition`" in page_text
    assert "[definition]" not in page_text


def test_concept_page_links_claim_ids_to_claim_json_files(tmp_path: Path) -> None:
    # 概念页里的 claim_id 应该能直接跳到 claims/<claim_id>.json，方便继续下钻证据链。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# Chunk Lint\n\n"
        "Chunk Lint 检查 chunk 是否可用： chunk 是否超过 hard max tokens。\n\n"
        "chunk 是否过短且未合并。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "ClaimReferenceRegression",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    page_records = [
        json.loads(line)
        for line in (workspace_dir / "state" / "pages.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    concept_page = next(record for record in page_records if record.get("type") == "concept")
    concept_page_text = (workspace_dir / concept_page["page_path"]).read_text(encoding="utf-8")

    claim_records = [
        json.loads(line)
        for line in (workspace_dir / "state" / "claims.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    linked_claim = next(record for record in claim_records if record.get("claim_type") == "definition")
    assert linked_claim["claim_file_path"] == f"claims/{linked_claim['claim_id']}.json"
    assert f"[`{linked_claim['claim_id']}`](../../../claims/{linked_claim['claim_id']}.json)" in concept_page_text


def test_concept_page_links_source_pages_raw_sources_and_chunks(tmp_path: Path) -> None:
    # 正式 concept 页应能继续下钻到来源摘要页、原始来源文件和对应 chunk 文件。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    source_path = source_dir / "topic.md"
    source_path.write_text(
        "# Chunk Lint\n\n"
        "Chunk Lint 检查 chunk 是否可用： chunk 是否超过 hard max tokens。\n\n"
        "chunk 是否过短且未合并。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "SourceEvidenceLinkRegression",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    page_records = [
        json.loads(line)
        for line in (workspace_dir / "state" / "pages.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    concept_page = next(record for record in page_records if record.get("type") == "concept")
    source_page = next(record for record in page_records if record.get("type") == "source-summary")
    concept_page_text = (workspace_dir / concept_page["page_path"]).read_text(encoding="utf-8")

    claim_records = [
        json.loads(line)
        for line in (workspace_dir / "state" / "claims.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    linked_claim = next(record for record in claim_records if record.get("claim_type") == "definition")
    source_ref = linked_claim["source_refs"][0]
    concept_page_path = Path(concept_page["page_path"])
    expected_source_page_link = quote(
        os.path.relpath(source_page["page_path"], start=concept_page_path.parent).replace(os.sep, "/"),
        safe="/._-~",
    )
    expected_source_path_link = quote(
        os.path.relpath(source_ref["source_path"], start=concept_page_path.parent).replace(os.sep, "/"),
        safe="/._-~",
    )
    expected_chunk_link = quote(
        os.path.relpath(f"chunks/{source_ref['source_id']}.jsonl", start=concept_page_path.parent).replace(os.sep, "/"),
        safe="/._-~",
    )

    assert "来源摘要页:" in concept_page_text
    assert "原始文件:" in concept_page_text
    assert "证据切块:" in concept_page_text
    assert f"[{source_page['title']}]({expected_source_page_link})" in concept_page_text
    assert f"[`{source_ref['source_path']}`]({expected_source_path_link})" in concept_page_text
    assert f"[`{source_ref['chunk_id']}`]({expected_chunk_link})" in concept_page_text


def test_query_evidence_intent_boosts_source_refs_field(tmp_path: Path) -> None:
    # “来源/证据”类问题应识别为 evidence，并让 source_refs 字段真正参与更强排序。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# 证据回链\n\n"
        "系统需要把 Wiki 结论回链到 Claim、Chunk 和 Source。\n\n"
        "来源证据应能在查询结果里被优先读取。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "EvidenceQueryRegression",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    result = run_cli("query", "这个结论的来源证据是什么", "--target-dir", str(workspace_dir))

    assert result["intent"] == "evidence"
    assert result["results"]
    source_result = next(item for item in result["results"] if item["type"] == "source-summary")
    assert result["results"].index(source_result) < 2
    assert source_result["intent_boost_reason"] == "intent_evidence_prefers_source"
    assert source_result["reading_pack"]["query_intent"] == "evidence"
    assert result["contract_version"] == "query_answer_handoff/v1"
    assert source_result["reading_pack"]["contract_version"] == "query_answer_handoff/v1"
    assert source_result["reading_pack"]["query"]["intent"] == "evidence"
    assert source_result["reading_pack"]["retrieval_context"]["focus"] == "source_evidence"
    assert source_result["reading_pack"]["answer_guardrails"]["must_read_sources"] is True
    assert source_result["reading_pack"]["answer_guardrails"]["cite_expectation"] == "strong"
    assert source_result["reading_pack"]["answer_handoff"]["answer_mode"] == "sources_first"
    assert source_result["reading_pack"]["answer_handoff"]["should_cite_sources"] is True
    assert source_result["reading_pack"]["answer_handoff"]["required_evidence_paths"][-1] == "evidence_context.source_trail"


def test_lint_passes_and_writes_report_for_initialized_workspace(tmp_path: Path) -> None:
    # lint_latest.md 应只代表“最近一次真实 lint 结果”，不应在 init 阶段先写占位文件。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# Git 版本管理\n\n"
        "系统需要使用 Git 管理本地版本历史。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "LintRegression",
        "--target-dir", str(workspace_dir),
    )
    report_path = workspace_dir / "reports" / "lint" / "lint_latest.md"
    assert not report_path.exists()

    run_cli("ingest", "--target-dir", str(workspace_dir))
    assert not report_path.exists()

    result = run_cli("lint", "--target-dir", str(workspace_dir))

    assert result["summary"]["ok"] is True
    assert report_path.exists()
    report_text = report_path.read_text(encoding="utf-8")
    assert "Lint Report" in report_text
    assert "search_index_covers_live_pages" in report_text


def test_lint_requires_single_live_page_type_per_canonical_id(tmp_path: Path) -> None:
    # 现版本每个 canonical_id 只应保留一个 live 页型。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# 知识声明层\n\n"
        "知识声明层是位于 chunk 与 wiki 之间的独立知识声明层。\n\n"
        "知识声明层用于承载可追踪、可合并、可审计的结论。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "CanonicalPageFamilyRegression",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    claim_records = load_jsonl(workspace_dir / "state" / "claims.jsonl")
    definition_claim = next(record for record in claim_records if record.get("claim_type") == "definition")
    run_cli(
        "claim-set-status",
        definition_claim["claim_id"],
        "stable",
        "--target-dir", str(workspace_dir),
    )

    page_records = load_jsonl(workspace_dir / "state" / "pages.jsonl")
    shared_canonical_pages = [
        record
        for record in page_records
        if record.get("canonical_id") == "concept:知识声明层"
    ]
    assert {record["type"] for record in shared_canonical_pages} == {"concept"}

    result = run_cli("lint", "--target-dir", str(workspace_dir))
    checks = {item["name"]: item for item in result["checks"]}

    assert result["summary"]["ok"] is True
    assert checks["canonical_page_family_valid"]["ok"] is True


def test_llm_assisted_readable_concept_page_uses_grounded_rewrite_when_enabled(tmp_path: Path) -> None:
    # 第三阶段允许对 concept 阅读页做 LLM 辅助润色，
    # 但只应在显式开启配置后生效，而且改写内容必须仍然绑在 stable claim 上。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# 知识声明层\n\n"
        "知识声明层是位于 chunk 与 wiki 之间的独立知识声明层。\n\n"
        "知识声明层用于承载可追踪、可合并、可审计的结论。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "LLMAssistedReadableConcept",
        "--target-dir", str(workspace_dir),
    )

    rewriter_script = tmp_path / "rewrite_readable_concept.py"
    rewriter_script.write_text(
        "import json\n"
        "import sys\n"
        "\n"
        "payload = json.load(sys.stdin)\n"
        "canonical = payload['canonical_claim']\n"
        "claim_id = canonical['claim_id']\n"
        "title = payload['title']\n"
        "practical_claim_id = next(\n"
        "    (\n"
        "        item['claim_id']\n"
        "        for item in payload['stable_claims']\n"
        "        if '用于承载可追踪、可合并、可审计的结论' in item['text']\n"
        "    ),\n"
        "    claim_id,\n"
        ")\n"
        "json.dump({\n"
        "    'summary': f'{title} 是位于 chunk 与 wiki 之间的独立知识声明层，可作为知识沉淀的稳定阅读入口。',\n"
        "    'key_points': [\n"
        "        {\n"
        "            'claim_id': claim_id,\n"
        "            'text': f'{title} 是位于 chunk 与 wiki 之间的独立知识声明层。',\n"
        "        }\n"
        "    ],\n"
        "    'practical_notes': [\n"
        "        {\n"
        "            'claim_id': practical_claim_id,\n"
        "            'text': f'{title} 用于承载可追踪、可合并、可审计的结论。',\n"
        "        }\n"
        "    ],\n"
        "}, sys.stdout, ensure_ascii=False)\n",
        encoding="utf-8",
    )
    configure_llm_assisted_readable_concept(workspace_dir, rewriter_script)

    run_cli("ingest", "--target-dir", str(workspace_dir))
    claim_records = load_jsonl(workspace_dir / "state" / "claims.jsonl")
    stable_claim_ids = [record["claim_id"] for record in claim_records]
    for claim_id in stable_claim_ids:
        run_cli(
            "claim-set-status",
            claim_id,
            "stable",
            "--target-dir", str(workspace_dir),
        )

    page_records = load_jsonl(workspace_dir / "state" / "pages.jsonl")
    readable_concept_page = next(record for record in page_records if record.get("type") == "concept")
    page_text = (workspace_dir / readable_concept_page["page_path"]).read_text(encoding="utf-8")

    assert readable_concept_page["summary"] == "知识声明层 是位于 chunk 与 wiki 之间的独立知识声明层，可作为知识沉淀的稳定阅读入口。"
    assert "知识声明层 是位于 chunk 与 wiki 之间的独立知识声明层，可作为知识沉淀的稳定阅读入口。" in page_text
    assert "- 知识声明层 是位于 chunk 与 wiki 之间的独立知识声明层。" in page_text
    assert "- 知识声明层 用于承载可追踪、可合并、可审计的结论。" in page_text


def test_llm_assisted_readable_concept_page_falls_back_when_rewrite_is_ungrounded(tmp_path: Path) -> None:
    # 如果 LLM 输出没有绑定到允许的 claim 或内容明显跑偏，应自动回退到第二阶段的确定性模板。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# 知识声明层\n\n"
        "知识声明层是位于 chunk 与 wiki 之间的独立知识声明层。\n\n"
        "知识声明层用于承载可追踪、可合并、可审计的结论。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "LLMAssistedFallback",
        "--target-dir", str(workspace_dir),
    )

    rewriter_script = tmp_path / "rewrite_readable_concept_bad.py"
    rewriter_script.write_text(
        "import json\n"
        "import sys\n"
        "\n"
        "json.load(sys.stdin)\n"
        "json.dump({\n"
        "    'summary': '这是一个完全脱离 claim 的新说法。',\n"
        "    'key_points': [\n"
        "        {'claim_id': 'claim_fake', 'text': '这个系统主要依赖向量数据库。'}\n"
        "    ],\n"
        "    'practical_notes': [\n"
        "        {'claim_id': 'claim_fake', 'text': '应该直接跳过证据页。'}\n"
        "    ],\n"
        "}, sys.stdout, ensure_ascii=False)\n",
        encoding="utf-8",
    )
    configure_llm_assisted_readable_concept(workspace_dir, rewriter_script)

    run_cli("ingest", "--target-dir", str(workspace_dir))
    claim_records = load_jsonl(workspace_dir / "state" / "claims.jsonl")
    definition_claim = next(record for record in claim_records if record.get("claim_type") == "definition")
    run_cli(
        "claim-set-status",
        definition_claim["claim_id"],
        "stable",
        "--target-dir", str(workspace_dir),
    )

    page_records = load_jsonl(workspace_dir / "state" / "pages.jsonl")
    readable_concept_page = next(record for record in page_records if record.get("type") == "concept")
    page_text = (workspace_dir / readable_concept_page["page_path"]).read_text(encoding="utf-8")

    assert readable_concept_page["summary"] == "知识声明层是位于 chunk 与 wiki 之间的独立知识声明层。 当前版本基于 1 条稳定 Claim、1 个来源整理。"
    assert "这是一个完全脱离 claim 的新说法。" not in page_text
    assert "这个系统主要依赖向量数据库。" not in page_text
    assert "## 关键要点 / Key Points" in page_text


def test_render_readable_concept_command_returns_render_metadata_and_page_text(tmp_path: Path) -> None:
    # 第四/五阶段把 readable concept 渲染收口成正式 CLI 命令，
    # 并进一步抽成通用 render-page 入口，便于后续接更多页面类型。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# 知识声明层\n\n"
        "知识声明层是位于 chunk 与 wiki 之间的独立知识声明层。\n\n"
        "知识声明层用于承载可追踪、可合并、可审计的结论。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "ReadableConceptRenderCommand",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    claim_records = load_jsonl(workspace_dir / "state" / "claims.jsonl")
    definition_claim = next(record for record in claim_records if record.get("claim_type") == "definition")
    run_cli(
        "claim-set-status",
        definition_claim["claim_id"],
        "stable",
        "--target-dir", str(workspace_dir),
    )

    page_records = load_jsonl(workspace_dir / "state" / "pages.jsonl")
    readable_concept_page = next(record for record in page_records if record.get("type") == "concept")

    result = run_cli(
        "render-readable-concept",
        "--page-id", readable_concept_page["page_id"],
        "--target-dir", str(workspace_dir),
    )

    assert result["summary"]["page_count"] == 1
    assert result["pages"][0]["page_id"] == readable_concept_page["page_id"]
    assert result["pages"][0]["render_target"] == "readable_concept"
    assert result["pages"][0]["render_mode"] == "llm_assisted"
    assert result["pages"][0]["render_status"] in {"llm_assisted", "deterministic_fallback"}
    assert "# 知识声明层" in result["page_text"]
    assert "## 摘要 / Summary" in result["page_text"]


def test_render_page_command_supports_generic_render_target_selector(tmp_path: Path) -> None:
    # 第五阶段开始，通用 render-page 应能按 render_target 统一查看页面，
    # 而不是每种页面类型都各开一个平行命令。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# 知识声明层\n\n"
        "知识声明层是位于 chunk 与 wiki 之间的独立知识声明层。\n\n"
        "知识声明层用于承载可追踪、可合并、可审计的结论。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "GenericRenderPageCommand",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    claim_records = load_jsonl(workspace_dir / "state" / "claims.jsonl")
    definition_claim = next(record for record in claim_records if record.get("claim_type") == "definition")
    run_cli(
        "claim-set-status",
        definition_claim["claim_id"],
        "stable",
        "--target-dir", str(workspace_dir),
    )

    result = run_cli(
        "render-page",
        "--render-target", "readable_concept",
        "--claim-id", definition_claim["claim_id"],
        "--target-dir", str(workspace_dir),
    )

    assert result["render_target"] == "readable_concept"
    assert result["summary"]["page_count"] == 1
    assert result["pages"][0]["render_target"] == "readable_concept"
    assert result["pages"][0]["canonical_id"] == "concept:知识声明层"
    assert "# 知识声明层" in result["page_text"]


def test_stable_multi_concept_workspace_generates_overview_page(tmp_path: Path) -> None:
    # 第六阶段引入 overview，先验证当工作区里已有多个稳定可读概念页时，
    # 系统会自动补出一个工作区级综述入口。
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "WorkspaceOverviewGeneration")

    page_records = load_jsonl(workspace_dir / "state" / "pages.jsonl")
    overview_page = next(record for record in page_records if record.get("type") == "overview")

    assert overview_page["render_target"] == "overview"
    assert overview_page["status"] == "stable"
    assert overview_page["canonical_id"] == "overview:workspace"
    assert overview_page["page_path"] == "wiki/overview/index.md"
    assert len(overview_page["claim_ids"]) >= 2

    page_text = (workspace_dir / overview_page["page_path"]).read_text(encoding="utf-8")
    assert "## 工作区综述 / Workspace Overview" in page_text
    assert "## 主题导览 / Theme Map" in page_text
    assert "## 推荐阅读路径 / Suggested Reading Path" in page_text
    assert "## 来源覆盖 / Source Coverage" in page_text
    assert "来源页:" in page_text
    assert "Claim" in page_text
    assert "Chunk" in page_text


def test_render_page_command_supports_overview_render_target(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "WorkspaceOverviewRender")

    result = run_cli(
        "render-page",
        "--render-target", "overview",
        "--canonical-id", "overview:workspace",
        "--target-dir", str(workspace_dir),
    )

    assert result["render_target"] == "overview"
    assert result["summary"]["page_count"] == 1
    assert result["pages"][0]["render_target"] == "overview"
    assert result["pages"][0]["canonical_id"] == "overview:workspace"
    assert "## 工作区综述 / Workspace Overview" in result["page_text"]


def test_query_overview_intent_prefers_overview_page_for_macro_question(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "WorkspaceOverviewQuery")

    result = run_cli("query", "这个工作区主要讲什么", "--target-dir", str(workspace_dir))

    assert result["intent"] == "overview"
    assert result["results"]
    assert result["results"][0]["type"] == "overview"
    assert result["results"][0]["canonical_id"] == "overview:workspace"
    assert result["results"][0]["intent_boost_reason"] == "intent_overview_prefers_overview_page"
    assert result["results"][0]["reading_pack"]["focus"] == "workspace_overview"


def test_llm_assisted_overview_page_uses_grounded_rewrite_when_enabled(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "LLMAssistedOverview")

    rewriter_script = tmp_path / "rewrite_overview.py"
    rewriter_script.write_text(
        "import json\n"
        "import sys\n"
        "\n"
        "payload = json.load(sys.stdin)\n"
        "first_theme = payload['theme_rows'][0]\n"
        "second_theme = payload['theme_rows'][1]\n"
        "json.dump({\n"
        "    'summary': '这个工作区主要围绕 Claim 和 Chunk 两个稳定主题展开。',\n"
        "    'theme_rows': [\n"
        "        {\n"
        "            'page_id': first_theme['page_id'],\n"
        "            'text': '这个主题解释了 Claim 作为独立知识声明层的定位。',\n"
        "        },\n"
        "        {\n"
        "            'page_id': second_theme['page_id'],\n"
        "            'text': '这个主题说明了 Chunk 作为证据切片单元的作用。',\n"
        "        },\n"
        "    ],\n"
        "    'reading_path': [\n"
        "        {\n"
        "            'page_id': first_theme['page_id'],\n"
        "            'text': '如果你想先建立全局认识，先读 Claim 主题。',\n"
        "        },\n"
        "        {\n"
        "            'page_id': second_theme['page_id'],\n"
        "            'text': '如果你想继续追证据结构，再看 Chunk 主题。',\n"
        "        },\n"
        "    ],\n"
        "}, sys.stdout, ensure_ascii=False)\n",
        encoding="utf-8",
    )
    configure_llm_assisted_overview(workspace_dir, rewriter_script)

    run_cli("ingest", "--target-dir", str(workspace_dir))
    page_records = load_jsonl(workspace_dir / "state" / "pages.jsonl")
    overview_page = next(record for record in page_records if record.get("type") == "overview")
    page_text = (workspace_dir / overview_page["page_path"]).read_text(encoding="utf-8")

    assert overview_page["render_status"] == "llm_assisted"
    assert overview_page["summary"] == "这个工作区主要围绕 Claim 和 Chunk 两个稳定主题展开。"
    assert "这个主题解释了 Claim 作为独立知识声明层的定位。" in page_text
    assert "如果你想先建立全局认识，先读 Claim 主题。" in page_text
    assert "## 改写回绑 / Rewrite Traceability" in page_text
    assert "<summary>查看 overview 改写句与其回绑页面</summary>" in page_text
    assert "主题导览句: `这个主题解释了 Claim 作为独立知识声明层的定位。`" in page_text
    assert "推荐阅读句: `如果你想先建立全局认识，先读 Claim 主题。`" in page_text


def test_llm_assisted_overview_page_falls_back_when_rewrite_is_ungrounded(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "LLMAssistedOverviewFallback")

    rewriter_script = tmp_path / "rewrite_overview_bad.py"
    rewriter_script.write_text(
        "import json\n"
        "import sys\n"
        "\n"
        "json.load(sys.stdin)\n"
        "json.dump({\n"
        "    'summary': '这个工作区的核心是向量数据库和外部缓存。',\n"
        "    'theme_rows': [\n"
        "        {\n"
        "            'page_id': 'page_fake',\n"
        "            'text': '这个主题主要讲多代理调度系统。',\n"
        "        }\n"
        "    ],\n"
        "    'reading_path': [\n"
        "        {\n"
        "            'page_id': 'page_fake',\n"
        "            'text': '建议先读缓存系统设计。',\n"
        "        }\n"
        "    ],\n"
        "}, sys.stdout, ensure_ascii=False)\n",
        encoding="utf-8",
    )
    configure_llm_assisted_overview(workspace_dir, rewriter_script)

    run_cli("ingest", "--target-dir", str(workspace_dir))
    page_records = load_jsonl(workspace_dir / "state" / "pages.jsonl")
    overview_page = next(record for record in page_records if record.get("type") == "overview")
    page_text = (workspace_dir / overview_page["page_path"]).read_text(encoding="utf-8")

    assert overview_page["render_status"] == "deterministic_fallback"
    assert "这个工作区的核心是向量数据库和外部缓存。" not in page_text
    assert "建议先读缓存系统设计。" not in page_text
    assert "## 推荐阅读路径 / Suggested Reading Path" in page_text


def test_lint_accepts_generated_overview_page_render_metadata(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "WorkspaceOverviewLint")

    result = run_cli("lint", "--target-dir", str(workspace_dir))
    checks = {item["name"]: item for item in result["checks"]}

    assert result["summary"]["ok"] is True
    assert checks["overview_render_metadata_present"]["ok"] is True
    assert checks["overview_pages_grounded"]["ok"] is True
    assert checks["alias_conflicts_absent"]["ok"] is True


def test_lint_flags_overview_page_when_manual_edit_breaks_grounding(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "OverviewGroundingLint")

    page_records = load_jsonl(workspace_dir / "state" / "pages.jsonl")
    overview_page = next(record for record in page_records if record.get("type") == "overview")
    page_path = workspace_dir / overview_page["page_path"]
    page_text = page_path.read_text(encoding="utf-8")
    page_text = page_text.replace(
        "Claim、Chunk 是当前工作区里已经沉淀出的稳定主题。",
        "这份综述主要讲向量数据库、缓存和多代理调度。",
    )
    page_path.write_text(page_text, encoding="utf-8")

    result = run_cli_expect_exit("lint", "--target-dir", str(workspace_dir), expected_exit_code=1)
    checks = {item["name"]: item for item in result["checks"]}

    assert result["summary"]["ok"] is False
    assert checks["overview_pages_grounded"]["ok"] is False


def test_lint_flags_readable_concept_page_when_manual_edit_breaks_grounding(tmp_path: Path) -> None:
    # 第四阶段 lint 应能发现可读页被手工改坏、开始脱离其 claim 证据边界的情况。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# 知识声明层\n\n"
        "知识声明层是位于 chunk 与 wiki 之间的独立知识声明层。\n\n"
        "知识声明层用于承载可追踪、可合并、可审计的结论。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "ReadableConceptGroundingLint",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    claim_records = load_jsonl(workspace_dir / "state" / "claims.jsonl")
    definition_claim = next(record for record in claim_records if record.get("claim_type") == "definition")
    run_cli(
        "claim-set-status",
        definition_claim["claim_id"],
        "stable",
        "--target-dir", str(workspace_dir),
    )

    page_records = load_jsonl(workspace_dir / "state" / "pages.jsonl")
    readable_concept_page = next(record for record in page_records if record.get("type") == "concept")
    page_path = workspace_dir / readable_concept_page["page_path"]
    page_text = page_path.read_text(encoding="utf-8")
    page_text = page_text.replace(
        "知识声明层是位于 chunk 与 wiki 之间的独立知识声明层。 当前版本基于 1 条稳定 Claim、1 个来源整理。",
        "这个页面现在主要讲向量数据库和外部缓存系统。",
    )
    page_path.write_text(page_text, encoding="utf-8")

    result = run_cli_expect_exit("lint", "--target-dir", str(workspace_dir), expected_exit_code=1)
    checks = {item["name"]: item for item in result["checks"]}

    assert result["summary"]["ok"] is False
    assert checks["readable_concept_pages_grounded"]["ok"] is False
    assert "summary_not_grounded" in checks["readable_concept_pages_grounded"]["details"]


def test_ingest_filters_obviously_bad_concept_titles(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# Query 预处理规范\n\n"
        "## 示例\n\n"
        "“那个 Karpathy 提的 LLM-Wiki 里面，搜索到底是不是语义搜索啊？”\n\n"
        "可以抽成更适合检索的关键词：Karpathy、LLM-Wiki、BM25。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "FilterBadConceptTitles",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    page_records = load_jsonl(workspace_dir / "state" / "pages.jsonl")
    concept_titles = {
        record["title"]
        for record in page_records
        if record.get("type") == "concept"
    }
    assert "示例" not in concept_titles


def test_gray_concept_title_can_be_renamed_by_llm_hook(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# 检索设计\n\n"
        "## 作用\n\n"
        "BM25 同时承担关键词召回和可解释排序的职责。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "ConceptTitleLLMReview",
        "--target-dir", str(workspace_dir),
    )

    reviewer_script = tmp_path / "review_concept_title.py"
    reviewer_script.write_text(
        "import json\n"
        "import sys\n"
        "\n"
        "payload = json.load(sys.stdin)\n"
        "json.dump({\n"
        "    'decision': 'rename',\n"
        "    'suggested_title': 'BM25',\n"
        "    'reason': 'test_rewrite_gray_title',\n"
        "    'confidence': 0.95,\n"
        "}, sys.stdout, ensure_ascii=False)\n",
        encoding="utf-8",
    )
    configure_llm_assisted_concept_quality(workspace_dir, reviewer_script)

    run_cli("ingest", "--target-dir", str(workspace_dir))
    page_records = load_jsonl(workspace_dir / "state" / "pages.jsonl")
    concept_titles = {
        record["title"]
        for record in page_records
        if record.get("type") == "concept"
    }
    assert "BM25" in concept_titles
    assert "作用" not in concept_titles


def test_lint_warns_on_low_quality_concept_titles(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# Alpha\n\n"
        "Alpha 是一个稳定概念。\n\n"
        "Alpha 用于承载稳定主题说明。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "ConceptTitleLint",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    pages_path = workspace_dir / "state" / "pages.jsonl"
    page_records = load_jsonl(pages_path)
    concept_page = next(record for record in page_records if record.get("type") == "concept")
    concept_page["title"] = "示例"
    pages_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in page_records) + "\n",
        encoding="utf-8",
    )

    result = run_cli("lint", "--target-dir", str(workspace_dir))
    checks = {item["name"]: item for item in result["checks"]}
    assert checks["concept_pages_title_quality"]["ok"] is False
    assert "generic_title" in checks["concept_pages_title_quality"]["details"] or "rejected_title" in checks["concept_pages_title_quality"]["details"]


def test_lint_warns_on_page_semantic_consistency_conflicts(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "workflow.md").write_text(
        "# 工作流\n\n"
        "首先扫描 raw 目录。\n\n"
        "然后生成 normalized 文档。\n\n"
        "例如，可以先处理 Markdown 文件。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "LintSemanticConsistency",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    pages_path = workspace_dir / "state" / "pages.jsonl"
    page_records = load_jsonl(pages_path)
    topic_page = next(record for record in page_records if record.get("type") == "guide")
    topic_page["type"] = "example"
    pages_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in page_records) + "\n",
        encoding="utf-8",
    )

    result = run_cli("lint", "--target-dir", str(workspace_dir))
    checks = {item["name"]: item for item in result["checks"]}
    assert checks["page_semantic_consistency"]["ok"] is False
    assert "page_type_intent_mismatch" in checks["page_semantic_consistency"]["details"]


def test_init_creates_alias_index_file(tmp_path: Path) -> None:
    # 初始化后的工作区应该直接带 alias registry，占位也好过缺文件。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text("知识库需要来源追踪。", encoding="utf-8")

    workspace_dir = tmp_path / "workspace"
    result = run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "AliasIndexInit",
        "--target-dir", str(workspace_dir),
    )

    assert Path(result["target_dir"]).resolve() == workspace_dir.resolve()
    alias_index_path = workspace_dir / "indexes" / "aliases.json"
    assert alias_index_path.exists()
    alias_index = json.loads(alias_index_path.read_text(encoding="utf-8"))
    assert alias_index["index_version"] == "aliases_v1"


def test_ingest_creates_alias_conflict_review_when_alias_registry_collides(tmp_path: Path) -> None:
    # 这个回归直接验证 alias registry 不只是“发现冲突”，
    # 而是真的会把冲突送进 review 队列。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "alpha.md").write_text(
        "# Alpha 术语\n\n"
        "Alpha 术语是用于管理版本状态的概念。\n",
        encoding="utf-8",
    )
    (source_dir / "beta.md").write_text(
        "# Beta 术语\n\n"
        "Beta 术语是用于管理审核状态的概念。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "AliasConflictReview",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    shared_alias = "共享术语"
    injected_page_ids = inject_shared_alias_override(workspace_dir, shared_alias)

    # 再次 ingest 会刷新 pages -> aliases -> reviews。
    run_cli("ingest", "--target-dir", str(workspace_dir))

    reviews_path = workspace_dir / "state" / "reviews.jsonl"
    review_records = [
        json.loads(line)
        for line in reviews_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    alias_reviews = [record for record in review_records if record.get("kind") == "alias_conflict"]

    assert alias_reviews
    assert any(shared_alias in json.dumps(record.get("evidence", []), ensure_ascii=False) for record in alias_reviews)
    assert any(sorted(record.get("candidate_page_ids", [])) == sorted(injected_page_ids) for record in alias_reviews)


def test_review_apply_assign_alias_updates_page_alias_overrides(tmp_path: Path) -> None:
    # alias_conflict 的细动作应能把某个 alias 指定给目标页，并写入可持久化的覆盖层。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "alpha.md").write_text("# Alpha 术语\n\nAlpha 术语是用于管理版本状态的概念。\n", encoding="utf-8")
    (source_dir / "beta.md").write_text("# Beta 术语\n\nBeta 术语是用于管理审核状态的概念。\n", encoding="utf-8")

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "AssignAliasReview",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    shared_alias = "共享术语"
    inject_shared_alias_override(workspace_dir, shared_alias)
    run_cli("ingest", "--target-dir", str(workspace_dir))

    reviews = run_cli("review-list", "--target-dir", str(workspace_dir))
    alias_review = next(item for item in reviews["items"] if item["kind"] == "alias_conflict")
    primary_page_id = alias_review["candidate_page_ids"][0]

    result = run_cli(
        "review-apply",
        alias_review["review_id"],
        "assign_alias",
        "--primary-page-id", primary_page_id,
        "--alias-value", shared_alias,
        "--target-dir", str(workspace_dir),
    )

    assert result["action"] == "assign_alias"
    overrides_path = workspace_dir / "state" / "page_alias_overrides.json"
    overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
    assert shared_alias in overrides["page_aliases"][primary_page_id]["aliases"]


def test_review_apply_remove_alias_clears_alias_from_overrides(tmp_path: Path) -> None:
    # remove_alias 应能把冲突 alias 从覆盖层里移掉，适合人工决定“先都别用这个别名”。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "alpha.md").write_text("# Alpha 术语\n\nAlpha 术语是用于管理版本状态的概念。\n", encoding="utf-8")
    (source_dir / "beta.md").write_text("# Beta 术语\n\nBeta 术语是用于管理审核状态的概念。\n", encoding="utf-8")

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "RemoveAliasReview",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    shared_alias = "共享术语"
    inject_shared_alias_override(workspace_dir, shared_alias)
    run_cli("ingest", "--target-dir", str(workspace_dir))

    reviews = run_cli("review-list", "--target-dir", str(workspace_dir))
    alias_review = next(item for item in reviews["items"] if item["kind"] == "alias_conflict")
    primary_page_id = alias_review["candidate_page_ids"][0]
    run_cli(
        "review-apply",
        alias_review["review_id"],
        "remove_alias",
        "--primary-page-id", primary_page_id,
        "--alias-value", shared_alias,
        "--target-dir", str(workspace_dir),
    )

    overrides_path = workspace_dir / "state" / "page_alias_overrides.json"
    overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
    for page_id in alias_review["candidate_page_ids"]:
        assert shared_alias not in overrides["page_aliases"][page_id]["aliases"]


def test_assign_alias_persists_after_reingest_and_clears_open_alias_conflict(tmp_path: Path) -> None:
    # assign_alias 后重新 ingest，不应因为自动页面重建而把同一冲突重新打开。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "alpha.md").write_text("# Alpha 术语\n\nAlpha 术语是版本状态相关概念。\n", encoding="utf-8")
    (source_dir / "beta.md").write_text("# Beta 术语\n\nBeta 术语是审核闭环相关概念。\n", encoding="utf-8")

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "AssignAliasPersistence",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    shared_alias = "共享术语"
    inject_shared_alias_override(workspace_dir, shared_alias)

    run_cli("ingest", "--target-dir", str(workspace_dir))
    reviews = run_cli("review-list", "--target-dir", str(workspace_dir))
    alias_review = next(item for item in reviews["items"] if item["kind"] == "alias_conflict")
    primary_page_id = alias_review["candidate_page_ids"][0]

    run_cli(
        "review-apply",
        alias_review["review_id"],
        "assign_alias",
        "--primary-page-id", primary_page_id,
        "--alias-value", shared_alias,
        "--target-dir", str(workspace_dir),
    )

    run_cli("ingest", "--target-dir", str(workspace_dir))

    overrides_path = workspace_dir / "state" / "page_alias_overrides.json"
    overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
    assert shared_alias in overrides["page_aliases"][primary_page_id]["aliases"]

    refreshed_reviews = run_cli("review-list", "--target-dir", str(workspace_dir))
    assert not any(
        item["kind"] == "alias_conflict" and item["status"] == "open"
        for item in refreshed_reviews["items"]
    )


def test_alias_conflict_keep_both_persists_accepted_ambiguity_and_clears_open_review(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "alpha.md").write_text("# Alpha 术语\n\nAlpha 术语是版本状态相关概念。\n", encoding="utf-8")
    (source_dir / "beta.md").write_text("# Beta 术语\n\nBeta 术语是审核闭环相关概念。\n", encoding="utf-8")

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "KeepBothAliasConflict",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    shared_alias = "共享术语"
    inject_shared_alias_override(workspace_dir, shared_alias)
    run_cli("ingest", "--target-dir", str(workspace_dir))

    reviews = run_cli("review-list", "--target-dir", str(workspace_dir))
    alias_review = next(item for item in reviews["items"] if item["kind"] == "alias_conflict")

    result = run_cli(
        "review-apply",
        alias_review["review_id"],
        "keep_both",
        "--target-dir", str(workspace_dir),
    )

    assert result["action"] == "keep_both"
    overrides = json.loads((workspace_dir / "state" / "page_alias_overrides.json").read_text(encoding="utf-8"))
    accepted_conflicts = overrides.get("accepted_conflicts", [])
    assert any(
        item.get("alias") == shared_alias and len(item.get("canonical_ids", [])) >= 2
        for item in accepted_conflicts
    )

    run_cli("ingest", "--target-dir", str(workspace_dir))
    refreshed_reviews = run_cli("review-list", "--target-dir", str(workspace_dir))
    assert not any(
        item["kind"] == "alias_conflict" and item["status"] == "open"
        for item in refreshed_reviews["items"]
    )


def test_lint_ignores_accepted_alias_conflicts_after_keep_both(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "alpha.md").write_text("# Alpha 术语\n\nAlpha 术语是版本状态相关概念。\n", encoding="utf-8")
    (source_dir / "beta.md").write_text("# Beta 术语\n\nBeta 术语是审核闭环相关概念。\n", encoding="utf-8")

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "LintAcceptedAliasConflict",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    shared_alias = "共享术语"
    inject_shared_alias_override(workspace_dir, shared_alias)
    run_cli("ingest", "--target-dir", str(workspace_dir))

    warning_result = run_cli("lint", "--target-dir", str(workspace_dir))
    warning_checks = {item["name"]: item for item in warning_result["checks"]}
    assert warning_checks["alias_conflicts_absent"]["ok"] is False

    reviews = run_cli("review-list", "--target-dir", str(workspace_dir))
    alias_review = next(item for item in reviews["items"] if item["kind"] == "alias_conflict")
    run_cli(
        "review-apply",
        alias_review["review_id"],
        "keep_both",
        "--target-dir", str(workspace_dir),
    )

    accepted_result = run_cli("lint", "--target-dir", str(workspace_dir))
    accepted_checks = {item["name"]: item for item in accepted_result["checks"]}
    assert accepted_checks["alias_conflicts_absent"]["ok"] is True


def test_assign_alias_allows_same_canonical_page_family_to_share_alias(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "alpha.md").write_text("# Alpha\n\nAlpha 是版本状态相关概念。\n", encoding="utf-8")
    (source_dir / "beta.md").write_text("# Beta\n\nBeta 是审核闭环相关概念。\n", encoding="utf-8")

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "AssignAliasCanonicalFamily",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    page_records = load_jsonl(workspace_dir / "state" / "pages.jsonl")
    candidate_pages = [
        record for record in page_records
        if not record.get("removed")
        and record.get("lifecycle_status", "active") == "active"
        and record.get("type") in {"concept", "topic", "guide", "example"}
    ]
    concept_summary = candidate_pages[0]
    other_concept = candidate_pages[1]
    shared_alias = "一句话总结"
    inject_shared_alias_override(
        workspace_dir,
        shared_alias,
        page_ids=[concept_summary["page_id"], other_concept["page_id"]],
    )

    run_cli("ingest", "--target-dir", str(workspace_dir))
    reviews = run_cli("review-list", "--target-dir", str(workspace_dir))
    alias_review = next(item for item in reviews["items"] if item["kind"] == "alias_conflict")

    run_cli(
        "review-apply",
        alias_review["review_id"],
        "assign_alias",
        "--primary-page-id", concept_summary["page_id"],
        "--alias-value", shared_alias,
        "--target-dir", str(workspace_dir),
    )

    refreshed_reviews = run_cli("review-list", "--target-dir", str(workspace_dir))
    assert not any(
        item["kind"] == "alias_conflict" and item["status"] == "open"
        for item in refreshed_reviews["items"]
    )


def test_review_list_archives_stale_alias_conflict_reviews(tmp_path: Path) -> None:
    # 当 alias 冲突已经在当前 pages/alias index 中消失时，review-list 应自动收掉过期 alias review。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "alpha.md").write_text("# Alpha 术语\n\nAlpha 术语是版本状态相关概念。\n", encoding="utf-8")
    (source_dir / "beta.md").write_text("# Beta 术语\n\nBeta 术语是审核闭环相关概念。\n", encoding="utf-8")

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "ArchiveStaleAliasReviews",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    shared_alias = "共享术语"
    inject_shared_alias_override(workspace_dir, shared_alias)

    run_cli("ingest", "--target-dir", str(workspace_dir))
    initial_reviews = run_cli("review-list", "--target-dir", str(workspace_dir))
    alias_review = next(item for item in initial_reviews["items"] if item["kind"] == "alias_conflict")

    overrides_path = workspace_dir / "state" / "page_alias_overrides.json"
    overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
    for page_override in overrides.get("page_aliases", {}).values():
        page_override["aliases"] = [
            alias for alias in page_override.get("aliases", [])
            if alias != shared_alias
        ]
    overrides_path.write_text(json.dumps(overrides, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    run_cli("ingest", "--target-dir", str(workspace_dir))

    refreshed_reviews = run_cli("review-list", "--target-dir", str(workspace_dir))
    assert not any(item["kind"] == "alias_conflict" and item["status"] == "open" for item in refreshed_reviews["items"])

    review_records = load_jsonl(workspace_dir / "state" / "reviews.jsonl")
    historical_alias_reviews = [
        record for record in review_records
        if record.get("kind") == "alias_conflict"
        and record.get("original_review_id") == alias_review["review_id"]
    ]
    assert historical_alias_reviews
    assert all(record.get("lifecycle_status") == "superseded" for record in historical_alias_reviews)


def test_alias_index_skips_noisy_shared_titles_for_concept_pages(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "alpha.md").write_text("# Alpha\n\nAlpha 是概念一。\n", encoding="utf-8")
    (source_dir / "beta.md").write_text("# Beta\n\nBeta 是概念二。\n", encoding="utf-8")

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "NoisyTitleAlias",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    pages_path = workspace_dir / "state" / "pages.jsonl"
    page_records = load_jsonl(pages_path)
    concept_pages = [record for record in page_records if record.get("type") == "concept"][:2]
    assert len(concept_pages) == 2
    concept_pages[0]["title"] = "一句话总结"
    concept_pages[1]["title"] = "一句话总结"
    pages_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in page_records) + "\n",
        encoding="utf-8",
    )

    run_cli("ingest", "--target-dir", str(workspace_dir))

    alias_index = json.loads((workspace_dir / "indexes" / "aliases.json").read_text(encoding="utf-8"))
    assert "一句话总结" not in alias_index["alias_map"]
    refreshed_reviews = run_cli("review-list", "--target-dir", str(workspace_dir))
    assert not any(
        item["kind"] == "alias_conflict"
        and any(evidence.get("alias") == "一句话总结" for evidence in item.get("evidence", []))
        and item["status"] == "open"
        for item in refreshed_reviews["items"]
    )


def test_assign_alias_rejects_stale_alias_review_target(tmp_path: Path) -> None:
    # 如果 review 已经过期，assign_alias 不应假成功，而应明确提示 alias 当前已不属于该候选集。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "alpha.md").write_text("# Alpha 术语\n\nAlpha 术语是版本状态相关概念。\n", encoding="utf-8")
    (source_dir / "beta.md").write_text("# Beta 术语\n\nBeta 术语是审核闭环相关概念。\n", encoding="utf-8")

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "RejectStaleAliasReview",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    pages_path = workspace_dir / "state" / "pages.jsonl"
    page_records = load_jsonl(pages_path)
    concept_pages = [record for record in page_records if record.get("type") == "concept"]
    shared_alias = "共享术语"
    concept_pages[0]["aliases"] = sorted(set(concept_pages[0].get("aliases", []) + [shared_alias]))
    concept_pages[1]["aliases"] = sorted(set(concept_pages[1].get("aliases", []) + [shared_alias]))
    pages_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in page_records) + "\n",
        encoding="utf-8",
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    reviews = run_cli("review-list", "--target-dir", str(workspace_dir))
    alias_review = next(item for item in reviews["items"] if item["kind"] == "alias_conflict")

    refreshed_pages = load_jsonl(pages_path)
    for record in refreshed_pages:
        aliases = [alias for alias in record.get("aliases", []) if alias != shared_alias]
        record["aliases"] = aliases
    pages_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in refreshed_pages) + "\n",
        encoding="utf-8",
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "myagentwiki.cli",
            "review-apply",
            alias_review["review_id"],
            "assign_alias",
            "--primary-page-id", alias_review["candidate_page_ids"][0],
            "--alias-value", shared_alias,
            "--target-dir", str(workspace_dir),
            "--json",
        ],
        cwd=str(REPO_ROOT),
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "Unknown review_id" in completed.stderr or "only supports active review items" in completed.stderr


def test_review_apply_text_output_includes_absolute_workspace_path(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "alpha.md").write_text("# Alpha 术语\n\nAlpha 术语是版本状态相关概念。\n", encoding="utf-8")
    (source_dir / "beta.md").write_text("# Beta 术语\n\nBeta 术语是审核闭环相关概念。\n", encoding="utf-8")

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "ReviewApplyTextOutput",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    pages_path = workspace_dir / "state" / "pages.jsonl"
    page_records = [
        json.loads(line)
        for line in pages_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    concept_pages = [record for record in page_records if record.get("type") == "concept"]
    shared_alias = "共享术语"
    concept_pages[0]["aliases"] = sorted(set(concept_pages[0].get("aliases", []) + [shared_alias]))
    concept_pages[1]["aliases"] = sorted(set(concept_pages[1].get("aliases", []) + [shared_alias]))
    pages_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in page_records) + "\n",
        encoding="utf-8",
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    reviews = run_cli("review-list", "--target-dir", str(workspace_dir))
    alias_review = next(item for item in reviews["items"] if item["kind"] == "alias_conflict")
    primary_page_id = alias_review["candidate_page_ids"][0]

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "myagentwiki.cli",
            "review-apply",
            alias_review["review_id"],
            "assign_alias",
            "--primary-page-id", primary_page_id,
            "--alias-value", shared_alias,
            "--target-dir", str(workspace_dir),
        ],
        cwd=str(REPO_ROOT),
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
        capture_output=True,
        text=True,
        check=True,
    )
    assert f"Workspace: {workspace_dir.resolve()}" in completed.stdout


def test_remove_alias_persists_after_reingest(tmp_path: Path) -> None:
    # remove_alias 后再次 ingest，冲突 alias 不应重新回到人工覆盖层里。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "alpha.md").write_text("# Alpha 术语\n\nAlpha 术语是版本状态相关概念。\n", encoding="utf-8")
    (source_dir / "beta.md").write_text("# Beta 术语\n\nBeta 术语是审核闭环相关概念。\n", encoding="utf-8")

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "RemoveAliasPersistence",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    pages_path = workspace_dir / "state" / "pages.jsonl"
    page_records = [
        json.loads(line)
        for line in pages_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    concept_pages = [record for record in page_records if record.get("type") == "concept"]
    shared_alias = "共享术语"
    concept_pages[0]["aliases"] = sorted(set(concept_pages[0].get("aliases", []) + [shared_alias]))
    concept_pages[1]["aliases"] = sorted(set(concept_pages[1].get("aliases", []) + [shared_alias]))
    pages_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in page_records) + "\n",
        encoding="utf-8",
    )

    run_cli("ingest", "--target-dir", str(workspace_dir))
    reviews = run_cli("review-list", "--target-dir", str(workspace_dir))
    alias_review = next(item for item in reviews["items"] if item["kind"] == "alias_conflict")

    run_cli(
        "review-apply",
        alias_review["review_id"],
        "remove_alias",
        "--primary-page-id", alias_review["candidate_page_ids"][0],
        "--alias-value", shared_alias,
        "--target-dir", str(workspace_dir),
    )

    run_cli("ingest", "--target-dir", str(workspace_dir))

    refreshed_reviews = run_cli("review-list", "--target-dir", str(workspace_dir))
    assert not any(
        item["kind"] == "alias_conflict" and item["status"] == "open"
        for item in refreshed_reviews["items"]
    )


def test_assign_alias_keeps_existing_page_aliases(tmp_path: Path) -> None:
    # assign_alias 不应该把页面原本已有的其他 alias 一起抹掉。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "alpha.md").write_text("# Alpha 术语\n\nAlpha 术语是版本状态相关概念。\n", encoding="utf-8")
    (source_dir / "beta.md").write_text("# Beta 术语\n\nBeta 术语是审核闭环相关概念。\n", encoding="utf-8")

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "AssignAliasKeepsExistingAliases",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    pages_path = workspace_dir / "state" / "pages.jsonl"
    page_records = [
        json.loads(line)
        for line in pages_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    concept_pages = [record for record in page_records if record.get("type") == "concept"]
    primary_page = concept_pages[0]
    secondary_page = concept_pages[1]
    original_alias = "原有别名"
    shared_alias = "共享术语"
    primary_page["aliases"] = sorted(set(primary_page.get("aliases", []) + [original_alias, shared_alias]))
    secondary_page["aliases"] = sorted(set(secondary_page.get("aliases", []) + [shared_alias]))
    pages_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in page_records) + "\n",
        encoding="utf-8",
    )

    run_cli("ingest", "--target-dir", str(workspace_dir))
    reviews = run_cli("review-list", "--target-dir", str(workspace_dir))
    alias_review = next(item for item in reviews["items"] if item["kind"] == "alias_conflict")
    refreshed_pages_before_apply = [
        json.loads(line)
        for line in pages_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    primary_page_id = next(
        record["page_id"]
        for record in refreshed_pages_before_apply
        if original_alias in record.get("aliases", []) and record["page_id"] in alias_review["candidate_page_ids"]
    )

    run_cli(
        "review-apply",
        alias_review["review_id"],
        "assign_alias",
        "--primary-page-id", primary_page_id,
        "--alias-value", shared_alias,
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    refreshed_pages = [
        json.loads(line)
        for line in pages_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    refreshed_primary = next(record for record in refreshed_pages if record.get("page_id") == primary_page_id)
    assert original_alias in refreshed_primary.get("aliases", [])
    assert shared_alias in refreshed_primary.get("aliases", [])


def test_query_how_to_and_compare_set_reading_pack_focus(tmp_path: Path) -> None:
    # 不同 query intent 至少应在 reading_pack 上体现出不同的关注重点。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# 操作与对比\n\n"
        "步骤一：先建立来源追踪。\n\n"
        "步骤二：然后生成 claim 与 wiki 页面。\n\n"
        "Alpha 方案相比 Beta 方案更强调人工审核闭环。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "IntentFocusRegression",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    how_to = run_cli("query", "如何建立来源追踪", "--target-dir", str(workspace_dir))
    compare = run_cli("query", "Alpha 和 Beta 的区别", "--target-dir", str(workspace_dir))

    assert how_to["intent"] == "how_to"
    assert how_to["results"][0]["reading_pack"]["focus"] == "procedural_chunks"
    assert how_to["results"][0]["reading_pack"]["answer_guardrails"]["must_read_chunks"] is True
    assert how_to["results"][0]["reading_pack"]["answer_guardrails"]["can_answer_from_summary_only"] is False
    assert how_to["results"][0]["reading_pack"]["answer_handoff"]["answer_mode"] == "chunks_first"
    assert compare["intent"] == "compare"
    assert compare["results"][0]["reading_pack"]["focus"] == "compare_claims"
    assert compare["results"][0]["reading_pack"]["answer_guardrails"]["must_read_claims"] is True
    assert compare["results"][0]["reading_pack"]["answer_guardrails"]["must_read_sources"] is False
    assert compare["results"][0]["reading_pack"]["answer_handoff"]["answer_mode"] == "claims_first"


def test_query_reading_pack_uses_page_type_specific_focus(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "guide.md").write_text(
        "# 导入流程\n\n"
        "首先扫描 raw 目录。\n\n"
        "然后生成 normalized 文档。\n\n"
        "最后写入 chunk 与 claim。\n",
        encoding="utf-8",
    )
    (source_dir / "example.md").write_text(
        "# 示例集合\n\n"
        "例如，Claim 可以承载定义句。\n\n"
        "比如，一个概念页可以引用多个 Claim。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "ReadingPackPageTypeFocus",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    how_to = run_cli("query", "如何生成 normalized 文档", "--target-dir", str(workspace_dir))
    example = run_cli("query", "Claim 的例子有哪些", "--target-dir", str(workspace_dir))

    how_to_result = next(item for item in how_to["results"] if item["type"] == "guide")
    example_result = next(item for item in example["results"] if item["type"] == "example")
    how_to_pack = how_to_result["reading_pack"]
    example_pack = example_result["reading_pack"]
    assert how_to_pack["focus"] == "guide_steps"
    assert how_to_pack["answer_handoff"]["recommended_read_order"][1] == "page_context.summary"
    assert example_pack["focus"] == "worked_examples"
    assert example_pack["answer_handoff"]["recommended_read_order"][1] == "page_context.summary"


def test_query_timeline_sets_timeline_focus_and_sources(tmp_path: Path) -> None:
    # timeline query 应返回时间线 focus，并把命中的 chunk 按来源做一层分组。
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "timeline.md").write_text(
        "# 时间线\n\n"
        "2024 年：系统完成原始资料标准化。\n\n"
        "2025 年：系统补齐 claim 与 review 闭环。\n\n"
        "2026 年：系统增加 query intent 与 alias conflict review。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "TimelineFocusRegression",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    timeline = run_cli("query", "系统的时间线", "--target-dir", str(workspace_dir))

    assert timeline["intent"] == "timeline"
    assert timeline["results"]
    reading_pack = timeline["results"][0]["reading_pack"]
    assert reading_pack["focus"] == "timeline_evidence"
    assert reading_pack["timeline_sources"]
    assert reading_pack["answer_guardrails"]["must_read_sources"] is True
    assert reading_pack["answer_guardrails"]["cite_expectation"] == "strong"
    assert reading_pack["answer_handoff"]["answer_mode"] == "sources_first"
    assert "evidence_context.timeline_sources" in reading_pack["answer_handoff"]["required_evidence_paths"]


def test_query_reading_depth_deep_returns_thicker_reading_pack(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# 知识沉淀流程\n\n"
        "如何生成 wiki 页面：第一步先标准化原始资料。\n\n"
        "第二步再切 chunk，确保来源可追踪。\n\n"
        "第三步继续抽取 claim，沉淀稳定结论。\n\n"
        "第四步最后生成 wiki 页面，并检查阅读入口。\n\n"
        "补充说明：review 流程用于处理冲突与不确定项。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "ReadingDepthRegression",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    standard = run_cli("query", "如何生成 wiki 页面", "--target-dir", str(workspace_dir))
    deep = run_cli("query", "如何生成 wiki 页面", "--target-dir", str(workspace_dir), "--reading-depth", "deep")

    assert standard["reading_depth"] == "standard"
    assert standard["reading_depth_limits"] == {"claim_limit": 3, "chunk_limit": 2}
    assert standard["results"][0]["reading_pack"]["reading_depth"] == "standard"

    assert deep["reading_depth"] == "deep"
    assert deep["reading_depth_limits"] == {"claim_limit": 6, "chunk_limit": 5}
    assert deep["results"][0]["reading_pack"]["reading_depth"] == "deep"
    assert len(deep["results"][0]["reading_pack"]["matched_chunks"]) >= len(standard["results"][0]["reading_pack"]["matched_chunks"])
    assert standard["results"][0]["reading_pack"]["source_trail"] == []
    assert deep["results"][0]["reading_pack"]["source_trail"]
    assert deep["results"][0]["reading_pack"]["source_trail"][0]["source_path"].endswith("topic.md")


def test_query_definition_contract_exposes_page_and_guardrails(tmp_path: Path) -> None:
    workspace_dir = create_workspace_with_two_concepts(tmp_path, "DefinitionContractRegression")

    result = run_cli("query", "什么是 Claim", "--target-dir", str(workspace_dir))

    assert result["contract_version"] == "query_answer_handoff/v1"
    assert result["results"]
    reading_pack = result["results"][0]["reading_pack"]
    assert reading_pack["page_context"]["title"]
    assert reading_pack["query"]["normalized_text"]
    assert reading_pack["retrieval_context"]["matched_fields"]
    assert reading_pack["evidence_context"]["matched_claims"] == reading_pack["matched_claims"]
    assert reading_pack["answer_guardrails"]["can_answer_from_summary_only"] is True
    assert reading_pack["answer_guardrails"]["must_read_sources"] is False
    assert reading_pack["answer_handoff"]["answer_mode"] == "summary_first"
    assert reading_pack["answer_handoff"]["fallback_action"] == "answer_from_summary_and_claims"


def test_query_contract_risk_flags_drive_uncertainty_handoff(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    (source_dir / "topic.md").write_text(
        "# 风险回答\n\n"
        "系统需要保留待审核状态，避免把不稳定结论伪装成确定答案。\n",
        encoding="utf-8",
    )

    workspace_dir = tmp_path / "workspace"
    run_cli(
        "init",
        "--source-dir", str(source_dir),
        "--project-name", "RiskGuardrailRegression",
        "--target-dir", str(workspace_dir),
    )
    run_cli("ingest", "--target-dir", str(workspace_dir))

    pages_path = workspace_dir / "state" / "pages.jsonl"
    page_records = load_jsonl(pages_path)
    for record in page_records:
        if record.get("status") != "removed":
            record["status"] = "needs_review"
    pages_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in page_records),
        encoding="utf-8",
    )
    search_index_path = workspace_dir / "indexes" / "search_pages.jsonl"
    index_records = load_jsonl(search_index_path)
    for record in index_records:
        if record.get("status") != "removed":
            record["status"] = "needs_review"
    search_index_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in index_records),
        encoding="utf-8",
    )

    result = run_cli("query", "系统需要保留什么状态", "--target-dir", str(workspace_dir))

    reading_pack = result["results"][0]["reading_pack"]
    assert "page_needs_review" in reading_pack["answer_guardrails"]["risk_flags"]
    assert reading_pack["answer_handoff"]["should_surface_uncertainty"] is True
    assert reading_pack["answer_handoff"]["fallback_action"] == "answer_with_uncertainty"
