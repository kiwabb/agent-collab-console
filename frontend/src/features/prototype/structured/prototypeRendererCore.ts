import type {
  StructuredPrototypeDocument,
  StructuredPrototypeFormNode,
  StructuredPrototypeInputNode,
  StructuredPrototypeLength,
  StructuredPrototypeNode,
} from "./types";
import { isStructuredPrototypeContainerNode } from "./structuredPrototypeNodes";

export const PROTOTYPE_RENDERER_VERSION = "structured-prototype-renderer/0.2.0";
export const PROTOTYPE_RENDERER_ENVIRONMENT_VERSION = "node20-static-bundle/1";
export const PROTOTYPE_RENDERER_SANDBOX_POLICY_VERSION = "prototype-static-csp/1";

export interface RenderedPrototypeFile {
  relativePath: "document.json" | "index.html" | "runtime.js" | "styles.css";
  content: string;
}

export interface FormInputBinding {
  nodeId: string;
  formId: string;
  fieldId: string;
  valueType: "string" | "integer";
}

export interface PrototypeRenderPreflight {
  contractVersion: 1;
  checks: Array<{
    code: string;
    status: "passed";
    evidence: string;
  }>;
  pageCount: number;
  nodeCount: number;
  formBindingCount: number;
  externalAssetCount: number;
}

export interface PrototypeShellTheme {
  accent: string;
  accentText: string;
  navigationBackground: string;
  navigationText: string;
  contentBackground: string;
  contentText: string;
  surface: string;
  surfaceText: string;
}

export class PrototypeRendererError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "PrototypeRendererError";
  }
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function length(value: StructuredPrototypeLength): string {
  if (value.unit === "auto") return "auto";
  if (value.value === null) {
    throw new PrototypeRendererError("renderer_layout_invalid", "non-auto length has no value");
  }
  const suffix = value.unit === "percent" ? "%" : value.unit;
  return `${value.value}${suffix}`;
}

const CSS_COLOR_KEYWORDS = new Set([
  "aqua",
  "black",
  "blue",
  "brown",
  "currentcolor",
  "cyan",
  "fuchsia",
  "gray",
  "green",
  "grey",
  "lime",
  "magenta",
  "maroon",
  "navy",
  "olive",
  "orange",
  "pink",
  "purple",
  "red",
  "rebeccapurple",
  "silver",
  "teal",
  "transparent",
  "white",
  "yellow",
]);

function safeColorTokenValue(value: string): boolean {
  if (
    value !== value.trim() ||
    value.length === 0 ||
    /[;{}@'"\\\r\n\f]/u.test(value) ||
    /\/\*|\*\//u.test(value) ||
    /\b(?:url|var)\s*\(/iu.test(value)
  ) {
    return false;
  }
  if (/^#(?:[0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8})$/iu.test(value)) {
    return true;
  }
  if (CSS_COLOR_KEYWORDS.has(value.toLowerCase())) return true;
  return /^(?:rgb|rgba|hsl|hsla|oklab|oklch|lab|lch|color)\([0-9a-z.+,%/ \t-]+\)$/iu.test(value);
}

function safeTokenValue(kind: "color" | "spacing", value: string): string {
  const valid =
    kind === "color"
      ? safeColorTokenValue(value)
      : /^(?:0|[1-9][0-9]*(?:\.[0-9]{1,4})?)(?:px|rem)$/u.test(value);
  if (!valid) {
    throw new PrototypeRendererError(
      "renderer_token_unsupported",
      `renderer does not support ${kind} token value ${value}`,
    );
  }
  return value;
}

function readableTextColor(value: string, fallback: string): string {
  const match = /^#([0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8})$/iu.exec(value);
  if (match === null) return fallback;
  const hex = match[1];
  if (hex === undefined) return fallback;
  const expanded =
    hex.length === 3 || hex.length === 4
      ? hex
          .slice(0, 3)
          .split("")
          .map((character) => `${character}${character}`)
          .join("")
      : hex.slice(0, 6);
  const red = Number.parseInt(expanded.slice(0, 2), 16);
  const green = Number.parseInt(expanded.slice(2, 4), 16);
  const blue = Number.parseInt(expanded.slice(4, 6), 16);
  return (red * 299 + green * 587 + blue * 114) / 1000 >= 150 ? "#17201d" : "#ffffff";
}

function shellColorToken(document: StructuredPrototypeDocument, key: string): string {
  const token = document.tokens.colors.find((candidate) => candidate.key === key);
  if (token === undefined) {
    throw new PrototypeRendererError(
      "renderer_shell_token_missing",
      `prototype shell references unknown color token ${key}`,
    );
  }
  return safeTokenValue("color", token.value);
}

export function resolvePrototypeShellTheme(
  document: StructuredPrototypeDocument,
): PrototypeShellTheme {
  const dark = document.settings.theme === "dark";
  const fallbackText = dark ? "#ffffff" : "#17201d";
  const shell = document.settings.shell;
  const accent = shellColorToken(document, shell.accentColorTokenKey);
  const navigationBackground = shellColorToken(document, shell.navigationBackgroundColorTokenKey);
  const contentBackground = shellColorToken(document, shell.contentBackgroundColorTokenKey);
  const surface = shellColorToken(document, shell.surfaceColorTokenKey);
  return {
    accent,
    accentText: readableTextColor(accent, fallbackText),
    navigationBackground,
    navigationText: readableTextColor(navigationBackground, fallbackText),
    contentBackground,
    contentText: readableTextColor(contentBackground, fallbackText),
    surface,
    surfaceText: readableTextColor(surface, fallbackText),
  };
}

export function structuredPrototypeShowsRoleControl(
  document: StructuredPrototypeDocument,
): boolean {
  return (
    document.runtime.roles.length > 1 &&
    document.runtime.scenarios[0]?.allowSimulatedRoleSwitch === true
  );
}

function layoutRules(node: StructuredPrototypeNode): string[] {
  const item = node.layoutItem;
  const rules = [
    `width:${length(item.width)}`,
    `height:${length(item.height)}`,
    `flex-grow:${item.grow}`,
    `flex-shrink:${item.shrink}`,
    `align-self:${item.alignSelf === "auto" ? "auto" : item.alignSelf}`,
  ];
  if (item.minWidth !== null) rules.push(`min-width:${length(item.minWidth)}`);
  if (item.maxWidth !== null) rules.push(`max-width:${length(item.maxWidth)}`);
  if (item.minHeight !== null) rules.push(`min-height:${length(item.minHeight)}`);
  if (item.maxHeight !== null) rules.push(`max-height:${length(item.maxHeight)}`);
  if (item.position !== undefined) {
    rules.push("position:absolute", `left:${item.position.x}px`, `top:${item.position.y}px`);
  }
  if (node.visibility === "hidden") rules.push("display:none");
  if (isStructuredPrototypeContainerNode(node) && item.position === undefined) {
    rules.push("position:relative");
  }
  if (node.type === "Freeform") {
    rules.push("overflow:hidden");
  }
  if (node.type === "Stack") {
    rules.push(
      "display:flex",
      `flex-direction:${node.direction}`,
      `gap:${node.gap}px`,
      `align-items:${node.align}`,
      `justify-content:${node.justify === "between" ? "space-between" : node.justify}`,
      `padding:${node.padding.top}px ${node.padding.right}px ${node.padding.bottom}px ${node.padding.left}px`,
    );
  }
  if (node.type === "Grid") {
    rules.push(
      "display:grid",
      `grid-template-columns:repeat(${node.columns},minmax(0,1fr))`,
      `gap:${node.gap}px`,
      `padding:${node.padding.top}px ${node.padding.right}px ${node.padding.bottom}px ${node.padding.left}px`,
    );
  }
  if (node.type === "Form") {
    rules.push(
      "display:flex",
      "flex-direction:column",
      `gap:${node.gap}px`,
      `padding:${node.padding.top}px ${node.padding.right}px ${node.padding.bottom}px ${node.padding.left}px`,
    );
  }
  if (node.type === "Divider") {
    rules.push(
      "height:1px",
      `margin:${node.spacing}px 0`,
      `background:${node.tone === "muted" ? "#e6eae8" : "#c9d2ce"}`,
    );
  }
  if (node.type === "Badge") {
    const tones = {
      default: ["#eef1ef", "#39443f"],
      success: ["#e9f4ec", "#237a45"],
      warning: ["#fff2d8", "#936221"],
      danger: ["#fff1f3", "#8c1d31"],
    } as const;
    const [background, color] = tones[node.tone];
    rules.push(
      "display:inline-flex",
      "width:fit-content",
      "align-items:center",
      "gap:4px",
      "padding:2px 8px",
      "font-size:11px",
      "font-weight:700",
      "line-height:1.5",
      `background:${background}`,
      `color:${color}`,
    );
  }
  return rules;
}

function responsiveRules(node: StructuredPrototypeNode): string[] {
  const widths = { sm: 640, md: 768, lg: 1024 } as const;
  return node.responsive.map((override) => {
    const rules: string[] = [];
    const item = override.layoutItem;
    if (item.width !== undefined) rules.push(`width:${length(item.width)}`);
    if (item.minWidth !== undefined) {
      rules.push(item.minWidth === null ? "min-width:0" : `min-width:${length(item.minWidth)}`);
    }
    if (item.maxWidth !== undefined) {
      rules.push(item.maxWidth === null ? "max-width:none" : `max-width:${length(item.maxWidth)}`);
    }
    if (item.height !== undefined) rules.push(`height:${length(item.height)}`);
    if (item.minHeight !== undefined) {
      rules.push(item.minHeight === null ? "min-height:0" : `min-height:${length(item.minHeight)}`);
    }
    if (item.maxHeight !== undefined) {
      rules.push(
        item.maxHeight === null ? "max-height:none" : `max-height:${length(item.maxHeight)}`,
      );
    }
    if (item.grow !== undefined) rules.push(`flex-grow:${item.grow}`);
    if (item.shrink !== undefined) rules.push(`flex-shrink:${item.shrink}`);
    if (item.alignSelf !== undefined) rules.push(`align-self:${item.alignSelf}`);
    return `@media(min-width:${widths[override.breakpoint]}px){[data-prototype-node-id="${node.id}"]{${rules.join(";")}}}`;
  });
}

function gridColumnRules(node: StructuredPrototypeNode): string[] {
  if (node.type !== "Grid") return [];
  return node.columnOverrides.map(
    (override) =>
      `@media(min-width:${override.minWidth}px){[data-prototype-node-id="${node.id}"]{grid-template-columns:repeat(${override.columns},minmax(0,1fr))}}`,
  );
}

function collectNodeCss(node: StructuredPrototypeNode, output: string[]): void {
  output.push(`[data-prototype-node-id="${node.id}"]{${layoutRules(node).join(";")}}`);
  output.push(...responsiveRules(node));
  output.push(...gridColumnRules(node));
  if (isStructuredPrototypeContainerNode(node)) {
    for (const child of node.children) collectNodeCss(child, output);
  }
}

function inputNodes(node: StructuredPrototypeNode, output: StructuredPrototypeInputNode[]): void {
  if (node.type === "Input") output.push(node);
  if (isStructuredPrototypeContainerNode(node)) {
    for (const child of node.children) inputNodes(child, output);
  }
}

function formNodes(node: StructuredPrototypeNode, output: StructuredPrototypeFormNode[]): void {
  if (node.type === "Form") output.push(node);
  if (isStructuredPrototypeContainerNode(node)) {
    for (const child of node.children) formNodes(child, output);
  }
}

export function deriveFormInputBindings(
  document: StructuredPrototypeDocument,
  requireComplete = true,
): FormInputBinding[] {
  const forms: StructuredPrototypeFormNode[] = [];
  for (const page of document.pages) formNodes(page.root, forms);
  const result: FormInputBinding[] = [];
  for (const form of forms) {
    const definition = document.runtime.forms.find(
      (candidate) => candidate.id === form.formDefinitionId,
    );
    if (definition === undefined) {
      throw new PrototypeRendererError(
        "renderer_form_definition_missing",
        `form node ${form.id} references an unknown runtime form`,
      );
    }
    const inputs: StructuredPrototypeInputNode[] = [];
    for (const child of form.children) inputNodes(child, inputs);
    const boundFieldIds = new Set<string>();
    for (const input of inputs) {
      if (input.formDefinitionId === null && input.formFieldId === null) continue;
      if (input.formDefinitionId !== definition.id || input.formFieldId === null) {
        throw new PrototypeRendererError(
          "renderer_form_binding_invalid",
          `input node ${input.id} does not belong to runtime form ${definition.id}`,
        );
      }
      const field = definition.fields.find((candidate) => candidate.id === input.formFieldId);
      if (field === undefined) {
        throw new PrototypeRendererError(
          "renderer_form_field_missing",
          `input node ${input.id} references an unknown runtime field`,
        );
      }
      if (boundFieldIds.has(field.id)) {
        throw new PrototypeRendererError(
          "renderer_form_binding_duplicate",
          `runtime field ${field.id} is bound more than once in form node ${form.id}`,
        );
      }
      const compatible =
        (field.valueType === "integer" && input.inputType === "number") ||
        (field.valueType === "string" && input.inputType !== "number");
      if (!compatible) {
        throw new PrototypeRendererError(
          "renderer_form_binding_type_mismatch",
          `input node ${input.id} does not match runtime field ${field.id}`,
        );
      }
      boundFieldIds.add(field.id);
      result.push({
        nodeId: input.id,
        formId: definition.id,
        fieldId: field.id,
        valueType: field.valueType,
      });
    }
    if (requireComplete && boundFieldIds.size !== definition.fields.length) {
      throw new PrototypeRendererError(
        "renderer_form_binding_incomplete",
        `form node ${form.id} must bind every runtime field exactly once`,
      );
    }
  }
  return result;
}

function renderNode(
  node: StructuredPrototypeNode,
  bindings: Map<string, FormInputBinding>,
): string {
  const common = `data-prototype-node-id="${node.id}" data-prototype-node-type="${node.type}"`;
  switch (node.type) {
    case "Freeform":
      return `<div ${common} class="prototype-freeform">${node.children.map((child) => renderNode(child, bindings)).join("")}</div>`;
    case "Stack":
      return `<div ${common} class="prototype-stack">${node.children.map((child) => renderNode(child, bindings)).join("")}</div>`;
    case "Grid":
      return `<div ${common} class="prototype-grid">${node.children.map((child) => renderNode(child, bindings)).join("")}</div>`;
    case "Form":
      return `<form ${common} class="prototype-form" data-prototype-form-id="${node.formDefinitionId}" novalidate>${node.children.map((child) => renderNode(child, bindings)).join("")}</form>`;
    case "Text": {
      const tag = node.semantic === "heading" ? "h2" : node.semantic === "label" ? "strong" : "p";
      return `<${tag} ${common} class="prototype-text prototype-text-${node.semantic} prototype-tone-${node.tone}">${escapeHtml(node.content)}</${tag}>`;
    }
    case "Input": {
      const binding = bindings.get(node.id);
      const bindingAttributes =
        binding === undefined
          ? ""
          : ` data-runtime-form-id="${binding.formId}" data-runtime-field-id="${binding.fieldId}" data-runtime-value-type="${binding.valueType}"`;
      return `<label ${common} class="prototype-input"><span>${escapeHtml(node.label)}</span><input type="${node.inputType}" value="${escapeHtml(node.value)}" placeholder="${escapeHtml(node.placeholder)}"${node.required ? " required" : ""}${node.disabled ? " disabled" : ""}${bindingAttributes}></label>`;
    }
    case "Button": {
      const trigger = node.disabled ? "" : ` data-runtime-node-id="${node.id}"`;
      return `<button ${common} type="button" class="prototype-button prototype-button-${node.variant} prototype-button-${node.size}"${node.disabled ? " disabled" : ""}${trigger}>${escapeHtml(node.label)}</button>`;
    }
    case "Divider":
      return `<div ${common} class="prototype-divider prototype-divider-${node.tone}" role="separator"></div>`;
    case "Badge":
      return `<span ${common} class="prototype-badge prototype-badge-${node.tone}">${escapeHtml(node.label)}</span>`;
    case "Table":
      return `<div ${common} class="prototype-table-wrap"><table class="prototype-table prototype-table-${node.density}"><thead><tr>${node.columns.map((column) => `<th data-column-key="${escapeHtml(column.key)}">${escapeHtml(column.label)}</th>`).join("")}</tr></thead><tbody>${node.rows.map((row) => `<tr data-static-row-id="${row.id}">${node.columns.map((column) => `<td>${escapeHtml(row.cells.find((cell) => cell.columnKey === column.key)?.value ?? "")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }
}

function shellRules(document: StructuredPrototypeDocument): string {
  const shell = document.settings.shell;
  if (shell.kind === "topbar") {
    return ".prototype-shell-topbar{display:flex;flex-direction:column}.prototype-shell-topbar>.prototype-header{display:flex;align-items:center;gap:20px;min-height:64px;padding:10px 24px}.prototype-shell-topbar .prototype-nav{display:flex;flex:1;flex-wrap:wrap;gap:4px}.prototype-shell-topbar .prototype-role{margin-left:auto}.prototype-shell-topbar .prototype-page{min-height:calc(100vh - 116px)}";
  }
  return `.prototype-shell-sidebar{display:flex;flex-direction:column}.prototype-shell-sidebar>.prototype-sidebar{display:flex;align-items:center;gap:20px;min-height:64px;padding:10px 16px}.prototype-shell-sidebar .prototype-nav{display:flex;flex:1;gap:4px;overflow:auto}.prototype-shell-sidebar .prototype-role{margin-left:auto}.prototype-shell-sidebar .prototype-page{min-height:calc(100vh - 116px)}@media(min-width:${shell.expandedMinWidth}px){.prototype-shell-sidebar{display:grid;grid-template-columns:${shell.navigationWidth}px minmax(0,1fr)}.prototype-shell-sidebar>.prototype-sidebar{min-height:100vh;display:flex;flex-direction:column;align-items:stretch;gap:0;padding:20px 14px}.prototype-shell-sidebar .prototype-nav{display:grid;flex:0 0 auto;margin-top:24px;overflow:visible}.prototype-shell-sidebar .prototype-nav button{width:100%;text-align:left}.prototype-shell-sidebar .prototype-role{display:grid;margin:auto 0 0}.prototype-shell-sidebar .prototype-page{min-height:calc(100vh - 52px)}}`;
}

function renderStyles(document: StructuredPrototypeDocument): string {
  const theme = resolvePrototypeShellTheme(document);
  const tokenRules = [
    `--prototype-accent:${theme.accent}`,
    `--prototype-accent-text:${theme.accentText}`,
    `--prototype-navigation-background:${theme.navigationBackground}`,
    `--prototype-navigation-text:${theme.navigationText}`,
    `--prototype-content-background:${theme.contentBackground}`,
    `--prototype-content-text:${theme.contentText}`,
    `--prototype-surface:${theme.surface}`,
    `--prototype-surface-text:${theme.surfaceText}`,
    "--prototype-text:var(--prototype-content-text)",
    ...document.tokens.colors.map(
      (token, index) => `--prototype-color-${index}:${safeTokenValue("color", token.value)}`,
    ),
    ...document.tokens.spacing.map(
      (token, index) => `--prototype-space-${index}:${safeTokenValue("spacing", token.value)}`,
    ),
  ];
  const nodeRules: string[] = [
    ".prototype-divider{height:1px;background:#c9d2ce}",
    ".prototype-divider-muted{background:#e6eae8}",
    ".prototype-badge{display:inline-flex;width:fit-content;align-items:center;gap:4px;border:1px solid transparent;padding:2px 8px;font-size:11px;font-weight:700;line-height:1.5}",
    ".prototype-badge-default{background:#eef1ef;color:#39443f}",
    ".prototype-badge-success{background:#e9f4ec;color:#237a45}",
    ".prototype-badge-warning{background:#fff2d8;color:#936221}",
    ".prototype-badge-danger{background:#fff1f3;color:#8c1d31}",
  ];
  for (const page of document.pages) collectNodeCss(page.root, nodeRules);
  return `:root{${tokenRules.join(";")};color-scheme:${document.settings.theme === "system" ? "light dark" : document.settings.theme};font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}*{box-sizing:border-box}html,body{margin:0;min-height:100%;background:var(--prototype-content-background);color:var(--prototype-text)}button,input,select{font:inherit}.prototype-toolbar,.prototype-role select,.prototype-input input,.prototype-button-secondary,.prototype-table-wrap{--prototype-text:var(--prototype-surface-text);color:var(--prototype-surface-text)}.prototype-shell{min-height:100vh}.prototype-header,.prototype-sidebar{background:var(--prototype-navigation-background);color:var(--prototype-navigation-text)}.prototype-brand{font-size:18px;font-weight:800;white-space:nowrap}.prototype-nav button{border:0;background:transparent;color:inherit;opacity:.75;min-height:40px;padding:0 12px;cursor:pointer}.prototype-nav button[aria-current="page"]{background:var(--prototype-accent);color:var(--prototype-accent-text);opacity:1;font-weight:700}.prototype-role{display:flex;align-items:center;gap:8px;color:inherit;font-size:12px}.prototype-role[hidden]{display:none!important}.prototype-role select{min-height:34px;border:1px solid color-mix(in srgb,var(--prototype-navigation-text) 32%,transparent);background:var(--prototype-surface);color:var(--prototype-text);padding:0 8px}.prototype-main{min-width:0;flex:1;background:var(--prototype-content-background);color:var(--prototype-content-text)}.prototype-toolbar{min-height:52px;display:flex;align-items:center;gap:16px;border-bottom:1px solid color-mix(in srgb,var(--prototype-text) 14%,transparent);background:var(--prototype-surface);padding:8px 24px}.prototype-toolbar-title{font-size:14px;font-weight:700}.prototype-notification{display:none;margin:16px 24px 0;border:1px solid #b6d7cf;background:#e9f4ec;color:#237a45;padding:10px 12px;font-size:13px}.prototype-notification[data-visible="true"]{display:block}.prototype-notification[data-level="error"]{border-color:#e4a8b2;background:#fff1f3;color:#8c1d31}.prototype-page{display:none}.prototype-page[data-active="true"]{display:block}.prototype-freeform,.prototype-stack,.prototype-grid,.prototype-form{min-width:0}.prototype-text{margin:0;line-height:1.5}.prototype-text-heading{font-size:24px;font-weight:800}.prototype-text-caption{font-size:12px}.prototype-tone-muted{color:color-mix(in srgb,var(--prototype-text) 64%,transparent)}.prototype-tone-success{color:#237a45}.prototype-tone-warning{color:#936221}.prototype-tone-danger{color:#8c1d31}.prototype-input{display:grid;gap:6px;color:inherit;font-size:12px}.prototype-input input{min-height:42px;border:1px solid color-mix(in srgb,var(--prototype-text) 20%,transparent);background:var(--prototype-surface);padding:0 12px;color:var(--prototype-text)}.prototype-button{border:1px solid transparent;cursor:pointer;font-weight:700}.prototype-button-small{min-height:32px;padding:0 12px;font-size:12px}.prototype-button-medium{min-height:40px;padding:0 16px;font-size:13px}.prototype-button-large{min-height:48px;padding:0 20px;font-size:14px}.prototype-button-primary{background:var(--prototype-accent);color:var(--prototype-accent-text)}.prototype-button-secondary{border-color:color-mix(in srgb,var(--prototype-text) 20%,transparent);background:var(--prototype-surface);color:var(--prototype-text)}.prototype-button-danger{background:#8c1d31;color:#fff}.prototype-button-ghost{background:transparent;color:var(--prototype-accent)}.prototype-button:disabled{cursor:not-allowed;opacity:.45}.prototype-table-wrap{overflow:auto;border:1px solid color-mix(in srgb,var(--prototype-text) 15%,transparent);background:var(--prototype-surface)}.prototype-table{width:100%;border-collapse:collapse;font-size:13px}.prototype-table th,.prototype-table td{border-bottom:1px solid color-mix(in srgb,var(--prototype-text) 12%,transparent);text-align:left}.prototype-table-compact th,.prototype-table-compact td{padding:8px 10px}.prototype-table-comfortable th,.prototype-table-comfortable td{padding:12px 14px}.prototype-table th{background:color-mix(in srgb,var(--prototype-surface) 94%,var(--prototype-text));color:color-mix(in srgb,var(--prototype-text) 64%,transparent);font-size:11px;text-transform:uppercase}.prototype-table tbody tr[data-entity-id]{cursor:pointer}.prototype-table tbody tr[data-entity-id]:hover{background:color-mix(in srgb,var(--prototype-accent) 8%,transparent)}.prototype-runtime-error{position:fixed;right:16px;bottom:16px;max-width:420px;border:1px solid #e4a8b2;background:#fff1f3;color:#8c1d31;padding:12px;font-size:12px;z-index:20}${shellRules(document)}${nodeRules.join("")}@media(max-width:767px){.prototype-header{align-items:flex-start;flex-wrap:wrap;padding:12px}.prototype-header .prototype-nav{order:3;flex-basis:100%;flex-wrap:nowrap;overflow:auto}.prototype-nav button{white-space:nowrap}.prototype-toolbar{padding:8px 12px}.prototype-text-heading{font-size:20px}}`;
}

function renderRoleControl(
  document: StructuredPrototypeDocument,
  showRoleControl: boolean,
): string {
  return `<label class="prototype-role"${showRoleControl ? "" : " hidden"}><span data-current-role-label></span><select data-role-select aria-label="Simulated role">${document.runtime.roles.map((role) => `<option value="${role.id}">${escapeHtml(role.label)}</option>`).join("")}</select></label>`;
}

function renderNavigation(document: StructuredPrototypeDocument): string {
  return `<nav class="prototype-nav" aria-label="Prototype navigation">${document.navigation.items.map((item) => `<button type="button" data-navigation-target="${item.targetPageId}">${escapeHtml(item.label)}</button>`).join("")}</nav>`;
}

function renderHtml(document: StructuredPrototypeDocument, documentHash: string): string {
  const bindings = new Map(
    deriveFormInputBindings(document).map((binding) => [binding.nodeId, binding]),
  );
  const showRoleControl = structuredPrototypeShowsRoleControl(document);
  const navigation = `${renderNavigation(document)}${renderRoleControl(document, showRoleControl)}`;
  const shellNavigation =
    document.settings.shell.kind === "sidebar"
      ? `<aside class="prototype-sidebar prototype-navigation"><div class="prototype-brand">${escapeHtml(document.settings.shell.title)}</div>${navigation}</aside>`
      : `<header class="prototype-header prototype-navigation"><div class="prototype-brand">${escapeHtml(document.settings.shell.title)}</div>${navigation}</header>`;
  const main = `<main class="prototype-main"><header class="prototype-toolbar"><div class="prototype-toolbar-title" data-current-page-title>${escapeHtml(document.pages[0]?.title ?? document.title)}</div></header><div class="prototype-notification" data-runtime-notification data-visible="false"></div>${document.pages.map((page) => `<section class="prototype-page" data-prototype-page-id="${page.id}" data-page-title="${escapeHtml(page.title)}" data-active="false">${renderNode(page.root, bindings)}</section>`).join("")}</main>`;
  return `<!doctype html><html lang="${document.locale}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="prototype-document-hash" content="${documentHash}"><meta http-equiv="Content-Security-Policy" content="default-src 'none';script-src 'self';style-src 'self';connect-src 'self';img-src 'self' data:;font-src 'self';base-uri 'none';form-action 'none';frame-ancestors 'self'"><title>${escapeHtml(document.title)}</title><link rel="stylesheet" href="./styles.css"></head><body><div class="prototype-shell prototype-shell-${document.settings.shell.kind}">${shellNavigation}${main}</div><div class="prototype-runtime-error" data-runtime-error hidden></div><script src="./runtime.js" defer></script></body></html>`;
}

function countNodes(node: StructuredPrototypeNode): number {
  if (!isStructuredPrototypeContainerNode(node)) return 1;
  return 1 + node.children.reduce((total, child) => total + countNodes(child), 0);
}

export function renderPrototypeDocument(
  document: StructuredPrototypeDocument,
  documentJson: string,
  documentHash: string,
  publicRuntimeSource: string,
): { files: RenderedPrototypeFile[]; preflight: PrototypeRenderPreflight } {
  if (document.assetRefs.length > 0) {
    throw new PrototypeRendererError(
      "renderer_assets_unsupported",
      "renderer asset resolution is unavailable for this compatibility version",
    );
  }
  const bindings = deriveFormInputBindings(document);
  const nodeCount = document.pages.reduce((total, page) => total + countNodes(page.root), 0);
  const preflight: PrototypeRenderPreflight = {
    contractVersion: 1,
    checks: [
      { code: "document-schema", status: "passed", evidence: `schema:${document.schemaVersion}` },
      {
        code: "runtime-graph",
        status: "passed",
        evidence: `rules:${document.runtime.rules.length}`,
      },
      { code: "node-bindings", status: "passed", evidence: `nodes:${nodeCount}` },
      {
        code: "sandbox-policy",
        status: "passed",
        evidence: PROTOTYPE_RENDERER_SANDBOX_POLICY_VERSION,
      },
    ],
    pageCount: document.pages.length,
    nodeCount,
    formBindingCount: bindings.length,
    externalAssetCount: 0,
  };
  const files: RenderedPrototypeFile[] = [
    { relativePath: "document.json", content: documentJson },
    { relativePath: "index.html", content: renderHtml(document, documentHash) },
    { relativePath: "runtime.js", content: publicRuntimeSource },
    { relativePath: "styles.css", content: renderStyles(document) },
  ];
  files.sort((left, right) => left.relativePath.localeCompare(right.relativePath, "en"));
  return { files, preflight };
}
