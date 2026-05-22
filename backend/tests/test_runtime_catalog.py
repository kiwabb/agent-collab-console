"""Tests for runtime catalog service and provider/model functionality."""

import pytest
from datetime import datetime
from pathlib import Path
import tempfile
import asyncio

pytestmark = pytest.mark.slow

from app.domain.models import (
    RuntimeCatalog,
    RuntimeExecutorConfig,
    RuntimeProviderConfig,
    RuntimeModelConfig,
    CodexTask,
    ExecutionProcess,
)
from app.adapters.async_sqlite_store import AsyncSQLiteStore
from app.application.runtime_catalog_service import RuntimeCatalogService, RuntimeCatalogValidationError


class TestRuntimeCatalogService:
    """Tests for RuntimeCatalogService."""

    @pytest.fixture
    def event_loop(self):
        """Create an instance of the default event loop for the test session."""
        loop = asyncio.get_event_loop_policy().new_event_loop()
        yield loop
        loop.close()

    @pytest.fixture
    async def store(self):
        """Create an in-memory AsyncSQLite store for testing."""
        store = AsyncSQLiteStore(Path(":memory:"))
        await store._init_db()
        yield store

    @pytest.fixture
    def service(self, store):
        """Create a RuntimeCatalogService with the test store."""
        return RuntimeCatalogService(store)

    @pytest.fixture
    def default_catalog(self):
        """Create a default runtime catalog for testing."""
        return RuntimeCatalog(
            executors=[
                RuntimeExecutorConfig(
                    id="codex",
                    label="Codex",
                    enabled=True,
                    providers=[
                        RuntimeProviderConfig(
                            id="anthropic",
                            label="Anthropic",
                            enabled=True,
                            models=[
                                RuntimeModelConfig(id="claude-sonnet-4-6", label="Claude Sonnet 4.6", enabled=True),
                                RuntimeModelConfig(id="claude-opus-4-7", label="Claude Opus 4.7", enabled=True),
                            ],
                            default_model_id="claude-sonnet-4-6",
                        ),
                    ],
                    default_provider_id="anthropic",
                ),
                RuntimeExecutorConfig(
                    id="claude",
                    label="Claude",
                    enabled=True,
                    providers=[
                        RuntimeProviderConfig(
                            id="anthropic",
                            label="Anthropic",
                            enabled=True,
                            models=[
                                RuntimeModelConfig(id="claude-sonnet-4-6", label="Claude Sonnet 4.6", enabled=True),
                            ],
                            default_model_id="claude-sonnet-4-6",
                        ),
                    ],
                    default_provider_id="anthropic",
                ),
            ]
        )

    @pytest.mark.asyncio
    async def test_load_catalog_creates_default(self, service):
        """Loading catalog when none exists creates a default."""
        catalog = await service.load_catalog()
        assert catalog is not None
        assert len(catalog.executors) >= 2  # codex and claude
        executor_ids = [e.id for e in catalog.executors]
        assert "codex" in executor_ids
        assert "claude" in executor_ids

    @pytest.mark.asyncio
    async def test_save_and_load_catalog(self, service, default_catalog):
        """Saving and loading a catalog preserves data."""
        await service.save_catalog(default_catalog)
        loaded = await service.load_catalog()
        assert len(loaded.executors) == 2
        codex = next(e for e in loaded.executors if e.id == "codex")
        assert codex.default_provider_id == "anthropic"
        anthropic = next(p for p in codex.providers if p.id == "anthropic")
        assert anthropic.default_model_id == "claude-sonnet-4-6"

    @pytest.mark.asyncio
    async def test_validate_catalog_rejects_duplicate_executor_ids(self, service, default_catalog):
        """Validation fails when executor IDs are duplicated."""
        default_catalog.executors.append(
            RuntimeExecutorConfig(id="codex", label="Duplicate", enabled=True, providers=[])
        )
        with pytest.raises(RuntimeCatalogValidationError, match="Duplicate executor ID"):
            service.validate_catalog(default_catalog)

    @pytest.mark.asyncio
    async def test_validate_catalog_rejects_duplicate_provider_ids(self, service, default_catalog):
        """Validation fails when provider IDs are duplicated within an executor."""
        codex = next(e for e in default_catalog.executors if e.id == "codex")
        codex.providers.append(
            RuntimeProviderConfig(id="anthropic", label="Duplicate", enabled=True, models=[])
        )
        with pytest.raises(RuntimeCatalogValidationError, match="Duplicate provider ID"):
            service.validate_catalog(default_catalog)

    @pytest.mark.asyncio
    async def test_validate_catalog_rejects_invalid_default_provider(self, service, default_catalog):
        """Validation fails when default_provider_id references non-existent provider."""
        codex = next(e for e in default_catalog.executors if e.id == "codex")
        codex.default_provider_id = "nonexistent"
        with pytest.raises(RuntimeCatalogValidationError, match="invalid default_provider_id"):
            service.validate_catalog(default_catalog)

    @pytest.mark.asyncio
    async def test_validate_catalog_rejects_disabled_default(self, service, default_catalog):
        """Validation fails when default provider is disabled."""
        codex = next(e for e in default_catalog.executors if e.id == "codex")
        anthropic = next(p for p in codex.providers if p.id == "anthropic")
        anthropic.enabled = False
        with pytest.raises(RuntimeCatalogValidationError, match="disabled provider"):
            service.validate_catalog(default_catalog)

    @pytest.mark.asyncio
    async def test_resolve_effective_config_uses_defaults(self, service, default_catalog):
        """When no provider/model specified, uses executor defaults."""
        executor, provider, model, env_overrides, executor_type = service.resolve_effective_config(
            default_catalog, "codex", provider=None, model=None
        )
        assert executor == "codex"
        assert provider == "anthropic"
        assert model == "claude-sonnet-4-6"

    @pytest.mark.asyncio
    async def test_resolve_effective_config_uses_explicit(self, service, default_catalog):
        """When provider/model specified, uses them directly."""
        executor, provider, model, env_overrides, executor_type = service.resolve_effective_config(
            default_catalog, "codex", provider="anthropic", model="claude-opus-4-7"
        )
        assert executor == "codex"
        assert provider == "anthropic"
        assert model == "claude-opus-4-7"

    @pytest.mark.asyncio
    async def test_resolve_effective_config_rejects_unknown_executor(self, service, default_catalog):
        """Unknown executor raises validation error."""
        with pytest.raises(RuntimeCatalogValidationError, match="Unknown executor"):
            service.resolve_effective_config(default_catalog, "unknown", provider=None, model=None)

    @pytest.mark.asyncio
    async def test_resolve_effective_config_rejects_disabled_executor(self, service, default_catalog):
        """Disabled executor raises validation error."""
        codex = next(e for e in default_catalog.executors if e.id == "codex")
        codex.enabled = False
        with pytest.raises(RuntimeCatalogValidationError, match="disabled"):
            service.resolve_effective_config(default_catalog, "codex", provider=None, model=None)

    @pytest.mark.asyncio
    async def test_render_template_valid_placeholders(self, service):
        """Template rendering works with valid placeholders."""
        template = "model={model} provider={provider}"
        context = {"model": "claude-sonnet-4-6", "provider": "anthropic", "workspace_cwd": "/tmp", "task_id": "123"}
        result = service.render_template(template, context)
        assert result == "model=claude-sonnet-4-6 provider=anthropic"

    @pytest.mark.asyncio
    async def test_render_template_rejects_invalid_placeholders(self, service):
        """Template rendering rejects invalid placeholders."""
        template = "unknown={unknown_var}"
        context = {"model": "claude-sonnet-4-6", "provider": "anthropic", "workspace_cwd": "/tmp", "task_id": "123"}
        with pytest.raises(RuntimeCatalogValidationError, match="Invalid template placeholders"):
            service.render_template(template, context)

    @pytest.mark.asyncio
    async def test_render_template_rejects_missing_context(self, service):
        """Template rendering fails when context is missing required keys."""
        template = "model={model} workspace={workspace_cwd}"
        context = {"model": "claude-sonnet-4-6", "provider": "anthropic", "task_id": "123"}
        with pytest.raises(RuntimeCatalogValidationError, match="Missing context"):
            service.render_template(template, context)

    @pytest.mark.asyncio
    async def test_get_executor_defaults(self, service, default_catalog):
        """Getting executor defaults returns correct provider/model."""
        provider, model = service.get_executor_defaults(default_catalog, "codex")
        assert provider == "anthropic"
        assert model == "claude-sonnet-4-6"


class TestCodexTaskWithProviderModel:
    """Tests for CodexTask with provider/model fields."""

    def test_codex_task_has_provider_model_fields(self):
        """CodexTask model accepts provider and model fields."""
        task = CodexTask(
            id="test-task",
            session_id="test-session",
            title="Test Task",
            prompt="Test prompt",
            executor="codex",
            provider="anthropic",
            model="claude-sonnet-4-6",
        )
        assert task.provider == "anthropic"
        assert task.model == "claude-sonnet-4-6"

    def test_codex_task_defaults_to_none_provider_model(self):
        """CodexTask defaults provider and model to None."""
        task = CodexTask(
            id="test-task",
            session_id="test-session",
            title="Test Task",
            prompt="Test prompt",
        )
        assert task.provider is None
        assert task.model is None


class TestExecutionProcessSnapshot:
    """Tests for ExecutionProcess snapshot fields."""

    def test_execution_process_has_snapshot_fields(self):
        """ExecutionProcess accepts executor, provider, model snapshot fields."""
        process = ExecutionProcess(
            id="test-process",
            task_id="test-task",
            session_id="test-session",
            status="Running",
            executor="codex",
            provider="anthropic",
            model="claude-sonnet-4-6",
        )
        assert process.executor == "codex"
        assert process.provider == "anthropic"
        assert process.model == "claude-sonnet-4-6"

    def test_execution_process_snapshot_defaults_to_none(self):
        """ExecutionProcess snapshot fields default to None."""
        process = ExecutionProcess(
            id="test-process",
            task_id="test-task",
            session_id="test-session",
            status="Running",
        )
        assert process.executor is None
        assert process.provider is None
        assert process.model is None
