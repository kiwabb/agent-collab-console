from __future__ import annotations

import json

import pytest

from app.adapters.prototype_renderer_worker import PrototypeRendererWorker
from app.adapters.prototype_runtime_worker import PrototypeRuntimeWorker
from app.application.structured_prototype_contracts import (
    StackNodeV1,
    TableNodeV1,
    document_hash,
    document_payload,
)
from app.application.structured_prototype_generation_assembler import (
    assemble_generation_candidate,
    generation_document_id,
    generation_table_row_id,
    generation_validation_cases,
)
from app.application.structured_prototype_generation_contracts import (
    GeneratedPageV1,
    GenerationBlueprintV1,
    GenerationFoundationV1,
)


def _events_blueprint_payload() -> dict[str, object]:
    return {
        "contractVersion": 3,
        "documentTitle": "City Weekends",
        "productIntent": "Help visitors discover local events and register for a place",
        "outputLocale": "en-US",
        "foundationIntent": {
            "visualLanguage": "Bright, accessible public event directory",
            "density": "comfortable",
            "responsiveStrategy": "Single column on mobile and a wider directory on desktop",
        },
        "pages": [
            {
                "pageKey": "event-catalog",
                "title": "Upcoming events",
                "route": "/events",
                "purpose": "Browse upcoming community events and remaining capacity",
                "navigationGroupKey": "public",
            },
            {
                "pageKey": "event-registration",
                "title": "Event registration",
                "route": "/events/register",
                "purpose": "Register a visitor for an event",
                "navigationGroupKey": "public",
            },
        ],
        "navigation": [
            {
                "key": "event-catalog",
                "label": "Events",
                "targetPageKey": "event-catalog",
            },
            {
                "key": "event-registration",
                "label": "Register",
                "targetPageKey": "event-registration",
            },
        ],
        "flowIntents": [
            {
                "key": "registration-to-catalog",
                "sourcePageKey": "event-registration",
                "behaviorIntentKey": "submit-registration",
                "targetPageKey": "event-catalog",
            }
        ],
        "roleIntents": [{"key": "visitor", "label": "Visitor"}],
        "entityIntents": [
            {
                "key": "event",
                "fields": [
                    {"key": "title", "valueType": "string", "nullable": False},
                    {"key": "venue", "valueType": "string", "nullable": False},
                    {
                        "key": "seats-available",
                        "valueType": "integer",
                        "nullable": False,
                    },
                ],
            },
            {
                "key": "registration",
                "fields": [
                    {
                        "key": "attendee-name",
                        "valueType": "string",
                        "nullable": False,
                    },
                    {
                        "key": "attendee-email",
                        "valueType": "string",
                        "nullable": False,
                    },
                    {"key": "status", "valueType": "enum", "nullable": False},
                ],
            },
        ],
        "variableIntents": [
            {
                "key": "latest-registration",
                "valueType": "entityRef",
                "nullable": True,
                "entitySchemaKey": "registration",
                "defaultValue": {"type": "null"},
            }
        ],
        "formIntents": [
            {
                "key": "event-registration",
                "pageKey": "event-registration",
                "fields": [
                    {
                        "key": "attendee-name",
                        "valueType": "string",
                        "initialValue": {"type": "string", "value": ""},
                        "required": True,
                        "minInteger": None,
                    },
                    {
                        "key": "attendee-email",
                        "valueType": "string",
                        "initialValue": {"type": "string", "value": ""},
                        "required": True,
                        "minInteger": None,
                    },
                ],
            }
        ],
        "viewBindingIntents": [
            {
                "key": "event-catalog-rows",
                "pageKey": "event-catalog",
                "target": "tableRows",
                "schemaKey": "event",
                "sortFieldKey": "title",
                "sortDirection": "asc",
            }
        ],
        "behaviorIntents": [
            {
                "key": "submit-registration",
                "sourcePageKey": "event-registration",
                "guard": {"kind": "formValid", "formKey": "event-registration"},
                "effects": [
                    {"kind": "validateForm", "formKey": "event-registration"},
                    {
                        "kind": "createEntity",
                        "schemaKey": "registration",
                        "resultVariableKey": "latest-registration",
                        "values": [
                            {
                                "fieldKey": "attendee-name",
                                "value": {
                                    "kind": "formField",
                                    "formKey": "event-registration",
                                    "fieldKey": "attendee-name",
                                },
                            },
                            {
                                "fieldKey": "attendee-email",
                                "value": {
                                    "kind": "formField",
                                    "formKey": "event-registration",
                                    "fieldKey": "attendee-email",
                                },
                            },
                            {
                                "fieldKey": "status",
                                "value": {
                                    "kind": "literal",
                                    "value": {"type": "enum", "value": "confirmed"},
                                },
                            },
                        ],
                    },
                    {
                        "kind": "notify",
                        "level": "success",
                        "message": "Your place is confirmed",
                    },
                    {"kind": "navigate", "targetPageKey": "event-catalog"},
                ],
                "guardFalseEffects": [
                    {
                        "kind": "notify",
                        "level": "error",
                        "message": "Complete the required fields",
                    }
                ],
            }
        ],
        "scenarioIntents": [
            {
                "key": "visitor-registration",
                "actorRoleKey": "visitor",
                "startPageKey": "event-registration",
                "initialVariables": [],
                "entityFixtures": [
                    {
                        "schemaKey": "event",
                        "entities": [
                            {
                                "key": "open-air-cinema",
                                "fields": [
                                    {
                                        "fieldKey": "title",
                                        "value": {
                                            "type": "string",
                                            "value": "Open-air cinema",
                                        },
                                    },
                                    {
                                        "fieldKey": "venue",
                                        "value": {
                                            "type": "string",
                                            "value": "Riverside Park",
                                        },
                                    },
                                    {
                                        "fieldKey": "seats-available",
                                        "value": {"type": "integer", "value": 24},
                                    },
                                ],
                            }
                        ],
                    }
                ],
                "allowSimulatedRoleSwitch": False,
                "scriptedSteps": [
                    {
                        "kind": "commitFormField",
                        "pageKey": "event-registration",
                        "formKey": "event-registration",
                        "fieldKey": "attendee-name",
                        "value": {"type": "string", "value": "Jamie Rivera"},
                        "expectedOutcome": "applied",
                    },
                    {
                        "kind": "commitFormField",
                        "pageKey": "event-registration",
                        "formKey": "event-registration",
                        "fieldKey": "attendee-email",
                        "value": {
                            "type": "string",
                            "value": "jamie@example.test",
                        },
                        "expectedOutcome": "applied",
                    },
                    {
                        "kind": "activateBehavior",
                        "behaviorIntentKey": "submit-registration",
                        "expectedOutcome": "applied",
                    },
                ],
                "milestones": [
                    {
                        "afterStep": 3,
                        "currentPageKey": "event-catalog",
                        "variableValues": [],
                        "entityFieldValues": [],
                    }
                ],
            }
        ],
        "startPageKeys": ["event-catalog"],
    }


def _events_foundation_payload() -> dict[str, object]:
    return {
        "contractVersion": 3,
        "colors": [
            {"key": "primary", "value": "#006c67"},
            {"key": "surface", "value": "#ffffff"},
            {"key": "accent", "value": "#d94f3d"},
        ],
        "spacing": [{"key": "content-gap", "value": "20px"}],
        "sharedShell": {
            "kind": "topbar",
            "title": "City Weekends",
            "accentColorTokenKey": "accent",
            "navigationBackgroundColorTokenKey": "surface",
            "contentBackgroundColorTokenKey": "surface",
            "surfaceColorTokenKey": "surface",
        },
        "contentConventions": "Use concise, welcoming public-facing language",
    }


def _event_catalog_page_payload() -> dict[str, object]:
    return {
        "contractVersion": 3,
        "pageKey": "event-catalog",
        "title": "Upcoming events",
        "route": "/events",
        "root": {
            "localKey": "catalog-root",
            "name": "Event catalog page",
            "type": "Stack",
            "direction": "column",
            "gap": 20,
            "padding": 24,
            "children": [
                {
                    "localKey": "catalog-heading",
                    "name": "Event catalog heading",
                    "type": "Text",
                    "content": "Find your next local event",
                    "semantic": "heading",
                    "tone": "default",
                },
                {
                    "localKey": "event-table",
                    "name": "Upcoming event directory",
                    "type": "Table",
                    "columns": [
                        {"key": "title", "label": "Event"},
                        {"key": "venue", "label": "Venue"},
                        {"key": "seats-available", "label": "Places left"},
                    ],
                    "rows": [],
                    "density": "comfortable",
                },
            ],
        },
        "formBindings": [],
        "viewBindings": [
            {
                "nodeKey": "event-table",
                "viewBindingIntentKey": "event-catalog-rows",
            }
        ],
        "behaviorBindings": [],
    }


def _event_registration_page_payload() -> dict[str, object]:
    return {
        "contractVersion": 3,
        "pageKey": "event-registration",
        "title": "Event registration",
        "route": "/events/register",
        "root": {
            "localKey": "registration-root",
            "name": "Registration page",
            "type": "Stack",
            "direction": "column",
            "gap": 20,
            "padding": 24,
            "children": [
                {
                    "localKey": "registration-heading",
                    "name": "Registration heading",
                    "type": "Text",
                    "content": "Reserve your place",
                    "semantic": "heading",
                    "tone": "default",
                },
                {
                    "localKey": "registration-form",
                    "name": "Visitor registration form",
                    "type": "Form",
                    "formKey": "event-registration",
                    "gap": 12,
                    "children": [
                        {
                            "localKey": "attendee-name-input",
                            "name": "Attendee name",
                            "type": "Input",
                            "label": "Name",
                            "placeholder": "Jamie Rivera",
                            "inputType": "text",
                            "required": True,
                        },
                        {
                            "localKey": "attendee-email-input",
                            "name": "Attendee email",
                            "type": "Input",
                            "label": "Email",
                            "placeholder": "name@example.com",
                            "inputType": "email",
                            "required": True,
                        },
                        {
                            "localKey": "submit-registration-button",
                            "name": "Submit registration",
                            "type": "Button",
                            "label": "Confirm registration",
                            "variant": "primary",
                        },
                    ],
                },
            ],
        },
        "formBindings": [
            {
                "formNodeKey": "registration-form",
                "formIntentKey": "event-registration",
                "fields": [
                    {
                        "inputNodeKey": "attendee-name-input",
                        "fieldKey": "attendee-name",
                    },
                    {
                        "inputNodeKey": "attendee-email-input",
                        "fieldKey": "attendee-email",
                    },
                ],
            }
        ],
        "viewBindings": [],
        "behaviorBindings": [
            {
                "sourceNodeKey": "submit-registration-button",
                "event": "submit",
                "behaviorIntentKey": "submit-registration",
            }
        ],
    }


def _repository_blueprint_payload() -> dict[str, object]:
    return {
        "contractVersion": 3,
        "documentTitle": "Repository inventory",
        "productIntent": "Inspect discovered project repositories without mutating them",
        "outputLocale": "en-US",
        "foundationIntent": {
            "visualLanguage": "Quiet operational repository inventory",
            "density": "compact",
            "responsiveStrategy": "Single column on mobile with a dense desktop table",
        },
        "pages": [
            {
                "pageKey": "repositories",
                "title": "Repositories",
                "route": "/repositories",
                "purpose": "Browse repositories discovered from project evidence",
                "navigationGroupKey": "project",
            }
        ],
        "navigation": [
            {
                "key": "repositories",
                "label": "Repositories",
                "targetPageKey": "repositories",
            }
        ],
        "flowIntents": [],
        "roleIntents": [],
        "entityIntents": [],
        "variableIntents": [],
        "formIntents": [],
        "viewBindingIntents": [],
        "behaviorIntents": [],
        "scenarioIntents": [],
        "startPageKeys": ["repositories"],
    }


def _repository_foundation_payload() -> dict[str, object]:
    return {
        "contractVersion": 3,
        "colors": [
            {"key": "primary", "value": "#176b5b"},
            {"key": "surface", "value": "#ffffff"},
        ],
        "spacing": [{"key": "content-gap", "value": "16px"}],
        "sharedShell": {
            "kind": "sidebar",
            "title": "Project workspace",
            "accentColorTokenKey": "primary",
            "navigationBackgroundColorTokenKey": "surface",
            "contentBackgroundColorTokenKey": "surface",
            "surfaceColorTokenKey": "surface",
            "navigationWidth": 224,
            "expandedMinWidth": 960,
        },
        "contentConventions": "Use concise repository names and observed stack labels",
    }


def _repository_page_payload() -> dict[str, object]:
    return {
        "contractVersion": 3,
        "pageKey": "repositories",
        "title": "Repositories",
        "route": "/repositories",
        "root": {
            "localKey": "repositories-root",
            "name": "Repository inventory page",
            "type": "Stack",
            "direction": "column",
            "gap": 16,
            "padding": 24,
            "children": [
                {
                    "localKey": "repositories-heading",
                    "name": "Repository inventory heading",
                    "type": "Text",
                    "content": "Project repositories",
                    "semantic": "heading",
                    "tone": "default",
                },
                {
                    "localKey": "repositories-table",
                    "name": "Discovered repositories",
                    "type": "Table",
                    "columns": [
                        {"key": "name", "label": "Repository"},
                        {"key": "stack", "label": "Stack"},
                        {"key": "status", "label": "Status"},
                    ],
                    "rows": [
                        {
                            "localKey": "admin-demo",
                            "cells": [
                                {"columnKey": "name", "value": "admin-demo"},
                                {
                                    "columnKey": "stack",
                                    "value": "Vue 3 + Spring Boot",
                                },
                                {"columnKey": "status", "value": "Ready"},
                            ],
                        }
                    ],
                    "density": "compact",
                },
            ],
        },
        "formBindings": [],
        "viewBindings": [],
        "behaviorBindings": [],
    }


def _renderer_input_manifest(
    worker: PrototypeRendererWorker,
    document_hash_value: str,
) -> dict[str, object]:
    identity = worker.identity
    return {
        "rendererVersion": identity.renderer_version,
        "rendererEnvironmentVersion": identity.renderer_environment_version,
        "runtimeCoreVersion": identity.runtime_core_version,
        "runtimeCoreSourceHash": identity.runtime_core_source_hash,
        "runtimeCoreBundleHash": identity.runtime_core_bundle_hash,
        "stateMachineKernelVersion": identity.state_machine_kernel_version,
        "renderRuntimeImageHash": identity.render_runtime_image_hash,
        "browserVersion": identity.browser_version,
        "fontPackHash": identity.font_pack_hash,
        "viewportProfileHash": identity.viewport_profile_hash,
        "documentObjectHash": document_hash_value,
        "documentSchemaVersion": 1,
        "assetObjectHashes": [],
        "sandboxPolicyVersion": identity.sandbox_policy_version,
        "outputLocale": "en-US",
    }


def _events_artifacts() -> tuple[
    GenerationBlueprintV1,
    GenerationFoundationV1,
    tuple[GeneratedPageV1, ...],
]:
    return (
        GenerationBlueprintV1.model_validate(_events_blueprint_payload(), strict=True),
        GenerationFoundationV1.model_validate(_events_foundation_payload(), strict=True),
        tuple(
            GeneratedPageV1.model_validate(payload, strict=True)
            for payload in (
                _event_catalog_page_payload(),
                _event_registration_page_payload(),
            )
        ),
    )


def test_non_admin_events_fixture_satisfies_contract_and_assembler() -> None:
    blueprint, foundation, pages = _events_artifacts()
    document = assemble_generation_candidate(
        document_id=generation_document_id("city-weekends-generality"),
        blueprint=blueprint,
        foundation=foundation,
        pages=pages,
    )

    variable = document.runtime.variables[0]
    registration_schema = document.runtime.entity_schemas[1]
    assert variable.entity_schema_id == registration_schema.id

    assert document.title == "City Weekends"
    assert [page.key for page in document.pages] == [
        "event-catalog",
        "event-registration",
    ]
    assert [schema.key for schema in document.runtime.entity_schemas] == [
        "event",
        "registration",
    ]
    assert document.runtime.forms[0].key == "event-registration"
    assert document.runtime.view_bindings[0].target == "tableRows"
    assert document.runtime.rules[0].key == "submit-registration"
    assert [effect.kind for effect in document.runtime.rules[0].effects] == [
        "validateForm",
        "createEntity",
        "notify",
        "navigate",
    ]


@pytest.mark.asyncio
async def test_read_only_repository_table_renders_static_rows_without_runtime_intents() -> None:
    blueprint = GenerationBlueprintV1.model_validate(_repository_blueprint_payload(), strict=True)
    foundation = GenerationFoundationV1.model_validate(
        _repository_foundation_payload(), strict=True
    )
    page = GeneratedPageV1.model_validate(_repository_page_payload(), strict=True)
    document_id = generation_document_id("read-only-repository-static-rows")
    document = assemble_generation_candidate(
        document_id=document_id,
        blueprint=blueprint,
        foundation=foundation,
        pages=(page,),
    )

    root = document.pages[0].root
    assert isinstance(root, StackNodeV1)
    table = root.children[1]
    assert isinstance(table, TableNodeV1)
    assert table.rows[0].id == generation_table_row_id(
        document_id,
        "repositories",
        "repositories-table",
        "admin-demo",
    )
    assert [cell.value for cell in table.rows[0].cells] == [
        "admin-demo",
        "Vue 3 + Spring Boot",
        "Ready",
    ]
    assert document.runtime.entity_schemas == []
    assert document.runtime.forms == []
    assert document.runtime.view_bindings == []
    assert document.runtime.rules == []

    worker = PrototypeRendererWorker()
    rendered = await worker.render(
        request_id=generation_document_id("read-only-repository-render-request"),
        artifact_id=generation_document_id("read-only-repository-render-artifact"),
        input_manifest=_renderer_input_manifest(worker, document_hash(document)),
        document=document_payload(document),
    )
    html = next(file.content for file in rendered.files if file.relative_path == "index.html")
    assert b"admin-demo" in html
    assert b"Vue 3 + Spring Boot" in html
    assert b"Ready" in html


def test_non_admin_fixture_projects_both_navigation_branches_without_domain_rules() -> None:
    payload = _events_blueprint_payload()
    behaviors = payload["behaviorIntents"]
    assert isinstance(behaviors, list)
    behavior = behaviors[0]
    assert isinstance(behavior, dict)
    guard_false_effects = behavior["guardFalseEffects"]
    assert isinstance(guard_false_effects, list)
    guard_false_effects.append({"kind": "navigate", "targetPageKey": "event-registration"})
    flows = payload["flowIntents"]
    assert isinstance(flows, list)
    flows.append(
        {
            "key": "registration-invalid-stays",
            "sourcePageKey": "event-registration",
            "behaviorIntentKey": "submit-registration",
            "targetPageKey": "event-registration",
        }
    )
    blueprint = GenerationBlueprintV1.model_validate(payload, strict=True)
    foundation = GenerationFoundationV1.model_validate(_events_foundation_payload(), strict=True)
    pages = tuple(
        GeneratedPageV1.model_validate(page, strict=True)
        for page in (_event_catalog_page_payload(), _event_registration_page_payload())
    )

    document = assemble_generation_candidate(
        document_id=generation_document_id("city-weekends-branching-flow"),
        blueprint=blueprint,
        foundation=foundation,
        pages=pages,
    )

    assert len(document.flows) == 2
    assert document.flows[0].rule_id == document.flows[1].rule_id
    assert {flow.to_page_id for flow in document.flows} == {page.id for page in document.pages}


def test_blueprint_refuses_create_entity_result_variable_schema_drift() -> None:
    payload = _events_blueprint_payload()
    variables = payload["variableIntents"]
    assert isinstance(variables, list)
    variable = variables[0]
    assert isinstance(variable, dict)
    variable["entitySchemaKey"] = "event"

    with pytest.raises(ValueError, match="create-entity result variable must match its schema"):
        GenerationBlueprintV1.model_validate(payload, strict=True)


@pytest.mark.asyncio
async def test_non_admin_events_fixture_replays_confirmed_scenario() -> None:
    blueprint, foundation, pages = _events_artifacts()
    document_id = generation_document_id("city-weekends-runtime")
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
    worker = PrototypeRuntimeWorker()
    definition = document.runtime.model_dump(mode="json", by_alias=True)
    initial = await worker.initialize_state(
        request_id="city-weekends-initialize",
        definition=definition,
        scenario_id=case.scenario_id,
        session_id="city-weekends-session",
    )
    replayed = await worker.replay_event_batches(
        request_id="city-weekends-replay",
        definition=definition,
        state_json=initial.state_json,
        batches=list(case.batches),
    )

    assert [transition.outcome for transition in replayed.transitions] == [
        "applied",
        "applied",
        "applied",
    ]
    final_state = json.loads(replayed.final.state_json)
    assert isinstance(final_state, dict)
    assert final_state["currentPageId"] == document.pages[0].id
    assert replayed.final.state_hash.startswith("sha256:")
