"""Tests for Architect workflow including development_task_list.json output."""

import json  # noqa: I001
import pytest
from pathlib import Path

from app.application.architect_workflow import (
    ArchitectWorkflow,
    ArchitectWorkflowError,
    ImplementationTask,
)
from app.domain.models import CodexTask


@pytest.fixture
def architect_workflow():
    return ArchitectWorkflow()


@pytest.fixture
def sample_task(tmp_path):
    return CodexTask(
        id="task-1",
        session_id="ws-1",
        issue_id="issue-1",
        phase="architecture",
        title="架构 - 购物车功能",
        prompt="请设计购物车功能架构",
        role="architect",
        executor="codex",
        status="done",
        workspace_path=str(tmp_path),
        result=json.dumps(
            {
                "language": "zh-CN",
                "project_name": "电商系统",
                "issue_id": "issue-1",
                "issue_title": "架构 - 购物车功能",
                "architecture_summary": "购物车模块设计",
                "components": ["购物车服务", "库存服务"],
                "data_models": ["CartItem", "Cart"],
                "interfaces": ["POST /cart/add", "GET /cart"],
                "data_flow": "用户添加商品 -> 购物车服务 -> 库存服务",
                "implementation_tasks": [
                    {
                        "title": "实现购物车API",
                        "description": "实现购物车增删改查接口",
                        "priority": "P1",
                    },
                    {"title": "实现库存检查", "description": "实现库存校验逻辑", "priority": "P1"},
                    {
                        "title": "实现价格计算",
                        "description": "实现购物车总价计算",
                        "priority": "P2",
                    },
                ],
                "development_task_list": [
                    "实现购物车API",
                    "实现库存检查",
                    "实现价格计算",
                ],
                "risks": ["库存并发问题"],
                "open_questions": ["是否需要购物车持久化"],
            }
        ),
    )


def test_architect_persists_development_task_list_json(architect_workflow, sample_task):
    """Verify Architect successfully persists development_task_list.json."""
    design = architect_workflow.persist_result(sample_task, workspace_title="电商系统")  # noqa: F841

    issue_root = Path(sample_task.workspace_path) / "issues" / sample_task.issue_id
    dev_task_list_path = issue_root / "architect" / "development_task_list.json"

    assert dev_task_list_path.exists(), "development_task_list.json should be created"

    content = json.loads(dev_task_list_path.read_text(encoding="utf-8"))
    assert isinstance(content, list), "development_task_list.json should be a list"
    assert len(content) == 3, "Should have 3 task titles"
    assert content == ["实现购物车API", "实现库存检查", "实现价格计算"]


def test_architect_rejects_missing_development_task_list(architect_workflow, tmp_path):
    """Verify Architect fails when development_task_list is missing."""
    task = CodexTask(
        id="task-1",
        session_id="ws-1",
        issue_id="issue-1",
        phase="architecture",
        title="架构 - 购物车功能",
        prompt="请设计购物车功能架构",
        role="architect",
        executor="codex",
        status="done",
        workspace_path=str(tmp_path),
        result=json.dumps(
            {
                "language": "zh-CN",
                "project_name": "电商系统",
                "issue_id": "issue-1",
                "issue_title": "架构 - 购物车功能",
                "architecture_summary": "购物车模块设计",
                "components": ["购物车服务"],
                "data_models": ["Cart"],
                "interfaces": ["POST /cart/add"],
                "data_flow": "用户添加商品",
                "implementation_tasks": [
                    {
                        "title": "实现购物车API",
                        "description": "实现购物车增删改查接口",
                        "priority": "P1",
                    },
                ],
                # Missing development_task_list
                "risks": [],
                "open_questions": [],
            }
        ),
    )

    with pytest.raises(ArchitectWorkflowError, match="development_task_list"):
        architect_workflow.persist_result(task, workspace_title="电商系统")


def test_architect_rejects_duplicate_titles_in_development_task_list(architect_workflow, tmp_path):
    """Verify Architect fails when development_task_list has duplicate titles."""
    task = CodexTask(
        id="task-1",
        session_id="ws-1",
        issue_id="issue-1",
        phase="architecture",
        title="架构 - 购物车功能",
        prompt="请设计购物车功能架构",
        role="architect",
        executor="codex",
        status="done",
        workspace_path=str(tmp_path),
        result=json.dumps(
            {
                "language": "zh-CN",
                "project_name": "电商系统",
                "issue_id": "issue-1",
                "issue_title": "架构 - 购物车功能",
                "architecture_summary": "购物车模块设计",
                "components": ["购物车服务"],
                "data_models": ["Cart"],
                "interfaces": ["POST /cart/add"],
                "data_flow": "用户添加商品",
                "implementation_tasks": [
                    {
                        "title": "实现购物车API",
                        "description": "实现购物车增删改查接口",
                        "priority": "P1",
                    },
                    {"title": "实现库存检查", "description": "实现库存校验逻辑", "priority": "P1"},
                ],
                "development_task_list": [
                    "实现购物车API",
                    "实现购物车API",  # Duplicate
                ],
                "risks": [],
                "open_questions": [],
            }
        ),
    )

    with pytest.raises(ArchitectWorkflowError, match="重复|duplicate"):  # noqa: RUF043
        architect_workflow.persist_result(task, workspace_title="电商系统")


def test_architect_rejects_mismatched_development_task_list(architect_workflow, tmp_path):
    """Verify Architect fails when development_task_list doesn't match implementation_tasks."""
    task = CodexTask(
        id="task-1",
        session_id="ws-1",
        issue_id="issue-1",
        phase="architecture",
        title="架构 - 购物车功能",
        prompt="请设计购物车功能架构",
        role="architect",
        executor="codex",
        status="done",
        workspace_path=str(tmp_path),
        result=json.dumps(
            {
                "language": "zh-CN",
                "project_name": "电商系统",
                "issue_id": "issue-1",
                "issue_title": "架构 - 购物车功能",
                "architecture_summary": "购物车模块设计",
                "components": ["购物车服务"],
                "data_models": ["Cart"],
                "interfaces": ["POST /cart/add"],
                "data_flow": "用户添加商品",
                "implementation_tasks": [
                    {
                        "title": "实现购物车API",
                        "description": "实现购物车增删改查接口",
                        "priority": "P1",
                    },
                    {"title": "实现库存检查", "description": "实现库存校验逻辑", "priority": "P1"},
                ],
                "development_task_list": [
                    "实现购物车API",
                    "实现价格计算",  # Not in implementation_tasks
                    "额外任务",  # Extra item to make counts differ
                ],
                "risks": [],
                "open_questions": [],
            }
        ),
    )

    with pytest.raises(ArchitectWorkflowError, match="不匹配|mismatch"):  # noqa: RUF043
        architect_workflow.persist_result(task, workspace_title="电商系统")


def test_architect_rejects_empty_development_task_list(architect_workflow, tmp_path):
    """Verify Architect fails when development_task_list is empty but implementation_tasks is not."""
    task = CodexTask(
        id="task-1",
        session_id="ws-1",
        issue_id="issue-1",
        phase="architecture",
        title="架构 - 购物车功能",
        prompt="请设计购物车功能架构",
        role="architect",
        executor="codex",
        status="done",
        workspace_path=str(tmp_path),
        result=json.dumps(
            {
                "language": "zh-CN",
                "project_name": "电商系统",
                "issue_id": "issue-1",
                "issue_title": "架构 - 购物车功能",
                "architecture_summary": "购物车模块设计",
                "components": ["购物车服务"],
                "data_models": ["Cart"],
                "interfaces": ["POST /cart/add"],
                "data_flow": "用户添加商品",
                "implementation_tasks": [
                    {
                        "title": "实现购物车API",
                        "description": "实现购物车增删改查接口",
                        "priority": "P1",
                    },
                ],
                "development_task_list": [],  # Empty
                "risks": [],
                "open_questions": [],
            }
        ),
    )
    with pytest.raises(ArchitectWorkflowError, match="空|empty"):  # noqa: RUF043
        architect_workflow.persist_result(task, workspace_title="电商系统")


def test_architect_persists_expected_files_in_implementation_plan(architect_workflow, tmp_path):
    """Verify Architect serializes expected_files into implementation_plan.json."""
    task = CodexTask(
        id="task-1",
        session_id="ws-1",
        issue_id="issue-1",
        phase="architecture",
        title="架构 - 购物车功能",
        prompt="请设计购物车功能架构",
        role="architect",
        executor="codex",
        status="done",
        workspace_path=str(tmp_path),
        result=json.dumps(
            {
                "language": "zh-CN",
                "project_name": "电商系统",
                "issue_id": "issue-1",
                "issue_title": "架构 - 购物车功能",
                "architecture_summary": "购物车模块设计",
                "components": ["购物车服务"],
                "data_models": ["Cart"],
                "interfaces": ["POST /cart/add"],
                "data_flow": "用户添加商品",
                "implementation_tasks": [
                    {
                        "title": "实现购物车API",
                        "description": "实现购物车增删改查接口",
                        "priority": "P1",
                        "expected_files": [
                            "backend/app/cart_api.py",
                            "backend/app/cart_service.py",
                        ],
                    },
                    {
                        "title": "实现库存检查",
                        "description": "实现库存校验逻辑",
                        "priority": "P1",
                        "expected_files": ["backend/app/inventory.py"],
                    },
                ],
                "development_task_list": ["实现购物车API", "实现库存检查"],
                "risks": [],
                "open_questions": [],
            }
        ),
    )

    design = architect_workflow.persist_result(task, workspace_title="电商系统")

    assert design.implementation_tasks[0].expected_files == [
        "backend/app/cart_api.py",
        "backend/app/cart_service.py",
    ]

    issue_root = Path(task.workspace_path) / "issues" / task.issue_id
    impl_plan_path = issue_root / "architect" / "implementation_plan.json"
    assert impl_plan_path.exists()

    plan = json.loads(impl_plan_path.read_text(encoding="utf-8"))
    assert plan[0]["expected_files"] == [
        "backend/app/cart_api.py",
        "backend/app/cart_service.py",
    ]
    assert plan[1]["expected_files"] == ["backend/app/inventory.py"]
    # Existing fields preserved.
    assert plan[0]["title"] == "实现购物车API"
    assert plan[0]["priority"] == "P1"


def test_architect_implementation_plan_defaults_expected_files_to_empty(
    architect_workflow, tmp_path
):
    """Verify old payloads (implementation_tasks without expected_files) degrade to []."""
    task = CodexTask(
        id="task-1",
        session_id="ws-1",
        issue_id="issue-1",
        phase="architecture",
        title="架构 - 购物车功能",
        prompt="请设计购物车功能架构",
        role="architect",
        executor="codex",
        status="done",
        workspace_path=str(tmp_path),
        result=json.dumps(
            {
                "language": "zh-CN",
                "project_name": "电商系统",
                "issue_id": "issue-1",
                "issue_title": "架构 - 购物车功能",
                "architecture_summary": "购物车模块设计",
                "components": ["购物车服务"],
                "data_models": ["Cart"],
                "interfaces": ["POST /cart/add"],
                "data_flow": "用户添加商品",
                "implementation_tasks": [
                    # No expected_files field (legacy payload).
                    {
                        "title": "实现购物车API",
                        "description": "实现购物车增删改查接口",
                        "priority": "P1",
                    },
                ],
                "development_task_list": ["实现购物车API"],
                "risks": [],
                "open_questions": [],
            }
        ),
    )

    design = architect_workflow.persist_result(task, workspace_title="电商系统")

    assert design.implementation_tasks[0].expected_files == []

    issue_root = Path(task.workspace_path) / "issues" / task.issue_id
    impl_plan_path = issue_root / "architect" / "implementation_plan.json"
    plan = json.loads(impl_plan_path.read_text(encoding="utf-8"))
    assert plan[0]["expected_files"] == []


def test_implementation_task_model_validate_missing_expected_files():
    """Legacy ImplementationTask payload validates with expected_files defaulting to []."""
    task = ImplementationTask.model_validate({"title": "t", "description": "d", "priority": "P1"})
    assert task.expected_files == []


def test_architect_rejects_duplicate_titles_in_implementation_tasks(architect_workflow, tmp_path):
    """Verify Architect fails when implementation_tasks has duplicate titles."""
    task = CodexTask(
        id="task-1",
        session_id="ws-1",
        issue_id="issue-1",
        phase="architecture",
        title="架构 - 购物车功能",
        prompt="请设计购物车功能架构",
        role="architect",
        executor="codex",
        status="done",
        workspace_path=str(tmp_path),
        result=json.dumps(
            {
                "language": "zh-CN",
                "project_name": "电商系统",
                "issue_id": "issue-1",
                "issue_title": "架构 - 购物车功能",
                "architecture_summary": "购物车模块设计",
                "components": ["购物车服务"],
                "data_models": ["Cart"],
                "interfaces": ["POST /cart/add"],
                "data_flow": "用户添加商品",
                "implementation_tasks": [
                    {
                        "title": "实现购物车API",
                        "description": "实现购物车增删改查接口",
                        "priority": "P1",
                    },
                    {
                        "title": "实现购物车API",
                        "description": "重复的标题",
                        "priority": "P1",
                    },  # Duplicate
                ],
                "development_task_list": ["实现购物车API"],
                "risks": [],
                "open_questions": [],
            }
        ),
    )
    with pytest.raises(ArchitectWorkflowError, match="重复|duplicate"):  # noqa: RUF043
        architect_workflow.persist_result(task, workspace_title="电商系统")
