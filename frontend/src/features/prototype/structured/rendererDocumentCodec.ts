import { parseRuntimeDefinition } from "../runtime/runtimeInputCodec";
import type { StructuredPrototypeDocument, StructuredPrototypeNode } from "./types";

export class RendererDocumentCodecError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "RendererDocumentCodecError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function record(value: unknown, path: string): Record<string, unknown> {
  if (!isRecord(value)) throw new RendererDocumentCodecError(`${path} must be an object`);
  return value;
}

function exactKeys(value: Record<string, unknown>, keys: readonly string[], path: string): void {
  const expected = new Set(keys);
  for (const key of Object.keys(value)) {
    if (!expected.has(key)) {
      throw new RendererDocumentCodecError(`${path} contains unknown field ${key}`);
    }
  }
  for (const key of keys) {
    if (!Object.hasOwn(value, key)) {
      throw new RendererDocumentCodecError(`${path} is missing field ${key}`);
    }
  }
}

function string(value: unknown, path: string): string {
  if (typeof value !== "string") throw new RendererDocumentCodecError(`${path} must be a string`);
  return value;
}

function nonEmptyString(value: unknown, path: string): string {
  const parsed = string(value, path);
  if (parsed.length === 0) throw new RendererDocumentCodecError(`${path} must not be empty`);
  return parsed;
}

function boolean(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") {
    throw new RendererDocumentCodecError(`${path} must be a boolean`);
  }
  return value;
}

function integer(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || Object.is(value, -0)) {
    throw new RendererDocumentCodecError(`${path} must be a safe integer`);
  }
  return value;
}

function array(value: unknown, path: string): unknown[] {
  if (!Array.isArray(value)) throw new RendererDocumentCodecError(`${path} must be an array`);
  return value;
}

function literal<const Values extends readonly string[]>(
  value: unknown,
  values: Values,
  path: string,
): Values[number] {
  if (typeof value === "string" && values.includes(value)) return value;
  throw new RendererDocumentCodecError(`${path} has an unsupported value`);
}

function uuid(value: unknown, path: string): string {
  const parsed = string(value, path);
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u.test(parsed)) {
    throw new RendererDocumentCodecError(`${path} must be a canonical UUID`);
  }
  return parsed;
}

function technicalKey(value: unknown, path: string): string {
  const parsed = string(value, path);
  if (!/^[a-z][a-z0-9-]{0,63}$/u.test(parsed)) {
    throw new RendererDocumentCodecError(`${path} must be a technical key`);
  }
  return parsed;
}

function validateLength(value: unknown, path: string): void {
  const item = record(value, path);
  exactKeys(item, ["unit", "value"], path);
  const unit = literal(item["unit"], ["px", "percent", "rem", "auto"] as const, `${path}.unit`);
  if (unit === "auto") {
    if (item["value"] !== null) {
      throw new RendererDocumentCodecError(`${path}.value must be null for auto length`);
    }
    return;
  }
  const parsed = string(item["value"], `${path}.value`);
  if (!/^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,4})?$/u.test(parsed)) {
    throw new RendererDocumentCodecError(`${path}.value must be a canonical decimal`);
  }
}

function validateLayoutUpdate(value: unknown, path: string): void {
  const item = record(value, path);
  const allowed = [
    "width",
    "minWidth",
    "maxWidth",
    "height",
    "minHeight",
    "maxHeight",
    "grow",
    "shrink",
    "alignSelf",
  ] as const;
  for (const key of Object.keys(item)) {
    if (!allowed.includes(key as (typeof allowed)[number])) {
      throw new RendererDocumentCodecError(`${path} contains unknown field ${key}`);
    }
  }
  if (Object.keys(item).length === 0) {
    throw new RendererDocumentCodecError(`${path} must contain an update`);
  }
  for (const key of [
    "width",
    "minWidth",
    "maxWidth",
    "height",
    "minHeight",
    "maxHeight",
  ] as const) {
    if (Object.hasOwn(item, key) && item[key] !== null) validateLength(item[key], `${path}.${key}`);
  }
  for (const key of ["grow", "shrink"] as const) {
    if (Object.hasOwn(item, key)) integer(item[key], `${path}.${key}`);
  }
  if (Object.hasOwn(item, "alignSelf")) {
    literal(
      item["alignSelf"],
      ["auto", "start", "center", "end", "stretch"] as const,
      `${path}.alignSelf`,
    );
  }
}

function validateLayout(value: unknown, path: string): void {
  const item = record(value, path);
  exactKeys(
    item,
    [
      "width",
      "minWidth",
      "maxWidth",
      "height",
      "minHeight",
      "maxHeight",
      "grow",
      "shrink",
      "alignSelf",
    ],
    path,
  );
  validateLength(item["width"], `${path}.width`);
  validateLength(item["height"], `${path}.height`);
  for (const key of ["minWidth", "maxWidth", "minHeight", "maxHeight"] as const) {
    if (item[key] !== null) validateLength(item[key], `${path}.${key}`);
  }
  integer(item["grow"], `${path}.grow`);
  integer(item["shrink"], `${path}.shrink`);
  literal(
    item["alignSelf"],
    ["auto", "start", "center", "end", "stretch"] as const,
    `${path}.alignSelf`,
  );
}

function validatePadding(value: unknown, path: string): void {
  const item = record(value, path);
  exactKeys(item, ["top", "right", "bottom", "left"], path);
  for (const key of ["top", "right", "bottom", "left"] as const)
    integer(item[key], `${path}.${key}`);
}

function validateCommon(item: Record<string, unknown>, path: string): void {
  uuid(item["id"], `${path}.id`);
  nonEmptyString(item["name"], `${path}.name`);
  literal(item["visibility"], ["visible", "hidden"] as const, `${path}.visibility`);
  validateLayout(item["layoutItem"], `${path}.layoutItem`);
  array(item["responsive"], `${path}.responsive`).forEach((override, index) => {
    const responsive = record(override, `${path}.responsive[${index}]`);
    exactKeys(responsive, ["breakpoint", "layoutItem"], `${path}.responsive[${index}]`);
    literal(
      responsive["breakpoint"],
      ["sm", "md", "lg"] as const,
      `${path}.responsive[${index}].breakpoint`,
    );
    validateLayoutUpdate(responsive["layoutItem"], `${path}.responsive[${index}].layoutItem`);
  });
}

function validateTable(value: Record<string, unknown>, path: string): void {
  array(value["columns"], `${path}.columns`).forEach((column, index) => {
    const item = record(column, `${path}.columns[${index}]`);
    exactKeys(item, ["key", "label"], `${path}.columns[${index}]`);
    technicalKey(item["key"], `${path}.columns[${index}].key`);
    nonEmptyString(item["label"], `${path}.columns[${index}].label`);
  });
  array(value["rows"], `${path}.rows`).forEach((row, rowIndex) => {
    const item = record(row, `${path}.rows[${rowIndex}]`);
    exactKeys(item, ["id", "cells"], `${path}.rows[${rowIndex}]`);
    uuid(item["id"], `${path}.rows[${rowIndex}].id`);
    array(item["cells"], `${path}.rows[${rowIndex}].cells`).forEach((cell, cellIndex) => {
      const parsed = record(cell, `${path}.rows[${rowIndex}].cells[${cellIndex}]`);
      exactKeys(parsed, ["columnKey", "value"], `${path}.rows[${rowIndex}].cells[${cellIndex}]`);
      technicalKey(parsed["columnKey"], `${path}.rows[${rowIndex}].cells[${cellIndex}].columnKey`);
      string(parsed["value"], `${path}.rows[${rowIndex}].cells[${cellIndex}].value`);
    });
  });
}

function validateNode(value: unknown, path: string, nodeIds: Set<string>): void {
  const item = record(value, path);
  const type = literal(
    item["type"],
    ["Stack", "Form", "Text", "Input", "Button", "Table"] as const,
    `${path}.type`,
  );
  const common = ["id", "name", "visibility", "layoutItem", "responsive", "type"];
  const fieldsByType = {
    Stack: ["direction", "gap", "align", "justify", "padding", "children"],
    Form: ["formDefinitionId", "gap", "padding", "children"],
    Text: ["content", "semantic", "tone"],
    Input: ["label", "placeholder", "value", "inputType", "required", "disabled"],
    Button: ["label", "variant", "size", "disabled", "iconName"],
    Table: ["columns", "rows", "density"],
  } as const;
  exactKeys(item, [...common, ...fieldsByType[type]], path);
  validateCommon(item, path);
  const nodeId = uuid(item["id"], `${path}.id`);
  if (nodeIds.has(nodeId)) throw new RendererDocumentCodecError(`${path}.id is duplicated`);
  nodeIds.add(nodeId);
  switch (type) {
    case "Stack":
      literal(item["direction"], ["row", "column"] as const, `${path}.direction`);
      integer(item["gap"], `${path}.gap`);
      literal(item["align"], ["start", "center", "end", "stretch"] as const, `${path}.align`);
      literal(item["justify"], ["start", "center", "end", "between"] as const, `${path}.justify`);
      validatePadding(item["padding"], `${path}.padding`);
      array(item["children"], `${path}.children`).forEach((child, index) =>
        validateNode(child, `${path}.children[${index}]`, nodeIds),
      );
      return;
    case "Form":
      uuid(item["formDefinitionId"], `${path}.formDefinitionId`);
      integer(item["gap"], `${path}.gap`);
      validatePadding(item["padding"], `${path}.padding`);
      array(item["children"], `${path}.children`).forEach((child, index) =>
        validateNode(child, `${path}.children[${index}]`, nodeIds),
      );
      return;
    case "Text":
      string(item["content"], `${path}.content`);
      literal(
        item["semantic"],
        ["heading", "body", "label", "caption"] as const,
        `${path}.semantic`,
      );
      literal(
        item["tone"],
        ["default", "muted", "success", "warning", "danger"] as const,
        `${path}.tone`,
      );
      return;
    case "Input":
      nonEmptyString(item["label"], `${path}.label`);
      string(item["placeholder"], `${path}.placeholder`);
      string(item["value"], `${path}.value`);
      literal(item["inputType"], ["text", "number", "email"] as const, `${path}.inputType`);
      boolean(item["required"], `${path}.required`);
      boolean(item["disabled"], `${path}.disabled`);
      return;
    case "Button":
      nonEmptyString(item["label"], `${path}.label`);
      literal(
        item["variant"],
        ["primary", "secondary", "danger", "ghost"] as const,
        `${path}.variant`,
      );
      literal(item["size"], ["small", "medium", "large"] as const, `${path}.size`);
      boolean(item["disabled"], `${path}.disabled`);
      if (item["iconName"] !== null) nonEmptyString(item["iconName"], `${path}.iconName`);
      return;
    case "Table":
      validateTable(item, path);
      literal(item["density"], ["compact", "comfortable"] as const, `${path}.density`);
  }
}

function collectNodes(
  node: StructuredPrototypeNode,
  result: Map<string, StructuredPrototypeNode>,
): void {
  result.set(node.id, node);
  if (node.type === "Stack" || node.type === "Form") {
    for (const child of node.children) collectNodes(child, result);
  }
}

function validateGraph(document: StructuredPrototypeDocument): void {
  const pageIds = new Set(document.pages.map((page) => page.id));
  if (pageIds.size !== document.pages.length)
    throw new RendererDocumentCodecError("pages contain duplicate IDs");
  if (
    document.runtime.pageIds.length !== document.pages.length ||
    document.runtime.pageIds.some((pageId, index) => document.pages[index]?.id !== pageId)
  ) {
    throw new RendererDocumentCodecError("runtime page order must match document page order");
  }
  for (const item of document.navigation.items) {
    if (!pageIds.has(item.targetPageId)) {
      throw new RendererDocumentCodecError(`navigation ${item.id} references an unknown page`);
    }
  }
  const nodes = new Map<string, StructuredPrototypeNode>();
  for (const page of document.pages) collectNodes(page.root, nodes);
  for (const binding of document.runtime.viewBindings) {
    const node = nodes.get(binding.nodeId);
    if (node === undefined)
      throw new RendererDocumentCodecError(`view binding ${binding.id} references an unknown node`);
    if (binding.target === "tableRows" && node.type !== "Table") {
      throw new RendererDocumentCodecError(`view binding ${binding.id} requires a Table node`);
    }
    if (binding.target === "textContent" && node.type !== "Text") {
      throw new RendererDocumentCodecError(`view binding ${binding.id} requires a Text node`);
    }
  }
  for (const rule of document.runtime.rules) {
    const node = nodes.get(rule.trigger.nodeId);
    if (node === undefined)
      throw new RendererDocumentCodecError(`rule ${rule.id} references an unknown node`);
    if (rule.trigger.event === "rowActivated" && node.type !== "Table") {
      throw new RendererDocumentCodecError(`rule ${rule.id} row activation requires a Table node`);
    }
    if (
      (rule.trigger.event === "click" || rule.trigger.event === "submit") &&
      node.type !== "Button"
    ) {
      throw new RendererDocumentCodecError(`rule ${rule.id} activation requires a Button node`);
    }
  }
}

export function parseRendererDocument(value: unknown): StructuredPrototypeDocument {
  const item = record(value, "document");
  exactKeys(
    item,
    [
      "schemaVersion",
      "id",
      "title",
      "locale",
      "settings",
      "tokens",
      "componentDefinitions",
      "pages",
      "navigation",
      "flows",
      "runtime",
      "assetRefs",
    ],
    "document",
  );
  if (item["schemaVersion"] !== 1)
    throw new RendererDocumentCodecError("document.schemaVersion must equal 1");
  uuid(item["id"], "document.id");
  nonEmptyString(item["title"], "document.title");
  literal(item["locale"], ["zh-CN", "en-US"] as const, "document.locale");
  const settings = record(item["settings"], "document.settings");
  exactKeys(settings, ["defaultViewport", "theme"], "document.settings");
  literal(
    settings["defaultViewport"],
    ["desktop", "tablet", "mobile"] as const,
    "document.settings.defaultViewport",
  );
  literal(settings["theme"], ["light", "dark", "system"] as const, "document.settings.theme");
  const tokens = record(item["tokens"], "document.tokens");
  exactKeys(tokens, ["colors", "spacing"], "document.tokens");
  for (const group of ["colors", "spacing"] as const) {
    array(tokens[group], `document.tokens.${group}`).forEach((token, index) => {
      const parsed = record(token, `document.tokens.${group}[${index}]`);
      exactKeys(parsed, ["key", "value"], `document.tokens.${group}[${index}]`);
      technicalKey(parsed["key"], `document.tokens.${group}[${index}].key`);
      nonEmptyString(parsed["value"], `document.tokens.${group}[${index}].value`);
    });
  }
  const nodeIds = new Set<string>();
  array(item["componentDefinitions"], "document.componentDefinitions").forEach(
    (definition, index) => {
      const parsed = record(definition, `document.componentDefinitions[${index}]`);
      exactKeys(parsed, ["id", "key", "root"], `document.componentDefinitions[${index}]`);
      uuid(parsed["id"], `document.componentDefinitions[${index}].id`);
      technicalKey(parsed["key"], `document.componentDefinitions[${index}].key`);
      validateNode(parsed["root"], `document.componentDefinitions[${index}].root`, nodeIds);
    },
  );
  array(item["pages"], "document.pages").forEach((page, index) => {
    const parsed = record(page, `document.pages[${index}]`);
    exactKeys(
      parsed,
      ["id", "key", "title", "route", "viewport", "root"],
      `document.pages[${index}]`,
    );
    uuid(parsed["id"], `document.pages[${index}].id`);
    technicalKey(parsed["key"], `document.pages[${index}].key`);
    nonEmptyString(parsed["title"], `document.pages[${index}].title`);
    const route = string(parsed["route"], `document.pages[${index}].route`);
    if (!/^\/(?:[A-Za-z0-9._~-]+(?:\/[A-Za-z0-9._~-]+)*)?$/u.test(route)) {
      throw new RendererDocumentCodecError(`document.pages[${index}].route is invalid`);
    }
    const viewport = record(parsed["viewport"], `document.pages[${index}].viewport`);
    exactKeys(viewport, ["width", "height"], `document.pages[${index}].viewport`);
    integer(viewport["width"], `document.pages[${index}].viewport.width`);
    integer(viewport["height"], `document.pages[${index}].viewport.height`);
    validateNode(parsed["root"], `document.pages[${index}].root`, nodeIds);
  });
  const navigation = record(item["navigation"], "document.navigation");
  exactKeys(navigation, ["items"], "document.navigation");
  array(navigation["items"], "document.navigation.items").forEach((entry, index) => {
    const parsed = record(entry, `document.navigation.items[${index}]`);
    exactKeys(
      parsed,
      ["id", "key", "label", "targetPageId"],
      `document.navigation.items[${index}]`,
    );
    uuid(parsed["id"], `document.navigation.items[${index}].id`);
    technicalKey(parsed["key"], `document.navigation.items[${index}].key`);
    nonEmptyString(parsed["label"], `document.navigation.items[${index}].label`);
    uuid(parsed["targetPageId"], `document.navigation.items[${index}].targetPageId`);
  });
  array(item["flows"], "document.flows").forEach((flow, index) => {
    const parsed = record(flow, `document.flows[${index}]`);
    exactKeys(
      parsed,
      ["id", "key", "ruleId", "fromNodeId", "toPageId"],
      `document.flows[${index}]`,
    );
    uuid(parsed["id"], `document.flows[${index}].id`);
    technicalKey(parsed["key"], `document.flows[${index}].key`);
    uuid(parsed["ruleId"], `document.flows[${index}].ruleId`);
    uuid(parsed["fromNodeId"], `document.flows[${index}].fromNodeId`);
    if (parsed["toPageId"] !== null) uuid(parsed["toPageId"], `document.flows[${index}].toPageId`);
  });
  const runtime = parseRuntimeDefinition(item["runtime"]);
  array(item["assetRefs"], "document.assetRefs").forEach((asset, index) => {
    const parsed = record(asset, `document.assetRefs[${index}]`);
    exactKeys(parsed, ["id", "contentHash", "mediaType", "alt"], `document.assetRefs[${index}]`);
    uuid(parsed["id"], `document.assetRefs[${index}].id`);
    const hash = string(parsed["contentHash"], `document.assetRefs[${index}].contentHash`);
    if (!/^sha256:[0-9a-f]{64}$/u.test(hash))
      throw new RendererDocumentCodecError(`document.assetRefs[${index}].contentHash is invalid`);
    literal(
      parsed["mediaType"],
      ["image/png", "image/jpeg", "image/webp", "image/svg+xml"] as const,
      `document.assetRefs[${index}].mediaType`,
    );
    string(parsed["alt"], `document.assetRefs[${index}].alt`);
  });
  const parsed = structuredClone({ ...item, runtime }) as StructuredPrototypeDocument;
  validateGraph(parsed);
  return parsed;
}
