"""One-shot helper: replace os.getenv(...) calls in feature code with
timeouts.py accessors.

Used by the Phase 2b refactor. Re-runnable: it does a string-level
substitution keyed off the env-var name (the only piece of the call
that maps 1:1 to a timeouts accessor).
"""
import re
import sys
from pathlib import Path

REPO = Path("/Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console")

# (env var name) -> (timeouts accessor, default-shape)
# default-shape: 'bool' / 'int' / 'float' / 'str' / 'str-or-none' / 'int-or-none' / 'float-or-none'
ACCESSOR_MAP = {
    "REAL_CLI": ("real_cli_enabled", "bool"),
    "CODEX_LAUNCH_ENABLED": ("codex_launch_enabled", "bool"),
    "USE_SQLITE": ("use_sqlite", "bool"),
    "SQLITE_DB_PATH": ("sqlite_db_path", "str"),
    "CODEX_WORKSPACE_ROOT": ("codex_workspace_root", "str-or-none"),
    "CODEX_DATA_DIR": ("codex_data_dir", "str"),
    "CODEX_CMD": ("codex_cmd", "str"),
    "CLAUDE_CMD": ("claude_cmd", "str"),
    "CODEX_APP_SERVER_CMD": ("codex_app_server_cmd", "str-or-none"),
    "CODEX_APP_SERVER_MODEL": ("codex_app_server_model", "str-or-none"),
    "CODEX_AUTO_APPROVE": ("codex_auto_approve", "bool"),
    "WORKFLOW_DAG_ENABLED": ("workflow_dag_enabled", "bool"),
    "WORKFLOW_ORCHESTRATOR_EXECUTOR_ID": ("workflow_orchestrator_executor_id", "str-or-none"),
    "WORKFLOW_ORCHESTRATOR_MODEL": ("workflow_orchestrator_model", "str-or-none"),
    "WORKFLOW_ORCHESTRATOR_MAX_TOKENS": ("workflow_orchestrator_max_tokens", "int-or-none"),
    "WORKFLOW_ORCHESTRATOR_TIMEOUT": ("workflow_orchestrator_timeout", "float-or-none"),
    "COST_USD_PER_M_INPUT": ("cost_usd_per_m_input", "float"),
    "COST_USD_PER_M_OUTPUT": ("cost_usd_per_m_output", "float"),
    "COST_USD_PER_M_CACHE_READ": ("cost_usd_per_m_cache_read", "float"),
    "OPENAI_API_KEY": ("openai_api_key", "str-or-none"),
    "OPENAI_BASE_URL": ("openai_base_url", "str-or-none"),
    "ANTHROPIC_API_KEY": ("anthropic_api_key", "str-or-none"),
    "ANTHROPIC_BASE_URL": ("anthropic_base_url", "str-or-none"),
    "CONDUCTOR_MAX_DISPATCHES_PER_ROLE": ("conductor_max_dispatches_per_role", "int"),
    "CONDUCTOR_MAX_RELAUNCHES": ("conductor_max_relaunches", "int"),
    "CONDUCTOR_RECOVERY_ENABLED": ("conductor_recovery_enabled", "bool"),
    "CONDUCTOR_LLM_EXECUTOR_ID": ("conductor_llm_executor_id", "str-or-none"),
    "CONDUCTOR_LLM_MODEL": ("conductor_llm_model", "str-or-none"),
    "CONDUCTOR_LLM_PROTOCOL": ("conductor_llm_protocol", "str-or-none"),
    "CONDUCTOR_LLM_MAX_TOKENS": ("conductor_llm_max_tokens", "int-or-none"),
    "CONDUCTOR_LLM_TIMEOUT": ("conductor_llm_timeout", "float-or-none"),
    "EMBEDDING_PROVIDER_TYPE": ("embedding_provider_type", "str-or-none"),
    "EMBEDDING_MODEL": ("embedding_model", "str-or-none"),
    "EMBEDDING_API_ENDPOINT": ("embedding_api_endpoint", "str-or-none"),
    "EMBEDDING_API_KEY": ("embedding_api_key", "str-or-none"),
    "EMBEDDING_DISABLED": ("embedding_disabled", "bool"),
    "EMBEDDING_TIMEOUT_S": ("embedding_timeout_s", "float"),
    "EVENT_BUS_BUFFER_SIZE": ("event_bus_buffer_size", "int"),
    "PROCESS_IDLE_TIMEOUT": ("process_idle_timeout", "float"),
    "PROCESS_MAX_TIMEOUT": ("process_max_timeout", "float"),
    "QA_EXECUTE_COMMANDS": ("qa_execute_commands", "bool"),
    "QA_COMMAND_TIMEOUT_S": ("qa_command_timeout_s", "float"),
    "QA_TOTAL_BUDGET_S": ("qa_total_budget_s", "float"),
    "AUDIT_LOG_MAX_QUEUE": ("audit_log_max_queue", "int"),
}


def looks_like_env_name(name: str) -> bool:
    return name in ACCESSOR_MAP


def main():
    if len(sys.argv) < 2:
        print("usage: swap_os_getenv.py <file> [<file>...]")
        sys.exit(2)
    for arg in sys.argv[1:]:
        path = Path(arg)
        src = path.read_text()
        new = src
        # Pattern: os.getenv("NAME", <default>)
        # We rewrite any os.getenv("NAME", ...) and os.getenv("NAME") where
        # NAME is in the map. Wrapping defaults is left in place (e.g.
        # `int(os.getenv("X", "120"))` -> `int(timeouts.x())`).
        for env, (acc, shape) in ACCESSOR_MAP.items():
            new = re.sub(
                rf'os\.getenv\(\s*"{env}"\s*\)',
                f"timeouts.{acc}()",
                new,
            )
            new = re.sub(
                rf'os\.getenv\(\s*"{env}"\s*,\s*[^)]+\)',
                f"timeouts.{acc}()",
                new,
            )
        if new != src:
            # Ensure `from app.application import timeouts` is present.
            if "from app.application import timeouts" not in new and "import timeouts" not in new:
                # Find the last `from app...` import; insert after.
                m = list(re.finditer(r"^from app\.\S+ import .+$", new, re.MULTILINE))
                if m:
                    last = m[-1]
                    insert_at = last.end()
                    new = new[:insert_at] + "\nfrom app.application import timeouts" + new[insert_at:]
                else:
                    # No `from app...` import; insert after the first `from app.X` block.
                    m2 = re.search(r"^(import \S+\n)+", new, re.MULTILINE)
                    if m2:
                        new = new[: m2.end()] + "from app.application import timeouts\n" + new[m2.end():]
                    else:
                        new = "from app.application import timeouts\n" + new
            path.write_text(new)
            print(f"updated {path}")


if __name__ == "__main__":
    main()
