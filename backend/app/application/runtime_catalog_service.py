"""Runtime catalog service for managing executor/provider/model configurations."""

from typing import Any

from app.domain.models import (
    RuntimeCatalog,
    RuntimeExecutorConfig,
    RuntimeProviderConfig,
    RuntimeModelConfig,
)


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

    def __init__(self, store):
        """Initialize with a store that has load_runtime_catalog and save_runtime_catalog."""
        self._store = store

    async def load_catalog(self) -> RuntimeCatalog:
        """Load the runtime catalog from storage.

        Returns a default catalog if none exists.
        """
        catalog = await self._store.load_runtime_catalog()
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
                if provider.default_model_id:
                    if provider.default_model_id not in model_ids:
                        raise RuntimeCatalogValidationError(
                            f"Provider '{provider.id}' has invalid default_model_id '{provider.default_model_id}'"
                        )

            # Validate default_provider_id references an existing provider
            if executor.default_provider_id:
                if executor.default_provider_id not in provider_ids:
                    raise RuntimeCatalogValidationError(
                        f"Executor '{executor.id}' has invalid default_provider_id '{executor.default_provider_id}'"
                    )

        # Validate defaults point to enabled items
        for executor in catalog.executors:
            if executor.default_provider_id:
                provider = self._find_provider(catalog, executor.id, executor.default_provider_id)
                if provider and not provider.enabled:
                    raise RuntimeCatalogValidationError(
                        f"Executor '{executor.id}' defaults to disabled provider '{executor.default_provider_id}'"
                    )
                if provider and provider.default_model_id:
                    model = self._find_model(catalog, executor.id, executor.default_provider_id, provider.default_model_id)
                    if model and not model.enabled:
                        raise RuntimeCatalogValidationError(
                            f"Provider '{provider.id}' defaults to disabled model '{provider.default_model_id}'"
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
        # Validate executor exists and is enabled
        executor_config = self._find_executor(catalog, executor)
        if executor_config is None:
            raise RuntimeCatalogValidationError(f"Unknown executor: {executor}")
        if not executor_config.enabled:
            raise RuntimeCatalogValidationError(f"Executor '{executor}' is disabled")

        # Resolve provider
        if provider is None or provider == "":
            provider = executor_config.default_provider_id
        if provider is None:
            raise RuntimeCatalogValidationError(f"No provider specified and no default for executor '{executor}'")

        provider_config = self._find_provider(catalog, executor, provider)
        if provider_config is None:
            raise RuntimeCatalogValidationError(
                f"Provider '{provider}' not found in executor '{executor}'"
            )
        if not provider_config.enabled:
            raise RuntimeCatalogValidationError(f"Provider '{provider}' is disabled")

        # Resolve model
        if model is None or model == "":
            model = executor_config.default_model or provider_config.default_model_id
        if model is None:
            raise RuntimeCatalogValidationError(f"No model specified and no default for provider '{provider}'")

        model_config = self._find_model(catalog, executor, provider, model)
        if model_config is None:
            raise RuntimeCatalogValidationError(
                f"Model '{model}' not found in provider '{provider}'"
            )
        if not model_config.enabled:
            raise RuntimeCatalogValidationError(f"Model '{model}' is disabled")

        # Get env overrides from executor config
        env_overrides = self._get_executor_env_overrides(executor_config)

        return (executor, provider, model, env_overrides, executor_config.executor_type)

    def render_template(self, template: str, context: dict[str, str]) -> str:
        """Render a template string with restricted placeholders.

        Only supports: {model}, {provider}, {workspace_cwd}, {task_id}

        Raises RuntimeCatalogValidationError if template contains invalid placeholders.
        """
        if not template:
            return template

        # Find all placeholders in the template
        import re
        found = set(re.findall(r'\{(\w+)\}', template))

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

    def get_executor_defaults(self, catalog: RuntimeCatalog, executor_id: str) -> tuple[str | None, str | None]:
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

    def _find_executor(self, catalog: RuntimeCatalog, executor_id: str) -> RuntimeExecutorConfig | None:
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
        env: dict[str, str] = {}
        if executor.api_endpoint:
            env["ANTHROPIC_BASE_URL"] = executor.api_endpoint
        if executor.api_key:
            env["ANTHROPIC_API_KEY"] = executor.api_key
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
                                RuntimeModelConfig(id="claude-sonnet-4-6", label="Claude Sonnet 4.6", enabled=True),
                                RuntimeModelConfig(id="claude-opus-4-7", label="Claude Opus 4.7", enabled=True),
                                RuntimeModelConfig(id="claude-haiku-4-5", label="Claude Haiku 4.5", enabled=True),
                            ],
                            default_model_id="claude-sonnet-4-6",
                        ),
                        RuntimeProviderConfig(
                            id="deepseek",
                            label="DeepSeek",
                            enabled=True,
                            models=[
                                RuntimeModelConfig(id="deepseek-chat", label="DeepSeek Chat", enabled=True),
                                RuntimeModelConfig(id="deepseek-coder", label="DeepSeek Coder", enabled=True),
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
                                RuntimeModelConfig(id="claude-sonnet-4-6", label="Claude Sonnet 4.6", enabled=True),
                                RuntimeModelConfig(id="claude-opus-4-7", label="Claude Opus 4.7", enabled=True),
                                RuntimeModelConfig(id="claude-haiku-4-5", label="Claude Haiku 4.5", enabled=True),
                            ],
                            default_model_id="claude-sonnet-4-6",
                        ),
                        RuntimeProviderConfig(
                            id="deepseek",
                            label="DeepSeek",
                            enabled=True,
                            models=[
                                RuntimeModelConfig(id="deepseek-chat", label="DeepSeek Chat", enabled=True),
                                RuntimeModelConfig(id="deepseek-coder", label="DeepSeek Coder", enabled=True),
                            ],
                            default_model_id="deepseek-chat",
                        ),
                    ],
                    default_provider_id="anthropic",
                ),
            ]
        )
