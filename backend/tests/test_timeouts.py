"""Timeout ladder single-source-of-truth: defaults + invariant assertions."""

from __future__ import annotations

import pytest

from app.application import timeouts


def test_defaults_pass_invariants():
    """The shipped defaults must satisfy every invariant."""
    assert timeouts.validate(strict=True) == []
    assert timeouts.check_invariants() == []


def test_default_values_match_shipped_ladder():
    # These are the shipped defaults. subagent_idle was raised 600→1200 so the
    # stall watchdog (900s) can reap a hung subprocess before the conductor
    # gives up and re-dispatches; idle must stay > stall_threshold + 120.
    assert timeouts.lease_ttl_s() == 180
    assert timeouts.recovery_interval_s() == 30
    assert timeouts.conductor_recovery_enabled() is True
    assert timeouts.conductor_max_relaunches() == 3
    assert timeouts.subagent_idle_s() == 1200.0
    assert timeouts.subagent_max_s() == 3600.0
    assert timeouts.codex_turn_timeout_s() == 480
    assert timeouts.codex_idle_timeout_s() == 180
    assert timeouts.codex_app_server_cmd() == "codex app-server"
    assert timeouts.codex_app_server_model() == "gpt-5.4-mini"
    assert timeouts.codex_auto_approve() is True
    assert timeouts.workflow_dag_enabled() is True
    assert timeouts.sqlite_db_path() == "console.db"
    assert timeouts.use_sqlite() is True
    assert timeouts.codex_launch_enabled() is True
    assert timeouts.real_cli_enabled() is True
    assert timeouts.claude_cli_cmd() == "claude"
    assert timeouts.codex_cli_cmd() == "codex"
    assert timeouts.codex_data_dir() == "/tmp"
    assert timeouts.claude_cmd() == "claude -p --output-format=stream-json --verbose"
    assert timeouts.anthropic_api_key_configured() is False
    assert timeouts.process_idle_timeout_s() == 180
    assert timeouts.process_max_timeout_s() == 1800
    assert timeouts.workflow_orchestrator_llm_enabled() is True
    assert timeouts.workflow_orchestrator_executor_id() is None
    assert timeouts.workflow_orchestrator_model() is None
    assert timeouts.workflow_orchestrator_timeout_s() == 28.0
    assert timeouts.workflow_orchestrator_max_tokens() == 8192
    assert timeouts.conductor_llm_executor_id() is None
    assert timeouts.conductor_llm_model() is None
    assert timeouts.conductor_llm_protocol() is None
    assert timeouts.conductor_llm_timeout_s() == 120.0
    assert timeouts.conductor_llm_max_tokens() == 8192
    assert timeouts.embedding_api_endpoint() == ""
    assert timeouts.embedding_api_key() == ""
    assert timeouts.embedding_model() == ""
    assert timeouts.embedding_provider_type() == "openai"
    assert timeouts.embedding_timeout_s() == 20.0
    assert timeouts.embedding_disabled() is False
    assert timeouts.cost_usd_per_m_input() == 0.30
    assert timeouts.cost_usd_per_m_output() == 1.20
    assert timeouts.cost_usd_per_m_cache_read() == 0.075
    assert timeouts.conductor_max_dispatches_per_role() == 4
    assert timeouts.stall_watchdog_enabled() is True
    assert timeouts.stall_threshold_s() == 900
    assert timeouts.stall_interval_s() == 30
    assert timeouts.stall_cooldown_s() == 900
    assert timeouts.project_review_interval_s() == 3600.0
    assert timeouts.project_review_limit() == 25
    assert timeouts.self_improvement_proposal_interval_s() == 3600.0
    assert timeouts.self_improvement_proposal_limit() == 25
    assert timeouts.event_bus_buffer_size() == 1000
    assert timeouts.audit_log_max_queue() == 10000
    assert timeouts.ws_workspace_queue_maxsize() == 256
    assert timeouts.ws_log_queue_maxsize() == 2048
    assert timeouts.ws_message_queue_maxsize() == 512


def test_conductor_max_dispatches_per_role_knob(monkeypatch):
    monkeypatch.setenv("CONDUCTOR_MAX_DISPATCHES_PER_ROLE", "2")
    assert timeouts.conductor_max_dispatches_per_role() == 2

    monkeypatch.setenv("CONDUCTOR_MAX_DISPATCHES_PER_ROLE", "0")
    assert timeouts.conductor_max_dispatches_per_role() == 1

    monkeypatch.setenv("CONDUCTOR_MAX_DISPATCHES_PER_ROLE", "not-an-int")
    assert timeouts.conductor_max_dispatches_per_role() == 4


def test_conductor_max_relaunches_knob(monkeypatch):
    monkeypatch.setenv("CONDUCTOR_MAX_RELAUNCHES", "5")
    assert timeouts.conductor_max_relaunches() == 5

    monkeypatch.setenv("CONDUCTOR_MAX_RELAUNCHES", "-1")
    assert timeouts.conductor_max_relaunches() == 0
    assert not any("CONDUCTOR_MAX_RELAUNCHES" in v for v in timeouts.check_invariants())

    monkeypatch.setenv("CONDUCTOR_MAX_RELAUNCHES", "not-an-int")
    assert timeouts.conductor_max_relaunches() == 3


def test_conductor_recovery_enabled_knob(monkeypatch):
    monkeypatch.setenv("CONDUCTOR_RECOVERY_ENABLED", "off")
    assert timeouts.conductor_recovery_enabled() is False

    monkeypatch.setenv("CONDUCTOR_RECOVERY_ENABLED", "on")
    assert timeouts.conductor_recovery_enabled() is True

    monkeypatch.setenv("CONDUCTOR_RECOVERY_ENABLED", "typo")
    assert timeouts.conductor_recovery_enabled() is True


def test_stall_watchdog_enabled_knob(monkeypatch):
    monkeypatch.setenv("CODEX_STALL_WATCHDOG", "false")
    assert timeouts.stall_watchdog_enabled() is False

    monkeypatch.setenv("CODEX_STALL_WATCHDOG", "true")
    assert timeouts.stall_watchdog_enabled() is True

    monkeypatch.setenv("CODEX_STALL_WATCHDOG", "not-a-bool")
    assert timeouts.stall_watchdog_enabled() is True


def test_process_runtime_timeout_knobs(monkeypatch):
    monkeypatch.setenv("PROCESS_IDLE_TIMEOUT", "42")
    monkeypatch.setenv("PROCESS_MAX_TIMEOUT", "900")
    assert timeouts.process_idle_timeout_s() == 42
    assert timeouts.process_max_timeout_s() == 900

    monkeypatch.setenv("PROCESS_IDLE_TIMEOUT", "garbage")
    monkeypatch.setenv("PROCESS_MAX_TIMEOUT", "garbage")
    assert timeouts.process_idle_timeout_s() == timeouts.DEFAULT_PROCESS_IDLE_TIMEOUT_S
    assert timeouts.process_max_timeout_s() == timeouts.DEFAULT_PROCESS_MAX_TIMEOUT_S


def test_codex_app_server_knobs(monkeypatch):
    monkeypatch.setenv("CODEX_APP_SERVER_CMD", " codex app-server --experimental ")
    monkeypatch.setenv("CODEX_APP_SERVER_MODEL", " gpt-x ")
    monkeypatch.setenv("CODEX_AUTO_APPROVE", "false")

    assert timeouts.codex_app_server_cmd() == "codex app-server --experimental"
    assert timeouts.codex_app_server_model() == "gpt-x"
    assert timeouts.codex_auto_approve() is False

    monkeypatch.setenv("CODEX_APP_SERVER_CMD", " ")
    monkeypatch.setenv("CODEX_APP_SERVER_MODEL", "")
    monkeypatch.setenv("CODEX_AUTO_APPROVE", "not-a-bool")

    assert timeouts.codex_app_server_cmd() == timeouts.DEFAULT_CODEX_APP_SERVER_CMD
    assert timeouts.codex_app_server_model() == timeouts.DEFAULT_CODEX_APP_SERVER_MODEL
    assert timeouts.codex_auto_approve() is True


def test_claude_cmd_knob(monkeypatch):
    monkeypatch.setenv("CLAUDE_CMD", " claude --print ")
    assert timeouts.claude_cmd() == "claude --print"

    monkeypatch.setenv("CLAUDE_CMD", " ")
    assert timeouts.claude_cmd() == timeouts.DEFAULT_CLAUDE_CMD


def test_bootstrap_knobs(monkeypatch):
    monkeypatch.setenv("WORKFLOW_DAG_ENABLED", "false")
    monkeypatch.setenv("SQLITE_DB_PATH", " custom.db ")
    monkeypatch.setenv("USE_SQLITE", "false")
    monkeypatch.setenv("CODEX_LAUNCH_ENABLED", "false")
    monkeypatch.setenv("REAL_CLI", "false")
    monkeypatch.setenv("CLAUDE_CMD", " claude --fast ")
    monkeypatch.setenv("CODEX_CMD", " codex --fast ")
    monkeypatch.setenv("CODEX_DATA_DIR", " /tmp/codex-data ")

    assert timeouts.workflow_dag_enabled() is False
    assert timeouts.sqlite_db_path() == "custom.db"
    assert timeouts.use_sqlite() is False
    assert timeouts.codex_launch_enabled() is False
    assert timeouts.real_cli_enabled() is False
    assert timeouts.claude_cli_cmd() == "claude --fast"
    assert timeouts.codex_cli_cmd() == "codex --fast"
    assert timeouts.codex_data_dir() == "/tmp/codex-data"

    monkeypatch.setenv("WORKFLOW_DAG_ENABLED", "not-a-bool")
    monkeypatch.setenv("SQLITE_DB_PATH", " ")
    monkeypatch.setenv("USE_SQLITE", "not-a-bool")
    monkeypatch.setenv("CODEX_LAUNCH_ENABLED", "not-a-bool")
    monkeypatch.setenv("REAL_CLI", "not-a-bool")
    monkeypatch.setenv("CLAUDE_CMD", " ")
    monkeypatch.setenv("CODEX_CMD", "")
    monkeypatch.setenv("CODEX_DATA_DIR", " ")

    assert timeouts.workflow_dag_enabled() is True
    assert timeouts.sqlite_db_path() == timeouts.DEFAULT_SQLITE_DB_PATH
    assert timeouts.use_sqlite() is True
    assert timeouts.codex_launch_enabled() is True
    assert timeouts.real_cli_enabled() is True
    assert timeouts.claude_cli_cmd() == timeouts.DEFAULT_CLAUDE_CLI_CMD
    assert timeouts.codex_cli_cmd() == timeouts.DEFAULT_CODEX_CLI_CMD
    assert timeouts.codex_data_dir() == timeouts.DEFAULT_CODEX_DATA_DIR


def test_anthropic_api_key_configured(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", " sk-test ")
    assert timeouts.anthropic_api_key_configured() is True

    monkeypatch.setenv("ANTHROPIC_API_KEY", " ")
    assert timeouts.anthropic_api_key_configured() is False


def test_workflow_orchestrator_llm_knobs(monkeypatch):
    monkeypatch.setenv("WORKFLOW_ORCHESTRATOR_LLM", "false")
    monkeypatch.setenv("WORKFLOW_ORCHESTRATOR_EXECUTOR_ID", " exec-a ")
    monkeypatch.setenv("WORKFLOW_ORCHESTRATOR_MODEL", " model-a ")
    monkeypatch.setenv("WORKFLOW_ORCHESTRATOR_TIMEOUT", "14.5")
    monkeypatch.setenv("WORKFLOW_ORCHESTRATOR_MAX_TOKENS", "1234")

    assert timeouts.workflow_orchestrator_llm_enabled() is False
    assert timeouts.workflow_orchestrator_executor_id() == "exec-a"
    assert timeouts.workflow_orchestrator_model() == "model-a"
    assert timeouts.workflow_orchestrator_timeout_s() == 14.5
    assert timeouts.workflow_orchestrator_max_tokens() == 1234

    monkeypatch.setenv("WORKFLOW_ORCHESTRATOR_LLM", "not-a-bool")
    monkeypatch.setenv("WORKFLOW_ORCHESTRATOR_EXECUTOR_ID", " ")
    monkeypatch.setenv("WORKFLOW_ORCHESTRATOR_MODEL", "")
    monkeypatch.setenv("WORKFLOW_ORCHESTRATOR_TIMEOUT", "garbage")
    monkeypatch.setenv("WORKFLOW_ORCHESTRATOR_MAX_TOKENS", "garbage")

    assert timeouts.workflow_orchestrator_llm_enabled() is True
    assert timeouts.workflow_orchestrator_executor_id() is None
    assert timeouts.workflow_orchestrator_model() is None
    assert (
        timeouts.workflow_orchestrator_timeout_s()
        == timeouts.DEFAULT_WORKFLOW_ORCHESTRATOR_TIMEOUT_S
    )
    assert (
        timeouts.workflow_orchestrator_max_tokens()
        == timeouts.DEFAULT_WORKFLOW_ORCHESTRATOR_MAX_TOKENS
    )


def test_conductor_llm_knobs(monkeypatch):
    monkeypatch.setenv("CONDUCTOR_LLM_EXECUTOR_ID", " exec-c ")
    monkeypatch.setenv("CONDUCTOR_LLM_MODEL", " model-c ")
    monkeypatch.setenv("CONDUCTOR_LLM_PROTOCOL", " OpenAI ")
    monkeypatch.setenv("CONDUCTOR_LLM_TIMEOUT", "99.5")
    monkeypatch.setenv("CONDUCTOR_LLM_MAX_TOKENS", "4567")

    assert timeouts.conductor_llm_executor_id() == "exec-c"
    assert timeouts.conductor_llm_model() == "model-c"
    assert timeouts.conductor_llm_protocol() == "openai"
    assert timeouts.conductor_llm_timeout_s() == 99.5
    assert timeouts.conductor_llm_max_tokens() == 4567

    monkeypatch.setenv("CONDUCTOR_LLM_EXECUTOR_ID", " ")
    monkeypatch.setenv("CONDUCTOR_LLM_MODEL", "")
    monkeypatch.setenv("CONDUCTOR_LLM_PROTOCOL", " ")
    monkeypatch.setenv("CONDUCTOR_LLM_TIMEOUT", "garbage")
    monkeypatch.setenv("CONDUCTOR_LLM_MAX_TOKENS", "garbage")

    assert timeouts.conductor_llm_executor_id() is None
    assert timeouts.conductor_llm_model() is None
    assert timeouts.conductor_llm_protocol() is None
    assert timeouts.conductor_llm_timeout_s(55.0) == 55.0
    assert timeouts.conductor_llm_max_tokens(3210) == 3210


def test_embedding_knobs(monkeypatch):
    monkeypatch.setenv("EMBEDDING_API_ENDPOINT", " https://emb.example/v1 ")
    monkeypatch.setenv("EMBEDDING_API_KEY", " key-1 ")
    monkeypatch.setenv("EMBEDDING_MODEL", " text-embedding-3-small ")
    monkeypatch.setenv("EMBEDDING_PROVIDER_TYPE", " voyage ")
    monkeypatch.setenv("EMBEDDING_TIMEOUT_S", "12.5")
    monkeypatch.setenv("EMBEDDING_DISABLED", "true")

    assert timeouts.embedding_api_endpoint() == "https://emb.example/v1"
    assert timeouts.embedding_api_key() == "key-1"
    assert timeouts.embedding_model() == "text-embedding-3-small"
    assert timeouts.embedding_provider_type() == "voyage"
    assert timeouts.embedding_timeout_s() == 12.5
    assert timeouts.embedding_disabled() is True

    monkeypatch.setenv("EMBEDDING_API_ENDPOINT", "")
    monkeypatch.setenv("EMBEDDING_API_KEY", " ")
    monkeypatch.setenv("EMBEDDING_MODEL", "")
    monkeypatch.setenv("EMBEDDING_PROVIDER_TYPE", " ")
    monkeypatch.setenv("EMBEDDING_TIMEOUT_S", "garbage")
    monkeypatch.setenv("EMBEDDING_DISABLED", "not-a-bool")

    assert timeouts.embedding_api_endpoint() == ""
    assert timeouts.embedding_api_key() == ""
    assert timeouts.embedding_model() == ""
    assert timeouts.embedding_provider_type() == timeouts.DEFAULT_EMBEDDING_PROVIDER_TYPE
    assert timeouts.embedding_timeout_s() == timeouts.DEFAULT_EMBEDDING_TIMEOUT_S
    assert timeouts.embedding_disabled() is False


def test_cost_rate_knobs(monkeypatch):
    monkeypatch.setenv("COST_USD_PER_M_INPUT", "2.5")
    monkeypatch.setenv("COST_USD_PER_M_OUTPUT", "7.5")
    monkeypatch.setenv("COST_USD_PER_M_CACHE_READ", "0.25")

    assert timeouts.cost_usd_per_m_input() == 2.5
    assert timeouts.cost_usd_per_m_output() == 7.5
    assert timeouts.cost_usd_per_m_cache_read() == 0.25

    monkeypatch.setenv("COST_USD_PER_M_INPUT", "garbage")
    monkeypatch.setenv("COST_USD_PER_M_OUTPUT", "garbage")
    monkeypatch.setenv("COST_USD_PER_M_CACHE_READ", "garbage")

    assert timeouts.cost_usd_per_m_input() == timeouts.DEFAULT_COST_USD_PER_M_INPUT
    assert timeouts.cost_usd_per_m_output() == timeouts.DEFAULT_COST_USD_PER_M_OUTPUT
    assert timeouts.cost_usd_per_m_cache_read() == timeouts.DEFAULT_COST_USD_PER_M_CACHE_READ


def test_observability_queue_knobs(monkeypatch):
    monkeypatch.setenv("EVENT_BUS_BUFFER_SIZE", "7")
    monkeypatch.setenv("AUDIT_LOG_MAX_QUEUE", "11")

    assert timeouts.event_bus_buffer_size() == 7
    assert timeouts.audit_log_max_queue() == 11

    monkeypatch.setenv("EVENT_BUS_BUFFER_SIZE", "0")
    monkeypatch.setenv("AUDIT_LOG_MAX_QUEUE", "0")

    assert timeouts.event_bus_buffer_size() == 1
    assert timeouts.audit_log_max_queue() == 1

    monkeypatch.setenv("EVENT_BUS_BUFFER_SIZE", "garbage")
    monkeypatch.setenv("AUDIT_LOG_MAX_QUEUE", "garbage")

    assert timeouts.event_bus_buffer_size() == timeouts.DEFAULT_EVENT_BUS_BUFFER_SIZE
    assert timeouts.audit_log_max_queue() == timeouts.DEFAULT_AUDIT_LOG_MAX_QUEUE


def test_ws_queue_knobs(monkeypatch):
    monkeypatch.setenv("WS_WORKSPACE_QUEUE_MAXSIZE", "3")
    monkeypatch.setenv("WS_LOG_QUEUE_MAXSIZE", "4")
    monkeypatch.setenv("WS_MESSAGE_QUEUE_MAXSIZE", "5")

    assert timeouts.ws_workspace_queue_maxsize() == 3
    assert timeouts.ws_log_queue_maxsize() == 4
    assert timeouts.ws_message_queue_maxsize() == 5

    monkeypatch.setenv("WS_WORKSPACE_QUEUE_MAXSIZE", "0")
    monkeypatch.setenv("WS_LOG_QUEUE_MAXSIZE", "0")
    monkeypatch.setenv("WS_MESSAGE_QUEUE_MAXSIZE", "0")

    assert timeouts.ws_workspace_queue_maxsize() == 1
    assert timeouts.ws_log_queue_maxsize() == 1
    assert timeouts.ws_message_queue_maxsize() == 1

    monkeypatch.setenv("WS_WORKSPACE_QUEUE_MAXSIZE", "garbage")
    monkeypatch.setenv("WS_LOG_QUEUE_MAXSIZE", "garbage")
    monkeypatch.setenv("WS_MESSAGE_QUEUE_MAXSIZE", "garbage")

    assert timeouts.ws_workspace_queue_maxsize() == timeouts.DEFAULT_WS_WORKSPACE_QUEUE_MAXSIZE
    assert timeouts.ws_log_queue_maxsize() == timeouts.DEFAULT_WS_LOG_QUEUE_MAXSIZE
    assert timeouts.ws_message_queue_maxsize() == timeouts.DEFAULT_WS_MESSAGE_QUEUE_MAXSIZE


def test_project_review_scheduler_knobs(monkeypatch):
    monkeypatch.setenv("PROJECT_REVIEW_INTERVAL_S", "120.5")
    monkeypatch.setenv("PROJECT_REVIEW_LIMIT", "7")
    assert timeouts.project_review_interval_s() == 120.5
    assert timeouts.project_review_limit() == 7

    monkeypatch.setenv("PROJECT_REVIEW_INTERVAL_S", "0")
    monkeypatch.setenv("PROJECT_REVIEW_LIMIT", "0")
    assert timeouts.project_review_interval_s() == timeouts.DEFAULT_PROJECT_REVIEW_INTERVAL_S
    assert timeouts.project_review_limit() == 1


def test_self_improvement_proposal_scheduler_knobs(monkeypatch):
    monkeypatch.setenv("SELF_IMPROVEMENT_PROPOSAL_INTERVAL_S", "222.5")
    monkeypatch.setenv("SELF_IMPROVEMENT_PROPOSAL_LIMIT", "9")
    assert timeouts.self_improvement_proposal_interval_s() == 222.5
    assert timeouts.self_improvement_proposal_limit() == 9

    monkeypatch.setenv("SELF_IMPROVEMENT_PROPOSAL_INTERVAL_S", "0")
    monkeypatch.setenv("SELF_IMPROVEMENT_PROPOSAL_LIMIT", "0")
    assert (
        timeouts.self_improvement_proposal_interval_s()
        == timeouts.DEFAULT_SELF_IMPROVEMENT_PROPOSAL_INTERVAL_S
    )
    assert timeouts.self_improvement_proposal_limit() == 1


def test_lease_pulse_interval_formula(monkeypatch):
    # Default: max(15, 180 // 3) == 60
    assert timeouts.lease_pulse_interval_s() == 60
    # Small TTL clamps to the 15s floor: max(15, 30 // 3) == 15
    monkeypatch.setenv("CONDUCTOR_LEASE_TTL_S", "30")
    assert timeouts.lease_pulse_interval_s() == 15


def test_lease_ttl_must_be_under_subagent_idle(monkeypatch):
    # A lease TTL >= subagent idle is the classic orphan-relaunch trap.
    # (idle default is 1200, so use a TTL above it to trip the invariant.)
    monkeypatch.setenv("CONDUCTOR_LEASE_TTL_S", "1300")
    violations = timeouts.check_invariants()
    assert any("CONDUCTOR_LEASE_TTL_S" in v for v in violations)
    with pytest.raises(timeouts.TimeoutConfigError):
        timeouts.validate(strict=True)


def test_lease_pulse_must_be_under_ttl(monkeypatch):
    # pulse < ttl < idle is the lease ladder. The pulse floor is 15s, so a TTL at
    # or below the floor makes the heartbeat fire no sooner than the lease
    # expires — the orphan-relaunch trap this invariant guards against.
    monkeypatch.setenv("CONDUCTOR_LEASE_TTL_S", "10")  # pulse=max(15,3)=15 >= ttl=10
    assert timeouts.lease_pulse_interval_s() >= timeouts.lease_ttl_s()
    violations = timeouts.check_invariants()
    assert any("lease pulse interval" in v and "CONDUCTOR_LEASE_TTL_S" in v for v in violations)


def test_subagent_idle_must_exceed_stall_threshold(monkeypatch):
    # The stall watchdog must get a chance to terminate a hung subprocess
    # before the conductor's idle timeout re-dispatches.
    monkeypatch.setenv("CONDUCTOR_SUBAGENT_IDLE_S", "600")  # < stall(900)+120
    violations = timeouts.check_invariants()
    assert any("CODEX_STALL_THRESHOLD_S" in v for v in violations)


def test_codex_idle_must_not_exceed_turn_budget(monkeypatch):
    monkeypatch.setenv("CODEX_IDLE_TIMEOUT_S", "9999")
    violations = timeouts.check_invariants()
    assert any("CODEX_IDLE_TIMEOUT_S" in v for v in violations)


def test_subagent_idle_must_not_exceed_hard_ceiling(monkeypatch):
    monkeypatch.setenv("CONDUCTOR_SUBAGENT_IDLE_S", "99999")
    violations = timeouts.check_invariants()
    assert any("CONDUCTOR_SUBAGENT_IDLE_S" in v for v in violations)


def test_non_positive_cadence_rejected(monkeypatch):
    monkeypatch.setenv("CODEX_STALL_INTERVAL_S", "0")
    violations = timeouts.check_invariants()
    assert any("CODEX_STALL_INTERVAL_S" in v for v in violations)


def test_invalid_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("CONDUCTOR_LEASE_TTL_S", "not-a-number")
    assert timeouts.lease_ttl_s() == 180
    monkeypatch.setenv("CONDUCTOR_SUBAGENT_IDLE_S", "garbage")
    assert timeouts.subagent_idle_s() == 1200.0
    monkeypatch.setenv("PROJECT_REVIEW_INTERVAL_S", "garbage")
    assert timeouts.project_review_interval_s() == timeouts.DEFAULT_PROJECT_REVIEW_INTERVAL_S
    monkeypatch.setenv("SELF_IMPROVEMENT_PROPOSAL_INTERVAL_S", "garbage")
    assert timeouts.self_improvement_proposal_interval_s() == (
        timeouts.DEFAULT_SELF_IMPROVEMENT_PROPOSAL_INTERVAL_S
    )


def test_validate_non_strict_returns_without_raising(monkeypatch):
    monkeypatch.setenv("CONDUCTOR_LEASE_TTL_S", "1300")  # >= idle(1200) → violation
    # Non-strict must not raise even when invariants are violated.
    violations = timeouts.validate(strict=False)
    assert violations  # non-empty
