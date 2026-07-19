import { parseRuntimeDefinition } from "../runtime/runtimeInputCodec";
import type { RuntimeDefinition } from "../runtime/types";
import { isStructuredPrototypeContainerNode } from "./structuredPrototypeNodes";
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

function exactKeys(
  value: Record<string, unknown>,
  keys: readonly string[],
  path: string,
  optionalKeys: readonly string[] = [],
): void {
  const expected = new Set([...keys, ...optionalKeys]);
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

function canonicalNonNegativeDecimal(value: unknown, path: string): number {
  const parsed = string(value, path);
  if (!/^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,4})?$/u.test(parsed)) {
    throw new RendererDocumentCodecError(`${path} must be a canonical non-negative decimal`);
  }
  const numeric = Number(parsed);
  if (numeric > 4096) {
    throw new RendererDocumentCodecError(`${path} must not exceed 4096`);
  }
  return numeric;
}

function canonicalPositiveDecimal(value: unknown, path: string): number {
  const numeric = canonicalNonNegativeDecimal(value, path);
  if (numeric <= 0) {
    throw new RendererDocumentCodecError(`${path} must be positive`);
  }
  return numeric;
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

function boundedNonEmptyString(value: unknown, maximumLength: number, path: string): string {
  const parsed = nonEmptyString(value, path);
  if (parsed.length > maximumLength) {
    throw new RendererDocumentCodecError(
      `${path} must contain at most ${maximumLength} characters`,
    );
  }
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

function boundedInteger(value: unknown, minimum: number, maximum: number, path: string): number {
  const parsed = integer(value, path);
  if (parsed < minimum || parsed > maximum) {
    throw new RendererDocumentCodecError(`${path} must be between ${minimum} and ${maximum}`);
  }
  return parsed;
}

function array(value: unknown, path: string): unknown[] {
  if (!Array.isArray(value)) throw new RendererDocumentCodecError(`${path} must be an array`);
  return value;
}

function boundedArray(
  value: unknown,
  minimumLength: number,
  maximumLength: number,
  path: string,
): unknown[] {
  const parsed = array(value, path);
  if (parsed.length < minimumLength || parsed.length > maximumLength) {
    throw new RendererDocumentCodecError(
      `${path} must contain between ${minimumLength} and ${maximumLength} items`,
    );
  }
  return parsed;
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

function registerEntityId(value: unknown, path: string, entityIds: Set<string>): string {
  const id = uuid(value, path);
  if (entityIds.has(id)) throw new RendererDocumentCodecError(`${path} is duplicated`);
  entityIds.add(id);
  return id;
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
  const numeric = Number(parsed);
  if (unit === "percent" && numeric > 100) {
    throw new RendererDocumentCodecError(`${path}.value must not exceed 100 for percent length`);
  }
  if (unit === "px" && numeric > 4096) {
    throw new RendererDocumentCodecError(`${path}.value must not exceed 4096 for px length`);
  }
  if (unit === "rem" && numeric > 256) {
    throw new RendererDocumentCodecError(`${path}.value must not exceed 256 for rem length`);
  }
}

function validatePosition(value: unknown, path: string): void {
  const item = record(value, path);
  exactKeys(item, ["x", "y"], path);
  for (const axis of ["x", "y"] as const) {
    canonicalNonNegativeDecimal(item[axis], `${path}.${axis}`);
  }
}

function validateFreeformGrids(
  value: unknown,
  path: string,
  width: number,
  height: number,
  entityIds: Set<string>,
  colorTokenKeys: ReadonlySet<string>,
): void {
  const grids = value === undefined ? [] : boundedArray(value, 0, 8, path);
  grids.forEach((grid, index) => {
    const gridPath = `${path}[${index}]`;
    const item = record(grid, gridPath);
    exactKeys(
      item,
      ["id", "version", "type", "visible", "snapEnabled", "origin", "params"],
      gridPath,
    );
    registerEntityId(item["id"], `${gridPath}.id`, entityIds);
    if (item["version"] !== 1) {
      throw new RendererDocumentCodecError(`${gridPath}.version must equal 1`);
    }
    const type = literal(item["type"], ["square", "columns", "rows"] as const, `${gridPath}.type`);
    boolean(item["visible"], `${gridPath}.visible`);
    boolean(item["snapEnabled"], `${gridPath}.snapEnabled`);
    validatePosition(item["origin"], `${gridPath}.origin`);
    const origin = record(item["origin"], `${gridPath}.origin`);
    const originX = Number(origin["x"]);
    const originY = Number(origin["y"]);
    if (originX >= width || originY >= height) {
      throw new RendererDocumentCodecError(`${gridPath}.origin must remain inside its Freeform`);
    }
    const params = record(item["params"], `${gridPath}.params`);
    const validatePresentation = (): void => {
      const colorTokenKey = technicalKey(
        params["colorTokenKey"],
        `${gridPath}.params.colorTokenKey`,
      );
      if (!colorTokenKeys.has(colorTokenKey)) {
        throw new RendererDocumentCodecError(
          `${gridPath}.params.colorTokenKey references an unknown color token`,
        );
      }
      const opacity = canonicalNonNegativeDecimal(params["opacity"], `${gridPath}.params.opacity`);
      if (opacity > 1) {
        throw new RendererDocumentCodecError(`${gridPath}.params.opacity must be between 0 and 1`);
      }
    };
    if (type === "square") {
      exactKeys(params, ["size", "colorTokenKey", "opacity"], `${gridPath}.params`);
      const size = canonicalPositiveDecimal(params["size"], `${gridPath}.params.size`);
      if (originX + size > width || originY + size > height) {
        throw new RendererDocumentCodecError(`${gridPath} does not fit inside its Freeform`);
      }
      validatePresentation();
      return;
    }
    exactKeys(
      params,
      ["count", "itemSize", "gutter", "margin", "alignment", "colorTokenKey", "opacity"],
      `${gridPath}.params`,
    );
    const count = boundedInteger(params["count"], 1, 24, `${gridPath}.params.count`);
    const gutter = canonicalNonNegativeDecimal(params["gutter"], `${gridPath}.params.gutter`);
    const margin = canonicalNonNegativeDecimal(params["margin"], `${gridPath}.params.margin`);
    const alignment = literal(
      params["alignment"],
      ["stretch", "start", "center", "end"] as const,
      `${gridPath}.params.alignment`,
    );
    const itemSize =
      params["itemSize"] === null
        ? null
        : canonicalPositiveDecimal(params["itemSize"], `${gridPath}.params.itemSize`);
    if ((alignment === "stretch") !== (itemSize === null)) {
      throw new RendererDocumentCodecError(
        `${gridPath}.params.itemSize must be null only for stretch alignment`,
      );
    }
    const axisLength = type === "columns" ? width - originX : height - originY;
    const occupiedWithoutItems = margin * 2 + gutter * (count - 1);
    const available = axisLength - occupiedWithoutItems;
    if (available <= 0 || (itemSize !== null && itemSize * count > available)) {
      throw new RendererDocumentCodecError(`${gridPath} does not fit inside its Freeform`);
    }
    validatePresentation();
  });
}

function validateLayoutUpdate(value: unknown, path: string, allowPosition = false): void {
  const item = record(value, path);
  const allowed = new Set<string>([
    "width",
    "minWidth",
    "maxWidth",
    "height",
    "minHeight",
    "maxHeight",
    "grow",
    "shrink",
    "alignSelf",
    ...(allowPosition ? ["position"] : []),
  ]);
  for (const key of Object.keys(item)) {
    if (!allowed.has(key)) {
      throw new RendererDocumentCodecError(`${path} contains unknown field ${key}`);
    }
  }
  if (Object.keys(item).length === 0) {
    throw new RendererDocumentCodecError(`${path} must contain an update`);
  }
  for (const key of ["width", "height"] as const) {
    if (Object.hasOwn(item, key)) validateLength(item[key], `${path}.${key}`);
  }
  for (const key of ["minWidth", "maxWidth", "minHeight", "maxHeight"] as const) {
    if (Object.hasOwn(item, key) && item[key] !== null) validateLength(item[key], `${path}.${key}`);
  }
  for (const key of ["grow", "shrink"] as const) {
    if (Object.hasOwn(item, key)) boundedInteger(item[key], 0, 12, `${path}.${key}`);
  }
  if (Object.hasOwn(item, "alignSelf")) {
    literal(
      item["alignSelf"],
      ["auto", "start", "center", "end", "stretch"] as const,
      `${path}.alignSelf`,
    );
  }
  if (Object.hasOwn(item, "position")) {
    if (item["position"] !== null) validatePosition(item["position"], `${path}.position`);
  }
}

function validateLayout(value: unknown, path: string): void {
  const item = record(value, path);
  const required = [
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
  const allowed = [...required, "position"] as const;
  for (const key of Object.keys(item)) {
    if (!allowed.includes(key as (typeof allowed)[number])) {
      throw new RendererDocumentCodecError(`${path} contains unknown field ${key}`);
    }
  }
  for (const key of required) {
    if (!Object.hasOwn(item, key)) {
      throw new RendererDocumentCodecError(`${path} is missing field ${key}`);
    }
  }
  validateLength(item["width"], `${path}.width`);
  validateLength(item["height"], `${path}.height`);
  for (const key of ["minWidth", "maxWidth", "minHeight", "maxHeight"] as const) {
    if (item[key] !== null) validateLength(item[key], `${path}.${key}`);
  }
  boundedInteger(item["grow"], 0, 12, `${path}.grow`);
  boundedInteger(item["shrink"], 0, 12, `${path}.shrink`);
  literal(
    item["alignSelf"],
    ["auto", "start", "center", "end", "stretch"] as const,
    `${path}.alignSelf`,
  );
  if (Object.hasOwn(item, "position")) validatePosition(item["position"], `${path}.position`);
}

function validatePadding(value: unknown, path: string): void {
  const item = record(value, path);
  exactKeys(item, ["top", "right", "bottom", "left"], path);
  for (const key of ["top", "right", "bottom", "left"] as const)
    boundedInteger(item[key], 0, 256, `${path}.${key}`);
}

function validateCommon(item: Record<string, unknown>, path: string): void {
  uuid(item["id"], `${path}.id`);
  boundedNonEmptyString(item["name"], 80, `${path}.name`);
  literal(item["visibility"], ["visible", "hidden"] as const, `${path}.visibility`);
  validateLayout(item["layoutItem"], `${path}.layoutItem`);
  const breakpoints = new Set<string>();
  const breakpointOrder = { sm: 0, md: 1, lg: 2 } as const;
  let previousBreakpointOrder = -1;
  boundedArray(item["responsive"], 0, 3, `${path}.responsive`).forEach((override, index) => {
    const responsive = record(override, `${path}.responsive[${index}]`);
    exactKeys(responsive, ["breakpoint", "layoutItem"], `${path}.responsive[${index}]`);
    const breakpoint = literal(
      responsive["breakpoint"],
      ["sm", "md", "lg"] as const,
      `${path}.responsive[${index}].breakpoint`,
    );
    if (breakpoints.has(breakpoint)) {
      throw new RendererDocumentCodecError(`${path}.responsive contains duplicate breakpoint`);
    }
    if (breakpointOrder[breakpoint] <= previousBreakpointOrder) {
      throw new RendererDocumentCodecError(
        `${path}.responsive must use strictly increasing breakpoint order`,
      );
    }
    breakpoints.add(breakpoint);
    previousBreakpointOrder = breakpointOrder[breakpoint];
    validateLayoutUpdate(responsive["layoutItem"], `${path}.responsive[${index}].layoutItem`);
  });
}

function validateTable(value: Record<string, unknown>, path: string, entityIds: Set<string>): void {
  array(value["columns"], `${path}.columns`).forEach((column, index) => {
    const item = record(column, `${path}.columns[${index}]`);
    exactKeys(item, ["key", "label", "fieldId"], `${path}.columns[${index}]`);
    technicalKey(item["key"], `${path}.columns[${index}].key`);
    nonEmptyString(item["label"], `${path}.columns[${index}].label`);
    if (item["fieldId"] !== null) uuid(item["fieldId"], `${path}.columns[${index}].fieldId`);
  });
  array(value["rows"], `${path}.rows`).forEach((row, rowIndex) => {
    const item = record(row, `${path}.rows[${rowIndex}]`);
    exactKeys(item, ["id", "cells"], `${path}.rows[${rowIndex}]`);
    registerEntityId(item["id"], `${path}.rows[${rowIndex}].id`, entityIds);
    array(item["cells"], `${path}.rows[${rowIndex}].cells`).forEach((cell, cellIndex) => {
      const parsed = record(cell, `${path}.rows[${rowIndex}].cells[${cellIndex}]`);
      exactKeys(parsed, ["columnKey", "value"], `${path}.rows[${rowIndex}].cells[${cellIndex}]`);
      technicalKey(parsed["columnKey"], `${path}.rows[${rowIndex}].cells[${cellIndex}].columnKey`);
      string(parsed["value"], `${path}.rows[${rowIndex}].cells[${cellIndex}].value`);
    });
  });
}

type NodePositionPolicy = "forbidden" | "required" | "optional";

function validateNodeChildren(
  value: unknown,
  path: string,
  entityIds: Set<string>,
  minimumLength: number,
  maximumLength: number,
  positionPolicy: NodePositionPolicy,
  colorTokenKeys: ReadonlySet<string>,
): void {
  const children = array(value, path);
  if (children.length < minimumLength || children.length > maximumLength) {
    throw new RendererDocumentCodecError(
      `${path} must contain between ${minimumLength} and ${maximumLength} items`,
    );
  }
  children.forEach((child, index) =>
    validateNode(child, `${path}[${index}]`, entityIds, positionPolicy, colorTokenKeys),
  );
}

function validateNode(
  value: unknown,
  path: string,
  entityIds: Set<string>,
  positionPolicy: NodePositionPolicy,
  colorTokenKeys: ReadonlySet<string>,
): void {
  const item = record(value, path);
  const type = literal(
    item["type"],
    ["Freeform", "Stack", "Grid", "Form", "Text", "Input", "Button", "Table"] as const,
    `${path}.type`,
  );
  const common = ["id", "name", "visibility", "layoutItem", "responsive", "type"];
  const fieldsByType = {
    Freeform: ["children"],
    Stack: ["direction", "gap", "align", "justify", "padding", "children"],
    Grid: ["columns", "gap", "padding", "columnOverrides", "children"],
    Form: ["formDefinitionId", "gap", "padding", "children"],
    Text: ["content", "semantic", "tone"],
    Input: [
      "label",
      "placeholder",
      "value",
      "inputType",
      "required",
      "disabled",
      "formDefinitionId",
      "formFieldId",
    ],
    Button: ["label", "variant", "size", "disabled", "iconName"],
    Table: ["columns", "rows", "density"],
  } as const;
  exactKeys(item, [...common, ...fieldsByType[type]], path, type === "Freeform" ? ["grids"] : []);
  validateCommon(item, path);
  const layoutItem = record(item["layoutItem"], `${path}.layoutItem`);
  const hasPosition = Object.hasOwn(layoutItem, "position");
  if (positionPolicy === "required" && !hasPosition) {
    throw new RendererDocumentCodecError(
      `${path}.layoutItem.position is required inside a Freeform container`,
    );
  }
  if (positionPolicy === "forbidden" && hasPosition) {
    throw new RendererDocumentCodecError(
      `${path}.layoutItem.position is forbidden on a document or component root`,
    );
  }
  registerEntityId(item["id"], `${path}.id`, entityIds);
  switch (type) {
    case "Freeform": {
      const width = record(layoutItem["width"], `${path}.layoutItem.width`);
      const height = record(layoutItem["height"], `${path}.layoutItem.height`);
      if (
        width["unit"] !== "px" ||
        height["unit"] !== "px" ||
        Number(width["value"]) <= 0 ||
        Number(height["value"]) <= 0
      ) {
        throw new RendererDocumentCodecError(
          `${path} Freeform width and height must be non-zero px lengths`,
        );
      }
      const widthValue = Number(width["value"]);
      const heightValue = Number(height["value"]);
      validateFreeformGrids(
        item["grids"],
        `${path}.grids`,
        widthValue,
        heightValue,
        entityIds,
        colorTokenKeys,
      );
      validateNodeChildren(
        item["children"],
        `${path}.children`,
        entityIds,
        0,
        500,
        "required",
        colorTokenKeys,
      );
      return;
    }
    case "Stack":
      literal(item["direction"], ["row", "column"] as const, `${path}.direction`);
      boundedInteger(item["gap"], 0, 128, `${path}.gap`);
      literal(item["align"], ["start", "center", "end", "stretch"] as const, `${path}.align`);
      literal(item["justify"], ["start", "center", "end", "between"] as const, `${path}.justify`);
      validatePadding(item["padding"], `${path}.padding`);
      validateNodeChildren(
        item["children"],
        `${path}.children`,
        entityIds,
        0,
        500,
        "optional",
        colorTokenKeys,
      );
      return;
    case "Grid": {
      boundedInteger(item["columns"], 1, 12, `${path}.columns`);
      boundedInteger(item["gap"], 0, 128, `${path}.gap`);
      validatePadding(item["padding"], `${path}.padding`);
      const overrides = array(item["columnOverrides"], `${path}.columnOverrides`);
      if (overrides.length > 3) {
        throw new RendererDocumentCodecError(
          `${path}.columnOverrides must contain at most 3 items`,
        );
      }
      let previousMinWidth: number | null = null;
      overrides.forEach((override, index) => {
        const overridePath = `${path}.columnOverrides[${index}]`;
        const parsed = record(override, overridePath);
        exactKeys(parsed, ["minWidth", "columns"], overridePath);
        const minWidth = boundedInteger(parsed["minWidth"], 320, 2560, `${overridePath}.minWidth`);
        boundedInteger(parsed["columns"], 1, 12, `${overridePath}.columns`);
        if (previousMinWidth !== null && minWidth <= previousMinWidth) {
          throw new RendererDocumentCodecError(
            `${path}.columnOverrides must use strictly increasing minWidth values`,
          );
        }
        previousMinWidth = minWidth;
      });
      validateNodeChildren(
        item["children"],
        `${path}.children`,
        entityIds,
        0,
        500,
        "optional",
        colorTokenKeys,
      );
      return;
    }
    case "Form":
      uuid(item["formDefinitionId"], `${path}.formDefinitionId`);
      boundedInteger(item["gap"], 0, 128, `${path}.gap`);
      validatePadding(item["padding"], `${path}.padding`);
      validateNodeChildren(
        item["children"],
        `${path}.children`,
        entityIds,
        1,
        200,
        "optional",
        colorTokenKeys,
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
      if ((item["formDefinitionId"] === null) !== (item["formFieldId"] === null)) {
        throw new RendererDocumentCodecError(`${path} form bindings must be supplied together`);
      }
      if (item["formDefinitionId"] !== null)
        uuid(item["formDefinitionId"], `${path}.formDefinitionId`);
      if (item["formFieldId"] !== null) uuid(item["formFieldId"], `${path}.formFieldId`);
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
      validateTable(item, path, entityIds);
      literal(item["density"], ["compact", "comfortable"] as const, `${path}.density`);
  }
}

function collectNodes(
  node: StructuredPrototypeNode,
  result: Map<string, StructuredPrototypeNode>,
): void {
  result.set(node.id, node);
  if (isStructuredPrototypeContainerNode(node)) {
    for (const child of node.children) collectNodes(child, result);
  }
}

function validateShell(value: unknown): string[] {
  const shell = record(value, "document.settings.shell");
  const kind = literal(
    shell["kind"],
    ["sidebar", "topbar"] as const,
    "document.settings.shell.kind",
  );
  const commonKeys = [
    "kind",
    "title",
    "accentColorTokenKey",
    "navigationBackgroundColorTokenKey",
    "contentBackgroundColorTokenKey",
    "surfaceColorTokenKey",
  ] as const;
  exactKeys(
    shell,
    kind === "sidebar" ? [...commonKeys, "navigationWidth", "expandedMinWidth"] : commonKeys,
    "document.settings.shell",
  );
  boundedNonEmptyString(shell["title"], 80, "document.settings.shell.title");
  const tokenKeys = [
    technicalKey(shell["accentColorTokenKey"], "document.settings.shell.accentColorTokenKey"),
    technicalKey(
      shell["navigationBackgroundColorTokenKey"],
      "document.settings.shell.navigationBackgroundColorTokenKey",
    ),
    technicalKey(
      shell["contentBackgroundColorTokenKey"],
      "document.settings.shell.contentBackgroundColorTokenKey",
    ),
    technicalKey(shell["surfaceColorTokenKey"], "document.settings.shell.surfaceColorTokenKey"),
  ];
  if (kind === "sidebar") {
    boundedInteger(shell["navigationWidth"], 160, 400, "document.settings.shell.navigationWidth");
    boundedInteger(
      shell["expandedMinWidth"],
      320,
      2560,
      "document.settings.shell.expandedMinWidth",
    );
  }
  return tokenKeys;
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
  for (const definition of document.componentDefinitions) collectNodes(definition.root, nodes);
  const schemasById = new Map(document.runtime.entitySchemas.map((schema) => [schema.id, schema]));
  const viewBindingTargets = new Set<string>();
  for (const binding of document.runtime.viewBindings) {
    const bindingTarget = `${binding.nodeId}:${binding.target}`;
    if (viewBindingTargets.has(bindingTarget)) {
      throw new RendererDocumentCodecError(
        `view bindings contain duplicate node target ${bindingTarget}`,
      );
    }
    viewBindingTargets.add(bindingTarget);
    const node = nodes.get(binding.nodeId);
    if (node === undefined)
      throw new RendererDocumentCodecError(`view binding ${binding.id} references an unknown node`);
    if (binding.target === "tableRows" && node.type !== "Table") {
      throw new RendererDocumentCodecError(`view binding ${binding.id} requires a Table node`);
    }
    if (binding.target === "tableRows" && node.type === "Table") {
      const schema = schemasById.get(binding.schemaId);
      if (schema === undefined) {
        throw new RendererDocumentCodecError(
          `view binding ${binding.id} references an unknown schema`,
        );
      }
      const schemaFieldIds = new Set(schema.fields.map((field) => field.id));
      for (const column of node.columns) {
        if (column.fieldId === null) {
          throw new RendererDocumentCodecError(
            `runtime table ${node.id} column ${column.key} requires a schema field`,
          );
        }
        if (!schemaFieldIds.has(column.fieldId)) {
          throw new RendererDocumentCodecError(
            `runtime table ${node.id} column ${column.key} field is not in its binding schema`,
          );
        }
      }
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

function registerRuntimeEntityIds(runtime: RuntimeDefinition, entityIds: Set<string>): void {
  runtime.roles.forEach((role, index) =>
    registerEntityId(role.id, `document.runtime.roles[${index}].id`, entityIds),
  );
  runtime.variables.forEach((variable, index) =>
    registerEntityId(variable.id, `document.runtime.variables[${index}].id`, entityIds),
  );
  runtime.entitySchemas.forEach((schema, schemaIndex) => {
    registerEntityId(schema.id, `document.runtime.entitySchemas[${schemaIndex}].id`, entityIds);
    schema.fields.forEach((field, fieldIndex) =>
      registerEntityId(
        field.id,
        `document.runtime.entitySchemas[${schemaIndex}].fields[${fieldIndex}].id`,
        entityIds,
      ),
    );
  });
  runtime.forms.forEach((form, formIndex) => {
    registerEntityId(form.id, `document.runtime.forms[${formIndex}].id`, entityIds);
    form.fields.forEach((field, fieldIndex) =>
      registerEntityId(
        field.id,
        `document.runtime.forms[${formIndex}].fields[${fieldIndex}].id`,
        entityIds,
      ),
    );
  });
  runtime.viewBindings.forEach((binding, index) =>
    registerEntityId(binding.id, `document.runtime.viewBindings[${index}].id`, entityIds),
  );
  runtime.rules.forEach((rule, index) =>
    registerEntityId(rule.id, `document.runtime.rules[${index}].id`, entityIds),
  );
  runtime.scenarios.forEach((scenario, scenarioIndex) => {
    registerEntityId(scenario.id, `document.runtime.scenarios[${scenarioIndex}].id`, entityIds);
    scenario.entityFixtures.forEach((entitySet, entitySetIndex) =>
      entitySet.entities.forEach((entity, entityIndex) =>
        registerEntityId(
          entity.id,
          `document.runtime.scenarios[${scenarioIndex}].entityFixtures[${entitySetIndex}].entities[${entityIndex}].id`,
          entityIds,
        ),
      ),
    );
  });
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
  const entityIds = new Set<string>();
  registerEntityId(item["id"], "document.id", entityIds);
  boundedNonEmptyString(item["title"], 120, "document.title");
  literal(item["locale"], ["zh-CN", "en-US"] as const, "document.locale");
  const settings = record(item["settings"], "document.settings");
  exactKeys(settings, ["defaultViewport", "theme", "shell"], "document.settings");
  literal(
    settings["defaultViewport"],
    ["desktop", "tablet", "mobile"] as const,
    "document.settings.defaultViewport",
  );
  literal(settings["theme"], ["light", "dark", "system"] as const, "document.settings.theme");
  const shellColorTokenKeys = validateShell(settings["shell"]);
  const tokens = record(item["tokens"], "document.tokens");
  exactKeys(tokens, ["colors", "spacing"], "document.tokens");
  const colorTokenKeys = new Set<string>();
  for (const group of ["colors", "spacing"] as const) {
    const maximumLength = group === "colors" ? 100 : 50;
    boundedArray(tokens[group], 0, maximumLength, `document.tokens.${group}`).forEach(
      (token, index) => {
        const parsed = record(token, `document.tokens.${group}[${index}]`);
        exactKeys(parsed, ["key", "value"], `document.tokens.${group}[${index}]`);
        const key = technicalKey(parsed["key"], `document.tokens.${group}[${index}].key`);
        if (group === "colors") colorTokenKeys.add(key);
        boundedNonEmptyString(parsed["value"], 120, `document.tokens.${group}[${index}].value`);
      },
    );
  }
  const missingShellColorTokenKeys = shellColorTokenKeys.filter((key) => !colorTokenKeys.has(key));
  if (missingShellColorTokenKeys.length > 0) {
    throw new RendererDocumentCodecError(
      `document.settings.shell references unknown color token keys: ${missingShellColorTokenKeys.join(", ")}`,
    );
  }
  boundedArray(item["componentDefinitions"], 0, 50, "document.componentDefinitions").forEach(
    (definition, index) => {
      const parsed = record(definition, `document.componentDefinitions[${index}]`);
      exactKeys(parsed, ["id", "key", "root"], `document.componentDefinitions[${index}]`);
      registerEntityId(parsed["id"], `document.componentDefinitions[${index}].id`, entityIds);
      technicalKey(parsed["key"], `document.componentDefinitions[${index}].key`);
      validateNode(
        parsed["root"],
        `document.componentDefinitions[${index}].root`,
        entityIds,
        "forbidden",
        colorTokenKeys,
      );
    },
  );
  boundedArray(item["pages"], 1, 20, "document.pages").forEach((page, index) => {
    const parsed = record(page, `document.pages[${index}]`);
    exactKeys(
      parsed,
      ["id", "key", "title", "route", "viewport", "root"],
      `document.pages[${index}]`,
    );
    registerEntityId(parsed["id"], `document.pages[${index}].id`, entityIds);
    technicalKey(parsed["key"], `document.pages[${index}].key`);
    boundedNonEmptyString(parsed["title"], 80, `document.pages[${index}].title`);
    const route = string(parsed["route"], `document.pages[${index}].route`);
    if (!/^\/(?:[A-Za-z0-9._~-]+(?:\/[A-Za-z0-9._~-]+)*)?$/u.test(route)) {
      throw new RendererDocumentCodecError(`document.pages[${index}].route is invalid`);
    }
    const viewport = record(parsed["viewport"], `document.pages[${index}].viewport`);
    exactKeys(viewport, ["width", "height"], `document.pages[${index}].viewport`);
    boundedInteger(viewport["width"], 320, 2560, `document.pages[${index}].viewport.width`);
    boundedInteger(viewport["height"], 480, 2160, `document.pages[${index}].viewport.height`);
    validateNode(
      parsed["root"],
      `document.pages[${index}].root`,
      entityIds,
      "forbidden",
      colorTokenKeys,
    );
  });
  const navigation = record(item["navigation"], "document.navigation");
  exactKeys(navigation, ["items"], "document.navigation");
  boundedArray(navigation["items"], 0, 20, "document.navigation.items").forEach((entry, index) => {
    const parsed = record(entry, `document.navigation.items[${index}]`);
    exactKeys(
      parsed,
      ["id", "key", "label", "targetPageId"],
      `document.navigation.items[${index}]`,
    );
    registerEntityId(parsed["id"], `document.navigation.items[${index}].id`, entityIds);
    technicalKey(parsed["key"], `document.navigation.items[${index}].key`);
    boundedNonEmptyString(parsed["label"], 80, `document.navigation.items[${index}].label`);
    uuid(parsed["targetPageId"], `document.navigation.items[${index}].targetPageId`);
  });
  boundedArray(item["flows"], 0, 100, "document.flows").forEach((flow, index) => {
    const parsed = record(flow, `document.flows[${index}]`);
    exactKeys(
      parsed,
      ["id", "key", "ruleId", "fromNodeId", "toPageId"],
      `document.flows[${index}]`,
    );
    registerEntityId(parsed["id"], `document.flows[${index}].id`, entityIds);
    technicalKey(parsed["key"], `document.flows[${index}].key`);
    uuid(parsed["ruleId"], `document.flows[${index}].ruleId`);
    uuid(parsed["fromNodeId"], `document.flows[${index}].fromNodeId`);
    if (parsed["toPageId"] !== null) uuid(parsed["toPageId"], `document.flows[${index}].toPageId`);
  });
  const runtime = parseRuntimeDefinition(item["runtime"]);
  registerRuntimeEntityIds(runtime, entityIds);
  boundedArray(item["assetRefs"], 0, 200, "document.assetRefs").forEach((asset, index) => {
    const parsed = record(asset, `document.assetRefs[${index}]`);
    exactKeys(parsed, ["id", "contentHash", "mediaType", "alt"], `document.assetRefs[${index}]`);
    registerEntityId(parsed["id"], `document.assetRefs[${index}].id`, entityIds);
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
