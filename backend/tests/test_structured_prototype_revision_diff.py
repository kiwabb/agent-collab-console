from __future__ import annotations

from app.application.structured_prototype_revision_diff import diff_prototype_documents


def _node(node_id: str, *, name: str = "n", children: list[dict[str, object]] | None = None) -> dict[str, object]:
    payload: dict[str, object] = {"id": node_id, "type": "Stack", "name": name}
    if children is not None:
        payload["children"] = children
    return payload


def _document(pages: list[dict[str, object]], **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schemaVersion": 1,
        "id": "doc-1",
        "title": "采购原型",
        "settings": {"theme": "light"},
        "tokens": {"colors": []},
        "componentDefinitions": [],
        "pages": pages,
        "navigation": {"items": []},
        "flows": [],
        "runtime": {"entities": []},
        "assetRefs": [],
    }
    payload.update(overrides)
    return payload


def _page(page_id: str, *, title: str, route: str, root: dict[str, object]) -> dict[str, object]:
    return {"id": page_id, "title": title, "route": route, "root": root}


def test_identical_documents_short_circuit() -> None:
    document = _document([_page("p1", title="列表", route="/list", root=_node("r1"))])
    diff = diff_prototype_documents(document, dict(document))
    assert diff.identical is True
    assert diff.pages_added == ()
    assert diff.pages_modified == ()


def test_page_add_remove_and_node_counts() -> None:
    base = _document(
        [
            _page(
                "p1",
                title="列表",
                route="/list",
                root=_node("r1", children=[_node("a"), _node("b")]),
            ),
            _page("p2", title="详情", route="/detail", root=_node("r2")),
        ]
    )
    target = _document(
        [
            _page(
                "p1",
                title="列表页",
                route="/list",
                root=_node("r1", children=[_node("a", name="改名"), _node("c")]),
            ),
            _page("p3", title="新建", route="/create", root=_node("r3")),
        ]
    )
    diff = diff_prototype_documents(base, target)
    assert diff.identical is False
    assert [page.id for page in diff.pages_added] == ["p3"]
    assert [page.id for page in diff.pages_removed] == ["p2"]
    assert len(diff.pages_modified) == 1
    changed = diff.pages_modified[0]
    assert changed.id == "p1"
    assert changed.title_changed is True
    assert changed.route_changed is False
    # c added, b removed; r1's child-id list changed and a was renamed.
    assert changed.nodes_added == 1
    assert changed.nodes_removed == 1
    assert changed.nodes_modified == 2


def test_child_reorder_marks_only_parent_modified() -> None:
    base = _document(
        [
            _page(
                "p1",
                title="列表",
                route="/list",
                root=_node("r1", children=[_node("a"), _node("b")]),
            )
        ]
    )
    target = _document(
        [
            _page(
                "p1",
                title="列表",
                route="/list",
                root=_node("r1", children=[_node("b"), _node("a")]),
            )
        ]
    )
    diff = diff_prototype_documents(base, target)
    changed = diff.pages_modified[0]
    assert changed.nodes_added == 0
    assert changed.nodes_removed == 0
    assert changed.nodes_modified == 1


def test_deep_edit_does_not_cascade_into_ancestors() -> None:
    base = _document(
        [
            _page(
                "p1",
                title="列表",
                route="/list",
                root=_node("r1", children=[_node("mid", children=[_node("leaf", name="旧")])]),
            )
        ]
    )
    target = _document(
        [
            _page(
                "p1",
                title="列表",
                route="/list",
                root=_node("r1", children=[_node("mid", children=[_node("leaf", name="新")])]),
            )
        ]
    )
    diff = diff_prototype_documents(base, target)
    changed = diff.pages_modified[0]
    assert changed.nodes_modified == 1
    assert changed.nodes_added == 0
    assert changed.nodes_removed == 0


def test_global_sections_and_collections() -> None:
    base = _document(
        [_page("p1", title="列表", route="/list", root=_node("r1"))],
        flows=[{"id": "f1", "name": "提交"}, {"id": "f2", "name": "审批"}],
        assetRefs=[{"contentHash": "sha256:" + "a" * 64}],
    )
    target = _document(
        [_page("p1", title="列表", route="/list", root=_node("r1"))],
        title="采购原型 v2",
        flows=[{"id": "f1", "name": "提交修订"}, {"id": "f3", "name": "驳回"}],
        tokens={"colors": [{"key": "primary"}]},
        assetRefs=[{"contentHash": "sha256:" + "b" * 64}],
    )
    diff = diff_prototype_documents(base, target)
    assert diff.title_from == "采购原型"
    assert diff.title_to == "采购原型 v2"
    assert (diff.flows_added, diff.flows_removed, diff.flows_modified) == (1, 1, 1)
    assert diff.tokens_changed is True
    assert diff.settings_changed is False
    assert diff.navigation_changed is False
    assert diff.runtime_changed is False
    assert diff.component_definitions_changed is False
    assert (diff.asset_refs_added, diff.asset_refs_removed) == (1, 1)
    assert diff.pages_modified == ()
