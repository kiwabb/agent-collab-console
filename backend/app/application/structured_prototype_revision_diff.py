"""Deterministic structural diff between two published prototype revisions.

Operates on the canonical document JSON payloads archived in the prototype
object store (camelCase keys), so it never re-validates historical documents
against the current pydantic contracts and works for any pair of revisions
that share document schema version 1.
"""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PrototypePageSummary:
    id: str
    title: str
    route: str


@dataclass(frozen=True, slots=True)
class PrototypePageChange:
    id: str
    title: str
    route: str
    title_changed: bool
    route_changed: bool
    nodes_added: int
    nodes_removed: int
    nodes_modified: int


@dataclass(frozen=True, slots=True)
class PrototypeRevisionDiff:
    identical: bool
    title_from: str | None
    title_to: str | None
    pages_added: tuple[PrototypePageSummary, ...]
    pages_removed: tuple[PrototypePageSummary, ...]
    pages_modified: tuple[PrototypePageChange, ...]
    flows_added: int
    flows_removed: int
    flows_modified: int
    component_definitions_changed: bool
    settings_changed: bool
    tokens_changed: bool
    navigation_changed: bool
    runtime_changed: bool
    asset_refs_added: int
    asset_refs_removed: int


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _page_summary(page: dict[str, object]) -> PrototypePageSummary:
    return PrototypePageSummary(
        id=_string(page.get("id")),
        title=_string(page.get("title")),
        route=_string(page.get("route")),
    )


def _pages_by_id(document: dict[str, object]) -> dict[str, dict[str, object]]:
    pages = document.get("pages")
    result: dict[str, dict[str, object]] = {}
    if not isinstance(pages, list):
        return result
    for page in pages:
        if isinstance(page, dict) and isinstance(page.get("id"), str):
            result[page["id"]] = page
    return result


def _flatten_nodes(root: object) -> dict[str, dict[str, object]]:
    """Flatten a UI node tree into id -> shallow payload.

    The shallow payload replaces each ``children`` list with the ordered list
    of child ids, so a node counts as modified when its own properties or its
    direct child ordering change — without cascading every ancestor of a deep
    edit into the modified set.
    """
    nodes: dict[str, dict[str, object]] = {}

    def walk(node: object) -> None:
        if not isinstance(node, dict):
            return
        node_id = node.get("id")
        if not isinstance(node_id, str):
            return
        shallow: dict[str, object] = {}
        for key, value in node.items():
            if key == "children" and isinstance(value, list):
                shallow[key] = [
                    child.get("id")
                    for child in value
                    if isinstance(child, dict) and isinstance(child.get("id"), str)
                ]
            else:
                shallow[key] = value
        nodes[node_id] = shallow
        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                walk(child)

    walk(root)
    return nodes


def _page_change(
    base_page: dict[str, object],
    target_page: dict[str, object],
) -> PrototypePageChange:
    base_nodes = _flatten_nodes(base_page.get("root"))
    target_nodes = _flatten_nodes(target_page.get("root"))
    added = [node_id for node_id in target_nodes if node_id not in base_nodes]
    removed = [node_id for node_id in base_nodes if node_id not in target_nodes]
    modified = [
        node_id
        for node_id, shallow in target_nodes.items()
        if node_id in base_nodes and base_nodes[node_id] != shallow
    ]
    summary = _page_summary(target_page)
    return PrototypePageChange(
        id=summary.id,
        title=summary.title,
        route=summary.route,
        title_changed=base_page.get("title") != target_page.get("title"),
        route_changed=base_page.get("route") != target_page.get("route"),
        nodes_added=len(added),
        nodes_removed=len(removed),
        nodes_modified=len(modified),
    )


def _identity_counts(
    base_items: object,
    target_items: object,
) -> tuple[int, int, int]:
    def by_id(items: object) -> dict[str, str]:
        result: dict[str, str] = {}
        if not isinstance(items, list):
            return result
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                result[item["id"]] = json.dumps(item, sort_keys=True, ensure_ascii=False)
        return result

    base = by_id(base_items)
    target = by_id(target_items)
    added = sum(1 for item_id in target if item_id not in base)
    removed = sum(1 for item_id in base if item_id not in target)
    modified = sum(
        1 for item_id, payload in target.items() if item_id in base and base[item_id] != payload
    )
    return added, removed, modified


def _set_counts(base_items: object, target_items: object) -> tuple[int, int]:
    def as_set(items: object) -> set[str]:
        if not isinstance(items, list):
            return set()
        return {json.dumps(item, sort_keys=True, ensure_ascii=False) for item in items}

    base = as_set(base_items)
    target = as_set(target_items)
    return len(target - base), len(base - target)


def diff_prototype_documents(
    base: dict[str, object],
    target: dict[str, object],
) -> PrototypeRevisionDiff:
    if base == target:
        return PrototypeRevisionDiff(
            identical=True,
            title_from=None,
            title_to=None,
            pages_added=(),
            pages_removed=(),
            pages_modified=(),
            flows_added=0,
            flows_removed=0,
            flows_modified=0,
            component_definitions_changed=False,
            settings_changed=False,
            tokens_changed=False,
            navigation_changed=False,
            runtime_changed=False,
            asset_refs_added=0,
            asset_refs_removed=0,
        )

    base_pages = _pages_by_id(base)
    target_pages = _pages_by_id(target)
    pages_added = tuple(
        _page_summary(page) for page_id, page in target_pages.items() if page_id not in base_pages
    )
    pages_removed = tuple(
        _page_summary(page) for page_id, page in base_pages.items() if page_id not in target_pages
    )
    pages_modified = tuple(
        _page_change(base_pages[page_id], page)
        for page_id, page in target_pages.items()
        if page_id in base_pages and base_pages[page_id] != page
    )

    flows_added, flows_removed, flows_modified = _identity_counts(
        base.get("flows"),
        target.get("flows"),
    )
    asset_refs_added, asset_refs_removed = _set_counts(
        base.get("assetRefs"),
        target.get("assetRefs"),
    )
    title_changed = base.get("title") != target.get("title")
    return PrototypeRevisionDiff(
        identical=False,
        title_from=_string(base.get("title")) if title_changed else None,
        title_to=_string(target.get("title")) if title_changed else None,
        pages_added=pages_added,
        pages_removed=pages_removed,
        pages_modified=pages_modified,
        flows_added=flows_added,
        flows_removed=flows_removed,
        flows_modified=flows_modified,
        component_definitions_changed=(
            base.get("componentDefinitions") != target.get("componentDefinitions")
        ),
        settings_changed=base.get("settings") != target.get("settings"),
        tokens_changed=base.get("tokens") != target.get("tokens"),
        navigation_changed=base.get("navigation") != target.get("navigation"),
        runtime_changed=base.get("runtime") != target.get("runtime"),
        asset_refs_added=asset_refs_added,
        asset_refs_removed=asset_refs_removed,
    )
