from __future__ import annotations

from copy import deepcopy

import pytest
from test_structured_prototype_generation_contracts import (
    blueprint_payload,
    branching_blueprint_payload,
    dashboard_page_payload,
    foundation_payload,
    orders_page_payload,
    users_page_payload,
    users_table_payload,
)

from app.adapters.prototype_runtime_worker import PrototypeRuntimeWorker
from app.application.structured_prototype_contracts import (
    GridNodeV1,
    SidebarShellV1,
    StackNodeV1,
    document_hash,
)
from app.application.structured_prototype_generation_assembler import (
    StructuredPrototypeGenerationAssemblyError,
    assemble_generation_candidate,
    generation_document_id,
    generation_validation_cases,
)
from app.application.structured_prototype_generation_contracts import (
    GeneratedPageV1,
    GenerationBlueprintV1,
    GenerationFoundationV1,
)


def _complete_blueprint_payload() -> dict[str, object]:
    return blueprint_payload()


def _list_page_payload() -> dict[str, object]:
    return dashboard_page_payload()


def _create_page_payload() -> dict[str, object]:
    return users_page_payload()


def _detail_page_payload() -> dict[str, object]:
    return orders_page_payload()


def _artifacts() -> tuple[
    GenerationBlueprintV1,
    GenerationFoundationV1,
    tuple[GeneratedPageV1, ...],
]:
    return (
        GenerationBlueprintV1.model_validate(blueprint_payload(), strict=True),
        GenerationFoundationV1.model_validate(foundation_payload(), strict=True),
        tuple(
            GeneratedPageV1.model_validate(payload, strict=True)
            for payload in (
                dashboard_page_payload(),
                users_page_payload(),
                orders_page_payload(),
            )
        ),
    )


def test_assembler_uses_dynamic_blueprint_page_order_and_navigation() -> None:
    blueprint, foundation, pages = _artifacts()
    document = assemble_generation_candidate(
        document_id=generation_document_id("admin-demo-navigation"),
        blueprint=blueprint,
        foundation=foundation,
        pages=pages,
    )

    assert [page.key for page in document.pages] == ["dashboard", "users", "orders"]
    assert [item.key for item in document.navigation.items] == [
        "dashboard",
        "users",
        "orders",
    ]


def test_assembler_copies_shared_shell_and_converts_responsive_grid_exactly() -> None:
    blueprint, foundation, pages = _artifacts()
    dashboard_payload = dashboard_page_payload()
    root = dashboard_payload["root"]
    assert isinstance(root, dict)
    children = root["children"]
    assert isinstance(children, list)
    children.append(
        {
            "localKey": "metric-grid",
            "name": "指标网格",
            "type": "Grid",
            "columns": 1,
            "gap": 20,
            "padding": 12,
            "columnOverrides": [
                {"minWidth": 768, "columns": 2},
                {"minWidth": 1200, "columns": 4},
            ],
            "children": [],
        }
    )
    dashboard = GeneratedPageV1.model_validate(dashboard_payload, strict=True)

    document = assemble_generation_candidate(
        document_id=generation_document_id("admin-demo-grid-shell"),
        blueprint=blueprint,
        foundation=foundation,
        pages=(dashboard, *pages[1:]),
    )

    assert isinstance(document.settings.shell, SidebarShellV1)
    assert document.settings.shell.model_dump(mode="json", by_alias=True) == (
        foundation.shared_shell.model_dump(mode="json", by_alias=True)
    )
    root = document.pages[0].root
    assert isinstance(root, StackNodeV1)
    grid = root.children[-1]
    assert isinstance(grid, GridNodeV1)
    assert grid.padding.model_dump(mode="json", by_alias=True) == {
        "top": 12,
        "right": 12,
        "bottom": 12,
        "left": 12,
    }
    assert [(item.min_width, item.columns) for item in grid.column_overrides] == [
        (768, 2),
        (1200, 4),
    ]


def test_assembler_uses_the_first_confirmed_role_for_an_implicit_preview_scenario() -> None:
    payload = blueprint_payload()
    payload["scenarioIntents"] = []
    blueprint = GenerationBlueprintV1.model_validate(payload, strict=True)
    _, foundation, pages = _artifacts()

    document = assemble_generation_candidate(
        document_id=generation_document_id("role-without-scenario"),
        blueprint=blueprint,
        foundation=foundation,
        pages=pages,
    )

    assert document.runtime.scenarios[0].actor_role_id == document.runtime.roles[0].id


def test_assembler_is_deterministic_and_compiles_typed_runtime_bindings() -> None:
    blueprint, foundation, pages = _artifacts()
    document_id = generation_document_id("admin-demo-determinism")

    first = assemble_generation_candidate(
        document_id=document_id,
        blueprint=blueprint,
        foundation=foundation,
        pages=pages,
    )
    replay = assemble_generation_candidate(
        document_id=document_id,
        blueprint=blueprint,
        foundation=foundation,
        pages=pages,
    )

    assert document_hash(first) == document_hash(replay)
    assert isinstance(first.pages[0].root, StackNodeV1)
    assert [schema.key for schema in first.runtime.entity_schemas] == ["user", "order"]
    assert [binding.target for binding in first.runtime.view_bindings] == [
        "tableRows",
        "tableRows",
    ]
    assert [rule.key for rule in first.runtime.rules] == ["open-users"]
    assert first.runtime.rules[0].effects[0].kind == "navigate"
    assert first.flows[0].rule_id == first.runtime.rules[0].id


def test_assembler_allows_distinct_targets_for_the_same_behavior() -> None:
    blueprint = GenerationBlueprintV1.model_validate(branching_blueprint_payload(), strict=True)
    _, foundation, pages = _artifacts()

    document = assemble_generation_candidate(
        document_id=generation_document_id("admin-demo-branching-flow"),
        blueprint=blueprint,
        foundation=foundation,
        pages=pages,
    )

    assert len(document.flows) == 2
    assert document.flows[0].rule_id == document.flows[1].rule_id
    assert {flow.to_page_id for flow in document.flows} == {
        document.pages[1].id,
        document.pages[2].id,
    }


@pytest.mark.parametrize(
    ("violation", "message"),
    [
        ("flow-key", "flow key dashboard-to-users is duplicated"),
        ("behavior-target", "behavior and target page projection is duplicated"),
        ("source", "source page does not match its behavior intent"),
    ],
)
def test_assembler_refuses_ambiguous_or_drifting_flow_projections(
    violation: str,
    message: str,
) -> None:
    blueprint, foundation, pages = _artifacts()
    first_flow = blueprint.flow_intents[0]
    if violation == "flow-key":
        branching = GenerationBlueprintV1.model_validate(branching_blueprint_payload(), strict=True)
        second_flow = branching.flow_intents[1].model_copy(update={"key": first_flow.key})
        invalid_blueprint = branching.model_copy(
            update={"flow_intents": [branching.flow_intents[0], second_flow]}
        )
    elif violation == "behavior-target":
        duplicate = first_flow.model_copy(update={"key": "dashboard-to-users-copy"})
        invalid_blueprint = blueprint.model_copy(update={"flow_intents": [first_flow, duplicate]})
    else:
        drifting = first_flow.model_copy(update={"source_page_key": "users"})
        invalid_blueprint = blueprint.model_copy(update={"flow_intents": [drifting]})

    with pytest.raises(StructuredPrototypeGenerationAssemblyError, match=message):
        assemble_generation_candidate(
            document_id=generation_document_id(f"admin-demo-{violation}"),
            blueprint=invalid_blueprint,
            foundation=foundation,
            pages=pages,
        )


def test_assembler_refuses_a_missing_confirmed_view_binding() -> None:
    blueprint, foundation, pages = _artifacts()
    invalid_payload = deepcopy(users_page_payload())
    invalid_payload["viewBindings"] = []
    invalid_users = GeneratedPageV1.model_validate(invalid_payload, strict=True)

    with pytest.raises(StructuredPrototypeGenerationAssemblyError) as error:
        assemble_generation_candidate(
            document_id=generation_document_id("admin-demo-missing-binding"),
            blueprint=blueprint,
            foundation=foundation,
            pages=(pages[0], invalid_users, pages[2]),
        )
    assert error.value.code == "generation_semantic_invalid"


def test_assembler_refuses_two_table_rows_intents_bound_to_one_table() -> None:
    blueprint_payload_value = blueprint_payload()
    view_intents = blueprint_payload_value["viewBindingIntents"]
    assert isinstance(view_intents, list)
    duplicate_intent = deepcopy(view_intents[0])
    assert isinstance(duplicate_intent, dict)
    duplicate_intent["key"] = "users-table-rows-descending"
    duplicate_intent["sortDirection"] = "desc"
    view_intents.append(duplicate_intent)
    blueprint = GenerationBlueprintV1.model_validate(blueprint_payload_value, strict=True)
    invalid_users_payload = deepcopy(users_page_payload())
    bindings = invalid_users_payload["viewBindings"]
    assert isinstance(bindings, list)
    bindings.append(
        {
            "nodeKey": "users-table",
            "viewBindingIntentKey": "users-table-rows-descending",
        }
    )
    invalid_users = GeneratedPageV1.model_validate(invalid_users_payload, strict=True)
    _, foundation, pages = _artifacts()

    with pytest.raises(
        StructuredPrototypeGenerationAssemblyError,
        match="more than one tableRows binding",
    ):
        assemble_generation_candidate(
            document_id=generation_document_id("admin-demo-duplicate-table-binding"),
            blueprint=blueprint,
            foundation=foundation,
            pages=(pages[0], invalid_users, pages[2]),
        )


def test_assembler_refuses_static_rows_on_a_runtime_bound_table() -> None:
    blueprint, foundation, pages = _artifacts()
    invalid_users_payload = deepcopy(users_page_payload())
    table = users_table_payload(invalid_users_payload)
    table["rows"] = [
        {
            "localKey": "alice",
            "cells": [
                {"columnKey": "name", "value": "Alice Chen"},
                {"columnKey": "email", "value": "alice@example.com"},
                {"columnKey": "status", "value": "Active"},
            ],
        }
    ]
    invalid_users = GeneratedPageV1.model_validate(invalid_users_payload, strict=True)

    with pytest.raises(
        StructuredPrototypeGenerationAssemblyError,
        match="tableRows binding cannot declare static rows",
    ) as error:
        assemble_generation_candidate(
            document_id=generation_document_id("admin-demo-static-and-runtime-table"),
            blueprint=blueprint,
            foundation=foundation,
            pages=(pages[0], invalid_users, pages[2]),
        )

    assert error.value.code == "generation_semantic_invalid"


@pytest.mark.asyncio
async def test_assembled_candidate_passes_admin_demo_scripted_scenario() -> None:
    blueprint, foundation, pages = _artifacts()
    document_id = generation_document_id("admin-demo-runtime-validation")
    document = assemble_generation_candidate(
        document_id=document_id,
        blueprint=blueprint,
        foundation=foundation,
        pages=pages,
    )
    case = generation_validation_cases(
        document_id=document_id,
        blueprint=blueprint,
        pages=pages,
    )[0]
    definition = document.runtime.model_dump(mode="json", by_alias=True)
    worker = PrototypeRuntimeWorker()
    initial = await worker.initialize_state(
        request_id="admin-demo-initialize",
        definition=definition,
        scenario_id=case.scenario_id,
        session_id="admin-demo-session",
    )
    replayed = await worker.replay_event_batches(
        request_id="admin-demo-replay",
        definition=definition,
        state_json=initial.state_json,
        batches=list(case.batches),
    )

    assert [transition.outcome for transition in replayed.transitions] == ["applied"]
    assert replayed.transitions[0].state_hash == replayed.final.state_hash
    assert replayed.final.state_hash.startswith("sha256:")
    assert replayed.final.view_model_hash.startswith("sha256:")
