"""Runtime catalog service for managing executor/provider/model configurations."""

from __future__ import annotations

import re
from collections.abc import Awaitable
from typing import Protocol

from app.application import timeouts
from app.domain.models import (
    RuntimeCatalog,
    RuntimeExecutorConfig,
    RuntimeModelConfig,
    RuntimeProviderConfig,
)


class RuntimeCatalogStore(Protocol):
    def load_runtime_catalog(self) -> Awaitable[RuntimeCatalog | None]: ...

    def save_runtime_catalog(self, catalog: RuntimeCatalog) -> Awaitable[None]: ...


class RuntimeCatalogValidationError(ValueError):
    """Raised when runtime catalog validation fails."""

    pass


class RuntimeCatalogService:
    """Service for managing the global runtime catalog.

    Responsibilities:
    - Load the catalog from storage
    - Validate uniqueness and cross-references
    - Normalize defaults
    - Resolve effective run configuration
    - Render restricted templates for command args and environment overrides
    """

    # Supported template placeholders
    TEMPLATE_PLACEHOLDERS = {"{model}", "{provider}", "{workspace_cwd}", "{task_id}"}
    ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    def __init__(self, store: RuntimeCatalogStore) -> None:
        """Initialize with a store that has load_runtime_catalog and save_runtime_catalog."""
        self._store = store

    async def load_catalog(self) -> RuntimeCatalog:
        """Load the runtime catalog from storage.

        Returns a default catalog if none exists.
        """
        catalog: RuntimeCatalog | None = await self._store.load_runtime_catalog()
        if catalog is None:
            catalog = self._create_default_catalog()
            await self._store.save_runtime_catalog(catalog)
        return catalog

    async def save_catalog(self, catalog: RuntimeCatalog) -> RuntimeCatalog:
        """Validate and save the runtime catalog.

        Raises RuntimeCatalogValidationError if validation fails.
        """
        self.validate_catalog(catalog)
        await self._store.save_runtime_catalog(catalog)
        return catalog

    def validate_catalog(self, catalog: RuntimeCatalog) -> None:
        """Validate the runtime catalog.

        Raises RuntimeCatalogValidationError if validation fails.
        """
        executor_ids = set()
        for executor in catalog.executors:
            # Check duplicate executor IDs
            if executor.id in executor_ids:
                raise RuntimeCatalogValidationError(f"Duplicate executor ID: {executor.id}")
            executor_ids.add(executor.id)

            if executor.executor_type == "acp":
                self._validate_acp_executor(executor)
            elif executor.acp is not None:
                raise RuntimeCatalogValidationError(
                    f"Non-ACP executor '{executor.id}' cannot define ACP launch configuration"
                )

            # Check duplicate provider IDs within executor
            provider_ids = set()
            for provider in executor.providers:
                if provider.id in provider_ids:
                    raise RuntimeCatalogValidationError(
                        f"Duplicate provider ID '{provider.id}' in executor '{executor.id}'"
                    )
                provider_ids.add(provider.id)

                # Check duplicate model IDs within provider
                model_ids = set()
                for model in provider.models:
                    if model.id in model_ids:
                        raise RuntimeCatalogValidationError(
                            f"Duplicate model ID '{model.id}' in provider '{provider.id}'"
                        )
                    model_ids.add(model.id)

                # Validate default_model_id references an existing model
                if provider.default_model_id:  # noqa: SIM102
                    if provider.default_model_id not in model_ids:
                        raise RuntimeCatalogValidationError(
                            f"Provider '{provider.id}' has invalid default_model_id '{provider.default_model_id}'"
                        )

            # Validate default_provider_id references an existing provider
            if executor.default_provider_id and executor.default_provider_id != "None":  # noqa: SIM102
                if executor.default_provider_id not in provider_ids:
                    raise RuntimeCatalogValidationError(
                        f"Executor '{executor.id}' has invalid default_provider_id '{executor.default_provider_id}'"
                    )

        # Validate defaults point to enabled items
        for executor in catalog.executors:
            default_provider_id = executor.default_provider_id
            if default_provider_id and default_provider_id != "None":
                default_provider = self._find_provider(catalog, executor.id, default_provider_id)
                if default_provider and not default_provider.enabled:
                    raise RuntimeCatalogValidationError(
                        f"Executor '{executor.id}' defaults to disabled provider '{default_provider_id}'"
                    )
                default_model_id = default_provider.default_model_id if default_provider else None
                if default_model_id and default_model_id != "None":
                    default_model = self._find_model(
                        catalog,
                        executor.id,
                        default_provider_id,
                        default_model_id,
                    )
                    if default_model and not default_model.enabled:
                        raise RuntimeCatalogValidationError(
                            f"Provider '{default_provider_id}' defaults to disabled model '{default_model_id}'"
                        )

        conductor_executor_id = catalog.conductor_llm.executor_id
        if conductor_executor_id:
            conductor_executor = self._find_executor(catalog, conductor_executor_id)
            if conductor_executor is None:
                raise RuntimeCatalogValidationError(
                    f"Conductor references unknown executor '{conductor_executor_id}'"
                )
            if conductor_executor.executor_type == "acp":
                raise RuntimeCatalogValidationError(
                    "ACP executors cannot be used as the Conductor LLM"
                )

    def _validate_acp_executor(self, executor: RuntimeExecutorConfig) -> None:
        config = executor.acp
        if config is None:
            raise RuntimeCatalogValidationError(
                f"ACP executor '{executor.id}' requires ACP launch configuration"
            )
        if not config.command.strip():
            raise RuntimeCatalogValidationError(
                f"ACP executor '{executor.id}' requires a non-empty command"
            )
        if "\x00" in config.command:
            raise RuntimeCatalogValidationError(
                f"ACP executor '{executor.id}' command contains a NUL byte"
            )
        if any("\x00" in arg for arg in config.args):
            raise RuntimeCatalogValidationError(
                f"ACP executor '{executor.id}' arguments cannot contain NUL bytes"
            )
        if executor.providers or executor.default_provider_id:
            raise RuntimeCatalogValidationError(
                f"ACP executor '{executor.id}' cannot define providers"
            )
        if executor.api_endpoint or executor.api_key:
            raise RuntimeCatalogValidationError(
                f"ACP executor '{executor.id}' cannot define HTTP credentials"
            )
        seen_env_names: set[str] = set()
        for name in config.env_allowlist:
            if not self.ENV_NAME_RE.fullmatch(name):
                raise RuntimeCatalogValidationError(
                    f"ACP executor '{executor.id}' has invalid environment name '{name}'"
                )
            if name in seen_env_names:
                raise RuntimeCatalogValidationError(
                    f"ACP executor '{executor.id}' repeats environment name '{name}'"
                )
            seen_env_names.add(name)
        if config.model_config_id is not None and not config.model_config_id.strip():
            raise RuntimeCatalogValidationError(
                f"ACP executor '{executor.id}' model_config_id cannot be blank"
            )

    def resolve_effective_config(
        self,
        catalog: RuntimeCatalog,
        executor: str,
        provider: str | None = None,
        model: str | None = None,
    ) -> tuple[str, str, str, dict[str, str] | None, str]:
        """Resolve effective executor/provider/model configuration.

        Resolution order:
        1. Explicit run override (provider, model)
        2. Task default (provider, model)
        3. Executor default (provider, model)

        Returns (resolved_executor, resolved_provider, resolved_model, env_overrides, executor_type).

        Raises RuntimeCatalogValidationError if configuration is invalid.
        """
        # Validate executor exists and is enabled. If the requested executor
        # is missing or disabled but the catalog has *some* enabled executor,
        # fall back to it. This lets DAG-spawned tasks that inherit legacy
        # `agent.default_executor = "codex"` still run on a catalog that only
        # has e.g. a `claude`-type minimax executor configured.
        executor_config = self._find_executor(catalog, executor)
        if executor_config is None or not executor_config.enabled:
            fallback = next((e for e in catalog.executors if e.enabled), None)
            if fallback is None:
                if executor_config is None:
                    raise RuntimeCatalogValidationError(f"Unknown executor: {executor}")
                raise RuntimeCatalogValidationError(f"Executor '{executor}' is disabled")
            import logging

            logging.getLogger(__name__).info(
                "Runtime catalog: requested executor %r not available; falling back to %r",
                executor,
                fallback.id,
            )
            executor_config = fallback
            executor = fallback.id
            # Reset provider/model so they're re-resolved against the fallback.
            provider = None
            model = None

        if executor_config.executor_type == "acp":
            if provider not in (None, "", "None"):
                raise RuntimeCatalogValidationError(
                    f"ACP executor '{executor}' does not support providers"
                )
            if model in ("", "None"):
                model = None
            resolved_model = model or executor_config.default_model or ""
            return (executor, "", resolved_model, None, "acp")

        # Resolve provider
        if provider == "None" or provider == "":
            provider = None

        if provider is None:
            provider = executor_config.default_provider_id

        provider_config = None
        if provider is not None:
            provider_config = self._find_provider(catalog, executor, provider)
            if provider_config is None:
                raise RuntimeCatalogValidationError(
                    f"Provider '{provider}' not found in executor '{executor}'"
                )
            if not provider_config.enabled:
                raise RuntimeCatalogValidationError(f"Provider '{provider}' is disabled")

        # Resolve model
        if model == "None" or model == "":
            model = None

        if model is None:
            model = executor_config.default_model or (
                provider_config.default_model_id if provider_config else None
            )
        if model is None:
            raise RuntimeCatalogValidationError(
                f"No model specified and no default for executor '{executor}'"
            )

        if provider_config is not None and not executor_config.api_endpoint:
            # Skip model whitelist check when a custom api_endpoint is configured —
            # the model list is for the UI picker only, not a hard gate for compatible APIs.
            if provider is None:
                raise RuntimeCatalogValidationError(
                    f"No provider specified for executor '{executor}'"
                )
            model_config = self._find_model(catalog, executor, provider, model)
            if model_config is None:
                raise RuntimeCatalogValidationError(
                    f"Model '{model}' not found in provider '{provider}'"
                )
            if not model_config.enabled:
                raise RuntimeCatalogValidationError(f"Model '{model}' is disabled")

        # Get env overrides from executor config
        env_overrides = self._get_executor_env_overrides(executor_config)

        return (executor, provider or "", model or "", env_overrides, executor_config.executor_type)

    def render_template(self, template: str, context: dict[str, str]) -> str:
        """Render a template string with restricted placeholders.

        Only supports: {model}, {provider}, {workspace_cwd}, {task_id}

        Raises RuntimeCatalogValidationError if template contains invalid placeholders.
        """
        if not template:
            return template

        # Find all placeholders in the template
        found = set(re.findall(r"\{(\w+)\}", template))

        # Check for invalid placeholders
        valid_placeholders = {"model", "provider", "workspace_cwd", "task_id"}
        invalid = found - valid_placeholders
        if invalid:
            raise RuntimeCatalogValidationError(
                f"Invalid template placeholders: {invalid}. Valid: {valid_placeholders}"
            )

        # Check for missing context keys
        missing = found - set(context.keys())
        if missing:
            raise RuntimeCatalogValidationError(
                f"Missing context for template placeholders: {missing}"
            )

        # Render
        result = template
        for key, value in context.items():
            result = result.replace(f"{{{key}}}", value)

        return result

    def get_executor_defaults(
        self, catalog: RuntimeCatalog, executor_id: str
    ) -> tuple[str | None, str | None]:
        """Get the default provider and model for an executor.

        Returns (default_provider_id, default_model_id).
        """
        executor = self._find_executor(catalog, executor_id)
        if executor is None:
            return None, None

        provider_id = executor.default_provider_id
        if provider_id is None:
            return None, None

        provider = self._find_provider(catalog, executor_id, provider_id)
        if provider is None:
            return provider_id, None

        return provider_id, provider.default_model_id

    def _find_executor(
        self, catalog: RuntimeCatalog, executor_id: str
    ) -> RuntimeExecutorConfig | None:
        for executor in catalog.executors:
            if executor.id == executor_id:
                return executor
        return None

    def _find_provider(
        self, catalog: RuntimeCatalog, executor_id: str, provider_id: str
    ) -> RuntimeProviderConfig | None:
        executor = self._find_executor(catalog, executor_id)
        if executor is None:
            return None
        for provider in executor.providers:
            if provider.id == provider_id:
                return provider
        return None

    def _find_model(
        self, catalog: RuntimeCatalog, executor_id: str, provider_id: str, model_id: str
    ) -> RuntimeModelConfig | None:
        provider = self._find_provider(catalog, executor_id, provider_id)
        if provider is None:
            return None
        for model in provider.models:
            if model.id == model_id:
                return model
        return None

    def _get_executor_env_overrides(self, executor: RuntimeExecutorConfig) -> dict[str, str]:
        if executor.executor_type == "acp":
            return {}
        env: dict[str, str] = {}
        # Only inject credential env when a key is actually available — from the
        # catalog or the backend process env (the UI promises "leave blank to use
        # env var"). With no key anywhere, this is *local CLI mode*: emit nothing
        # (not even the base URL) so the spawned CLI falls back entirely to its own
        # logged-in default. A base URL without a key is a broken half-state that
        # points the local CLI at the wrong endpoint with no way to authenticate.
        has_key = bool(executor.api_key) or timeouts.anthropic_api_key_configured()
        if has_key:
            if executor.api_endpoint:
                env["ANTHROPIC_BASE_URL"] = executor.api_endpoint
                # Claude Code may perform telemetry / feature-discovery calls against
                # Anthropic's default hosts before the model request. With a custom
                # Anthropic-compatible endpoint (MiniMax, gateway, etc.) those calls
                # can fail auth with the provider key even though the configured API
                # endpoint is valid. Agent-console subprocesses only need the model
                # call, so keep the CLI on the configured endpoint.
                env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
                env["DISABLE_TELEMETRY"] = "1"
                env["DISABLE_ERROR_REPORTING"] = "1"
            if executor.api_key:
                env["ANTHROPIC_API_KEY"] = executor.api_key
            # else: ANTHROPIC_API_KEY is inherited from the process env.
        if executor.default_model:
            env["CLAUDE_MODEL"] = executor.default_model
        return env

    def _create_default_catalog(self) -> RuntimeCatalog:
        """Create a default runtime catalog with codex and claude executors."""
        return RuntimeCatalog(
            executors=[
                RuntimeExecutorConfig(
                    id="codex",
                    label="Codex",
                    enabled=True,
                    executor_type="codex",
                    default_model="claude-sonnet-4-6",
                    providers=[
                        RuntimeProviderConfig(
                            id="anthropic",
                            label="Anthropic",
                            enabled=True,
                            models=[
                                RuntimeModelConfig(
                                    id="claude-sonnet-4-6", label="Claude Sonnet 4.6", enabled=True
                                ),
                                RuntimeModelConfig(
                                    id="claude-opus-4-7", label="Claude Opus 4.7", enabled=True
                                ),
                                RuntimeModelConfig(
                                    id="claude-haiku-4-5", label="Claude Haiku 4.5", enabled=True
                                ),
                            ],
                            default_model_id="claude-sonnet-4-6",
                        ),
                        RuntimeProviderConfig(
                            id="deepseek",
                            label="DeepSeek",
                            enabled=True,
                            models=[
                                RuntimeModelConfig(
                                    id="deepseek-chat", label="DeepSeek Chat", enabled=True
                                ),
                                RuntimeModelConfig(
                                    id="deepseek-coder", label="DeepSeek Coder", enabled=True
                                ),
                            ],
                            default_model_id="deepseek-chat",
                        ),
                    ],
                    default_provider_id="anthropic",
                ),
                RuntimeExecutorConfig(
                    id="claude",
                    label="Claude",
                    enabled=True,
                    executor_type="claude",
                    default_model="claude-sonnet-4-6",
                    providers=[
                        RuntimeProviderConfig(
                            id="anthropic",
                            label="Anthropic",
                            enabled=True,
                            models=[
                                RuntimeModelConfig(
                                    id="claude-sonnet-4-6", label="Claude Sonnet 4.6", enabled=True
                                ),
                                RuntimeModelConfig(
                                    id="claude-opus-4-7", label="Claude Opus 4.7", enabled=True
                                ),
                                RuntimeModelConfig(
                                    id="claude-haiku-4-5", label="Claude Haiku 4.5", enabled=True
                                ),
                            ],
                            default_model_id="claude-sonnet-4-6",
                        ),
                        RuntimeProviderConfig(
                            id="deepseek",
                            label="DeepSeek",
                            enabled=True,
                            models=[
                                RuntimeModelConfig(
                                    id="deepseek-chat", label="DeepSeek Chat", enabled=True
                                ),
                                RuntimeModelConfig(
                                    id="deepseek-coder", label="DeepSeek Coder", enabled=True
                                ),
                            ],
                            default_model_id="deepseek-chat",
                        ),
                    ],
                    default_provider_id="anthropic",
                ),
            ]
        )
